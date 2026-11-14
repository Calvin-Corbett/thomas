"""What merging a candidate onto dev would do, measured without a checkout, a green or a model.

``git merge-tree --write-tree`` computes the merged tree against a temporary
object store (``Repo.scratch``). From it the screen says:

* whether dev already has the candidate's content (the merged tree is dev's tree);
* which files conflict, and which side's version to keep for each;
* what the promoter would refuse, in its own words, before a green or a proof is spent;
* which added files bring back what dev deleted, and which added tests dev already has;
* which added lines must not land: a conflict marker, a line naming you.

Coordination files -- the board, task plans, a salvage snapshot's file list,
runtime/ -- are other sessions' live state, never a candidate's payload. They are
left out of the candidate and recorded as left out.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.gitrepo import Repo

LEFT_OUT = (".praxis-salvage-expected-files", "plans/thomas/WORKBOARD.md", "plans/thomas/tasks/*/PLAN.md", "runtime/*")
_MARKER = re.compile(r"^\+(<{7}|>{7})( |$)|^\+={7}$")
_TEST_DEF = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test_\w+)", re.MULTILINE)
_ADVICE = {
    "candidate_deleted": "the candidate deleted it and dev has changed it since: keep dev's file, and carry over "
    "by hand only what the candidate's change needs",
    "dev_deleted": "dev deleted it and the candidate changed it: keep dev's deletion, and say in your report "
    "what the candidate's edits were",
    "both_added": "both sides added it: keep one file that does what both versions meant",
    "both_changed": "both sides changed it: keep both sides' intent",
}


@dataclass(frozen=True)
class Conflict:
    path: str
    kind: str
    advice: str


@dataclass(frozen=True)
class Screen:
    dev_sha: str
    sha: str
    merged_tree: str
    already_on_dev: bool = False
    conflicts: tuple[Conflict, ...] = ()
    changes: tuple[tuple[str, str], ...] = ()
    dropped: tuple[str, ...] = ()
    refusal: str = ""
    resurrected: tuple[str, ...] = ()
    duplicate_tests: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()

    @property
    def mechanical(self) -> bool:
        """True when no model is needed: a clean merge with nothing that must be decided."""
        return not (self.conflicts or self.resurrected or self.duplicate_tests or self.flags)

    def needs(self) -> str:
        """What a model has to decide, in a few words ("" when nothing)."""
        parts = []
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} conflict(s)")
        if self.resurrected:
            parts.append(f"{len(self.resurrected)} file(s) dev deleted coming back")
        if self.duplicate_tests:
            parts.append(f"{len(self.duplicate_tests)} test(s) dev already has")
        parts.extend(self.flags)
        return ", ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duplicate_tests"] = list(self.duplicate_tests[:40])
        return data


def left_out(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in LEFT_OUT)


def screen(repo: Repo, dev_sha: str, cand: Candidate, *, onto: str = "") -> Screen:
    """Measure merging *cand* onto dev; with *onto*, only its commits above *onto* (work that already landed)."""
    with repo.scratch() as s:
        args = ["merge-tree", "--write-tree", "--name-only", "--no-messages"]
        if onto:
            args.append(f"--merge-base={onto}")
        merged = s.run(*args, dev_sha, cand.sha, ok=(0, 1))
        lines = [line.strip() for line in merged.stdout.splitlines() if line.strip()]
        tree, conflicted = lines[0], sorted(set(lines[1:]))
        dev_tree = s.out("rev-parse", f"{dev_sha}^{{tree}}")
        if merged.returncode == 0 and tree == dev_tree:
            return Screen(dev_sha, cand.sha, tree, already_on_dev=True)
        base = onto or s.out("merge-base", dev_sha, cand.sha)
        changes = _changes(s, dev_tree, tree)
        dropped = tuple(p for _, p in changes if left_out(p))
        kept = tuple((status, p) for status, p in changes if not left_out(p))
        patch = _keep(s.run("diff", "--no-renames", "--binary", "--full-index", dev_tree, tree).stdout, set(dropped))
        added = [p for status, p in kept if status == "A"]
        write_safety = cage_checks().write_safety_refusal(patch, repo.path)
        refusal = write_safety or integrity_refusal(s, dev_sha, [p for _, p in kept])
        return Screen(
            dev_sha=dev_sha,
            sha=cand.sha,
            merged_tree=tree,
            conflicts=tuple(_conflict(s, base, dev_sha, cand.sha, p) for p in conflicted if not left_out(p)),
            changes=kept,
            dropped=dropped,
            refusal=(refusal or "") if kept else "",
            resurrected=tuple(resurrections(s, base, dev_sha, added)),
            duplicate_tests=tuple(duplicate_tests(s, dev_sha, tree, added)),
            flags=tuple(flags(_keep(patch, set(conflicted)), owner_words(repo))),
        )


def _changes(repo: Repo, a: str, b: str) -> tuple[tuple[str, str], ...]:
    listed = repo.out("diff-tree", "-r", "--no-renames", "--name-status", a, b)
    pairs = (line.split("\t", 1) for line in listed.splitlines() if "\t" in line)
    return tuple((status[:1], path) for status, path in pairs)


def _path_of(header: str) -> str:
    """The path in ``diff --git a/<p> b/<p>`` (the same path twice: renames are off), spaces and all."""
    rest = header[len("diff --git a/") :]
    half = (len(rest) - len(" b/")) // 2
    if rest[half : half + 3] == " b/" and rest[:half] == rest[half + 3 :]:
        return rest[:half]
    return rest.split(" b/", 1)[0]


def _sections(patch: str) -> list[tuple[str, str]]:
    return [
        (_path_of(chunk.split("\n", 1)[0]), chunk)
        for chunk in re.split(r"(?m)^(?=diff --git )", patch)
        if chunk.startswith("diff --git a/")
    ]


def _keep(patch: str, skip: set[str]) -> str:
    return "".join(chunk for path, chunk in _sections(patch) if path not in skip)


def _conflict(repo: Repo, base: str, dev_sha: str, sha: str, path: str) -> Conflict:
    in_base, in_dev, in_cand = (repo.has_path(rev, path) for rev in (base, dev_sha, sha))
    if in_base and in_dev and not in_cand:
        kind = "candidate_deleted"
    elif in_base and in_cand and not in_dev:
        kind = "dev_deleted"
    elif not in_base and in_dev and in_cand:
        kind = "both_added"
    else:
        kind = "both_changed"
    return Conflict(path, kind, _ADVICE[kind])


def cage_checks() -> Any:
    """What the promoter checks. Imported when a run asks, because a release carries the package and not ``scripts/cage``.

    The ratchet's code has to load there all the same, so that its row can come up, and ``host.host_refusal`` is what
    stops a run reaching this in a release.
    """
    from scripts.cage import self_change_checks

    return self_change_checks


def integrity_refusal(repo: Repo, dev_sha: str, paths: Sequence[str]) -> str:
    """``self_change_checks.integrity_refusal``'s sentence, for changed paths rather than a tree in the store."""
    manifest = cage_checks().MANIFEST_PATH
    shown = repo.run("show", f"{dev_sha}:{manifest}", ok=(0, 128)).stdout
    try:
        enforced = list(json.loads(shown or "{}"))
    except ValueError:
        return "the enforcement manifest on dev cannot be read"
    changed = set(paths)
    touched = [p for p in [manifest, *enforced] if p in changed]
    if touched:
        return (
            "the change edits enforced gate file(s): "
            + ", ".join(touched[:6])
            + ". Gate changes go through your own commit path, not a self-fix."
        )
    return ""


