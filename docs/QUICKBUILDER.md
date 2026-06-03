# QuickBuilder mode

QuickBuilder is a **human-activated build-fast mode**. It relaxes the
*workflow / coordination / location* gates (the "am I in the right worktree",
"did I claim this path", "is the tree dirty" gates) and removes the breakglass
**cooldown and per-agent 24h quota**, so you can iterate quickly from an isolated
worktree without fighting bookkeeping gates or rate-limits.

It does **not** relax any code-engineering or security gate. Tests, ruff,
`enforcement-integrity` (anti-tamper), the **secret-scan** (publish preflight),
`exception-handler`, `type-safety`, `circular-imports`, `monolith`,
`changelog`, `protected-files`, and `protected-deletions` all still run.
Editing a protected file still requires a Windows-Hello breakglass tap —
QuickBuilder only removes the *cooldown and daily quota* between taps, not the
human approval.

## Activate / deactivate

```bash
python scripts/quickbuilder_toggle.py on      # activate (Windows Hello prompt)
python scripts/quickbuilder_toggle.py status  # check
python scripts/quickbuilder_toggle.py off     # deactivate
```

Activation requires a Windows credential prompt, so a headless agent cannot
self-activate. The flag (`runtime/.quickbuilder_mode`) is HMAC-signed with a
per-install key (`runtime/.quickbuilder_key`, freshly minted on each activation);
the validator rejects any forged or unsigned flag. Both files are gitignored.

There is no auto-expiry timer — QuickBuilder stays on until you run `off`.
`status` and every suppressed gate print a clear `QuickBuilder mode` line so the
state is never silent.

## What it suppresses (and what it never will)

Suppressible (workflow / coordination / location), in
`scripts/forge/gates/_quickbuilder_guard.py::SUPPRESSIBLE_HOOKS`:

- `thomas-worktree-branch-guard`, `thomas-worktree-rules-gate`
- `thomas-workboard-claims-gate`, `thomas-workboard-agent-claim-gate`,
  `thomas-workboard-changed-files-gate`, `thomas-workboard-task-problems-gate`
- `thomas-plan-structure-gate`, `thomas-merge-readiness`

**Never suppressible** (any hook not in that allowlist — fail-safe):
the secret-scan, `enforcement-integrity`, `protected-files`/`protected-deletions`,
`exception-handler`, `type-safety`, `circular-imports`, `monolith`, `changelog`,
`repo-identity`, all tests/ruff, and the **workboard inbox gates** (inbound agent
coordination must always surface, so a fast solo build can't bulldoze another
agent's blocker message).

The guard module and the toggle are both in the integrity-protected manifest, so
an agent cannot widen the suppressible set or forge an activation without a
visible, signed change.

## Multi-agent caution

QuickBuilder relaxes the claim/worktree gates that prevent agents from stepping
on each other. Use it for **solo** intensive builds. The inbox gates stay on, so
you'll still see coordination messages, but don't run QuickBuilder while another
agent is actively editing shared paths.
