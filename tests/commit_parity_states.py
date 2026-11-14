"""The staged states of the parity corpus: each changes the working tree of a freshly seeded repo."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.commit_lane_support import git, write

# ---- the corpus: each state changes the working tree of a freshly seeded repo -----------------------------------------


def clean(repo: Path) -> None:
    write(repo / "src" / "app.py", "".join(f"line = {i}\n" for i in range(31)))


def protected(repo: Path) -> None:
    write(repo / "protected" / "p.txt", "changed\n")


def resurrected(repo: Path) -> None:
    write(repo / "graveyard" / "back.py", "x = 1\n")


def syntax_error(repo: Path) -> None:
    write(repo / "src" / "broken.py", "def broken(:\n")


def bare_except(repo: Path) -> None:
    write(repo / "src" / "swallow.py", "try:\n    pass\nexcept:\n    pass\n")


def duplicate_name(repo: Path) -> None:
    write(repo / "docs" / "app.py", "x = 1\n")


def long_line(repo: Path) -> None:
    write(repo / "src" / "wide.py", "x = '" + "y" * 130 + "'\n")


def bulk(repo: Path) -> None:
    for i in range(6):
        write(repo / "src" / f"n{i}.py", f"v = {i}\n")


def growth(repo: Path) -> None:
    write(repo / "src" / "app.py", "".join(f"line = {i}\n" for i in range(30 + 45)))


def locked(repo: Path) -> None:
    write(repo / "locked" / "x.txt", "x\n")


def broken_claim(repo: Path) -> None:
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.write_text(
        board.read_text(encoding="utf-8").replace("# Workboard", "# Workboard BROKEN-CLAIM", 1), encoding="utf-8"
    )
    clean(repo)


def forbidden(repo: Path) -> None:
    write(repo / "forbidden" / "f.txt", "f\n")


def big_file(repo: Path) -> None:
    write(repo / "big" / "huge.py", "".join(f"v{i} = {i}\n" for i in range(200)))


def split_name(repo: Path) -> None:
    write(repo / "src" / "thing_part1.py", "x = 1\n")


def deletion(repo: Path) -> None:
    (repo / "keep" / "k.txt").unlink()


def rename(repo: Path) -> None:
    git(repo, "mv", "src/old.py", "src/new.py")


def version_alone(repo: Path) -> None:
    (repo / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.1"\n', encoding="utf-8")
    clean(repo)


def thomas_trio(repo: Path) -> None:
    for name in ("a", "b", "c"):
        write(repo / "thomas" / f"{name}.py", f"{name.upper()} = 1\n")


def untested(repo: Path) -> None:
    write(repo / "src" / "p1.py", "a = 1\n")
    write(repo / "src" / "p2.py", "b = 2\n")


def shrunk(repo: Path) -> None:
    write(repo / "src" / "shrink.py", "".join(f"row = {i}\n" for i in range(10)))


def mail(repo: Path) -> None:
    clean(repo)
    write(repo / "mail.flag", "unread\n")


def protected_and_broken(repo: Path) -> None:
    protected(repo)
    syntax_error(repo)


def late_stage_refusal_before_early_stage_one(repo: Path) -> None:
    broken_claim(repo)  # workboard_claims (stage 1, registry position 11) refuses ...
    big_file(repo)  # ... and so does monolith_guard (stage 0, position 13), which finishes first


def locked_and_forbidden(repo: Path) -> None:
    locked(repo)  # active_folder_guard (stage 0) comes before workboard_agent_claim (stage 1)
    forbidden(repo)


def everything_wrong(repo: Path) -> None:
    for fix in (protected, syntax_error, bulk, locked, forbidden, mail):
        fix(repo)


STATES: dict[str, Callable[[Path], None]] = {
    fn.__name__: fn
    for fn in (
        clean, protected, resurrected, syntax_error, bare_except, duplicate_name, long_line, bulk, growth, locked,
        broken_claim, forbidden, big_file, split_name, deletion, rename, version_alone, thomas_trio, untested, shrunk,
        mail, protected_and_broken, late_stage_refusal_before_early_stage_one, locked_and_forbidden, everything_wrong,
    )
}  # fmt: skip
