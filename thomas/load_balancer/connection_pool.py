"""
Connection pooling for backend servers.

Maintains a pool of connections per backend with min/max size,
connection lifecycle management, idle timeout, and graceful draining.
"""

import queue
import socket
import threading
import time

from thomas.load_balancer._types import Backend


class PooledConnection:
    """Represents a connection in the pool."""

    def __init__(self, conn_id: str, backend: Backend, socket_obj: socket.socket | None = None) -> None:
        """
        Initialize pooled connection.

        Args:
            conn_id: Unique connection identifier.
            backend: Backend this connection connects to.
            socket_obj: Optional socket object.
        """
        self.conn_id = conn_id
        self.backend = backend
        self.socket = socket_obj
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0
        self.is_valid = True

    def touch(self) -> None:
        """Update last used timestamp."""
        self.last_used = time.time()
        self.use_count += 1

    def is_idle(self, timeout: int) -> bool:
        """
        Check if connection is idle.

        Args:
            timeout: Idle timeout in seconds.

        Returns:
            True if connection hasn't been used for timeout seconds.
        """
        return time.time() - self.last_used > timeout

    def is_expired(self, max_age: int) -> bool:
        """
        Check if connection has reached max age.

        Args:
            max_age: Maximum connection age in seconds.

        Returns:
            True if connection is older than max_age.
        """
        return time.time() - self.created_at > max_age

    def close(self) -> None:
        """Close the underlying socket."""
        if self.socket:
            try:
                self.socket.close()
            except (ConnectionError, TimeoutError):
                pass
        self.is_valid = False


