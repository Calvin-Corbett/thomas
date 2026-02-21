# thomas/tools/database.py
"""
Thomas — Feature 10: Database Connector (SQLAlchemy Core)

Tools:
  - db.query            Execute SQL (read-only by default; confirm=true required for writes)
  - db.schema           Inspect schema (tables/columns; optionally detailed)
  - db.connections      List saved named connections (safe metadata only)
  - db.save_connection  Save a named connection encrypted with Fernet

"Best v5" — meaningful, consumer-grade improvements (what people actually feel):
  ✅ 1) WITH/CTE support (huge UX bug fix)
     - Most real SQL starts with WITH. Prior versions blocked these.
     - v5 classifies the *main statement* (SELECT/INSERT/...) even when prefixed by CTEs.

  ✅ 2) Safer + clearer READ ONLY mode
     - Allowlist is based on main statement type, not first token.
     - Hardened SELECT variants that can write/lock now require confirm=true:
       * SELECT ... INTO (table) (Postgres)
       * INTO OUTFILE/DUMPFILE (MySQL)
       * FOR UPDATE/SHARE (locks rows)

  ✅ 3) Auto-limit that works with CTEs + MSSQL TOP
     - If query is SELECT and no LIMIT/TOP/FETCH present, inject a limit derived from max_rows.
     - Handles WITH ... SELECT ... and MSSQL CTE + TOP insertion properly.
     - Default on; disable with THOMAS_DB_AUTO_LIMIT=0.

  ✅ 4) "Explain why" debugging (consumer trust)
     - Optional dry_run=true returns classification + effective SQL (after auto-limit) without executing.
     - The tool can now tell the user *why* it blocked a statement in a structured way.

  ✅ 5) Polished safety + UX details (the boring stuff that matters)
     - True LRU engine cache (bounded).
     - Optional statement timeout (THOMAS_DB_STATEMENT_TIMEOUT_MS) best-effort:
       * Postgres: SET LOCAL statement_timeout + transaction_read_only (read queries)
       * MySQL:   MAX_EXECUTION_TIME (and reset)
     - Big-cell truncation (THOMAS_DB_MAX_CELL_CHARS) with meta warnings.
     - Schema now includes PK/FK/index/unique + views (optional), while keeping base shape compatible.

Notes:
  - SQLAlchemy Core only (no ORM), driver-agnostic.
  - Async-friendly: DB work runs in threads via asyncio.to_thread.
  - Multi-statement SQL is blocked (no "SELECT ...; DROP ...").
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

# --- Best-effort imports from Thomas core ------------------------------------
try:
    from thomas.tools.base import Tool, ToolResult  # type: ignore
except Exception:  # pragma: no cover
    class Tool:  # minimal fallback for standalone use
        name: str
        category: str
        description: str
        parameters: Dict[str, Any]

        async def execute(self, args: Dict[str, Any]) -> Any:
            raise NotImplementedError

    @dataclass
    class ToolResult:  # minimal fallback shape
        ok: bool
        data: Any = None
        error: Optional[str] = None


def _tool_ok(data: Any) -> Any:
    try:
        return ToolResult(ok=True, data=data)  # type: ignore[arg-type]
    except Exception:
        return {"ok": True, "data": data}


def _tool_err(msg: str) -> Any:
    try:
        return ToolResult(ok=False, error=msg)  # type: ignore[arg-type]
    except Exception:
        return {"ok": False, "error": msg}


# =============================================================================
# Connections persistence
# =============================================================================
def _connections_file_path() -> Path:
    # Requirement: reads from thomas_db_connections.json
    return Path(os.getenv("THOMAS_DB_CONNECTIONS_FILE", "thomas_db_connections.json")).resolve()


def _load_connections_raw() -> Dict[str, Any]:
    path = _connections_file_path()
    if not path.exists():
        return {"version": 1, "connections": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "connections": [], "warning": "failed_to_parse_existing_file"}


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# =============================================================================
# Crypto (Fernet)
# =============================================================================
def _get_fernet():
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except Exception as e:
        raise RuntimeError("cryptography is required for db.save_connection (pip install cryptography)") from e

    key = os.getenv("THOMAS_DB_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "THOMAS_DB_KEY env var is required (Fernet key). "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise RuntimeError(
            "THOMAS_DB_KEY is invalid. It must be a urlsafe base64-encoded 32-byte Fernet key."
        ) from e


def _decrypt_connection(enc: str) -> str:
    f = _get_fernet()
    return f.decrypt(enc.encode("utf-8")).decode("utf-8")


def _encrypt_connection(cs: str) -> str:
    f = _get_fernet()
    return f.encrypt(cs.encode("utf-8")).decode("utf-8")


# =============================================================================
# Connection string helpers
# =============================================================================
def _dialect_from_connection_string(cs: str) -> str:
    return (cs or "").split("://", 1)[0].lower()


def _mask_connection_string(cs: str) -> str:
    """
    Mask secrets in connection URLs (best-effort).
    """
    try:
        u = make_url(cs)
        if u.password:
            u = u.set(password="***")
        return str(u)
    except Exception:
        return re.sub(r":([^:@/]+)@", r":***@", cs)


def _sanitize_error_message(msg: str) -> str:
    if not msg:
        return msg
    msg = re.sub(r"://([^:/@\s]+):([^@/\s]+)@", r"://\1:***@", msg)
    msg = re.sub(r":([^:@/\s]+)@", r":***@", msg)
    return msg


def _resolve_saved_connection_alias(connection_string: str) -> str:
    """
    Allow using connection_string="saved:<name>" to reference encrypted saved connections.
    """
    cs = (connection_string or "").strip()
    if not cs.lower().startswith("saved:"):
        return cs

    name = cs.split(":", 1)[1].strip()
    if not name:
        raise ValueError('saved connection alias requires a name: connection_string="saved:<name>"')

    raw = _load_connections_raw()
    conns = raw.get("connections", [])
    if not isinstance(conns, list):
        raise ValueError("connections file is malformed")

    for c in conns:
        if isinstance(c, dict) and c.get("name") == name:
            enc = c.get("connection_string_encrypted")
            if not isinstance(enc, str) or not enc:
                raise ValueError(f'saved connection "{name}" is missing encrypted payload')
            return _decrypt_connection(enc)

    raise ValueError(f'saved connection "{name}" not found in {str(_connections_file_path())}')


# =============================================================================
# Engine cache (true LRU)
# =============================================================================
_ENGINE_LOCK = threading.Lock()
_ENGINE_CACHE: "OrderedDict[str, Engine]" = OrderedDict()
_ENGINE_CACHE_MAX = int(os.getenv("THOMAS_DB_ENGINE_CACHE_MAX", "16"))


def _is_sqlite(cs: str) -> bool:
    return cs.strip().lower().startswith("sqlite:")


def _driver_help_message(connection_string: str) -> str:
    dialect = _dialect_from_connection_string(connection_string)
    if dialect.startswith("postgresql"):
        return "PostgreSQL driver missing. Install: psycopg2-binary (or psycopg). Example: pip install psycopg2-binary"
    if dialect.startswith("mysql"):
        return "MySQL driver missing. Install: pymysql. Example: pip install pymysql"
    if dialect.startswith("mssql"):
        return (
            "MSSQL driver missing. Install: pyodbc and ensure an ODBC Driver is installed on the OS. "
            "Example: pip install pyodbc"
        )
    return "Database driver missing or misconfigured."


def _get_engine(connection_string: str) -> Engine:
    cs = _resolve_saved_connection_alias(connection_string).strip()
    if not cs:
        raise ValueError("connection_string is required")

    with _ENGINE_LOCK:
        eng = _ENGINE_CACHE.get(cs)
        if eng is not None:
            _ENGINE_CACHE.move_to_end(cs, last=True)
            return eng

        while len(_ENGINE_CACHE) >= max(1, _ENGINE_CACHE_MAX):
            _, old = _ENGINE_CACHE.popitem(last=False)
            try:
                old.dispose()
            except Exception:
                pass

        kwargs: Dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if _is_sqlite(cs):
            kwargs["connect_args"] = {"check_same_thread": False}

        try:
            eng = create_engine(cs, **kwargs)
        except ModuleNotFoundError as e:
            raise RuntimeError(_driver_help_message(cs)) from e

        _ENGINE_CACHE[cs] = eng
        return eng


# =============================================================================
# SQL parsing helpers (lightweight, but handles WITH/CTEs)
# =============================================================================
_SQL_LINE_COMMENT = re.compile(r"^\s*--.*?$", re.MULTILINE)
_SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

_ALLOWED_MAIN_STATEMENTS = {"select", "show", "describe", "explain"}
_MAIN_VERBS = {
    "select",
    "insert",
    "update",
    "delete",
    "merge",
    "create",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "call",
    "execute",
}


def _strip_comments(sql: str) -> str:
    s = sql or ""
    s = _SQL_BLOCK_COMMENT.sub(" ", s)
    s = _SQL_LINE_COMMENT.sub(" ", s)
    return s


def _strip_strings_and_comments_for_scan(sql: str) -> str:
    """
    Lowercase text with comments removed and string/identifier literals replaced by spaces.
    Helps safe scans without matching inside quotes.
    """
    s = sql or ""
    out: List[str] = []
    in_squote = False
    in_dquote = False
    in_bquote = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append("\n")
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                out.append(" ")
                continue
            i += 1
            continue

        if not (in_squote or in_dquote or in_bquote):
            if ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not (in_dquote or in_bquote):
            if in_squote and nxt == "'":  # escaped ''
                out.append(" ")
                i += 2
                continue
            in_squote = not in_squote
            out.append(" ")
            i += 1
            continue

        if ch == '"' and not (in_squote or in_bquote):
            in_dquote = not in_dquote
            out.append(" ")
            i += 1
            continue

        if ch == "`" and not (in_squote or in_dquote):
            in_bquote = not in_bquote
            out.append(" ")
            i += 1
            continue

        if in_squote or in_dquote or in_bquote:
            out.append(" ")
            i += 1
            continue

        out.append(ch.lower())
        i += 1

    return "".join(out)


def _contains_multiple_statements(sql: str) -> bool:
    """
    Detect semicolons outside of strings/comments to block multi-statement SQL.
    Allows a single trailing semicolon.
    """
    s = sql or ""
    in_squote = False
    in_dquote = False
    in_bquote = False
    in_line_comment = False
    in_block_comment = False

    semicolons = 0
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if not (in_squote or in_dquote or in_bquote):
            if ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if ch == "'" and not (in_dquote or in_bquote):
            if in_squote and nxt == "'":
                i += 2
                continue
            in_squote = not in_squote
            i += 1
            continue

        if ch == '"' and not (in_squote or in_bquote):
            in_dquote = not in_dquote
            i += 1
            continue

        if ch == "`" and not (in_squote or in_dquote):
            in_bquote = not in_bquote
            i += 1
            continue

        if ch == ";" and not (in_squote or in_dquote or in_bquote):
            semicolons += 1

        i += 1

    if semicolons == 0:
        return False

    if semicolons == 1:
        cleaned = _strip_comments(sql)
        last = cleaned.rfind(";")
        if last == -1:
            return False
        trailing = cleaned[last + 1 :].strip()
        return trailing != ""

    return True


def _classify_main_statement(sql: str) -> str:
    """
    Returns the "main verb" of the statement, handling WITH/CTEs.
    Examples:
      - "SELECT ..." -> "select"
      - "WITH x AS (...) SELECT ..." -> "select"
      - "WITH x AS (...) UPDATE ..." -> "update"
    This is not a full SQL parser, but it's good enough to avoid blocking normal CTE reads.
    """
    scan = _strip_strings_and_comments_for_scan(sql).lstrip()
    if not scan:
        return ""

    # quick path
    m = re.match(r"([a-z]+)", scan)
    if not m:
        return ""
    first = m.group(1)
    if first != "with":
        return first

    # WITH: scan tokens at paren depth 0 until we find a main verb
    depth = 0
    token = ""
    i = 0
    n = len(scan)

    def flush_token() -> Optional[str]:
        nonlocal token
        if token:
            t = token
            token = ""
            return t
        return None

    while i < n:
        ch = scan[i]

        if ch == "(":
            depth += 1
            flush_token()
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            flush_token()
            i += 1
            continue

        if ch.isalnum() or ch == "_":
            token += ch
            i += 1
            continue

        # delimiter
        t = flush_token()
        if t and depth == 0 and t in _MAIN_VERBS and t != "with":
            return t

        i += 1

    # If we never found a verb, return "with" as a fallback
    return "with"


def _is_read_only_safe(sql: str) -> Tuple[bool, str, List[str]]:
    """
    Decide read-only safety based on the main statement verb, with hardening.
    Returns (is_safe, main_statement, reasons[])
    """
    reasons: List[str] = []
    main = _classify_main_statement(sql)

    if main not in _ALLOWED_MAIN_STATEMENTS:
        reasons.append(f"main_statement_is_{main or 'unknown'}")
        return False, main, reasons

    scan = _strip_strings_and_comments_for_scan(sql)

    # Hardened checks for SELECT (including WITH ... SELECT)
    if main == "select":
        # Prevent write-y variants:
        if re.search(r"\binto\b", scan):
            reasons.append("select_into_detected")
            return False, main, reasons

        # Prevent locking reads:
        if re.search(r"\bfor\s+update\b", scan) or re.search(r"\bfor\s+share\b", scan):
            reasons.append("locking_select_detected")
            return False, main, reasons

        # Prevent export-to-file on MySQL-like syntaxes
        if re.search(r"\binto\s+outfile\b", scan) or re.search(r"\binto\s+dumpfile\b", scan):
            reasons.append("outfile_dumpfile_detected")
            return False, main, reasons

    return True, main, reasons


def _requires_confirm(sql: str) -> Tuple[bool, str, List[str]]:
    ok, main, reasons = _is_read_only_safe(sql)
    return (not ok), main, reasons


# =============================================================================
# Consumer ergonomics: auto-limit + timeouts + size guards + dry-run
# =============================================================================
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "")
    if v == "":
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")


_AUTO_LIMIT = _env_bool("THOMAS_DB_AUTO_LIMIT", True)
_MAX_CELL_CHARS = int(os.getenv("THOMAS_DB_MAX_CELL_CHARS", "20000"))


def _get_statement_timeout_ms() -> Optional[int]:
    v = os.getenv("THOMAS_DB_STATEMENT_TIMEOUT_MS", "").strip()
    if not v:
        return None
    try:
        ms = int(v)
        return ms if ms > 0 else None
    except Exception:
        return None


def _truncate_str(s: str) -> Tuple[str, bool]:
    if _MAX_CELL_CHARS <= 0:
        return s, False
    if len(s) <= _MAX_CELL_CHARS:
        return s, False
    return s[: _MAX_CELL_CHARS] + f"...(truncated {len(s) - _MAX_CELL_CHARS} chars)", True


def _json_safe(v: Any) -> Tuple[Any, bool]:
    if v is None:
        return None, False
    if isinstance(v, (bool, int, float)):
        return v, False
    if isinstance(v, str):
        return _truncate_str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        preview = b[:32].hex()
        suffix = "" if len(b) <= 32 else f"...(+{len(b)-32} bytes)"
        return f"0x{preview}{suffix}", False

    try:
        import datetime as _dt
        if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
            return v.isoformat(), False
    except Exception:
        pass

    try:
        import decimal as _dec
        if isinstance(v, _dec.Decimal):
            return str(v), False
    except Exception:
        pass

    try:
        import uuid as _uuid
        if isinstance(v, _uuid.UUID):
            return str(v), False
    except Exception:
        pass

    try:
        if isinstance(v, (dict, list, tuple)):
            s = json.dumps(v, ensure_ascii=False)
            return _truncate_str(s)
    except Exception:
        pass

    return _truncate_str(str(v))


def _rows_json_safe(rows: List[Tuple[Any, ...]]) -> Tuple[List[List[Any]], int]:
    out: List[List[Any]] = []
    trunc_cells = 0
    for r in rows:
        rr: List[Any] = []
        for x in r:
            j, t = _json_safe(x)
            rr.append(j)
            if t:
                trunc_cells += 1
        out.append(rr)
    return out, trunc_cells


def _normalize_sql(sql: str) -> str:
    s = (sql or "").strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def _has_limit_or_equivalent(scan: str) -> bool:
    # Covers LIMIT, FETCH FIRST, TOP, OFFSET ... FETCH (coarse)
    if re.search(r"\blimit\b", scan):
        return True
    if re.search(r"\bfetch\s+first\b", scan):
        return True
    if re.search(r"\btop\s*\(", scan) or re.search(r"\btop\s+\d+", scan):
        return True
    if re.search(r"\boffset\b", scan) and re.search(r"\bfetch\b", scan):
        return True
    return False


def _find_main_select_in_with_sql(original_sql: str) -> Optional[Tuple[int, int]]:
    """
    For SQL starting with WITH, find the first 'select' token at paren depth 0.
    Returns (start_index, end_index) in the *original_sql* string for the token.
    This is used for MSSQL TOP insertion with CTEs.
    """
    scan = _strip_strings_and_comments_for_scan(original_sql)
    if not scan.lstrip().startswith("with"):
        return None

    depth = 0
    token = ""
    token_start = None

    i = 0
    n = len(scan)

    while i < n:
        ch = scan[i]

        if ch == "(":
            depth += 1
            token = ""
            token_start = None
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            token = ""
            token_start = None
            i += 1
            continue

        if ch.isalnum() or ch == "_":
            if token_start is None:
                token_start = i
            token += ch
            i += 1
            continue

        # delimiter: flush token
        if token and depth == 0 and token == "select":
            # Map scan indices to original_sql indices: scan preserves length.
            start = token_start if token_start is not None else i - len(token)
            end = start + len(token)
            return (start, end)

        token = ""
        token_start = None
        i += 1

    return None


def _apply_auto_limit_if_needed(sql: str, eng: Engine, max_rows: int, main_stmt: str) -> Tuple[str, bool]:
    """
    If enabled and main statement is SELECT, and there's no explicit limiting,
    inject a limit derived from max_rows.
    """
    if not _AUTO_LIMIT:
        return sql, False
    if main_stmt != "select":
        return sql, False

    scan = _strip_strings_and_comments_for_scan(sql)
    if _has_limit_or_equivalent(scan):
        return sql, False

    dialect = (getattr(getattr(eng, "dialect", None), "name", "") or "").lower()
    s = _normalize_sql(sql)

    if dialect == "mssql":
        # Insert TOP after the main SELECT (or SELECT DISTINCT), including WITH/CTE queries.
        if s.lstrip().lower().startswith("with"):
            loc = _find_main_select_in_with_sql(s)
            if loc:
                sel_start, sel_end = loc
                # Look ahead after SELECT for DISTINCT (ignoring whitespace)
                after = s[sel_end:]
                m = re.match(r"(\s+distinct\s+)", after, flags=re.IGNORECASE)
                if m:
                    insert_at = sel_end + m.end()
                    return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True
                insert_at = sel_end + 1  # after 'select' token and following space gets normalized by our insert
                return s[:sel_end] + f" TOP ({int(max_rows)})" + s[sel_end:], True

        # Non-CTE MSSQL: simple regex
        m = re.match(r"^\s*select\s+distinct\s+", s, flags=re.IGNORECASE)
        if m:
            insert_at = m.end()
            return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True

        m2 = re.match(r"^\s*select\s+", s, flags=re.IGNORECASE)
        if m2:
            insert_at = m2.end()
            return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True

        return s, False

    # Postgres/MySQL/SQLite: append LIMIT
    return f"{s} LIMIT {int(max_rows)}", True


def _apply_dialect_session_guards(conn: Connection, eng: Engine, read_only_session: bool) -> None:
    """
    Best-effort: apply statement timeout and read-only guards where safe.
    - Postgres: SET LOCAL statement_timeout; SET LOCAL transaction_read_only
    - MySQL: MAX_EXECUTION_TIME session setting for the duration of the transaction
    """
    dialect = (getattr(getattr(eng, "dialect", None), "name", "") or "").lower()
    ms = _get_statement_timeout_ms()

    try:
        if dialect == "postgresql":
            if ms is not None:
                conn.execute(text(f"SET LOCAL statement_timeout = {int(ms)}"))
            if read_only_session:
                conn.execute(text("SET LOCAL transaction_read_only = on"))
        elif dialect == "mysql":
            if ms is not None:
                conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME={int(ms)}"))
    except Exception:
        pass


def _reset_mysql_session(conn: Connection, eng: Engine) -> None:
    dialect = (getattr(getattr(eng, "dialect", None), "name", "") or "").lower()
    ms = _get_statement_timeout_ms()
    if dialect == "mysql" and ms is not None:
        try:
            conn.execute(text("SET SESSION MAX_EXECUTION_TIME=0"))
        except Exception:
            pass


# =============================================================================
# Sync DB workers (wrapped by asyncio.to_thread)
# =============================================================================
def _query_sync(
    connection_string: str,
    sql: str,
    params_obj: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]],
    max_rows: int,
    confirm: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    eng = _get_engine(connection_string)
    started = time.perf_counter()

    requires_confirm, main_stmt, ro_reasons = _requires_confirm(sql)
    read_only = not requires_confirm

    # Compute effective SQL (auto-limit). This is useful for dry-run and meta transparency.
    sql_exec, auto_limited = _apply_auto_limit_if_needed(sql, eng, max_rows, main_stmt)

    meta: Dict[str, Any] = {
        "main_statement": main_stmt or None,
        "read_only": bool(read_only),
        "confirm": bool(confirm),
        "requires_confirm": bool(requires_confirm),
        "read_only_block_reasons": ro_reasons,
        "auto_limit_applied": bool(auto_limited),
        "max_rows": int(max_rows),
        "truncated_cells": 0,
        "statement_timeout_ms": _get_statement_timeout_ms(),
        "dialect": (getattr(getattr(eng, "dialect", None), "name", "") or None),
        "warnings": [],
        "effective_sql": sql_exec if dry_run else None,  # only reveal when dry-run
        "dry_run": bool(dry_run),
    }

    if dry_run:
        duration_ms = (time.perf_counter() - started) * 1000.0
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "duration_ms": float(duration_ms),
            "meta": meta,
        }

    # Execute inside a transaction block always, so SET LOCAL works (Postgres).
    with eng.begin() as conn:
        # For read-only sessions, enforce read-only at session level when supported
        _apply_dialect_session_guards(conn, eng, read_only_session=read_only and not confirm)

        result = conn.execute(text(sql_exec), params_obj or {})

        columns = list(result.keys()) if result.returns_rows else []
        rows_out: List[List[Any]] = []
        trunc_cells = 0

        if result.returns_rows:
            fetched = result.fetchmany(size=max_rows)
            rows_out, trunc_cells = _rows_json_safe(fetched)
            row_count = len(rows_out)
        else:
            rc = getattr(result, "rowcount", None)
            row_count = int(rc) if isinstance(rc, int) and rc >= 0 else 0

        _reset_mysql_session(conn, eng)

    duration_ms = (time.perf_counter() - started) * 1000.0
    meta["truncated_cells"] = int(trunc_cells)
    if trunc_cells > 0:
        meta["warnings"].append("some_cells_truncated")
    if auto_limited:
        meta["warnings"].append("auto_limit_applied")

    return {
        "columns": columns,
        "rows": rows_out,
        "row_count": int(row_count),
        "duration_ms": float(duration_ms),
        "meta": meta,
    }


def _schema_sync(
    connection_string: str,
    table: Optional[str],
    include_views: bool,
    detailed: bool,
    pattern: Optional[str],
) -> Dict[str, Any]:
    eng = _get_engine(connection_string)
    insp = inspect(eng)

    def split_schema_table(t: str) -> Tuple[Optional[str], str]:
        t = t.strip()
        if "." in t:
            schema, name = t.split(".", 1)
            schema = schema.strip() or None
            name = name.strip()
            return schema, name
        return None, t

    default_schema = getattr(insp, "default_schema_name", None)
    if not default_schema:
        default_schema = getattr(getattr(eng, "dialect", None), "default_schema_name", None)

    def matches(name: str) -> bool:
        if not pattern:
            return True
        # simple glob-like: '*' supported
        pat = pattern.strip()
        if not pat:
            return True
        regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
        return re.match(regex, name, flags=re.IGNORECASE) is not None

    def table_payload(schema: Optional[str], tbl: str, is_view: bool) -> Dict[str, Any]:
        cols = insp.get_columns(tbl, schema=schema)
        payload: Dict[str, Any] = {
            "name": f"{schema}.{tbl}" if (schema and schema != default_schema) else tbl,
            "columns": [
                {"name": c.get("name"), "type": str(c.get("type")), "nullable": bool(c.get("nullable", True))}
                for c in cols
            ],
        }
        if not detailed:
            return payload

        # Additive goodies (best-effort)
        payload["table_type"] = "view" if is_view else "table"

        try:
            pk = insp.get_pk_constraint(tbl, schema=schema) or {}
            payload["primary_key"] = pk.get("constrained_columns", []) or []
        except Exception:
            payload["primary_key"] = []

        try:
            fks = insp.get_foreign_keys(tbl, schema=schema) or []
            payload["foreign_keys"] = [
                {
                    "constrained_columns": fk.get("constrained_columns") or [],
                    "referred_schema": fk.get("referred_schema"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns") or [],
                    "name": fk.get("name"),
                }
                for fk in fks
            ]
        except Exception:
            payload["foreign_keys"] = []

        try:
            idx = insp.get_indexes(tbl, schema=schema) or []
            payload["indexes"] = [
                {"name": i.get("name"), "unique": bool(i.get("unique", False)), "columns": i.get("column_names") or []}
                for i in idx
            ]
        except Exception:
            payload["indexes"] = []

        try:
            uq = insp.get_unique_constraints(tbl, schema=schema) or []
            payload["unique_constraints"] = [{"name": u.get("name"), "columns": u.get("column_names") or []} for u in uq]
        except Exception:
            payload["unique_constraints"] = []

        return payload

    tables_out: List[Dict[str, Any]] = []

    if table:
        schema, tbl = split_schema_table(table)
        if schema is None:
            schema = default_schema
        is_view = False
        try:
            if include_views and schema is not None:
                is_view = tbl in (insp.get_view_names(schema=schema) or [])
        except Exception:
            pass
        tables_out.append(table_payload(schema, tbl, is_view=is_view))
        return {"tables": tables_out}

    # All tables: include schemas when supported
    try:
        schemas = insp.get_schema_names()
    except Exception:
        schemas = [default_schema] if default_schema else [None]  # type: ignore[list-item]

    filtered: List[Optional[str]] = []
    for s in schemas:
        if s is None:
            filtered.append(None)
            continue
        sl = str(s).lower()
        if sl in ("information_schema", "pg_catalog", "sys"):
            continue
        filtered.append(str(s))

    seen: set = set()
    for s in filtered:
        try:
            tbls = insp.get_table_names(schema=s)
        except Exception:
            tbls = insp.get_table_names()

        views: List[str] = []
        if include_views:
            try:
                views = insp.get_view_names(schema=s) or []
            except Exception:
                views = []

        for tbl in tbls:
            display = f"{s}.{tbl}" if (s and s != default_schema) else tbl
            if not matches(display):
                continue
            key = (s or "", tbl, "table")
            if key in seen:
                continue
            seen.add(key)
            tables_out.append(table_payload(s, tbl, is_view=False))

        for v in views:
            display = f"{s}.{v}" if (s and s != default_schema) else v
            if not matches(display):
                continue
            key = (s or "", v, "view")
            if key in seen:
                continue
            seen.add(key)
            tables_out.append(table_payload(s, v, is_view=True))

    return {"tables": tables_out}


# =============================================================================
# Tools
# =============================================================================
class DBQueryTool(Tool):
    name = "db.query"
    category = "database"
    description = "Execute a SQL statement using SQLAlchemy Core (read-only by default)."
    parameters = {
        "type": "object",
        "properties": {
            "connection_string": {
                "type": "string",
                "description": (
                    "SQLAlchemy URL (e.g. postgresql://user:pass@host/db) "
                    'or "saved:<name>" to use an encrypted saved connection.'
                ),
            },
            "sql": {"type": "string", "description": "SQL to execute (single statement)"},
            "params": {
                "description": "Optional bind parameters (dict) or list[dict] for executemany.",
                "oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}],
            },
            "max_rows": {"type": "integer", "default": 100, "maximum": 1000},
            "confirm": {"type": "boolean", "default": False, "description": "Required for non-read-only statements."},
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "If true, do not execute. Return classification + effective SQL (after auto-limit).",
            },
        },
        "required": ["connection_string", "sql"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any]) -> Any:
        try:
            connection_string = str(args.get("connection_string") or "").strip()
            sql = str(args.get("sql") or "")
            confirm = bool(args.get("confirm", False))
            dry_run = bool(args.get("dry_run", False))

            max_rows = args.get("max_rows", 100)
            try:
                max_rows = int(max_rows)
            except Exception:
                max_rows = 100
            max_rows = max(1, min(1000, max_rows))

            params_val = args.get("params")
            params_obj: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
            if isinstance(params_val, dict):
                params_obj = params_val
            elif isinstance(params_val, list) and all(isinstance(x, dict) for x in params_val):
                params_obj = params_val

            if not connection_string:
                return _tool_err("connection_string is required")
            if not sql.strip():
                return _tool_err("sql is required")

            if _contains_multiple_statements(sql):
                return _tool_err("Multi-statement SQL is blocked. Send a single statement at a time.")

            requires_confirm, main_stmt, ro_reasons = _requires_confirm(sql)
            if requires_confirm and not confirm and not dry_run:
                kw = (main_stmt or "unknown").upper()
                hint = ""
                if ro_reasons:
                    hint = f" Reasons: {', '.join(ro_reasons)}."
                return _tool_err(
                    f"READ ONLY mode blocked this statement (main statement: {kw})."
                    f"{hint} Pass confirm=true to allow."
                )

            data = await asyncio.to_thread(_query_sync, connection_string, sql, params_obj, max_rows, confirm, dry_run)
            return _tool_ok(data)

        except RuntimeError as e:
            return _tool_err(_sanitize_error_message(str(e)))
        except (ValueError, TypeError) as e:
            return _tool_err(str(e))
        except SQLAlchemyError as e:
            return _tool_err(f"Database error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")
        except Exception as e:
            return _tool_err(f"Unexpected error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")


class DBSchemaTool(Tool):
    name = "db.schema"
    category = "database"
    description = "Get schema info for a database (tables + columns)."
    parameters = {
        "type": "object",
        "properties": {
            "connection_string": {"type": "string", "description": 'SQLAlchemy URL or "saved:<name>"'},
            "table": {"type": "string", "description": "Optional table name (supports schema.table)"},
            "include_views": {"type": "boolean", "default": True, "description": "Include views when table omitted."},
            "detailed": {
                "type": "boolean",
                "default": False,
                "description": "Include PK/FK/index/unique + table_type when available (additive).",
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter tables when table omitted (e.g. '*user*').",
            },
        },
        "required": ["connection_string"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any]) -> Any:
        try:
            connection_string = str(args.get("connection_string") or "").strip()
            table = args.get("table")
            table_s = str(table).strip() if isinstance(table, str) and table.strip() else None
            include_views = bool(args.get("include_views", True))
            detailed = bool(args.get("detailed", False))
            pattern = args.get("pattern")
            pattern_s = str(pattern).strip() if isinstance(pattern, str) and pattern.strip() else None

            if not connection_string:
                return _tool_err("connection_string is required")

            data = await asyncio.to_thread(_schema_sync, connection_string, table_s, include_views, detailed, pattern_s)
            return _tool_ok(data)

        except RuntimeError as e:
            return _tool_err(_sanitize_error_message(str(e)))
        except (ValueError, TypeError) as e:
            return _tool_err(str(e))
        except SQLAlchemyError as e:
            return _tool_err(f"Database error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")
        except Exception as e:
            return _tool_err(f"Unexpected error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")


class DBConnectionsTool(Tool):
    name = "db.connections"
    category = "database"
    description = "List saved named DB connections from thomas_db_connections.json (metadata only)."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, args: Dict[str, Any]) -> Any:
        try:
            raw = _load_connections_raw()
            conns = raw.get("connections", [])
            out: List[Dict[str, Any]] = []

            for c in conns if isinstance(conns, list) else []:
                if not isinstance(c, dict):
                    continue
                name = c.get("name")
                out.append(
                    {
                        "name": name,
                        "dialect": c.get("dialect"),
                        "masked_connection_string": c.get("masked_connection_string"),
                        "updated_at": c.get("updated_at"),
                        "created_at": c.get("created_at"),
                        "usage": f"saved:{name}" if name else None,
                    }
                )

            # Sort by name for consistent UX
            out.sort(key=lambda x: (x.get("name") or "").lower())

            return _tool_ok({"connections": out, "file": str(_connections_file_path())})

        except Exception as e:
            return _tool_err(f"Unexpected error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")


class DBSaveConnectionTool(Tool):
    name = "db.save_connection"
    category = "database"
    description = "Save a named DB connection encrypted with Fernet (THOMAS_DB_KEY)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "connection_string": {"type": "string", "description": "SQLAlchemy URL (encrypted at rest)"},
            "test": {"type": "boolean", "default": False, "description": "Optionally test the connection before saving."},
        },
        "required": ["name", "connection_string"],
        "additionalProperties": False,
    }

    async def execute(self, args: Dict[str, Any]) -> Any:
        try:
            name = str(args.get("name") or "").strip()
            cs = str(args.get("connection_string") or "").strip()
            test = bool(args.get("test", False))

            if not name:
                return _tool_err("name is required")
            if not cs:
                return _tool_err("connection_string is required")

            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
                return _tool_err("Invalid name. Use 1-64 chars: letters, numbers, underscore, dot, dash.")

            if test:
                try:
                    eng = _get_engine(cs)
                    with eng.connect() as conn:
                        conn.execute(text("SELECT 1"))
                except Exception as e:
                    return _tool_err(f"Connection test failed: {_sanitize_error_message(str(e))}")

            enc = _encrypt_connection(cs)
            dialect = _dialect_from_connection_string(cs)
            masked = _mask_connection_string(cs)

            path = _connections_file_path()
            raw = _load_connections_raw()
            if not isinstance(raw.get("connections"), list):
                raw["connections"] = []

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            updated = False
            for c in raw["connections"]:
                if isinstance(c, dict) and c.get("name") == name:
                    c["connection_string_encrypted"] = enc
                    c["dialect"] = dialect
                    c["masked_connection_string"] = masked
                    c["updated_at"] = now
                    updated = True
                    break

            if not updated:
                raw["connections"].append(
                    {
                        "name": name,
                        "dialect": dialect,
                        "masked_connection_string": masked,
                        "connection_string_encrypted": enc,
                        "created_at": now,
                        "updated_at": now,
                    }
                )

            raw["version"] = int(raw.get("version", 1) or 1)
            _atomic_write_json(path, raw)

            return _tool_ok(
                {
                    "saved": True,
                    "name": name,
                    "dialect": dialect,
                    "masked_connection_string": masked,
                    "file": str(path),
                    "usage": f'set connection_string="saved:{name}"',
                }
            )

        except RuntimeError as e:
            return _tool_err(_sanitize_error_message(str(e)))
        except Exception as e:
            return _tool_err(f"Unexpected error: {e.__class__.__name__}: {_sanitize_error_message(str(e))}")


TOOLS = [DBQueryTool(), DBSchemaTool(), DBConnectionsTool(), DBSaveConnectionTool()]
