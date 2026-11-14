"""Each `bootdoctor` command reads the config file it was told to, including the memory folder that file names.

The offline checks read thomas.toml for parse errors and the memory folder for databases. Left to their defaults
they look at <root>/thomas.toml and the current folder, and call the wrong file fine. The commands below each hand
the config over at a different call, and only `check --config` and the direct runner were covered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
import thomas.core.boot_doctor as boot_doctor
from tests._bootdoctor_fakes import fake_owners, free_port, isolate_offline_checks


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    fake_owners(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))


def test_check_looks_in_the_memory_folder_the_config_names(tmp_path: Path, capsys) -> None:
    # repair.cmd runs the check for a person whose databases sit under a [memory] root set in thomas.toml.
    mem = tmp_path / "kept_elsewhere"
    damaged = mem / ".thomas" / "runs.sqlite3"
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"not a database at all" * 5)
    config = tmp_path / "config" / "thomas.toml"
    config.parent.mkdir()
    config.write_text(f"[memory]\nroot = '{mem.as_posix()}'\n", encoding="utf-8")

    exit_code = bd_main.main(["check", "--root", str(tmp_path), "--port", "22127", "--config", str(config)])

    assert exit_code == 3
    assert re.search(r"\[fail\] database_integrity: .*runs\.sqlite3: file is not a database", capsys.readouterr().out)
    assert damaged.exists()


@pytest.mark.parametrize("command", ["report", "rescue", "chat"])
def test_a_report_made_by_any_command_reads_the_config_it_was_given(tmp_path: Path, command: str) -> None:
    # The file is not <root>/thomas.toml, so a command that forgets to pass it on reads an absent file and says ok.
    bad = tmp_path / "elsewhere" / "bad.toml"
    bad.parent.mkdir()
    bad.write_text("[server\nport = = 1\n", encoding="utf-8")
    report = tmp_path / "report.txt"
    argv = [command, "--config", str(bad), "--root", str(tmp_path), "--port", str(free_port())]
    argv += ["--report", str(report), "--no-ai", "--no-auto-repair", "--no-interactive"]

    bd_main.main(argv)

    text = report.read_text(encoding="utf-8")
    assert f"[fail] config_file: {bad.resolve()}" in text
    assert "line 1" in text
