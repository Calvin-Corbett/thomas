from thomas.agent.task_definition import (
    augment_prompt_with_task_definition,
    derive_task_definition,
    evaluate_task_result,
    should_activate_task_definition,
)


def test_should_activate_task_definition_requires_max_mode_and_task_like_prompt() -> None:
    assert should_activate_task_definition(
        prompt_text="Build a snake game in HTML and JavaScript",
        applied_token_economy="max",
        requested_job_type=None,
    )
    assert not should_activate_task_definition(
        prompt_text="What time is it?",
        applied_token_economy="max",
        requested_job_type=None,
    )
    assert not should_activate_task_definition(
        prompt_text="Build a snake game in HTML and JavaScript",
        applied_token_economy="cheap",
        requested_job_type=None,
    )


def test_derive_task_definition_prioritizes_visible_success_for_interactive_tasks() -> None:
    definition = derive_task_definition("Build a snake game with start, score, restart, and no console errors.")
    payload = definition.to_dict()
    assert payload["deliverable_type"] == "interactive_game"
    assert payload["interactive"] is True
    assert any("visibly advances" in item.lower() for item in payload["visible_success_criteria"])
    assert any("manual time advancement" in item.lower() for item in payload["failure_conditions"])


def test_augment_prompt_with_task_definition_embeds_contract() -> None:
    definition = derive_task_definition("Build a snake game")
    prompt = augment_prompt_with_task_definition("Build a snake game", definition.to_dict())
    assert "[Task Definition Contract]" in prompt
    assert "Visible success criteria:" in prompt


def test_evaluate_task_result_fails_interactive_task_without_visible_verification_language() -> None:
    definition = derive_task_definition("Build a snake game")
    evaluation = evaluate_task_result(
        definition.to_dict(),
        response_text="Completed. Files written to the output directory.",
        token_report={"rules_of_road": {"passed": True}},
        run_ok=True,
    )
    assert evaluation["status"] == "failed"
    assert any("visible-behavior verification" in item.lower() for item in evaluation["failed_checks"])


def test_evaluate_task_result_passes_when_interactive_verification_is_stated() -> None:
    definition = derive_task_definition("Build a snake game")
    evaluation = evaluate_task_result(
        definition.to_dict(),
        response_text="Completed and verified. I opened the page, clicked Start, and confirmed the snake visibly moves.",
        token_report={"rules_of_road": {"passed": True}},
        run_ok=True,
    )
    assert evaluation["status"] == "passed"
