"""A self-edit run is fenced by the board's claims (2026-09-07).

Tonight a Redesign sent to Thomas's own code was told, in prose, to leave six
files alone that other agents held on the workboard. The run edited two of
them, collided with another agent's repair, and was stopped. The write tools
can now refuse a fenced path (``protected_paths`` on the loop); this is where
the list comes from.

Every scope another agent claims on the board is fenced for a self-edit run.
The fence is computed on the server from plans/thomas/WORKBOARD.md when the
Redesign is sent, listed in the brief so the model can say "not mine to
change" instead of trying, carried on the conversation record so the run
that starts later can enforce it, and passed by the client with the new
thread. Only the server's own environment can exempt an agent; nothing the
client sends weakens another agent's fence.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil import forge_code_store
from thomas.server.routes import ui_redesign_runtime as rt
from thomas.server.routes import work_dashboard_runtime as dash

BOARD = """# Board

## Agent Claims

- agent=codex-image-takeover; name=Codex takeover; role=solo; parent=none; scope=thomas/server/chat_delegation.py,thomas/server/web/chat.html; task=IMAGE-CHAT-TAKEOVER-20260907
- agent=claude; name=Claude; role=solo; parent=none; scope=thomas/tools/web_preflight.py,plans/thomas/tasks/FRONTIER-PARITY-20260905; task=FRONTIER-PARITY-20260905
- agent=codex-cleanup-final; name=Final cleanup; role=worker; parent=codex-integrator; scope=plans/thomas/problems/GENERATED-MODULE-DELETION-20260902; task=GENERATED-MODULE-DELETION-20260902

## Active Tasks

- task_id=FRONTIER-PARITY-20260905; agent=claude; scope=thomas/tools/web_preflight.py; summary=x; status=active
"""


def test_every_other_agents_scope_is_fenced_and_an_exempt_agent_is_not() -> None:
    fenced = rt.board_fenced_paths(BOARD, exempt_agents={"claude"})
    assert fenced == [
        "plans/thomas/problems/GENERATED-MODULE-DELETION-20260902",
        "thomas/server/chat_delegation.py",
        "thomas/server/web/chat.html",
    ]
    assert "thomas/tools/web_preflight.py" in rt.board_fenced_paths(BOARD, exempt_agents=set())


def test_a_board_without_claims_fences_nothing() -> None:
    assert rt.board_fenced_paths("# Board\n\n## Active Tasks\n", exempt_agents=set()) == []
    assert rt.board_fenced_paths("", exempt_agents=set()) == []


def test_the_brief_names_the_fence_so_the_model_can_decline() -> None:
    prompt = rt.code_thread_prompt(
        "make the chip blue",
        [{"uiId": "chat.action.activity", "label": "Activity button", "component": "button", "text": "Activity"}],
        "chat",
        unsupported=[],
        applied=[],
        server_url="http://127.0.0.1:8977/",
        protected_paths=["thomas/server/web/chat.html", "thomas/server/chat_delegation.py"],
    )
    assert "thomas/server/web/chat.html" in prompt and "thomas/server/chat_delegation.py" in prompt
    assert "fenced" in prompt.lower() and "refuse" in prompt.lower()


def test_the_fence_is_read_from_the_project_boards_file(tmp_path: Path, monkeypatch) -> None:
    board = tmp_path / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text(BOARD, encoding="utf-8")
    monkeypatch.delenv("THOMAS_REDESIGN_EXEMPT_AGENTS", raising=False)
    assert "thomas/tools/web_preflight.py" in dash.fenced_paths_for(tmp_path)
    monkeypatch.setenv("THOMAS_REDESIGN_EXEMPT_AGENTS", "claude")
    fenced = dash.fenced_paths_for(tmp_path)
    assert "thomas/tools/web_preflight.py" not in fenced and "thomas/server/web/chat.html" in fenced
    assert dash.fenced_paths_for(tmp_path / "elsewhere") == []


def test_the_conversation_record_carries_the_fence() -> None:
    conv = forge_code_store.draft_conversation(title="t", self_edit=True, protected_paths=["a.py", " ", "b/"])
    assert conv["protected_paths"] == ["a.py", "b/"]
    assert "protected_paths" not in forge_code_store.draft_conversation(title="t")


def test_a_long_fence_is_summarised_in_the_brief_but_kept_whole_on_the_record() -> None:
    many = [f"thomas/pkg{i}/mod{i}.py" for i in range(431)]
    prompt = rt.code_thread_prompt(
        "make the chip blue",
        [{"uiId": "chat.action.activity", "label": "Activity button", "component": "button", "text": "Activity"}],
        "chat",
        unsupported=[],
        applied=[],
        server_url="http://127.0.0.1:8977/",
        protected_paths=many,
    )
    listed = [p for p in many if p in prompt]
    assert 1 <= len(listed) <= rt.FENCE_BRIEF_LIMIT < 431
    assert "431" in prompt  # the count is stated; the tools refuse every one of them
    conv = forge_code_store.draft_conversation(title="t", self_edit=True, protected_paths=many)
    assert len(conv["protected_paths"]) == 431
