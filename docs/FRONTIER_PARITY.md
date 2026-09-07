# Frontier parity: everything frontier agents can do, and where Thomas stands

Started 2026-09-05 (overnight, claude + codex). Calvin's instruction: "make a long list of everything frontier agents
can do then make sure thomas can do it better or the same as them. that's more than code, that's UI, user-facing
buttons, options, sliders, everything."

Frontier set compared: Claude Code 2.1.x (CLI + desktop + web + Chrome), Claude.ai / Claude in Chrome (GA 2026-08-26),
OpenAI Codex CLI/app (Aug-Sep 2026), ChatGPT (Atlas folded in 2026-08-09), Cursor 3, Antigravity/Gemini CLI.

How each row was verified:
- **L2** = exercised live in the Thomas UI or a real run on 2026-09-05
- **L1** = read in the code path (file named)
- **L0** = keyword hit only; not trusted as "works"
- Status: **have** / **partial** / **missing** / **n/a** (not applicable to a local product)

## A. Coding harness

| # | Capability | Frontier reference | Thomas | Verified | Gap / action |
|---|---|---|---|---|---|
| A1 | Effort / reasoning slider per turn (none…max) | Claude Code effort, Codex reasoning | have: composer "Reasoning effort" None/Low/Medium/High/xHigh/Max | L2 | none |
| A2 | Autonomy / permission mode per turn | Claude Code permission modes, Codex approval modes | have: composer "Autonomy" Chat only/Assist/Agent/Full autonomy | L2 | none |
| A3 | File-access scope switch | Claude Code allow rules | have: "File access" own space / anywhere on PC | L2 | none |
| A4 | Guardrail / internet-reach level | n/a frontier; Thomas-specific | have: composer row "Reaching the internet" Off/Normal/Open (values fortress/guarded/open; chat.html:2693 explains Off = no web, no browser, no remote calls) | L2 | none; my first read called this inverted, it is not |
| A5 | Memory on/off per chat | Claude.ai memory toggle | have: composer checkbox | L2 | none |
| A6 | Model picker in the composer/header | Claude Code /model, ChatGPT picker | have: header "Switch model" | L2 | none |
| A7 | Plan mode (read-only explore, then approve a plan) | Claude Code plan mode, Codex plan | partial: `plan_mode` in chat routes | L0 | verify it is reachable from the composer; no visible control today |
| A8 | Hooks (pre/post tool, stop, session start) | Claude Code hooks | have: `thomas/agent/hook_events.py` (TOOL_PRE, read-only) | L1 | user-configurable hooks with commands: missing |
| A9 | Skills / slash commands | Claude Code skills, Codex prompts | have: `thomas skills`, skills_runtime | L1 | `/` palette in composer: missing (see B4) |
| A10 | Subagents, parallel workers | Claude Code Agent tool, Cursor subagents | have: workboard dispatch, worktree workers | L1 | none for coordination; in-chat "spawn a helper" control: missing |
| A11 | Worktree isolation per agent | Cursor 3, Claude Code EnterWorktree | have: `tools/session_worktree.py`, ledger | L1 | none |
| A12 | Background tasks + completion notification | Claude Code background agents | have: task_bots, backgrounding.py | L1 | none |
| A13 | Context compaction (auto + manual) | Claude Code /compact, Cursor self-summarization | have + improved (2026-09-05): measured why run 3 never compacted (200k window, trigger at 75% = 150k, calls averaged ~116k); NEW `agent/tool_output_pruning.py` shrinks stale tool outputs to a 400-char stub at 33% of the window with no model call, wired in `loop_core._auto_compact_if_needed` ahead of the compactor guard; 4 tests incl. the real AgentLoop | L1 | manual /compact control still missing; measure the saving on the next real run |
| A14 | Persistent memory (auto + project) | Claude Code auto-memory, ChatGPT memory | have: `thomas/memory` | L1 | user-editable memory panel in UI: missing |
| A15 | MCP client (stdio/HTTP/SSE, OAuth) | all | have: `tools/mcp_bridge.py`, Agent Plugins adapter | L1 | OAuth flow: unverified |
| A16 | Thomas as an MCP server | Claude Code, Codex | have: agent_plugins_surface | L1 | none |
| A17 | Fast mode | Claude Code /fast | have (2026-09-05): a `Fast: on/off` pill under the composer marks each chat request `mode: fast` (half the context budget, fewer tools offered, lighter memory lookup - what the V2 route always did with the key nothing sent); Settings > Autonomy > Reply speed sets the saved default (`advanced.runtime.default_mode`, a preference that had no control); `/fast` in the palette | L2 (server's route event reported mode=fast for the toggled turn; setting patched, persisted, restored) | - |
| A18 | Cost / token usage + cache-miss cause | Claude Code /cost + prompt_cache field | have (2026-09-05): a live line under the composer, `This reply 5.4k in · 5 out · ~$0.0108 · This chat 10.8k · ~$0.0215`, folded from the `done` receipt every V2 reply already carried and nothing read; priced with the same table and key order as the cost tracker | L2 (two live replies on 8977, chat total accumulated); cache reads L1 (every transport now carries `cached_prompt_tokens` to the receipt and the line shows `(1k cached)`; not yet seen live because the verify server's replies had no cache hits) | the cache-MISS cause (why a prefix stopped matching) is still not derived; chat dollars after a restart are a marked lower bound |
| A19 | Live diff panel of uncommitted changes | Claude Code 2.1.259 diff panel | missing | L0 | build in Code tab |
| A20 | Checkpoints / rewind to a prior turn | Claude Code rewind, Codex | partial: "Edit and resend from here" | L2 | file-state rewind: missing |
| A21 | Resume / continue / search sessions | all | have: sidebar search, `thomas sessions` | L2 | none |
| A22 | Headless mode + JSON output | Claude Code -p, Codex exec | have (2026-09-05): `python -m thomas.cli.headless_run --json "prompt"` prints one JSON line: ok, exit_code, outcome, model, reply, tool_log (tool, ok, ms, detail), checks (verified / unchecked), iterations, tool_calls, verification, tokens, runtime_model, error, artifacts | L2 (two real runs on gpt-5.6-sol) | - |
| A23 | Git commit / PR creation / CI monitor | Claude Code, Codex, Cursor | have: git.commit; NEW `git.pull_request` (2026-09-05) opens a PR through the installed GitHub CLI with title, body, base, draft, and pushes only when asked; 3 tests with a stubbed CLI | L1 (no live PR opened tonight: that is an outward action) | CI monitor still missing |
| A24 | Scheduled tasks / routines | Claude Code /schedule, ChatGPT tasks, Chrome scheduled | have (2026-09-05): found that NOTHING ever executed a saved schedule (the scheduler had no executor anywhere); NEW `core/schedule_executor.py` runs a fired task as `python -m thomas chat <goal>` with a log under `.thomas/schedule_logs/`, one shared `.thomas/schedules.json` for server and CLI; routes `/api/schedules` (list/add/pause/resume/run/remove); Settings > Autonomy "Scheduled tasks" card; verified live on :8977 (scheduler running, add -> next-run shown -> pause -> remove) | L2 end to end (2026-09-05 05:34 UTC: a one-minute schedule fired on time, ran a headless chat on the real model, answered, passed its checks, exit 0, log kept; `thomas cron list` reads the same data-dir file) | none; card shows each task's last run (ok/failed, seconds, time, error) from the run history the route always returned (2026-09-05) |
| A25 | Cloud/remote session handoff | Claude Code remote, Codex queue | partial: `tools/session_continuity.py` | L1 | n/a for local; leave |
| A26 | Agents dashboard (list/start/stop) | Codex agents dashboard, Cursor Agents Window | have: Mission Control; POST `/api/mission/jobs/{id}/cancel` registered | L2 | fixed 2026-09-05: the store's `cancel_job` said nothing when it touched no row (and wrote a cancelled audit for a job that never existed); it now raises and the route answers 404 |
| A27 | Doom-loop breaking (identical failing call) | LangChain LoopDetection; Claude Code | have (2026-09-05): `agent/tool_failure_guard.py` disables the exact call at the 3rd identical failure and tells the model; the run continues; abort only after 3 more hammering calls. Proven through the real AgentLoop (tests/test_tool_failure_guard.py) | L2 | none |
| A28 | Pre-completion verification / goal evaluator | Claude Code /goal, deep-agents rubric | have: acceptance contract + evaluator | L1 | none |
| A29 | Auto-update + doctor | all | have: updater, doctor | L1 | none |
| A30 | OS sandbox for shell + outbound network policy | Claude Code sandbox, Gemini seatbelt | have: check_outbound_url, sandbox_root | L1 | shell sandboxing is policy, not OS-level |
| A31 | Rate-limit banner + credential refresh progress | Codex Sep 2026 | have (2026-09-05): a countdown line under the composer when a model profile is parked after a 429 or server failures, folded from the runtime receipt (the skipped attempt and the model that answered instead), the error text, and GET /api/chat/cooldowns (`core/provider_cooldowns.py` over the client's registry) | L1 (node driver + route tests; a real 429 was not provoked) | credential refresh progress: not shown |
| A32 | Vim mode in composer | Codex | missing | L0 | low priority |
| A33 | Shell completion | Claude Code, Codex | have: `thomas completion` | L1 | none |
| A34 | Status line customization | Claude Code | partial | L0 | low priority |
| A35 | Keybindings customization | Claude Code | partial: `/help` in the palette lists every `/` command with its hint in a card above the composer (2026-09-05); a name prefix now outranks a label substring so `/he` + Enter runs help, not retry; the page itself has only Enter-to-send as a shortcut | L2 (card opened and closed on 8977) | keybinding customisation: none |
| A36 | Image paste / screenshots into chat | all | have: attachments | L1 | none |
| A37 | Voice input | Claude.ai, ChatGPT | have: composer "Voice input" | L2 | none |
| A38 | Web search + fetch with allowlists | all | have: web.search, eng.web_extract, allowlists | L1 | none |
| A39 | Shareable read-only thread snapshot | Codex thread snapshots, Claude share | have, local-first (2026-09-05): sidebar menu Save as web page to share -> `GET /api/chats/{id}/export?format=html`, one self-contained page (no scripts, no outside resources, every string escaped, light and dark) the person can send | L2 (served for a real chat on 8977) | a hosted link is not offered; the file is the share |
| A40 | Artifacts / canvas / live preview | Claude artifacts, ChatGPT canvas | have: canvas, live preview | L1 | none |
| A41 | Design mode (annotate UI visually) | Cursor 3 Design Mode | have: UI Edit Mode + source annotation panel | L1 | none |
| A42 | Multi-repo parallel | Cursor 3 | partial: multi_workspace | L0 | low priority |
| A43 | Plugin marketplace | Claude Code plugins, Cursor | have: extensions/ + Agent Plugins | L1 | none |
| A44 | Structured ask-the-user question (options, multi-select) | Claude Code AskUserQuestion, ChatGPT clarifying | partial (2026-09-05): `tools/ask_user.py` + `core/user_questions.py` (moved from agent/ 2026-09-05: tools may not import thomas.agent) + routes `/api/chat/questions` + panel `js/ask_user_panel.js` (chips above the composer, polls, answers); 11 tests incl. HTTP; panel verified live on :8977. NOT yet reachable from a Chat turn: the reasoning specialist's read-only allowlist (`marketplace/specialists/reasoning.py`, codex's file) must include `ask_user`; asked codex 04:5xZ. CLI prompt: `cli/ask_user_console.py` prints the options on a terminal and answers from a typed number or free text, started by `thomas.cli.headless_run` (2026-09-05, 3 tests incl. a thread answering a real waiter) | L2 (panel) / L1 (tool, console); session-scoped 13:4xZ: the runner binds the chat (`core/session_scope.py`), the tool ignores a model-supplied id, the panel polls for the open chat only, an answer from another chat is 403, a cancelled run forgets its question | codex allowlist line; then a live chips-to-answer turn |
| A45 | Todo / task list widget | Claude Code TodoWrite | have (2026-09-05): `todo.write` tool (core book, one list per chat, one item in progress), GET /api/chat/todos?session_id=, card above the composer with the plan and progress (`todo_panel.js`) | L1 (7 route/tool tests + live panel wiring; a model-driven checklist waits on the specialist allowlist codex is wiring) | codex: allowlist + bind_session in the runner |
| A46 | Docs lookup (Context7-like) | Claude Code Context7 MCP | missing | L0 | wrap through MCP bridge |
| A47 | LSP integration | Claude Code LSP | partial: code.find_definition | L1 | none |
| A48 | Notebook editing | Claude Code | partial | L0 | low |
| A49 | Code review / security review | Claude Code /code-review, /security-review | have: self_review | L1 | none |
| A50 | Push notification to phone | Claude Code PushNotification | missing in practice: `notifications/api.py` defines FastAPI routes (subscribe, public key, stream) but the server is aiohttp and nothing registers them; finished code with no caller (2026-09-05) | L2 (live probe) | port the routes to aiohttp and register them, then a real subscription |
| A51 | Remote control from phone | Claude Code Remote Control | missing | L0 | n/a for now |
| A52 | Telemetry / OTel | Claude Code | partial | L0 | low |
| A53 | Tool accepts absolute paths inside the sandbox | every frontier agent | have (2026-09-05): any tool's absolute path is accepted when it resolves under the sandbox root, refused with the root named otherwise (`agent/loop_tool_paths.py`) | L2 | none |
| A54 | Tool errors name the real cause | every frontier agent | have (2026-09-05): refusals say "tool" for read tools, "write tool" only for writes | L2 | none |
| A55 | git tools outside a repo | Claude Code (bash) | have (2026-09-05): one refusal naming the folder and the alternatives, identical on retry so the guard recognises it | L2 | none |
| A56 | Lint tool works where `python` is not on PATH | n/a | have (2026-09-05): sys.executable, then a `ruff` binary, then a readable tool error; optional sandbox cwd (tests/test_eng_lint_tool.py) | L2 | lands with codex's engineering.py batch |

## B. Chat surface (buttons, options, message actions)

| # | Capability | Frontier reference | Thomas | Verified | Gap / action |
|---|---|---|---|---|---|
| B1 | Attach files | all | have "Add files" | L2 | none |
| B2 | Copy message | all | have | L2 | none |
| B3 | Edit and resend from here | Claude.ai, ChatGPT | have | L2 | none |
| B4 | `/` command palette in composer | Claude Code, Codex, ChatGPT | have (2026-09-05): `js/slash_palette.js` (self-contained, injected with the question panel): type `/` in the composer, arrow keys, Enter runs, Escape closes; nine commands (new, ask, model, tools, files, voice, settings, export, schedules) each resolved to a control that exists on the page at that moment, hidden otherwise. Verified live on :8977 (`/mo` -> Enter opened the model switcher); node test of the core | L2 | skills as commands once a skills API exists |
| B5 | `@` mention files / context | Claude Code, Cursor | partial: mention_context_panel.js | L1 | verify live |
| B6 | Regenerate reply | Claude.ai, ChatGPT | have (2026-09-05): palette command `/retry` drives the page's own Edit-and-resend on the last message (history forks there, text returns to the composer) and then Send | L2 (live on :8977: `/retry` + Enter -> truncate POST -> new chat POST -> fresh reply) | a per-message Regenerate button needs chat.html |
| B7 | Branch / fork a conversation | Claude.ai, ChatGPT | have (2026-09-05): sidebar menu Branch this chat, and a Branch from here button on every reply row that keeps the conversation up to that reply (`POST /api/chats/{id}/branch` with `upto`); the copy is named after the original and opened | L2 (whole-chat branch on 8977; per-reply button on 8977 at 15:3xZ wrote a 2-message copy named 'branch at 2' from the open chat) | Delete on real chats: codex fixed in their lane |
| B8 | Stop generation button | all | have (2026-09-05): Send doubles as Stop while a reply streams; for a delegated run the click reaches the session's cancel endpoint and, since codex's 16:21Z repair, the inner worker task itself is cancelled (their live run went cancelled 1 s after the click and stayed so through 128 s; late finalizers refused). Found missing at 14:47Z on 8977, fixed and proven by codex on 8898 | L2 (scoped proof: one delegated run on their QA server; not every subprocess kind) | - |
| B9 | Rename / pin / archive / delete chat | all | have: row menu in `js/sidebar_history.js` (rename, pin, archive, delete, show archived, and now Export); the open chat's row now carries `aria-current` (2026-09-05) | L2 | row buttons still expose no accessible name |
| B10 | Sort and filter chats | Claude.ai | have | L2 | none |
| B11 | Thumbs up/down feedback | ChatGPT, Claude.ai | have (2026-09-05): `js/message_feedback.js` adds Good/Bad reply buttons beside Copy on every Thomas reply (rows without the Edit button), posts to `/api/chat/feedback` (`routes/chat_feedback_routes.py`, JSONL under `.thomas/feedback.jsonl`, newest-first GET); a thumbs-down asks for an optional note; verified live on :8977 (POST 200, row stored, button pressed) | L2 | none: `self_review._recent_feedback` folds the window's ratings into the review corpus (2026-09-05) |
| B12 | Keyboard shortcuts help | all | have: `browser_shell_keys.js` `bindings()` renders the honest table on the new-tab page (Ctrl+1..9, Ctrl+L/Alt+D, Ctrl+Tab, Ctrl+T/W, Alt+arrows, F5) | L1 | none |
| B13 | Theme / dark mode / font size | all | have (settings) | L1 | none |
| B14 | Output styles / personas | Claude Code output styles | missing | L0 | low |
| B15 | Quick question side chat | Claude Code "Ask" | have | L2 | none |
| B16 | Tabs like a browser (Chat/Build/Work) | Claude desktop tabs | have | L2 | none |
| B17 | Bookmarks + omnibox | Atlas | have | L2 | none |

## C. Data, sharing, export

| # | Capability | Frontier reference | Thomas | Verified | Gap / action |
|---|---|---|---|---|---|
| C1 | Projects with knowledge files | Claude Projects, ChatGPT Projects | partial: local_projects | L1 | verify UI |
| C2 | Connectors (Gmail, Drive, Calendar, Slack) | Claude.ai, ChatGPT | have: work_google_connector, slack | L1 | verify auth flow |
| C3 | Deep research | all | have: `thomas research`, library | L1 | UI entry point: verify |
| C4 | Real-time voice | ChatGPT voice | have: `/realtime` page + `/api/realtime/ws` websocket + upload, registered from app_core (`marketplace/realtime/routes.py`) | L1 (routes registered; a voice session not exercised) | exercise a session |
| C5 | File upload parsing (PDF/DOCX/images) | all | have (codex fixing PDF paths tonight) | L1 | none |
| C6 | Image generation | ChatGPT | have: image.generate | L1 | none |
| C7 | Export a conversation (Markdown/JSON) | ChatGPT, Claude.ai data export | have (2026-09-05): GET `/api/chats/{id}/export?format=md` or `format=json` (`routes/chat_export_routes.py`, hex-id only, attachment) + sidebar row menu "Export as Markdown" (`js/sidebar_history.js`); verified live on :8977 against a real session | L2 | none |
| C8 | Public share link | all | missing | L0 | after C7 |
| C9 | Comments on artifacts with agent replies | Claude artifacts | missing | L0 | low |
| C10 | Mobile / PWA | all | have: companion.webmanifest | L1 | none |

## D. Computer use and browser

| # | Capability | Frontier reference | Thomas | Verified | Gap / action |
|---|---|---|---|---|---|
| D1 | Desktop screenshot/click/type | Claude computer use, Codex computer use | partial: Desktop Operator (VM-first, allowlisted workflows); `thomas desktop-operator status` on 2026-09-05: VM `Bobs_Chromebook-desktop-vm` (Hyper-V) configured, service not running, no active session | L2 (status probe) | bring the helper service up and run one allowlisted workflow |
| D2 | Per-app access grants with tiers (read/click/full) | Claude desktop computer use | missing | L0 | build on top of Desktop Operator profiles |
| D3 | Teach mode (record a demo) | Claude computer use teach | missing | L0 | later |
| D4 | Clipboard read/write | Claude computer use | missing (2026-09-05 grep: no clipboard tool under thomas/tools, thomas/desktop_operator or thomas/core; the earlier "partial" was unfounded) | L1 (searched) | build a clipboard tool behind the sensitive-site pause |
| D5 | Isolated desktop VM | Codex cloud sandbox | have: Hyper-V VM settings | L1 | none |
| D6 | Browser sidebar that sees the page | Claude in Chrome | have: "Side panel - what's relevant to this page" | L2 | none |
| D7 | Agentic browsing (click/type/forms) | Claude in Chrome, Atlas | have: browser.* tools via Playwright | L1 | none |
| D8 | Multi-tab workflows / tab groups | Claude in Chrome | partial: every browser tool takes a `session` name (isolated cookies, its own page), so the agent can work several pages side by side; the shell's visible tabs are not the agent's sessions | L1 | tie agent sessions to visible tabs |
| D9 | Console / network / DOM reading | Claude in Chrome, Claude Code browser pane | have (2026-09-05): `browser.console` (log/warn/error + uncaught page errors, errors_only) and `browser.network` (method/url/status + failed requests, failures_only, url_contains) in `tools/browser.py`; listeners attach when a page is created, 200-entry ring per session; 4 tests with a fake page. DOM reading: `browser.extract` already | L2 (live Playwright smoke 04:42Z: console.log, console.error, the browser's resource error, an uncaught page error and a 404 all captured) | none |
| D10 | Scheduled browser tasks | Claude in Chrome | have (2026-09-05): a scheduled task runs as a headless chat, and the CLI registry now carries the browser tools and their parity layer (`thomas/cli/cli_browser_tools.py`); before, a headless run asked to open a page tried the shell twice and fell back to the web extractor | L2 (headless --json run: one `browser.open` call, reply Example Domain) | - |
| D11 | Site allow/block lists; pause on sensitive sites | Claude in Chrome, Atlas | have (2026-09-05): allow/block host lists in thomas.toml already gated fetch and browser.open; NEW `tools/site_policy.py` pauses browser.click/type on banks, payment, government and health hosts plus the user's own list; Settings > Tools "Sensitive sites" mode + hosts, saved on change, PATCH verified live on :8977 and read back after reload | L2 | allow/block lists still have no settings UI (toml only) |
| D12 | Screen recording / GIF | Claude in Chrome | missing | L0 | low |
| D13 | Dev-server preview pane | Claude Code browser pane | have: canvas live preview | L1 | none |
| D14 | Credential fill via password manager (agent never sees values) | Claude in Chrome | missing | L0 | later |

## D2. Found while working (not frontier rows, but they block parity work)

| # | Finding | Evidence | Action |
|---|---|---|---|
| X1 | The board's claim writer loses an `os.replace` race whenever another process holds WORKBOARD.md open with delete sharing | 13 WinError 5 failures on 2026-09-05, each leaving a 1.3 MB temp copy; rename-away and in-place writes succeed | fixed 2026-09-05: `claim_utils._atomic_write` retries, then writes in place; 2 tests |
| X2 | Presence never retires dead sessions | ~170 sessions "active" with heartbeats up to 114,576 minutes old; the newest codex heartbeat was 95 min old while their hold stood | a sweep that marks a session inactive after N missed heartbeats |
| X4 | Mission job actions said "ok" for jobs that do not exist | POST cancel / run-now / retry / pause on an unknown id answered ok:true live on 2026-09-05; the store's updates ignored a zero row count and cancel even wrote an audit entry | fixed 2026-09-05: both store methods raise KeyError, the routes answer 404; 3 tests |
| X5 | Push-notification routes are dead code | `thomas/notifications/api.py` is FastAPI inside an aiohttp server; nothing registers it; all three routes 404 live | port to aiohttp and register, then a real subscription |
| X6 | The Build preview could not run a project that imports from node_modules | Calvin's Minecraft game: the preview origin 404'd three.module.js, the script never ran, ENTER WORLD did nothing; three 'fix' runs, one crashed on Thomas's own RAG index inside the project, one claimed a fix without a file change, one passed a smoke that pressed the button without checking the outcome | web-asset files under node_modules are served (no dotfiles, no source, boundary suite green); the smoke and the report/turn reconciliation are codex's files, reported |
| X3 | The scheduler had no executor anywhere | grep: no `execute_fn=` outside scheduler.py; `thomas cron add` saved tasks that could never run | fixed 2026-09-05 (`core/schedule_executor.py`) |

## E. Integrations and channels

| # | Capability | Frontier | Thomas | Verified | Gap |
|---|---|---|---|---|---|
| E1 | Telegram / Discord | ChatGPT, Claude | have | L1 | none |
| E2 | Slack app | Claude Slack | partial | L1 | verify |
| E3 | GitHub app (@mention in PRs) | Claude Code GitHub | missing | L0 | later |
| E4 | Email agent | ChatGPT Work | have: email.* | L1 | none |
| E5 | Calendar agent | ChatGPT Work | have: calendar.* | L1 | none |
| E6 | Database tools | Cursor, Codex MCP | have: db.*, nl_to_sql | L1 | none |
| E7 | SSH / remote exec | Codex | have: ssh.exec | L1 | none |
| E8 | Deploy / rollback | Vercel, Codex | have | L1 | none |
| E9 | Self-extend (create tools/skills at runtime) | Claude Code skill-creator | have | L1 | none |

## Build queue: what happened on 2026-09-05 (03:45-05:56 UTC)

Done in the working tree, each test-driven, ruff-clean and exercised live on a second server (:8977), never on the
owner's :8899:

1. **Tool layer** (A27, A53-A56): absolute paths inside the sandbox accepted for every tool; read-tool refusals named
   honestly; git tools refuse once outside a repo; the third identical failure disables that call instead of killing
   the run (abort only after three more hammering calls); eng.lint uses the running interpreter.
2. **Sensitive sites** (D11): browser.click/type pause on banking, payment, government and health hosts plus the
   user's own list; Settings > Tools card, saved on change.
3. **Ask the user** (A44): `ask_user` tool, question book, routes, panel with chips above the composer. Not yet visible
   to a Chat turn until the reasoning specialist's read-only allowlist (codex's file) includes it.
4. **Export a chat** (C7): route + sidebar menu item.
5. **Browser console and network** (D9): `browser.console`, `browser.network`; Playwright smoke captured all five
   kinds of event.
6. **Transcript pruning** (A13): stale tool outputs shrink to a stub at a third of the window, no model call; run 3's
   cost profile was the evidence.
7. **Scheduled tasks** (A24): a page, routes, and the executor the scheduler never had; server and CLI share one
   file.
8. **Slash palette** (B4): `/` in the composer lists nine commands that resolve to controls present on the page,
   including `/retry`, which regenerates the last reply through the page's own edit-and-resend (B6).
9. **Reply feedback** (B11): Good/Bad reply buttons on every Thomas reply, stored as JSON lines, read by the
   self-review report.
10. **Landing repairs**: the board's claim writer no longer loses the rename race (X1, fixed in `claim_utils`);
    app_core, settings and browser changes were restructured into new modules so the size guard passes.
11. **Headless chat has the sign-in** (A22): plain `thomas chat` failed in every shell on the ChatGPT sign-in; the CLI
    entry now registers the resolver before chat, repl and agent, and the scheduler's executor runs through it. Proven
    by a real scheduled firing that answered on the model and exited 0.
12. **Pull requests from a task** (A23): `git.pull_request` through the installed GitHub CLI; pushes only when asked.
13. **Ask-the-user on the terminal** (A44): a console answerer prints the options and reads the answer for headless
    and terminal runs; the question book now resolves answers safely from another thread.
14. **Mission actions stop lying** (X4): cancel, run-now, retry and pause on an unknown job answer 404 instead of ok.
15. **Live cost readout** (A18): every reply's token receipt and an estimated dollar figure, per reply and per chat,
    under the composer; the receipt was already in every `done` event, unread.
16. **Fast mode has a control** (A17): a pill under the composer for this browser, a Reply speed setting for the
    default, and `/fast`; the server honoured both for months with nothing able to set them.
17. **A visible checklist** (A45): `todo.write` keeps one list per chat and the page draws it above the composer.
18. **Questions and checklists stay with their chat**: the runner binds the session in core, the tools ignore a
    model-supplied id, an answer from another chat is refused, a cancelled run forgets its question (codex's finding).
19. **Branch this chat** (B7) from the sidebar menu; the export route accepts the real session ids the sidebar carries
    (the first version answered 400 on every real chat).
20. **A resting model says so** (A31): a countdown under the composer from the receipt, the error text, or the cooldown route.
21. **Headless JSON output** (A22): one JSON line with the reply, outcome, model, tokens and verification.
22. **Praxis**: the plans gate blocks only on the committer's task and demands a plan update only from a commit inside
    that task's scope; the scheduler releases its lock on app cleanup; panels back off while the server is away;
    injected modules are cache-stamped from their own bytes.
23. **`/help`** lists every command; a typed name prefix outranks a label match.
24. **Branch from here** on every reply row; **Save as web page to share** (A39) as a script-free HTML file.
25. **Headless runs have the browser tools** (D10): a scheduled task can drive a page; the JSON line carries
    the tool log, checks and counts (A22).
26. **Each scheduled task shows its last run** (A24): ok or failed, seconds, time, error.

Landing status: LANDED as 20e72ed4 (13:14 UTC), 02ddb47d (13:59 UTC) and 1c9abea6 (15:13 UTC) on 2026-09-05 through commit.py plumbing and 4ba3469b (16:46 UTC, items 23-26), after the plans gate learned to block only on the committer's task. Before that, sixteen lanes and two lie fixes were in the working tree with the touched and neighbouring
suites green and the monolith and exception gates passing on the staged set, but the commit is held by the plans gate, which needs the board and every plan file
codex touched to land together (their repo-truth batch, or one owner tap). Details in the session's landing notes.

Corrections to this document's own first draft: A4 was not inverted (it is the internet-reach row); B9's rename,
pin, archive and delete already existed behind the row menu.

Still open, in priority order: `/` palette (B4), regenerate and branch (B6, B7), feedback (B11), CLI prompt for
ask_user, per-app computer-use grants (D2), live diff panel (A19), the cache-miss half of A18. B6, B7 live in
chat.html and chat_turn_flow.js, which sit in codex's claim tonight.

Praxis proposal for the owner (2026-09-05): every landing today needed codex to release `CHANGELOG.md` from their claim
for the seconds of one commit (13:11, 13:57, 15:08 UTC), because the changelog gate wants the file staged and the
claim system gives it to one agent. Changelog fragments would end that: each commit adds `changelog.d/<agent>-<slug>.md`,
the gate accepts a staged fragment, and the release step folds fragments into `CHANGELOG.md`. The gate script is
protected, so this is a tap, not an engineering call.

Rows marked "verify" are honest unknowns: a keyword in the tree is not a feature. They get promoted to L2 only when exercised.

## Batch 6 and 7 (2026-09-05, from the Mario Kart drive)

27. **A Build runs until the task is done, not until a pass ends.** The loop's acceptance settlement reaches the engine (`translator.acceptance`), unmet items go back as CONTINUE passes under the 20-pass guard, and a spent budget is "unfinished after N passes" with the gaps named. Landed 63ee48f6.
28. **Feature lists are requirements.** "It needs A (x, y), B, and C" becomes one judged item per feature; cap 24. Landed 63ee48f6.
29. **A Build declares its verification depth.** `verification_effort` on the loop, floored at xhigh so judged requirements get the separate judge while the worker stays at its own effort; codex's `effort_level` hook honours it. Landed 63ee48f6 (dispatcher) + codex's tree.
30. **The offline smoke names what it blocked.** A Google Fonts `@import` no longer reads as a broken local stylesheet. Landed 63ee48f6.
31. **Thomas can play what he writes.** `web.playtest`: scripted headless browser session against the project, one allowlist shared with the smoke, per-step text/errors/canvas paint, screenshots. In tree.

Frontier comparison for 31: Codex CLI and Claude Code rely on a separate browser MCP the user must install and grant; Thomas ships the capability in the Build toolset, offline, with the same file boundary as its verifier. Gap that remains: the separate judge does not yet play the game itself; it reads the worker's playtest receipts.
32. **The patch tools read the grammar the model writes.** 35 of 88 `diff.apply_patch`/`preview_patch` calls in one day were rejected for lacking `---/+++` headers because the GPT worker writes the Codex `*** Begin Patch` envelope; it is now converted in front of both tools (anchored placement, file's own text, honest refusal by hunk). In tree.
33. **The judge can play the page.** One playtest per judge call, same grammar as the worker's tool, result fed back before the verdict. In tree.
34. **A pass wall clock is a pass boundary.** Files changed at the clock are verified and the run continues; only a clock with nothing changed fails. Generation 4 of the Mario Kart drive was filed as a crash by the old rule with a working race on disk. In tree.
35. **The judge reads what the browser said.** The worker's recorded `web.playtest` sessions are quoted to the judge verbatim as evidence, the judge is told the real shell (cmd.exe on Windows), and a playtest is mandatory for an item about what a page does. Generation 6: fourteen worker playtests, judge asked for PowerShell twice and ruled nothing. In tree.
36. **The contract hears instructions, not narration.** Imperative sentences are requirements; the user's account of what they did or saw is not; "do not" counts only when it opens an instruction. Generations 5 and 6 were sent back over the user's own sentences; a condition clause lends no words; a want that introduces a list with a colon is one requirement per entry (the Minecraft steer: nine). In tree.
37. **The edit tools read the text the model meant.** `diff.create`/`diff.preview` keep a file's line endings (they flipped CRLF/LF per edit by platform) and forgive trailing whitespace with a note; `diff.apply_patch` treats `hunks: []` as no restriction. Fifteen plus eight wasted rounds in one day. In tree.
38. **Goals are standing requirements.** `goal.add`/`goal.list`/`goal.done` in Build and Chat; every open goal enters the acceptance contract on every turn as a judged item until closed with evidence (`thomas/core/goal_book.py`). Codex CLI and Claude Code carry goals only as prose in a memory file; Thomas's judge holds work to them. In tree.
39. **The judge may search for the words it may not run, reads the full saved playtest, and sees the goals file.** Generation 9: the judge's source scan for "never loads from the internet" was denied for naming curl and wget, it called the worker's recorded race "truncated" (the loop's tool preview stops at 2000 characters), its own playtest failed on the chord "w+ArrowUp", and nothing showed it whether the goals still stood. The gate now denies by command head, every `web.playtest` session saves `report.txt` and the judge quotes those in full, chords hold every key, a goal item brings `.thomas/goals.json`, and the Build record's acceptance line names each judge check and its outcome. Proven live: with the detection removed by Thomas himself, the Minecraft build finished in one pass with every item checked and the judge's own playtest run. In tree.
40. **A page cannot hide from the verifier.** The Minecraft build detected automated browsers (navigator.webdriver, Headless/Playwright/Puppeteer) and never started its renderer under one: a HUD over a void for every check, a world for a person. The contract now carries a machine item (`honest_page`) that fails while any changed web source detects automation; `web.playtest` presents as a person's browser and photographs WebGL canvases to say how much of them differs from a flat colour; a condition clause lends no words to the contract. No frontier harness checks its own page for automation detection. In tree.
41. **A Build on a plain folder still attributes its changes.** A folder opened without version history gets a content manifest (path, size, sha256; bounded, links and junctions not followed) as its pre-run snapshot, and the post-run delta comes from that same snapshot whether the run finished or was stopped; undo and run snapshots say plainly that there is no history. Codex CLI and Claude Code attribute changes only through git. In tree; route wiring is codex's.
42. **A build runs until the task is done, across passes, with the record in hand.** The Minecraft feature list (nine features in one request) ran across wall-clock passes: the clock is a boundary, a pass that only played counts as work, the continue prompt names the saved sessions so nothing is replayed, the judge rules per feature with a reason each, sees every saved session, may play after its shell checks, and sessions from the last day are never pruned from under the proof record. Finished with every item checked and satisfied and a proof page citing a saved on-screen session per feature. Codex CLI and Claude Code stop at a turn. In tree.
43. **Redesign changes what an element says.** A layout record carries `text` (one plain line, at most 120 characters); the planner offers it only for a target that shows words and refuses with a reason for one that does not; the layout runtime writes it into the element's own text runs, keeps the icon, and restores every stock run exactly when the record goes. Verified live: "Start a chat" survives a reload from the overlay (`thomas/server/overlay/records.py`, `thomas/server/routes/ui_redesign_runtime.py`, `thomas/server/web/js/ui_edit_layout.js`, `thomas/server/web/js/ui_redesign_select.js`).
44. **Redesign admits the part of an ask its locked target cannot carry.** "Hide this whole Workspaces section" on the heading hid the heading and said Changed 1 thing; the contract now requires the model to do what the locked target allows and list the target as unsupported with what remains and where to point next (`thomas/server/routes/ui_redesign_runtime.py`).
45. **Every sidebar click in Work opened the last job.** Work's job rows dropped the history preview into a static button, and the shared rule positioned it absolutely with inset 0, so 25 invisible full-sidebar spans stacked over the mode buttons, New chat and search. The absolute placement now belongs to the cross-fade box alone (`thomas/server/web/css/sidebar_history.css`).
46. **The Work onboarding fits the window it renders in.** The transcript's fixed 360px minimum beat its viewport-fitting maximum, so in a short window Thomas's reply and the workflow chooser sat below the panel's visible bottom; the chooser buttons had no rules at all (`thomas/server/web/css/unified_work_mode.css`, `thomas/server/web/css/unified_work_details.css`).
47. **A Work job can be created when its plan named a connector that is not installed.** The onboarding tool's connector field had no description, so the model invented "HTTP request" and "Mission Control inbox" and the store rightly refused the job. The field now says it holds installed connector ids and is usually empty, and the parser keeps only installed ids (`thomas/core/work_onboarding_tool.py`, `thomas/server/work_onboarding_state.py`).
48. **The run report's rubric reads the acceptance contract.** "Acceptance contract met: every item checked and satisfied" sat one line above "your specific ask was not separately verified": the report was built from forge events and none carried the settlement. The dispatcher records it as an `acceptance` event and the rubric builds one row per requirement from it: met, not met, or unverified, with the judge's detail as evidence (`thomas/forge/anvil/dispatch_agent_loop.py`, `thomas/forge/anvil/run_report.py`).
49. **The thumbs-down under every reply was the digit 2.** Two icon-map entries written through a shell heredoc had their backslash escapes read as octal control bytes; both are real glyphs again and a test refuses any control character in the map (`thomas/server/web/css/chat_shell.css`).
50. **A run that cannot run commands is not told to run one.** An edit-only Build run on Thomas's own checkout has no shell, and the rules of the road still required `python scripts/forge/gates/monolith_guard.py` after code edits, so the run repeated for an hour that it was blocked. When the toolset has no shell and code was written, the loop runs the guard itself and hands the check a receipt that is judged, not trusted; a run with a shell must still run it. (2026-09-06, `thomas/agent/harness_guard.py`, `thomas/core/rules_of_road.py`, `thomas/agent/loop_completion.py`)
51. **The offline browser smoke only runs on pages it could ever load.** Thomas's own chat shell was smoked from disk under the fake smoke host, its `/static/` modules denied, and the run spent three hours adding smoke-mode branches to the product. A page whose root-absolute asset links resolve nowhere under the project root is a served page and is left out of the smoke on every path in; the live-server playtest stays its check. (2026-09-06, `thomas/tools/web_preflight.py`)
52. **The server log keeps its records when another process holds the file.** Two servers on one data dir share thomas.log; at the cap every rotation failed on Windows, the standard handler printed a traceback per line and dropped the record, and a handler's real 500 never reached the file. The shared handler writes the record anyway, notes the skipped rotation once, and retries a minute later. (2026-09-06, `thomas/server/log_handlers.py`)
53. **A loop pass no longer waits ~30 s for its verdict.** The acceptance contract's source walk did not know `runtime/` existed and walked its 566,161 files twice per pass. The walk prunes runtime, data and dependency trees and carries a three-second budget. (2026-09-06, `thomas/core/acceptance_contract.py`)
54. **A user in chat makes Thomas change himself.** The Activity chip's placement (inside the chat surface, none in the browser bar) and the refresh-icon context menu were asked for through the chat's own Redesign flow: point, type the owner's words, Apply; the card reports what the overlay cannot do and sends the rest to a Build run on Thomas's own checkout. Two structural findings on the way: the Build-tab composer silently queues and loses sends while any other conversation's run is live, and self-edits go live on the owner's server the moment they are written (the isolation work now in flight). (2026-09-06)
55. **A run cannot write into a fenced file.** A self-edit run told in prose to leave another agent's files alone edited two of them and collided with that agent's repair. The loop's write tools now refuse any path in the run's `protected_paths` with a sentence that names the fence; the file stays untouched. A patch's own headers are read too, so a unified or codex patch cannot slip a fenced file past the path check. (2026-09-06, `thomas/agent/loop_tool_paths.py`)
56. **A self-edit run is fenced by the board's claims.** Every scope another agent holds on the workboard is computed into the Redesign's brief and conversation record as `protected_paths`, which the loop's write tools refuse; only the server's own environment can exempt an agent. (2026-09-07, `thomas/server/routes/ui_redesign_runtime.py`, `thomas/server/routes/work_dashboard_runtime.py`)
57. **Both dispatch paths carry the fence.** The loop dispatcher forwards `protected_paths` into every pass; the Claude CLI dispatcher turns it into permission deny rules in a settings file, so a fenced write is refused by the CLI itself. (2026-09-07, `thomas/forge/anvil/dispatch_claude_cli.py`)
58. **Settings' Export logs button has something to call.** The settings page had probed `/api/logs/export` since its script was split and greyed the button on the 404; the route now exists (HEAD for availability, GET for a zip of the server and chat logs, a note when empty), so the probe stops logging a console error and the overlay truth-tests see a clean console. (2026-09-07, `thomas/server/routes/logs_export_routes.py`)
59. **The board tools import two modules that were never committed.** `9510a13e` landed the session-bound coordination path but not `thomas/core/agent_session_identity.py` or `thomas/core/agent_presence_sessions.py`; a clean checkout failed with an ImportError on every board command while every working tree that had the files kept passing. Both are tracked now, bytes as written on 2026-09-02. The same scan found two more in codex's claim, `thomas/server/chat_delegation_tool_receipts.py` and `thomas/server/work_execution_adapter.py`, imported by committed files; reported to codex. (2026-09-07, `thomas/core/agent_session_identity.py`)
60. **The Windows authorization prompt never appeared.** `WindowsAuthGate` passed its message text where pywin32 wants the `CREDUI_INFO` dict, so every native authorization died with a `TypeError` before a dialog opened, and the gate's except clause let it escape. The prompt receives the dict now and a prompt that cannot be shown is a denial, not a crash. (2026-09-07, `thomas/tools/windows_auth.py`, `tests/test_the_windows_prompt_passes_pywin32_a_dict.py`)
61. **An isolated self-edit cannot write in its own candidate copy — open.** The candidate under `~/.thomas/self-edit-candidates/` becomes the run's project root, and `_runtime_protection_roots` treats any project root as Thomas's live runtime, so every write under `thomas/server/**` in the copy was refused (run fc_20260907T053138_2b7f40, sent through the Chat tab's Redesign). The guarded step is Apply, which `source_application_gate` already covers; the exemption belongs in `thomas/tools/filesystem.py` (codex) or at candidate preparation (codex-image-takeover); reported to both with the rule and the test to write. (2026-09-07)
62. **The Redesign panel polls a self-edit route that does not exist — open.** `ui_redesign_select.js` fetches `/api/evolve/agent/conversations/{cid}/self-edit/status` and `/demo`; the server registers `/api/evolve/agent/self-edit/{cid}/status` and `/demo`, so the panel says "the private run could not be reached" while the run is live. The file is codex's; reported with the 404 evidence. (2026-09-07)
63. **A directory preview refuses a page that only a server can render.** The self-edit demo served the candidate's `chat.html` through the static preview; the console showed eleven 404 script loads and a `ThomasChatThemes` TypeError, a blank shell offered as "Demo ready". The preview service now refuses a page whose root-absolute links resolve nowhere in the tree, before any origin starts, with the link in the reason. (2026-09-07, `thomas/server/routes/deliverable_aiohttp.py`, `tests/test_a_preview_refuses_a_served_page.py`)
64. **A receipt says when the model server reported no usage.** A local model through the OpenAI-compatible path produced `This reply 0 in · 0 out · ~$0.0000` on every turn: usage was never requested, and its absence was normalized to zeros and priced. Streaming requests now ask for usage (`stream_options.include_usage`, Azure excepted), the done event carries `usage_reported`, and the readout says `usage not reported by <provider>` when it is false. (2026-09-07, `thomas/core/llm_client.py`, `thomas/server/routes/chat_v2_usage.py`, `thomas/server/web/js/cost_readout.js`)
65. **A tool call the model writes as text is heard as a tool call.** A local model behind the OpenAI-compatible path answered chat turns with the whole call written into its content, and the JSON was shown as the answer. The stream client now holds content that opens like JSON while tools were offered and, when the finished content is one call to an offered tool, emits real tool-call events; everything downstream is unchanged. Verified live on :8977: the model's text-written `remember` calls ran, repeated three times with identical arguments, and the specialist's repeat guard stopped the turn with an honest sentence. (2026-09-07, `thomas/core/llm_shared.py`, `thomas/core/llm_streaming.py`, `tests/test_a_tool_call_written_as_text_is_heard.py`)
66. **A model served from this machine costs nothing, and the receipt says so.** The local profile was priced at the cloud defaults on every reply because its provider is `openai_compat`; the cost tracker now publishes a zero row flagged `local` for every configured model whose base URL is loopback or private, unless `[pricing]` names it, and the receipt reads `local, no charge`. Verified live: `/api/spend/pricing` on :8977 carries the row. (2026-09-07, `thomas/core/cost_tracker.py`, `thomas/server/web/js/cost_readout.js`, `tests/test_a_local_model_costs_nothing.py`)
67. **A finished build was filed as failed by the stall watchdog — open.** A chat-dispatched Build (exec-a242850cf926, provider-native worker) wrote a complete, working countdown page at 01:40:48 and was recorded `failed / provider_native_timeout / artifact unverified` at 01:43:45: the idle window is 120 s plus 15 s grace, widened only for worker `effort` max or exhaustive, while this run's `reasoning_effort` was xhigh and a silent reasoning turn outlasts it with no heartbeat. Reported to codex with the fix (key the window on reasoning_effort, or heartbeat during an open model call). (2026-09-07, `thomas/server/chat_delegation_supervisor.py`, `thomas/server/chat_delegation_runner_events.py`)
68. **A commit cannot import a module it does not track.** The class behind row 59 now has an instrument: `scripts/forge/gates/untracked_import_gate.py` refuses a staged Python file whose import resolves to an untracked file, and `--all` scans every tracked file (run tonight it names the four plus their importers). Registration in `.pre-commit-config.yaml` and `enforcement_manifest.json` is protected and waits for the owner's tap. (2026-09-07, `scripts/forge/gates/untracked_import_gate.py`, `tests/test_a_commit_cannot_import_what_it_does_not_track.py`)
