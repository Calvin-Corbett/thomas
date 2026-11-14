"""Who owns what: the map scripts/plugins/carve.py carves the repo by. First match wins."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plugin:
    name: str
    summary: str
    paths: tuple[str, ...]


def _server(*names: str) -> tuple[str, ...]:
    return tuple(f"thomas/server/{name}" for name in names)


def _routes(*names: str) -> tuple[str, ...]:
    return tuple(f"thomas/server/routes/{name}" for name in names)


def _core(*names: str) -> tuple[str, ...]:
    return tuple(f"thomas/core/{name}" for name in names)


#: Needs written ahead of the imports that will earn them, so the commits that move call sites never touch plugins/.
#: Each entry is a path and the plugins that will import it; carve adds it to their needs, and the entry goes when the
#: import is real. The models slot: one plugin per group of the 25 direct ``LLMClient(`` sites.
RESERVED_NEEDS: dict[str, tuple[str, ...]] = {
    "thomas/core/llm_slot.py": (
        "build",
        "chat",
        "cli",
        "companion",
        "core",
        "demo",
        "integrations",
        "server",
        "services",
        "work",
    ),
}


MAP = (
    Plugin(
        "checks",
        "The check before your card and its proof machinery.",
        ("thomas/server/precard/**", "thomas/server/proof/**"),
    ),
    Plugin(
        "selfchange",
        "How Thomas changes itself: projects, hand-ins, holds, greens, the keeper and landed code.",
        (
            *_server(
                "autopilot_*.py",
                "capacity_ledger*.py",
                "dial_elevation.py",
                "green_*.py",
                "hand_in_hold*.py",
                "keeper_guard*.py",
                "landed_code_*.py",
                "repair_ledger.py",
                "self_*.py",
                "stale_execution_sweep.py",
                "thomas_project*.py",
                "window_records.py",
            ),
            *_routes("autopilot_*.py", "dial_elevation_routes.py", "self_project_*.py", "self_review.py"),
            *_core("self_change_ledger.py", "self_upgrade_engine.py", "green_place.py", "protected_write_grants.py"),
        ),
    ),  # fmt: skip
    Plugin(
        "ratchet",
        "Thomas's unattended repair loop.",
        ("thomas/server/ratchet/**", "thomas/server/routes/ratchet_routes.py"),
    ),
    Plugin(
        "praxis",
        "Running a team of agents: launches, runs and their records.",
        (
            "thomas/server/praxis/**",
            "thomas/core/praxis/**",
            "thomas/core/praxis_scaffold.py",
            "thomas/server/routes/praxis_run_routes.py",
        ),
    ),
    Plugin(
        "build",
        "The Build engine and everything that drives a Build run.",
        (
            "thomas/forge/**",
            "thomas/core/coding_agents/**",
            "evolve_supervisor/**",
            *_routes("evolve_*.py", "fleet_reply_routes.py", "run_telemetry_routes.py", "worktree_progress_routes.py"),
        ),
    ),  # fmt: skip
    Plugin(
        "chat",
        "Chat: its turns, delegation, deliverables and surfaces.",
        (
            "thomas/chat/**",
            "thomas/chat_logger.py",
            *_server(
                "chat_*.py",
                "app_chat_store.py",
                "app_routes_chat_storage.py",
                "agent_spawn_tool.py",
                "delegation_lifecycle.py",
                "deliverable_*.py",
                "exhaustive_*.py",
                "game_playtest.py",
                "swarm_mode.py",
                "worker_runtime.py",
                "workspace_specialist_runtime.py",
            ),
            *_routes(
                "chat_*.py",
                "deliverable_*.py",
                "mention_context_routes.py",
                "sessions_aiohttp.py",
                "task_events.py",
                "todo_routes.py",
                "user_questions_routes.py",
            ),
        ),
    ),  # fmt: skip
    Plugin(
        "workspace",
        "Local projects and the workspace specialist.",
        (
            "thomas/server/workspace/**",
            "thomas/server/workspace_specialist_*.py",
            *_routes("local_project*.py", "source_annotation_routes.py"),
            *_core("workspace_sync_*.py", "cross_surface_session.py", "project_root.py"),
        ),
    ),  # fmt: skip
    Plugin(
        "work",
        "Work mode, missions and workflows.",
        (
            "thomas/work/**",
            "thomas/workflows/**",
            "thomas/flows/**",
            "thomas/workflow_v2/**",
            "thomas/server/work_*.py",
            *_routes("work*.py", "mission*.py", "goals.py", "schedule_routes.py"),
        ),
    ),  # fmt: skip
    Plugin(
        "extensions",
        "Installable extensions and the host that loads them.",
        (
            "extensions/**",
            "thomas/plugins/**",
            *_server(
                "plugin_*.py",
                "desktop_plugins*.py",
                "agent_plugins_*.py",
                "install_transaction.py",
                "marketplace_bundle_download.py",
                "tool_extensions.py",
            ),
            *_routes(
                "plugin_*.py",
                "marketplace_catalog_*.py",
                "standalone_app_aiohttp.py",
                "third_party_agent_access_aiohttp.py",
            ),
        ),
    ),  # fmt: skip
    Plugin("overlay", "Changing Thomas's own UI while it runs.", ("thomas/server/overlay/**", *_routes("ui_*.py"))),
    Plugin(
        "gateway", "Webhooks and the gateway surface.", ("thomas/server/routes/gateway/**", *_routes("webhooks*.py"))
    ),
    Plugin(
        "companion",
        "The companion surface.",
        (
            "thomas/companion/**",
            *_routes("companion*.py", "life_manager_aiohttp.py", "inkwell*.py", "paper_trading_aiohttp.py"),
        ),
    ),  # fmt: skip
    Plugin(
        "attention",
        "Cards Thomas puts beside the conversation: the store, its routes and its tools. Its row is with the other rows "
        "and its page files are with the web app's.",
        (
            *_core("attention_blocks.py", "attention_cards.py"),
            *_server("attention_tools.py", "attention_widget_templates.py", "attention_widgets.py"),
            *_routes("attention_routes.py"),
        ),
    ),
    Plugin("webui", "The pages, styles and scripts of the web app.", ("thomas/server/web/**", "web/**")),
    Plugin(
        "server",
        "The server shell: the app, its routes and its startup. It loads every other plugin, and so does the audit of it.",
        (
            "thomas/server/**",
            "thomas/marketplace/security/mutating_route_policy.py",
            "thomas/marketplace/security/security_audit.py",
            "thomas/marketplace/security/tools.py",
            "scripts/security_audit.py",
            "scripts/forge/gates/mutating_route_policy_exceptions.py",
            "scripts/forge/gates/release_hygiene.py",
        ),
    ),  # fmt: skip
    Plugin(
        "llm",
        "Talking to models: clients, providers, limits and cost.",
        (
            "thomas/models/**",
            *_core(
                "llm*.py",
                "provider_*.py",
                "claude_*.py",
                "codex_*.py",
                "model_*.py",
                "ollama_autostart.py",
                "listed_models.py",
                "chatgpt_review.py",
                "token*.py",
                "metering.py",
                "cost_tracker.py",
                "usage_telemetry.py",
                "retry.py",
                "cross_process_pacing.py",
            ),
        ),
    ),  # fmt: skip
    Plugin(
        "memory",
        "Memory, retrieval and the library.",
        (
            "thomas/memory/**",
            "thomas/library/**",
            "thomas/loaders/**",
            *_core(
                "rag_*.py",
                "search_history*.py",
                "incremental_index.py",
                "needle_context.py",
                "scale_index.py",
                "unindexed.py",
            ),
        ),
    ),  # fmt: skip
    Plugin(
        "tasks",
        "Tasks, goals and the schedule.",
        _core(
            "task_*.py",
            "todo_book.py",
            "goal_book.py",
            "scheduler.py",
            "initiative.py",
            "autonomy.py",
            "user_questions.py",
        ),
    ),  # fmt: skip
    Plugin("aliveness", "Thomas acting on its own while idle.", _core("aliveness*.py")),
    Plugin("acceptance", "Whether a finished job does what was asked.", _core("acceptance*.py")),
    Plugin("agent", "The agent loop.", ("thomas/agent/**",)),
    Plugin("tools", "What an agent can do: the tool definitions and registry.", ("thomas/tools/**",)),
    Plugin(
        "cli",
        "The command line, and what starts it: a shell that loads every other plugin.",
        ("thomas/cli/**", "thomas/__main__.py", "thomas/core/schedule_executor.py", "scripts/cage/caged_server.py"),
    ),  # fmt: skip
    Plugin("marketplace", "The domain modules.", ("thomas/marketplace/**",)),
    Plugin("browser", "Driving a browser.", ("thomas/browser/**",)),
    Plugin("integrations", "Connections to other services.", ("thomas/integrations/**",)),
    Plugin(
        "messaging",
        "Messages, channels and notifications.",
        ("thomas/messages/**", "thomas/channels/**", "thomas/notify/**", "thomas/notifications/**"),
    ),
    Plugin(
        "desktop",
        "The desktop operator and tray.",
        ("thomas/desktop_operator/**", "thomas/tray_agent/**", "desktop/**"),
    ),
    Plugin(
        "security", "Security, policy and the vault.", ("thomas/security/**", "thomas/policy/**", "thomas/vault/**")
    ),
    Plugin(
        "demo",
        "Demos and benchmarks.",
        ("thomas/demo/**", "thomas/benchmarks/**", "benchmarks/**", "scripts/run_agentic_benchmark.py"),
    ),  # fmt: skip
    Plugin("cage", "Running Thomas under its own account, and the checker.", ("scripts/cage/**",)),
    Plugin("crew", "The agents' workboard, briefing and commit lane.", ("scripts/crew/**",)),
    Plugin("gates", "The gates every commit passes.", ("scripts/forge/**",)),
    Plugin("tooling", "Scripts for running and measuring Thomas.", ("scripts/**", "tools/**")),
    Plugin(
        "core",
        "What everything else stands on: config, persistence, events and the rest.",
        ("thomas/core/**", "thomas/*"),
    ),
    Plugin("services", "The smaller packages.", ("thomas/**",)),
)
