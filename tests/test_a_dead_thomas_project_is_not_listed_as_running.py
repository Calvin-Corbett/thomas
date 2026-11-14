"""A Thomas project that died hours ago is not listed as running.

You reported ``GET /api/self/projects`` showing a project that had been dead for hours as
``running -- its first Build run is starting``. That is the wording
``self_project_routes._in_green`` uses when ``thomas_project.project_phase`` answers ``("waiting", "")``,
which it does for any project whose Build conversation carries no agent turn yet. That answer had no clock
in it, so a run killed before it recorded anything read as "just started" for as long as the green existed.

The liveness rule existed only inside ``chat_self_project.follow_card``, as a 120-second idle timer in a
loop's local variable. It dies with the process that started it and the list route never had one, so the
chat card and the list could disagree about the same project and a restart reset the question entirely.

``thomas_project_quiet`` is that rule moved onto what is on disk, and it measures ONE thing: how long the
Build conversation in the green has been silent. It makes no claim about what will or will not start a run
again, because two passes registered at boot do carry a stopped run on -- ``autopilot_park``'s ``park_loop``
and ``praxis.startup.install_praxis_recovery`` -- so a rule that ended every wait older than this process
would call those projects stopped at the very moment they were picked up.
``test_a_project_quiet_for_minutes_is_still_reported_as_running`` below holds that line, and
``test_the_restart_passes_this_rule_defers_to_are_registered_at_startup`` holds the two modules it defers
to: an earlier draft of ``thomas_project_quiet`` named a ``thomas/server/autopilot_restart.py`` that has
never existed in this repo, which is the same "claimed but not wired" fault the rule itself was fixing.

These tests drive the real route through the real server, with real git greens, and only the clock is moved.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import chat_self_project, green_checkout, green_handoff, thomas_project, thomas_project_quiet
from thomas.server.app import create_app
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN

ROOT = Path(__file__).resolve().parents[1]
ASK = "Make the Send button blue"
URL = "/api/self/projects"
CLAUDE = {"model": "claude:opus", "model_id": "opus", "reasoning_effort": "xhigh", "autonomy_level": 5,
          "file_access": "project", "memory": True, "guardrails": "guarded", "token_economy": "balanced",
          "build_roles": {"builder": None, "reviewer": None}}  # fmt: skip


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue = tmp_path / "blue"
    blue.mkdir()
    (blue / "README.md").write_text("README\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    greens, catalog, board = (tmp_path / name for name in ("green", "catalog", "board"))
    for folder in (greens / "work", greens / "git", catalog, board):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    from thomas.core import persistence

    state, reports = tmp_path / "state.json", tmp_path / "reports"
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", state)
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", reports)
    monkeypatch.setattr(persistence, "_engine", persistence.PersistenceEngine(state, report_dir=reports))
    world = SimpleNamespace(tmp=tmp_path, greens=greens, catalog=catalog, board=board, starts=[])

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        world.starts.append({**body, "port": port})
        return 200, {"ok": True, "conversation_id": body["conversation_id"], "run_id": "run-1"}

    world.hook = hook
    return world


async def _listed(client: TestClient) -> dict[str, Any]:
    for _ in range(100):
        body = await (await client.get(URL)).json()
        if not body.get("refreshing"):
            return {row["conversation_id"]: row for row in body["projects"]}
        await asyncio.sleep(0.02)
    raise AssertionError("Thomas project listing did not finish refreshing")


async def _client(w: SimpleNamespace) -> TestClient:
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")}, default_model="local",
        memory=MemoryConfig(root=str(w.tmp / "memory")), server=ServerConfig(access_mode="local"),
    )  # fmt: skip
    app = create_app(config)
    app[APP_PRAXIS_START_CODE_RUN] = w.hook
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    return client


def _live(project: dict[str, Any]) -> Path:
    """The green's own copy of the Build conversation -- the file a running team writes its turns to."""
    conversations = Path(project["project_root"]) / ".thomas" / "evolve" / "agent" / "conversations"
    return conversations / f"{project['conversation_id']}.json"


def _age(live_file: Path, seconds: float) -> None:
    """Make the green's Build conversation look as though nothing has written to it for ``seconds``."""
    old = time.time() - seconds
    os.utime(live_file, (old, old))


