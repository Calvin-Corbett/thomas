### Fixed

- **A self-fix run can no longer stop the Thomas it is running inside.** On
  2026-09-24 your caged server (port 8898) ended with exit code 15, which is what
  Python's `os.kill(pid, SIGTERM)` leaves on Windows, while five Thomas projects
  were working in greens, and everything stopped with it, Chat included. A
  starting server used to stop whatever process its memory folder's
  `serve.lock` named, and any Thomas server holding its port, without checking
  whose they were. Which command actually did it is not confirmed; a builder
  starting a server of its own to look at its work is the likeliest cause. Now:
  - `serve.lock` records the checkout a server came from, and a starting server
    stops only an earlier server of its own checkout, so a restart still
    replaces the old one.
  - A server of another checkout, or one whose lock was written before locks
    recorded their checkout, is left running, and the new server refuses to
    start (exit code 3) with a sentence saying what to do instead, for example
    "port 8898 is used by another Thomas (...); start this one with --port
    <free port>".
  - A server started from a green stops nothing at all. It takes a free port
    instead of the usual one and prints the address to open. Whether a start is
    from a green is decided by where its code or its folder is, not by the agent
    id the cage runner sets, which a command can drop.
  - The caged server is never stopped by a start. A builder that ran the
    checkout's own `scripts/cage/caged_server.py` looked exactly like its restart
    (same code, same folder, same memory); it is now refused and told to end the
    `ThomasCagedServer` task first. The task already ends the old server before
    running it again, so no restart relied on the stop.
  - A lock whose process has exited no longer blocks a start. On Windows the old
    liveness check, `os.kill(pid, 0)`, reported even an exited process as
    running.
  - A lock whose process number now belongs to another process is stale, and
    nothing is stopped. Windows reuses process numbers, and after a reboot the
    caged server's lock could name the cage's own shell runner, which a start
    would then have stopped. `serve.lock` now records when its server started,
    and a start stops the lock's process only when that time still matches, or,
    for a lock written before this, when its command line is a Thomas server of
    the same checkout. A process whose command line cannot be read, or no
    process list at all, is never taken as proof.
  - A server that stops removes `serve.lock` only if the lock is still its own.
