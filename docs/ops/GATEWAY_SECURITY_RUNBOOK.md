# Gateway Security Runbook

Last updated: 2026-02-21

## Threat Surface

Gateway endpoints can trigger control-plane actions (including restarts). Assume:
- inbound requests may be malicious
- tokens may be brute-forced if exposed
- repeated restart requests can degrade availability

## Baseline Configuration

1. Prefer local mode (`server.access_mode="local"`).
2. If remote mode is required:
- set strong `server.api_token`
- use TLS-terminating trusted infrastructure
- apply IP/network restrictions
3. Keep `gateway_auth_mode` enabled for gateway routes when remote access exists.
4. Keep auth brute-force throttling enabled:
- `THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED=1`
- `THOMAS_GATEWAY_AUTH_RATE_LIMIT_MAX_FAILURES` (default `8`)
- `THOMAS_GATEWAY_AUTH_RATE_LIMIT_WINDOW_SECONDS` (default `60`)

## Restart Endpoint Controls

`/gateway/restart` currently enforces:
- access-mode checks (loopback local mode, token in remote mode)
- optional gateway auth policy
- per-client rate limiting
- in-flight restart lock
- bounded restart deferral for pending work

## Incident Response

1. If repeated `access_denied` or `rate_limited` errors appear, treat as probing/abuse.
2. Rotate API tokens immediately after suspected leakage.
3. Tighten allowlists/firewall rules before re-enabling remote access.
4. Review audit/journal logs to reconstruct timeline.

## Verification Checklist

1. `python scripts/check_release_hygiene.py`
2. `python scripts/doc.py`
3. targeted gateway tests:
- `python -m pytest -q tests/prompt_pack/test_p127_gateway_restart_command.py`
- `python -m pytest -q tests/prompt_pack/test_p136_gateway_auth_policy_enforcement.py`
