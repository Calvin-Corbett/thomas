### Changed
- `check.run` now takes `--timeout=N` (1 to 600 seconds a test), so a hanging test fails in seconds with its name and stack. On 2026-10-26 a Build team's check.run hit the 10-minute tool limit twice on files that held hanging tests, and nothing said which test hung.

### Fixed
- When a change will not apply to dev, the lines that name what conflicted now come first by git's own wording ("with conflicts.", "error:", an unmerged path). A file whose name holds the word "conflict" was put first even though it applied cleanly.
