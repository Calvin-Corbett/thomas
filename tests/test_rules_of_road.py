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
                "command": "python scripts/forge/gates/monolith_guard.py",
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


def test_coding_write_with_missing_skill_required_probe_fails() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix analyzer suppression directives",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "edit:bandit/core/manager.py",
                "ok": True,
                "command": "",
                "path": "",
            },
            {
                "name": "python -m unittest tests.functional.test_functional.FunctionalTests.test_nosec",
                "ok": True,
                "command": "",
                "path": "",
                "output_preview": "OK",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=False,
        skill_required_checks=[
            {
                "skill": "line-suppression-directives",
                "text": "Before finishing, run the literal probe.",
                "snippets": ["subprocess.Popen(", "shell=True,  # nosec-begin B602", "# nosec-end"],
                "expected_outputs": ["[]"],
            }
        ],
        attempt=0,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_skill_required_checks" in failed_ids
    check = next(c for c in report["checks"] if c["id"] == "coding_skill_required_checks")
    assert "[]" in check["detail"]


def test_coding_write_with_skill_required_probe_observed_passes() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix analyzer suppression directives",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "edit:bandit/core/manager.py",
                "ok": True,
                "command": "",
                "path": "",
            },
            {
                "name": "python -m unittest tests.functional.test_functional.FunctionalTests.test_nosec",
                "ok": True,
                "command": "",
                "path": "",
                "output_preview": (
                    "source = 'import subprocess\\nsubprocess.Popen(\\n"
                    "    shell=True,  # nosec-begin B602\\n)\\n# nosec-end'\\n"
                    "remaining ids: []\\nOK"
                ),
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=False,
        skill_required_checks=[
            {
                "skill": "line-suppression-directives",
                "text": "Before finishing, run the literal probe.",
                "snippets": ["subprocess.Popen(", "shell=True,  # nosec-begin B602", "# nosec-end"],
                "expected_outputs": ["[]"],
            }
        ],
        attempt=0,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_skill_required_checks" not in failed_ids
    assert report["passed"] is True


def test_skill_required_probe_must_observe_snippets_and_expected_output_together() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix analyzer suppression directives",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "edit:bandit/core/manager.py",
                "ok": True,
            },
            {
                "name": "probe shape",
                "ok": True,
                "command": "source='subprocess.Popen(... shell=True,  # nosec-begin B602 ... # nosec-end)'",
                "output_preview": "remaining ids: ['B602']",
            },
            {
                "name": "unrelated output",
                "ok": True,
                "command": "print(empty_list)",
                "output_preview": "[]",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=False,
        skill_required_checks=[
            {
                "skill": "line-suppression-directives",
                "text": "Before finishing, run the literal probe.",
                "snippets": ["subprocess.Popen(", "shell=True,  # nosec-begin B602", "# nosec-end"],
                "expected_outputs": ["[]"],
            }
        ],
        attempt=0,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_skill_required_checks" in failed_ids


def test_codex_passthrough_edit_and_shell_command_count_as_write_and_test():
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix serializer bug and run tests",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "edit:mashumaro/core/meta/code/builder.py",
                "ok": True,
                "command": "",
                "path": "",
            },
            {
                "name": "python -m pytest -q tests/test_serializer.py",
                "ok": True,
                "command": "",
                "path": "",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    assert report["passed"] is True
    assert report["signals"]["writes_detected"] is True
    assert report["signals"]["tests_detected"] is True


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


def test_coding_write_in_external_repo_without_monolith_guard_does_not_require_thomas_gate(tmp_path):
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix external repo bug",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "pkg/module.py",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q tests/test_module.py",
                "path": "",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=True,
        attempt=0,
        repo_root=tmp_path,
    )
    required_ids = {c["id"] for c in report["checks"] if c["required"]}
    assert "coding_monolith_guard" not in required_ids
    assert report["signals"]["monolith_guard_available"] is False
    assert report["passed"] is True


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


