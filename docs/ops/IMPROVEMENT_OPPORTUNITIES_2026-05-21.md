# Thomas — Easiest & Fastest Improvement Opportunities

**Generated:** 2026-05-21 (after 0.15.42 CI recovery sprint)
**For:** the product owner
**Effort budget per item:** 30 minutes to 4 hours

This list captures the cheapest, highest-leverage cleanups discovered while clearing CI debt across 0.15.0 → 0.15.42. Items are ordered by **payoff per minute of effort**. None require the product owner's approval; an agent can pick any item and ship it in one focused session.

---

## Tier 1: 30-minute fixes with broad payoff

### 1. Stop spurious "modified" reports on CRLF files (30 min)
**Problem:** Every Windows-side `git status` shows `thomas/server/routes/chat_aiohttp_streaming.py` modified even when the contents are identical — Git would convert LF→CRLF on next touch, so the status output stays noisy forever. The audit gate has to be re-run every time the file is "touched" for the same reason. This wasted ~5 commits of recovery work in 0.15.36–0.15.41.

**Fix:** Decide on a line-ending policy. Either:
- Add `* text=auto eol=lf` (or `* text=auto eol=crlf`) to `.gitattributes` and run `git add --renormalize .` once to fix every file.
- OR fix the audit script to hash with `text=False` / line-ending-normalized contents.

**Recommended:** `.gitattributes` with `eol=lf` for `.py`, `.json`, `.md`, `.yml`, `.toml`, and `.js`. Aligns with Linux CI environment, ends the CRLF/LF audit-hash divergence permanently.

**Files to touch:** `.gitattributes` (1 file).

---

### 2. Replace `contextlib.suppress(Exception)` around imports (45 min)
**Problem:** Found 3 separate cases in this session where a module-level `from X import Y` was wrapped in `contextlib.suppress` and the import silently failed for months — `maybe_auto_start_autopilot_from_chat`, `maybe_handle_discord_chat_command`, and the bridge run-store import. Each one disabled a feature without anyone noticing.

**Fix:** Replace `contextlib.suppress(Exception)` around imports with:
- An explicit `except (ImportError, ModuleNotFoundError):` (declares intent), AND
- A `log.warning("Module X unavailable: %s", e)` so the disablement shows up in logs, AND
- A startup-diagnostic counter (see `app_core.py:_diagnostics`) so the boot path reports which optional integrations are off.

**Files to touch:** Grep `contextlib.suppress(Exception)` near imports — likely 6–10 sites.

---

### 3. Add `_via_lookup` generalization to `scripts/lib/` (1 hour)
**Problem:** The `_via_claim` helper in `scripts/crew/workboard/claim.py` is duplicated in spirit in 6+ other places (the new `_build_memory` server-side, `_run_chat` CLI-side, several test-target propagation helpers). Each one reimplements the same `sys.modules.get(name)` → `getattr(module, sym, None)` → fallback pattern.

**Fix:** Extract a single helper:
```python
# scripts/lib/sys_modules_lookup.py
def via_module(module_name: str, attr: str, default):
    import sys
    mod = sys.modules.get(module_name)
    if mod is not None:
        return getattr(mod, attr, default)
    return default
```
Then call sites become one-liners. Closes Pattern 9 + Pattern 16 from the bible.

**Files to touch:** Create 1 new helper, refactor ~6 call sites.

---

### 4. Wire the orphaned chat-mode handlers properly (30 min)
**Problem:** This session found `maybe_handle_discord_chat_command` was orphaned (defined but not imported). The pattern: any function named `maybe_handle_*` or `maybe_execute_*` in `thomas/server/routes/` should be wired into the chat pipeline. Quick scan suggests there may be others.

**Fix:** Grep for `maybe_handle_*` / `maybe_execute_*` / `match_*_chat_command` across `thomas/server/routes/`. For each, verify it has at least one caller via `grep -rn 'function_name' thomas/`. Build a `CHAT_INTERCEPTORS` registry in `chat_aiohttp_streaming.py` so adding a new interceptor is a one-line append, not "find the right spot to call it".

**Files to touch:** `thomas/server/routes/chat_aiohttp_streaming.py` + audit the routes/ dir.

