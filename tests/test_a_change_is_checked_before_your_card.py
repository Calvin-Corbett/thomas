"""A change is checked before its card is shown to you, and a change that fails goes back to its team.

You said, on 2026-09-25: "Every change you make to yourself reaches my Windows sign-in card with nothing
on it that says whether it was checked... This morning two cards reached me before that check ran; I
approved both, and between them they took thomas/core/llm_client.py past the 800-line limit
(tests/test_architecture.py failed on dev), broke about 45 chat tests... and removed a helper the restart
resume still called."

Real here, and the reason this file is slower than its neighbours: a real git repo with a real ``dev``
branch, real greens, real scratch copies made by ``git clone --shared``, a real ``git apply --3way``, and
real pytest processes run against both copies. The only stand-ins are the promoter's inbox folder and
Build's start hook. Both cases you asked to see are proved here on that machinery: a change that should
pass, and a change with a planted regression that must be sent back.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core.git_launcher import real_git_first
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import capacity_ledger, green_checkout, green_handoff, precard, self_change_status, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.precard import check, pool, report, scratch
from thomas.server.precard.review import review_verdict as real_review_verdict
from thomas.server.proof import environment
from thomas.server.routes import evolve_agent_autopilot as ap

EXECUTION = "thomas-checked1"
ADDER = "def add(a: int, b: int) -> int:\n    return a + b\n"
TEST_ADDER = (
    "from pkg.adder import add\n\n\n"
    "def test_add_makes_a_sum() -> None:\n    assert add(2, 2) == 4\n\n\n"
    "def test_add_takes_negatives() -> None:\n    assert add(-1, 1) == 0\n"
)
# Stands in for tests/test_architecture.py: the file both of this morning's hand-ins broke, and the one
# the proof set always runs whatever else changed.
TEST_ARCHITECTURE = (
    "from pathlib import Path\n\nLIMIT = 40\n\n\n"
    "def test_no_module_is_longer_than_the_limit() -> None:\n"
    "    for path in sorted(Path('pkg').rglob('*.py')):\n"
    "        assert len(path.read_text(encoding='utf-8').splitlines()) <= LIMIT, path\n"
)
PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n[tool.ruff]\nline-length = 120\n'

# A change that should pass: one new function, one new test for it, nothing else touched.
CLEAN_ADDER = ADDER + "\n\ndef double(n: int) -> int:\n    return add(n, n)\n"
_DOUBLE_TEST = "\n\ndef test_double_doubles() -> None:\n    assert double(3) == 6\n"
CLEAN_TEST = TEST_ADDER.replace("import add\n", "import add, double\n") + _DOUBLE_TEST
# The planted regression: two tests that pass on dev fail with it, and it touches no test file at all.
BROKEN_ADDER = "def add(a: int, b: int) -> int:\n    return a - b\n"
# What dev grows underneath the change, for the case where the two cannot be merged.
MOVED_ADDER = "def add(a: int, b: int) -> int:\n    return a * b\n"

FAILING = ("tests/test_adder.py::test_add_makes_a_sum", "tests/test_adder.py::test_add_takes_negatives")


def _git(cwd: Path, *args: str) -> None:
    env = real_git_first(os.environ)
    command = [
        shutil.which("git", path=env.get("PATH")) or "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "core.autocrlf=false",
        *args,
    ]
    subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True)


@pytest.fixture(scope="module")
def base_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Commit the unchanged dev fixture once; each test still gets an independent clone."""
    blue = tmp_path_factory.mktemp("precard-base") / "blue"
    (blue / "pkg").mkdir(parents=True)
    (blue / "tests").mkdir()
    (blue / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (blue / "pkg" / "adder.py").write_text(ADDER, encoding="utf-8")
    (blue / "tests" / "test_adder.py").write_text(TEST_ADDER, encoding="utf-8")
    (blue / "tests" / "test_architecture.py").write_text(TEST_ARCHITECTURE, encoding="utf-8")
    (blue / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    # As the real repo does: a Build conversation lives in .thomas/ inside the green and is never part of
    # the patch, so the check never applies one to its scratch copy of dev.
    (blue / ".gitignore").write_text(".thomas/\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    return blue


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_repo: Path) -> SimpleNamespace:
    """A small repo that really runs pytest, on a ``dev`` branch, with a green already cut from it."""
    blue, greens = tmp_path / "blue", tmp_path / "green"
    _git(tmp_path, "clone", "-q", "--shared", str(base_repo), str(blue))
    for folder in (greens / "work", greens / "git"):  # a green root that exists gets no ACLs set
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.setenv(environment.PYTHON_ENV, sys.executable)
    # Tiny scratch repos need pytest itself, not the host's installed plugin collection.
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv(precard.CHECK_ENV, "on")
    monkeypatch.setenv(precard.review.REVIEW_ENV, "on")
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))  # never the real catalog's ledger
    monkeypatch.setattr(capacity_ledger, "measure", lambda _w: capacity_ledger.Room(100 * 1024**3, None, None))
    monkeypatch.setattr(precard.review, "review_verdict", lambda _eid, _goal, _patch: precard.review.Verdict(safe=True))
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    catalog = tmp_path / "catalog"
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    green = green_checkout.create_green(blue=blue, execution_id=EXECUTION)
    return SimpleNamespace(tmp=tmp_path, blue=blue, greens=greens, catalog=catalog, green=green, starts=[])


