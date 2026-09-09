# Security Checklist

- Avoid import-time warnings and secret checks that execute on import.
- Keep secret validation at runtime initialization points.
- Run `python scripts/security_audit.py --repo-root . --json`.
- Keep webhook/auth policy manifests current.
- Ensure no sensitive files are added to tracked source.
