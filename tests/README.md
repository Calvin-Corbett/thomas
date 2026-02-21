# Thomas Competitive Test Suite

This test suite is designed to measure Thomas against competitor agent surfaces.

Primary goals:
- verify feature parity for CLI, API, streaming, and UX-facing behaviors
- catch regressions that widen gaps versus competitors
- keep outputs deterministic so cross-run and cross-agent comparisons are reliable

Scope notes:
- tests in `tests/prompt_pack/` and `tests/test_agent_comparison_suite.py` are the main competitive/comparison layers
- Thomas can execute these tests locally; competitor products (for example Claude Code) are external systems and must be run separately in their own environment, then compared using shared metrics/artifacts


Competitor intelligence dataset:
- `tests/competitors/` (per-competitor profiles, source links, and provisional scorecard)