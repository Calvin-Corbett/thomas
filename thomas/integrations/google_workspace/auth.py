"""OAuth2 authentication helper for Google Workspace APIs.

Handles authorization URL generation, token exchange, and token refresh
using the standard Google OAuth2 flow.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when OAuth2 authentication fails."""

    pass


class TokenExpiredError(AuthError):
    """Raised when token has expired and cannot be refreshed."""

    pass


class GoogleOAuth2:
    """Manages OAuth2 flow and token lifecycle for Google APIs."""

    # Google OAuth2 endpoints
    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    # Standard Google Workspace scopes
    GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
    GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
    GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
    CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
    CALENDAR_WRITE = "https://www.googleapis.com/auth/calendar"
    DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
    DRIVE_WRITE = "https://www.googleapis.com/auth/drive"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> None:
        """Initialize OAuth2 client.

        Args:
            client_id: Google OAuth2 client ID
            client_secret: Google OAuth2 client secret
            redirect_uri: Redirect URI registered in Google Cloud Console
            scopes: List of OAuth2 scopes to request (defaults to all Workspace scopes)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes or [
            self.GMAIL_READONLY,
            self.GMAIL_SEND,
            self.CALENDAR_READONLY,
            self.CALENDAR_WRITE,
            self.DRIVE_READONLY,
            self.DRIVE_WRITE,
        ]

    def generate_auth_url(self) -> tuple[str, str]:
        """Generate Google authorization URL and PKCE code verifier.

        Returns:
            Tuple of (authorization_url, code_verifier) to store for callback
        """
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode("utf-8").rstrip("=")
        )

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        auth_url = f"{self.GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return auth_url, code_verifier

    async def exchange_code_for_tokens(self, code: str, code_verifier: str, session: Any) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier generated during auth URL generation
            session: aiohttp ClientSession

        Returns:
            Dict containing access_token, refresh_token, expires_in, token_type, etc.

        Raises:
            AuthError: If token exchange fails
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }

        try:
            async with session.post(self.GOOGLE_TOKEN_URL, data=data) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise AuthError(f"Token exchange failed: {resp.status} - {error_text}")

                tokens = await resp.json()
                if "access_token" not in tokens:
                    raise AuthError(f"No access_token in response: {tokens}")

                # Add expiration time
                expires_in = tokens.get("expires_in", 3600)
                tokens["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
                return tokens
        except AuthError:
            raise
        except Exception as e:
            raise AuthError(f"Token exchange request failed: {e}") from e

    async def refresh_access_token(self, refresh_token: str, session: Any) -> dict[str, Any]:
        """Refresh an expired access token.

        Args:
            refresh_token: Refresh token from initial auth
            session: aiohttp ClientSession

        Returns:
            Dict containing new access_token, expires_in, token_type, etc.

        Raises:
            TokenExpiredError: If refresh token is invalid or revoked
            AuthError: If refresh request fails
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with session.post(self.GOOGLE_TOKEN_URL, data=data) as resp:
                if resp.status == 400:
                    # Invalid refresh token
                    raise TokenExpiredError("Refresh token is invalid or has been revoked")
                if resp.status != 200:
                    error_text = await resp.text()
                    raise AuthError(f"Token refresh failed: {resp.status} - {error_text}")

                tokens = await resp.json()
                if "access_token" not in tokens:
                    raise AuthError(f"No access_token in refresh response: {tokens}")

                expires_in = tokens.get("expires_in", 3600)
                tokens["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
                return tokens
        except (TokenExpiredError, AuthError):
            raise
        except Exception as e:
            raise AuthError(f"Token refresh request failed: {e}") from e

    @staticmethod
    def is_token_expired(token_data: dict[str, Any]) -> bool:
        """Check if access token is expired or expiring soon.

        Args:
            token_data: Token dict with optional expires_at field

        Returns:
            True if token is expired or expires within 5 minutes
        """
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return True

        try:
            exp_time = datetime.fromisoformat(expires_at)
            # Consider expired if expiring within 5 minutes
            threshold = datetime.utcnow() + timedelta(minutes=5)
            return exp_time <= threshold
        except (ValueError, TypeError):
            return True

    async def revoke_token(self, token: str, session: Any) -> None:
        """Revoke an access or refresh token.

        Args:
            token: Token to revoke
            session: aiohttp ClientSession
        """
        data = {"token": token}
        try:
            async with session.post(self.GOOGLE_REVOKE_URL, data=data) as resp:
                if resp.status not in (200, 400):  # 400 if already revoked
                    log.warning(f"Token revocation returned status {resp.status}")
        except Exception as e:
            log.warning(f"Failed to revoke token: {e}")


def serialize_tokens(token_data: dict[str, Any]) -> str:
    """Serialize tokens to JSON string for storage."""
    return json.dumps(token_data, ensure_ascii=True)


def deserialize_tokens(token_json: str) -> dict[str, Any]:
    """Deserialize tokens from JSON string."""
    try:
        return json.loads(token_json)
    except json.JSONDecodeError as e:
        raise AuthError(f"Failed to deserialize tokens: {e}") from e
