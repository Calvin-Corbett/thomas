"""Serving what a Code run built, without serving the project it built it in.

Split out of ``evolve_agent_routes`` because this is a security boundary, not a
feature: everything here exists to decide whether ONE file may leave the
project folder, and under what headers. Two rules do the deciding -- the file
must be an artifact this conversation's own build recorded, and an HTML entry
point never streams from here at all (it redirects into the isolated preview
origin) -- and both are easier to audit in a file that does nothing else.

The expiring per-conversation capability lives here too, with its secret, so
the only way to mint one is to be this module.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server.app_keys import APP_DELIVERABLE_PREVIEW_SERVICE

from .evolve_agent_http_support import conversation_artifact_allowlist


def build_evolve_agent_artifact_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    project_for_conversation: Callable[[str], Path],
    capability_ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Build the artifact handlers with a capability secret of their own.

    The secret is minted per build (per server start), so capabilities do not
    survive a restart -- an expired link is a re-fetch, and a leaked one dies
    with the process.
    """
    artifact_capability_secret = secrets.token_bytes(32)

    def _artifact_capability(cid: str, bucket: int | None = None) -> str:
        current_bucket = int(time.time() // capability_ttl_seconds) if bucket is None else bucket
        payload = f"{cid}:{current_bucket}".encode()
        return hmac.new(artifact_capability_secret, payload, hashlib.sha256).hexdigest()

    def _valid_artifact_capability(cid: str, capability: str) -> bool:
        current_bucket = int(time.time() // capability_ttl_seconds)
        return any(
            hmac.compare_digest(capability, _artifact_capability(cid, bucket))
            for bucket in (current_bucket, current_bucket - 1)
        )

    def _artifact_scope(cid: str, tail: str) -> tuple[Path, Path, set[str]]:
        try:
            root = project_for_conversation(cid)
        except forge_code_projects.ForgeCodeProjectError as exc:
            raise web.HTTPNotFound(text=str(exc)) from exc
        tail = str(tail or "").strip()
        if not tail:
            raise web.HTTPNotFound(text="no artifact path")
        rel = tail.replace("\\", "/")
        allowed = conversation_artifact_allowlist(root, forge_code_store.load_conversation(root, str(cid)))
        if rel not in allowed:
            raise web.HTTPNotFound(text="not an artifact of this build")
        root_resolved = root.resolve()
        target = (root_resolved / rel).resolve()
        if not target.is_file() or not target.is_relative_to(root_resolved):
            raise web.HTTPNotFound(text="artifact file not found")
        return root_resolved, target, allowed

    def _artifact_file_response(cid: str, tail: str) -> web.FileResponse:
        _root_resolved, target, _allowed = _artifact_scope(cid, tail)
        response = web.FileResponse(target)
        # 'unsafe-eval' for the same reason the deliverable preview grants it:
        # the browser smoke that CERTIFIES these pages already allows it, so
        # without it this route is stricter than the check the page passed, and
        # a verified build breaks the instant the owner opens it. A calculator
        # evaluating a typed expression is the ordinary case, and it failed here
        # with `EvalError` while verification reported `completed`.
        #
        # 'unsafe-inline' is already granted, so a page can run any JavaScript
        # it likes by writing it out; refusing to evaluate a STRING removes no
        # capability. What actually contains the page is untouched and is
        # stricter here than in the preview: default-src 'none', connect-src
        # 'none' (no network at all), form-action 'none', base-uri 'none'.
        #
        # connect-src 'none' STAYS even though the standalone preview tab now
        # allows outbound https/wss (deliverable_aiohttp._apply_headers,
        # measured w2-code-network / w2-code-impossible). This response never
        # serves that tab: HTML routed through `artifact` 302s to the preview
        # service, so what reaches here is downloads, non-HTML assets, and the
        # capability route's decorative frames beside the chat -- surfaces
        # where a silent network block is announced by the visible notice in
        # unified_code_results.js, not fixed by widening a boundary nothing
        # interactive runs on.
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' data:; img-src 'self' data:; font-src 'self' data:; "
            "media-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def artifact(request: web.Request) -> web.StreamResponse:
        """Enter an isolated preview origin or download one verified artifact."""
        require_api_access(request)
        cid = str(request.match_info.get("cid", "") or "")
        tail = str(request.match_info.get("tail", "") or "")
        if Path(tail).suffix.lower() not in {".html", ".htm"}:
            return _artifact_file_response(cid, tail)
        root, _target, allowed = _artifact_scope(cid, tail)
        preview_service = app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
        if preview_service is None:
            raise web.HTTPServiceUnavailable(text="Code preview service is not ready")
        try:
            location = await preview_service.preview_directory_url(
                subject_id=f"code:{cid}",
                workspace=root,
                tail=tail,
                allowed_files=allowed,
            )
        except (FileNotFoundError, RuntimeError):
            raise web.HTTPServiceUnavailable(text="Code preview service is not ready") from None
        raise web.HTTPFound(
            location=location,
            headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache", "Expires": "0"},
        )

    async def artifact_content(request: web.Request) -> web.StreamResponse:
        """Serve one artifact only when its expiring conversation capability is valid."""
        require_api_access(request)
        cid = str(request.match_info.get("cid", "") or "")
        capability = str(request.match_info.get("capability", "") or "")
        if not _valid_artifact_capability(cid, capability):
            raise web.HTTPNotFound(text="preview capability expired or invalid")
        response = _artifact_file_response(cid, str(request.match_info.get("tail", "") or ""))
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return {
        "artifact": artifact,
        "artifact_content": artifact_content,
    }
