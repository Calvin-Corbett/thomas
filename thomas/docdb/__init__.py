"""Document database module with collections, indexes, and aggregation."""

from thomas.docdb.core import (
    Collection,
    Document,
    DocumentDatabase,
    Index,
)
from thomas.docdb.tools import register_docdb_tools

__all__ = [
    "DocumentDatabase",
    "Collection",
    "Document",
    "Index",
    "register_docdb_tools",
]
