"""Safe repository selection and conversation-to-project persistence."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class ForgeCodeProjectError(ValueError):
    """Raised when a requested Forge Code project is not a usable repository."""


def _git(args: list[str], *, cwd: Path | str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    """Run git against a folder the user explicitly chose.

    ``safe.directory`` is set for that one invocation, and only that one. Git
    refuses to read a repository whose directory is owned by a different OS
    account -- "detected dubious ownership" -- which protects you from a hostile
    repo dropped on a shared machine. On this user's box the whole F:\\DevHub
    tree carries a SID from a previous Windows install, so every project on that
    drive was unreadable: the folder could not be inspected, could not be
    initialised, and could not be opened. Two of their real projects live there.

    Naming the exact path scopes the trust to the folder the user just picked,
    and touches no global git config. It is not a blanket `safe.directory=*`,
    and it never runs against a path the user did not choose.
    """
    root = str(cwd)
    return subprocess.run(
        ["git", "-c", f"safe.directory={root}", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


class ForgeCodeHistoryRequired(ForgeCodeProjectError):
    """The folder is usable, but it has no version history and nobody has said
    whether that is acceptable.

    Distinct from ForgeCodeProjectError so a caller can offer the choice instead
    of reporting a dead end. ``project_path`` is the resolved directory, so the
    caller can name it and act on it without re-resolving.
    """

    def __init__(self, message: str, *, project_path: Path) -> None:
        super().__init__(message)
        self.project_path = project_path


def validate_project_root(
    value: str | Path | None,
    *,
    fallback: str | Path,
    allow_without_history: bool = False,
) -> Path:
    """Resolve ``value`` to its containing git repository root.

    Change attribution and Revert are git-backed, so a folder with no history
    cannot offer them. That is a reason to SAY SO, not a reason to refuse: 117 of
    the 121 projects in this user's library had no .git, and every one of them was
    unopenable. The error even promised that Thomas "asks first" for your own
    folders -- nothing anywhere asked. It was a wall with a sign describing a door
    that did not exist.

    So a folder without history now raises ForgeCodeHistoryRequired, which the
    caller turns into a choice. Pass ``allow_without_history=True`` once someone
    has actually chosen to work without undo, and the directory itself is
    returned. Every existing caller keeps the old refusing behaviour by default.
    """

    raw = Path(value).expanduser() if value else Path(fallback)
    if not raw.is_absolute():
        raise ForgeCodeProjectError("project_root must be an absolute path")
    try:
        candidate = raw.resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeProjectError("project_root does not exist") from exc
    if not candidate.is_dir():
        raise ForgeCodeProjectError("project_root must be a directory")
    try:
        proc = _git(["rev-parse", "--show-toplevel"], cwd=candidate)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ForgeCodeProjectError("project_root could not be inspected") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        if allow_without_history:
            # Chosen deliberately: work here with no undo. The directory itself
            # is the root -- there is no repository to take a toplevel from.
            return candidate
        raise ForgeCodeHistoryRequired(
            "project_root must be inside a git repository",
            project_path=candidate,
        )
    try:
        root = Path(proc.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeProjectError("git reported an unavailable repository root") from exc
    if not root.is_dir():
        raise ForgeCodeProjectError("git repository root is not a directory")
    return root


def thomas_source_repo_root() -> Path | None:
    """Absolute git-toplevel of Thomas's OWN source checkout, if it is one.

    Code runs must NEVER be pointed here: a "make me a game" ask would write
    into the product tree and its change-attribution/Revert UI would sweep up
    unrelated edits. Used as a hard safety net that rejects this path.
    """
    try:
        import thomas

        pkg = Path(thomas.__file__).resolve().parent  # .../thomas
        proc = subprocess.run(
            ["git", "-C", str(pkg.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError, ImportError, ValueError):
        return None
    return None


def thomas_owned_root() -> Path:
    """The ~/.thomas tree: folders Thomas itself creates and manages."""
    return (Path.home() / ".thomas").expanduser()


def is_thomas_owned(path: str | Path) -> bool:
    """True when a path lives inside Thomas's own data directory.

    Only these are safe to git-init automatically. A folder the user browsed to
    on their PC is theirs, and silently creating a .git in it is not ours to do.
    """
    try:
        candidate = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return False
    try:
        candidate.relative_to(thomas_owned_root().resolve())
    except (OSError, ValueError):
        return False
    return True


def ensure_git_repo(path: str | Path) -> bool:
    """Make a Thomas-owned folder bindable by Code. Returns True if it initialised one.

    Code requires a git toplevel because that is what Revert and change
    attribution are built on -- Revert is literally ``git checkout -- <file>``.
    But Thomas writes every app it builds into ``~/.thomas/workspaces/<exec-id>``
    and never inits one, so the 913 apps it has made for the user were all
    unopenable: the picker offered them and binding them returned
    "project_root must be inside a git repository".

    Initialising is the smaller, safer half of the fix. It only ever touches
    Thomas's own tree; anything outside it is refused here and handled by the
    caller, because putting a .git in a user's folder without asking is not a
    thing a tool should do quietly.
    """
    candidate = Path(path).expanduser()
    if not is_thomas_owned(candidate):
        return False
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ForgeCodeProjectError("project folder could not be created") from exc
    if (candidate / ".git").exists():
        return False
    try:
        # The directory is passed as the working directory, never as a
        # positional argument. git parses a leading "--" as an option, so a
        # folder literally named --template=<dir> would become one -- and that
        # option copies hooks out of the named directory, which then run on the
        # next git command. Naming a folder cannot be allowed to choose a flag.
        proc = subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=str(candidate),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ForgeCodeProjectError("project folder could not be prepared for editing") from exc
    if proc.returncode != 0:
        raise ForgeCodeProjectError(
            f"project folder could not be prepared for editing: {proc.stderr.strip()[:200]}"
        )
    _seal_initial_commit(candidate)
    return True


def initialize_history(path: str | Path) -> Path:
    """Give a folder version history because someone asked for it.

    ``ensure_git_repo`` deliberately refuses anything outside ~/.thomas: putting
    a .git in someone's own folder unasked is not a tool's decision. This is the
    other half -- the same operation, reached only after an explicit choice. It
    is why the caller can now offer that choice instead of reporting a dead end.

    Thomas's own source checkout is refused outright and no consent unlocks it:
    a "make me a game" run must never be able to edit the product tree, where
    Revert would sweep up unrelated work.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ForgeCodeProjectError("project_root must be an absolute path")
    try:
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise ForgeCodeProjectError("project_root does not exist") from exc
    if not candidate.is_dir():
        raise ForgeCodeProjectError("project_root must be a directory")

    source_root = thomas_source_repo_root()
    if source_root is not None:
        try:
            candidate.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise ForgeCodeProjectError("project_root must not be inside Thomas's own source tree")

    if (candidate / ".git").exists():
        return candidate
    try:
        proc = _git(["init", "--initial-branch=main"], cwd=candidate)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ForgeCodeProjectError("project folder could not be prepared for editing") from exc
    if proc.returncode != 0:
        raise ForgeCodeProjectError(
            f"project folder could not be prepared for editing: {proc.stderr.strip()[:200]}"
        )
    _seal_initial_commit(candidate)
    return candidate


