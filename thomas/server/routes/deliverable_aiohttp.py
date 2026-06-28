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

import ipaddress
from pathlib import Path

from aiohttp import web

from thomas.core import task_bot_runtime

# Must match thomas/server/chat_delegation.py::_ensure_task_workspace.
_WORKSPACES_BASE = Path.home() / ".thomas" / "workspaces"
_ENTRY_PREFERENCES = ("index.html", "game.html", "main.html")

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


def _inject_storage_shim(html: str) -> str:
    """Insert the storage shim as the FIRST thing in the document so it runs before any
    of the deliverable's own scripts."""
    lower = html.lower()
    head = lower.find("<head")
    if head != -1:
        close = lower.find(">", head)
        if close != -1:
            return html[: close + 1] + _STORAGE_SHIM + html[close + 1 :]
    htmltag = lower.find("<html")
    if htmltag != -1:
        close = lower.find(">", htmltag)
        if close != -1:
            return html[: close + 1] + _STORAGE_SHIM + html[close + 1 :]
    return _STORAGE_SHIM + html


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
    # Worker output is UNTRUSTED and served same-origin with the chat UI. Force it into
    # a sandbox (opaque origin) at the RESPONSE layer so it can never reach the host
    # app's DOM/cookies/localStorage regardless of how a client frames it (preview
    # pane, inline viewer, or a download-then-open). `allow-scripts` keeps games and the
    # PDF viewer working; we deliberately omit `allow-same-origin`. This is the
    # call-site-independent backstop to the iframe `sandbox` attributes in the chat UI,
    # which are otherwise a single point of failure. (Adversarial review 2026-06-17.)
    csp = "sandbox allow-scripts allow-forms"
    # The opaque-origin sandbox makes `localStorage`/`sessionStorage` THROW on access.
    # A huge fraction of generated games/apps use them (e.g. a high-score), and the
    # uncaught SecurityError aborts their init — the page renders but is dead on the
    # first interaction. Inject a tiny in-memory storage shim that ONLY activates when
    # the real one is unavailable, so those apps actually run WITHOUT weakening the
    # sandbox (no allow-same-origin; the shim never touches host data). HTML only.
    if target.suffix.lower() in (".html", ".htm"):
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
    return response


def register_deliverable_routes(app: web.Application) -> None:
    app.router.add_get("/deliverable/{execution_id}", handle_deliverable)
    app.router.add_get("/deliverable/{execution_id}/{tail:.*}", handle_deliverable)
