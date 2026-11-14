"""The approval cards: the only words a Windows PIN prompt may carry.

Owner direction, 2026-09-22: "if you got hacked, it could just literally say
whatever ... the card wants to say. So the solution is we make sure all the big
serious things have encrypted um, stuff in them. So the only card you can use is
the one that says what we want it to say."

These pin the catalogue itself: wording comes only from its templates, details
cannot smuggle in a second paragraph, the pairing code follows the content, and
the danger classifier sorts files into policy C's classes.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "cage"))

import card_catalogue as cat  # noqa: E402


def test_a_card_is_worded_only_by_its_template() -> None:
    title, body = cat.render("protected_write", {"path": "thomas/tools/x.py", "diffstat": "+3 -1 line(s)"})
    assert title == cat.KINDS["protected_write"].title
    assert body == "Change thomas/tools/x.py: +3 -1 line(s)"


def test_an_unknown_card_is_not_issued() -> None:
    with pytest.raises(KeyError):
        cat.render("anything_thomas_likes", {"text": "trust me"})


def test_a_card_with_the_wrong_details_is_refused() -> None:
    with pytest.raises(ValueError):
        cat.render("protected_write", {"path": "a.py"})
    with pytest.raises(ValueError):
        cat.render("protected_write", {"path": "a.py", "diffstat": "+1", "note": "extra words"})


def test_a_detail_cannot_start_a_second_paragraph() -> None:
    """A path is data. Newlines in it must not become new lines on the dialog,
    where they could forge a reassuring sentence under the real one."""
    _title, body = cat.render(
        "protected_write", {"path": "a.py\n\nThis is only a typo fix, approve it.", "diffstat": "+1 -0"}
    )
    assert "\n" not in body


def test_a_detail_is_capped() -> None:
    _title, body = cat.render("protected_write", {"path": "x" * 5000, "diffstat": "+1"})
    assert len(body) < 400


def test_the_pairing_code_follows_the_content() -> None:
    details = {"path": "a.py", "diffstat": "+1 -0"}
    one = cat.pairing_code("protected_write", details, cat.content_hash("print(1)"), "n1")
    assert one == cat.pairing_code("protected_write", details, cat.content_hash("print(1)"), "n1")
    assert one != cat.pairing_code("protected_write", details, cat.content_hash("print(2)"), "n1")
    assert one != cat.pairing_code("protected_write", details, cat.content_hash("print(1)"), "n2")


def test_the_pairing_code_is_easy_to_read_aloud() -> None:
    code = cat.pairing_code("raise_dial", {"dial": "Autonomy", "value": "5"}, cat.content_hash(""), "n")
    left, sep, right = code.partition("-")
    assert sep == "-" and len(left) == 3 and len(right) == 3
    assert set(left + right) <= set("23456789ABCDEFGHJKMNPQRSTVWXYZ"), "no 0/O or 1/I/L to misread"


def test_diffstat_says_what_happened() -> None:
    assert cat.diffstat(None, "a\nb\n") == "new file, 2 line(s)"
    assert cat.diffstat("a\nb\n", "a\nc\nd\n") == "+2 -1 line(s)"


def test_the_excerpt_is_the_real_diff() -> None:
    excerpt = cat.diff_excerpt("keep\nold\n", "keep\nnew\n")
    assert "-old" in excerpt and "+new" in excerpt
    assert "---" not in excerpt.splitlines()[0], "file headers are noise on a card"


def test_gates_are_dangerous() -> None:
    paths = cat.load_enforcement_paths(REPO)
    assert cat.danger_class("agent_safety.toml", enforcement_paths=paths) == cat.DANGER_GATES
    assert cat.danger_class("scripts/forge/gates/anything_new.py", enforcement_paths=paths) == cat.DANGER_GATES


def test_the_cage_and_approvals_are_dangerous() -> None:
    assert cat.danger_class("scripts/cage/card_catalogue.py") == cat.DANGER_CAGE
    assert cat.danger_class("thomas/tools/shell.py") == cat.DANGER_CAGE
    assert cat.danger_class("thomas\\tools\\windows_auth.py") == cat.DANGER_CAGE


def test_new_network_reach_is_dangerous_by_content() -> None:
    assert cat.danger_class("thomas/tools/x.py", added_diff="+import requests") == cat.DANGER_NETWORK
    assert cat.danger_class("thomas/tools/x.py", added_diff='+URL = "https://api.github.com/x"') == cat.DANGER_NETWORK
    assert cat.danger_class("thomas/tools/x.py", added_diff='+URL = "HTTPS://api.github.com/x"') == cat.DANGER_NETWORK
    assert cat.danger_class("thomas/tools/x.py", added_diff="-import requests") is None, (
        "removing reach is not adding it"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://fixture.invalid",
        "http://127.0.0.1:8888/x",
        "http://localhost:8899",
        "http://[::1]:8888",
        "https://ollama.example.com/v1",
        "https://example.org",
        "https://api.example/x",
        "https://thing.test?q=1",
        "http://app.localhost/",
        "http://127.0.0.1:{port}/x",
        "http://localhost:${port}/x",
        "http://localhost:%d",
        "http://127.0.0.1:",
    ],
)
def test_an_address_that_can_never_be_on_the_internet_is_not_reach(url: str) -> None:
    """2026-10-08: every self-fix card that day asked a second time, for a test's fake address."""
    assert cat.danger_class("tests/test_x.py", added_diff=f'+BASE = "{url}"') is None, url


