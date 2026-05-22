# Thomas

**Thomas is an AI workspace platform.** You install it once, give it your model API key, and from then on it runs locally — chat, memory, tool calls, browser automation, planning, swarms, marketplace plugins — all gated by your machine and your providers.

Fresh install: run `run-ui.cmd`, open `http://127.0.0.1:8899`, and finish Easy Setup.

> **Status (2026-05-21):** Early product release, actively stabilizing. Core flows (Easy Setup → chat → memory → task dispatch → tool calls → mission control) are wired and exercised by CI. Edges (mobile companion, swarm wiring in `/api/chat`, desktop operator runtime helpers, some marketplace domain packages) are still mid-build. See [`CHANGELOG.md`](CHANGELOG.md) for what shipped recently.

---

## What Thomas actually is

Thomas is **one local server + one web UI + one CLI**. The server hosts everything: chat, memory, plugins, tools, mission control, marketplace, autonomy engine. The UI is a static web app served from the same process. The CLI is a separate entry that drives the same code paths.

The architecture in 30 seconds:

- `thomas/core/` — config, persistence, token economy, LLM clients (bottom of the dependency tree; never imports server or tools)
- `thomas/agent/` — chat dispatch and the agent loop. Casual messages get fast replies, actionable messages get dispatched to the task manager
- `thomas/server/` — aiohttp web app, routes, the web UI assets
- `thomas/cli/` — CLI and REPL
- `thomas/tools/` — tool definitions and registry
- `thomas/memory/` — conversation and context stores
- `thomas/marketplace/` — domain modules (asset studio, companion, observability, autonomy engine, cv, vision, etc.) that the agent can call into
- `extensions/` + `thomas/plugins/` — installable plugins and the manifest catalog

Domain modules under `thomas/` are intentionally broad. The repo is a kitchen-sink platform on purpose — Thomas's value is that one workspace covers tasks that today require a half-dozen separate tools.

---

## Fresh install (the normal path)

1. Run `run-ui.cmd`
2. Wait for first-launch bootstrap to finish (dependencies + starter profile)
3. Open `http://127.0.0.1:8899` if it does not open automatically
4. Complete Easy Setup. Thomas verifies the connection before it unlocks chat, memory, and automation.

Optional advanced/manual setup: run `setup.cmd`.
If setup breaks, run `repair.cmd` (or use **Auto Repair** in the onboarding wizard).

Troubleshooting and model setup details: [`ONBOARDING.md`](ONBOARDING.md).
Security policy: [`SECURITY.md`](SECURITY.md).

---

## Production / remote deploy

Thomas defaults to **local-only**. To run remote/production, you copy `.env.thomas.production.example` → `.env.thomas.production` (or set the env inline) and:

