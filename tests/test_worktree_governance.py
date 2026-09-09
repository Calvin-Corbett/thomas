"""Tests for the worktree-sprawl prevention system.

Covers the three pillars:
  * ledger ``update`` produces a correct row set for a fixture repo with N
    worktrees (and writes both artifacts);
  * the creation gate blocks at the dirty ceiling and on a keyword collision;
  * the detector flags an over-ceiling repo.

The fixtures build *real* git repositories with real worktrees, so the tests
exercise the actual ``git worktree list --porcelain`` parsing path. They skip
cleanly when git is unavailable.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.crew import worktree_debt, worktree_ledger  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _load_gate():
    """Load the creation gate by path (it lives under scripts/forge/gates)."""
    path = REPO_ROOT / "scripts" / "forge" / "gates" / "worktree_creation_gate.py"
    spec = importlib.util.spec_from_file_location("worktree_creation_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* exec_module: the gate uses
    # `from __future__ import annotations`, so its @dataclass fields are string
    # annotations that dataclasses resolves via `sys.modules.get(cls.__module__)`.
    # Without this registration that lookup returns None and class creation
    # crashes. This is the documented importlib loading idiom.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── git fixture helpers ────────────────────────────────────────────────────────


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    base_env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    if env:
        base_env.update(env)
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env={**os.environ, **base_env},
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "seed")
    return path


def _add_worktree(main: Path, wt_path: Path, branch: str) -> Path:
    _git(main, "worktree", "add", "-b", branch, str(wt_path))
    return wt_path


def _make_dirty(wt_path: Path) -> None:
    (wt_path / "scratch.txt").write_text("uncommitted work\n", encoding="utf-8")


def _commit_old(wt_path: Path, days: int) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    (wt_path / "old.txt").write_text("old\n", encoding="utf-8")
    _git(wt_path, "add", "old.txt")
    _git(wt_path, "commit", "-m", "old work", env={"GIT_AUTHOR_DATE": old, "GIT_COMMITTER_DATE": old})


def _write_governance(root: Path, *, max_dirty: int) -> None:
    (root / "agent_safety.toml").write_text(
        f"[worktree_governance]\nmax_dirty_worktrees = {max_dirty}\nstale_days = 7\n",
        encoding="utf-8",
    )


# ── 1. Ledger ──────────────────────────────────────────────────────────────────


def test_ledger_update_produces_correct_rows(tmp_path):
    main = _init_repo(tmp_path / "repo")
    dirty_wt = _add_worktree(main, tmp_path / "wt-alpha", "feat/alpha")
    _make_dirty(dirty_wt)
    stale_wt = _add_worktree(main, tmp_path / "wt-beta", "feat/beta")
    _commit_old(stale_wt, days=30)

    ledger = worktree_ledger.update(main)

    assert ledger.total == 3
    assert ledger.dirty_count == 1
    assert ledger.stale_count == 1

    branches = {row.branch for row in ledger.rows}
    assert {"feat/alpha", "feat/beta"} <= branches

    alpha = next(row for row in ledger.rows if row.branch == "feat/alpha")
    assert alpha.dirty is True
    assert alpha.uncommitted_count >= 1
    assert alpha.purpose == "alpha"  # type prefix stripped

    beta = next(row for row in ledger.rows if row.branch == "feat/beta")
    assert beta.stale is True
    assert beta.dirty is False

    md_path, json_path = worktree_ledger.ledger_paths(ledger)
    assert md_path.exists()
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 3
    assert data["summary"]["dirty"] == 1
    assert len(data["worktrees"]) == 3


def test_ledger_default_safe_single_checkout(tmp_path):
    main = _init_repo(tmp_path / "solo")
    ledger = worktree_ledger.collect(main)
    assert ledger.total == 1
    assert ledger.dirty_count == 0
    assert ledger.over_ceiling is False
    assert "clean" in worktree_ledger.summary_line(ledger)


def test_missing_worktree_path_degrades_to_noted_row(tmp_path):
    main = _init_repo(tmp_path / "repo")
    gone = _add_worktree(main, tmp_path / "wt-gone", "feat/gone")
    shutil.rmtree(gone)

    ledger = worktree_ledger.collect(main)  # must not raise
    gone_row = next(row for row in ledger.rows if row.branch == "feat/gone")
    assert gone_row.exists is False
    assert gone_row.note  # carries a human note instead of crashing


# ── 2. Creation gate ───────────────────────────────────────────────────────────


def test_creation_gate_blocks_at_ceiling(tmp_path):
    main = _init_repo(tmp_path / "repo")
    _write_governance(main, max_dirty=1)
    dirty_wt = _add_worktree(main, tmp_path / "wt-one", "feat/one")
    _make_dirty(dirty_wt)

    gate = _load_gate()
    decision = gate.evaluate_creation(main, "brand-new-thing")
    assert decision.allowed is False
    assert any("ceiling" in reason.lower() for reason in decision.blocked_reasons)


def test_creation_gate_blocks_on_keyword_collision(tmp_path):
    main = _init_repo(tmp_path / "repo")
    _add_worktree(main, tmp_path / "wt-pay", "feat/payment")

    gate = _load_gate()
    blocked = gate.evaluate_creation(main, "payment-retry")
    assert blocked.allowed is False
    assert blocked.collisions

    # --force with a reason overrides the collision.
    forced = gate.evaluate_creation(main, "payment-retry", force=True, reason="parallel spike approved")
    assert forced.allowed is True
    assert forced.warnings


def test_creation_gate_passes_when_clean(tmp_path):
    main = _init_repo(tmp_path / "repo")
    gate = _load_gate()
    decision = gate.evaluate_creation(main, "fresh-feature")
    assert decision.allowed is True
    assert not decision.blocked_reasons


# ── 3. Detector ────────────────────────────────────────────────────────────────


def test_detector_flags_over_ceiling(tmp_path):
    main = _init_repo(tmp_path / "repo")
    _write_governance(main, max_dirty=1)
    dirty_wt = _add_worktree(main, tmp_path / "wt-one", "feat/one")
    _make_dirty(dirty_wt)

    report = worktree_debt.assess_debt(main)
    assert report.over_ceiling is True
    assert report.dirty_count >= 1
    assert "MERGE DEBT" in worktree_debt.render_report(report)
    assert worktree_debt.run(["--root", str(main)]) == 1


def test_detector_quiet_when_clean(tmp_path):
    main = _init_repo(tmp_path / "repo")
    report = worktree_debt.assess_debt(main)
    assert report.over_ceiling is False
    assert worktree_debt.run(["--root", str(main)]) == 0
