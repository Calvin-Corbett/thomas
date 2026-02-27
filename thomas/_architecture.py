"""Thomas Executable Architecture -- v1

This file IS the architecture. Agents read it. Tests enforce it.
Thomas's own agent loop will consume it for autopoietic self-improvement.

Change the architecture by changing this file -- everything else follows.
"""

__architecture_version__ = 1

# ---------------------------------------------------------------------------
# Module registry --every thomas/ subdirectory, its tier, allowed deps,
# health status, known debt, and description.
# ---------------------------------------------------------------------------

MODULES = {
    # -- CORE --stable foundations ------------------------------------------
    "core": {
        "tier": "core",
        "depends_on": ["tools", "codex", "server"],
        "health": "yellow",
        "debt": "llm.py exceeds 1000 lines, rag_index.py exceeds 1400 lines, scheduler.py exceeds 900 lines, search_history.py exceeds 900 lines, local_agent_engine.py exceeds 800 lines; core imports tools/codex/server --should be inverted",
        "description": "LLM client, persistence, config, events",
    },
    "agent": {
        "tier": "core",
        "depends_on": ["core", "tools", "memory", "policy", "learning", "models", "observability", "library"],
        "health": "yellow",
        "debt": "loop.py exceeds 2500 lines, response_tone.py exceeds 827 lines, swarm.py exceeds 930 lines",
        "description": "Agent loop, tool execution, streaming, guidance",
    },
    "server": {
        "tier": "core",
        "depends_on": [
            "core",
            "agent",
            "memory",
            "models",
            "preferences",
            "tools",
            "observability",
            "policy",
            "system",
            "autonomy",
            "realtime",
            "security",
            "plugins",
            "asset_studio",
            "codex",
            "channels",
            "companion",
        ],
        "health": "yellow",
        "debt": "app.py exceeds 1500 lines (shrunk from 3957); routes/chat_aiohttp.py exceeds 800 lines, routes/companion_aiohttp.py exceeds 1000 lines, routes/webhooks.py exceeds 1100 lines, routes/mission.py exceeds 2500 lines, routes/asset_studio_aiohttp.py exceeds 960 lines, routes/setup_aiohttp.py exceeds 1000 lines",
        "description": "aiohttp web server, API routing, static serving",
    },
    "cli": {
        "tier": "core",
        "depends_on": [
            "core",
            "agent",
            "server",
            "tools",
            "memory",
            "models",
            "plugins",
            "browser",
            "companion",
            "integrations",
            "channels",
            "nodes",
            "messages",
            "gateway",
            "system",
            "investigation",
            "vision",
            "security",
            "codex",
            "upgrade",
        ],
        "health": "yellow",
        "debt": "main.py exceeds 1600 lines, parity_compat.py exceeds 2100 lines, parity_commands.py exceeds 1000 lines; cli/commands/ has p### files importing many modules",
        "description": "Click CLI commands and entry points",
    },
    "memory": {
        "tier": "core",
        "depends_on": ["core", "library"],
        "health": "yellow",
        "debt": "autonomy.py exceeds 880 lines, curator.py exceeds 1130 lines, store.py exceeds 860 lines, v2/fabric.py exceeds 1170 lines",
        "description": "Episodic and global memory storage",
    },
    "models": {
        "tier": "core",
        "depends_on": ["core", "codex"],
        "health": "green",
        "description": "Model registry, provider routing, model metadata",
    },
    "preferences": {
        "tier": "core",
        "depends_on": ["core"],
        "health": "yellow",
        "debt": "store.py exceeds 800 lines",
        "description": "User preferences persistence and API",
    },
    # -- EXTENSIONS --feature modules, isolated from each other ------------
    "browser": {
        "tier": "ext",
        "depends_on": ["core", "tools", "cli"],
        "health": "yellow",
        "debt": "p015 imports cli --should be inverted; p001_browser_command_registry_scaffold.py exceeds 850 lines, p024_browser_error_normalization.py exceeds 845 lines",
        "description": "Browser automation and page capture",
    },
    "asset_studio": {
        "tier": "ext",
        "depends_on": ["core", "server", "integrations"],
        "health": "yellow",
        "debt": "connector_shims imports integrations for github/notion/figma normalization --consider extracting shared adapters to core; contracts.py exceeds 870 lines",
        "description": "Creative asset generation and management",
    },
    "companion": {
        "tier": "ext",
        "depends_on": ["core", "server"],
        "health": "green",
        "description": "Companion app framework and store compliance",
    },
    "channels": {
        "tier": "ext",
        "depends_on": ["core", "integrations"],
        "health": "yellow",
        "debt": "p096 imports integrations (ext->ext) --should extract shared code to core",
        "description": "Multi-channel messaging (Telegram, Discord, Slack)",
    },
    "integrations": {
        "tier": "ext",
        "depends_on": ["core", "agent", "tools"],
        "health": "green",
        "description": "Third-party service connectors",
    },
    "realtime": {
        "tier": "ext",
        "depends_on": ["core"],
        "health": "green",
        "description": "WebSocket and real-time communication",
    },
    "investigation": {
        "tier": "ext",
        "depends_on": ["core", "memory"],
        "health": "green",
        "description": "Background document analysis, evidence patterns, timeline building",
    },
    "vision": {"tier": "ext", "depends_on": ["core"], "health": "green", "description": "Image and video analysis"},
    # -- INFRASTRUCTURE --cross-cutting support ----------------------------
    "observability": {
        "tier": "infra",
        "depends_on": ["core"],
        "health": "green",
        "description": "Logging, metrics, run store, tracing",
    },
    "security": {
        "tier": "infra",
        "depends_on": ["core", "server", "plugins", "system"],
        "health": "green",
        "description": "Auth, policy enforcement, audit, threat model",
    },
    "system": {
        "tier": "infra",
        "depends_on": ["core"],
        "health": "yellow",
        "debt": "heartbeat.py exceeds 970 lines",
        "description": "Config validation, health probes, soak runner",
    },
    "plugins": {
        "tier": "infra",
        "depends_on": ["core", "agent", "autonomy"],
        "health": "yellow",
        "debt": "test_suite_contract.py exceeds 835 lines",
        "description": "Plugin loading, lifecycle, certification",
    },
    "policy": {
        "tier": "infra",
        "depends_on": ["core"],
        "health": "green",
        "description": "Runtime guardrails and policy engine",
    },
    "tools": {
        "tier": "infra",
        "depends_on": ["core", "investigation"],
        "health": "yellow",
        "debt": "browser.py exceeds 940 lines, database.py exceeds 1300 lines, dep_scanner.py exceeds 1290 lines, email_calendar.py exceeds 1540 lines, git_conflicts.py exceeds 1110 lines, sandbox.py exceeds 1100 lines, web_search.py exceeds 1470 lines",
        "description": "Tool definitions, registry, sandbox",
    },
    # -- SUPPORT --smaller utility modules ---------------------------------
    "agriculture": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Agriculture domain algorithms and utilities (archived)",
    },
    "approvals": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Approval workflows for risky actions",
    },
    "audio_engine": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Audio engine domain algorithms and utilities",
    },
    "autonomy": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "debt": "workflows.py exceeds 860 lines",
        "description": "Autonomy level management",
    },
    "climate": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Climate domain algorithms and utilities",
    },
    "conversations": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Conversation orchestration primitives",
    },
    "codex": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Bridge to Codex/external providers",
    },
    "benchmarks": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Benchmark suites, scoring, and reporting runtime",
    },
    "demo": {
        "tier": "support",
        "depends_on": ["core", "agent", "cli", "tools", "plugins"],
        "health": "yellow",
        "debt": "agentic_benchmark.py exceeds 930 lines, agent_comparison_suite.py exceeds 3400 lines, harness.py exceeds 1150 lines",
        "description": "Demo harnesses and comparison suites",
    },
    "gateway": {"tier": "support", "depends_on": ["core"], "health": "green", "description": "Gateway/proxy layer"},
    "groupchat": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Multi-participant chat coordination",
    },
    "human_loop": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Human approvals and escalation flow",
    },
    "intake": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Intake processing for external drops",
    },
    "learning": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Lesson capture and teachability utilities",
    },
    "library": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Research library and catalog",
    },
    "marketplace": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Marketplace domain algorithms and utilities",
    },
    "markdown": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Markdown processing domain algorithms and utilities",
    },
    "messages": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Message handling and formatting",
    },
    "nodes": {
        "tier": "support",
        "depends_on": ["core", "cli"],
        "health": "yellow",
        "debt": "p049 imports cli --should be inverted",
        "description": "Node/graph execution structures",
    },
    "notify": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Notification campaign and delivery domain algorithms and utilities",
    },
    "notifications": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Notification dispatch",
    },
    "prompts": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Prompt templates, message types, and token helpers",
    },
    "sandbox": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Code execution sandbox abstractions",
    },
    "tests": {
        "tier": "support",
        "depends_on": ["core", "models", "preferences"],
        "health": "green",
        "description": "Internal package-scoped tests for local runtime modules",
    },
    "tray_agent": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "System tray agent for background operation",
    },
    "upgrade": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "green",
        "description": "Self-upgrade and migration logic",
    },
    "watcher": {
        "tier": "support",
        "depends_on": ["core", "library"],
        "health": "green",
        "description": "File and event watching",
    },
    "autonomous_vehicles": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Autonomous vehicle domain algorithms and utilities (archived)",
    },
    "bioinformatics": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Bioinformatics domain algorithms and utilities",
    },
    "blockchain": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Blockchain domain algorithms and utilities",
    },
    "cad": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "CAD domain algorithms and utilities",
    },
    "caching": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Caching domain algorithms and utilities",
    },
    "columnar": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Columnar storage domain algorithms and utilities",
    },
    "compiler_infra": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Compiler infrastructure domain algorithms and utilities",
    },
    "config_mgmt": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Configuration management orchestration and policy utilities",
    },
    "containers": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Container orchestration domain algorithms and utilities",
    },
    "cqrs": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "CQRS domain algorithms and utilities",
    },
    "crm": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "CRM domain algorithms and utilities",
    },
    "cv": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Computer vision domain algorithms and utilities",
    },
    "dataframe": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Dataframe domain algorithms and utilities",
    },
    "data_pipeline": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Data pipeline domain algorithms and utilities",
    },
    "db_internals": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "debt": "query_parser.py exceeds 800 lines",
        "description": "Database internals domain algorithms and utilities",
    },
    "doc_processing": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Document processing domain algorithms and utilities",
    },
    "dns": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "DNS domain algorithms and utilities",
    },
    "dsl": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "DSL domain algorithms and utilities",
    },
    "ecommerce": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "E-commerce domain algorithms and utilities (archived)",
    },
    "email_protocol": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Email protocol domain algorithms and utilities",
    },
    "energy": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Energy domain algorithms and utilities",
    },
    "erp": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "ERP domain algorithms and utilities",
    },
    "event_bus": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Event bus domain algorithms and utilities",
    },
    "fintech": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "FinTech domain algorithms and utilities (archived)",
    },
    "food_tech": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Food technology domain algorithms and utilities (archived)",
    },
    "game_ai": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Game AI domain algorithms and utilities",
    },
    "gaming_platform": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Gaming platform domain algorithms and utilities",
    },
    "graph_analytics": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Graph analytics domain algorithms and utilities",
    },
    "graphdb": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Graph database domain algorithms and utilities",
    },
    "graphics3d": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "debt": "_types.py exceeds 800 lines",
        "description": "3D graphics domain algorithms and utilities",
    },
    "healthcare": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Healthcare domain algorithms and utilities (archived)",
    },
    "hr_platform": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "HR platform domain algorithms and utilities (archived)",
    },
    "hrm": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Human resource management domain algorithms and utilities (archived)",
    },
    "http2": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "HTTP/2 domain algorithms and utilities",
    },
    "iot_platform": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "IoT platform domain algorithms and utilities",
    },
    "image_proc": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Image processing domain algorithms and utilities",
    },
    "kvstore": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "KV store domain algorithms and utilities",
    },
    "legal": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Legal domain algorithms and utilities (archived)",
    },
    "load_balancer": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Load balancing domain algorithms and utilities",
    },
    "logging_framework": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Logging framework domain algorithms and utilities",
    },
    "message_queue": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Message queue domain algorithms and utilities",
    },
    "monitoring": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Monitoring domain algorithms and utilities",
    },
    "music": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Music domain algorithms and utilities",
    },
    "nlg": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Natural language generation domain algorithms and utilities",
    },
    "nlu": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Natural language understanding domain algorithms and utilities",
    },
    "pathfinding": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Pathfinding domain algorithms and utilities",
    },
    "pentest": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Penetration testing domain algorithms and utilities",
    },
    "physics": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Physics simulation domain algorithms and utilities",
    },
    "procgen": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Procedural generation domain algorithms and utilities",
    },
    "project_mgmt": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Project management domain algorithms and utilities",
    },
    "quantfin": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Quantitative finance domain algorithms and utilities (archived)",
    },
    "real_estate": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Real estate domain algorithms and utilities (archived)",
    },
    "recommender": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Recommender-system domain algorithms and utilities",
    },
    "regex_engine": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Regex engine domain algorithms and utilities",
    },
    "robotics_deep": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Robotics domain algorithms and utilities",
    },
    "scheduler_deep": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Scheduling domain algorithms and utilities",
    },
    "search_engine": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Search engine domain algorithms and utilities",
    },
    "serialization": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Serialization domain algorithms and utilities",
    },
    "signal_proc": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Signal processing domain algorithms and utilities",
    },
    "siem": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "SIEM domain algorithms and utilities",
    },
    "simulation": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Simulation domain algorithms and utilities",
    },
    "smart_home": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Smart home domain algorithms and utilities",
    },
    "social_platform": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Social platform domain algorithms and utilities",
    },
    "stats": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Statistics domain algorithms and utilities",
    },
    "supply_chain": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Supply-chain domain algorithms and utilities (archived)",
    },
    "task_queue": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Task queue domain algorithms and utilities",
    },
    "telecom": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Telecom domain algorithms and utilities",
    },
    "template_engine": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Template engine domain algorithms and utilities",
    },
    "travel": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "archived": True,
        "description": "Travel domain algorithms and utilities (archived)",
    },
    "tsdb": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Time-series database domain algorithms and utilities",
    },
    "validation": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Validation domain algorithms and utilities",
    },
    "visualization": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Visualization domain algorithms and utilities",
    },
    "voice": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Voice domain algorithms and utilities",
    },
    "waf": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Web application firewall domain algorithms and utilities",
    },
    "webhooks": {
        "tier": "support",
        "depends_on": ["core"],
        "health": "yellow",
        "description": "Webhook delivery, retry, signing, and filtering utilities",
    },
}

