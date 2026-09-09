"""Bounded evidence collection for explicit read-only web-search requests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

_EXPLICIT_WEB_SEARCH_RE = re.compile(
    r"\b(?:use|call|run)\s+(?:the\s+)?web[._ ]search\b|\bsearch\s+the\s+web\b",
    re.I,
)


@dataclass(frozen=True)
class WebEvidence:
    ok: bool
    text: str
    calls: tuple[str, ...]


def explicit_web_search_requested(prompt: str) -> bool:
    """Return true only for an explicit read-only web-search instruction."""
    return bool(_EXPLICIT_WEB_SEARCH_RE.search(str(prompt or "")))


def _search_query(prompt: str) -> str:
    text = str(prompt or "").strip()
    text = _EXPLICIT_WEB_SEARCH_RE.sub("", text, count=1)
    text = re.sub(r"^\s*(?:now\s+)?(?:to\s+)?find\s+", "", text, flags=re.I)
    text = re.split(
        r"\b(?:answer|respond|return|reply)\s+with\b|\bthis\s+is\s+read-only\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    return text.strip(" .,:;-") or str(prompt or "").strip()


def _source_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.netloc.lower().endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


async def collect_explicit_web_evidence(registry: Any, prompt: str) -> WebEvidence:
    """Search once, fetch up to three results, and return bounded source evidence."""
    if registry is None or not hasattr(registry, "execute"):
        return WebEvidence(False, "Web tools are unavailable.", ())
    calls: list[str] = []
    query = _search_query(prompt)
    search = None
    results: list[Any] = []
    for candidate in (query, f"{query} {datetime.now(timezone.utc):%B %Y}"):
        search = await registry.execute("web.search", {"query": candidate, "count": 8})
        calls.append("web.search")
        if not bool(getattr(search, "ok", False)):
            continue
        data = getattr(search, "data", None)
        results = data.get("results", []) if isinstance(data, dict) else []
        if results:
            break
    if search is None or not bool(getattr(search, "ok", False)):
        return WebEvidence(False, f"web.search failed: {getattr(search, 'error', '')}", tuple(calls))
    normalized: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        normalized.append({**result, "url": _source_url(str(result.get("url") or ""))})

    sections = ["WEB SEARCH RESULTS:\n" + json.dumps(normalized, ensure_ascii=False, default=str)[:6000]]
    fetched = 0
    for result in normalized:
        url = str(result.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        fetch = await registry.execute("web.fetch", {"url": url})
        calls.append("web.fetch")
        if not bool(getattr(fetch, "ok", False)):
            continue
        payload = getattr(fetch, "data", None)
        text = str(payload.get("text") or "") if isinstance(payload, dict) else str(payload or "")
        if not text.strip():
            continue
        sections.append(f"FETCHED SOURCE: {url}\n{text[:7000]}")
        fetched += 1
        if fetched >= 1 or calls.count("web.fetch") >= 3:
            break
        if calls.count("web.fetch") >= 3:
            break

    return WebEvidence(
        bool(normalized),
        "\n\n".join(sections),
        tuple(calls),
    )


__all__ = ["WebEvidence", "collect_explicit_web_evidence", "explicit_web_search_requested"]
