"""What a load run's change looks like, what each check's entry says it ran, and how the run writes its files.

Spec 2026-10-12 Step 0. The load run's numbers go into the repo as a baseline, so a check that failed on the
formatting of the harmless change, or a summary that does not say which tests ran, would make them mean less.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts.praxis import check_load

from tests.test_the_check_load_run_starts_checks_together import _fake_result, _install, _load
from thomas.server.precard import check, clocks

SHAPES = {
    "a function": "def total(values):\n    return sum(values)\n",
    "a class": "class Holder:\n    size = 1\n",
    "a statement": "SIZE = 1\n",
    "an if block": "SIZE = 1\nif SIZE:\n    OTHER = 2\n",
}


def _ruff(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "ruff", *arguments]
    return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)


@pytest.mark.skipif(_ruff("--version").returncode != 0, reason="ruff is not installed here")
@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["unix line ends", "windows line ends"])
@pytest.mark.parametrize("body", list(SHAPES.values()), ids=list(SHAPES))
def test_a_module_ending_with_the_mark_still_passes_ruff_format_and_check(
    tmp_path: Path, body: str, ending: str
) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(body.replace("\n", ending).encode("utf-8"))

    check_load._mark(target)

    for arguments in (("format", "--check", "--line-length", "120"), ("check", "--select", "E,W,F,I")):
        done = _ruff(arguments[0], "--isolated", *arguments[1:], str(target))
        assert done.returncode == 0, f"{arguments[0]}: {done.stdout}{done.stderr}"


def _checking(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
    time.sleep(0.05)
    clocks.note("selected_files", 31)
    clocks.note("change_tests_seen", 412)
    clocks.note("dev_tests_seen", 410)
    return check.Checked(check.PASSED, "checked")


def test_each_checks_entry_says_how_many_files_and_tests_it_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(tmp_path, monkeypatch, _checking)

    result = _load(tmp_path, "t9", copies=2)

    for entry in result["checks"]:
        assert (entry["selected_files"], entry["change_tests_seen"], entry["dev_tests_seen"]) == (31, 412, 410)
    assert check_load.disk_record(result)["selected_files"] == [31, 31], "counts only, one for each check"


def test_the_disk_record_holds_counts_and_not_which_modules_were_checked() -> None:
    result = _fake_result(time.time(), [])
    result["checks"][0]["selected_files"] = 31

    record = check_load.disk_record(result)

    assert record["selected_files"] == [31, None], "a check that never selected has no count, and keeps its place"
    assert "secret_module" not in json.dumps(record) and "load-t7" not in json.dumps(record)


def test_the_run_writes_its_files_with_unix_line_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/a.py", 25)] * 2)
    monkeypatch.setattr(check_load, "run_load", lambda *args, **kwargs: _fake_result(time.time(), []))
    out, disk = tmp_path / "out", tmp_path / "repo" / "disk.json"

    code = check_load.main(["--count", "2", "--blue", str(tmp_path), "--out-dir", str(out), "--disk-out", str(disk)])

    assert code == 0
    written = [*out.glob("*.json"), disk]
    assert len(written) == 2
    for path in written:
        assert b"\r" not in path.read_bytes(), f"{path.name} would differ between Windows and Linux"
    capsys.readouterr()


def test_the_timeline_line_names_the_folder_the_clocks_were_written_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/a.py", 25)] * 2)
    seen: list[Path] = []

    def run(blue: Path, catalog: Path, picked: list, *, stamp: str, **kwargs: object) -> dict:
        seen.append(Path(catalog))
        return _fake_result(time.time(), [])

    monkeypatch.setattr(check_load, "run_load", run)
    spaced = tmp_path / "my checkout"
    spaced.mkdir()

    check_load.main(["--count", "2", "--blue", str(spaced), "--out-dir", str(tmp_path / "out")])

    last = capsys.readouterr().out.splitlines()[-1]
    assert seen == [spaced], "the clocks went into the checkout the copies were made from"
    assert last.endswith(f' --catalog-root "{spaced}"'), "a path with a space is quoted so the line can be pasted"
