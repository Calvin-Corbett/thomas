from __future__ import annotations

import json
from pathlib import Path


def test_browser_workflow_corpus_is_well_formed_and_coverage_rich() -> None:
    prod_root = Path(__file__).resolve().parents[1] / "thomas" / "browser" / "workflow_corpus"
    test_root = Path(__file__).resolve().parent / "browser_workflow_corpus"
    files = sorted(prod_root.glob("*.json"))
    mirror_files = sorted(test_root.glob("*.json"))
    assert len(files) >= 1536
    assert len(mirror_files) == len(files)

    seen_ids: set[str] = set()
    actions: set[str] = set()
    categories: set[str] = set()
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        workflow_id = str(payload.get("workflow_id") or "")
        assert workflow_id
        assert workflow_id not in seen_ids
        seen_ids.add(workflow_id)
        category = str(payload.get("category") or "")
        assert category
        categories.add(category)
        steps = payload.get("steps") or []
        assert isinstance(steps, list)
        assert len(steps) >= 24
        for step in steps:
            assert isinstance(step, dict)
            action = str(step.get("action") or "")
            assert action
            actions.add(action)
        assertions = payload.get("assertions") or []
        assert isinstance(assertions, list)
        assert len(assertions) >= 10

    required_actions = {
        "open_url",
        "click",
        "type",
        "wait_for_selector",
        "capture_screenshot",
        "collect_network",
        "start_trace",
        "stop_trace",
    }
    assert required_actions.issubset(actions)
    assert len(categories) >= 10
