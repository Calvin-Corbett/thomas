"""Natural Language to SQL translation tool.

Converts natural language questions into executable SQL queries using the LLM
client. Supports schema discovery, multiple SQL dialects, query validation,
and safe execution with read-only defaults.

Features:
  - translate(): Convert NL → SQL with optional schema context
  - execute_query(): Translate and execute in one step
  - explain_sql(): Explain what a SQL query does in plain English
  - schema_from_db(): Extract schema from SQLite/PostgreSQL/MySQL databases
  - Built-in validation: No DROP, DELETE without WHERE, etc.
  - Read-only by default; requires explicit flag for write queries
  - Schema caching for performance
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

try:
    from thomas.core.llm import LLMClient
    from thomas.tools.base import Tool, ToolResult
except ImportError:
    # Fallback imports for testing
    LLMClient = None  # type: ignore
    Tool = object  # type: ignore
    ToolResult = None  # type: ignore

try:
    import sqlalchemy as sa
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import Engine
except ImportError:
    sa = None  # type: ignore
    create_engine = None  # type: ignore
    inspect = None  # type: ignore
    text = None  # type: ignore
    Engine = None  # type: ignore

log = logging.getLogger(__name__)

# SQL validation patterns
_DROP_PATTERN = re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX)", re.IGNORECASE)
_DELETE_PATTERN = re.compile(r"\bDELETE\b", re.IGNORECASE)
_WHERE_PATTERN = re.compile(r"\bWHERE\b", re.IGNORECASE)
_TRUNCATE_PATTERN = re.compile(r"\bTRUNCATE\b", re.IGNORECASE)
_ALTER_PATTERN = re.compile(r"\bALTER\s+(TABLE|DATABASE|SCHEMA)", re.IGNORECASE)
_INSERT_PATTERN = re.compile(r"\bINSERT\b", re.IGNORECASE)
_UPDATE_PATTERN = re.compile(r"\bUPDATE\b", re.IGNORECASE)
_SELECT_PATTERN = re.compile(r"\bSELECT\b", re.IGNORECASE)
_WITH_PATTERN = re.compile(r"\bWITH\b", re.IGNORECASE)


@dataclass
class SchemaColumn:
    """Represents a database column."""

    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
            "foreign_key": self.foreign_key,
        }


@dataclass
class SchemaTable:
    """Represents a database table."""

    name: str
    columns: list[SchemaColumn] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": [col.to_dict() for col in self.columns],
            "indexes": self.indexes,
        }


@dataclass
class DatabaseSchema:
    """Represents complete database schema."""

    tables: list[SchemaTable] = field(default_factory=list)
    schema_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": [t.to_dict() for t in self.tables],
            "schema_hash": self.schema_hash,
        }

    def to_text(self) -> str:
        """Convert schema to readable text for LLM."""
        lines = []
        for table in self.tables:
            lines.append(f"\nTable: {table.name}")
            for col in table.columns:
                nullable = "NULL" if col.nullable else "NOT NULL"
                pk = " PRIMARY KEY" if col.primary_key else ""
                fk = f" REFERENCES {col.foreign_key}" if col.foreign_key else ""
                lines.append(f"  - {col.name}: {col.type} {nullable}{pk}{fk}")
            if table.indexes:
                lines.append(f"  Indexes: {', '.join(table.indexes)}")
        return "\n".join(lines)


@dataclass
class SQLTranslationResult:
    """Result of NL → SQL translation."""

    sql: str
    explanation: str
    confidence: float  # 0.0 to 1.0
    dialect: str = "sqlite"
    schema_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class QueryExecutionResult:
    """Result of query execution."""

    sql: str
    results: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


class NLToSQLTool(Tool):
    """Natural Language to SQL conversion tool."""

    name = "nl_to_sql"
    category = "database"
    description = "Convert natural language questions to SQL queries and execute them"
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Natural language question to convert to SQL"},
            "database_path": {"type": "string", "description": "Path to SQLite database file"},
            "execute": {"type": "boolean", "description": "Whether to execute the query (default: false for safety)"},
            "allow_write": {"type": "boolean", "description": "Allow write operations (default: false)"},
            "dialect": {
                "type": "string",
                "enum": ["sqlite", "postgresql", "mysql"],
                "description": "SQL dialect to use",
            },
        },
        "required": ["question"],
    }

    def __init__(self, llm_client: LLMClient | None = None):
        """Initialize NL to SQL tool.

        Args:
            llm_client: LLMClient instance for translation
        """
        self.llm_client = llm_client
        self._schema_cache: dict[str, DatabaseSchema] = {}
        self._engines: dict[str, Engine] = {}

    def _validate_sql(
        self, sql: str, allow_write: bool = False, allow_dangerous: bool = False
    ) -> tuple[bool, str | None]:
        """Validate SQL query for safety.

        Args:
            sql: SQL query to validate
            allow_write: Allow write operations
            allow_dangerous: Allow dangerous operations (DROP, TRUNCATE, ALTER)

        Returns:
            (is_valid, error_message)
        """
        # Check for dangerous patterns
        if _DROP_PATTERN.search(sql) and not allow_dangerous:
            return False, "DROP statements are not allowed"

        if _TRUNCATE_PATTERN.search(sql) and not allow_dangerous:
            return False, "TRUNCATE statements are not allowed"

        if _ALTER_PATTERN.search(sql) and not allow_dangerous:
            return False, "ALTER statements are not allowed"

        # Check for writes
        is_write = bool(_INSERT_PATTERN.search(sql) or _UPDATE_PATTERN.search(sql) or _DELETE_PATTERN.search(sql))

        if is_write and not allow_write:
            return False, "Write operations are not allowed (enable with allow_write=true)"

        # Check DELETE without WHERE
        if _DELETE_PATTERN.search(sql):
            if not _WHERE_PATTERN.search(sql):
                return False, "DELETE without WHERE clause is not allowed for safety"

        return True, None

    async def _get_llm_response(self, prompt: str, system_prompt: str | None = None) -> str:
        """Get response from LLM.

        Args:
            prompt: User prompt
            system_prompt: System prompt for context

        Returns:
            LLM response text
        """
        if not self.llm_client:
            raise RuntimeError("LLM client not configured")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Use the LLM client to get a response
        response = await self.llm_client.complete(
            messages=messages,
            max_tokens=1000,
            temperature=0.3,  # Lower temperature for consistency
        )

        if hasattr(response, "content"):
            return response.content[0]["text"] if response.content else ""
        return str(response)

    def _extract_sql_from_response(self, response: str) -> tuple[str, str]:
        """Extract SQL query and explanation from LLM response.

        Args:
            response: LLM response text

        Returns:
            (sql_query, explanation)
        """
        lines = response.strip().split("\n")
        sql_block = []
        explanation_lines = []
        in_sql_block = False

        for line in lines:
            if "```sql" in line.lower():
                in_sql_block = True
                continue
            if "```" in line and in_sql_block:
                in_sql_block = False
                continue
            if in_sql_block:
                sql_block.append(line)
            else:
                if line.strip():
                    explanation_lines.append(line)

        sql = "\n".join(sql_block).strip()
        if not sql:
            # Try to extract SQL if no code block found
            for line in lines:
                if line.strip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
                    sql = "\n".join(lines[lines.index(line) :])
                    break

        explanation = "\n".join(explanation_lines).strip()
        return sql, explanation

    async def translate(
        self, question: str, schema: DatabaseSchema | None = None, dialect: str = "sqlite"
    ) -> SQLTranslationResult:
        """Translate natural language to SQL.

        Args:
            question: Natural language question
            schema: Optional database schema for context
            dialect: SQL dialect (sqlite, postgresql, mysql)

        Returns:
            SQLTranslationResult with SQL, explanation, and confidence
        """
        system_prompt = self._build_system_prompt(dialect, schema)
        prompt = f"Convert this question to {dialect} SQL:\n{question}"

        response = await self._get_llm_response(prompt, system_prompt)
        sql, explanation = self._extract_sql_from_response(response)

        # Validate extracted SQL
        is_valid, error = self._validate_sql(sql, allow_write=False)
        warnings = []
        if error:
            warnings.append(error)

        # Estimate confidence based on response clarity
        confidence = self._estimate_confidence(sql, explanation)

        return SQLTranslationResult(
            sql=sql,
            explanation=explanation,
            confidence=confidence,
            dialect=dialect,
            schema_used=schema is not None,
            warnings=warnings,
        )

    def _build_system_prompt(self, dialect: str, schema: DatabaseSchema | None = None) -> str:
        """Build system prompt for LLM.

        Args:
            dialect: SQL dialect
            schema: Optional schema for context

        Returns:
            System prompt string
        """
        prompt = f"""You are a SQL expert. Convert natural language questions to {dialect} SQL.

