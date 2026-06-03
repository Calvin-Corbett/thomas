"""Security regressions for the commit-master (Praxis cage finale).

These pin the privilege-separation properties that close the same-user-shell
residual class WITHOUT relying on server-side enforcement:

* sanitized env -> worker bypass vars never reach a gate (B4/B5/R4)
* clean-room rebuild -> only base+patch is built; the worker's dirty tree and
  any local tampering are irrelevant (B1'/B6)
* gates run FROM the clean room -> they inspect the submitted change (each gate
  resolves its repo via __file__, not cwd), not the main repo
* external integrity anchor -> a patch that neuters a clean-room gate is caught
  by a manifest hash the worker cannot write (B3/B7/B13)
* submissions are data -> malformed/forged submissions are rejected, not run;
  self-asserted approval trailers carry no authority (B12/B19)
* append-only audit -> every decision is logged

The tests build a throwaway git repo with a handful of one-line fake gate
scripts COMMITTED at the base, so the security logic is exercised
deterministically, independent of the real 52-gate suite.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts.forge.commit_master import (
    CageLayout,
    CommitMaster,
    GateSpec,
    create_submission,
    sanitize_env,
)

GATE_DIR = "scripts/forge/gates"

_PASS = "import sys; sys.exit(0)\n"
_FAIL = "import sys; sys.exit(1)\n"
# Fails (exit 3) iff GITHUB_ACTIONS leaked into the gate's environment.
_ENV_PROBE = "import os, sys; sys.exit(3 if os.environ.get('GITHUB_ACTIONS') else 0)\n"
# Exits 0 iff the clean room's STAGED diff includes thomas/feature.py — proves
# the gate, run from the clean room, actually inspects the submitted change.
_STAGED_PROBE = (
    "import subprocess, sys\n"
    "out = subprocess.run(['git','diff','--cached','--name-only'], capture_output=True, text=True).stdout\n"
    "sys.exit(0 if 'thomas/feature.py' in out else 5)\n"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-b", "main")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    workboard = repo / "plans" / "thomas" / "WORKBOARD.md"
    workboard.parent.mkdir(parents=True, exist_ok=True)
    workboard.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims\n\n"
            "- none\n\n"
            "## Active Tasks\n\n"
            "- none\n\n"
            "## Issues / Blockers\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    _run(repo, "add", "README.md", "plans/thomas/WORKBOARD.md")
    _run(repo, "commit", "-m", "initial")
    return repo


def _commit_gate(repo: Path, name: str, body: str) -> str:
    """Commit a fake gate at scripts/forge/gates/<name> so the clean room has it.

    Returns the repo-relative path for use in a GateSpec.
    """
    rel = f"{GATE_DIR}/{name}"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _run(repo, "add", rel)
    _run(repo, "commit", "-m", f"add gate {name}")
    return rel


def _write_manifest(tmp_path: Path, entries: dict[str, str]) -> Path:
    """Write a trusted integrity manifest {rel_path: sha256(normalized body)}."""
    manifest = {
        rel: hashlib.sha256(body.replace("\r\n", "\n").encode("utf-8")).hexdigest() for rel, body in entries.items()
    }
    path = tmp_path / "trusted_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _layout(tmp_path: Path) -> CageLayout:
    layout = CageLayout(root=tmp_path / "cage")
    layout.ensure()
    return layout


def _stage_new_file(repo: Path, rel: str, content: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _run(repo, "add", rel)


def _master(repo: Path, layout: CageLayout, gate_rel: str, *, manifest: Path | None = None) -> CommitMaster:
    name = Path(gate_rel).stem
    return CommitMaster(
        repo=repo,
        layout=layout,
        gate_suite=(GateSpec(name, gate_rel),),
        manifest_path=manifest,
        sign=False,
        push=False,
    )


# --------------------------------------------------------------------------- #
# env sanitization
# --------------------------------------------------------------------------- #
def test_sanitize_env_strips_worker_bypass_vars() -> None:
    base = {
        "PATH": "/usr/bin",
        "SYSTEMROOT": "C:/Windows",
        "GITHUB_ACTIONS": "true",
        "CI": "true",
        "AGENT_ID": "Codex Red B",
        "CODEX_AGENT_NAME": "red",
        "THOMAS_SKIP_BREAKGLASS": "1",
        "THOMAS_SKIP_TICKET": "OPS-9999",
        "THOMAS_BULK_COMMIT_GUARD_DISABLE": "1",
        "THOMAS_COMMIT_GROWTH_GUARD_DISABLE": "1",
        "THOMAS_PRAXIS_MARKER_KEY_FILE": "/tmp/evil.key",
        "HOME": "/home/dev",
    }
    out = sanitize_env(base)
    for stripped in (
        "GITHUB_ACTIONS",
        "CI",
        "AGENT_ID",
        "CODEX_AGENT_NAME",
        "THOMAS_SKIP_BREAKGLASS",
        "THOMAS_SKIP_TICKET",
        "THOMAS_BULK_COMMIT_GUARD_DISABLE",
        "THOMAS_COMMIT_GROWTH_GUARD_DISABLE",
        "THOMAS_PRAXIS_MARKER_KEY_FILE",
    ):
        assert stripped not in out, stripped
    assert out["PATH"] == "/usr/bin"
    assert out["SYSTEMROOT"] == "C:/Windows"
    assert out["HOME"] == "/home/dev"
    assert out["THOMAS_COMMIT_MASTER"] == "1"


def test_sanitize_env_strips_any_disable_suffix() -> None:
    out = sanitize_env({"THOMAS_SOME_NEW_GUARD_DISABLE": "1", "KEEP": "yes"})
    assert "THOMAS_SOME_NEW_GUARD_DISABLE" not in out
    assert out["KEEP"] == "yes"


# --------------------------------------------------------------------------- #
# clean change -> commit
# --------------------------------------------------------------------------- #
def test_clean_change_passes_gates_and_commits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_pass.py", _PASS)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="add feature", base=base)

    verdict = _master(repo, layout, gate).run_once()
    assert verdict is not None
    assert verdict.status == "committed", verdict.detail
    assert verdict.commit_sha
    log = _run(repo, "log", verdict.commit_sha, "-1", "--format=%B").stdout
    assert "Thomas-Committed-By: commit-master" in log
    assert "Thomas-Submitted-By: claude" in log


def test_gate_inspects_cleanroom_staged_diff(tmp_path: Path) -> None:
    """A gate run from the clean room sees the SUBMITTED change's staged diff.

    This pins the core correctness fix: gates resolve their repo via __file__,
    so they must run from inside the clean room to inspect the right tree.
    """
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_staged.py", _STAGED_PROBE)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="add feature", base=base)

    verdict = _master(repo, layout, gate).run_once()
    # exit 0 only if the gate saw thomas/feature.py staged in the clean room.
    assert verdict.status == "committed", verdict.detail


def test_clean_room_contains_only_base_plus_patch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_pass.py", _PASS)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="add feature", base=base)
    # Dirty the worker's worktree with an UNRELATED file not in the patch.
    (repo / "thomas").mkdir(exist_ok=True)
    (repo / "thomas" / "sneaky.py").write_text("import os\n", encoding="utf-8")
    _run(repo, "add", "thomas/sneaky.py")

    verdict = _master(repo, layout, gate).run_once()
    assert verdict.status == "committed", verdict.detail
    tree = _run(repo, "ls-tree", "-r", "--name-only", verdict.commit_sha).stdout
    assert "thomas/feature.py" in tree
    assert "sneaky.py" not in tree  # worker's out-of-band dirt never reached the commit


# --------------------------------------------------------------------------- #
# gate failure -> reject
# --------------------------------------------------------------------------- #
def test_failing_gate_rejects_with_no_commit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_fail.py", _FAIL)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="bad change", base=base)

    verdict = _master(repo, layout, gate).run_once()
    assert verdict.status == "rejected"
    assert "g_fail" in verdict.detail
    assert _run(repo, "rev-parse", "HEAD").stdout.strip() == base  # HEAD unmoved


# --------------------------------------------------------------------------- #
# external integrity anchor: a patched/neutered gate has no authority
# --------------------------------------------------------------------------- #
def test_patch_cannot_neuter_a_gate_integrity_anchor(tmp_path: Path) -> None:
    """A patch that rewrites a gate to always-pass is caught by the anchor.

    The master hashes the clean-room gate files against a trusted manifest the
    worker cannot write. Tampering changes the hash -> rejected before the gate
    even runs. Structural close of B3/B7/B12/B19.
    """
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_guard.py", _FAIL)  # base: the gate FAILS
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    manifest = _write_manifest(tmp_path, {gate: _FAIL})  # trusted hash = failing copy

    # Worker stages a patch that REWRITES the gate to pass + adds a file.
    (repo / gate).write_text(_PASS, encoding="utf-8")
    _run(repo, "add", gate)
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="red", message="sneak past guard", base=base)

    verdict = _master(repo, layout, gate, manifest=manifest).run_once()
    assert verdict.status == "rejected", verdict.detail
    assert "tampering" in verdict.detail.lower()


def test_untampered_gate_passes_integrity(tmp_path: Path) -> None:
    """A normal change with the gate untouched passes the integrity anchor."""
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_pass.py", _PASS)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    manifest = _write_manifest(tmp_path, {gate: _PASS})
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="benign", base=base)

    verdict = _master(repo, layout, gate, manifest=manifest).run_once()
    assert verdict.status == "committed", verdict.detail


def test_self_approval_trailer_carries_no_authority(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_fail.py", _FAIL)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "AGENTS.md", "tampered\n")
    create_submission(
        layout=layout,
        repo=repo,
        agent="red",
        message="edit\n\nThomas-Protected-Files-Approved: self-approved by red",
        base=base,
    )
    verdict = _master(repo, layout, gate).run_once()
    assert verdict.status == "rejected"


# --------------------------------------------------------------------------- #
# sanitized env reaches the gate subprocess
# --------------------------------------------------------------------------- #
def test_sanitized_env_reaches_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_env.py", _ENV_PROBE)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")  # poison the master's own env
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="red", message="env probe", base=base)

    verdict = _master(repo, layout, gate).run_once()
    # If GITHUB_ACTIONS had leaked, the probe gate would exit 3 -> rejected.
    assert verdict.status == "committed", verdict.detail


# --------------------------------------------------------------------------- #
# malformed / forged submissions are rejected, never executed
# --------------------------------------------------------------------------- #
def test_malformed_submission_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    bad = layout.inbox / "sub-bad"
    bad.mkdir(parents=True)
    (bad / "submission.json").write_text("{ this is not json", encoding="utf-8")

    master = CommitMaster(repo=repo, layout=layout, sign=False, push=False)
    verdict = master.run_once()
    assert verdict is not None
    assert verdict.status == "rejected"
    assert "malformed" in verdict.detail


def test_unknown_base_is_rejected(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    sub = layout.inbox / "sub-x"
    sub.mkdir(parents=True)
    (sub / "change.patch").write_text("dummy", encoding="utf-8")
    (sub / "submission.json").write_text(
        json.dumps({"id": "sub-x", "agent": "red", "base": "deadbeef" * 5, "patch": "change.patch", "message": "x"}),
        encoding="utf-8",
    )
    master = CommitMaster(repo=repo, layout=layout, sign=False, push=False)
    verdict = master.run_once()
    assert verdict.status == "rejected"
    assert "base commit not found" in verdict.detail


# --------------------------------------------------------------------------- #
# submission helper + append-only audit
# --------------------------------------------------------------------------- #
def test_submit_builds_wellformed_submission(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    sub_dir = create_submission(layout=layout, repo=repo, agent="claude", message="add", base="HEAD")
    manifest = json.loads((sub_dir / "submission.json").read_text(encoding="utf-8"))
    assert manifest["agent"] == "claude"
    assert manifest["patch"] == "change.patch"
    assert len(manifest["base"]) == 40
    assert (sub_dir / "change.patch").read_text(encoding="utf-8").strip()


def test_empty_patch_is_refused(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    with pytest.raises(ValueError):
        create_submission(layout=layout, repo=repo, agent="claude", message="nothing", base="HEAD")


def test_audit_log_is_append_only(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    layout = _layout(tmp_path)
    gate = _commit_gate(repo, "g_pass.py", _PASS)
    base = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _stage_new_file(repo, "thomas/feature.py", "x = 1\n")
    create_submission(layout=layout, repo=repo, agent="claude", message="add", base=base)
    _master(repo, layout, gate).run_once()
    lines = layout.audit_log.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert "submitted" in events
    assert "verdict" in events
    assert all(json.loads(line) for line in lines)
