"""A stop leaves the drawer telling the truth, and a finished run lands in view.

Three measured defects in ``unified_code_mode.js``:

1. The drawer Stop button path (``stopRun``) never refreshed changes or files
   after the stop. Measured live: FILES stuck on "Loading files…", CHANGED
   FILES absent, until the user switched away and back. The post-Keep/Revert
   path already reloads both; a confirmed stop now does the same.

2. Two stop controls with divergent behavior: the drawer's ``#tc-code-stop``
   called ``stopRun`` (honest wording, no refresh) while the mode adapter's
   ``stop()`` was a second function with different wording and different
   behavior. One routine now serves both entry points, keeping the honest
   wording and the refresh.

3. After a follow-up run completed in an open conversation, the viewport stayed
   at the previous turn -- the new answer below the fold.
   ``scrollTranscriptToNewest()`` existed but only ran on conversation OPEN;
   it now also runs when a run's durable result lands on screen.

Plus the live half of the never-suppress-an-answer rule: a failed run whose
live feed carries a final answer renders the answer AND the failure note.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
CODE_JS = WEB_JS / "unified_code_mode.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_stop_refresh_and_scroll.mjs"
# chat.html loads these ahead of the adapter; the harness has to as well,
# because the adapter configures them at load time.
SIBLINGS = (
    WEB_JS / "unified_code_lifecycle.js",
    WEB_JS / "self_edit_controls.js",
    WEB_JS / "unified_code_artifacts.js",
    WEB_JS / "unified_code_results.js",
    WEB_JS / "unified_code_projects.js",
    WEB_JS / "unified_code_roster.js",
    WEB_JS / "unified_code_drawer.js",
    WEB_JS / "unified_code_agent_chat.js",
    WEB_JS / "unified_code_cards.js",
    WEB_JS / "unified_code_live_diff.js",
    WEB_JS / "unified_code_composer.js",
    WEB_JS / "unified_code_events.js",
    WEB_JS / "unified_code_live_view.js",
    WEB_JS / "unified_code_surface.js",
    WEB_JS / "unified_code_run_stream.js",
    WEB_JS / "unified_code_questions.js",
    WEB_JS / "unified_code_controls.js",
    WEB_JS / "unified_code_view_state.js",
)

HONEST_STOP_WORDING = "Stopped — you interrupted this run"


def _drive() -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(CODE_JS), *[str(path) for path in SIBLINGS]],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and the em dash in the stop wording arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_confirmed_stop_reloads_the_changes_and_the_file_tree() -> None:
    seen = _drive()["drawerStop"]
    assert seen["fetched"]["stop"] == 1
    assert seen["fetched"]["changes"] >= 1, (
        "the stop never re-read the changed files; CHANGED FILES stays absent until the user switches away and back"
    )
    assert seen["fetched"]["tree"] >= 1, "the stop never re-read the file tree; FILES stays on 'Loading files…'"
    assert seen["changes"] == ["app.js"], "the reloaded changes did not land in state"
    assert seen["treeLoaded"] is True and seen["tree"] == ["app.js"]
    assert seen["status"] == "stopped" and seen["running"] is False


def test_native_stop_reloads_retained_candidate_and_truthful_wording() -> None:
    seen = _drive()["nativeStop"]
    assert seen["fetched"]["conversation"] == 1
    assert seen["selfEdit"] == {"status": "failed", "reason": "Stopped safely"}
    assert "private changes were retained" in seen["wording"]
    assert "Keep/Revert" not in seen["wording"]
    assert seen["running"] is False
    assert "Needs repair" in seen["cardHtml"]
    assert "Review changes" in seen["cardHtml"]


def test_both_stop_entry_points_run_the_same_routine() -> None:
    report = _drive()
    drawer, adapter = report["drawerStop"], report["adapterStop"]
    assert HONEST_STOP_WORDING in drawer["wording"]
    assert adapter["wording"] == drawer["wording"], (
        f"the two stop controls still speak differently: drawer={drawer['wording']!r} adapter={adapter['wording']!r}"
    )
    assert adapter["fetched"] == drawer["fetched"], (
        "the two stop controls still behave differently: "
        f"drawer fetched {drawer['fetched']} while adapter fetched {adapter['fetched']}"
    )
    assert adapter["status"] == "stopped" and adapter["running"] is False


def test_one_stop_request_site_exists_in_the_source() -> None:
    """The unification is structural, not two functions that happen to agree.

    Comment lines are stripped first: the change documents itself and quotes
    the old shape, so a scan reading its own comment would pass on prose.
    """

    code = "\n".join(
        line
        for line in "\n".join(
            path.read_text(encoding="utf-8")
            for path in (CODE_JS, WEB_JS / "unified_code_surface.js", WEB_JS / "unified_code_run_stream.js")
        ).splitlines()
        if not line.strip().startswith(("//", "*", "/*"))
    )
    stop_posts = code.count("'/api/evolve/agent/stop'")
    assert stop_posts == 1, (
        f"{stop_posts} sites POST to the stop endpoint; a second stop routine "
        "is free to drift in wording and behavior again"
    )


def test_a_durable_result_landing_on_screen_scrolls_to_the_newest_turn() -> None:
    seen = _drive()["durableScroll"]
    assert seen["scrollTop"] == seen["scrollHeight"], (
        f"after the durable result landed, the viewport sat at {seen['scrollTop']} "
        f"of {seen['scrollHeight']} -- the new answer is below the fold"
    )


def test_the_stop_and_continue_steer_continues_the_same_conversation() -> None:
    """The steer a lead that cannot take messages still gets (the queue's Steer
    falls back to it since the 2026-10 redesign, which removed the form that
    used to sit in the transcript)."""
    seen = _drive()["steer"]
    assert seen["requests"][0]["body"] == {"message": "Use a clear status", "run_id": "run-c1"}
    assert seen["requests"][1]["body"]["conversation_id"] == "c1"
    assert seen["requests"][1]["body"]["message"] == "Steering update: Use a clear status"
    assert seen["applied"] is True
    assert any("Update applied" in event for event in seen["events"])


def test_failed_continuation_does_not_claim_steering_was_applied() -> None:
    seen = _drive()["steerFailure"]
    assert seen["applied"] is False
    assert "not applied" in " ".join(seen["messages"])
    assert "Update applied" not in " ".join(seen["messages"])
    assert seen["status"] == "failed"


def test_the_live_render_of_a_failed_run_keeps_its_produced_answer() -> None:
    html = _drive()["liveFailedWithAnswer"]
    assert "LIVE-PRODUCED-ANSWER" in html, "the live final answer was suppressed"
    assert re.search(r"tc-code-reply is-error", html), (
        "the failure note vanished from the live render once the answer showed"
    )
