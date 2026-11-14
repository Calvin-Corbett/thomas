"""Read-only readers for the Praxis timeline (``scripts/praxis_timeline.py``).

Nothing here writes, makes a folder or asks a server. Conversations come from the catalog checkout's
``.thomas/evolve/agent/conversations``, each green root's work trees, and wherever the catalog's project registry binds
one (which finds a green no root names); a place this account cannot read is reported, never skipped silently. Build
runs come from their transcripts' file times; checks from ``hand_in_clocks.jsonl``; commits from read-only ``git``. The
cage folder is read by ``timeline_cage``. The names of those places are copied here rather than imported: the modules
that own them make the folder when asked (``forge_code_store.conversations_dir``,
``forge_code_conversations._registry_path``, ``evolve_agent_runtime._agent_dir``) or load the tool registry
(``thomas.tools``). ``tests/test_the_timeline_reads_only_and_names_no_one.py`` and
``tests/test_the_timeline_reports_what_it_cannot_read.py`` keep the copies equal to the originals.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAGE_ROOT_ENV = "THOMAS_CAGE_ROOT"
DEFAULT_CAGE_ROOT = Path(r"C:\ProgramData\ThomasCage")
AGENT_DIR = Path(".thomas") / "evolve" / "agent"
CONVERSATIONS = AGENT_DIR / "conversations"
PROJECT_REGISTRY = AGENT_DIR / "project_registry.json"
CLOCKS_FILE = "hand_in_clocks.jsonl"
_CID = re.compile(r"fc_(\d{8}T\d{6})_")
_SHA = re.compile(r"[0-9a-fA-F]{4,64}")
_REGISTERED_CID = re.compile(r"fc_\d{8}T\d{6}_\w+")  # a name, never a path: the key is made into a file name


@dataclass(frozen=True)
class Paths:
    """Where the timeline reads: the catalog, the cage folder, and green roots (each holds ``work/<exec>/...``)."""

    catalog: Path
    cage: Path
    greens: Path | None
    dev_branch: str = "dev"
    more_greens: tuple[Path, ...] = ()

    @property
    def green_roots(self) -> list[Path]:
        return [Path(root) for root in (self.greens, *self.more_greens) if root is not None]

    @property
    def agent_dir(self) -> Path:
        return Path(self.catalog) / AGENT_DIR


def iso_to_epoch(value: object) -> float | None:
    """Seconds since the epoch for an ISO time or a number; a time with no zone is this machine's local time."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return (moment if moment.tzinfo is not None else moment.astimezone()).timestamp()
    except (ValueError, OverflowError, OSError):  # not a time, or one this machine's clock cannot place
        return None


def cid_epoch(cid: str) -> float | None:
    """When a conversation started, from its id ``fc_YYYYMMDDTHHMMSS_...`` (UTC, as forge_code_store names it)."""
    found = _CID.match(str(cid or ""))
    if found is None:
        return None
    try:
        return datetime.strptime(found.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, OverflowError, OSError):  # the digits match but are not a date: fc_20261399T250000_...
        return None


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def file_times(path: Path) -> dict[str, float] | None:
    """A file's creation time (``st_birthtime`` where the system keeps one), last write and size; None if unread."""
    try:
        status = Path(path).stat()
    except OSError:
        return None
    created = getattr(status, "st_birthtime", None)
    return {
        "created": float(created if created is not None else status.st_ctime),
        "modified": float(status.st_mtime),
        "size": float(status.st_size),
    }


def _note(problems: list[dict[str, str]] | None, cid: str, where: Path, error: OSError) -> None:
    """Record a place this account could not read; one that is not there (FileNotFoundError) is no problem."""
    if problems is not None and not isinstance(error, FileNotFoundError):
        problems.append({"conversation_id": cid, "where": str(where), "error": type(error).__name__})


def _project_folders(paths: Paths, problems: list[dict[str, str]] | None) -> list[Path]:
    folders = [Path(paths.catalog) / CONVERSATIONS]
    for root in paths.green_roots:
        try:
            works = sorted(path for path in (root / "work").iterdir() if path.is_dir())
        except OSError as error:
            _note(problems, "", root / "work", error)
            works = []
        folders += [work / CONVERSATIONS for work in works]
    return folders


def _registered(catalog: Path, since: float, problems: list[dict[str, str]] | None) -> list[tuple[str, Path]]:
    """(conversation id, folder) for each conversation started since *since* that the catalog's registry binds to one.

    This finds a conversation in a green that no root names, such as the caged account's, from the catalog alone.
    """
    registry = Path(catalog) / PROJECT_REGISTRY
    try:
        rows = json.loads(registry.read_text(encoding="utf-8-sig"))
    except OSError as error:
        _note(problems, "", registry, error)
        return []
    except ValueError:
        return []
    if not isinstance(rows, dict):
        return []
    found = []
    for cid, row in rows.items():
        root = row.get("project_root") if isinstance(row, dict) else None
        if isinstance(root, str) and root.strip() and _REGISTERED_CID.fullmatch(str(cid)):
            if (cid_epoch(str(cid)) or 0.0) >= since:
                found.append((str(cid), Path(root)))
    return found


