"""Structured model-owned state updates for Work onboarding.

The browser must never infer a goal, workflow, phase, or selection from prose.
Thomas's model owns those semantic decisions and records them through this
function tool. Runtime code only validates the structured envelope.
"""

from __future__ import annotations

WORK_ONBOARDING_UPDATE_TOOL_NAME = "work_onboarding_update"

WORK_ONBOARDING_UPDATE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": WORK_ONBOARDING_UPDATE_TOOL_NAME,
        "description": (
            "Record your current structured understanding of a Work onboarding conversation. "
            "This tool is available only while creating a Work job. Call it once on every turn "
            "before replying. You own the semantic decisions: choose the phase, confirmed goal, "
            "workflow map, and whether the explicitly selected workflow is configured. Ordinary "
            "prose is never parsed to create or select workflows. Do not invent a selection; copy "
            "selected_workflow_id from the current structured state only after the user clicks one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "enum": ["goal_discovery", "workflow_mapping", "workflow_configuration"],
                },
                "confirmed_goal": {
                    "type": "string",
                    "description": "The confirmed job goal, or an empty string while it is still unclear.",
                },
                "workflows": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "purpose": {"type": "string"},
                            "type": {"type": "string", "enum": ["manual", "scheduled", "event"]},
                            "connector_suggestions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["id", "name", "purpose", "type", "connector_suggestions"],
                    },
                },
                "selected_workflow_id": {
                    "type": "string",
                    "description": "Copy the current explicit browser selection, or use an empty string.",
                },
                "selected_workflow_configured": {
                    "type": "boolean",
                    "description": "True only when the selected workflow has enough configuration to create the job.",
                },
            },
            "required": [
                "phase",
                "confirmed_goal",
                "workflows",
                "selected_workflow_id",
                "selected_workflow_configured",
            ],
        },
    },
}

__all__ = ["WORK_ONBOARDING_UPDATE_TOOL", "WORK_ONBOARDING_UPDATE_TOOL_NAME"]
