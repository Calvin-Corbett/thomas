### Fixed

- **The README stops calling the CI smoke list "the full test ladder".** The `full-test-matrix` job runs a fixed list of eleven test files, not the suite of about thirteen thousand tests; the publish section now says so, and names the changelog fragment step that folds `changelog.d/` into `CHANGELOG.md` at release.
