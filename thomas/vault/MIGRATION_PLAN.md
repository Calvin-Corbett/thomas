# Vault migration plan (Tier 6)

Status: **SCAFFOLD ONLY** — `thomas/vault/` directory exists, content
migration deferred to a dedicated session.

## Target shape (per goal text)

```
thomas/vault/
├── __init__.py
├── MIGRATION_PLAN.md            # this file
├── policy/                      # was: thomas/marketplace/policy/
│   ├── __init__.py
│   ├── config.py
│   ├── policy.py
│   ├── redact.py
│   ├── rules.py
│   ├── run_id.py
│   └── tools.py
├── tool_runner.py               # was: thomas/agent/guarded_tools.py
└── breakglass/
    ├── __init__.py
    ├── auth.py                  # was: scripts/breakglass_auth.py
    └── runtime_toggle.py        # was: scripts/runtime_protection_toggle.py
```

## Migration steps

Each step needs its own commit so the cascade is recoverable.

### Step 1 — policy package (smallest cascade, highest test coverage)

1. `Move-Item thomas/marketplace/policy/ thomas/vault/policy/`
2. Grep `from thomas.marketplace.policy` and `import thomas.marketplace.policy`
   across `thomas/`, `tests/`, `scripts/`. Replace with `thomas.vault.policy`.
3. Estimated ~10-20 importing files.
4. Run `python -m pytest tests/test_policy*` to verify.
5. Commit.

### Step 2 — tool_runner (medium cascade)

1. `Move-Item thomas/agent/guarded_tools.py thomas/vault/tool_runner.py`
2. Grep `from thomas.agent import guarded_tools`, `from thomas.agent.guarded_tools`,
   `import thomas.agent.guarded_tools`. Replace with `thomas.vault.tool_runner`
   (preserving any alias used at call sites).
3. Estimated ~30-50 importing files; this file is widely used.
4. Test: run a chat-loop smoke + tool-execution test.
5. Commit.

### Step 3 — breakglass package (smallest)

1. `mkdir thomas/vault/breakglass/`
2. `Move-Item scripts/breakglass_auth.py thomas/vault/breakglass/auth.py`
3. `Move-Item scripts/runtime_protection_toggle.py thomas/vault/breakglass/runtime_toggle.py`
4. Update `from scripts.breakglass_auth` and `from scripts import breakglass_auth`
   references. Update `scripts/runtime_protection_toggle.py` references (mostly
   docs + AGENTS.md).
5. **Critical:** the runtime_toggle command published in AGENTS.md and elsewhere
   changes from `python scripts/runtime_protection_toggle.py off` to
   `python -m thomas.vault.breakglass.runtime_toggle off`. Update every
   doc occurrence.
6. Verify the `runtime/.runtime_protection_disabled` flag location is
   still resolved correctly by the new module path.
7. Commit.

### Step 4 — agent_safety.toml update

1. Update protected_files + enforcement_scripts references for all moved files.
2. Update any references to `thomas.marketplace.policy` in policy-related
   config sections.
3. Commit (breakglass required).

## Risk notes

- `guarded_tools.py` is the largest-cascade rename in the entire arc.
  Every chat-loop, tool registry, and policy-enforcement code path
  touches it. Test coverage is critical here.
- Breakglass scripts MUST keep working through the migration — if you
  break `runtime_protection_toggle.py` you also break the ability to
  do protected-file edits to roll back. Stage carefully.
- `agent_safety.toml` references should be the LAST thing to update,
  not the first — the protected-files gate reads it at commit time.
