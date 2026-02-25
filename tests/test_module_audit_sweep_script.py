from __future__ import annotations

import json
from pathlib import Path

import scripts.module_audit_sweep as mod
from thomas.observability.module_audit import MAJOR_MODULES


def test_module_audit_sweep_records_all_major_modules(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "module_audit_log.json"
    rc = mod.run(
        [
            "--registry",
            str(registry),
            "--auditor",
            "Codex 2",
            "--summary",
            "sweep",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["module_count"] == len(MAJOR_MODULES)

    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    latest = registry_payload["latest_by_module"]
    assert set(latest.keys()) == set(MAJOR_MODULES)
    assert any(len(item.get("issues") or []) > 0 for item in latest.values())
