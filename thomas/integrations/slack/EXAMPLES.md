# Slack Integration Examples

Practical examples of using the Slack integration with Thomas.

## Setup and Authentication

### Initialize with Pre-existing Token

```python
from thomas.integrations.slack import SlackIntegration
from thomas.integrations.slack.integration import SlackToken

# Load token from secrets
slack_token_data = secrets_manager.get('slack_bot_token')
token = SlackToken.from_dict(slack_token_data)

# Create integration
slack = SlackIntegration(
    client_id="xoxb-...",
    client_secret="...",
)

# Set token (no OAuth needed)
slack.set_token(token)

# Connect
await slack.connect()

# Verify
is_ok = await slack.health_check()
print(f"Slack connected: {is_ok}")
```

### OAuth Flow in Web Handler

```python
from thomas.integrations.slack import SlackIntegration

slack = SlackIntegration(
    client_id="xoxb-...",
    client_secret="...",
)

# In your OAuth callback handler
@app.route('/slack/callback')
async def slack_callback(request):
    code = request.query.get('code')

    try:
        token = await slack.handle_oauth_callback(
            code=code,
            redirect_uri="https://myapp.com/slack/callback",
        )

        # Save token for later use
        secrets_manager.store('slack_bot_token', token.to_dict())

        return {"status": "ok", "team": token.team_name}
    except Exception as e:
        return {"error": str(e)}, 400
```

## Message Examples

### Send Rich Message with Buttons

```python
from thomas.integrations.slack.messaging import SlackMessaging

messaging = SlackMessaging(slack)

# Create interactive message
blocks = [
    messaging.create_text_block("*Task Assignment*\nPlease review and accept"),
    messaging.create_divider_block(),
    messaging.create_actions_block([
        messaging.create_button_block(
            text="Accept",
            action_id="task_accept",
            value="yes",
            style="primary",
        ),
        messaging.create_button_block(
            text="Decline",
            action_id="task_decline",
            value="no",
            style="danger",
        ),
    ]),
]

response = await messaging.send_message(
    channel="C123456",
    text="Task assignment notification",
    blocks=blocks,
)

print(f"Message sent: {response['ts']}")
```

### Search and React to Messages

```python
messaging = SlackMessaging(slack)

# Search for messages mentioning a keyword
results = await messaging.search_messages(
    query="bug report",
    sort="timestamp",
    count=10,
)

# React to matching messages
for match in results["messages"]["matches"]:
    message = match["text"]
    channel = match["channel"]["id"]
    ts = match["ts"]

    # Add bug emoji reaction
    await messaging.add_reaction(
        channel=channel,
        ts=ts,
        emoji="bug",
    )

    # Reply in thread
    await messaging.reply_to_thread(
        channel=channel,
        thread_ts=ts,
        text="Bug logged in tracker",
    )
```

### Update Message Status

```python
messaging = SlackMessaging(slack)

# Send initial status message
response = await messaging.send_message(
    channel="C123456",
    text="Processing...",
)

ts = response["ts"]

# Simulate work...
await asyncio.sleep(5)

# Update with completion
await messaging.update_message(
    channel="C123456",
    ts=ts,
    text="Processing complete!",
)
```

## Error Handling Examples

### Retry on Rate Limit

```python
import asyncio
from thomas.integrations.slack.integration import SlackRateLimitError

messaging = SlackMessaging(slack)

async def send_with_retry(channel, text, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await messaging.send_message(channel, text)
        except SlackRateLimitError as e:
            # Extract retry time from error message
            if attempt < max_retries - 1:
                error_str = str(e)
                # Parse "retry after Xs" from error
                import re
                match = re.search(r"(\d+)s", error_str)
                wait_time = int(match.group(1)) if match else (2 ** attempt)

                print(f"Rate limited, retrying after {wait_time}s")
                await asyncio.sleep(wait_time)
            else:
                raise

result = await send_with_retry("C123456", "Hello!")
```

### Handle Authentication Errors

```python
from thomas.integrations.slack.integration import SlackAuthError

try:
    result = await messaging.send_message("C123456", "Hello")
except SlackAuthError as e:
    # Token may have been revoked
    print(f"Auth error: {e}")

    # Clear token and require re-authentication
    secrets_manager.delete('slack_bot_token')

    # Notify user to re-authenticate
    # Trigger OAuth flow again
```

## Practical Integration Examples

### Slash Command Handler

```python
# Web framework (e.g., Quart)
@app.route('/slack/events', methods=['POST'])
async def slack_events():
    payload = await request.get_json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    if payload["type"] == "event_callback":
        event = payload["event"]

        if event.get("type") == "slash_commands":
            command = event["command"]

            if command == "/task":
                # Handle task command
                channel = event["channel_id"]
                text = event["text"]

                messaging = SlackMessaging(slack)
                await messaging.send_message(
                    channel,
                    f"Processing task: {text}",
                )

    return {"ok": True}
```

These examples demonstrate real-world usage patterns for the Slack integration with Thomas.
