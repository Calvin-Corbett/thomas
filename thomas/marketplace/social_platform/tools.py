"""Tools for Social Platform system - exposes user management, content, messaging, and analytics."""

from typing import Any
from uuid import UUID

from thomas.tools.base import Tool, ToolResult


class SocialRegisterUserTool(Tool):
    """Register a new user on the social platform."""

    name = "social.register_user"
    category = "social"
    description = "Register a new user with username, email, password, and profile info"
    parameters = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "Unique username"},
            "email": {"type": "string", "description": "Email address"},
            "password": {"type": "string", "description": "Password"},
            "full_name": {"type": "string", "description": "User's full name"},
            "bio": {"type": "string", "description": "User bio (optional)"},
        },
        "required": ["username", "email", "password", "full_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.users import UserManager

        um = UserManager()
        try:
            user = um.register_user(
                username=args["username"],
                email=args["email"],
                password=args["password"],
                full_name=args["full_name"],
                bio=args.get("bio", ""),
            )
            return ToolResult(
                ok=True,
                data={
                    "user_id": str(user.user_id),
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialGetUserTool(Tool):
    """Get user profile information."""

    name = "social.get_user"
    category = "social"
    description = "Retrieve user profile including followers, following, and bio"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "User ID or username"},
        },
        "required": ["user_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.users import UserManager

        um = UserManager()
        try:
            user_id = args["user_id"]
            try:
                user_uuid = UUID(user_id)
                user = um.get_user_by_id(user_uuid)
            except (ValueError, TypeError):
                user = um.get_user_by_username(user_id)
            return ToolResult(
                ok=True,
                data={
                    "user_id": str(user.user_id),
                    "username": user.username,
                    "full_name": user.full_name,
                    "bio": user.bio,
                    "email": user.email,
                    "created_at": str(user.created_at) if hasattr(user, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialCreatePostTool(Tool):
    """Create a new post on the social platform."""

    name = "social.create_post"
    category = "social"
    description = "Create a new post with text content, optional media and hashtags"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "Creator user ID"},
            "content": {"type": "string", "description": "Post content text"},
            "media_urls": {"type": "array", "items": {"type": "string"}, "description": "Optional list of media URLs"},
        },
        "required": ["user_id", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.content import ContentManager

        cm = ContentManager()
        try:
            user_id = UUID(args["user_id"])
            post = cm.create_post(
                user_id=user_id,
                content=args["content"],
                media_urls=args.get("media_urls", []),
            )
            return ToolResult(
                ok=True,
                data={
                    "post_id": str(post.post_id),
                    "user_id": str(post.user_id),
                    "content": post.content,
                    "created_at": str(post.created_at) if hasattr(post, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialSearchPostsTool(Tool):
    """Search for posts on the platform."""

    name = "social.search_posts"
    category = "social"
    description = "Search for posts by keyword or hashtag"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query or hashtag"},
            "search_type": {"type": "string", "enum": ["keyword", "hashtag"], "description": "Type of search"},
            "limit": {"type": "integer", "description": "Maximum results (default 20)"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.content import ContentManager

        cm = ContentManager()
        try:
            limit = args.get("limit", 20)
            if args.get("search_type") == "hashtag":
                posts = cm.search_by_hashtag(args["query"], limit=limit)
            else:
                posts = cm.search_posts(args["query"], limit=limit)
            return ToolResult(
                ok=True,
                data=[
                    {
                        "post_id": str(p.post_id),
                        "user_id": str(p.user_id),
                        "content": p.content[:100],
                        "created_at": str(p.created_at) if hasattr(p, "created_at") else None,
                    }
                    for p in posts
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialFollowUserTool(Tool):
    """Follow another user."""

    name = "social.follow_user"
    category = "social"
    description = "Follow a user to see their posts in your feed"
    parameters = {
        "type": "object",
        "properties": {
            "follower_id": {"type": "string", "description": "Your user ID"},
            "following_id": {"type": "string", "description": "User to follow ID"},
        },
        "required": ["follower_id", "following_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.users import UserManager

        um = UserManager()
        try:
            follower_uuid = UUID(args["follower_id"])
            following_uuid = UUID(args["following_id"])
            follow = um.follow_user(follower_uuid, following_uuid)
            return ToolResult(
                ok=True,
                data={
                    "follower_id": str(follow.follower_id),
                    "following_id": str(follow.following_id),
                    "created_at": str(follow.created_at) if hasattr(follow, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialGetFollowersTool(Tool):
    """Get a user's followers."""

    name = "social.get_followers"
    category = "social"
    description = "Retrieve list of users following a specific user"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "User ID"},
        },
        "required": ["user_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.users import UserManager

        um = UserManager()
        try:
            user_uuid = UUID(args["user_id"])
            followers = um.get_followers(user_uuid)
            return ToolResult(
                ok=True,
                data=[
                    {
                        "user_id": str(f.user_id),
                        "username": f.username,
                        "full_name": f.full_name,
                    }
                    for f in followers
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialBlockUserTool(Tool):
    """Block a user from interacting with you."""

    name = "social.block_user"
    category = "social"
    description = "Block a user to prevent them from seeing your posts and messaging you"
    parameters = {
        "type": "object",
        "properties": {
            "blocker_id": {"type": "string", "description": "Your user ID"},
            "blocked_id": {"type": "string", "description": "User to block ID"},
        },
        "required": ["blocker_id", "blocked_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.users import UserManager

        um = UserManager()
        try:
            blocker_uuid = UUID(args["blocker_id"])
            blocked_uuid = UUID(args["blocked_id"])
            block = um.block_user(blocker_uuid, blocked_uuid)
            return ToolResult(
                ok=True,
                data={
                    "blocker_id": str(block.blocker_id),
                    "blocked_id": str(block.blocked_id),
                    "created_at": str(block.created_at) if hasattr(block, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SocialCreateCommentTool(Tool):
    """Create a comment on a post."""

    name = "social.create_comment"
    category = "social"
    description = "Comment on a post with reply text"
    parameters = {
        "type": "object",
        "properties": {
            "post_id": {"type": "string", "description": "Post ID to comment on"},
            "user_id": {"type": "string", "description": "Your user ID"},
            "content": {"type": "string", "description": "Comment text"},
        },
        "required": ["post_id", "user_id", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.social_platform.content import ContentManager

        cm = ContentManager()
        try:
            post_uuid = UUID(args["post_id"])
            user_uuid = UUID(args["user_id"])
            comment = cm.create_comment(
                post_id=post_uuid,
                user_id=user_uuid,
                content=args["content"],
            )
            return ToolResult(
                ok=True,
                data={
                    "comment_id": str(comment.comment_id),
                    "post_id": str(comment.post_id),
                    "user_id": str(comment.user_id),
                    "content": comment.content,
                    "created_at": str(comment.created_at) if hasattr(comment, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_social_platform_tools(registry, sandbox=None):
    """Register all social platform tools."""
    registry.register(SocialRegisterUserTool())
    registry.register(SocialGetUserTool())
    registry.register(SocialCreatePostTool())
    registry.register(SocialSearchPostsTool())
    registry.register(SocialFollowUserTool())
    registry.register(SocialGetFollowersTool())
    registry.register(SocialBlockUserTool())
    registry.register(SocialCreateCommentTool())
