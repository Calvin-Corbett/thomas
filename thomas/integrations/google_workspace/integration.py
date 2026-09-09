"""Main Google Workspace integration for Thomas.

Orchestrates authentication, token management, and provides unified interface
to Gmail, Google Calendar, and Google Drive APIs.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from thomas.integrations._circuit_breaker import CircuitBreaker
from thomas.integrations._health import get_health_checker
from thomas.integrations._rate_limiter import TokenBucketRateLimiter
from thomas.integrations.google_workspace.auth import (
    AuthError,
    GoogleOAuth2,
    TokenExpiredError,
    deserialize_tokens,
    serialize_tokens,
)
from thomas.integrations.google_workspace.calendar import CalendarAPI, CalendarError
from thomas.integrations.google_workspace.drive import DriveAPI, DriveError
from thomas.integrations.google_workspace.gmail import GmailAPI, GmailError

log = logging.getLogger(__name__)


class GoogleWorkspaceIntegrationError(Exception):
    """Raised when Google Workspace integration operations fail."""

    pass


class GoogleWorkspaceIntegration:
    """Unified integration for Google Workspace (Gmail, Calendar, Drive).

    Handles OAuth2 authentication, token management, and provides
    high-level interfaces to all three services.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        secrets_manager: Any | None = None,
        secrets_key: str = "google_workspace_tokens",
    ) -> None:
        """Initialize Google Workspace integration.

        Args:
            client_id: Google OAuth2 client ID
            client_secret: Google OAuth2 client secret
            redirect_uri: Redirect URI registered in Google Cloud Console
            scopes: OAuth2 scopes (defaults to all Workspace scopes)
            secrets_manager: Optional secrets manager for storing tokens
            secrets_key: Key to use when storing tokens in secrets manager
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.secrets_manager = secrets_manager
        self.secrets_key = secrets_key

        self._oauth = GoogleOAuth2(client_id, client_secret, redirect_uri, scopes)
        self._tokens: dict[str, Any] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._gmail: GmailAPI | None = None
        self._calendar: CalendarAPI | None = None
        self._drive: DriveAPI | None = None

        # Production hardening
        # Rate limiters: Google allows 250 requests/minute per service
        self._rate_limiter = TokenBucketRateLimiter(
            rate=250 / 60,  # 250 per minute
            burst=50,
            name="google_workspace",
        )
        self._circuit_breaker = CircuitBreaker(
            name="google_workspace",
            failure_threshold=5,
            recovery_timeout=60,
        )
        self._health_checker = get_health_checker()

    async def connect(self) -> None:
        """Establish connection and initialize HTTP session.

        Loads stored tokens from secrets manager if available.
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()

        # Register with health checker
        await self._health_checker.register("google_workspace")

        # Try to load existing tokens
        if self.secrets_manager is not None:
            try:
                stored = self.secrets_manager.get(self.secrets_key)
                if stored:
                    self._tokens = deserialize_tokens(stored)
                    log.info("Loaded Google Workspace tokens from secrets manager")
            except Exception as e:
                log.warning(f"Failed to load tokens from secrets: {e}")

    async def disconnect(self) -> None:
        """Close connection and cleanup resources."""
        if self._session is not None:
            await self._session.close()
            self._session = None

        if self._tokens and self.secrets_manager is not None:
            try:
                self.secrets_manager.put(self.secrets_key, serialize_tokens(self._tokens))
                log.info("Saved Google Workspace tokens to secrets manager")
            except Exception as e:
                log.warning(f"Failed to save tokens to secrets: {e}")

    def generate_auth_url(self) -> tuple[str, str]:
        """Generate Google authorization URL for user.

        Should be called first to initiate OAuth2 flow.

        Returns:
            Tuple of (authorization_url, code_verifier)
            User opens auth_url in browser, code_verifier is returned with auth code
        """
        return self._oauth.generate_auth_url()

    async def exchange_auth_code(self, code: str, code_verifier: str) -> None:
        """Exchange authorization code for tokens.

        Called after user authorizes and receives code from callback.

        Args:
            code: Authorization code from Google callback
            code_verifier: Code verifier from generate_auth_url()

        Raises:
            GoogleWorkspaceIntegrationError: If token exchange fails
        """
        if self._session is None:
            raise GoogleWorkspaceIntegrationError("Not connected. Call connect() first.")

        try:
            self._tokens = await self._oauth.exchange_code_for_tokens(code, code_verifier, self._session)
            self._gmail = None  # Reset API clients
            self._calendar = None
            self._drive = None
            log.info("Successfully exchanged auth code for tokens")
        except AuthError as e:
            raise GoogleWorkspaceIntegrationError(f"Failed to exchange auth code: {e}") from e

    async def _ensure_valid_token(self) -> None:
        """Refresh token if expired."""
        if not self._tokens:
            raise GoogleWorkspaceIntegrationError("No tokens. Must authenticate first.")

        if self._session is None:
            raise GoogleWorkspaceIntegrationError("Not connected. Call connect() first.")

        if self._oauth.is_token_expired(self._tokens):
            refresh_token = self._tokens.get("refresh_token")
            if not refresh_token:
                raise GoogleWorkspaceIntegrationError("Token expired and no refresh token available")

            try:
                new_tokens = await self._oauth.refresh_access_token(refresh_token, self._session)
                self._tokens.update(new_tokens)
                # Reset API clients to use new token
                self._gmail = None
                self._calendar = None
                self._drive = None
                log.info("Refreshed Google Workspace access token")
            except TokenExpiredError as e:
                raise GoogleWorkspaceIntegrationError(f"Tokens expired: {e}") from e
            except AuthError as e:
                raise GoogleWorkspaceIntegrationError(f"Failed to refresh token: {e}") from e

    def _get_access_token(self) -> str:
        """Get current access token."""
        if not self._tokens or "access_token" not in self._tokens:
            raise GoogleWorkspaceIntegrationError("No access token available")
        return self._tokens["access_token"]

    async def health_check(self) -> dict[str, Any]:
        """Check integration health and API connectivity.

        Returns:
            Dict with health status, last_auth_time, token_info, etc.
        """
        if not self._tokens:
            return {
                "status": "unauthenticated",
                "message": "Not authenticated. Call exchange_auth_code() first.",
            }

        try:
            await self._ensure_valid_token()

            if self._session is None:
                return {
                    "status": "disconnected",
                    "message": "Session not initialized",
                }

            # Quick test of each API
            gmail_ok = False
            calendar_ok = False
            drive_ok = False

            access_token = self._get_access_token()

            try:
                gmail = GmailAPI(access_token)
                await gmail.list_labels(self._session)
                gmail_ok = True
            except GmailError as e:
                log.debug(f"Gmail health check failed: {e}")

            try:
                calendar = CalendarAPI(access_token)
                await calendar.list_calendars(self._session)
                calendar_ok = True
            except CalendarError as e:
                log.debug(f"Calendar health check failed: {e}")

            try:
                drive = DriveAPI(access_token)
                await drive.list_files(self._session, max_results=1)
                drive_ok = True
            except DriveError as e:
                log.debug(f"Drive health check failed: {e}")

            return {
                "status": "healthy" if (gmail_ok and calendar_ok and drive_ok) else "degraded",
                "gmail": "ok" if gmail_ok else "error",
                "calendar": "ok" if calendar_ok else "error",
                "drive": "ok" if drive_ok else "error",
                "authenticated": True,
                "token_expires_at": self._tokens.get("expires_at"),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
            }

    async def execute(
        self,
        command: str,
        service: str,
        operation: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a high-level operation on a service.

        Args:
            command: Command type (e.g., "gmail.list_messages")
            service: Service name ("gmail", "calendar", "drive")
            operation: Operation name
            **kwargs: Operation-specific arguments

        Returns:
            Operation result

        Example:
            result = await integration.execute(
                command="gmail.list_messages",
                service="gmail",
                operation="list_messages",
                query="is:unread",
                max_results=10,
            )
        """
        if not self._session:
            raise GoogleWorkspaceIntegrationError("Not connected. Call connect() first.")

        await self._ensure_valid_token()
        access_token = self._get_access_token()

        # Apply rate limiting and circuit breaker
        await self._rate_limiter.acquire()

        start_time = time.time()
        try:
            await self._circuit_breaker.check()

            if service == "gmail":
                result = await self._execute_gmail(operation, access_token, **kwargs)
            elif service == "calendar":
                result = await self._execute_calendar(operation, access_token, **kwargs)
            elif service == "drive":
                result = await self._execute_drive(operation, access_token, **kwargs)
            else:
                raise GoogleWorkspaceIntegrationError(f"Unknown service: {service}")

            # Record success
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_success()
            await self._health_checker.record_success("google_workspace", latency_ms)

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure()
            await self._health_checker.record_error("google_workspace", e, latency_ms)
            raise

    async def _execute_gmail(self, operation: str, access_token: str, **kwargs: Any) -> dict[str, Any]:
        """Execute Gmail operation."""
        if self._gmail is None:
            self._gmail = GmailAPI(access_token)

        try:
            if operation == "list_messages":
                return await self._gmail.list_messages(
                    self._session,
                    query=kwargs.get("query", ""),
                    max_results=kwargs.get("max_results", 10),
                    label_ids=kwargs.get("label_ids"),
                    page_token=kwargs.get("page_token"),
                )
            elif operation == "get_message":
                return await self._gmail.get_message(
                    self._session,
                    message_id=kwargs.get("message_id", ""),
                    format=kwargs.get("format", "full"),
                )
            elif operation == "send_message":
                return await self._gmail.send_message(
                    self._session,
                    to=kwargs.get("to", ""),
                    subject=kwargs.get("subject", ""),
                    body=kwargs.get("body", ""),
                    cc=kwargs.get("cc"),
                    bcc=kwargs.get("bcc"),
                    attachments=kwargs.get("attachments"),
                )
            elif operation == "reply_to_message":
                return await self._gmail.reply_to_message(
                    self._session,
                    message_id=kwargs.get("message_id", ""),
                    body=kwargs.get("body", ""),
                )
            elif operation == "create_draft":
                return await self._gmail.create_draft(
                    self._session,
                    to=kwargs.get("to", ""),
                    subject=kwargs.get("subject", ""),
                    body=kwargs.get("body", ""),
                    cc=kwargs.get("cc"),
                    bcc=kwargs.get("bcc"),
                )
            elif operation == "list_labels":
                return await self._gmail.list_labels(self._session)
            elif operation == "modify_labels":
                return await self._gmail.modify_labels(
                    self._session,
                    message_id=kwargs.get("message_id", ""),
                    add_labels=kwargs.get("add_labels"),
                    remove_labels=kwargs.get("remove_labels"),
                )
            else:
                raise GoogleWorkspaceIntegrationError(f"Unknown Gmail operation: {operation}")
        except GmailError as e:
            raise GoogleWorkspaceIntegrationError(f"Gmail operation failed: {e}") from e

    async def _execute_calendar(self, operation: str, access_token: str, **kwargs: Any) -> dict[str, Any]:
        """Execute Calendar operation."""
        if self._calendar is None:
            self._calendar = CalendarAPI(access_token)

        try:
            if operation == "list_calendars":
                return await self._calendar.list_calendars(self._session)
            elif operation == "list_events":
                return await self._calendar.list_events(
                    self._session,
                    calendar_id=kwargs.get("calendar_id", "primary"),
                    time_min=kwargs.get("time_min"),
                    time_max=kwargs.get("time_max"),
                    max_results=kwargs.get("max_results", 25),
                )
            elif operation == "get_event":
                return await self._calendar.get_event(
                    self._session,
                    calendar_id=kwargs.get("calendar_id", "primary"),
                    event_id=kwargs.get("event_id", ""),
                )
            elif operation == "create_event":
                return await self._calendar.create_event(
                    self._session,
                    calendar_id=kwargs.get("calendar_id", "primary"),
                    summary=kwargs.get("summary", ""),
                    start=kwargs.get("start", ""),
                    end=kwargs.get("end", ""),
                    description=kwargs.get("description", ""),
                    attendees=kwargs.get("attendees"),
                    location=kwargs.get("location", ""),
                )
            elif operation == "update_event":
                return await self._calendar.update_event(
                    self._session,
                    calendar_id=kwargs.get("calendar_id", "primary"),
                    event_id=kwargs.get("event_id", ""),
                    updates=kwargs.get("updates", {}),
                )
            elif operation == "delete_event":
                return await self._calendar.delete_event(
                    self._session,
                    calendar_id=kwargs.get("calendar_id", "primary"),
                    event_id=kwargs.get("event_id", ""),
                )
            elif operation == "check_freebusy":
                return await self._calendar.check_freebusy(
                    self._session,
                    calendar_ids=kwargs.get("calendar_ids", []),
                    time_min=kwargs.get("time_min", ""),
                    time_max=kwargs.get("time_max", ""),
                )
            else:
                raise GoogleWorkspaceIntegrationError(f"Unknown Calendar operation: {operation}")
        except CalendarError as e:
            raise GoogleWorkspaceIntegrationError(f"Calendar operation failed: {e}") from e

    async def _execute_drive(self, operation: str, access_token: str, **kwargs: Any) -> dict[str, Any]:
        """Execute Drive operation."""
        if self._drive is None:
            self._drive = DriveAPI(access_token)

        try:
            if operation == "list_files":
                return await self._drive.list_files(
                    self._session,
                    query=kwargs.get("query", ""),
                    max_results=kwargs.get("max_results", 50),
                    folder_id=kwargs.get("folder_id"),
                    page_token=kwargs.get("page_token"),
                )
            elif operation == "get_file":
                return await self._drive.get_file(
                    self._session,
                    file_id=kwargs.get("file_id", ""),
                )
            elif operation == "download_file":
                return await self._drive.download_file(
                    self._session,
                    file_id=kwargs.get("file_id", ""),
                    output_path=kwargs.get("output_path", ""),
                )
            elif operation == "upload_file":
                return await self._drive.upload_file(
                    self._session,
                    file_path=kwargs.get("file_path", ""),
                    folder_id=kwargs.get("folder_id", "root"),
                    name=kwargs.get("name"),
                )
            elif operation == "create_folder":
                return await self._drive.create_folder(
                    self._session,
                    name=kwargs.get("name", ""),
                    parent_id=kwargs.get("parent_id", "root"),
                )
            elif operation == "share_file":
                return await self._drive.share_file(
                    self._session,
                    file_id=kwargs.get("file_id", ""),
                    email=kwargs.get("email", ""),
                    role=kwargs.get("role", "reader"),
                )
            elif operation == "search_files":
                return await self._drive.search_files(
                    self._session,
                    query=kwargs.get("query", ""),
                    max_results=kwargs.get("max_results", 50),
                )
            else:
                raise GoogleWorkspaceIntegrationError(f"Unknown Drive operation: {operation}")
        except DriveError as e:
            raise GoogleWorkspaceIntegrationError(f"Drive operation failed: {e}") from e
