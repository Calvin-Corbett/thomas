from __future__ import annotations

import json
from pathlib import Path

import scripts.check_plan_structure_gate as mod


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_required_structure(root: Path) -> None:
    _write(root / "docs" / "REPO_STRUCTURE_PROTOCOL.md", "# protocol\n")
    _write(root / "plans" / "README.md", "# plans\n")
    _write(root / "plans" / "thomas" / "README.md", "# thomas plans\n")
    _write(root / "plans" / "thomas" / "WORKBOARD.md", "# workboard\n")
    for rel in mod.LEGACY_POINTER_FILES:
        pointer = "# Pointer\n\n" "Canonical location:\n" "- `plans/thomas/README.md`\n"
        _write(root / rel, pointer)


def test_generated_task_plan_docs_are_exempt_from_reference_coverage(monkeypatch, tmp_path: Path) -> None:
    _seed_required_structure(tmp_path)
    _write(tmp_path / "plans" / "thomas" / "tasks" / "task-a" / "PLAN.md", "# plan\n")
    _write(tmp_path / "plans" / "thomas" / "swarm" / "swarm-a" / "lanes" / "codex-1.md", "# lane\n")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    violations = mod.evaluate()
    assert not any("plan missing from workboard references" in v for v in violations)
    assert not any("plan missing from plans/thomas/README.md references" in v for v in violations)


def test_non_generated_plan_docs_still_require_workboard_and_hub_refs(monkeypatch, tmp_path: Path) -> None:
    _seed_required_structure(tmp_path)
    _write(tmp_path / "plans" / "thomas" / "launch" / "LAUNCH_V2_PLAN.md", "# launch plan\n")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    violations = mod.evaluate()

    assert "plan missing from workboard references: plans/thomas/launch/LAUNCH_V2_PLAN.md" in violations
    assert "plan missing from plans/thomas/README.md references: plans/thomas/launch/LAUNCH_V2_PLAN.md" in violations


def test_template_plan_refs_are_not_flagged_as_stale(monkeypatch, tmp_path: Path) -> None:
    _seed_required_structure(tmp_path)
    _write(
        tmp_path / "plans" / "thomas" / "WORKBOARD.md",
        "# workboard\n\n`plans/thomas/tasks/<task_id>/PLAN.md`\n`plans/thomas/missing.md`\n",
    )
    _write(
        tmp_path / "plans" / "thomas" / "README.md",
        "# thomas plans\n\n`plans/thomas/tasks/<task_id>/PLAN.md`\n",
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    violations = mod.evaluate()

    assert "stale plan reference to missing file: plans/thomas/missing.md" in violations
    assert not any("<task_id>" in v for v in violations)


def test_run_json_pass_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    _seed_required_structure(tmp_path)
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    rc = mod.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "plan_structure"
    assert payload["violation_count"] == 0
    assert payload["violations"] == []


def test_run_json_fail_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    rc = mod.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "plan_structure"
    assert payload["violation_count"] >= 1
    assert any("missing required structure file" in item for item in payload["violations"])
