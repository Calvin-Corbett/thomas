# Marketplace visible eligibility

Status: active Thomas product standard, 2026-07-21.

## Why this exists

Marketplace is an operating app store, not a display of every row that happens to exist in a catalog. The main store must never imply that Thomas can install, open, or run a package when the product has no evidence for that claim.

## Main-store gate

A package is eligible for the visible **Verified Store** only when the live Marketplace response proves at least one of these facts:

1. Thomas reports the package as installed in the current runtime.
2. Thomas reports it as installable and the compatibility/backend action layer marks it eligible.
3. Thomas reports a download as available and provides a real download or release-manifest action URL.

The renderer applies this gate to runtime data; it does not maintain a second hand-authored allowlist. An entrypoint-looking string such as `hooks.py`, a catalog description, a publisher name, or a category is not operating evidence by itself.

## Potential quarantine

Rows that do not pass the gate appear only in the **Potential** view. Potential is intentionally labeled as local review/catalog evidence, exposes no fabricated install action, and is not promoted in the Verified Store. Its list is derived at runtime and is not copied into a committed replacement catalog.

Potential does not mean rejected or unsafe. It means Thomas has not yet proven an installed runtime or a trusted install/download path. Promotion requires adding the real package evidence through the existing Marketplace backend and rerunning the audit.

## Current audit

The 2026-07-21 local audit evaluated every one of the 481 rows returned by `/api/marketplace/sync?limit=600`:

- 0 installed
- 0 backend-installable
- 0 trusted download actions
- 0 verified-store eligible
- 481 Potential

The per-entry evidence report is retained as local verification output outside the repository so Potential inventory is not accidentally treated as shipped product data.

## Safety and lifecycle

- Existing install, update, enable, disable, uninstall, download, copy-ID, and import wiring remains authoritative.
- Marketplace never constructs an install action for Potential rows.
- Source packages and catalog rows are not destructively deleted until their reachability and provenance are understood.
- Re-audit after package installation, manifest/action-policy changes, Marketplace backend changes, or catalog sync changes.
- UI Edit Mode identities use semantic package IDs and category keys; catalog order and DOM indexes are never persisted as layout identity.
