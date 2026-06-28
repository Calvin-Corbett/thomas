# Evolve-Loop Safety Red-Team — Punch List (Claude → Codex)

**Source:** Claude's proactive 32-agent adversarial sweep (6 attack lenses → independent verify → rank), 2026-06-22. 25 attacks, **17 confirmed NEW holes** (excludes the already-known B2 / risk_floor-dead / B1 / B3). The top item is **reproduced live**.

**Reprioritization:** C1 now outranks risk_floor and B2. C1 voids the entire green→blue isolation model — if the green agent can write directly into blue, the supervisor / risk_floor / verifier-panel / protected-set logic are all moot. **HALT self-evolve passes until C1 is closed.**

---

## CRITICAL

### C1 — Green agent's `shell.exec` writes anywhere on the operator FS (escapes green→blue isolation entirely). REPRODUCED LIVE.
`shell.exec` is NOT in `EVOLVE_DENIED_TOOLS` and `allow_shell=true` is the live config, so the green self-development pass (`python -m thomas chat --autonomy-level 4 --job-type self_development`, full `os.environ`) can run `echo X > C:/Users/corbe/Thomas/...` and write directly into **blue**, `.thomas/`, or the **`evolve_supervisor/` package**. The supervisor re-derives trust purely from a green-vs-blue *delta*, so an out-of-band write is never in that delta → never seen. Poison-then-promote chains all hold: overwrite blue `supervisor.py`, blank blue `agent_safety.toml [protected]`, or forge a passing `session.json`.
- Evidence: `thomas/forge/anvil/evolve_runtime_exec.py:17-26` (denylist omits shell.exec); `thomas/tools/shell.py:122-135` (command text never path-checked, only `cwd`); `evolve.py:1122` (allow_shell inherited). **Reproduced:** a file was created in `C:/Users/corbe/Thomas/runtime/` outside the green cwd, tool returned ok=True.
- Fix: deny `shell.exec` + all process/exec tools in `EVOLVE_DENIED_TOOLS` for `self_development`; force `allow_shell=false` in `green_env` regardless of operator prefs (run green under the existing `.wsb` cage for defense-in-depth); pin a signed sha256 manifest of blue's `evolve_supervisor/*` + `thomas/forge/anvil/*.py`, checked as a promote-time precondition.

### C2 — Supervisor protected-set omits the runtime-protected dirs → a candidate that neuters its own write-guard auto-promotes.
Green runs with `THOMAS_EVOLVE_GREEN_RUNTIME_WRITES=1` and the blue supervisor derives its protected set only from `agent_safety.toml [protected]`, which omits `thomas/tools/filesystem.py` and most of `thomas/{tools,agent,core,server}` + `scripts/`. A candidate that rewrites `_is_protected_runtime_path()` to `return None` returns `ok=True, risk_floor=low`, panel 5/5, auto-promotes.
- Evidence: `evolve_supervisor/supervisor.py:308-321`; `doppelganger.py:212-232`; `decision.py:186-221` (human-hold only for anvil/ + evolve_supervisor/); `thomas/tools/filesystem.py:283-284`.
- Fix: hardcode a blue-only mirror of `filesystem.py:_HARDCODED_PROTECTED_DIRS` in both `_load_agent_safety_paths` and `doppelganger._load_promotion_protected_paths`; force `risk_floor=critical`→human-hold for any change under those prefixes; do NOT trust the green-editable toml's narrow keys.

### C3 — Spend governor is inert: no runtime path writes the ledger it gates on, so caps never bind.
`evaluate_spend_governor` reads `thomas_spend.jsonl`; the only writer `CostTracker.record()` has zero callers in the agent/chat path (only the read-only `/cost` REPL + read-only spend routes consume it). Ledger stays empty → always within budget → the self-evolving loop runs with no real cost ceiling.
- Evidence: `evolve_loop.py:185`; `thomas/core/cost_tracker.py:336-367` (sole writer, uncalled at runtime); `spend_governor.py:86-88`.
- Fix: meter at a blue-trustworthy choke point — BLUE parses provider usage from the green child's result after `_run_exec` and appends signed rows; guard test fails if a completed session leaves the ledger byte-count unchanged.

## HIGH

### H1 — Verification floor satisfied by any test that merely NAME-MATCHES the changed module (even in a comment/unused import). Reproduced PROMOTE=True.
`_blast_radius_tests` selects a "covering" test via `re.search` of the dotted path OR the bare leaf component anywhere in the test text → a pre-existing import-smoke test clears the floor with zero behavioral coverage; arbitrary low-risk code (`BACKDOOR=True`) auto-promotes.
- Evidence: `evolve_supervisor/supervisor.py:347,359`; `evolve_verification.py:767-768`.
- Fix: drop the bare-last-component alias; require ≥1 selected test to actually execute a changed line (coverage.py), reject otherwise; add diff-coverage so a body change with no behavioral test delta is held.