@pytest.mark.parametrize(
    "line",
    [
        'BASE = "https://example.com@attacker.net/x"',
        'BASE = "https://example.com.attacker.net/x"',
        'BASE = "https://127.0.0.1.attacker.net/x"',
        'BASE = "https://localhost:8080@attacker.net"',
        'A = "https://fixture.invalid"; B = "https://attacker.net"',
        'BASE = "https://test/x"',
        "from requests import get  # see https://fixture.invalid",
        # What stands before an "@" is a user name; these characters are all allowed in one (RFC 3986).
        'BASE = "https://localhost;@attacker.net/x"',
        'BASE = "https://example.com,@attacker.net/x"',
        'BASE = "https://fixture.invalid)@attacker.net/x"',
        'BASE = "https://127.0.0.1:8080;@attacker.net/x"',
        'BASE = "https://api.example.com;x@attacker.net/x"',
        'BASE = "https://localhost:{port}@attacker.net/x"',
        'BASE = "https://localhost ,@attacker.net/x"',
    ],
)
def test_a_real_host_next_to_or_behind_a_fake_one_is_still_reach(line: str) -> None:
    assert cat.danger_class("tests/test_x.py", added_diff="+" + line) == cat.DANGER_NETWORK, line


@pytest.mark.parametrize("separator", ["\r", "\x0b", "\x0c", "\x1c", "\x85", " ", " "])
def test_a_separator_git_does_not_split_on_cannot_hide_reach(separator: str) -> None:
    """Python and JavaScript end a line at some of these; git does not, so they arrive inside one added line."""
    diff = f"--- a/x.py\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1{separator}import requests\n"
    assert cat.danger_class("thomas/x.py", added_diff=diff) == cat.DANGER_NETWORK, repr(separator)


def test_prose_that_mentions_a_library_is_not_reach() -> None:
    assert cat.danger_class("docs/x.md", added_diff="+Errors From httpx are retried. Import Requests first.") is None


