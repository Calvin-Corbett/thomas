"""A deliverable's deep link must be readable by the shell it points at.

`/?forge_code=<cid>` is minted in thomas/forge/anvil/forge_code_deliverables.py.
For nine days nothing on `/` read it. The only consumer shipped inside the split
runtime, which is pulled by index.html -- served at `/classic`, not `/`. My
Stuff's "Open Source Chat" button navigates the top frame straight to that link,
so clicking a finished build's route back to the conversation that produced it
dropped the reader on a blank Chat surface, parameter still in the URL, with no
error and no hint that anything had been requested.

The existing test for this feature, tests/test_forge_code_deliverables.py, asserts
`entry["deep_link"] == "/?forge_code=fc_123"` -- a string comparison against a
dict the function under test just built. It could not have failed if the consumer
were deleted, if `/` were rewired, or if the param were renamed, because it never
resolves a route and never runs a line of JavaScript. That is the shape this file
exists to close: the only green check measured the producer against itself.

So these tests deliberately cross three independently-authored places -- the
Python that mints the link, the route that decides which shell answers `/`, and
the JavaScript that shell actually loads -- because the bug was that they had
drifted out of step while each was internally consistent.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"

PRODUCER = ROOT / "thomas" / "forge" / "anvil" / "forge_code_deliverables.py"
ROUTE_HELPERS = ROOT / "thomas" / "server" / "app_middleware_helpers.py"

PARAM = "forge_code"
# Matches a read of the parameter -- `get('forge_code')` -- and not prose. A bare
# substring search also matched a comment mentioning `forge_code_projects.py` in
# unified_code_projects.js, which put a file with no handler at the front of the
# reader list and made the behaviour assertions inspect the wrong 2000 characters.
PARAM_READ = re.compile(r"""['"]forge_code['"]""")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _shell_served_at_root() -> str:
    """The filename the `/` handler reads, taken from the handler itself."""
    source = _read(ROUTE_HELPERS)
    body = source.split("async def index(", 1)[1].split("async def ", 1)[0]
    names = re.findall(r'web_dir\s*/\s*"([^"]+\.html)"', body)
    assert names, "could not determine which HTML the `/` handler serves"
    assert len(set(names)) == 1, f"the `/` handler serves more than one shell: {set(names)}"
    return names[0]


def _scripts_loaded_by(shell: str) -> list[Path]:
    """Every same-origin <script src> the shell pulls, resolved to a real file.

    `/static/` is a route mount over thomas/server/web, not a directory, so
    `/static/js/x.js` lives at web/js/x.js. Unresolvable sources are a hard
    failure rather than a skip: quietly dropping the scripts it cannot find is
    how this helper would report "no reader" while the reader sat in a file it
    failed to open -- which is exactly the mistake it exists to catch. The first
    draft did precisely that and reported all 13 scripts missing.
    """
    html = _read(WEB / shell)
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    paths: list[Path] = []
    unresolved: list[str] = []
    for src in srcs:
        if src.startswith(("http://", "https://", "//", "data:")):
            continue
        rel = src.split("?", 1)[0].lstrip("/")
        candidates = [WEB / rel]
        if rel.startswith("static/"):
            candidates.append(WEB / rel[len("static/") :])
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            unresolved.append(src)
        else:
            paths.append(found)

    assert not unresolved, (
        f"{shell} loads scripts this test cannot open: {unresolved} -- "
        "resolve them or the reader search below is searching nothing"
    )
    assert paths, f"{shell} loads no resolvable local scripts -- the walk below would be vacuous"
    return paths


def test_the_producer_still_mints_the_param_these_tests_track() -> None:
    """If the link format changes, the rest of this file must be re-read rather
    than silently keep passing against a parameter nobody emits."""
    producer = _read(PRODUCER)

    assert f'"/?{PARAM}=' in producer or f"/?{PARAM}=" in producer, (
        f"the deliverable deep link no longer contains ?{PARAM}= -- "
        "update this file deliberately"
    )


def test_the_shell_served_at_root_actually_reads_the_deep_link_param() -> None:
    """The regression, stated as a contract.

    Before the fix this failed: `/` serves chat.html, and not one of the scripts
    chat.html loads contained the string `forge_code`. The reader existed only in
    the split runtime, which chat.html does not pull.
    """
    shell = _shell_served_at_root()
    scripts = _scripts_loaded_by(shell)

    readers = [p.name for p in scripts if PARAM_READ.search(_read(p))]

    assert readers, (
        f"{shell} is served at / and carries the {PARAM} deep link, but none of its "
        f"{len(scripts)} scripts read that parameter -- every deliverable's "
        f"'open the conversation that built this' link is a no-op. "
        f"scripts checked: {[p.name for p in scripts]}"
    )


def _deep_link_handler_source() -> str:
    """The source of the one loaded script that reads the param.

    Whole-file rather than a character window around the first match: windowing
    picked up a neighbouring file's comment and then asserted against text that
    had nothing to do with the handler.
    """
    shell = _shell_served_at_root()
    readers = [p for p in _scripts_loaded_by(shell) if PARAM_READ.search(_read(p))]
    assert readers, "no script served at / reads the param; see the previous test"
    return "\n".join(_read(p) for p in readers)


def test_the_reader_switches_to_code_mode_and_opens_that_conversation() -> None:
    """Reading the param is not enough -- it has to do the two things that make
    the link mean something. Pins behaviour, not one spelling of it."""
    source = _deep_link_handler_source()

    assert re.search(r"setMode\(\s*['\"]code['\"]", source), (
        "the deep-link handler does not switch to Code mode, so the conversation "
        "would load behind whatever surface happened to be showing"
    )
    assert "loadConversation" in source, (
        "the deep-link handler does not open the conversation it was given"
    )


def test_the_param_is_consumed_so_a_refresh_does_not_replay_it() -> None:
    """A link that survives in the URL reopens on every reload, and reopens the
    failure too when the task cannot be loaded."""
    source = _deep_link_handler_source()

    assert "replaceState" in source, "the handler leaves forge_code in the URL"
    assert re.search(r"searchParams\.delete\(\s*['\"]forge_code['\"]", source), (
        "the handler does not strip the parameter it consumed"
    )
