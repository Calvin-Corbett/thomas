### Added

- **The Build agent can run the project's tests and lint on its own work.** Below the
  "Open" guardrails setting the Build agent had no way to run any command: asked to run
  pytest it answered "direct shell is unavailable", even at Full autonomy, and so could
  never verify a change before calling it done. A new `check.run` tool runs a closed
  set of checks and nothing else: pytest on project paths or `-k` selections, `ruff
  check` and `ruff format --check`, and read-only `git status`, `git diff` and `git
  log`. It never uses a shell, runs in the project folder with a 15-minute limit, and
  refuses any argument outside the list with a reason. It is available whenever the
  run may edit files, and the agent is told to use it before saying it is done.
