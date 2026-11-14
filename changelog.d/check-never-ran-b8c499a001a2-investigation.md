### Changed

- Investigated `check_never_ran` on `thomas_project`, fingerprint `b8c499a001a2`, using the supplied diagnostic `{"category":"unavailable"}`. Before this fragment was added, Git search found no tracked occurrence of the fingerprint; the checkout has no `runtime/logs/issues.jsonl`.
- `thomas/server/hand_in_hold.py` records `check_never_ran` when a held check exhausts its retry or strike limit. The supplied diagnostic does not identify the underlying cause. The reported incident was not reproduced, no runtime code was changed, and no fix is claimed.
- The existing unavailable-check, durable-hold, hold-retry, disk-recovery, and architecture test files passed together (72 tests). This checks existing behavior, not resolution of the reported incident.
- Further diagnosis needs a sanitized unavailable-check reason, the failed stage or command, its exit status or timeout, and relevant checker error output. Retry and strike counts would help distinguish exhaustion paths. Do not include credentials or conversation content.
