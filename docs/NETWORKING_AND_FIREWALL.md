# Networking And Firewall

Thomas is local-first by default.

## Default Runtime

- `run-ui.cmd` and `scripts/run-ui.ps1` start the web UI on `127.0.0.1:8899`.
- `127.0.0.1` is the loopback address. It means "this computer only."
- Thomas does not configure router port forwarding.
- Thomas does not expose the UI to your LAN or the public internet unless you explicitly change the bind host or deployment settings.

## Windows Firewall Prompt

Windows can still show a firewall prompt because Python starts a local web server. For normal local use:

- Use `http://127.0.0.1:8899` in the browser.
- If Windows asks, allow Private networks only.
- Do not allow Public networks unless you are intentionally exposing a remote deployment.
- If you see a LAN IP, `0.0.0.0`, or a public IP in the URL, stop and check the command that launched Thomas.

## Remote Deployment

Remote production use is opt-in. Before exposing Thomas outside the local machine:

- Set a strong `THOMAS_SERVER_API_TOKEN`.
- Use `THOMAS_ENV=production`.
- Keep `THOMAS_ALLOW_REMOTE_PRODUCTION=1` unset unless remote access is intentional.
- Read `docs/ops/GATEWAY_SECURITY_RUNBOOK.md` first.

## Troubleshooting Install Reports

If someone says their firewall blocked an IP, ask for:

- The exact URL they tried to open.
- Whether Windows Firewall mentioned Private or Public networks.
- The command they ran (`run-ui.cmd`, `python -m thomas.server`, Docker, or another launcher).
- Whether any VPN, antivirus, corporate firewall, or managed Windows policy is active.

For normal download/install from GitHub, the app should not require inbound firewall access. The only expected local URL is `http://127.0.0.1:8899`.
