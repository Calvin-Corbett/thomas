"""Google Workspace integration for Thomas.

Provides access to Gmail, Google Calendar, and Google Drive APIs.
Requires OAuth2 authentication with appropriate Google Cloud credentials.
"""

from __future__ import annotations

from thomas.integrations.google_workspace.integration import GoogleWorkspaceIntegration

__all__ = ["GoogleWorkspaceIntegration"]
