"""The runner's reports and selection files are never inside the tests' own Thomas folders (2026-10-27).

tests/conftest.py treats THOMAS_DATA_DIR as real Thomas data and fails a session that opens anything in it. The proof
sandbox pointed THOMAS_DATA_DIR at the folder the runner keeps its reports in, so every shard that read its selection
file or wrote its JUnit report failed its session with every test passed: reproduced on 3603b9's first shard, "20
passed", exit 1, "REAL THOMAS DATA ACCESS ... reports\\shard-1.select.json was opened by this test run". Since
2026-10-26 that exit 1 makes a check incomplete, so long checks were held as "dev-side".
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.proof.environment import sandbox_env

FOLDERS = (
    "THOMAS_DATA_DIR",
    "THOMAS_HOME",
    "THOMAS_STATE_DIR",
    "THOMAS_RUNTIME_DIR",
    "THOMAS_GREEN_ROOT",
    "THOMAS_CAGE_ROOT",
    "THOMAS_PROJECT_ROOT",
)


def test_the_tests_thomas_folders_sit_apart_from_the_runners_reports(tmp_path: Path) -> None:
    data = tmp_path / "change"
    env = sandbox_env(tmp_path / "work", data)
    reports = (data / "reports" / "shard-1.xml").resolve()
    for key in FOLDERS:
        folder = Path(env[key]).resolve()
        assert data.resolve() in folder.parents, key  # still inside the run's own scratch space
        assert folder not in reports.parents and folder != reports, key
    assert Path(env["THOMAS_DB_PATH"]).parent == Path(env["THOMAS_DATA_DIR"])
    assert Path(env["THOMAS_DATA_DIR"]).is_dir()


def test_each_shard_still_has_folders_of_its_own(tmp_path: Path) -> None:
    one = sandbox_env(tmp_path / "work", tmp_path / "data" / "shard-1")
    two = sandbox_env(tmp_path / "work", tmp_path / "data" / "shard-2")
    assert all(one[key] != two[key] for key in FOLDERS)
