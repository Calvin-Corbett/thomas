"""``?slim=1`` is for the Build sidebar: the same rows without their settings, and without the day grouping that repeats them."""

from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "thomas" / "server" / "routes" / "evolve_agent_conversation_routes.py"


def test_the_slim_answer_drops_settings_and_days_but_the_full_answer_keeps_them():
    text = SOURCE.read_text(encoding="utf-8")
    slim = text[text.index('if request.query.get("slim") == "1":') :]
    slim = slim[
        : slim.index(
            'return web.json_response(\n            {\n                "ok": True,\n                "conversations": summaries,'
        )
    ]
    assert 'if k != "settings"' in slim and "days" not in slim
    full = text[text.index('"conversations": summaries,') :]
    assert '"days": forge_code_store.group_by_day(summaries)' in full  # every other caller is unchanged
