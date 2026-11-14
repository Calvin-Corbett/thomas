"""Each sentence of the Publish to GitHub row's words is listed here with the test that shows it is true.

Proves thomas.server.rows.public_release and thomas.server.routes.public_release_routes. The words are in
``thomas/server/rows/default.toml`` and are what the Plugins page shows. A sentence that is added or changed without a
line below fails, and so does a line that names a test that is not there.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
ROUTES = "test_the_publish_routes_ask_for_a_sign_in.py"
OFF = "test_turning_public_release_off_touches_only_its_routes.py"
BROWSER = "test_the_publish_section_in_a_real_browser.py"
CONFIRMED = "test_the_public_release_publishes_only_a_confirmed_preview.py"
WHERE = "test_a_confirmation_covers_where_the_release_goes.py"

PROOFS = {
    "Shows what would go into a public release of Thomas and, when you ask, sends a review copy to GitHub": [
        (BROWSER, "test_the_section_asks_nothing_until_a_button_is_pressed_and_shows_what_would_go_public"),
    ],
    "You find it in Settings, under Publish to GitHub": [
        ("test_the_publish_row_words_name_their_proofs.py", "test_settings_has_a_publish_to_github_section"),
    ],
    "Looking builds the public version in a scratch folder on this computer and checks it, which takes a few minutes, "
    "and sends nothing": [
        ("test_the_public_release_preview.py", "test_a_clean_release_is_safe_and_the_preview_counts_what_goes"),
        (ROUTES, "test_the_first_ask_starts_a_build_off_the_loop_and_says_working"),
        (CONFIRMED, "test_the_command_line_preview_sends_nothing_and_a_dry_run_sends_nothing"),
    ],
    "Sending asks you to sign in with Windows for exactly what you were shown, including where it goes, and writes "
    "only a new review branch": [
        (WHERE, "test_a_sign_in_for_one_destination_cannot_publish_to_another"),
        (WHERE, "test_the_prompt_names_the_destination_in_plain_words"),
        (CONFIRMED, "test_a_confirmed_preview_goes_to_a_review_branch_and_main_is_untouched"),
    ],
    "It never changes the main branch": [
        (CONFIRMED, "test_only_a_release_branch_is_ever_written_and_a_diverged_one_is_refused_not_forced"),
    ],
    "Only a program on this computer can ask": [
        (OFF, "test_a_caller_on_another_machine_with_the_right_token_is_refused_on_both_routes"),
    ],
    "While this is off, the Publish to GitHub section of Settings is still there, but it says publishing is turned "
    "off, and nothing is built or sent": [
        (BROWSER, "test_a_page_opened_with_the_row_off_asks_once_when_pressed_and_never_again"),
    ],
    "Nothing else in Thomas changes": [
        ("test_the_publish_row_words_name_their_proofs.py", "test_only_the_section_reads_these_routes"),
    ],
    "A preview that was already on the screen stays there until you reload the page, and sending it is then refused": [
        (BROWSER, "test_with_the_row_off_the_section_says_so_once_and_does_not_loop"),
    ],
    "Turning this on again brings the section back with no restart": [
        (OFF, "test_turning_it_on_brings_back_both_routes_without_a_restart"),
    ],
    "A preview that is still being built is thrown away when it finishes": [
        (ROUTES, "test_a_stop_throws_the_preview_away_and_a_build_that_ends_after_it_closes_its_own_copy"),
    ],
    "A release that is already being sent to GitHub carries on and cannot be called back": [
        ("test_the_publish_row_words_name_their_proofs.py", "test_a_stop_does_not_reach_a_release_being_sent"),
    ],
}


def _row() -> dict[str, str]:
    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text(encoding="utf-8"))["row"]
    return next(row for row in rows if row["id"] == "public_release")


def _sentences() -> list[str]:
    row = _row()
    text = " ".join(row[key] for key in ("about", "off_means", "stop_now"))
    return [part.strip().rstrip(".") for part in re.split(r"(?<=\.)\s+", text) if part.strip()]


def test_every_sentence_of_the_words_has_a_proof_listed() -> None:
    assert [s for s in _sentences() if s not in PROOFS] == []
    assert [s for s in PROOFS if s not in _sentences()] == []


def test_every_proof_listed_is_a_test_that_exists() -> None:
    missing = [
        (name, test)
        for proofs in PROOFS.values()
        for name, test in proofs
        if not re.search(rf"^def {re.escape(test)}\(", (TESTS / name).read_text(encoding="utf-8"), re.M)
    ]
    assert missing == []


def test_settings_has_a_publish_to_github_section() -> None:
    page = (ROOT / "thomas/server/web/settings.html").read_text(encoding="utf-8")

    assert 'data-section="publish"' in page and "<span>Publish to GitHub</span>" in page
    assert 'id="publish"' in page and '<div class="panel-title">Publish to GitHub</div>' in page
    assert page.index("settings.plugins-panel.js") < page.index("settings.publish-panel.js")


def test_only_the_section_reads_these_routes() -> None:
    web = ROOT / "thomas/server/web"
    callers = sorted(
        path.name
        for path in [*web.rglob("*.js"), *web.rglob("*.html")]
        if path.is_file() and "api/public-release" in path.read_text(encoding="utf-8", errors="ignore")
    )

    assert callers == ["settings.publish-panel.js"]


def test_a_stop_does_not_reach_a_release_being_sent() -> None:
    """The stop step closes the preview and nothing else: it holds no handle on a push that is running."""
    from thomas.server.routes import public_release_routes as routes

    source = (ROOT / "thomas/server/routes/public_release_routes.py").read_text(encoding="utf-8")
    stop = source.split("async def stop(self)")[1].split("def read(self)")[0]

    assert "publish" not in stop and "cancel" not in stop
    assert routes.ReleaseJobs.stop.__name__ == "stop"


def test_the_words_pass_the_plugins_page_rules() -> None:
    row = _row()
    banned = re.compile(
        r"\b(row|fork|kernel|mount|seam|hook|profile|entry|unloading|pending|disposed|loopback)\b", re.I
    )
    text = " ".join(row[key] for key in ("title", "about", "off_means", "stop_now"))

    assert not banned.search(text)
    assert not set("/\\_") & set(text)
    assert row["title"].lower() != row["id"].lower()