# ---------------------------------------------------------------------------
# Monolith ceiling --absolute hard limit for any file, no exceptions
# ---------------------------------------------------------------------------

MONOLITH_CEILING = 1200  # Absolute max. No exemptions. Split or fail.

# ---------------------------------------------------------------------------
# Rules --enforced by tests/test_architecture.py and pre-commit hooks
# ---------------------------------------------------------------------------

RULES = {
    "max_new_file_lines": 500,  # soft limit for new files
    "max_file_lines_hard": 800,  # hard block for new files
    "forbidden_patterns": [
        "tmp_*",
        "probe_*",
        "*_probe.*",  # debug artifacts
    ],
    "legacy_patterns": [
        "p[0-9][0-9][0-9]_*",  # numbered stubs --existing are legacy, no new ones
    ],
    "test_required_dirs": [
        "thomas/server/routes/",
        "thomas/agent/",
        "thomas/core/",
    ],
    "extension_isolation": True,  # ext modules cannot import each other
    "ext_isolation_exceptions": [
        # Known ext->ext imports that exist as tech debt.
        ("channels", "integrations"),  # p096 uses telegram integration
        ("asset_studio", "integrations"),  # connector shims reuse github automation helpers
    ],
    "known_cycles": [
        # These circular deps exist in the current codebase and are tech debt.
        # The test will only fail on NEW cycles not listed here.
        ("core", "tools"),
        ("core", "codex"),
        ("core", "server"),
        ("server", "security"),
        ("server", "asset_studio"),
        ("server", "companion"),
        ("cli", "browser"),  # p015 browser imports cli, cli imports browser
        ("cli", "nodes"),  # p049 nodes imports cli, cli imports nodes
    ],
    "frontend_limits": {
        "js": {"soft": 800, "hard": 2000},  # JavaScript files
        "css": {"soft": 600, "hard": 1200},  # CSS files
        "html": {"soft": 2000, "hard": 3000},  # HTML standalone apps
    },
    "frontend_legacy_exempt": [
        "**/app_parts/part-*.js",  # Legacy JS parts being migrated to modules --documented debt
    ],
}

