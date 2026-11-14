"""What an outside agent's change is checked for before it is handed in.

Thomas's own changes are checked before your card by a server that needs a green copy and an execution id
(thomas/server/precard); an outside change has neither, so the checks that can run without them run here and their
words go into the hand-in's ``checked`` line. Nothing here starts a process of its own: git goes through
``hand_in_outside_build.git`` (``scripts.pipeline_canary.act._git`` with the clone's config switched off) and ruff through ``thomas.server.precard.lint``, both already counted launches.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import tomllib

from scripts.crew.hand_in_outside_build import Change, Refusal, git

# Always guarded, and all that is when the checkout's agent_safety.toml cannot be read.
FALLBACK_PROTECTED = (
    "agent_safety.toml", "AGENTS.md", "GUARDRAILS.md", "pyproject.toml", ".pre-commit-config.yaml",
    "tests/test_architecture.py", "thomas/_architecture.py", "docs/monolith_guard_baseline.json",
)  # fmt: skip
_LISTS = ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts")
DEFAULT_GROWTH = 300


def dev_tip(checkout: Path, branch: str) -> str:
    """The commit the promoter applies changes to: the checkout's *branch*, else its HEAD; "" when unread."""
    for ref in (f"refs/heads/{branch}", "HEAD"):
        try:
            return git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
        except ValueError:
            continue
    return ""


def applies_to(checkout: Path, tip: str, patch: bytes) -> str:
    """ "" when *patch* applies to *tip*; else git's words. Uses a temporary index, so nothing in the checkout moves."""
    with tempfile.TemporaryDirectory(prefix="outside-index-") as folder:
        env = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        try:
            git(checkout, "read-tree", tip, env=env)
            git(checkout, "apply", "--cached", "--check", "-", env=env, stdin=patch)
        except ValueError as exc:
            return str(exc)
    return ""


def promoter_refusal(patch: bytes, checkout: Path) -> tuple[str, str]:
    """(refusal, note): the promoter's own write-safety verdict on *patch*; the note says when it could not be asked."""
    try:
        from scripts.cage import self_change_checks as checks
    except ImportError as exc:
        return "", f"the promoter's write-safety check could not be loaded ({exc}); not run"
    return checks.write_safety_refusal(patch.decode("utf-8", errors="replace"), checkout) or "", ""


def protected_paths(checkout: Path, tip: str, files: list[str]) -> list[str]:
    """Which of *files* the checkout guards: agent_safety.toml's lists, else the fallback; plus the promoter's gate,
    cage and approval classes (scripts/cage/card_catalogue.danger_class), each of which gets a card of its own."""
    names = set(FALLBACK_PROTECTED)
    try:
        table = tomllib.loads(git(checkout, "cat-file", "blob", f"{tip}:agent_safety.toml").decode("utf-8")).get(
            "protected", {}
        )
        listed = {str(item) for key in _LISTS for item in table.get(key, []) if isinstance(item, str)}
        names |= listed  # the fallback always stands: a short list never unguards agent_safety.toml
    except (ValueError, tomllib.TOMLDecodeError, AttributeError, UnicodeDecodeError):
        pass  # unreadable or absent: the fallback list stands

    def guarded(path: str) -> bool:
        return any(path == n or (n.endswith("/") and path.startswith(n)) for n in names)

    try:
        from scripts.cage import card_catalogue
    except ImportError:
        card_catalogue = None
    return [
        path
        for path in files
        if guarded(path) or (card_catalogue is not None and card_catalogue.danger_class(path) is not None)
    ]


def growth_findings(change: Change) -> tuple[list[str], str]:
    """Files whose squashed change grows them by more lines than the commit growth guard allows (a new file counts in
    full). The second value is a note when the limit could not be read from the guard."""
    note = ""
    limit = DEFAULT_GROWTH
    try:
        from scripts.forge.gates import commit_growth_guard

        limit = int(commit_growth_guard.DEFAULT_MAX_GROWTH)
    except (ImportError, AttributeError, ValueError):
        note = f"the commit growth guard could not be loaded; {DEFAULT_GROWTH} lines assumed"
    stat = git(
        change.clone, "diff-tree", "-r", "--numstat", "-z", "--no-renames", "--no-ext-diff", change.base, change.tip
    ).decode("utf-8", "replace")
    found = []
    for entry in filter(None, stat.split("\0")):
        added, _, rest = entry.partition("\t")
        removed, _, name = rest.partition("\t")
        if added.isdigit() and removed.isdigit() and int(added) - int(removed) > limit:
            found.append(f"{name} grows by {int(added) - int(removed)} lines (the limit is {limit} in one commit)")
    return found, note


