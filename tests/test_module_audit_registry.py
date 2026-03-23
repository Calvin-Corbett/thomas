from __future__ import annotations

from pathlib import Path

from thomas.marketplace.observability.module_audit import (
    build_file_hashes,
    load_registry,
    module_for_path,
    record_audit,
    sha256_file,
    touched_modules,
)


def test_module_for_path_maps_major_module() -> None:
    assert module_for_path("thomas/agent/loop.py") == "agent"
    assert module_for_path("thomas/server/app.py") == "server"
    assert module_for_path("README.md") is None
    assert module_for_path("thomas/unknown/new.py") is None


def test_touched_modules_collects_unique_module_names() -> None:
    mods = touched_modules(
        [
            "thomas/agent/loop.py",
            "thomas/agent/routing.py",
            "thomas/server/app.py",
            "docs/anything.md",
        ]
    )
    assert mods == {"agent", "server"}


def test_record_audit_updates_latest_and_chains_signature(tmp_path: Path) -> None:
    registry_path = tmp_path / "module_audit_log.json"
    file_path = tmp_path / "thomas" / "agent" / "loop.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('ok')\n", encoding="utf-8")
    relative = "thomas/agent/loop.py"
    hashes = build_file_hashes(tmp_path, [relative])

    first = record_audit(
        registry_path=registry_path,
        module="agent",
        auditor="doctor-bot",
        status="warn",
        summary="Initial pass",
        files_touched=[relative],
        file_hashes=hashes,
        issues=["loop size exceeds threshold"],
        signing_key="secret-key",
    )
    second = record_audit(
        registry_path=registry_path,
        module="agent",
        auditor="doctor-bot",
        status="pass",
        summary="Follow-up pass",
        files_touched=[relative],
        file_hashes=hashes,
        issues=[],
        signing_key="secret-key",
    )

    assert first["signature"]
    assert second["signature"]
    assert second["prev_signature"] == first["signature"]
    assert second["signature"] != first["signature"]

    registry = load_registry(registry_path)
    latest = registry["latest_by_module"]["agent"]
    assert latest["status"] == "pass"
    assert latest["signature"] == second["signature"]
    assert latest["files_touched"] == [relative]
    assert latest["file_hashes"][relative] == sha256_file(file_path)
    assert latest["issues"] == []
    assert len(registry["history"]) == 2