def _dead_paths(blue: Path) -> set[str] | None:
    from scripts.forge import graveyard

    try:
        yard = graveyard.load(blue)
    except SystemExit:  # a malformed graveyard: load refuses to read it as empty
        return None
    dead = yard.dead_file_paths()
    return {path.casefold() for path, record in dead.items() if not yard.is_resurrection_approved(record["id"])}


def resurrections(repo: Repo, base: str, dev_sha: str, added: Sequence[str]) -> list[str]:
    """Added paths that bring back what dev deleted, or what the graveyard records as dead.

    The promoter never runs merge_resurrection_gate, and the graveyard missed the
    30, 145 and 143 paths the three August lines would restore (2026-09-24), so
    dev's own history is asked too.
    """
    if not added:
        return []
    dead = _dead_paths(repo.path)
    found: list[str] = []
    for path in added:
        if base and repo.has_path(base, path):
            found.append(f"{path} (dev deleted it after the candidate branched)")
            continue
        gone = repo.run("log", "--diff-filter=D", "--format=%h", "-1", dev_sha, "--", path).stdout.strip()
        if gone:
            found.append(f"{path} (dev deleted it in {gone})")
        elif dead is None:
            found.append(f"{path} (the graveyard cannot be read, so a new file cannot be told from a dead one)")
        elif path.casefold() in dead:
            found.append(f"{path} (the graveyard records it as dead)")
    return found


