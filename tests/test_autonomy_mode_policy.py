from thomas.marketplace.autonomy.mode_policy import apply_workflow_mode_policy, classify_task


def test_classify_task_detects_coding_signals() -> None:
    payload = {"goal": "Fix bug in src/app.py and add a unit test"}
    assert classify_task(payload) == "coding"


def test_mode_policy_uses_coding_pipeline_for_max_coding() -> None:
    payload, meta = apply_workflow_mode_policy(
        {
            "goal": "Refactor function in repo and add tests",
            "mode": "thinking",
            "token_economy": "max",
        }
    )
    assert payload.get("workflow") == "coding_pipeline"
    assert int(payload.get("max_rounds") or 0) >= 1
    assert bool(meta.get("applied"))
    assert str(meta.get("reason") or "") == "max_coding_pipeline"


def test_mode_policy_keeps_general_task_unchanged() -> None:
    payload, meta = apply_workflow_mode_policy(
        {
            "goal": "Summarize this meeting",
            "workflow": "chain",
            "mode": "auto",
            "token_economy": "optimal",
        }
    )
    assert payload.get("workflow") == "chain"
    assert not bool(meta.get("applied"))
    assert str(meta.get("task_class") or "") == "general"
