"""
Type definitions and data structures for the database engine.

This module defines all core types used throughout the database system:
- Data types (INT, FLOAT, VARCHAR, BOOL, DATE, TIMESTAMP, BLOB)
- Storage structures (Page, BufferFrame, Record, Column, Index)
- Schema objects (Table, Schema, Constraint, ForeignKey)
- Transaction management (Transaction, LockMode)
- Query execution (Cursor, QueryPlan, JoinType, LogRecord)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class DataType(Enum):
    """Enumeration of supported SQL data types."""

    INT = auto()
    FLOAT = auto()
    VARCHAR = auto()
    BOOL = auto()
    DATE = auto()
    TIMESTAMP = auto()
    BLOB = auto()

    def size_bytes(self) -> int | None:
        """Return fixed size in bytes, or None for variable-length types."""
        size_map = {
            DataType.INT: 8,
            DataType.FLOAT: 8,
            DataType.BOOL: 1,
            DataType.DATE: 8,
            DataType.TIMESTAMP: 8,
            DataType.VARCHAR: None,
            DataType.BLOB: None,
        }
        return size_map[self]

    def default_value(self) -> Any:
        """Return default NULL value for this type."""
        return None


@dataclass
class Column:
    """Represents a column in a table with type and constraints."""

    name: str
    data_type: DataType
    nullable: bool = True
    default_value: Any | None = None
    max_length: int | None = None

    def __hash__(self) -> int:
        return hash((self.name, self.data_type))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Column):
            return NotImplemented
        return self.name == other.name and self.data_type == other.data_type


@dataclass
class Page:
    """In-memory representation of a 4KB database page."""

    page_id: int
    data: bytearray = field(default_factory=lambda: bytearray(4096))
    is_dirty: bool = False
    pin_count: int = 0
    last_access_time: float = 0.0

    @property
    def page_size(self) -> int:
        """Return page size in bytes (always 4KB)."""
        return 4096

    def reset(self) -> None:
        """Clear page data and reset metadata."""
        self.data = bytearray(4096)
        self.is_dirty = False
        self.pin_count = 0


@dataclass
class BufferFrame:
    """A frame in the buffer pool holding a page."""

    frame_id: int
    page: Page
    pin_count: int = 0
    reference_count: int = 0
    last_accessed: float = 0.0

    @property
    def is_pinned(self) -> bool:
        """Check if frame is currently pinned."""
        return self.pin_count > 0


@dataclass
class Record:
    """A row/record in a table with column values."""

    rid: tuple[int, int] | None = None  # (page_id, slot_id)
    values: dict[str, Any] = field(default_factory=dict)
    is_deleted: bool = False

    def get_value(self, column_name: str) -> Any:
        """Get column value, returning None if not present."""
        return self.values.get(column_name)

    def set_value(self, column_name: str, value: Any) -> None:
        """Set column value."""
        self.values[column_name] = value

    def to_bytes(self) -> bytes:
        """Serialize record to bytes."""
        # Simple serialization: store as JSON-like format
        import json

        return json.dumps(self.values).encode("utf-8")

    @staticmethod
    def from_bytes(data: bytes) -> "Record":
        """Deserialize record from bytes."""
        import json

        values = json.loads(data.decode("utf-8"))
        return Record(values=values)


@dataclass
class Constraint:
    """Represents a table constraint."""

    name: str
    constraint_type: str  # PRIMARY_KEY, UNIQUE, NOT_NULL, CHECK, FOREIGN_KEY
    columns: list[str]
    expression: str | None = None  # For CHECK constraints


@dataclass
class ForeignKey:
    """Represents a foreign key constraint."""

    name: str
    source_table: str
    source_columns: list[str]
    target_table: str
    target_columns: list[str]
    on_delete: str = "RESTRICT"  # CASCADE, SET_NULL, RESTRICT, NO_ACTION
    on_update: str = "RESTRICT"


@dataclass
class Index:
    """Metadata for a database index."""

    index_id: int
    name: str
    table_name: str
    columns: list[str]
    is_unique: bool = False
    is_primary: bool = False
    root_page_id: int | None = None
    height: int = 0
    num_keys: int = 0


@dataclass
class Table:
    """Metadata for a table."""

    table_id: int
    name: str
    columns: list[Column]
    indexes: list[Index] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    first_page_id: int | None = None
    num_rows: int = 0
    num_pages: int = 0

    def get_column(self, name: str) -> Column | None:
        """Get column by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def column_names(self) -> list[str]:
        """Return list of column names."""
        return [col.name for col in self.columns]

    def record_size_estimate(self) -> int:
        """Estimate average record size in bytes."""
        total = 0
        for col in self.columns:
            if col.data_type.size_bytes() is not None:
                total += col.data_type.size_bytes()
            else:
                # Estimate for VARCHAR/BLOB
                total += col.max_length or 100
        return total + 8  # Add overhead


