from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TEXT_EXTS = {".txt", ".md", ".py"}
DEFAULT_PDF_EXTS = {".pdf"}
DEFAULT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

DEFAULT_INCLUDE_EXTS = sorted(DEFAULT_TEXT_EXTS | DEFAULT_PDF_EXTS | DEFAULT_IMAGE_EXTS)


@dataclass
class WatcherConfig:
    enabled: bool = True
    recursive: bool = False
    paths: list[str] = field(default_factory=list)

    # extraction/safety
    max_file_size_mb: int = 64
    max_hash_bytes_mb: int = 64
    read_retry_attempts: int = 6
    read_retry_sleep_ms: int = 250
    ocr_lang: str = "eng"

    # de-dupe
    dedupe: bool = True
    dedupe_ttl_seconds: int = 60

    # ignore temp noise
    ignore_suffixes: list[str] = field(default_factory=lambda: [".tmp", ".part", ".crdownload", ".swp"])
    ignore_prefixes: list[str] = field(default_factory=lambda: ["~$", "."])
    ignore_globs: list[str] = field(default_factory=lambda: ["*.DS_Store", "Thumbs.db"])

    # worker tuning
    worker_threads: int = 2

    # override supported ext list (optional)
    include_exts: list[str] | None = None

    def to_public_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "recursive": self.recursive,
            "paths": list(self.paths),
            "max_file_size_mb": self.max_file_size_mb,
            "max_hash_bytes_mb": self.max_hash_bytes_mb,
            "read_retry_attempts": self.read_retry_attempts,
            "read_retry_sleep_ms": self.read_retry_sleep_ms,
            "ocr_lang": self.ocr_lang,
            "dedupe": self.dedupe,
            "dedupe_ttl_seconds": self.dedupe_ttl_seconds,
            "ignore_suffixes": list(self.ignore_suffixes),
            "ignore_prefixes": list(self.ignore_prefixes),
            "ignore_globs": list(self.ignore_globs),
            "worker_threads": self.worker_threads,
            "include_exts": list(self.include_exts) if self.include_exts else None,
        }


def is_supported_file(path: str, include_exts: list[str] | None = None) -> bool:
    p = Path(path)
    ext = p.suffix.lower()
    exts = set(x.lower() for x in (include_exts or DEFAULT_INCLUDE_EXTS))
    return bool(ext) and ext in exts


@dataclass
class IngestResult:
    path: str
    indexed: bool
    skipped: bool = False
    text_len: int = 0
    error: str | None = None
    fingerprint: str | None = None


def _sha256_file(path: Path, max_bytes: int) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        remaining = max_bytes
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def _basic_metadata(path: Path, fingerprint: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "filename": path.name,
        "path": str(path.resolve()),
        "ext": path.suffix.lower(),
        "size_bytes": int(st.st_size),
        "mtime": float(st.st_mtime),
        "sha256": fingerprint,
        "source": "watcher",
    }


def _resolve_config_path(config_path: str | None) -> Path:
    cp = config_path or os.environ.get("THOMAS_CONFIG_PATH") or "thomas.toml"
    return Path(cp)


