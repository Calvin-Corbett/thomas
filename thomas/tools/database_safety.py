"""Database query validation and safety checking.

Handles:
  - SQL parsing and classification
  - Read-only mode enforcement
  - Dangerous operation detection
  - Statement type detection (SELECT, INSERT, etc.)
  - CTE (WITH clause) handling
"""

from __future__ import annotations

import re
from typing import Any


def _strip_comments(sql: str) -> str:
    """Remove SQL comments (-- and /* */)."""
    # Remove -- comments
    sql = re.sub(r"--[^\n]*\n", "\n", sql)
    # Remove /* */ comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def _strip_strings_and_comments_for_scan(sql: str) -> str:
    """
    Remove strings and comments for keyword scanning.
    This is a best-effort approach; edge cases may exist.
    """
    result = []
    i = 0
    while i < len(sql):
        # Skip /* */ comments
        if sql[i : i + 2] == "/*":
            j = sql.find("*/", i + 2)
            if j != -1:
                result.append(" ")
                i = j + 2
                continue
            i += 2
            continue

        # Skip -- comments (rest of line)
        if sql[i : i + 2] == "--":
            j = sql.find("\n", i + 2)
            if j != -1:
                result.append("\n")
                i = j + 1
                continue
            i = len(sql)
            continue

        # Skip 'strings'
        if sql[i] == "'":
            j = i + 1
            while j < len(sql):
                if sql[j] == "'":
                    if j + 1 < len(sql) and sql[j + 1] == "'":
                        j += 2  # '' escape
                        continue
                    break
                j += 1
            result.append("'S'")
            i = j + 1 if j < len(sql) else len(sql)
            continue

        # Skip "strings" (identifiers)
        if sql[i] == '"':
            j = i + 1
            while j < len(sql):
                if sql[j] == '"':
                    if j + 1 < len(sql) and sql[j + 1] == '"':
                        j += 2  # "" escape
                        continue
                    break
                j += 1
            result.append('"I"')
            i = j + 1 if j < len(sql) else len(sql)
            continue

        # Skip `identifiers` (MySQL)
        if sql[i] == "`":
            j = i + 1
            while j < len(sql):
                if sql[j] == "`":
                    if j + 1 < len(sql) and sql[j + 1] == "`":
                        j += 2  # `` escape
                        continue
                    break
                j += 1
            result.append("`I`")
            i = j + 1 if j < len(sql) else len(sql)
            continue

        result.append(sql[i])
        i += 1

    return "".join(result)


def _contains_multiple_statements(sql: str) -> bool:
    """
    Detect if SQL contains multiple statements (naive check).
    Look for semicolons outside strings/comments.
    """
    scan = _strip_strings_and_comments_for_scan(sql)
    # Count semicolons (but not at very end)
    semis = [i for i, c in enumerate(scan) if c == ";"]
    if not semis:
        return False
    # Allow one trailing semicolon
    if len(semis) == 1 and semis[0] == len(scan.rstrip()) - 1:
        return False
    return len(semis) > 1 or (len(semis) == 1 and semis[0] < len(scan.rstrip()) - 1)


def _classify_main_statement(sql: str) -> str:
    """
    Classify the main SQL statement (SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, etc.).
    Handles WITH (CTE) prefixes.
    """
    scan = _strip_strings_and_comments_for_scan(sql).strip().upper()

    # Strip leading WITH ... SELECT / INSERT / etc.
    with_match = re.match(
        r"WITH\s+.*?\s+(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|MERGE|CALL|TRUNCATE)", scan, re.DOTALL
    )
    if with_match:
        return with_match.group(1).strip()

    # Simple match
    for stmt_type in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "MERGE", "CALL", "TRUNCATE"]:
        if re.match(rf"{stmt_type}\b", scan):
            return stmt_type

    return "UNKNOWN"


def _is_read_only_safe(sql: str) -> tuple[bool, str, list[str]]:
    """
    Check if a SQL statement is safe for read-only execution.
    Returns (is_safe, classification, reasons_if_unsafe).
    """
    scan = _strip_strings_and_comments_for_scan(sql).strip().upper()
    main_stmt = _classify_main_statement(sql)

    # Safe read-only statements
    if main_stmt == "SELECT":
        # Check for dangerous SELECT variants
        if "INTO" in scan:
            return False, main_stmt, ["SELECT ... INTO creates/populates tables (Postgres)"]
        if "FOR UPDATE" in scan or "FOR SHARE" in scan:
            return False, main_stmt, ["SELECT ... FOR UPDATE/SHARE locks rows"]
        return True, main_stmt, []

    if main_stmt == "WITH":
        return True, "WITH", []

    if main_stmt in ("CALL", "EXPLAIN", "DESCRIBE", "DESC", "SHOW"):
        return True, main_stmt, []

    return False, main_stmt, [f"{main_stmt} statement may write/modify data"]


def _requires_confirm(sql: str) -> tuple[bool, str, list[str]]:
    """
    Detect write operations that require explicit confirm=true.
    Returns (needs_confirm, classification, reasons_if_yes).
    """
    main_stmt = _classify_main_statement(sql)

    if main_stmt in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE", "MERGE"):
        return True, main_stmt, ["Write operation requires confirm=true"]

    # SELECT is normally read-only, but check for edge cases
    is_safe, _, reasons = _is_read_only_safe(sql)
    if not is_safe:
        return True, "SELECT (unsafe)", reasons

    return False, main_stmt, []


