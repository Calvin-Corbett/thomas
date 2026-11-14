"""Point the worker at a requirement your messages carry instead of repeating it.

Every requirement is kept whole, and the text in front of the worker repeated each one, so your request went out
twice on every model call: once as itself and once in the contract block, and again in the gaps a repair round sends
back. Before cab55497 at most 24 requirements of at most 300 characters were repeated; now any number are, so a
request that fits a small model window once did not fit twice. Your request and your amendments are pinned to every
call (``loop_anchors``). A requirement read from your request counts as carried when the worker sees it whole in one of
those messages: the contract reader, reading that message, yields the same statement again (a sentence, or a listed
need rebuilt as "<lead> <need>."), or the whole request is inside it, as when a reminder is put in front of it. These
forms then say so instead of repeating it: first a requirement over ``LONG_REQUIREMENT_CHARS`` is named by its length
and opening words, the way the launch notice names it; then every carried requirement is folded into one line. A repair
round past its budget sends a carried requirement back by its opening words. Anything else stays whole. Only the
worker's copy changes: the contract items are not touched, so the judge still rules on each requirement whole.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from functools import lru_cache

from thomas.core.acceptance_contract import (
    KIND_REQUIREMENT,
    ContractItem,
    contract_prompt_block,
    remediation_prompt,
    requirement_statements,
)
from thomas.core.acceptance_launch_notice import LONG_REQUIREMENT_CHARS
from thomas.core.acceptance_notes import without_thomas_notes
from thomas.core.tokens import estimate_tokens

_WHERE = "the messages that set the task"  # your request and amendments; never Thomas's own repair messages
_OPENING_CHARS = 60  # a requirement sent back by its opening words, past the repair round's budget
_DETAIL_CHARS = 160  # and the judge's reason for it, cut to this


@lru_cache(maxsize=16)
def _statements(text: str) -> frozenset[str]:
    """The reader's statements for one message. The pinned messages are the same on every call of a run, and reading
    a 300-need list takes about 20 ms, so each is read once."""
    return frozenset(requirement_statements(text))


@lru_cache(maxsize=16)
def _flat(text: str) -> str:
    """Whitespace as the contract reader sees it, with Thomas's notes left out as the reader leaves them out."""
    return " ".join(without_thomas_notes(text).split())


def _carried(items: Sequence[ContractItem], carried: Sequence[str], request: str = "") -> set[int]:
    """Positions of the requirements read from ``request`` that the worker sees whole in a carried message."""
    requirements = [
        index for index, item in enumerate(items) if item.kind == KIND_REQUIREMENT and item.source == "prompt"
    ]
    texts = [str(text) for text in carried if str(text or "").strip()]
    if not requirements or not texts:
        return set()
    found = frozenset().union(*(_statements(text) for text in texts))
    if request.strip() and _flat(request) and any(_flat(request) in _flat(text) for text in texts):
        found |= _statements(
            request
        )  # the whole request is inside a pinned message: all of it is in front of the worker
    return {index for index in requirements if items[index].description in found}


def _long(items: Sequence[ContractItem], positions: set[int]) -> set[int]:
    return {index for index in positions if len(items[index].description) > LONG_REQUIREMENT_CHARS}


def _named(items: Sequence[ContractItem], positions: set[int]) -> list[ContractItem]:
    """Copies of ``items``, each one at ``positions`` named by its length and opening words."""
    return [
        replace(
            item,
            description=f"({len(item.description):,} characters, stated whole in {_WHERE}; judged whole) "
            f'"{item.description[:100]}..."',
        )
        if index in positions
        else item
        for index, item in enumerate(items)
    ]


def _folded(items: Sequence[ContractItem], positions: set[int]) -> list[ContractItem]:
    """``items`` with the requirements at ``positions`` folded into one line where the first of them was."""
    if not positions:
        return list(items)
    count, first = len(positions), min(positions)
    line = ContractItem(
        item_id="req:carried",
        kind=KIND_REQUIREMENT,
        description=f"{count} requirement{'s' if count != 1 else ''} read from the request: each sentence or listed "
        "need in it that asks for something is one item, and each is judged whole.",
    )
    return [line if index == first else item for index, item in enumerate(items) if index not in positions - {first}]


