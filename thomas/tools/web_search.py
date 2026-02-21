# thomas/tools/web_search.py
from __future__ import annotations

"""
Thomas Web Tools: `web.search` + `web.fetch` (v5)

This is the "consumer-grade" upgrade. Not just correct — *pleasant*.

What users actually love:
- Fast repeats (cache + connection pooling + request coalescing)
- Clean links (no tracking junk)
- Diverse results (not 5 links from the same domain)
- Fetch that returns *content*, not cookie banners and navbar sludge
- Fewer failures (retry/backoff + conditional policy checks + sane limits)
- Optional PDF text extraction (when dependency is present)

REQUIRED CONTRACT (kept):
- Tool: web.search
  - Category: web
  - Brave Search API primary (https://api.search.brave.com/res/v1/web/search)
  - API key from env BRAVE_SEARCH_API_KEY or thomas.toml [tools.web_search] api_key
  - Parameters: query (str), count (int 1-10 default 5), freshness (pd/pw/pm/py optional)
  - Returns structured results: list of {title, url, description, published_date}
  - Falls back to DuckDuckGo Instant Answer API if no Brave key configured
- Tool: web.fetch
  - Fetch a URL and return clean text (HTML stripped), max 8000 chars
- httpx for async HTTP, default timeout 10s
- Clear handling for rate limits (429)
- Factory functions: get_web_search_tool(), get_web_fetch_tool()

v5 Upgrades (meaningful):
1) Shared httpx AsyncClient + tuned connection limits.
2) TTL+LRU in-memory cache + OPTIONAL persistent SQLite cache (survives restarts).
3) Request coalescing: concurrent identical requests collapse into one network call.
4) URL canonicalization: strips tracking params (utm_*, gclid, fbclid, msclkid, etc).
5) Result diversity: prefers unique domains first, then fills remainder.
6) Fetch: "reader-ish" main content extraction + boilerplate/cookie banner suppression.
7) Redirect-safe policy: enforce host policy on initial + final redirected URL.
8) Optional PDF extraction:
   - If content-type is application/pdf and pdfplumber is available, extract text.
   - Otherwise returns a clear "unsupported content-type" error.

Optional config (safe defaults if absent):

    [tools.web_search]
    api_key = "..."
    timeout_s = 10
    user_agent = "Thomas/1.0 (+web)"
    max_fetch_chars = 8000
    max_fetch_bytes = 2000000
    retries = 1

    # caching
    cache_ttl_s = 120
    cache_max_entries = 256

    # persistent cache (optional)
    persistent_cache = false
    cache_db_path = "runtime/cache/web_tools_cache.sqlite3"

    # host policy (optional hardening)
    allow_private_network = true
    allowed_hosts = []     # exact "example.com" or suffix ".example.com"
    blocked_hosts = []     # exact "bad.com" or suffix ".bad.com"

    # content cleanup
    strip_cookie_banners = true
    min_text_len = 200     # if extracted text is shorter, fallback to full-page text

This file is dependency-light; optional pdfplumber is used only if installed.
"""

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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

# Adjust if your project uses a different import path for Tool/ToolResult/ToolSpec.
from thomas.tools.base import Tool, ToolResult, ToolSpec  # type: ignore


# --- Endpoints / defaults -----------------------------------------------------

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_DDG_ENDPOINT = "https://api.duckduckgo.com/"
_DDG_HTML_ENDPOINT = "https://duckduckgo.com/html/"

_DEFAULT_TIMEOUT_S = 10.0
_MIN_RESULTS = 1
_MAX_RESULTS = 10

_DEFAULT_MAX_FETCH_CHARS = 8000
_DEFAULT_MAX_FETCH_BYTES = 2_000_000
_DEFAULT_RETRIES = 1

_DEFAULT_CACHE_TTL_S = 120
_DEFAULT_CACHE_MAX_ENTRIES = 256

# tiny cache to avoid re-reading thomas.toml repeatedly
_TOML_CACHE: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
_TOML_CACHE_TTL_S = 5.0


