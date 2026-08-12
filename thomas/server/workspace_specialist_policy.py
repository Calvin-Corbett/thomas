"""Exact semantic action policies for Thomas workspace residents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from thomas.server.routes.chat_surface_namespace import normalize_workspace_context_id


@dataclass(frozen=True, slots=True)
class WorkspaceActionSpec:
    description: str
    mutating: bool = False
    reversible: bool = False
    preference_keys: frozenset[str] = frozenset()
    required_capabilities: frozenset[str] = frozenset()


SETTINGS_PREFERENCE_KEYS = frozenset(
    {
        "animation_fidelity",
        "code_theme",
        "default_autonomy_level",
        "default_model",
        "default_reasoning_effort",
        "default_run_mode",
        "default_token_economy",
        "show_token_meter",
        "ui_density",
    }
)
TOKEN_PREFERENCE_KEYS = frozenset(
    {
        "daily_token_budget",
        "default_token_economy",
        "reasoning_token_budget",
        "session_token_budget",
        "show_token_meter",
        "token_throttle_enabled",
    }
)

_INSPECT = WorkspaceActionSpec("Read the current workspace's bounded server-owned status.")
_MISSION_LIST = WorkspaceActionSpec("List Mission Control jobs and their current status.")

WORKSPACE_ACTION_POLICIES: dict[str, dict[str, WorkspaceActionSpec]] = {
    "mission": {
        "workspace.inspect": _INSPECT,
        "mission.jobs.list": _MISSION_LIST,
        "mission.job.cancel": WorkspaceActionSpec(
            "Cancel one Mission Control job.", True, False, required_capabilities=frozenset({"allow_file_write"})
        ),
        "mission.job.requeue": WorkspaceActionSpec(
            "Requeue one Mission Control job.", True, True, required_capabilities=frozenset({"allow_file_write"})
        ),
        "mission.job.run_now": WorkspaceActionSpec(
            "Queue one Mission Control job to run now.", True, True, required_capabilities=frozenset({"allow_file_write"})
        ),
    },
    "office": {
        "workspace.inspect": _INSPECT,
        "mission.jobs.list": _MISSION_LIST,
        "office.view.set_follow_agent": WorkspaceActionSpec(
            "Persist which live Virtual Office agent the shared viewport follows, or clear follow mode.",
            True,
            True,
            required_capabilities=frozenset({"allow_file_write"}),
        ),
    },
    "app_builder": {
        "workspace.inspect": _INSPECT,
        "canvas.spec.save": WorkspaceActionSpec(
            "Atomically save one Canvas UI spec by stable id.",
            True,
            True,
            required_capabilities=frozenset({"allow_file_write"}),
        ),
    },
    "my_stuff": {
        "workspace.inspect": _INSPECT,
        "library.project.move": WorkspaceActionSpec(
            "Persist a Library project's board position.",
            True,
            True,
            required_capabilities=frozenset({"allow_file_write"}),
        ),
    },
    "channels": {
        "workspace.inspect": _INSPECT,
        "channels.discord.set_enabled": WorkspaceActionSpec(
            "Persistently enable or disable the Discord channel bridge.",
            True,
            True,
            required_capabilities=frozenset({"allow_channels"}),
        ),
    },
    "token_economy": {
        "workspace.inspect": _INSPECT,
        "preferences.get": WorkspaceActionSpec(
            "Read one token-economy preference.", preference_keys=TOKEN_PREFERENCE_KEYS
        ),
        "preferences.list": WorkspaceActionSpec(
            "List bounded token-economy preferences.", preference_keys=TOKEN_PREFERENCE_KEYS
        ),
        "preferences.set": WorkspaceActionSpec(
            "Update one token-economy preference.",
            True,
            True,
            TOKEN_PREFERENCE_KEYS,
            frozenset({"allow_file_write"}),
        ),
    },
    "marketplace": {
        "workspace.inspect": _INSPECT,
        "marketplace.plugin.set_enabled": WorkspaceActionSpec(
            "Enable or disable one already-installed Marketplace plugin.",
            True,
            True,
            required_capabilities=frozenset({"allow_file_write"}),
        ),
    },
    "paper_trading": {
        "workspace.inspect": _INSPECT,
        "paper_trading.propose": WorkspaceActionSpec(
            "Persist a risk-checked paper-trade proposal for owner approval without submitting it.",
            True,
            False,
            required_capabilities=frozenset({"allow_file_write"}),
        ),
    },
    "settings": {
        "workspace.inspect": _INSPECT,
        "preferences.get": WorkspaceActionSpec(
            "Read one bounded Thomas preference.", preference_keys=SETTINGS_PREFERENCE_KEYS
        ),
        "preferences.list": WorkspaceActionSpec(
            "List bounded Thomas settings preferences.", preference_keys=SETTINGS_PREFERENCE_KEYS
        ),
        "preferences.set": WorkspaceActionSpec(
            "Update one bounded Thomas preference.",
            True,
            True,
            SETTINGS_PREFERENCE_KEYS,
            frozenset({"allow_file_write"}),
        ),
    },
}

WORKSPACE_LABELS = {
    "mission": "Mission Control",
    "office": "Virtual Office",
    "app_builder": "Canvas",
    "my_stuff": "Library",
    "channels": "Channels",
    "token_economy": "Token Economy",
    "marketplace": "Marketplace",
    "paper_trading": "Paper Trading",
    "settings": "Settings",
}

GUARDED_TOOL_NAMES = {
    "canvas.spec.save": "fs.write.workspace",
    "channels.discord.set_enabled": "channel_management",
    "library.project.move": "fs.write.workspace",
    "marketplace.plugin.set_enabled": "fs.write.workspace",
    "mission.job.cancel": "db.command",
    "mission.job.requeue": "db.command",
    "mission.job.run_now": "db.command",
    "office.view.set_follow_agent": "db.command",
    "paper_trading.propose": "db.command",
    "preferences.set": "db.command",
}


def workspace_key_from_context(context_id: str) -> str:
    return normalize_workspace_context_id(context_id).removeprefix("workspace:")


def workspace_tool_spec(workspace_key: str) -> dict[str, Any]:
    actions = sorted(WORKSPACE_ACTION_POLICIES[workspace_key])
    return {
        "type": "function",
        "function": {
            "name": "operate_workspace",
            "description": (
                "Inspect or directly operate the current Thomas workspace. "
                "Only the listed semantic actions are available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": actions},
                    "key": {"type": "string", "description": "Preference key, when required."},
                    "value": {"description": "Preference value, when required."},
                    "target_id": {"type": "string", "description": "Stable target id, when required."},
                    "payload": {
                        "type": "object",
                        "description": "Bounded workspace-specific structured values, when required.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    }


__all__ = [
    "GUARDED_TOOL_NAMES",
    "WORKSPACE_ACTION_POLICIES",
    "WORKSPACE_LABELS",
    "WorkspaceActionSpec",
    "workspace_key_from_context",
    "workspace_tool_spec",
]
