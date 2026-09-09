# Changelog

User-facing changes are recorded here. Development conversations and raw test reports are not release notes.

## [Unreleased]

### Fixed

- **Registering an agent session binds its identity again.** The session layer moved to
  `thomas/core/agent_presence_sessions.py` but nothing was removed from
  `thomas/core/agent_presence.py`, so both carried the same six functions and drifted. The
  copies left behind predate the session-identity checks, so a caller reaching them skipped
  the binding that ties a session to one agent and one process.
  (`thomas/core/agent_presence.py`)
- **The circular-import gate reads imports rather than mentions.** A regex over raw source
  treated any quoted string beginning `thomas.` as an import, so a substring test against a
  process command line was reported as a forbidden dependency and the file holding it could
  not be changed at all. Real imports, including `import_module()`, are still caught by AST.
  (`scripts/forge/gates/circular_imports_gate.py`)

## [0.19.37] - 2026-09-08

### Changed

- Refreshed installation, architecture, and contributor documentation.
- Removed internal development records and historical QA artifacts from the public distribution.
- Replaced personal examples with fictional test data.
- Strengthened release-content validation and snapshot filtering.

## [0.19.36] - 2026-09-07

### Added

- Updated Chat, Build, and Work workflows and the browser workspace.
- Expanded file handling and model integration support.

### Fixed

- Improved task state reporting, workspace navigation, and delivery handling.

Thomas remains beta software. See the README for prerequisites and limitations.
