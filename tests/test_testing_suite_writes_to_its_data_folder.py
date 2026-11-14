from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from thomas.core.testing_suite import CycleResult
from thomas.core.testing_suite import TestingSuite as _TestingSuite


def test_suite_writes_results_and_report_only_in_its_data_folder(tmp_path: Path, monkeypatch) -> None:
    work_dir = tmp_path / "work"
    data_dir = tmp_path / "data"
    work_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.chdir(work_dir)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("THOMAS_PROFILE", "isolated")

    suite = _TestingSuite()
    result = CycleResult(cycle=1, autonomy_accuracy_measured=False)
    suite._results.append(result)
    suite._write_result(result)
    suite._generate_report()

    output_dir = data_dir / "isolated" / "testing_suite"
    results_file = output_dir / "thomas_test_results.jsonl"
    report_file = output_dir / f"thomas_test_report_{date.today().isoformat()}.md"
    assert json.loads(results_file.read_text(encoding="utf-8")) == result.to_dict()
    assert "# Thomas Test Report" in report_file.read_text(encoding="utf-8")
    assert list(work_dir.iterdir()) == []


def test_write_failures_are_visible_in_suite_summary(tmp_path: Path, monkeypatch) -> None:
    work_dir = tmp_path / "work"
    data_dir = tmp_path / "data"
    work_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.chdir(work_dir)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    (data_dir / "testing_suite").write_text("not a directory", encoding="utf-8")

    suite = _TestingSuite()
    result = CycleResult(cycle=1, autonomy_accuracy_measured=False)
    suite._results.append(result)
    suite._write_result(result)
    result_summary = suite.summary_text()
    assert "results write failed" in result_summary
    assert "testing_suite" in result_summary
    assert "0 cycles" not in result_summary

    suite._generate_report()
    report_summary = suite.summary_text()
    assert "report write failed" in report_summary
    assert "testing_suite" in report_summary
    assert "last write failure" in report_summary
    assert datetime.fromisoformat(report_summary.split("last write failure at ", 1)[1].split(": report", 1)[0])
    assert list(work_dir.iterdir()) == []
