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
    WEB_JS / "unified_code_results.js",
    WEB_JS / "unified_code_projects.js",
    WEB_JS / "unified_code_events.js",
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
        "the stop never re-read the changed files; CHANGED FILES stays absent "
        "until the user switches away and back"
    )
    assert seen["fetched"]["tree"] >= 1, (
        "the stop never re-read the file tree; FILES stays on 'Loading files…'"
    )
    assert seen["changes"] == ["app.js"], "the reloaded changes did not land in state"
    assert seen["treeLoaded"] is True and seen["tree"] == ["app.js"]
    assert seen["status"] == "stopped" and seen["running"] is False


def test_both_stop_entry_points_run_the_same_routine() -> None:
    report = _drive()
    drawer, adapter = report["drawerStop"], report["adapterStop"]
    assert HONEST_STOP_WORDING in drawer["wording"]
    assert adapter["wording"] == drawer["wording"], (
        "the two stop controls still speak differently: "
        f"drawer={drawer['wording']!r} adapter={adapter['wording']!r}"
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
        for line in CODE_JS.read_text(encoding="utf-8").splitlines()
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


def test_the_live_render_of_a_failed_run_keeps_its_produced_answer() -> None:
    html = _drive()["liveFailedWithAnswer"]
    assert "LIVE-PRODUCED-ANSWER" in html, "the live final answer was suppressed"
    assert re.search(r'tc-code-reply is-error', html), (
        "the failure note vanished from the live render once the answer showed"
    )
