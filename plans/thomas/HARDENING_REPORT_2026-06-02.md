# Thomas Hardening Sweep — 2026-06-02

Coordinator: claude · Worker: codex (frontend/CI lane) · Directed by Calvin
("harden every critical field, main functionality outward, decisions yours").

Method: a 6-agent live-code audit of core / agent / server / tools / Praxis
gates / secrets, verified against the **current worktree** (the CodeQL alert DB
is computed on `main`, which lags the dev line, so most of its 201 alerts are
stale — fixes already applied here). Findings were triaged real-vs-stale, then
fixed (non-protected surfaces) or documented (protected surfaces).

---

## 1. Fixed + tested (ready to land) — 51 new tests, all green

All in-tree, ruff-clean, with regression tests. **Not yet committed** — see §5.

| # | Area | Fix | Files | Tests |
|---|------|-----|-------|-------|
| 1 | **SSRF (HIGH)** | `eng.web_extract` + `browser.open` fetched model-supplied URLs with **no SSRF guard** (reachable cloud-metadata `169.254.169.254` / internal services). Added one canonical guard and wired all three URL tools through it; tiered policy (always-block link-local/metadata/multicast/reserved, gate RFC1918/loopback behind `allow_private`), DNS resolution, per-redirect-hop validation. Hardened `web.fetch` too. | `thomas/tools/url_safety.py` (new), `web_search_providers.py`, `engineering.py`, `browser.py` | `test_tool_url_safety.py` (32) |
| 2 | **Rate-limit bypass (MED)** | `plugin_hosting._get_client_ip` trusted `X-Forwarded-For` unconditionally → spoof XFF per request = fresh bucket. Now off by default, opt-in via `THOMAS_TRUST_FORWARDED_FOR`. Also made file-stored API-key check constant-time (`hmac.compare_digest`). | `thomas/server/routes/plugin_hosting.py` | `test_plugin_hosting_security.py` (6) |
| 3 | **Weak KDF (MED)** | `THOMAS_SECRET_KEY` passphrase derived the at-rest Fernet key via **unsalted single SHA-256**. Upgraded to salted PBKDF2-HMAC-SHA256 (200k iters, persisted per-install salt); `MultiFernet` keeps the legacy key so existing data still decrypts (seamless migration). | `thomas/preferences/_utils.py`, `_db.py` | `test_preferences_kdf.py` (4) |
| 4 | **Code injection (MED)** | `verify_after_tool` built `python -c "import {module_name}"` from a model-controlled filename — a `;` in the stem injected a second statement. Now passes the name as argv data to `importlib.import_module(sys.argv[1])` + a dotted-identifier regex guard. | `thomas/agent/verification.py` | `test_verification_import_guard.py` (3) |
| 5 | **Boot robustness (LOW)** | `_coerce_types` called `int()/float()` unguarded → `THOMAS_MAX_TOKENS=abc` crashed `load_config()` at startup. Now drops the malformed override so the validated default applies. | `thomas/core/config.py` | `test_config_coerce.py` (3) |
| 6 | **Tool DoS (MED)** | `AgentLoop` defaulted `tool_timeout_s`/`max_parallel_tools` to `None` → plan-mode/CLI/integrations ran tools with **no timeout + unbounded fan-out** (one hung tool stalls the turn). Now defaults to 600s backstop / 6 parallel; explicit values still honored. | `thomas/agent/loop_core.py` | `test_agent_loop_tool_timeout.py` (3) |
| 7 | **Read DoS (LOW)** | `ui_workflow_engine._fetch_json` did `response.read()` with no size cap. Capped at 8 MB. | `thomas/core/ui_workflow_engine.py` | (obvious; covered by import smoke) |

**Codex frontend/CI lane (separate worktree, staged + validated, also HOLD):**
real download-token **secret leak** (API key embedded in URL) fixed, prod-required
signing secret, process-random dev secret, `timingSafeEqual`, no-store responses,
per-IP throttles, HTTPS-only redirects, salted IP hashes, and the unpkg Spline
loader pinned with **Subresource Integrity**. Confirmed the 12 workflow-permission
CodeQL alerts are **stale** (workflows already least-privilege).

---

## 2. Requires Calvin — protected enforcement files (DO NOT auto-edit)

These are real, but live in `agent_safety.toml [protected_files]` / the Praxis
enforcement system. Editing them needs explicit approval (CLAUDE.md). Recommended
fixes:

- **[HIGH] `scripts/forge/gates/enforcement_integrity.py` + `enforcement_manifest.json`** —
  `preflight.py` (the **active pre-push secret-scan hook**, listed in
  `enforcement_scripts`) has **no manifest entry**, so it's treated as
  `missing_from_manifest` (advisory) and silently passes. An agent could rewrite
  `preflight.py` to `sys.exit(0)`, neutering the pre-push secret/leak scan, with
  zero integrity alarm. **Fix:** treat `expected_hash is None` for a protected-
  list script as FAILURE (fail-closed); regenerate the manifest to cover
  `preflight.py`.
- **[MED] `enforcement_integrity.py:63-64`** — if `agent_safety.toml` is absent,
  `_load_protected_scripts()` returns `[]` *before* appending `SELF_PATH`, so
  `verify()` checks nothing and returns PASS. **Fix:** a populated manifest with
  an empty script list is contradictory → fail closed; always self-check.
