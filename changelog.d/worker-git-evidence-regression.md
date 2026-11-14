### Fixed

- Added regression coverage in `tests/test_workboard_worker_script.py` for the existing fake Git `show-ref --verify refs/heads/dev` response. Both worker Git fakes resolve the exact target ref before evidence verification; the refusal fake reports non-ancestry rather than an unavailable target. Removing the success fake's ref response reproduces `test_worker_executes_assigned_task_and_releases_on_success` failing with exit code 1.