def _gap(item: ContractItem, *, opening: bool) -> str:
    """One gap line: whole, or (``opening``) a carried requirement by its opening words and a shortened reason."""
    detail, text = str(item.detail or "unmet"), item.description
    if opening and len(detail) > _DETAIL_CHARS:
        detail = detail[:_DETAIL_CHARS] + "..."
    shown = f'"{text[:_OPENING_CHARS]}..."' if opening and len(text) > _OPENING_CHARS + 10 else text
    return f"- {shown} (observed: {detail})"


def repair_gaps(
    items: Sequence[ContractItem], carried: Sequence[str], *, request: str = "", budget_tokens: int = 0
) -> str:
    """The gaps a repair round sends back to the worker: each checked item that failed, then the line to finish on.

    A long requirement ``carried`` holds is named. If the whole gaps exceed ``budget_tokens``, carried requirements
    go back by their opening words where they fit, and the rest are counted. A failed item no carried message holds
    always goes back whole, with its reason, even when the available room is exhausted."""
    positions = _carried(items, carried, request)
    gaps = remediation_prompt(_named(items, _long(items, positions))).split("\n", 1)[-1]
    if budget_tokens > 0 and estimate_tokens(gaps) <= budget_tokens:
        return gaps
    finish = gaps.rsplit("\n", 1)[-1]
    unmet = [(index, item) for index, item in enumerate(items) if item.checked and not item.satisfied]
    fixed = [_gap(item, opening=False) for index, item in unmet if index not in positions]
    carried_lines = [_gap(item, opening=True) for index, item in unmet if index in positions]

    def counted(more: int, *, terse: bool = False) -> str:
        if terse:
            return f"{more} more requirements in request" if more != 1 else "1 more requirement in request"
        return (
            f"- and {more} more requirement{'s' if more != 1 else ''} read from the request "
            f"{'was' if more == 1 else 'were'} ruled unmet; each is still judged whole, as the request states it."
        )

    # Check the complete returned string, including separators, summary, and closing instruction.
    # Uncarried failures cannot be shortened: they are not present in any pinned message.
    shown = 0
    for count in range(len(carried_lines), -1, -1):
        lines = [*fixed, *carried_lines[:count]]
        if count < len(carried_lines):
            lines.append(counted(len(carried_lines) - count))
        if estimate_tokens("\n".join([*lines, finish])) <= budget_tokens:
            shown = count
            break
    lines = [*fixed, *carried_lines[:shown]]
    if shown < len(carried_lines):
        lines.append(counted(len(carried_lines) - shown))
    result = "\n".join([*lines, finish])
    if estimate_tokens(result) <= budget_tokens:
        return result
    # Even the counted sentence and closing instruction may not fit. Keep the
    # irreducible failures whole, and count rather than list what the request holds.
    lines = [*fixed]
    if carried_lines:
        count = counted(len(carried_lines), terse=True)
        if not fixed and budget_tokens > 0 and estimate_tokens(count) > budget_tokens:
            count = str(len(carried_lines))
        lines.append(count)
    return "\n".join(lines)


def compact_contract_prompt_blocks(
    items: Sequence[ContractItem], carried: Sequence[str], *, request: str = "", require_finish: bool = False
) -> list[str]:
    """Shorter forms of ``contract_prompt_block(items)``, each repeating less of what ``carried`` holds: the long
    requirements named, then every carried requirement folded into one line. A form no shorter is left out."""
    positions = _carried(items, carried, request)
    forms: list[str] = []
    shortest = contract_prompt_block(items, require_finish=require_finish)
    for shown in (_named(items, _long(items, positions)), _folded(items, positions)):
        block = contract_prompt_block(shown, require_finish=require_finish)
        if len(block) < len(shortest):
            forms.append(block)
            shortest = block
    return forms


__all__ = ["compact_contract_prompt_blocks", "repair_gaps"]
