"""File storage behind an interface (PLAN §4 Files, §18 Uploads): local disk in dev, S3-compatible
in prod. Keys are opaque relative paths (`<institution_id>/documents/<document_id>/<name>`); files
live outside any web root and are never served directly."""

import asyncio
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...


class BlobKeyError(ValueError):
    pass


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not key or key.startswith("/") or not path.is_relative_to(self.root):
            raise BlobKeyError(f"invalid blob key {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic on the same filesystem

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)


class S3BlobStore:
    """S3-compatible store (Cloudflare R2 / host volume alternative) — implemented at deploy time
    (step 9.1) once the backend host is chosen. Same interface as LocalBlobStore."""

    def __init__(self, settings: Settings) -> None:
        raise NotImplementedError("S3BlobStore lands with hosting (9.1); use BLOB_BACKEND=local")

    async def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError


def make_blobstore(settings: Settings) -> BlobStore:
    if settings.blob_backend == "s3":
        return S3BlobStore(settings)
    return LocalBlobStore(settings.blob_dir)
