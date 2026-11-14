"""The twenty-one gates of the parity corpus: real gate NAMES (so the stage structure applies), small checkable bodies."""

from __future__ import annotations

from pathlib import Path

from tests.commit_lane_support import PY, git, init_repo, write

GATE = r"""
import pathlib, subprocess, sys, time
name = sys.argv[1]
repo = pathlib.Path.cwd()

def git(*args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout

rows = [r.split("\t") for r in git("diff", "--cached", "--name-status", "--no-renames").splitlines() if r]
staged = {r[1]: r[0][0] for r in rows}
live = [p for p, s in staged.items() if s != "D"]

def fail(text):
    print(text)
    sys.exit(1)

def lines(path):
    return (repo / path).read_text(encoding="utf-8").count("\n")

def head_lines(path):
    return git("show", "HEAD:" + path).count("\n")

if name == "protected_files":
    for p in staged:
        if p.startswith("protected/"):
            fail("protected file touched: " + p)
elif name == "merge_resurrection":
    for p, s in staged.items():
        if s == "A" and p.startswith("graveyard/"):
            fail("resurrected: " + p)
elif name == "agent_safety":
    for p in live:
        if p.endswith(".py"):
            try:
                compile((repo / p).read_text(encoding="utf-8"), p, "exec")
            except SyntaxError as exc:
                fail(f"syntax error in {p}: {exc.msg}")
elif name == "exception_handler":
    for p in live:
        if p.endswith(".py") and "except:" in (repo / p).read_text(encoding="utf-8"):
            fail("bare except in " + p)
elif name == "duplicate_filename":
    base = lambda x: x.rsplit("/", 1)[-1]
    tracked = [base(x) for x in git("ls-files").splitlines()]
    for p, s in staged.items():
        if s == "A" and tracked.count(base(p)) > 1:
            fail("duplicate filename: " + base(p))
elif name == "ruff":
    for p in live:
        if p.endswith(".py") and any(len(l) > 120 for l in (repo / p).read_text(encoding="utf-8").splitlines()):
            fail("E501 line too long in " + p)
elif name == "bulk_commit":
    if len(staged) > 5:
        fail(f"{len(staged)} files staged, limit 5")
elif name == "commit_growth":
    for p, s in staged.items():
        if s == "M" and lines(p) - head_lines(p) > 40:
            fail("grew by more than 40 lines: " + p)
elif name == "active_folder_guard":
    time.sleep(0.4)
    for p in staged:
        if p.startswith("locked/"):
            fail("folder is locked by another agent: " + p)
elif name == "workboard_claims":
    if "BROKEN-CLAIM" in (repo / "plans/thomas/WORKBOARD.md").read_text(encoding="utf-8"):
        fail("the board has a broken claim")
elif name == "workboard_agent_claim":
    for p in staged:
        if p.startswith("forbidden/"):
            fail("staged outside the claim: " + p)
elif name == "monolith_guard":
    for p in live:
        if p.endswith(".py") and lines(p) > 150:
            fail(f"{p} is {lines(p)} lines")
elif name == "monolith_filename_guard":
    for p in live:
        if p.endswith("_part1.py"):
            fail("split-file name: " + p)
elif name == "protected_deletion":
    for p, s in staged.items():
        if s == "D" and p.startswith("keep/"):
            fail("protected deletion: " + p)
elif name == "release_update":
    if "pyproject.toml" in staged and "thomas/__init__.py" not in staged:
        fail("version file staged without its twin")
elif name == "changelog":
    if sum(p.startswith("thomas/") for p in staged) >= 3 and "CHANGELOG.md" not in staged:
        fail("three thomas/ files and no changelog")
elif name == "test_coverage":
    if sum(p.startswith("src/") and p.endswith(".py") for p in live) >= 2 and not any(p.startswith("tests/") for p in staged):
        fail("two source files and no test")
elif name == "shrinkage":
    for p, s in staged.items():
        if s == "M" and head_lines(p) >= 20 and lines(p) < 0.7 * head_lines(p):
            fail("shrank by more than 30%: " + p)
elif name == "workboard_inbox_final":
    if (repo / "mail.flag").exists():
        fail("mail arrived during the ladder")
print("ok " + name)
"""

# The real registry's order for these names (workboard gates after the guard, monolith gates after the claim gates ...).
ORDER = (
    "protected_files",
    "merge_resurrection",
    "agent_safety",
    "exception_handler",
    "duplicate_filename",
    "workboard_inbox",
    "ruff",
    "bulk_commit",
    "commit_growth",
    "active_folder_guard",
    "precommit_skip_policy",
    "workboard_claims",
    "workboard_agent_claim",
    "monolith_guard",
    "monolith_filename_guard",
    "protected_deletion",
    "release_update",
    "changelog",
    "test_coverage",
    "shrinkage",
    "workboard_inbox_final",
)
SCOPES = "src,docs,protected,graveyard,keep,locked,forbidden,thomas,tests,pyproject.toml,big"
CLAIM = f"agent=codex; name=Codex; role=solo; parent=none; scope={SCOPES}; task=Scoped commit"


def _registry(gate_py: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    gates = [(name, (PY, str(gate_py), name)) for name in ORDER]
    gates.insert(10, ("untracked_import", (PY, "tools/never.py")))  # a gate nobody committed: skipped, never run
    return tuple(gates)


def _seed(tmp_path: Path) -> Path:
    repo, _board = init_repo(tmp_path, claims=(CLAIM,))
    write(repo / "src" / "app.py", "".join(f"line = {i}\n" for i in range(30)))
    write(repo / "src" / "old.py", "VALUE = 1\n")
    write(repo / "src" / "shrink.py", "".join(f"row = {i}\n" for i in range(40)))
    write(repo / "docs" / "readme.md", "docs\n")
    write(repo / "protected" / "p.txt", "p\n")
    write(repo / "keep" / "k.txt", "k\n")
    write(repo / "tests" / "test_x.py", "def test_x():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    write(repo / "tools" / "never.py", "raise SystemExit('an unreviewed gate must never run')\n")  # untracked
    return repo
