# Thomas — Deployment Guide

## Quick Start

### Development (local)

```bash
# Clone and install
git clone https://github.com/thomas-ai-assistant/thomas.git
cd thomas
bash install.sh

# Or on Windows:
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

# Run the UI
python -m thomas.server
# Open http://127.0.0.1:8899
```

### Production (Docker)

```bash
docker compose up -d
```

This builds and runs Thomas in production mode with locked-down defaults.

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
# or
docker compose up -d
```

Uses `requirements-lock.txt` for reproducible installs and `thomas.prod.toml` for configuration.

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
