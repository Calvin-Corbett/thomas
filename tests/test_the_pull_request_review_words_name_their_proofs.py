"""Each sentence the Plugins page shows for ``thomas.server.rows.pr_review``, with the tests that show it.

The words are in ``thomas/server/rows/default.toml``. A new sentence, a changed one or a dropped one fails here until it
is listed with a test that shows it. This file needs no server, and that name is how a check finds it when the list
changes, so the walk through the real page runs only for a change to the page or the row, and the words cannot land
without being read against it.

The scans at the end hold what a route test cannot see: nothing else in Thomas reads a review, and no page calls these
routes. A caller added anywhere else is found by the full suite, which is the one run that always holds this.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import PROFILE_PATH

THIS_FILE = "tests/test_the_pull_request_review_words_name_their_proofs.py"
OFF_TEST = "tests/test_turning_pr_review_off_touches_only_its_routes.py"
WEB = ROOT / "thomas" / "server" / "web"
WORDS = {
    "about": {
        "Keeps pull request reviews for other programs to call.": (
            "test_a_whole_review_works_through_the_row_on_a_real_server",
        ),
        "No page in Thomas shows them any more, so only other programs can use it.": (
            "test_no_page_in_thomas_calls_these_routes",
        ),
        "A caller sends a diff, and it ranks each change by risk and lets the caller comment, hand off a fix and "
        "approve.": ("test_a_whole_review_works_through_the_row_on_a_real_server",),
        "All of that stays in these routes: it does not reach GitHub or change your code, no agent picks up a fix that "
        "is handed off, and approving only marks the review.": (
            "test_a_review_cannot_reach_anything_outside_the_section",
            "test_nothing_else_in_thomas_reads_a_review_a_fix_or_an_approval",
        ),
        "Reviews last only until Thomas restarts.": ("test_nothing_a_review_holds_reaches_the_disk",),
    },
    "off_means": {
        "While this is off, nothing you see in Thomas changes, because no page uses it.": (
            "test_no_page_in_thomas_calls_these_routes",
        ),
        "Every one of its routes answers 404 and none is listed.": (
            "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
        ),
        "Thomas keeps the reviews it holds while this is off, and they are there again when it is back on.": (
            "test_reviews_outlive_off_and_on_and_their_numbers_go_on",
        ),
        "A restart still loses them.": ("test_nothing_a_review_holds_reaches_the_disk",),
        "Opening a pull request from chat does not use this and is not affected.": (
            "test_opening_a_pull_request_from_chat_does_not_touch_this_row",
        ),
    },
    "stop_now": {
        "A review or comment still on its way to Thomas is cut off and not kept, so it needs sending again.": (
            "test_stop_now_cuts_off_a_review_still_arriving_and_keeps_nothing_of_it",
        ),
        "Reviews Thomas already holds are not touched.": (
            "test_stop_now_cuts_off_a_review_still_arriving_and_keeps_nothing_of_it",
        ),
    },
}


def _row() -> dict[str, str]:
    with PROFILE_PATH.open("rb") as handle:
        return next(row for row in tomllib.load(handle)["row"] if row["id"] == "pr_review")


@pytest.mark.parametrize("field", WORDS)
def test_every_sentence_names_the_test_that_shows_it(field: str) -> None:
    proofs = "".join((ROOT / path).read_text(encoding="utf-8") for path in (OFF_TEST, THIS_FILE))

    assert re.split(r"(?<=\.)\s+", _row()[field]) == list(WORDS[field])
    named = {name for names in WORDS[field].values() for name in names}
    assert named  # an empty list would pass below
    assert {name for name in named if f"def {name}(" not in proofs} == set()


def test_a_change_to_the_list_runs_this_file() -> None:
    assert THIS_FILE in select(ROOT, ["thomas/server/rows/default.toml"]).files


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(str(node.module))
    return found


def test_a_review_cannot_reach_anything_outside_the_section() -> None:
    """The words say it reaches no GitHub and changes no code. These two files import nothing that could.

    If either gains an import, this fails and those words have to be read again.
    """
    assert _imports(ROOT / "thomas" / "tools" / "pr_review.py") == {
        "__future__",
        "collections.abc",
        "dataclasses",
        "re",
    }
    assert _imports(ROOT / "thomas" / "server" / "routes" / "pr_review_routes.py") == {
        "__future__",
        "aiohttp",
        "json",
        "logging",
        "thomas.tools.pr_review",
        "typing",
    }


def test_nothing_else_in_thomas_reads_a_review_a_fix_or_an_approval() -> None:
    """The words say no agent picks up a fix and Approve PR only marks the review. If anything starts to, they must change."""
    reaching = re.compile(r"tools\.pr_review|pr_review_routes|PrReviewStore|PrReview\b|fix_tasks|create_fix_task")
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if reaching.search(path.read_text(encoding="utf-8", errors="replace"))
    }

    assert found == {
        "thomas/server/rows/pr_review.py",
        "thomas/server/routes/pr_review_routes.py",
        "thomas/tools/pr_review.py",
    }


def test_opening_a_pull_request_from_chat_does_not_touch_this_row() -> None:
    tool = (ROOT / "thomas" / "tools" / "git.py").read_text(encoding="utf-8")

    assert 'name = "git.pull_request"' in tool
    assert "pr_review" not in tool


def test_no_page_in_thomas_calls_these_routes() -> None:
    """The words say no page shows reviews any more. A new caller has to be read, and the old page must stay gone."""
    pages = [
        path
        for folder in (WEB, ROOT / "extensions", ROOT / "apps", ROOT / "desktop", ROOT / "web")
        if folder.is_dir()
        for path in folder.rglob("*")
        if path.suffix in {".html", ".js", ".mjs", ".ts", ".tsx"} and "node_modules" not in path.parts
    ]
    assert pages  # an empty read would pass below

    calling = [path for path in pages if "api/pr-review" in path.read_text(encoding="utf-8", errors="replace")]

    assert calling == []
    assert not (WEB / "js" / "pr_review_panel.js").exists()
