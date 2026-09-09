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

## Channel Examples

### Monitor and Archive Inactive Channels

```python
from thomas.integrations.slack.channels import SlackChannels
from datetime import datetime, timedelta

channels_ops = SlackChannels(slack)

# Get all public channels
all_channels = await channels_ops.list_all_channels(
    types="public_channel",
)

# Check for inactive channels (no messages in 30 days)
thirty_days_ago = datetime.now().timestamp() - (30 * 24 * 3600)

for channel in all_channels:
    if channel.get("is_archived"):
        continue

    channel_id = channel["id"]

    # Get recent history
    history = await channels_ops.get_channel_history(
        channel_id=channel_id,
        limit=1,
        oldest=str(int(thirty_days_ago)),
    )

    messages = history.get("messages", [])

    # If no messages in 30 days, archive
    if not messages:
        info = await channels_ops.get_channel_info(channel_id)
        channel_name = info["channel"]["name"]

        await channels_ops.archive_channel(channel_id)
        print(f"Archived inactive channel: #{channel_name}")
```

### Create Project Channel and Populate

```python
channels_ops = SlackChannels(slack)
users_ops = SlackUsers(slack)

# Create channel
project = await channels_ops.create_channel(
    name="project-acme",
    is_private=True,
    description="ACME Project coordination",
)

channel_id = project["channel"]["id"]

# Set topic
await channels_ops.set_topic(
    channel_id=channel_id,
    topic="ACME Project - Q1 Roadmap",
)

# Find team members
team_members = await users_ops.search_users("acme-team")
member_ids = [u["id"] for u in team_members]

# Invite to channel
if member_ids:
    await channels_ops.invite_users(channel_id, member_ids)
    print(f"Invited {len(member_ids)} users to #project-acme")
```

### Backup Channel Messages

```python
import json
from pathlib import Path

channels_ops = SlackChannels(slack)

async def backup_channel(channel_id, output_file):
    """Backup all messages from a channel."""

    messages = []
    cursor = None

    while True:
        result = await channels_ops.get_channel_history(
            channel_id=channel_id,
            limit=100,
            cursor=cursor,
        )

        messages.extend(result.get("messages", []))

        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(messages, f, indent=2)

    print(f"Backed up {len(messages)} messages to {output_file}")

# Backup a channel
await backup_channel("C123456", "/backups/channel_export.json")
```

## User Examples

### Sync User Directory

```python
from thomas.integrations.slack.users import SlackUsers
from datetime import datetime

users_ops = SlackUsers(slack)

# Get all active users
active_users = await users_ops.get_users_in_team()

user_directory = []

for user in active_users:
    user_data = {
        "id": user["id"],
        "name": users_ops.get_display_name(user),
        "email": users_ops.get_user_email(user),
        "avatar": users_ops.get_user_avatar(user),
        "title": users_ops.get_user_title(user),
        "department": users_ops.get_user_department(user),
        "active": users_ops.is_user_active(user),
        "synced_at": datetime.now().isoformat(),
    }
    user_directory.append(user_data)

# Store in database or cache
await db.store_slack_users(user_directory)
print(f"Synced {len(user_directory)} users")
```

### Monitor User Presence

```python
users_ops = SlackUsers(slack)

# Get all active users
all_users = await users_ops.list_all_users()

presence_report = {}

for user in all_users:
    if user.get("deleted") or user.get("is_bot"):
        continue

    user_id = user["id"]
    presence = await users_ops.get_presence(user_id)

    presence_report[user["name"]] = {
        "status": presence["presence"],
        "online": presence["presence"] == "active",
    }

# Generate report
active_count = sum(1 for u in presence_report.values() if u["online"])
total_count = len(presence_report)

print(f"Presence: {active_count}/{total_count} users online")
```

### Set Status for All Team Members

```python
users_ops = SlackUsers(slack)
import asyncio

# Get current authenticated user
auth_result = await slack.execute("GET", "auth.test")
current_user = auth_result["user_id"]

# Set status for current user
await users_ops.set_status(
    status_text="In standup",
    status_emoji="calendar",
    expiration_s=900,  # 15 minutes
)

print("Status updated")
```

## File Examples

### Upload Build Artifacts

```python
from thomas.integrations.slack.files import SlackFiles
from pathlib import Path

files_ops = SlackFiles(slack)

# Upload build artifact
artifact_path = "/builds/app-v1.0.tar.gz"

result = await files_ops.upload_file(
    channels=["C_BUILDS_CHANNEL"],
    file_path=artifact_path,
    title="App Build v1.0",
    initial_comment="Latest production build",
)

print(f"Uploaded: {result['file']['name']}")
```

### Archive Channel Files

```python
files_ops = SlackFiles(slack)
from datetime import datetime, timedelta

# Get files from last 30 days
thirty_days_ago = int((datetime.now() - timedelta(days=30)).timestamp())

file_list = await files_ops.list_files(
    channel="C123456",
    count=100,
)

# Download and archive
archive_dir = Path("/archive/slack_files")
archive_dir.mkdir(parents=True, exist_ok=True)

for file_obj in file_list["files"]:
    file_id = file_obj["id"]
    file_info = await files_ops.get_file_info(file_id)

    download_url = file_info["file"]["url_private"]
    filename = files_ops.get_file_name(file_obj)

    output_path = archive_dir / filename

    await files_ops.download_file(download_url, str(output_path))
    print(f"Archived: {filename}")
```

### Generate File Report

```python
files_ops = SlackFiles(slack)

file_list = await files_ops.list_files(count=1000)

report = {
    "total_files": len(file_list["files"]),
    "by_type": {},
    "by_size": {"small": 0, "medium": 0, "large": 0},
}

for file_obj in file_list["files"]:
    # Count by MIME type
    mimetype = files_ops.get_file_type(file_obj)
    category = mimetype.split("/")[0]
    report["by_type"][category] = report["by_type"].get(category, 0) + 1

    # Count by size
    size = files_ops.get_file_size(file_obj)
    if size < 1_000_000:
        report["by_size"]["small"] += 1
    elif size < 100_000_000:
        report["by_size"]["medium"] += 1
    else:
        report["by_size"]["large"] += 1

print("File Report:")
print(f"Total: {report['total_files']} files")
print(f"By type: {report['by_type']}")
print(f"By size: {report['by_size']}")
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

### Scheduled Channel Summary

```python
import asyncio
from datetime import datetime, timedelta

async def post_channel_summary():
    """Post daily summary of channel activity."""

    channels_ops = SlackChannels(slack)
    messaging = SlackMessaging(slack)

    # Get channels
    channels_result = await channels_ops.list_channels(limit=50)

    summary = []

    for channel in channels_result["channels"]:
        if channel.get("is_archived"):
            continue

        # Get history from last 24 hours
        yesterday = int((datetime.now() - timedelta(days=1)).timestamp())

        history = await channels_ops.get_channel_history(
            channel_id=channel["id"],
            limit=100,
            oldest=str(yesterday),
        )

        msg_count = len(history.get("messages", []))

        if msg_count > 0:
            summary.append(f"• #{channel['name']}: {msg_count} messages")

    # Post summary
    if summary:
        await messaging.send_message(
            channel="C_SUMMARY_CHANNEL",
            text="24-Hour Channel Activity Summary",
            blocks=[
                messaging.create_text_block(
                    "*Channel Activity (Last 24h)*\n" + "\n".join(summary)
                ),
            ],
        )
```

These examples demonstrate real-world usage patterns for the Slack integration with Thomas.
