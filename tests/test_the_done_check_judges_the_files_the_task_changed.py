"""The done-check holds a task to the file-size limit on what it changed, not on old debt.

The harness ran the monolith guard over the whole repo and failed the run on any
violation. On Thomas's own code that meant every Build task, even one that wrote a
two-byte file, came back "not finished yet" because of old oversized files it never
touched (scripts/breakglass_auth.py, 1,386 lines), and the agent was pushed to edit
a protected gate script to "fix" it. The commit gate already judges changed files
only; the done-check now does the same.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from thomas.agent.harness_guard import GUARD_RELATIVE, changed_paths, run_monolith_guard

_VIOLATIONS = [
    {"path": "scripts/breakglass_auth.py", "lines": 1386, "hard_limit": 1200, "reason": "old debt"},
    {"path": "thomas/core/llm_client.py", "lines": 904, "hard_limit": 1200, "reason": "changed and too big"},
]


def _fake_guard(root: Path, violations: list[dict]) -> Path:
    """A stand-in guard that reports fixed violations, like the real one's --json output."""
    script = root / GUARD_RELATIVE
    script.parent.mkdir(parents=True, exist_ok=True)
    failing = bool(violations)
    payload = json.dumps({"ok": not failing, "violations": violations})
    script.write_text(
        "import sys\n"
        f"PAYLOAD = {payload!r}\n"
        "if '--json' in sys.argv:\n"
        "    print(PAYLOAD)\n"
        "else:\n"
        f"    print({'Monolith guard FAILED' if failing else 'Monolith guard: PASS'!r})\n"
        f"sys.exit({1 if failing else 0})\n",
        encoding="utf-8",
    )
    return script


def test_old_debt_in_untouched_files_does_not_fail_the_task(tmp_path: Path) -> None:
    script = _fake_guard(tmp_path, _VIOLATIONS[:1])

    receipt = run_monolith_guard(tmp_path, only_paths=["probe/PROBE.txt"], script=script)

    assert receipt["ok"] is True
    assert "not counted" in receipt["detail"]


def test_a_changed_file_over_the_limit_still_fails(tmp_path: Path) -> None:
    script = _fake_guard(tmp_path, _VIOLATIONS)

    receipt = run_monolith_guard(tmp_path, only_paths=["thomas/core/llm_client.py"], script=script)

    assert receipt["ok"] is False
    judged = receipt["detail"].split("not counted")[0]
    assert "thomas/core/llm_client.py" in judged
    assert "breakglass_auth" not in judged


def test_absolute_windows_paths_match(tmp_path: Path) -> None:
    script = _fake_guard(tmp_path, _VIOLATIONS)

    receipt = run_monolith_guard(
        tmp_path, only_paths=[str(tmp_path / "thomas" / "core" / "llm_client.py")], script=script
    )

    assert receipt["ok"] is False


def test_a_task_that_waives_its_own_limit_fails(tmp_path: Path) -> None:
    # Found live 2026-09-19: pushed by the whole-repo check, a Build agent rewrote the
    # guard's waiver file to excuse every violation, renewing an expired waiver and
    # pushing expiry dates to 2027. A task may not change the guard that judges it.
    script = _fake_guard(tmp_path, [])

    receipt = run_monolith_guard(tmp_path, only_paths=["docs/monolith_guard_baseline.json", "app.py"], script=script)

    assert receipt["ok"] is False
    assert "docs/monolith_guard_baseline.json" in receipt["detail"]


def test_a_task_that_edits_the_guard_script_fails(tmp_path: Path) -> None:
    script = _fake_guard(tmp_path, [])

    receipt = run_monolith_guard(tmp_path, only_paths=[GUARD_RELATIVE.as_posix()], script=script)

    assert receipt["ok"] is False


def test_without_a_list_the_whole_repo_is_judged_as_before(tmp_path: Path) -> None:
    script = _fake_guard(tmp_path, _VIOLATIONS[:1])

    receipt = run_monolith_guard(tmp_path, script=script)

    assert receipt["ok"] is False


def test_files_git_sees_as_changed_are_listed(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "patched_new.py").write_text("y = 1\n", encoding="utf-8")

    assert changed_paths(tmp_path) == {"a.py", "patched_new.py"}


def test_outside_git_there_is_no_changed_list(tmp_path: Path) -> None:
    assert changed_paths(tmp_path) is None


def test_a_guard_written_in_the_workspace_is_never_run(tmp_path: Path) -> None:
    folder = tmp_path / "worker"
    folder.mkdir()
    marker = tmp_path / "planted_guard_ran"
    script = folder / GUARD_RELATIVE
    script.parent.mkdir(parents=True)
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
        'print(\'{"ok": true, "violations": []}\')\n',
        encoding="utf-8",
    )
    (folder / "app.py").write_text("x = 1\n" * 1300, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    subprocess.run(["git", "add", "app.py", GUARD_RELATIVE.as_posix()], cwd=folder, check=True)

    receipt = run_monolith_guard(folder, only_paths=["app.py"])

    assert not marker.exists()
    assert receipt["ok"] is False
    assert "app.py" in receipt["detail"]
