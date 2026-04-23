from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    """
    Consumer-grade search hit.

    - turn_id: stable id (hash of ts/channel/user/assistant/tools)
    - turn_pos: best-effort index in persistence.turn_history at time of indexing
    - snippets include HL markers matching SQLite tokenization
    - score combines bm25 relevance + soft recency boost
    """

    turn_id: str
    turn_pos: int
    ts: str
    channel: str
    user_msg: str
    user_snippet: str
    assistant_snippet: str
    assistant_snippet_plain: str
    rank: float
    score: float


@dataclass(frozen=True)
class TurnContext:
    turn_id: str
    turn_pos: int
    ts: str
    channel: str
    user_msg: str
    assistant_msg: str
    tool_calls: str


@dataclass(frozen=True)
class Bookmark:
    turn_id: str
    label: str
    created_ts: str


@dataclass(frozen=True)
class SavedSearch:
    id: int
    name: str
    query: str
    filters_json: str
    created_ts: str
    last_used_ts: str
    use_count: int


def _safe_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        return str(x)


def _norm_ts(ts: Any) -> str:
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.isoformat()
    s = str(ts).strip()
    if not s:
        return ""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s + "T00:00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except Exception:
        return s


def _parse_ts(ts: str) -> datetime | None:
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # last resort: date only
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                return datetime.fromisoformat(s + "T00:00:00+00:00")
        except Exception:
            return None
    return None


def _turn_fingerprint(ts: str, channel: str, user_msg: str, assistant_msg: str, tool_calls: str) -> str:
    payload = (ts + "\n" + channel + "\n" + user_msg + "\n" + assistant_msg + "\n" + tool_calls).encode(
        "utf-8", "ignore"
    )
    return hashlib.sha1(payload).hexdigest()


def _turn_id(fp: str) -> str:
    return fp[:20]


def _looks_like_fts_syntax(q: str) -> bool:
    uq = q.upper()
    return (
        '"' in q
        or ":" in q
        or "*" in q
        or "(" in q
        or ")" in q
        or " OR " in uq
        or " AND " in uq
        or " NOT " in uq
        or " NEAR" in uq
    )


def _to_prefix_query(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return ""
    if _looks_like_fts_syntax(q):
        return q
    parts = [p.strip() for p in q.split() if p.strip()]
    cooked = []
    for p in parts:
        p = p.replace('"', "").replace("'", "")
        cooked.append(f"{p}*")
    return " AND ".join(cooked)


def _scoped_query(q: str, scopes: set[str]) -> str:
    """
    Build a scoped FTS query that works well for consumers:
    - if scopes = {"all"} return q
    - else, for each term, OR it across selected columns, AND across terms

    Example: query="truck invoice"
      scopes={"user","assistant"} ->
        (user_msg:truck* OR assistant_msg:truck*) AND (user_msg:invoice* OR assistant_msg:invoice*)
    """

    cooked = _to_prefix_query(q)
    if not cooked:
        return ""

    if "all" in scopes or not scopes:
        return cooked

    # If user provided explicit FTS syntax, do not rewrite.
    if _looks_like_fts_syntax(q):
        # If they also used explicit column syntax, assume they know what they're doing.
        return q

    terms = [t.strip() for t in q.split() if t.strip()]
    # Very small terms can produce huge match sets with prefix; keep but allow.
    cols = []
    if "user" in scopes:
        cols.append("user_msg")
    if "assistant" in scopes:
        cols.append("assistant_msg")
    if "tools" in scopes:
        cols.append("tool_calls")

    if not cols:
        return cooked

    def term_clause(term: str) -> str:
        t = term.replace('"', "").replace("'", "") + "*"
        ors = [f"{c}:{t}" for c in cols]
        return "(" + " OR ".join(ors) + ")"

    clauses = [term_clause(t) for t in terms]
    return " AND ".join(clauses)
