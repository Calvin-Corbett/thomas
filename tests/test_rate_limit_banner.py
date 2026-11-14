"""A resting model is announced with a countdown (frontier parity: Codex rate-limit banner, 2026-09-05).

The client parks a profile after a 429; the page saw a generic error and
nothing about when the model would be back. The banner folds the runtime
receipt (a skipped attempt with its cooldown), the error text, and the
cooldown route, and counts down.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "rate_limit_banner.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_banner_folds_receipt_error_and_route_and_counts_down() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "rate_limit_banner.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["text_ignored"] is None
    assert report["from_receipt"] == {
        "profile": "gpt-5.6-sol",
        "until": 1_200_000,
        "via": "claude-x",
        "kind": "rate_limit",
    }
    assert report["line_receipt"] == "gpt-5.6-sol is rate-limited · back in 3:15 · replies come from claude-x meanwhile"
    assert report["from_error"] == {"profile": "gpt-5.6-sol", "until": 1_045_000, "via": ""}
    assert report["line_error"] == "gpt-5.6-sol is rate-limited · back in 0:45 · Thomas will try again when it clears"
    # the route: the longest wait is the one that matters
    assert report["from_route"] == {"profile": "gpt-5.6-sol", "until": 1_090_000, "kind": "rate_limit"}
    assert report["line_route"] == "gpt-5.6-sol is rate-limited · back in 1:30 · Thomas will try again when it clears"
    assert report["line_expired"] == ""
    assert report["empty_route_clears"] is None
    assert report["format_null"] == ""
    assert report["clock"] == ["0:00", "0:59", "3:20", "1:02:05"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_spent_allowance_is_named_and_dated_not_counted_down() -> None:
    """A park is ten minutes; the allowance behind it can be out until Saturday.

    You were told "please wait a moment" and wrote back: "The limit lasts until
    Saturday morning, not a moment." A countdown under the composer says the same
    thing without words, so a row the cooldown route marks as a spent allowance
    (``thomas/core/provider_cooldowns.py``) is shown as the limit it is, with the
    reset worded once in Python, and stays up past the park that caused it.
    """
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "rate_limit_banner.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["spent_until_is_the_reset"] is True
    assert report["line_spent"] == (
        "ChatGPT Pro has reached its usage limit · resets Saturday 26 September at 08:02 "
        "· another model is needed until then"
    )
    # the park lifts after ten minutes; the limit does not, and neither does the line
    assert report["line_spent_after_the_park"] == report["line_spent"]
    assert report["line_spent_after_the_reset"] == ""
    assert report["line_spent_via"] == (
        "ChatGPT Pro has reached its usage limit · resets Saturday 26 September at 08:02 "
        "· replies come from claude-x meanwhile"
    )
    assert report["line_spent_no_reset"] == (
        "ChatGPT has reached its usage limit · the provider did not say when it resets "
        "· another model is needed until then"
    )
    assert report["spent_outranks_a_longer_park"] == "gpt-5.6-sol"
    # the route keeps sending the row after the park lifts (remaining_s 0), and the
    # page asks it on open, so a limit that started before this tab did is announced
    assert report["line_after_the_park_lifted"] == report["line_spent"]
    assert report["a_lifted_burst_shows_nothing"] is None
    for line in (report["line_spent"], report["line_spent_via"], report["line_spent_no_reset"]):
        assert "back in" not in line, "a countdown is the truth only for a short burst"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_plan_that_answers_again_takes_its_own_line_down() -> None:
    """The line outlasts the park on purpose; it must not outlast the limit.

    A spent-allowance line now ends at the reset the refusal named, which can be up
    to 41 hours off, and a plan can come back before then -- a reset read from the
    Claude CLI's printed words is put an hour late on purpose. The server stops
    claiming the limit the moment the plan answers (``llm_client._clear_cooldown``),
    but this page only asked the route after a failed turn, so the composer's line
    would have gone on reading "Claude has reached its usage limit · resets
    Saturday..." directly above the reply that plan had just written.
    """
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "rate_limit_banner.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["line_before_it_answered"].startswith("Claude has reached its usage limit · resets Saturday")
    assert report["answered_names_the_profile"] == "anthropic"
    assert report["answering_retires_its_own_line"] is None, "the line sat above the reply it had just given"
    assert report["someone_elses_turn_leaves_it_up"] == report["line_before_it_answered"]
    assert report["a_failover_still_parks"] == "gpt-5.6-sol", "one attempt answering does not free the parked one"
    assert report["answered_ignores_other_events"] == ["", ""]


def test_the_banner_is_injected_with_the_other_chat_modules() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    html = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert html.count("rate_limit_banner.js") == 1
    assert html.index("chat_session_id.js") < html.index("rate_limit_banner.js")
