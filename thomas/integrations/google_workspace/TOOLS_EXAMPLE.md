# Google Workspace Integration - Thomas Tool Examples

This document shows how to create Thomas tools that use the Google Workspace integration.

## Tool: Gmail - Send Email

```python
# In thomas/tools/gmail_send.py

from __future__ import annotations

import json
from typing import Any, Dict

from thomas.tools.base import Tool, ToolResult
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration


class GmailSendTool(Tool):
    """Send emails via Gmail."""

    def __init__(self, integration: GoogleWorkspaceIntegration) -> None:
        self.integration = integration

    def schema(self) -> Dict[str, Any]:
        return {
            "name": "gmail_send",
            "description": "Send an email via Gmail",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text",
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CC recipients",
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "BCC recipients",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        }

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self.integration.execute(
                service="gmail",
                operation="send_message",
                to=kwargs["to"],
                subject=kwargs["subject"],
                body=kwargs["body"],
                cc=kwargs.get("cc"),
                bcc=kwargs.get("bcc"),
            )

            return ToolResult(
                output=json.dumps({
                    "success": True,
                    "message_id": result.get("messageId"),
                    "thread_id": result.get("threadId"),
                }),
                status="success",
            )
        except Exception as e:
            return ToolResult(
                output=json.dumps({"error": str(e)}),
                status="error",
            )
```

## Tool: Google Calendar - Create Event

```python
# In thomas/tools/calendar_create_event.py

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from thomas.tools.base import Tool, ToolResult
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration


class CalendarCreateEventTool(Tool):
    """Create a calendar event in Google Calendar."""

    def __init__(self, integration: GoogleWorkspaceIntegration) -> None:
        self.integration = integration

    def schema(self) -> Dict[str, Any]:
        return {
            "name": "calendar_create_event",
            "description": "Create an event in Google Calendar",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time (RFC 3339 or ISO format)",
                    },
                    "end": {
                        "type": "string",
                        "description": "End time (RFC 3339 or ISO format)",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Attendee email addresses",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description",
                    },
                },
                "required": ["summary", "start", "end"],
            },
        }

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self.integration.execute(
                service="calendar",
                operation="create_event",
                calendar_id="primary",
                summary=kwargs["summary"],
                start=kwargs["start"],
                end=kwargs["end"],
                location=kwargs.get("location", ""),
                attendees=kwargs.get("attendees"),
                description=kwargs.get("description", ""),
            )

            return ToolResult(
                output=json.dumps({
                    "success": True,
                    "event_id": result.get("eventId"),
                    "html_link": result.get("htmlLink"),
                }),
                status="success",
            )
        except Exception as e:
            return ToolResult(
                output=json.dumps({"error": str(e)}),
                status="error",
            )
```

## Tool: Google Drive - Upload File

```python
# In thomas/tools/drive_upload.py

from __future__ import annotations

import json
from typing import Any, Dict

from thomas.tools.base import Tool, ToolResult
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration


class DriveUploadTool(Tool):
    """Upload a file to Google Drive."""

    def __init__(self, integration: GoogleWorkspaceIntegration) -> None:
        self.integration = integration

    def schema(self) -> Dict[str, Any]:
        return {
            "name": "drive_upload",
            "description": "Upload a file to Google Drive",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Local path to file to upload",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for file in Drive (optional)",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Destination folder ID (default: root)",
                    },
                },
                "required": ["file_path"],
            },
        }

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self.integration.execute(
                service="drive",
                operation="upload_file",
                file_path=kwargs["file_path"],
                name=kwargs.get("name"),
                folder_id=kwargs.get("folder_id", "root"),
            )

            return ToolResult(
                output=json.dumps({
                    "success": True,
                    "file_id": result.get("fileId"),
                    "name": result.get("name"),
                    "web_link": result.get("webViewLink"),
                }),
                status="success",
            )
        except Exception as e:
            return ToolResult(
                output=json.dumps({"error": str(e)}),
                status="error",
            )
```

## Tool: Gmail - List Unread Messages

