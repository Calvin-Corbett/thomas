### Changed

- Investigated `check_never_ran` on `thomas_project`, fingerprint `4183016dc03d`. The supplied diagnostic is only `{"category":"unavailable"}`; the checkout has no `runtime/logs/issues.jsonl`, and the fingerprint was not found in tracked files.
- `thomas/server/hand_in_hold.py` records `check_never_ran` when a check's hold exhausts its retry or strike limit. The supplied diagnostic does not identify the underlying unavailable-check cause, so the reported failure was not reproduced and no runtime fix is claimed.
- Existing tests passed: `tests/test_a_change_that_could_not_be_checked_waits.py`, `tests/test_an_unavailable_check_names_its_cause.py`, and `tests/test_architecture.py` (48 passed together); `tests/test_a_held_hand_in_is_tried_again.py` and `tests/test_a_check_held_for_room_runs_when_room_returns.py` (24 passed together).
- Further diagnosis needs sanitized evidence for this fingerprint: the unavailable check's reason, the check stage, retry and strike counts, and relevant checker error output. Do not include credentials or conversation content.
