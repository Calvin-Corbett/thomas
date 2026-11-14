### Changed

- **CI stops calling eleven files the full test matrix, and the whole suite runs weekly and on demand.** The `full-test-matrix` job ran eleven named test files, about one percent of the suite, and a failing test hid behind its green badge for two days. It is now `smoke-matrix`, named for what it does, and a new `full-suite.yml` workflow runs every test file on Sundays and whenever someone asks, keeping the JUnit report as an artifact. It is not a required check; it is evidence, and it is scheduled weekly so the private repository's CI minutes are not spent on every push.