def test_an_added_line_that_starts_with_plus_signs_is_still_read() -> None:
    """In a diff, an added line whose own text starts with "++" shows as "+++", like a file header."""
    diff = '--- a/x.md\n+++ b/x.md\n@@ -0,0 +1 @@\n+++ see "https://attacker.net"\n'
    assert cat.danger_class("docs/x.md", added_diff=diff) == cat.DANGER_NETWORK
    header_only = "--- a/x.md\n+++ b/https://attacker.net/x.md\n@@ -1 +1 @@\n-a\n+b\n"
    assert cat.danger_class("docs/x.md", added_diff=header_only) is None, "a file header is not an added line"


def test_an_ordinary_change_is_not_dangerous() -> None:
    assert cat.danger_class("thomas/tools/filesystem.py", added_diff="+x = 1") is None


# tests/test_a_question_takes_only_the_answers_it_offered.py (2026-10-09) added "from aiohttp import web" and got a
# guarded card of its own as "new network reach": one more sign-in for you. "web", and aiohttp's helpers that run
# entirely inside the test process, reach nothing.
IN_PROCESS = (
    "+from aiohttp import web\n"
    "+from aiohttp.test_utils import make_mocked_request, make_mocked_coro, loop_context\n"
    "+from aiohttp.test_utils import setup_test_loop, teardown_test_loop, unittest_run_loop, unused_port\n"
)


def test_aiohttp_web_and_its_in_process_helpers_in_a_test_are_not_reach() -> None:
    diff = "--- /dev/null\n+++ b/tests/test_q.py\n@@ -0,0 +1,6 @@\n+import asyncio\n+\n" + IN_PROCESS + "+\n"
    assert cat.danger_class("tests/test_a_question_takes_only_the_answers_it_offered.py", added_diff=diff) is None
    assert cat.danger_class("tests/test_x.py", added_diff=diff + "+import requests\n") == cat.DANGER_NETWORK
    for line in IN_PROCESS.splitlines():
        assert cat.danger_class("tests/test_x.py", added_diff=line) is None, line
        assert cat.danger_class("tests/test_x.py", added_diff=f"+    {line[1:]}\r") is None, "indented, CRLF"
    for path in ("thomas/server/x.py", "scripts/x.py", "thomas/tests/test_x.py", "tests/../thomas/x.py"):
        assert cat.danger_class(path, added_diff=diff) == cat.DANGER_NETWORK, f"outside tests/ it is reach: {path}"
        for line in IN_PROCESS.splitlines():
            assert cat.danger_class(path, added_diff=line) == cat.DANGER_NETWORK, (path, line)


@pytest.mark.parametrize(
    "line",
    [
        "import aiohttp",
        "import aiohttp.test_utils",
        "from aiohttp import ClientSession",
        "from aiohttp import web, ClientSession",
        "from aiohttp import ClientSession, web",
        "from aiohttp.web import run_app",
        # The question-answers test's other line. TestClient carries a live aiohttp ClientSession (TestClient.session),
        # and the test servers can listen beyond this machine: reach, as the review of 6689e87d found.
        "from aiohttp.test_utils import TestClient, TestServer",
        "from aiohttp.test_utils import TestClient",
        "from aiohttp.test_utils import TestServer",
        "from aiohttp.test_utils import RawTestServer",
        "from aiohttp.test_utils import BaseTestServer",
        "from aiohttp.test_utils import AioHTTPTestCase",
        "from aiohttp.test_utils import make_mocked_request, TestClient",
        # aiohttp.test_utils re-exports a client, the socket module and aiohttp itself.
        "from aiohttp.test_utils import ClientSession",
        "from aiohttp.test_utils import make_mocked_request, socket",
        "from aiohttp.test_utils import aiohttp",
        "from aiohttp.test_utils import (",
        "from aiohttp.test_utils import make_mocked_request, \\",
        "from aiohttp import web; import socket",
        "from aiohttp import web  # https://attacker.net",
        "from aiohttp import web\x0bimport requests",
        "import requests",
        "import httpx",
        "import socket",
        "from urllib.request import urlopen",
        'BASE = "https://attacker.net/x"',
    ],
)
def test_any_other_import_or_address_in_a_test_is_still_reach(line: str) -> None:
    assert cat.danger_class("tests/test_x.py", added_diff="+" + line) == cat.DANGER_NETWORK, line