def load_watcher_config(config_path: str | None = None) -> WatcherConfig:
    """
    Loads watcher config from thomas.toml.
    """
    p = _resolve_config_path(config_path)
    if not p.exists():
        return WatcherConfig()

    try:
        import tomllib  # py3.11+
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(p.read_text(encoding="utf-8", errors="replace"))
    watcher = data.get("watcher", {}) if isinstance(data, dict) else {}

    cfg = WatcherConfig()
    if isinstance(watcher, dict):
        cfg.enabled = bool(watcher.get("enabled", cfg.enabled))
        cfg.recursive = bool(watcher.get("recursive", cfg.recursive))

        paths = watcher.get("paths", [])
        if isinstance(paths, str):
            cfg.paths = [paths]
        elif isinstance(paths, list):
            cfg.paths = [str(x) for x in paths if x]

        cfg.max_file_size_mb = int(watcher.get("max_file_size_mb", cfg.max_file_size_mb))
        cfg.max_hash_bytes_mb = int(watcher.get("max_hash_bytes_mb", cfg.max_hash_bytes_mb))
        cfg.read_retry_attempts = int(watcher.get("read_retry_attempts", cfg.read_retry_attempts))
        cfg.read_retry_sleep_ms = int(watcher.get("read_retry_sleep_ms", cfg.read_retry_sleep_ms))
        cfg.ocr_lang = str(watcher.get("ocr_lang", cfg.ocr_lang))

        cfg.dedupe = bool(watcher.get("dedupe", cfg.dedupe))
        cfg.dedupe_ttl_seconds = int(watcher.get("dedupe_ttl_seconds", cfg.dedupe_ttl_seconds))

        ignore_suffixes = watcher.get("ignore_suffixes", cfg.ignore_suffixes)
        ignore_prefixes = watcher.get("ignore_prefixes", cfg.ignore_prefixes)
        ignore_globs = watcher.get("ignore_globs", cfg.ignore_globs)

        if isinstance(ignore_suffixes, list):
            cfg.ignore_suffixes = [str(x) for x in ignore_suffixes if x]
        if isinstance(ignore_prefixes, list):
            cfg.ignore_prefixes = [str(x) for x in ignore_prefixes if x]
        if isinstance(ignore_globs, list):
            cfg.ignore_globs = [str(x) for x in ignore_globs if x]

        cfg.worker_threads = int(watcher.get("worker_threads", cfg.worker_threads))

        include_exts = watcher.get("include_exts", None)
        if isinstance(include_exts, list):
            cfg.include_exts = [str(x).lower() for x in include_exts if x]
        elif isinstance(include_exts, str):
            cfg.include_exts = [include_exts.lower()]

    if cfg.include_exts:
        cfg.include_exts = sorted(set(x if x.startswith(".") else "." + x for x in cfg.include_exts))
    return cfg


# -------------------------------
# Extraction
# -------------------------------


def _read_text_with_retries(path: Path, attempts: int, sleep_ms: int) -> str:
    last_err: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            last_err = e
            time.sleep(max(0, sleep_ms) / 1000.0)
    raise last_err or RuntimeError("Failed to read text file")


def extract_text(path: str, cfg: WatcherConfig) -> str:
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".pdf":
        return extract_text_pdf(path)
    if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        return extract_text_image(path, cfg.ocr_lang)
    if ext in {".txt", ".md", ".py"}:
        return extract_text_plain(path, cfg.read_retry_attempts, cfg.read_retry_sleep_ms)

    raise ValueError(f"Unsupported file type: {ext}")


def extract_text_plain(path: str, attempts: int, sleep_ms: int) -> str:
    return _read_text_with_retries(Path(path), attempts=attempts, sleep_ms=sleep_ms)


def extract_text_pdf(path: str) -> str:
    try:
        import pdfplumber  # type: ignore
    except Exception as e:
        raise RuntimeError("pdfplumber is required for PDF ingestion") from e

    chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            try:
                txt = page.extract_text() or ""
            except ImportError:
                txt = ""
            txt = txt.strip()
            if txt:
                chunks.append(txt)
    return "\n\n".join(chunks).strip()


def extract_text_image(path: str, lang: str) -> str:
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError("Pillow is required for image ingestion") from e
    try:
        import pytesseract  # type: ignore
    except Exception as e:
        raise RuntimeError("pytesseract is required for image ingestion") from e

    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return (pytesseract.image_to_string(img, lang=lang) or "").strip()


# -------------------------------
# Persistent de-dupe state (SQLite)
# -------------------------------


def _state_db_path(config_path: str | None) -> Path:
    cp = _resolve_config_path(config_path)
    return cp.parent / "thomas_watcher_state.sqlite3"


