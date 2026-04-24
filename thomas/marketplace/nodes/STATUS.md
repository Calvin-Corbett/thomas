# Module: nodes

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | scaffolded infrastructure, not fully verified          |
| Last assessed    | 2026-04-24                                             |
| Used in prod     | imported, but not verified as functional end-to-end    |
| Has real tests   | partial                                                |
| Blocking issues  | end-to-end node lifecycle still needs verification     |

## What This Is

Headless node infrastructure for running Thomas workers on another machine that
connects back to a gateway. Numbered files cover node host config, state store,
lifecycle, CLI commands, registry, push payloads, approvals, pairing handshake,
and notifications.

The package has real code for config models, JSON Schema, CLI commands, and
state handling. The open question is whether the full remote-node lifecycle is
wired and usable from installation through pairing, work dispatch, approval,
and status reporting.

## Known Gaps

- End-to-end functionality needs a fresh verification pass.
- Public documentation should explain this as an advanced feature, not the
  default install path.
- No remote binding should happen by default for normal local installs.
