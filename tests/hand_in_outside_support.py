"""A throwaway checkout and clone for the hand-in command's tests. Everything lives under the folder it is given."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    done = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=T", "-c", "user.email=t@example.test", *args],
        cwd=repo, env=env, capture_output=True, check=False,
    )  # fmt: skip
    if done.returncode:
        raise AssertionError(done.stderr.decode("utf-8", "replace"))
    return done.stdout.decode("utf-8", "replace").strip()


def write(repo: Path, name: str, text: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))  # bytes: the file keeps its LF on Windows


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@dataclass
class Repos:
    checkout: Path
    clone: Path
    base: str
    plain: str  # tip after two ordinary commits
    guarded: str  # tip after a third commit that edits agent_safety.toml


def make_repos(root: Path) -> Repos:
    checkout, clone = root / "checkout", root / "clone"
    checkout.mkdir(parents=True)
    git(checkout, "init", "-q", "-b", "dev")
    write(checkout, "agent_safety.toml", '[protected]\npolicy_files = ["AGENTS.md"]\n')
    write(checkout, "pkg/__init__.py", "")
    write(checkout, "pyproject.toml", '[tool.ruff]\nsrc = ["lib"]\n[tool.ruff.lint]\nselect = ["E", "F", "I"]\n')
    write(checkout, "pkg/tool.py", "VALUE = 1\n")
    base = commit(checkout, "base")
    git(root, "clone", "-q", str(checkout), str(clone))
    git(clone, "checkout", "-q", "-b", "work")
    write(clone, "pkg/tool.py", "VALUE = 2\n\n\ndef answer() -> int:\n    return VALUE\n")
    commit(clone, "feat: tool answers\n\nA body line.")
    write(clone, "pkg/other.py", 'NAME = "other"\n')
    plain = commit(clone, "feat: another module")
    write(clone, "agent_safety.toml", '[protected]\npolicy_files = ["AGENTS.md", "X.md"]\n')
    guarded = commit(clone, "chore: widen the protected list")
    return Repos(checkout, clone, base, plain, guarded)
