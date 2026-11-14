"""The Praxis timeline reports a project it cannot read, and ends a project that has gone quiet (spec 2026-10-12 Step 0).

Found by setting the landed tool beside a scratch timeline of the same week. Two stopped projects whose only copy sat
in the caged account's green, which this account cannot read, were skipped without a word. And a stopped project was
followed to the extraction time as if it were still being built, so the Part 3 building share read 0.835, not 0.318.
The baseline is published, so it must not miss a project silently or count a stopped one as open.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts import praxis_timeline
from scripts.praxis import timeline_report
from scripts.praxis import timeline_runs as runs
from scripts.praxis import timeline_sources as sources

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
CID = "fc_20261009T120000_aaaa1111"
LATE = "fc_20261011T090000_late0002"  # launched after the window the CLI tests ask for
EXEC = "thomas-tl1"
HOUR = 3600.0


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _json(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _stopped(cid: str = CID, *, created: float = T0, ended: float = T0 + 600, **project: object) -> dict:
    """A project whose one Build run was stopped at *ended*; nothing was handed in."""
    turns = [
        {"role": "user", "text": "Make the button blue", "ts": _iso(created + 30)},
        {"role": "agent", "ts": _iso(ended), "ok": False, "outcome": "stopped", "changed_files": [], "run_id": "r1"},
    ]
    return {"id": cid, "title": "t", "created_at": _iso(created), "updated_at": _iso(ended), "turns": turns,
            "thomas_project": {"execution_id": EXEC, "repairs": [], **project}}  # fmt: skip


def _collect(tmp_path: Path, conversation: dict, now: float) -> dict:
    greens = tmp_path / "green"
    _json(greens / "work" / EXEC / sources.CONVERSATIONS / f"{conversation['id']}.json", conversation)
    paths = sources.Paths(tmp_path / "catalog", tmp_path / "cage", greens)
    return praxis_timeline.collect(paths, since=T0 - 1, now=now, tz=timezone.utc)


def test_the_paths_and_the_quiet_hour_equal_the_servers(tmp_path: Path) -> None:
    from thomas.forge.anvil import forge_code_conversations
    from thomas.server import thomas_project_quiet

    assert tmp_path / sources.PROJECT_REGISTRY == forge_code_conversations._registry_path(tmp_path)
    assert runs.PROJECT_QUIET_S == thomas_project_quiet.QUIET_MAX_S


_WAITING = {"submitted_at": 1.0, "where": "inbox", "verdict_status": None}


@pytest.mark.parametrize(
    ("expected", "quiet_s", "hand_ins", "running", "parked_for_s"),
    [
        ("ended", HOUR + 1, [], False, None),
        ("open", HOUR, [], False, None),
        ("open", 60.0, [], False, None),
        ("open", HOUR + 1, [_WAITING], False, None),
        ("open", HOUR + 1, [{**_WAITING, "where": "processed", "verdict_status": "held"}], False, None),
        ("ended", HOUR + 1, [{**_WAITING, "where": "withdrawn"}], False, None),
        ("open", HOUR + 1, [], True, None),
        ("open", HOUR + 1, [], False, 60.0),
        ("ended", HOUR + 1, [], False, -60.0),
    ],
    ids=["quiet", "exactly-an-hour", "written-a-minute-ago", "hand-in-waits", "held-by-the-promoter", "withdrawn",
         "run-going", "parked-until-later", "park-is-over"],
)  # fmt: skip
def test_a_project_quiet_for_an_hour_with_nothing_waiting_has_ended(
    expected: str, quiet_s: float, hand_ins: list, running: bool, parked_for_s: float | None
) -> None:
    now = T0 + quiet_s
    conversation = {"updated_at": _iso(T0), "thomas_project": {"execution_id": EXEC}}
    if parked_for_s is not None:
        conversation["autopilot"] = {"parked_until": now + parked_for_s, "provider": "chatgpt"}
    going = [{"outcome": "running"}] if running else []

    assert runs.project_state(conversation, hand_ins, now=now, runs=going) == expected
    assert runs.project_state(conversation, hand_ins, runs=going) == "open", "with no time given it is never quiet"


def test_the_existing_rules_still_come_first_and_a_time_that_is_not_read_never_ends_a_project() -> None:
    quiet = {"updated_at": _iso(T0), "thomas_project": {}}
    late = T0 + 9 * HOUR
    landed = [{"submitted_at": 1.0, "verdict_status": "landed", "verdict_ts": 2.0}]
    refused = [{"submitted_at": 1.0, "verdict_status": "refused", "verdict_ts": 2.0}]
    repaired = {**quiet, "thomas_project": {"repairs": [{"at": _iso(T0)}]}}

    assert runs.project_state(quiet, landed, now=late) == "landed"
    assert runs.project_state({"thomas_project": {"retirement": {"outcome": "reported"}}}, [], now=T0) == "ended"
    assert runs.project_state(quiet, refused, now=T0) == "ended"
    assert runs.project_state(repaired, refused) == "open", "a repair round followed the refusal"
    assert runs.project_state(repaired, refused, now=late) == "ended", "and then it went quiet"
    for unread in ({"thomas_project": {}}, {"updated_at": "not a time", "thomas_project": {}}, {"updated_at": []}):
        assert runs.project_state(unread, [], now=late) == "open"


def test_a_stopped_green_ends_at_its_last_event_and_is_not_followed_to_extraction(tmp_path: Path) -> None:
    now = T0 + 600 + 2 * HOUR

    [row] = _collect(tmp_path / "a", _stopped(), now)["projects"]

    assert row["state"] == "ended" and "open_now" not in row["phases_s"]
    assert sum(row["phases_s"].values()) == pytest.approx(600, abs=0.5), "tracked time is its span, launch to stop"
    assert row["totals"]["tracked_total_min"] == pytest.approx(10.0) and row["totals"]["open_now_min"] == 0
    window = _collect(tmp_path / "b", _stopped(), now)["window"]
    assert window["building_busy_share"] == pytest.approx(600 / (now - T0 + 1), abs=0.002), "it stopped being built"

    fresh = _stopped("fc_20261009T123000_fresh003", created=T0 + 1800, ended=now - 60)
    [still] = _collect(tmp_path / "c", fresh, now)["projects"]
    assert still["state"] == "open", "written a minute ago: it may be mid-build"
    assert still["phases_s"]["open_now"] == pytest.approx(60, abs=0.5)


def test_a_project_bound_to_a_green_in_another_folder_is_read_through_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, bound = tmp_path / "catalog", tmp_path / "elsewhere" / "work" / EXEC
    _json(bound / sources.CONVERSATIONS / f"{CID}.json", _stopped())
    registry = {
        CID: {"project_root": str(bound)},
        "fc_20261009T130000_gone0001": {"project_root": str(tmp_path / "removed")},
        "fc_20261009T140000_bad00002": {"project_root": 5},
        "fc_20261009T150000_none0003": {"project_root": ""},
        "fc_20260101T000000_before04": {"project_root": str(bound)},
        "fc_20261009T160000_../escape": {"project_root": str(bound)},
        "fc_20261009T170000_noroot05": ["not a row"],
    }
    _json(catalog / sources.PROJECT_REGISTRY, registry)
    read: list[str] = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (read.append(self.name), real(self))[1])
    problems: list[dict] = []

    found = sources.load_conversations(sources.Paths(catalog, tmp_path / "cage", None), T0 - 1, problems)

    assert set(found) == {CID} and problems == [], "a green that is gone, or a row of the wrong shape, is no problem"
    assert read.count(f"{CID}.json") == 1 and all("before04" not in name and ".." not in name for name in read)
    nowhere = sources.Paths(catalog, tmp_path / "cage", tmp_path / "no-such-green")
    assert sources.load_conversations(nowhere, T0 - 1, problems) == {CID: found[CID]} and problems == []


@pytest.fixture
def denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything under a folder named ``caged`` is refused to this account, as another account's profile is."""

    def refuse(real):  # noqa: ANN001, ANN202
        def guarded(self: Path, *args: object, **kwargs: object):  # noqa: ANN202
            if "caged" in self.parts:
                raise PermissionError(13, "Access is denied", str(self))
            return real(self, *args, **kwargs)

        return guarded

    monkeypatch.setattr(Path, "read_bytes", refuse(Path.read_bytes))
    monkeypatch.setattr(Path, "iterdir", refuse(Path.iterdir))


