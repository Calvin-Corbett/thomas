"""Check the candidate's screened merge against the green before and after proof."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.server import green_checkout
from thomas.server.ratchet.context import Attempt, Context, green_repo
from thomas.server.ratchet.gitrepo import Repo

_SAID = {"A": "added", "M": "changed", "D": "deleted"}


def against_the_screen(att: Attempt, changes: Sequence[tuple[str, str]]) -> tuple[str, tuple[str, ...]]:
    """Return an objection and any extra repair paths in the green's change.

    A repair may add paths beyond the candidate's change, but a green cannot
    delete a file the candidate did not delete. An un-repaired green may not
    introduce other paths either.
    """
    expected = {path: status for status, path in att.screen.changes}
    wrong: list[str] = []
    extra: list[str] = []
    for status, path in changes:
        want = expected.get(path)
        if status == "D" and want != "D":
            wrong.append(f"{path} is deleted, and the candidate does not delete it")
        elif want is None:
            if att.repaired:
                extra.append(path)
            else:
                wrong.append(f"{path} is {_SAID.get(status, status)} here, and the candidate does not change it")
    return "; ".join(wrong[:6]), tuple(sorted(extra))


def _blobs(repo: Repo, tree: str, paths: set[str]) -> dict[str, str]:
    """Object ids for the requested files in a tree; absent paths are omitted."""
    found: dict[str, str] = {}
    for line in repo.out("ls-tree", "-r", "--full-tree", tree).splitlines():
        meta, _tab, path = line.partition("\t")
        if path in paths:
            found[path] = meta.split()[2]
    return found


def _off_the_merge(ctx: Context, att: Attempt) -> str:
    """Explain how the green differs from the merge the screen measured."""
    paths = {path for _status, path in att.screen.changes}
    here = _blobs(green_repo(att.green), green_checkout.green_tree(att.green, _staged=True), paths)
    with ctx.repo.scratch() as scratch:
        args = ["merge-tree", "--write-tree", "--name-only", "--no-messages"]
        if att.onto:
            args.append(f"--merge-base={att.onto}")
        merged = scratch.run(*args, att.dev_sha, att.candidate.sha, ok=(0, 1))
        lines = [line.strip() for line in merged.stdout.splitlines() if line.strip()]
        if not lines:
            return "merging it onto dev cannot be measured again, so what green holds cannot be checked against it"
        if lines[0] != att.screen.merged_tree:
            return (
                f"merging it onto dev now makes tree {lines[0][:12]}, not the {att.screen.merged_tree[:12]} "
                "the screen measured"
            )
        want = _blobs(scratch, lines[0], paths)
    off = sorted(path for path in paths if here.get(path) != want.get(path))
    if not off:
        return ""
    return f"green does not hold what merging it onto dev makes, in {len(off)} file(s): " + ", ".join(off[:6])


def wrong_green(ctx: Context, att: Attempt) -> str:
    """Explain why the merged green cannot yet be proven as the candidate's change."""
    why, _extra = against_the_screen(att, green_checkout.changed_status(att.green))
    if why:
        return "what green holds is not the candidate's change: " + why
    return _off_the_merge(ctx, att)
