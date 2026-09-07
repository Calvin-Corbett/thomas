"""What the governor should do about each way work sits outside the trunk.

`thomas consolidate` measured one dimension - local branch count - and read
green on 2026-09-03 while the trunk was 75 commits unpushed, the public repo 891
behind, 9 branches held live unlanded work and 7,312 lines were uncommitted. A
person then did the consolidation by hand. That is the failure this module
exists to end: the governor should name every place work is stranded AND the
next move for each, so nobody has to hold the plan in their head.

Two rules shape it.

**Not every remedy is the governor's to perform.** Pushing a green trunk is safe
to automate. Publishing to a public repository is not - this project's public
history is squashed, privacy-scrubbed releases, so a raw push would expose work
never meant to be public and cannot be undone. Another agent's uncommitted work
is theirs. Each action therefore carries an ``actor``, and the governor performs
only its own.

**Zero merge conflicts does not mean safe to merge.** On 2026-09-03 three live
branches merged into `dev` with no conflicts at all, and each carried
`ccea3027` - a 1,322-file public release squash that DELETES 255 files the trunk
still has. Landing a six-commit feature branch would have silently removed them.
:func:`merge_deletions` is that check, and it is why a stranded branch is
advised as a cherry-pick rather than a merge whenever a merge would delete.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Who may carry an action out.
THOMAS = "thomas"  # safe to automate
OWNER = "owner"  # irreversible, or a product decision
OTHER_AGENT = "other agent"  # someone else's work; never touched

# (exit code, stdout). The exit code is not optional here: `git merge-tree`
# signals a conflict by exiting 1 while printing NO conflict markers at all, so
# a runner that discards output on failure reports every conflicting branch as
# clean - which is exactly the bug this interface exists to prevent.
GitProbe = Callable[[Sequence[str]], tuple[int, str]]


def subprocess_git_runner(repo: Path) -> GitProbe:
    """A git probe rooted at `repo`, decoding UTF-8 explicitly.

    Not the platform default: one 0x9d byte in the workboard - half a curly
    quote - crashed a gate that captured git output as cp1252, and the failure
    surfaced as a file appearing absent from the index.
    """

    def run(args: Sequence[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ("git", *args),
                cwd=str(repo),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return 1, ""
        return proc.returncode, proc.stdout

    return run


def _out(git: GitProbe, args: Sequence[str]) -> str:
    """Stdout when the command succeeded, empty string otherwise."""
    code, text = git(args)
    return text if code == 0 else ""


@dataclass(frozen=True)
class Action:
    """One next move, and who may make it."""

    dimension: str
    do: str
    why: str
    actor: str

    def render(self) -> str:
        tag = "" if self.actor == THOMAS else f"  [{self.actor}]"
        return f"{self.dimension}: {self.do}{tag}\n    why: {self.why}"


def merge_deletions(git: GitProbe, trunk: str, branch: str) -> tuple[int, int]:
    """(files a merge of `branch` would delete from `trunk`, conflict count).

    The deletion count is the number that matters and the one nobody looks at.
    A branch built on top of a squashed snapshot re-applies that snapshot's
    deletions to the trunk, so a clean-merging six-commit branch can remove
    hundreds of files that are still live.
    """
    base = _out(git, ["merge-base", trunk, branch]).strip()
    if not base:
        return 0, 0
    # `--no-renames` matters: with rename detection on, a file deleted here and
    # a file added there with the same bytes is reported as ONE rename and the
    # deletion never appears. A safety count that silently halves is worse than
    # no count, and a path that disappears is a path that disappears - every
    # caller importing it breaks whether or not the bytes live on elsewhere.
    deleted = [
        line.strip()
        for line in _out(git, ["diff", "--diff-filter=D", "--no-renames", "--name-only", base, branch]).splitlines()
        if line.strip()
    ]
    # Present in the trunk means the merge would take it away.
    still_present = sum(1 for path in deleted if _out(git, ["rev-parse", "--verify", f"{trunk}:{path}"]).strip())

    # `merge-tree --write-tree --name-only` exits 1 on conflict and prints the
    # merged tree oid, then the conflicted paths, then a blank line. Counting
    # `<<<<<<<` markers finds none - it never emits them.
    code, text = git(["merge-tree", "--write-tree", "--name-only", trunk, branch])
    conflicts = 0
    if code != 0:
        rest = text.splitlines()[1:]  # drop the tree oid
        conflicts = len(list(_takewhile_nonblank(rest))) or 1
    return still_present, conflicts


def _takewhile_nonblank(lines: Sequence[str]):
    for line in lines:
        if not line.strip():
            return
        yield line.strip()


def advise_branch(git: GitProbe, trunk: str, branch: str) -> Action:
    """How to land one stranded branch: merge, resolve by hand, or cherry-pick."""
    deletions, conflicts = merge_deletions(git, trunk, branch)
    if deletions:
        return Action(
            dimension="stranded",
            do=f"cherry-pick the feature commits from `{branch}` - do NOT merge it",
            why=(
                f"merging would delete {deletions} file(s) the trunk still has - a branch built on a "
                "squashed snapshot re-applies that snapshot's deletions"
            ),
            actor=OWNER,
        )
    if conflicts:
        return Action(
            dimension="stranded",
            do=f"merge `{branch}` by hand and resolve {conflicts} conflict(s)",
            why="the merge is not clean, so it needs someone who knows which side is right",
            actor=OWNER,
        )
    return Action(
        dimension="stranded",
        do=f"merge `{branch}` into `{trunk}`",
        why="it merges clean and deletes nothing the trunk still has",
        actor=THOMAS,
    )


def _first(findings: Sequence[str], prefix: str) -> str | None:
    return next((f for f in findings if f.startswith(prefix)), None)


def advise(
    findings: Sequence[str],
    *,
    git: GitProbe | None = None,
    trunk: str = "dev",
    live_branches: Sequence[str] = (),
    uncommitted_is_mine: bool = True,
) -> list[Action]:
    """Turn measured divergence into an ordered plan, each step with an actor.

    Order is the one the repository forces: an untidy tree blocks the push, and
    an unpushed trunk cannot be published. Discovering that by hand cost a day.
    """
    actions: list[Action] = []

    if (found := _first(findings, "uncommitted:")) is not None:
        actions.append(
            Action(
                dimension="uncommitted",
                do="commit or park it" if uncommitted_is_mine else "ask the agent who owns it to land or park it",
                why=f"{found} - an untidy tree blocks the push for everyone, not only its owner",
                actor=THOMAS if uncommitted_is_mine else OTHER_AGENT,
            )
        )

    if (found := _first(findings, "unpushed:")) is not None:
        actions.append(
            Action(
                dimension="unpushed",
                do=f"push `{trunk}` to its remote",
                why=f"{found} - work that exists on one machine is one disk failure from gone",
                actor=THOMAS,
            )
        )

    if git is not None:
        actions.extend(advise_branch(git, trunk, branch) for branch in live_branches)

    if (found := _first(findings, "stranded:")) is not None and "stale fork" in found:
        actions.append(
            Action(
                dimension="stranded",
                do="archive and retire the stale forks",
                why=f"{found} - only a branch whose content the trunk already has may be retired automatically",
                actor=THOMAS,
            )
        )

    if (found := _first(findings, "public:")) is not None:
        actions.append(
            Action(
                dimension="public",
                do="cut a release: scrub, squash, then publish",
                why=(
                    f"{found} - the public history is squashed, privacy-scrubbed releases, so a raw push "
                    "would expose work never meant to be public and cannot be taken back"
                ),
                actor=OWNER,
            )
        )

    if (found := _first(findings, "clones:")) is not None:
        actions.append(
            Action(
                dimension="clones",
                do="confirm each holds nothing unique, then retire it",
                why=f"{found} - a clone is where a fix goes to be forgotten",
                actor=OWNER,
            )
        )

    return actions


def render_plan(actions: Sequence[Action]) -> str:
    if not actions:
        return "CONSOLIDATION: nothing to do - every dimension is level."
    mine = sum(1 for action in actions if action.actor == THOMAS)
    lines = [f"CONSOLIDATION: {len(actions)} step(s), {mine} of them Thomas may take itself"]
    lines.extend(f"  - {action.render()}" for action in actions)
    return "\n".join(lines)
