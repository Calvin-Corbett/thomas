from __future__ import annotations

from pathlib import Path

import thomas.demo.project_swarm_runtime as mod


def test_claim_scope_does_not_force_presence_override(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_claim(workboard, **kwargs):  # noqa: ANN001
        captured["workboard"] = workboard
        captured.update(kwargs)
        return True, {}

    monkeypatch.setattr(mod, "claim", _fake_claim)

    mod.claim_scope(
        tmp_path / "WORKBOARD.md",
        agent="lane-01",
        scope="src/app.js",
        task="build production mode",
        role="worker",
        parent="planner",
    )

    assert captured["agent"] == "lane-01"
    assert captured["scope"] == "src/app.js"
    assert captured["task"] == "build production mode"
    assert "allow_presence_override" not in captured
    assert "presence_override_reason" not in captured


def test_release_scope_does_not_force_dirty_or_presence_bypass(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_release(workboard, **kwargs):  # noqa: ANN001
        captured["workboard"] = workboard
        captured.update(kwargs)
        return True, {}

    monkeypatch.setattr(mod, "release", _fake_release)

    mod.release_scope(tmp_path / "WORKBOARD.md", agent="lane-01")

    assert captured["agent"] == "lane-01"
    assert "allow_dirty" not in captured
    assert "dirty_reason" not in captured
    assert "allow_presence_override" not in captured
    assert "presence_override_reason" not in captured