def _caged(tmp_path: Path) -> Path:
    """The catalog's registry binds two projects to a green only another account can read; returns the first's file."""
    green = tmp_path / "caged" / "work" / EXEC
    _json(tmp_path / "catalog" / sources.PROJECT_REGISTRY, {CID: {"project_root": str(green)},
                                                            LATE: {"project_root": str(green)}})  # fmt: skip
    return green / sources.CONVERSATIONS / f"{CID}.json"


def test_a_green_this_account_cannot_read_is_reported_and_not_skipped(tmp_path: Path, denied: None) -> None:
    file = _caged(tmp_path)
    problems: list[dict] = []

    found = sources.load_conversations(sources.Paths(tmp_path / "catalog", tmp_path / "cage", None), T0 - 1, problems)

    assert found == {}
    late = file.parent / f"{LATE}.json"
    assert problems == [
        {"conversation_id": CID, "where": str(file), "error": "PermissionError"},
        {"conversation_id": LATE, "where": str(late), "error": "PermissionError"},
    ]
    folder: list[dict] = []
    sources.load_conversations(sources.Paths(tmp_path / "x", tmp_path / "cage", tmp_path / "caged"), T0 - 1, folder)
    assert folder == [{"conversation_id": "", "where": str(tmp_path / "caged" / "work"), "error": "PermissionError"}]


