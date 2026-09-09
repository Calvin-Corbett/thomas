"""Main Slack integration class with OAuth2 flow and connection management."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import aiohttp

from thomas.integrations._circuit_breaker import CircuitBreaker
from thomas.integrations._health import get_health_checker
from thomas.integrations._rate_limiter import TokenBucketRateLimiter

log = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api/"
_SLACK_OAUTH_URL = "https://slack.com/oauth_v2/authorize"
_SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"

_DEFAULT_SCOPES = [
    "channels:read",
    "channels:history",
    "chat:write",
    "users:read",
    "files:read",
    "reactions:read",
]


class SlackAPIError(Exception):
    """Base exception for Slack API errors."""

    pass


class SlackAuthError(SlackAPIError):
    """Authentication or authorization error."""

    pass


class SlackRateLimitError(SlackAPIError):
    """Rate limit exceeded error."""

    pass


class SlackConnectionError(SlackAPIError):
    """Connection or network error."""

    pass


@dataclass
class SlackToken:
    """Slack authentication token data."""

    bot_token: str
    user_token: str | None = None
    app_id: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    user_id: str | None = None
    scope: str = ""
    expires_at: float = field(default_factory=lambda: time.time() + 43200)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "bot_token": self.bot_token,
            "user_token": self.user_token,
            "app_id": self.app_id,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "user_id": self.user_id,
            "scope": self.scope,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlackToken:
        """Create from dictionary."""
        return cls(
            bot_token=str(data.get("bot_token", "")),
            user_token=data.get("user_token"),
            app_id=data.get("app_id"),
            team_id=data.get("team_id"),
            team_name=data.get("team_name"),
            user_id=data.get("user_id"),
            scope=str(data.get("scope", "")),
            expires_at=float(data.get("expires_at", time.time() + 43200)),
        )


class SlackIntegration:
    """Slack workspace integration with OAuth2 and Web API access."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        bot_token: str | None = None,
        user_token: str | None = None,
        scopes: list[str] | None = None,
        timeout_s: int = 30,
    ) -> None:
        """Initialize Slack integration.

        Args:
            client_id: OAuth app client ID
            client_secret: OAuth app client secret
            bot_token: Pre-existing bot token (bypasses OAuth flow)
            user_token: Pre-existing user token for user-scoped operations
            scopes: OAuth scopes to request (default: channels:read, etc.)
            timeout_s: HTTP request timeout in seconds
        """
        self._client_id = str(client_id).strip()
        self._client_secret = str(client_secret).strip()
        self._timeout = timeout_s
        self._scopes = scopes or list(_DEFAULT_SCOPES)

        self._token: SlackToken | None = None
        if bot_token:
            self._token = SlackToken(bot_token=bot_token, user_token=user_token)

        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

        # Production hardening
        # Slack limits: 1 request/second for web API, 1 message/second for posting
        self._rate_limiter = TokenBucketRateLimiter(
            rate=1.0,
            burst=5,
            name="slack",
        )
        self._circuit_breaker = CircuitBreaker(
            name="slack",
            failure_threshold=5,
            recovery_timeout=60,
        )
        self._health_checker = get_health_checker()

    async def connect(self) -> None:
        """Connect to Slack API."""
        async with self._lock:
            if self._session is None:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                self._session = aiohttp.ClientSession(timeout=timeout)
                # Register with health checker
                await self._health_checker.register("slack")
                log.debug("Slack integration connected")

    async def disconnect(self) -> None:
        """Disconnect from Slack API."""
        async with self._lock:
            if self._session is not None:
                await self._session.close()
                self._session = None
                log.debug("Slack integration disconnected")

    async def health_check(self) -> bool:
        """Check Slack API connectivity and authentication.

        Returns:
            True if connected and authenticated, False otherwise.
        """
        try:
            if not self._token or not self._token.bot_token:
                return False
            await self.connect()
            result = await self._api_call("auth.test", use_bot_token=True)
            return result.get("ok", False)
        except Exception as e:
            log.warning("Slack health check failed: %s", e)
            return False

    async def execute(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a Slack API call.

        Args:
            method: HTTP method (GET, POST)
            endpoint: Slack API endpoint (e.g., 'chat.postMessage')
            data: Request body data for POST
            params: Query parameters

        Returns:
            Response JSON dict

        Raises:
            SlackAPIError: If API returns error
            SlackAuthError: If authentication fails
            SlackRateLimitError: If rate limited
        """
        return await self._api_call(endpoint, method=method, data=data, params=params)

    def get_oauth_url(self, redirect_uri: str, state: str | None = None) -> str:
        """Generate OAuth authorization URL.

        Args:
            redirect_uri: OAuth callback URI
            state: Optional state parameter for security

        Returns:
            Full OAuth URL to redirect user to
        """
        params = {
            "client_id": self._client_id,
            "scope": ",".join(self._scopes),
            "redirect_uri": redirect_uri,
        }
        if state:
            params["state"] = str(state).strip()
        return f"{_SLACK_OAUTH_URL}?{urlencode(params)}"

    async def handle_oauth_callback(
        self,
        code: str,
        redirect_uri: str,
    ) -> SlackToken:
        """Exchange OAuth code for tokens.

        Args:
            code: OAuth authorization code from callback
            redirect_uri: Same redirect_uri used in authorization request

        Returns:
            SlackToken with bot and user tokens

        Raises:
            SlackAuthError: If token exchange fails
        """
        await self.connect()

        try:
            async with self._session.post(
                _SLACK_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": str(code).strip(),
                    "redirect_uri": str(redirect_uri).strip(),
                },
            ) as resp:
                result = await resp.json()

                if not result.get("ok"):
                    raise SlackAuthError(f"OAuth token exchange failed: {result.get('error', 'unknown error')}")

                bot_token = result.get("access_token", "")
                user_token = result.get("authed_user", {}).get("access_token")

                self._token = SlackToken(
                    bot_token=bot_token,
                    user_token=user_token,
                    app_id=result.get("app_id"),
                    team_id=result.get("team", {}).get("id"),
                    team_name=result.get("team", {}).get("name"),
                    user_id=result.get("authed_user", {}).get("id"),
                    scope=result.get("scope", ""),
                )
                log.info("Slack OAuth token exchange successful for team %s", self._token.team_name)
                return self._token

        except aiohttp.ClientError as e:
            raise SlackConnectionError(f"Failed to connect to Slack OAuth: {e}") from e

    def set_token(self, token: SlackToken) -> None:
        """Set authentication token.

        Args:
            token: SlackToken instance to use
        """
        self._token = token
        log.debug("Slack token updated")

    def get_token(self) -> SlackToken | None:
        """Get current authentication token.

        Returns:
            Current SlackToken or None if not authenticated
        """
        return self._token

    async def _ensure_connected(self) -> None:
        """Ensure session is connected."""
        if self._session is None or self._session.closed:
            await self.connect()

    async def _api_call(
        self,
        endpoint: str,
        method: str = "POST",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        use_bot_token: bool = True,
    ) -> dict[str, Any]:
        """Internal Slack API call handler with hardening.

        Args:
            endpoint: API endpoint
            method: HTTP method
            data: Request body
            params: Query parameters
            use_bot_token: Use bot token (vs user token)

        Returns:
            JSON response

        Raises:
            SlackAuthError: If not authenticated
            SlackRateLimitError: If rate limited
            SlackAPIError: On other API errors
        """
        if not self._token:
            raise SlackAuthError("Not authenticated with Slack")

        await self._ensure_connected()

        token = self._token.bot_token if use_bot_token else (self._token.user_token or self._token.bot_token)
        if not token:
            raise SlackAuthError("No suitable token available")

        headers = {"Authorization": f"Bearer {token}"}

        # Apply rate limiting and circuit breaker
        await self._rate_limiter.acquire()

        start_time = time.time()
        try:
            await self._circuit_breaker.check()

            url = f"{_SLACK_API_BASE}{endpoint}"

            if method.upper() == "GET":
                async with self._session.get(url, headers=headers, params=params) as resp:
                    result = await self._handle_response(resp, endpoint)
            else:
                async with self._session.post(url, headers=headers, json=data, params=params) as resp:
                    result = await self._handle_response(resp, endpoint)

            # Record success
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_success()
            await self._health_checker.record_success("slack", latency_ms)

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure()
            await self._health_checker.record_error("slack", e, latency_ms)
            raise SlackConnectionError(f"Connection error calling {endpoint}: {e}") from e

    async def _handle_response(
        self,
        resp: aiohttp.ClientResponse,
        endpoint: str,
    ) -> dict[str, Any]:
        """Handle API response with error handling.

        Args:
            resp: aiohttp response
            endpoint: API endpoint name for logging

        Returns:
            JSON response dict

        Raises:
            SlackRateLimitError: If rate limited
            SlackAuthError: If auth error
            SlackAPIError: On other errors
        """
        retry_after = resp.headers.get("Retry-After")
        if resp.status == 429:
            wait_seconds = int(retry_after) if retry_after else 1
            raise SlackRateLimitError(f"Slack rate limited on {endpoint}, retry after {wait_seconds}s")

        if resp.status == 401:
            raise SlackAuthError(f"Authentication failed for {endpoint}")

        if resp.status == 403:
            raise SlackAuthError(f"Permission denied for {endpoint}")

        if resp.status >= 500:
            raise SlackConnectionError(f"Slack server error ({resp.status}) on {endpoint}")

        try:
            result = await resp.json()
        except Exception as e:
            raise SlackAPIError(f"Failed to parse response from {endpoint}: {e}") from e

        if not result.get("ok"):
            error = result.get("error", "unknown error")
            if error in ("invalid_auth", "token_revoked", "no_permission"):
                raise SlackAuthError(f"Auth error on {endpoint}: {error}")
            raise SlackAPIError(f"Slack API error on {endpoint}: {error}")

        return result
