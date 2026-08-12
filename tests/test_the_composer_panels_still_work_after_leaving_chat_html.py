"""The composer's panels kept working when they moved out of chat.html.

chat.html was 3310 lines against the 3000-line hard ceiling in
``tests/test_architecture.py::test_frontend_file_sizes``, so the page failed that
guard outright. The 349 lines behind the composer bar --- the AI-settings sheet,
the Thomas Library picker, the attachment chips and the mic --- moved verbatim to
``js/chat_composer_panels.js``::

    before   chat.html 3310 lines   FRONTEND FILE SIZE VIOLATIONS
    after    chat.html 2975 lines   (warning only, soft limit 2000)
             js/chat_composer_panels.js 386 lines (soft limit 800)

Everything in that block ran inside one closure and read ``state``, ``esc``,
``inputEl``, ``autosize``, ``syncDynamic``, ``DIAL_FIELDS`` and ``saveDials``
directly, so the whole risk of the move is scope, not logic. Driven at
127.0.0.1:8917 on the real page: 0 console errors, the AI-settings sheet renders
all six dials, the Library panel loads 2 projects and renders their cards,
monograms and "4 days ago" meta, the search filters 2 -> 1 -> 2, Escape closes
it, and a dropped file becomes an attachment chip. With the module removed the
page dies at the destructure with ``Cannot read properties of undefined
(reading 'create')`` and renders 0 welcome cards --- so those readings could
have shown failure.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "thomas" / "server" / "web"
CHAT_HTML = WEB / "chat.html"
PANELS_JS = WEB / "js" / "chat_composer_panels.js"
PANELS_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_composer_panels.mjs"


def test_chat_html_is_back_under_its_hard_ceiling() -> None:
    lines = len(CHAT_HTML.read_text(encoding="utf-8", errors="replace").splitlines())
    assert lines < 3000, f"chat.html is {lines} lines; the hard ceiling is 3000"
    panel_lines = len(PANELS_JS.read_text(encoding="utf-8", errors="replace").splitlines())
    assert panel_lines < 1500, f"chat_composer_panels.js is {panel_lines} lines; the JS ceiling is 1500"


def test_the_panel_module_loads_before_the_inline_shell_script() -> None:
    """A module loaded after the inline block is a module the page never sees."""

    text = CHAT_HTML.read_text(encoding="utf-8", errors="replace")
    tag = text.index('src="/static/js/chat_composer_panels.js')
    inline = text.index("\n  <script>\n")
    assert tag < inline, "chat_composer_panels.js must load before the inline shell script"


def test_every_panel_the_page_calls_is_exported_and_destructured() -> None:
    """The trap this guards: lifted out, exported, and never bound back.

    chat.html still calls these by bare name. If the module stops returning one,
    or the destructure drops it, the page throws on the first click instead of
    failing here.
    """

    text = CHAT_HTML.read_text(encoding="utf-8", errors="replace")
    js = PANELS_JS.read_text(encoding="utf-8", errors="replace")

    bind = re.search(
        r"const \{(.*?)\} = window\.ThomasChatComposerPanels\.create\(\{(.*?)\}\);",
        text,
        re.S,
    )
    assert bind, "chat.html no longer binds the composer panels back into scope"
    destructured = set(re.findall(r"[A-Za-z_$][\w$]*", bind.group(1)))
    handed = set(re.findall(r"[A-Za-z_$][\w$]*", bind.group(2)))
    returned = set(re.findall(r"[A-Za-z_$][\w$]*", js.split("    return {", 1)[1].split("};", 1)[0]))

    for name in ("toggleToolsMenu", "closeToolsMenu", "toggleLibraryMenu", "closeLibraryMenu",
                 "libraryVisibleProjects", "libraryCardHTML", "mountLibraryPreviews",
                 "chooseLibraryProject", "onFiles", "renderAttachments", "setupMic"):
        assert name in destructured, f"{name} is called in chat.html but never bound back"
        assert name in returned, f"{name} is bound in chat.html but the module never returns it"
        assert f"function {name}" in js, f"{name} is exported but not defined in the module"
        assert f"function {name}" not in text, f"{name} is defined twice -- the page kept a copy"

    for dep in ("state", "esc", "inputEl", "autosize", "syncDynamic", "DIAL_FIELDS", "saveDials"):
        assert dep in handed, f"{dep} is read inside the module but the page never hands it over"


def test_the_lifted_panels_run_with_the_values_the_page_hands_them() -> None:
    """Drives the module in node: cards render, search filters, the mic types."""

    result = subprocess.run(
        ["node", str(PANELS_HARNESS), str(PANELS_JS)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout.strip().splitlines()[-1])
    assert all(checks.values()), checks
