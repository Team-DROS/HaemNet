"""Private storage for hospital licence documents.

Two backends behind one interface:
  * LocalStorage: a folder on disk (UPLOAD_DIR). Fine for development or a host
    with a persistent disk. Lost on hosts with an ephemeral disk (Render free).
  * S3Storage: a private S3 or Cloudflare R2 bucket (S3_BUCKET). Files are
    never public; admins read them through the API, which checks their token.

Keys look like `HOSP-1001/<32 hex>.pdf` and are only ever generated here, never
taken from user input. Both backends refuse any other key shape.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional, Protocol

from backend.config import settings

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[A-Za-z0-9_-]+/[0-9a-f]{32}\.(pdf|jpg|png)$")


def folder_for(hospital_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", hospital_id)


class Storage(Protocol):
    async def save(self, hospital_id: str, ext: str, data: bytes, content_type: str) -> str: ...
    async def load(self, key: str) -> Optional[bytes]: ...
    async def delete_prefix(self, hospital_id: str) -> None: ...
    async def check(self) -> bool: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)

    async def save(self, hospital_id: str, ext: str, data: bytes, content_type: str = "") -> str:
        folder = self.root / folder_for(hospital_id)
        folder.mkdir(parents=True, exist_ok=True)
        key = f"{folder.name}/{uuid.uuid4().hex}.{ext}"
        (self.root / key).write_bytes(data)
        return key

    def path(self, key: str) -> Optional[Path]:
        if not KEY_RE.match(key or ""):
            return None
        target = (self.root / key).resolve()
        if self.root.resolve() not in target.parents or not target.is_file():
            return None
        return target

    async def load(self, key: str) -> Optional[bytes]:
        path = self.path(key)
        return path.read_bytes() if path else None

    async def delete_prefix(self, hospital_id: str) -> None:
        folder = (self.root / folder_for(hospital_id)).resolve()
        if self.root.resolve() in folder.parents and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)

    async def check(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".write-check"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False


class S3Storage:
    """S3 or R2. boto3 is synchronous, so each call runs in a worker thread."""

    def __init__(self, client, bucket: str, prefix: str = "", encrypt: bool = True):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.encrypt = encrypt

    def _full(self, key: str) -> str:
        return f"{self.prefix}{key}"

    async def save(self, hospital_id: str, ext: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        key = f"{folder_for(hospital_id)}/{uuid.uuid4().hex}.{ext}"
        extra = {"ServerSideEncryption": "AES256"} if self.encrypt else {}
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=self._full(key), Body=data,
            ContentType=content_type, **extra,
        )
        return key

    async def load(self, key: str) -> Optional[bytes]:
        if not KEY_RE.match(key or ""):
            return None
        from botocore.exceptions import ClientError

        def get() -> Optional[bytes]:
            try:
                return self.client.get_object(Bucket=self.bucket, Key=self._full(key))["Body"].read()
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                    return None
                raise
        return await asyncio.to_thread(get)

    async def delete_prefix(self, hospital_id: str) -> None:
        prefix = self._full(f"{folder_for(hospital_id)}/")

        def run() -> None:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if keys:
                    self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True})
        await asyncio.to_thread(run)

    async def check(self) -> bool:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
            return True
        except Exception as exc:
            logger.error("Document storage check failed: %s", type(exc).__name__)
            return False


_cache: Dict[tuple, Storage] = {}


def reset_cache() -> None:
    _cache.clear()


def get_storage() -> Storage:
    """The configured backend. Cached per configuration so the S3 client is reused."""
    ident = (settings.s3_bucket, settings.s3_endpoint_url, settings.s3_region, settings.s3_access_key_id,
             settings.s3_prefix, settings.upload_dir)
    if ident not in _cache:
        if settings.s3_bucket:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url or None,
                region_name=settings.s3_region or None,
                aws_access_key_id=settings.s3_access_key_id or None,
                aws_secret_access_key=settings.s3_secret_access_key or None,
                config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                              connect_timeout=5, read_timeout=15),
            )
            # R2 encrypts at rest itself and rejects the SSE header; AWS gets AES256.
            _cache[ident] = S3Storage(client, settings.s3_bucket, settings.s3_prefix, encrypt=not settings.s3_endpoint_url)
        else:
            _cache[ident] = LocalStorage(settings.upload_dir)
    return _cache[ident]


def persistent() -> bool:
    """True when documents survive a redeploy (a bucket is configured)."""
    return bool(settings.s3_bucket)
