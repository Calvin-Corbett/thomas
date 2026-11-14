"""One version per front-end file on the chat page, so a change re-downloads only the file that changed.

The page used to stamp every script and stylesheet with one fingerprint of the whole front end, so any edit made the
browser fetch about 110 files again (3.4 to 5.2 s measured cold, against 0.6 s warm). Each file now carries a hash of its
own bytes. Caching stays safe the same way it did: a file's URL changes whenever, and only when, that file does. The
module scripts spliced in by ``app_middleware_helpers._module_stamp`` already worked this way.

Only the chat page uses this. Pages whose loaders reuse one version for many files (the classic page's runtime modules)
keep the whole-front-end fingerprint.
"""

from __future__ import annotations

import re
import threading
from hashlib import sha1
from pathlib import Path

# The browser-style window chrome (title bar, tabs, bookmarks) is loaded by script from js/workspace_shell.js, which
# cannot read its own tag's version off a page link any more. The page hands it these versions as a map instead.
CHROME_FILES = (
    "css/browser_shell.css",
    "js/browser_shell_panel.js",
    "js/browser_shell_desktop.js",
    "js/browser_shell_keys.js",
    "js/browser_shell_search.js",
    "js/browser_shell_web.js",
    "js/browser_shell_docs_policy.js",
    "js/browser_shell_docs.js",
    "js/browser_shell.js",
)

_lock = threading.Lock()
_seen: dict[str, tuple[int, int, str]] = {}


def file_stamp(web_dir: Path, relative: str) -> str | None:
    """A 12-character hash of the file's bytes, re-read only when its modified time or size changes."""
    path = web_dir / relative
    try:
        stat = path.stat()
    except OSError:
        return None
    with _lock:
        known = _seen.get(relative)
    if known and known[0] == stat.st_mtime_ns and known[1] == stat.st_size:
        return known[2]
    try:
        stamp = sha1(path.read_bytes(), usedforsecurity=False).hexdigest()[:12]
    except OSError:
        return None
    with _lock:
        _seen[relative] = (stat.st_mtime_ns, stat.st_size, stamp)
    return stamp


def chrome_stamps(web_dir: Path) -> dict[str, str]:
    """``{relative path: stamp}`` for the window chrome's files that exist."""
    found = {rel: file_stamp(web_dir, rel) for rel in CHROME_FILES}
    return {rel: stamp for rel, stamp in found.items() if stamp}


def stamp_each_asset(html: str, web_dir: Path, page_stamp: str) -> str:
    """Replace the page-wide ``?v=<page_stamp>`` on each /static js or css URL with that file's own stamp.

    A file that cannot be read keeps the page-wide stamp, which only costs it one extra download after any change."""
    pattern = re.compile(r"(/static/((?:js|css)/[A-Za-z0-9_./-]+))\?v=" + re.escape(page_stamp))

    def swap(match: re.Match[str]) -> str:
        stamp = file_stamp(web_dir, match.group(2))
        return f"{match.group(1)}?v={stamp}" if stamp else match.group(0)

    return pattern.sub(swap, html)
