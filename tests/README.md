# Thomas Test Suite

This test suite protects the public Thomas runtime surface.

Primary goals:

- Verify install, server, CLI, web UI, security, and release behavior.
- Keep public release checks deterministic.
- Catch regressions in the local-first user experience.

Public-release surface checks live in `tests/test_public_release_surface.py`.
