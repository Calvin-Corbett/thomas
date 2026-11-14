### Fixed
- Tests now use a separate home folder per test outside each test's `tmp_path` for implicit skill discovery and Work migration paths, while the real-data alarm continues watching the original home folder.
- Regression tests cover both implicit discovery paths and assert that the watched real home stays outside the test home.