def _argv(tmp_path: Path, *more: str) -> list[str]:
    return [
        "--since", "2026-10-09T00:00", "--until", "2026-10-10T00:00", "--catalog-root", str(tmp_path / "catalog"),
        "--cage-root", str(tmp_path / "cage"), "--green-root", str(tmp_path / "no-greens"), "--no-git",
        "--out-dir", str(tmp_path / "out"), *more,
    ]  # fmt: skip


def test_the_summary_names_it_and_no_baseline_is_written_while_a_project_is_unreadable(
    tmp_path: Path, denied: None, capsys: pytest.CaptureFixture[str]
) -> None:
    file, target = _caged(tmp_path), tmp_path / "out" / "baseline.json"
    now = T0 + 86400

    assert praxis_timeline.main(_argv(tmp_path), now=now, tz=timezone.utc) == 0
    said = capsys.readouterr().out
    assert CID in said and LATE not in said, "the line names it; a project launched after --until is not this window's"
    payload = json.loads((tmp_path / "out" / "timeline.json").read_text(encoding="utf-8"))
    assert payload["meta"]["unreadable"] == [{"conversation_id": CID, "where": str(file), "error": "PermissionError"}]
    assert payload["aggregate"]["projects_unreadable"] == 1 and payload["aggregate"]["projects"] == 0
    assert "no projects; 1 could not be read" in (tmp_path / "out" / "timeline.md").read_text(encoding="utf-8")

    assert praxis_timeline.main(_argv(tmp_path, "--baseline-out", str(target)), now=now, tz=timezone.utc) == 3
    assert not target.exists(), "a baseline that missed a project would be published as if it had not"
    refused = capsys.readouterr()
    assert CID in refused.out and "no baseline written" in refused.err and "--allow-unreadable" in refused.err

    flags = ["--baseline-out", str(target), "--allow-unreadable"]
    assert praxis_timeline.main(_argv(tmp_path, *flags), now=now, tz=timezone.utc) == 0
    text = target.read_text(encoding="utf-8")
    assert json.loads(text)["aggregate"]["projects_unreadable"] == 1, "the baseline keeps the count"
    assert CID not in text and "caged" not in text, "the baseline names no project"


def test_a_conversation_found_in_a_second_green_root_is_read_and_drops_its_unreadable_entry(
    tmp_path: Path, denied: None
) -> None:
    _caged(tmp_path)
    exported, target = tmp_path / "exported", tmp_path / "out" / "baseline.json"
    _json(exported / "work" / EXEC / sources.CONVERSATIONS / f"{CID}.json", _stopped())
    more = ["--green-root", str(exported), "--baseline-out", str(target)]

    assert praxis_timeline.main(_argv(tmp_path, *more), now=T0 + 86400, tz=timezone.utc) == 0

    payload = json.loads((tmp_path / "out" / "timeline.json").read_text(encoding="utf-8"))
    assert [row["conversation_id"] for row in payload["projects"]] == [CID] and target.exists()
    assert payload["meta"]["unreadable"] == [] and payload["aggregate"]["projects_unreadable"] == 0


def test_green_root_may_be_given_more_than_once_and_the_help_says_what_it_is() -> None:
    parser = praxis_timeline.build_parser()

    assert parser.parse_args(["--green-root", "a", "--green-root", "b"]).green_root == ["a", "b"]
    assert parser.parse_args([]).green_root == [] and parser.parse_args([]).allow_unreadable is False
    help_text = " ".join(parser.format_help().split())
    for words in ("more than once", "work/<exec>", "--allow-unreadable"):
        assert words in help_text, words


def test_the_notes_say_what_could_not_be_read_and_when_a_project_has_ended() -> None:
    said = " ".join(timeline_report.NOTES)

    for words in ("meta.unreadable", "projects_unreadable", "--allow-unreadable", "last hour", "last event"):
        assert words in said, words
    doc = " ".join((praxis_timeline.__doc__ or "").split())
    for words in ("--green-root", "project registry", "exits 3", "--allow-unreadable", "quiet for an hour"):
        assert words in doc, words
