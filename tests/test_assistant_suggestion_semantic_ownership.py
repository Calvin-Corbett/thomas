"""Frontend guards for model-owned prompt semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "thomas/server/web/js"


def _read(relative_path: str) -> str:
    return (WEB_JS / relative_path).read_text(encoding="utf-8")


def test_followup_suggestions_do_not_classify_conversation_prose() -> None:
    live_options = _read("runtime/006_easy_setup_onboarding_04.js")
    live_display = _read("runtime/007_easy_setup_onboarding_05.js")
    combined = "\n".join((live_options, live_display))

    for forbidden in (
        "classifySuggestionIntent",
        "buildIntentSuggestionOptions",
        "withSuggestionContext",
        "context: `followup_${intent}`",
    ):
        assert forbidden not in combined

    assert "function buildUniversalFollowupSuggestionOptions()" in live_options
    assert "function maybeShowAssistantFollowups()" in live_display
    assert "context: 'followup'" in live_display
    assert "options: buildUniversalFollowupSuggestionOptions()" in live_display
    assert "userText" not in live_display
    assert "assistantText" not in live_display


def test_followup_callers_do_not_forward_prose_for_local_categorization() -> None:
    live_stream = _read("runtime/013_actions_interactions_02.js")
    live_history = _read("runtime/039_module_rendering_dispatch_02.js")

    assert "maybeShowAssistantFollowups();" in live_stream
    assert "maybeShowAssistantFollowups();" in live_history
    assert "maybeShowAssistantFollowups({" not in live_stream
    assert "maybeShowAssistantFollowups({" not in live_history


def test_task_ui_starts_from_structured_runtime_events_not_prompt_keywords() -> None:
    live_helpers = _read("runtime/003_easy_setup_onboarding_01.js")
    live_stream = _read("runtime/013_actions_interactions_02.js")
    combined = "\n".join((live_helpers, live_stream))

    for forbidden in (
        "chatPromptLooksTaskLike",
        "chatShouldSeedTaskUi",
        "_promptTaskSeed",
    ):
        assert forbidden not in combined

    # The visual task strip remains; a structured task/delegation event creates it.
    assert "function _ensureTaskUi(summaryText = '')" in live_stream
    assert "_ensureTaskUi(taskText);" in live_stream


def test_live_office_uses_structured_room_and_task_fields() -> None:
    config = _read("runtime/office_static_config.js")
    chat_send = _read("runtime/011_chat_games_02.js")
    stream = _read("runtime/013_actions_interactions_02.js")
    mission_bridge = _read("runtime/019_virtual_office_03.js")
    office = _read("runtime/020_virtual_office_04.js")
    combined = "\n".join((config, chat_send, stream, mission_bridge, office))

    for forbidden in (
        "OFFICE_TASK_KEYWORDS",
        "OFFICE_TASK_ROOM_RULES",
        "officeResolveRoomForTask",
        "officeMaybeQueueTaskFromPrompt",
        "lower.includes('build')",
        "lower.includes('ship')",
    ):
        assert forbidden not in combined

    assert "const OFFICE_EXPLICIT_ROOM_IDS = Object.freeze({" in config
    assert "const OFFICE_SPECIALIST_ROOM_IDS = Object.freeze({" in config
    assert "function officeSyncStructuredDelegationTask(" in office
    assert "evt.room_id || evt.roomId" in office
    assert "OFFICE_SPECIALIST_ROOM_IDS[specialistId]" in office
    assert "officeSyncStructuredDelegationTask(evt, status, taskText);" in stream
    assert "return OFFICE_MISSION_ROOM_TO_OFFICE_ROOM[missionRoom] || 'room-lobby';" in mission_bridge
    assert "} else if (parsed.command === 'task') {" in office


def test_game_studio_does_not_fake_prompt_understanding_with_keywords() -> None:
    live = _read("runtime/033_workbench_editors_05.js")
    start = live.index("function moduleGameStudioAssistantReply(")
    end = live.index("function moduleGameStudioOpenCommand(", start)
    reply_function = live[start:end]

    assert "function moduleGameStudioAssistantReply(wb)" in reply_function
    assert "promptRaw" not in reply_function
    assert ".includes(" not in reply_function
    assert "Free-form requests are handled by Thomas in Code mode" in reply_function
    assert "moduleGameStudioAssistantReply(wb, prompt)" not in live
