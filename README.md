# Thomas

**Thomas is a local AI workspace you own, built on the engineering standards private teams keep to themselves, applied to AI, for everyone.** One server on your machine, one browser-shaped app, one CLI. You give it a model (a cloud key or a local model) and from then on it chats, remembers, builds and verifies software, runs work you define, drives a browser, and edits its own interface when you ask it to. Everything runs and is stored on your computer.

Fresh install: run `run-ui.cmd`, open `http://127.0.0.1:8899`, finish Easy Setup. The desktop app (`desktop.cmd`) wraps the same server in a window whose tabs Thomas can see and act on.

> **Status (2026-09-07):** version 0.19.36, in active development on a private `dev` branch that lands here as squashed releases. The lanes below are wired end to end and are exercised daily by the people building it; the "Known rough edges" section says exactly what is not yet right.

---

## What Thomas is

Thomas is not a chat window in front of an API. It is a workspace with three lanes in one shell, and a standards layer underneath that treats an AI agent the way a serious engineering team treats an engineer.

- **Chat** is not the usual assistant. It is a dispatcher, always ready for the next task: it answers what it can answer, remembers what you told it, calls tools, and hands real work to Build or Work with a task card you can follow while you carry on talking. The home tab is always Chat.
- **Build** takes a request for software, writes it in a workspace, runs it, plays it in a browser, and holds itself to an acceptance contract drawn from your own words before it says "done".
- **Work** is where you give Thomas a job and he keeps doing it. An onboarding conversation maps the job into workflows, automations and connectors; then Thomas designs a dashboard for that job alone, with its own metrics, sections, inboxes and action buttons bound to that job's workflows. That dashboard is where you see the work. It is not Mission Control; Mission Control is the operator's view of runs and agents across the whole system.

Around the lanes sits a browser: Chrome-style tabs, an omnibox, back and forward, a refresh button with a right-click "Restart server". Every Chat, Build or Work tab is its own page.

**Redesign** is how Thomas changes himself. Point at anything on the screen, from a button to a whole panel, and tell Thomas what you want. A visual change (colour, size, wording, position) applies at once as an overlay your browser keeps, with undo. A change that needs code becomes a Build run on Thomas's own source, fenced off from files other agents hold, verified like any other build. Press Ctrl+Shift and release it and the page enters **UI Edit Mode**: every region gets a handle, so you can move it, resize it eight ways, edit it from the keyboard with snapping and guides, lock it, undo and redo, and save or cancel; the layout is kept per device.

**Praxis** is the standards layer. Every agent that works on Thomas, human or model, claims the files it will touch on a shared board, binds a session before it can change anything, commits through a tool that runs the whole gate stack, and is held to the same honesty rules as the product: a claim is evidence or it is not a claim, a closed problem has a practice or an owned expiring risk, a dead branch has a grave, an owner-only action arrives as a Windows Hello tap. Thirty-four pre-commit hooks stand behind it, including one that refuses a commit importing a module git does not track. This is what private engineering teams do for themselves; Thomas ships it for everyone and uses it on its own AI.

Thomas is honest by construction. A reply with no evidence is never "done". A receipt says what a turn cost, or that the model server reported nothing. A run that fails says so, and the record keeps what it did produce. When the harness cannot verify something, it says it could not, rather than presenting a guess as a result.

---

## Everything Thomas can do

Grouped by lane. Every item names something that exists in this tree and is reachable from the app; the tool counts come from the server's own registry.

### Chat

