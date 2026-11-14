"""Path-identity fixtures: a spelling that names one place to a checker and another place to the file system.

Each builder creates the trick for real inside the lab's scratch folder and records what it measured, so a
self-test can confirm the trick exists before any later test claims something refused it. Every case names the
spelling a hand-in would use (``claimed``), a hand-written patch that adds it (``patches``) and the folders a test
should compare before and after (``protected``). The builders say nothing about what a referee or writer should
answer. Nothing here runs outside the scratch root.

``junction_after_check`` is the one trick that happens in time: its ``arm`` moves the landing folder aside and puts
a junction to a folder outside the tree in its place, so the code under test can call it between its last check and
its first write. ``arm`` records ``facts["blocked"]`` instead of raising if the file system refuses the swap.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.express_lab import ExpressLab, LabCase, lab_fixture
from tests.express_lab_patches import hand_written_add
from tests.express_winfs import (
    EnvironmentUnavailable,
    FixtureBroken,
    alternate_streams,
    create_junction,
    is_reparse_point,
    remove_junction,
    remove_link,
    short_path,
)

EXISTING = "changelog.d/existing-fragment.md"
LANDING_NAME = "changelog.d/lab-landing-swap.md"


def _same_file(a: Path, b: Path) -> bool:
    """True when both names reach one file. A name that is simply not there is False; any other failure raises."""
    try:
        return os.path.samefile(a, b)
    except (FileNotFoundError, NotADirectoryError):
        return False


def path_case(lab: ExpressLab, name: str, trick: str, windows_only: bool, **fields: object) -> LabCase:
    claimed = fields["claimed"]
    patches = tuple(hand_written_add(lab, c.encode()) for c in claimed)  # type: ignore[attr-defined]
    return LabCase(name, "path", trick, windows_only, lab.layout.root, patches=patches, **fields)  # type: ignore[arg-type]


def _folded_claim(lab: ExpressLab, name: str, trick: str, variant: str, *, unfolded_is_broken: bool) -> LabCase:
    """A claimed spelling that the file system folds onto the existing base fragment."""
    real = lab.repo.root / EXISTING
    if not _same_file(real, lab.repo.root / variant):
        message = f"this file system does not fold {variant!r} onto {EXISTING}"
        raise (FixtureBroken if unfolded_is_broken else EnvironmentUnavailable)(message)
    facts = {"real": real, "same_file": True, "original": real.read_bytes()}
    return path_case(lab, name, trick, True, claimed=(variant,), protected=(lab.repo.root,), facts=facts)


@lab_fixture("junction_after_check", "path", windows_only=True)
def junction_after_check(lab: ExpressLab) -> LabCase:
    (lab.outside / "canary.txt").write_bytes(b"outside canary\n")
    folder, moved = lab.repo.root / "changelog.d", lab.repo.root / "changelog.d.lab-moved"
    facts: dict[str, object] = {
        "parent": folder,
        "moved": moved,
        "outside": lab.outside,
        "target": lab.outside,
        "reparse_before_arm": is_reparse_point(folder),
    }

    def arm() -> None:
        try:
            os.rename(folder, moved)
        except OSError as exc:  # the code under test holds the folder open: the swap itself is refused
            facts["blocked"] = f"{type(exc).__name__}: {exc}"
            return
        create_junction(folder, lab.outside)

    def undo() -> None:
        remove_junction(folder)
        if moved.exists() and not folder.exists():
            os.rename(moved, folder)

    lab.on_close(undo, gone=folder)
    trick = "the landing folder changes into a junction to a folder outside the tree after the path was checked"
    return path_case(
        lab,
        "junction_after_check",
        trick,
        True,
        claimed=(LANDING_NAME,),
        protected=(lab.outside,),
        arm=arm,
        facts=facts,
    )


@lab_fixture("symlink_to_outside", "path")
def symlink_to_outside(lab: ExpressLab) -> LabCase:
    victim = lab.outside / "victim.txt"
    victim.write_bytes(b"outside victim\n")
    link = lab.repo.root / "changelog.d" / "lab-symlink-target.md"
    lab.symlink(link, victim)  # injectable: a test without the symlink privilege supplies its own creator
    lab.on_close(lambda: remove_link(link), gone=link)
    return path_case(
        lab,
        "symlink_to_outside",
        "the target name is a symlink to a file outside the tree",
        False,
        claimed=("changelog.d/lab-symlink-target.md",),
        protected=(lab.outside,),
        facts={"link": link, "outside": lab.outside, "victim": victim, "is_link": link.is_symlink()},
    )


@lab_fixture("short_name_alias", "path", windows_only=True)
def short_name_alias(lab: ExpressLab) -> LabCase:
    rel = "changelog.d/express-long-fragment-name.md"
    lab.base_sha = lab.repo.commit_files({rel: b"original long-name bytes\n"}, "a fragment with a long name")
    real = lab.repo.root / rel
    short = short_path(real)
    alias = Path(short).name if short else ""
    if not alias or alias.lower() == real.name.lower():
        raise EnvironmentUnavailable("8.3 short names are switched off for this volume")
    claimed = f"changelog.d/{alias}"
    facts = {
        "real": real,
        "alias": alias,
        "same_file": _same_file(real, lab.repo.root / claimed),
        "original": real.read_bytes(),
        "base": lab.base_sha,  # this fixture commits, so dev is one commit past the lab's first base
    }
    trick = "the 8.3 alias of an existing file, which names that file under another spelling"
    return path_case(lab, "short_name_alias", trick, True, claimed=(claimed,), protected=(lab.repo.root,), facts=facts)


@lab_fixture("case_variant", "path", windows_only=True)
def case_variant(lab: ExpressLab) -> LabCase:
    # a case-sensitive folder is a legitimate difference between machines, so a missing fold is a skip
    return _folded_claim(
        lab, "case_variant", "an existing path spelled in another case", "changelog.d/EXISTING-Fragment.MD",
        unfolded_is_broken=False,
    )  # fmt: skip


@lab_fixture("alternate_stream", "path", windows_only=True)
def alternate_stream(lab: ExpressLab) -> LabCase:
    real = lab.repo.root / EXISTING
    facts = {"real": real, "streams_before": alternate_streams(real), "original": real.read_bytes()}
    trick = "a hidden NTFS stream on an existing file, named as file:stream"
    return path_case(
        lab, "alternate_stream", trick, True, claimed=(EXISTING + ":hidden",), protected=(lab.repo.root,), facts=facts
    )


@lab_fixture("trailing_dot", "path", windows_only=True)
def trailing_dot(lab: ExpressLab) -> LabCase:
    trick = "a name with a trailing dot, which Windows drops"
    return _folded_claim(lab, "trailing_dot", trick, EXISTING + ".", unfolded_is_broken=True)


@lab_fixture("trailing_space", "path", windows_only=True)
def trailing_space(lab: ExpressLab) -> LabCase:
    trick = "a name with a trailing space, which Windows drops"
    return _folded_claim(lab, "trailing_space", trick, EXISTING + " ", unfolded_is_broken=True)


@lab_fixture("dot_git_variant", "path", windows_only=True)
def dot_git_variant(lab: ExpressLab) -> LabCase:
    hooks = lab.repo.root / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    spellings = [".GIT/hooks/lab-hook", ".git./hooks/lab-hook"]
    short = short_path(lab.repo.root / ".git")
    if short and Path(short).name.lower() != ".git":
        spellings.append(f"{Path(short).name}/hooks/lab-hook")
    folded = [s for s in spellings if _same_file(lab.repo.root / Path(s).parent, hooks)]
    if not folded:
        raise EnvironmentUnavailable("no spelling of .git folds onto the real .git folder here")
    trick = "spellings of the .git folder that the file system folds onto the real one"
    return path_case(
        lab, "dot_git_variant", trick, True, claimed=tuple(folded), protected=(hooks,),
        facts={"hooks": hooks, "spellings": tuple(folded)},
    )  # fmt: skip
