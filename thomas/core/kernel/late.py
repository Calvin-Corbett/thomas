"""Named calls: one plugin calls another by a name the kernel holds, so neither imports the other.

A plugin's code may import only the kernel, itself and its declared needs. When it has to reach further at run time, the
plugin that has the function provides it here and the plugin that needs it asks by name (``thomas.core.kernel.seams``
spells the names). That is a dependency turned around, not one hidden: a call nothing provides raises :class:`NotProvided`
naming the seam, the server will not start while one is missing (:func:`require`), and
tests/test_every_named_call_has_one_provider.py holds that each name has exactly one provider.

A provider should look its function up when called (``lambda config: _build_tools(config)``), so a test that patches the
function still reaches the patch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

_provided: dict[str, Callable[..., Any]] = {}


class NotProvided(LookupError):
    """A named call whose provider was never loaded."""


def provide(name: str, function: Callable[..., Any]) -> None:
    _provided[name] = function


def withdraw(name: str) -> None:
    _provided.pop(name, None)


def provided(name: str) -> bool:
    return name in _provided


def require(names: Iterable[str]) -> None:
    """Stop here, naming every call nothing provides: a server must not start with one missing."""
    missing = [name for name in names if name not in _provided]
    if missing:
        raise NotProvided(f"nothing provides {', '.join(missing)}: the plugins that have them were not loaded")


def call(name: str, *args: Any, **kwargs: Any) -> Any:
    function = _provided.get(name)
    if function is None:
        raise NotProvided(f"nothing provides {name!r}: the plugin that has it was not loaded")
    return function(*args, **kwargs)


__all__ = ["NotProvided", "call", "provide", "provided", "require", "withdraw"]
