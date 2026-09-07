"""The Sign in with ChatGPT fallback says so instead of waiting.

Verified finding FOUR of the owner's 2026-09-01 directive: when no ChatGPT
(openai_codex) profile existed, the wizard's fallback called three addresses
that were registered nowhere (/api/codex/status, /api/codex/login with a
310-second timeout, /api/codex/models), then told you your sign-in had failed.
The real routes are /api/openai-codex/* and they need a profile, which is
exactly what the fallback lacks. Now the fallback says that immediately, and a
legacy profile whose provider is spelled codex takes the real route. Driven
through the real runtime module in a vm context by
``tests/web_node/easy_setup_connection_flow.mjs``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime"
FLOW_JS = RUNTIME / "easy_setup_connection_flow.js"
FINDER_JS = RUNTIME / "007_easy_setup_onboarding_05.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "easy_setup_connection_flow.mjs"


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    result = subprocess.run(
        ["node", str(HARNESS), str(FLOW_JS)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_no_profile_means_an_immediate_honest_message_not_three_missing_routes(report) -> None:
    assert report["fetched"] == [], report["fetched"]
    kind, text = report["statuses"][-1]
    assert kind == "error"
    assert "No ChatGPT profile is configured" in text
    assert "Remediation" in text
    assert report["verified"] is False


def test_the_fallback_settles_in_well_under_a_second_not_five_minutes(report) -> None:
    assert report["elapsed_ms"] < 1000, report["elapsed_ms"]


def test_the_dead_addresses_are_gone_from_the_wizard() -> None:
    # One more dead fallback to /api/codex/status lives in 040_model_setup_settings_01.js
    # (1794 lines, past the hard limit); it fails to null rather than to a claim, and is
    # reported on the board instead of touched here.
    for path in (FLOW_JS, FINDER_JS):
        assert "/api/codex/" not in path.read_text(encoding="utf-8"), path.name


def test_a_legacy_codex_profile_takes_the_real_route() -> None:
    finder = FINDER_JS.read_text(encoding="utf-8")
    assert "provider === 'codex'" in finder
    assert "provider === 'openai_codex'" in finder
