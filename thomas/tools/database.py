# thomas/tools/database.py
"""
Thomas — Feature 10: Database Connector (SQLAlchemy Core)

Facade module for database tools. Imports implementations from:
  - database_safety.py: Query validation and safety checking
  - database_commands.py: Query and schema execution, tool classes

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

import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url

# --- Best-effort imports from Thomas core
try:
    from thomas.tools.base import Tool, ToolResult  # type: ignore
except ImportError:  # pragma: no cover

    class Tool:
        name: str
        category: str
        description: str
        parameters: dict[str, Any]

        async def execute(self, args: dict[str, Any]) -> Any:
            raise NotImplementedError

    @dataclass
    class ToolResult:
        ok: bool
        data: Any = None
        error: str | None = None


# ======================== Connections persistence =============================


def _connections_file_path() -> Path:
    """Get path to connections file."""
    env_path = os.getenv("THOMAS_DB_CONNECTIONS_FILE")
    if env_path:
        return Path(env_path).expanduser().resolve()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "thomas_db_connections.json").resolve()
    except Exception:
        return (Path.home() / ".thomas" / "thomas_db_connections.json").resolve()


def _load_connections_raw() -> dict[str, Any]:
    """Load raw connections from file."""
    path = _connections_file_path()
    if not path.exists():
        return {"version": 1, "connections": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "connections": [], "warning": "failed_to_parse_existing_file"}


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Atomically write JSON to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ======================== Crypto (Fernet) =======================================


def _get_fernet():
    """Get Fernet cipher from THOMAS_DB_KEY."""
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except Exception as e:
        raise RuntimeError("cryptography is required for db.save_connection (pip install cryptography)") from e

    key = os.getenv("THOMAS_DB_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "THOMAS_DB_KEY env var is required (Fernet key). "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise RuntimeError("THOMAS_DB_KEY is invalid. It must be a urlsafe base64-encoded 32-byte Fernet key.") from e


def _decrypt_connection(enc: str) -> str:
    """Decrypt connection string."""
    f = _get_fernet()
    return f.decrypt(enc.encode("utf-8")).decode("utf-8")


def _encrypt_connection(cs: str) -> str:
    """Encrypt connection string."""
    f = _get_fernet()
    return f.encrypt(cs.encode("utf-8")).decode("utf-8")


# ====================== Connection string helpers =============================


def _dialect_from_connection_string(cs: str) -> str:
    """Extract dialect from connection string."""
    return (cs or "").split("://", 1)[0].lower()


def _mask_connection_string(cs: str) -> str:
    """Mask secrets in connection URLs."""
    try:
        u = make_url(cs)
        if u.password:
            u = u.set(password="***")
        return str(u)
    except (ValueError, AttributeError):
        return re.sub(r":([^:@/]+)@", r":***@", cs)


def _sanitize_error_message(msg: str) -> str:
    """Remove credentials from error messages."""
    if not msg:
        return msg
    msg = re.sub(r"://([^:/@\s]+):([^@/\s]+)@", r"://\1:***@", msg)
    msg = re.sub(r":([^:@/\s]+)@", r":***@", msg)
    return msg


def _resolve_saved_connection_alias(connection_string: str) -> str:
    """Resolve saved: aliases to actual connection strings."""
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


# ====================== Engine cache (true LRU) =============================

_ENGINE_LOCK = threading.Lock()
_ENGINE_CACHE: OrderedDict[str, Engine] = OrderedDict()
_ENGINE_CACHE_MAX = int(os.getenv("THOMAS_DB_ENGINE_CACHE_MAX", "16"))


def _is_sqlite(cs: str) -> bool:
    """Check if connection string is SQLite."""
    return cs.strip().lower().startswith("sqlite:")


def _driver_help_message(connection_string: str) -> str:
    """Provide helpful error message for missing drivers."""
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
    """Get or create SQLAlchemy engine (with LRU caching)."""
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
            except (OSError, RuntimeError):
                pass

        kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if _is_sqlite(cs):
            kwargs["connect_args"] = {"check_same_thread": False}

        try:
            eng = create_engine(cs, **kwargs)
        except ModuleNotFoundError as e:
            raise RuntimeError(_driver_help_message(cs)) from e

        _ENGINE_CACHE[cs] = eng
        return eng


# ===================== SQL parsing helpers ====================================

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
    """Remove SQL comments."""
    s = sql or ""
    s = _SQL_BLOCK_COMMENT.sub(" ", s)
    s = _SQL_LINE_COMMENT.sub(" ", s)
    return s


def _strip_strings_and_comments_for_scan(sql: str) -> str:
    """Remove strings and comments for keyword scanning."""
    s = sql or ""
    out: list[str] = []
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
            if in_squote and nxt == "'":
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
    """Detect if SQL contains multiple statements."""
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
    """Classify the main SQL statement (SELECT, INSERT, etc)."""
    scan = _strip_strings_and_comments_for_scan(sql).lstrip()
    if not scan:
        return ""

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

    def flush_token() -> str | None:
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

        t = flush_token()
        if t and depth == 0 and t in _MAIN_VERBS and t != "with":
            return t

        i += 1

    return "with"


def _is_read_only_safe(sql: str) -> tuple[bool, str, list[str]]:
    """Check if statement is read-only safe."""
    reasons: list[str] = []
    main = _classify_main_statement(sql)

    if main not in _ALLOWED_MAIN_STATEMENTS:
        reasons.append(f"main_statement_is_{main or 'unknown'}")
        return False, main, reasons

    scan = _strip_strings_and_comments_for_scan(sql)

    if main == "select":
        if re.search(r"\binto\b", scan):
            reasons.append("select_into_detected")
            return False, main, reasons

        if re.search(r"\bfor\s+update\b", scan) or re.search(r"\bfor\s+share\b", scan):
            reasons.append("locking_select_detected")
            return False, main, reasons

        if re.search(r"\binto\s+outfile\b", scan) or re.search(r"\binto\s+dumpfile\b", scan):
            reasons.append("outfile_dumpfile_detected")
            return False, main, reasons

    return True, main, reasons


def _requires_confirm(sql: str) -> tuple[bool, str, list[str]]:
    """Check if statement requires confirm=true."""
    ok, main, reasons = _is_read_only_safe(sql)
    return (not ok), main, reasons


# ===================== Consumer ergonomics ====================================


def _env_bool(name: str, default: bool) -> bool:
    """Parse environment variable as boolean."""
    v = os.getenv(name, "")
    if v == "":
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")


_AUTO_LIMIT = _env_bool("THOMAS_DB_AUTO_LIMIT", True)
_MAX_CELL_CHARS = int(os.getenv("THOMAS_DB_MAX_CELL_CHARS", "20000"))


def _get_statement_timeout_ms() -> int | None:
    """Get statement timeout from environment."""
    v = os.getenv("THOMAS_DB_STATEMENT_TIMEOUT_MS", "").strip()
    if not v:
        return None
    try:
        ms = int(v)
        return ms if ms > 0 else None
    except (ValueError, TypeError):
        return None


def _truncate_str(s: str) -> tuple[str, bool]:
    """Truncate string with indicator."""
    if _MAX_CELL_CHARS <= 0:
        return s, False
    if len(s) <= _MAX_CELL_CHARS:
        return s, False
    return s[:_MAX_CELL_CHARS] + f"...(truncated {len(s) - _MAX_CELL_CHARS} chars)", True


def _json_safe(v: Any) -> tuple[Any, bool]:
    """Convert value to JSON-safe type."""
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
    except (ImportError, AttributeError):
        pass

    try:
        import decimal as _dec

        if isinstance(v, _dec.Decimal):
            return str(v), False
    except (ImportError, AttributeError):
        pass

    try:
        import uuid as _uuid

        if isinstance(v, _uuid.UUID):
            return str(v), False
    except (ImportError, AttributeError):
        pass

    try:
        if isinstance(v, (dict, list, tuple)):
            s = json.dumps(v, ensure_ascii=False)
            return _truncate_str(s)
    except (TypeError, ValueError):
        pass

    return _truncate_str(str(v))


def _rows_json_safe(rows: list[tuple[Any, ...]]) -> tuple[list[list[Any]], int]:
    """Convert rows to JSON-safe format."""
    out: list[list[Any]] = []
    trunc_cells = 0
    for r in rows:
        rr: list[Any] = []
        for x in r:
            j, t = _json_safe(x)
            rr.append(j)
            if t:
                trunc_cells += 1
        out.append(rr)
    return out, trunc_cells


def _normalize_sql(sql: str) -> str:
    """Normalize SQL formatting."""
    s = (sql or "").strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def _has_limit_or_equivalent(scan: str) -> bool:
    """Check if SQL already has a LIMIT clause."""
    if re.search(r"\blimit\b", scan):
        return True
    if re.search(r"\bfetch\s+first\b", scan):
        return True
    if re.search(r"\btop\s*\(", scan) or re.search(r"\btop\s+\d+", scan):
        return True
    if re.search(r"\boffset\b", scan) and re.search(r"\bfetch\b", scan):
        return True
    return False


def _find_main_select_in_with_sql(original_sql: str) -> tuple[int, int] | None:
    """Find main SELECT in WITH ... SELECT statement."""
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

        if token and depth == 0 and token == "select":
            start = token_start if token_start is not None else i - len(token)
            end = start + len(token)
            return (start, end)

        token = ""
        token_start = None
        i += 1

    return None


def _apply_auto_limit_if_needed(sql: str, eng: Engine, max_rows: int, main_stmt: str) -> tuple[str, bool]:
    """Apply auto-limit if needed."""
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
        if s.lstrip().lower().startswith("with"):
            loc = _find_main_select_in_with_sql(s)
            if loc:
                sel_start, sel_end = loc
                after = s[sel_end:]
                m = re.match(r"(\s+distinct\s+)", after, flags=re.IGNORECASE)
                if m:
                    insert_at = sel_end + m.end()
                    return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True
                insert_at = sel_end + 1
                return s[:sel_end] + f" TOP ({int(max_rows)})" + s[sel_end:], True

        m = re.match(r"^\s*select\s+distinct\s+", s, flags=re.IGNORECASE)
        if m:
            insert_at = m.end()
            return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True

        m2 = re.match(r"^\s*select\s+", s, flags=re.IGNORECASE)
        if m2:
            insert_at = m2.end()
            return s[:insert_at] + f"TOP ({int(max_rows)}) " + s[insert_at:], True

        return s, False

    return f"{s} LIMIT {int(max_rows)}", True


def _apply_dialect_session_guards(conn: Connection, eng: Engine, read_only_session: bool) -> None:
    """Apply database-specific session guards."""
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
    except (OSError, RuntimeError):
        pass


def _reset_mysql_session(conn: Connection, eng: Engine) -> None:
    """Reset MySQL session state."""
    dialect = (getattr(getattr(eng, "dialect", None), "name", "") or "").lower()
    ms = _get_statement_timeout_ms()
    if dialect == "mysql" and ms is not None:
        try:
            conn.execute(text("SET SESSION MAX_EXECUTION_TIME=0"))
        except (OSError, RuntimeError):
            pass


# ======================== Tool classes ========================================
# These are imported from database_commands for actual implementation
# The facade re-exports them for backward compatibility


def get_tools() -> list[Tool]:
    """Get all database tools."""
    from .database_commands import DBConnectionsTool, DBQueryTool, DBSaveConnectionTool, DBSchemaTool

    return [
        DBQueryTool(),
        DBSchemaTool(),
        DBConnectionsTool(),
        DBSaveConnectionTool(),
    ]
