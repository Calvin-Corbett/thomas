from pathlib import Path

import pytest

from thomas.cli import virtual_office_roster as roster

CANONICAL_NAMES = (
    "Brandon",
    "Trey",
    "Zach",
    "Matt",
    "Taylor",
    "John",
    "Nova",
    "Pixel",
    "Byte",
    "Orbit",
    "Echo",
    "Glitch",
)


@pytest.fixture(autouse=True)
def reset_roster_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roster, "_cached_roster", None)
    monkeypatch.setattr(roster, "_cached_mtime_ns", None)
    monkeypatch.setattr(roster, "_cached_path", None)


def _write_seed_source(path: Path) -> None:
    path.write_text(
        """
const DECOY_AGENTS = [
    { name: 'Atlas', color: '#0000ff', specialty: 'Stale fallback' },
];
const OFFICE_AGENT_SEEDS = [
    { name: 'Alpha', color: '#9ad8ff', specialty: 'Software builds', personality: 'One' },
    { specialty: "Research", name: "Beta", color: "#9becc9", personality: "Two" },
];
""",
        encoding="utf-8",
    )


def test_get_roster_reads_all_canonical_browser_seeds() -> None:
    source_path = roster._canonical_agent_seed_path()

    agents = roster.get_roster()

    assert source_path.name == "office_static_config.js"
    assert tuple(agent.name for agent in agents) == CANONICAL_NAMES
    assert len(agents) == 12
    assert agents[0].agent_id == "brandon"
    assert agents[0].role == agents[0].specialty == "Software builds"
    assert agents[0].accent == "#9ad8ff"


def test_parser_reads_only_office_agent_seed_block(tmp_path: Path) -> None:
    source_path = tmp_path / "office_static_config.js"
    _write_seed_source(source_path)

    agents = roster._parse_agents_from_seed_source(source_path)

    assert tuple(agent.name for agent in agents) == ("Alpha", "Beta")
    assert tuple(agent.specialty for agent in agents) == ("Software builds", "Research")
    assert "Atlas" not in {agent.name for agent in agents}


def test_first_load_fails_loudly_when_canonical_source_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-office-static-config.js"
    monkeypatch.setattr(roster, "_canonical_agent_seed_path", lambda: missing)

    with pytest.raises(RuntimeError, match="Canonical Virtual Office agent seed source is unavailable"):
        roster.get_roster()


def test_cached_canonical_roster_survives_transient_source_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "office_static_config.js"
    _write_seed_source(source_path)
    monkeypatch.setattr(roster, "_canonical_agent_seed_path", lambda: source_path)
    first = roster.get_roster()
    monkeypatch.setattr(roster, "_canonical_agent_seed_path", lambda: tmp_path / "temporarily-missing.js")

    assert roster.get_roster() is first


def test_specialist_map_resolves_to_current_office_agents() -> None:
    expected = {
        "engineering": "Brandon",
        "research": "Trey",
        "gaming": "Zach",
        "design": "Matt",
        "planning": "Taylor",
        "support": "John",
        "ops": "Nova",
        "creative": "Pixel",
        "data": "Byte",
        "integration": "Orbit",
        "documentation": "Echo",
        "debugging": "Glitch",
    }

    resolved = {specialty: roster.agent_for_specialist(specialty) for specialty in expected}

    assert {key: agent.name for key, agent in resolved.items() if agent} == expected
    assert all(agent is not None for agent in resolved.values())
