### Investigation

- Investigated `check_never_ran` on `thomas_project`, fingerprint `05edf13cfaf1`, with the supplied diagnostic `{"category":"unavailable"}`. Before this fragment was added, Git search found no tracked occurrence of the fingerprint; the checkout has no `runtime/logs/issues.jsonl`.
- `thomas/server/hand_in_hold.py` records this issue when a held check exhausts its retry or strike limit. The supplied diagnostic does not identify the underlying cause. The reported incident was not reproduced, no runtime code was changed, and no fix is claimed.
- The focused unavailable-check, durable-hold, and hold-retry tests plus `tests/test_architecture.py` passed together: 68 tests, with five temporary-directory cleanup warnings.
- Further diagnosis needs a sanitized failure reason and the failed check step or command, including its exit status or timeout and relevant error output. Do not include credentials or private runtime data.
