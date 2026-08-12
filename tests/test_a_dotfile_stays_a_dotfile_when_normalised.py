"""A protected file whose name starts with a dot must survive path normalisation.

`_normalize_relpath` ended in ``.lstrip("./")``. ``str.lstrip`` takes a SET of
characters rather than a prefix, so it ate every leading ``.`` and ``/`` — and
every consumer turns the result straight back into a real filesystem path.

``.gitignore`` is a ``[protected] policy_files`` entry in ``agent_safety.toml``.
Normalised to ``gitignore``, it names a file that exists in neither the blue nor
the green tree, and `_promotion_protected_diffs` opens with::

    if not blue_path.exists() and not green_path.exists(): continue

So "this protected file changed" could not be reported for it — not for some
inputs, for ANY input. The gate had exactly one reachable answer.

Worse than a miss: `_restore_green_path_from_blue` copies ``blue/<norm>`` over
``green/<norm>``, so reverting a tampered ``.gitignore`` wrote nothing while
`_revert_protected_changes` still listed the path as reverted. A false claim,
not a silent gap.

The control below matters as much as the case: a leading ``./`` must still be
dropped, or this "fix" would just be a different wrong answer.
"""

from __future__ import annotations

import pytest

from thomas.forge.anvil.doppelganger import _normalize_relpath as normalise_doppelganger
from thomas.forge.anvil.evolve_charter import _normalize_relpath as normalise_charter

NORMALISERS = pytest.mark.parametrize(
    "normalise",
    [normalise_doppelganger, normalise_charter],
    ids=["doppelganger", "evolve_charter"],
)


@NORMALISERS
def test_a_dotfile_keeps_its_leading_dot(normalise) -> None:
    assert normalise(".gitignore") == ".gitignore", (
        "a protected dotfile is renamed by normalisation, so every path built "
        "from it names a file that exists in neither tree and its guard can "
        "only ever answer one way"
    )
    assert normalise(".github/workflows/ci.yml") == ".github/workflows/ci.yml"
    assert normalise("..hidden") == "..hidden", "leading dots are part of the name"


@NORMALISERS
def test_a_leading_dot_slash_is_still_dropped(normalise) -> None:
    """The control. Without it, keeping dots could just be a different wrong answer."""

    assert normalise("./thomas/x.py") == "thomas/x.py"
    assert normalise(".\\thomas\\x.py") == "thomas/x.py", "Windows separators normalise too"


@NORMALISERS
def test_an_ordinary_path_is_untouched(normalise) -> None:
    assert normalise("thomas/server/app.py") == "thomas/server/app.py"
    assert normalise("") == ""


@NORMALISERS
def test_the_character_set_bug_cannot_come_back(normalise) -> None:
    """`lstrip("./")` strips a SET, so it eats any run of dots and slashes.

    Pinned by behaviour rather than by scanning the source, so a rewrite that
    reintroduces the bug in different words still fails.
    """

    assert normalise("./.gitignore") == ".gitignore", (
        "a leading './' was dropped but the dotfile's own dot went with it"
    )
    assert normalise("...config") == "...config"
