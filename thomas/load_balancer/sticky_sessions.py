"""
Session affinity (sticky sessions) implementation.

Ensures requests from the same client are routed to the same backend
using cookies, IP addresses, or custom headers.
"""

import hashlib
import threading
import time

from thomas.load_balancer._types import Backend, RequestContext


class SessionEntry:
    """Represents a session mapping."""

    def __init__(self, backend_id: str, created_at: float = 0) -> None:
        """
        Initialize session entry.

        Args:
            backend_id: ID of the backend this session is bound to.
            created_at: Timestamp when session was created.
        """
        self.backend_id = backend_id
        self.created_at = created_at or time.time()
        self.last_accessed: float = self.created_at
        self.access_count: int = 0

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed = time.time()
        self.access_count += 1

    def is_expired(self, ttl: int) -> bool:
        """
        Check if session has expired.

        Args:
            ttl: Time-to-live in seconds.

        Returns:
            True if session has expired, False otherwise.
        """
        return time.time() - self.last_accessed > ttl


class SessionManager:
    """Manages session affinity for sticky sessions."""

    def __init__(self, session_ttl: int = 3600, cleanup_interval: int = 300) -> None:
        """
        Initialize session manager.

        Args:
            session_ttl: Session time-to-live in seconds (default 1 hour).
            cleanup_interval: Interval in seconds to clean up expired sessions.
        """
        self.session_ttl = session_ttl
        self.cleanup_interval = cleanup_interval

        self._sessions: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()
        self._cleanup_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the session cleanup background thread."""
        if self._running:
            return

        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
        )
        self._cleanup_thread.start()

    def stop(self) -> None:
        """Stop the session cleanup background thread."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)

    def _cleanup_loop(self) -> None:
        """Background loop for cleaning up expired sessions."""
        while self._running:
            time.sleep(self.cleanup_interval)
            self._cleanup_expired_sessions()

    def _cleanup_expired_sessions(self) -> None:
        """Remove expired sessions from the table."""
        with self._lock:
            expired = [sid for sid, entry in self._sessions.items() if entry.is_expired(self.session_ttl)]
            for sid in expired:
                del self._sessions[sid]

    def get_cookie_name(self, app_name: str = "lb") -> str:
        """
        Get the session cookie name.

        Args:
            app_name: Application name prefix (default 'lb').

        Returns:
            Cookie name for session tracking.
        """
        return f"{app_name}_session_id"

    def extract_session_id(
        self,
        context: RequestContext,
        cookie_name: str | None = None,
    ) -> str | None:
        """
        Extract session ID from request context.

        Looks for session ID in:
        1. Custom session_id field in context
        2. Cookie header
        3. X-Session-ID header

        Args:
            context: Request context.
            cookie_name: Name of the session cookie.

        Returns:
            Session ID if found, None otherwise.
        """
        # Check context's explicit session_id
        if context.session_id:
            return context.session_id

        if not cookie_name:
            cookie_name = self.get_cookie_name()

        # Check cookies header
        cookie_header = context.headers.get("cookie", "")
        if cookie_header:
            for cookie in cookie_header.split(";"):
                cookie = cookie.strip()
                if cookie.startswith(f"{cookie_name}="):
                    session_id = cookie[len(cookie_name) + 1 :]
                    return session_id if session_id else None

        # Check X-Session-ID header
        session_id = context.headers.get("x-session-id")
        if session_id:
            return session_id

        return None

    def get_backend_for_session(
        self,
        session_id: str,
        available_backends: list[Backend],
    ) -> Backend | None:
        """
        Get the backend bound to a session.

        Args:
            session_id: Session identifier.
            available_backends: List of available backends (for fallback if preferred is down).

        Returns:
            Backend bound to this session, or None if not found/expired.
        """
        with self._lock:
            if session_id not in self._sessions:
                return None

            entry = self._sessions[session_id]

            # Check if expired
            if entry.is_expired(self.session_ttl):
                del self._sessions[session_id]
                return None

            # Find the backend
            preferred_backend = None
            for backend in available_backends:
                if backend.id == entry.backend_id:
                    preferred_backend = backend
                    break

            if preferred_backend:
                entry.touch()
                return preferred_backend

            # Preferred backend not available, allow failover
            return None

    def bind_session(self, session_id: str, backend_id: str) -> None:
        """
        Bind a session to a backend.

        Args:
            session_id: Session identifier.
            backend_id: ID of the backend to bind to.
        """
        with self._lock:
            self._sessions[session_id] = SessionEntry(backend_id)

    def update_session(self, session_id: str) -> None:
        """
        Update session access time (touch).

        Args:
            session_id: Session identifier.
        """
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].touch()

    def invalidate_session(self, session_id: str) -> None:
        """
        Invalidate a session.

        Args:
            session_id: Session identifier.
        """
        with self._lock:
            self._sessions.pop(session_id, None)

    def migrate_sessions(self, old_backend_id: str, new_backend_id: str) -> None:
        """
        Migrate all sessions from one backend to another.

        Used when draining or failing over a backend.

        Args:
            old_backend_id: ID of the backend being removed.
            new_backend_id: ID of the new backend.
        """
        with self._lock:
            for entry in self._sessions.values():
                if entry.backend_id == old_backend_id:
                    entry.backend_id = new_backend_id

    def get_session_info(self, session_id: str) -> dict | None:
        """
        Get information about a session.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with session info, or None if not found.
        """
        with self._lock:
            if session_id not in self._sessions:
                return None

            entry = self._sessions[session_id]
            if entry.is_expired(self.session_ttl):
                del self._sessions[session_id]
                return None

            return {
                "session_id": session_id,
                "backend_id": entry.backend_id,
                "created_at": entry.created_at,
                "last_accessed": entry.last_accessed,
                "access_count": entry.access_count,
                "age_seconds": time.time() - entry.created_at,
            }

    def get_all_sessions(self) -> dict[str, dict]:
        """
        Get information about all active sessions.

        Returns:
            Dict mapping session ID to session info.
        """
        with self._lock:
            result = {}
            expired_keys = []

            for sid, entry in self._sessions.items():
                if entry.is_expired(self.session_ttl):
                    expired_keys.append(sid)
                else:
                    result[sid] = {
                        "backend_id": entry.backend_id,
                        "created_at": entry.created_at,
                        "last_accessed": entry.last_accessed,
                        "access_count": entry.access_count,
                    }

            # Clean up expired
            for sid in expired_keys:
                del self._sessions[sid]

            return result

    def get_sessions_for_backend(self, backend_id: str) -> list[str]:
        """
        Get all session IDs bound to a specific backend.

        Args:
            backend_id: ID of the backend.

        Returns:
            List of session IDs bound to this backend.
        """
        with self._lock:
            return [
                sid
                for sid, entry in self._sessions.items()
                if entry.backend_id == backend_id and not entry.is_expired(self.session_ttl)
            ]

    def generate_session_id(self, context: RequestContext) -> str:
        """
        Generate a new session ID.

        Args:
            context: Request context to base session ID on.

        Returns:
            New session identifier.
        """
        # Use IP + timestamp for consistent but unique session IDs
        seed = f"{context.client_ip}:{time.time()}".encode()
        return hashlib.sha256(seed).hexdigest()
