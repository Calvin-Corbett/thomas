# Onboarding — install, model setup, and troubleshooting

This is the practical "get it running" guide. For what Thomas *is*, see [`README.md`](README.md).

Thomas runs locally: one server + one web UI + one CLI. You bring your own model
API key; nothing is unlocked until Thomas can verify a connection to your provider.

---

## 1. Install

Pick the path for your OS. All paths end the same way: a local server on
`http://127.0.0.1:8899` and a one-time **Easy Setup** in the browser.

### Windows (one-click)

1. Run `run-ui.cmd`.
2. Wait for first-launch bootstrap to finish (it installs dependencies and a starter profile).
3. The browser should open `http://127.0.0.1:8899` automatically; open it manually if not.

Advanced/manual setup instead: run `setup.cmd`.

The server runs without a window, so closing the browser leaves Thomas running. The first Start
Menu launch that works shows a message saying so, once. To stop it, use **Stop Thomas** in the Start
Menu folder, or run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ui.ps1 -Stop`
from the install folder: it exits 0 when it ended a Thomas, 3 while a Build run is active (that
Thomas is left running), 5 when it found none and 6 when one would not stop. **Restart Thomas**, or
`-Restart`, replaces the running one once no Build run is active. Each launch writes a log under
`runtime\logs` (the newest five are kept).

### macOS / Linux

```bash
bash install.sh
```

Run it from a checkout of the repository. `install.sh` offers to create a virtual environment
(`.venv`; the default answer is yes, and `THOMAS_NO_VENV=1` skips it), installs Thomas with the
web server dependencies, and sets up a starter profile. It then offers to start the UI. If you
answer no, start it yourself with `source .venv/bin/activate` (only if you accepted the `.venv`)
and `thomas serve`, then open `http://127.0.0.1:8899`.

### Docker (any platform)

```bash
docker compose up
```

This builds and runs the server in a container. Open `http://127.0.0.1:8899` once it
reports ready. See [`docs/ops/DOCKER_DEPLOY.md`](docs/ops/DOCKER_DEPLOY.md) for
production/remote Docker deployment.

---

## 2. Model setup (Easy Setup)

On first launch, the browser wizard walks you through connecting a model provider:

1. Choose a provider and paste your API key.
2. Thomas **verifies the connection** before unlocking chat, memory, and automation —
   if the key or endpoint is wrong, it tells you instead of silently failing.
3. Once verified, the main surface (chat) becomes available.

Your key is stored locally on your machine. Thomas defaults to **local-only**; it does
not phone home, and remote/production exposure is opt-in (see the "Production / remote
deploy" section of [`README.md`](README.md)).

---

## 3. Troubleshooting

**Something drifted or won't start.** On Windows, run `repair.cmd`, or use
**Auto Repair** in the onboarding wizard. Both re-check dependencies and the profile and
fix the common breakages.

**Quick health check.** The CLI exposes `status`, `quickstart`, `setup`, and `repair`
verbs for diagnosing a stuck install without the UI.

**The server starts but the UI is blank or stale.** Hard-refresh the browser, then
confirm the server is actually listening on `http://127.0.0.1:8899`.

**Logs.** Server logging is controlled by the `THOMAS_LOG_FILE`, `THOMAS_LOG_MAX_BYTES`,
and `THOMAS_LOG_BACKUP_COUNT` environment variables (see [`README.md`](README.md) and
[`DEPLOYMENT.md`](DEPLOYMENT.md)). When reporting a problem, the log file is the most
useful thing to attach.

**Still stuck?** Open an issue with your OS, the install path you used, and the relevant
log lines. Security issues should follow [`SECURITY.md`](SECURITY.md) instead of a public
issue.
