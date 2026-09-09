"""What a page Thomas generated may be handed from its own folder (2026-09-05).

One allowlist for every place that serves a workspace to a browser: the
offline smoke check and the playtest tool. It is a security boundary --
generated code runs against it -- so it stays a list of formats a browser
PARSES rather than executes, plus the scripts and styles the page ships.
Source, secrets, dotfiles and databases stay refused; widening this to
"anything in the folder" would turn a verification run into a way to read a
project's private files out of a page Thomas just wrote.

The data formats are here on purpose. A page that fetched a ``sales.csv``
beside it once got a 404 from the smoke server and honestly reported itself
blank, and the build then spent its whole fix budget repairing a page that was
already right.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlsplit

WEB_ASSET_SUFFIXES = frozenset(
    {
        ".avif",
        ".css",
        ".csv",
        ".gif",
        ".html",
        ".htm",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".png",
        ".svg",
        ".tsv",
        ".txt",
        ".wasm",
        ".webp",
        ".woff",
        ".woff2",
        ".xml",
    }
)
MAX_ASSET_BYTES = 16 * 1024 * 1024


def safe_web_path(root: Path, raw_path: str) -> Path | None:
    """The file under ``root`` that a request path may be served from, or None.

    Refuses anything outside the root, any dotfile segment, any suffix outside
    the allowlist, and anything over the size cap. ``raw_path`` may be a bare
    path or a full URL; only its path is used.
    """
    relative = unquote(urlsplit(raw_path).path).lstrip("/").replace("\\", "/")
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part in {".", ".."} or part.startswith(".") for part in parts):
        return None
    try:
        base = root.resolve()
        target = (base / Path(*parts)).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(base) or not target.is_file():
        return None
    if target.suffix.lower() not in WEB_ASSET_SUFFIXES:
        return None
    try:
        if target.stat().st_size > MAX_ASSET_BYTES:
            return None
    except OSError:
        return None
    return target
