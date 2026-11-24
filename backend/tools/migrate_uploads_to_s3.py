"""Copy documents from the local UPLOAD_DIR into the configured S3 / R2 bucket.

Run once when switching from local disk to a bucket. Keys are identical in both
places, so existing hospital records keep working without any database change.

    python -m backend.tools.migrate_uploads_to_s3 --dry-run
    python -m backend.tools.migrate_uploads_to_s3

Local files are left in place; delete them yourself after checking the bucket.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from backend.config import settings
from backend.services.file_storage import KEY_RE, S3Storage, get_storage

CONTENT_TYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png"}


async def migrate(root: Path, storage: S3Storage, dry_run: bool) -> dict:
    counts = {"copied": 0, "skipped_existing": 0, "ignored": 0}
    for path in sorted(root.glob("*/*")):
        key = f"{path.parent.name}/{path.name}"
        if not path.is_file() or not KEY_RE.match(key):
            counts["ignored"] += 1
            continue
        if await storage.load(key) is not None:
            counts["skipped_existing"] += 1
            continue
        if not dry_run:
            from asyncio import to_thread
            extra = {"ServerSideEncryption": "AES256"} if storage.encrypt else {}
            await to_thread(
                storage.client.put_object, Bucket=storage.bucket, Key=storage._full(key), Body=path.read_bytes(),
                ContentType=CONTENT_TYPES[path.suffix.lstrip(".")], **extra,
            )
        counts["copied"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show what would be copied")
    args = parser.parse_args()
    if not settings.s3_bucket:
        print("S3_BUCKET is not set; nothing to migrate to.", file=sys.stderr)
        return 1
    root = Path(settings.upload_dir)
    if not root.is_dir():
        print(f"No local upload folder at {root}.", file=sys.stderr)
        return 1
    counts = asyncio.run(migrate(root, get_storage(), args.dry_run))
    print(("DRY RUN: " if args.dry_run else "") + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
