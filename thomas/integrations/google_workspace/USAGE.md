# Google Workspace Integration for Thomas

Complete integration for Gmail, Google Calendar, and Google Drive APIs with OAuth2 authentication.

## Setup

### Prerequisites

1. Google Cloud Project with credentials:
   - OAuth2 client ID and secret
   - Redirect URI (e.g., `http://localhost:8080/callback`)

2. Required scopes are automatically configured:
   - Gmail: read/send
   - Calendar: read/write
   - Drive: read/write

### Installation

```bash
# Google Workspace integration is built-in, just ensure aiohttp is installed
pip install aiohttp
```

## Quick Start

### 1. Initialize Integration

```python
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration

integration = GoogleWorkspaceIntegration(
    client_id="YOUR_CLIENT_ID.apps.googleusercontent.com",
    client_secret="YOUR_CLIENT_SECRET",
    redirect_uri="http://localhost:8080/callback",
    secrets_manager=your_secrets_manager,  # Optional
)

await integration.connect()
```

### 2. OAuth2 Authentication Flow

```python
# Step 1: Generate authorization URL
auth_url, code_verifier = integration.generate_auth_url()
print(f"Visit this URL to authorize: {auth_url}")

# Step 2: User visits URL and authorizes
# Step 3: Handle callback with authorization code
authorization_code = "code_from_callback"
await integration.exchange_auth_code(authorization_code, code_verifier)
```

### 3. Check Health

```python
health = await integration.health_check()
print(health)
# Output: {'status': 'healthy', 'gmail': 'ok', 'calendar': 'ok', 'drive': 'ok', ...}
```

## Gmail Operations

### List Messages

```python
result = await integration.execute(
    command="gmail.list_messages",
    service="gmail",
    operation="list_messages",
    query="is:unread",  # Gmail search query
    max_results=10,
)
print(result['messages'])  # List of message objects
```

### Get Message Details

```python
message = await integration.execute(
    command="gmail.get_message",
    service="gmail",
    operation="get_message",
    message_id="message_id_here",
    format="full",  # "minimal" or "full"
)
print(message['body'])  # Message body text
print(message['attachmentCount'])  # Number of attachments
```

### Send Email

```python
result = await integration.execute(
    command="gmail.send_message",
    service="gmail",
    operation="send_message",
    to="recipient@example.com",
    subject="Hello",
    body="This is the message body",
    cc=["cc@example.com"],
    bcc=["bcc@example.com"],
)
print(result['messageId'])  # Sent message ID
```

### Create Draft

```python
draft = await integration.execute(
    command="gmail.create_draft",
    service="gmail",
    operation="create_draft",
    to="recipient@example.com",
    subject="Draft email",
    body="This is a draft",
)
print(draft['draftId'])
```

### List Labels

```python
labels = await integration.execute(
    command="gmail.list_labels",
    service="gmail",
    operation="list_labels",
)
for label in labels['labels']:
    print(f"{label['name']}: {label['id']}")
```

### Modify Labels

```python
result = await integration.execute(
    command="gmail.modify_labels",
    service="gmail",
    operation="modify_labels",
    message_id="message_id",
    add_labels=["LABEL_ID_1"],
    remove_labels=["LABEL_ID_2"],
)
```

## Calendar Operations

### List Calendars

```python
calendars = await integration.execute(
    command="calendar.list_calendars",
    service="calendar",
    operation="list_calendars",
)
for cal in calendars['calendars']:
    print(f"{cal['summary']}: {cal['id']}")
```

### List Events

```python
events = await integration.execute(
    command="calendar.list_events",
    service="calendar",
    operation="list_events",
    calendar_id="primary",  # or specific calendar ID
    time_min="2024-02-26T00:00:00Z",  # RFC 3339
    time_max="2024-02-27T23:59:59Z",
    max_results=25,
)
for event in events['events']:
    print(f"{event['summary']}: {event['startTime']} - {event['endTime']}")
```

### Create Event

```python
event = await integration.execute(
    command="calendar.create_event",
    service="calendar",
    operation="create_event",
    calendar_id="primary",
    summary="Team Meeting",
    start="2024-02-26T14:00:00",
    end="2024-02-26T15:00:00",
    location="Conference Room A",
    attendees=["colleague@example.com"],
    description="Quarterly planning",
)
print(event['eventId'])
```

### Update Event

