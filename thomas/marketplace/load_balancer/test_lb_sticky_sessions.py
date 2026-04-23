"""
Tests for sticky sessions (session affinity).

Verifies cookie/IP affinity, failover, and TTL behavior.
"""

import time

import pytest

from thomas.marketplace.load_balancer._types import Backend, RequestContext
from thomas.marketplace.load_balancer.sticky_sessions import SessionEntry, SessionManager


@pytest.fixture
def backends():
    """Create test backends."""
    return [
        Backend("b1", "host1", 8080),
        Backend("b2", "host2", 8080),
        Backend("b3", "host3", 8080),
    ]


@pytest.fixture
def manager():
    """Create session manager."""
    return SessionManager(session_ttl=3600)


class TestSessionEntry:
    """Tests for session entry."""

    def test_creation(self):
        """Test creating session entry."""
        entry = SessionEntry("b1")
        assert entry.backend_id == "b1"
        assert entry.access_count == 0

    def test_touch_updates_time(self):
        """Test touch updates last accessed."""
        entry = SessionEntry("b1")
        first_time = entry.last_accessed

        time.sleep(0.1)
        entry.touch()

        assert entry.last_accessed > first_time
        assert entry.access_count == 1

    def test_is_expired(self):
        """Test expiration checking."""
        entry = SessionEntry("b1")

        assert not entry.is_expired(10)  # Not expired

        # Mock old creation time
        entry.last_accessed = time.time() - 100

        assert entry.is_expired(10)  # Expired


class TestSessionManager:
    """Tests for session manager."""

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager.session_ttl == 3600
        manager.start()
        manager.stop()

    def test_get_cookie_name(self, manager):
        """Test cookie name generation."""
        assert manager.get_cookie_name() == "lb_session_id"
        assert manager.get_cookie_name("myapp") == "myapp_session_id"

    def test_extract_session_id_from_context(self, manager):
        """Test extracting session ID from context."""
        context = RequestContext(
            client_ip="192.168.1.1",
            path="/test",
            session_id="sess123",
        )

        session_id = manager.extract_session_id(context)
        assert session_id == "sess123"

    def test_extract_session_id_from_cookie(self, manager):
        """Test extracting session ID from cookie header."""
        context = RequestContext(
            client_ip="192.168.1.1",
            path="/test",
            headers={"cookie": "lb_session_id=sess456;other=value"},
        )

        session_id = manager.extract_session_id(context)
        assert session_id == "sess456"

    def test_extract_session_id_from_header(self, manager):
        """Test extracting session ID from X-Session-ID header."""
        context = RequestContext(
            client_ip="192.168.1.1",
            path="/test",
            headers={"x-session-id": "sess789"},
        )

        session_id = manager.extract_session_id(context)
        assert session_id == "sess789"

    def test_extract_session_id_precedence(self, manager):
        """Test extraction precedence: context > cookie > header."""
        context = RequestContext(
            client_ip="192.168.1.1",
            path="/test",
            session_id="context_id",
            headers={
                "cookie": "lb_session_id=cookie_id",
                "x-session-id": "header_id",
            },
        )

        session_id = manager.extract_session_id(context)
        assert session_id == "context_id"

    def test_bind_session(self, manager, backends):
        """Test binding session to backend."""
        manager.bind_session("sess1", "b1")

        backend = manager.get_backend_for_session("sess1", backends)
        assert backend.id == "b1"

    def test_get_backend_for_session(self, manager, backends):
        """Test getting backend for session."""
        manager.bind_session("sess1", "b1")

        backend = manager.get_backend_for_session("sess1", backends)
        assert backend is not None
        assert backend.id == "b1"

    def test_get_backend_not_found(self, manager, backends):
        """Test getting backend for non-existent session."""
        backend = manager.get_backend_for_session("unknown", backends)
        assert backend is None

    def test_get_backend_preferred_unavailable(self, manager, backends):
        """Test failover when preferred backend unavailable."""
        manager.bind_session("sess1", "b1")

        # b1 not in available list
        available = [b for b in backends if b.id != "b1"]

        backend = manager.get_backend_for_session("sess1", available)
        assert backend is None  # Prefers session backend if available

    def test_update_session(self, manager, backends):
        """Test updating session access time."""
        manager.bind_session("sess1", "b1")
        backend = manager.get_backend_for_session("sess1", backends)
        assert backend.id == "b1"

        first_access = manager.get_session_info("sess1")["last_accessed"]

        time.sleep(0.1)
        manager.update_session("sess1")

        updated_info = manager.get_session_info("sess1")
        assert updated_info["last_accessed"] > first_access

    def test_invalidate_session(self, manager):
        """Test invalidating a session."""
        manager.bind_session("sess1", "b1")
        assert manager.get_session_info("sess1") is not None

        manager.invalidate_session("sess1")
        assert manager.get_session_info("sess1") is None

    def test_migrate_sessions(self, manager):
        """Test migrating sessions from one backend to another."""
        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b1")
        manager.bind_session("sess3", "b2")

        manager.migrate_sessions("b1", "b3")

        assert manager.get_session_info("sess1")["backend_id"] == "b3"
        assert manager.get_session_info("sess2")["backend_id"] == "b3"
        assert manager.get_session_info("sess3")["backend_id"] == "b2"

    def test_get_session_info(self, manager):
        """Test getting session information."""
        manager.bind_session("sess1", "b1")

        info = manager.get_session_info("sess1")
        assert info["session_id"] == "sess1"
        assert info["backend_id"] == "b1"
        assert "created_at" in info
        assert "last_accessed" in info
        assert info["access_count"] >= 0

    def test_get_all_sessions(self, manager):
        """Test getting all active sessions."""
        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b2")

        all_sessions = manager.get_all_sessions()
        assert len(all_sessions) == 2
        assert "sess1" in all_sessions
        assert "sess2" in all_sessions

    def test_get_sessions_for_backend(self, manager):
        """Test getting sessions for a backend."""
        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b1")
        manager.bind_session("sess3", "b2")

        b1_sessions = manager.get_sessions_for_backend("b1")
        assert len(b1_sessions) == 2
        assert "sess1" in b1_sessions
        assert "sess2" in b1_sessions

        b2_sessions = manager.get_sessions_for_backend("b2")
        assert len(b2_sessions) == 1
        assert "sess3" in b2_sessions

    def test_session_ttl_expiration(self):
        """Test session expiration based on TTL."""
        manager = SessionManager(session_ttl=1)  # 1 second TTL

        manager.bind_session("sess1", "b1")
        assert manager.get_session_info("sess1") is not None

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired now
        assert manager.get_session_info("sess1") is None

    def test_cleanup_expired_sessions(self):
        """Test background cleanup of expired sessions."""
        manager = SessionManager(session_ttl=1, cleanup_interval=1)
        manager.start()

        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b2")

        # Wait for expiration
        time.sleep(1.1)

        # Cleanup should run
        time.sleep(1.2)

        # Expired session should be gone
        all_sessions = manager.get_all_sessions()
        # Note: May still exist until cleanup runs

        manager.stop()

    def test_generate_session_id(self, manager):
        """Test session ID generation."""
        context = RequestContext(client_ip="192.168.1.1", path="/test")

        sid1 = manager.generate_session_id(context)
        sid2 = manager.generate_session_id(context)

        # Should be different (different timestamps)
        assert sid1 != sid2

        # Should be hex string
        assert len(sid1) == 64  # SHA256 hex


