# Competitor Intelligence

This directory is the shared competitor map for Thomas.

Each competitor has its own folder at `tests/competitors/<id>/` with:

- `profile.json`: machine-readable profile for tooling and reports.
- `README.md`: human-readable summary, strengths, and source links.

Core files:

- `tests/competitors/catalog.json`: master competitor list.
- `tests/competitors/metric_framework.md`: normalized metrics used for apples-to-apples comparisons.
- `tests/competitors/provisional_scoreboard.json`: provisional 0-5 metric scores derived from public evidence.

Notes:

- Scores and capability tags are provisional unless backed by runtime benchmark artifacts.
- Closed products (for example Claude Code, Devin, and some web builders) must be run in their own environment, then compared using exported artifacts.
- Last refresh date for this dataset is stored per profile.
