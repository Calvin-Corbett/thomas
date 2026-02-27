from thomas.core.rules_of_road import build_remediation_prompt, evaluate_rules


def test_coding_write_without_verification_fails_required_gate():
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="update the function in app.py",
        response_text="Done.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/server/app.py",
            }
        ],
        requested_job_type=None,
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )
    assert report["job_type"] == "coding"
    assert report["passed"] is False
    assert report["required_failed_count"] >= 1
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_verification" in failed_ids


def test_coding_write_with_verification_and_tests_passes():
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix bug and run tests",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/core/config.py",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q tests/test_config_env_override.py",
                "path": "",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python scripts/check_monolith_guard.py",
                "path": "",
            },
        ],
        requested_job_type=None,
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )
    assert report["passed"] is True


def test_coding_write_with_only_prewrite_verification_fails():
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="patch bug",
        response_text="Done.",
        tool_events=[
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q",
                "path": "",
            },
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/core/config.py",
            },
        ],
        requested_job_type=None,
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )
    assert report["job_type"] == "coding"
    assert report["passed"] is False
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_verification" in failed_ids


def test_coding_write_without_monolith_guard_fails_required_gate():
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="refactor module boundaries",
        response_text="Patched.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/server/app.py",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q tests/test_rules_of_road.py",
                "path": "",
            },
        ],
        requested_job_type=None,
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_monolith_guard" in failed_ids


def test_config_job_fails_on_unknown_keys():
    report = evaluate_rules(
        route_path="planning",
        prompt_text="please adjust configuration in thomas.toml",
        response_text="Updated config.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas.toml",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "thomas doctor",
                "path": "",
            },
        ],
        requested_job_type="config",
        config_errors=["Unknown core config key 'server.rat_limit_enabled'."],
        unknown_core_keys=["server.rat_limit_enabled"],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )
    assert report["job_type"] == "config"
    assert report["passed"] is False
    prompt = build_remediation_prompt(report)
    assert "Quality gate failed" in prompt
    assert "No unknown core config keys" in prompt


def test_strict_issue_ownership_fails_workaround_only_completion() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix this bug end-to-end",
        response_text="I applied a temporary workaround for now. The issue is still failing.",
        tool_events=[],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        strict_issue_ownership=True,
        attempt=0,
    )
    assert report["passed"] is False
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "issue_ownership" in failed_ids


def test_non_strict_issue_ownership_does_not_require_gate() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix this bug end-to-end",
        response_text="I applied a temporary workaround for now. The issue is still failing.",
        tool_events=[],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=False,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        strict_issue_ownership=False,
        attempt=0,
    )
    issue_check = next(
        (c for c in report["checks"] if c.get("id") == "issue_ownership"),
        None,
    )
    assert isinstance(issue_check, dict)
    assert issue_check["required"] is False
