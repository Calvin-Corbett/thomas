"""--until ends the window; it does not stop a project's own rows (spec 2026-10-12 Step 0).

The baseline goes into the repo, so a project that was launched before --until and landed after it must be followed
to its landing, and a run that ended after --until must not read as still running and absorb every later phase.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import praxis_timeline
from scripts.praxis import timeline_report
from scripts.praxis import timeline_sources as sources

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
CID = "fc_20261009T120000_aaaa1111"
EXEC = "thomas-tl1"
UNTIL = T0 + 900
NOW = T0 + 5000


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A project whose run was cut at T0+700 (no agent turn), handed in at T0+850 and landed at T0+1001."""
    catalog, cage, out = tmp_path / "catalog", tmp_path / "cage", tmp_path / "out"
    turns = [{"role": "user", "text": "Make the button blue", "ts": _iso(T0 + 30)}]
    project = {"execution_id": EXEC, "repairs": []}
    conversation = {"id": CID, "title": "t", "created_at": _iso(T0), "updated_at": _iso(T0 + 1001), "turns": turns,
                    "thomas_project": project}  # fmt: skip
    _json(catalog / sources.CONVERSATIONS / f"{CID}.json", conversation)
    sid = f"self-{EXEC}"
    _json(cage / "processed" / sid / "submission.json", {"execution_id": EXEC, "submitted_at": T0 + 850})
    _json(cage / "outbox" / f"{sid}.verdict.json", {"status": "landed", "ts": T0 + 1001})
    clocks = [
        {"started_at": _iso(T0 + start), "execution_id": EXEC, "stages": {"check_for_hand_in": {
            "start": _iso(T0 + start), "end": _iso(T0 + start + 10), "seconds": 10.0}}}
        for start in (500, 950)
    ]  # fmt: skip
    clocks_file = catalog / sources.AGENT_DIR / sources.CLOCKS_FILE
    clocks_file.write_text("\n".join(json.dumps(record) for record in clocks) + "\n", encoding="utf-8")
    transcript = (T0 + 31, T0 + 700, 10.0, "transcript-0123456789abcdef.txt")
    monkeypatch.setattr(praxis_timeline, "transcript_index", lambda agent_dir, since: [transcript])
    return SimpleNamespace(catalog=catalog, cage=cage, out=out)


def _argv(tree: SimpleNamespace, until: float, *more: str) -> list[str]:
    return [
        "--since", "2026-10-09T11:58:20", "--until", _iso(until), "--catalog-root", str(tree.catalog),
        "--cage-root", str(tree.cage), "--green-root", str(tree.catalog / "no-greens"), "--no-git",
        "--out-dir", str(tree.out), *more,
    ]  # fmt: skip


def _run(tree: SimpleNamespace, *more: str, until: float = UNTIL) -> dict:
    assert praxis_timeline.main(_argv(tree, until, *more), now=NOW, tz=timezone.utc) == 0
    return json.loads((tree.out / "timeline.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("until", [UNTIL, T0 + 600], ids=["after the run's last write", "before the run's last write"])
def test_a_project_that_landed_after_until_is_followed_to_its_landing(tree: SimpleNamespace, until: float) -> None:
    payload = _run(tree, until=until)

    [row] = payload["projects"]
    assert row["state"] == "landed" and payload["aggregate"]["projects_landed"] == 1
    [run] = row["runs"]
    assert run["outcome"].startswith("cut without") and run["end"] == T0 + 700, "it was not running at --until"
    spent = row["phases_s"]
    assert spent["run:first_build"] == pytest.approx(670, abs=0.5), "no later phase was absorbed by the run"
    assert sum(spent.values()) == pytest.approx(1001, abs=0.5), "from launch to the landing, after --until"
    assert "open_now" not in spent
    assert row["totals"]["launch_to_landed_min"] == pytest.approx(1001 / 60, abs=0.01)


def test_the_window_shares_the_days_and_the_clocks_stop_at_until(tree: SimpleNamespace) -> None:
    payload = _run(tree)

    window = payload["window"]
    assert (window["seconds"], window["in_flight_avg"]) == (1000.0, 0.9), "launch to --until, not to the landing"
    assert (window["building_busy_share"], window["busy_runs_share"]) == (0.85, 0.67)
    [day] = payload["per_day"]
    assert (day["day"], day["landed"], day["building_busy_share"]) == ("2026-10-09", 0, 0.85)
    assert payload["clocks"]["records"] == 1, "the check clock that started after --until is not in the window"
    assert payload["meta"]["until"] == "2026-10-09T12:15+00:00"


def test_every_file_the_timeline_writes_has_unix_line_ends(tree: SimpleNamespace) -> None:
    target = tree.out / "baseline.json"

    _run(tree, "--baseline-out", str(target))

    for path in (tree.out / "timeline.json", tree.out / "timeline.md", target):
        assert b"\r" not in path.read_bytes(), f"{path.name} would differ between Windows and Linux"


def test_the_notes_and_the_docstring_say_what_until_covers() -> None:
    said = {note for note in timeline_report.NOTES if "--until" in note}
    assert len(said) == 1
    [note] = said
    for words in ("launch filter", "check clocks", "window shares", "per_day", "extraction time", "runs", "phases"):
        assert words in note, words
    ratchet = [note for note in timeline_report.NOTES if "ratchet" in note]
    assert len(ratchet) == 1 and "before --since" in ratchet[0] and "aggregate" in ratchet[0]
    doc = " ".join((praxis_timeline.__doc__ or "").split())
    for words in ("launch filter", "extraction time", "ratchet", "before --since"):
        assert words in doc, words
