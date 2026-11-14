"""A correlation tag is an instrument. It does not get to kill the work it measures.

Found live 2026-09-19 by driving the Thomas UI in a browser: a chat task card
("PRAXIS-PROBE-001 split loop execution module") failed twice, and the chat
reported `ValueError at capture_context.py:94`. The delegation runner logged only
`Background worker run raised ValueError` with no traceback, so the logs alone
could not have found it.

Root cause: `loop_execution.py` sets the capture tag at :558 and resets it in a
`finally` at :672, and the code between them `yield`s. An async generator runs in
its CALLER's context, so a background worker that drives `__anext__()` from
different tasks resets a token it did not create, and `ContextVar.reset` raises
"<Token ...> was created in a different Context".

capture_context's own module docstring already states the rule this violated:
"Capture failure is never allowed to break a model call ... every catch is
counted by the caller rather than vanishing silently."
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.core import capture_context as cc


async def _tagged_generator(run_id: str):
    """The loop_execution shape: set, yield across suspensions, reset in finally."""
    token = cc.set_capture_run(run_id)
    try:
        yield "first"
        yield "second"
    finally:
        cc.reset(token)


def test_reset_survives_a_token_from_another_context() -> None:
    """The exact production shape: two steps driven from two different tasks."""

    async def main() -> str | None:
        gen = _tagged_generator("run-cross-context")
        assert await asyncio.create_task(gen.__anext__()) == "first"
        assert await asyncio.create_task(gen.__anext__()) == "second"
        # Before the fix this raised ValueError and killed the whole worker run.
        await asyncio.create_task(gen.aclose())
        return cc.current()

    assert asyncio.run(main()) is None, "the tag must be cleared even when the token is foreign"


def test_a_cross_context_reset_is_counted_not_swallowed() -> None:
    """Silence is the failure mode this repo keeps rediscovering. Count it."""
    before = cc.cross_context_resets()

    async def main() -> None:
        gen = _tagged_generator("run-counted")
        await asyncio.create_task(gen.__anext__())
        await asyncio.create_task(gen.aclose())

    asyncio.run(main())

    assert cc.cross_context_resets() > before


def test_the_ordinary_same_context_reset_still_restores_the_previous_value() -> None:
    """The fix must not turn a correct reset into a blunt clear."""
    outer = cc.set_capture_run("outer-run")
    try:
        inner = cc.set_capture_run("inner-run")
        assert cc.current() == "inner-run"
        cc.reset(inner)

        assert cc.current() == "outer-run", "a same-context reset restores, it does not clear"
    finally:
        cc.reset(outer)


def test_the_tag_is_still_readable_inside_the_generator() -> None:
    """The fix must not cost the correlation the tag exists to provide."""

    async def main() -> list[str | None]:
        seen: list[str | None] = []
        gen = _tagged_generator("run-visible")
        await gen.__anext__()
        seen.append(cc.current())
        await gen.__anext__()
        seen.append(cc.current())
        await gen.aclose()
        return seen

    assert asyncio.run(main()) == ["run-visible", "run-visible"]


@pytest.mark.parametrize("run_id", ["run-a", "run-b"])
def test_reset_never_raises_whatever_the_run(run_id: str) -> None:
    async def main() -> None:
        gen = _tagged_generator(run_id)
        await asyncio.create_task(gen.__anext__())
        await asyncio.create_task(gen.aclose())

    asyncio.run(main())