Guidelines:
1. Write clear, efficient SQL
2. Use proper table and column names
3. Include explanations of the query
4. Format SQL in a code block with ```sql markers
5. Provide confidence level (high/medium/low)

"""
        if schema:
            prompt += f"Available schema:\n{schema.to_text()}\n\n"

        return prompt

    def _estimate_confidence(self, sql: str, explanation: str) -> float:
        """Estimate confidence in translation.

        Args:
            sql: Generated SQL
            explanation: LLM explanation

        Returns:
            Confidence score 0.0 to 1.0
        """
        score = 0.5
        if sql and sql.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            score += 0.2
        if explanation and len(explanation) > 20:
            score += 0.2
        if "high" in explanation.lower():
            score += 0.1
        return min(score, 1.0)

    async def execute_query(
        self,
        question: str,
        database_path: str | None = None,
        schema: DatabaseSchema | None = None,
        dialect: str = "sqlite",
        allow_write: bool = False,
    ) -> QueryExecutionResult | dict[str, Any]:
        """Translate and execute query in one step.

        Args:
            question: Natural language question
            database_path: Path to database
            schema: Optional schema
            dialect: SQL dialect
            allow_write: Allow write operations

        Returns:
            QueryExecutionResult if successful, error dict otherwise
        """
        if not database_path:
            return {"ok": False, "error": "database_path is required for execution"}

        # Translate question to SQL
        translation = await self.translate(question, schema=schema, dialect=dialect)

        # Validate SQL
        is_valid, error = self._validate_sql(translation.sql, allow_write=allow_write)
        if not is_valid:
            return {"ok": False, "error": error, "sql": translation.sql, "explanation": translation.explanation}

        # Execute query
        try:
            result = await self._execute_on_db(translation.sql, database_path, dialect)
            result.warnings = translation.warnings
            return result
        except Exception as e:
            return {"ok": False, "error": str(e), "sql": translation.sql}

    async def _execute_on_db(self, sql: str, database_path: str, dialect: str) -> QueryExecutionResult:
        """Execute SQL on database.

        Args:
            sql: SQL query
            database_path: Path to database
            dialect: SQL dialect

        Returns:
            QueryExecutionResult
        """
        import time

        start_time = time.monotonic()

        if dialect == "sqlite":
            results, columns = await self._execute_sqlite(sql, database_path)
        else:
            raise ValueError(f"Dialect {dialect} not yet supported")

        duration_ms = (time.monotonic() - start_time) * 1000

        return QueryExecutionResult(
            sql=sql, results=results, columns=columns, row_count=len(results), duration_ms=duration_ms
        )

    async def _execute_sqlite(self, sql: str, database_path: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Execute query on SQLite database.

        Args:
            sql: SQL query
            database_path: Path to SQLite database

        Returns:
            (results, column_names)
        """

        def _run_query():
            conn = sqlite3.connect(database_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results, columns

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run_query)

    async def explain_sql(self, sql: str) -> str:
        """Explain what a SQL query does in plain English.

        Args:
            sql: SQL query to explain

        Returns:
            Plain English explanation
        """
        prompt = f"Explain what this SQL query does in simple English:\n\n{sql}"
        system = "You are a SQL expert. Explain queries in clear, simple language suitable for non-technical users."

        explanation = await self._get_llm_response(prompt, system)
        return explanation

    def schema_from_db(self, database_path: str, dialect: str = "sqlite") -> DatabaseSchema:
        """Extract schema from database.

        Args:
            database_path: Path to database
            dialect: SQL dialect (sqlite, postgresql, mysql)

        Returns:
            DatabaseSchema object
        """
        # Check cache
        cache_key = f"{database_path}:{dialect}"
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]

        if dialect == "sqlite":
            schema = self._schema_from_sqlite(database_path)
        else:
            raise ValueError(f"Dialect {dialect} not yet supported")

        # Cache it
        self._schema_cache[cache_key] = schema
        return schema

    def _schema_from_sqlite(self, database_path: str) -> DatabaseSchema:
        """Extract schema from SQLite database.

        Args:
            database_path: Path to SQLite database

        Returns:
            DatabaseSchema object
        """
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()

        tables = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [row[0] for row in cursor.fetchall()]

        for table_name in table_names:
            columns = []
            cursor.execute(f"PRAGMA table_info({table_name})")
            for row in cursor.fetchall():
                cid, name, type_str, notnull, dflt_value, pk = row
                columns.append(
                    SchemaColumn(name=name, type=type_str or "TEXT", nullable=not notnull, primary_key=pk > 0)
                )

            # Get indexes
            indexes = []
            cursor.execute(f"PRAGMA index_list({table_name})")
            for row in cursor.fetchall():
                indexes.append(row[1])  # index name

            tables.append(SchemaTable(name=table_name, columns=columns, indexes=indexes))

        conn.close()

        schema = DatabaseSchema(tables=tables)
        # Compute hash for schema versioning
        schema_str = json.dumps(schema.to_dict(), sort_keys=True)
        schema.schema_hash = hashlib.sha256(schema_str.encode()).hexdigest()[:12]

        return schema

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Execute NL to SQL tool (from Tool interface).

        Args:
            args: Tool arguments

        Returns:
            ToolResult
        """
        try:
            question = args.get("question", "")
            database_path = args.get("database_path")
            execute = args.get("execute", False)
            allow_write = args.get("allow_write", False)
            dialect = args.get("dialect", "sqlite")

            if not question:
                return ToolResult(ok=False, error="question is required")

            # Just translate if no database path
            if not database_path or not execute:
                result = await self.translate(question, dialect=dialect)
                return ToolResult(
                    ok=True,
                    data={
                        "sql": result.sql,
                        "explanation": result.explanation,
                        "confidence": result.confidence,
                        "dialect": result.dialect,
                        "warnings": result.warnings,
                    },
                )

            # Translate and execute
            exec_result = await self.execute_query(
                question, database_path=database_path, dialect=dialect, allow_write=allow_write
            )

            if isinstance(exec_result, dict) and not exec_result.get("ok", True):
                return ToolResult(ok=False, data=exec_result)

            return ToolResult(
                ok=True,
                data={
                    "sql": exec_result.sql,
                    "results": exec_result.results,
                    "columns": exec_result.columns,
                    "row_count": exec_result.row_count,
                    "duration_ms": exec_result.duration_ms,
                    "warnings": exec_result.warnings,
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")
