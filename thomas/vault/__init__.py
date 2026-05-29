"""Praxis.Vault -- runtime safety substrate (Tier 6 scaffold).

Target home for the safety/policy/breakglass machinery currently scattered
across `thomas/agent/guarded_tools.py`, `thomas/marketplace/policy/`,
`scripts/breakglass_auth.py`, `scripts/runtime_protection_toggle.py`, and
the protected-files / enforcement-scripts lists in `agent_safety.toml`.

Planned subsystems (per goal text "thomas/vault/ (Policy/ToolRunner/Breakglass)"):

- `thomas.vault.policy` — origin: `thomas/marketplace/policy/`. Policy
  evaluation, redaction rules, run-id tracking, agent-action allowlists.
  Multi-file package; ~6 modules.
- `thomas.vault.tool_runner` — origin: `thomas/agent/guarded_tools.py`.
  Wrapper that runs agent-callable tools under policy enforcement. Single
  file ~1200 lines.
- `thomas.vault.breakglass` — origin: `scripts/breakglass_auth.py` +
  `scripts/runtime_protection_toggle.py`. Human-authentication
  side-channel for protected-file edits and runtime-protection toggle.

Migration is NOT YET PERFORMED. This package is a scaffold that establishes
the target shape; the actual move (with cascading import updates across
the codebase and atomic `agent_safety.toml` updates via breakglass) is
deferred to a dedicated session because the product owner's goal estimated 5-8h
for the work and the import cascade is the largest in the rename arc to
date.

See `CHANGELOG.md` Tier 6 entry and
`memory/thomas_security_incident_2026-05-19.md` Tier 6 disposition for
the planned migration steps.
"""

from __future__ import annotations

__all__: list[str] = []
