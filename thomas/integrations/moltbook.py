"""Moltbook integration for Thomas.

Provides a full-featured client for the Moltbook AI agent social network,
including agent registration, claim-tweet authentication, posting,
commenting, voting, submolt management, feed retrieval, and search.

API Base: https://www.moltbook.com/api/v1
Authentication: Bearer token (moltbook_xxx) obtained via agent registration.
Rate limits: 100 req/min general, 1 post/30min, 50 comments/hour.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_BASE_URL = "https://www.moltbook.com/api/v1"
_DEFAULT_TIMEOUT_S = 10.0
_USER_AGENT = "Thomas-AI-Agent/1.0"

# Default identity when posting as the Thomas platform itself.
_DEFAULT_AGENT_NAME = "thomas"
_DEFAULT_AGENT_DESCRIPTION = (
    "Thomas — an AI-first workspace platform with domain intelligence. "
    "Not a lobster, but happy to be here."
)


@dataclass
class MoltbookConfig:
    """Configuration for a Moltbook connection."""

    api_key: str = ""
    agent_name: str = _DEFAULT_AGENT_NAME
    agent_description: str = _DEFAULT_AGENT_DESCRIPTION
    base_url: str = _BASE_URL
    timeout_s: float = _DEFAULT_TIMEOUT_S


@dataclass
class MoltbookRateLimitState:
    """Tracks rate limit headers from Moltbook responses."""

    limit: int = 100
    remaining: int = 100
    reset_at: float = 0.0


@dataclass
class MoltbookAgentProfile:
    """Agent profile returned from the Moltbook API."""

    name: str = ""
    description: str = ""
    api_key: str = ""
    claim_url: str = ""
    verification_code: str = ""
    status: str = "unclaimed"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MoltbookPost:
    """A Moltbook post (submolt)."""

    post_id: str = ""
    title: str = ""
    content: str = ""
    url: str = ""
    submolt: str = ""
    author: str = ""
    upvotes: int = 0
    downvotes: int = 0
    comment_count: int = 0
    created_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MoltbookComment:
    """A comment on a Moltbook post."""

    comment_id: str = ""
    post_id: str = ""
    parent_id: str = ""
    content: str = ""
    author: str = ""
    upvotes: int = 0
    created_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MoltbookSubmolt:
    """A Moltbook community (submolt)."""

    name: str = ""
    display_name: str = ""
    description: str = ""
    subscriber_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# HTTP transport (stdlib only — no external dependencies required)
# ---------------------------------------------------------------------------


def _http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Perform an HTTP request using only the standard library."""
    import urllib.error
    import urllib.request

    all_headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        all_headers.update(headers)

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        all_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url=url,
        data=data,
        headers=all_headers,
        method=method.upper(),
    )

    rate_info: dict[str, str] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 0) or 0)
            for hdr in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
                val = resp.headers.get(hdr)
                if val:
                    rate_info[hdr] = val
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(getattr(exc, "code", 0) or 0)
        payload = _decode_json(raw)
        return {
            "ok": False,
            "status": status,
            "payload": payload,
            "rate_limit": rate_info,
            "error": f"HTTP {status}",
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "status": 0,
            "payload": {},
            "rate_limit": {},
            "error": f"URLError: {exc.reason}",
        }

    payload = _decode_json(raw)
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "payload": payload,
        "rate_limit": rate_info,
    }


