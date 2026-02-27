"""
Tests for IMAP protocol implementation.

Tests IMAP client operations including folder management, message
fetching, searching, flagging, and response handling.
"""

from datetime import datetime, timezone

import pytest

from thomas.email_protocol._exceptions import (
    IMAPAuthenticationError,
    IMAPError,
    IMAPProtocolError,
)
from thomas.email_protocol._types import (
    EmailAddress,
    EmailMessage,
    Flag,
    SearchCriteria,
)
from thomas.email_protocol.imap import (
    IMAPClient,
    IMAPResponse,
    IMAPState,
)


class TestIMAPClient:
    """Test IMAP client implementation."""

    def test_client_initialization(self):
        """Test IMAP client initialization."""
        client = IMAPClient("imap.example.com", 993)

        assert client.hostname == "imap.example.com"
        assert client.port == 993
        assert client.state == IMAPState.DISCONNECTED

    def test_connect(self):
        """Test IMAP connection."""
        client = IMAPClient("imap.example.com")
        response = client.connect()

        assert response.is_success
        assert client.state == IMAPState.CONNECTED

    def test_cannot_connect_twice(self):
        """Test cannot connect when already connected."""
        client = IMAPClient("imap.example.com")
        client.connect()

        with pytest.raises(IMAPError):
            client.connect()

    def test_login(self):
        """Test IMAP login."""
        client = IMAPClient("imap.example.com")
        client.connect()

        response = client.login("user@example.com", "password123")
        assert response.is_success
        assert client.authenticated

    def test_login_invalid_password(self):
        """Test login with invalid password."""
        client = IMAPClient("imap.example.com")
        client.connect()

        with pytest.raises(IMAPAuthenticationError):
            client.login("user@example.com", "short")

    def test_select_mailbox(self):
        """Test SELECT mailbox."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        response = client.select("INBOX")
        assert response.is_success
        assert client.current_folder == "INBOX"

    def test_select_invalid_mailbox(self):
        """Test SELECT with invalid mailbox."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        with pytest.raises(IMAPProtocolError):
            client.select("INVALID")

    def test_fetch_message(self):
        """Test FETCH message."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.envelope.message_id = "test123"
        client.messages[1] = msg

        results = client.fetch(1)
        assert len(results) > 0

    def test_fetch_range(self):
        """Test FETCH with range."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        for i in range(1, 4):
            msg = EmailMessage()
            msg.envelope.message_id = f"test{i}"
            client.messages[i] = msg

        results = client.fetch("1:3")
        assert len(results) == 3

    def test_search_by_from(self):
        """Test SEARCH by FROM."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.envelope.from_addr = EmailAddress("sender@example.com")
        client.messages[1] = msg

        criteria = SearchCriteria(from_addr="sender@example.com")
        results = client.search(criteria)
        assert 1 in results

    def test_search_by_subject(self):
        """Test SEARCH by SUBJECT."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.envelope.subject = "Important Email"
        client.messages[1] = msg

        criteria = SearchCriteria(subject="Important")
        results = client.search(criteria)
        assert 1 in results

    def test_search_by_seen_flag(self):
        """Test SEARCH by seen status."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg1 = EmailMessage()
        msg1.flags.add(Flag.SEEN)
        client.messages[1] = msg1

        msg2 = EmailMessage()
        client.messages[2] = msg2

        criteria = SearchCriteria(seen=True)
        results = client.search(criteria)
        assert 1 in results
        assert 2 not in results

    def test_store_flags(self):
        """Test STORE flag modification."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        client.messages[1] = msg

        flags = {Flag.SEEN, Flag.FLAGGED}
        results = client.store(1, flags)

        assert 1 in results
        assert Flag.SEEN in client.messages[1].flags
        assert Flag.FLAGGED in client.messages[1].flags

    def test_store_add_flags(self):
        """Test STORE adding flags."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.flags.add(Flag.SEEN)
        client.messages[1] = msg

        results = client.store(1, {Flag.FLAGGED}, action="+FLAGS")
        assert Flag.SEEN in client.messages[1].flags
        assert Flag.FLAGGED in client.messages[1].flags

    def test_copy_message(self):
        """Test COPY message."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        client.messages[1] = msg
        client.mailbox_data["INBOX"] = {"EXISTS": 1, "RECENT": 0}
        client.mailbox_data["Archive"] = {"EXISTS": 0, "RECENT": 0}

        response = client.copy(1, "Archive")
        assert response.is_success

    def test_expunge(self):
        """Test EXPUNGE deleted messages."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.flags.add(Flag.DELETED)
        client.messages[1] = msg

        expunged = client.expunge()
        assert 1 in expunged
        assert 1 not in client.messages

    def test_create_mailbox(self):
        """Test CREATE mailbox."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        response = client.create("NewFolder")
        assert response.is_success
        assert "NewFolder" in client.mailbox_data

    def test_create_existing_mailbox_fails(self):
        """Test CREATE existing mailbox fails."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        client.create("Folder")
        with pytest.raises(IMAPProtocolError):
            client.create("Folder")

    def test_delete_mailbox(self):
        """Test DELETE mailbox."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        client.create("Folder")
        response = client.delete("Folder")
        assert response.is_success
        assert "Folder" not in client.mailbox_data

    def test_list_mailboxes(self):
        """Test LIST mailboxes."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        client.mailbox_data["INBOX"] = {"EXISTS": 10, "UNSEEN": 3}
        client.mailbox_data["Archive"] = {"EXISTS": 100, "UNSEEN": 0}

        folders = client.list_mailboxes()
        assert len(folders) >= 2
        names = [f.name for f in folders]
        assert "INBOX" in names
        assert "Archive" in names

    def test_logout(self):
        """Test LOGOUT."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")

        response = client.logout()
        assert response.is_success
        assert not client.authenticated