---

## Tier 2: 1–2 hour fixes that compound over time

### 5. Cache server-route registration error rate (1.5 hours)
**Problem:** `app_routes_init.py` has 15+ `_register_X_routes(app_ref)` wrappers, each wrapped in try/except. Three of these (goals, spend, companion) were silently disabled for months because they raised an exception on import and the try/except swallowed it. Hard to notice 404s in production because the routes "should exist".

**Fix:**
1. Add a startup-diagnostic counter for each route group: `_route_registration_status: dict[str, str]`.
2. Expose at `/api/health/route-registration` so missing groups show up in any healthcheck.
3. If `THOMAS_STRICT_ROUTES=1`, fail boot when any registration raises.
4. Add a test that asserts every `_register_X_routes` import succeeds.

**Files to touch:** `app_routes_init.py`, `health.py` route, new test.

---

### 6. Add architecture-debt counters to gate output (1 hour)
**Problem:** `_architecture.py` has annotated debt entries (e.g. `chat_aiohttp_streaming.py exceeds 810 lines`) but the gate just passes/fails. No trend over time. Cannot tell "is debt growing or shrinking?".

**Fix:** Have the architecture gate emit a `docs/ops/architecture_debt_trend.json` on every CI run with `{commit, debt_count, top_offenders}`. Render a sparkline in the README or in a Site Release Safety summary.

**Files to touch:** `scripts/forge/gates/architecture_gate.py`, JSON output schema.

---

### 7. Test fixture: build-bundle-on-demand helper (1 hour)
**Problem:** This session found `tests/test_server_marketplace_routes.py` reading hardcoded `bundle.zip` paths under `plugins_registry/plugins/<id>/` that don't exist (bundles generate at runtime). Added `_materialize_hosted_bundles` as a workaround. Same pattern likely needed by other tests.

**Fix:** Promote `_materialize_hosted_bundles` to `tests/marketplace_fixtures.py`. Add a `pytest` fixture for it: `@pytest.fixture def hosted_plugin_bundles(client)`. Tests that need bundle bytes get them for free.

**Files to touch:** New `tests/marketplace_fixtures.py`, refactor 2-3 tests to use the fixture.

---

### 8. Auto-record module audit on staged file change (1.5 hours)
**Problem:** The module audit gate is opaque: changes to `thomas/server/*` require running `scripts/record_module_audit.py` with the right `--module`, `--file ...` args. Easy to forget. This session burned 4 commits re-running this dance.

**Fix:** Add a pre-commit hook that runs `scripts/record_module_audit.py` automatically for any major-module file change in the staging set. The hook reads `agent_safety.toml` for the major-module list, infers `--module` from the file path, and re-records the audit with the right --file args.

**Files to touch:** `.pre-commit-config.yaml`, new hook script.

---

## Tier 3: 2–4 hour fixes that retire long-running debt

### 9. Retire 27-line `swarm_mode.py` Pattern 7 shim (2 hours)
**Problem:** `thomas/server/swarm_mode.py` is a 27-line compat shim that imports `SwarmOrchestrator` from `thomas.agent.swarm` with a try/except raising RuntimeError. Exists only so tests can monkeypatch this path. Right fix: patch the canonical path directly, delete the shim.

**Documented:** Already in bible Section "Planned features and open ideas" as a known item.

**Files to touch:** `thomas/server/swarm_mode.py` (delete), 5 test files (rewrite patches).

---

### 10. Decide in-process swarm fate (3 hours of discussion + 0–1 day of execution)
**Problem:** `thomas/agent/swarm.py` (1,135 lines) is fully tested but **not called from `/api/chat`** per its own docstring. Plus `swarm_planner.py` (282 lines) + `swarm_planner_graph.py` (69 lines) = ~1,486 lines of dead chat-path code. Bible Section 18 has detailed analysis.

**Three options:**
1. **Wire it up** to chat-V2 (highest impact — pairs with Section 7 ⭐).
2. **Retire it** (delete ~1,500 lines + tests; workboard variant stays).
3. **Document as planned-but-not-wired** (cheapest; just update the docstring).