def duplicate_tests(repo: Repo, dev_sha: str, tree: str, added: Sequence[str]) -> list[str]:
    """Tests an added file defines that dev already has: a copy of a split dev already made.

    One shared name is common; a file whose tests are mostly dev's own -- at least
    three, and at least half of them -- is a copy (fcb5f06's split adds 30 tests,
    all already on dev).
    """
    files = [p for p in added if p.startswith("tests/") and p.endswith(".py")]
    if not files:
        return []
    listed = repo.run("grep", "-h", "-o", "-E", "def test_[A-Za-z0-9_]+", dev_sha, "--", "tests/", ok=(0, 1))
    on_dev = {line.split()[-1] for line in listed.stdout.splitlines() if line.strip()}
    found: list[str] = []
    for path in files:
        names = sorted(set(_TEST_DEF.findall(repo.run("show", f"{tree}:{path}").stdout)))
        same = [n for n in names if n in on_dev]
        if len(same) >= 3 and 2 * len(same) >= len(names):
            found.extend(f"{path}::{name}" for name in same)
    return found


def owner_words(repo: Repo) -> set[str]:
    """Words of the name the running copy commits under (its git config): an added line naming you is flagged."""
    name = repo.run("config", "--get", "user.name", ok=(0, 1)).stdout
    return {word.lower() for word in re.findall(r"[A-Za-z]{3,}", name)}


def flags(patch: str, words: set[str]) -> list[str]:
    """Added lines that must not land: a conflict marker (the promoter compiles only .py), a line naming you."""
    naming = re.compile(r"\b(" + "|".join(map(re.escape, sorted(words))) + r")\b", re.IGNORECASE) if words else None
    found: set[str] = set()
    for path, chunk in _sections(patch):
        for line in chunk.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            if _MARKER.match(line):
                found.add(f"a conflict marker in {path}")
            elif naming is not None and naming.search(line):
                found.add(f"a line naming you in {path}")
    return sorted(found)


def final_refusal(repo: Repo, dev_sha: str, patch: str, files: Sequence[str]) -> str:
    """Why a green's finished change must not go to your card ("" when it may): the same checks, on what was made.

    A coordination file still in the change is refused first. The ratchet restores them before every proof
    (``context.restore_left_out``), so one here means something wrote it afterwards.
    """
    kept = [p for p in files if left_out(p)]
    if kept:
        return "it changes coordination files the ratchet leaves out: " + ", ".join(kept[:6])
    refusal = cage_checks().write_safety_refusal(patch, repo.path) or integrity_refusal(repo, dev_sha, files)
    if refusal:
        return f"the promoter would refuse it: {refusal}"
    back = resurrections(repo, "", dev_sha, [p for p in files if not repo.has_path(dev_sha, p)])
    if back:
        return "it brings back what dev deleted: " + "; ".join(back[:6])
    found = flags(patch, owner_words(repo))
    return "it adds " + "; ".join(found[:6]) if found else ""


__all__ = [
    "LEFT_OUT",
    "Conflict",
    "Screen",
    "cage_checks",
    "duplicate_tests",
    "final_refusal",
    "flags",
    "integrity_refusal",
    "left_out",
    "owner_words",
    "resurrections",
    "screen",
]
