"""The voice choices, saved in one small file under the data folder.

``engine`` is who speaks: ``auto`` uses Voice Studio when it is running and the browser's own voice otherwise,
``voicestudio`` and ``browser`` always use that one. ``voice`` is the voice's name for that engine, and the saved default,
``default``, means the engine's own first voice. ``fast_model`` is ``auto`` (the smallest and fastest model you have
set up) or ``<profile>|<model id>``. ``studio_url`` is where Voice Studio listens on this computer. ``ears`` is the
listening model Thomas runs himself, ``default`` or an id listed in voice_ears_models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from thomas.core.atomic_json import write_json_atomic
from thomas.server import voice_ears_models
from thomas.server.voice_studio import DEFAULT_URL, local_url

ENGINES = ("auto", "voicestudio", "browser")
DEFAULTS: dict[str, str] = {
    "engine": "auto",
    "voice": "default",
    "fast_model": "auto",
    "studio_url": DEFAULT_URL,
    "ears": "default",
}
_MAX = {"voice": 200, "fast_model": 300}


def load(path: Path) -> dict[str, str]:
    """The saved choices with every missing or unusable one replaced by its default."""
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    found = dict(DEFAULTS)
    if isinstance(saved, dict):
        for key in DEFAULTS:
            try:
                found[key] = _clean(key, saved[key]) if key in saved else DEFAULTS[key]
            except ValueError:
                pass
    return found


def update(path: Path, changes: dict[str, Any]) -> dict[str, str]:
    """Save the named choices and return all of them. A choice that cannot be used raises ``ValueError``."""
    unknown = sorted(set(changes) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"Unknown voice setting: {unknown[0]}")
    now = load(path)
    for key, value in changes.items():
        now[key] = _clean(key, value)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, now)
    return now


def _clean(key: str, value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if key == "engine":
        if text not in ENGINES:
            raise ValueError("engine must be auto, voicestudio or browser")
        return text
    if key == "studio_url":
        address = local_url(text)
        if address is None:
            raise ValueError("studio_url must be an http address on this computer")
        return address
    if key == "ears":
        voice_ears_models.get(text)  # raises ValueError for a model Thomas does not list
        return text or DEFAULTS[key]
    if key == "fast_model" and text != "auto" and "|" not in text:
        raise ValueError("fast_model must be auto or profile|model")
    if len(text) > _MAX[key]:
        raise ValueError(f"{key} is too long")
    return text or DEFAULTS[key]
