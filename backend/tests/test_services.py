"""The business rules, exercised directly without HTTP."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.errors import register_error_handlers
from backend.services import hospital_documents, hospital_review, hospital_staff
from backend.services import hospital_platform as hp
from backend.services.errors import (
    BadRequestError,
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)
from backend.services.rate_limit import Limiter, enforce

# ── errors map to HTTP in one place ───────────────────────────────

@pytest.mark.parametrize("error,status", [
    (BadRequestError("x"), 400), (UnauthorizedError("x"), 401), (NotFoundError("x"), 404),
    (ConflictError("x"), 409), (InvalidInputError("x"), 422), (RateLimitedError("x", 7), 429),
])
def test_every_domain_error_becomes_its_http_status(error, status):
    small_app = FastAPI()
    register_error_handlers(small_app)

    @small_app.get("/raise")
    async def raiser():
        raise error

    res = TestClient(small_app).get("/raise")
    assert res.status_code == status and res.json() == {"detail": "x"}
    if status == 429:
        assert res.headers["retry-after"] == "7"
    if status == 401:
        assert res.headers["www-authenticate"] == "Bearer"


def test_domain_errors_carry_their_message_and_default_status():
    assert DomainError("boom").status_code == 400 and DomainError("boom").message == "boom"


@pytest.mark.asyncio
async def test_enforce_raises_with_retry_after_once_the_limit_is_used():
    limiter = Limiter("svc-test", max_events=1, window_seconds=60)
    await enforce(limiter, "k", "slow down")
    with pytest.raises(RateLimitedError) as caught:
        await enforce(limiter, "k", "slow down")
    assert caught.value.headers["Retry-After"] and caught.value.message == "slow down"


# ── approval gate ─────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
async def test_unapproved_hospitals_are_refused(platform_repo, status):
    platform_repo.hospitals["H1"] = {"id": "H1", "status": status}
    with pytest.raises(hp.HospitalNotApproved) as caught:
        await hp.assert_approved("H1")
    assert caught.value.status == status


# ── review rules ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_rules(platform_repo):
    platform_repo.hospitals["H1"] = {"id": "H1", "name": "A", "status": "pending", "email_verified": False,
                                     "official_email": "a@a.example"}
    with pytest.raises(InvalidInputError):
        await hospital_review.decide("H1", "explode", "", "root")
    with pytest.raises(InvalidInputError):
        await hospital_review.decide("H1", "reject", "  ", "root")  # a reason is mandatory
    with pytest.raises(ConflictError):
        await hospital_review.decide("H1", "approve", "", "root")  # email not verified
    with pytest.raises(NotFoundError):
        await hospital_review.decide("NOPE", "approve", "", "root")
    assert await hospital_review.decide("H1", "reject", " Unreadable licence ", "root") == "rejected"
    assert platform_repo.hospitals["H1"]["decision_reason"] == "Unreadable licence"
    with pytest.raises(ConflictError):
        await hospital_review.decide("H1", "suspend", "x", "root")  # only approved hospitals can be suspended
    assert platform_repo.audit[-1]["actor"] == "root"


# ── staff rules ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_staff_authentication_never_reveals_which_part_was_wrong(platform_repo):
    platform_repo.hospitals["H1"] = {"id": "H1"}
    await hospital_staff.add_staff("H1", "Devi", "devi@a.example", "staff", "password1")
    for email, password in [("devi@a.example", "wrongpass1"), ("nobody@a.example", "password1")]:
        with pytest.raises(UnauthorizedError) as caught:
            await hospital_staff.authenticate("H1", email, password)
        assert caught.value.message == "Incorrect hospital ID, email or password"
    with pytest.raises(UnauthorizedError):
        await hospital_staff.authenticate("NO-SUCH-HOSPITAL", "devi@a.example", "password1")
    hospital, member = await hospital_staff.authenticate("H1", "devi@a.example", "password1")
    assert member["role"] == "staff" and hospital["id"] == "H1"


@pytest.mark.asyncio
async def test_staff_limit_and_public_shape(platform_repo, monkeypatch):
    platform_repo.hospitals["H1"] = {"id": "H1"}
    monkeypatch.setattr(hospital_staff, "MAX_STAFF", 2)
    for i in range(2):
        created = await hospital_staff.add_staff("H1", f"S{i}", f"s{i}@a.example", "staff", "password1")
    assert "password_hash" not in created
    with pytest.raises(ConflictError):
        await hospital_staff.add_staff("H1", "S3", "s3@a.example", "staff", "password1")


# ── documents ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_documents_are_validated_by_content_not_name(platform_repo, uploads):
    platform_repo.hospitals["H1"] = {"id": "H1"}
    with pytest.raises(InvalidInputError):
        await hospital_documents.store_document("H1", "selfie", "a.pdf", b"%PDF-1")
    with pytest.raises(InvalidInputError):
        await hospital_documents.store_document("H1", "other", "a.pdf", b"")
    from backend.services.errors import UnsupportedMediaError
    with pytest.raises(UnsupportedMediaError):
        await hospital_documents.store_document("H1", "other", "licence.pdf", b"<html>not a pdf</html>")
    doc = await hospital_documents.store_document("H1", "other", None, b"%PDF-1.4 ok")
    assert doc["content_type"] == "application/pdf" and doc["filename"] == "document.pdf"
    meta, content = await hospital_documents.read_document("H1", doc["id"])
    assert content == b"%PDF-1.4 ok" and meta["kind"] == "other"
    with pytest.raises(NotFoundError):
        await hospital_documents.read_document("H1", "missing")
