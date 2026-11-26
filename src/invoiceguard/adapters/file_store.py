"""File storage for uploaded invoices. Local folder in v1–v2; Blob Storage arrives in v3
together with the Blob-triggered Durable Functions orchestration."""

from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname


class FileStore(Protocol):
    def save(self, sha256: str, filename: str, content: bytes) -> str: ...
    def load(self, uri: str) -> bytes: ...


class LocalFileStore:
    """Content-addressed storage on the local file system."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir.resolve()

    def save(self, sha256: str, filename: str, content: bytes) -> str:
        """Store bytes under ``<sha[:2]>/<sha><suffix>`` and return a ``file://`` URI."""
        suffix = Path(filename).suffix.lower()[:10]
        path = self._base / sha256[:2] / f"{sha256}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return path.as_uri()

    def load(self, uri: str) -> bytes:
        """Read bytes back. Only files inside the store directory are allowed."""
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"unsupported URI scheme: {parsed.scheme}")
        path = Path(url2pathname(parsed.path)).resolve()
        if not path.is_relative_to(self._base):
            raise ValueError("path outside the file store")
        return path.read_bytes()
