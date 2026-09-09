from thomas.marketplace.autonomy.mode_policy import apply_workflow_mode_policy


def test_max_mode_does_not_classify_coding_prose_or_select_a_pipeline() -> None:
    payload, meta = apply_workflow_mode_policy(
        {
            "goal": "Refactor function in repo and add tests",
            "workflow": "chain",
            "mode": "thinking",
            "token_economy": "max",
        }
    )
    assert payload["workflow"] == "chain"
    assert "worker_count" not in payload
    assert meta["applied"] is False
    assert meta["task_class"] == "general"
    assert meta["reason"] == "structured_routing_only"


def test_explicit_structured_workflow_and_task_class_are_preserved() -> None:
    payload, meta = apply_workflow_mode_policy(
        {
            "goal": "Any prose is content",
            "workflow": "coding_pipeline",
            "task_class": "coding",
            "mode": "auto",
            "token_economy": "optimal",
        }
    )
    assert payload["workflow"] == "coding_pipeline"
    assert meta["effective_workflow"] == "coding_pipeline"
    assert meta["task_class"] == "coding"
