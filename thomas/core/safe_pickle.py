from __future__ import annotations

import io
import pickle
from collections.abc import Mapping
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

_DEFAULT_ALLOWED_GLOBALS: dict[tuple[str, str], Any] = {
    ("builtins", "bool"): bool,
    ("builtins", "bytes"): bytes,
    ("builtins", "bytearray"): bytearray,
    ("builtins", "complex"): complex,
    ("builtins", "dict"): dict,
    ("builtins", "float"): float,
    ("builtins", "frozenset"): frozenset,
    ("builtins", "int"): int,
    ("builtins", "list"): list,
    ("builtins", "set"): set,
    ("builtins", "str"): str,
    ("builtins", "tuple"): tuple,
    ("types", "SimpleNamespace"): SimpleNamespace,
    ("datetime", "date"): date,
    ("datetime", "datetime"): datetime,
}


class RestrictedUnpickler(pickle.Unpickler):
    def __init__(self, file_obj: io.BytesIO, *, allowed_globals: Mapping[tuple[str, str], Any] | None = None) -> None:
        super().__init__(file_obj)
        self._allowed_globals = dict(_DEFAULT_ALLOWED_GLOBALS)
        if allowed_globals:
            self._allowed_globals.update(dict(allowed_globals))

    def find_class(self, module: str, name: str) -> Any:
        key = (str(module or ""), str(name or ""))
        if key in self._allowed_globals:
            return self._allowed_globals[key]
        raise pickle.UnpicklingError(f"global '{module}.{name}' is not allowed")


def safe_pickle_loads(data: bytes, *, allowed_globals: Mapping[tuple[str, str], Any] | None = None) -> Any:
    return RestrictedUnpickler(io.BytesIO(data), allowed_globals=allowed_globals).load()
