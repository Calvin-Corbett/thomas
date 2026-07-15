# Product-Ready Push — Mission Plan (2026-07-15)

Coordinator: claude (Fable 5). Peer builder: codex (GPT-5.6 xhigh). Owner: Calvin.
Source: 11-agent read-only recon sweep of dev @ 89d708d4 + landing-lane diagnosis. Full per-area
evidence lives in the recon journal; this doc is the distilled, binding plan. Update it as units land.

## Mission (Calvin, 2026-07-15)

1. Chat, Code, and Work tabs work end-to-end at frontier presentation level (action-after-action
   on par with Claude Code / Codex).
2. ONE canonical frontend/backend; the new main-chat UI presents everywhere; all other
   frontends/backends deleted or route-disabled (delete-old-before-new).
3. Forge mode reconciled with the canonical UI.
4. Marketplace product-ready (user skill upload is a designed follow-on, see P4).
5. UI editor works.
6. Organic in-browser testing of every major use case (Playwright against a live instance —
   mandatory before declaring any unit fixed; this repo has a history of stale scorecards).
7. Final capability test: an agent driven through Thomas's own chat upgrades Thomas live (hot swap).
8. Public GitHub release Calvin can promote.

**Grading protocol (Calvin rule):** every completed unit is graded by a FRESH codex session against
an explicit rubric before it lands. Only the final product gets one Claude Fable grading pass.

**Fast mode (Calvin grant, 2026-07-15):** thomas-dev dev = green gates only, no human review,
auto-merge on. Landing Lane components A-H per msg-20260715193735 + msg-20260715194410.
Autonomy toggle (component G) is a human-only guardrails feature — never delete the human option.
DISCOVERY: **QuickBuilder mode already IS that toggle** (CHANGELOG 2026-06-03: Windows-Hello gated,
HMAC-signed flag, relaxes workflow/coordination gates, security spine unsuppressible, agents cannot
self-activate; currently ON — merge_readiness reports "SKIP (QuickBuilder mode)"). Component G
therefore = extend `scripts/quickbuilder_toggle.py` to project its level onto GitHub branch
protection (sync step), not a greenfield build. `scripts/dev_land.py` (Hello-tap admin landing)
already covers the human-approved override lane.

## Canonical UI decision

- **Canonical product UI:** `thomas/server/web/chat.html` served at `/`, backed by `/api/v2/chat`.
- **`/classic`** (index.html + app_runtime_loader.js + js/runtime/, 48 files) survives ONLY as the
  embedded workspace host until each workspace (Code/Forge, Mission, Office...) is re-homed.
- **wt2's unified Chat/Code/Work shell** becomes the evolution target of chat.html once landed and
  browser-verified. Its `unified_code_mode.js` capability wiring merges with dev's richer
  047 transcript rendering — ONE Code client at the end, the other deleted.
- **apps/site** stays: separate public Next.js site.
- **Delete or route-disable** (single sweep unit, protected-files pre-check first): legacy
  `/api/chat` pipeline (~2,600 lines, after companion/onboarding/discord consumer audit),
  thomas_chat.html, app_runtime_primary.mjs (retarget chat_control_protocol gate +
  test_web_chat_surface_contract.py first), js/src/runtime_modules/, js/modules/ (inline the three
  063_* rescue deps), dead top-level JS (app_modules.js, settings.js, composer_redesign.js,
  model_settings_dropdown.js, thomas_engine_panel.js, thomas_world.js), routes/core_aiohttp.py,
  web-ui/, web-root autonomy.* + swarm_board.*, nine orphan static workspace pages (Calvin
  confirmation), both token_economy previews. Keep exactly one virtual_office.html (CLI parses it).
- Fix `__THOMAS_CHAT_V2__` flag drift to default-V2 everywhere, then delete the flag.

## Priority sequence

- **P0a — Worktree landing/reconciliation.** wt2 (codex/unified-chat-code-work-clean-20260715,
  +43.7k lines) absorbs wt1/wt3/wt4 (verified by cross-diff) and is the ONLY Work-tab / unified-shell
  implementation. Land it as an integration checkpoint; its 61-row fail-closed rubric then gets
  verified row-by-row on dev with browser evidence. Salvage-review wt1 (~363 residual lines) and
  wt3 (chat_v2.py delta); abandon wt4. Handle wt2's junk auto-sync commit 8b94855e (amend/drop);
  DISABLE the Workspace Sync Engine idle auto-commit in wt2 before landing. Decide
  claude/forge-evolve-tab-2026-07-02 (conflicting chat.html rewrite) BEFORE any chat.html work.