- Dispatches: a casual message gets a fast reply, an actionable one becomes a task card in Build or Work, and Chat stays free for the next thing you say. Any configured model: OpenAI-compatible endpoints (including a local Ollama or LM Studio), Anthropic, and an OpenAI Codex account, with a per-turn model switch in the top bar.
- Hears a tool call even when a smaller model writes it into its text instead of calling it natively, and executes it through the same fence and policy as a native call.
- Remembers across sessions with `remember` and `recall` tools and a memory fabric (scored retrieval, contradiction tracking, token-aware packing); temporary chats keep nothing.
- Creates images, music and video from the plus menu, with a local model or an API key per medium, and shows the result in the chat's Activity panel.
- Changes itself on request (**Redesign**): point at anything, say what you want; visual changes apply as a per-browser overlay with undo, deeper ones become a fenced Build on Thomas's own source. **UI Edit Mode** (Ctrl+Shift, press and release) turns every region into a handle: move, eight-way resize, keyboard editing, snapping, lock, undo and redo, save or cancel, per device.
- Keeps a visible checklist, asks one clear question with options when a decision is yours, records standing goals every later turn is held to, and shows what it made recently.
- Prices every reply on the receipt line; a locally served model reads "local, no charge".
- Exports a chat, branches a conversation from any message, rates a reply, and speaks or listens through a realtime voice surface.

### Build

- Turns a request into a workspace, writes the files, and runs them; web pages get a real browser playtest (`web.playtest`) against a served preview, never a file opened from disk.
- Holds itself to an **acceptance contract** extracted from your ask (data-file fields, outputs, commands), checked in the workspace by a separate evaluator; the finish is a checked declaration, not a sentence.
- Snapshots by manifest so a project without version control still has a before-and-after record of every run.
- Previews deliverables on an isolated origin that serves the page's own packages and nothing beside them (no secrets, no git config).
- Refuses to write into files another agent has claimed, in both dispatch paths (the in-process loop and the Claude CLI).
- Records every run: transcript, tool receipts, changed files, verdict, tokens.

### Work

- Onboards a job in conversation: the model owns the goal, the phase, the workflow map and the selection, and records them as structured state rather than guessing from prose.
- Designs a dashboard for each job: up to eight metrics, six sections, inboxes, and action buttons that can only bind to that job's own workflows and automations, never to an invented one. The dashboard is the job's home; you watch and steer the work there.
- Links a one-time automation to a recurring one, keeps run history and outcomes per job, and cancels in a way that waits for the run's own cleanup.
- Suggests only connectors that are installed, and refuses to promise a hand-off it cannot perform.

### Tools the model can call (170 registered)

| Area | What is there |
|---|---|
| Files and code | read, write, search, list; unified-diff patches with per-hunk preflight; definition and reference lookup, project structure, hybrid semantic + lexical code search |
| Shell and git | shell in the project directory (policy-gated); git status, diff, log, blame, commit, pull request; SSH exec and SFTP |
| Browser | open, click, extract, console and network capture, screenshots, playtest of a served page |
| Web | fetch a page as clean text; search |
| Knowledge | library entries and research notes with a build-context step; RAG index over the repo and your documents |
| Communication | email read, reply, send; calendar today, week, create, suggest times; Google Drive list, get, search, share; Telegram and Discord channels; notifications and webhooks |
| Media and vision | image generation; vision analysis and OCR; realtime publish and subscribe |
| Engineering | complexity, dead code, dependency tree, encoding and type detection, formatting, security audit, dependency policy, threat-model cadence |
| Operations | blue/green upgrade with backup, promote and rollback; system tray agent; config drift and compliance; policy evaluation; preferences |
| Workflow | flows with nodes and edges, sagas with compensation, two-phase transactions, templates, task management |
| Trading (paper) | account, quotes, bars, positions, proposals against a simulated account |
| Self | create a skill from a workflow, list and use trusted skills, ask the user, keep a todo, record a goal, list recent work |

### Under the hood

- **Coordination board.** Every agent working in this repository claims files on `plans/thomas/WORKBOARD.md`, binds a session before any mutation, and lands through a commit tool that runs the whole gate stack; 34 pre-commit hooks stand behind it, including one that refuses a commit importing a module git does not track.
- **Verification.** A separate evaluator judges a Build against its contract; a monolith guard, an exception-handler gate, a changelog gate and an enforcement-integrity manifest stop the usual ways a codebase rots.
- **Observability.** Runs are persisted and replayable (`/api/runs/{id}/events`, replay seek and step), with secrets redacted; a task ledger tracks chat to in-progress to complete.
- **Self-update.** Doppelganger blue/green upgrades with rollback; Evolve runs let Thomas change its own code under the same fence and verification as any other build.
- **Security posture.** Local-only by default; remote mode needs an API token and a CSRF token; runtime protection refuses agent writes into Thomas's own runtime unless a Windows Hello approval window is open; secrets are stored, never committed; a publish preflight scans for them before anything reaches this repository.