def _decode_json(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(value, dict):
        return value
    return {"raw": value}


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


# ---------------------------------------------------------------------------
# Moltbook API client
# ---------------------------------------------------------------------------


class MoltbookClient:
    """Full-featured client for the Moltbook API.

    Covers: agent registration, profile management, posting, commenting,
    voting, submolt CRUD, following, feed, and search.
    """

    def __init__(self, config: MoltbookConfig | None = None) -> None:
        self._config = config or MoltbookConfig()
        self._rate = MoltbookRateLimitState()

    @property
    def config(self) -> MoltbookConfig:
        return self._config

    @property
    def api_key(self) -> str:
        return self._config.api_key

    def _url(self, path: str) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}{path}"

    def _headers(self) -> dict[str, str]:
        hdrs: dict[str, str] = {}
        if self._config.api_key:
            hdrs.update(_auth_headers(self._config.api_key))
        return hdrs

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
            if qs:
                url = f"{url}?{qs}"
        result = _http_request(
            method, url,
            headers=self._headers(),
            body=body,
            timeout_s=self._config.timeout_s,
        )
        self._update_rate_limit(result.get("rate_limit", {}))
        return result

    def _update_rate_limit(self, info: dict[str, str]) -> None:
        if not info:
            return
        try:
            self._rate.limit = int(info.get("X-RateLimit-Limit", self._rate.limit))
            self._rate.remaining = int(
                info.get("X-RateLimit-Remaining", self._rate.remaining)
            )
            reset_raw = info.get("X-RateLimit-Reset", "")
            if reset_raw:
                self._rate.reset_at = float(reset_raw)
        except (ValueError, TypeError):
            pass

    # -- Agent management --------------------------------------------------

    def register_agent(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> MoltbookAgentProfile:
        """Register a new agent. Returns profile with api_key and claim_url."""
        agent_name = str(name or self._config.agent_name).strip()
        agent_desc = str(description or self._config.agent_description).strip()
        result = self._call("POST", "/agents/register", body={
            "name": agent_name,
            "description": agent_desc,
        })
        payload = result.get("payload", {})
        if not result.get("ok"):
            log.error("Moltbook agent registration failed: %s", result.get("error"))
            return MoltbookAgentProfile(
                name=agent_name, description=agent_desc, raw=payload,
            )
        return MoltbookAgentProfile(
            name=str(payload.get("name", agent_name)),
            description=str(payload.get("description", agent_desc)),
            api_key=str(payload.get("api_key", "")),
            claim_url=str(payload.get("claim_url", "")),
            verification_code=str(payload.get("verification_code", "")),
            status="unclaimed",
            raw=payload,
        )

    def get_profile(self) -> dict[str, Any]:
        """Get the current agent's profile."""
        result = self._call("GET", "/agents/me")
        return result.get("payload", {})

    def update_profile(self, **fields: Any) -> dict[str, Any]:
        """Update the current agent's profile fields."""
        result = self._call("PATCH", "/agents/me", body=fields)
        return result.get("payload", {})

    def get_status(self) -> dict[str, Any]:
        """Check current agent's claim status."""
        result = self._call("GET", "/agents/status")
        return result.get("payload", {})

    def get_agent_profile(self, name: str) -> dict[str, Any]:
        """View another agent's public profile."""
        result = self._call("GET", "/agents/profile", params={"name": name})
        return result.get("payload", {})

    # -- Posts -------------------------------------------------------------

    def create_text_post(
        self, *, submolt: str, title: str, content: str,
    ) -> MoltbookPost:
        """Create a text post in a submolt."""
        result = self._call("POST", "/posts", body={
            "submolt": submolt,
            "title": title,
            "content": content,
        })
        return self._parse_post(result)

    def create_link_post(
        self, *, submolt: str, title: str, url: str,
    ) -> MoltbookPost:
        """Create a link post in a submolt."""
        result = self._call("POST", "/posts", body={
            "submolt": submolt,
            "title": title,
            "url": url,
        })
        return self._parse_post(result)

    def get_feed(
        self,
        *,
        sort: str = "hot",
        limit: int = 25,
    ) -> list[MoltbookPost]:
        """Get posts from the global feed."""
        result = self._call("GET", "/posts", params={
            "sort": sort,
            "limit": str(limit),
        })
        return self._parse_post_list(result)

    def get_personalized_feed(
        self,
        *,
        sort: str = "hot",
        limit: int = 25,
    ) -> list[MoltbookPost]:
        """Get posts from followed agents and subscribed submolts."""
        result = self._call("GET", "/feed", params={
            "sort": sort,
            "limit": str(limit),
        })
        return self._parse_post_list(result)

    def get_post(self, post_id: str) -> MoltbookPost:
        """Fetch a single post by ID."""
        result = self._call("GET", f"/posts/{post_id}")
        return self._parse_post(result)

    def delete_post(self, post_id: str) -> bool:
        """Delete a post (must be author)."""
        result = self._call("DELETE", f"/posts/{post_id}")
        return bool(result.get("ok"))

    # -- Comments ----------------------------------------------------------

    def add_comment(
        self, *, post_id: str, content: str, parent_id: str = "",
    ) -> MoltbookComment:
        """Add a comment (or reply) to a post."""
        body: dict[str, Any] = {"content": content}
        if parent_id:
            body["parent_id"] = parent_id
        result = self._call("POST", f"/posts/{post_id}/comments", body=body)
        return self._parse_comment(result)

    def get_comments(
        self,
        post_id: str,
        *,
        sort: str = "top",
    ) -> list[MoltbookComment]:
        """List comments on a post."""
        result = self._call(
            "GET", f"/posts/{post_id}/comments",
            params={"sort": sort},
        )
        return self._parse_comment_list(result)

    # -- Voting ------------------------------------------------------------

    def upvote_post(self, post_id: str) -> bool:
        result = self._call("POST", f"/posts/{post_id}/upvote")
        return bool(result.get("ok"))

    def downvote_post(self, post_id: str) -> bool:
        result = self._call("POST", f"/posts/{post_id}/downvote")
        return bool(result.get("ok"))

    def upvote_comment(self, comment_id: str) -> bool:
        result = self._call("POST", f"/comments/{comment_id}/upvote")
        return bool(result.get("ok"))

    # -- Submolts (communities) --------------------------------------------

    def create_submolt(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
    ) -> MoltbookSubmolt:
        """Create a new submolt community."""
        result = self._call("POST", "/submolts", body={
            "name": name,
            "display_name": display_name,
            "description": description,
        })
        return self._parse_submolt(result)

    def list_submolts(self) -> list[MoltbookSubmolt]:
        """List all available submolts."""
        result = self._call("GET", "/submolts")
        payload = result.get("payload", {})
        items = payload if isinstance(payload, list) else payload.get("submolts", [])
        out: list[MoltbookSubmolt] = []
        for item in (items if isinstance(items, list) else []):
            if isinstance(item, dict):
                out.append(self._submolt_from_dict(item))
        return out

    def get_submolt(self, name: str) -> MoltbookSubmolt:
        """Get details of a specific submolt."""
        result = self._call("GET", f"/submolts/{name}")
        return self._parse_submolt(result)

    def subscribe_submolt(self, name: str) -> bool:
        result = self._call("POST", f"/submolts/{name}/subscribe")
        return bool(result.get("ok"))

    def unsubscribe_submolt(self, name: str) -> bool:
        result = self._call("DELETE", f"/submolts/{name}/subscribe")
        return bool(result.get("ok"))

    # -- Following ---------------------------------------------------------

    def follow_agent(self, name: str) -> bool:
        result = self._call("POST", f"/agents/{name}/follow")
        return bool(result.get("ok"))

    def unfollow_agent(self, name: str) -> bool:
        result = self._call("DELETE", f"/agents/{name}/follow")
        return bool(result.get("ok"))

    # -- Search ------------------------------------------------------------

    def search(self, query: str, *, limit: int = 25) -> dict[str, Any]:
        """Search posts, agents, and submolts."""
        result = self._call("GET", "/search", params={
            "q": query,
            "limit": str(limit),
        })
        return result.get("payload", {})

    # -- Parsing helpers ---------------------------------------------------

    def _parse_post(self, result: dict[str, Any]) -> MoltbookPost:
        payload = result.get("payload", {})
        if not isinstance(payload, dict):
            return MoltbookPost(raw={"error": result.get("error", "unknown")})
        return self._post_from_dict(payload)

    def _parse_post_list(self, result: dict[str, Any]) -> list[MoltbookPost]:
        payload = result.get("payload", {})
        items = payload if isinstance(payload, list) else (
            payload.get("posts", []) if isinstance(payload, dict) else []
        )
        out: list[MoltbookPost] = []
        for item in (items if isinstance(items, list) else []):
            if isinstance(item, dict):
                out.append(self._post_from_dict(item))
        return out

    def _post_from_dict(self, d: dict[str, Any]) -> MoltbookPost:
        return MoltbookPost(
            post_id=str(d.get("id", "")),
            title=str(d.get("title", "")),
            content=str(d.get("content", "")),
            url=str(d.get("url", "")),
            submolt=str(d.get("submolt", "")),
            author=str(d.get("author", d.get("agent_name", ""))),
            upvotes=int(d.get("upvotes", 0)),
            downvotes=int(d.get("downvotes", 0)),
            comment_count=int(d.get("comment_count", d.get("comments", 0))),
            created_at=str(d.get("created_at", "")),
            raw=d,
        )

    def _parse_comment(self, result: dict[str, Any]) -> MoltbookComment:
        payload = result.get("payload", {})
        if not isinstance(payload, dict):
            return MoltbookComment(raw={"error": result.get("error", "unknown")})
        return self._comment_from_dict(payload)

    def _parse_comment_list(self, result: dict[str, Any]) -> list[MoltbookComment]:
        payload = result.get("payload", {})
        items = payload if isinstance(payload, list) else (
            payload.get("comments", []) if isinstance(payload, dict) else []
        )
        out: list[MoltbookComment] = []
        for item in (items if isinstance(items, list) else []):
            if isinstance(item, dict):
                out.append(self._comment_from_dict(item))
        return out

    def _comment_from_dict(self, d: dict[str, Any]) -> MoltbookComment:
        return MoltbookComment(
            comment_id=str(d.get("id", "")),
            post_id=str(d.get("post_id", "")),
            parent_id=str(d.get("parent_id", "")),
            content=str(d.get("content", "")),
            author=str(d.get("author", d.get("agent_name", ""))),
            upvotes=int(d.get("upvotes", 0)),
            created_at=str(d.get("created_at", "")),
            raw=d,
        )

    def _parse_submolt(self, result: dict[str, Any]) -> MoltbookSubmolt:
        payload = result.get("payload", {})
        if not isinstance(payload, dict):
            return MoltbookSubmolt(raw={"error": result.get("error", "unknown")})
        return self._submolt_from_dict(payload)

    def _submolt_from_dict(self, d: dict[str, Any]) -> MoltbookSubmolt:
        return MoltbookSubmolt(
            name=str(d.get("name", "")),
            display_name=str(d.get("display_name", "")),
            description=str(d.get("description", "")),
            subscriber_count=int(d.get("subscriber_count", d.get("subscribers", 0))),
            raw=d,
        )


# ---------------------------------------------------------------------------
# Claim-tweet authentication flow
# ---------------------------------------------------------------------------


class MoltbookAuthFlow:
    """Manages the Moltbook claim-tweet registration and verification flow.

    Steps:
    1. register_agent() → returns claim_url + verification_code
    2. User posts the verification_code on X/Twitter (manual step)
    3. poll_claim_status() → checks if claim was completed
    4. Once claimed, the api_key is active for all endpoints
    """

    def __init__(self, client: MoltbookClient) -> None:
        self._client = client
        self._profile: MoltbookAgentProfile | None = None

    @property
    def profile(self) -> MoltbookAgentProfile | None:
        return self._profile

    @property
    def is_claimed(self) -> bool:
        return self._profile is not None and self._profile.status == "claimed"

    def start_registration(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> MoltbookAgentProfile:
        """Register the agent and return the profile with claim instructions."""
        profile = self._client.register_agent(name=name, description=description)
        self._profile = profile
        if profile.api_key:
            self._client._config.api_key = profile.api_key
        return profile

    def poll_claim_status(self) -> str:
        """Check whether the claim tweet has been verified.

        Returns the current status string: 'claimed', 'unclaimed', or 'pending'.
        """
        status_data = self._client.get_status()
        current = str(status_data.get("status", "unclaimed"))
        if self._profile:
            self._profile.status = current
        return current

    def claim_instructions(self) -> str:
        """Return human-readable instructions for completing the claim."""
        if not self._profile:
            return "No registration in progress. Call start_registration() first."
        return (
            f"To verify your Moltbook agent '{self._profile.name}':\n"
            f"1. Visit: {self._profile.claim_url}\n"
            f"2. Post a tweet containing this code: {self._profile.verification_code}\n"
            f"3. Wait a moment, then the agent will be verified.\n"
            f"\nAPI key (store securely): {self._profile.api_key}"
        )


# ---------------------------------------------------------------------------
# Provider interface (used by Thomas channel/integration system)
# ---------------------------------------------------------------------------


def _resolve_config(
    config: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> MoltbookConfig:
    merged: dict[str, Any] = {}
    if isinstance(config, Mapping):
        merged.update({str(k): v for k, v in config.items()})
    merged.update({str(k): v for k, v in kwargs.items()})
    return MoltbookConfig(
        api_key=str(
            merged.get("api_key")
            or merged.get("token")
            or os.environ.get("MOLTBOOK_API_KEY", "")
        ).strip(),
        agent_name=str(
            merged.get("agent_name") or os.environ.get("MOLTBOOK_AGENT_NAME", _DEFAULT_AGENT_NAME)
        ).strip(),
        agent_description=str(
            merged.get("agent_description")
            or os.environ.get("MOLTBOOK_AGENT_DESCRIPTION", _DEFAULT_AGENT_DESCRIPTION)
        ).strip(),
        base_url=str(
            merged.get("base_url") or os.environ.get("MOLTBOOK_BASE_URL", _BASE_URL)
        ).strip(),
        timeout_s=float(merged.get("timeout_s", _DEFAULT_TIMEOUT_S)),
    )


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "moltbook",
        "name": "Moltbook",
        "capabilities": [
            "send", "health_check", "post", "comment", "vote",
            "submolt", "feed", "search", "follow",
        ],
        "required_config_keys": ["api_key"],
        "optional_config_keys": [
            "agent_name", "agent_description", "base_url", "timeout_s",
        ],
        "native": {
            "social": True,
            "agent_network": True,
            "communities": True,
        },
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "social": True,
        "agent_network": True,
        "communities": True,
        "posting": True,
        "commenting": True,
        "voting": True,
        "search": True,
    }


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = _resolve_config(config, **kwargs)
    if cfg.api_key:
        return {"message": "Moltbook credentials stored.", "agent_name": cfg.agent_name}
    client = MoltbookClient(cfg)
    auth = MoltbookAuthFlow(client)
    profile = auth.start_registration()
    return {
        "message": "Agent registered. Complete claim to activate.",
        "agent_name": profile.name,
        "api_key": profile.api_key,
        "claim_url": profile.claim_url,
        "verification_code": profile.verification_code,
        "instructions": auth.claim_instructions(),
    }


def logout(**_: Any) -> dict[str, Any]:
    return {
        "message": (
            "Moltbook logout is local-state only. "
            "Remove the stored API key to disconnect."
        ),
    }


def health_check(
    config: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = _resolve_config(config, **kwargs)
    if not cfg.api_key:
        return {"ok": False, "details": {"reason": "missing api_key"}}
    client = MoltbookClient(cfg)
    try:
        profile = client.get_profile()
        agent_name = str(profile.get("name", "")).strip()
        ok = bool(agent_name)
        return {
            "ok": ok,
            "details": {
                "agent_name": agent_name,
                "status": str(profile.get("status", "")),
            },
        }
    except Exception as e:
        return {"ok": False, "details": {"reason": str(e)}}


def send_message(
    request: Any = None,
    *,
    config: Mapping[str, Any] | None = None,
    recipient: str | None = None,
    message: str | None = None,
    text: str | None = None,
    subject: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    dry_run: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Send a message to Moltbook as a post.

    For the channel adapter pattern, 'recipient' maps to the submolt name
    and 'message' becomes the post content. 'subject' becomes the title.
    """
    cfg = _resolve_config(config, **kwargs)
    if not cfg.api_key:
        raise ValueError("Moltbook api_key is required.")

    # Extract fields from request object if provided.
    body_text = str(message or text or "").strip()
    title = str(subject or "").strip()
    target_submolt = str(recipient or "general").strip()
    is_dry = bool(dry_run)

    if request is not None:
        if hasattr(request, "message"):
            body_text = str(request.message or body_text).strip()
        if hasattr(request, "recipient"):
            target_submolt = str(request.recipient or target_submolt).strip()
        if hasattr(request, "subject"):
            title = str(request.subject or title).strip()
        if hasattr(request, "metadata") and isinstance(request.metadata, Mapping):
            meta = dict(request.metadata)
            target_submolt = str(meta.get("submolt", target_submolt)).strip()
            title = str(meta.get("title", title)).strip()
        if hasattr(request, "dry_run"):
            is_dry = bool(request.dry_run)

    if not body_text:
        raise ValueError("Moltbook post content is required.")
    if not title:
        title = body_text[:80].split("\n")[0]

    if is_dry:
        return {
            "delivered": True,
            "message_id": "dry-run",
            "provider_response": {"mode": "dry_run"},
        }

    client = MoltbookClient(cfg)
    post = client.create_text_post(
        submolt=target_submolt,
        title=title,
        content=body_text,
    )
    delivered = bool(post.post_id)
    return {
        "delivered": delivered,
        "message_id": post.post_id,
        "provider_response": post.raw,
    }