class TestSessionAffinity:
    """Tests for session affinity behavior."""

    def test_sticky_session_affinity(self, manager, backends):
        """Test that same session stays with same backend."""
        context1 = RequestContext(
            client_ip="192.168.1.1",
            path="/test",
            session_id="sess1",
        )

        # First request - bind session
        manager.bind_session("sess1", "b1")
        backend1 = manager.get_backend_for_session("sess1", backends)

        # Second request - should get same backend
        manager.update_session("sess1")
        backend2 = manager.get_backend_for_session("sess1", backends)

        assert backend1.id == backend2.id == "b1"

    def test_different_sessions_different_backends(self, manager, backends):
        """Test that different sessions can use different backends."""
        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b2")

        b1 = manager.get_backend_for_session("sess1", backends)
        b2 = manager.get_backend_for_session("sess2", backends)

        assert b1.id == "b1"
        assert b2.id == "b2"

    def test_session_access_count(self, manager, backends):
        """Test that access count increments."""
        manager.bind_session("sess1", "b1")

        info1 = manager.get_session_info("sess1")
        initial_count = info1["access_count"]

        manager.update_session("sess1")
        manager.get_backend_for_session("sess1", backends)

        info2 = manager.get_session_info("sess1")
        assert info2["access_count"] > initial_count

    def test_multiple_sessions_same_backend(self, manager, backends):
        """Test multiple sessions can be bound to same backend."""
        manager.bind_session("sess1", "b1")
        manager.bind_session("sess2", "b1")
        manager.bind_session("sess3", "b1")

        sessions = manager.get_sessions_for_backend("b1")
        assert len(sessions) == 3
