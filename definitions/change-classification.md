# Change Classification (Safe vs Breaking)

Thomas distinguishes between changes that are low-risk (safe) and changes that can break core behavior (breaking).

## Safe Changes

Safe changes are changes that:
- Do not affect boot/serve paths, routing, config parsing, tool execution, memory, or persistence.
- Are additive and isolated.
- Have a clear rollback and do not change data formats.

Examples:
- Adding a small UI affordance with no API changes.
- Adding model metadata in `models.json`.
- Copy tweaks, CSS-only changes.

## Breaking (Risky) Changes

Breaking changes are changes that can:
- Prevent the server/UI from booting.
- Change config formats, routing, tool execution, memory storage, or secrets.
- Change persistence formats or migrations.
- Touch authentication, network access, or sandbox boundaries.
- Introduce new dependencies or modify installation behavior.

Examples:
- Refactoring server startup, request routing, or streaming.
- Changing secret storage behavior.
- Adding new background jobs, indexers, or file watchers.
- Reworking tool sandbox logic.

## Rule Of Thumb

If you are not sure: treat it as **breaking** and use the Doppelganger Protocol.

