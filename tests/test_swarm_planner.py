import json

from thomas.agent.swarm import TaskGraph
from thomas.agent.swarm_planner import build_prompt_task_slices, build_task_graph_dict, prompt_units, slug


FINANCE_PROMPT = """
You are a senior engineer briefing a team of junior developers.

We need a useful browser-based personal finance app. Keep it dependency-free and local-first. It should feel like a real product, not a demo.

Required broad capabilities:
- track income and expenses
- organize transactions into categories
- show account or budget summaries
- let the user filter and review past activity
- persist data locally in the browser
- polished responsive UI

In addition to the required capabilities above, add 3 genuinely useful features of your own choosing.

Make practical product decisions where the spec is vague. No external dependencies.
""".strip()


def test_prompt_task_slices_scale_without_fallback_project_unit() -> None:
    prompt = "Build a simple CRM with contacts, pipelines, tasks, notes, and reporting"
    slices = build_prompt_task_slices(prompt, 25)
    keys = {slice_.key for slice_ in slices}

    assert "project" not in prompt_units(prompt)
    assert len(slices) == 25
    assert len(keys) == 25
    for slice_ in slices:
        assert set(slice_.depends_on).issubset(keys)


def test_task_graph_dict_parses_as_valid_swarm_task_graph() -> None:
    graph_obj = build_task_graph_dict(
        "Build a collaborative note board with columns, cards, comments, and search",
        max_tasks=7,
    )
    graph = TaskGraph.from_planner_json(json.dumps(graph_obj))

    assert graph.goal == "Build a collaborative note board with columns, cards, comments, and search"
    assert len(graph.tasks) == 7
    assert "T7" in graph.tasks
    assert graph.tasks["T7"].agent == "tester"
    assert graph.tasks["T7"].deps == tuple(f"T{index}" for index in range(1, 7))


def test_single_task_graph_skips_integrated_validation() -> None:
    graph_obj = build_task_graph_dict("Build a lightweight budget tracker", max_tasks=1)
    graph = TaskGraph.from_planner_json(json.dumps(graph_obj))

    assert list(graph.tasks) == ["T1"]
    assert graph.tasks["T1"].agent == "coder"


def test_prompt_units_extract_subject_and_bullet_capabilities() -> None:
    units = prompt_units(FINANCE_PROMPT)

    assert units[0].endswith("personal finance app")
    assert "track income and expenses" in units
    assert "organize transactions into categories" in units
    assert len(units) == len({slug(unit) for unit in units})


def test_task_graph_dict_keeps_unique_task_ids_for_vague_bullet_prompt() -> None:
    graph_obj = build_task_graph_dict(FINANCE_PROMPT, max_tasks=9)
    task_ids = [task["id"] for task in graph_obj["tasks"]]

    assert len(task_ids) == len(set(task_ids))

    graph = TaskGraph.from_planner_json(json.dumps(graph_obj))
    assert list(graph.tasks) == [f"T{index}" for index in range(1, 10)]