def test_coding_placeholder_backed_write_without_completion_note_fails(tmp_path) -> None:
    placeholder_file = tmp_path / "thomas" / "core" / "placeholder_runtime.py"
    placeholder_file.parent.mkdir(parents=True, exist_ok=True)
    placeholder_file.write_text(
        "# Source placeholder for placeholder_runtime.py\n",
        encoding="utf-8",
    )

    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="restore runtime",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/core/placeholder_runtime.py",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q tests/test_rules_of_road.py",
                "path": "",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python scripts/forge/gates/monolith_guard.py",
                "path": "",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
        repo_root=tmp_path,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_placeholder_policy" in failed_ids


def test_coding_placeholder_backed_write_with_completion_note_passes(tmp_path) -> None:
    placeholder_file = tmp_path / "thomas" / "core" / "placeholder_runtime.py"
    placeholder_file.parent.mkdir(parents=True, exist_ok=True)
    placeholder_file.write_text(
        "\n".join(
            [
                "# Source placeholder for placeholder_runtime.py",
                "# placeholder-why: temporary path-stable stub during restoration.",
                "# placeholder-scope_to_finish: restore the source-backed runtime.",
                "# placeholder-owner: thomas/core",
                "# placeholder-exit_rule: fail fast until the real implementation lands.",
                "# placeholder-acceptance: runtime tests pass without placeholder state.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="restore runtime",
        response_text="Patched and validated.",
        tool_events=[
            {
                "name": "diff.create",
                "ok": True,
                "command": "",
                "path": "thomas/core/placeholder_runtime.py",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -m pytest -q tests/test_rules_of_road.py",
                "path": "",
            },
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python scripts/forge/gates/monolith_guard.py",
                "path": "",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=True,
        attempt=0,
        repo_root=tmp_path,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_placeholder_policy" not in failed_ids


# ---------------------------------------------------------------------------
# Praxis red/blue hardening regressions (praxis-unbypassable-2026-05-29).
# R1: shell-command file mutations must count as writes.
# R2: failed tests/verification must not satisfy post-write requirements.
# R3: echo-spoofed skill probes must not satisfy skill_required_checks.
# ---------------------------------------------------------------------------


def test_shell_command_file_mutation_counts_as_write_R1() -> None:
    # A file mutation done through shell.exec (not a write-named tool) must be
    # seen as a write, so the post-write verification requirement still fires.
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="touch up config",
        response_text="Done.",
        tool_events=[
            {
                "name": "shell.exec",
                "ok": True,
                "command": "python -c \"from pathlib import Path; Path('thomas/core/config.py').write_text('bad engineering')\"",
                "path": "",
            }
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    assert report["signals"]["writes_detected"] is True
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_verification" in failed_ids
    assert report["passed"] is False


def test_redirection_write_counts_as_write_R1() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="patch file",
        response_text="Done.",
        tool_events=[{"name": "shell.exec", "ok": True, "command": "echo 'bad' > thomas/core/config.py"}],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    assert report["signals"]["writes_detected"] is True
    assert report["passed"] is False


def test_failing_test_after_write_blocks_completion_R2() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix bug",
        response_text="Patched.",
        tool_events=[
            {"name": "diff.create", "ok": True, "command": "", "path": "thomas/core/config.py"},
            {
                "name": "shell.exec",
                "ok": False,  # the test FAILED
                "command": "python -m pytest -q tests/test_config_env_override.py",
                "output_preview": "1 failed, 0 passed\nFAILED tests/test_config_env_override.py",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    # A failing test must not be credited as "tests ran" and must hard-fail.
    assert report["signals"]["tests_detected"] is False
    assert report["signals"]["failed_test_after_write"] is True
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_tests_passed" in failed_ids
    assert report["passed"] is False


def test_echo_spoofed_skill_probe_does_not_satisfy_check_R3() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix analyzer suppression directives",
        response_text="Patched.",
        tool_events=[
            {"name": "diff.create", "ok": True, "command": "", "path": "bandit/core/manager.py"},
            {
                # spoof: echo the snippets + expected output so text-matching passes
                "name": "shell.exec",
                "ok": True,
                "command": 'echo "subprocess.Popen( shell=True,  # nosec-begin B602 # nosec-end []"',
                "output_preview": "subprocess.Popen( shell=True,  # nosec-begin B602 # nosec-end\n[]",
            },
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=False,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        skill_required_checks=[
            {
                "skill": "line-suppression-directives",
                "text": "Before finishing, run the literal probe.",
                "snippets": ["subprocess.Popen(", "shell=True,  # nosec-begin B602", "# nosec-end"],
                "expected_outputs": ["[]"],
            }
        ],
        attempt=0,
    )
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_skill_required_checks" in failed_ids
    assert report["passed"] is False


def test_echo_does_not_count_as_verification_B10() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix bug",
        response_text="Done.",
        tool_events=[
            {"name": "diff.create", "ok": True, "command": "", "path": "thomas/core/config.py"},
            {"name": "shell.exec", "ok": True, "command": "echo verified"},
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    assert report["signals"]["verification_after_write_detected"] is False
    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "coding_verification" in failed_ids
    assert report["passed"] is False


def test_alternate_shell_write_forms_count_as_writes_B11() -> None:
    forms = [
        "python -c \"open('thomas/core/config.py','w').write('bad engineering')\"",
        "python -c \"from pathlib import Path; Path('thomas/core/config.py').open('w').write('bad')\"",
        "python -c \"import pathlib; pathlib.Path('thomas/core/config.py').touch()\"",
        "powershell -Command \"[IO.File]::WriteAllText('thomas/core/config.py','bad')\"",
        "node -e \"require('fs').writeFileSync('thomas/core/config.py','bad')\"",
    ]
    for cmd in forms:
        report = evaluate_rules(
            route_path="coding_task",
            prompt_text="touch up config",
            response_text="Done.",
            tool_events=[{"name": "shell.exec", "ok": True, "command": cmd}],
            requested_job_type="coding",
            config_errors=[],
            unknown_core_keys=[],
            require_verification_for_coding=True,
            require_tests_for_code_edits=False,
            require_monolith_guard_for_coding=False,
            attempt=0,
        )
        assert report["signals"]["writes_detected"] is True, f"write not detected for: {cmd}"
        assert report["passed"] is False, f"gate did not fail for: {cmd}"


def test_git_topology_mutation_fails_praxis_gate() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="verify in a clean copy",
        response_text="Done.",
        tool_events=[
            {
                "name": "shell.exec",
                "ok": True,
                "command": "git clone https://example.invalid/thomas.git C:/tmp/thomas-copy",
            }
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=False,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )

    failed_ids = {c["id"] for c in report["checks"] if c["required"] and not c["passed"]}
    assert "git_topology_protection" in failed_ids
    assert report["signals"]["git_topology_mutation_detected"] is True
    assert report["passed"] is False


def test_inert_shell_commands_do_not_verify_B15() -> None:
    # B15: a successful but inert shell command after a write must NOT satisfy
    # the post-write verification requirement. Only real verifiers (test/lint/
    # check) count.
    for inert in ["pwd", "sleep 1", "python -c pass", "node -e console.log(1)", "powershell -Command Write-Host hi"]:
        report = evaluate_rules(
            route_path="coding_task",
            prompt_text="fix",
            response_text="done",
            tool_events=[
                {"name": "diff.create", "ok": True, "command": "", "path": "thomas/core/config.py"},
                {"name": "shell.exec", "ok": True, "command": inert},
            ],
            requested_job_type="coding",
            config_errors=[],
            unknown_core_keys=[],
            require_verification_for_coding=True,
            require_tests_for_code_edits=False,
            require_monolith_guard_for_coding=False,
            attempt=0,
        )
        assert report["signals"]["verification_after_write_detected"] is False, f"inert verified: {inert}"
        assert report["passed"] is False, f"gate passed with inert verifier: {inert}"


def test_real_verifier_after_write_still_passes() -> None:
    report = evaluate_rules(
        route_path="coding_task",
        prompt_text="fix",
        response_text="done",
        tool_events=[
            {"name": "diff.create", "ok": True, "command": "", "path": "thomas/core/config.py"},
            {"name": "shell.exec", "ok": True, "command": "python -m pytest -q tests/test_config.py"},
        ],
        requested_job_type="coding",
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=False,
        require_monolith_guard_for_coding=False,
        attempt=0,
    )
    assert report["signals"]["verification_after_write_detected"] is True
