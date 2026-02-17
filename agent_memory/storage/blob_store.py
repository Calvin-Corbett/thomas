from __future__ import annotations
import hashlib
from pathlib import Path

class BlobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        sub = self.root / h[:2]
        sub.mkdir(parents=True, exist_ok=True)
        p = sub / h
        if not p.exists():
            p.write_bytes(data)
        return h

    def get_bytes(self, blob_id: str) -> bytes:
        p = self.root / blob_id[:2] / blob_id
        return p.read_bytes()

    def put_text(self, text: str, encoding: str = "utf-8") -> str:
        return self.put_bytes(text.encode(encoding))

    def get_text(self, blob_id: str, encoding: str = "utf-8") -> str:
        return self.get_bytes(blob_id).decode(encoding)