def test_worlds_reuse_a_base_commit_but_keep_their_dev_and_green_independent(
    world: SimpleNamespace, base_repo: Path
) -> None:
    origin = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=world.blue, text=True).strip()
    assert Path(origin).resolve() == base_repo.resolve()
    assert (world.blue / ".git" / "objects" / "info" / "alternates").is_file()
    assert world.blue != base_repo and world.green.work != base_repo
    (world.blue / "pkg" / "adder.py").write_text(MOVED_ADDER, encoding="utf-8")
    assert (base_repo / "pkg" / "adder.py").read_text(encoding="utf-8") == ADDER
    assert (world.green.work / "pkg" / "adder.py").read_text(encoding="utf-8") == ADDER


def _change(world: SimpleNamespace, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        (world.green.work / rel).write_text(text, encoding="utf-8")
    return sorted(files)


def _finished(world: SimpleNamespace, changed: list[str]) -> str:
    """Its team finished: a Thomas project conversation in the green with one ok, completed run."""
    record = {"execution_id": EXECUTION}
    cid = str(forge_code_store.new_conversation(world.green.work, title="make it double", thomas_project=record)["id"])
    forge_code_store.append_user_turn(world.green.work, cid, "make it double")
    forge_code_store.append_agent_turn(
        world.green.work, cid, model="claude", transcript="", changed_files=changed, returncode=0,
        ok=True, noop=False, reason=f"{len(changed)} file(s) changed", outcome="completed",
    )  # fmt: skip
    forge_code_projects.bind_conversation(
        world.catalog, cid, world.green.work, settings={"requested": {"autonomy_level": 3}},
        allow_without_history=True,
    )  # fmt: skip
    return cid


def _submissions(world: SimpleNamespace) -> list[str]:
    inbox = world.tmp / "inbox"
    return sorted(path.name for path in inbox.iterdir()) if inbox.is_dir() else []


def _scratch_left(world: SimpleNamespace) -> list[str]:
    return sorted(p.name for p in (world.greens / "work").iterdir() if p.name.startswith(scratch.PREFIX))


@pytest.mark.parametrize(
    "request_suffix",
    [
        ". Reproduce the failure and keep the regression test passing.",
        "; rerun it to verify the fix.",
    ],
)
def test_planner_test_that_already_passes_closes_without_a_card(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, request_suffix: str
) -> None:
    from thomas.server import self_project_queue

    note = "changelog.d/test-note.md"
    (world.green.work / "changelog.d").mkdir()
    changed = _change(world, {note: "A note, not a fix.\n"})
    cid = _finished(world, changed)
    node = "tests/test_adder.py::test_add_makes_a_sum"

    def add_started(data: dict) -> None:
        data["started"].append(
            {
                "origin": "pytest",
                "conversation_id": cid,
                "execution_id": EXECUTION,
                "request": f"Fix failing test {node}{request_suffix}",
            }
        )

    self_project_queue.change(world.catalog, add_started)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda *a, **kw: pytest.fail("no card check needed"))

    assert thomas_project.settle_if_finished(world.green.work, world.catalog, cid) is None
    assert _submissions(world) == []
    stored = forge_code_store.load_conversation(world.catalog, cid)
    assert stored["thomas_project"]["summary"] == f"{node} already passes; no code change or sign-in card."
    assert node in self_project_queue.read(world.catalog)["planner"]["already_passing_tests"]
    assert not world.green.work.exists()
    assert green_checkout.find_green(EXECUTION) is None
    from thomas.server import chat_self_project

    messages: list[str] = []

    class Emitter:
        async def completed(self, record: dict[str, Any], *, text: str, **kwargs: Any) -> None:
            messages.append(text)

    monkeypatch.setattr(chat_self_project.task_bot_runtime, "complete_execution", lambda *a, **kw: {})
    card = chat_self_project._Card(
        app={},
        eid="already-passing",
        root=world.green.work,
        cid=cid,
        execution_id=EXECUTION,
        project_root=world.green.work,
        catalog_root=world.catalog,
        emitter=Emitter(),
        bot=None,
    )
    assert asyncio.run(chat_self_project._settled(card)) is False
    assert messages == [f"{node} already passes; no code change or sign-in card."]


