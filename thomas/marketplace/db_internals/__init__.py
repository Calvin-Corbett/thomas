"""
Thomas Database Internals - A relational database built from scratch.

This package provides a complete implementation of a relational database engine,
including:
- Type system (DataType, Column, Table, Index, Schema)
- Buffer pool management with LRU replacement
- Storage engine with slotted pages and heap files
- B+ tree indexes for efficient lookups
- SQL parser and query optimizer
- Query executor with iterator model
- Transaction manager with ACID guarantees
- Write-ahead logging for crash recovery
- System catalog for metadata management
"""

from ._exceptions import (
    BufferPoolException,
    ConstraintViolationException,
    DatabaseException,
    DeadlockException,
    ExecutorException,
    IndexException,
    LockException,
    PageException,
    ParseException,
    SchemaException,
    StorageException,
    TransactionException,
    WALException,
)
from ._types import (
    BinaryOpNode,
    BufferFrame,
    Column,
    ColumnNode,
    Constraint,
    Cursor,
    DataType,
    ExpressionNode,
    ForeignKey,
    FunctionCallNode,
    Index,
    LiteralNode,
    LockMode,
    LogRecord,
    Page,
    QueryPlan,
    Record,
    Schema,
    Statistics,
    Table,
    Transaction,
    UnaryOpNode,
)
from .btree import BPlusTree, BTreeKey, BTreeNode
from .buffer_pool import BufferPool
from .catalog import Catalog
from .executor import (
    AggregationOperator,
    FilterOperator,
    HashJoinOperator,
    IndexScanOperator,
    LimitOperator,
    NestedLoopJoinOperator,
    Operator,
    ProjectionOperator,
    SeqScanOperator,
    SortOperator,
)
from .query_optimizer import CostEstimator, JoinOrderer, QueryOptimizer
from .query_parser import Parser, Token, Tokenizer, TokenType
from .storage import FreeSpaceMap, HeapFile, SlottedPage, ToastManager
from .transactions import LockManager, TransactionManager
from .wal import CheckpointManager, RecoveryManager, WriteAheadLog

__version__ = "0.1.0"
__all__ = [
    # Types
    "DataType",
    "Column",
    "Page",
    "BufferFrame",
    "Record",
    "Table",
    "Index",
    "Schema",
    "Constraint",
    "ForeignKey",
    "Transaction",
    "LockMode",
    "LogRecord",
    "Cursor",
    "QueryPlan",
    "Statistics",
    "ExpressionNode",
    "LiteralNode",
    "ColumnNode",
    "BinaryOpNode",
    "UnaryOpNode",
    "FunctionCallNode",
    # Exceptions
    "DatabaseException",
    "StorageException",
    "BufferPoolException",
    "PageException",
    "TransactionException",
    "LockException",
    "DeadlockException",
    "ConstraintViolationException",
    "SchemaException",
    "ParseException",
    "ExecutorException",
    "WALException",
    "IndexException",
    # Core components
    "BufferPool",
    "HeapFile",
    "SlottedPage",
    "FreeSpaceMap",
    "ToastManager",
    "BPlusTree",
    "BTreeKey",
    "BTreeNode",
    "Parser",
    "Tokenizer",
    "Token",
    "TokenType",
    "QueryOptimizer",
    "CostEstimator",
    "JoinOrderer",
    "Operator",
    "SeqScanOperator",
    "IndexScanOperator",
    "FilterOperator",
    "ProjectionOperator",
    "NestedLoopJoinOperator",
    "HashJoinOperator",
    "SortOperator",
    "AggregationOperator",
    "LimitOperator",
    "TransactionManager",
    "LockManager",
    "WriteAheadLog",
    "RecoveryManager",
    "CheckpointManager",
    "Catalog",
]
