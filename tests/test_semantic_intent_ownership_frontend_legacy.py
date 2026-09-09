"""Regression guards for prompt semantics formerly owned outside Thomas."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "thomas/server/web/js/runtime"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_browser_does_not_infer_tasks_or_rooms_from_prompt_words() -> None:
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in sorted(RUNTIME_DIR.glob("*.js")))
    for forbidden in (
        "chatPromptLooksTaskLike",
        "chatShouldSeedTaskUi",
        "OFFICE_TASK_KEYWORDS",
        "OFFICE_TASK_ROOM_RULES",
        "officeResolveRoomForTask",
        "officeMaybeQueueTaskFromPrompt",
    ):
        assert forbidden not in runtime

    assert "officeSyncStructuredDelegationTask(evt, status, taskText);" in runtime
    assert "OFFICE_SPECIALIST_ROOM_IDS[specialistId]" in runtime
    assert "evt.room_id || evt.roomId" in runtime


def test_mention_task_creation_requires_the_explicit_task_command() -> None:
    # The live mention handler (the js/modules archive copies were deleted).
    source = _read("thomas/server/web/js/runtime/020_virtual_office_04.js")
    assert "parsed.command === 'task'" in source
    assert "lower.includes('build')" not in source
    assert "lower.includes('ship')" not in source
    assert "OFFICE_TASK_KEYWORDS" not in source


def test_natural_language_cannot_switch_runtime_model() -> None:
    assert not (ROOT / "thomas/models/switching.py").exists()

    command_source = _read("thomas/cli/_commands_base.py")
    repl_source = _read("thomas/cli/repl.py")
    slash_source = _read("thomas/cli/repl_slash.py")
    server_source = _read("thomas/server/app_middleware_handlers.py")
    assert "_parse_model_switch_prompt" not in command_source
    assert "_handle_nl_model" not in repl_source
    assert "_resolve_natural_model_switch_request" not in server_source

    # Explicit command/UI selection remains supported.
    assert '"/model"' in slash_source
    assert "Switch or list model profiles" in slash_source


def test_legacy_chat_route_does_not_derive_task_contract_from_prompt() -> None:
    route_source = _read("thomas/server/routes/chat_request_execution.py")
    for forbidden in (
        "thomas.agent.task_definition",
        "should_activate_task_definition",
        "derive_task_definition",
        "augment_prompt_with_task_definition",
        "evaluate_task_result",
    ):
        assert forbidden not in route_source
    assert not (ROOT / "thomas/agent/task_definition.py").exists()
