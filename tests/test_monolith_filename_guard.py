from pathlib import Path

import pytest
from scripts.forge.gates.monolith_filename_guard import _is_forbidden_part_file, _scan


@pytest.mark.parametrize(
    "path",
    [
        Path("thomas/server/app_part03.py"),
        Path("thomas/server/app.part03.py"),
        Path("thomas/server/web/js/part-001.js"),
        Path("thomas/server/web/js/part-032b.js"),
        Path("thomas/server/web/js/app_parts/runtime-loader.js"),
    ],
)
def test_forbidden_part_file_patterns_match_agent_policy(path: Path) -> None:
    assert _is_forbidden_part_file(path) is True


@pytest.mark.parametrize(
    "path",
    [
        Path("thomas/server/web/js/app_parts/GUARDRAILS.md"),
        Path("thomas/server/web/js/app_parts/README.md"),
        Path("thomas/marketplace/groupchat/participant.py"),
        Path("tests/test_preferences_partial_patch.py"),
    ],
)
def test_forbidden_part_file_patterns_allow_non_split_names(path: Path) -> None:
    assert _is_forbidden_part_file(path) is False


def test_changed_scan_reports_dash_part_files(tmp_path: Path) -> None:
    part_file = tmp_path / "thomas" / "server" / "web" / "js" / "part-001.js"
    part_file.parent.mkdir(parents=True)
    part_file.write_text("console.log('split');\n", encoding="utf-8")

    clean_file = tmp_path / "thomas" / "server" / "web" / "js" / "app-runtime.js"
    clean_file.write_text("console.log('clean');\n", encoding="utf-8")

    violations = _scan(
        tmp_path,
        staged_only=False,
        changed_paths=[
            "thomas/server/web/js/part-001.js",
            "thomas/server/web/js/app-runtime.js",
        ],
    )

    assert violations == [
        {
            "path": "thomas/server/web/js/part-001.js",
            "reason": "legacy split filename pattern",
        }
    ]
