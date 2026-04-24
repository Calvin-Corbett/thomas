# Thomas

Thomas is a local-first AI workspace for chat, tools, memory, automation, and
guarded agent work. The first public path is simple: install the Windows app,
finish Easy Setup, then use the browser workspace at `http://127.0.0.1:8899`.

Thomas is intentionally not a hosted SaaS product by default. It starts on your
own machine, keeps the default web server bound to loopback, and requires you to
opt into integrations, remote access, or advanced builder workflows.

## Download for Windows

[Download `ThomasSetup_0.14.60.exe`](https://github.com/Calvin-Corbett/thomas/releases/download/v0.14.60/ThomasSetup_0.14.60.exe)

## Quick Start on Windows

Fresh install: download the Windows installer above.

1. Download `ThomasSetup_0.14.60.exe`.
2. Double-click it.
3. Click through the installer prompts.
4. Leave **Finish setup and launch Thomas now** checked.
5. Wait for the first-run setup window to finish.
6. Complete Easy Setup after the browser opens.

If setup breaks, run `support.cmd` and attach the ZIP it creates under
`runtime\support\` to the GitHub issue. The bundle includes
`runtime\logs\first_run_wizard.log` when that log exists. For quick self-repair,
run `repair.cmd`. For a manual setup pass, run `setup.cmd`. For startup
diagnostics, run `bootdoctor.cmd`.

Thomas is local-only by default. If Windows Firewall prompts you, this is the
local Python web server starting on `127.0.0.1`; see
[`docs/NETWORKING_AND_FIREWALL.md`](docs/NETWORKING_AND_FIREWALL.md).

## What Thomas Does

- Local chat workspace with model/provider setup, message history, progress
  updates, and tool/result display.
- Guarded tool execution for filesystem, shell, git, browser, search, diff, and
  domain modules.
- Memory and retrieval surfaces for thread context, global facts, and local
  research/library workflows.
- Mission Control for jobs, objectives, approvals, live activity, and supervised
  automation.
- Evolve mode for guarded self-improvement sessions and promotion workflows.
- Companion platform scaffolding for future private mobile app workflows.
- Installer, repair, support bundle, and GitHub release gates for public builds.

For a fuller status map, read
[`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md) and
[`docs/FUNCTIONALITY_INVENTORY.md`](docs/FUNCTIONALITY_INVENTORY.md).

## What to Expect

- First launch creates a local Python virtual environment in `.venv`.
- Thomas runs on your own machine by default.
- The default web UI address is `http://127.0.0.1:8899`, not a public IP.
- Model/provider setup happens in Easy Setup after the web UI opens.
- If Codex, Ollama, or API keys are not ready yet, Thomas should still start and
  show setup guidance.

## Everyday Use

Use Thomas first as a local chat workspace. Start the app from the desktop
shortcut or `run-ui.cmd`, open the browser UI, and use Easy Setup to connect the
model path you want to use. You can add memory, tools, automation, and
integrations after the basic chat path is working.

## Grow Into Advanced Thomas Safely

Thomas includes builder and automation surfaces, but you do not need them for
first use. Keep the default local/protected posture until you understand what a
tool or integration will do, and use `bootdoctor.cmd` or `repair.cmd` when setup
state looks wrong.

## For Agents and Contributors

If you are an AI agent, reviewer, or contributor, start here:

- [`docs/AGENT_START_HERE.md`](docs/AGENT_START_HERE.md) - fastest safe route
  through the repo
- [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md) - public capability matrix
  with status, audience, entry points, and evidence
- [`docs/REPO_MAP.md`](docs/REPO_MAP.md) - what each top-level area is for
- [`docs/ARCHITECTURE_OVERVIEW.md`](docs/ARCHITECTURE_OVERVIEW.md) - install,
  runtime, and companion architecture diagrams
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - near-term launch work, Infinite app,
  and Thomas OS concept notes

Do not assume every module is production-ready because a file exists. The status
labels in the feature matrix are the public source of truth.

## What Ships in This Repo

- `thomas/` - core runtime, memory, tools, server, policy, autonomy, companion,
  marketplace, and web UI
- `apps/` - companion/client surfaces and app experiments that are part of the
  public codebase
- `installer/` - Windows installer assets
- `scripts/` - automation, quality, packaging, release, and maintenance helpers
- `tests/` - regression, release, installer, policy, and surface checks
- `.github/` - GitHub Actions, issue templates, PR template, and agent guidance

## Documentation

- [`DOCUMENTATION_INDEX.md`](DOCUMENTATION_INDEX.md) - stable docs hub for the
  public release
- [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md) - user-facing,
  backend, agent-facing, and planned capability status
- [`docs/FUNCTIONALITY_INVENTORY.md`](docs/FUNCTIONALITY_INVENTORY.md) -
  capability list with readiness notes
- [`docs/NETWORKING_AND_FIREWALL.md`](docs/NETWORKING_AND_FIREWALL.md) -
  local-first networking and firewall guidance
- [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) - chat and
  execution flow
- [`docs/WINDOWS_INSTALLER_GUIDE.md`](docs/WINDOWS_INSTALLER_GUIDE.md) -
  Windows installer build and packaging
- [`SECURITY.md`](SECURITY.md) - disclosure policy and supported security
  posture
- [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) - current rough edges and active
  limitations

## Development Notes

This is an early public product release. Normal use does not require
understanding the internal automation and contributor infrastructure.

If you are changing code, start with `docs/AGENT_START_HERE.md`, then move into
the README for the specific area you are touching.

## Production Checklist

Before exposing a deployment externally:

1. Copy `.env.thomas.production.example` to `.env.thomas.production`, or provide equivalent environment variables.
2. Set a strong `THOMAS_SERVER_API_TOKEN`.
3. Set `THOMAS_MUTATING_CSRF_TOKEN` if you want request-level protection for mutating `/api` and `/gateway` routes.
4. Start with `THOMAS_ENV=production`.
5. Verify `/api/health` before opening external traffic.
6. Configure log rotation with `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, and `THOMAS_LOG_BACKUP_COUNT`.
7. Keep `THOMAS_ALLOW_REMOTE_PRODUCTION=1` disabled unless the deployment is explicitly intended for remote access.