def _seal_initial_commit(root: Path) -> None:
    """Record what was already there, so the first edit can be undone.

    An initialised repo with no commits is not revertible: Revert is
    ``git checkout -- <file>`` and change attribution is ``git status``, both of
    which need a baseline. Without this, opening an app Thomas built would let
    it be edited and leave no way back to the version that worked.

    Best effort by design -- failing to seal must not stop someone opening their
    project, it only means the first edit has no prior version to compare with.
    """
    identity = [
        "-c",
        "user.name=Thomas",
        "-c",
        "user.email=thomas@localhost",
        "-c",
        "commit.gpgsign=false",
    ]
    try:
        head = _git(["rev-parse", "--verify", "HEAD"], cwd=root)
        if head.returncode == 0:
            return  # already has history
        _git([*identity, "add", "-A"], cwd=root, timeout=30)
        _git(
            [
                *identity,
                "commit",
                "--allow-empty",
                "-m",
                "Baseline: contents before Thomas opened this project",
            ],
            cwd=root,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
        log.warning("could not seal a baseline commit in %s: %s", root, exc)


def default_scratch_project(catalog_root: str | Path) -> Path:
    """Default project for a NEW Code conversation when the user picked none.

    The scratch repo is anchored in the user's HOME (``~/.thomas/code_scratch``),
    deliberately OUTSIDE any Thomas checkout: when the server runs from the repo
    with a repo-relative data dir, a data-dir-relative scratch path sits inside
    the repo working tree, so ``git rev-parse --show-toplevel`` walks up to the
    repo root and Code edits the product source (observed 2026-07-19). A
    home-anchored scratch has its OWN git toplevel. A real project is still one
    "Choose project folder" click away.
    """

    scratch = (Path.home() / ".thomas" / "code_scratch").expanduser()
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        if not (scratch / ".git").exists():
            # cwd rather than a positional path, for the same reason as
            # ensure_git_repo: a directory name must never be able to act as a
            # git option.
            proc = subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=str(scratch),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                raise ForgeCodeProjectError(f"scratch project git init failed: {proc.stderr.strip()[:200]}")
    except OSError as exc:
        raise ForgeCodeProjectError("scratch project directory could not be created") from exc
    resolved = validate_project_root(scratch, fallback=scratch)
    repo = thomas_source_repo_root()
    if repo is not None and resolved == repo:
        # Scratch somehow still resolved to the Thomas repo (e.g. HOME is inside
        # the checkout). Fail loudly rather than silently editing the product.
        raise ForgeCodeProjectError("scratch project resolved to the Thomas source repo; refusing")
    return resolved


def _registry_path(catalog_root: str | Path) -> Path:
    directory = Path(catalog_root) / ".thomas" / "evolve" / "agent"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "project_registry.json"


def _load_registry(catalog_root: str | Path) -> dict[str, dict[str, Any]]:
    path = _registry_path(catalog_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(cid): row for cid, row in payload.items() if isinstance(row, dict)}


def _write_registry(catalog_root: str | Path, registry: dict[str, dict[str, Any]]) -> None:
    path = _registry_path(catalog_root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def bind_conversation(
    catalog_root: str | Path,
    conversation_id: str,
    project_root: str | Path,
    *,
    settings: dict[str, Any] | None = None,
    allow_without_history: bool = False,
) -> dict[str, Any]:
    """Persist the selected repository and settings for one Code conversation.

    ``allow_without_history`` has to be threaded through: the caller has already
    resolved the root and, for a folder opened deliberately without undo, this
    second validation would otherwise reject what was just accepted.
    """

    cid = str(conversation_id or "").strip()
    if not cid:
        raise ForgeCodeProjectError("conversation_id is required")
    root = validate_project_root(
        project_root,
        fallback=catalog_root,
        allow_without_history=allow_without_history,
    )
    registry = _load_registry(catalog_root)
    row = {"project_root": str(root), "settings": dict(settings or {})}
    registry[cid] = row
    _write_registry(catalog_root, registry)
    return dict(row)


def update_conversation_settings(
    catalog_root: str | Path,
    conversation_id: str,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    registry = _load_registry(catalog_root)
    row = registry.get(str(conversation_id or ""))
    if row is None:
        return None
    row["settings"] = dict(settings)
    _write_registry(catalog_root, registry)
    return dict(row)


def conversation_metadata(catalog_root: str | Path, conversation_id: str) -> dict[str, Any] | None:
    row = _load_registry(catalog_root).get(str(conversation_id or ""))
    return dict(row) if row is not None else None


def conversation_project(catalog_root: str | Path, conversation_id: str) -> Path:
    """Return a validated bound project, falling back for legacy conversations."""

    row = conversation_metadata(catalog_root, conversation_id)
    selected = row.get("project_root") if row else catalog_root
    return validate_project_root(selected, fallback=catalog_root)


def conversation_roots(catalog_root: str | Path) -> list[Path]:
    """Return unique, still-valid roots that may hold Code conversations."""

    roots: list[Path] = []
    candidates: list[str | Path] = [catalog_root]
    candidates.extend(
        row.get("project_root", "") for row in _load_registry(catalog_root).values() if row.get("project_root")
    )
    for candidate in candidates:
        try:
            root = validate_project_root(candidate, fallback=catalog_root)
        except ForgeCodeProjectError:
            continue
        if root not in roots:
            roots.append(root)
    return roots


def forget_conversation(catalog_root: str | Path, conversation_id: str) -> None:
    registry = _load_registry(catalog_root)
    if registry.pop(str(conversation_id or ""), None) is not None:
        _write_registry(catalog_root, registry)
