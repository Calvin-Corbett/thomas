### Fixed

- **A Build run on a copy of Thomas runs the real Thomas, not the copy it is editing.**
  The Build agent starts inside the project folder, and when that folder is a copy of
  Thomas (a worktree you ask Thomas to improve), the copy's code was loaded instead of
  the Thomas that launched the run. The agent ran the very code it was changing, and
  every check for "is this Thomas's own source?" pointed at the copy. The agent now
  loads the running Thomas, while the checks it runs still test the project's own code.
- **Test stand-ins for the Build agent's output now behave like the real thing.** Nine
  test files faked the output pipe with only `readline()`, so the previous fix to how
  that output is read broke them. Each fake now answers `read()` as well.
