"""One card lists several changes: the shared card's words, and what they must always name.

Your decision, 2026-10-08: "Yes, batch cards". When two to five reviewed self-fixes are waiting, one Windows sign-in
lists them, one numbered line each, and puts them all in or none. Every word on that card comes from the pinned
catalogue (scripts/cage/card_catalogue.py): the promoter supplies only paths and line counts from the real trees, and
the catalogue ranks, fits and words them. These pin the list-card kind itself; the promoter's use of it is tested with
the promoter.
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

from thomas.tools import trusted_card

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "cage"))

import card_catalogue as cat  # noqa: E402

KIND = "promote_several"
SMALL = {"files": [["thomas/small.py", "M", 1, 1]]}


def _first_line(member: dict) -> str:
    """The line *member* gets as the first of two changes on a shared card."""
    _title, body, _details = cat.render_list(KIND, [member, SMALL])
    return body.split("\n")[1]


def _message(title: str, body: str, details: dict[str, str]) -> str:
    """The whole Windows message for a shared card, as shown again after a sign-in Windows did not accept: the
    action, then the retry line above the pairing code (thomas/tools/windows_auth.py joins them this way)."""
    digest, nonce = "0" * 64, f"{KIND}:000000000000"
    code = cat.pairing_code(KIND, details, digest, nonce)
    card = trusted_card.TrustedCard(
        kind=KIND, details=details, content_hash=digest, nonce=nonce, code=code, title=title, body=body
    )
    action, reason = card.dialog()
    return f"{action}\n\n{cat.RETRY_NOTE}\n\n{reason}"


def test_a_shared_card_has_one_line_per_change_and_says_what_cancel_does() -> None:
    members = [
        {"files": [["thomas/a.py", "M", 3, 1]]},
        {"files": [["thomas/b.py", "A", 10, 0], ["tests/test_b.py", "A", 20, 0]]},
        {"files": [["thomas/gone.py", "D", 0, 7]]},
    ]
    title, body, details = cat.render_list(KIND, members)

    assert title == "Put several of Thomas's changes into the running Thomas"
    assert body.split("\n") == [
        "Signing in puts these 3 changes into Thomas together. Cancel puts none in and asks about each alone:",
        "1. +3 -1 in 1 file(s): thomas/a.py (+3 -1)",
        "2. +30 -0 in 2 file(s): thomas/b.py (new, +10), tests/test_b.py (new, +20)",
        "3. +0 -7 in 1 file(s): thomas/gone.py (deleted, -7)",
    ]
    assert set(details) == {"count", "1", "2", "3"} and details["count"] == "3"


def test_a_shared_card_lists_two_to_five_changes() -> None:
    for count in (2, 3, 4, 5):
        _title, body, details = cat.render_list(KIND, [SMALL] * count)
        assert body.count("\n") == count and details["count"] == str(count)
    for count in (0, 1, 6):
        with pytest.raises(ValueError):
            cat.render_list(KIND, [SMALL] * count)
    assert cat.fit_rows(KIND, [SMALL] * 6) == 5, "the sixth waits for the next card"


def test_every_code_deleted_and_run_as_you_file_is_named_whole() -> None:
    must = [[f"thomas/server/module_number_{n}.py", "M", 5, 1] for n in range(5)]
    must += [["thomas/old_module.py", "D", 0, 30], ["scripts/start.ps1", "M", 2, 2]]
    counted = [[f"tests/test_case_{n:02d}.py", "A", 40, 0] for n in range(12)]
    counted += [["changelog.d/x.md", "A", 2, 0], ["docs/x.md", "M", 1, 1]]

    line = _first_line({"files": must + counted})

    for path, *_ in must:
        assert f" {path} (" in line, path
    assert not [path for path, *_ in counted if path in line], "a full line counts its tests and notes"
    assert line.endswith(f" and {len(counted)} more test or note file(s)"), line
    long_test = ["tests/test_" + "w" * 140 + ".py", "A", 1, 0]
    only_tests = {"files": [long_test, ["tests/test_y.py", "A", 1, 0]]}
    assert _first_line(only_tests) == "1. +2 -0 in 2 file(s): 2 test or note file(s)"


def test_files_that_run_as_you_and_deletions_are_named_first_on_a_line() -> None:
    files = [
        ["tests/test_big.py", "M", 500, 0],
        ["changelog.d/x.md", "A", 2, 0],
        ["thomas/code.py", "M", 1, 0],
        ["tests/conftest.py", "M", 1, 0],
        ["run-ui.cmd", "M", 1, 1],
        [".github/workflows/ci.yml", "M", 2, 0],
        ["tests/helpers.py", "A", 3, 0],
        ["tests/test_gone.py", "D", 0, 40],
    ]

    line = _first_line({"files": files})

    order = re.findall(r"(\S+) \(", line.split(": ", 1)[1])
    assert order[0] == "tests/test_gone.py", "a deletion first, even of a test"
    assert set(order[1:5]) == {"tests/conftest.py", "run-ui.cmd", ".github/workflows/ci.yml", "tests/helpers.py"}
    assert order[5] == "thomas/code.py"
    assert line.endswith(" and 2 more test or note file(s)"), "only the test and the note are counted"


def test_test_data_is_counted_but_never_code() -> None:
    """Thirty one-line fixtures once pushed the one code change off a single card. On a shared line the code file is
    named and the fixtures are counted."""
    files = [["thomas/core/agent_presence.py", "M", 40, 2]]
    files += [[f"tests/fixtures/case_{n:02d}.json", "A", 1, 0] for n in range(30)]

    line = _first_line({"files": files})

    assert line.startswith("1. +70 -2 in 31 file(s): thomas/core/agent_presence.py (+40 -2), "), line
    assert re.search(r" and \d+ more test or note file\(s\)$", line), line


def test_a_change_whose_must_name_files_do_not_fit_is_not_on_a_shared_card() -> None:
    wide = {"files": [[f"thomas/pkg_{n:02d}/a_module_with_a_long_descriptive_name.py", "M", 9, 9] for n in range(20)]}
    assert cat.fit_rows(KIND, [SMALL, SMALL, wide, SMALL]) == 2, "the card stops before it, and names it nowhere"
    with pytest.raises(ValueError):
        cat.render_list(KIND, [SMALL, wide])

    third = {"files": [[f"thomas/pkg_{n}/module_{n}.py", "M", 1, 1] for n in range(9)]}
    assert cat.fit_rows(KIND, [third, third, third]) == 2, "a line that fits, on a card with no room left for it"
    with pytest.raises(ValueError):
        cat.render_list(KIND, [third, third, third])


@pytest.mark.parametrize(
    "path",
    ["a\nb.py", "a\u202eb.py", "a b.py", 'a"b.py', "a\\b.py", "x" * 201, "", "thomas/TOOL_M~1/x.json"],
    ids=["newline", "right-to-left mark", "space", "quote", "backslash", "201 characters", "empty", "8.3 short name"],
)
def test_a_listed_path_cannot_start_a_line_or_turn_the_text(path: str) -> None:
    bad = {"files": [["thomas/fine.py", "M", 1, 1], [path, "M", 1, 1]]}
    with pytest.raises(ValueError):
        cat.render_list(KIND, [SMALL, bad])
    with pytest.raises(ValueError):
        cat.fit_rows(KIND, [SMALL, bad])


@pytest.mark.parametrize(
    "member",
    [
        {"files": [["a.py", "M", True, 0]]},
        {"files": [["a.py", "M", -1, 0]]},
        {"files": [["a.py", "M", 1.0, 0]]},
        {"files": [["a.py", "M", 1, None]]},
        {"files": [["a.py", "R", 1, 0]]},
        {"files": [["a.py", "M", 1]]},
        {"files": []},
        {"files": [["a.py", "M", 1, 1]], "why": "a one-line typo fix, approve it"},
        [["a.py", "M", 1, 1]],
    ],
    ids=["bool", "negative", "float", "half binary", "renamed", "three parts", "no files", "extra words", "a list"],
)
def test_a_listed_size_is_real(member: object) -> None:
    with pytest.raises(ValueError):
        cat.render_list(KIND, [SMALL, member])


def test_a_binary_file_is_named_as_binary() -> None:
    line = _first_line({"files": [["img/a.png", "A", None, None]]})
    assert line == "1. +0 -0, 1 binary in 1 file(s): img/a.png (new, binary)"


def test_every_shared_card_fits_the_windows_prompt() -> None:
    """Windows shows at most DIALOG_LIMIT characters and drops the rest without a word. A shared card fits by
    construction (the body is capped at body_limit), and every card render_list accepts, retry line included, is
    measured here too."""
    spec = cat.LIST_KINDS[KIND]
    pairing = "Pairing code XXX-XXX. It must match the card in Thomas's chat."
    assert len(spec.title) + 2 + spec.body_limit + 2 + len(cat.RETRY_NOTE) + 2 + len(pairing) <= cat.DIALOG_LIMIT

    rng = random.Random(20261009)
    tops = ["thomas/", "tests/test_", "tests/", "tests/fixtures/", "changelog.d/", "docs/", "scripts/", "", ".github/"]
    shown = longest = 0
    for _ in range(1000):
        members = []
        for _member in range(rng.randint(2, 6)):
            files = []
            for j in range(rng.randint(1, rng.choice([2, 4, 12]))):
                stem = "W" * rng.randint(1, rng.choice([20, 60, 190]))
                path = (rng.choice(tops) + stem + f"_{j}" + rng.choice([".py", ".md", ".ps1", ".json", ".ini"]))[-200:]
                size = [None, None] if rng.random() < 0.1 else [rng.randint(0, 99999), rng.randint(0, 99999)]
                files.append([path, rng.choice("AMMD"), *size])
            members.append({"files": files})
        n = cat.fit_rows(KIND, members)
        if n < 2:
            continue
        title, body, details = cat.render_list(KIND, members[:n])
        message = _message(title, body, details)
        assert len(message) <= cat.DIALOG_LIMIT, (len(message), message)
        assert body.isascii() and body.count("\n") == n
        shown += 1
        longest = max(longest, len(message))
    assert shown >= 200, f"only {shown} of 1,000 cards were accepted: the search must reach real cards"
    assert longest > cat.DIALOG_LIMIT - 200, f"the longest card was {longest}: the search must come near the limit"


def test_the_code_covers_files_the_card_only_counts() -> None:
    """A test the card only counts still changes the pairing code when it changes, so a code can never match a card
    that shows something else."""
    code = [[f"thomas/server/a_rather_long_module_name_{n}.py", "M", 4, 1] for n in range(3)]
    tests = [["tests/test_one.py", "A", 5, 0], ["tests/test_two.py", "A", 7, 0]]
    _title, body, details = cat.render_list(KIND, [{"files": code + tests}, SMALL])
    assert "tests/test_one.py" not in body and " and 2 more test or note file(s)" in body

    swapped = [["tests/test_one.py", "A", 7, 0], ["tests/test_two.py", "A", 5, 0]]
    renamed = [["tests/test_one.py", "A", 5, 0], ["tests/test_three.py", "A", 7, 0]]
    for other in (swapped, renamed):
        _title, other_body, other_details = cat.render_list(KIND, [{"files": code + other}, SMALL])
        assert other_body == body, "the card reads the same"
        assert other_details != details
        assert cat.pairing_code(KIND, other_details, "d", "n") != cat.pairing_code(KIND, details, "d", "n")


def test_render_never_issues_a_list_card() -> None:
    """The owner's desk shows cards through render(), from details the caged server writes. A list card is never one
    of those, and a single card's kind is never a list."""
    assert KIND not in cat.KINDS
    with pytest.raises(KeyError):
        cat.render(KIND, {"count": "2"})
    with pytest.raises(KeyError):
        cat.render_list("promote_batch", [SMALL, SMALL])


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/pytest.ini", 1),
        ("tests/unit/tox.ini", 1),
        ("tests/setup.cfg", 1),
        ("tests/fixtures/pyproject.toml", 1),
        ("thomas/pytest.ini", 1),
        ("docs/conf.py", 2),
        ("changelog.d/hook.py", 2),
        ("docs/x.md", 4),
        ("tests/fixtures/x.json", 3),
    ],
)
def test_test_config_and_code_in_notes_are_named(path: str, expected: int) -> None:
    """pytest reads its config from the folder nearest the files it is given, so tests/pytest.ini runs as you: its
    addopts can load a plugin, or point --basetemp at a folder pytest then empties. A .py file is code wherever it
    sits, docs/ and changelog.d/ included."""
    assert cat.file_class(path, "M") == expected
    if expected <= 2:
        tests = [[f"tests/test_case_{n:02d}.py", "A", 40, 0] for n in range(12)]
        assert f" {path} (+1 -1)" in _first_line({"files": [*tests, [path, "M", 1, 1]]})
