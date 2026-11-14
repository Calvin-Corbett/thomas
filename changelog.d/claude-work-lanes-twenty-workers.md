### Added

- **A harness that measures whether concurrent agents lose each other's work, and
  the answer at twenty.** Scripted workers — no model calls, no token spend —
  drive real git operations against a disposable repository, each editing a path
  no other worker touches, so a missing file is the substrate losing work rather
  than two workers disagreeing. On one shared checkout, twenty workers lost two of
  sixty files and throughput was **flat at ~3.2 commits/sec whether two workers ran
  or twenty** — twenty agents did the work of two, then lost a file. With a private
  worktree and branch per worker, twenty workers landed 60 of 60 across five
  consecutive runs at 5.3–7.7 commits/sec.
- The mechanism is not the lock everyone assumes: `lock_waits` was **zero** in
  every run. `git commit` rewrites the whole index, so one worker's commit discards
  another's completed `git add`, and the victim fails with `pathspec ... did not
  match any file(s) known to git` for a file it added successfully. The second
  failure is `cannot lock ref HEAD: is at X but expected Y`, because ref updates
  are compare-and-swap. Private worktrees fix the first, private branches the
  second, and it takes both.
