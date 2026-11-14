"""The briefing tells agents to land through the queue, and the script it names exists."""

from __future__ import annotations

from pathlib import Path

from scripts.crew.brief.briefing import generate_briefing

ROOT = Path(__file__).resolve().parents[1]


def test_the_briefing_points_at_land_py_and_its_status_command():
    text = generate_briefing(modules=["general"])
    assert "scripts/crew/brief/land.py" in text and "land.py --status" in text
    assert "not blocked" in text and "slows everyone" in text and "advisory" in text
    for needed in (
        "--status",
        "--submit",
        "--wait N",
        "Waits take minutes",
        "--no-precheck",
        "5 still waiting",
        "3, 4 and 5 mean run it again",
        "at least every 8 minutes",
        "45 minutes",
        "--no-detach",
        "not-yours ticket",
        "tamper-evident, not tamper-proof",
        "real run still runs every gate",
        "do not bypass",
        "loses its ticket",
        "kills its whole job",
        "exit 0: read its status",
    ):
        assert needed in text, needed


def test_the_script_the_briefing_names_exists_next_to_the_commit_tool():
    assert (ROOT / "scripts" / "crew" / "brief" / "land.py").is_file()
    assert (ROOT / "scripts" / "crew" / "brief" / "commit.py").is_file()
