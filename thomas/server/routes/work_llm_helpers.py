"""Model-client and JSON helpers shared by Work dashboards, chat titles and the UI redesign."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _build_llm(root: Path, profile: str) -> Any | None:
    """Construct an LLMClient (server->core import, guarded)."""
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_slot import models

        cfg = load_config(Path(root) / "thomas.toml")
        model_cfg = cfg.get_model(profile or None)
        return models().open(model_cfg)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        log.warning("Work dashboard: could not build LLM client: %s", exc)
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
