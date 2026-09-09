"""Moltbook agent tools for the Thomas tool registry.

Exposes Moltbook capabilities as agent-callable tools so Thomas agents can
post, comment, vote, browse feeds, manage submolts, follow other agents,
and search the Moltbook AI social network.

Tools are registered with the Thomas tool registry and become available to
the agent loop. Each tool follows the standard Thomas tool contract:
name, description, parameters (JSON schema), and a handler function.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy client construction
# ---------------------------------------------------------------------------

_CLIENT_CACHE: dict[str, Any] = {}


def _get_client() -> Any:
    """Lazily construct and cache a MoltbookClient."""
    from thomas.integrations.moltbook import MoltbookClient, MoltbookConfig

    cache_key = "default"
    cached = _CLIENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    api_key = str(os.environ.get("MOLTBOOK_API_KEY", "")).strip()
    agent_name = str(os.environ.get("MOLTBOOK_AGENT_NAME", "thomas")).strip()
    agent_desc = str(os.environ.get("MOLTBOOK_AGENT_DESCRIPTION", "") or "Thomas AI workspace agent").strip()

    client = MoltbookClient(
        MoltbookConfig(
            api_key=api_key,
            agent_name=agent_name,
            agent_description=agent_desc,
        )
    )
    _CLIENT_CACHE[cache_key] = client
    return client


def _format_post(post: Any) -> str:
    """Format a MoltbookPost for display."""
    votes = f"+{post.upvotes}/-{post.downvotes}"
    header = f"[{post.submolt}] {post.title} (by {post.author}, {votes})"
    body = post.content[:500] if post.content else post.url
    return f"{header}\n{body}\nID: {post.post_id}"


def _format_comment(comment: Any) -> str:
    """Format a MoltbookComment for display."""
    prefix = f"  └─ reply to {comment.parent_id}" if comment.parent_id else ""
    return f"{comment.author} (+{comment.upvotes}){prefix}\n  {comment.content[:300]}\n  ID: {comment.comment_id}"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_moltbook_register(
    name: str = "",
    description: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Register a new agent on Moltbook and start the claim-tweet flow."""
    from thomas.integrations.moltbook import MoltbookAuthFlow

    client = _get_client()
    auth = MoltbookAuthFlow(client)
    profile = auth.start_registration(
        name=name or None,
        description=description or None,
    )
    return {
        "success": bool(profile.api_key),
        "agent_name": profile.name,
        "api_key": profile.api_key,
        "claim_url": profile.claim_url,
        "verification_code": profile.verification_code,
        "instructions": auth.claim_instructions(),
    }


def handle_moltbook_status(**_: Any) -> dict[str, Any]:
    """Check the current agent's Moltbook claim and profile status."""
    client = _get_client()
    status = client.get_status()
    profile = client.get_profile()
    return {
        "status": str(status.get("status", "unknown")),
        "agent_name": str(profile.get("name", "")),
        "description": str(profile.get("description", "")),
        "profile": profile,
    }


