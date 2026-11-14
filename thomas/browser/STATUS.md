# Module: browser

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | integrated (CLI browser contract/adapter package) |
| Last assessed    | 2026-06-05                                                  |
| Assessed by      | claude-opus-4-8 (wiring truth-up)      |
| Used in prod     | yes — backs `thomas browser ...` (43 subcommands; 34 via pack_bridge) |
| Has real tests   | not assessed       |
| Blocking issues  | live-runtime adapter mismatch (browser-01); agent-registry gap (browser-02) |

## What This Is

The browser contract/adapter package that backs Thomas's CLI browser
subcommands. `thomas browser ...` has 43 subcommands: 34 registered
through the pack bridge and nine defined directly in the CLI.

**Stats:** 28 Python files, 14,275 lines total after generated workflow data removal.

## Honest Assessment

**Contains real algorithms and logic** with actual implementations, data
structures, and domain-specific logic. It IS wired — the CLI `thomas browser`
subcommands route into this package through the pack bridge. The remaining
gaps are integration-quality issues at the live-runtime boundary, not a
lack of wiring (see Known Gaps).

## Known Gaps

- Live-runtime adapter mismatch between the contract surface and the
  executing runtime (browser-01)
- Agent-registry gap: not exposed as agent-loop tools the same way other
  packs are (browser-02)
- Test coverage not assessed
