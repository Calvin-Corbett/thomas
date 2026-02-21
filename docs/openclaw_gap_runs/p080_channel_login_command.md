# P080 - Channel login command

This adds a `channels login` operation that triggers a provider-specific authentication/linking flow.

## Thomas behavior

* The CLI subcommand is `thomas channels login --channel <name>`.
* The command supports a machine-readable output mode via `--json`.
* Login is integration-driven:
  * The command loads `thomas.integrations.<channel>`
  * Finds a login entrypoint (`login()`, `channel_login()`, or a class with `.login()`)
  * Calls it with supported request arguments
* Failures are mapped to stable error codes:
  * `invalid_input`
  * `unknown_channel`
  * `login_unavailable`
  * `missing_config`
  * `external_failure`

## Notes vs OpenClaw

OpenClaw documents interactive login primarily for WhatsApp. Thomas implements login as an integration capability:
channels that need interactive linking can expose a `login` entrypoint, and channels that do not can omit it.

python -m pytest -q tests/prompt_pack/test_p080_channel_login_command.py
python -m pytest -q tests/test_cli_parity_commands.py -k "channels"

- Integration login entrypoint discovery is heuristic (function/class naming); if an integration exposes login differently, the command may report `login_unavailable`/`missing_config`.
- CLI registration assumes an argparse-style subparser contract; if the registry expects a different hook, only the `COMMAND`/alias helpers may be detected.
- Import-time `ModuleNotFoundError` inside an integration could be surfaced as `external_failure` (by design) rather than `unknown_channel`.
