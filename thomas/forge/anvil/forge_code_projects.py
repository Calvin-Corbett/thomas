"""Safe repository selection and conversation-to-project persistence."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
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
    if (candidate / ".git").exists():
        # A directory that holds .git IS its own toplevel -- that is precisely
        # what `rev-parse --show-toplevel` would answer, so asking costs a
        # process spawn to learn what the filesystem already said. It is not a
        # micro-optimisation: this function is called once per known project
        # every time the Code history is listed, each call spawns git, and each
        # spawn measured 0.3-0.7s on this machine. Once every task owns a
        # folder that is seconds of stall per project, growing forever.
        # git is still asked whenever there is no .git here, which is the only
        # case where the answer can be a PARENT repository.
        return candidate
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


_PROJECT_NAME_SAFE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_"

# Windows refuses these as a path component no matter what you do with them.
# A folder called CON can be created and then cannot be used: `git init` inside
# it fails with ".git: Invalid argument", and handing it to a subprocess as a
# working directory raises "The directory name is invalid" (both measured here).
# That never mattered while folder names came from a name box; it matters now
# that the name comes from whatever the person typed as their task.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in "0123456789"}
    | {f"LPT{digit}" for digit in "0123456789"}
)

# Long enough to recognise the task, short enough to stay a folder name.
_TASK_NAME_MAX_CHARS = 48


def _safe_project_slug(name: str) -> str:
    """Flatten any string into one folder name that lives where we put it.

    A path separator, a drive letter or a .. would otherwise let the name choose
    where the project is created, so every character outside the safe set is
    dropped rather than escaped -- there is nothing here to escape into.
    """
    raw = " ".join(str(name or "").split()).strip()
    cleaned = "".join(ch for ch in raw if ch in _PROJECT_NAME_SAFE).strip(" -_.")
    slug = cleaned[:64].strip(" -_.") or "New project"
    if slug.upper() in _WINDOWS_RESERVED_NAMES:
        slug = f"{slug} project"
    return slug


def project_name_for_task(task: str) -> str:
    """Name a project after the thing that was asked for.

    The folder is how someone finds this work again months later. "exec-065aad"
    and "code_scratch" tell them nothing; the sentence they typed does.
    """
    return _name_from_task(task) or f"Code task {datetime.now().strftime('%Y-%m-%d %H%M')}"


def _name_from_task(task: str) -> str:
    """The usable part of a task sentence as a folder name -- "" when there is none.

    Split out from :func:`project_name_for_task` so a caller can tell "the task
    named this folder" from "the task was empty and a timestamp stood in". The
    distinction is stamped into the task-born marker at creation, because the
    timestamp SHAPE cannot be trusted later: a person can name a project
    "Code task 2026" themselves.
    """
    first_line = next((line for line in str(task or "").splitlines() if line.strip()), "")
    cleaned = "".join(ch for ch in " ".join(first_line.split()) if ch in _PROJECT_NAME_SAFE).strip(" -_.")
    if len(cleaned) > _TASK_NAME_MAX_CHARS:
        head = cleaned[: _TASK_NAME_MAX_CHARS + 1]
        boundary = head.rfind(" ")
        # Cut on a word boundary unless that would leave a stub too short to
        # recognise, in which case a hard cut still beats a one-word folder.
        cleaned = (head[:boundary] if boundary >= 12 else cleaned[:_TASK_NAME_MAX_CHARS]).strip(" -_.")
    return cleaned


def project_for_new_task(task: str) -> Path:
    """Give a NEW Code task its OWN folder, named after the task.

    Every task that arrived without a chosen project used to be pointed at one
    shared ~/.thomas/code_scratch. Measured on this user's machine: 106 tasks
    bound to that single folder, with index.html written by FIVE different ones,
    each silently replacing the last. Four of their builds are simply gone -- the
    only surviving trace was haunted-arcade.css, an orphaned stylesheet whose
    page no longer exists.

    Reuse before mint, measured 2026-08-05 in the other direction: a QUESTION
    ("look at the project I have selected...") asked three times with nothing
    selected minted three empty siblings -- "...tell me what", "...tell me what
    2", "...tell me what 3" -- because every question is a new task and every
    new task got a fresh folder. Deleting the leftovers is not an option: each
    one holds the question's own transcript under .thomas/. So a folder whose
    run FINISHED as a pure answer (``mark_workspace_reusable``) is claimed by
    the next same-named task instead of minting the next sibling. Only a
    finished answer frees a folder -- two same-named tasks in flight still get
    separate folders, and a folder that gained files keeps its identity.

    Nothing here migrates or moves an existing conversation: a task that is
    already bound keeps the folder it was bound to. This decides where a NEW one
    starts.

    The folder is stamped as task-born on the way out. Measured 2026-08-05: the
    Code UI keeps the last root it was handed and sends it back as
    ``project_root`` on the next new task, so the SECOND task of a session was
    bound into the first task's folder -- the shared-drawer defect reborn, with
    task A's folder playing the drawer. The stamp is what lets
    ``_chosen_project`` in evolve_agent_routes tell "a leftover of the previous
    task" from "a folder somebody actually picked": picks now carry
    ``project_choice: "picked"`` and are honoured, stamps without it are not a
    choice. A failed stamp is logged and swallowed -- an unmarked folder means
    the pre-stamp behaviour for that folder, never a task that cannot start.
    """
    name = project_name_for_task(task)
    reused = _claim_reusable_sibling(_safe_project_slug(name))
    if reused is not None:
        # The folder already carries its stamp, shield, and the previous
        # question's transcript -- reuse must leave all three exactly as they
        # are. Preserving the recorded answer outranks tidiness.
        return reused
    project = create_named_project(name)
    try:
        marker = _task_born_marker(project)
        marker.parent.mkdir(parents=True, exist_ok=True)
        # title_source records whether the TASK named this folder or a
        # timestamp stood in for an empty one. "empty" is what later allows the
        # first real message to rename the folder after itself (New chat binds
        # a folder before any words exist); "task" folders already carry the
        # sentence they were asked for and are never renamed.
        title_source = "task" if _name_from_task(task) else "empty"
        marker.write_text(
            json.dumps({"created_by": "project_for_new_task", "title_source": title_source}) + "\n",
            encoding="utf-8",
        )
    except OSError:
        log.warning("task-born stamp could not be written for %s", project, exc_info=True)
    # Born shielded: the stamp directory doubles as bookkeeping, and even a
    # task-born project's own status output should show the work, not Thomas's
    # internals.
    shield_thomas_dir(project)
    return project


def shield_thomas_dir(root: str | Path) -> None:
    """Plant ``.thomas/.gitignore`` containing ``*`` so Thomas's bookkeeping
    never appears as ``?? .thomas/`` noise in the project's own git status.

    Observed in the user's picked project (w2-code-picked-project): one Code
    run left ``?? .thomas/`` in THEIR ``git status`` forever -- conversation
    transcripts and markers Thomas wrote for itself, presented to the user as
    untracked work they never made. A ``*`` ignore inside the directory hides
    everything in it (including itself) from status without touching the
    project's own ``.gitignore`` or any tracked file.

    Best-effort and idempotent: an existing ``.thomas/.gitignore`` is theirs
    and is left exactly as it is, and a failure to plant is logged, never
    raised -- a project that cannot be shielded must still open.
    """
    try:
        thomas_dir = Path(root).expanduser() / ".thomas"
        thomas_dir.mkdir(parents=True, exist_ok=True)
        ignore = thomas_dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
    except OSError:
        log.warning("could not shield .thomas bookkeeping in %s", root, exc_info=True)


def _task_born_marker(root: str | Path) -> Path:
    return Path(root) / ".thomas" / "created-for-one-task.json"


def is_task_born_project(path: str | Path | None) -> bool:
    """True when a folder was minted by ``project_for_new_task`` for one task.

    Reads the stamp that function writes. Only the stamp is trusted -- the slug
    shape is not, because a person can type a project name that looks exactly
    like a task sentence, and their folder must never be mistaken for a
    leftover.
    """
    if not path:
        return False
    try:
        return _task_born_marker(Path(path).expanduser()).is_file()
    except (OSError, ValueError):
        return False


def _reusable_marker(root: str | Path) -> Path:
    return Path(root) / ".thomas" / "free-for-another-question.json"


def workspace_is_unused(path: str | Path | None) -> bool:
    """True when a folder holds nothing but .git and Thomas's own .thomas dir.

    That is exactly what a question leaves behind: the mint's baseline repo
    plus the bookkeeping (transcript, stamps) Thomas wrote for itself. One
    user file anywhere at the top level makes the folder a workspace with
    work in it, and everything that keys off this must stand down.
    """
    if not path:
        return False
    try:
        entries = list(Path(path).expanduser().iterdir())
    except OSError:
        return False
    return all(entry.name in (".git", ".thomas") for entry in entries)


def mark_workspace_reusable(path: str | Path | None) -> bool:
    """Free a task-born folder that an answer-only run left empty.

    Called by the run recorder when a run finishes as a pure conversation
    (an answer, zero changed files) -- the case measured live 2026-08-05,
    where every question asked with nothing selected minted another empty
    sibling under ~/.thomas/projects. The marker this writes is what lets
    the NEXT same-named question claim the folder instead of minting
    "sentence 2", "sentence 3", ...

    Guarded twice, never raising: only a task-born mint is ever freed (a
    user's own folder is theirs, not a mint to recycle), and only while it
    still holds nothing but .git and .thomas. Returns whether it marked --
    False is not an error, it means the folder earned its identity.
    """
    if not is_task_born_project(path) or not workspace_is_unused(path):
        return False
    try:
        marker = _reusable_marker(Path(path).expanduser())
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('{"freed_by": "answer-only run"}\n', encoding="utf-8")
        return True
    except OSError:
        log.warning("empty task folder %s could not be marked reusable", path, exc_info=True)
        return False


def _claim_reusable_sibling(slug: str) -> Path | None:
    """Claim an existing freed folder of this exact name family, if one exists.

    Matches only ``slug`` and ``slug N`` -- the names ``create_named_project``
    itself would mint -- because the folder name is what the UI's project chip
    shows, and a different question must never inherit a folder named after
    someone else's sentence.

    The unlink IS the claim, mirroring create_named_project's mkdir: two tasks
    arriving together can both see the marker, but only one unlink succeeds,
    and the loser falls through to minting its own folder. Every check is
    re-taken here rather than trusted from marking time, because files may
    have appeared since.
    """
    base = thomas_owned_root() / "projects"
    try:
        siblings = sorted(base.iterdir())
    except OSError:
        return None
    for candidate in siblings:
        name = candidate.name
        if name != slug and not (name.startswith(slug + " ") and name[len(slug) + 1 :].isdigit()):
            continue
        if not candidate.is_dir():
            continue
        if not is_task_born_project(candidate) or not workspace_is_unused(candidate):
            continue
        try:
            _reusable_marker(candidate).unlink()
        except OSError:
            continue  # no marker, or another task claimed it first
        try:
            return candidate.resolve()
        except OSError:
            continue
    return None


def rename_task_born_for_first_message(
    catalog_root: str | Path,
    conversation_id: str,
    project_root: str | Path,
    message: str,
) -> Path:
    """Give a New-chat folder the name its first message just provided.

    Measured (w3-parallel-newtask, 2026-08-05): a task started via New chat got
    the folder "Code task 2026-08-05 2020", because ``conversation_new`` binds a
    folder before any message exists, while the send-first path names folders
    after the task. This runs when that first message finally arrives and
    renames the folder to the message-derived name -- but ONLY when all three
    hold: the folder is task-born and its marker says ``title_source: "empty"``
    (the stamp written at creation, the one precise record that a timestamp
    stood in for a name), the working tree holds no user files yet, and the
    message actually yields a name.

    Failures keep the generic name, silently-visibly: every bail-out is logged
    and the original root is returned, because a folder that keeps a dull name
    is an inconvenience and a run that cannot start is a loss. If the folder is
    renamed but the registry cannot be rewritten, the rename is undone -- a
    registry pointing at a gone directory would strand the conversation.
    """
    try:
        root = Path(project_root).expanduser().resolve()
    except (OSError, ValueError):
        return Path(project_root)
    try:
        payload = json.loads(_task_born_marker(root).read_text(encoding="utf-8"))
        title_source = str(payload.get("title_source") or "") if isinstance(payload, dict) else ""
    except (OSError, ValueError):
        return root
    if title_source != "empty":
        return root
    try:
        has_user_files = any(entry.name not in (".thomas", ".git") for entry in root.iterdir())
    except OSError:
        log.warning("could not inspect %s before renaming; keeping its generic name", root)
        return root
    if has_user_files:
        return root
    wanted = _safe_project_slug(_name_from_task(message)) if _name_from_task(message) else ""
    if not wanted or wanted == root.name:
        return root

    renamed: Path | None = None
    for suffix in range(1, 500):
        candidate = root.parent / (wanted if suffix == 1 else f"{wanted} {suffix}")
        try:
            if candidate.exists():
                continue
            root.rename(candidate)
        except FileExistsError:
            continue
        except OSError:
            log.warning("Code task folder %s could not be renamed to %s; keeping its generic name", root, candidate)
            return root
        renamed = candidate
        break
    if renamed is None:
        log.warning("no free name for renaming %s; keeping its generic name", root)
        return root

    try:
        registry = _load_registry(catalog_root)
        row = registry.get(str(conversation_id or ""))
        if row is not None:
            row["project_root"] = str(renamed)
            _write_registry(catalog_root, registry)
    except OSError:
        # A registry that still points at the old path would strand the
        # conversation, so the rename is rolled back rather than half-kept.
        log.warning("registry could not be rebound after renaming %s; undoing the rename", root, exc_info=True)
        try:
            renamed.rename(root)
        except OSError:
            log.error("rename of %s to %s could not be undone; conversation may need re-binding", root, renamed)
        return root

    try:
        marker = _task_born_marker(renamed)
        marker.write_text(
            json.dumps({"created_by": "project_for_new_task", "title_source": "message"}) + "\n",
            encoding="utf-8",
        )
    except OSError:
        log.warning("task-born stamp could not be refreshed for %s", renamed, exc_info=True)
    log.info("Code task folder renamed for its first message: %s -> %s", root, renamed)
    return renamed


def create_named_project(name: str) -> Path:
    """Make a NEW, ISOLATED project folder under ~/.thomas/projects.

    "New project" previously sent no project_root at all, so the server fell
    back to a single shared scratch repo. Every new project landed in the same
    directory: 26 entries deep with pacman.html, star-catcher.html, museum.html
    and one index.html that each new build overwrote. The user noticed Thomas
    reading games they had made months earlier -- correctly, because those files
    were sitting in its working directory.

    Names are sanitised to a flat folder name. A path separator, a drive letter
    or a .. would otherwise let a project name choose where the project lives.
    """
    slug = _safe_project_slug(name)

    base = thomas_owned_root() / "projects"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ForgeCodeProjectError("project folder could not be created") from exc

    # The mkdir IS the claim. Looking with exists() and creating afterwards
    # leaves a gap where two tasks starting at the same moment both see the name
    # free -- and Thomas runs Code tasks in parallel, so two tasks named alike is
    # the ordinary case, not the exotic one. Losing the race here means taking
    # the next number, never sharing the folder.
    target: Path | None = None
    for suffix in range(1, 500):
        candidate = base / (slug if suffix == 1 else f"{slug} {suffix}")
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ForgeCodeProjectError("project folder could not be created") from exc
        target = candidate
        break
    if target is None:
        raise ForgeCodeProjectError("project folder could not be created")

    # Inside ~/.thomas, so this is Thomas's own tree and initialising is ours to
    # do without asking -- the consent question is only for the user's folders.
    ensure_git_repo(target)
    return target.resolve()


def shared_scratch_root() -> Path:
    """Where the one shared drawer lives, without creating it."""
    return (Path.home() / ".thomas" / "code_scratch").expanduser()


def is_shared_scratch(path: str | Path | None) -> bool:
    """True when a path is the shared drawer rather than a project.

    Needed because the drawer now arrives dressed as a choice. The Code UI saves
    whichever root it was handed and sends it back as ``project_root`` on the
    next new task -- and until now the answer was always this folder, so it is
    sitting in browsers today (observed in the live UI: the project chip read
    "code_scratch"). Nothing in the product can actually have chosen it: the
    picker offered 123 projects and the drawer was not one of them.
    """
    if not path:
        return False
    try:
        candidate = Path(path).expanduser().resolve()
        scratch = shared_scratch_root().resolve()
    except (OSError, ValueError):
        return False
    return candidate == scratch or scratch in candidate.parents


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
    # Binding is the moment Thomas commits to writing its bookkeeping under
    # this root (conversation transcripts land in <root>/.thomas/...), so it is
    # the moment to keep that bookkeeping out of the project's git status.
    shield_thomas_dir(root)
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


def resolve_conversation_root(catalog_root: str | Path, conversation_id: str) -> Path:
    """The root a conversation's file is ACTUALLY in, not the one it is filed under.

    ``conversation_project`` answers from the registry, and falls back to the
    catalog root when a conversation has no row. Plenty have none -- they were
    written straight into a project by a path that never called
    ``bind_conversation`` -- so that fallback names a folder the file is not in,
    and every read through it comes back empty.

    An empty read is the dangerous part: it is indistinguishable from "this
    conversation has nothing in it", so callers treat it as a fact rather than a
    miss. Measured on this workspace, the CLI's multi-turn history did exactly
    that -- ``history_turns(repo_root, cid)`` returned 0 turns for **110 of 113**
    conversations that have real turns, and the caller's own comment described
    the empty result as the normal no-history case.

    So this checks the binding first and then walks the same roots the Code
    history endpoint walks. The conversation id itself is the check: a root that
    does not hold the file is skipped, and if none does, the binding is returned
    unchanged so the caller's own not-found handling still runs.
    """

    catalog = Path(catalog_root)
    bound = conversation_project(catalog, conversation_id)
    if not conversation_id:
        return bound
    if _conversation_file(bound, conversation_id).is_file():
        return bound
    for root in conversation_roots(catalog):
        if root != bound and _conversation_file(root, conversation_id).is_file():
            return root
    return bound


def _conversation_file(root: Path, conversation_id: str) -> Path:
    """Where a conversation's JSON lives under ``root``.

    Kept beside the resolver rather than imported from ``forge_code_store``:
    this module sits UNDER the store in the import order, and reaching upward
    for one path join would invert that for no benefit. The layout is asserted
    against the store's own resolver in
    ``tests/test_forge_code_projects.py`` so the two cannot drift apart.
    """

    return Path(root) / ".thomas" / "evolve" / "agent" / "conversations" / f"{conversation_id}.json"


def forget_conversation(catalog_root: str | Path, conversation_id: str) -> None:
    registry = _load_registry(catalog_root)
    if registry.pop(str(conversation_id or ""), None) is not None:
        _write_registry(catalog_root, registry)
