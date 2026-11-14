"""A screenshot or PDF can be pasted or dropped on the composer, and it shows on the message in Chat and Build."""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"


def _read(relative: str) -> str:
    return (WEB / relative).read_text(encoding="utf-8")


def test_paste_and_drop_feed_the_same_path_as_the_file_picker():
    source = _read("js/chat_shell_bindings.js")
    assert "composerInput.addEventListener('paste'" in source
    assert "composerBox.addEventListener('drop'" in source and "composerBox.classList.add('is-dropping')" in source
    assert source.count("deps.onFiles(") >= 3  # the picker, paste and drop all use onFiles
    # A pasted screenshot is always "image.png": each needs its own name or two would overwrite each other.
    assert "pasted-${Date.now().toString(36)}" in source
    # Plain text still pastes as text: only a paste that carries files is taken over.
    assert "if (!files.length) return;" in source


def test_a_message_shows_what_was_attached_in_chat_and_in_build():
    assert "ThomasAttachmentStrip.html(m.attachments)" in _read("js/chat_message_view.js")
    assert "itemsFrom(deps.state.docs, deps.state.images)" in _read("js/chat_stream_actions.js")
    mode = _read("js/unified_code_mode.js")
    assert "window.ThomasAttachmentStrip?.stage(state, message, context)" in mode
    assert "state.pendingAttachments = itemsFrom(context && context.docs, context && context.images)" in _read(
        "js/chat_attachment_strip.js"
    )
    assert "attachments: deps.state.pendingAttachments" in _read("js/unified_code_surface.js")
    assert "strip.recall(text)" in _read("js/unified_code_events.js")  # and again when the task is opened later


def test_build_sends_what_was_attached_with_the_run_request_so_thomas_can_read_it():
    lifecycle = _read("js/unified_code_lifecycle.js")
    assert "if (docs.length) base.docs = docs;" in lifecycle and "if (images.length) base.images = images;" in lifecycle
    # The shell hands both lists to Build, which is how a pasted file reaches the project.
    assert "docs: deps.state.docs.slice()" in _read("js/chat_stream_actions.js")
    assert "images: deps.state.images.slice()" in _read("js/chat_stream_actions.js")


def test_a_pictures_data_is_drawn_now_but_never_saved_or_copied():
    strip = _read("js/chat_attachment_strip.js")
    assert "Object.defineProperty(item, 'thumb'" in strip and "enumerable: false" in strip
    assert ".map(item => ({ name: item.name, kind: item.kind }))" in strip  # what is remembered is names only


def test_the_strip_and_its_styles_are_loaded_by_the_page():
    html = _read("chat.html")
    assert "/static/js/chat_attachment_strip.js" in html
    assert html.index("chat_attachment_strip.js") < html.index("chat_message_view.js")
    css = _read("css/unified_code_header.css")
    assert ".tc-att-strip" in css and '[data-ui-id="chat.composer"].is-dropping' in css
