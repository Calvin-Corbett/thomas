from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Life Manager Foundation is a support component for bundled and hosted installs.
PACK_ID = "life-manager-foundation"
MODULE_NAME = "life_manager_foundation"
MODE = "life_manager_foundation"


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
    """Report pack health. The declared surface must exist and resolve."""
    report = _surface_report()
    if not report.get("ok"):
        return {"ok": False, "pack": PACK_ID, "error": report.get("error")}
    return {"ok": True, "pack": PACK_ID, **{k: v for k, v in report.items() if k != "ok"}}
