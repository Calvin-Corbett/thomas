from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "thomas", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_generated_browser_workflow_assets_do_not_return() -> None:
    assert not (ROOT / "scripts" / "generate_gap_assets.py").exists()
    assert not (ROOT / "thomas" / "browser" / "workflow_runtime.py").exists()
    assert not (ROOT / "thomas" / "browser" / "workflows" / "registry.py").exists()
    assert not list((ROOT / "thomas" / "browser" / "workflows").glob("workflow_profile_*.py"))
    assert not list((ROOT / "thomas" / "browser" / "workflow_corpus").glob("case_*.json"))
    assert not list((ROOT / "tests" / "browser_workflow_corpus").glob("case_*.json"))


def test_browser_cli_does_not_advertise_generated_workflows() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "thomas", "browser", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    commands = {line.strip().split()[0] for line in proc.stdout.splitlines() if line.startswith("  ") and line.strip()}
    assert "workflows" not in commands
    assert "workflow-cases" not in commands
    assert {"open", "smoke", "status"}.issubset(commands)


def test_extension_catalog_command_is_runtime_integrated() -> None:
    payload = _run("plugins", "extension-catalog", "--json")
    catalog = json.loads((ROOT / "extensions" / "catalog.json").read_text(encoding="utf-8-sig"))
    assert int(payload.get("total") or 0) == len(catalog["packs"])
    assert int(payload.get("total") or 0) > 0
    assert int(payload.get("invalid") or 0) == 0
