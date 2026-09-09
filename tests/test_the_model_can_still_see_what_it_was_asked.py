"""History is a fraction of the real window, and the ask is never the first thing dropped.

Two defects in the same pair of functions:

  * the history budget was a constant — 5,200 tokens, handed to a model with a
    200,000-token window. 2.6% utilisation. A thimble, and the model was asked to
    remember a conversation out of it.
  * `preserve_first` was 0, so the HEAD of the conversation had no protection and the
    user's original request was evicted before the file dumps that arrived after it.
    A run could finish a job whose brief it could no longer read.

The floor matters as much as the ceiling: Thomas supports models with 8k windows, and
a fraction-of-window rule must not shrink those. `_build_messages` fits everything to
the true window afterwards, so this soft cap only needs to stop history crowding out
tools and the response.
"""

from __future__ import annotations

import pytest

from thomas.agent.loop_core import AgentLoop
from thomas.agent.routing import PATH_MODEL_OWNED


class _Route:
    def __init__(self, path: str) -> None:
        self.path = path


class _Loop:
    _context_preserve_mode = "normal"

    def __init__(self, window: int) -> None:
        self._context_window = window


def _cap(window: int, path: str = PATH_MODEL_OWNED) -> int:
    loop = _Loop(window)
    return AgentLoop._history_token_cap.__get__(loop, _Loop)(_Route(path))


def _counts(window: int, path: str = PATH_MODEL_OWNED) -> tuple[int, int]:
    loop = _Loop(window)
    return AgentLoop._history_preserve_counts.__get__(loop, _Loop)(_Route(path))


@pytest.mark.parametrize(("window", "at_least"), [(128_000, 40_000), (200_000, 55_000)])
def test_a_large_window_gets_a_large_history(window: int, at_least: int) -> None:
    assert _cap(window) >= at_least, (
        f"a {window:,}-token model is being handed {_cap(window):,} tokens of history; "
        "the constant is back"
    )


def test_a_small_model_is_not_made_worse(monkeypatch) -> None:
    """The floor. A fraction-of-window rule must not shrink an 8k model."""

    assert _cap(8_192) == 5_200


def test_the_budget_scales_with_the_window() -> None:
    """The property, not a magic number: a bigger model gets more room."""

    assert _cap(200_000) > _cap(32_000) > _cap(8_192) or _cap(32_000) >= _cap(8_192)
    assert _cap(200_000) > _cap(8_192)


def test_history_never_swallows_the_whole_window() -> None:
    """It must leave room for tools and the response on any size of model."""

    for window in (32_000, 128_000, 200_000, 1_000_000):
        assert _cap(window) <= window // 2


def test_the_original_request_is_not_droppable() -> None:
    """preserve_first was 0: the ask was evicted before the file dumps after it."""

    first, last = _counts(200_000)
    assert first >= 1, "the head of the conversation is unprotected; the brief can be dropped"
    assert last >= 12, "recent turns lost protection"


def test_the_small_talk_route_is_untouched() -> None:
    """Widening every turn must not mean the cheap path was quietly rewritten too."""

    assert _cap(200_000, "casual_chat") == 2_200
