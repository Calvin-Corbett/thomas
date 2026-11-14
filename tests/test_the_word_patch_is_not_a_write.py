"""Regression tests for patch-command write detection in Build completion checks."""

import pytest

from thomas.core.rules_of_road import evaluate_rules


def _report_for(*commands: str) -> dict:
    return evaluate_rules(
        route_path="coding_task",
        prompt_text="Check the Build run before finishing.",
        response_text="Checks passed.",
        tool_events=[{"name": "shell.exec", "ok": True, "command": command, "path": ""} for command in commands],
        requested_job_type=None,
        config_errors=[],
        unknown_core_keys=[],
        require_verification_for_coding=True,
        require_tests_for_code_edits=True,
        require_monolith_guard_for_coding=True,
        attempt=0,
    )


def test_read_only_check_printing_patch_sha_does_not_create_a_write() -> None:
    check = (
        'python -c "from pathlib import Path; import hashlib; import subprocess; '
        "data = Path('README.md').read_bytes(); "
        "subprocess.run(['git', 'diff', '--cached'], check=True); "
        "print('Patch SHA-256', hashlib.sha256(data).hexdigest())\""
    )
    report = _report_for("python -m pytest tests/test_rules_of_road.py -q", check)

    assert report["signals"]["tests_detected"] is True
    assert report["signals"]["writes_detected"] is False
    assert report["passed"] is True


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/forge/changelog_fragments.py check changelog.d/the-word-patch-is-not-a-write.md",
        "cat docs/patch-notes.md",
        "echo patch notes",
        "grep -n patch file.txt",
    ],
)
def test_reading_hyphenated_patch_filename_does_not_create_a_write(command: str) -> None:
    report = _report_for("python -m pytest tests/test_rules_of_road.py -q", command)

    assert report["signals"]["writes_detected"] is False
    assert report["passed"] is True


@pytest.mark.parametrize(
    "command",
    [
        "patch -p1 < change.diff",
        "cd src && patch -p1 -i change.diff",
        "patch original.txt updated.txt",
        'bash -c "patch -p1 -i change.diff"',
        "cat change.diff | patch -p1",
        "git format-patch -1 HEAD",
        "echo ready; patch -p1 -i change.diff",
        "echo ready & patch -p1 -i change.diff",
        "(patch -p1 -i change.diff)",
        "printf ready\npatch -p1 -i change.diff",
        "PATCH -p1 -i change.diff",
        "patch < change.diff",
        "patch -p1 <change.diff",
        "patch<change.diff",
        "sudo patch a.c fix.diff",
        "env X=1 patch a.c fix.diff",
        "nice patch a.c fix.diff",
        "time patch a.c fix.diff",
        "xargs patch a.c",
        "find . -name x -exec patch a.c fix.diff",
        "cmd /c patch a.c fix.diff",
        'powershell -Command "patch a.c fix.diff"',
        "`patch a.c fix.diff`",
    ],
)
def test_real_patch_commands_still_count_as_writes(command: str) -> None:
    report = _report_for(command)

    assert report["signals"]["writes_detected"] is True


@pytest.mark.parametrize("command", ["git apply change.diff", "apply_patch change.diff"])
def test_other_patch_writes_remain_detected(command: str) -> None:
    assert _report_for(command)["signals"]["writes_detected"] is True
