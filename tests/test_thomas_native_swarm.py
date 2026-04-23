from __future__ import annotations

import json
from pathlib import Path

import scripts.thomas_native_swarm as runner

from thomas.demo.native_swarm_product import normalize_payload, render_module


def _workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- none\n\n"
        "## Active Tasks\n\n"
        "- none\n\n"
        "## Issues / Blockers\n\n"
        "- none\n\n"
        "## Up For Grabs\n\n"
        "- none\n\n"
        "## Agent Message Traffic\n\n"
        "- none\n",
        encoding="utf-8",
    )
    return path


def test_mock_native_swarm_writes_scoped_product_and_metrics(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(runner, "_claim", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_release", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_message", lambda *_args, **_kwargs: None)

    rc = runner.run(
        [
            "--run-product-benchmark",
            "--run-id",
            "native-swarm-test",
            "--lanes",
            "3",
            "--max-concurrency",
            "3",
            "--repo-root",
            str(tmp_path),
            "--workboard",
            str(_workboard(tmp_path)),
            "--mock",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    root = Path(payload["root"])

    assert rc == 0
    assert payload["passed"] == 3
    assert payload["failed"] == 0
    assert payload["lines"]["nonblank"] > 0
    assert payload["lines_per_minute"] > 0
    assert (root / "native_swarm_metrics.json").exists()
    assert (root / "benchmark_audit.jsonl").exists()
    assert sorted(path.name for path in (root / "product" / "features").glob("*.mjs")) == [
        "feature-01.mjs",
        "feature-02.mjs",
        "feature-03.mjs",
    ]


def test_native_swarm_claim_does_not_force_presence_override(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_claim(workboard, **kwargs):  # noqa: ANN001
        captured["workboard"] = workboard
        captured.update(kwargs)
        return True, {}

    monkeypatch.setattr(runner, "claim", _fake_claim)

    runner._claim(
        tmp_path / "WORKBOARD.md",
        agent="lane-01",
        scope="src/app.js",
        task="native swarm lane",
        role="worker",
        parent="supervisor",
    )

    assert captured["agent"] == "lane-01"
    assert "allow_presence_override" not in captured
    assert "presence_override_reason" not in captured


def test_native_swarm_release_does_not_force_dirty_or_presence_bypass(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_release(workboard, **kwargs):  # noqa: ANN001
        captured["workboard"] = workboard
        captured.update(kwargs)
        return True, {}

    monkeypatch.setattr(runner, "release", _fake_release)

    runner._release(tmp_path / "WORKBOARD.md", agent="lane-01")

    assert captured["agent"] == "lane-01"
    assert "allow_dirty" not in captured
    assert "dirty_reason" not in captured
    assert "allow_presence_override" not in captured
    assert "presence_override_reason" not in captured


def test_host_renderer_overrides_malicious_identity_fields() -> None:
    payload = normalize_payload(
        7,
        {
            "id": "feature-99",
            "ownerLane": "lane-99",
            "title": "Safe Card",
            "category": "governance",
            "metric": "92%",
            "accent": "not-a-color",
            "problem": "Keep writes scoped.",
            "workflow": ["one", "two", "three"],
            "acceptanceChecks": ["a", "b", "c"],
            "implementationNotes": "identity must be host-owned",
        },
    )
    module_text = render_module(7, payload)

    assert payload["id"] == "feature-07"
    assert payload["ownerLane"] == "lane-07"
    assert payload["accent"] == "#375a7f"
    assert "feature-99" not in module_text
    assert "lane-99" not in module_text