def test_a_project_whose_run_died_stops_being_reported_as_running(w: SimpleNamespace) -> None:
    """The reported case: no agent turn ever recorded, no run going, hours of silence."""

    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        client = await _client(w)
        try:
            started = await client.post(URL, json={"request": ASK, "settings": CLAUDE})
            project = await started.json()

            fresh = await _listed(client)
            _age(_live(project), thomas_project_quiet.QUIET_MAX_S + 4 * 3600)
            # Disk-only changes become visible when the shared listing's cache window expires.
            await asyncio.sleep(2.1)
            stale = await _listed(client)
            return fresh[project["conversation_id"]], stale[project["conversation_id"]]
        finally:
            await client.close()

    fresh, stale = asyncio.run(scenario())
    # A project that really did just start is untouched -- the old wording is still the right answer for it.
    assert (fresh["state"], fresh["detail"]) == ("running", "its first Build run is starting")
    assert stale["state"] == "stopped"
    assert "no Build run is going" in stale["detail"]
    assert "its first Build run was starting" in stale["detail"]  # it still says what it had been waiting for
    # It reports the silence it measured and nothing else. The draft that also announced why a project had
    # gone quiet ("stopped when Thomas restarted ... nothing resumes it") contradicted the two passes the
    # test below holds: `autopilot_park`'s loop and Praxis's startup recovery.
    assert "restart" not in stale["detail"].lower()


def test_a_project_quiet_for_minutes_is_still_reported_as_running(w: SimpleNamespace) -> None:
    """Minutes of silence is a run thinking, or a pass about to carry it on -- never "stopped".

    A Build turn writes nothing while it thinks, and Thomas's restart pass carries a stopped Autopilot run
    on after a restart. Both look identical from here: a conversation last written to a few minutes ago,
    with no run in the registry yet. An hour is the whole rule; anything shorter than it is left alone,
    however old the conversation is relative to this process.
    """

    async def scenario() -> dict[str, Any]:
        client = await _client(w)
        try:
            project = await (await client.post(URL, json={"request": ASK, "settings": CLAUDE})).json()
            _age(_live(project), 120.0)  # written two minutes ago, before this reading of the list
            for _ in range(100):
                listing = await (await client.get(URL)).json()
                if not listing.get("refreshing"):
                    rows = {row["conversation_id"]: row for row in listing["projects"]}
                    return rows[project["conversation_id"]]
                await asyncio.sleep(0.02)
            pytest.fail("the project listing did not finish refreshing")
        finally:
            await client.close()

    row = asyncio.run(scenario())
    assert (row["state"], row["detail"]) == ("running", "its first Build run is starting")


