"""There is one "Improve Thomas", and it starts a Thomas project.

You asked whether the Build chooser's "Improve Thomas" section and the Thomas projects that land by your
sign-in card were "two separate ways of doing the same job". They were:

* the chooser's button opened a dialog that asked for a LIST OF FILES and created a ``self_edit`` Build
  conversation. One worker edited a snapshot inside that scope, and the result landed by writing those files
  over the running copy (Review -> Apply -> Restart). No commit, no team, no size check.
* ``POST /api/self/projects`` starts a Thomas project: a green git clone, Build's full team in it, the
  repo's size rule checked before hand-in, repair rounds on a refusal, and a submission on your Windows
  sign-in card that lands a real commit.

The button now starts the second. These tests hold that to one way: the entry posts to the project route,
and nothing left in the UI can create a ``self_edit`` conversation.

``ThomasSelfEdit.html``/``bind`` still render the old review card for conversations that already carry
``self_edit`` -- history, not a second way to start work. ``tests/web_node/self_edit_controls.mjs`` still
covers that half.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "thomas/server/web/js"
ENTRY = JS_DIR / "self_edit_controls.js"
CHOOSER = JS_DIR / "chat_composer_panels.js"
HARNESS = ROOT / "tests/web_node/improve_thomas_panel.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_improve_thomas_panel_matches_the_route_it_posts_to() -> None:
    """The harness runs the shipped panel. Only this test needs node; the rest below read the files.

    Skipped rather than failed where node is missing, as every other harness wrapper in this suite does --
    a machine without node would otherwise see ``FileNotFoundError: 'node'`` instead of a verdict about
    the panel.
    """
    result = subprocess.run(
        ["node", str(ROOT / "tests/web_node/improve_thomas_panel.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_dials_the_panel_sends_are_the_ones_the_route_takes() -> None:
    """The button's settings object is checked against the route's own key list, not against a copy of it.

    ``POST /api/self/projects`` refuses an unknown settings key BY NAME (``_checked``: "settings Build does
    not take here: ..."), so one renamed dial makes the button fail on its first use, with a 400 the person
    reads instead of a project. The Node harness holds the panel to a hand-written ``ACCEPTED`` set, which
    cannot notice that rename: it would keep agreeing with itself. This is the join -- the set in the
    harness is the route's ``SETTINGS_KEYS``, and every key the panel actually sends is one of them.
    """
    from thomas.server.routes.self_project_routes import SETTINGS_KEYS

    listed = re.search(r"const ACCEPTED = new Set\(\[(.*?)\]\)", HARNESS.read_text(encoding="utf-8"), re.S)
    assert listed, "the harness no longer names the keys it holds the panel to"
    accepted = {name.strip().strip("'\"") for name in listed.group(1).split(",") if name.strip()}
    assert accepted == set(SETTINGS_KEYS), "the harness's ACCEPTED set has drifted from self_project_routes"

    body = re.search(r"function settings\(\) \{(.*?)\n  \}", ENTRY.read_text(encoding="utf-8"), re.S)
    assert body, "self_edit_controls.settings() is what the panel POSTs; it is no longer a function here"
    sent = set(re.findall(r"^\s+(\w+):", body.group(1), re.M))
    assert sent, "settings() no longer returns an object literal of dials"
    assert sent <= set(SETTINGS_KEYS), f"the panel sends dials the route refuses: {sorted(sent - SETTINGS_KEYS)}"


def test_the_panel_shapes_build_roles_exactly_as_build_itself_does() -> None:
    """The one dial the route accepted and the panel never sent, held to Build's own composer. No node.

    The Node harness above checks the VALUE ``settings()`` builds for a given context; it is skipped where
    node is missing, and it was the only check of this dial. This one reads both files: the panel's
    ``build_roles`` expression must be ``unified_code_lifecycle.requestSettings``'s, character for
    character, so a change to how Build shapes its role picks cannot leave the panel behind again.

    Two identifiers are renamed and only those two: this file already has a ``context(state)`` for the
    legacy review card and a ``key(cid, rid)`` for its record map, so the copy reads ``ctx`` and ``saved``.
    """
    roles = re.compile(r"build_roles:(.*?)\n\s+reasoning_effort:", re.S)
    build = roles.search((JS_DIR / "unified_code_lifecycle.js").read_text(encoding="utf-8"))
    panel = roles.search(ENTRY.read_text(encoding="utf-8"))
    assert build and panel, "one of the two settings composers no longer has a build_roles entry"

    renamed = re.sub(r"\bkey\b", "saved", build.group(1).replace("context.", "ctx."))
    assert " ".join(renamed.split()) == " ".join(panel.group(1).split())


def test_the_chooser_button_still_reaches_the_one_entry() -> None:
    """The section you named is in the Build project chooser, and it selects Thomas as the project; a
    message sent there reaches the same project route (tests/test_improve_thomas_selects_thomas.py)."""
    chooser = CHOOSER.read_text(encoding="utf-8")
    assert "'Improve Thomas'" in chooser
    assert "data-lib-action" in chooser and "'self-edit'" in chooser
    assert "window.ThomasSelfEdit?.selectThomas(chooseLibraryProject)" in chooser


def test_the_entry_starts_a_thomas_project_and_asks_for_the_request_not_the_files() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    assert "'/api/self/projects'" in entry
    assert "What should Thomas change about himself?" in entry
    assert "Start a Thomas project" in entry
    # The old dialog's two defining pieces are gone from the entry.
    assert "selfEditScope" not in entry
    assert "One Thomas product file per line" not in entry


@pytest.mark.parametrize("marker", ["selfEdit: true", "self_edit: true", "selfEdit:true"])
def test_nothing_in_the_ui_can_create_a_self_edit_conversation_any_more(marker: str) -> None:
    """Delete-old-before-adding-new: the parallel way must not still be reachable from a page.

    ``unified_code_projects.newConversation`` still KNOWS how to make one -- it is what renders and resumes
    the ones that exist -- but no caller asks it to.
    """
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}"
        for path in sorted(JS_DIR.rglob("*.js"))
        if marker in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert offenders == [], f"a second way to start a self-change is still wired: {offenders}"
