import os
from pathlib import Path

from thomas.agent.task_definition import (
    augment_prompt_with_task_definition,
    derive_task_definition,
    evaluate_required_artifact_contract,
    evaluate_task_result,
    extract_required_artifact_contract,
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


def test_extract_required_artifact_contract_parses_exact_relative_path_and_mention() -> None:
    prompt = """
Before finishing, write a JSON report to this exact relative path:
- runtime/agentic_bench/run-x/thomas_os/endurance_report.json

In your final response, mention: runtime/agentic_bench/run-x/thomas_os/endurance_report.json
""".strip()
    contract = extract_required_artifact_contract(prompt)
    assert contract["required_artifact_paths"] == ["runtime/agentic_bench/run-x/thomas_os/endurance_report.json"]
    assert contract["required_response_mentions"] == ["runtime/agentic_bench/run-x/thomas_os/endurance_report.json"]


def test_evaluate_required_artifact_contract_checks_files_and_mentions(tmp_path: Path) -> None:
    prompt = """
Before finishing, write a JSON report to this exact relative path:
- runtime/agentic_bench/run-x/thomas_os/endurance_report.json

In your final response, mention: runtime/agentic_bench/run-x/thomas_os/endurance_report.json
""".strip()
    missing = evaluate_required_artifact_contract(prompt, response_text="Done.", repo_root=tmp_path)
    assert missing["passed"] is False
    assert missing["missing_paths"] == ["runtime/agentic_bench/run-x/thomas_os/endurance_report.json"]
    assert missing["missing_response_mentions"] == ["runtime/agentic_bench/run-x/thomas_os/endurance_report.json"]

    report_path = tmp_path / "runtime/agentic_bench/run-x/thomas_os/endurance_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"ok": true}\n', encoding="utf-8")
    passed = evaluate_required_artifact_contract(
        prompt,
        response_text="Wrote runtime/agentic_bench/run-x/thomas_os/endurance_report.json",
        repo_root=tmp_path,
    )
    assert passed["passed"] is True
    assert passed["missing_paths"] == []
    assert passed["missing_response_mentions"] == []


def test_evaluate_required_artifact_contract_uses_benchmark_repo_root_env(tmp_path: Path) -> None:
    prompt = """
Before finishing, write a JSON report to this exact relative path:
- runtime/agentic_bench/run-x/thomas_os/endurance_report.json

In your final response, mention: runtime/agentic_bench/run-x/thomas_os/endurance_report.json
""".strip()
    report_path = tmp_path / "runtime/agentic_bench/run-x/thomas_os/endurance_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"ok": true}\n', encoding="utf-8")
    previous = os.environ.get("THOMAS_BENCHMARK_REPO_ROOT")
    try:
        os.environ["THOMAS_BENCHMARK_REPO_ROOT"] = str(tmp_path)
        passed = evaluate_required_artifact_contract(
            prompt,
            response_text="Wrote runtime/agentic_bench/run-x/thomas_os/endurance_report.json",
        )
    finally:
        if previous is None:
            os.environ.pop("THOMAS_BENCHMARK_REPO_ROOT", None)
        else:
            os.environ["THOMAS_BENCHMARK_REPO_ROOT"] = previous
    assert passed["passed"] is True
    assert passed["repo_root"] == str(tmp_path.resolve())


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


def test_evaluate_task_result_fails_when_required_artifact_is_missing() -> None:
    prompt = """
Implement the change.

Before finishing, write a JSON report to this exact relative path:
- runtime/agentic_bench/run-x/thomas_os/endurance_report.json

In your final response, mention: runtime/agentic_bench/run-x/thomas_os/endurance_report.json
""".strip()
    definition = derive_task_definition(prompt)
    evaluation = evaluate_task_result(
        definition.to_dict(),
        response_text="Implemented the change.",
        token_report={"rules_of_road": {"passed": True}},
        run_ok=True,
    )
    assert evaluation["status"] == "failed"
    assert any("required artifact path is missing" in item.lower() for item in evaluation["failed_checks"])
