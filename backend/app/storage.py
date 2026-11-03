"""Storage abstraction.

All file access goes through :class:`Storage`. The local implementation maps keys to
paths under ``DATA_DIR``. Processing tools (FFmpeg, Whisper) need real file paths, so
the interface exposes :meth:`local_path`; an S3/R2 implementation would download to a
cache there and upload in :meth:`commit`.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings


class Storage(ABC):
    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Return a local filesystem path for *key* (parent dirs are created)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def write_at(self, key: str, offset: int, stream: BinaryIO) -> int:
        """Write *stream* into *key* at *offset*; returns bytes written."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def commit(self, key: str) -> None:  # noqa: B027 - optional hook
        """Persist a file produced at ``local_path(key)`` (no-op for local disk)."""

    def iter_bytes(self, key: str, chunk: int = 1024 * 1024) -> Iterator[bytes]:
        with open(self.local_path(key), "rb") as f:
            while data := f.read(chunk):
                yield data


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("invalid storage key")
        return p

    def local_path(self, key: str) -> Path:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def size(self, key: str) -> int:
        p = self._path(key)
        return p.stat().st_size if p.exists() else 0

    def write_at(self, key: str, offset: int, stream: BinaryIO) -> int:
        p = self.local_path(key)
        mode = "r+b" if p.exists() else "wb"
        written = 0
        with open(p, mode) as f:
            f.seek(offset)
            while data := stream.read(1024 * 1024):
                f.write(data)
                written += len(data)
        return written

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_file():
            p.unlink()

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().data_dir)
    return _storage


def user_prefix(user_id: str) -> str:
    return f"users/{user_id}"


def project_prefix(user_id: str, project_id: str) -> str:
    return f"users/{user_id}/projects/{project_id}"
