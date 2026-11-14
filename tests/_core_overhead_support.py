"""What the core overhead guard tests share: a throwaway repository, a fake promoter ledger and the helpers."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "forge" / "gates" / "core_overhead_guard.py"
LOOP = "thomas/agent/loop.py"
OTHER = "thomas/agent/other.py"
SID = "self-thomas-0123456789ab"
GATE = "owner-approved/windows-sign-in"


def promoter(sid: str = SID) -> str:
    return (
        "self-fix\n\nA body paragraph.\n\nThomas-Submitted-By: thomas\nThomas-Committed-By: self-change-promoter\n"
        f"Thomas-Submission-Id: {sid}\nThomas-Gated: {GATE}\n"
    )


def load():
    spec = importlib.util.spec_from_file_location("core_overhead_guard_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)
    return done.stdout.strip()


def make_repo(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "docs").mkdir()
    (work / "docs" / "core_overhead_manifest.json").write_text(json.dumps({"protected_files": [LOOP]}))
    (work / "thomas" / "agent").mkdir(parents=True)
    (work / LOOP).write_text("a\n")
    (work / OTHER).write_text("a\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    for key in (
        "THOMAS_CORE_OVERHEAD_UNLOCK",
        "THOMAS_AGENT_ROLE",
        "PRE_COMMIT_FROM_REF",
        "PRE_COMMIT_TO_REF",
        "PRE_COMMIT_REMOTE_NAME",
        "PRE_COMMIT_REMOTE_URL",
        "PRE_COMMIT_HOOK_STAGE",
        "THOMAS_PROMOTER_LEDGER",
    ):
        monkeypatch.delenv(key, raising=False)
    return work


def make_ledger(tmp_path):
    (tmp_path / "ledger" / "outbox").mkdir(parents=True)
    return tmp_path / "ledger"


def record(ledger: Path, sha: str, sid: str = SID, status: str = "landed") -> None:
    body = {"id": sid, "submission_id": sid, "status": status, "commit_sha": sha}
    (ledger / "outbox" / f"{sid}.verdict.json").write_text(json.dumps(body))


def edit(repo: Path, message: str, n: object, path: str = LOOP) -> str:
    (repo / path).write_text(f"{n}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def tip(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def guard(repo, ledger, *extra, files=(LOOP,)):
    mod = load()
    mod.ROOT = repo
    manifest = str(repo / "docs" / "core_overhead_manifest.json")
    return mod.run(["--manifest", manifest, "--ledger", str(ledger), *extra, *files])


def push(repo, ledger, monkeypatch, capsys, base, head, files=(LOOP,)):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head)
    code = guard(repo, ledger, "--push", files=files)
    return code, capsys.readouterr().out