@dataclass
class Schema:
    """Database schema containing tables and constraints."""

    tables: dict[str, Table] = field(default_factory=dict)
    indexes: dict[str, Index] = field(default_factory=dict)
    sequences: dict[str, int] = field(default_factory=dict)

    def get_table(self, name: str) -> Table | None:
        """Get table by name."""
        return self.tables.get(name)

    def create_table(self, table: Table) -> None:
        """Register a table in the schema."""
        self.tables[table.name] = table

    def drop_table(self, name: str) -> None:
        """Remove a table from the schema."""
        if name in self.tables:
            del self.tables[name]

    def list_tables(self) -> list[str]:
        """Return list of table names."""
        return list(self.tables.keys())


class LockMode(Enum):
    """Types of locks for transaction isolation."""

    SHARED = auto()  # Read lock
    EXCLUSIVE = auto()  # Write lock
    INTENT_SHARED = auto()
    INTENT_EXCLUSIVE = auto()


@dataclass
class Lock:
    """A lock held on a resource."""

    resource_id: int  # page_id or tuple (table_id, row_id)
    transaction_id: int
    mode: LockMode
    acquired_time: float = 0.0
    wait_graph_id: int | None = None


@dataclass
class Transaction:
    """Represents a database transaction."""

    transaction_id: int
    start_time: float
    isolation_level: str = "READ_COMMITTED"  # or REPEATABLE_READ, SERIALIZABLE
    is_active: bool = True
    locks: dict[int, list[Lock]] = field(default_factory=dict)  # resource_id -> locks
    modified_pages: set[int] = field(default_factory=set)  # page_ids
    undo_log: list["LogRecord"] = field(default_factory=list)
    redo_log: list["LogRecord"] = field(default_factory=list)
    savepoints: dict[str, int] = field(default_factory=dict)  # savepoint_name -> lsn


@dataclass
class LogRecord:
    """A write-ahead log record."""

    lsn: int  # Log sequence number
    transaction_id: int
    record_type: str  # INSERT, UPDATE, DELETE, COMMIT, ABORT, CHECKPOINT
    table_id: int | None = None
    page_id: int | None = None
    slot_id: int | None = None
    before_image: bytes | None = None
    after_image: bytes | None = None
    timestamp: float = 0.0
    prev_lsn: int | None = None  # For transaction log chain


@dataclass
class Cursor:
    """Iterator for table/index scans."""

    cursor_id: int
    table_id: int
    current_page_id: int | None = None
    current_slot: int = 0
    is_eof: bool = False
    direction: str = "FORWARD"  # FORWARD or BACKWARD

    def reset(self) -> None:
        """Reset cursor to start."""
        self.current_page_id = None
        self.current_slot = 0
        self.is_eof = False


class JoinType(Enum):
    """Types of join algorithms."""

    NESTED_LOOP = auto()
    SORT_MERGE = auto()
    HASH_JOIN = auto()
    INDEX_LOOKUP = auto()


@dataclass
class QueryPlan:
    """Physical query execution plan."""

    plan_id: int
    query_type: str  # SELECT, INSERT, UPDATE, DELETE
    cost_estimate: float = 0.0
    io_cost: float = 0.0
    cpu_cost: float = 0.0
    operator_tree: dict[str, Any] | None = None
    tables_accessed: list[str] = field(default_factory=list)
    indexes_used: list[str] = field(default_factory=list)
    estimated_rows: int = 0
    plan_hash: str | None = None

    def __hash__(self) -> int:
        if self.plan_hash is None:
            import hashlib

            self.plan_hash = hashlib.md5(str((self.query_type, tuple(self.tables_accessed))).encode()).hexdigest()
        return int(self.plan_hash, 16) % (2**31)


