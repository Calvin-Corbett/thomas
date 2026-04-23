"""Exception types for the graph database engine."""


class GraphDBError(Exception):
    """Base exception for all graph database errors."""

    pass


class NodeNotFoundError(GraphDBError):
    """Raised when a node cannot be found."""

    def __init__(self, node_id: str) -> None:
        """Initialize NodeNotFoundError.

        Args:
            node_id: The ID of the node that was not found
        """
        self.node_id = node_id
        super().__init__(f"Node not found: {node_id}")


class EdgeNotFoundError(GraphDBError):
    """Raised when an edge cannot be found."""

    def __init__(self, edge_id: str) -> None:
        """Initialize EdgeNotFoundError.

        Args:
            edge_id: The ID of the edge that was not found
        """
        self.edge_id = edge_id
        super().__init__(f"Edge not found: {edge_id}")


class ConstraintViolationError(GraphDBError):
    """Raised when a constraint is violated."""

    def __init__(self, constraint_type: str, details: str) -> None:
        """Initialize ConstraintViolationError.

        Args:
            constraint_type: Type of constraint violated (e.g., 'unique', 'required')
            details: Additional details about the violation
        """
        self.constraint_type = constraint_type
        self.details = details
        super().__init__(f"Constraint violation ({constraint_type}): {details}")


class QuerySyntaxError(GraphDBError):
    """Raised when a query has syntax errors."""

    def __init__(self, message: str, position: int = -1, token: str = "") -> None:
        """Initialize QuerySyntaxError.

        Args:
            message: Error message
            position: Character position where error occurred
            token: The problematic token
        """
        self.message = message
        self.position = position
        self.token = token
        if position >= 0:
            super().__init__(f"Syntax error at position {position}: {message} (token: {token})")
        else:
            super().__init__(f"Syntax error: {message}")


class IndexError(GraphDBError):
    """Raised for index-related errors."""

    def __init__(self, index_id: str, message: str) -> None:
        """Initialize IndexError.

        Args:
            index_id: The ID of the problematic index
            message: Error message
        """
        self.index_id = index_id
        super().__init__(f"Index error ({index_id}): {message}")


class SchemaError(GraphDBError):
    """Raised for schema-related errors."""

    def __init__(self, message: str) -> None:
        """Initialize SchemaError.

        Args:
            message: Error message
        """
        super().__init__(f"Schema error: {message}")


class TransactionError(GraphDBError):
    """Raised for transaction-related errors."""

    def __init__(self, message: str) -> None:
        """Initialize TransactionError.

        Args:
            message: Error message
        """
        super().__init__(f"Transaction error: {message}")