1. Set a strong `THOMAS_SERVER_API_TOKEN`
2. Set `THOMAS_MUTATING_CSRF_TOKEN` for request-level protection on mutating `/api` and `/gateway` routes
3. Start with `THOMAS_ENV=production`
4. Verify `/api/health` returns before opening external traffic
5. Keep logs rotating via `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, `THOMAS_LOG_BACKUP_COUNT`
6. Set `THOMAS_ALLOW_REMOTE_PRODUCTION=1` only for explicitly approved remote deployments

Gateway security runbook: [`docs/ops/GATEWAY_SECURITY_RUNBOOK.md`](docs/ops/GATEWAY_SECURITY_RUNBOOK.md).
Docker deploy: [`docs/ops/DOCKER_DEPLOY.md`](docs/ops/DOCKER_DEPLOY.md).
Retry guidance: [`docs/ops/RETRY_POLICY.md`](docs/ops/RETRY_POLICY.md).
Installer build docs: [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md).

---

## Everyday Use

The normal-user contract is intentionally simple:

- **Chat** — ask Thomas questions, plan work, keep the main surface calm
- **Tasks** — turn requests into checklists, follow-ups, and next actions
- **Memory** — keeps context between sessions only when you want it
- **Integrations** — connect providers and tools gradually instead of all at once
- **Repair** — `status`, `quickstart`, `setup`, or `repair.cmd` when something drifts

## Grow Into Advanced Thomas Safely

The deeper systems (mission control, workboards, swarms, autonomy engine, marketplace builder, companion mobile) are intentional. They exist so Thomas can expand without becoming fragile. Normal use should not require understanding those systems on day one.

---

## What works today vs. what's still rough

**Works:**

- Easy Setup → first chat (Sections 1–5 of the design spec are wired end-to-end)
- Memory store + retrieval across sessions
- Task ledger (`/api/task-ledger`) tracking chat → in-progress → complete transitions
- Asset Studio routes (`/api/asset-studio/v1/*`)
- Marketplace catalog + plugin install/uninstall (`/api/marketplace/*`)
- Discord bridge for chat (`channel=discord`)
- Codex bridge for ChatGPT-account-based model use
- Mission control (`/api/mission/*`) including autopilot intent detection
- 90+ CI gates (linting, type safety, secret scanning, repo hygiene, audit trails)

**Rough or partial (don't be surprised):**

- Mobile companion (`thomas/companion/`) — scaffold + API contracts exist, app handoff still in flight
- Desktop operator (`thomas/desktop_operator/`) — runtime helpers have signature mismatches under refactor (xfailed in CI)
- Swarm in `/api/chat` — `thomas/agent/swarm.py` is fully tested but not called from the chat route (planned: see CHANGELOG)
- Some marketplace domain packages — STATUS.md says one thing, code says another (gradual cleanup in progress)
- UI polish — expect transient layout artifacts in dense composer / overlay screens

If you find a layer that's misrepresented, please open an issue rather than assuming it's broken everywhere.

---

## For contributors

**Start here:** the agent router. It tells you which docs to read for your specific task.

```
python scripts/crew/brief/startup_router.py --summary "<task summary>"
```

Canonical router doc: [`docs/ai/AGENT_ROUTER.md`](docs/ai/AGENT_ROUTER.md). The router replaces "read every doc in the repo first" — the long docs are reference, not first-pass reading.

**Before you build:**

1. Read [`AGENTS.md`](AGENTS.md) (full rules + router startup)
2. Read [`GUARDRAILS.md`](GUARDRAILS.md) (immutable project rules)
3. Read the module-level `GUARDRAILS.md` in whatever directory you're modifying (if one exists)
4. Check `agent_safety.toml` for protected files, forbidden patterns, circular-import rules
5. Check the planning board: [`plans/thomas/WORKBOARD.md`](plans/thomas/WORKBOARD.md)

**Planning & coordination:**

- Active planning board: `plans/thomas/WORKBOARD.md`
- Planning hub: `plans/thomas/README.md`
- Repo structure source of truth: `docs/REPO_STRUCTURE_PROTOCOL.md`
- Task ecosystem protocol: `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`

Active plans go in `plans/thomas/` (`tasks/`, `problems/`, canonical plan files), NOT randomly in `docs/` or repo root. Enforced by `scripts/forge/gates/plan_structure_gate.py` + `scripts/forge/gates/release_update_gate.py`.

**Branch awareness (required — prevents duplicate work):**

Before creating any new file or feature, check for existing work on other branches:

```bash
git branch -a --list '*<keyword>*'          # branches named after the feature
git log --all --oneline --grep='<keyword>'  # commits mentioning it anywhere
```

If you find matching branches or commits, READ the diff before building anything new.

---

## Common contributor commands

```bash
# Pre-commit + pre-push hooks (run these once per checkout)
pre-commit install
pre-commit install --hook-type pre-push

# Fast static checks
python scripts/auto_checks.py --quick

# Full auto checks (lint + gates + step-up test protocol)
python scripts/auto_checks.py

# Full pytest ladder
python scripts/test_stepup_protocol.py

# Repo-wide tests including the monolithic suite (slow)
python scripts/test_stepup_protocol.py --max-stage full

# Clean junk artifacts + report worktree cleanliness
thomas repo-clean --apply --strict

# Status check (gate-ready)
thomas status --json --strict-worktree
```

---

## Code intelligence (built-in)

Thomas indexes its own source so the agent can answer questions about the codebase using hybrid (semantic + lexical) search.

```bash
pip install chromadb sentence-transformers
```

Lexical search uses SQLite FTS5 (built into many Python sqlite builds). If FTS5 isn't available, lexical auto-disables.

Query operators inside the search string (no schema changes):

- `path:thomas/tools ToolRegistry`
- `file:rag_index.py build`
- `ext:.py registry register`
- `symbol:ToolRegistry kind:class`
- `phrase:"ToolRegistry class"`
- `regex:/rag\.search/`

Results come with line-numbered previews when the file is on disk.

---

## How Thomas is documented

Every Thomas instance has its own **private bible** (`docs/THOMAS_BIBLE.md`) — a per-user, accurate record of what's actually true about that workspace's code. The bible is intentionally not committed to the public repo; it captures internal honesty (what works, what doesn't, what STATUS.md files lied about) for the operator who maintains that copy.

This README is the public-facing summary. If something here disagrees with reality, file an issue — the bible was almost certainly right.

---

## Release safety

The public repo enforces:

- `scripts/forge/gates/public_repo_leak_guard.py` — blocks any push that re-introduces competitor names or internal-only doc patterns (installed 2026-05-21 after a manual cleanup arc)
- `scripts/forge/publish/preflight.py` — secret scan + blocked-file check before push to public main
- `.github/workflows/github-publish-safety.yml` — same gates run server-side in CI
- `.github/workflows/robustness-gates.yml` — full test ladder, module audits, repo hygiene
- `.github/workflows/site-release.yml` — `apps/site/` deploy guard with visual proof

If you fork the repo and want to extend any of these, the gates' configuration is intentionally readable — `FORBIDDEN_SUBSTRINGS` / `FORBIDDEN_PATHS` / `ALLOWLIST_PATHS` lists at the top of each gate file.

---

## License

MIT. See [`LICENSE`](LICENSE).
