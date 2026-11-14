"""Read a Thomas project's whole green change without staging or changing its copy."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server import green_checkout, green_handoff, thomas_project
from thomas.server import keeper_guard_capture as capture
from thomas.server.routes import self_project_routes as projects

PATH = projects.PATH + "/{conversation_id}/change"


def _git_bytes(green: green_checkout.Green, *args: str) -> tuple[int, bytes, bytes]:
    try:
        result = subprocess.run(
            green_checkout._git_command(green, "--no-optional-locks", "-c", "diff.autoRefreshIndex=false", *args),
            cwd=green.work,
            env=green_checkout._clean_env(),
            capture_output=True,
            timeout=green_checkout._GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise green_checkout.GreenUnavailable("could not read green's patch") from exc
    return result.returncode, result.stdout, result.stderr


def _find_green_read_only(execution_id: str) -> green_checkout.Green | None:
    """Resolve a green's effective base without find_green's metadata update."""
    try:
        work, git_dir = green_checkout._paths(execution_id)
    except green_checkout.GreenUnavailable:
        return None
    meta = green_checkout._metadata(git_dir)
    if meta is None or not work.is_dir():
        return None
    green = green_checkout.Green(
        execution_id=execution_id,
        work=work,
        git_dir=git_dir,
        base=str(meta.get("base") or ""),
        blue=Path(str(meta.get("blue") or "")),
    )
    taken_in = green_checkout._dev_taken_in(green)
    return replace(green, base=taken_in) if taken_in else green


def _read_patch(green: green_checkout.Green) -> tuple[list[str], str]:
    """Recreate the staged hand-in diff from tracked and untracked files, without writing an index."""
    code, tracked, _ = _git_bytes(green, "diff", "--no-renames", "--name-only", "-z", green.base, "--")
    if code:
        raise green_checkout.GreenUnavailable("could not list green's tracked changes")
    code, added, _ = _git_bytes(green, "ls-files", "--others", "--exclude-standard", "-z")
    if code:
        raise green_checkout.GreenUnavailable("could not list green's new files")
    tracked_names = {n for n in tracked.decode("utf-8", "surrogateescape").split("\0") if n}
    added_names = {n for n in added.decode("utf-8", "surrogateescape").split("\0") if n}
    code, base_names, _ = _git_bytes(green, "ls-tree", "-r", "--name-only", "-z", green.base)
    if code:
        raise green_checkout.GreenUnavailable("could not list green's base files")
    base_files = {n for n in base_names.decode("utf-8", "surrogateescape").split("\0") if n}
    exclude = Path(green.blue) / ".git" / "info" / "exclude"
    extra = ("-c", f"core.excludesFile={exclude}") if exclude.is_file() else ()
    for name in (tracked_names - base_files) | added_names:
        code, _ignored, _ = _git_bytes(green, *extra, "check-ignore", "--no-index", "--", name)
        if code == 0:
            tracked_names.discard(name)
            added_names.discard(name)
        elif code != 1:
            raise green_checkout.GreenUnavailable("could not check green's ignored files")
    excluded = green_checkout.COORDINATION_PATHS
    files = sorted(
        name
        for name in tracked_names | added_names
        if not any(name == path or name.startswith(path + "/") for path in excluded)
    )
    if capture.linked(green.work, "") or any(capture.first_link(green.work, name) is not None for name in files):
        raise green_checkout.GreenUnavailable("green's change contains a link and cannot be read safely")
    chunks: list[bytes] = []
    changed_files: list[str] = []
    for name in files:
        if name in tracked_names:
            code, data, _ = _git_bytes(
                green, "diff", "--no-renames", "--binary", "--full-index", green.base, "--", name
            )
        else:
            code, data, _ = _git_bytes(green, "diff", "--no-index", "--binary", "--full-index", "--", os.devnull, name)
            if code == 1:
                code = 0  # --no-index uses 1 for a difference.
        if code:
            raise green_checkout.GreenUnavailable(f"could not read green's change for {name}")
        if data:
            changed_files.append(name)
            chunks.append(data)
    return changed_files, b"".join(chunks).decode("utf-8", "surrogateescape")


def _readable_greens() -> list[tuple[Path, dict[str, Any]]]:
    """Keep readable conversations even if a different green cannot be listed."""
    try:
        return projects._in_greens()
    except projects.GreensUnreadable as exc:
        return exc.found


def _change(cid: str, catalog: Path, running: set[str]) -> tuple[int, dict[str, Any]]:
    try:
        listing = projects.read_projects(catalog, running, changed_files=False)
        row = next((row for row in listing["projects"] if row["conversation_id"] == cid), None)
        if row is None:
            return 404, {"ok": False, "error": "no Thomas project in a green has that id"}
        if not any(str(c.get("id") or "") == cid for _work, c in _readable_greens()):
            return 404, {"ok": False, "error": "no Thomas project in a green has that id"}
        if any(str(c.get("id") or "") == cid for c in projects._conversations(catalog / projects._CONVERSATIONS)):
            return 404, {"ok": False, "error": "no Thomas project in a green has that id"}
        execution_id = str(row.get("execution_id") or "")
        green = _find_green_read_only(execution_id) if execution_id else None
        if green is None:
            return 409, {"ok": False, "error": "this project's green copy is gone, so its change cannot be read"}
        if not any(str(c.get("id") or "") == cid and work == green.work for work, c in _readable_greens()):
            return 404, {"ok": False, "error": "no Thomas project in a green has that id"}
        files, patch = _read_patch(green)
        return 200, {
            "ok": True,
            "conversation_id": cid,
            "execution_id": execution_id,
            "state": row["state"],
            "detail": row["detail"],
            "changed_files": files,
            "patch": patch,
        }
    except (green_checkout.GreenUnavailable, OSError, UnicodeError) as exc:
        return 409, {"ok": False, "error": f"this project's green patch cannot be read: {exc}"}


def register_self_project_change_routes(app: web.Application, *, require_loopback: Any) -> None:
    """Add the loopback-only, read-only view of a project's green change."""

    async def change(request: web.Request) -> web.Response:
        require_loopback(request)
        cid = request.match_info["conversation_id"]
        if not projects._CHAT_ID.fullmatch(cid):
            return web.json_response({"ok": False, "error": "not a valid conversation id"}, status=400)
        catalog, running = thomas_project._catalog_root(), projects._running(request.app)
        status, body = await asyncio.to_thread(_change, cid, catalog, running)
        return web.json_response(body, status=status, dumps=lambda value: json.dumps(value, ensure_ascii=True))

    app.router.add_get(PATH, change)