@dataclass
class Statistics:
    """Table and column statistics for query optimization."""

    table_name: str
    num_rows: int = 0
    num_pages: int = 0
    avg_record_size: int = 0
    column_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_updated: float = 0.0

    def get_column_stat(self, col_name: str, stat_name: str) -> Any:
        """Get a specific statistic for a column."""
        if col_name not in self.column_stats:
            return None
        return self.column_stats[col_name].get(stat_name)

    def set_column_stat(self, col_name: str, stat_name: str, value: Any) -> None:
        """Set a statistic for a column."""
        if col_name not in self.column_stats:
            self.column_stats[col_name] = {}
        self.column_stats[col_name][stat_name] = value


class ExpressionNode(ABC):
    """Abstract base for expression tree nodes."""

    @abstractmethod
    def evaluate(self, record: Record) -> Any:
        """Evaluate expression on a record."""
        pass

    @abstractmethod
    def __repr__(self) -> str:
        pass


@dataclass
class LiteralNode(ExpressionNode):
    """Literal value node."""

    value: Any

    def evaluate(self, record: Record) -> Any:
        return self.value

    def __repr__(self) -> str:
        return f"Literal({self.value!r})"


@dataclass
class ColumnNode(ExpressionNode):
    """Column reference node."""

    column_name: str

    def evaluate(self, record: Record) -> Any:
        return record.get_value(self.column_name)

    def __repr__(self) -> str:
        return f"Column({self.column_name})"


@dataclass
class BinaryOpNode(ExpressionNode):
    """Binary operation node."""

    operator: str  # +, -, *, /, =, <, >, <=, >=, !=, AND, OR
    left: ExpressionNode
    right: ExpressionNode

    def evaluate(self, record: Record) -> Any:
        left_val = self.left.evaluate(record)
        right_val = self.right.evaluate(record)

        if left_val is None or right_val is None:
            return None

        ops = {
            "+": lambda l, r: l + r,
            "-": lambda l, r: l - r,
            "*": lambda l, r: l * r,
            "/": lambda l, r: l / r if r != 0 else None,
            "=": lambda l, r: l == r,
            "<": lambda l, r: l < r,
            ">": lambda l, r: l > r,
            "<=": lambda l, r: l <= r,
            ">=": lambda l, r: l >= r,
            "!=": lambda l, r: l != r,
            "AND": lambda l, r: l and r,
            "OR": lambda l, r: l or r,
        }
        return ops.get(self.operator, lambda l, r: None)(left_val, right_val)

    def __repr__(self) -> str:
        return f"BinOp({self.operator}, {self.left}, {self.right})"


@dataclass
class UnaryOpNode(ExpressionNode):
    """Unary operation node."""

    operator: str  # NOT, -
    operand: ExpressionNode

    def evaluate(self, record: Record) -> Any:
        val = self.operand.evaluate(record)
        if val is None:
            return None
        if self.operator == "NOT":
            return not val
        elif self.operator == "-":
            return -val
        return None

    def __repr__(self) -> str:
        return f"UnaryOp({self.operator}, {self.operand})"


@dataclass
class FunctionCallNode(ExpressionNode):
    """Function call node."""

    function_name: str
    arguments: list[ExpressionNode]

    def evaluate(self, record: Record) -> Any:
        args = [arg.evaluate(record) for arg in self.arguments]

        # Built-in functions
        funcs = {
            "COUNT": lambda x: 1 if x is not None else 0,
            "SUM": lambda x: x,
            "AVG": lambda x: x,
            "MIN": lambda x: x,
            "MAX": lambda x: x,
            "UPPER": lambda x: x.upper() if isinstance(x, str) else None,
            "LOWER": lambda x: x.lower() if isinstance(x, str) else None,
            "LENGTH": lambda x: len(x) if isinstance(x, (str, bytes)) else None,
        }

        func = funcs.get(self.function_name.upper())
        if func is None:
            return None

        return func(args[0]) if args else None

    def __repr__(self) -> str:
        return f"FuncCall({self.function_name}, {self.arguments})"
