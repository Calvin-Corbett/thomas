# Slack Integration for Thomas

Complete asynchronous Slack workspace integration using the Slack Web API (v2).

## Features

- **OAuth2 Authentication**: Full Slack OAuth v2 flow with token management
- **Async/Await**: Built for Thomas's async event loop using `aiohttp`
- **Message Operations**: Send, update, delete, search, and react to messages
- **Block Kit Support**: Rich message formatting with interactive blocks
- **Error Handling**: Specific exception types for different error scenarios
- **Rate Limiting**: Automatic retry-after header parsing

## Architecture

### Core Modules

- **`integration.py`** (372 lines): Main `SlackIntegration` class with OAuth2 and connection management
- **`messaging.py`** (433 lines): Message operations via `SlackMessaging`

### Exception Types

```python
SlackAPIError              # Base exception
├── SlackAuthError         # Authentication/permission errors
├── SlackRateLimitError    # Rate limit exceeded
└── SlackConnectionError   # Network/connection errors
```

## Installation

Requires: `aiohttp`

```bash
pip install aiohttp
```

## Usage

### Basic Setup

```python
from thomas.integrations.slack import SlackIntegration
from thomas.integrations.slack.messaging import SlackMessaging

# Create integration
slack = SlackIntegration(
    client_id="xoxb-your-client-id",
    client_secret="your-client-secret",
    scopes=[
        "channels:read",
        "channels:history",
        "chat:write",
        "users:read",
        "files:read",
        "reactions:read",
    ]
)

# Connect
await slack.connect()

# Verify connection
is_healthy = await slack.health_check()
```

### OAuth2 Flow

```python
# Generate authorization URL
oauth_url = slack.get_oauth_url(
    redirect_uri="https://yourapp.com/slack/callback"
)

# After user authorizes, exchange code for tokens
token = await slack.handle_oauth_callback(
    code="xoxb-oauth-code",
    redirect_uri="https://yourapp.com/slack/callback"
)

# Save token to Thomas secrets for later use
# token.to_dict() -> stored in secrets
# Later: slack.set_token(SlackToken.from_dict(stored_data))
```

### Message Operations

```python
messaging = SlackMessaging(slack)

# Send simple message
response = await messaging.send_message(
    channel="C123456",
    text="Hello, Slack!"
)
print(response["ts"])  # Message timestamp

# Send with Block Kit
blocks = [
    messaging.create_text_block("*Bold text* here"),
    messaging.create_divider_block(),
    messaging.create_image_block(
        image_url="https://example.com/image.png",
        alt_text="An image",
    ),
    messaging.create_actions_block([
        messaging.create_button_block(
            text="Click me",
            action_id="button_click",
            value="clicked",
            style="primary",
        )
    ]),
]

await messaging.send_message(
    channel="C123456",
    blocks=blocks,
)

# Update message
await messaging.update_message(
    channel="C123456",
    ts="1234567890.123456",
    text="Updated message",
)

# Delete message
await messaging.delete_message(
    channel="C123456",
    ts="1234567890.123456",
)

# Reply to thread
await messaging.reply_to_thread(
    channel="C123456",
    thread_ts="1234567890.123456",
    text="Thread reply",
)

# Add reaction
await messaging.add_reaction(
    channel="C123456",
    ts="1234567890.123456",
    emoji="thumbsup",
)

# Search messages
results = await messaging.search_messages(
    query="keyword",
    sort="timestamp",
    count=20,
)
```

## Scopes

Default scopes:
- `channels:read` - Read channel list and details
- `channels:history` - Read message history
- `chat:write` - Post messages
- `users:read` - Read user list and profiles
- `files:read` - Read and download files
- `reactions:read` - Read message reactions

Additional available scopes:
- `files:write` - Upload files
- `reactions:write` - Add/remove reactions
- `users:read.email` - Read user email addresses
- `chat:write.public` - Post to any public channel
- `chat:write.customize` - Post as different user

## Token Management

### Storing Tokens

```python
# Get token as dict for storage
token_data = slack_token.to_dict()

# Store in Thomas secrets
secrets_manager.store('slack_token', token_data)
```

### Loading Tokens

```python
# Retrieve from Thomas secrets
token_data = secrets_manager.get('slack_token')

# Restore token
from thomas.integrations.slack.integration import SlackToken
token = SlackToken.from_dict(token_data)

slack.set_token(token)
```

## Error Handling

```python
from thomas.integrations.slack.integration import (
    SlackAPIError,
    SlackAuthError,
    SlackRateLimitError,
    SlackConnectionError,
)

try:
    result = await messaging.send_message("C123", "Hello")
except SlackRateLimitError as e:
    # Wait and retry
    wait_seconds = int(e.retry_after)
    await asyncio.sleep(wait_seconds)
except SlackAuthError as e:
    # Re-authenticate or refresh token
    print(f"Auth error: {e}")
except SlackConnectionError as e:
    # Network error, retry
    print(f"Connection error: {e}")
except SlackAPIError as e:
    # Other API error
    print(f"API error: {e}")
```

## Rate Limiting

The integration automatically detects rate limits via the `Retry-After` header:

```python
try:
    await slack.execute("POST", "chat.postMessage", data=...)
except SlackRateLimitError as e:
    # Error message includes recommended retry time
    print(str(e))  # "... retry after 5s"
```

## Best Practices

1. **Token Lifecycle**: Cache tokens in secrets, refresh when needed
2. **Error Retry**: Implement exponential backoff for rate limit errors
3. **Connection Pooling**: Reuse SlackIntegration instance across requests
4. **Async Context**: Always await all async operations
5. **Channel Names vs IDs**: Slack accepts both, IDs are more reliable
6. **Message Timestamps**: Use for thread replies and message updates

## Testing

```python
# Mock or stub the SlackIntegration for testing
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_send_message():
    slack = SlackIntegration("client_id", "secret")
    slack._session = MagicMock()
    slack._session.post = AsyncMock(return_value=...)

    # Test your code
```

## Limitations

- Direct message channels require the app to be invited first
- Some operations require specific workspace permissions
- File downloads are limited by Slack's rate limits and token permissions
- User email lookup requires `users:read.email` scope

## References

- [Slack Web API](https://api.slack.com/)
- [Slack OAuth 2.0](https://api.slack.com/authentication/oauth-v2)
- [Block Kit](https://api.slack.com/block-kit)
- [API Method Reference](https://api.slack.com/methods)
