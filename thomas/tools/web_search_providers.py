"""Web search provider implementations and HTTP utilities.

Contains:
  - Configuration loading
  - HTTP client management and retry logic
  - Request coalescing and caching
  - URL policy enforcement
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import sqlite3
import time
from collections import OrderedDict
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.tools.url_safety import check_url

# Defaults + public constants consumed by web_search.py
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_DDG_ENDPOINT = "https://api.duckduckgo.com/"
_DDG_HTML_ENDPOINT = "https://duckduckgo.com/html/"
_MIN_RESULTS = 1
_MAX_RESULTS = 10
_DEFAULT_TIMEOUT_S = 10.0
_DEFAULT_MAX_FETCH_CHARS = 8000
_DEFAULT_MAX_FETCH_BYTES = 2_000_000
_DEFAULT_RETRIES = 1
_DEFAULT_CACHE_TTL_S = 120
_DEFAULT_CACHE_MAX_ENTRIES = 256
_TOML_CACHE_TTL_S = 5.0
_TOML_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_isoish_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s2)
        return dt.isoformat()
    except ValueError:
        return s


def _hash_key(s: str) -> str:
    # stable small key for sqlite index
    import hashlib

    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


# --- TOML config --------------------------------------------------------------


def _get_toml_path() -> str:
    return os.environ.get("THOMAS_TOML_PATH", "thomas.toml")


def _load_toml() -> dict[str, Any]:
    global _TOML_CACHE
    now = time.time()
    ts, cached = _TOML_CACHE
    if cached is not None and (now - ts) < _TOML_CACHE_TTL_S:
        return cached

    path = _get_toml_path()
    try:
        try:
            import tomllib  # Python 3.11+
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}

    _TOML_CACHE = (now, data)
    return data


def _get_tool_cfg() -> dict[str, Any]:
    cfg = _load_toml()
    try:
        tools = cfg.get("tools") or {}
        ws = tools.get("web_search") or {}
        return ws if isinstance(ws, dict) else {}
    except (AttributeError, KeyError):
        return {}


def _cfg_bool(key: str, default: bool) -> bool:
    ws = _get_tool_cfg()
    v = ws.get(key, default)
    return bool(v)


def _cfg_int(key: str, default: int, lo: int, hi: int) -> int:
    ws = _get_tool_cfg()
    v = ws.get(key, default)
    try:
        i = int(v)
    except (ValueError, TypeError):
        i = default
    return _clamp_int(i, lo, hi)


def _cfg_str(key: str, default: str) -> str:
    ws = _get_tool_cfg()
    v = ws.get(key, default)
    s = str(v).strip() if v is not None else ""
    return s or default


def _get_brave_api_key() -> str | None:
    env_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    ws = _get_tool_cfg()
    key = ws.get("api_key")
    if key and str(key).strip():
        return str(key).strip()

    return None


def _get_timeout_s() -> float:
    ws = _get_tool_cfg()
    t = ws.get("timeout_s")
    try:
        v = float(t)
        if 1.0 <= v <= 60.0:
            return v
    except (ValueError, TypeError):
        pass
    return _DEFAULT_TIMEOUT_S


def _get_user_agent() -> str:
    return _cfg_str("user_agent", "Thomas/1.0 (+web)")


def _get_fetch_limits() -> tuple[int, int]:
    max_chars = _cfg_int("max_fetch_chars", _DEFAULT_MAX_FETCH_CHARS, 1000, 20000)
    max_bytes = _cfg_int("max_fetch_bytes", _DEFAULT_MAX_FETCH_BYTES, 100_000, 10_000_000)
    return max_chars, max_bytes


def _get_retries() -> int:
    return _cfg_int("retries", _DEFAULT_RETRIES, 0, 3)


def _get_cache_cfg() -> tuple[int, int]:
    ttl = _cfg_int("cache_ttl_s", _DEFAULT_CACHE_TTL_S, 5, 3600)
    mx = _cfg_int("cache_max_entries", _DEFAULT_CACHE_MAX_ENTRIES, 16, 2048)
    return ttl, mx


def _get_cache_db_path() -> str:
    # default path under runtime/cache
    ws = _get_tool_cfg()
    p = ws.get("cache_db_path")
    if p and str(p).strip():
        return str(p).strip()
    env_db = str(os.environ.get("THOMAS_WEB_SEARCH_CACHE_DB_PATH") or "").strip()
    if env_db:
        return env_db
    runtime_dir = str(os.environ.get("THOMAS_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        return os.path.join(runtime_dir, "cache", "web_tools_cache.sqlite3")
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return str((resolve_thomas_data_dir() / "runtime" / "cache" / "web_tools_cache.sqlite3").resolve())
    except Exception:
        pass
    return "runtime/cache/web_tools_cache.sqlite3"


def _get_host_policy() -> dict[str, Any]:
    ws = _get_tool_cfg()
    allow_private = ws.get("allow_private_network", True)
    allowed_hosts = ws.get("allowed_hosts", [])
    blocked_hosts = ws.get("blocked_hosts", [])

    def _norm_list(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip().lower() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [s.strip().lower() for s in v.split(",") if s.strip()]
        return []

    return {
        "allow_private_network": bool(allow_private),
        "allowed_hosts": _norm_list(allowed_hosts),
        "blocked_hosts": _norm_list(blocked_hosts),
    }


# --- URL canonicalization -----------------------------------------------------

_TRACKING_KEYS = {
    "gclid",
    "fbclid",
    "dclid",
    "msclkid",
    "igshid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_reader",
    "utm_name",
    "utm_referrer",
    "ref",
    "ref_src",
}


def _canonicalize_url(url: str) -> str:
    try:
        p = urlparse(url)
    except (ValueError, AttributeError):
        return url

    q = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        lk = k.lower()
        if lk in _TRACKING_KEYS or lk.startswith("utm_"):
            continue
        q.append((k, v))
    query = urlencode(q, doseq=True)

    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path or "", p.params or "", query, ""))


# --- Host policy / SSRF hardening --------------------------------------------


def _validate_http_url(url: str) -> str | None:
    try:
        p = urlparse(url)
    except (ValueError, AttributeError):
        return None
    if p.scheme not in ("http", "https"):
        return None
    if not p.netloc:
        return None
    if p.username or p.password:
        return None
    return url


def _host_is_private(host: str) -> bool:
    h = host.strip().lower()
    if not h:
        return True
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local"):
        return True
    if h.startswith("[") and h.endswith("]"):
        h_ip = h[1:-1]
    else:
        h_ip = h
    try:
        ip = ipaddress.ip_address(h_ip)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except (ValueError, AttributeError):
        return False


def _host_matches_rule(host: str, rule: str) -> bool:
    h = host.lower().strip()
    r = rule.lower().strip()
    if not h or not r:
        return False
    if r.startswith("."):
        return h == r[1:] or h.endswith(r)
    return h == r


def _enforce_host_policy(url: str) -> str | None:
    """Apply the operator host policy to *url* (SSRF guard).

    Delegates to :func:`thomas.tools.url_safety.check_url`, the single source of
    truth shared with ``eng.web_extract`` and ``browser.open`` so all outbound
    tool fetches enforce the same tiered policy (cloud-metadata/link-local are
    always blocked; RFC1918/loopback gated behind ``allow_private``).
    """
    policy = _get_host_policy()
    return check_url(
        url,
        allow_private=policy["allow_private_network"],
        allowed_hosts=policy["allowed_hosts"],
        blocked_hosts=policy["blocked_hosts"],
    )


def check_outbound_url(url: str) -> str | None:
    """Public SSRF guard for any tool that fetches a model/user-supplied URL.

    Returns an error message to surface to the caller, or ``None`` if the URL is
    allowed by the current host policy.
    """
    return _enforce_host_policy(url)


# --- Text / HTML extraction ---------------------------------------------------


def _compact_ws(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


_COOKIE_NOISE_RE = re.compile(
    r"(?is)\b(cookie(s)?|privacy policy|terms of service|consent|preferences)\b.*?(?:accept|agree|reject|manage)\b"
)

_SUBSCRIBE_NOISE_RE = re.compile(r"(?is)\b(subscribe|sign up|newsletter|log in|sign in|register)\b")


def _strip_common_noise(text: str) -> str:
    # This is intentionally gentle: it removes obvious boilerplate lines, not normal prose.
    lines = [ln.strip() for ln in text.splitlines()]
    kept: list[str] = []
    for ln in lines:
        if not ln:
            kept.append("")
            continue
        if len(ln) < 30 and _SUBSCRIBE_NOISE_RE.search(ln):
            continue
        if len(ln) < 200 and _COOKIE_NOISE_RE.search(ln):
            continue
        kept.append(ln)
    return _compact_ws("\n".join(kept))


class _HTMLMainExtractor(HTMLParser):
    """
    Dependency-free "reader-ish" extractor.

    - Skips script/style/noscript/svg/canvas/iframe
    - Skips chrome: nav/header/footer/aside
    - Tracks main/article candidates
    - Extracts: title, published_date, language (best effort)
    """

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}
    _CHROME_TAGS = {"nav", "header", "footer", "aside"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chrome_depth = 0
        self._link_depth = 0
        self._stack: list[str] = []

        self._buf_all: list[str] = []
        self._cand_stack: list[tuple[str, list[str]]] = []
        self._candidates: list[tuple[str, str]] = []

        self.title: str | None = None
        self.published_date: str | None = None
        self.language: str | None = None

        self._html_lang_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        self._stack.append(t)

        attr = {k.lower(): (v or "") for k, v in attrs}

        if t == "html" and not self._html_lang_seen:
            lang = (attr.get("lang") or "").strip()
            if lang:
                self.language = lang
            self._html_lang_seen = True

        if t in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if t in self._CHROME_TAGS:
            self._chrome_depth += 1
            return
        if t == "a":
            self._link_depth += 1

        # meta extraction
        if t == "meta":
            prop = (attr.get("property") or "").lower()
            name = (attr.get("name") or "").lower()
            content = (attr.get("content") or "").strip()

            if content:
                if prop in ("og:title", "twitter:title") and not self.title:
                    self.title = content
                if prop in ("article:published_time", "og:published_time") and not self.published_date:
                    self.published_date = content
                if name in ("date", "pubdate", "publishdate", "timestamp") and not self.published_date:
                    self.published_date = content

        if t in ("main", "article"):
            self._cand_stack.append((t, []))

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()

        if t in ("main", "article") and self._cand_stack:
            tag0, buf = self._cand_stack.pop()
            text = _compact_ws(unescape(" ".join(buf)))
            if text:
                self._candidates.append((tag0, text))

        if t == "a" and self._link_depth > 0:
            self._link_depth -= 1
        if t in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if t in self._CHROME_TAGS and self._chrome_depth > 0:
            self._chrome_depth -= 1

        if t in ("p", "br", "div", "li", "section", "article", "main", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._buf_all.append("\n")
            for _, buf in self._cand_stack:
                buf.append("\n")

        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 or self._chrome_depth > 0:
            return
        if not data or not data.strip():
            return

        # Reduce nav-like micro text (still keep real content)
        if self._link_depth > 0 and len(data.strip()) < 3:
            return

        self._buf_all.append(data)
        for _, buf in self._cand_stack:
            buf.append(data)

        if self.title is None and self._stack and self._stack[-1] == "title":
            txt = data.strip()
            if txt:
                self.title = txt

    def best_text(self) -> str:
        all_text = _compact_ws(unescape(" ".join(self._buf_all)))

        best = ""
        best_score = -1.0

        def score(txt: str) -> float:
            if not txt:
                return 0.0
            length = len(txt)
            punct = sum(txt.count(ch) for ch in (".", "!", "?", ";", ":"))
            density = punct / max(1, length)
            return float(length) * (0.75 + min(0.85, density * 45.0))

        for _, txt in self._candidates:
            s = score(txt)
            if s > best_score:
                best_score = s
                best = txt

        # pick candidate if it covers enough, else fallback
        if best and len(best) >= min(800, int(0.35 * len(all_text))):
            return best
        return all_text


def _extract_html(html: str) -> dict[str, str | None]:
    parser = _HTMLMainExtractor()
    parser.feed(html)
    parser.close()

    title = parser.title.strip() if parser.title else None
    pub = parser.published_date.strip() if parser.published_date else None
    lang = parser.language.strip() if parser.language else None

    if pub:
        pub = _parse_isoish_date(pub)

    text = parser.best_text()
    if _cfg_bool("strip_cookie_banners", True):
        text = _strip_common_noise(text)

    return {"title": title, "published_date": pub, "language": lang, "text": text}


# --- Persistent cache (optional) ---------------------------------------------

_DB_LOCK = asyncio.Lock()
_DB_READY = False


def _ensure_db_sync(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS web_tools_cache (k TEXT PRIMARY KEY,exp REAL NOT NULL,v TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_tools_cache_exp ON web_tools_cache(exp)")
        conn.commit()
    finally:
        conn.close()


async def _db_get(key: str) -> Any | None:
    if not _cfg_bool("persistent_cache", False):
        return None
    db_path = _get_cache_db_path()
    global _DB_READY
    async with _DB_LOCK:
        if not _DB_READY:
            _ensure_db_sync(db_path)
            _DB_READY = True

        now = time.time()
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT exp, v FROM web_tools_cache WHERE k=?", (key,)).fetchone()
            if not row:
                return None
            exp, v = float(row[0]), row[1]
            if exp <= now:
                conn.execute("DELETE FROM web_tools_cache WHERE k=?", (key,))
                conn.commit()
                return None
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        finally:
            conn.close()


async def _db_set(key: str, value: Any) -> None:
    if not _cfg_bool("persistent_cache", False):
        return
    db_path = _get_cache_db_path()
    global _DB_READY
    ttl_s, _ = _get_cache_cfg()
    exp = time.time() + float(ttl_s)

    async with _DB_LOCK:
        if not _DB_READY:
            _ensure_db_sync(db_path)
            _DB_READY = True

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO web_tools_cache (k, exp, v) VALUES (?,?,?)",
                (key, exp, json.dumps(value, ensure_ascii=False)),
            )
            # light prune (avoid table growing without bound)
            conn.execute("DELETE FROM web_tools_cache WHERE exp < ?", (time.time() - 60.0,))
            conn.commit()
        finally:
            conn.close()


# --- TTL+LRU in-memory cache --------------------------------------------------


class _TTLCache:
    """
    Tiny TTL + LRU cache.

    Stores key -> (expires_at_epoch_s, value)
    Evicts on insert if over capacity; LRU based on access.
    """

    def __init__(self) -> None:
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        ttl_s, max_entries = _get_cache_cfg()
        now = time.time()
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            exp, val = item
            if exp <= now:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key, last=True)
            return val

    async def set(self, key: str, value: Any) -> None:
        ttl_s, max_entries = _get_cache_cfg()
        exp = time.time() + float(ttl_s)
        async with self._lock:
            self._data[key] = (exp, value)
            self._data.move_to_end(key, last=True)
            while len(self._data) > max_entries:
                self._data.popitem(last=False)


_SEARCH_CACHE = _TTLCache()
_FETCH_CACHE = _TTLCache()

# Request coalescing: key -> Future
_INFLIGHT: dict[str, asyncio.Future] = {}
_INFLIGHT_LOCK = asyncio.Lock()


async def _coalesced(key: str, coro_factory):
    """
    If multiple callers request the same key concurrently,
    only one actual network call runs. Others await the same future.
    """
    async with _INFLIGHT_LOCK:
        fut = _INFLIGHT.get(key)
        if fut is None:
            fut = asyncio.get_event_loop().create_future()
            _INFLIGHT[key] = fut
            is_leader = True
        else:
            is_leader = False

    if not is_leader:
        return await fut

    try:
        result = await coro_factory()
        fut.set_result(result)
        return result
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        async with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)


# --- HTTP client + retries ----------------------------------------------------

_HTTP_CLIENT: httpx.AsyncClient | None = None
_HTTP_LOCK = asyncio.Lock()


def _client_limits() -> httpx.Limits:
    # tuned for tools: lots of small requests, keep connections warm
    return httpx.Limits(max_connections=60, max_keepalive_connections=25, keepalive_expiry=30.0)


async def _get_client(timeout_s: float, ua: str) -> httpx.AsyncClient:
    global _HTTP_CLIENT
    async with _HTTP_LOCK:
        if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
            _HTTP_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s),
                follow_redirects=True,
                limits=_client_limits(),
                headers={"User-Agent": ua},
            )
        else:
            _HTTP_CLIENT.timeout = httpx.Timeout(timeout_s)
            _HTTP_CLIENT.headers.update({"User-Agent": ua})
        return _HTTP_CLIENT


async def _request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int,
    backoff_s: float = 0.35,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(retries + 1):
        resp = await client.request(method, url, **kwargs)

        if resp.status_code == 429 and attempt < retries:
            ra = resp.headers.get("retry-after")
            sleep_s = None
            if ra:
                try:
                    sleep_s = float(ra)
                except (ValueError, TypeError):
                    sleep_s = None
            if sleep_s is None:
                sleep_s = backoff_s * (1.7**attempt)
            sleep_s = max(0.05, min(2.0, sleep_s))
            await asyncio.sleep(sleep_s)
            continue

        if 500 <= resp.status_code <= 599 and attempt < retries:
            sleep_s = backoff_s * (1.7**attempt)
            sleep_s = max(0.05, min(1.2, sleep_s))
            await asyncio.sleep(sleep_s)
            continue

        return resp

    return resp  # type: ignore[name-defined]


def _rate_limit_error(provider: str, resp: httpx.Response) -> str:
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        return f"{provider} rate limit hit (HTTP 429). Retry after {retry_after} seconds."
    return f"{provider} rate limit hit (HTTP 429). Try again later or reduce call frequency."


def _http_error(provider: str, resp: httpx.Response) -> str:
    if resp.status_code in (401, 403) and provider.lower().startswith("brave"):
        return "Brave Search authentication failed (HTTP 401/403). Check your API key."
    snippet = ""
    try:
        snippet = (resp.text or "")[:300].strip()
    except AttributeError:
        snippet = ""
    if snippet:
        return f"{provider} HTTP {resp.status_code}: {snippet}"
    return f"{provider} HTTP {resp.status_code}."


# --- Search normalization helpers --------------------------------------------