class TestIMAPResponse:
    """Test IMAP response handling."""

    def test_successful_response(self):
        """Test successful response."""
        response = IMAPResponse("OK", message="Command completed")
        assert response.is_success

    def test_failure_response(self):
        """Test failure response."""
        response = IMAPResponse("NO", message="Invalid command")
        assert not response.is_success

    def test_response_with_code(self):
        """Test response with status code."""
        response = IMAPResponse("OK", code="READ-WRITE")
        assert response.code == "READ-WRITE"


class TestIMAPSearch:
    """Test IMAP search functionality."""

    def test_search_multiple_criteria(self):
        """Test search with multiple criteria."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.envelope.from_addr = EmailAddress("sender@example.com")
        msg.envelope.subject = "Test Subject"
        msg.envelope.date = datetime.now(timezone.utc)
        client.messages[1] = msg

        criteria = SearchCriteria(
            from_addr="sender@example.com",
            subject="Test",
        )
        results = client.search(criteria)
        assert 1 in results

    def test_search_by_date(self):
        """Test search by date."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.envelope.date = datetime(2023, 1, 15, tzinfo=timezone.utc)
        client.messages[1] = msg

        since = datetime(2023, 1, 1, tzinfo=timezone.utc)
        criteria = SearchCriteria(since=since)
        results = client.search(criteria)
        assert 1 in results

    def test_search_by_size(self):
        """Test search by message size."""
        client = IMAPClient("imap.example.com")
        client.connect()
        client.login("user@example.com", "password123")
        client.select("INBOX")

        msg = EmailMessage()
        msg.size = 5000
        client.messages[1] = msg

        criteria = SearchCriteria(size_min=1000, size_max=10000)
        results = client.search(criteria)
        assert 1 in results


class TestIMAPStateManagement:
    """Test IMAP state transitions."""

    def test_state_progression(self):
        """Test correct state progression."""
        client = IMAPClient("imap.example.com")

        assert client.state == IMAPState.DISCONNECTED

        client.connect()
        assert client.state == IMAPState.CONNECTED

        client.login("user@example.com", "password123")
        assert client.state == IMAPState.AUTHENTICATED

        client.select("INBOX")
        assert client.state == IMAPState.SELECTED
