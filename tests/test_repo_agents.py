"""Tests for repository-defined agent/role definitions (CAP-025).

Acceptance line: support repository-defined agents with explicit tools, model,
instructions, and validation.
"""

from __future__ import annotations

from pathlib import Path

from thomas.agent.repo_agents import (
    RepoAgent,
    ValidationResult,
    discover_repo_agents,
    discover_valid_repo_agents,
    find_repo_agent,
    known_tool_names,
    validate_agent_definition,
)

KNOWN_TOOLS = {"read_file", "write_file", "grep", "shell"}


def _write_agent(root: Path, source: str, name: str, body: str) -> Path:
    directory = root / source / "agents"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


_REVIEWER = (
    "---\n"
    "name: reviewer\n"
    "description: Careful code reviewer\n"
    "tools: read_file, grep\n"
    "model: reasoning\n"
    "---\n"
    "You are a meticulous code reviewer. Flag real defects only.\n"
)


# ---------------------------------------------------------------------------
# Discovery: a valid definition loads with explicit tools/model/instructions
# ---------------------------------------------------------------------------


def test_valid_agent_loads_with_tools_model_instructions(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "reviewer", _REVIEWER)
    scan = discover_repo_agents(tmp_path)
    assert scan.warnings == ()
    assert [a.name for a in scan.agents] == ["reviewer"]
    agent = scan.agents[0]
    assert agent.description == "Careful code reviewer"
    assert agent.tools == ("read_file", "grep")
    assert agent.model == "reasoning"
    assert agent.instructions == "You are a meticulous code reviewer. Flag real defects only."
    assert agent.origin == ".thomas"
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result == ValidationResult(ok=True, errors=())


def test_name_defaults_to_file_stem_when_not_declared(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "planner", "---\ntools: shell\nmodel: fast\n---\nPlan the work.\n")
    agent = find_repo_agent("planner", root=tmp_path)
    assert agent is not None
    assert agent.name == "planner"
    assert agent.model == "fast"


def test_claude_agents_are_a_fallback_source(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".claude", "helper", "---\ntools: read_file\nmodel: fast\n---\nHelp out.\n")
    scan = discover_repo_agents(tmp_path)
    assert scan.warnings == ()
    assert [a.name for a in scan.agents] == ["helper"]
    assert scan.agents[0].origin == ".claude"


def test_tools_accept_inline_list_syntax(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "multi", "---\ntools: [read_file, grep, shell]\nmodel: fast\n---\nDo work.\n")
    agent = find_repo_agent("multi", root=tmp_path)
    assert agent is not None
    assert agent.tools == ("read_file", "grep", "shell")


# ---------------------------------------------------------------------------
# Precedence: .thomas wins over .claude on a name collision
# ---------------------------------------------------------------------------


def test_thomas_wins_name_collision_with_claude(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "reviewer", "---\ntools: shell\nmodel: reasoning\n---\nThomas reviewer.\n")
    _write_agent(tmp_path, ".claude", "reviewer", "---\ntools: shell\nmodel: fast\n---\nClaude reviewer.\n")
    scan = discover_repo_agents(tmp_path)
    assert [a.name for a in scan.agents] == ["reviewer"]
    assert scan.agents[0].origin == ".thomas"
    assert scan.agents[0].instructions == "Thomas reviewer."
    assert scan.agents[0].model == "reasoning"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_tool_fails_validation_with_precise_error() -> None:
    agent = RepoAgent(name="rev", tools=("read_file", "does_not_exist"), model="fast", instructions="Review.")
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result.ok is False
    assert result.errors == ("unknown tool 'does_not_exist' (not a registered tool name)",)


def test_missing_model_fails_validation() -> None:
    agent = RepoAgent(name="rev", tools=("read_file",), model="", instructions="Review.")
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result.ok is False
    assert "model profile must be a non-empty string" in result.errors


def test_missing_tools_field_fails_validation() -> None:
    agent = RepoAgent(name="rev", tools=(), model="fast", instructions="Review.")
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result.ok is False
    assert any("missing required field 'tools'" in err for err in result.errors)


def test_missing_instructions_fails_validation() -> None:
    agent = RepoAgent(name="rev", tools=("read_file",), model="fast", instructions="   ")
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result.ok is False
    assert any("missing required field 'instructions'" in err for err in result.errors)


