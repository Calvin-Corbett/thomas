""""needs key" is a remedy now, not just a verdict.

The model menu listed Anthropic, Google, xAI, Meta Llama and Mistral, marked
every one "needs key", and the unified shell had NO way to supply one. The only
code that can POST a key lives in ``model_settings_dropdown.js``, which nothing
loads -- it targets ``#modelSetupModal``, an element the new shell does not have.
Five providers were visible, unusable, and unfixable from the UI.

``POST /api/secrets/{profile} {api_key}`` has always existed. Driven end to end
against a keyless profile with a dummy value, then cleaned up::

    key field           type=password, autocomplete=off
    has_key             False -> True
    the row afterwards  gone -- the profile became usable and the menu re-read
    page errors         none

Three properties this pins, each of which would be a real fault:

* the field must be ``type=password``. This menu is screenshotted constantly;
  a key in a text input ends up in the picture.
* the value must be cleared on submit, so it does not sit in the DOM afterwards.
* saving a key must NOT change the active model. Refreshing through ``boot()``
  would re-run its selection logic, and pasting a Mistral key would silently
  move the conversation to Mistral.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"


def _shell() -> str:
    """chat.html with comments stripped before anything is searched."""

    text = CHAT_HTML.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def _key_row_body() -> str:
    shell = _shell()
    start = shell.find("function buildKeyRow")
    assert start != -1, "buildKeyRow is gone; a keyless provider has no way to be given a key"
    return shell[start:start + 2400]


def test_the_key_row_is_rendered_for_keyless_providers() -> None:
    shell = _shell()
    # Negative lookbehind so the DEFINITION cannot satisfy the call check --
    # without it this passes with the call removed, which is the exact
    # built-but-never-called state that buried the old settings UI.
    assert re.search(r"(?<!function )buildKeyRow\(p\)", shell), (
        "buildKeyRow is defined but never called, so a provider marked "
        "'needs key' still offers no way to supply one"
    )
    assert "profileIsUsable(p)" in shell, (
        "the keyless list no longer filters on profileIsUsable, so the key row "
        "may appear for providers that already work"
    )


def test_the_key_is_typed_into_a_password_field_and_not_left_behind() -> None:
    body = _key_row_body()
    assert re.search(r"input\.type\s*=\s*'password'", body), (
        "the API key field is no longer type=password; the key becomes "
        "shoulder-readable and lands in every screenshot of this menu"
    )
    assert re.search(r"input\.value\s*=\s*''", body), (
        "the key is no longer cleared from the field on submit, so it sits in "
        "the DOM after being sent"
    )


def test_it_posts_the_key_to_the_secrets_endpoint() -> None:
    body = _key_row_body()
    assert "/api/secrets/" in body and "encodeURIComponent(profile.name)" in body, (
        "the key row no longer POSTs to /api/secrets/{profile}, or no longer "
        "escapes the profile name"
    )
    assert re.search(r"api_key:\s*key", body), (
        "the request body no longer carries api_key, which is the only field "
        "the endpoint accepts"
    )


def test_saving_a_key_does_not_switch_the_active_model() -> None:
    """The safety property.

    Reloading through boot() would re-run its "pick a usable profile" logic, so
    pasting a Mistral key could move the conversation to Mistral. The refresh
    used here updates what is usable and leaves the selection alone.
    """

    shell = _shell()
    start = shell.find("async function reloadModelProfiles")
    assert start != -1, "reloadModelProfiles is gone"
    body = shell[start:start + 900]
    assert "setProfile(" not in body, (
        "reloadModelProfiles now changes the active profile, so saving a key "
        "for one provider can silently switch the conversation to it"
    )
    assert "renderModelMenu()" in body, (
        "the refresh no longer redraws the menu, so a provider stays greyed out "
        "as 'needs key' after its key is accepted"
    )
