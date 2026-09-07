"""What a finished workspace offers as its deliverable, and which files a page may load.

Split out of ``deliverable_aiohttp.py`` (2026-09-05) so that module stays under the
size guard: the ranking that puts the person's real output before build scripts,
the junk-dir filter, the workspace lookup, and the package-asset rule that lets a
page import from ``node_modules``. Pure functions over paths and the run record;
no aiohttp here.
"""

from __future__ import annotations

from pathlib import Path

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


# Third-party packages a page links (a Vite project's node_modules) are web
# assets, not the owner's secrets. The preview allowlist never names them (the
# artifact listing treats node_modules as noise), so a game importing three.js
# got a 404 for the module, its script never ran, and ENTER WORLD could do
# nothing while the same files served plainly played (Calvin's Minecraft,
# 2026-09-05). Serve them by extension; dotfiles, source and manifests of
# other languages stay refused, and .git and the rest of the root stay behind
# the allowlist.
_PACKAGE_WEB_ASSET_EXTENSIONS = frozenset(
    {
        "js",
        "mjs",
        "cjs",
        "css",
        "map",
        "json",
        "wasm",
        "svg",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "avif",
        "ico",
        "woff",
        "woff2",
        "ttf",
        "otf",
        "eot",
        "glb",
        "gltf",
        "bin",
        "hdr",
        "ktx2",
        "mp3",
        "ogg",
        "wav",
        "mp4",
        "webm",
        "txt",
        "md",
        "html",
    }
)


def _is_package_web_asset(rel: Path) -> bool:
    """A web-asset file under node_modules that a page may import or fetch."""
    parts = rel.parts
    if len(parts) < 3 or parts[0] != "node_modules":
        return False
    if any(part.startswith(".") for part in parts):
        return False
    return rel.suffix.lstrip(".").lower() in _PACKAGE_WEB_ASSET_EXTENSIONS


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


__all__ = [
    "_WORKSPACES_BASE",
    "_ENTRY_PREFERENCES",
    "_SCRIPT_EXTS",
    "_BUILD_FILENAMES",
    "_DELIVERABLE_PRIORITY",
    "_JUNK_DIRS",
    "_PACKAGE_WEB_ASSET_EXTENSIONS",
    "_is_package_web_asset",
    "_is_noise_path",
    "_deliverable_rank",
    "_recorded_artifact_entries",
    "deliverable_kind",
    "_safe_id",
    "_workspace_dir",
    "deliverable_entry",
]
