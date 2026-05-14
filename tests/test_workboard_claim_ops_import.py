from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Use this section to announce active ownership and prevent conflicting edits.\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            "- none\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            "- none\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_workboard_claim_ops_top_level_import_supports_claim(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    mod = _load_module("workboard_claim_ops_fallback", ROOT / "scripts" / "crew" / "workboard" / "claim_ops.py")
    monkeypatch.setattr(mod, "_presence_gate", lambda **_: (True, ""))
    monkeypatch.setattr(mod, "_scope_guard_supported", lambda _: False)

    workboard = _write_workboard(tmp_path)
    ok, message = mod.claim(
        workboard,
        agent="Codex Script",
        scope="scripts/crew/workboard/claim_ops.py",
        task="script import claim",
    )
    text = workboard.read_text(encoding="utf-8")

    assert ok is True
    assert "claimed scope `scripts/crew/workboard/claim_ops.py`" in message
    assert "agent=Codex Script;" in text
    assert "summary=script import claim; status=active" in text