def handle_moltbook_post(
    submolt: str = "general",
    title: str = "",
    content: str = "",
    url: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Create a new post on Moltbook."""
    client = _get_client()
    if not title:
        return {"success": False, "error": "title is required"}
    if not content and not url:
        return {"success": False, "error": "content or url is required"}
    if url:
        post = client.create_link_post(submolt=submolt, title=title, url=url)
    else:
        post = client.create_text_post(submolt=submolt, title=title, content=content)
    return {
        "success": bool(post.post_id),
        "post_id": post.post_id,
        "formatted": _format_post(post),
    }


def handle_moltbook_comment(
    post_id: str = "",
    content: str = "",
    parent_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Add a comment or reply to a Moltbook post."""
    client = _get_client()
    if not post_id:
        return {"success": False, "error": "post_id is required"}
    if not content:
        return {"success": False, "error": "content is required"}
    comment = client.add_comment(
        post_id=post_id,
        content=content,
        parent_id=parent_id,
    )
    return {
        "success": bool(comment.comment_id),
        "comment_id": comment.comment_id,
        "formatted": _format_comment(comment),
    }


def handle_moltbook_vote(
    target_id: str = "",
    target_type: str = "post",
    direction: str = "up",
    **_: Any,
) -> dict[str, Any]:
    """Upvote or downvote a post or comment."""
    client = _get_client()
    if not target_id:
        return {"success": False, "error": "target_id is required"}
    if target_type == "comment":
        ok = client.upvote_comment(target_id)
        return {"success": ok, "action": "upvote_comment", "target": target_id}
    if direction == "down":
        ok = client.downvote_post(target_id)
        return {"success": ok, "action": "downvote_post", "target": target_id}
    ok = client.upvote_post(target_id)
    return {"success": ok, "action": "upvote_post", "target": target_id}


def handle_moltbook_feed(
    feed_type: str = "global",
    sort: str = "hot",
    limit: int = 10,
    **_: Any,
) -> dict[str, Any]:
    """Browse the Moltbook feed."""
    client = _get_client()
    limit = max(1, min(limit, 50))
    if feed_type == "personalized":
        posts = client.get_personalized_feed(sort=sort, limit=limit)
    else:
        posts = client.get_feed(sort=sort, limit=limit)
    formatted = "\n\n---\n\n".join(_format_post(p) for p in posts)
    return {
        "count": len(posts),
        "feed_type": feed_type,
        "sort": sort,
        "posts": [p.raw for p in posts],
        "formatted": formatted or "No posts found.",
    }


def handle_moltbook_get_post(
    post_id: str = "",
    include_comments: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """Get a specific post and optionally its comments."""
    client = _get_client()
    if not post_id:
        return {"success": False, "error": "post_id is required"}
    post = client.get_post(post_id)
    result: dict[str, Any] = {
        "success": bool(post.post_id),
        "post": post.raw,
        "formatted": _format_post(post),
    }
    if include_comments:
        comments = client.get_comments(post_id)
        result["comments"] = [c.raw for c in comments]
        result["formatted_comments"] = "\n".join(_format_comment(c) for c in comments)
    return result


def handle_moltbook_submolt(
    action: str = "list",
    name: str = "",
    display_name: str = "",
    description: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Manage Moltbook submolts (communities)."""
    client = _get_client()
    if action == "create":
        if not name:
            return {"success": False, "error": "name is required to create a submolt"}
        submolt = client.create_submolt(
            name=name,
            display_name=display_name or name,
            description=description or f"A community for {name}",
        )
        return {
            "success": bool(submolt.name),
            "submolt": submolt.raw,
        }
    if action == "get" and name:
        submolt = client.get_submolt(name)
        return {"success": bool(submolt.name), "submolt": submolt.raw}
    if action == "subscribe" and name:
        return {"success": client.subscribe_submolt(name), "action": "subscribed"}
    if action == "unsubscribe" and name:
        return {"success": client.unsubscribe_submolt(name), "action": "unsubscribed"}
    # Default: list
    submolts = client.list_submolts()
    return {
        "count": len(submolts),
        "submolts": [s.raw for s in submolts],
        "names": [s.name for s in submolts],
    }


def handle_moltbook_follow(
    agent_name: str = "",
    action: str = "follow",
    **_: Any,
) -> dict[str, Any]:
    """Follow or unfollow another agent."""
    client = _get_client()
    if not agent_name:
        return {"success": False, "error": "agent_name is required"}
    if action == "unfollow":
        ok = client.unfollow_agent(agent_name)
        return {"success": ok, "action": "unfollowed", "agent": agent_name}
    ok = client.follow_agent(agent_name)
    return {"success": ok, "action": "followed", "agent": agent_name}


def handle_moltbook_search(
    query: str = "",
    limit: int = 10,
    **_: Any,
) -> dict[str, Any]:
    """Search Moltbook for posts, agents, and submolts."""
    client = _get_client()
    if not query:
        return {"success": False, "error": "query is required"}
    results = client.search(query, limit=max(1, min(limit, 50)))
    return {"success": True, "results": results}


def handle_moltbook_view_agent(
    agent_name: str = "",
    **_: Any,
) -> dict[str, Any]:
    """View another agent's public profile."""
    client = _get_client()
    if not agent_name:
        return {"success": False, "error": "agent_name is required"}
    profile = client.get_agent_profile(agent_name)
    return {"success": bool(profile), "profile": profile}


def handle_moltbook_delete_post(
    post_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Delete a post you authored."""
    client = _get_client()
    if not post_id:
        return {"success": False, "error": "post_id is required"}
    ok = client.delete_post(post_id)
    return {"success": ok, "post_id": post_id}


# ---------------------------------------------------------------------------
# Tool definitions for the Thomas tool registry
# ---------------------------------------------------------------------------

MOLTBOOK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "moltbook_register",
        "description": (
            "Register a new agent on Moltbook and start the claim-tweet "
            "verification flow. Returns an API key and instructions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent display name"},
                "description": {"type": "string", "description": "Agent bio/description"},
            },
        },
        "handler": handle_moltbook_register,
    },
    {
        "name": "moltbook_status",
        "description": "Check the current Moltbook agent's profile and claim status.",
        "parameters": {"type": "object", "properties": {}},
        "handler": handle_moltbook_status,
    },
    {
        "name": "moltbook_post",
        "description": (
            "Create a new post on Moltbook. Specify a submolt (community), title, and either text content or a URL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "submolt": {
                    "type": "string",
                    "description": "Target submolt community name (default: general)",
                },
                "title": {"type": "string", "description": "Post title (required)"},
                "content": {"type": "string", "description": "Post body text"},
                "url": {"type": "string", "description": "URL for link posts"},
            },
            "required": ["title"],
        },
        "handler": handle_moltbook_post,
    },
    {
        "name": "moltbook_comment",
        "description": "Add a comment or reply to a Moltbook post.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "ID of the post to comment on"},
                "content": {"type": "string", "description": "Comment text"},
                "parent_id": {
                    "type": "string",
                    "description": "Parent comment ID for nested replies (optional)",
                },
            },
            "required": ["post_id", "content"],
        },
        "handler": handle_moltbook_comment,
    },
    {
        "name": "moltbook_vote",
        "description": "Upvote or downvote a post or comment on Moltbook.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Post or comment ID"},
                "target_type": {
                    "type": "string",
                    "enum": ["post", "comment"],
                    "description": "Whether voting on a post or comment",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Vote direction (down only for posts)",
                },
            },
            "required": ["target_id"],
        },
        "handler": handle_moltbook_vote,
    },
    {
        "name": "moltbook_feed",
        "description": (
            "Browse the Moltbook feed. Use 'global' for all posts or "
            "'personalized' for subscribed content. Sort by hot/new/top/rising."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feed_type": {
                    "type": "string",
                    "enum": ["global", "personalized"],
                    "description": "Feed scope",
                },
                "sort": {
                    "type": "string",
                    "enum": ["hot", "new", "top", "rising"],
                    "description": "Sort order",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max posts to return (1-50)",
                },
            },
        },
        "handler": handle_moltbook_feed,
    },
    {
        "name": "moltbook_get_post",
        "description": "Get a specific Moltbook post by ID, with comments.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "Post ID"},
                "include_comments": {
                    "type": "boolean",
                    "description": "Whether to include comments (default: true)",
                },
            },
            "required": ["post_id"],
        },
        "handler": handle_moltbook_get_post,
    },
    {
        "name": "moltbook_submolt",
        "description": ("Manage Moltbook submolts (communities): list, get, create, subscribe, or unsubscribe."),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "subscribe", "unsubscribe"],
                    "description": "Action to perform",
                },
                "name": {"type": "string", "description": "Submolt name"},
                "display_name": {"type": "string", "description": "Display name (for create)"},
                "description": {"type": "string", "description": "Description (for create)"},
            },
        },
        "handler": handle_moltbook_submolt,
    },
    {
        "name": "moltbook_follow",
        "description": "Follow or unfollow another agent on Moltbook.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Agent name to follow/unfollow"},
                "action": {
                    "type": "string",
                    "enum": ["follow", "unfollow"],
                    "description": "Follow or unfollow",
                },
            },
            "required": ["agent_name"],
        },
        "handler": handle_moltbook_follow,
    },
    {
        "name": "moltbook_search",
        "description": "Search Moltbook for posts, agents, and submolts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (1-50)"},
            },
            "required": ["query"],
        },
        "handler": handle_moltbook_search,
    },
    {
        "name": "moltbook_view_agent",
        "description": "View another agent's public profile on Moltbook.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Agent name to view"},
            },
            "required": ["agent_name"],
        },
        "handler": handle_moltbook_view_agent,
    },
    {
        "name": "moltbook_delete_post",
        "description": "Delete a post you authored on Moltbook.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "string", "description": "Post ID to delete"},
            },
            "required": ["post_id"],
        },
        "handler": handle_moltbook_delete_post,
    },
]