def test_validation_skips_tool_resolution_when_no_known_set() -> None:
    # Without an injected tool set, declared tools cannot be resolution-checked,
    # but structural required-field validation still applies.
    agent = RepoAgent(name="rev", tools=("anything",), model="fast", instructions="Review.")
    assert validate_agent_definition(agent, None).ok is True


def test_validation_reports_multiple_errors_at_once() -> None:
    agent = RepoAgent(name="rev", tools=("nope",), model="", instructions="")
    result = validate_agent_definition(agent, KNOWN_TOOLS)
    assert result.ok is False
    assert len(result.errors) == 3


# ---------------------------------------------------------------------------
# Malformed files degrade to warnings, never a crash
# ---------------------------------------------------------------------------


def test_missing_frontmatter_warns_and_skips(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "nofm", "Just a body with no frontmatter.\n")
    _write_agent(tmp_path, ".thomas", "good", _REVIEWER.replace("reviewer", "good"))
    scan = discover_repo_agents(tmp_path)
    assert [a.name for a in scan.agents] == ["good"]
    assert len(scan.warnings) == 1
    assert "nofm.md" in scan.warnings[0]
    assert "missing frontmatter" in scan.warnings[0]


def test_unterminated_frontmatter_warns_and_skips(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "broken", "---\ntools: shell\nmodel: fast\nBody with no closing fence\n")
    scan = discover_repo_agents(tmp_path)
    assert scan.agents == ()
    assert len(scan.warnings) == 1
    assert "unterminated frontmatter" in scan.warnings[0]


def test_empty_instructions_warns_and_skips(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "empty", "---\ntools: shell\nmodel: fast\n---\n\n")
    scan = discover_repo_agents(tmp_path)
    assert scan.agents == ()
    assert len(scan.warnings) == 1
    assert "empty agent instructions" in scan.warnings[0]


def test_invalid_frontmatter_line_warns_and_skips(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "oddmeta", "---\njust some words\n---\nBody\n")
    scan = discover_repo_agents(tmp_path)
    assert scan.agents == ()
    assert len(scan.warnings) == 1
    assert "invalid frontmatter line" in scan.warnings[0]


def test_scan_of_repo_without_agent_dirs_is_empty(tmp_path: Path) -> None:
    scan = discover_repo_agents(tmp_path)
    assert scan.agents == ()
    assert scan.warnings == ()


# ---------------------------------------------------------------------------
# Live re-scan picks up a new file without restart
# ---------------------------------------------------------------------------


def test_new_file_discoverable_without_restart(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "first", "---\ntools: shell\nmodel: fast\n---\nFirst.\n")
    assert [a.name for a in discover_repo_agents(tmp_path).agents] == ["first"]
    _write_agent(tmp_path, ".thomas", "second", "---\ntools: shell\nmodel: fast\n---\nSecond.\n")
    assert [a.name for a in discover_repo_agents(tmp_path).agents] == ["first", "second"]


# ---------------------------------------------------------------------------
# Integration seam: discover + validate against a known tool set
# ---------------------------------------------------------------------------


def test_discover_valid_partitions_agents_by_validation(tmp_path: Path) -> None:
    _write_agent(tmp_path, ".thomas", "reviewer", _REVIEWER)
    _write_agent(tmp_path, ".thomas", "bogus", "---\ntools: ghost_tool\nmodel: fast\n---\nBad agent.\n")
    scan = discover_valid_repo_agents(tmp_path, KNOWN_TOOLS)
    assert [a.name for a in scan.agents] == ["reviewer"]
    assert [name for name, _ in scan.invalid] == ["bogus"]
    invalid_result = scan.invalid[0][1]
    assert invalid_result.ok is False
    assert "unknown tool 'ghost_tool'" in invalid_result.errors[0]


def test_known_tool_names_extracts_from_registry_like_object() -> None:
    class _Tool:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Registry:
        def list_tools(self) -> list[_Tool]:
            return [_Tool("read_file"), _Tool("shell")]

    assert known_tool_names(_Registry()) == frozenset({"read_file", "shell"})
    assert known_tool_names(object()) == frozenset()
