"""Durable team receipts preserve completed work and resume unfinished work."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from thomas.forge.anvil.build_agent_workspace import current_fingerprint, fingerprint
from thomas.forge.anvil.build_team_ledger import TeamLedger, _plain


def jobs():
    return [{"title": "Builder", "instructions": "Create file", "path": "a.txt"}] * 3


def test_ordinary_directory_link_counts_do_not_prevent_team_recovery(monkeypatch, tmp_path):
    original = Path.stat

    def posix_directory_links(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if stat.S_ISDIR(result.st_mode):
            values = list(result)
            values[3] = max(2, result.st_nlink)
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", posix_directory_links)
    assert _plain(tmp_path) == tmp_path
    with TeamLedger.start(tmp_path, jobs(), "gpt-5.6-luna") as ledger:
        assert TeamLedger.recover(tmp_path) == []
    assert TeamLedger.recover(tmp_path) == [ledger.data["team_id"]]


def test_live_os_lease_prevents_false_interruption_then_recovers_only_unfinished(tmp_path):
    with TeamLedger.start(tmp_path, jobs(), "gpt-5.6-luna") as ledger:
        ledger.update(0, "integrated", receipt="retained/receipt.json")
        ledger.update(1, "running", child_id="child_0123456789ab")
        candidate = ledger.folder / "candidate.txt"
        candidate.write_text("retained candidate", encoding="utf-8")
        assert TeamLedger.recover(tmp_path) == []
        target = ledger.folder / "team.json"
        assert json.loads(target.read_text())["state"] == "running"
    assert TeamLedger.recover(tmp_path) == [ledger.data["team_id"]]
    recovered = json.loads(target.read_text())
    assert recovered["state"] == "interrupted"
    assert [child["state"] for child in recovered["children"]] == ["integrated", "interrupted", "interrupted"]
    assert recovered["children"][0]["receipt"] == "retained/receipt.json"
    assert candidate.read_text() == "retained candidate" and not (tmp_path / "a.txt").exists()
    assert TeamLedger.recover(tmp_path) == []


def test_finished_receipts_and_damaged_records_are_not_replayed(tmp_path):
    with TeamLedger.start(tmp_path, jobs(), "gpt-5.6-luna") as ledger:
        ledger.finish("cancelled")
    original = (ledger.folder / "team.json").read_bytes()
    with TeamLedger.start(tmp_path, jobs(), "gpt-5.6-luna") as damaged:
        (damaged.folder / "team.json").write_text("invalid json", encoding="utf-8")
    assert TeamLedger.recover(tmp_path) == []
    assert (ledger.folder / "team.json").read_bytes() == original
    assert (damaged.folder / "team.json").read_text() == "invalid json"


def test_receipt_hardlink_is_rejected_without_mutating_external_file(tmp_path):
    with TeamLedger.start(tmp_path, jobs(), "gpt-5.6-luna") as ledger:
        target = ledger.folder / "team.json"
        outside = tmp_path / "outside.json"
        outside.write_bytes(target.read_bytes())
        target.unlink()
        os.link(outside, target)
        before = outside.read_bytes()
        with pytest.raises(ValueError, match="links"):
            ledger.update(0, "running")
        assert outside.read_bytes() == before
    assert TeamLedger.recover(tmp_path) == []
    assert outside.read_bytes() == before


def test_matching_team_resumes_only_unfinished_children(tmp_path):
    work = [{"title": str(i), "instructions": "write", "path": f"{i}.txt"} for i in range(2)]
    (tmp_path / "0.txt").write_text("completed", encoding="utf-8")
    with TeamLedger.start(tmp_path, work, "luna") as ledger:
        team_id = ledger.data["team_id"]
        ledger.update(0, "integrated", integrated_file=current_fingerprint(tmp_path, "0.txt"))
        ledger.update(1, "running", child_id="child_0123456789ab")
    assert TeamLedger.recover(tmp_path) == [team_id]
    with TeamLedger.start_or_resume(tmp_path, work, "luna") as resumed:
        assert resumed.data["team_id"] == team_id
        assert [child["state"] for child in resumed.data["children"]] == ["integrated", "queued"]
        assert "child_id" not in resumed.data["children"][1]
        resumed.finish("completed")


def test_resume_refuses_to_replay_when_integrated_output_changed(tmp_path):
    work = [{"title": "one", "instructions": "write", "path": "one.txt"}]
    (tmp_path / "one.txt").write_text("integrated", encoding="utf-8")
    with TeamLedger.start(tmp_path, work, "luna") as ledger:
        ledger.update(0, "integrated", integrated_file=current_fingerprint(tmp_path, "one.txt"))
        ledger.finish("failed")
    (tmp_path / "one.txt").write_text("later owner edit", encoding="utf-8")
    with pytest.raises(ValueError, match="Previously integrated file changed"):
        with TeamLedger.start_or_resume(tmp_path, work, "luna"):
            pass


def test_resume_detects_applied_candidate_after_crash_without_reapplying(tmp_path):
    work = [{"title": "one", "instructions": "write", "path": "one.txt"}]
    with TeamLedger.start(tmp_path, work, "luna") as ledger:
        workspace = tmp_path / ".thomas/evolve/agent/team/child_0123456789ab"
        (workspace / "workspace").mkdir(parents=True)
        (workspace / "workspace/one.txt").write_text("applied", encoding="utf-8")
        (tmp_path / "one.txt").write_text("applied", encoding="utf-8")
        receipt = workspace / "receipt.json"
        receipt.write_text(
            json.dumps({"path": "one.txt", "state": "candidate", "candidate_file": fingerprint(b"applied")}),
            encoding="utf-8",
        )
        ledger.update(0, "running", receipt=str(receipt.relative_to(tmp_path)))
    TeamLedger.recover(tmp_path)
    with TeamLedger.start_or_resume(tmp_path, work, "luna") as resumed:
        assert resumed.data["children"][0]["state"] == "integrated"
        assert resumed.data["children"][0]["integrated_file"] == current_fingerprint(tmp_path, "one.txt")
