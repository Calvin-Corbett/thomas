"""One composer, and it behaves the same in Chat, Build and Work (2026-11-09).

You said: "I'm pretty sure we kind of standardized the composer. We should just use the same one." The box was already
one element. What happened after Enter was not the same. Work answered a message sent while it was still replying with
a bare ``return``, the shell reported success whatever the mode did, and the box cleared: the words were gone with no
sign. Work also ignored what you attached, and the chips were cleared anyway. Escape stopped a run only in Build, the
"/" palette found its box by its placeholder (so it missed Work, and in Build could find the side drawer's box first),
and the "+" menu offered image, music and video in modes where they did nothing.

The behaviour is driven in node (``tests/web_node/composer_keeps_what_you_send.mjs``); the wiring is read from the
files that hold it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JS = REPO_ROOT / "thomas" / "server" / "web" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text("utf-8")


def test_the_shell_reports_what_the_mode_did_and_work_shows_its_queue() -> None:
    out = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "web_node" / "composer_keeps_what_you_send.mjs"),
         str(JS / "unified_mode_shell.js"), str(JS / "unified_work_support.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "shellReportsWhatTheModeDid": True,
        "workShowsItsQueue": True,
    }


def test_work_queues_a_message_sent_mid_reply_and_sends_it_when_the_reply_ends() -> None:
    work = _read("unified_work_mode.js")
    assert "if (!text || state.running) return;" not in work, "the silent drop is gone"
    send = work.split("async function send(message, context) {", 1)[1].split("async function finishOnboarding", 1)[0]
    assert "state.queuedSends = (state.queuedSends || []).concat(" in send
    assert "(state.queuedSends || []).shift()" in send, "the reply's end takes the next one off the queue"
    assert "void send(next.text, { files: next.files })" in send
    assert "Not sent, because you opened something else first" in send, (
        "a message for a job you left is named, not sent to another"
    )


def test_work_sends_what_you_attached() -> None:
    work = _read("unified_work_mode.js")
    post = next(line for line in work.splitlines() if "fetch('/api/v2/chat'" in line)
    assert "docs: options.files ? options.files.docs : undefined" in post
    assert "images: options.files ? options.files.images : undefined" in post
    assert work.count("files, ") >= 2, "both the wizard's turn and a job's turn pass them on"


def test_the_box_clears_only_when_the_mode_took_the_message() -> None:
    actions = _read("chat_stream_actions.js")
    send = actions.split("function send() {", 1)[1].split("function chunkText", 1)[0]
    assert "if (routed === 'refused') return;" in send
    assert send.index("if (routed === 'refused') return;") < send.index("deps.state.input = ''")
    assert "if (inChat && deps.state.streaming) { deps.turnFlow.enqueue(); return; }" in send, (
        "Chat's queue takes a message only when Chat is the mode on screen"
    )


def test_escape_and_enter_mean_the_same_in_every_mode() -> None:
    bindings = _read("chat_shell_bindings.js")
    assert "e.key === 'Enter' && !e.shiftKey && !e.isComposing" in bindings, (
        "Enter that picks an IME word is not a send"
    )
    assert "unified.mode() === 'work' && unified.stop()" in bindings, (
        "Escape on an empty box stops Work's reply, as in Build"
    )


def test_the_helpers_around_the_composer_find_it_by_its_id() -> None:
    for name in ("slash_palette.js", "todo_panel.js"):
        assert "document.getElementById('tc-input') ||" in _read(name), name
    assert "#tc-agent-chat-input, #tc-input," in _read("ask_user_panel.js")


def test_the_plus_menu_offers_media_only_where_it_is_made() -> None:
    menu = _read("chat_create_menu.js")
    assert "window.ThomasUnifiedModes.mode() === 'chat'" in menu
    assert "item.style.display = inChat ? '' : 'none'" in menu


def test_builds_own_button_name_is_not_overwritten_with_send() -> None:
    panels = _read("chat_composer_panels.js")
    assert "else if (!button.getAttribute('data-primary')) button.title = 'Send';" in panels
