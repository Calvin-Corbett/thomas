"""Serve a Code conversation preview from its pruned project asset allowlist."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.event_loop_offload import off_loop
from thomas.forge.anvil import forge_code_projects
from thomas.server.app_keys import APP_DELIVERABLE_PREVIEW_SERVICE

# What a page may pull in while it runs. Keeping the preview to web assets
# means previewing a page cannot serve source or secrets from the project.
_PREVIEWABLE_SUFFIXES = {
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".json",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp3",
    ".ogg",
    ".wav",
    ".webm",
    ".mp4",
}

# Directories the preview walk must never even ENTER. The old rglob("*")
# filtered these from its RESULTS but still descended into them, and it ran on
# the event loop -- measured live (py-spy, 2026-08-05): a conversation whose
# project root was a full checkout froze the WHOLE server for the duration of a
# ~1.5M-entry walk; every request, including "/", timed out for four minutes.
# The walk fires automatically -- the results UI hydrates artifact thumbnails
# whenever a Code conversation renders -- so one click on the wrong task took
# Thomas down for everyone watching.
_PREVIEW_PRUNED_DIRS = {".git", "node_modules", ".thomas", ".claude", ".venv", "__pycache__"}


def _preview_allowlist(root: Path) -> set[str]:
    """Walk a project for previewable web assets, pruning as it goes.

    Runs in a worker thread (see conversation_preview) and prunes excluded
    directories IN PLACE so the walk never enters them, instead of enumerating
    a million entries and discarding most of them afterwards.
    """
    allowed: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PREVIEW_PRUNED_DIRS]
        for filename in filenames:
            if Path(filename).suffix.lower() not in _PREVIEWABLE_SUFFIXES:
                continue
            rel = Path(dirpath, filename).relative_to(root)
            allowed.add(rel.as_posix())
    return allowed


def _preview_target(root: Path, tail: str) -> bool:
    """Resolve the requested file, keeping filesystem probes out of the handler."""
    target = (root / tail).resolve()
    return target.is_relative_to(root.resolve()) and target.is_file()


def build_evolve_agent_preview_handlers(
    *,
    require_api_access: Callable[[web.Request], None],
    _load_conversation: Callable[[str], tuple[Path, dict[str, Any] | None]],
    _is_thomas_source: Callable[[Any], bool],
) -> dict[str, Any]:
    async def conversation_preview(request: web.Request) -> web.Response:
        """An isolated loopback origin that can actually SERVE the project.

        A generated page was previewed with srcdoc, which has no origin and no
        base URL, so anything the page fetches at runtime fails. Static script
        tags could be inlined, but Thomas moved a game's renderer to a dynamic
        loader and the preview 404'd 51 times and silently fell back to the old
        canvas -- a broken game that looked like the renderer not working.

        This is the same service Chat previews deliverables through: a real
        origin, so relative paths, dynamic imports and fetches behave exactly as
        they will for the user. The allowlist keeps it to web assets, so
        previewing a page cannot serve source or secrets sitting in the project.
        """
        require_api_access(request)
        cid = request.match_info.get("cid", "")
        tail = str(request.query.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not tail or ".." in tail.split("/"):
            return web.json_response({"ok": False, "error": "invalid path"}, status=400)
        service = request.app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
        if service is None:
            return web.json_response({"ok": False, "error": "preview service unavailable"}, status=503)
        try:
            project_root, conv = await off_loop("preview.conversation_lookup", _load_conversation, cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        if conv is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        root = Path(project_root)
        if not await off_loop("preview.target_check", _preview_target, root, tail):
            return web.json_response({"ok": False, "error": "file not found"}, status=404)
        # The same refusal the edit path makes (`project_is_thomas_source`),
        # for the same reason plus one more: walking the checkout is exactly
        # the multi-minute freeze described above _preview_allowlist, and Code
        # will not serve its own source tree as an app either way.
        if await off_loop("preview.source_check", _is_thomas_source, root):
            return web.json_response(
                {
                    "ok": False,
                    "error": "This task is pointed at Thomas's own source folder, which Code will not preview.",
                    "code": "project_is_thomas_source",
                },
                status=409,
            )
        # RELATIVE paths from a PRUNED walk, off the event loop. See
        # _preview_allowlist for both measured failure modes this closes: the
        # absolute-parts filter that emptied every allowlist under ~/.thomas,
        # and the on-loop rglob that froze the whole server on big roots.
        allowed = await off_loop("preview.allowlist_walk", _preview_allowlist, root)
        if not allowed:
            return web.json_response({"ok": False, "error": "nothing to preview"}, status=404)
        try:
            url = await service.preview_directory_url(
                subject_id=f"code:{cid}",
                workspace=root,
                tail=tail,
                allowed_files=allowed,
            )
        except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)
        return web.json_response({"ok": True, "url": url, "path": tail})

    return {"conversation_preview": conversation_preview}
