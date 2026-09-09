# thomas/observability/auto_instrument.py
from __future__ import annotations

import inspect
import types
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from thomas.marketplace.observability.event_recorder import record_event

_INSTALLED = False


def _wrap_async_fn(name: str, fn: Callable[..., Awaitable[Any]]):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        record_event(
            "auto_instrument.call",
            {"target": name, "kind": "async", "args_n": len(args), "kwargs_keys": list(kwargs.keys())},
        )
        try:
            out = await fn(*args, **kwargs)
            record_event("auto_instrument.result", {"target": name, "kind": "async"})
            return out
        except Exception as e:
            record_event("auto_instrument.error", {"target": name, "kind": "async", "error": str(e)})
            raise

    return wrapped


def _wrap_sync_fn(name: str, fn: Callable[..., Any]):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        record_event(
            "auto_instrument.call",
            {"target": name, "kind": "sync", "args_n": len(args), "kwargs_keys": list(kwargs.keys())},
        )
        try:
            out = fn(*args, **kwargs)
            record_event("auto_instrument.result", {"target": name, "kind": "sync"})
            return out
        except Exception as e:
            record_event("auto_instrument.error", {"target": name, "kind": "sync", "error": str(e)})
            raise

    return wrapped


def _wrap_async_gen(name: str, agen_fn: Callable[..., Any]):
    @wraps(agen_fn)
    async def wrapped(*args, **kwargs):
        record_event("auto_instrument.call", {"target": name, "kind": "async_gen"})
        agen = agen_fn(*args, **kwargs)
        i = 0
        try:
            async for chunk in agen:
                # "model.chunk" heuristic: if it's bytes/str/dict
                record_event("model.chunk", {"target": name, "i": i, "chunk": chunk})
                i += 1
                yield chunk
            record_event("auto_instrument.result", {"target": name, "kind": "async_gen", "chunks": i})
        except Exception as e:
            record_event("auto_instrument.error", {"target": name, "kind": "async_gen", "error": str(e), "chunks": i})
            raise

    return wrapped


def _wrap_sync_gen(name: str, gen_fn: Callable[..., Any]):
    @wraps(gen_fn)
    def wrapped(*args, **kwargs):
        record_event("auto_instrument.call", {"target": name, "kind": "sync_gen"})
        gen = gen_fn(*args, **kwargs)
        i = 0
        try:
            for chunk in gen:
                record_event("model.chunk", {"target": name, "i": i, "chunk": chunk})
                i += 1
                yield chunk
            record_event("auto_instrument.result", {"target": name, "kind": "sync_gen", "chunks": i})
        except Exception as e:
            record_event("auto_instrument.error", {"target": name, "kind": "sync_gen", "error": str(e), "chunks": i})
            raise

    return wrapped


def _maybe_wrap_callable(mod: types.ModuleType, attr_name: str):
    obj = getattr(mod, attr_name, None)
    if not callable(obj):
        return False
    qual = f"{mod.__name__}.{attr_name}"

    # Avoid double-wrap
    if getattr(obj, "__thomas_instrumented__", False):
        return False

    try:
        if inspect.isasyncgenfunction(obj):
            w = _wrap_async_gen(qual, obj)
        elif inspect.iscoroutinefunction(obj):
            w = _wrap_async_fn(qual, obj)
        elif inspect.isgeneratorfunction(obj):
            w = _wrap_sync_gen(qual, obj)
        else:
            w = _wrap_sync_fn(qual, obj)
        w.__thomas_instrumented__ = True
        setattr(mod, attr_name, w)
        return True
    except AttributeError:
        return False


def ensure_installed() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Best-effort: wrap "likely" entrypoints without assuming exact structure.
    candidates = [
        "thomas.llm",
        "thomas.model",
        "thomas.models",
        "thomas.openai_client",
        "thomas.tools",
        "thomas.tool_runner",
        "thomas.cortex",
        "thomas.agent",
    ]
    wrapped = 0
    for mod_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except ImportError:
            continue

        for attr in dir(mod):
            low = attr.lower()
            if low in {"__", "main"}:
                continue
            # Heuristics: likely model/tool entrypoints
            if any(
                k in low for k in ("tool", "call", "execute", "run", "stream", "chat", "complete", "generate", "infer")
            ):
                if _maybe_wrap_callable(mod, attr):
                    wrapped += 1

    record_event("auto_instrument.status", {"installed": True, "wrapped": wrapped})
    _INSTALLED = True
