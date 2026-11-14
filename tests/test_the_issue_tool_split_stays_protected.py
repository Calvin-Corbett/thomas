"""The module the issue tool forwards its Up For Grabs mover to is protected and attested like issue.py.

Proves scripts.crew.workboard.issue and scripts.crew.workboard.issue_up_for_grabs, scripts.forge.gates.protected_files_gate,
scripts.os_protect and scripts.forge.gates.enforcement_integrity: the new file is in agent_safety.toml
[protected].enforcement_scripts (what the protected-files gate and the filesystem lock read) AND in the enforcement
manifest with its real hash, and the check below fails when it is dropped from the toml.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.forge.gates.protected_files_gate as protected_gate
import scripts.os_protect as os_protect
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SPLIT = "scripts/crew/workboard/issue_up_for_grabs.py"
ISSUE = "scripts/crew/workboard/issue.py"


def _listed(toml_text: str) -> list[str]:
    return tomllib.loads(toml_text)["protected"]["enforcement_scripts"]


def _missing_from(toml_text: str, manifest: dict) -> list[str]:
    """Files the manifest attests that agent_safety.toml does not protect."""
    return [path for path in (ISSUE, SPLIT) if path in manifest and path not in _listed(toml_text)]


def test_the_split_module_is_listed_beside_issue_py_in_the_toml() -> None:
    listed = _listed((ROOT / "agent_safety.toml").read_text(encoding="utf-8"))
    assert ISSUE in listed and SPLIT in listed


def test_the_split_module_is_attested_with_its_real_hash() -> None:
    manifest = json.loads((ROOT / "scripts/forge/gates/enforcement_manifest.json").read_text(encoding="utf-8"))
    real = hashlib.sha256((ROOT / SPLIT).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert manifest[SPLIT] == real


def test_the_protected_files_gate_and_the_filesystem_lock_both_cover_it() -> None:
    assert SPLIT in protected_gate.PROTECTED_ENFORCEMENT_SCRIPTS
    locked = {p.relative_to(ROOT).as_posix() for p in os_protect._load_protected_files(ROOT)}
    assert SPLIT in locked


def test_dropping_it_from_the_toml_is_caught() -> None:
    text = (ROOT / "agent_safety.toml").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "scripts/forge/gates/enforcement_manifest.json").read_text(encoding="utf-8"))
    assert _missing_from(text, manifest) == []
    dropped = "\n".join(line for line in text.splitlines() if SPLIT not in line)
    assert _missing_from(dropped, manifest) == [SPLIT]