**Recommended:** Option 3 first (5 minutes), then Option 1 if the product owner wants to invest a focused day on the chat-V2 path.

---

### 11. Add `THOMAS_STRICT_CHAT=1` mode (2 hours)
**Problem:** Chat pipeline has SIX silent failure points: UI control interception, autopilot dispatch, Discord intercept, batch ledger update, run store recording, autonomy bootstrap. Each is wrapped in `try/except` that swallows errors. Hard to debug "why didn't the autopilot fire?" in production.

**Fix:** Add a `THOMAS_STRICT_CHAT` env var that re-raises any exception in the chat dispatch chain instead of suppressing. Devs and CI run with strict mode; production stays lenient. Mirrors the `THOMAS_AUTONOMY_AUDIT_KEY` pattern.

**Files to touch:** `chat_aiohttp_streaming.py`, `chat_request_setup.py`, `chat_batch_mode.py`.

---

## Tier 4: 4-hour but high-leverage cleanups

### 12. Move legacy test-fixture data out of `thomas/server/plugins_registry/` (4 hours)
**Problem:** `thomas/server/plugins_registry/plugins/life-manager/` and `life-manager-foundation/` contain only `manifest.json` files. Bundles are runtime-generated. The path is confusing for new agents who see "plugins/{id}/" and assume a full bundle should be there.

**Fix:** Either:
- Document the runtime-bundle contract in `plugins_registry/README.md`, OR
- Move the manifests into a `manifests/` subdirectory so the `plugins/` directory is reserved for actual bundles, OR
- Generate `bundle.zip` at build time so the directory layout matches expectations.

**Recommended:** Documentation (cheapest) plus a `verify_plugin_registry_layout.py` gate.

---

### 13. Convert `_architecture.py` debt to GitHub issues automatically (4 hours)
**Problem:** Debt entries live in `_architecture.py` as comments. Nobody reads source comments. Real issues to close vs. fake annotations get lost.

**Fix:** A `scripts/sync_arch_debt_to_github.py` that:
1. Reads `_architecture.py` debt annotations.
2. For each, ensures a GitHub issue exists (creates if missing, updates body if present).
3. Adds the issue number back to the annotation.
4. Marks closed issues as resolved in the annotation.

Runs as a nightly workflow. Closes the gap between "architecture debt tracking" and "actually doing something about it".

**Files to touch:** New `scripts/sync_arch_debt_to_github.py` + nightly workflow.

---

## Top 3 recommendations (if you only do three things)

1. **#1 (CRLF policy)** — 30 minutes, ends the audit-hash divergence permanently. The single highest-payoff fix in the list.
2. **#5 (route registration diagnostics)** — 1.5 hours, prevents the next "goals routes silently disabled for 3 months" incident.
3. **#11 (`THOMAS_STRICT_CHAT`)** — 2 hours, makes chat pipeline failures noisy instead of silent. Saves debugging hours every time something orphans.

Together: **4 hours** of work, eliminates entire classes of CI-recovery debt.

---

## What this session did NOT touch (deferred)

These showed up in the broader regression sweep but were out of scope for the "CI recovery" goal:

- `test_server_models_routes::test_models_returns_profiles` — default model is `local`, test expects `cloud`. Probably needs `THOMAS_DEFAULT_MODEL` env or test fixture update.
- `test_server_local_projects_routes::test_delete_project_removes_registry_entry` + `test_import_builds_project_dossier_and_layout_persists` — passed individually, flaked when running together (likely shared state in tmp dir).
- `test_smoke_demo::test_demo_server_no_key_boot_contract_windows_safe` — Windows-specific boot contract assertion.
- `test_desktop_operator_permissions::test_desktop_operator_permissions_are_allowed`
- `test_desktop_operator_runtime::test_helper_server_round_trip`
- `test_launcher_user_experience_source::test_manifest_includes_embedded_discord_bridge_assets`
- `test_memory_curator::test_curator_*` (2 tests)
- `test_workboard_worker_script::test_worker_success_triggers_immediate_redispatch` — `dispatch_assigned_count` expected 1, got 0. Pre-existing redispatch-loop issue.

Each of these is a separate, focused session. None block the "0.15.42 ships clean" state.
