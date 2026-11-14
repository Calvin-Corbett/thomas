"""Enforcement integrity must compare a script and its manifest from the same tree.

`--check-staged` hashes every protected script from the index, and it used to read
the manifest those hashes are compared against from the working tree. During a
scoped commit the index is HEAD plus that commit's own files. So when another agent
had an enforcement script staged, with its new hash already written into the
on-disk manifest, the script hashed at HEAD while being compared with its NEW hash.

Measured on 2026-09-10: three such scripts made the native commit tool refuse every
commit in the repository -- including a one-file plan update that touched no gate --
with `SAFETY GATE FAILED: Enforcement Scripts Tampered Or Uncovered`. The committing
agent had tampered with nothing; a peer's honest in-flight work was reported as an
attack on somebody else's commit.

What must NOT change: a tampered script staged beside a stale manifest entry still
fails, and a missing manifest still fails closed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "forge" / "gates"))

import enforcement_integrity as gate  # noqa: E402

SCRIPT = "gates/g.py"
MANIFEST = "gates/manifest.json"


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True, env=env).stdout


def _h(content: str) -> str:
    return hashlib.sha256(gate._normalize(content.encode("utf-8"))).hexdigest()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / "gates").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / SCRIPT).write_text("v1\n", encoding="utf-8")
    (root / MANIFEST).write_text(json.dumps({SCRIPT: _h("v1\n")}), encoding="utf-8")
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "seed")

    monkeypatch.setattr(gate, "ROOT", root)
    monkeypatch.setattr(gate, "MANIFEST_PATH", root / MANIFEST)
    monkeypatch.setattr(gate, "_load_protected_scripts", lambda: [SCRIPT])
    return root


def _stage_peer_gate_change(root: Path, content: str, manifest_hash: str) -> None:
    """A peer stages a gate edit and updates the manifest, both on disk and staged."""
    (root / SCRIPT).write_text(content, encoding="utf-8")
    (root / MANIFEST).write_text(json.dumps({SCRIPT: manifest_hash}), encoding="utf-8")
    _git(root, "add", SCRIPT, MANIFEST)


def _scoped_index(root: Path, tmp_path: Path, *paths: str) -> Path:
    """The temp index a pathspec commit builds: HEAD plus only the committed paths."""
    index = tmp_path / "scoped.index"
    import os

    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    _git(root, "read-tree", "HEAD", env=env)
    for p in paths:
        _git(root, "update-index", "--add", p, env=env)
    return index


def test_an_unrelated_commit_passes_while_a_peer_has_a_gate_staged(repo, tmp_path, monkeypatch):
    """The load-bearing case: the commit touches no gate and must not be refused."""
    _stage_peer_gate_change(repo, "v2\n", _h("v2\n"))
    (repo / "notes.md").write_text("an unrelated change\n", encoding="utf-8")
    monkeypatch.setenv("GIT_INDEX_FILE", str(_scoped_index(repo, tmp_path, "notes.md")))
    assert gate.verify(["--check-staged"]) == 0


def test_the_peer_can_land_its_own_gate_change(repo, tmp_path, monkeypatch):
    """The staged script and its staged manifest entry agree, so the author's commit passes."""
    _stage_peer_gate_change(repo, "v2\n", _h("v2\n"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(_scoped_index(repo, tmp_path, SCRIPT, MANIFEST)))
    assert gate.verify(["--check-staged"]) == 0


def test_a_tampered_staged_script_still_fails(repo, tmp_path, monkeypatch):
    """Protection must not weaken: a rewritten gate beside a stale manifest is caught."""
    _stage_peer_gate_change(repo, "return PASS always\n", _h("v1\n"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(_scoped_index(repo, tmp_path, SCRIPT, MANIFEST)))
    assert gate.verify(["--check-staged"]) == 1


def test_a_missing_manifest_still_fails_closed(repo, monkeypatch):
    (repo / MANIFEST).unlink()
    _git(repo, "rm", "-q", "--cached", MANIFEST)
    assert gate.verify(["--check-staged"]) == 1


OTHER = "gates/other.py"


def test_a_commit_cannot_land_a_key_for_a_script_it_does_not_carry(repo, tmp_path, monkeypatch):
    """Own keys only, enforced by the gate itself - which is what makes the manifest shareable.

    Reading the manifest from the same tree as the scripts has a consequence worth
    pinning: a staged manifest can only move keys for scripts in the same commit. A key
    for any other script is checked against that script's HEAD copy and fails. So no
    agent can land somebody else's pending key by accident, and the manifest needs no
    exclusive claim - the argument claude-perf made for listing it as shared
    infrastructure beside WORKBOARD.md and changelog.d.
    """
    (repo / OTHER).write_text("other v1\n", encoding="utf-8")
    (repo / MANIFEST).write_text(json.dumps({SCRIPT: _h("v1\n"), OTHER: _h("other v1\n")}), encoding="utf-8")
    _git(repo, "add", OTHER, MANIFEST)
    _git(repo, "commit", "-qm", "second protected script")
    monkeypatch.setattr(gate, "_load_protected_scripts", lambda: [SCRIPT, OTHER])

    # A peer's pending change to OTHER sits in the shared manifest beside mine.
    (repo / SCRIPT).write_text("v2\n", encoding="utf-8")
    (repo / OTHER).write_text("other v2\n", encoding="utf-8")
    (repo / MANIFEST).write_text(json.dumps({SCRIPT: _h("v2\n"), OTHER: _h("other v2\n")}), encoding="utf-8")
    _git(repo, "add", SCRIPT, MANIFEST)

    # My commit carries SCRIPT and a manifest that still holds the peer's key for OTHER.
    monkeypatch.setenv("GIT_INDEX_FILE", str(_scoped_index(repo, tmp_path, SCRIPT, MANIFEST)))
    assert gate.verify(["--check-staged"]) == 1, "a key for a script outside the commit must not land"


def test_the_same_commit_passes_once_it_carries_only_its_own_key(repo, tmp_path, monkeypatch):
    """The passing half: stage a manifest that is HEAD plus only my key, and it lands."""
    (repo / OTHER).write_text("other v1\n", encoding="utf-8")
    (repo / MANIFEST).write_text(json.dumps({SCRIPT: _h("v1\n"), OTHER: _h("other v1\n")}), encoding="utf-8")
    _git(repo, "add", OTHER, MANIFEST)
    _git(repo, "commit", "-qm", "second protected script")
    monkeypatch.setattr(gate, "_load_protected_scripts", lambda: [SCRIPT, OTHER])

    (repo / SCRIPT).write_text("v2\n", encoding="utf-8")
    (repo / MANIFEST).write_text(json.dumps({SCRIPT: _h("v2\n"), OTHER: _h("other v1\n")}), encoding="utf-8")
    _git(repo, "add", SCRIPT, MANIFEST)

    monkeypatch.setenv("GIT_INDEX_FILE", str(_scoped_index(repo, tmp_path, SCRIPT, MANIFEST)))
    assert gate.verify(["--check-staged"]) == 0
