"""Deciding whether a browser URL is the agent's own output, and page-URL basics.

An agent that has just written `index.html` needs to look at it. Refusing that
cost one measured run eleven minutes and ~390 MB: `browser.open` rejected
`file://`, so the worker shelled out to install a browser the tool already had
five builds of, and stood up its own HTTP server to reach a file on its own disk.

The shared SSRF guard is not the place to fix that. ``check_url`` is what
``web.fetch`` and ``eng.web_extract`` rely on; teaching it to accept ``file://``
would let any agent read any local file and render it on a page. The owner's
standing direction on the browser is "no weakening these to make something
easier", so this does not weaken it -- it adds one narrow, separately-tested
allowance beside it.

The rule, in full: a ``file://`` URL is permitted only when a workspace was
configured for this run AND the path, resolved through symlinks, really exists
inside that workspace. Everything else -- no workspace, a path outside it, a
link pointing out of it, a UNC host, a file that is not there -- is refused and
falls through to the ordinary guard.

The rest of this module is the session-free helper layer that moved out of
``browser.py`` on 2026-09-21, when that file sat at 1001 lines and nothing in it
could be changed until some of it left.
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

try:  # Playwright is optional; error formatting still works without it.
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - only on installs without playwright

    class PlaywrightTimeoutError(Exception):  # type: ignore[no-redef]
        """Stand-in so error formatting works when playwright is absent."""


# A file:// URL may name a host, and then it is a network fetch (UNC), not a
# local read. Only these mean "this machine".
_LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1"})

_MAX_TEXT_CHARS = 8000


def workspace_file_url(url: str, workspace: str | Path | None) -> Path | None:
    """Return the real path if *url* is a file inside *workspace*, else ``None``.

    ``None`` means "not my business, apply the normal policy" -- it is returned
    both for a non-``file://`` URL and for a ``file://`` URL that fails the
    confinement check, so a refusal can never be mistaken for an allowance.
    """
    if not workspace:
        return None
    try:
        parsed = urlparse(str(url or ""))
    except (ValueError, AttributeError):
        return None
    if parsed.scheme != "file":
        return None
    if (parsed.netloc or "").strip().lower() not in _LOCAL_HOSTS:
        return None

    try:
        candidate = Path(url2pathname(unquote(parsed.path)))
        # strict=True: the file has to exist. resolve() also follows symlinks,
        # and that must happen BEFORE the containment test or a link planted in
        # the workspace would read as inside it.
        real = candidate.resolve(strict=True)
        root = Path(workspace).resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        return None

    if real == root or root in real.parents:
        return real
    return None


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        return u
    return "https://" + u.lstrip("/")


def _looks_like_css_or_xpath(selector: str) -> bool:
    s = (selector or "").strip()
    if not s:
        return False
    # Playwright engine prefixes
    if re.match(r"^(css|xpath|text|id|data-test|data-testid)=", s):
        return True
    # XPath patterns
    if s.startswith("//") or s.startswith("(//"):
        return True
    # CSS-ish characters that usually indicate an actual selector
    if any(ch in s for ch in ("#", ".", "[", "]", ">", "+", "~", ":", "=", "*", "(", ")", ",")):
        return True
    # If it has spaces, could still be CSS, but in consumer flows it's often a label.
    # We'll treat plain words/phrases as "human" unless it clearly looks like CSS above.
    return False


def _normalize_selector(selector: str) -> str:
    s = (selector or "").strip()
    if not s:
        return s
    if re.match(r"^(css|xpath|text|id|data-test|data-testid)=", s):
        return s
    if s.startswith("//") or s.startswith("(//"):
        return f"xpath={s}"
    return s  # CSS


def _clean_text(text: str) -> str:
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = t.strip()
    if len(t) > _MAX_TEXT_CHARS:
        t = t[:_MAX_TEXT_CHARS].rstrip() + "…"
    return t


def _temp_screenshot_name() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"{int(time.time() * 1000) % 1_000_000:06d}"
    return f"thomas_screenshot_{ts}_{suffix}.png"


def _resolve_screenshot_path(path_in: str | None) -> str:
    if not path_in:
        p = Path(tempfile.gettempdir()) / _temp_screenshot_name()
        return str(p)

    p = Path(path_in).expanduser()
    try:
        p = p.resolve()
    except Exception:
        p = Path(str(p))

    if p.exists() and p.is_dir():
        p = p / _temp_screenshot_name()

    if p.suffix == "":
        p = p.with_suffix(".png")

    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _fmt_action_error(action: str, exc: Exception, selector: str | None = None) -> str:
    msg = str(exc).strip() if exc else ""
    if isinstance(exc, PlaywrightTimeoutError):
        return f"{action} timed out{f' for selector {selector!r}' if selector else ''}."
    return f"{action} failed{f' for selector {selector!r}' if selector else ''}: {msg or exc.__class__.__name__}"


def _fmt_nav_error(url: str, exc: Exception, timeout_ms: int) -> str:
    msg = str(exc).strip() if exc else ""
    upper = msg.upper()

    if isinstance(exc, PlaywrightTimeoutError):
        return f"Navigation timed out after {timeout_ms}ms: {url}"

    if "ERR_NAME_NOT_RESOLVED" in upper:
        return f"DNS error (domain not resolved) while navigating to {url}: {msg}"
    if "ERR_CONNECTION_REFUSED" in upper:
        return f"Connection refused while navigating to {url}: {msg}"
    if "ERR_CONNECTION_TIMED_OUT" in upper:
        return f"Connection timed out while navigating to {url}: {msg}"
    if "ERR_INTERNET_DISCONNECTED" in upper:
        return f"Internet disconnected while navigating to {url}: {msg}"
    if "ERR_TOO_MANY_REDIRECTS" in upper:
        return f"Too many redirects while navigating to {url}: {msg}"
    if "ERR_ABORTED" in upper:
        return f"Navigation aborted while navigating to {url}: {msg}"

    if "ERR_CERT" in upper or "CERTIFICATE" in upper or "SSL" in upper:
        return f"SSL/certificate error while navigating to {url}: {msg}"

    return f"Navigation error while navigating to {url}: {msg or exc.__class__.__name__}"
