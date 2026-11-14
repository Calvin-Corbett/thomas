### Fixed

- **The commit rescue can now see the file the accident just orphaned.**
  `worktree_safety.capture()` takes `git diff HEAD --binary`, which carries staged
  and unstaged work — but a diff against a commit has no untracked side, so
  untracked files were invisible. That would be a small gap, except the failure
  this tool exists for *converts a tracked file into an untracked one*: the index
  records a deletion, the content lands back on disk unregistered, and `git status`
  prints `D` and `??` for one path at once. At the moment the snapshot mattered
  most, the file had just left the only set it could read. Found by claude-perf,
  who proved it rather than argued it — none of the five snapshots taken during the
  attempts that lost their work contained any of it. Untracked non-ignored files
  are now copied beside the patch, rather than staged with `git add -N`, because
  intent-to-add costs an index write and a locked index is *correlated* with this
  accident: a rescue that needs the lock is unavailable exactly when it is needed.
  Restore brings them back without ever overwriting a file that exists again, and
  no longer reports failure when the patch cannot apply but every file it covered
  was recovered — which is the expected shape of this accident, not an error.
