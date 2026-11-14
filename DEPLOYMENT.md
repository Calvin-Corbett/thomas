# Thomas — Deployment Guide

## Quick Start

### Development (local)

```bash
# Clone and install
git clone https://github.com/Calvin-Corbett/thomas.git
cd thomas

# macOS / Linux: installs Thomas with the web server dependencies. It asks whether to
# create .venv (the default answer is yes); THOMAS_NO_VENV=1 skips the question and the .venv.
bash install.sh
source .venv/bin/activate   # skip this line if you declined the .venv

# Windows: run-ui.cmd installs what it needs and starts the UI in one step.
# For the install alone, run setup.cmd (or scripts/setup.ps1), then use .venv\Scripts\activate.

# Run the UI
python -m thomas serve
# Open http://127.0.0.1:8899
```

`install.sh` only installs; it offers to start the UI when it finishes. The server dependencies
are the `server` extra in `pyproject.toml`, so a bare `pip install .` is not enough to run
`thomas serve`. Use `pip install ".[server,repl]"`.

### Docker

```bash
docker compose up -d
```

This builds the image in production mode (`THOMAS_ENV=production`, which forces the overrides in
the table below) and runs it. The compose file sets `THOMAS_CONFIG` to the development
`thomas.toml` it mounts, so every other setting is a permissive development default. For the
locked-down template, run the image built by the Dockerfile without that override: it bakes in
`thomas.prod.toml` (see "Docker Builds").

---

## Environment Modes

Thomas supports two environments controlled by the `THOMAS_ENV` variable:

| Setting | `development` (default) | `production` |
|---------|------------------------|--------------|
| Shell access | Configurable | **Disabled** (forced) |
| Access mode | Configurable | **local** (forced) |
| Quality gates | Configurable | **Always on** (forced) |
| Log level | INFO | WARNING |
| Log format | Human-readable | JSON |

Set the environment:

```bash
export THOMAS_ENV=production
```

Production mode enforces safety overrides that cannot be weakened by the config file.

---

## Docker Builds

### Production

```bash
docker build -t thomas:latest .
```

Uses `requirements-lock.txt` for reproducible installs and bakes in `thomas.prod.toml` as the
configuration. `docker compose up -d` builds the same image but overrides `THOMAS_CONFIG` with
the development `thomas.toml` (see "Docker" above).

### Development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Mounts source code for hot-reload, enables debug logging, and uses `thomas.toml` (dev config).

---

## Configuration

Thomas loads config from TOML files with environment variable overrides.

**Search order:**
1. Explicit `--config` / `-c` CLI flag
2. `THOMAS_CONFIG` environment variable
3. `./thomas.toml` in working directory
4. Built-in defaults

**Config files:**
- `thomas.toml` — Development defaults (permissive, all model profiles)
- `thomas.prod.toml` — Production template (locked down, minimal)

**Environment variables:** See `.env.example` for all available overrides. Key variables:

```bash
THOMAS_ENV=production              # Environment mode
THOMAS_CONFIG=/path/to/config.toml # Config file path
THOMAS_LOG_LEVEL=WARNING           # DEBUG, INFO, WARNING, ERROR
THOMAS_LOG_FORMAT=json             # text or json
THOMAS_SERVER_PORT=8899            # Server port
THOMAS_MODELS_OPENAI_API_KEY=...   # API keys via env vars
```

---

## Health Checks

Thomas exposes health endpoints for monitoring:

```bash
curl http://localhost:8899/api/health
curl http://localhost:8899/healthz
```

Returns:
```json
{
  "status": "ok",
  "uptime_s": 123.4,
  "pid": 12345,
  "features": {},
  "degraded": [],
  "crash_count": 0
}
```

Use `/healthz` for Kubernetes liveness probes.

---

## Security Audit

Run the built-in secrets scanner before any release:

```bash
python scripts/audit_secrets.py
```

This checks the codebase for accidentally committed API keys, passwords, PII, and sensitive file paths. Exit code 0 means clean; exit code 1 means findings were detected.

---

## Pre-Release Checklist

1. All tests pass: `pytest tests/ -x -q`
2. Secrets audit clean: `python scripts/audit_secrets.py`
3. Docker builds succeed for both targets
4. Health endpoint returns 200
5. No bare `except:` clauses: `grep -rn "except:" thomas/ --include="*.py" | grep -v "except [A-Z]" | grep -v "# "`
