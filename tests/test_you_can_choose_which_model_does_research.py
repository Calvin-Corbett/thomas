"""Which model handles research, coding and the rest is choosable again.

Thomas already HAD per-specialist models and stopped showing them. The whole
path worked: ``worker_runtime._resolve_profile`` consults the per-role override
before the chat default, ``GET /api/models`` returns ``role_profiles`` and
``role_model_ids``, and ``PATCH /api/preferences`` writes them. What was missing
was any way to set one --- ``persist_user_model_role_preference`` has no
production caller at all, and nothing in the unified shell ever mentioned
``role_profiles``. The feature was reachable only by hand-editing preferences.

Driven end to end through the actual select, not the API::

    chose for Research                GPT-5.6 Terra
    after choosing                    {'research': 'openai_codex'} / {'research': 'gpt-5.6-terra'}
    after a full reload, the row shows GPT-5.6 Terra
    after choosing "Same as chat"     {} / {}

The clear matters as much as the set: the preferences patch treats an empty map
as "no change", so only an explicit null removes an override. A control that
could set but not unset would strand the owner on a choice.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"
DELEGATION = ROOT / "thomas" / "server" / "chat_delegation.py"


def _shell() -> str:
    """chat.html with comments removed before anything is searched.

    Without this, commenting the call out leaves the searched text intact and
    every assertion here still passes -- verified: the guard went green against
    ``/* renderSpecialistModels(wrap); */``. Fourth time this exact trap has
    appeared in guards I wrote today, which is why it is handled at the reader
    rather than in each assertion.

    Block comments cover the JS and the CSS; `//` is dropped only when it opens
    a line, so `https://` inside a string survives.
    """

    text = CHAT_HTML.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def test_the_specialist_ids_match_the_ones_delegation_accepts() -> None:
    """The whole feature is dead if the ids disagree.

    `chat_delegation` coerces any unknown specialist_id to "reasoning", so a UI
    offering a prettier name would cheerfully write an override that never
    matches anything. This is the check that keeps the two lists honest.
    """

    backend = re.search(
        r"specialist_id not in \{([^}]*)\}", DELEGATION.read_text(encoding="utf-8")
    )
    assert backend, "chat_delegation no longer declares its accepted specialist ids"
    accepted = set(re.findall(r'"([a-z_]+)"', backend.group(1)))

    block = re.search(r"SPECIALIST_ROLES\s*=\s*\[(.*?)\];", _shell(), re.S)
    assert block, "the shell no longer declares SPECIALIST_ROLES"
    offered = set(re.findall(r"\['([a-z_]+)'", block.group(1)))

    assert offered == accepted, (
        "the specialist ids offered in the model menu no longer match the ones "
        "the delegation runner accepts, so a chosen override would be coerced to "
        f"'reasoning' and silently ignored. menu={sorted(offered)} "
        f"backend={sorted(accepted)}"
    )


def test_the_rows_are_rendered_into_the_model_menu() -> None:
    """Built but never called is the state this feature was already in."""

    shell = _shell()
    assert "function renderSpecialistModels" in shell, "the specialist rows are gone"
    # The negative lookbehind is load-bearing. Without it the pattern matches the
    # DEFINITION -- `function renderSpecialistModels(wrap) {` -- so the assertion
    # passed with the call commented out, which is precisely the "defined but
    # never called" state this test exists to detect. Caught by reverting.
    assert re.search(r"(?<!function )renderSpecialistModels\(wrap\);", shell), (
        "renderSpecialistModels is defined but never called from the model menu, "
        "which is exactly how this capability was buried the first time"
    )


def test_choosing_same_as_chat_clears_the_override() -> None:
    """`""` means "no change" to the preferences patch; only null clears."""

    shell = _shell()
    assert re.search(r"role_profiles:\s*\{\s*\[role\]:\s*profileName\s*\|\|\s*null\s*\}", shell), (
        "the clear path no longer sends null for role_profiles, so selecting "
        "'Same as chat' leaves the previous override in place"
    )
    assert re.search(r"role_model_ids:\s*\{\s*\[role\]:\s*modelId\s*\|\|\s*null\s*\}", shell), (
        "the clear path no longer sends null for role_model_ids"
    )


def test_the_menu_opens_showing_what_is_actually_set() -> None:
    """Seeded from the payload that always carried it and nothing read."""

    shell = _shell()
    assert re.search(r"state\.roleProfiles\s*=.*prefs\.role_profiles", shell), (
        "the shell no longer seeds role overrides from /api/models, so the rows "
        "always read 'Same as chat' even when an override is set"
    )
    assert re.search(r"state\.roleModelIds\s*=.*prefs\.role_model_ids", shell), (
        "the shell no longer seeds role model ids from /api/models"
    )