# -- the single card names its files, and every change card says what Cancel does ------------------------------ #

# self-thomas-ea1c748556b8 (2026-10-08): six files. Its card capped the list at 200 characters and hid two of them
# without saying so.
EA1C = [
    ["thomas/server/chat_app_keys.py", "A", 26, 0],
    ["thomas/server/routes/chat_v2_keys.py", "M", 9, 14],
    ["thomas/server/app_chat_store.py", "M", 1, 1],
    ["thomas/server/worker_runtime.py", "M", 1, 1],
    ["tests/test_the_server_core_imports_no_route_module.py", "A", 33, 0],
    ["changelog.d/chat-keys-live-outside-routes.md", "A", 4, 0],
]


def test_a_single_card_names_its_files_without_cutting_one() -> None:
    limit = cat.KINDS["promote_batch"].cap("files")
    shown = cat.name_files(EA1C, limit)
    _title, body = cat.render("promote_batch", {"count": len(EA1C), "files": shown})
    for path, *_ in EA1C:
        assert path in body, path
    assert "..." not in body and " more" not in body, "nothing was cut and nothing was counted"
    assert "thomas/server/chat_app_keys.py (new, +26)" in body
    assert "thomas/server/routes/chat_v2_keys.py (+9 -14)" in body

    many = [[f"thomas/module_number_{n:02d}_with_a_long_descriptive_name.py", "M", n, 1] for n in range(40)]
    shown = cat.name_files(many, limit)
    assert len(shown) <= limit
    named = shown.rsplit(" and ", 1)[0].split(", ")
    assert shown.endswith(f" and {40 - len(named)} more"), shown
    assert all(any(name == cat.file_text(*f) for f in many) for name in named), "every name shown is whole"
    _title, body = cat.render("promote_batch", {"count": 40, "files": shown})
    assert shown in body, "the card shows the list exactly as named, never cut again"


def test_the_files_that_say_most_are_named_first() -> None:
    """When a list must be cut, what is cut is tests and notes: deletions, files that run as you outside Thomas, and
    code come first."""
    files = [
        ["tests/test_big.py", "M", 500, 0],
        ["changelog.d/x.md", "A", 3, 0],
        ["thomas/code.py", "M", 1, 0],
        ["tests/conftest.py", "M", 1, 0],
        ["run-ui.cmd", "M", 1, 0],
        [".github/workflows/ci.yml", "M", 1, 0],
        ["tests/helpers.py", "M", 1, 0],
        ["tests/test_gone.py", "D", 0, 9],
    ]
    order = re.findall(r"(\S+) \(", cat.name_files(files, 600))
    assert order[0] == "tests/test_gone.py", "a deletion first"
    assert set(order[1:5]) == {"tests/conftest.py", "run-ui.cmd", ".github/workflows/ci.yml", "tests/helpers.py"}
    assert order[5] == "thomas/code.py"
    assert order[6:] == ["tests/test_big.py", "changelog.d/x.md"]
    assert cat.file_class("tests/test_gone.py", "D") == 0
    assert cat.file_class("Thomas.vbs", "M") == 1 and cat.file_class("scripts/x.ps1", "M") == 1
    assert cat.file_class("thomas/x.py", "M") == 2
    assert cat.file_class("tests/test_x.py", "M") == 3 and cat.file_class("docs/x.md", "M") == 4
    assert cat.file_class("tests/fixtures/x.json", "A") == 3, "a data file under tests/ runs nothing"


