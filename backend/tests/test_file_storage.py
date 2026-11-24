"""S3 / R2 document storage (moto), local fallback, key safety and the API flow on top of it."""

import boto3
import pytest
from moto import mock_aws

from backend.config import settings
from backend.services import file_storage
from backend.services.file_storage import KEY_RE, LocalStorage, S3Storage
from backend.tests.test_hospital_platform import (  # noqa: F401  (fixtures and helpers)
    PDF, PNG, admin, hospital_db, signup, upload,
)

BUCKET = "haemnet-docs"


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
        raw = boto3.client("s3", region_name="us-east-1")
        raw.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(settings, "s3_bucket", BUCKET)
        monkeypatch.setattr(settings, "s3_region", "us-east-1")
        monkeypatch.setattr(settings, "s3_prefix", "hospital-documents/")
        monkeypatch.setattr(settings, "s3_endpoint_url", "")
        file_storage.reset_cache()
        yield raw
        file_storage.reset_cache()


def objects(raw):
    return [o["Key"] for o in raw.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


@pytest.mark.asyncio
async def test_s3_round_trip_is_private_encrypted_and_prefixed(s3):
    storage = file_storage.get_storage()
    assert isinstance(storage, S3Storage)
    key = await storage.save("HOSP-1001", "pdf", PDF, "application/pdf")
    assert KEY_RE.match(key)
    assert objects(s3) == [f"hospital-documents/{key}"]
    head = s3.head_object(Bucket=BUCKET, Key=f"hospital-documents/{key}")
    assert head["ServerSideEncryption"] == "AES256" and head["ContentType"] == "application/pdf"
    assert await storage.load(key) == PDF


@pytest.mark.asyncio
async def test_s3_load_unknown_or_malformed_keys_return_none(s3):
    storage = file_storage.get_storage()
    assert await storage.load("HOSP-1001/" + "a" * 32 + ".pdf") is None
    assert await storage.load("../../etc/passwd") is None
    assert await storage.load("HOSP-1001/../HOSP-2/" + "a" * 32 + ".pdf") is None


@pytest.mark.asyncio
async def test_s3_delete_prefix_only_removes_that_hospital(s3):
    storage = file_storage.get_storage()
    await storage.save("HOSP-1", "pdf", PDF, "application/pdf")
    await storage.save("HOSP-1", "png", PNG, "image/png")
    other = await storage.save("HOSP-10", "pdf", PDF, "application/pdf")  # shares a string prefix with HOSP-1
    await storage.delete_prefix("HOSP-1")
    assert objects(s3) == [f"hospital-documents/{other}"]


@pytest.mark.asyncio
async def test_s3_delete_handles_more_than_one_page(s3):
    storage = file_storage.get_storage()
    for _ in range(12):
        await storage.save("HOSP-7", "pdf", PDF, "application/pdf")
    await storage.delete_prefix("HOSP-7")
    assert objects(s3) == []


@pytest.mark.asyncio
async def test_r2_style_endpoint_skips_the_encryption_header(monkeypatch, s3):
    monkeypatch.setattr(settings, "s3_endpoint_url", "https://example.r2.cloudflarestorage.com")
    file_storage.reset_cache()
    assert file_storage.get_storage().encrypt is False


@pytest.mark.asyncio
async def test_check_reports_a_missing_bucket(s3, monkeypatch):
    assert await file_storage.get_storage().check() is True
    monkeypatch.setattr(settings, "s3_bucket", "no-such-bucket")
    file_storage.reset_cache()
    assert await file_storage.get_storage().check() is False


def test_without_a_bucket_local_disk_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "s3_bucket", "")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    file_storage.reset_cache()
    assert isinstance(file_storage.get_storage(), LocalStorage) and file_storage.persistent() is False


@pytest.mark.asyncio
async def test_local_rejects_keys_that_are_not_ours(tmp_path):
    storage = LocalStorage(str(tmp_path))
    (tmp_path.parent / "secret.pdf").write_bytes(b"x")
    assert await storage.load("../secret.pdf") is None
    key = await storage.save("HOSP-1", "pdf", PDF)
    assert await storage.load(key) == PDF


# ── the API on top of S3 ──────────────────────────────────────────

def test_upload_download_and_delete_through_the_api_on_s3(client, platform_repo, hospital_db, admin, s3):
    hid, owner = signup(client, platform_repo, hospital_db)
    doc = upload(client, owner).json()
    assert len(objects(s3)) == 1
    res = client.get(f"/api/admin/hospitals/{hid}/documents/{doc['id']}", headers=admin)
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-type"] == "application/pdf" and res.headers["cache-control"] == "private, no-store"
    assert client.get(f"/api/admin/hospitals/{hid}/documents/{doc['id']}", headers=owner).status_code == 401
    assert client.post("/api/hospitals/me/delete", headers=owner, json={"confirm_id": hid}).status_code == 200
    assert objects(s3) == []


def test_missing_object_is_a_404_and_storage_outage_a_503(client, platform_repo, hospital_db, admin, s3, monkeypatch):
    hid, owner = signup(client, platform_repo, hospital_db)
    doc = upload(client, owner).json()
    s3.delete_object(Bucket=BUCKET, Key=f"hospital-documents/{platform_repo.hospitals[hid]['documents'][0]['key']}")
    assert client.get(f"/api/admin/hospitals/{hid}/documents/{doc['id']}", headers=admin).status_code == 404

    async def boom(*a, **k):
        raise RuntimeError("bucket down")

    monkeypatch.setattr(S3Storage, "save", boom)
    assert upload(client, owner).status_code == 503
    monkeypatch.setattr(S3Storage, "delete_prefix", boom)
    res = client.post("/api/hospitals/me/delete", headers=owner, json={"confirm_id": hid})
    assert res.status_code == 503 and hid in platform_repo.hospitals  # account kept when files could not be removed


def test_deep_health_reports_storage(client, s3, monkeypatch):
    from backend.api import routes

    async def db_ok():
        return {"status": "connected", "backend": "mongodb"}

    monkeypatch.setattr(routes, "db_health", db_ok)
    monkeypatch.setattr(settings, "sarvam_api_key", "")
    body = client.get("/api/health/deep").json()
    assert body["checks"]["storage"] is True and body["checks"]["storage_persistent"] is True


# ── migration tool ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_copies_local_files_once(s3, tmp_path):
    from backend.tools.migrate_uploads_to_s3 import migrate

    local = LocalStorage(str(tmp_path))
    key = await local.save("HOSP-1001", "pdf", PDF)
    (tmp_path / "HOSP-1001" / "notes.txt").write_text("not a document")
    storage = file_storage.get_storage()
    assert await migrate(tmp_path, storage, dry_run=True) == {"copied": 1, "skipped_existing": 0, "ignored": 1}
    assert objects(s3) == []
    assert await migrate(tmp_path, storage, dry_run=False) == {"copied": 1, "skipped_existing": 0, "ignored": 1}
    assert await storage.load(key) == PDF
    assert (await migrate(tmp_path, storage, dry_run=False))["skipped_existing"] == 1
