"""--require-slot: the commit tool refuses to land unless the caller holds the landing queue's slot (off by default)."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from scripts.crew.brief import gate_runner, scoped_commit_cli, slot_check
from scripts.crew.brief.slot_check import SlotView

from tests.commit_lane_support import Lane, git, make_lane, mod


@pytest.fixture
def lane(tmp_path: Path, monkeypatch) -> Lane:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    for key in slot_check.SESSION_ENV:
        monkeypatch.delenv(key, raising=False)
    return make_lane(tmp_path)


class Source:
    """A queue that answers each question with the next view in `answers` (the last one repeats)."""

    def __init__(self, *answers: SlotView | None):
        self.answers, self.asked = list(answers), []

    def holding(self, *, agent: str, session: str):
        self.asked.append((agent, session))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _use(monkeypatch, source) -> None:
    monkeypatch.setattr(slot_check, "queue_source", lambda root: source)


LIVE = SlotView(ticket=7, state="holding", lease_left=600.0)


def test_off_by_default_so_the_queue_is_never_consulted(lane: Lane, monkeypatch) -> None:
    def never(root):
        raise AssertionError("the queue was consulted although no slot was required")

    monkeypatch.setattr(slot_check, "queue_source", never)
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert result.ok is True, (result.blocker_class, result.message)


def test_without_a_slot_it_refuses_before_any_gate_and_says_how_to_get_one(lane: Lane, monkeypatch) -> None:
    source = Source(None)
    _use(monkeypatch, source)
    before = lane.head()
    result = lane.land((("quiet", lane.logging("quiet")),), require_slot=True)
    assert (result.ok, result.blocker_class) == (False, "no_landing_slot")
    assert "land.py" in result.message and "land.py" in (result.next_step or "")
    assert lane.ran() == [] and lane.head() == before  # refused before the ladder cost anything
    assert source.asked == [("codex", "")]


def test_a_ticket_with_no_lease_left_is_not_a_slot(lane: Lane, monkeypatch) -> None:
    _use(monkeypatch, Source(SlotView(ticket=3, state="holding", lease_left=0.0)))
    result = lane.land((("quiet", lane.logging("quiet")),), require_slot=True)
    assert (result.ok, result.blocker_class) == (False, "no_landing_slot")
    assert "no lease left" in result.message and "T000003" in result.message


def test_with_a_live_slot_it_lands_and_asks_again_just_before_the_commit_object(lane: Lane, monkeypatch) -> None:
    source = Source(LIVE)
    _use(monkeypatch, source)
    result = lane.land((("quiet", lane.logging("quiet")),), require_slot=True)
    assert result.ok is True, (result.blocker_class, result.message)
    assert len(source.asked) == 2


def test_a_slot_the_lane_took_back_during_the_gates_stops_the_landing_before_the_commit_object(
    lane: Lane, monkeypatch
) -> None:
    _use(monkeypatch, Source(LIVE, None))  # held when asked first, skipped by the time the gates are done
    before = lane.head()
    result = lane.land((("quiet", lane.logging("quiet")),), require_slot=True)
    assert (result.ok, result.blocker_class) == (False, "no_landing_slot")
    assert lane.ran() == ["quiet"] and lane.head() == before


def test_a_dry_run_never_needs_a_slot(lane: Lane, monkeypatch) -> None:
    source = Source(None)
    _use(monkeypatch, source)
    result = lane.land((("quiet", lane.logging("quiet")),), dry_run=True, require_slot=True)
    assert (result.ok, result.dry_run) == (True, True)
    assert source.asked == []


def test_the_policy_in_agent_safety_toml_requires_a_slot_and_a_caller_cannot_relax_it(lane: Lane, monkeypatch) -> None:
    (lane.repo / "agent_safety.toml").write_text("[landing_queue]\nrequire_slot = true\n", encoding="utf-8")
    _use(monkeypatch, Source(None))
    for flag in (None, False):
        kwargs = {} if flag is None else {"require_slot": flag}
        result = lane.land((("quiet", lane.logging("quiet")),), **kwargs)
        assert (result.ok, result.blocker_class) == (False, "no_landing_slot"), flag


def test_the_policy_off_or_absent_changes_nothing(lane: Lane, monkeypatch) -> None:
    for text in ("[landing_queue]\nrequire_slot = false\n", "[other]\nx = 1\n", "not toml [[["):
        (lane.repo / "agent_safety.toml").write_text(text, encoding="utf-8")
        assert slot_check.configured_default(lane.repo) is False, text
    assert slot_check.configured_default(lane.repo / "missing") is False


def _commit_policy(lane: Lane, text: str) -> None:
    (lane.repo / "agent_safety.toml").write_text(text, encoding="utf-8")
    git(lane.repo, "add", "agent_safety.toml")
    git(lane.repo, "commit", "-qm", "policy")


def test_an_uncommitted_edit_cannot_turn_a_committed_requirement_off(lane: Lane) -> None:
    # Review finding: the policy was read from the working tree only, so an edit nobody had committed switched it off.
    _commit_policy(lane, "[landing_queue]\nrequire_slot = true\n")
    (lane.repo / "agent_safety.toml").write_text("[landing_queue]\nrequire_slot = false\n", encoding="utf-8")
    assert slot_check.configured_default(lane.repo) is True
    (lane.repo / "agent_safety.toml").unlink()
    assert slot_check.configured_default(lane.repo) is True  # not even by deleting the file


def test_an_uncommitted_edit_can_turn_the_requirement_on_but_the_committed_off_stands_otherwise(lane: Lane) -> None:
    _commit_policy(lane, "[landing_queue]\nrequire_slot = false\n")
    assert slot_check.configured_default(lane.repo) is False
    (lane.repo / "agent_safety.toml").write_text("[landing_queue]\nrequire_slot = true\n", encoding="utf-8")
    assert slot_check.configured_default(lane.repo) is True


def test_a_policy_file_that_does_not_parse_still_requires_a_slot_when_it_says_so(lane: Lane) -> None:
    # Review finding: one syntax error anywhere in the file read as "not required".
    for broken in (
        "[landing_queue]\nrequire_slot = true\nnot toml [[[\n",
        "x = [\n[landing_queue]\nrequire_slot=TRUE\n",
    ):
        (lane.repo / "agent_safety.toml").write_text(broken, encoding="utf-8")
        assert slot_check.configured_default(lane.repo) is True, broken
    for fine in ("[landing_queue]\nrequire_slot = false\nnot toml [[[\n", "garbage [[[ require_slot = true\n"):
        (lane.repo / "agent_safety.toml").write_text(fine, encoding="utf-8")
        assert slot_check.configured_default(lane.repo) is False, fine


def test_a_lease_that_is_not_a_number_is_not_a_slot(tmp_path: Path) -> None:
    refusal = slot_check.check_slot(
        tmp_path, agent="a", source=lambda root: Source(SlotView(ticket=1, state="holding", lease_left=float("nan")))
    )
    assert refusal is not None and "no lease left" in refusal


@pytest.mark.parametrize(
    "error",
    [
        IndexError("empty"),
        LookupError("gone"),
        AssertionError("invariant"),
        subprocess.TimeoutExpired("git", 5),
        ModuleNotFoundError("lazy import"),
    ],
)
def test_a_queue_that_raises_anything_else_refuses_instead_of_crashing_the_landing(tmp_path: Path, error) -> None:
    class Broken:
        def holding(self, *, agent: str, session: str):
            raise error

    refusal = slot_check.check_slot(tmp_path, agent="a", source=lambda root: Broken())
    assert refusal is not None and "could not be read" in refusal


def test_with_no_queue_installed_the_flag_refuses_and_says_so(lane: Lane, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "scripts.crew.brief.landing_queue", None)  # an import of it fails
    result = lane.land((("quiet", lane.logging("quiet")),), require_slot=True)
    assert (result.ok, result.blocker_class) == (False, "no_landing_slot")
    assert "unavailable" in result.message and "landing queue code is not in this checkout" in result.message


def test_a_queue_that_cannot_be_read_does_not_read_as_a_held_slot(tmp_path: Path) -> None:
    class Broken:
        def holding(self, *, agent: str, session: str):
            raise OSError("ledger unreadable")

    refusal = slot_check.check_slot(tmp_path, agent="a", source=lambda root: Broken())
    assert refusal is not None and "could not be read" in refusal and "ledger unreadable" in refusal


def _fake_queue(monkeypatch, states: dict[int, dict], leases: dict[int, float]) -> list:
    made: list = []
    queue = types.ModuleType("scripts.crew.brief.landing_queue")
    store = types.ModuleType("scripts.crew.brief.landing_store")

    class FakeLane:
        def __init__(self, store_, *, agent: str = "", session: str = ""):
            made.append((agent, session))
            self.ident = session or agent

        def states(self):
            return states

        def lease_left(self, number: int) -> float:
            return leases[number]

    class FakeStore:
        def __init__(self, root):
            self.root = root

    queue.Lane = FakeLane
    store.FileTicketStore = FakeStore
    store.resolve_queue_root = lambda env=None, start=None: Path("queue-root")
    monkeypatch.setitem(sys.modules, "scripts.crew.brief.landing_queue", queue)
    monkeypatch.setitem(sys.modules, "scripts.crew.brief.landing_store", store)
    return made


def _ticket(owner_agent: str, owner_session: str, state: str, *, open_: bool = True) -> dict:
    return {"ticket": {"agent": owner_agent, "session": owner_session}, "state": state, "open": open_}


def test_the_queue_adapter_finds_this_identitys_holding_ticket_and_nothing_else(tmp_path: Path, monkeypatch) -> None:
    states = {
        1: _ticket("codex", "s-other", "holding"),  # someone else's slot
        2: _ticket("codex", "s-mine", "waiting"),  # mine, but not my turn
        3: _ticket("codex", "s-mine", "holding", open_=False),  # mine, finished
        4: _ticket("codex", "s-mine", "holding"),  # mine, held now
    }
    _fake_queue(monkeypatch, states, {1: 50.0, 2: 60.0, 3: 70.0, 4: 80.0})
    source = slot_check.queue_source(tmp_path)
    assert source.holding(agent="codex", session="s-mine") == SlotView(4, "holding", 80.0)
    assert source.holding(agent="codex", session="s-nobody") is None
    del states[4]
    assert source.holding(agent="codex", session="s-mine") is None


def test_the_flag_is_forwarded_by_the_command_line_only_when_given() -> None:
    seen: list[dict] = []

    class Core:
        @staticmethod
        def commit_scoped_changes(**kwargs):
            seen.append(kwargs)
            return mod.CommitResult(
                ok=True, blocker_class=None, message="m", agent="a", branch="b", claim_scopes=(), selected_paths=()
            )

        _result_payload = staticmethod(mod._result_payload)

    assert scoped_commit_cli.run(["--message", "m"], core=Core) == 0
    assert scoped_commit_cli.run(["--message", "m", "--require-slot"], core=Core) == 0
    assert "require_slot" not in seen[0]
    assert seen[1]["require_slot"] is True


@pytest.mark.skipif(
    not os.environ.get("THOMAS_LANDING_QUEUE_TREE"),
    reason="set THOMAS_LANDING_QUEUE_TREE to a checkout that has the landing queue to run this against the real queue",
)
def test_the_adapter_against_the_real_queue_code(tmp_path: Path, monkeypatch) -> None:
    import scripts.crew.brief as brief

    tree = Path(os.environ["THOMAS_LANDING_QUEUE_TREE"]) / "scripts" / "crew" / "brief"
    monkeypatch.setattr(brief, "__path__", [*brief.__path__, str(tree)])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setenv("THOMAS_LANDING_QUEUE_DIR", str(tmp_path / "queue"))
    try:
        from scripts.crew.brief.landing_queue import Lane
        from scripts.crew.brief.landing_store import FileTicketStore

        lane = Lane(FileTicketStore(tmp_path / "queue"), agent="claude-x", session="s1")
        ticket = lane.enqueue("key-1", "subject")
        source = slot_check.queue_source(tmp_path)
        assert source.holding(agent="claude-x", session="s1") is None  # waiting, not holding
        assert lane.wait_turn(ticket, max_wait=10) == "granted"
        view = source.holding(agent="claude-x", session="s1")
        assert view is not None and (view.ticket, view.state) == (ticket, "holding") and view.lease_left > 0
        assert source.holding(agent="claude-x", session="someone-else") is None
    finally:
        for name in [n for n in sys.modules if n.startswith("scripts.crew.brief.landing_")]:
            del sys.modules[name]
