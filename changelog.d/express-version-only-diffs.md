### Fixed

- The express window accepts an exact single version-line replacement in `pyproject.toml`'s `[project]` table or `thomas/__init__.py`, using the complete per-file Git diff. Additional edits, deletions, mode changes, malformed diffs, and enforcement-path protection still require your card.
- Regression tests cover allowed version replacements and rejected changes, including real Git diffs, TOML table scope, Python assignment scope, and newline changes.