- **[MED] `core_overhead_guard.py`** — `THOMAS_AGENT_ROLE in {orchestrator,...}`
  is an unsigned bare-env full SKIP and is **not** in `commit_master.sanitize_env`
  deny-set, so even a caged run honors a worker-set role. **Fix:** add
  `THOMAS_AGENT_ROLE` (+ `THOMAS_CORE_OVERHEAD_UNLOCK`) to `_ENV_DENY_EXACT`, or
  gate the skip behind the signed runtime flag.
- **[LOW] `public_repo_leak_guard.py:101-105`** — `THOMAS_LEAK_BLOCKLIST_FILE`
  can point the blocklist at a nonexistent file, silently dropping local rules.
  **Fix:** drop the override (mirror the `THOMAS_PRAXIS_MARKER_KEY_FILE` decision)
  or add to the sanitizer.
- **[LOW] systemic fail-open** — `_staged_files()` returns `[]` on a `git diff`
  non-zero in `commit_scope_gate.py`, `protected_files_gate.py`,
  `validate_agent_changes.py`, `type_safety_gate.py` → empty change set = PASS.
  `frontend_lint_gate`/`type_safety_gate`/`validate_agent_changes` also PASS when
  node/eslint/mypy is missing or times out. **Fix:** distinguish rc!=0 (fail
  closed) from "no staged files"; emit a `SKIPPED` status for genuinely-optional
  tools (use `deletions.py` as the fail-closed template).

The Praxis core spine (`commit_breakglass_guard`, `breakglass_auth`,
`_runtime_guard`, `precommit_skip_policy`, `commit_master`, `deletions`,
`merge_readiness`, the cage) was audited and is **rigorously fail-closed** — these
are coverage gaps at the edges, not a broken core.

---

## 3. Remaining LOW / latent (deferred — locations recorded)

- `thomas/tools/http_client.py` — `http.client` tool has SSRF + `verify_ssl:false`
  escape hatch but appears **unregistered/dormant**. Gate through `url_safety`
  before it's ever wired up.
- `thomas/tools/sandbox_helpers.py` — in-process code-exec deny-list sandbox;
  the OS-subprocess consumer (`sandbox.py`) is currently **non-loadable** (missing
  `sandbox_part01/02`), so dormant. Restore the OS boundary before re-enabling.
- `thomas/tools/browser.py` — `page.goto` subresource fetches aren't intercepted
  (only the top URL + final redirect are guarded). Full coverage needs `page.route`.
- `thomas/agent/loop_execution.py:119-153` — suspicious-prompt gate wrapped in a
  blanket `except Exception` (fail-open). **CODEX-OWNED + protected** — route to codex.
- ~~`thomas/marketplace/travel/itinerary.py:355` — share token used `random.choices`~~
  **FIXED** → now `secrets.token_urlsafe` (CSPRNG capability token).
- `thomas/marketplace/secrets/core.py` — base64 "encryption" re-exported under
  `thomas.secrets`; latent trap. Real AEAD or rename/guard.
- `thomas/server/routes/gateway/p150_*.py:290` — non-constant-time bearer compare
  (latent/unwired compat layer) → `hmac.compare_digest`.
- ~~`thomas/core/api_importer_importer.py:695-707` — corrupt-store handler clobbers
  the good `.bak`~~ **FIXED** (skip-if-`.bak`-exists). NOTE: this module also has a
  **pre-existing circular import** — it fails a standalone `import` with
  `cannot import name 'ApiImporter' ... partially initialized` (works in-app via
  load order). Pre-existing, unrelated to the fix; worth a structural follow-up.
- ~~`thomas/core/local_agent_engine.py:443`~~ **FIXED** (capped Ollama read) ·
  ~~`p150_*.py:290` non-constant-time bearer~~ **FIXED** (`hmac.compare_digest`).
- `thomas/chat_logger.py` / TrainingMode — chat written to JSONL without running
  `core.redaction.Redactor`; defense-in-depth redaction pass recommended.

---

## 4. Test hygiene

`tests/test_server_preferences_runtime.py::...test_require_command_approval_bypassed_for_autonomy_level_4`
fails **only under certain broad test orderings** (passes in isolation and in the
model+routes+runtime grouping). Pre-existing test-pollution (shared global/env/
singleton leakage), independent of the KDF change. Worth a `conftest` isolation
fix.

---

## 5. Landing decision — HOLD for Calvin (structural)

Both agents independently hit the **same hard stop**: `worktree-branch-guard`
rejects the dev line (`claude/runtime-protection-fix-2026-05-27`) because it's
stacked on 4 unmerged topic ancestors (`claude/bot-stack`, `claude/safety-arc-v2`,
`codex/public-ready-fixes`, `dev`) rather than a canonical base. Autonomous
landing is **not** available: breakglass-skipping a hard-stop would only deepen
the stack you'd have to rebase, and a real breakglass commit would hang waiting
for your Win-Hello tap. So both lanes are **staged/in-tree, tested, and holding**
— not stranded.

**Pick one to land everything:**
- **(A)** Rebase the dev line onto a canonical base (`master`/`release/oss-launch`/
  `publish-clean`); both topic branches then commit clean through the normal gates.
- **(B)** Run `commit_master` (the cage) with your signing tap to land the
  clean-room commits despite the stack.

Once you choose, both agents land immediately with full gate coverage.
