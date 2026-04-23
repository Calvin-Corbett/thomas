# Release Checklist

- Ensure `pyproject.toml` version matches `thomas/__init__.py`.
- Add a matching current-version header in `CHANGELOG.md`.
- Run `python scripts/check_release_hygiene.py`.
- Keep generated artifacts deterministic and clearly marked.
- Confirm release scripts do not require import-time warnings to pass.
