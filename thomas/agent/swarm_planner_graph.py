"""Task-graph serialization for prompt-derived swarm plans."""

from __future__ import annotations

from typing import Any

from thomas.agent.swarm_planner import (
    DEFAULT_SWARM_MAX_TASKS,
    build_prompt_task_slices,
    normalize_request,
    project_label,
)


def build_task_graph_dict(user_request: str | None, max_tasks: int = DEFAULT_SWARM_MAX_TASKS) -> dict[str, Any]:
    limit = max(1, int(max_tasks))
    prompt = normalize_request(user_request)
    slices = build_prompt_task_slices(prompt, 1 if limit == 1 else limit - 1)
    key_to_id = {slice_.key: f"T{index + 1}" for index, slice_ in enumerate(slices)}
    tasks: list[dict[str, Any]] = []
    for slice_ in slices:
        tasks.append(
            {
                "id": key_to_id[slice_.key],
                "title": slice_.title,
                "agent": "coder",
                "deps": [key_to_id[key] for key in slice_.depends_on],
                "prompt": slice_.task_prompt,
                "acceptance": [
                    f"Produce a concrete implementation slice for {slice_.deliverable}",
                    "Respect dependency outputs and avoid conflicting ownership",
                    "Report exactly what was changed or produced",
                ],
                "meta": {
                    "mutates_fs": True,
                    "risk": "med",
                    "scope_key": slice_.key,
                    "focus_term": slice_.focus_term,
                },
            }
        )
    if limit > 1:
        tasks.append(
            {
                "id": f"T{len(tasks) + 1}",
                "title": "Integrated Validation",
                "agent": "tester",
                "deps": [task["id"] for task in tasks],
                "prompt": (
                    f"Validate the integrated result for {prompt}. "
                    "Use prior task outputs, run checks if possible, and report what still fails."
                ),
                "acceptance": [
                    "State whether the composed result works",
                    "List the strongest evidence for that judgment",
                    "Call out blockers or missing integration if present",
                ],
                "meta": {"mutates_fs": False, "risk": "low", "scope_key": "integrated_validation"},
            }
        )
    return {
        "version": 1,
        "goal": prompt,
        "summary": f"Prompt-derived task graph for {project_label(prompt) or 'requested project'}",
        "tasks": tasks,
    }


__all__ = ["build_task_graph_dict"]
