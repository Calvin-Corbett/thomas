### Fixed

- **Thomas can improve a copy of itself, and Build can edit any project's own `scripts/`
  and `pyproject.toml`.** Thomas's runtime protection checked paths relative to whatever
  folder a Build run worked in. A copy of Thomas (a worktree you ask Thomas to improve)
  therefore could not have `thomas/core` edited, and any project with its own `scripts/`
  folder or `pyproject.toml` could not have those edited either. The Build runner now
  anchors protection to the Thomas that is actually running: its files stay protected
  whatever folder a tool is confined to, and folders that only look like Thomas do not.
  Nothing changes for Thomas's own server agents.

### Changed

- **The runtime-protection flag code moved into its own module,**
  `thomas/tools/runtime_protection_flag.py`, unchanged and re-exported from
  `thomas/tools/filesystem.py`, which keeps that file under the 800-line limit.
