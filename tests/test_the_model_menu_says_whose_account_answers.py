"""The model menu says which account is answering, and on what plan.

`/api/openai-codex/status?profile=<name>` has always returned `logged_in`,
`email` and `plan_type`. The unified shell read none of it. The old Model Setup
modal showed it through `model_settings_dropdown.js` -- 18.8 KB the new shell
never loaded, because it targeted `#modelSetupModal`, an element that no longer
exists (that dead file has since been deleted). So "4 ready" was the only
signal a provider was usable, and nothing said WHOSE account was being spent.

Now the menu heads with the signed-in email and plan (`pro · signed in`),
verified on screen at 1920x1080.

Two failure modes this pins, both worse than showing nothing:

* claiming "signed out" because a fetch failed. The line HIDES on error rather
  than guessing, so a network blip cannot invent an account state.
* one request per render. The menu re-renders on every open and every accordion
  toggle, so the lookup is cached per profile.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"


def _shell() -> str:
    """chat.html with comments stripped before anything is searched.

    A guard written for the specialist rows passed with its call commented out
    because the searched text survived inside the comment. Handled here at the
    reader so no assertion below has to remember.
    """

    text = CHAT_HTML.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def test_the_account_line_is_rendered_not_merely_defined() -> None:
    shell = _shell()
    assert "function refreshAccountLine" in shell, "the account line builder is gone"
    # The negative lookbehind is load-bearing: without it the pattern also
    # matches the DEFINITION, and the assertion passes with the call removed --
    # the exact "built but never called" state that buried this feature.
    assert re.search(r"(?<!function )refreshAccountLine\(\);", shell), (
        "refreshAccountLine is defined but never called, so the menu shows no "
        "account even when one is signed in"
    )
    assert 'id="tc-model-account"' in shell, (
        "the account element is gone from the menu markup, so the builder has "
        "nothing to fill"
    )


def test_it_reads_the_fields_the_endpoint_actually_returns() -> None:
    """Field names are the whole contract here.

    `/api/openai-codex/status` returns logged_in / email / plan_type. Reading
    `plan` or `user` instead would render a blank line against a live account
    and look like being signed out.
    """

    shell = _shell()
    for field in ("logged_in", "email", "plan_type"):
        assert field in shell, (
            f"the account line no longer reads {field!r} from the codex status "
            f"payload; it would render empty against a signed-in account"
        )


def test_a_failed_lookup_hides_the_line_instead_of_guessing() -> None:
    shell = _shell()
    match = re.search(r"function refreshAccountLine[\s\S]{0,2600}", shell)
    assert match, "refreshAccountLine is gone"
    body = match.group(0)
    # The specific catch that records the failure, not any `.catch(` in the
    # window. A bare substring check passed with this handler deleted, because
    # `persistRoleModel` right below has its own `.catch(() => {})` and the
    # window reached it -- the same wrong-element error as reading a neighbour's
    # attribute.
    assert re.search(r"\.catch\(\(\)\s*=>\s*\{\s*accountByProfile", body), (
        "the account lookup no longer handles failure by recording it, so a "
        "rejected fetch leaves whatever was on screen before -- possibly "
        "another profile's account"
    )
    assert re.search(r"if \(!info \|\| !info\.logged_in \|\| !info\.email\)", body), (
        "the line no longer hides when the payload says signed out or carries "
        "no email; it must not guess an account state"
    )


def test_the_lookup_is_cached_per_profile() -> None:
    """The menu re-renders on every open and every accordion toggle."""

    shell = _shell()
    assert "accountByProfile" in shell, (
        "the per-profile cache is gone, so opening the menu fires a status "
        "request every time it renders"
    )
    assert re.search(r"hasOwnProperty\.call\(accountByProfile", shell), (
        "the cache is no longer consulted before fetching. A plain truthiness "
        "check would also miss a cached null, refetching forever for a profile "
        "that is signed out"
    )
