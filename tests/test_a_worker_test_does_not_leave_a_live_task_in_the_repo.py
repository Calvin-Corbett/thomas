"""A test that runs a worker must not leave a task record in the real checkout.

THE MEASUREMENT THAT FOUND THIS

    $ rm -rf runtime/coordination/task_bots
    $ pytest -p no:warnings -q \
        "tests/test_mission_runtime_views.py::test_mission_control_excludes_stale_runs_from_active_count"
      1 passed in 3.10s                                          <- control

    $ rm -rf runtime/coordination/task_bots
    $ pytest -p no:warnings -q \
        "tests/test_chat_delegation.py::TestChatDelegation::test_run_agent_worker_marks_cancellation_and_propagates" \
        "tests/test_mission_runtime_views.py::test_mission_control_excludes_stale_runs_from_active_count"
      >  assert payload["totals"]["active_agents"] == 0
      E  assert 1 == 0
      1 failed, 1 passed in 5.88s                                 <- same test, one neighbour

Seven cases in `test_chat_delegation.py` and four in
`test_chat_delegation_self_recovery.py` passed ``repo_root=Path(".")`` into
`chat_delegation._run_agent_worker`. pytest runs from the checkout, so that WAS
the live repo. Two of them did not patch `task_bot_runtime.update_execution`, so
the worker's first act -- writing "Preparing workspace change baseline." to the
execution record -- created real files:

    runtime/coordination/task_bots/exec-c.json        state "requested"
    runtime/coordination/task_bots/exec-native.json   state "executing"
    runtime/coordination/task_bots/executions-summary.json   "active_count": 2

Neither state is terminal, so `_summary_row` kept them off the stale list for
five minutes, and Mission Control reads that directory directly
(`mission_control_routes` -> `task_bot_runtime.list_executions(refresh=True)`).
The leftovers therefore counted as live agents (1 or 2, depending on timing)
instead of 0, and each non-terminal delegation costs one extra `_utc_iso_now()`
call per snapshot -- which exhausted the two-value `side_effect` in the snapshot
cache test and turned it into a 500.

Over the same 20 files: 3 failed / 168 passed before, 0 failed / 171 passed
after (173 with this file's own two cases added). The three were
`test_mission_control_hides_idle_desktop_operator_from_agent_queue`,
`test_mission_control_excludes_stale_runs_from_active_count` and
`test_mission_control_snapshot_cache_coalesces_and_fresh_bypasses` -- each green
on its own, which is exactly why this hid rather than reported.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from thomas.core import task_bot_runtime
from thomas.server import chat_delegation

TESTS_DIR = Path(__file__).resolve().parent

# `repo_root=Path(".")`, `repo_root="."` and `repo_root=Path.cwd()` all resolve to
# the checkout, because that is where pytest runs from.
_LIVE_CHECKOUT_REPO_ROOT = re.compile(
    r"""repo_root\s*=\s*(?:Path\(\s*["']\.["']\s*\)(?:\.resolve\(\))?|["']\.["']|Path\.cwd\(\))"""
)


def _prose_line_numbers(text: str) -> set[int]:
    """The lines a bare string statement occupies -- module, class and function docstrings.

    This lint reads call sites, and the files most likely to spell out
    ``repo_root`` pointed at the checkout are the ones documenting the hazard:
    this module's own docstring, and the one in
    `test_a_test_run_does_not_create_a_project_in_your_list.py` that explains
    what this lint cannot see. A `#` comment was already exempt; a docstring is
    the same prose under different punctuation.

    Only strings that stand alone as a statement are dropped. Blanking every
    string token instead would also blank the ``"."`` inside the call being
    hunted, and the lint would pass on a real offender.
    """

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()  # not parseable, so read every line rather than trust nothing
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            prose.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return prose


def test_no_test_aims_a_worker_at_the_live_checkout() -> None:
    """The repo root a test hands the worker is where the worker writes.

    Before: 11 occurrences across test_chat_delegation.py (7) and
    test_chat_delegation_self_recovery.py (4). After: 0.
    """

    offenders: list[str] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        prose = _prose_line_numbers(text)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#") or lineno in prose:
                continue  # a comment or docstring explaining the hazard is not a call site
            if _LIVE_CHECKOUT_REPO_ROOT.search(line):
                offenders.append(f"{path.relative_to(TESTS_DIR.parent).as_posix()}:{lineno}: {line.strip()}")

    assert not offenders, (
        "these tests point product code at the live checkout, so anything they "
        "write lands in runtime/ and is read back by a later test:\n" + "\n".join(offenders)
    )


def test_the_worker_still_records_its_task_under_the_root_it_was_given(tmp_path: Path) -> None:
    """The control for the fix above: the write is real, just not in the repo.

    Swapping the repo root for a tmp dir would be worthless if it also stopped
    the worker writing at all -- the leaking tests would go green by doing
    nothing. This drives the same unpatched `update_execution` path the two
    leaking cases hit and shows the record appears under tmp_path (1 file) while
    the checkout's own task_bots directory gains nothing (0 files).
    """

    # The checkout's ledger BY PATH, not by asking the resolver. `task_bot_runtime.runtime_dir()` no longer
    # answers this directory inside a test process -- `shared_root_sandbox` sends a shared root to a
    # throwaway folder -- and pointing this at the sandbox would leave the assertion below measuring a
    # directory nothing in the repo reads, while still passing.
    real_dir = TESTS_DIR.parent / "runtime" / "coordination" / task_bot_runtime.STATE_DIRNAME
    before = {p.name for p in real_dir.glob("*.json")} if real_dir.exists() else set()

    execution_id = str(
        task_bot_runtime.create_execution(
            session_id="sess-leak-probe",
            summary="leak probe",
            repo_root=tmp_path,
        )["execution_id"]
    )

    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())

    async def _events():  # noqa: ANN202
        for _ in range(0):
            yield {}  # makes this an async generator without yielding
        raise asyncio.CancelledError

    async def _drive() -> None:
        with (
            patch(
                "thomas.server.chat_delegation.run_agent_worker_events",
                new=lambda *args, **kwargs: _events(),  # noqa: ARG005
            ),
            patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution"),
        ):
            await chat_delegation._run_agent_worker(
                {},
                execution_id=execution_id,
                prompt="x",
                specialist_id="coding",
                bot=SimpleNamespace(id="nova", name="Nova", to_event_dict=lambda: {}),
                emitter=emitter,
                instructions="do",
                repo_root=tmp_path,
            )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_drive())

    written = tmp_path / "runtime" / "coordination" / "task_bots" / f"{execution_id}.json"
    assert written.is_file(), "the worker no longer records its task at all, so the leak test proves nothing"
    assert "Preparing workspace change baseline." in written.read_text(encoding="utf-8"), (
        "the worker's own progress write is what leaked into the repo; if it no "
        "longer happens this test has stopped covering the defect"
    )

    after = {p.name for p in real_dir.glob("*.json")} if real_dir.exists() else set()
    assert after - before == set(), f"the worker wrote into the real checkout: {sorted(after - before)}"
