### Fixed

- **A commit message reaches git as it was written.** The three tools that commit
  by plumbing (`scripts/crew/brief/commit.py`, `scripts/forge/commit_master.py` and
  the self-change promoter) passed the message to `git commit-tree` through a
  Windows text pipe. That pipe writes cp1252 and turns every line ending into CRLF,
  which had three effects:
  - Every commit they made stored a CR on each line (42 in b4f33dee).
  - A message written to a file on Windows failed the integrity check as
    `broken_repo_tool`.
  - A single "→" crashed the commit with a charmap error.

  The read-back went through the same text mode, which is why nothing noticed. The
  tools now send UTF-8 bytes, and a CRLF message is treated as the same message.
