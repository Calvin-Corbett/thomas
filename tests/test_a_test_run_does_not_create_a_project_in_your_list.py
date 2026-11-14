"""A test run does not put a project in your Build list.

You reported the Build project chooser "full of projects your own tests created", naming
"Use browser.open and browser.extract then ...". That string is a test prompt
(``tests/test_chat_delegation_worker_contract.py``), and it reaches your list through TWO stores under a
shared root, both of which that one test writes:

* the task ledger -- a card in the chooser is built straight from an execution record:
  ``local_projects_generated._generated_deliverable_project`` lists ``task_bot_runtime.list_executions()``
  and titles each card with the run's own ``summary`` via ``_request_title``;
* the Build conversation registry -- a coding task mints a project and binds its conversation to it
  (``chat_delegation_build_session.open_build_session`` -> ``forge_code_projects.bind_conversation``),
  which writes ``<catalog>/.thomas/evolve/agent/project_registry.json``; that registry is what
  ``GET /api/evolve/agent/conversations`` lists. Closing only the ledger half left this one open, and the
  checkout's registry went on gaining an entry per run.

Two earlier fixes went at this and neither closed it:

* ``tests/test_a_worker_test_does_not_leave_a_live_task_in_the_repo.py`` lints test files for
  ``repo_root=Path(".")``. It cannot see a call that passes no ``repo_root`` at all -- and that resolves to
  the checkout just the same, because ``resolve_project_root()`` answers the git root above the current
  directory and pytest runs from there.
* ``tests/conftest.py`` points ``THOMAS_DATA_DIR`` and ``THOMAS_OWNED_ROOT`` at a temp folder for the whole
  run, naming this exact symptom: "test_chat_delegation_worker_contract had made 23 'Use browseropen and
  browserextract then' projects in your Build list". That covers the ledger a one-off job coordinates in
  (``coordination_root(root, "isolated")`` answers the data dir, whatever root it was handed). It does not
  cover the checkout's own ``runtime/coordination/task_bots/``, which no ``THOMAS_*`` variable moves, and
  the session's end-of-run tripwire watches your ``~/.thomas`` rather than the checkout.

So both stores refuse, instead of a lint or an env var chasing them: ``thomas.core.shared_root_sandbox``
sends a test process's root to a throwaway folder whenever it would otherwise be a shared one -- the
checkout or the data dir, whichever one the caller happened to reach. A root a test passes in itself is
left alone, which is why every existing fixture still works, and each shared root gets a stand-in of its
own rather than one shared by the whole process, so two tests that name two different data dirs do not end
up reading each other's records.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.core import project_root, shared_root_sandbox, task_bot_runtime
from thomas.forge.anvil import forge_code_projects
from thomas.server import chat_delegation_build_session
from thomas.server.routes import local_projects_generated

CHECKOUT = Path(__file__).resolve().parents[1]
LEAKED_PROMPT = "Use browser.open and browser.extract, then fs.write_file agentic_report.md"
REGISTRY = Path(".thomas") / "evolve" / "agent" / "project_registry.json"


def _registered(catalog: Path) -> set[str]:
    """The conversation ids the registry FILE under ``catalog`` names, read off the disk, not through the API.

    Through the API would ask the sandbox, which answers the throwaway copy -- the very redirect under test.
    What your running Thomas lists is this file, so this is the file the tests below count.
    """
    try:
        loaded = json.loads((catalog / REGISTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set(loaded) if isinstance(loaded, dict) else set()


def test_the_roots_a_live_thomas_reads_are_the_ones_a_test_is_kept_out_of() -> None:
    assert CHECKOUT in shared_root_sandbox.shared_roots()
    assert shared_root_sandbox.in_test_run() is True
    assert shared_root_sandbox.sandbox_root() not in shared_root_sandbox.shared_roots()


def test_a_record_with_no_root_of_its_own_lands_in_the_sandbox_and_is_still_readable() -> None:
    """The unguarded call: no ``repo_root`` at all. It must still work, just not here.

    A redirect that also stopped the write would make every leaking test pass by doing nothing, so the
    record is read back through the same resolver to show it was really written.
    """
    # Named explicitly rather than left to the working directory, so this says the same thing wherever
    # pytest was launched from: a call that resolves to the checkout does not write to the checkout.
    assert task_bot_runtime.runtime_dir(CHECKOUT).is_relative_to(shared_root_sandbox.sandbox_root())
    # And in the checkout's OWN stand-in, not a folder every shared root shares.
    assert task_bot_runtime.runtime_dir(CHECKOUT).is_relative_to(shared_root_sandbox.sandboxed(CHECKOUT))
    ledger = task_bot_runtime.runtime_dir()
    assert not ledger.is_relative_to(CHECKOUT), f"a test's task ledger is inside the checkout: {ledger}"

    record = task_bot_runtime.create_execution(session_id="sess-probe", summary=LEAKED_PROMPT)
    execution_id = str(record["execution_id"])
    assert task_bot_runtime.get_execution(execution_id) is not None  # the write is real
    assert (CHECKOUT / "runtime" / "coordination" / "task_bots" / f"{execution_id}.json").exists() is False


def test_the_isolated_workspace_that_ignores_repo_root_is_covered_too(tmp_path: Path) -> None:
    """The vector the ``repo_root=`` lint cannot see, reproduced and then shown closed.

    ``coordination_root(<a tmp_path>, "isolated")`` is the delegation default, and it answers the Thomas
    data dir whatever root it was handed. Writing a record under that answer used to land in your own
    ledger; now it lands in the sandbox, and the data dir gains no file.
    """
    data_dir = project_root.coordination_root(tmp_path, "isolated")
    assert Path(data_dir).resolve() in shared_root_sandbox.shared_roots()
    assert Path(data_dir).resolve() != tmp_path  # the root that was passed in is not the root that is used

    record = task_bot_runtime.create_execution(session_id="sess-isolated", summary=LEAKED_PROMPT, repo_root=data_dir)
    leaked = Path(data_dir) / "runtime" / "coordination" / "task_bots" / f"{record['execution_id']}.json"
    assert not leaked.exists(), f"a test's task record reached your data dir: {leaked}"
    assert task_bot_runtime.get_execution(str(record["execution_id"]), data_dir) is not None  # still readable


def test_your_library_gains_nothing_from_a_test_that_starts_a_worker() -> None:
    """The surface you reported, asserted where it can actually be asserted.

    A card in the chooser comes from ``_generated_deliverable_projects``, which reads the ledger under the
    root it resolves -- and inside this process that resolution is the sandbox, so reading it here would
    only show the sandbox. What the LIVE server reads is the ledger directory itself, in the checkout and
    in the data dir, so those two are what this counts: they gain no file, so the chooser gains no card.
    """
    ledgers = [root / "runtime" / "coordination" / "task_bots" for root in shared_root_sandbox.shared_roots()]
    before = {ledger: {p.name for p in ledger.glob("*.json")} for ledger in ledgers if ledger.is_dir()}

    for session in ("sess-library", "sess-library-2"):
        task_bot_runtime.create_execution(session_id=session, summary=LEAKED_PROMPT)
    # The reader the chooser uses is still exercised, so a redirect that broke it would show up here.
    assert isinstance(local_projects_generated._generated_deliverable_projects(), list)

    for ledger in ledgers:
        now = {p.name for p in ledger.glob("*.json")} if ledger.is_dir() else set()
        assert now - before.get(ledger, set()) == set(), f"a test's task record reached {ledger}"


def test_a_root_a_test_named_itself_is_left_exactly_as_it_is(tmp_path: Path) -> None:
    """Every existing fixture passes its own root; none of them is diverted.

    A root PASSED IN, that is. A root named through ``THOMAS_DATA_DIR`` is the data dir for as long as it is
    set, which is a shared root by definition, and it is redirected -- to a stand-in of its own, which is
    what the next test measures.
    """
    assert shared_root_sandbox.coordination_root(tmp_path) == tmp_path
    assert shared_root_sandbox.sandboxed(tmp_path) == tmp_path
    written = task_bot_runtime.create_execution(session_id="s", summary="own root", repo_root=tmp_path)
    path = tmp_path / "runtime" / "coordination" / "task_bots" / f"{written['execution_id']}.json"
    assert path.is_file()

    forge_code_projects.bind_conversation(tmp_path, "cid-own-root", tmp_path, allow_without_history=True)
    assert _registered(tmp_path) == {"cid-own-root"}  # written where the caller said, not in the sandbox


def test_two_tests_that_name_their_own_data_dir_do_not_share_a_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One stand-in per root, so the redirect does not introduce a leak of its own.

    ``THOMAS_DATA_DIR`` is what a fixture moves to give a test a data dir of its own, and the isolated
    workspace above resolves through it. While every shared root shared ONE sandbox folder, those tests
    shared one ledger instead of having one each: this is the two-test probe, run as two rounds here, and
    the second round must see only its own record.
    """
    made, seen, stand_ins = [], [], []
    for name in ("first", "second"):
        own = tmp_path / name
        own.mkdir()
        monkeypatch.setenv("THOMAS_DATA_DIR", str(own))
        data_dir = project_root.coordination_root(own, "isolated")
        assert Path(data_dir).resolve() == own.resolve()  # the root this round named for itself
        record = task_bot_runtime.create_execution(
            session_id=f"sess-{name}", summary=LEAKED_PROMPT, repo_root=data_dir
        )
        made.append(str(record["execution_id"]))
        seen.append({str(row.get("execution_id") or "") for row in task_bot_runtime.list_executions(data_dir)})
        stand_ins.append(shared_root_sandbox.sandboxed(data_dir))
        assert not (own / "runtime" / "coordination").exists()  # still nothing written to the root itself

    assert seen[0] == {made[0]}
    assert seen[1] == {made[1]}, "a test read the executions of the test before it"
    # Different roots, different stand-ins -- and neither of them is the folder the checkout gets.
    assert len(set(stand_ins)) == 2
    assert shared_root_sandbox.sandboxed(CHECKOUT) not in stand_ins


