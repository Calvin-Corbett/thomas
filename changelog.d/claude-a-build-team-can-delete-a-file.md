### Added

- **Build's Claude team can delete a file in its own project.** On 2026-09-25 a
  Thomas project you asked to clean junk out of Thomas's code found 19 modules
  with no caller and could only empty them. Build on Claude had file read and
  write, and a shell only with guardrails open, so there was no way to remove a
  file. In its own words: "This execution policy gives me file read/write but
  **no shell and no delete**." Its hand-in carried 19 zero-byte files and a
  changelog that said they were gone. A run that may edit now also gets
  `delete_files` (`paths`, `why`) on its run channel. It deletes files in that
  run's project folder and nothing else. It refuses an absolute path, a path
  outside the folder or the folder itself, anything inside `.git`, a folder, a
  symlink or junction (or a path through one), and a file that does not exist,
  and each refusal says which rule it hit. One call names at most 200 paths and
  returns one result per path, so one bad path never stops the rest. Every call
  is recorded in the run's history with its reason and results, and that record
  survives a server restart. A read-only or dry run is never offered the tool,
  and the shell is unchanged: whether Build on Claude gets one is still your
  guardrails choice.