class ConnectionPool:
    """
    Connection pool for a single backend.

    Maintains min/max connections, handles lifecycle, idle timeout, and draining.
    """

    def __init__(
        self,
        backend: Backend,
        min_connections: int = 1,
        max_connections: int = 10,
        idle_timeout: int = 300,
        max_connection_age: int = 3600,
    ) -> None:
        """
        Initialize connection pool.

        Args:
            backend: Backend to create pool for.
            min_connections: Minimum connections to maintain.
            max_connections: Maximum concurrent connections.
            idle_timeout: Close idle connections after this many seconds.
            max_connection_age: Close connections older than this many seconds.
        """
        self.backend = backend
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self.max_connection_age = max_connection_age

        self._available_queue: queue.Queue = queue.Queue(maxsize=max_connections)
        self._all_connections: dict[str, PooledConnection] = {}
        self._active_count = 0
        self._next_conn_id = 0
        self._lock = threading.Lock()
        self._draining = False
        self._maintenance_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the connection pool."""
        if self._running:
            return

        self._running = True

        # Start maintenance thread
        self._maintenance_thread = threading.Thread(
            target=self._maintenance_loop,
            daemon=True,
        )
        self._maintenance_thread.start()

        # Create minimum connections
        for _ in range(self.min_connections):
            self._create_connection()

    def stop(self) -> None:
        """Stop the connection pool and close all connections."""
        self._running = False
        if self._maintenance_thread:
            self._maintenance_thread.join(timeout=5)

        with self._lock:
            for conn in self._all_connections.values():
                conn.close()
            self._all_connections.clear()

    def get_connection(self, timeout: float = 5.0) -> PooledConnection | None:
        """
        Get a connection from the pool.

        Args:
            timeout: Maximum time to wait for a connection in seconds.

        Returns:
            PooledConnection or None if none available.
        """
        if self._draining:
            return None

        try:
            conn = self._available_queue.get(timeout=timeout)
            if conn.is_valid and not conn.is_expired(self.max_connection_age):
                with self._lock:
                    self._active_count += 1
                    conn.touch()
                return conn
            else:
                conn.close()
                return self.get_connection(timeout)

        except queue.Empty:
            # Try to create new connection if under limit
            if self._active_count < self.max_connections:
                return self._create_and_activate_connection()
            return None

    def return_connection(self, conn: PooledConnection) -> None:
        """
        Return a connection to the pool.

        Args:
            conn: Connection to return.
        """
        if not conn or not conn.is_valid:
            return

        with self._lock:
            self._active_count = max(0, self._active_count - 1)

        if not self._draining and conn.is_valid:
            try:
                self._available_queue.put_nowait(conn)
            except queue.Full:
                conn.close()

    def _create_connection(self) -> None:
        """Create a new connection."""
        with self._lock:
            conn_id = f"{self.backend.id}:{self._next_conn_id}"
            self._next_conn_id += 1

            # Try to create socket
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.backend.host, self.backend.port))
                sock.settimeout(None)
            except (ConnectionError, TimeoutError):
                sock = None

            conn = PooledConnection(conn_id, self.backend, sock)
            self._all_connections[conn_id] = conn

            if sock:
                try:
                    self._available_queue.put_nowait(conn)
                except queue.Full:
                    conn.close()

    def _create_and_activate_connection(self) -> PooledConnection | None:
        """Create a new connection and mark it as active."""
        with self._lock:
            if self._active_count >= self.max_connections:
                return None

            conn_id = f"{self.backend.id}:{self._next_conn_id}"
            self._next_conn_id += 1

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.backend.host, self.backend.port))
                sock.settimeout(None)
            except (ConnectionError, TimeoutError):
                sock = None

            conn = PooledConnection(conn_id, self.backend, sock)
            self._all_connections[conn_id] = conn

            if sock:
                self._active_count += 1
                return conn

            return None

    def _maintenance_loop(self) -> None:
        """Background thread for connection maintenance."""
        while self._running:
            time.sleep(30)  # Check every 30 seconds
            self._cleanup_idle_connections()

    def _cleanup_idle_connections(self) -> None:
        """Remove idle and expired connections."""
        with self._lock:
            expired_ids = []

            for conn_id, conn in self._all_connections.items():
                if conn.is_idle(self.idle_timeout) or conn.is_expired(self.max_connection_age):
                    conn.close()
                    expired_ids.append(conn_id)

            for conn_id in expired_ids:
                del self._all_connections[conn_id]

            # Recreate minimum connections if needed
            healthy_conns = sum(
                1 for c in self._all_connections.values() if c.is_valid and not c.is_idle(self.idle_timeout)
            )

            for _ in range(max(0, self.min_connections - healthy_conns)):
                self._create_connection()

    def drain(self) -> None:
        """
        Begin graceful draining.

        No new connections are issued, but existing connections remain valid.
        """
        self._draining = True

    def is_draining(self) -> bool:
        """Check if pool is draining."""
        return self._draining

    def get_stats(self) -> dict:
        """
        Get pool statistics.

        Returns:
            Dict with pool stats.
        """
        with self._lock:
            healthy_conns = sum(1 for c in self._all_connections.values() if c.is_valid)

            return {
                "backend_id": self.backend.id,
                "total_connections": len(self._all_connections),
                "active_connections": self._active_count,
                "available_connections": self._available_queue.qsize(),
                "healthy_connections": healthy_conns,
                "min_connections": self.min_connections,
                "max_connections": self.max_connections,
                "is_draining": self._draining,
            }


class ConnectionPoolManager:
    """Manages connection pools for all backends."""

    def __init__(
        self,
        min_connections: int = 1,
        max_connections: int = 10,
        idle_timeout: int = 300,
    ) -> None:
        """
        Initialize connection pool manager.

        Args:
            min_connections: Minimum connections per pool.
            max_connections: Maximum connections per pool.
            idle_timeout: Idle timeout in seconds.
        """
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout

        self._pools: dict[str, ConnectionPool] = {}
        self._lock = threading.Lock()

    def get_pool(self, backend: Backend) -> ConnectionPool:
        """
        Get or create a pool for a backend.

        Args:
            backend: Backend to get pool for.

        Returns:
            ConnectionPool for this backend.
        """
        with self._lock:
            if backend.id not in self._pools:
                pool = ConnectionPool(
                    backend,
                    min_connections=self.min_connections,
                    max_connections=self.max_connections,
                    idle_timeout=self.idle_timeout,
                )
                pool.start()
                self._pools[backend.id] = pool

            return self._pools[backend.id]

    def get_connection(self, backend: Backend) -> PooledConnection | None:
        """
        Get a connection from a backend's pool.

        Args:
            backend: Backend to get connection for.

        Returns:
            PooledConnection or None.
        """
        pool = self.get_pool(backend)
        return pool.get_connection()

    def return_connection(self, conn: PooledConnection) -> None:
        """
        Return a connection to its pool.

        Args:
            conn: Connection to return.
        """
        pool = self._pools.get(conn.backend.id)
        if pool:
            pool.return_connection(conn)

    def drain_backend(self, backend_id: str) -> None:
        """
        Drain connections for a backend.

        Args:
            backend_id: ID of backend to drain.
        """
        with self._lock:
            pool = self._pools.get(backend_id)
            if pool:
                pool.drain()

    def remove_backend(self, backend_id: str) -> None:
        """
        Remove a backend's pool.

        Args:
            backend_id: ID of backend to remove.
        """
        with self._lock:
            pool = self._pools.pop(backend_id, None)
            if pool:
                pool.stop()

    def get_all_stats(self) -> dict[str, dict]:
        """
        Get stats for all pools.

        Returns:
            Dict mapping backend ID to pool stats.
        """
        with self._lock:
            return {bid: pool.get_stats() for bid, pool in self._pools.items()}

    def shutdown(self) -> None:
        """Shutdown all pools."""
        with self._lock:
            for pool in self._pools.values():
                pool.stop()
            self._pools.clear()
