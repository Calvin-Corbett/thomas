# P072 - Message channel specific route resolver

## What this adds

Thomas can receive messages from multiple channels (Slack, Discord, Telegram, etc.).
Once you run more than one channel (or multiple accounts per channel), **routing**
needs to be deterministic:

- the model does not choose a channel
- the model does not choose an assistant/agent
- the host config (Thomas) does

This gap run implements a Thomas-native message route resolver that selects a
destination assistant based on channel-specific metadata.

## Core API

The routing logic lives in:

- `thomas/messages/p072_message_channel_specific_route_resolver.py`

Key entrypoint:

- `resolve_message_route(context, config) -> MessageRouteResolution`

### Context fields

`MessageRouteContext` supports:

- `channel` (required)
- `account_id` (optional)
- `peer` (optional): `{kind, id}`
- `parent_peer` (optional): `{kind, id}` (thread inheritance)
- `guild_id` + `roles` (optional): Discord routing
- `team_id` (optional): Slack routing

### Rule precedence

Rules are evaluated by **specificity tiers**, then by config order within each tier:

1. Peer match
2. Parent peer match
3. Guild + roles match
4. Guild match
5. Team match
6. Account match
7. Channel-only match (account wildcard)
8. Default assistant

## CLI

The CLI wrapper lives in:

- `thomas/cli/commands/messages/p072_message_channel_specific_route_resolver.py`

Example (human output):

```bash
python -m thomas.cli.commands.messages.p072_message_channel_specific_route_resolver \
  --config routing.json \
  --channel slack \
  --team-id T123
```

Machine-readable output:

```bash
python -m thomas.cli.commands.messages.p072_message_channel_specific_route_resolver \
  --config routing.json \
  --json \
  --channel discord \
  --guild-id G1 \
  --role R1 --role R2
```

Schema for automation:

```bash
python -m thomas.cli.commands.messages.p072_message_channel_specific_route_resolver --config routing.json --schema
```

## Failure modes

All errors are deterministic and machine-readable when `--json` is used.
Common error codes:

- `invalid_input`
- `invalid_config`
- `config_read_failed`
- `config_parse_failed`
