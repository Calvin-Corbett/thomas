"""Referee core, class D content (plan B1; invariant 28): the repository's own fragment check decides, plus stricter rules."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.cage.referee import fragment as vendored
from scripts.cage.referee.fragment import content_problems, grammar_problems, parse_fragment
from scripts.forge import changelog_fragments as repo

from tests.express_referee_support import FRAGMENT, decide, git, lab, patch_adding  # noqa: F401

REPO_ROOT = Path(repo.__file__).resolve().parents[2]
NAME = "lab-sample-note.md"
SAMPLES = {  # name, text: the repository's grammar accepts or refuses each of these
    NAME: "### Added\n- One bullet.\n",
    "lab-two-sections.md": "### Added\n- One.\n\n### Fixed\n- Two\n  continued here.\n",
    "Lab-Upper.md": "### Added\n- Upper-case name.\n",
    "nodash.md": "### Added\n- No dash in the name.\n",
    "lab-wrong.txt": "### Added\n- Wrong extension.\n",
    "lab-empty-section.md": "### Added\n\n### Fixed\n- Only the second has a bullet.\n",
    "lab-no-header.md": "- A bullet with no section header.\n",
    "lab-no-bullet.md": "### Added\nJust prose.\n",
    "lab-bad-header.md": "### Improved\n- Not one of the five headers.\n",
    "lab-bullet-spacing.md": "### Added\n-no space after the dash\n",
    "lab-empty.md": "",
}


def repo_problems(tmp_path: Path, name: str, text: str) -> list[str]:
    target = tmp_path / name
    target.write_bytes(text.encode("utf-8"))
    return repo.check_fragment(target)


def test_vendored_fragment_grammar_matches_repo(tmp_path):
    """The drift test: the copied patterns, section list and parser behave exactly as the repository's."""
    assert vendored.SECTIONS == repo.SECTIONS
    for mine, theirs in (
        (vendored._NAME, repo._NAME),
        (vendored._SECTION, repo._SECTION),
        (vendored._BULLET, repo._BULLET),
    ):
        assert mine.pattern == theirs.pattern and mine.flags == theirs.flags
    real = [(p.name, p.read_text(encoding="utf-8")) for p in repo.list_fragments(REPO_ROOT / "changelog.d")]
    assert real, "the repository has no fragments to compare against"
    for name, text in [*SAMPLES.items(), *real]:
        assert parse_fragment(text) == repo.parse_fragment(text), name
        assert (grammar_problems(name, text) == []) == (repo_problems(tmp_path, name, text) == []), name


def test_class_d_fragment_must_pass_repo_check(lab, git, tmp_path):
    """Invariant 28: whatever the referee takes as Express, the repository's own check accepts."""
    taken = refused = 0
    for name, text in SAMPLES.items():
        decision = decide(lab, git, patch_adding(lab, {f"changelog.d/{name}": text.encode()}))
        if decision.lane == "express":
            taken += 1
            assert repo_problems(tmp_path, name, text) == [], name
        else:
            refused += 1
    assert taken == 2 and refused == len(SAMPLES) - 2
    for path in repo.list_fragments(REPO_ROOT / "changelog.d"):  # the repository's real fragments: none slips past
        data = path.read_bytes()
        if not content_problems(path.name, data):
            assert repo.check_fragment(path) == [], path.name


@pytest.mark.parametrize(
    "body,code",
    [
        (b"### Added\n- See https://example.invalid/page for details.\n", "url"),
        (b"### Added\n- Visit www.example.invalid today.\n", "url"),
        (b"### Added\n- Write to someone@example.invalid.\n", "email"),
        (b"### Added\n- Uses <b>bold</b> text.\n", "html"),
        (b"### Added\n- Uses &amp; as an entity.\n", "html"),
        (b"### Added\n- A [link](somewhere) in text.\n", "link"),
        (b"### Added\n- A [reference][ref] link.\n\n[ref]: elsewhere\n", "link"),
        ("### Added\n- Café is not ASCII.\n".encode(), "not_plain_ascii"),
        (b"### Added\n- Tab\there.\n", "not_plain_ascii"),
        (b"### Added\r\n- CRLF line ends.\r\n", "not_plain_ascii"),
        (b"### Added\n- " + b"x" * 4100 + b"\n", "too_large"),
        (b"### Added\n- The owner asked for this.\n", "wording"),
        (b"### Added\n- The user could not understand it.\n", "wording"),
        (b"### Added\n- This helps a non-technical person.\n", "wording"),
        (b"### Added\n- Calvin wanted a button.\n", "wording"),
        (b"### Added\n- The  user asked for this.\n", "wording"),
        (b"### Added\n- The\n  owner asked for this.\n", "wording"),
        (b"### Added\n- Pay at evil.example.com/pay now.\n", "url"),
        (b"### Added\n- Go to example.org for more.\n", "url"),
        (b"### Added\n- See EXAMPLE.COM.\n", "url"),
        (
            b"### Fixed\n- Fixes ledger.py, run.sh, notes.md and thomas/core/leaf.py in version 0.19.40; see changelog.d/foo-bar.md\n"
            b"  and thomas.core.config for e.g. the i.e. case.\n",
            "",
        ),
        (b"### Added\n- You wanted a button, so there is one.\n", ""),
        (b"### Added\n- The check now reads the file as it is on disk.\n", ""),
    ],
)
def test_class_d_content_rules(lab, git, body, code):
    problems = content_problems(NAME, body)
    assert (code in problems) if code else problems == [], problems
    decision = decide(lab, git, patch_adding(lab, {f"changelog.d/{NAME}": body}))
    assert decision.lane == ("regular" if code else "express"), decision


def test_a_name_ending_in_a_line_break_is_not_a_fragment_name():
    assert grammar_problems("lab-note.md\n", "### Added\n- One.\n") == ["name"]
    assert repo._NAME.match(
        "lab-note.md\n"
    )  # the repository's own pattern is looser: the referee is stricter on purpose


def test_the_plain_fragment_is_taken(lab, git):
    assert content_problems(NAME, FRAGMENT) == []
