### Security

- **The cage is on, and it was proven by using it.** A shell command now runs as
  `thomas-agent`, and that account cannot write Thomas's own code. Verified
  against the live cage rather than inferred from a setup script reporting
  success:
  - `whoami` returns `bobs_chromebook\thomas-agent`.
  - Python running there gets `PermissionError: Permission denied` writing into
    `thomas\` and `scripts\` — the exact shape of the incident this exists to
    stop, where a run used a shell command to put a protected file back, around
    the card and the password.
  - Writing into `tests\` still works, so agent work is not blocked.
  - `git config --local` is still refused: `could not lock config file`.
- **The caged account can now actually work.** Three things made the cage a
  place where nothing could be done, each found by running a real command in it:
  - **Python was not on its PATH** (`'python' is not recognized`). The runner
    now puts its own interpreter's directory first, so a caged `python -m
    pytest` uses exactly the interpreter the rest of Thomas uses. It is taken
    from the running process, not from a setting, so it cannot drift.
  - **git refused the repository outright** as owned by another user. It is
    marked `safe.directory` for every account.
  - **git could not read `.git\config`.** Sealing that file removed inheritance
    and granted only SYSTEM and you — which stopped the agent writing it, as
    intended, but git reads its config before doing anything at all, so `status`,
    `log` and `diff` all failed. Read is restored; writing is still refused.
  - Bytecode writing is disabled for caged commands, since most of the repo is
    read-only to that account and every `.pyc` write would silently fail.
- **Only one runner can hold the channel.** Repeated task restarts left three
  runners serving the same inbox. They took turns writing the heartbeat, which
  was merely confusing — but a request is read, run, and deleted afterwards, so
  two runners could both read the same one and **the command would run twice**.
  For anything that changes state that is a bug with consequences, and it gets
  worse the more the cage is relied on. A runner now takes a byte-range lock on
  the channel and a second one exits quietly. Verified against the live cage:
  three requests produced exactly three appends, not six. The lock is released
  by the operating system when the process ends, so a runner killed mid-command
  leaves nothing stale behind to second-guess.
- **Tools that cache into the repo now have somewhere to write.** `ruff check`
  failed inside the cage — "Failed to create temporary file ... `.ruff_cache`
  ... Access is denied" — while `pytest` passed 25 tests in the same cage,
  because pytest degrades when its cache is unwritable and ruff does not. The
  caches moved to the account's own temp directory; the boundary did not move.
  Worth remembering the next time the cage is tightened: what a privilege
  boundary usually costs is a place to write scratch files, not the ability to
  do the work.
