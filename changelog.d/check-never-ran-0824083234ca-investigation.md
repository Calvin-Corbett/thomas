### Investigation

- Investigated `thomas_project` report `check_never_ran`, fingerprint
  `0824083234ca`, with the supplied diagnostic `{"category": "unavailable"}`.
- `thomas/server/hand_in_hold.py` records this issue when a held check exhausts
  its tries or strikes. The diagnostic does not identify the underlying cause.
- The checkout has no `runtime/logs/issues.jsonl`, and Git search found no
  tracked occurrence of the fingerprint. The original incident was not
  reproduced; no runtime fix is claimed or included.
- The three focused test files for unavailable checks, durable holds, and
  hold retries passed together (50 tests). Architecture tests passed (13 tests).
- Further diagnosis needs a sanitized failure reason and the failed check step
  or command, with its exit status or timeout and relevant error output.