```python
# In thomas/tools/gmail_list_unread.py

from __future__ import annotations

import json
from typing import Any, Dict

from thomas.tools.base import Tool, ToolResult
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration


class GmailListUnreadTool(Tool):
    """List unread emails in Gmail."""

    def __init__(self, integration: GoogleWorkspaceIntegration) -> None:
        self.integration = integration

    def schema(self) -> Dict[str, Any]:
        return {
            "name": "gmail_list_unread",
            "description": "List unread messages in Gmail",
            "input_schema": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum messages to return (default: 10)",
                    },
                    "from_address": {
                        "type": "string",
                        "description": "Filter by sender (optional)",
                    },
                },
            },
        }

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            # Build query
            query = "is:unread"
            if kwargs.get("from_address"):
                query += f" from:{kwargs['from_address']}"

            result = await self.integration.execute(
                service="gmail",
                operation="list_messages",
                query=query,
                max_results=kwargs.get("max_results", 10),
            )

            messages = []
            for msg in result.get("messages", []):
                messages.append({
                    "id": msg.get("messageId"),
                    "from": msg.get("headers", {}).get("from"),
                    "subject": msg.get("headers", {}).get("subject"),
                    "snippet": msg.get("snippet"),
                })

            return ToolResult(
                output=json.dumps({
                    "success": True,
                    "count": len(messages),
                    "messages": messages,
                }),
                status="success",
            )
        except Exception as e:
            return ToolResult(
                output=json.dumps({"error": str(e)}),
                status="error",
            )
```

## Registering Tools

To use these tools in Thomas, register them in your tool registry:

```python
# In your Thomas application setup

from thomas.integrations.google_workspace import GoogleWorkspaceIntegration
from thomas.tools.gmail_send import GmailSendTool
from thomas.tools.calendar_create_event import CalendarCreateEventTool
from thomas.tools.drive_upload import DriveUploadTool
from thomas.tools.gmail_list_unread import GmailListUnreadTool

# Initialize the integration
integration = GoogleWorkspaceIntegration(
    client_id=config.google.client_id,
    client_secret=config.google.client_secret,
    redirect_uri=config.google.redirect_uri,
    secrets_manager=config.secrets,
)

await integration.connect()

# Register tools
tools.register(GmailSendTool(integration))
tools.register(CalendarCreateEventTool(integration))
tools.register(DriveUploadTool(integration))
tools.register(GmailListUnreadTool(integration))
```

## Integration with Tool System

The Google Workspace integration can be used in two ways:

### Direct Tool Usage

Use specific tool functions directly:

```python
result = await tools.execute("gmail_send", to="user@example.com", ...)
```

### Raw Integration Usage

Access the integration directly for complex workflows:

```python
# Get the integration from your registry
integration = app.config.integrations["google_workspace"]

# Perform multi-step operation
events = await integration.execute(
    service="calendar",
    operation="list_events",
    calendar_id="primary",
)

for event in events["events"]:
    # Process each event
    await integration.execute(
        service="drive",
        operation="upload_file",
        file_path=f"/reports/{event['summary']}.pdf",
    )
```

## Error Handling in Tools

```python
from thomas.integrations.google_workspace.auth import TokenExpiredError
from thomas.integrations.google_workspace.gmail import GmailError

async def tool_with_error_handling(**kwargs):
    try:
        result = await integration.execute(...)
        return ToolResult(output=json.dumps(result), status="success")
    except TokenExpiredError:
        return ToolResult(
            output="Authentication expired, please re-authorize",
            status="error",
        )
    except GmailError as e:
        return ToolResult(
            output=f"Gmail error: {e}",
            status="error",
        )
    except Exception as e:
        return ToolResult(
            output=f"Unexpected error: {e}",
            status="error",
        )
```

## Configuration

Store Google credentials in Thomas config:

```toml
# thomas.toml

[google]
client_id = "YOUR_CLIENT_ID.apps.googleusercontent.com"
client_secret = "YOUR_CLIENT_SECRET"
redirect_uri = "http://localhost:8080/callback"
```

Or use environment variables:

```bash
export THOMAS_GOOGLE_CLIENT_ID="..."
export THOMAS_GOOGLE_CLIENT_SECRET="..."
export THOMAS_GOOGLE_REDIRECT_URI="..."
```

Load in application:

```python
integration = GoogleWorkspaceIntegration(
    client_id=os.getenv("THOMAS_GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("THOMAS_GOOGLE_CLIENT_SECRET"),
    redirect_uri=os.getenv("THOMAS_GOOGLE_REDIRECT_URI"),
)
```
