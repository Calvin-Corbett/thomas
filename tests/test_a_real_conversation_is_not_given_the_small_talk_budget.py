"""Every turn is `model_owned`, so it must not run on the small-talk allowance.

`IntentRouter.decide()` returns `PATH_MODEL_OWNED` unconditionally -- it opens with
`del text, prior_route` and never branches. There is exactly one route for a
natural-language turn, and `loop_streaming.py` says so in as many words.

When the prompt-word classifier was retired, `model_owned` was added to the
casual-chat branch of both history helpers. So every real conversation -- a coding
session, a research thread, a twenty-turn debugging chat -- was cut to 2200 tokens
and ten messages of history, while the 5200 written for `coding_task` sat in a
branch nothing could reach. Thomas forgot constraints set earlier in the same
session, and the code that was supposed to prevent that was dead.

These tests pin the routing fact first, because the budget only matters if
`model_owned` really is universal. If the router ever starts producing other paths,
the first test fails and the rest should be revisited rather than patched.
"""

from __future__ import annotations

import pytest

from thomas.agent.loop_core import AgentLoop
from thomas.agent.routing import PATH_MODEL_OWNED, IntentRouter


class _Route:
    def __init__(self, path: str) -> None:
        self.path = path


class _Loop:
    """Only the attributes the two helpers read.

    `_context_window` was added when the history budget stopped being a constant and
    became a fraction of the model's real window; a stub without it now raises.
    """

    _context_preserve_mode = "normal"
    _context_window = 200_000


def _caps(path: str) -> tuple[int, int]:
    loop = _Loop()
    tokens = AgentLoop._history_token_cap.__get__(loop, _Loop)(_Route(path))
    messages = AgentLoop._history_preserve_counts.__get__(loop, _Loop)(_Route(path))[1]
    return tokens, messages


@pytest.mark.parametrize(
    "text",
    [
        "build me a dashboard with three files",
        "hey",
        "why is the test failing in module four",
    ],
)
def test_every_turn_routes_to_model_owned(text: str) -> None:
    """The premise. The budget fix only makes sense while this holds."""

    assert IntentRouter().decide(text).path == PATH_MODEL_OWNED


def test_a_real_turn_gets_a_real_history_budget() -> None:
    tokens, messages = _caps(PATH_MODEL_OWNED)

    assert tokens >= 5200, (
        f"every conversation is running on {tokens} tokens of history -- the small-talk "
        "allowance is back, and a coding session will forget what it was told"
    )
    assert messages >= 12, f"only {messages} messages of history preserved on every turn"


def test_the_small_talk_allowance_still_exists_for_small_talk() -> None:
    """Widening every turn must not mean the cheap path was simply deleted."""

    assert _caps("casual_chat") == (2200, 10)
    assert _caps("personal_context") == (2200, 10)


def test_model_owned_is_no_longer_cheaper_than_a_coding_task() -> None:
    """The comparison that made this a bug: the universal path was the poorest."""

    assert _caps(PATH_MODEL_OWNED)[0] >= _caps("coding_task")[0]
    assert _caps(PATH_MODEL_OWNED)[0] > _caps("casual_chat")[0]
