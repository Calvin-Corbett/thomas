# Release Contracts

Thomas uses a versioned contract registry to enforce deprecation and migration discipline.

## Registry file

- `docs/release/contract_registry.json`

## Validate contract discipline

- CLI: `thomas release-contracts check --json`
- Script: `python scripts/release_contract_check.py --json --strict`

## Policy rules enforced

1. Every contract has `id`, `surface`, `version`, and `status`.
2. Version must be semantic (`X.Y.Z`).
3. `deprecated` contracts must include both `deprecated_on` and `sunset_on`.
4. Deprecation notice window must be at least `policy.min_deprecation_notice_days`.
5. Migration guarantees must be declared and linked to verification hooks.
