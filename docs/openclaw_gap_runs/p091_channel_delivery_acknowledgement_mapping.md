# P091 - Channel delivery acknowledgement mapping

## What this adds

Thomas now exposes a deterministic mapping describing **what a successful message post returns per channel** (the "delivery acknowledgement handle") and, where supported, how Thomas can apply a visual "delivered" marker (typically via reactions).

This is designed for automation and CLI parity workflows that need to know, for each channel:

* the provider-native identifier field(s) returned on a successful send (e.g., `message_id` or `ts`)
* the expected primitive type (`int` vs `string`)
* whether a delivery marker reaction is supported and what value format to use

## Behavior

* Builds a mapping from either:
  * an explicit channel list (CLI: `--channel` repeated), or
  * the configured channel set in a JSON config (`channels` object)

* Outputs:
  * `ok: true` responses with a stable `schema_version` and `mapping` object
  * `ok: false` responses with deterministic error codes:
    * `CONFIG_NOT_FOUND`
    * `CONFIG_INVALID`
    * `INVALID_INPUT`

## CLI

The channels operation is registered with several aliases:

* `delivery-acknowledgement-mapping`
* `delivery-acknowledgment-mapping`
* `delivery-ack-mapping`
* `delivery-ack-map`

Example:

```bash
thomas channels delivery-ack-mapping --channel telegram --channel slack --json
```

Schema output for automation:

```bash
thomas channels delivery-ack-mapping --json-schema
```

## Notes

* Unknown channels discovered from config are included as `unknown` (unsupported) rather than hard-failing, to avoid breaking older configs.
* The mapping describes **identifiers and marker formats**, not cross-platform emoji translation.