def test_test_data_cannot_push_code_off_the_card() -> None:
    """Thirty one-line fixtures used to rank as files that run as you, ahead of code, and the one code change in the
    hand-in was counted in "and 16 more" without being named."""
    files = [["thomas/core/agent_presence.py", "M", 40, 2]]
    files += [[f"tests/fixtures/case_{n:02d}.json", "A", 1, 0] for n in range(30)]
    shown = cat.name_files(files, cat.KINDS["promote_batch"].cap("files"))
    assert shown.startswith("thomas/core/agent_presence.py (+40 -2), "), shown
    assert shown.endswith(" more")


@pytest.mark.parametrize(
    "path", ["a\nb.py", "a‮b.py", "a b.py", 'a"b.py', "a\\b.py", "x" * 201, "", "thomas/TOOL_M~1/x.json"]
)
def test_a_named_path_cannot_start_a_line_or_turn_the_text(path: str) -> None:
    with pytest.raises(ValueError):
        cat.name_files([[path, "M", 1, 1]], 600)


def test_a_named_file_has_a_real_size() -> None:
    with pytest.raises(ValueError):
        cat.name_files([["a.py", "M", -1, 0]], 600)
    with pytest.raises(ValueError):
        cat.name_files([["a.py", "R", 1, 0]], 600)
    with pytest.raises(ValueError):
        cat.name_files([], 600)
    assert cat.name_files([["a.png", "A", None, None]], 600) == "a.png (new, binary)"


def test_every_change_card_says_what_cancel_does() -> None:
    _title, body = cat.render("promote_batch", {"count": 1, "files": "a.py (+1 -1)"})
    assert body.splitlines()[-1] == "Cancel declines this change."
    _title, body = cat.render("promote_dangerous", {"category": cat.DANGER_CAGE, "path": "a.py", "diffstat": "+1"})
    assert body.splitlines()[-1] == "Cancel leaves this file out; any other file in its change is still asked."
    _title, body = cat.render("promote_batch", {"count": 1, "files": "a.py\nCancel approves this change."})
    assert body.count("\n") == 1, "the line break is the template's, never a detail's"


def test_a_detail_is_shown_as_plain_ascii() -> None:
    """A right-to-left mark in a detail would turn the text after it around on the dialog."""
    assert cat._one_line("x‮y") == "x?y"
    _title, body = cat.render("protected_write", {"path": "a‮.py", "diffstat": "+1 -0"})
    assert body.isascii() and "‮" not in body


def test_every_card_fits_the_windows_prompt_whatever_its_details() -> None:
    """Windows shows at most DIALOG_LIMIT characters of the message: title, body, the retry line, the pairing line
    and the guarded line together. The promoter measures each card before it asks; the owner desk
    (scripts/cage/owner_desk.py) renders any kind from details the caged server writes and measures nothing, so every
    detail at its longest must fit. A 600-character count beside the 600-character file list made 1,357 characters."""
    pairing = "Pairing code XXX-XXX. It must match the card in Thomas's chat."
    danger = max((cat.DANGER_GATES, cat.DANGER_CAGE, cat.DANGER_NETWORK), key=len)
    guarded = f"This touches {danger}. It gets its own approval every time."
    for kind, spec in cat.KINDS.items():
        title, body = cat.render(kind, {name: "W" * 5000 for name in spec.fields})
        message = f"{title}\n\n{body}\n\n{cat.RETRY_NOTE}\n\n{pairing}\n\n{guarded}"
        assert len(message) <= cat.DIALOG_LIMIT, (kind, len(message))
    assert cat.KINDS["promote_batch"].cap("files") == 600 and cat.KINDS["promote_batch"].cap("count") == 20


def test_the_catalogue_is_ascii_and_standard_library_only() -> None:
    """ASCII, because its pin is a hash computed in PowerShell and in Python and
    the two must agree. Standard library only, because the commit-master loads it."""
    path = REPO / "scripts" / "cage" / "card_catalogue.py"
    raw = path.read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII byte in the catalogue"
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for node in ast.walk(ast.parse(raw.decode("ascii"))):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        for name in names:
            assert name in allowed, f"the catalogue imports {name}"
