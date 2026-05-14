"""Local secret storage for the Thomas server.

Goal: allow the web UI to set cloud API keys without putting them in thomas.toml.

Security model:
- Secret management endpoints should be restricted to loopback requests.
- On Windows, keys are persisted encrypted using DPAPI (current user scope).
- Keys are never returned back to the browser once set.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)


@dataclass
class SecretStorageInfo:
    encryption: str  # "dpapi" | "none"
    scope: str  # "current_user" | "plaintext"
    path: str


class SecretStore:
    """In-memory + persisted (optional) secret store."""

    def __init__(self, root_dir: Path, *, filename: str = "secrets.json") -> None:
        self._root_dir = Path(root_dir)
        self._path = self._root_dir / filename
        self._keys: dict[str, str] = {}
        self._persisted: set[str] = set()
        self._meta: dict[str, dict[str, object]] = {}
        self._storage = self._detect_storage()
        self._load()

    @property
    def storage_info(self) -> SecretStorageInfo:
        return SecretStorageInfo(
            encryption=self._storage["encryption"],
            scope=self._storage["scope"],
            path=str(self._path),
        )

    def has(self, profile: str) -> bool:
        return bool(self._keys.get(profile))

    def is_persisted(self, profile: str) -> bool:
        return profile in self._persisted

    def get(self, profile: str) -> str | None:
        v = self._keys.get(profile)
        return v if v else None

    def set(
        self,
        profile: str,
        api_key: str,
        *,
        persist: bool = True,
        rotation_days: int | None = None,
    ) -> None:
        api_key = str(api_key or "").strip()
        if not api_key:
            raise ValueError("api_key is required")

        name = str(profile or "").strip()
        if not name:
            raise ValueError("profile is required")

        prev_persisted = name in self._persisted
        now_iso = _utc_iso()
        self._keys[profile] = api_key
        meta = dict(self._meta.get(name) or {})
        meta["updated_at"] = now_iso
        if rotation_days is not None:
            meta["rotation_days"] = _normalize_rotation_days(rotation_days)
        self._meta[name] = meta
        if persist:
            self._persisted.add(name)
            self._save()
        else:
            self._persisted.discard(name)
            if prev_persisted:
                self._save()

    def clear(self, profile: str) -> None:
        self._keys.pop(profile, None)
        self._persisted.discard(profile)
        self._meta.pop(profile, None)
        self._save()

    def set_rotation_days(self, profile: str, rotation_days: int) -> None:
        name = str(profile or "").strip()
        if not name:
            raise ValueError("profile is required")
        if name not in self._keys:
            raise ValueError("profile has no stored secret")
        meta = dict(self._meta.get(name) or {})
        meta["rotation_days"] = _normalize_rotation_days(rotation_days)
        if not _safe_iso(meta.get("updated_at")):
            meta["updated_at"] = _utc_iso()
        self._meta[name] = meta
        if name in self._persisted:
            self._save()

    def metadata(self, profile: str) -> dict[str, object]:
        return dict(self._meta.get(str(profile or "").strip()) or {})

    def rotation_reminders(
        self,
        *,
        default_rotation_days: int = 90,
        warning_days: int = 14,
        now_utc: datetime | None = None,
    ) -> list[dict[str, object]]:
        now = now_utc.astimezone(timezone.utc) if isinstance(now_utc, datetime) else datetime.now(timezone.utc)
        default_days = _normalize_rotation_days(default_rotation_days)
        warn_days = max(0, int(warning_days))

        rows: list[dict[str, object]] = []
        for profile in sorted(self._keys.keys()):
            key = self._keys.get(profile)
            if not key:
                continue
            meta = dict(self._meta.get(profile) or {})
            updated_at_text = _safe_iso(meta.get("updated_at"))
            updated_at_dt = _parse_iso_utc(updated_at_text)
            rotation_days_raw = meta.get("rotation_days")
            rotation_days = _normalize_rotation_days(rotation_days_raw if rotation_days_raw is not None else default_days)
            due_at_text = ""
            due_in_days: int | None = None
            status = "unknown"
            if updated_at_dt is not None:
                due_at_dt = updated_at_dt + timedelta(days=rotation_days)
                delta_days = (due_at_dt - now).total_seconds() / 86400.0
                due_in_days = int(delta_days)
                due_at_text = due_at_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if due_in_days < 0:
                    status = "expired"
                elif due_in_days <= warn_days:
                    status = "due_soon"
                else:
                    status = "ok"
            rows.append(
                {
                    "profile": profile,
                    "persisted": profile in self._persisted,
                    "updated_at": updated_at_text,
                    "rotation_days": rotation_days,
                    "due_at": due_at_text,
                    "due_in_days": due_in_days,
                    "status": status,
                }
            )

        rank = {"expired": 0, "due_soon": 1, "ok": 2, "unknown": 3}
        rows.sort(key=lambda r: (rank.get(str(r.get("status") or "unknown"), 9), int(r.get("due_in_days") or 999999)))
        return rows

    # ----- internal helpers -----

    def _detect_storage(self) -> dict:
        if sys.platform == "win32":
            return {"encryption": "dpapi", "scope": "current_user"}
        return {"encryption": "none", "scope": "plaintext"}

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return

        enc = str(data.get("encryption") or "")
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

        for profile, stored in keys.items():
            if not isinstance(profile, str) or not isinstance(stored, str):
                continue

            try:
                if enc == "dpapi" and sys.platform == "win32":
                    plain = _dpapi_unprotect(base64.b64decode(stored.encode("ascii")))
                    self._keys[profile] = plain.decode("utf-8", errors="replace")
                    self._persisted.add(profile)
                elif enc == "none":
                    # Plaintext fallback (non-Windows).
                    self._keys[profile] = stored
                    self._persisted.add(profile)
            except Exception as e:
                # Corrupt entry; skip.
                log.debug("Skipping unreadable secret for profile %s: %s", profile, e)

        for profile, row in meta.items():
            if not isinstance(profile, str) or not isinstance(row, dict):
                continue
            normalized: dict[str, object] = {}
            updated_at = _safe_iso(row.get("updated_at"))
            if updated_at:
                normalized["updated_at"] = updated_at
            rotation_days = row.get("rotation_days")
            if rotation_days is not None:
                try:
                    normalized["rotation_days"] = _normalize_rotation_days(rotation_days)
                except Exception:
                    pass
            if normalized:
                self._meta[profile] = normalized

    def _save(self) -> None:
        self._root_dir.mkdir(parents=True, exist_ok=True)

        if self._storage["encryption"] == "dpapi" and sys.platform == "win32":
            keys = {}
            for profile, key in self._keys.items():
                if profile not in self._persisted:
                    continue
                blob = _dpapi_protect(key.encode("utf-8"))
                keys[profile] = base64.b64encode(blob).decode("ascii")
            data = {"version": 2, "encryption": "dpapi", "keys": keys}
        else:
            keys = {p: self._keys[p] for p in self._persisted if p in self._keys}
            data = {"version": 2, "encryption": "none", "keys": keys}

        meta: dict[str, dict[str, object]] = {}
        for profile in self._persisted:
            if profile not in self._keys:
                continue
            row = dict(self._meta.get(profile) or {})
            updated_at = _safe_iso(row.get("updated_at")) or _utc_iso()
            item: dict[str, object] = {"updated_at": updated_at}
            if row.get("rotation_days") is not None:
                try:
                    item["rotation_days"] = _normalize_rotation_days(row.get("rotation_days"))
                except Exception:
                    pass
            meta[profile] = item
        data["meta"] = meta

        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _set_private_permissions(tmp)
        os.replace(tmp, self._path)
        _set_private_permissions(self._path)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_iso(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    dt = _parse_iso_utc(raw)
    if dt is None:
        return ""
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_rotation_days(value: object) -> int:
    try:
        days = int(value)
    except Exception as exc:
        raise ValueError("rotation_days must be an integer") from exc
    if days < 1:
        raise ValueError("rotation_days must be >= 1")
    return days


def _set_private_permissions(path: Path) -> None:
    """Best-effort private file permissions for persisted secrets."""
    if os.name == "nt":
        # Windows ACLs are inherited; keep this as a no-op.
        return
    try:
        os.chmod(path, 0o600)
    except Exception as e:
        # Don't fail secret writes if chmod is unavailable.
        log.debug("Could not apply restrictive permissions to %s: %s", path, e)


def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI (current user scope)."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI only available on Windows")

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    CryptProtectData = crypt32.CryptProtectData
    CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    CryptProtectData.restype = wintypes.BOOL

    LocalFree = kernel32.LocalFree
    LocalFree.argtypes = [ctypes.c_void_p]
    LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()

    if not CryptProtectData(ctypes.byref(blob_in), "thomas", None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData failed")

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt bytes with Windows DPAPI (current user scope)."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI only available on Windows")

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    CryptUnprotectData = crypt32.CryptUnprotectData
    CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    CryptUnprotectData.restype = wintypes.BOOL

    LocalFree = kernel32.LocalFree
    LocalFree.argtypes = [ctypes.c_void_p]
    LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    desc = wintypes.LPWSTR()

    if not CryptUnprotectData(ctypes.byref(blob_in), ctypes.byref(desc), None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData failed")

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if desc:
            LocalFree(desc)
        LocalFree(blob_out.pbData)