# ---------------------------------------------------------------------------
# Anti-patterns --agents should never do these
# ---------------------------------------------------------------------------

ANTI_PATTERNS = [
    "No placeholder/stub files --only real implementations",
    "No governance scripts without explicit user request",
    "No docs for features that don't exist yet",
    "No mocking internal modules in tests --mock external services only",
    "No abstractions for things used only once",
    "No version bumps for non-behavioral changes",
    "No numbered command stubs (p001, p002...)",
    "No bulk deletion --before removing ANY file, grep for all imports/references, verify nothing depends on it, and confirm the server still boots",
    "No file may exceed MONOLITH_CEILING lines regardless of debt annotation",
]

# ---------------------------------------------------------------------------
# Code deletion protocol --every agent must follow this before removing code
# ---------------------------------------------------------------------------

DELETION_PROTOCOL = [
    "1. grep -r '<module_or_function>' thomas/ tests/ scripts/ --include='*.py' to find ALL references",
    "2. For each reference: is it a live import, lazy import, or dead reference?",
    "3. If ANY live import exists: do NOT delete. Refactor or replace the code instead.",
    "4. If only lazy/conditional imports exist: stub them with safe fallbacks before deleting.",
    "5. After deletion: run 'python -m thomas serve --port 0' to verify boot. Run 'python -m pytest tests/test_architecture.py -x'.",
    "6. If boot fails or tests fail: revert and try a different approach.",
]

