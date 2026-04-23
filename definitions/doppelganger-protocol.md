# Doppelganger Protocol (Blue/Green)

Thomas uses the **Doppelganger Protocol** for changes that can break the system.

Terminology:
- **Blue**: the real running Thomas (your primary instance).
- **Green**: an isolated upgrade sandbox used to build, validate, and stage changes.

## Core Rule

For breaking/risky changes: **do not edit the running Blue code in-place.**

Instead:
1. Copy Blue into Green.
2. Apply changes in Green.
3. Validate in Green (tests + smoke).
4. Promote Green into Blue (with backup and rollback).

## Green Environment Rules

- Green uses a **separate runtime/memory root** (no real chat history, no real indices).
- Green uses a **separate secrets store** (no production API keys).
- Green can start a server on a non-default port for smoke testing.

## Promotion Rules

Promotion from Green to Blue must:
- Create a backup snapshot first.
- Sync the code and allow deletions (to support code pruning), but never touch user runtime data.
- Optionally re-install dependencies in Blue if needed.

## Rollback Rules

Rollback must be fast:
- Restore from the last backup snapshot.
- Restart Blue.

## Implementation (This Repo)

Default locations:
- Green working copy: `runtime/doppelganger/green/`
- Green runtime root: `runtime/doppelganger/green-runtime/`
- Backups: `runtime/doppelganger/backups/`

CLI helpers:

```bash
thomas doppelganger status
thomas doppelganger sync
thomas doppelganger test
thomas doppelganger serve-green --port 8902
thomas doppelganger promote
thomas doppelganger rollback
```