```python
event = await integration.execute(
    command="calendar.update_event",
    service="calendar",
    operation="update_event",
    calendar_id="primary",
    event_id="event_id",
    updates={
        "summary": "Updated Meeting Title",
        "start": "2024-02-26T15:00:00",
        "end": "2024-02-26T16:00:00",
    }
)
```

### Delete Event

```python
result = await integration.execute(
    command="calendar.delete_event",
    service="calendar",
    operation="delete_event",
    calendar_id="primary",
    event_id="event_id",
)
```

### Check Free/Busy

```python
freebusy = await integration.execute(
    command="calendar.check_freebusy",
    service="calendar",
    operation="check_freebusy",
    calendar_ids=["primary", "other@example.com"],
    time_min="2024-02-26T09:00:00Z",
    time_max="2024-02-26T17:00:00Z",
)
for cal_id, info in freebusy['calendars'].items():
    print(f"{cal_id}: {len(info['busy'])} busy slots")
```

## Drive Operations

### List Files

```python
files = await integration.execute(
    command="drive.list_files",
    service="drive",
    operation="list_files",
    query="name contains 'report'",  # Optional search
    max_results=50,
    folder_id="folder_id_or_none",  # Filter by folder
)
for file in files['files']:
    print(f"{file['name']}: {file['size']} bytes")
```

### Search Files

```python
results = await integration.execute(
    command="drive.search_files",
    service="drive",
    operation="search_files",
    query="budget",
    max_results=25,
)
```

### Get File Metadata

```python
file_info = await integration.execute(
    command="drive.get_file",
    service="drive",
    operation="get_file",
    file_id="file_id",
)
print(file_info['name'])
print(file_info['webViewLink'])  # Google Drive link
```

### Download File

```python
result = await integration.execute(
    command="drive.download_file",
    service="drive",
    operation="download_file",
    file_id="file_id",
    output_path="/local/path/filename.pdf",
)
print(f"Downloaded {result['size']} bytes")
```

### Upload File

```python
file_info = await integration.execute(
    command="drive.upload_file",
    service="drive",
    operation="upload_file",
    file_path="/local/file.pdf",
    folder_id="root",  # or specific folder
    name="custom_name.pdf",  # optional
)
print(f"Uploaded to: {file_info['webViewLink']}")
```

### Create Folder

```python
folder = await integration.execute(
    command="drive.create_folder",
    service="drive",
    operation="create_folder",
    name="New Project",
    parent_id="root",
)
print(f"Created folder: {folder['fileId']}")
```

### Share File

```python
result = await integration.execute(
    command="drive.share_file",
    service="drive",
    operation="share_file",
    file_id="file_id",
    email="user@example.com",
    role="reader",  # "reader", "commenter", or "writer"
)
```

## Error Handling

```python
from thomas.integrations.google_workspace import GoogleWorkspaceIntegration
from thomas.integrations.google_workspace.gmail import GmailError
from thomas.integrations.google_workspace.auth import TokenExpiredError

try:
    result = await integration.execute(
        service="gmail",
        operation="send_message",
        to="user@example.com",
        subject="Test",
        body="Test message",
    )
except TokenExpiredError:
    # Token automatically refreshed, operation should retry
    pass
except GmailError as e:
    print(f"Gmail error: {e}")
except Exception as e:
    print(f"Integration error: {e}")
```

## Secrets Manager Integration

Store tokens securely in Thomas's secrets system:

```python
integration = GoogleWorkspaceIntegration(
    client_id="...",
    client_secret="...",
    redirect_uri="...",
    secrets_manager=thomas_config.secrets,  # Thomas secrets manager
    secrets_key="google_workspace_tokens",
)

await integration.connect()  # Loads stored tokens if available
# ... use integration ...
await integration.disconnect()  # Saves tokens
```

## Rate Limiting

Google APIs have rate limits:
- Gmail: 250 requests/second per user
- Calendar: 1,000,000 requests/day
- Drive: 1,000 requests/second

The integration includes automatic token refresh but does not implement backoff
for rate limits. Implement your own backoff strategy:

```python
import asyncio

async def call_with_backoff(coro, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await coro
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"Rate limited, waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise
```

## Architecture

- **auth.py**: OAuth2 flow, token management, and PKCE support
- **gmail.py**: Gmail API v1 operations (list, read, send, labels)
- **calendar.py**: Google Calendar API v3 (events, availability)
- **drive.py**: Google Drive API v3 (files, folders, sharing)
- **integration.py**: Main integration orchestrator with high-level execute() method

All modules use `aiohttp` for async HTTP requests and return normalized, structured responses.
