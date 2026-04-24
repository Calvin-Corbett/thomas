# Thomas

Thomas is a local-first AI workspace for chat, tools, memory, and automation.

## Download for Windows

Normal users should download the installer, not the green **Code -> Download ZIP**
source archive.

[Download `ThomasSetup_0.14.59.exe`](https://github.com/Calvin-Corbett/thomas/releases/download/v0.14.59/ThomasSetup_0.14.59.exe)

## Quick Start on Windows

Recommended fresh install: use the Windows installer above or download it from
[`Releases`](https://github.com/Calvin-Corbett/thomas/releases).

1. Download `ThomasSetup_*.exe` from the latest GitHub release.
2. Double-click the installer.
3. Click through the installer prompts.
4. Leave **Finish setup and launch Thomas now** checked.
5. Wait for the first-run setup window to finish. It creates the local runtime and launches Thomas.
6. Complete Easy Setup in the app after the browser opens.

Developer/manual fallback: download the repo from GitHub with **Code -> Download ZIP**,
extract it, open the extracted `thomas` folder, and double-click `run-ui.cmd`.

If setup breaks, run `repair.cmd`. For installer first-run failures, send
`runtime\logs\first_run_wizard.log` with the issue report. For a manual setup
pass, run `setup.cmd`. For startup diagnostics, run `bootdoctor.cmd`.

Thomas is local-only by default. If Windows Firewall prompts you, this is the
local Python web server starting on `127.0.0.1`; see
[`docs/NETWORKING_AND_FIREWALL.md`](docs/NETWORKING_AND_FIREWALL.md).

## What to Expect

- First launch creates a local Python virtual environment in `.venv`.
- Thomas runs on your own machine by default.
- The default web UI address is `http://127.0.0.1:8899`, not a public IP.
- Model/provider setup happens in Easy Setup after the web UI opens.
- If Codex, Ollama, or API keys are not ready yet, Thomas should still start and show setup guidance.

## Everyday Use

Use Thomas first as a local chat workspace. Start the app with `run-ui.cmd`, open the browser UI, and use Easy Setup to connect the model path you want to use. You can add memory, tools, automation, and integrations after the basic chat path is working.

## Grow Into Advanced Thomas Safely

Thomas includes builder and automation surfaces, but you do not need them for first use. Keep the default local/protected posture until you understand what a tool or integration will do, and use `bootdoctor.cmd` or `repair.cmd` when setup state looks wrong.

## What Ships in This Repo

- `thomas/` - core runtime, memory, tools, server, and web UI
- `apps/` - companion clients and supporting app surfaces
- `installer/` - Windows installer assets
- `scripts/` - automation, quality, packaging, and maintenance helpers
- `tests/` - regression and release checks

## Functionality Status

The public capability map is in
[`docs/FUNCTIONALITY_INVENTORY.md`](docs/FUNCTIONALITY_INVENTORY.md). It
separates user-facing features, backend/runtime systems, marketplace/domain
modules, and removed private-release artifacts.

## Documentation

- `DOCUMENTATION_INDEX.md` - stable docs hub for the public release
- `docs/FUNCTIONALITY_INVENTORY.md` - capability list with readiness notes
- `docs/NETWORKING_AND_FIREWALL.md` - local-first networking and firewall guidance
- `docs/CHAT_EXECUTION_MODEL.md` - chat and execution flow
- `docs/WINDOWS_INSTALLER_GUIDE.md` - Windows installer build and packaging
- `docs/ops/DOCKER_DEPLOY.md` - container deployment
- `docs/ops/GATEWAY_SECURITY_RUNBOOK.md` - gateway hardening and incident response
- `docs/ops/RETRY_POLICY.md` - retry behavior and failure handling
- `SECURITY.md` - disclosure policy and supported security posture
- `KNOWN_ISSUES.md` - current rough edges and active limitations

## Development Notes

This is an early public product release. The repo includes contributor and automation infrastructure used to build Thomas, but normal use does not require understanding those internal workflows.

If you are changing code, start with `DOCUMENTATION_INDEX.md` and then move into the README for the specific area you are touching.

## Production Checklist

Before exposing a deployment externally:

1. Copy `.env.thomas.production.example` to `.env.thomas.production`, or provide equivalent environment variables.
2. Set a strong `THOMAS_SERVER_API_TOKEN`.
3. Set `THOMAS_MUTATING_CSRF_TOKEN` if you want request-level protection for mutating `/api` and `/gateway` routes.
4. Start with `THOMAS_ENV=production`.
5. Verify `/api/health` before opening external traffic.
6. Configure log rotation with `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`, and `THOMAS_LOG_BACKUP_COUNT`.
7. Keep `THOMAS_ALLOW_REMOTE_PRODUCTION=1` disabled unless the deployment is explicitly intended for remote access.
