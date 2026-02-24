# Extension Certification

Thomas certifies extension packs using catalog validity, capability requirements, and pass-rate thresholds.

## Commands

- CLI certify: `thomas plugins certify --json`
- CLI update plan: `thomas plugins update --json`
- Script certify: `python scripts/extension_certify.py --json --strict`

## Certification checks

1. Every pack in `extensions/catalog.json` resolves to a valid manifest + hooks + README.
2. Required capabilities are present (default includes `healthcheck`).
3. Certification pass rate meets `--min-pass-rate` (default `0.95`).

## Update planning

`plugins update` compares local plugin state (`.thomas/cli/plugins.json`) against the extension catalog and emits:

1. `update` candidates.
2. `up_to_date` entries.
3. `unknown` entries when version metadata is missing.
