# thomas/forge/anvil

**Self-modification machinery — Doppelganger Protocol blue/green sandboxing,
Evolve charter-bounded self-improvement, refactor pass.** | tier: infra | health: green
Allowed imports: core, tools

Forge.Anvil is one of four Forge sub-pieces (Anvil, Gates, Intake, Publish).
This module was renamed from `thomas/upgrade/` to fit the locked Praxis
architecture vocabulary. Function rename: `register_upgrade_tools` →
`register_anvil_tools`. Tool category strings still emit `"upgrade"` — that
label is user-facing and may be revisited in a separate cosmetic pass.
