"""Redesign is "edit this thing however I say" (2026-09-06).

You said: "ITS NOT JUST RESIZING. ITS SENDING THOMAS A MESSAGE SAYING EDIT THIS
THING HOWEVER I SAY ... make thomas do everything ui wise through ui redesign.
this will prove he can edit himself." Pointing at the composer's "+" and asking
for a menu ended as "Nothing changed": the overlay has no channel for that, and
the client only opened a Code thread when the overlay had changed something,
with a brief that told Thomas the change was already done and the stock files
needed no edit.

Now the brief is a directive to change Thomas's own UI source, it names the
ask and everything the overlay could not do, and the client opens the thread
and leaves it in the composer, unsent, whenever the overlay could not carry the whole ask.
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.routes import ui_redesign_runtime as rt

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    {"uiId": "chat.composer", "label": "Add files button", "component": "button", "box": {"width": 28, "height": 28}}
]
UNSUPPORTED = [
    {
        "target_index": 0,
        "label": "Add files button",
        "reason": "a menu with new actions is not something a style or layout record can make",
    }
]


def test_the_brief_tells_thomas_to_change_his_own_source() -> None:
    brief = rt.code_thread_prompt(
        "turn this plus into a menu: create image, create video, create music, redesign with AI",
        TARGETS,
        "chat",
        unsupported=UNSUPPORTED,
        applied=[],
    )
    low = brief.lower()
    assert "turn this plus into a menu" in brief
    assert "a menu with new actions" in brief  # every reason the overlay gave
    assert "thomas/server/web" in low and "chat.html" in low  # where stock Thomas lives
    assert "web.playtest" in low or "verify" in low  # prove it in the browser
    assert "nothing in the stock ui files needs editing" not in low
    assert "only if" not in low  # no more "open this only if"


def test_the_brief_says_what_the_overlay_already_did() -> None:
    brief = rt.code_thread_prompt(
        "make it green and add a menu",
        TARGETS,
        "chat",
        unsupported=UNSUPPORTED,
        applied=["Add files button: style backgroundColor=#47d7ac"],
    )
    assert "already" in brief.lower() and "backgroundColor" in brief


def test_the_client_opens_the_thread_and_leaves_its_prompt_in_the_composer_unsent() -> None:
    """When the overlay could not carry the whole ask, the client opens the Code thread and puts the prompt in
    the composer. It never sends it: a redesign must not start a run that edits source unasked."""
    js = (ROOT / "thomas" / "server" / "web" / "js" / "ui_redesign_select.js").read_text(
        encoding="utf-8", errors="replace"
    )
    start = js.index("function openThread()")
    body = js[start : js.index("\n  }\n", start)]

    assert "openConversation(thread.id)" in body, "the thread is not opened"
    assert "document.getElementById('tc-input')" in body and "field.value = prompt" in body, (
        "the prompt is not put in the composer"
    )
    for sending in (".send(", "sendThread", ".click()", "requestSubmit", "submit("):
        assert sending not in body, f"openThread sends the prompt on its own ({sending})"
    assert "async function sendThread" not in js, "an automatic sender exists again"
    # What the result panel tells you, and the buttons it offers.
    assert "Code thread ready" in js
    assert "Open in Code" in js and "Change stock Thomas too" in js
