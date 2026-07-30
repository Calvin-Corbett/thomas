"""Serve worker-built deliverables (e.g. a generated game) as a playable app.

The provider-native worker builds user deliverables in an ISOLATED workspace at
``~/.thomas/workspaces/<execution_id>/`` (never the source repo). The build works,
but the finished artifact was never served — so a "build me a game" result was a
file the user couldn't actually open. This module serves that workspace, loopback-
only and path-traversal-safe, so the task card can link a one-click "Play".

Route: GET /deliverable/{execution_id}            -> the workspace entry file
       GET /deliverable/{execution_id}/{tail:.*}  -> a specific file under it
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from thomas.core import task_bot_runtime
from thomas.server.app_keys import APP_DELIVERABLE_PREVIEW_SERVICE

# Must match thomas/server/chat_delegation.py::_ensure_task_workspace.
_WORKSPACES_BASE = Path.home() / ".thomas" / "workspaces"
_ENTRY_PREFERENCES = ("index.html", "game.html", "main.html")
_PREVIEW_CAPABILITY_TTL_SECONDS = 3600
_MAX_ACTIVE_PREVIEW_GRANTS = 32
_PREVIEW_CAPABILITY_RE = re.compile(r"^[a-z2-7]{52}$")

# Build/helper files are NOT the deliverable — a worker that writes
# build_cookie_pdf.py + cookies.pdf must surface the PDF, not the script. These
# rank LAST so the user's actual output wins. (Fixes the "Open it -> .py script"
# bug the adversarial review caught.)
_SCRIPT_EXTS = {"py", "pyc", "sh", "bash", "bat", "ps1", "rb", "pl", "lock"}
_BUILD_FILENAMES = {"requirements.txt", "package.json", "package-lock.json", "makefile", "dockerfile", ".gitignore"}
# Real deliverables, most "show me" first. HTML = a live web app/game (right-pane
# preview); pdf/image/text render inline in chat; the rest are downloads.
_DELIVERABLE_PRIORITY = (
    "html",
    "htm",
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "svg",
    "webp",
    "docx",
    "pptx",
    "xlsx",
    "doc",
    "ppt",
    "xls",
    "csv",
    "md",
    "txt",
    "json",
    "rtf",
    "mp4",
    "mp3",
    "wav",
    "zip",
)


# Directories that are build/VCS/tooling noise, never the user's deliverable.
_JUNK_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
}


def _is_noise_path(rel: Path) -> bool:
    """True for files that are never the user's deliverable: a true dotfile
    (``.DS_Store``, ``.gitignore``) or any file under a junk dir (``.git``, ``node_modules``)."""
    if rel.name.startswith("."):
        return True
    return any(part in _JUNK_DIRS for part in rel.parts[:-1])


def _deliverable_rank(rel: Path) -> tuple:
    """Sort key: real deliverables before build scripts; within deliverables, the most
    presentable type first; then shallower paths; then name."""
    ext = rel.suffix.lstrip(".").lower()
    name = rel.name.lower()
    is_build = ext in _SCRIPT_EXTS or name in _BUILD_FILENAMES
    try:
        type_rank = _DELIVERABLE_PRIORITY.index(ext)
    except ValueError:
        type_rank = len(_DELIVERABLE_PRIORITY)
    return (1 if is_build else 0, type_rank, len(rel.parts), str(rel))


def _recorded_artifact_entries(execution_id: str, wd: Path) -> list[str]:
    """Return proof artifact paths from the successful execution, validated on disk."""
    record = task_bot_runtime.get_execution(_safe_id(execution_id))
    proof = record.get("proof") if isinstance(record, dict) else None
    artifacts = proof.get("artifacts") if isinstance(proof, dict) else None
    if not isinstance(artifacts, list):
        return []
    entries: list[Path] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        raw = str(artifact.get("path") or artifact.get("file") or "").strip()
        if not raw:
            continue
        rel_text = raw.replace("\\", "/").lstrip("/")
        rel = Path(rel_text)
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            continue
        target = (wd / rel).resolve()
        if not (target == wd or wd in target.parents) or not target.is_file():
            continue
        normalized = target.relative_to(wd)
        if _is_noise_path(normalized):
            continue
        entries.append(normalized)
    entries.sort(key=_deliverable_rank)
    return [str(path).replace("\\", "/") for path in entries]


def deliverable_kind(execution_id: str) -> str:
    """Classify the primary deliverable so the chat UI knows how to present it:
    'web' (open in the right-side live preview), 'pdf'/'image'/'text' (render inline
    in chat), or 'file' (download). '' when there is nothing to show."""
    entry = deliverable_entry(execution_id)
    if not entry:
        return ""
    ext = Path(entry).suffix.lstrip(".").lower()
    if ext in ("html", "htm"):
        return "web"
    if ext == "pdf":
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "gif", "svg", "webp"):
        return "image"
    if ext in ("md", "txt", "csv", "json", "log", "rst"):
        return "text"
    return "file"


def _safe_id(execution_id: str) -> str:
    """Same sanitization _ensure_task_workspace uses to name the dir."""
    return "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_")


def _workspace_dir(execution_id: str) -> Path | None:
    safe = _safe_id(execution_id)
    if not safe:
        return None
    base = _WORKSPACES_BASE.resolve()
    target = (base / safe).resolve()
    # Containment guard: target must be directly under the workspaces base.
    if target.parent != base or not target.is_dir():
        return None
    return target


def deliverable_entry(execution_id: str) -> str | None:
    """Return the relative entry filename for a workspace, or None if it's empty.

    Every produced file gets an openable URL — not just playable HTML. A web entry
    (index/game/main .html) is preferred for the one-click "Play"; otherwise the
    shallowest produced file is served so the user can open/download a .txt, .pdf,
    .csv, .png, etc. instead of being shown a dead text path.
    """
    wd = _workspace_dir(execution_id)
    if wd is None:
        return None
    all_files = [p for p in wd.rglob("*") if p.is_file()]
    if not all_files:
        return None
    # Drop obvious noise: true dotfiles (.DS_Store, .gitignore) and files under known
    # junk dirs (.git, node_modules, ...). A real deliverable in a non-junk subdir
    # (e.g. a build output under dist/ or .next/) is KEPT, ranked below flat output.
    # But if filtering leaves nothing, fall back to all files so a successful build is
    # never reported as "nothing to show". (Adversarial review 2026-06-17.)
    files = [p for p in all_files if not _is_noise_path(p.relative_to(wd))] or all_files
    recorded = _recorded_artifact_entries(execution_id, wd)
    if recorded:
        return recorded[0]
    # 1) Preferred playable web entry, matched case-insensitively so Linux CI and the
    #    owner's Windows box agree (a worker that wrote "Index.html" must still resolve).
    top_level = {p.name.lower(): p.name for p in wd.iterdir() if p.is_file()}
    for name in _ENTRY_PREFERENCES:
        if name in top_level:
            return top_level[name]
    # 2) The real deliverable: rank produced files so the user's actual output (a PDF,
    #    an image, a doc, a web page) wins over the build script that made it.
    files.sort(key=lambda p: _deliverable_rank(p.relative_to(wd)))
    return str(files[0].relative_to(wd)).replace("\\", "/")


# Runs before any deliverable script. If localStorage/sessionStorage are unavailable
# (opaque-origin sandbox throws on access), replace them with an in-memory store so the
# app doesn't crash on init. Only activates when the real API is broken — a normal
# context keeps its own storage. No host-data access; the sandbox is unchanged.
_STORAGE_SHIM = (
    "<script>(function(){function S(){var s={};return{getItem:function(k){"
    "return Object.prototype.hasOwnProperty.call(s,k)?s[k]:null;},"
    "setItem:function(k,v){s[k]=String(v);},removeItem:function(k){delete s[k];},"
    "clear:function(){s={};},key:function(i){return Object.keys(s)[i]||null;},"
    "get length(){return Object.keys(s).length;}};}function fix(n){try{window[n].getItem('__t');}"
    "catch(e){try{Object.defineProperty(window,n,{value:S(),configurable:true});}catch(_){}}}"
    "fix('localStorage');fix('sessionStorage');})();</script>"
)
_FAVICON_SHIM = (
    '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
    "viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='24' fill='%238b8cff'/%3E"
    "%3Ctext x='50' y='72' text-anchor='middle' font-family='sans-serif' font-size='64' "
    "font-weight='700' fill='white'%3ET%3C/text%3E%3C/svg%3E\">"
)
_HEAD_SHIM = _FAVICON_SHIM + _STORAGE_SHIM


def _inject_storage_shim(html: str) -> str:
    """Insert the storage shim as the FIRST thing in the document so it runs before any
    of the deliverable's own scripts."""
    lower = html.lower()
    head = lower.find("<head")
    if head != -1:
        close = lower.find(">", head)
        if close != -1:
            return html[: close + 1] + _HEAD_SHIM + html[close + 1 :]
    htmltag = lower.find("<html")
    if htmltag != -1:
        close = lower.find(">", htmltag)
        if close != -1:
            return html[: close + 1] + _HEAD_SHIM + html[close + 1 :]
    return _HEAD_SHIM + html


