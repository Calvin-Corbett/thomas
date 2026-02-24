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
    "core":        {"tier": "core", "depends_on": ["tools", "codex", "server"],
                    "health": "yellow",
                    "debt": "api_importer.py exceeds 1500 lines, llm.py exceeds 1000 lines, rag_index.py exceeds 1400 lines, scheduler.py exceeds 900 lines, search_history.py exceeds 900 lines; core imports tools/codex/server --should be inverted",
                    "description": "LLM client, persistence, config, events"},
    "agent":       {"tier": "core", "depends_on": ["core", "tools", "memory", "policy"],
                    "health": "yellow",
                    "debt": "loop.py exceeds 2500 lines, swarm.py exceeds 930 lines",
                    "description": "Agent loop, tool execution, streaming, guidance"},
    "server":      {"tier": "core",
                    "depends_on": ["core", "agent", "memory", "models", "preferences",
                                   "tools", "observability", "policy", "system",
                                   "autonomy", "realtime", "security", "plugins",
                                   "asset_studio", "codex", "channels", "companion"],
                    "health": "yellow",
                    "debt": "app.py exceeds 1500 lines (shrunk from 3957); routes/companion_aiohttp.py exceeds 1000 lines, routes/webhooks.py exceeds 1100 lines, routes/mission.py exceeds 2500 lines, routes/asset_studio_aiohttp.py exceeds 960 lines",
                    "description": "aiohttp web server, API routing, static serving"},
    "cli":         {"tier": "core",
                    "depends_on": ["core", "agent", "server", "tools", "memory",
                                   "models", "plugins", "browser", "companion",
                                   "integrations", "channels", "nodes",
                                   "messages", "gateway", "system",
                                   "investigation", "vision", "security"],
                    "health": "yellow",
                    "debt": "main.py exceeds 1600 lines, parity_compat.py exceeds 2100 lines, parity_commands.py exceeds 1000 lines; cli/commands/ has p### files importing many modules",
                    "description": "Click CLI commands and entry points"},
    "memory":      {"tier": "core", "depends_on": ["core", "library"],
                    "health": "yellow",
                    "debt": "autonomy.py exceeds 880 lines, curator.py exceeds 1130 lines, store.py exceeds 860 lines, v2/fabric.py exceeds 1170 lines",
                    "description": "Episodic and global memory storage"},
    "models":      {"tier": "core", "depends_on": ["core", "codex"],
                    "health": "green",
                    "description": "Model registry, provider routing, model metadata"},
    "preferences": {"tier": "core", "depends_on": ["core"],
                    "health": "yellow",
                    "debt": "store.py exceeds 920 lines",
                    "description": "User preferences persistence and API"},

    # -- EXTENSIONS --feature modules, isolated from each other ------------
    "browser":      {"tier": "ext", "depends_on": ["core", "tools", "cli"],
                     "health": "yellow",
                     "debt": "p015 imports cli --should be inverted; p001_browser_command_registry_scaffold.py exceeds 850 lines, p024_browser_error_normalization.py exceeds 845 lines",
                     "description": "Browser automation and page capture"},
    "asset_studio": {"tier": "ext", "depends_on": ["core", "server", "integrations"],
                     "health": "yellow",
                     "debt": "connector_shims imports integrations for github/notion/figma normalization --consider extracting shared adapters to core; contracts.py exceeds 870 lines",
                     "description": "Creative asset generation and management"},
    "companion":    {"tier": "ext", "depends_on": ["core", "server"],
                     "health": "green",
                     "description": "Companion app framework and store compliance"},
    "channels":     {"tier": "ext", "depends_on": ["core", "integrations"],
                     "health": "yellow",
                     "debt": "p096 imports integrations (ext->ext) --should extract shared code to core",
                     "description": "Multi-channel messaging (Telegram, Discord, Slack)"},
    "integrations": {"tier": "ext", "depends_on": ["core", "agent", "tools"],
                     "health": "green",
                     "description": "Third-party service connectors"},
    "realtime":     {"tier": "ext", "depends_on": ["core"],
                     "health": "green",
                     "description": "WebSocket and real-time communication"},
    "investigation": {"tier": "ext", "depends_on": ["core", "memory"],
                      "health": "green",
                      "description": "Background document analysis, evidence patterns, timeline building"},
    "vision":       {"tier": "ext", "depends_on": ["core"],
                     "health": "green",
                     "description": "Image and video analysis"},

    # -- INFRASTRUCTURE --cross-cutting support ----------------------------
    "observability": {"tier": "infra", "depends_on": ["core"],
                      "health": "green",
                      "description": "Logging, metrics, run store, tracing"},
    "security":      {"tier": "infra", "depends_on": ["core", "server", "plugins", "system"],
                      "health": "green",
                      "description": "Auth, policy enforcement, audit, threat model"},
    "system":        {"tier": "infra", "depends_on": ["core"],
                      "health": "yellow",
                      "debt": "heartbeat.py exceeds 970 lines",
                      "description": "Config validation, health probes, soak runner"},
    "plugins":       {"tier": "infra", "depends_on": ["core", "agent", "autonomy"],
                      "health": "yellow",
                      "debt": "test_suite_contract.py exceeds 835 lines",
                      "description": "Plugin loading, lifecycle, certification"},
    "policy":        {"tier": "infra", "depends_on": ["core"],
                      "health": "green",
                      "description": "Runtime guardrails and policy engine"},
    "tools":         {"tier": "infra", "depends_on": ["core", "investigation"],
                      "health": "yellow",
                      "debt": "browser.py exceeds 940 lines, database.py exceeds 1300 lines, dep_scanner.py exceeds 1290 lines, email_calendar.py exceeds 1540 lines, git_conflicts.py exceeds 1110 lines, sandbox.py exceeds 1100 lines, web_search.py exceeds 1470 lines",
                      "description": "Tool definitions, registry, sandbox"},

    # -- SUPPORT --smaller utility modules ---------------------------------
    "approvals":     {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Approval workflows for risky actions"},
    "autonomy":      {"tier": "support", "depends_on": ["core"],
                      "health": "yellow",
                      "debt": "workflows.py exceeds 860 lines",
                      "description": "Autonomy level management"},
    "codex":         {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Bridge to Codex/external providers"},
    "demo":          {"tier": "support", "depends_on": ["core", "agent", "cli", "tools", "plugins"],
                      "health": "yellow",
                      "debt": "agentic_benchmark.py exceeds 930 lines, agent_comparison_suite.py exceeds 3400 lines, harness.py exceeds 1150 lines",
                      "description": "Demo harnesses and comparison suites"},
    "gateway":       {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Gateway/proxy layer"},
    "intake":        {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Intake processing for external drops"},
    "library":       {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Research library and catalog"},
    "messages":      {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Message handling and formatting"},
    "nodes":         {"tier": "support", "depends_on": ["core", "cli"],
                      "health": "yellow",
                      "debt": "p049 imports cli --should be inverted",
                      "description": "Node/graph execution structures"},
    "notifications": {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Notification dispatch"},
    "tray_agent":    {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "System tray agent for background operation"},
    "upgrade":       {"tier": "support", "depends_on": ["core"],
                      "health": "green",
                      "description": "Self-upgrade and migration logic"},
    "watcher":       {"tier": "support", "depends_on": ["core", "library"],
                      "health": "green",
                      "description": "File and event watching"},
}

# ---------------------------------------------------------------------------
# Rules --enforced by tests/test_architecture.py and pre-commit hooks
# ---------------------------------------------------------------------------

RULES = {
    "max_new_file_lines": 500,      # soft limit for new files
    "max_file_lines_hard": 800,     # hard block for new files
    "forbidden_patterns": [
        "tmp_*", "probe_*", "*_probe.*",   # debug artifacts
    ],
    "legacy_patterns": [
        "p[0-9][0-9][0-9]_*",             # numbered stubs --existing are legacy, no new ones
    ],
    "test_required_dirs": [
        "thomas/server/routes/",
        "thomas/agent/",
        "thomas/core/",
    ],
    "extension_isolation": True,    # ext modules cannot import each other
    "ext_isolation_exceptions": [
        # Known ext->ext imports that exist as tech debt.
        ("channels", "integrations"),   # p096 uses telegram integration
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
        ("cli", "browser"),         # p015 browser imports cli, cli imports browser
        ("cli", "nodes"),           # p049 nodes imports cli, cli imports nodes
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
