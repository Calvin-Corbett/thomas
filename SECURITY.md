# Security Policy

Thomas exposes local and remote control surfaces. Treat all inbound prompts and API calls as untrusted input.

## Supported Versions

Only the latest release branch is supported for security fixes.

## Reporting a Vulnerability

1. Do not open a public issue with exploit details.
2. Report privately to project maintainers with:
- impact and affected component
- exact reproduction steps
- environment and version
- suggested mitigation
3. Allow maintainers reasonable time to triage and patch before public disclosure.

## Secure Baseline

1. Keep server access local unless remote access is explicitly required.
2. When using remote access, require a strong API token.
3. Keep tool permissions minimal (`allow_shell=false` unless needed).
4. Restrict filesystem/tool scope to expected workspace paths.
5. Rotate model/provider credentials and avoid committing secrets.

## Gateway Restart Endpoint Hardening

`/gateway/restart` is protected by:
- local-mode loopback enforcement by default
- remote-mode token authentication when configured
- optional gateway auth policy enforcement
- per-client rate limiting
- in-flight restart suppression
- deterministic error responses for monitoring and automation

Relevant env overrides:
- `THOMAS_GATEWAY_RESTART_ACCESS_MODE`
- `THOMAS_GATEWAY_RESTART_API_TOKEN`
- `THOMAS_GATEWAY_RESTART_RATE_LIMIT_ENABLED`
- `THOMAS_GATEWAY_RESTART_RATE_LIMIT_MAX_REQUESTS`
- `THOMAS_GATEWAY_RESTART_RATE_LIMIT_WINDOW_SECONDS`

## Operational Recommendations

1. Run Thomas behind trusted network boundaries.
2. Keep dependencies updated and run repository gates before release.
3. Enable audit and journal features for incident investigation.
4. Review logs and restart failures for repeated auth/rate-limit events.
