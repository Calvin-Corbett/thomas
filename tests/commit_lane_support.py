"""Shared fixtures for the scoped-commit landing tests: a tiny real repo, a real neighbour, gates that log what they ran."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
# The machine-wide gate slots live in a folder in the temporary directory by default. Tests that land with several workers
# use a folder of their own, so they neither wait on nor hold up the real agents' commits on the same machine.
os.environ.setdefault("THOMAS_COMMIT_GATE_SLOT_DIR", tempfile.mkdtemp(prefix="thomas-test-slots-"))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The commit tool, loaded as its own module so a test can patch its helpers and the landing code (which is handed the
# module as `core`) sees the patch.
mod = _load_module("agent_commit_lane_support", ROOT / "scripts" / "crew" / "brief" / "commit.py")

NEIGHBOUR = r"""
import os, pathlib, subprocess, sys, tempfile
repo, rel, text = sys.argv[1], sys.argv[2], sys.argv[3]
base_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

def git(*args, env=None):
    done = subprocess.run(["git", *args], cwd=repo, env=env or base_env, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(done.stderr)
    return done.stdout.strip()

branch = git("symbolic-ref", "--short", "HEAD")
old = git("rev-parse", "HEAD")
target = pathlib.Path(repo) / rel
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(text)
index_env = dict(base_env, GIT_INDEX_FILE=os.path.join(tempfile.mkdtemp(), "index"))
git("read-tree", "HEAD", env=index_env)
git("add", "--", rel, env=index_env)
tree = git("write-tree", env=index_env)
commit = git("-c", "user.name=N", "-c", "user.email=n@example.invalid", "commit-tree", tree, "-p", old,
             "-m", "neighbour lands " + rel, env=index_env)
git("update-ref", "refs/heads/" + branch, commit, old)
git("reset", "-q", "HEAD", "--", rel)
print(commit)
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def workboard_text(*claims: str) -> str:
    claim_lines = "\n".join(f"- {claim}" for claim in claims) or "- none"
    tasks = []
    for idx, claim in enumerate(claims, start=1):
        scope = claim.split("scope=", 1)[1].split(";", 1)[0]
        agent = claim.split("agent=", 1)[1].split(";", 1)[0]
        task = claim.split("task=", 1)[1]
        tasks.append(f"- task_id=TASK-{idx}; agent={agent}; scope={scope}; summary={task}; status=in_progress")
    return (
        "# Workboard\n\n## Agent Claims\n"
        + claim_lines
        + "\n\n## Active Tasks\n"
        + ("\n".join(tasks) or "- none")
        + "\n\n## Up For Grabs\n- none\n\n## Issues / Blockers\n- none\n"
    )


def init_repo(tmp_path: Path, *, claims: tuple[str, ...]) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    write(repo / "src" / "app.py", 'print("init")\n')
    write(repo / "CHANGELOG.md", "# Changelog\n")
    write(repo / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    write(repo / "thomas" / "__init__.py", '__version__ = "0.1.0"\n')
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    write(board, workboard_text(*claims))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo, board


def program(*lines: str) -> tuple[str, ...]:
    return (PY, "-c", "\n".join(lines))


@dataclass
class Lane:
    repo: Path
    board: Path
    neighbour: Path
    log: Path
    root: Path

    def head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD")

    def subjects(self) -> list[str]:
        return git(self.repo, "log", "--format=%s").splitlines()

    def ran(self) -> list[str]:
        return [line.split("|")[0] for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def bases(self, name: str) -> list[str]:
        rows = self.log.read_text().splitlines() if self.log.exists() else []
        return [row.split("|")[1] for row in rows if row.split("|")[0] == name]

    def logging(self, name: str, *extra: str, code: int = 0) -> tuple[str, ...]:
        return program(
            "import os, pathlib, sys",
            f"open({str(self.log)!r}, 'a').write({name!r} + '|' + os.environ.get('THOMAS_COMMIT_BASE', '-') + chr(10))",
            *extra,
            f"sys.exit({code})",
        )

    def neighbour_lands(self, rel: str = "other/n.txt") -> str:
        done = subprocess.run(
            [PY, str(self.neighbour), str(self.repo), rel, "x"], capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    def lands_a_neighbour(self, times: int = 1, *, fail: bool = False, vary: bool = False) -> list[str]:
        """Lines for a gate that moves the branch tip (a neighbour lands) on its first `times` runs.

        With `fail` it also refuses on each of those runs, in the same words; with `vary` the words change every run."""
        counter = self.root / "mover.count"
        return [
            "import pathlib, subprocess, sys",
            f"c = pathlib.Path({str(counter)!r}); n = int(c.read_text()) if c.exists() else 0; c.write_text(str(n + 1))",
            f"if n < {times}:",
            f"    subprocess.run([sys.executable, {str(self.neighbour)!r}, {str(self.repo)!r}, 'other/n%d.txt' % n, 'x'], check=True, capture_output=True)",
            *([f"    print('spurious refusal' + (' ' + str(n) if {vary} else '')); sys.exit(1)"] if fail else []),
        ]

    def land(self, gates, **kwargs):
        return mod.commit_scoped_changes(
            message="feat: land",
            agent="codex",
            repo_root=self.repo,
            workboard_path=self.board,
            local_gate_commands=gates,
            **kwargs,
        )


def make_lane(tmp_path: Path) -> Lane:
    """A repo whose one agent (codex) claims `src` and has src/app.py changed, plus a neighbour script and a gate log."""
    repo, board = init_repo(
        tmp_path, claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",)
    )
    script = tmp_path / "neighbour.py"
    script.write_text(NEIGHBOUR, encoding="utf-8")
    write(repo / "src" / "app.py", 'print("changed")\n')
    return Lane(repo, board, script, tmp_path / "gates.log", tmp_path)