def _state_init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed (
            fingerprint TEXT PRIMARY KEY,
            path TEXT,
            size_bytes INTEGER,
            mtime REAL,
            status TEXT,
            created_at REAL
        )
        """
    )
    conn.commit()


def _state_seen(conn: sqlite3.Connection, fingerprint: str) -> bool:
    cur = conn.execute("SELECT 1 FROM processed WHERE fingerprint = ? LIMIT 1", (fingerprint,))
    return cur.fetchone() is not None


def _state_mark(
    conn: sqlite3.Connection, fingerprint: str, path: str, size_bytes: int, mtime: float, status: str
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO processed(fingerprint, path, size_bytes, mtime, status, created_at) VALUES(?,?,?,?,?,?)",
        (fingerprint, path, int(size_bytes), float(mtime), status, time.time()),
    )
    conn.commit()


# -------------------------------
# Library adapter
# -------------------------------


def index_into_library(path: str, text: str, metadata: dict[str, Any]) -> None:
    """
    Adapter to your existing library store.

    Default expected integration point:

        # thomas/library/store.py
        def index_file(path: str, text: str, metadata: dict) -> None: ...

    If your store differs, change this function only.
    """
    try:
        from thomas.library import store as store_mod  # type: ignore
    except Exception as e:
        raise RuntimeError("Could not import thomas.library.store") from e

    fn = getattr(store_mod, "index_file", None)
    if callable(fn):
        fn(path=path, text=text, metadata=metadata)  # type: ignore[arg-type]
        return

    get_store = getattr(store_mod, "get_store", None)
    if callable(get_store):
        store = get_store()
        fn2 = getattr(store, "index_file", None)
        if callable(fn2):
            fn2(path=path, text=text, metadata=metadata)  # type: ignore[arg-type]
            return

    raise RuntimeError(
        "No compatible library index function found. "
        "Expected thomas.library.store.index_file(path, text, metadata). "
        "Update thomas/watcher/ingest.py:index_into_library to match your store API."
    )


# -------------------------------
# Ingest entrypoint
# -------------------------------


def ingest_file(path: str, config_path: str | None = None, cfg: WatcherConfig | None = None) -> IngestResult:
    """
    Extract text and index into library store.
    Includes persistent de-dupe (SQLite) keyed by bounded SHA-256 fingerprint.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return IngestResult(path=path, indexed=False, skipped=True, error="File does not exist")

    cfg = cfg or load_watcher_config(config_path=config_path)

    if not is_supported_file(path, include_exts=cfg.include_exts):
        return IngestResult(path=path, indexed=False, skipped=True, error="Unsupported file type")

    try:
        st = p.stat()
        max_bytes = int(cfg.max_file_size_mb) * 1024 * 1024
        if st.st_size > max_bytes:
            return IngestResult(path=path, indexed=False, skipped=True, error="File too large")

        max_hash_bytes = int(cfg.max_hash_bytes_mb) * 1024 * 1024
        max_hash_bytes = min(max_hash_bytes, max_bytes)  # never hash beyond allowed read size

        fingerprint = _sha256_file(p, max_bytes=max_hash_bytes)
        meta = _basic_metadata(p, fingerprint=fingerprint)

        if cfg.dedupe:
            db_path = _state_db_path(config_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path))
            try:
                _state_init(conn)
                if _state_seen(conn, fingerprint):
                    return IngestResult(
                        path=path,
                        indexed=False,
                        skipped=True,
                        error="Duplicate (already indexed)",
                        fingerprint=fingerprint,
                    )
            finally:
                conn.close()

        text = extract_text(path, cfg)
        if not text.strip():
            text = ""

        index_into_library(path=str(p.resolve()), text=text, metadata=meta)

        if cfg.dedupe:
            db_path = _state_db_path(config_path)
            conn = sqlite3.connect(str(db_path))
            try:
                _state_init(conn)
                _state_mark(conn, fingerprint, str(p.resolve()), int(st.st_size), float(st.st_mtime), status="indexed")
            finally:
                conn.close()

        return IngestResult(path=path, indexed=True, text_len=len(text), fingerprint=fingerprint)
    except Exception as e:
        # mark failure fingerprint if we have it? keep simple: return error
        return IngestResult(path=path, indexed=False, skipped=False, error=str(e))