def _candidates(paths: Paths, since: float, problems: list[dict[str, str]]) -> Iterator[Path]:
    """Every conversation file started since *since*: each project folder's listing, then the registry's bindings."""
    tried: set[Path] = set()
    for folder in _project_folders(paths, problems):
        try:
            names = sorted(path for path in folder.iterdir() if path.suffix == ".json")
        except OSError as error:
            _note(problems, "", folder, error)
            continue
        for path in names:
            if (cid_epoch(path.stem) or 0.0) >= since and path not in tried:
                tried.add(path)
                yield path
    for cid, root in _registered(paths.catalog, since, problems):
        path = root / CONVERSATIONS / f"{cid}.json"
        if path not in tried:
            tried.add(path)
            yield path


def _read_conversation(path: Path, problems: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except OSError as error:
        _note(problems, path.stem, path, error)
        return None
    if b'"thomas_project"' not in raw:  # most conversations are ordinary Build work: skipped unparsed
        return None
    try:
        conversation = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(conversation, dict) or conversation.get("id") != path.stem:
        return None
    project = conversation.get("thomas_project")
    return conversation if isinstance(project, dict) and project.get("execution_id") else None


def load_conversations(
    paths: Paths, since: float, unreadable: list[dict[str, str]] | None = None
) -> dict[str, dict[str, Any]]:
    """Every Thomas project conversation started at or after *since*, by id, from the catalog and every green.

    A green holds its team's copy while it builds and the catalog holds the copy handed in; the one written last
    (``updated_at``) says where the project stands. Every project is read, not only the newest 20 the listing shows.

    A file or folder this account could not read (a permission error, not a missing file) is appended to *unreadable*
    as ``{"conversation_id", "where", "error"}`` (the id is "" for a folder); an entry is dropped once the same
    conversation was read from another source.
    """
    found: dict[str, dict[str, Any]] = {}
    problems: list[dict[str, str]] = []
    for path in _candidates(paths, since, problems):
        conversation = _read_conversation(path, problems)
        if conversation is None:
            continue
        held = found.get(path.stem)
        written = iso_to_epoch(conversation.get("updated_at")) or 0.0
        if held is None or written >= (iso_to_epoch(held.get("updated_at")) or 0.0):
            found[path.stem] = conversation
    if unreadable is not None:
        unreadable.extend(problem for problem in problems if problem["conversation_id"] not in found)
    return found


def load_clocks(catalog: Path) -> list[dict[str, Any]]:
    """Every record in ``hand_in_clocks.jsonl``; a line that is not a JSON object is skipped."""
    try:
        lines = (Path(catalog) / AGENT_DIR / CLOCKS_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def transcript_name(run_id: str) -> str:
    """A Build run's transcript file name (``evolve_agent_runtime._transcript_path``)."""
    return f"transcript-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:16]}.txt"


def transcript_times(agent_dir: Path, run_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    name = transcript_name(run_id)
    times = file_times(Path(agent_dir) / name)
    return {**times, "file": name} if times else None


def transcript_index(agent_dir: Path, since: float) -> list[tuple[float, float, float, str]]:
    """(created, modified, size, name) of every run transcript created since an hour before *since*.

    It finds a run that never recorded its own agent turn (a restart cut it) by when it started.
    """
    rows: list[tuple[float, float, float, str]] = []
    for path in Path(agent_dir).glob("transcript-*.txt"):
        times = file_times(path)
        if times and times["created"] >= since - 3600:
            rows.append((times["created"], times["modified"], times["size"], path.name))
    return sorted(rows)


def git_commit(repo: Path, sha: str, branch: str = "dev") -> dict[str, Any] | None:
    """When *sha* was committed and whether *branch* holds it, by read-only git.

    None unless *sha* is 4 to 64 hex digits: it is read from a file a Build team can write, and ``git show`` honours
    ``--output=<file>``. ``--end-of-options`` keeps *sha* and *branch* from being read as options. ``on_dev`` is None
    when git could not say: ``merge-base --is-ancestor`` exits 0 for yes, 1 for no and anything else for a failure.
    """
    if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
        return None
    try:
        shown = subprocess.run(
            ["git", "-C", str(repo), "show", "-s", "--format=%H%x09%cI", "--end-of-options", sha],
            capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
        if shown.returncode or not shown.stdout.strip():
            return {"sha": sha, "found": False}
        full, committed = shown.stdout.strip().split("\t", 1)
        held = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "--end-of-options", full, branch],
            capture_output=True, timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"sha": sha, "found": False}
    return {
        "sha": full,
        "committed_epoch": iso_to_epoch(committed),
        "on_dev": {0: True, 1: False}.get(held.returncode),
        "found": True,
    }


__all__ = [
    "AGENT_DIR",
    "CAGE_ROOT_ENV",
    "CLOCKS_FILE",
    "CONVERSATIONS",
    "DEFAULT_CAGE_ROOT",
    "PROJECT_REGISTRY",
    "Paths",
    "cid_epoch",
    "file_times",
    "git_commit",
    "iso_to_epoch",
    "load_clocks",
    "load_conversations",
    "read_json",
    "transcript_index",
    "transcript_name",
    "transcript_times",
]
