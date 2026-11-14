"""Asking Thomas to fix himself has to reach his own code.

Observed live on 2026-09-22, on Autopilot: "use self.issues, pick the top issue,
fix it in your own code". Chat handed off a task whose instructions named
C:\\Users\\corbe\\Thomas, and the run started in a brand-new empty Build project
(``~/.thomas/projects/On Autopilot inspect Thomass actual selfissues``). It
could not reach the code it was asked to fix, a tool call failed, and the card
ended "the run crashed before finishing ... no files changed".

The model had chosen correctly. ``send_task``'s ``workspace="project"`` means
self-development, and the tool description says so. But when a task also set
``needs_build``, the Chat hand-off called ``submit_build_task`` without the
workspace at all, and Build's project defaulted to "new". Build also refuses
Thomas's own source outright (``project_is_thomas_source``), so Build was never
a door that could open. The design spec's Q2 default is the self-development
worker, which is what now gets the task.
"""

from __future__ import annotations

import ast
from pathlib import Path

CHAT_V2 = Path(__file__).resolve().parents[1] / "thomas" / "server" / "routes" / "chat_v2.py"


def _branch_that_starts_a_build() -> ast.If:
    tree = ast.parse(CHAT_V2.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = [
            n
            for stmt in node.body
            for n in ast.walk(stmt)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "submit_build_task"
        ]
        if calls:
            return node
    raise AssertionError("chat_v2 no longer hands anything to submit_build_task")


def test_a_self_development_task_is_not_sent_to_build() -> None:
    condition = ast.unparse(_branch_that_starts_a_build().test)
    assert "needs_build" in condition
    assert "workspace" in condition and "'project'" in condition, (
        "a workspace='project' task still goes to Build, which starts an empty new project "
        f"and refuses Thomas's own source: if {condition}"
    )


def test_the_self_development_worker_is_told_the_workspace() -> None:
    """The fall-through must carry workspace, or the worker runs isolated."""
    src = CHAT_V2.read_text(encoding="utf-8")
    delegation = src[src.index("await start_background_delegation(") :]
    delegation = delegation[: delegation.index("\n        )")]
    assert "workspace=workspace" in delegation


def test_build_really_does_refuse_thomas_own_source() -> None:
    """Why Build is the wrong door, pinned where Build says so."""
    routes = CHAT_V2.parent / "evolve_agent_routes.py"
    assert '"project_is_thomas_source"' in routes.read_text(encoding="utf-8")