- **P0b — CI/gates green at HEAD** (claude, in progress): test_architecture.py 4 failures,
  preflight/snapshot ModuleNotFoundError, 'redacted-acp-peer' leak-guard scrub (3 plans/ files). Nothing
  auto-merges until this lands.
- **P1 — UI unification** onto the canonical stack (route repair: /mission shadowed, /landing
  missing, /settings unstyled; flag unification; /api/chat retirement after consumer audit;
  deletion sweep; doc truth pass). Browser-verified.
- **P2 — Per-tab polish** (each unit browser-verified + codex-graded):
  Chat: mid-stream tool_start/args events in reasoning.py; write_eof event-loss fix; REST
  cancel/steer endpoint wired to UI; per-message activity/receipt persistence across reload.
  Code: merge unified_code_mode capabilities into one client; per-conversation build keying (lift
  the single-global-lock); real effort dial; fix 'GPT-5.5' label.
  UI editor: 048_ui_studio_canvas.js postJson envelope bug (one function!) + 120s timeouts +
  destroy() teardown; resolve rescue-mode divergence; delete dead 044 editor + rewrite pinning tests.
  Forge: My Stuff deep link, embed-CSS vs composer conflict, re-run 83-MUST rubric on canonical surface.
- **P3 — Hot-swap seam:** after promote_green_delta_to_blue succeeds, trigger the existing
  /api/server/restart graceful reload (replace Stop-Process self-kill); log promote subprocess
  output; retire/supervisor-gate legacy upgrade_promote_green_to_blue; falsifiable end-to-end
  marker test (chat -> loop -> promote -> reload -> new marker served).
- **P4 — Marketplace MVP:** resolve retired-ids contradiction (life-manager is both blocklisted and
  the only published bundle), publish the wave, regenerate site snapshot (hostedPlugins == [] today),
  exclude 480 pack-* scaffolds from public browse. USER UPLOADS DEFERRED: current signing is
  presence-only theater; accepting third-party uploads requires a real signing/verification design.
- **P5 — Parity harness honesty** (after codex's exclusive slice): land harness to dev, regenerate
  evidence live, publish the real ~68.5 baseline, delete stale 100/100 scorecards, work the gap ledger.
- **P6 — Release readiness:** one release lane (recommend: public main, kill the phantom 'prod'
  branch expectation), reconcile dev/main divergence (49 vs 23 commits), refresh 5-week-stale public
  main, tag a release so PyPI workflow runs, fix daily-red Nightly Reliability, README/docs truth pass
  (Bible claim, DOCUMENTATION_INDEX broken links, Dockerfile nonexistent [dev] extra, CONTRIBUTING.md).

## Conflict rules (binding)

- chat.html is FROZEN for all agents until the wt2-vs-forge-tab direction decision is executed.
- codex holds tests/stress/chatgpt_parity_*.py, tests/test_chatgpt_parity_loop.py, CHANGELOG.md
  until its integrity slice completes.
- No parallel edits to the same file without a board claim. Units are small; land same-session.
- Deletion sweep must retarget gates/tests that pin dead surfaces in the SAME commit
  (chat_control_protocol.py, test_web_chat_surface_contract.py, test_ui_editor_rescue_surface.py).

## Decision log (Calvin)

- 2026-07-15: Fast mode granted; autonomy toggle must remain a human-only option forever.
- 2026-07-15: 0.17.0 bump approved (coherence passage) — land AFTER P0b makes gates green.
- PENDING (proceeding with coordinator defaults unless Calvin objects):
  D1 wt2 lands as integration checkpoint, rubric verified after (default: yes).
  D2 UI direction = wt2 unified shell; forge-tab branch salvaged into it, not landed (default: yes).
  D3 Nine orphan static workspace pages deleted (default: yes, recoverable via git).
  D4 Marketplace: un-retire life-manager OR publish paper-trading/inkwell/desktop-operator instead
     (default: publish paper-trading/inkwell/desktop-operator, keep life-manager retired).
  D5 Release lane = public main (default: yes; delete prod-branch expectation from CI).
  D6 Guardrails default-on in thomas.toml so /api/health stops reporting 'degraded' (default: on).
  D7 Runtime-protected-path promotion lane for self-improvement (needs design; default: directed
     evolve agent + git + restart, no silent self-modification of protected paths).
  D8 E-commerce marketplace.* agent tools (register_vendor w/ tax_id+bank_account into unwired local
     store) unregistered by default (default: unregister until real backend exists).