# --- Utility -----------------------------------------------------------------

def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_isoish_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(s2)
        return dt.isoformat()
    except Exception:
        return s


def _hash_key(s: str) -> str:
    # stable small key for sqlite index
    import hashlib
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


# --- TOML config --------------------------------------------------------------

def _get_toml_path() -> str:
    return os.environ.get("THOMAS_TOML_PATH", "thomas.toml")


def _load_toml() -> Dict[str, Any]:
    global _TOML_CACHE
    now = time.time()
    ts, cached = _TOML_CACHE
    if cached is not None and (now - ts) < _TOML_CACHE_TTL_S:
        return cached

    path = _get_toml_path()
    try:
        try:
            import tomllib  # Python 3.11+
        except Exception:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    _TOML_CACHE = (now, data)
    return data


def _get_tool_cfg() -> Dict[str, Any]:
    cfg = _load_toml()
    try:
        tools = cfg.get("tools") or {}
        ws = tools.get("web_search") or {}
        return ws if isinstance(ws, dict) else {}
    except Exception:
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
    except Exception:
        i = default
    return _clamp_int(i, lo, hi)


def _cfg_str(key: str, default: str) -> str:
    ws = _get_tool_cfg()
    v = ws.get(key, default)
    s = str(v).strip() if v is not None else ""
    return s or default


def _get_brave_api_key() -> Optional[str]:
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
    except Exception:
        pass
    return _DEFAULT_TIMEOUT_S


def _get_user_agent() -> str:
    return _cfg_str("user_agent", "Thomas/1.0 (+web)")


def _get_fetch_limits() -> Tuple[int, int]:
    max_chars = _cfg_int("max_fetch_chars", _DEFAULT_MAX_FETCH_CHARS, 1000, 20000)
    max_bytes = _cfg_int("max_fetch_bytes", _DEFAULT_MAX_FETCH_BYTES, 100_000, 10_000_000)
    return max_chars, max_bytes


def _get_retries() -> int:
    return _cfg_int("retries", _DEFAULT_RETRIES, 0, 3)


def _get_cache_cfg() -> Tuple[int, int]:
    ttl = _cfg_int("cache_ttl_s", _DEFAULT_CACHE_TTL_S, 5, 3600)
    mx = _cfg_int("cache_max_entries", _DEFAULT_CACHE_MAX_ENTRIES, 16, 2048)
    return ttl, mx


def _get_cache_db_path() -> str:
    # default path under runtime/cache
    ws = _get_tool_cfg()
    p = ws.get("cache_db_path")
    if p and str(p).strip():
        return str(p).strip()
    return "runtime/cache/web_tools_cache.sqlite3"


def _get_host_policy() -> Dict[str, Any]:
    ws = _get_tool_cfg()
    allow_private = ws.get("allow_private_network", True)
    allowed_hosts = ws.get("allowed_hosts", [])
    blocked_hosts = ws.get("blocked_hosts", [])

    def _norm_list(v: Any) -> List[str]:
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
    "gclid", "fbclid", "dclid", "msclkid", "igshid",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name", "utm_referrer",
    "ref", "ref_src",
}

def _canonicalize_url(url: str) -> str:
    try:
        p = urlparse(url)
    except Exception:
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