def _env_bool(name: str, default: bool) -> bool:
    """Parse environment variable as boolean."""
    import os

    val = os.environ.get(name, "").lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return default


def _get_statement_timeout_ms() -> int | None:
    """Get statement timeout from environment, if configured."""
    import os

    val = os.environ.get("THOMAS_DB_STATEMENT_TIMEOUT_MS", "").strip()
    if val:
        try:
            ms = int(val)
            return ms if ms > 0 else None
        except ValueError:
            pass
    return None


def _normalize_sql(sql: str) -> str:
    """Normalize SQL: strip leading/trailing whitespace, collapse inner whitespace."""
    sql = sql.strip()
    sql = re.sub(r"\s+", " ", sql)
    return sql


def _has_limit_or_equivalent(scan: str) -> bool:
    """Check if SQL query already has a LIMIT / TOP / FETCH clause."""
    # LIMIT (most DBs)
    if re.search(r"\bLIMIT\s+\d+", scan):
        return True
    # TOP (MSSQL)
    if re.search(r"\bTOP\s*\(\s*\d+\s*\)", scan):
        return True
    # FETCH (standard SQL)
    if re.search(r"\bFETCH\s+(FIRST|NEXT)\s+\d+\s+(ROW|ROWS)", scan):
        return True
    return False


def _find_main_select_in_with_sql(original_sql: str) -> tuple[int, int] | None:
    """
    For WITH ... SELECT, find the main SELECT statement start/end positions.
    Returns (start_pos, end_pos) in original_sql, or None if not found.
    """
    scan = _strip_strings_and_comments_for_scan(original_sql).upper()

    # Match WITH ... SELECT
    with_match = re.search(r"WITH\s+.*?\s+(SELECT)", scan, re.DOTALL)
    if not with_match:
        return None

    select_start = with_match.start(1)

    # Find the position of the SELECT keyword in the original SQL
    # by counting characters and adjusting for removed strings/comments
    select_pos = select_start
    # This is approximate; a proper implementation would track character offsets

    return None  # Conservative: don't auto-inject for CTEs


def _apply_auto_limit_if_needed(sql: str, eng: Any, max_rows: int, main_stmt: str) -> tuple[str, bool]:
    """
    Apply auto-limit if needed for safety.
    Returns (modified_sql, was_modified).
    """
    if main_stmt != "SELECT":
        return sql, False

    # Check if limit already present
    scan = _strip_strings_and_comments_for_scan(sql).upper()
    if _has_limit_or_equivalent(scan):
        return sql, False

    # For simplicity, append LIMIT clause (works for most DBs)
    sql_normalized = _normalize_sql(sql)

    # For MSSQL TOP syntax, this is trickier; just append LIMIT for now
    modified = f"{sql_normalized} LIMIT {max_rows}"
    return modified, True


def _apply_dialect_session_guards(conn: Any, eng: Any, read_only_session: bool) -> None:
    """
    Apply database-specific session guards for read-only mode.
    """
    dialect_name = (eng.dialect.name or "").lower()

    if dialect_name == "postgresql":
        if read_only_session:
            conn.exec_driver_sql("SET default_transaction_read_only = ON;")
    elif dialect_name == "mysql":
        if read_only_session:
            conn.exec_driver_sql("SET SESSION sql_mode = 'STRICT_TRANS_TABLES';")
            conn.exec_driver_sql("SET SESSION read_only = ON;")
    elif dialect_name == "mssql":
        if read_only_session:
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
    # SQLite doesn't have a direct "read-only" mode; rely on filesystem permissions


def _reset_mysql_session(conn: Any, eng: Any) -> None:
    """Reset MySQL session state after a query (clear session-local state)."""
    dialect_name = (eng.dialect.name or "").lower()
    if dialect_name == "mysql":
        try:
            conn.exec_driver_sql("RESET SESSION;")
        except Exception:
            pass


def _truncate_str(s: str) -> tuple[str, bool]:
    """Truncate string to 500 chars, return (truncated, was_truncated)."""
    if len(s) > 500:
        return s[:500] + "...", True
    return s, False


def _json_safe(v: Any) -> tuple[Any, bool]:
    """Convert value to JSON-safe type, return (safe_value, was_modified)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v, False

    if isinstance(v, (list, dict)):
        return v, False

    # Convert bytes to string
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace"), True
        except Exception:
            return str(v), True

    # Convert other types to string
    return str(v), True


def _rows_json_safe(rows: list[tuple[Any, ...]]) -> tuple[list[list[Any]], int]:
    """Convert query rows to JSON-safe list, return (safe_rows, bytes_estimate)."""
    safe_rows = []
    est_bytes = 0

    for row in rows:
        safe_row = []
        for v in row:
            safe_v, _ = _json_safe(v)
            safe_row.append(safe_v)
            est_bytes += len(str(safe_v)) + 10  # rough estimate
        safe_rows.append(safe_row)

    return safe_rows, est_bytes
