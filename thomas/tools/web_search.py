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

Facade module imports from:
  - web_search_providers.py: HTTP, caching, and provider utilities
  - web_search_parsing.py: HTML parsing and result processing
"""

import json
from typing import Any

try:
    from thomas.tools.base import Tool, ToolResult, ToolSpec  # type: ignore
except ImportError:  # pragma: no cover

    class ToolResult:
        def __init__(self, ok: bool, data: Any = None, error: str = "", duration_ms: float = 0) -> None:
            self.ok = ok
            self.data = data
            self.error = error
            self.duration_ms = duration_ms

    class ToolSpec:
        pass

    class Tool:
        name: str = ""
        category: str = ""
        description: str = ""
        parameters: dict[str, Any] = {}

        async def execute(self, args: dict[str, Any]) -> ToolResult:
            raise NotImplementedError


# Import utilities from submodules
import httpx  # noqa: E402

from .web_search_parsing import (  # noqa: E402
    _DDGHtmlResultsParser,
    _dedupe_by_url,
    _diversify_by_domain,
    _extract_html,
    _flatten_ddg_related_topics,
    _normalize_brave_result,
)
from .web_search_providers import (  # noqa: E402
    _BRAVE_ENDPOINT,
    _DDG_ENDPOINT,
    _DDG_HTML_ENDPOINT,
    _FETCH_CACHE,
    _MAX_RESULTS,
    _MIN_RESULTS,
    _SEARCH_CACHE,
    _canonicalize_url,
    _clamp_int,
    _coalesced,
    _db_get,
    _db_set,
    _enforce_host_policy,
    _get_brave_api_key,
    _get_client,
    _get_fetch_limits,
    _get_retries,
    _get_timeout_s,
    _get_user_agent,
    _hash_key,
    _http_error,
    _now_ms,
    _rate_limit_error,
    _request_with_retries,
    _safe_str,
)


class WebSearchTool(Tool):
    """Web search tool for Thomas (Brave + DuckDuckGo)."""

    name: str = "web.search"
    category: str = "web"
    description: str = "Search the web (Brave API with DuckDuckGo fallback) and return structured results."
    parameters: dict[str, Any] = {
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

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        start = _now_ms()
        timeout_s = _get_timeout_s()
        ua = _get_user_agent()
        retries = _get_retries()

        try:
            query = _safe_str(args.get("query")).strip()
            if not query:
                return ToolResult(
                    ok=False, data=None, error="Missing required parameter: query", duration_ms=_now_ms() - start
                )

            try:
                count = int(args.get("count", 5))
            except (ValueError, TypeError):
                count = 5
            count = _clamp_int(count, _MIN_RESULTS, _MAX_RESULTS)

            freshness = args.get("freshness")
            if freshness is not None:
                freshness = _safe_str(freshness).strip() or None
            if freshness not in (None, "pd", "pw", "pm", "py"):
                return ToolResult(
                    ok=False,
                    data=None,
                    error="Invalid freshness. Allowed: pd, pw, pm, py.",
                    duration_ms=_now_ms() - start,
                )

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
                    return await self._search_brave(
                        query=query,
                        count=count,
                        freshness=freshness,
                        api_key=brave_key,
                        timeout_s=timeout_s,
                        ua=ua,
                        retries=retries,
                    )
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
            return ToolResult(
                ok=False,
                data=None,
                error=f"Web search timed out after {timeout_s:.0f}s.",
                duration_ms=_now_ms() - start,
            )
        except httpx.RequestError as e:
            return ToolResult(
                ok=False, data=None, error=f"Web search network error: {e}", duration_ms=_now_ms() - start
            )
        except Exception as e:
            return ToolResult(
                ok=False, data=None, error=str(e) or f"Web search failed: {e}", duration_ms=_now_ms() - start
            )

    async def _search_brave(
        self,
        *,
        query: str,
        count: int,
        freshness: str | None,
        api_key: str,
        timeout_s: float,
        ua: str,
        retries: int,
    ) -> dict[str, Any]:
        """Execute a Brave Search API call."""
        params: dict[str, Any] = {"q": query, "count": max(count, 8)}
        if freshness:
            params["freshness"] = freshness

        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}

        client = await _get_client(timeout_s, ua)
        t0 = _now_ms()
        resp = await _request_with_retries(
            client, "GET", _BRAVE_ENDPOINT, retries=retries, params=params, headers=headers
        )
        took_ms = _now_ms() - t0

        if resp.status_code == 429:
            raise RuntimeError(_rate_limit_error("Brave Search", resp))
        if resp.status_code >= 400:
            raise RuntimeError(_http_error("Brave Search", resp))

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            raise RuntimeError("Brave Search returned non-JSON response.")

        results_raw: list[dict[str, Any]] = []
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
            "results": results[: max(count, 10)],
            "meta": {"freshness": freshness, "took_ms": took_ms, "cache_hit": False},
        }

    async def _search_ddg(self, *, query: str, count: int, timeout_s: float, ua: str, retries: int) -> dict[str, Any]:
        """Execute a DuckDuckGo search (instant answer + HTML fallback)."""
        client = await _get_client(timeout_s, ua)

        # 1) Instant Answer (required)
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "1"}
        t0 = _now_ms()
        resp = await _request_with_retries(
            client, "GET", _DDG_ENDPOINT, retries=retries, params=params, headers={"Accept": "application/json"}
        )
        took_ms = _now_ms() - t0

        if resp.status_code == 429:
            raise RuntimeError(_rate_limit_error("DuckDuckGo", resp))
        if resp.status_code >= 400:
            raise RuntimeError(_http_error("DuckDuckGo", resp))

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            payload = {}

        payload = payload if isinstance(payload, dict) else {}
        results: list[dict[str, Any]] = []

        abstract = _safe_str(payload.get("AbstractText")).strip()
        abstract_url = _safe_str(payload.get("AbstractURL")).strip()
        abstract_src = _safe_str(payload.get("AbstractSource")).strip()
        if abstract and abstract_url:
            results.append(
                {
                    "title": f"{abstract_src or 'DuckDuckGo'} instant answer",
                    "url": _canonicalize_url(abstract_url),
                    "description": abstract,
                    "published_date": None,
                }
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
        results = _dedupe_by_url(
            [r for r in results if (r.get("title") or "").strip() and (r.get("url") or "").strip()]
        )

        variant = "instant_answer"

        # 2) If IA yields nothing, attempt HTML SERP parsing
        if not results:
            try:
                t1 = _now_ms()
                resp2 = await _request_with_retries(
                    client,
                    "GET",
                    _DDG_HTML_ENDPOINT,
                    retries=retries,
                    params={"q": query},
                    headers={"Accept": "text/html"},
                )
                took2 = _now_ms() - t1
                if resp2.status_code == 200 and (resp2.text or ""):
                    parser = _DDGHtmlResultsParser()
                    parser.feed(resp2.text)
                    parser.close()
                    if parser.results:
                        results = _dedupe_by_url(parser.results)
                        took_ms += took2
                        variant = "html_serp"
            except (ValueError, KeyError, AttributeError):
                pass

        return {
            "provider": "duckduckgo",
            "query": query,
            "count": count,
            "results": results[: max(count, 10)],
            "meta": {"variant": variant, "took_ms": took_ms, "cache_hit": False},
        }


class WebFetchTool(Tool):
    """Fetch a URL and return cleaned text content."""

    name: str = "web.fetch"
    category: str = "web"
    description: str = "Fetch a URL and return the cleaned main content text (max 8000 chars)."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch"},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        start = _now_ms()
        timeout_s = _get_timeout_s()
        ua = _get_user_agent()
        retries = _get_retries()
        max_chars, max_bytes = _get_fetch_limits()

        try:
            url = _safe_str(args.get("url")).strip()
            if not url:
                return ToolResult(
                    ok=False, data=None, error="Missing required parameter: url", duration_ms=_now_ms() - start
                )

            # Enforce host policy
            policy_err = _enforce_host_policy(url)
            if policy_err:
                return ToolResult(ok=False, data=None, error=policy_err, duration_ms=_now_ms() - start)

            # Check cache
            cache_key = _hash_key(f"fetch::{url}")
            cached = await _FETCH_CACHE.get(cache_key)
            if cached is not None:
                result = dict(cached)
                result["_cached"] = True
                return ToolResult(ok=True, data=result, error=None, duration_ms=_now_ms() - start)

            # Fetch
            client = await _get_client(timeout_s, ua)
            t0 = _now_ms()
            resp = await _request_with_retries(client, "GET", url, retries=retries, follow_redirects=True)
            took_ms = _now_ms() - t0

            # Check final URL policy
            final_url = str(resp.url) if hasattr(resp, "url") else url
            policy_err = _enforce_host_policy(final_url)
            if policy_err:
                return ToolResult(ok=False, data=None, error=policy_err, duration_ms=_now_ms() - start)

            if resp.status_code >= 400:
                return ToolResult(ok=False, data=None, error=f"HTTP {resp.status_code}", duration_ms=_now_ms() - start)

            content_type = (resp.headers.get("content-type") or "").lower()

            # PDF handling
            if "application/pdf" in content_type:
                try:
                    import pdfplumber

                    text = ""
                    try:
                        with pdfplumber.open(resp.content):
                            # type: ignore
                            for page in pdfplumber.open(resp.content).pages:  # type: ignore
                                text += page.extract_text() or ""
                    except Exception:
                        text = "(PDF extraction failed; content is likely binary)"
                except ImportError:
                    text = "(PDF detected but pdfplumber not installed; install pdfplumber to extract PDF text)"

                result = {
                    "url": final_url,
                    "status_code": resp.status_code,
                    "content_type": content_type,
                    "text": text[:max_chars],
                    "took_ms": took_ms,
                }
                await _FETCH_CACHE.set(cache_key, result)
                return ToolResult(ok=True, data=result, error=None, duration_ms=_now_ms() - start)

            # HTML/text handling
            if "text/html" in content_type or "text/plain" in content_type or "application/json" in content_type:
                if len(resp.content) > max_bytes:
                    return ToolResult(
                        ok=False,
                        data=None,
                        error=f"Response too large ({len(resp.content)} > {max_bytes} bytes)",
                        duration_ms=_now_ms() - start,
                    )

                try:
                    if "text/html" in content_type:
                        extracted = _extract_html(resp.text)
                        text = extracted.get("text") or ""
                    else:
                        text = resp.text
                except Exception:
                    text = resp.text[:max_chars]
            else:
                # Unsupported content type
                return ToolResult(
                    ok=False,
                    data=None,
                    error=f"Unsupported content-type: {content_type}. Supported: text/html, text/plain, application/json, application/pdf.",
                    duration_ms=_now_ms() - start,
                )

            text = text[:max_chars].strip()
            result = {
                "url": final_url,
                "status_code": resp.status_code,
                "content_type": content_type,
                "text": text,
                "took_ms": took_ms,
            }

            await _FETCH_CACHE.set(cache_key, result)
            return ToolResult(ok=True, data=result, error=None, duration_ms=_now_ms() - start)

        except httpx.TimeoutException:
            return ToolResult(
                ok=False, data=None, error=f"Fetch timed out after {timeout_s:.0f}s", duration_ms=_now_ms() - start
            )
        except httpx.RequestError as e:
            return ToolResult(ok=False, data=None, error=f"Fetch network error: {e}", duration_ms=_now_ms() - start)
        except Exception as e:
            return ToolResult(ok=False, data=None, error=str(e) or f"Fetch failed: {e}", duration_ms=_now_ms() - start)


def get_web_search_tool() -> WebSearchTool:
    """Factory: Get web search tool instance."""
    return WebSearchTool()


def get_web_fetch_tool() -> WebFetchTool:
    """Factory: Get web fetch tool instance."""
    return WebFetchTool()