def _validate_http_url(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
    except Exception:
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
    except Exception:
        return False


def _host_matches_rule(host: str, rule: str) -> bool:
    h = host.lower().strip()
    r = rule.lower().strip()
    if not h or not r:
        return False
    if r.startswith("."):
        return h == r[1:] or h.endswith(r)
    return h == r


def _enforce_host_policy(url: str) -> Optional[str]:
    p = urlparse(url)
    host = (p.hostname or "").strip().lower()
    if not host:
        return "Invalid URL host."

    policy = _get_host_policy()
    allowed = policy["allowed_hosts"]
    blocked = policy["blocked_hosts"]
    allow_private = policy["allow_private_network"]

    for r in blocked:
        if _host_matches_rule(host, r):
            return f"Host blocked by policy: {host}"

    if allowed:
        ok = any(_host_matches_rule(host, r) for r in allowed)
        if not ok:
            return f"Host not in allowed_hosts policy: {host}"

    if not allow_private and _host_is_private(host):
        return f"Private network host disallowed by policy: {host}"

    return None


# --- Text / HTML extraction ---------------------------------------------------

def _compact_ws(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


_COOKIE_NOISE_RE = re.compile(
    r"(?is)\b(cookie(s)?|privacy policy|terms of service|consent|preferences)\b.*?(?:accept|agree|reject|manage)\b"
)

_SUBSCRIBE_NOISE_RE = re.compile(
    r"(?is)\b(subscribe|sign up|newsletter|log in|sign in|register)\b"
)

def _strip_common_noise(text: str) -> str:
    # This is intentionally gentle: it removes obvious boilerplate lines, not normal prose.
    lines = [ln.strip() for ln in text.splitlines()]
    kept: List[str] = []
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
        self._stack: List[str] = []

        self._buf_all: List[str] = []
        self._cand_stack: List[Tuple[str, List[str]]] = []
        self._candidates: List[Tuple[str, str]] = []

        self.title: Optional[str] = None
        self.published_date: Optional[str] = None
        self.language: Optional[str] = None

        self._html_lang_seen = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
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


def _extract_html(html: str) -> Dict[str, Optional[str]]:
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
            "CREATE TABLE IF NOT EXISTS web_tools_cache ("
            "k TEXT PRIMARY KEY,"
            "exp REAL NOT NULL,"
            "v TEXT NOT NULL"
            ")"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_web_tools_cache_exp ON web_tools_cache(exp)")
        conn.commit()
    finally:
        conn.close()

async def _db_get(key: str) -> Optional[Any]:
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
            except Exception:
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
        self._data: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
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
_INFLIGHT: Dict[str, asyncio.Future] = {}
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

_HTTP_CLIENT: Optional[httpx.AsyncClient] = None
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
                except Exception:
                    sleep_s = None
            if sleep_s is None:
                sleep_s = backoff_s * (1.7 ** attempt)
            sleep_s = max(0.05, min(2.0, sleep_s))
            await asyncio.sleep(sleep_s)
            continue

        if 500 <= resp.status_code <= 599 and attempt < retries:
            sleep_s = backoff_s * (1.7 ** attempt)
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
    except Exception:
        snippet = ""
    if snippet:
        return f"{provider} HTTP {resp.status_code}: {snippet}"
    return f"{provider} HTTP {resp.status_code}."


# --- Search normalization helpers --------------------------------------------

def _normalize_brave_result(item: Dict[str, Any]) -> Dict[str, Any]:
    title = _safe_str(item.get("title") or item.get("name")).strip()
    url = _safe_str(item.get("url") or item.get("link")).strip()
    desc = _safe_str(item.get("description") or item.get("snippet")).strip()

    published = (
        item.get("age")
        or item.get("published_date")
        or item.get("page_age")
        or item.get("date")
        or item.get("last_crawled")
    )
    published_date = _parse_isoish_date(_safe_str(published)) if published else None

    url = _canonicalize_url(url) if url else url

    return {"title": title, "url": url, "description": desc, "published_date": published_date}


def _flatten_ddg_related_topics(related_topics: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(related_topics, list):
        return out

    for item in related_topics:
        if not isinstance(item, dict):
            continue
        if "Topics" in item and isinstance(item["Topics"], list):
            out.extend(_flatten_ddg_related_topics(item["Topics"]))
            continue
        text = item.get("Text")
        first_url = item.get("FirstURL")
        if text and first_url:
            t = _safe_str(text).strip()
            u = _canonicalize_url(_safe_str(first_url).strip())
            if t and u:
                out.append({"title": t, "url": u, "description": t, "published_date": None})
    return out


def _dedupe_by_url(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in results:
        u = (r.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


def _domain(u: str) -> str:
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""


def _diversify_by_domain(results: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    """
    Prefer unique domains first (feels better than 5 results from the same site).
    Then fill remaining slots in original order.
    """
    picked: List[Dict[str, Any]] = []
    seen_dom = set()

    for r in results:
        if len(picked) >= count:
            break
        dom = _domain(r.get("url") or "")
        if dom and dom not in seen_dom:
            picked.append(r)
            seen_dom.add(dom)

    if len(picked) < count:
        for r in results:
            if len(picked) >= count:
                break
            if r in picked:
                continue
            picked.append(r)

    return picked[:count]


class _DDGHtmlResultsParser(HTMLParser):
    """
    Best-effort parser for DuckDuckGo HTML results page.
    Tolerant: if markup shifts, you just get fewer results.
    """
    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, Any]] = []
        self._in_result = False
        self._cur: Dict[str, Any] = {}
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: List[str] = []
        self._snip_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if t == "div" and "result" in (a.get("class", "")):
            self._in_result = True
            self._cur = {}
            self._title_parts = []
            self._snip_parts = []
        if self._in_result and t == "a":
            cls = a.get("class", "")
            href = a.get("href", "").strip()
            if href and ("result__a" in cls or "result-link" in cls or "result__url" in cls):
                self._cur["url"] = href
                self._capture_title = True
        if self._in_result and t in ("a", "div", "span"):
            cls = a.get("class", "")
            if "result__snippet" in cls:
                self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "a":
            self._capture_title = False
        if t in ("div", "span"):
            self._capture_snippet = False
        if t == "div" and self._in_result:
            title = _compact_ws(unescape(" ".join(self._title_parts)))
            snip = _compact_ws(unescape(" ".join(self._snip_parts)))
            url = _canonicalize_url(_safe_str(self._cur.get("url")).strip())
            if title and url:
                self.results.append({"title": title, "url": url, "description": snip or title, "published_date": None})
            self._in_result = False
            self._cur = {}
            self._title_parts = []
            self._snip_parts = []

    def handle_data(self, data: str) -> None:
        if not data or not data.strip():
            return
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_snippet:
            self._snip_parts.append(data)


# --- Tools -------------------------------------------------------------------

class WebSearchTool(Tool):
    """
    Web search tool for Thomas.

    Tool name: "web.search"
    Category: "web"

    Parameters:
      - query: string (required)
      - count: integer (1-10, default 5)
      - freshness: string enum {pd,pw,pm,py} optional

    Returns ToolResult.data:
      {
        "provider": "brave" | "duckduckgo",
        "query": "<query>",
        "count": <count>,
        "results": [
          {"title": "...", "url": "...", "description": "...", "published_date": "...|None"},
          ...
        ],
        "meta": { ... }
      }
    """

    name: str = "web.search"
    category: str = "web"
    description: str = "Search the web (Brave API with DuckDuckGo fallback) and return structured results."
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Number of results (1-10, default 5)",
                "minimum": _MIN_RESULTS,
                "maximum": _MAX_RESULTS,
                "default": 5,
            },
            "freshness": {
                "type": "string",
                "description": "pd=past day, pw=past week, pm=past month, py=past year. Optional.",
                "enum": ["pd", "pw", "pm", "py"],
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        start = _now_ms()
        timeout_s = _get_timeout_s()
        ua = _get_user_agent()
        retries = _get_retries()

        try:
            query = _safe_str(args.get("query")).strip()
            if not query:
                return ToolResult(ok=False, data=None, error="Missing required parameter: query", duration_ms=_now_ms() - start)

            try:
                count = int(args.get("count", 5))
            except Exception:
                count = 5
            count = _clamp_int(count, _MIN_RESULTS, _MAX_RESULTS)

            freshness = args.get("freshness")
            if freshness is not None:
                freshness = _safe_str(freshness).strip() or None
            if freshness not in (None, "pd", "pw", "pm", "py"):
                return ToolResult(ok=False, data=None, error="Invalid freshness. Allowed: pd, pw, pm, py.", duration_ms=_now_ms() - start)

            provider = "brave" if _get_brave_api_key() else "duckduckgo"
            raw_key = f"search::{provider}::{freshness or ''}::{count}::{query.lower()}"
            key = _hash_key(raw_key)

            # 1) memory cache
            cached = await _SEARCH_CACHE.get(key)
            if cached is not None:
                payload = dict(cached)
                payload.setdefault("meta", {})
                payload["meta"] = dict(payload["meta"])
                payload["meta"]["cache_hit"] = True
                payload["meta"]["cache_layer"] = "memory"
                return ToolResult(ok=True, data=payload, error=None, duration_ms=_now_ms() - start)

            # 2) persistent cache (optional)
            cached_db = await _db_get(key)
            if cached_db is not None:
                await _SEARCH_CACHE.set(key, cached_db)
                payload = dict(cached_db)
                payload.setdefault("meta", {})
                payload["meta"] = dict(payload["meta"])
                payload["meta"]["cache_hit"] = True
                payload["meta"]["cache_layer"] = "sqlite"
                return ToolResult(ok=True, data=payload, error=None, duration_ms=_now_ms() - start)

            async def do_search():
                brave_key = _get_brave_api_key()
                if brave_key:
                    return await self._search_brave(query=query, count=count, freshness=freshness, api_key=brave_key, timeout_s=timeout_s, ua=ua, retries=retries)
                return await self._search_ddg(query=query, count=count, timeout_s=timeout_s, ua=ua, retries=retries)

            # request coalescing
            data = await _coalesced(f"inflight::{key}", do_search)

            # diversify + cache
            data = dict(data)
            data["results"] = _diversify_by_domain(_dedupe_by_url(data.get("results") or []), count)

            await _SEARCH_CACHE.set(key, data)
            await _db_set(key, data)

            return ToolResult(ok=True, data=data, error=None, duration_ms=_now_ms() - start)

        except httpx.TimeoutException:
            return ToolResult(ok=False, data=None, error=f"Web search timed out after {timeout_s:.0f}s.", duration_ms=_now_ms() - start)
        except httpx.RequestError as e:
            return ToolResult(ok=False, data=None, error=f"Web search network error: {e}", duration_ms=_now_ms() - start)
        except Exception as e:
            return ToolResult(ok=False, data=None, error=str(e) or f"Web search failed: {e}", duration_ms=_now_ms() - start)

    async def _search_brave(
        self,
        *,
        query: str,
        count: int,
        freshness: Optional[str],
        api_key: str,
        timeout_s: float,
        ua: str,
        retries: int,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"q": query, "count": max(count, 8)}  # ask for a bit more for diversity
        if freshness:
            params["freshness"] = freshness

        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

        client = await _get_client(timeout_s, ua)
        t0 = _now_ms()
        resp = await _request_with_retries(client, "GET", _BRAVE_ENDPOINT, retries=retries, params=params, headers=headers)
        took_ms = _now_ms() - t0

        if resp.status_code == 429:
            raise RuntimeError(_rate_limit_error("Brave Search", resp))
        if resp.status_code >= 400:
            raise RuntimeError(_http_error("Brave Search", resp))

        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError("Brave Search returned non-JSON response.")

        results_raw: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            web = payload.get("web")
            if isinstance(web, dict) and isinstance(web.get("results"), list):
                results_raw = [r for r in web["results"] if isinstance(r, dict)]
            elif isinstance(payload.get("results"), list):
                results_raw = [r for r in payload["results"] if isinstance(r, dict)]

        results = [_normalize_brave_result(r) for r in results_raw]
        results = [r for r in results if (r.get("title") or "").strip() and (r.get("url") or "").strip()]
        results = _dedupe_by_url(results)

        return {
            "provider": "brave",
            "query": query,
            "count": count,
            "results": results[: max(count, 10)],  # diversify later
            "meta": {"freshness": freshness, "took_ms": took_ms, "cache_hit": False},
        }

    async def _search_ddg(self, *, query: str, count: int, timeout_s: float, ua: str, retries: int) -> Dict[str, Any]:
        client = await _get_client(timeout_s, ua)

        # 1) Instant Answer (required)
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "1"}
        t0 = _now_ms()
        resp = await _request_with_retries(client, "GET", _DDG_ENDPOINT, retries=retries, params=params, headers={"Accept": "application/json"})
        took_ms = _now_ms() - t0

        if resp.status_code == 429:
            raise RuntimeError(_rate_limit_error("DuckDuckGo", resp))
        if resp.status_code >= 400:
            raise RuntimeError(_http_error("DuckDuckGo", resp))

        try:
            payload = resp.json()
        except Exception:
            payload = {}

        payload = payload if isinstance(payload, dict) else {}
        results: List[Dict[str, Any]] = []

        abstract = _safe_str(payload.get("AbstractText")).strip()
        abstract_url = _safe_str(payload.get("AbstractURL")).strip()
        abstract_src = _safe_str(payload.get("AbstractSource")).strip()
        if abstract and abstract_url:
            results.append(
                {"title": f"{abstract_src or 'DuckDuckGo'} instant answer", "url": _canonicalize_url(abstract_url), "description": abstract, "published_date": None}
            )

        direct = payload.get("Results")
        if isinstance(direct, list):
            for item in direct:
                if not isinstance(item, dict):
                    continue
                t = _safe_str(item.get("Text")).strip()
                u = _safe_str(item.get("FirstURL")).strip()
                if t and u:
                    results.append({"title": t, "url": _canonicalize_url(u), "description": t, "published_date": None})

        results.extend(_flatten_ddg_related_topics(payload.get("RelatedTopics")))
        results = _dedupe_by_url([r for r in results if (r.get("title") or "").strip() and (r.get("url") or "").strip()])

        variant = "instant_answer"

        # 2) If IA yields nothing, attempt HTML SERP parsing (best-effort)
        if not results:
            try:
                t1 = _now_ms()
                resp2 = await _request_with_retries(client, "GET", _DDG_HTML_ENDPOINT, retries=retries, params={"q": query}, headers={"Accept": "text/html"})
                took2 = _now_ms() - t1
                if resp2.status_code == 200 and (resp2.text or ""):
                    parser = _DDGHtmlResultsParser()
                    parser.feed(resp2.text)
                    parser.close()
                    if parser.results:
                        results = _dedupe_by_url(parser.results)
                        took_ms += took2
                        variant = "html_serp"
            except Exception:
                pass

        return {
            "provider": "duckduckgo",
            "query": query,
            "count": count,
            "results": results[: max(count, 10)],
            "meta": {"variant": variant, "took_ms": took_ms, "cache_hit": False},
        }


class WebFetchTool(Tool):
    """
    Fetch a URL and return cleaned text.

    Tool name: "web.fetch"
    Category: "web"

    Parameters:
      - url: string (required; http/https)

    Returns ToolResult.data:
      {
        "url": "<original url>",
        "final_url": "<after redirects>",
        "status_code": <int>,
        "content_type": "<lowercase content-type>",
        "title": "<best-effort title or None>",
        "published_date": "<best-effort ISO-ish date or None>",
        "language": "<html lang or None>",
        "text": "<cleaned text, max N chars>",
        "meta": { ... }
      }
    """

    name: str = "web.fetch"
    category: str = "web"
    description: str = "Fetch a URL and return cleaned text (HTML stripped, max 8000 chars)."
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to fetch"}},
        "required": ["url"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        start = _now_ms()
        timeout_s = _get_timeout_s()
        ua = _get_user_agent()
        retries = _get_retries()
        max_chars, max_bytes = _get_fetch_limits()
        min_text_len = _cfg_int("min_text_len", 200, 0, 2000)

        try:
            url_in = _safe_str(args.get("url")).strip()
            url = _validate_http_url(url_in) or ""
            if not url:
                return ToolResult(ok=False, data=None, error="Invalid URL. Must be http(s) with a host and no userinfo.", duration_ms=_now_ms() - start)

            url = _canonicalize_url(url)

            # enforce host policy on initial URL
            policy_err = _enforce_host_policy(url)
            if policy_err:
                return ToolResult(ok=False, data=None, error=policy_err, duration_ms=_now_ms() - start)

            cache_raw = f"fetch::{max_chars}::{max_bytes}::{url}"
            key = _hash_key(cache_raw)

            # memory cache
            cached = await _FETCH_CACHE.get(key)
            if cached is not None:
                payload = dict(cached)
                payload.setdefault("meta", {})
                payload["meta"] = dict(payload["meta"])
                payload["meta"]["cache_hit"] = True
                payload["meta"]["cache_layer"] = "memory"
                return ToolResult(ok=True, data=payload, error=None, duration_ms=_now_ms() - start)

            # persistent cache
            cached_db = await _db_get(key)
            if cached_db is not None:
                await _FETCH_CACHE.set(key, cached_db)
                payload = dict(cached_db)
                payload.setdefault("meta", {})
                payload["meta"] = dict(payload["meta"])
                payload["meta"]["cache_hit"] = True
                payload["meta"]["cache_layer"] = "sqlite"
                return ToolResult(ok=True, data=payload, error=None, duration_ms=_now_ms() - start)

            async def do_fetch():
                return await self._fetch_impl(url=url, timeout_s=timeout_s, ua=ua, retries=retries, max_chars=max_chars, max_bytes=max_bytes, min_text_len=min_text_len)

            data = await _coalesced(f"inflight::{key}", do_fetch)

            await _FETCH_CACHE.set(key, data)
            await _db_set(key, data)

            return ToolResult(ok=True, data=data, error=None, duration_ms=_now_ms() - start)

        except httpx.TimeoutException:
            return ToolResult(ok=False, data=None, error=f"Fetch timed out after {timeout_s:.0f}s.", duration_ms=_now_ms() - start)
        except httpx.RequestError as e:
            return ToolResult(ok=False, data=None, error=f"Fetch network error: {e}", duration_ms=_now_ms() - start)
        except Exception as e:
            return ToolResult(ok=False, data=None, error=f"Fetch failed: {e}", duration_ms=_now_ms() - start)

    async def _fetch_impl(self, *, url: str, timeout_s: float, ua: str, retries: int, max_chars: int, max_bytes: int, min_text_len: int) -> Dict[str, Any]:
        client = await _get_client(timeout_s, ua)

        final_url = url
        status_code = 0
        content_type_hdr = ""
        downloaded = 0

        t0 = _now_ms()
        async with client.stream(
            "GET",
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,application/json;q=0.8,*/*;q=0.3",
                "Accept-Language": "en-US,en;q=0.8,*;q=0.5",
            },
        ) as resp:
            status_code = resp.status_code
            final_url = str(resp.url)
            content_type_hdr = _safe_str(resp.headers.get("content-type", ""))

            if status_code == 429:
                raise RuntimeError(_rate_limit_error("Fetch", resp))
            if status_code >= 400:
                raise RuntimeError(f"Failed to fetch URL (HTTP {status_code}).")

            # enforce policy on final redirect
            policy_err2 = _enforce_host_policy(final_url)
            if policy_err2:
                raise RuntimeError(f"Redirected URL blocked: {policy_err2}")

            # pre-check content-length
            cl = resp.headers.get("content-length")
            if cl:
                try:
                    if int(cl) > max_bytes:
                        raise RuntimeError(f"Fetch exceeds {max_bytes} bytes limit.")
                except ValueError:
                    pass

            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                buf.extend(chunk)
                downloaded = len(buf)
                if downloaded > max_bytes:
                    raise RuntimeError(f"Fetch exceeded {max_bytes} bytes limit.")

        took_ms = _now_ms() - t0

        # sniff content type
        prefix = bytes(buf[:64]).lstrip()
        ct = (content_type_hdr or "").lower().split(";")[0].strip()

        if prefix.startswith(b"%PDF"):
            content_type = "application/pdf"
        elif prefix.startswith(b"\x89PNG"):
            content_type = "image/png"
        elif prefix.startswith(b"\xff\xd8\xff"):
            content_type = "image/jpeg"
        elif prefix.startswith(b"GIF87a") or prefix.startswith(b"GIF89a"):
            content_type = "image/gif"
        elif prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html") or prefix.startswith(b"<head") or prefix.startswith(b"<body"):
            content_type = "text/html"
        else:
            content_type = ct or "application/octet-stream"

        # PDF extraction (optional delight)
        if content_type == "application/pdf":
            try:
                import pdfplumber  # type: ignore
            except Exception:
                raise RuntimeError("Unsupported content-type for text extraction: application/pdf (install pdfplumber to enable).")

            text = ""
            try:
                import io
                with pdfplumber.open(io.BytesIO(bytes(buf))) as pdf:
                    parts = []
                    for page in pdf.pages[:20]:  # keep it bounded
                        t = page.extract_text() or ""
                        if t.strip():
                            parts.append(t)
                    text = "\n\n".join(parts)
            except Exception as e:
                raise RuntimeError(f"PDF extraction failed: {e}")

            text = _compact_ws(text)
            if len(text) > max_chars:
                text = text[:max_chars]

            return {
                "url": url,
                "final_url": _canonicalize_url(final_url),
                "status_code": status_code,
                "content_type": content_type,
                "title": None,
                "published_date": None,
                "language": None,
                "text": text,
                "meta": {"took_ms": took_ms, "downloaded_bytes": downloaded, "cache_hit": False, "extracted": "pdf"},
            }

        is_text_like = (
            content_type.startswith("text/")
            or content_type in ("application/json", "application/xml")
            or "html" in content_type
            or "json" in content_type
            or "xml" in content_type
        )

        if not is_text_like:
            raise RuntimeError(f"Unsupported content-type for text extraction: {content_type}.")

        raw = bytes(buf)
        text = raw.decode("utf-8", errors="replace")

        title = None
        published_date = None
        language = None

        cleaned = ""
        extracted_mode = "plain"

        if "html" in content_type or "<html" in text.lower() or "<body" in text.lower():
            extracted = _extract_html(text)
            title = extracted.get("title")
            published_date = extracted.get("published_date")
            language = extracted.get("language")
            cleaned = extracted.get("text") or ""
            extracted_mode = "html_main"

            # If the "main" extraction is too short, fall back to full-page text
            if min_text_len and len(cleaned) < min_text_len:
                # fallback: strip tags broadly by re-parsing as "all text"
                parser = _HTMLMainExtractor()
                parser.feed(text)
                parser.close()
                cleaned2 = parser.best_text()
                if _cfg_bool("strip_cookie_banners", True):
                    cleaned2 = _strip_common_noise(cleaned2)
                if len(cleaned2) > len(cleaned):
                    cleaned = cleaned2
                    extracted_mode = "html_full_fallback"
        else:
            cleaned = _compact_ws(unescape(text))

        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars]

        # Provide a stable content hash for dedupe (consumers love "same content" detection)
        content_hash = _hash_key(cleaned[:4000])

        return {
            "url": url,
            "final_url": _canonicalize_url(final_url),
            "status_code": status_code,
            "content_type": content_type,
            "title": title,
            "published_date": published_date,
            "language": language,
            "text": cleaned,
            "meta": {
                "took_ms": took_ms,
                "downloaded_bytes": downloaded,
                "cache_hit": False,
                "extracted": extracted_mode,
                "content_hash": content_hash,
            },
        }


# --- Factories ----------------------------------------------------------------

def get_web_search_tool() -> WebSearchTool:
    return WebSearchTool()


def get_web_fetch_tool() -> WebFetchTool:
    return WebFetchTool()


__all__ = ["WebSearchTool", "WebFetchTool", "get_web_search_tool", "get_web_fetch_tool"]