def test_a_passing_test_probe_never_inherits_the_real_data_paths(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import self_project_already_passing, self_project_queue

    node = "tests/test_adder.py::test_add_makes_a_sum"
    (world.green.work / "changelog.d").mkdir()
    _change(world, {"changelog.d/note.md": "A note, not a fix.\n"})
    cid = _finished(world, ["changelog.d/note.md"])
    self_project_queue.change(
        world.catalog,
        lambda data: data["started"].append(
            {
                "origin": "pytest",
                "conversation_id": cid,
                "execution_id": EXECUTION,
                "request": f"Fix failing test {node}; rerun it to verify the fix.",
            }
        ),
    )
    monkeypatch.setattr(self_project_already_passing.environment, "interpreter", lambda blue: sys.executable)
    monkeypatch.setenv("THOMAS_DB_PATH", str(world.blue / "real-data.db"))
    monkeypatch.setenv("THOMAS_AGENT_ID", "real-agent")
    actual_run = subprocess.run
    seen: list[Path] = []

    def checked_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        env = kwargs["env"]
        data = Path(env["THOMAS_DATA_DIR"])
        seen.append(data)
        assert env["THOMAS_DB_PATH"] == str(data / "thomas.db")
        assert env["THOMAS_DB_PATH"] != os.environ["THOMAS_DB_PATH"]
        assert "THOMAS_AGENT_ID" not in env
        assert env["PYTHONPATH"] == str(world.green.work)
        assert data.is_dir()
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(
        self_project_already_passing,
        "subprocess",
        SimpleNamespace(run=checked_run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(self_project_already_passing.green_checkout, "find_green", lambda execution_id: world.green)
    monkeypatch.setattr(
        self_project_already_passing.green_checkout, "changed_paths", lambda green: ["changelog.d/test-note.md"]
    )
    assert self_project_already_passing.passing_test(world.catalog, cid, EXECUTION) == node
    assert len(seen) == 1
    assert not seen[0].exists(), "the probe's private data is removed after the run"


# ── the change that should pass ────────────────────────────────────────────────────────────────────────


def test_a_clean_change_passes_and_its_card_says_what_was_checked(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    copies: list[str] = []
    make_copy = scratch.copy_of_dev

    def recorded_copy(*args: Any) -> green_checkout.Green:
        copies.append(args[3])
        return make_copy(*args)

    monkeypatch.setattr(scratch, "copy_of_dev", recorded_copy)
    changed = _change(world, {"pkg/adder.py": CLEAN_ADDER, "tests/test_adder.py": CLEAN_TEST})
    cid = _finished(world, changed)
    tip = green_handoff.dev_tip(EXECUTION)

    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, cid)

    assert submission is not None and _submissions(world) == [f"self-{EXECUTION}"]
    manifest = json.loads((submission / "submission.json").read_text(encoding="utf-8"))
    line = manifest["checked"]
    assert line.startswith(f"Checked against dev {tip[:12]}: it applies cleanly"), line
    assert "test file(s) and" in line and "no failure this change causes" in line, line
    assert "ran with the change" in line and "ran on dev" not in line, line
    assert "the repo's size rule kept" in line, line
    # The card you see, the listing and the record all read it from the same place.
    assert thomas_project.settled_record(world.catalog, cid)["checked"] == line
    assert copies == [scratch.WITH_CHANGE], "a clean change never needs a dev baseline"
    assert _scratch_left(world) == [], "the check's own copies of dev are gone"


def test_each_check_checks_out_the_target_tip_only_once(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _change(world, {"pkg/adder.py": CLEAN_ADDER, "tests/test_adder.py": CLEAN_TEST})
    tip = green_handoff.dev_tip(EXECUTION)
    checkouts: list[tuple[str, ...]] = []
    original = green_checkout._git

    def recorded_git(green: green_checkout.Green, *args: str) -> Any:
        if "checkout" in args:  # a parallel-checkout speed-up puts its -c settings before the word checkout
            checkouts.append(args[args.index("checkout") :])
        return original(green, *args)

    monkeypatch.setattr(green_checkout, "_git", recorded_git)
    for _ in range(2):
        assert precard.check_before_card(EXECUTION).state == "passed"
        assert _scratch_left(world) == [], "each check removes its scratch after use"
    assert checkouts == [("checkout", "--quiet", "--detach", tip)] * 2


# ── the change with a planted regression ───────────────────────────────────────────────────────────────


def test_a_planted_regression_goes_back_to_its_team_instead_of_reaching_your_card(
    world: SimpleNamespace,
) -> None:
    """The whole path: the check finds it, the hand-in never happens, and the team gets a repair round."""
    changed = _change(world, {"pkg/adder.py": BROKEN_ADDER})
    cid = _finished(world, changed)

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        world.starts.append(body)
        forge_code_store.append_user_turn(world.green.work, body["conversation_id"], body["message"])
        return 200, {"ok": True, "conversation_id": body["conversation_id"]}

    app = {APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8899}
    forge_code_projects.bind_conversation(
        world.catalog,
        cid,
        world.green.work,
        settings={"requested": {"autonomy_level": 3}},
        allow_without_history=True,
    )
    asyncio.run(ap._settle_thomas_project(world.green.work, world.catalog, cid, app=app))

    assert _submissions(world) == [], "nothing reached the promoter's inbox"
    assert thomas_project.settled_record(world.catalog, cid) is None, "it never settled"
    conversation = forge_code_store.load_conversation(world.green.work, cid)
    round_one = (conversation.get("thomas_project") or {}).get("repairs")[0]
    assert (round_one["round"], round_one["why"]) == (1, thomas_project.SENT_BACK)
    findings = round_one["detail"]
    assert report.HEADINGS["regressed"] in findings, findings
    for test in FAILING:
        assert test in findings, findings
    assert "re-run on its own, first with the change" in findings
    assert len(world.starts) == 1 and findings in world.starts[0]["message"]
    assert world.starts[0]["message"].startswith(ap.REPAIR_PREFIX)
    assert _scratch_left(world) == []


# ── a single worker's change, when Chat could not start a Thomas project ───────────────────────────────


def _single_worker_finished(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Chat's single-worker path ends: its emitter settles the green. Returns what the chat and the card saw."""
    from thomas.server.chat_delegation_emitter import _DelegationEmitter

    seen = SimpleNamespace(events=[], follows=[])

    async def emit(event: dict[str, Any]) -> None:
        seen.events.append(event)

    async def follow(sid: str, chat: str, **kwargs: Any) -> str:
        seen.follows.append((sid, chat, kwargs.get("checked")))
        return ""

    monkeypatch.setattr(self_change_status, "follow", follow)
    emitter = _DelegationEmitter(emit, notifier=lambda *a, **k: None)
    bot = SimpleNamespace(to_event_dict=lambda: {})
    record = {"execution_id": EXECUTION, "session_id": "chat-single", "summary": "Fix."}

    async def scenario() -> None:
        await emitter.completed(record, specialist_id="coding", bot=bot, text="Fixed it.")
        await asyncio.sleep(0)  # let the follow task the emitter started run

    asyncio.run(scenario())
    return seen


def test_a_single_workers_planted_regression_never_reaches_your_card(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one other way a change to Thomas is handed in: it gets the same check, and no card on failure."""
    _change(world, {"pkg/adder.py": BROKEN_ADDER})

    seen = _single_worker_finished(monkeypatch)

    assert _submissions(world) == [] and seen.follows == [], "nothing reached the promoter or a card"
    told = "".join(str(event.get("text") or "") for event in seen.events if event.get("type") == "text")
    assert "was not handed in for your approval" in told, told
    for test in FAILING:
        assert test in told, told
    assert _scratch_left(world) == []


def test_a_single_workers_clean_change_reaches_your_card_saying_it_was_checked(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _change(world, {"pkg/adder.py": CLEAN_ADDER, "tests/test_adder.py": CLEAN_TEST})

    seen = _single_worker_finished(monkeypatch)

    assert _submissions(world) == [f"self-{EXECUTION}"]
    manifest = json.loads((world.tmp / "inbox" / f"self-{EXECUTION}" / "submission.json").read_text(encoding="utf-8"))
    assert manifest["checked"].startswith("Checked against dev"), manifest["checked"]
    assert seen.follows == [(f"self-{EXECUTION}", "chat-single", manifest["checked"])]


# ── a change that will not apply to the dev it would land on ───────────────────────────────────────────


def test_a_change_that_will_not_apply_to_dev_is_a_finding_before_any_test_runs(world: SimpleNamespace) -> None:
    _change(world, {"pkg/adder.py": BROKEN_ADDER})
    (world.blue / "pkg" / "adder.py").write_text(MOVED_ADDER, encoding="utf-8")
    for args in (("add", "-A"), ("commit", "-q", "-m", "dev moved")):
        _git(world.blue, *args)

    checked = precard.check_before_card(EXECUTION)

    assert checked.state == precard.FAILED and checked.failed
    assert "could not apply this change to dev" in checked.findings
    assert checked.dev_moved and "pkg/adder.py" in checked.findings
    assert "git merge" not in checked.findings  # the server merges dev in for its team (a dev-moved round)
    assert _scratch_left(world) == []


def test_a_check_runs_the_change_once_and_confirms_its_failure_alone_on_both_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server.precard.lint import LintResult
    from thomas.server.proof import ProofRun, Selection

    monkeypatch.setenv(pool.PARALLEL_ENV, "off")  # the worker formula pinned here is the off path's
    started: list[str] = []
    changed = ("tests/test_regression.py::test_broken",)
    base = SimpleNamespace(work=tmp_path / "base")
    with_change = SimpleNamespace(work=tmp_path / "change")
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_regression.py",), ()))
    monkeypatch.setattr(check.os, "cpu_count", lambda: 8)
    # 3 GiB free with the 8 GiB reserve counted once holds 4 shards of 768 MiB; counted twice, it held none.
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * 1024**3, 3 * 1024**3))

    def fake_tests(work: Path, files: tuple[str, ...], *, shard_workers: int, **kwargs: Any) -> ProofRun:
        assert shard_workers == 4 and files == ("tests/test_regression.py",), "one run, at full width"
        started.append(work.name)
        return ProofRun(True, "", changed, 1, 1)

    alone: list[tuple[str, str]] = []

    def fake_one(work: Path, test: str, **kwargs: Any) -> str:
        alone.append((work.name, test))
        return check.proofs.FAILED if work == with_change.work else check.proofs.PASSED

    monkeypatch.setattr(check.proofs, "run_tests", fake_tests)
    monkeypatch.setattr(check.proofs, "run_one", fake_one)
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_args, **_kwargs: LintResult(True, "", (), ()))

    result = check._steps(SimpleNamespace(execution_id="example"), "abc123", "patch", ["pkg/adder.py"],
                          sys.executable, base, with_change, tmp_path / "data", check.proofs.Deadline(10))  # fmt: skip

    assert started == ["change"], "dev is not run in full for a change whose run finished"
    assert result.state == check.FAILED and changed[0] in result.findings
    assert alone == [("change", changed[0]), ("base", changed[0])]


@pytest.mark.parametrize("available_gib, estimated", [(20, 4), (3, 31)])
def test_the_change_runs_alone_under_the_cpu_and_free_memory_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available_gib: int, estimated: int
) -> None:
    monkeypatch.setenv(pool.PARALLEL_ENV, "off")  # the per-side worker formula is the off path's
    from thomas.server.precard.lint import LintResult
    from thomas.server.proof import Selection

    base, changed = (tmp_path / name for name in ("base", "change"))
    files = tuple(f"tests/test_{number}.py" for number in range(10))
    for work in (base, changed):
        for name in files:
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def test_ok(): pass\n", encoding="utf-8")
    monkeypatch.setattr(check.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * 1024**3, available_gib * 1024**3))
    estimates: list[tuple[int, int | None]] = []

    def estimated_capacity(*, cpus: int, total_ram_bytes: int | None, run_budget_mb: int) -> int:
        assert run_budget_mb == check.machine_capacity.DEFAULT_RUN_BUDGET_MB
        estimates.append((cpus, total_ram_bytes))
        return estimated

    monkeypatch.setattr(check.machine_capacity, "estimate", estimated_capacity)
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(files, ()))
    monkeypatch.setattr(check.lint, "ruff_findings", lambda *_args, **_kwargs: LintResult(True, "", (), ()))
    original = check.proofs.run_tests
    active = peak = 0
    sides: set[str] = set()
    lock = threading.Lock()

    def fake_run(command: list[str], *, cwd: Path, **kwargs: Any) -> tuple[int, str]:
        nonlocal active, peak
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        with lock:
            active += 1
            peak = max(peak, active)
            sides.add(cwd.name)
        try:
            time.sleep(0.06)
            module = command[-1][:-3].replace("/", ".")
            report.write_text(
                f'<testsuites><testsuite tests="1"><testcase classname="{module}" name="test_ok"/></testsuite></testsuites>'
            )
            return 0, ""
        finally:
            with lock:
                active -= 1

    def fake_tests(work: Path, selected: tuple[str, ...], **kwargs: Any) -> Any:
        return original(work, selected, shard_files=1, run=fake_run, **kwargs)

    monkeypatch.setattr(check.proofs, "run_tests", fake_tests)
    result = check._steps(
        SimpleNamespace(execution_id="example"),
        "abc123",
        "patch",
        ["pkg/adder.py"],
        sys.executable,
        SimpleNamespace(work=base),
        SimpleNamespace(work=changed),
        tmp_path / "data",
        check.proofs.Deadline(10),
    )
    assert result.state == check.PASSED
    assert sides == {"change"}
    assert estimates == [(16, 32 * 1024**3)]
    assert 1 < peak <= 4, "the one run respects the smaller of the estimated and free-memory caps"


# ── the check's own copies of dev, while it is using them ──────────────────────────────────────────────


def test_a_sweep_during_the_check_leaves_its_copies_and_no_sibling_sees_them(world: SimpleNamespace) -> None:
    """Another self-fix starting sweeps greens; a settled one goes at any age, even under a running pytest."""
    tip = green_handoff.dev_tip(EXECUTION)
    copy = scratch.copy_of_dev(world.blue, tip, EXECUTION, scratch.WITH_CHANGE)
    try:
        (copy.work / "pkg" / "adder.py").write_text(BROKEN_ADDER, encoding="utf-8")

        assert copy.execution_id not in green_checkout.sweep(), "a copy the check is using is not swept"
        assert copy.work.is_dir()
        assert copy.execution_id not in green_handoff.sibling_changes(""), "a scratch copy is no team's work"
    finally:
        scratch.discard(copy)
    assert _scratch_left(world) == []


# ── a check that cannot run never sends an unchecked change to a card ──────────────────────────────────


def test_a_check_without_an_interpreter_waits_before_the_card(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(environment.PYTHON_ENV)  # no .venv in this repo either
    changed = _change(world, {"pkg/adder.py": BROKEN_ADDER})
    cid = _finished(world, changed)

    with pytest.raises(precard.CheckUnavailable, match="no interpreter"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, cid)

    assert _submissions(world) == []
    assert green_checkout.find_green(EXECUTION) is not None
    assert thomas_project.settled_record(world.catalog, cid) is None


def test_unavailable_check_books_a_durable_hold_instead_of_a_card(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import hand_in_hold

    monkeypatch.delenv(environment.PYTHON_ENV)
    cid = _finished(world, _change(world, {"pkg/adder.py": BROKEN_ADDER}))
    forge_code_projects.bind_conversation(
        world.catalog,
        cid,
        world.green.work,
        settings={"requested": {"autonomy_level": 3}},
        allow_without_history=True,
    )
    asyncio.run(ap._settle_thomas_project(world.green.work, world.catalog, cid, app={APP_LOCAL_PORT: 8899}))

    row = hand_in_hold.row(world.catalog, cid)
    assert row is not None and row["state"] == "held" and row["step"] == "check"
    assert _submissions(world) == []
    assert green_checkout.find_green(EXECUTION) is not None
    assert thomas_project.project_phase(world.green.work, world.catalog, cid)[0] == "paused"


def test_the_second_look_off_is_reported_on_the_card(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import hand_in_hold

    monkeypatch.setattr(precard.review, "review_verdict", real_review_verdict)
    monkeypatch.setenv(precard.review.REVIEW_ENV, "off")
    cid = _finished(world, _change(world, {"pkg/adder.py": CLEAN_ADDER}))
    forge_code_projects.bind_conversation(
        world.catalog,
        cid,
        world.green.work,
        settings={"requested": {"autonomy_level": 3}},
        allow_without_history=True,
    )
    asyncio.run(ap._settle_thomas_project(world.green.work, world.catalog, cid, app={APP_LOCAL_PORT: 8899}))

    assert hand_in_hold.row(world.catalog, cid) is None
    assert len(_submissions(world)) == 1
    assert "second look was turned off" in thomas_project.settled_record(world.catalog, cid)["checked"]


def test_the_check_can_be_turned_off_and_then_says_that_is_why(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(precard.CHECK_ENV, "off")
    _change(world, {"pkg/adder.py": BROKEN_ADDER})

    checked = precard.check_before_card(EXECUTION)

    assert checked.state == precard.UNAVAILABLE and precard.CHECK_ENV in checked.line
    assert _scratch_left(world) == [], "it never made a copy"


def test_a_check_with_no_copy_to_apply_to_says_so_and_never_raises(world: SimpleNamespace) -> None:
    green_checkout.remove_green(world.green)

    checked = precard.check_before_card(EXECUTION)

    assert checked.state == precard.UNAVAILABLE and "copy is gone" in checked.line


# ── what the card you are looking at says about the check ──────────────────────────────────────────────


class Book:
    """The question book's shape, as ``tests/test_the_chat_sees_its_self_fix_cards.py`` stands it in."""

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.forgotten: list[str] = []

    def ask(self, **kwargs: Any) -> Any:
        self.asked.append(kwargs)
        return SimpleNamespace(id=f"q{len(self.asked)}")

    def forget(self, question_id: str) -> None:
        self.forgotten.append(question_id)


def _mirrored(tmp_path: Path, sid: str, checked: str) -> list[dict[str, Any]]:
    """The cards ``follow`` mirrors into a chat for one hand-in, given *checked* as its line."""
    outbox, book = tmp_path / sid, Book()
    outbox.mkdir()
    card = {"title": "Put Thomas's changes into the running Thomas", "body": "Apply 1 change(s): pkg/adder.py"}
    (outbox / f"{sid}.pending.json").write_text(json.dumps({"cards": [card]}), encoding="utf-8")
    original_ask = book.ask

    def ask_then_decide(**kwargs: Any) -> Any:
        result = original_ask(**kwargs)
        # The verdict arrives only after follow actually mirrors the pending card.
        (outbox / f"{sid}.verdict.json").write_text(json.dumps({"status": "landed"}), encoding="utf-8")
        return result

    book.ask = ask_then_decide  # type: ignore[method-assign]
    verdict = asyncio.run(
        self_change_status.follow(sid, "chat-3", outbox=outbox, book=book, poll_s=0.001, timeout_s=5, checked=checked)
    )
    assert verdict == "landed"
    return book.asked


def test_the_card_mirrored_into_the_chat_shows_what_was_checked(tmp_path: Path) -> None:
    """The Windows dialog's own wording is pinned by the card catalogue, so the check's line rides this card."""
    line = "Checked against dev abc123456789: it applies cleanly; 2 test file(s) and 3 test(s) ran with the change ..."

    fields = _mirrored(tmp_path, "self-e9", line)[0]["details"]["fields"]

    assert [field["label"] for field in fields] == ["Change", "Checked"], fields
    assert fields[1]["value"] == line


def test_a_card_with_nothing_to_say_about_the_check_shows_no_checked_field(tmp_path: Path) -> None:
    """An empty line is not the same as "checked and fine": the card says nothing rather than something false."""
    fields = _mirrored(tmp_path, "self-e10", "")[0]["details"]["fields"]

    assert [field["label"] for field in fields] == ["Change"], fields