### H2 — Semantic-delta strips ALL top-level imports → import-binding swaps (sha256→md5) are invisible.
`normalized_tree()` drops every `Import`/`ImportFrom` before `ast.dump`; an import-only behavior swap + one trivial body edit passes `semantic delta: PASS`, ruff, py_compile.
- Evidence: `thomas/forge/anvil/evolve_verification.py:41` (import strip), `:55-58` (noop-only reject).
- Fix: include each import (module, name, asname) in the normalized form; treat any top-level import change as behavior-bearing requiring behavioral coverage.

### H3 — Promotable non-`.py` files (`pyproject.toml`, `run-ui.cmd`, `.gitignore`, `README.md`) receive ZERO verification. Reproduced: 0 checks.
Whole plan is gated on `changed_py`; a `[project.scripts]` repoint or `[tool.pytest] addopts/pythonpath` poison rides into blue behind one clean `.py` edit.
- Evidence: `evolve_verification.py:883` (changed_py gate); `doppelganger.py:34-44` (`_INCLUDE_FILES`).
- Fix: content-gate promotable non-`.py` files; semantic-diff `pyproject.toml` (reject scripts/build-system/pytest-ini/data hooks unless human-approved); force human-hold for `pyproject`/`run-*.cmd`/`.gitignore` deltas.

### H4 — Daily-cap bypass via forged/omitted `day`. Reproduced: 1000×$5 → daily=0.0.
`_read_spend_ledger` counts daily only when `day==today`; a chosen/omitted `day` contributes $0. Daily-only config = unbounded; live watchdog shares the parser.
- Evidence: `spend_governor.py:109,206`; `evolve.py:1125-1127`; `cost_tracker.py:336`.
- Fix: derive daily from a parsed `ts`; reject missing/backdated/mismatched `ts`; make `total_cap` mandatory (omitted → fail-closed); blue-only signed ledger writes.

## MEDIUM

### M1 — Spend writer/schema (`cost_tracker.py`) is green-promotable; parser hardcoded to `usd_total`/`day`. Reproduced: rows keyed `cost` → total=0.0.
- Evidence: `doppelganger.py:33`; `supervisor.py:426-469`; `spend_governor.py:105`.
- Fix: add `thomas/core/cost_tracker.py` to protected + supervisor reject list; schema-version/required-field check in `_read_spend_ledger` that fails closed.

### M2 — Watchdog never spend-checks sub-interval (fast) sessions. Reproduced: evaluator calls=0.
Evaluator runs only in the `except TimeoutExpired` branch; sessions finishing under the 5s interval are never checked.
- Evidence: `spend_governor.py:350-356` vs `:357-381`.
- Fix: evaluate spend on every tick and once immediately before returning a completed result.

## LOW (defense-in-depth)
- **L1** `_prepare_delta_candidate_root` overlay copies/deletes session-JSON-sourced relpaths with no `..`/scope guard (`evolve.py:777-789`). Reuse `doppelganger._normalize_delta_relpath` + `_is_promotable_scope` before any overlay write.
- **L2** Verifier panel is non-independent theater — all 5 votes re-read 2 already-gated signals (`verifier_panel.py:95-152`). Add ≥1 role independent of returncodes (execution coverage); broaden `_reward_hack_vote` to flag import-swaps / pyproject-script / "clean but zero behavioral coverage".
- **L3** `run_evolve_corpus` never runs in the live promote path and isn't a CI gate (`evolve.py:864→842`). Wire it into `_promote_verified_green_delta` as a fail-closed precondition + a real CI job.
- **L4** Supervisor scope omits `extensions/` and `apps/` the candidate can contain (`supervisor.py:19` vs `doppelganger.py:45-60`). Derive all scope lists from one constant; assert `DEFAULT_SCOPE_DIRS ⊇ promotable scope` at import.
- **L5** Governor fail-opens on missing/disabled/mis-sectioned config (`spend_governor.py:122-129,142-149`) — wrong default for a kill-switch. Fail closed unless a signed operator opt-out is present.
- **L6** Watchdog tree-kill escapable by an orphaned/double-forked grandchild (reproduced on Windows). Wrap green in a Windows Job Object (`KILL_ON_JOB_CLOSE`) / Linux cgroup.

---

## Priority order (supersedes prior)
1. **C1** (shell.exec escape) — voids isolation; HALT self-evolve until closed.
2. **C2** (protected-set omits runtime dirs) + **C3** (inert spend governor).
3. Previously flagged: **risk_floor → human-hold** for meta/loop-file; then **B2** (nonce-behavioral acceptance).
4. H1–H4, then M1–M2, then L1–L6.

The throughline of every CRITICAL: the candidate can reach trust-bearing state the supervisor doesn't re-derive (the FS directly via shell, its own write-guard, the spend ledger). The supervisor must own and re-derive EVERY such signal, and the green pass must be a real sandbox — not just a different cwd.
