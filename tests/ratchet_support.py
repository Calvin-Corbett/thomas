"""Fixture repositories for the ratchet tests: a dev line, and work on refs that is not on it.

Dates matter: the custodian calls a branch ACTIVE when its tip is within three
days of dev's tip, so candidates are dated well before the dev commit every test
makes last (``dev_moves``).

It also holds the stand-ins for everything outside the ratchet: ``FakeCage`` for
the caged runner (a JUnit report per shard, a node run by itself, and every green
it is asked to end), and ``promote``/``verdict`` for the promoter and your card.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from thomas.server import green_handoff
from thomas.server.ratchet.candidates import Candidate
from thomas.tools.cage_shell import CagedResult

OLD = "2026-09-01T12:00:00+00:00"
CAND = "2026-09-05T12:00:00+00:00"
NEW = "2026-09-20T12:00:00+00:00"
_ID = ("-c", "user.email=test@example.invalid", "-c", "user.name=test", "-c", "core.autocrlf=false")


def git(repo: Path, *args: str, when: str = NEW, email: str = "test@example.invalid") -> str:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when, GIT_AUTHOR_EMAIL=email)
    done = subprocess.run(["git", *_ID, *args], cwd=repo, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def commit(
    repo: Path, files: dict[str, str | None], message: str, *, when: str = NEW, email: str = "test@example.invalid"
) -> str:
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, when=when, email=email)
    return git(repo, "rev-parse", "HEAD")


def on_ref(
    repo: Path,
    ref: str,
    start: str,
    files: dict[str, str | None],
    message: str,
    *,
    when: str = CAND,
    email: str = "test@example.invalid",
) -> str:
    """Commit *files* on top of *start*, point the full ref *ref* at it, and go back to dev."""
    git(repo, "checkout", "-q", "--detach", start)
    sha = commit(repo, files, message, when=when, email=email)
    git(repo, "update-ref", ref, sha)
    git(repo, "checkout", "-q", "dev")
    return sha


def orphan(repo: Path, ref: str, files: dict[str, str | None], message: str) -> str:
    """A commit with no history in common with dev, like the public repository's line."""
    git(repo, "checkout", "-q", "--orphan", "fixture-orphan")
    git(repo, "rm", "-rfq", ".")
    sha = commit(repo, files, message, when=CAND)
    git(repo, "update-ref", ref, sha)
    git(repo, "checkout", "-q", "-f", "dev")
    git(repo, "branch", "-q", "-D", "fixture-orphan")
    return sha


def make_repo(root: Path) -> Path:
    """Blue, on dev: a small Thomas, an architecture test, a board file and a gate list."""
    repo = root / "blue"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    # The name the running copy commits under: the screen flags added lines naming it.
    git(repo, "config", "user.name", "Robin Quill")
    commit(
        repo,
        {
            "thomas/__init__.py": "",
            "thomas/core/__init__.py": "",
            "thomas/core/widget.py": "VALUE = 1\n",
            "thomas/core/old.py": "OLD = 1\n",
            "tests/__init__.py": "",
            "tests/test_widget.py": "from thomas.core import widget\n\n\ndef test_widget():\n    assert widget.VALUE\n",
            "tests/test_architecture.py": "def test_architecture():\n    assert True\n",
            "plans/thomas/WORKBOARD.md": "board\n",
            "scripts/forge/gates/enforcement_manifest.json": '{"scripts/forge/gates/gate.py": "sha"}\n',
            "scripts/forge/gates/gate.py": "GATE = 1\n",
            "README.md": "blue\n",
        },
        "base",
        when=OLD,
    )
    return repo


def dev_moves(repo: Path, message: str = "dev moves", files: dict[str, str | None] | None = None) -> str:
    """A commit on dev dated after every candidate: dev's tip is what "today" means to the custodian."""
    return commit(repo, files or {"README.md": f"blue: {message}\n"}, message, when=NEW)


def candidate(sha: str, *refs: str, stacked_on: str = "") -> Candidate:
    return Candidate(sha, tuple(refs) or ("refs/heads/work",), 1, (), 0, stacked_on)


def junit(cases: list[tuple[str, bool]]) -> str:
    """A pytest xunit1 report, one test per file, named after its file so names never collide."""
    rows = []
    for file, failed in cases:
        inner = '<failure message="boom">E   boom</failure>' if failed else ""
        name = "test_" + Path(file).stem.removeprefix("test_")
        module = file[:-3].replace("/", ".")
        rows.append(
            f'<testcase classname="{module}" name="{name}" file="{file}" line="1" time="0.01">{inner}</testcase>'
        )
    head = '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
    return head + "".join(rows) + "</testsuite></testsuites>"


