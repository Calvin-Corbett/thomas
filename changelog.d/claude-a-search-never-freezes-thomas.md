### Fixed

- **A search in a Chat turn no longer freezes Thomas.** `fs.search` was `async` but
  never awaited: it walked the whole search root on the server's event loop, and in
  a Chat turn that root is the repo, `runtime/` and `.thomas/` included. Measured on
  2026-09-23, one search that found nothing held the loop for 543 s over 259,348
  files; live, two Chat turns froze it for about 120 s and 145 s, and four self-fix
  workers that were working were failed together the moment it came back. You
  asked: "make them fix ... performance". `fs.search` and recursive `fs.list_dir`
  patterns now walk in a worker thread, never enter `.git/`, `.thomas/`,
  `node_modules/`, `.venv/`, `__pycache__/` or the root's `runtime/`, and stop at
  20,000 files or 20 seconds with a line saying they stopped early and why, so the
  model can narrow the search. Large files are read a chunk at a time, so one big
  file can neither overrun the time budget nor hold the interpreter lock for long.
  The same search of the repo now keeps the loop's longest stall at 0.1 s. A search
  that finishes within its budget returns exactly what it returned before.
- **A worker is judged by its own silence, not the server's.** The worker watchdog
  runs on the server loop, and every worker's progress was handed to that loop and
  awaited, so a held loop made every worker look silent and the watchdog failed them
  all the moment the loop came back. The watchdog now notices its own late wake-ups
  and does not charge that time to the worker. Progress no longer waits for the loop:
  it is queued, still delivered in order, and each report beats an in-memory
  heartbeat the watchdog reads directly. The long 360-second window now follows the
  task's reasoning effort (xhigh or max) as well as the Thorough economy setting; the
  records showed `effort: "cheap"` beside `reasoning_effort: "xhigh"`, and the window
  only ever read the first.
- **A helper's work keeps its lead alive, and a failed worker actually stops.** A lead
  waiting on a `task.spawn` helper emits nothing of its own, so a helper that worked
  longer than the window got its lead failed as silent; each helper step now beats the
  lead's heartbeat, and both watchdogs keep waiting while it is fresh. When the
  watchdog failed a worker it cancelled only the task that waited for the worker's
  thread, and the thread ran on: `exec-a5ab521aff9c` started "attempt 2 of 12" after
  its card said failed. The watchdog, and a Stop from you, now set a flag the worker
  checks between attempts and cancel the run inside the worker's own loop, and a
  stopped run writes nothing over the reason on its card.