---

## Known rough edges

Read this before assuming a lane is broken everywhere.

- The isolated self-edit flow (demo a change in a candidate copy, then apply) is built but blocked: runtime protection currently fires inside the candidate copy, so a Redesign that needs source changes runs but cannot write there yet.
- The first message sent after a page reload can be hidden by the previous chat being restored over it. The turn completes on the server; the fix is in progress.
- A background build worker can be filed as failed by a stall watchdog whose window is shorter than a long reasoning turn, even when the deliverable exists and works.
- The mobile companion (`thomas/companion/`) is a scaffold with API contracts, not a shipping app.
- The desktop app is blocked on machines with Windows Smart App Control enabled; `docs/DESKTOP.md` explains.
- Many domain modules under `thomas/marketplace/` were generated in one burst, are wired into the tool registry, and have no real caller. They are debt, not features; the catalogue above lists only what has one.

---

## Fresh install (the normal path)

1. Run `run-ui.cmd`
2. Wait for first-launch bootstrap to finish (dependencies + starter profile)
3. Open `http://127.0.0.1:8899` if it does not open automatically
4. Complete Easy Setup. Thomas verifies the connection before it unlocks chat, memory, and automation.

Optional advanced/manual setup: run `setup.cmd`. If setup breaks, run `repair.cmd` (or use **Auto Repair** in the onboarding wizard).

Troubleshooting and model setup: [`ONBOARDING.md`](ONBOARDING.md). Desktop app: [`docs/DESKTOP.md`](docs/DESKTOP.md). Security policy: [`SECURITY.md`](SECURITY.md).

---

## Production / remote deploy

Thomas defaults to **local-only**. To run remote/production, copy `.env.thomas.production.example` to `.env.thomas.production` (or set the env inline) and:

1. Set a strong `THOMAS_SERVER_API_TOKEN`
2. Set `THOMAS_MUTATING_CSRF_TOKEN` for request-level protection on mutating `/api` and `/gateway` routes
3. Start with `THOMAS_ENV=production`
4. Verify `/api/health` returns before opening external traffic
5. Keep logs rotating via `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, `THOMAS_LOG_BACKUP_COUNT`
6. Set `THOMAS_ALLOW_REMOTE_PRODUCTION=1` only for explicitly approved remote deployments

Gateway security runbook: [`docs/ops/GATEWAY_SECURITY_RUNBOOK.md`](docs/ops/GATEWAY_SECURITY_RUNBOOK.md). Docker deploy: [`docs/ops/DOCKER_DEPLOY.md`](docs/ops/DOCKER_DEPLOY.md). Retry guidance: [`docs/ops/RETRY_POLICY.md`](docs/ops/RETRY_POLICY.md). Installer build: [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md).

---

## The architecture in 30 seconds

- `thomas/core/` — config, persistence, token economy, LLM clients (bottom of the dependency tree)
- `thomas/agent/` — chat dispatch and the agent loop; casual messages get fast replies, actionable ones go to the task manager
- `thomas/server/` — aiohttp web app, routes, the web UI (the browser shell, the three lanes, Redesign)
- `thomas/forge/` — Build: dispatchers, verification, manifests, previews, self-edit
- `thomas/work/` — Work: job store and mission delegation
- `thomas/cli/` — CLI and REPL
- `thomas/tools/` — tool definitions and the registry
- `thomas/memory/` — conversation and context stores
- `thomas/marketplace/` — domain modules; see the rough edges above
- `extensions/` + `thomas/plugins/` — installable plugins and the manifest catalogue
- `scripts/forge/gates/` — the commit gates; `scripts/crew/` — the coordination board and its tools

---

## For contributors

**Start here:** the agent router. It tells you which docs to read for your specific task.

```
python scripts/crew/brief/startup_router.py --summary "<task summary>"
```

Canonical router doc: [`docs/ai/AGENT_ROUTER.md`](docs/ai/AGENT_ROUTER.md).

**Before you build:**

1. Read [`AGENTS.md`](AGENTS.md) (full rules + router startup)
2. Read [`GUARDRAILS.md`](GUARDRAILS.md) (immutable project rules)
3. Read the module-level `GUARDRAILS.md` in whatever directory you're modifying (if one exists)
4. Check `agent_safety.toml` for protected files, forbidden patterns, circular-import rules
5. Check the planning board: [`plans/thomas/WORKBOARD.md`](plans/thomas/WORKBOARD.md)

**Planning & coordination:** the board is `plans/thomas/WORKBOARD.md`; the planning hub is `plans/thomas/README.md`; repo structure is `docs/REPO_STRUCTURE_PROTOCOL.md`; the task ecosystem protocol is `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`. Active plans go in `plans/thomas/` (`tasks/`, `problems/`), enforced by a gate.

**Branch awareness (required):** before creating any new file or feature, check for existing work on other branches:

```bash
git branch -a --list '*<keyword>*'
git log --all --oneline --grep='<keyword>'
```

**Landing code:** commits go through `scripts/crew/brief/commit.py`, which runs every gate and refuses what the board does not allow. `--no-verify` is banned. Run `ruff check` on any Python you touch.

## Common contributor commands

```bash
# Pre-commit + pre-push hooks (run these once per checkout)
pre-commit install && pre-commit install --hook-type pre-push

