"""Runtime registry for browser workflow profiles."""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

PKG = __name__.rsplit('.', 1)[0]

def _iter_modules() -> list[str]:
    import thomas.browser.workflows as pkg
    names: list[str] = []
    for item in pkgutil.iter_modules(pkg.__path__):
        if item.name.startswith('workflow_profile_'):
            names.append(item.name)
    names.sort()
    return names

def list_workflow_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for mod_name in _iter_modules():
        mod = importlib.import_module(f'{PKG}.{mod_name}')
        getter = getattr(mod, 'get_profile', None)
        if callable(getter):
            row = getter()
            if isinstance(row, dict):
                profiles.append(dict(row))
    profiles.sort(key=lambda x: str(x.get('profile_id') or ''))
    return profiles

def get_workflow_profile(profile_id: str) -> dict[str, Any] | None:
    needle = str(profile_id or '').strip()
    if not needle:
        return None
    for row in list_workflow_profiles():
        if str(row.get('profile_id') or '') == needle:
            return row
    return None
