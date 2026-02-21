# P064 - Message poll vote and close

## Summary

Thomas supports a single **messages** operation that:

1. Casts a vote on a message poll.
2. Closes that poll immediately afterward.

The implementation is Thomas-native and backend-agnostic: it will work with any
messages backend that exposes poll vote/close APIs.

## CLI

Registered command (within the `messages` group):

```bash
thomas messages poll-vote-and-close --poll-id <id> --option <value>
```

Automation-friendly JSON mode:

```bash
thomas messages poll-vote-and-close --poll-id <id> --option <value> --json
```

### Success payload

```json
{
  "ok": true,
  "poll_id": "poll-123",
  "option": "A",
  "voted": true,
  "closed": true,
  "vote_receipt": {},
  "close_receipt": {}
}
```

### Failure payload

```json
{
  "ok": false,
  "error": {
    "code": "invalid_input | missing_config | missing_backend_capability | external_failure",
    "message": "…",
    "details": { "stage": "vote|close", "…": "…" }
  }
}
```

Notes:
- `external_failure` includes a `stage` indicating whether vote or close failed.
- If closing fails *after* a successful vote, the error `details` includes the
  `vote_receipt` to make the partial state visible to automation.

## Implementation

- Core logic: `thomas/messages/p064_message_poll_vote_and_close.py`
- CLI wrapper: `thomas/cli/commands/messages/p064_message_poll_vote_and_close.py`
- Tests: `tests/prompt_pack/test_p064_message_poll_vote_and_close.py`
