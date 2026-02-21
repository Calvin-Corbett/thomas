# P096 - Channel integration into existing channels module

This gap run adds a Thomas-native library + CLI path to **validate** and **enable**
messaging channels (initially: **Telegram**) using an existing Thomas JSON config.

## Library entrypoint

- `thomas.channels.p096_channel_integration_into_existing_channels_module.integrate_channel`

### Input contract

`ChannelIntegrationRequest` (dataclass):

- `provider`: channel provider name (`telegram`)
- `config_path`: optional JSON config path (required for persistence)
- `config`: optional in-memory config mapping
- `persist_enablement`: update `channels_enabled` in the config file
- `dry_run`: validate/compute without writing changes
- `test_message`: optional external validation step (send message)
- `validate_external`: optional lightweight validation step (may call integration)

### Output contract

`ChannelIntegrationResult` (dataclass):

- `provider`, `integrated`, `validated`
- `wrote_config`, `config_path`
- `enabled_channels`: post-integration enabled list (when persisted)
- `details`: structured details (safe for `--json`)
- `warnings`: non-fatal notes

## CLI

The feature is wired into the existing `channels` command group through a
`channel_ops` registration hook:

- `thomas/cli/commands/channel_ops/p096_channel_integration_into_existing_channels_module.py`

### List providers

```bash
thomas channels providers
thomas channels providers --json
```

### Integrate provider

```bash
thomas channels integrate telegram --config ./thomas.json --persist
thomas channels integrate telegram --config ./thomas.json --dry-run --json
```

Telegram config can come from the config file and/or environment variables:

- `THOMAS_TELEGRAM_BOT_TOKEN`
- `THOMAS_TELEGRAM_CHAT_ID`

## Errors

All failures raise `ChannelIntegrationError` (or subclasses) with:

- `code`: stable machine-readable error code
- `message`: human-readable summary
- `details`: structured context for automation