# ---------------------------------------------------------------------------
# Prompt templates --guide agents toward correct patterns
# ---------------------------------------------------------------------------

PROMPTS = {
    "add_route": "Use 'thomas scaffold route <name>'. Adds handler + test.",
    "add_module": "Use 'thomas scaffold module <name>'. Sets up dir + init + test.",
    "fix_bug": "Read the module. Check _architecture.py debt notes. Minimal fix, add test.",
    "add_test": "Mirror source path in tests/. Mock external services only. Test real logic.",
    "refactor": "Run 'thomas doctor' first. Address debt items in _architecture.py.",
}

# ---------------------------------------------------------------------------
# Programmatic helpers --used by CLI tools and fitness tests
# ---------------------------------------------------------------------------


def get_module(name: str) -> dict | None:
    """Get module definition by name."""
    return MODULES.get(name)


def get_allowed_deps(name: str) -> list[str]:
    """Get the list of modules this module is allowed to import from."""
    mod = MODULES.get(name)
    return list(mod["depends_on"]) if mod else []


def get_all_by_tier(tier: str) -> dict[str, dict]:
    """Get all modules in a given tier (core/ext/infra/support)."""
    return {k: v for k, v in MODULES.items() if v.get("tier") == tier}


def resolve_module(path: str) -> str | None:
    """Given a file path, resolve which module it belongs to.

    Accepts paths like 'thomas/server/routes/foo.py' or absolute paths.
    Returns the module name (e.g. 'server') or None.
    """
    import pathlib

    p = pathlib.PurePosixPath(path.replace("\\", "/"))
    parts = p.parts
    # Find 'thomas' in the path and take the next part
    for i, part in enumerate(parts):
        if part == "thomas" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate in MODULES:
                return candidate
    return None
