import json
import pytest
from thomas.agent.swarm import TaskGraph


def test_taskgraph_rejects_unknown_keys():
    bad = {
        "version": 1,
        "goal": "x",
        "tasks": [],
        "extra": 123,
    }
    with pytest.raises(ValueError):
        TaskGraph.from_planner_json(json.dumps(bad))


def test_taskgraph_cycle_detect():
    obj = {
        "version": 1,
        "goal": "x",
        "summary": "",
        "tasks": [
            {"id": "A", "title": "A", "agent": "coder", "deps": ["B"], "prompt": "", "acceptance": [], "meta": {}},
            {"id": "B", "title": "B", "agent": "coder", "deps": ["A"], "prompt": "", "acceptance": [], "meta": {}},
        ],
    }
    with pytest.raises(ValueError):
        TaskGraph.from_planner_json(json.dumps(obj))
