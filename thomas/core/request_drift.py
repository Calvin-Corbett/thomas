"""Where a model request stopped matching the one before it, in the step log, so prompt caching can be read.

A provider serves from its cache only the longest prefix a request shares with an earlier one. On 2026-11-06 the
token log showed 25% of Build's prompt tokens served from cache, while each call resent about 90% of the call before
it: the cached count sat at one number for a whole run (11,136 tokens on every call of one), so something near the
start changed on every call. Thomas's own message lists, driven offline, only ever grew at the end, and Build runs
keep no copy of what they sent, so this notes, for every request, which part first differs from the last request
with the same cache key: the tools, the instructions, or which input item, and that item's kind before and after.
Hashes are compared in this process and only the verdict is written; no prompt text leaves the request.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any

KEYS_KEPT = 64  # requests remembered, one per cache key: a run and each of its helpers

_lock = threading.Lock()
_last: OrderedDict[str, tuple[str, str, list[str], list[str]]] = OrderedDict()


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def _kind(item: Any) -> str:
    if not isinstance(item, dict):
        return type(item).__name__
    return str(item.get("type") or item.get("role") or "item")[:40]


def compare(key: str, tools: Any, instructions: str, items: list[Any]) -> dict[str, Any]:
    """What changed since the last request with *key*: ``{}`` for the first request of a key, else a verdict.

    ``first_change`` is ``"none"`` when the earlier request is a prefix of this one, the cacheable case.
    """
    tools_hash, instructions_hash = _digest(tools or []), _digest(instructions or "")
    hashes, kinds = [_digest(item) for item in items], [_kind(item) for item in items]
    with _lock:
        before = _last.pop(key, None)
        _last[key] = (tools_hash, instructions_hash, hashes, kinds)
        while len(_last) > KEYS_KEPT:
            _last.popitem(last=False)
    if before is None:
        return {}
    old_tools, old_instructions, old_hashes, old_kinds = before
    verdict: dict[str, Any] = {"items": len(hashes), "items_before": len(old_hashes)}
    if old_tools != tools_hash:
        verdict["first_change"] = "tools"
    elif old_instructions != instructions_hash:
        verdict["first_change"] = "instructions"
    else:
        index = next((i for i, (a, b) in enumerate(zip(old_hashes, hashes)) if a != b), None)
        if index is None and len(hashes) < len(old_hashes):
            index = len(hashes)  # items were taken off the end
        if index is None:
            verdict["first_change"] = "none"
        else:
            verdict["first_change"] = "item"
            verdict["item"] = index
            verdict["was"] = old_kinds[index] if index < len(old_kinds) else "(nothing)"
            verdict["now"] = kinds[index] if index < len(kinds) else "(nothing)"
    return verdict


def note(key: str, tools: Any, instructions: str, items: list[Any], *, model: str = "") -> None:
    """Write :func:`compare`'s verdict to the step log as a ``request`` step. Never raises."""
    if not key:
        return
    try:
        verdict = compare(key, tools, instructions, items)
        if verdict:
            from thomas.core import step_log

            step_log.record("request", key=key[:60], model=model or None, **verdict)
    except (TypeError, ValueError, OSError):
        return


def reset() -> None:
    """Forget every remembered request (tests)."""
    with _lock:
        _last.clear()
