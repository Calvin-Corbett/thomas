"""A worker bootstrapped in a linked worktree is bound where its commits are checked.

``commit.py`` and the message tool validate a session binding at the coordination
root: the primary checkout of a linked worktree. ``bootstrap_claim.py`` registered
the session in the worktree's own ``runtime/`` instead, so an agent that did
exactly what bootstrap told it (run it, apply the exports it printed) could
claim but could neither ack its mail nor commit from that worktree. Binding it at
the root alone would have moved the split to ``claim.py --claim``, which checked
the binding at the board's own checkout, so the flow claims again on purpose.

The scenario drives the real CLIs as fresh processes from disposable git
checkouts built under ``tmp_path``. The worker's binding comes only from
``bootstrap_claim.py``; nothing here registers it by hand.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._native_coordination_harness import (
    BARRIER_PROBE,
    COORDINATOR,
    WORKER,
    _bare_env,
    _bind,
    _build_checkouts,
    _env_for,
    _git,
    _json,
    _lines,
    _norm,
)

PRESENCE = Path("runtime") / "coordination" / "presence"
CLAIM_TOOL = "scripts/crew/workboard/claim.py"


def _run(checkout: Path, script: str, *args: str, env: dict[str, str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(checkout / script), *args],
        cwd=str(checkout),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _bootstrap_worker(worktree: Path) -> tuple[dict[str, object], dict[str, str]]:
    """Bootstrap the worker in its own worktree the way an agent does, and apply the exports it printed."""
    bare = _bare_env()
    rc, out, err = _run(
        worktree,
        "scripts/crew/brief/bootstrap_claim.py",
        *("--agent", WORKER[0], "--scope", "unit", "--task", "unit work", "--role", "solo"),
        *("--no-auto-dispatch", "--json"),
        env=bare,
    )
    boot = _json(out)
    assert rc == 0 and boot["ok"] is True, out + err
    worker_env = {**bare, **dict(re.findall(r'\$env:([A-Z_]+)="([^"]*)"', str(boot["powershell_export"])))}
    assert worker_env["THOMAS_AGENT_SESSION_ID"] == boot["session_id"] and worker_env["THOMAS_AGENT_ID"] == WORKER[0]
    return boot, worker_env


@pytest.mark.timeout(600)
def test_a_worker_bootstrapped_in_a_linked_worktree_commits_there_once_its_p0_is_acked(tmp_path: Path) -> None:
    primary, worktree = _build_checkouts(tmp_path)
    canonical_board = (primary / "plans" / "thomas" / "WORKBOARD.md").resolve()
    local_board = (worktree / "plans" / "thomas" / "WORKBOARD.md").resolve()
    _bind(primary, *COORDINATOR)

    # (1) Bootstrap; every later command runs with the exports it printed and nothing else.
    boot, worker_env = _bootstrap_worker(worktree)
    session = str(boot["session_id"])

    # (2) With those exports alone it releases and claims again; the claim lands on the checkout's own board.
    rc, out, err = _run(worktree, CLAIM_TOOL, "--release", env=worker_env)
    assert rc == 0 and f"released claim for `{WORKER[0]}`" in out, out + err
    rc, out, err = _run(worktree, CLAIM_TOOL, "--claim", "--scope", "unit", "--task", str(boot["task"]), env=worker_env)
    assert rc == 0 and f"claimed scope `unit` for agent `{WORKER[0]}`" in out, out + err
    claim_line = f"agent={WORKER[0]};"
    assert claim_line in local_board.read_text(encoding="utf-8")
    assert claim_line not in canonical_board.read_text(encoding="utf-8")

    (worktree / "unit").mkdir()
    (worktree / "unit" / "work.txt").write_text("unit work\n", encoding="utf-8")
    (worktree / "barrier_probe.py").write_text(BARRIER_PROBE, encoding="utf-8")

    # (3) The coordinator sends one addressed P0 blocker from the primary checkout.
    rc, out, _ = _run(
        primary,
        "scripts/crew/workboard/message.py",
        *("--send", "--to-agent", WORKER[0], "--kind", "blocker", "--priority", "p0", "--task-id", "BOOT-1"),
        *("--summary", "stop: wait for my review", "--json"),
        env=_env_for(*COORDINATOR),
    )
    assert rc == 0 and _json(out)["ok"] is True, out
    msg_id = str(_json(out)["message"]["msg_id"])  # type: ignore[index]

    # (4) Blocked while it is unread: the commit stops at its P0 barrier, not at the session check.
    rc, out, err = _run(worktree, "barrier_probe.py", str(worktree), WORKER[0], env=worker_env)
    commit_lines = _lines(out, "commit ")
    assert commit_lines and commit_lines[0].startswith("commit False coordination_p0 |") and msg_id in out, out + err

    # (5) The worker acks with the same exports; (6) the same dry-run commit then goes through.
    rc, out, err = _run(
        worktree, "scripts/crew/workboard/message.py", "--ack", "--msg-id", msg_id, "--json", env=worker_env
    )
    assert rc == 0 and _json(out)["ok"] is True, out + err
    rc, out, err = _run(worktree, "barrier_probe.py", str(worktree), WORKER[0], env=worker_env)
    assert _lines(out, "commit ") == ["commit True None | local scoped commit checks passed (dry-run)"], out + err
    assert _lines(out, "land ") == [f"land {_norm(canonical_board)}"], out

    # One binding, at the root commit.py and the message tool read; none left behind in the worktree.
    assert (primary / PRESENCE / f"{session}.json").exists(), "the session was not bound at the coordination root"
    assert not (worktree / PRESENCE / f"{session}.json").exists(), "a second binding was left in the worktree"


@pytest.mark.timeout(600)
def test_a_takeover_by_a_worktree_agent_is_written_and_audited_together(tmp_path: Path) -> None:
    # The takeover audit checked the taker's binding at the board's own checkout. Once the binding moved to the
    # coordination root, a takeover from a worktree rewrote the board and then failed that check: a handover with
    # no audit line. It must succeed whole, with its own exports, and leave the audit row.
    _primary, worktree = _build_checkouts(tmp_path)
    board = worktree / "plans" / "thomas" / "WORKBOARD.md"
    _boot, worker_env = _bootstrap_worker(worktree)
    rc, out, err = _run(worktree, CLAIM_TOOL, "--release", env=worker_env)
    assert rc == 0, out + err
    holder = "- agent=holder-c3; name=Holder; role=solo; parent=none; scope=hold; task=HOLD-1"
    task = "- task_id=HOLD-1; agent=holder-c3; scope=hold; summary=hold work; status=active"
    text = board.read_text(encoding="utf-8").replace("## Agent Claims\n", f"## Agent Claims\n{holder}\n", 1)
    board.write_text(text.replace("## Active Tasks\n", f"## Active Tasks\n{task}\n", 1), encoding="utf-8")

    rc, out, err = _run(
        worktree,
        CLAIM_TOOL,
        *("--claim", "--scope", "hold", "--task", "HOLD-1", "--allow-scope-takeover"),
        *("--takeover-reason", "holder-c3 handed hold over in this test"),
        *("--allow-presence-override", "--presence-override-reason", "holder-c3 agreed to hand this scope over"),
        env=worker_env,
    )
    assert rc == 0 and f"claimed scope `hold` for agent `{WORKER[0]}`" in out, out + err
    after = board.read_text(encoding="utf-8")
    assert "agent=holder-c3;" not in after and f"agent={WORKER[0]}; name=" in after
    audit = worktree / "runtime" / "coordination" / "workboard_claim_override_audit.jsonl"
    rows = [line for line in audit.read_text(encoding="utf-8").splitlines() if "holder-c3" in line]
    assert len(rows) == 1 and WORKER[0] in rows[0], rows


def test_every_binding_check_resolves_a_linked_worktree_to_the_primary_checkout(tmp_path: Path, monkeypatch) -> None:
    from scripts.crew.brief import bootstrap_claim
    from scripts.crew.workboard import claim, claim_ownership

    primary, worktree = tmp_path / "primary", tmp_path / "worktree"
    primary.mkdir()
    (primary / "README.md").write_text("disposable\n", encoding="utf-8")
    _git(primary, "init", "-q", "-b", "main")
    _git(primary, "add", "-A")
    _git(primary, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "disposable")
    _git(primary, "worktree", "add", "-q", str(worktree), "-b", "w")
    worktree_board, primary_board = (root / "plans" / "thomas" / "WORKBOARD.md" for root in (worktree, primary))
    monkeypatch.setattr(bootstrap_claim, "ROOT", worktree.resolve())
    assert bootstrap_claim._presence_repo_root(worktree_board) == primary.resolve()
    assert claim._binding_repo_root(worktree_board) == primary.resolve()
    assert claim_ownership._binding_root(worktree_board) == primary.resolve()
    # The holder evidence a takeover reads stays with the board's own checkout.
    assert claim_ownership._takeover_repo_root(worktree_board) == worktree.resolve()
    monkeypatch.setattr(bootstrap_claim, "ROOT", primary.resolve())
    assert bootstrap_claim._presence_repo_root(primary_board) == primary.resolve()
    assert claim._binding_repo_root(primary_board) == primary.resolve()
    # A board outside any checkout keeps its old answer: the board's own folder.
    scratch = tmp_path / "scratch" / "WORKBOARD.md"
    assert bootstrap_claim._presence_repo_root(scratch) == scratch.resolve().parent
    assert claim._binding_repo_root(scratch) == claim_ownership._binding_root(scratch) == scratch.resolve().parent
