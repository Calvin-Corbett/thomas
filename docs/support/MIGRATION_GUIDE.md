# Migration Guide

Use this guide for safe upgrades and rollback planning.

## Pre-upgrade checklist

1. Read changelog entries since current version.
2. Run `python scripts/config_validator.py --json`.
3. Snapshot critical state (`thomas_state.json`, workspace store, DB files).
4. Verify required CI checks are green on target build.
5. Confirm deprecation notes for removed/renamed surfaces.

## Upgrade checklist

1. Deploy binaries/package for target version.
2. Apply config changes from release notes.
3. Start service and verify `/api/version` and `/api/setup/bootstrap`.
4. Run smoke path:
- new session create
- chat send
- settings save
- setup repair dry run
5. Confirm telemetry and security headers are healthy.

## Rollback checklist

1. Stop service.
2. Restore last-good binaries and config.
3. Restore state backup if schema migration failed.
4. Restart and rerun smoke path.
5. Log RCA with exact failed migration step and remediation.

## Compatibility policy

1. Contract-breaking API changes require a versioned path or compatibility shim.
2. Deprecations require one release cycle of warnings before removal.
3. Migration notes must include forward and rollback commands.