# Fast static checks
ruff check . && ruff format --check .

# Full pytest ladder
python -m pytest -q

# Status check (gate-ready)
python scripts/crew/brief/commit.py --agent <you> --message "x" --dry-run
```

---

## Code intelligence (built-in)

Thomas indexes its own source so the agent can answer questions about the codebase using hybrid (semantic + lexical) search.

```bash
pip install chromadb sentence-transformers
```

Lexical search uses SQLite FTS5. Query operators inside the search string: `path:thomas/tools ToolRegistry`, `file:rag_index.py build`, `ext:.py registry register`, `symbol:ToolRegistry kind:class`, `phrase:"ToolRegistry class"`, `regex:/rag\.search/`.

---

## How Thomas is documented: the Bible

Thomas is too large for any one person or model to hold in their head, so it keeps an encyclopedia of itself: `docs/THOMAS_BIBLE.md`. It traces the whole system one user step at a time, from download to install to the first message, through chat, dispatch, tools, memory, Mission Control, the browser, the companion, updates, publishing and swarms, and then covers the rest of the tree package by package. Each section names the files that actually fire.

Its design rule is that it never says "verified working". Every section carries a verification level (deep, sampled, scanned, mapped) and a date, so a reader knows how far to trust it and what has not been looked at since. Agents that change the code are required to bring the relevant section with them, so it moves with the project instead of lagging it; when the bible and the code disagree, the bible records that too. It is the ledger of truth for the codebase, the first thing an agent reads before touching an area, and the place a wrong claim is caught.

Beside it: `docs/FEATURE_CATALOG.md` is the map of major capabilities, `docs/FRONTIER_PARITY.md` is the running ledger of what was checked against frontier tools and what was found, and `CHANGELOG.md` says what changed and why in plain sentences.

This README is the public-facing summary. If something here disagrees with reality, file an issue; the bible was almost certainly right.

---

## How this repository is published

Development happens on a private `dev` branch with the coordination board and the full gate stack. Releases reach this repository's `main` as a single squashed landing after `scripts/forge/publish/preflight.py` (secret scan, blocked-file check, private-marker sweep) passes. The public repo enforces the same in CI:

- `scripts/forge/gates/public_repo_leak_guard.py` blocks any push that re-introduces internal-only patterns
- `.github/workflows/github-publish-safety.yml` runs the publish gates server-side
- `.github/workflows/robustness-gates.yml` runs the full test ladder, module audits, repo hygiene
- `.github/workflows/publish.yml` builds to PyPI only when a version tag is pushed

---

## License

MIT. See [`LICENSE`](LICENSE).
