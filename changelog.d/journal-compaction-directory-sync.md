### Fixed

- Journal compaction syncs the replacement's directory entry after replacing the file, using the journal's existing POSIX directory-sync helper and its documented Windows fallback. If that sync fails, existing owners must reopen before continuing; replay preserves saved results and unfinished inputs.
- Regression tests verify file-sync, replacement, and directory-sync ordering, plus rejection of an existing owner after directory-sync failure. Both tests fail without the compaction directory-sync protection.