def deliverable_url(execution_id: str) -> str:
    """Public URL for the workspace entry, or "" if there's nothing playable."""
    entry = deliverable_entry(execution_id)
    if not entry:
        return ""
    return f"/deliverable/{_safe_id(execution_id)}/{entry}"


def _is_loopback(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    host = peer[0] if isinstance(peer, tuple) and peer else ""
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class _PreviewGrant:
    capability: str
    subject_key: str
    workspace: Path
    entry: str
    allowed_files: frozenset[str] | None
    expires_at: float
    runner: web.AppRunner
    port: int
    cleanup_task: asyncio.Task[None] | None = None


class DeliverablePreviewService:
    """Preview-only loopback origin for untrusted generated web applications."""

    def __init__(
        self,
        *,
        ttl_seconds: int = _PREVIEW_CAPABILITY_TTL_SECONDS,
        max_grants: int = _MAX_ACTIVE_PREVIEW_GRANTS,
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._max_grants = max(1, int(max_grants))
        self._grants: dict[str, _PreviewGrant] = {}
        self._subject_capabilities: dict[str, str] = {}
        self._main_origin = ""
        self._lock = asyncio.Lock()

    def configure(self, *, main_origin: str) -> None:
        self._main_origin = str(main_origin or "").rstrip("/")

    def is_live_capability(self, capability: str) -> bool:
        """True while a capability still authorises preview requests.

        Preview cookies are set for the whole of 127.0.0.1, so they reach the
        main server too, where they accumulate until they overflow its header
        limit. That server sweeps them, and asks here first: a capability that is
        still granted belongs to a preview that may yet request its stylesheet
        or script, and expiring it mid-load would break multi-file apps.
        """
        grant = self._grants.get(str(capability or ""))
        return grant is not None and grant.expires_at > time.time()

    async def stop(self) -> None:
        async with self._lock:
            grants = list(self._grants.values())
            self._grants.clear()
            self._subject_capabilities.clear()
        tasks = [grant.cleanup_task for grant in grants if grant.cleanup_task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for grant in grants:
            await grant.runner.cleanup()

    async def preview_url(self, execution_id: str, tail: str) -> str:
        safe_execution_id = _safe_id(execution_id)
        workspace = _workspace_dir(safe_execution_id)
        if workspace is None:
            raise FileNotFoundError("deliverable workspace is unavailable")
        return await self.preview_directory_url(
            subject_id=f"task:{safe_execution_id}",
            workspace=workspace,
            tail=tail,
        )

    async def preview_directory_url(
        self,
        *,
        subject_id: str,
        workspace: Path,
        tail: str,
        allowed_files: set[str] | frozenset[str] | None = None,
    ) -> str:
        """Create an isolated preview for a directory and optional file allowlist."""
        if not self._main_origin:
            raise RuntimeError("deliverable preview service is not configured")
        root = Path(workspace).resolve()
        if not root.is_dir():
            raise FileNotFoundError("deliverable workspace is unavailable")
        entry = str(Path(str(tail or "").replace("\\", "/")).as_posix()).lstrip("/")
        allowed = self._normalize_allowed_files(allowed_files)
        target = self._target_path(root, entry, allowed)
        if not target.is_file():
            raise FileNotFoundError("deliverable preview entry is unavailable")
        subject_key = f"{subject_id}\0{root}"
        now = time.time()
        async with self._lock:
            await self._drop_expired(now)
            capability = self._subject_capabilities.get(subject_key, "")
            grant = self._grants.get(capability)
            if grant is not None and grant.expires_at > now and grant.workspace == root:
                # Same project, so keep the origin and refresh what it may serve.
                # Replacing the grant here tore down a runner that open frames
                # were still using: a build finishing, or the conversation being
                # refetched, silently killed the port the game was loaded from
                # and every preview on screen collapsed to a network error. The
                # request handlers read these fields per request, so updating
                # them in place takes effect immediately.
                grant.allowed_files = allowed
                grant.entry = entry
            elif grant is None or grant.expires_at <= now or grant.workspace != root:
                if grant is not None:
                    await self._remove_grant(grant)
                while len(self._grants) >= self._max_grants:
                    oldest = min(self._grants.values(), key=lambda item: item.expires_at)
                    await self._remove_grant(oldest)
                grant = await self._start_grant(
                    subject_key=subject_key,
                    workspace=root,
                    entry=entry,
                    allowed_files=allowed,
                    expires_at=now + self._ttl_seconds,
                )
                capability = grant.capability
                self._grants[capability] = grant
                self._subject_capabilities[subject_key] = capability
                grant.cleanup_task = asyncio.create_task(
                    self._expire_grant(capability, grant.expires_at),
                    name=f"thomas-preview-expiry-{capability[:10]}",
                )
        safe_tail = "/".join(quote(part, safe="") for part in Path(tail).parts)
        return f"http://127.0.0.1:{grant.port}/__enter/{capability}/{safe_tail}"

    @staticmethod
    def _normalize_allowed_files(
        allowed_files: set[str] | frozenset[str] | None,
    ) -> frozenset[str] | None:
        if allowed_files is None:
            return None
        normalized: set[str] = set()
        for raw in allowed_files:
            rel = Path(str(raw or "").replace("\\", "/").lstrip("/"))
            if not rel.is_absolute() and rel.parts and ".." not in rel.parts:
                normalized.add(rel.as_posix())
        return frozenset(normalized)

    async def _drop_expired(self, now: float) -> None:
        expired = [grant for grant in self._grants.values() if grant.expires_at <= now]
        for grant in expired:
            await self._remove_grant(grant)

    async def _remove_grant(self, grant: _PreviewGrant) -> None:
        self._grants.pop(grant.capability, None)
        if self._subject_capabilities.get(grant.subject_key) == grant.capability:
            self._subject_capabilities.pop(grant.subject_key, None)
        cleanup_task = grant.cleanup_task
        if cleanup_task is not None and cleanup_task is not asyncio.current_task() and not cleanup_task.done():
            cleanup_task.cancel()
        await grant.runner.cleanup()

    async def _expire_grant(self, capability: str, expires_at: float) -> None:
        try:
            await asyncio.sleep(max(0.0, expires_at - time.time()))
            async with self._lock:
                grant = self._grants.get(capability)
                if grant is not None and grant.expires_at <= time.time():
                    await self._remove_grant(grant)
        except asyncio.CancelledError:
            return

    async def _start_grant(
        self,
        *,
        subject_key: str,
        workspace: Path,
        entry: str,
        allowed_files: frozenset[str] | None,
        expires_at: float,
    ) -> _PreviewGrant:
        capability = base64.b32encode(secrets.token_bytes(32)).decode("ascii").rstrip("=").lower()
        cookie_name = f"thomas_preview_{capability}"
        grant_ref: dict[str, _PreviewGrant] = {}
        preview_app = web.Application()

        async def enter(request: web.Request) -> web.StreamResponse:
            grant = grant_ref["grant"]
            if not _is_loopback(request) or time.time() >= grant.expires_at:
                raise web.HTTPNotFound(text="preview capability expired or invalid")
            supplied = str(request.match_info.get("capability", "") or "")
            if not _PREVIEW_CAPABILITY_RE.fullmatch(supplied) or not secrets.compare_digest(supplied, capability):
                raise web.HTTPNotFound(text="preview capability expired or invalid")
            tail = self._safe_tail(request, grant)
            self._target(grant, tail)
            response = web.HTTPFound(location="/" + "/".join(quote(part, safe="") for part in Path(tail).parts))
            response.headers.update(
                {
                    "Cache-Control": "private, no-store, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Referrer-Policy": "no-referrer",
                    "Clear-Site-Data": '"cache", "storage"',
                    "X-Content-Type-Options": "nosniff",
                }
            )
            response.set_cookie(
                cookie_name,
                "1",
                max_age=self._ttl_seconds,
                httponly=True,
                samesite="Strict",
                path="/",
            )
            raise response

        async def serve(request: web.Request) -> web.StreamResponse:
            grant = grant_ref["grant"]
            if not _is_loopback(request) or time.time() >= grant.expires_at:
                raise web.HTTPNotFound(text="preview capability expired or invalid")
            if (
                str(request.headers.get("Service-Worker") or "").strip().lower() == "script"
                or str(request.headers.get("Sec-Fetch-Dest") or "").strip().lower() == "serviceworker"
            ):
                raise web.HTTPNotFound(text="preview service workers are disabled")
            if not secrets.compare_digest(str(request.cookies.get(cookie_name) or ""), "1"):
                raise web.HTTPNotFound(text="preview capability required")
            target = self._target(grant, self._safe_tail(request, grant))
            response = self._file_response(target)
            self._apply_headers(response)
            return response

        preview_app.router.add_get("/__enter/{capability}/{tail:.*}", enter)
        preview_app.router.add_get("/{tail:.*}", serve)
        runner = web.AppRunner(preview_app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host="127.0.0.1", port=0)
        try:
            await site.start()
            sockets = list(getattr(getattr(site, "_server", None), "sockets", ()) or ())
            if not sockets:
                raise RuntimeError("preview server did not expose a listening socket")
            grant = _PreviewGrant(
                capability=capability,
                subject_key=subject_key,
                workspace=workspace,
                entry=entry,
                allowed_files=allowed_files,
                expires_at=expires_at,
                runner=runner,
                port=int(sockets[0].getsockname()[1]),
            )
            grant_ref["grant"] = grant
            return grant
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            await runner.cleanup()
            raise

    @staticmethod
    def _safe_tail(request: web.Request, grant: _PreviewGrant) -> str:
        return str(request.match_info.get("tail", "") or grant.entry).replace("\\", "/").lstrip("/")

    @staticmethod
    def _target(grant: _PreviewGrant, tail: str) -> Path:
        return DeliverablePreviewService._target_path(grant.workspace, tail, grant.allowed_files)

    @staticmethod
    def _target_path(workspace: Path, tail: str, allowed_files: frozenset[str] | None) -> Path:
        rel = Path(tail)
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            raise web.HTTPNotFound(text="preview file not found")
        normalized = rel.as_posix()
        if allowed_files is not None and normalized not in allowed_files:
            raise web.HTTPNotFound(text="preview file not found")
        target = (workspace / rel).resolve()
        if not target.is_file() or not (target == workspace or workspace in target.parents):
            raise web.HTTPNotFound(text="preview file not found")
        return target

    def _file_response(self, target: Path) -> web.StreamResponse:
        if target.suffix.lower() in {".html", ".htm"}:
            try:
                html = target.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise web.HTTPNotFound(text="preview file not found") from exc
            return web.Response(body=_inject_storage_shim(html).encode("utf-8"), content_type="text/html")
        return web.FileResponse(target)

    def _apply_headers(self, response: web.StreamResponse) -> None:
        # 'self' as well as the UI, because a generated app is allowed to frame
        # its OWN pages: a shell index.html embedding the game it built is an
        # ancestor chain of [preview origin, UI], and frame-ancestors is checked
        # against every entry in that chain, not just the immediate parent.
        # Naming only the UI meant the shell loaded and the game inside it was
        # refused -- indistinguishable from the game being broken. Each grant
        # listens on its own ephemeral port, so 'self' is one app's own origin;
        # it grants nothing to another preview or to a remote page.
        frame_ancestors = f"{self._main_origin} 'self'" if self._main_origin else "'none'"
        # 'unsafe-eval' matches what the browser smoke already allows when it
        # CERTIFIES these pages. Without it the viewer was stricter than the
        # checker, so a page could pass every verification and still be broken
        # the moment the owner opened it -- with nothing to report, because both
        # halves did exactly what they were configured to do.
        #
        # Measured, not theorised: the owner asked for a calculator, Thomas
        # built one, verification returned `completed`, and `12 + 8` produced
        # `Error` on screen. `Function('return (12+8)')()` -- the ordinary way a
        # calculator evaluates a typed expression -- threw `EvalError:
        # Evaluating a string as JavaScript violates the following Content
        # Security Policy directive`, and the page's own catch turned that into
        # `Error`. Proven by injecting an inline <script> into the live preview,
        # which CSP governs; evaluating the same call from devtools reported
        # success, because the devtools console is not subject to CSP.
        #
        # It costs nothing to allow. 'unsafe-inline' is already granted here, so
        # a hostile page can run whatever JavaScript it likes by writing it out
        # directly; refusing to evaluate a STRING removes no capability it does
        # not already have. The directives that actually contain a generated
        # page -- connect-src 'self', object-src 'none', base-uri 'none',
        # form-action 'self', and the sandbox -- are untouched.
        # `allow-modals` for the same reason, found the same way. The owner asked
        # for a habit tracker with a Reset button; Thomas built one whose handler
        # reads `if (!confirm("Clear all habit checkoffs?")) return;`. Clicking
        # Reset did nothing at all -- no dialog, no error, no console message.
        # Without `allow-modals` the sandbox makes `confirm()` return false and
        # show nothing, so the guard clause returns early every time. Measured on
        # the live page: 2 boxes checked -> 2 after clicking Reset; with
        # `window.confirm` forced to true, the same click cleared them. The page's
        # logic was correct throughout.
        #
        # This is a CSP `sandbox` directive, so it applied to the top-level
        # document too -- "open in a new tab" produced the same dead button, not
        # just the framed preview.
        #
        # Granting it here raises the CEILING only. The effective sandbox is the
        # intersection with each iframe's own `sandbox` attribute, so the
        # decorative surfaces (transcript thumbnail, drawer shot -- both
        # `tabindex="-1"` and non-interactive) still refuse modals and cannot pop
        # a dialog out of a 168px picture. Only the viewer stage, which the owner
        # actually clicks, opts in.
        #
        # It removes no containment: a hostile page can already draw a convincing
        # fake dialog in HTML, and can already hang its own frame with a loop.
        # What it removes is a whole class of generated app -- anything with a
        # confirm-before-delete -- being silently dead on the one button that
        # matters. Guard: tests/test_generated_apps_can_ask_before_they_delete.py
        #
        # `allow-pointer-lock` is the third instance of the same shape, and it is
        # the one that makes first-person games unplayable. From a game Thomas
        # built on 2026-07-30 (~/.thomas/projects/Code task 2026-07-30 1137/game.js):
        #
        #     if (document.pointerLockElement !== canvas) canvas.requestPointerLock?.();
        #     ...
        #     addEventListener("mousemove", (event) => {
        #       if (... && document.pointerLockElement === canvas && state.player)
        #         state.player.angle += event.movementX * .0023;
        #     });
        #
        # Mouse-look is gated entirely on `pointerLockElement === canvas`. Without
        # the token that is never true, so the player cannot TURN -- an FPS where
        # you may only shoot straight ahead. No error is raised; the request is
        # simply refused. Two of the owner's own deliverables call it
        # (that game.js and code_scratch/blocktown-84.html).
        #
        # `allow-downloads` is the fourth, and the only one caught on FRESH
        # output: Thomas was asked for a to-do list with an Export CSV button and
        # built a correct one. Through this route the button did nothing at all;
        # the identical bytes served from a plain local http server downloaded
        # `tasks-2026-07-30.csv` immediately. Same browser, same clicks, only the
        # sandbox differs -- which is what makes it Thomas's defect rather than
        # the model's. Any generated export/save/report button was dead.
        #
        # `allow-popups` is deliberately NOT granted: zero deliverables call
        # `window.open(`, so there is no defect to fix and no reason to widen.
        # Census across 442 generated files: modals 9, pointer lock 3, downloads
        # 3, popups 0.
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-forms allow-same-origin allow-modals "
            "allow-pointer-lock allow-downloads; "
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
            "style-src 'self' 'unsafe-inline' data:; img-src 'self' data: blob:; "
            "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'self'; "
            "worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; "
            f"frame-ancestors {frame_ancestors}"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Content-Type-Options"] = "nosniff"


async def handle_deliverable(request: web.Request) -> web.StreamResponse:
    # Worker output is untrusted generated content; only ever serve it to the local UI.
    if not _is_loopback(request):
        raise web.HTTPForbidden(text="Deliverables are served on loopback only.")
    execution_id = request.match_info.get("execution_id", "")
    wd = _workspace_dir(execution_id)
    if wd is None:
        raise web.HTTPNotFound(text="No deliverable for this task.")
    tail = request.match_info.get("tail", "") or (deliverable_entry(execution_id) or "")
    if not tail:
        raise web.HTTPNotFound(text="No playable file in this deliverable.")
    target = (wd / tail).resolve()
    # Path-traversal guard: resolved file must stay inside the workspace dir.
    if not (target == wd or wd in target.parents) or not target.is_file():
        raise web.HTTPNotFound(text="File not found in deliverable.")
    query = getattr(request, "query", {})
    download = str(query.get("download") or "").strip().lower() in {"1", "true", "yes"}
    # Worker output is UNTRUSTED and served same-origin with the chat UI. Force it into
    # a sandbox (opaque origin) at the RESPONSE layer so it can never reach the host
    # app's DOM/cookies/localStorage regardless of how a client frames it (preview
    # pane, inline viewer, or a download-then-open). `allow-scripts` keeps games and the
    # PDF viewer working; we deliberately omit `allow-same-origin`. This is the
    # call-site-independent backstop to the iframe `sandbox` attributes in the chat UI,
    # which are otherwise a single point of failure. (Adversarial review 2026-06-17.)
    #
    # NOT updated with `allow-modals` / `allow-pointer-lock`, and that is a known
    # gap rather than a decision that this route is different. The preview service
    # above got both because generated apps demonstrably need them: a
    # confirm-before-delete button that never asks, and an FPS whose mouse-look is
    # gated on `pointerLockElement`. The same generated files would hit the same
    # walls here.
    #
    # It is left alone because nothing in the unified shell requests this route --
    # `grep -rn "/deliverable/" thomas/server/web/js/ chat.html` finds nothing --
    # so there is no surface to verify the change on, and shipping an unverified
    # header change on a security boundary is worse than an inconsistency that is
    # written down. If a caller appears, mirror the tokens above and verify with
    # tests/test_generated_apps_can_ask_before_they_delete.py.
    csp = "sandbox allow-scripts allow-forms"
    # The opaque-origin sandbox makes `localStorage`/`sessionStorage` THROW on access.
    # A huge fraction of generated games/apps use them (e.g. a high-score), and the
    # uncaught SecurityError aborts their init — the page renders but is dead on the
    # first interaction. Inject a tiny in-memory storage shim that ONLY activates when
    # the real one is unavailable, so those apps actually run WITHOUT weakening the
    # sandbox (no allow-same-origin; the shim never touches host data). HTML only.
    if not download and target.suffix.lower() in (".html", ".htm"):
        try:
            html = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            html = None
        if html is not None:
            response = web.Response(body=_inject_storage_shim(html).encode("utf-8"), content_type="text/html")
            response.headers["Content-Security-Policy"] = csp
            return response
    response = web.FileResponse(target)
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Content-Type-Options"] = "nosniff"
    if download:
        filename = re.sub(r"[^A-Za-z0-9._ -]", "_", target.name).strip() or "thomas-result"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def register_deliverable_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
) -> DeliverablePreviewService:
    """Register deliverables behind the server's configured access-mode guard."""
    if not callable(require_api_access):
        raise TypeError("require_api_access must be callable")
    preview_service = DeliverablePreviewService()
    app[APP_DELIVERABLE_PREVIEW_SERVICE] = preview_service

    async def _preview_redirect(request: web.Request) -> web.HTTPFound | None:
        query = getattr(request, "query", {})
        if str(query.get("download") or "").strip().lower() in {"1", "true", "yes"}:
            return None
        execution_id = str(request.match_info.get("execution_id", "") or "")
        wd = _workspace_dir(execution_id)
        if wd is None:
            return None
        tail = str(request.match_info.get("tail", "") or (deliverable_entry(execution_id) or ""))
        target = (wd / tail).resolve()
        if (
            target.suffix.lower() not in {".html", ".htm"}
            or not target.is_file()
            or not (target == wd or wd in target.parents)
        ):
            return None
        try:
            location = await preview_service.preview_url(execution_id, tail)
        except (FileNotFoundError, RuntimeError):
            raise web.HTTPServiceUnavailable(text="Generated preview service is not ready") from None
        return web.HTTPFound(
            location=location,
            headers={
                "Cache-Control": "private, no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    async def guarded_deliverable(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        redirect = await _preview_redirect(request)
        if redirect is not None:
            raise redirect
        return await handle_deliverable(request)

    app.router.add_get("/deliverable/{execution_id}", guarded_deliverable)
    app.router.add_get("/deliverable/{execution_id}/{tail:.*}", guarded_deliverable)
    return preview_service