def _parents(name: str) -> list[str]:
    """The folders above *name*: pkg/sub/x.py gives pkg and pkg/sub."""
    parts = name.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


# Names Python looks for and runs on its own when it starts beside them. A change that brings one is not linted.
_RUNS_ON_START = ("sitecustomize.py", "usercustomize.py", "ruff.py")


def startup_files(files: list[str]) -> list[str]:
    """Which of *files* Python could run by itself if ruff were started near them: sitecustomize.py, usercustomize.py,
    ruff.py, anything inside a folder named ruff, and any .pth file."""
    found = []
    for name in files:
        parts = [part.lower() for part in name.split("/")]
        if parts[-1] in _RUNS_ON_START or parts[-1].endswith(".pth") or "ruff" in parts[:-1]:
            found.append(name)
    return found


def unsafe_name(name: str) -> str:
    """Why *name* may not be written under the lint folder, or "". Judges the text only; :func:`lint_target` also looks
    at where the joined path lands."""
    parts = name.split("/")
    if not name or "\0" in name:
        return "it is empty or holds a NUL character"
    if "\\" in name or ":" in name:
        return "it holds a backslash or a colon"
    if name.startswith("/"):
        return "it is an absolute path"
    for part in parts:
        if part in ("", ".", ".."):
            return "it has an empty, '.' or '..' part"
        if part.startswith("-"):
            return "it has a part starting with a dash, which ruff would read as an option"
        if part.lower().startswith(".git"):
            return "it has a part starting with .git"
    return ""


def lint_target(root: Path, side: str, name: str) -> Path:
    """Where *name* goes under root/side, or a Refusal saying what was refused and why. Nothing is skipped quietly."""
    why = unsafe_name(name)
    base = (root / side).resolve()
    target = (base / name) if not why else base
    if not why and not target.resolve().is_relative_to(base):
        why = "it would land outside the lint folder"
    if why:
        raise Refusal(
            f"The change names a path I will not write into the lint folder: {name!r} ({why}). "
            "Nothing was linted and nothing was handed in."
        )
    return target


def ruff_findings(change: Change) -> tuple[bool, str, list[str]]:
    """What ruff check and ruff format --check say the change adds. Files are read out of git into two temporary
    folders, so the clone is not touched."""
    wanted = [name for name in change.files if name.endswith(".py")]
    if not wanted:
        return True, "", []
    packages = sorted({f"{parent}/__init__.py" for name in wanted for parent in _parents(name)})
    for name in [*wanted, *packages]:
        lint_target(Path("."), "change", name)  # every name is judged before anything is made or run
    risky = startup_files(change.files)
    if risky:
        return False, (
            "linting was skipped: the change adds " + ", ".join(risky) + ", which Python could run as soon as ruff "
            "starts. Read those files yourself; nothing of this change was run."
        ), []  # fmt: skip
    try:
        from thomas.server.precard import ruff_findings
    except ImportError as exc:
        return False, f"ruff's runner could not be loaded ({exc})", []
    with (
        tempfile.TemporaryDirectory(prefix="outside-ruff-") as folder,
        tempfile.TemporaryDirectory(prefix="outside-ruff-cwd-") as trusted,
    ):
        root = Path(folder)
        # Ruff tells first-party imports from the rest by which top-level folders exist, so make them (empty), with the __init__.py that makes each a package.
        listing = git(change.clone, "ls-tree", "-d", "--name-only", "-z", change.tip).decode("utf-8", "replace")
        # A folder named .github or .claude can never be an import, so it is not mirrored. Any other odd name stays in the
        # list, where lint_target refuses it.
        tops = [name for name in listing.split(chr(0)) if name and not re.fullmatch(r"\.[A-Za-z0-9_-]+", name)]
        for name in tops:
            lint_target(root, "change", name)
        for side, rev in (("base", change.base), ("change", change.tip)):
            for name in tops:
                lint_target(root, side, name).mkdir(parents=True, exist_ok=True)
            for name in [*wanted, "pyproject.toml", *packages]:
                try:
                    data = git(
                        change.clone, "cat-file", "blob", f"{rev if name != 'pyproject.toml' else change.tip}:{name}"
                    )
                except ValueError:
                    continue  # a file the change adds is not in base
                target = lint_target(root, side, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        result = ruff_findings(
            lambda: root / "base", root / "change", wanted, python=sys.executable, data_dir=root / "data",
            trusted_cwd=Path(trusted),
        )  # fmt: skip
    if not result.ran:
        return False, result.why, []
    return True, "", [*result.added, *(f"{name}: ruff format would change it" for name in result.unformatted)]