def test_a_live_run_is_never_called_quiet_however_long_it_thinks(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long turn writes nothing to the conversation while it runs, so the run registry decides that case.

    The registry is the route's own ``_running``; it is stood in for here because seeding a real Build
    subprocess into a started app is not what this test is about.
    """
    from thomas.server.routes import self_project_routes

    live_ids: set[str] = set()
    monkeypatch.setattr(self_project_routes, "_running", lambda app: set(live_ids))

    async def scenario() -> dict[str, Any]:
        client = await _client(w)
        try:
            project = await (await client.post(URL, json={"request": ASK, "settings": CLAUDE})).json()
            cid = project["conversation_id"]
            _age(_live(project), thomas_project_quiet.QUIET_MAX_S * 5)
            live_ids.add(cid)
            for _ in range(40):
                listing = await (await client.get(URL)).json()
                if not listing.get("refreshing"):
                    rows = {row["conversation_id"]: row for row in listing["projects"]}
                    return rows[cid]
                await asyncio.sleep(0.05)
            pytest.fail("the project listing did not finish refreshing")
        finally:
            await client.close()

    row = asyncio.run(scenario())
    assert row["state"] == "running" and row["detail"] == "a Build run is going"


def test_a_settle_in_flight_is_exempt_through_the_real_phase_call(w: SimpleNamespace) -> None:
    """The exemption is a SENTENCE compared by equality, so it is checked through the code that produces it.

    Settling copies the conversation into the catalog and the green's own file stops changing on purpose --
    so a settle in flight looks exactly like the silence the quiet rule ends projects for. The guard is
    ``why == thomas_project_quiet.HANDING_OVER``. A reworded copy in ``thomas_project._stored_phase`` would
    pass every string-free assertion and report projects mid-hand-over as stopped an hour later, so drive
    ``project_phase`` itself and let it produce the wording.
    """

    async def scenario() -> tuple[str, str]:
        client = await _client(w)
        try:
            project = await (await client.post(URL, json={"request": ASK, "settings": CLAUDE})).json()
            cid = project["conversation_id"]
            # What settling does first: the conversation is in the catalog, and the green's copy goes quiet.
            forge_code_store.conversations_dir(w.catalog)
            (w.catalog / ".thomas/evolve/agent/conversations" / f"{cid}.json").write_text(
                '{"turns": []}', encoding="utf-8"
            )
            _age(_live(project), thomas_project_quiet.QUIET_MAX_S * 6)
            return thomas_project.project_phase(Path(project["project_root"]), w.catalog, cid)
        finally:
            await client.close()

    phase, why = asyncio.run(scenario())
    assert (phase, why) == ("waiting", thomas_project_quiet.HANDING_OVER)
    # The chat card's steer gate keeps its own copy of that sentence (`_deliver` compares `detail` to it).
    # Two copies that must match, so the drift that would silently break the gate fails here instead.
    assert chat_self_project._HANDING_OVER == thomas_project_quiet.HANDING_OVER


def test_the_quiet_rule_leaves_every_other_phase_alone(tmp_path: Path) -> None:
    """Only ``waiting`` is reconsidered, and not the wait that is a settle in flight."""
    ancient = tmp_path / "conversation.json"
    ancient.write_text("{}", encoding="utf-8")
    _age(ancient, thomas_project_quiet.QUIET_MAX_S * 10)
    for phase in ("settled", "paused", "ended"):
        assert thomas_project_quiet.settle_quiet(ancient, phase, "why") == (phase, "why")
    handing = thomas_project_quiet.HANDING_OVER
    assert thomas_project_quiet.settle_quiet(ancient, "waiting", handing) == ("waiting", handing)
    assert thomas_project_quiet.settle_quiet(ancient, "waiting", "")[0] == "ended"  # the case it does answer
    # A conversation file that is not there is never called quiet: project_phase already ends that project.
    assert thomas_project_quiet.settle_quiet(tmp_path / "gone.json", "waiting", "") == ("waiting", "")


def test_an_hour_is_the_whole_rule(tmp_path: Path) -> None:
    """The threshold, at both sides of it, and a wait another pass owns treated like any other.

    ``why`` here is the kind of sentence ``project_phase`` gets from a pass that means to carry a project on.
    It is not exempt and it is not singled out: an hour of silence answers for it, the same as for a project
    that never recorded anything, and it is repeated back so the row still says what the project was waiting
    for.
    """
    live = tmp_path / "conversation.json"
    live.write_text("{}", encoding="utf-8")
    carried_on = "Autopilot: carrying on after the restart"

    _age(live, thomas_project_quiet.QUIET_MAX_S - 60.0)
    assert thomas_project_quiet.settle_quiet(live, "waiting", carried_on) == ("waiting", carried_on)

    _age(live, thomas_project_quiet.QUIET_MAX_S + 60.0)
    phase, why = thomas_project_quiet.settle_quiet(live, "waiting", carried_on)
    assert phase == "ended"
    assert "no Build run is going" in why and carried_on in why


def test_the_restart_passes_this_rule_defers_to_are_registered_at_startup(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason this rule says nothing about restarts is two startup hooks. They are started, here.

    An earlier draft of ``thomas_project_quiet`` justified itself by naming ``thomas/server/autopilot_restart.py``,
    a module this repo has never had. The claim's substance was right and its citation was not, which is the
    fault the whole change is about: something claimed, nothing wired. So the claim is checked by starting the
    real app and reading what boot left behind, not by reading either module.

    ``loop_enabled()`` keeps the park loop off under pytest so no test can start a Build run from a park; the
    env var it reads is turned on for this one test, and the app's own cleanup cancels the task on close.
    """
    from thomas.server import autopilot_park
    from thomas.server.praxis.startup import APP_PRAXIS_RECOVERY_REPORT

    monkeypatch.setenv(autopilot_park.LOOP_ENV, "1")

    async def scenario() -> tuple[Any, Any]:
        client = await _client(w)
        try:
            return client.app.get(APP_PRAXIS_RECOVERY_REPORT), client.app.get(autopilot_park.APP_AUTOPILOT_PARK_TASK)
        finally:
            await client.close()

    report, park_task = asyncio.run(scenario())
    # install_praxis_recovery's on_startup hook ran: it writes this report whether or not it resumed anything.
    # Only its shape is asserted -- the journal lives under the run's THOMAS_DATA_DIR, which every test in the
    # session shares, so what is in it depends on what ran before this.
    assert isinstance(report, dict) and set(report) == {"resumed", "skipped"}
    assert isinstance(report["resumed"], list) and isinstance(report["skipped"], list)
    # start_park_loop ran, and the loop it starts was still going when the app's own cleanup cancelled it.
    assert park_task is not None, "app_routes_init's on_startup did not start the park loop"
    assert park_task.cancelled(), f"the park loop ended on its own: {park_task.done() and park_task.exception()!r}"

    # And the citations themselves: every thomas/... module the rule's own docstring names is in the tree.
    named = set(re.findall(r"thomas/[\w/]+\.py", thomas_project_quiet.__doc__ or ""))
    assert named, "the rule no longer says which passes it defers to"
    missing = sorted(name for name in named if not (ROOT / name).is_file())
    assert missing == [], f"thomas_project_quiet names modules that do not exist: {missing}"