def test_a_live_thomas_is_not_redirected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside a test process the sandbox does nothing at all -- your own tasks stay in your own ledger."""
    monkeypatch.setattr(shared_root_sandbox, "in_test_run", lambda: False)
    for root in (*shared_root_sandbox.shared_roots(), Path.home()):
        assert shared_root_sandbox.coordination_root(root) == root
        assert shared_root_sandbox.sandboxed(root) == root


def test_a_build_session_a_test_opens_adds_nothing_to_your_conversation_list() -> None:
    """The half the ledger fix missed, reproduced through the join that dispatch actually calls.

    ``chat_delegation._start_agent_worker_delegation`` hands a coding task to
    ``chat_delegation_build_session.prepare_workspace``, which mints a project and binds the conversation
    with ``catalog_root`` = the resolved checkout. That binding is what ``GET /api/evolve/agent/conversations``
    lists, which is where you saw the browser/artifact prompt. The session must still open -- a redirect that
    broke it would make this pass by doing nothing -- so the binding is read back through the API too.
    """
    before = _registered(CHECKOUT)
    session = chat_delegation_build_session.open_build_session(
        specialist_id="coding", targets_live_repo=False, title=LEAKED_PROMPT, catalog_root=CHECKOUT
    )
    assert session is not None and session["conversation_id"]

    cid = str(session["conversation_id"])
    bound = forge_code_projects.conversation_metadata(CHECKOUT, cid)
    assert bound is not None and bound["project_root"] == session["project_root"]  # the join is real
    assert _registered(CHECKOUT) == before, "a test's Build conversation reached the checkout's registry"
    assert cid in _registered(shared_root_sandbox.sandboxed(CHECKOUT))