class FakeCage:
    """The caged runner, for tests: answers the boot check, writes a JUnit report per pytest shard, runs a
    node by itself, and records every green it is asked to end.

    ``failing`` maps a side's label (base, cand, prnt, land, halt) to the test files that fail there; ``alone``
    lists node ids that pass when run by themselves, on any side; ``during`` runs as each shard starts.
    """

    def __init__(
        self,
        failing: dict[str, set[str]] | None = None,
        *,
        alone: set[str] | None = None,
        during: Callable[[str], object] | None = None,
    ) -> None:
        self.failing = failing or {}
        self.alone = alone or set()
        self.during = during
        self.calls: list[tuple[str, str]] = []
        self.labels: list[str] = []
        self.ended: list[str] = []

    def __call__(
        self, command: str, *, cwd: str, timeout_s: float, extra: dict[str, object] | None = None, **_: object
    ) -> CagedResult:
        if extra and extra.get("action") == "end_green":
            self.ended.append(str(extra.get("green") or ""))
            return CagedResult("ok", 0, "", "thomas-agent")
        self.calls.append((command, cwd))
        if "python -c" in command:
            return CagedResult("ok", 0, f"{Path(cwd) / 'thomas' / '__init__.py'}\n", "thomas-agent")
        found = re.search(r'--junitxml=([^" ]+)', command)
        if found is None:
            return CagedResult("error", 2, "missing JUnit report", "thomas-agent")
        report = Path(found.group(1))
        label = report.name.split("-")[0]
        rerun = label == "rerun"
        if rerun:
            label = "base" if "ratchet-base-" in cwd else "cand"
        self.labels.append(label)
        if self.during is not None:
            self.during(label)
        targets = re.findall(r'"(tests/[^" ]+)"', command)
        files = [target.split("::", 1)[0] for target in targets]
        bad = self.failing.get(label, set())
        cases = [
            (
                file,
                file in bad
                and (not rerun or f"{file}::test_{Path(file).stem.removeprefix('test_')}" not in self.alone),
            )
            for file in files
        ]
        report.write_text(junit(cases), encoding="utf-8")
        return CagedResult("ok", 1 if any(failed for _, failed in cases) else 0, "", "thomas-agent")


def extra_candidate(repo: Path) -> str:
    """refs/heads/fix/extra: a new module and its test, plus a board edit the ratchet leaves out."""
    base = git(repo, "rev-parse", "dev")
    files = {
        "thomas/core/extra.py": "X = 1\n",
        "tests/test_extra.py": "from thomas.core import extra\n\n\ndef test_extra():\n    assert extra.X\n",
        "plans/thomas/WORKBOARD.md": "claimed by the candidate\n",
    }
    return on_ref(repo, "refs/heads/fix/extra", base, files, "extra")


def submissions() -> list[Path]:
    """What is waiting in the promoter's inbox (the test's own cage root)."""
    inbox = green_handoff.inbox_dir()
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.iterdir() if p.is_dir() and not p.name.startswith("."))


def promote(repo: Path, submission: Path, *, trailer: bool = True) -> str:
    """What the promoter does, for a test: the submission's patch as one single-parent commit on dev."""
    git(repo, "apply", "--index", str(submission / "change.patch"))
    message = submission.parent.parent / f"{submission.name}.msg"
    tail = f"\nThomas-Submission-Id: {submission.name}\n" if trailer else ""
    message.write_text(f"self-fix: test\n\nApproved at the Windows sign-in.\n{tail}", encoding="utf-8")
    git(repo, "commit", "-q", "-F", str(message))
    return git(repo, "rev-parse", "HEAD")


def verdict(
    submission: Path, status: str, *, commit: str = "", files: list[str] | None = None, detail: str = ""
) -> None:
    """The promoter's verdict file, as ``self_change_promoter._finish`` writes it."""
    outbox = submission.parent.parent / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": submission.name,
        "submission_id": submission.name,
        "status": status,
        "detail": detail,
        "commit_sha": commit,
        "files": files or [],
    }
    (outbox / f"{submission.name}.verdict.json").write_text(json.dumps(payload), encoding="utf-8")
