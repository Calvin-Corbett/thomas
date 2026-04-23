"""Database command implementations: query, schema, and connection tools."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from .database import (
    Tool,
    ToolResult,
    _atomic_write_json,
    _connections_file_path,
    _dialect_from_connection_string,
    _encrypt_connection,
    _get_engine,
    _load_connections_raw,
    _mask_connection_string,
)
from .database_safety import (
    _apply_auto_limit_if_needed,
    _apply_dialect_session_guards,
    _contains_multiple_statements,
    _get_statement_timeout_ms,
    _requires_confirm,
    _reset_mysql_session,
    _rows_json_safe,
    _sanitize_error_message,
)


def _tool_ok(data: Any) -> ToolResult:
    return ToolResult(ok=True, data=data)


def _tool_err(message: str) -> ToolResult:
    return ToolResult(ok=False, error=str(message))


def _query_sync(
    connection_string: str,
    sql: str,
    params_obj: dict[str, Any] | list[dict[str, Any]] | None,
    max_rows: int,
    confirm: bool,
    dry_run: bool,
) -> dict[str, Any]:
    eng = _get_engine(connection_string)
    started = time.perf_counter()

    requires_confirm, main_stmt, ro_reasons = _requires_confirm(sql)
    read_only = not requires_confirm
    sql_exec, auto_limited = _apply_auto_limit_if_needed(sql, eng, max_rows, main_stmt)

    meta: dict[str, Any] = {
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
        "effective_sql": sql_exec if dry_run else None,
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

    with eng.begin() as conn:
        _apply_dialect_session_guards(conn, eng, read_only_session=read_only and not confirm)

        result = conn.execute(text(sql_exec), params_obj or {})

        columns = list(result.keys()) if result.returns_rows else []
        rows_out: list[list[Any]] = []
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
    table: str | None,
    include_views: bool,
    detailed: bool,
    pattern: str | None,
) -> dict[str, Any]:
    eng = _get_engine(connection_string)
    insp = inspect(eng)

    def split_schema_table(t: str) -> tuple[str | None, str]:
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
        pat = pattern.strip()
        if not pat:
            return True
        regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
        return re.match(regex, name, flags=re.IGNORECASE) is not None

    def table_payload(schema: str | None, tbl: str, is_view: bool) -> dict[str, Any]:
        cols = insp.get_columns(tbl, schema=schema)
        payload: dict[str, Any] = {
            "name": f"{schema}.{tbl}" if (schema and schema != default_schema) else tbl,
            "columns": [
                {"name": c.get("name"), "type": str(c.get("type")), "nullable": bool(c.get("nullable", True))}
                for c in cols
            ],
        }
        if not detailed:
            return payload
        payload["table_type"] = "view" if is_view else "table"

        try:
            pk = insp.get_pk_constraint(tbl, schema=schema) or {}
            payload["primary_key"] = pk.get("constrained_columns", []) or []
        except (OSError, RuntimeError, AttributeError):
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
        except (OSError, RuntimeError, AttributeError):
            payload["foreign_keys"] = []

        try:
            idx = insp.get_indexes(tbl, schema=schema) or []
            payload["indexes"] = [
                {"name": i.get("name"), "unique": bool(i.get("unique", False)), "columns": i.get("column_names") or []}
                for i in idx
            ]
        except (OSError, RuntimeError, AttributeError):
            payload["indexes"] = []

        try:
            uq = insp.get_unique_constraints(tbl, schema=schema) or []
            payload["unique_constraints"] = [
                {"name": u.get("name"), "columns": u.get("column_names") or []} for u in uq
            ]
        except (OSError, RuntimeError, AttributeError):
            payload["unique_constraints"] = []

        return payload

    tables_out: list[dict[str, Any]] = []
    if table:
        schema, tbl = split_schema_table(table)
        if schema is None:
            schema = default_schema
        is_view = False
        try:
            if include_views and schema is not None:
                is_view = tbl in (insp.get_view_names(schema=schema) or [])
        except (OSError, RuntimeError, AttributeError):
            pass
        tables_out.append(table_payload(schema, tbl, is_view=is_view))
        return {"tables": tables_out}
    try:
        schemas = insp.get_schema_names()
    except (OSError, RuntimeError, AttributeError):
        schemas = [default_schema] if default_schema else [None]

    filtered: list[str | None] = []
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
        except (OSError, RuntimeError, AttributeError):
            tbls = insp.get_table_names()

        views: list[str] = []
        if include_views:
            try:
                views = insp.get_view_names(schema=s) or []
            except (OSError, RuntimeError, AttributeError):
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

    async def execute(self, args: dict[str, Any]) -> Any:
        try:
            connection_string = str(args.get("connection_string") or "").strip()
            sql = str(args.get("sql") or "")
            confirm = bool(args.get("confirm", False))
            dry_run = bool(args.get("dry_run", False))

            max_rows = args.get("max_rows", 100)
            try:
                max_rows = int(max_rows)
            except (ValueError, TypeError):
                max_rows = 100
            max_rows = max(1, min(1000, max_rows))

            params_val = args.get("params")
            params_obj: dict[str, Any] | list[dict[str, Any]] | None = None
            if (
                isinstance(params_val, dict)
                or isinstance(params_val, list)
                and all(isinstance(x, dict) for x in params_val)
            ):
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

    async def execute(self, args: dict[str, Any]) -> Any:
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

    async def execute(self, args: dict[str, Any]) -> Any:
        try:
            raw = _load_connections_raw()
            conns = raw.get("connections", [])
            out: list[dict[str, Any]] = []

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
            "test": {
                "type": "boolean",
                "default": False,
                "description": "Optionally test the connection before saving.",
            },
        },
        "required": ["name", "connection_string"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> Any:
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


class DatabaseCommand(Tool):
    """
    Simple SQLite database tool supporting SELECT, INSERT, UPDATE, COUNT, DESCRIBE.
    Blocks dangerous operations (DROP, DELETE without WHERE, ALTER, TRUNCATE).
    """

    name = "db.command"
    category = "database"
    description = (
        "Execute SQLite database commands: SELECT, INSERT, UPDATE, COUNT, DESCRIBE. "
        "Blocks DROP, DELETE without WHERE, ALTER, TRUNCATE for safety."
    )
    parameters = {
        "type": "object",
        "properties": {
            "database": {
                "type": "string",
                "description": "Path to SQLite database file (default: ~/.thomas/thomas.db)",
            },
            "operation": {
                "type": "string",
                "enum": ["SELECT", "INSERT", "UPDATE", "COUNT", "DESCRIBE"],
                "description": "Operation type",
            },
            "table": {
                "type": "string",
                "description": "Table name",
            },
            "sql": {
                "type": "string",
                "description": "Custom SQL query (advanced; bypasses operation validation)",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Columns to SELECT or INSERT into",
            },
            "values": {
                "type": "object",
                "description": "Values for INSERT/UPDATE as {column: value} dict",
            },
            "where": {
                "type": "string",
                "description": "WHERE clause for SELECT/UPDATE/DELETE (required for UPDATE/DELETE)",
            },
            "limit": {
                "type": "integer",
                "description": "Limit results (for SELECT, default: 100)",
            },
        },
        "required": ["operation"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Execute SQLite database operations safely."""
        try:
            operation = str(args.get("operation", "")).upper().strip()
            database = str(args.get("database", "")).strip() or self._default_db_path()
            sql = str(args.get("sql", "")).strip() if args.get("sql") else ""
            table = str(args.get("table", "")).strip() if args.get("table") else ""
            where = str(args.get("where", "")).strip() if args.get("where") else ""
            columns = args.get("columns")
            values = args.get("values")
            limit = args.get("limit", 100)

            # Validate inputs
            if operation not in ("SELECT", "INSERT", "UPDATE", "COUNT", "DESCRIBE"):
                return _tool_err(f"Invalid operation: {operation}. Must be SELECT, INSERT, UPDATE, COUNT, or DESCRIBE.")

            if not database:
                return _tool_err("database path is required or ~/.thomas/thomas.db does not exist")

            # If custom SQL is provided, validate it for safety
            if sql:
                if any(keyword in sql.upper() for keyword in ("DROP", "DELETE", "ALTER", "TRUNCATE")):
                    return _tool_err(f"Blocked for safety: {sql[:100]}... contains DROP, DELETE, ALTER, or TRUNCATE")
                return await self._execute_custom_sql(database, sql, values)

            # Route to appropriate handler
            if operation == "SELECT":
                return await self._execute_select(database, table, columns, where, limit)
            elif operation == "INSERT":
                return await self._execute_insert(database, table, columns, values)
            elif operation == "UPDATE":
                if not where:
                    return _tool_err("UPDATE requires where clause for safety")
                return await self._execute_update(database, table, values, where)
            elif operation == "COUNT":
                return await self._execute_count(database, table, where)
            elif operation == "DESCRIBE":
                return await self._execute_describe(database, table)

            return _tool_err(f"Unknown operation: {operation}")

        except ValueError as e:
            return _tool_err(str(e))
        except RuntimeError as e:
            return _tool_err(str(e))
        except Exception as e:
            return _tool_err(f"{type(e).__name__}: {str(e)}")

    async def _execute_select(self, database: str, table: str, columns: Any, where: str, limit: int) -> ToolResult:
        """Execute SELECT query."""
        import sqlite3

        if not table:
            return _tool_err("table is required for SELECT")

        cols = ", ".join(columns) if isinstance(columns, list) and columns else "*"
        query = f"SELECT {cols} FROM {table}"

        if where:
            query += f" WHERE {where}"

        query += f" LIMIT {max(1, min(limit, 10000))}"

        try:
            data = await asyncio.to_thread(self._query_sqlite, database, query, ())
            return _tool_ok(data)
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    async def _execute_insert(self, database: str, table: str, columns: Any, values: Any) -> ToolResult:
        """Execute INSERT query."""
        import sqlite3

        if not table:
            return _tool_err("table is required for INSERT")
        if not isinstance(values, dict) or not values:
            return _tool_err("values must be a non-empty dict for INSERT")

        cols = list(values.keys())
        placeholders = ", ".join(["?"] * len(cols))
        query = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        vals = tuple(values[c] for c in cols)

        try:
            result = await asyncio.to_thread(self._execute_sqlite, database, query, vals)
            return _tool_ok({"rows_affected": result})
        except sqlite3.IntegrityError as e:
            return _tool_err(f"Integrity error: {e}")
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    async def _execute_update(self, database: str, table: str, values: Any, where: str) -> ToolResult:
        """Execute UPDATE query."""
        import sqlite3

        if not table:
            return _tool_err("table is required for UPDATE")
        if not isinstance(values, dict) or not values:
            return _tool_err("values must be a non-empty dict for UPDATE")
        if not where:
            return _tool_err("where clause is required for UPDATE (safety)")

        set_clause = ", ".join([f"{k} = ?" for k in values.keys()])
        query = f"UPDATE {table} SET {set_clause} WHERE {where}"
        vals = tuple(values.values())

        try:
            result = await asyncio.to_thread(self._execute_sqlite, database, query, vals)
            return _tool_ok({"rows_affected": result})
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    async def _execute_count(self, database: str, table: str, where: str) -> ToolResult:
        """Execute COUNT query."""
        import sqlite3

        if not table:
            return _tool_err("table is required for COUNT")

        query = f"SELECT COUNT(*) as count FROM {table}"
        if where:
            query += f" WHERE {where}"

        try:
            data = await asyncio.to_thread(self._query_sqlite, database, query, ())
            count = data.get("rows", [{}])[0].get("count", 0)
            return _tool_ok({"count": count})
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    async def _execute_describe(self, database: str, table: str) -> ToolResult:
        """Get table schema info."""
        import sqlite3

        if not table:
            return _tool_err("table is required for DESCRIBE")

        query = f"PRAGMA table_info({table})"

        try:
            data = await asyncio.to_thread(self._query_sqlite, database, query, ())
            columns = data.get("rows", [])
            return _tool_ok(
                {
                    "table": table,
                    "columns": [
                        {
                            "name": col.get("name"),
                            "type": col.get("type"),
                            "nullable": not col.get("notnull"),
                            "primary_key": bool(col.get("pk")),
                        }
                        for col in columns
                    ],
                }
            )
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    async def _execute_custom_sql(self, database: str, sql: str, params: Any = None) -> ToolResult:
        """Execute arbitrary SQL (pre-validated for safety)."""
        import sqlite3

        try:
            data = await asyncio.to_thread(self._query_sqlite, database, sql, params or ())
            return _tool_ok(data)
        except sqlite3.DatabaseError as e:
            return _tool_err(f"SQL error: {e}")
        except FileNotFoundError:
            return _tool_err(f"Database not found: {database}")

    @staticmethod
    def _default_db_path() -> str:
        """Get default database path."""
        home = Path.home()
        db_path = home / ".thomas" / "thomas.db"
        if db_path.exists():
            return str(db_path)
        return str(db_path)

    @staticmethod
    def _query_sqlite(database: str, query: str, params: tuple) -> dict[str, Any]:
        """Execute SELECT query and return rows as list of dicts."""
        import sqlite3

        db_path = Path(database).expanduser()
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(row) for row in cursor.fetchall()]
            return {"columns": columns, "rows": rows}

    @staticmethod
    def _execute_sqlite(database: str, query: str, params: tuple) -> int:
        """Execute INSERT/UPDATE/DELETE and return affected row count."""
        import sqlite3

        db_path = Path(database).expanduser()
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount


TOOLS = [DatabaseCommand(), DBQueryTool(), DBSchemaTool(), DBConnectionsTool(), DBSaveConnectionTool()]
