### Fixed

- **Registering an agent session binds its identity again.** The session layer moved
  to `thomas/core/agent_presence_sessions.py` but nothing was removed from
  `thomas/core/agent_presence.py`, so both carried the same six functions and drifted.
  The copies left behind predate `handoff_secret` and every session-identity check, so
  a caller reaching them skipped the binding that ties a session to one agent and one
  process. `agent_presence` now re-exports the session layer instead of duplicating it.
  (`thomas/core/agent_presence.py`)
- **The circular-import gate reads imports rather than mentions.** A regex over raw
  source treated any quoted string beginning `thomas.` as an import, so a substring
  test against a process command line was reported as a forbidden dependency and the
  file holding it could not be changed at all. Real imports, including
  `import_module()`, are still caught by AST. (`scripts/forge/gates/circular_imports_gate.py`)
