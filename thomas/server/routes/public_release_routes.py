"""The two routes behind Settings > Publish to GitHub: look at what would go public, then send a review copy.

GET  /api/public-release/preview   -> {"state": "idle" | "working" | "ready" | "failed", "preview"?, "message"?}
POST /api/public-release/publish   -> {"preview_digest", "open_pr"?}; asks you to sign in with Windows first

The first GET starts building the preview in a worker thread and answers ``working``; asking again reads where it is.
``?fresh=1`` builds a new one. Publishing needs the digest of the preview you are looking at, and then a Windows sign-in
for that exact preview, where it goes included. Both routes need the access token and a caller on this computer.

The release tool lives in ``scripts/forge/publish`` and travels only with a development checkout, so a copy of Thomas
without it says so in words and does nothing else.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)

WORKING, READY, FAILED, IDLE = "working", "ready", "failed", "idle"
NOT_HERE = "Publishing needs the development copy of Thomas, and this copy does not have it."


class CheckoutBackend:
    """The real release tool, loaded when first used so a copy without it can still serve the page."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def _tool(self) -> Any:
        try:
            from scripts.forge.publish import public_release
        except ImportError as exc:
            raise RuntimeError(NOT_HERE) from exc
        return public_release

    def build(self) -> Any:
        return self._tool().build(self.repo, remote="origin")

    def confirm(self, preview: Any) -> Any:
        return self._tool().confirm(preview)

    def publish(self, preview: Any, record: Any, open_pr: bool) -> Any:
        return self._tool().publish(preview, record, open_pr=open_pr)


class ReleaseJobs:
    """The one preview this server holds, and the work that makes it."""

    def __init__(self, backend: Any, spawn: Callable[..., Any]) -> None:
        self.backend, self.spawn = backend, spawn
        self.state, self.message = IDLE, ""
        self.preview: Any = None
        self.stopped = False
        self.publishing = False

    def begin(self) -> None:
        self.state, self.message = WORKING, ""
        self._drop_preview()
        self.spawn(self._run, name="public-release-preview")

    async def _run(self) -> None:
        # A stop ends this wait, not the worker: the worker closes its own copy when it finds the stop.
        await asyncio.to_thread(self._work)

    def _work(self) -> None:
        try:
            preview = self.backend.build()
        except (RuntimeError, OSError, ValueError) as exc:
            self.state, self.message = FAILED, f"The preview could not be made: {exc}"
            return
        if self.stopped:
            preview.close()
            return
        self.preview, self.state = preview, READY

    def _drop_preview(self) -> None:
        old, self.preview = self.preview, None
        if old is not None:
            old.close()

    async def stop(self) -> None:
        self.stopped = True
        self._drop_preview()

    def read(self) -> dict[str, Any]:
        if self.state == READY and self.preview is not None:
            return {"state": READY, "preview": self.preview.to_dict()}
        return {"state": self.state, "message": self.message}


def register_public_release_routes(
    app: web.Application,
    *,
    jobs: ReleaseJobs,
    require_api_access: Callable[[web.Request], Any],
    require_loopback: Callable[[web.Request], Any],
    read_json: Callable[[web.Request], Awaitable[Any]],
) -> None:
    async def preview(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        if jobs.state != WORKING and (jobs.state == IDLE or request.query.get("fresh") == "1"):
            jobs.begin()
        return web.json_response(jobs.read())

    async def publish(request: web.Request) -> web.Response:
        require_api_access(request)
        require_loopback(request)
        body = await read_json(request)
        body = body if isinstance(body, dict) else {}
        shown = jobs.preview
        if jobs.state != READY or shown is None or str(body.get("preview_digest") or "") != shown.digest():
            return _said(
                409, "That is not the preview you are looking at any more. Look at it again before publishing."
            )
        if jobs.publishing:
            return _said(409, "A release is already being sent.")
        jobs.publishing = True
        try:
            record = await asyncio.to_thread(jobs.backend.confirm, shown)
            if record is None:
                return _said(403, "You did not sign in with Windows, so nothing was published.")
            result = await asyncio.to_thread(jobs.backend.publish, shown, record, bool(body.get("open_pr")))
        except (RuntimeError, OSError, ValueError) as exc:
            log.warning("public release publish failed: %s", exc)
            return _said(500, f"Nothing was published: {exc}")
        finally:
            jobs.publishing = False
        if result.ok and not result.dry_run:
            jobs.state = IDLE  # the branch now exists, so this preview cannot be sent again
            jobs.preview = None
            shown.close()
        payload = {
            "ok": bool(result.ok),
            "lines": list(result.lines),
            "branch": result.branch,
            "branch_url": result.branch_url,
            "pr_url": result.pr_url,
            "signed": bool(result.signed),
        }
        return web.json_response(payload, status=200 if result.ok else 409)

    app.router.add_get("/api/public-release/preview", preview, allow_head=False)
    app.router.add_post("/api/public-release/publish", publish)


def _said(status: int, text: str) -> web.Response:
    return web.json_response({"ok": False, "lines": [text]}, status=status)
