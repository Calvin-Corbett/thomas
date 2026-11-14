from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PACK_ID = "desktop-operator"
MODULE_NAME = "desktop_operator"
MODE = "desktop_operator"


def before_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("desktop_operator", True)
    return data


def after_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("desktop_operator", True)
    return data


def _surface_report() -> dict[str, Any]:
    """Verify the surface this pack promises is actually on disk.

    A marketplace row can advertise a surface the bundle never shipped, and the
    user only finds out by clicking it. The entry file and every local asset it
    references are checked here so the failure is reported, not discovered.
    """
    here = Path(__file__).resolve().parent
    try:
        manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"manifest unreadable: {type(exc).__name__}: {exc}"}

    if str(manifest.get("id") or "") != PACK_ID:
        return {"ok": False, "error": f"manifest id {manifest.get('id')!r} is not {PACK_ID!r}"}

    entry_rel = str((manifest.get("surface") or {}).get("entry_html") or "")
    if not entry_rel:
        return {"ok": False, "error": "manifest declares no surface.entry_html"}

    entry = here / entry_rel
    if not entry.is_file():
        return {"ok": False, "error": f"declared surface is missing: {entry_rel}"}

    try:
        html = entry.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": f"surface unreadable: {type(exc).__name__}: {exc}"}

    refs = re.findall(r'(?:src|href)="(\./[^"]+)"', html)
    missing = [ref for ref in refs if not (entry.parent / ref[2:]).is_file()]
    if missing:
        return {"ok": False, "error": f"surface references missing assets: {sorted(missing)}"}

    return {"ok": True, "surface": entry_rel, "assets_verified": len(refs)}


def healthcheck() -> dict[str, Any]:
    """Report pack health: the surface resolves AND the domain module agrees.

    Unlike the surface-only packs this one is backed by ``thomas.desktop_operator``.
    The import is half the check -- an uninstalled or renamed module means the
    pack cannot work. The version comparison is the other half: a bundle that has
    drifted from the module it drives is the quiet failure worth catching.
    """
    report = _surface_report()
    if not report.get("ok"):
        return {"ok": False, "pack": PACK_ID, "error": report.get("error")}

    try:
        from thomas.desktop_operator import DESKTOP_OPERATOR_SERVICE_ID, DESKTOP_OPERATOR_VERSION
    # A missing/uninstalled domain package raises ImportError, a renamed symbol
    # AttributeError, and a package __init__ touching env or files can raise
    # OSError/RuntimeError. All four mean "pack not healthy".
    except (AttributeError, ImportError, OSError, RuntimeError) as exc:
        return {"ok": False, "pack": PACK_ID, "error": f"{type(exc).__name__}: {exc}"}

    if not str(DESKTOP_OPERATOR_SERVICE_ID or "").strip():
        return {"ok": False, "pack": PACK_ID, "error": "desktop operator service id is empty"}

    here = Path(__file__).resolve().parent
    manifest_version = str(json.loads((here / "manifest.json").read_text(encoding="utf-8")).get("version") or "")
    if manifest_version != str(DESKTOP_OPERATOR_VERSION):
        return {
            "ok": False,
            "pack": PACK_ID,
            "error": f"bundle version {manifest_version} != module {DESKTOP_OPERATOR_VERSION}",
        }

    return {
        "ok": True,
        "pack": PACK_ID,
        "surface": report["surface"],
        "assets_verified": report["assets_verified"],
        "service_id": DESKTOP_OPERATOR_SERVICE_ID,
        "version": manifest_version,
    }
