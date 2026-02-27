"""Slack integration for Thomas.

Provides asynchronous Slack workspace interactions using the Slack Web API.
Includes OAuth2 flow, message operations, channel management, user lookup,
and file operations.
"""

from __future__ import annotations

from .integration import SlackIntegration

__all__ = ["SlackIntegration"]
