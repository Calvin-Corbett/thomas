"""Rendered replies retain safe markdown, provenance and durable completion."""

import subprocess
from pathlib import Path

from tests.web_fixtures.chat_sources import read_chat_sources

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas/server/web/chat.html"
CHAT_SHELL_CSS = REPO_ROOT / "thomas/server/web/css/chat_shell.css"

CHAT_MARKDOWN_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_markdown_renderer.mjs"

CHAT_ANNOUNCEMENT_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_completion_announcement_retry.mjs"

CHAT_MODEL_ATTRIBUTION_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_message_model_attribution.mjs"


def test_primary_chat_renders_safe_structured_markdown_for_assistant_only() -> None:
    text = read_chat_sources(CHAT_HTML)

    # The assistant branch still routes through mdToHtml; since 2026-08-05 it
    # first settles a completed delegation's stale "running now" promise
    # (_settledStatusText) before rendering, so the pin follows the line.
    assert (
        "let html = isUser ? deps.esc(m.text) : deps.mdToHtml(m.streaming ? m.text : (_settledStatusText(m) ?? m.text));"
        in text
    )
    assert "tc-bubble${isUser ? '' : ' tc-markdown'}" in text
    # The markdown rules moved with the rest of the shell's inline CSS into
    # chat_shell.css; the class the renderer emits still has to be styled.
    assert ".tc-markdown h1, .tc-markdown h2, .tc-markdown h3" in CHAT_SHELL_CSS.read_text(encoding="utf-8")
    assert "html += '<pre><code>' + deps.esc(code.join('\\n')) + '</code></pre>'" in text
    assert 'target="_blank" rel="noopener noreferrer"' in text

    completed = subprocess.run(
        ["node", str(CHAT_MARKDOWN_HARNESS), str(CHAT_HTML)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"userLiteral":true' in completed.stdout
    assert '"escapedHtml":true' in completed.stdout


def test_a_saved_reply_reports_the_model_that_wrote_it() -> None:
    """Which model answered is a fact about the past, not about the picker.

    ``mapRealMessages`` stamped ``state.modelLabel || 'GPT-5.6 Sol'`` onto every
    assistant message it restored, discarding the model the conversation row
    actually carries. Measured on a live store: 370 of 476 saved chats record a
    real model across EIGHT of them -- 185 gpt-5.6-sol, 136 codex, 37
    openai_codex, 5 local, 4 qwen2.5-coder:7b, plus gpt-5.5, terra and luna --
    and every one of them was displayed as whatever was selected right now.
    Opening a codex chat with Terra selected showed "GPT-5.6 Terra" on a reply
    codex wrote, on screen, under Thomas's name.

    The harness runs the real function with a ``state`` whose modelLabel is set,
    so a reintroduced fallback is caught rather than merely spelled around. The
    unknown case is the load-bearing one: a truthy row model hides the bug.
    """

    completed = subprocess.run(
        ["node", str(CHAT_MODEL_ATTRIBUTION_HARNESS), str(CHAT_HTML)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"codexKeepsItsOwnModel":true' in completed.stdout
    assert '"unknownIsNotInvented":true' in completed.stdout
    assert '"neverBorrowsThePicker":true' in completed.stdout

    # The renderer must not put the fallback back either: an unknown model shows
    # no chip at all rather than naming one.
    text = "\n".join(
        (CHAT_HTML.parent / "js" / name).read_text(encoding="utf-8")
        for name in ("chat_message_view.js", "chat_history_view.js")
    )
    assert "GPT-5.6 Sol" not in text, "a hardcoded model name is a claim about which model answered"


def test_chat_completion_announcement_retries_until_durably_reported() -> None:
    html = read_chat_sources(CHAT_HTML)

    assert "function queueCompletionAnnouncement(step, eid, attempt = 0)" in html
    assert "queueCompletionAnnouncement(s, rid)" in html
    assert "step._announced = true" in html
    assert "setTimeout(() =>" in html
    assert "queueCompletionAnnouncement(step, eid, attempt + 1)" in html
    assert "d.skipped === 'already_reported'" in html
    assert "Thomas completion announcement remains retryable" in html

    completed = subprocess.run(
        ["node", str(CHAT_ANNOUNCEMENT_HARNESS), str(CHAT_HTML)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
