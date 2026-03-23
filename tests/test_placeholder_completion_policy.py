from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from thomas.core.placeholder_policy import parse_placeholder_fields, placeholder_policy_report


def test_parse_placeholder_fields_extracts_required_note() -> None:
    text = "\n".join(
        [
            "# Source placeholder for sample.py",
            "# placeholder-why: needed during migration.",
            "# placeholder-scope_to_finish: restore the runtime.",
            "# placeholder-owner: thomas/core",
            "# placeholder-exit_rule: fail fast until restored.",
            "# placeholder-acceptance: tests pass without placeholder state.",
        ]
    )

    fields = parse_placeholder_fields(text)

    assert fields == {
        "why": "needed during migration.",
        "scope_to_finish": "restore the runtime.",
        "owner": "thomas/core",
        "exit_rule": "fail fast until restored.",
        "acceptance": "tests pass without placeholder state.",
    }


def test_placeholder_policy_report_flags_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text("# Source placeholder for demo.py\n", encoding="utf-8")

    report = placeholder_policy_report(path)

    assert report["is_placeholder"] is True
    assert report["ok"] is False
    assert "why" in report["missing_fields"]


def test_placeholder_completion_policy_script_passes_on_repo() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "scripts/check_placeholder_completion_policy.py", "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["placeholder_file_count"] >= 1
