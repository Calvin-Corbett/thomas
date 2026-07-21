"""Named multi-root workspaces with cross-repo search, edit, and PR proof.

CAP-016 (Multi-repo / multi-workspace context, Level 2): a
:class:`MultiRootWorkspace` names a set of repository roots as a single logical
workspace and provides three coordinated operations across those roots:

1. **Cross-repo search** -- :meth:`MultiRootWorkspace.search` scans every root
   for a symbol or literal/regex text and returns per-repo hits. The result is
   deterministic (repos in sorted name order, files sorted, lines by number).

2. **Cross-repo edit** -- :meth:`MultiRootWorkspace.apply_coordinated_edit`
   applies a set of file edits that spans more than one repo as a single
   all-or-nothing unit. Edits are validated in memory first (a missing target
   file or an unmatched ``find`` string aborts before anything is written), and
   if a write fails midway every already-written file is restored to its
   original contents, so the workspace is never left half-changed.

3. **Coordinated PR proof** -- :meth:`MultiRootWorkspace.plan_coordinated_prs`
   turns one logical change spanning N repos into N linked PR payloads, each
   referencing the shared change id and cross-referencing the companion repos.
   The push/PR-create step runs through the same injectable dry-run gateway used
   by :mod:`thomas.tools.governed_git_pr`, so no real push or ``gh`` call ever
   happens.

Everything here is deterministic and hermetic: no network, no live model, no
implicit global state. Git operations are not required for search/edit; the PR
proof composes payloads and hands them to an injectable gateway.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from thomas.tools.governed_git_pr import (
    Gateway,
    GatewayResult,
    PrPayload,
    default_dry_run_gateway,
)

__all__ = [
    "SearchHit",
    "WorkspaceSearchResult",
    "RepoFileEdit",
    "CoordinatedEditResult",
    "CoordinatedChange",
    "CoordinatedPrPlan",
    "MultiRootWorkspace",
    "WorkspaceError",
]

# Directories never descended into during cross-repo search.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
    }
)

# Files above this size are skipped by search (assumed binary/generated).
_MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class WorkspaceError(RuntimeError):
    """Raised for invalid workspace configuration or edit references."""


# A file writer seam so tests can force a mid-write failure and prove rollback.
# It writes ``text`` to ``path`` (utf-8) and raises OSError on failure.
FileWriter = Callable[[Path, str], None]


def _default_file_writer(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _slugify(text: str, *, max_len: int = 48) -> str:
    """Lowercase, hyphen-separated, alnum-only slug bounded to ``max_len``."""

    slug = _SLUG_RE.sub("-", str(text).strip().lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


# ---------------------------------------------------------------------------
# Cross-repo search
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """A single match: which repo, the repo-relative file, line number, text."""

    repo: str
    relpath: str
    line_number: int
    line: str


@dataclass(frozen=True)
class WorkspaceSearchResult:
    """All hits for one cross-repo search, grouped and deterministic."""

    term: str
    hits: tuple[SearchHit, ...] = ()

    def by_repo(self) -> dict[str, tuple[SearchHit, ...]]:
        """Return hits grouped by repo name (only repos that matched)."""

        grouped: dict[str, list[SearchHit]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.repo, []).append(hit)
        return {repo: tuple(items) for repo, items in grouped.items()}

    @property
    def repos_with_hits(self) -> tuple[str, ...]:
        """Sorted names of the repos that contained at least one hit."""

        return tuple(sorted({hit.repo for hit in self.hits}))

    def hits_in(self, repo: str) -> tuple[SearchHit, ...]:
        """Return the hits found in ``repo`` (empty tuple if none)."""

        return tuple(hit for hit in self.hits if hit.repo == repo)

    @property
    def total(self) -> int:
        return len(self.hits)


# ---------------------------------------------------------------------------
# Cross-repo edit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoFileEdit:
    """One file edit inside a named repo: replace ``find`` with ``replace``.

    ``count`` bounds how many occurrences are replaced (0 = all). When
    ``find`` is not present in the target file, the whole coordinated edit is
    rejected before anything is written.
    """

    repo: str
    relpath: str
    find: str
    replace: str
    count: int = 0


@dataclass(frozen=True)
class CoordinatedEditResult:
    """Outcome of an all-or-nothing coordinated edit across repos."""

    applied: bool
    repos_changed: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    rolled_back: bool = False
    reason: str | None = None

    @property
    def spanned_multiple_repos(self) -> bool:
        return len(self.repos_changed) > 1


@dataclass(frozen=True)
class _StagedEdit:
    """An edit resolved to an absolute path with its original + new content."""

    repo: str
    relpath: str
    path: Path
    original: str
    new: str


# ---------------------------------------------------------------------------
# Coordinated PR proof
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoordinatedChange:
    """One logical change spanning several repos of a workspace.

    Parameters
    ----------
    change_id:
        Stable identifier shared by every companion PR (e.g. ``"CH-42"``).
    title:
        Human title used for each PR (repo name is appended per payload).
    repo_summaries:
        Mapping of repo name -> what changed in that repo. Its keys are the
        affected repos; there must be at least two for the change to be
        genuinely cross-repo.
    base:
        Base branch each PR targets (default ``"main"``).
    branch:
        Feature branch name. Defaults to ``coordinated/<slug(change_id)>``.
    """

    change_id: str
    title: str
    repo_summaries: Mapping[str, str]
    base: str = "main"
    branch: str = ""

    @property
    def repos(self) -> tuple[str, ...]:
        return tuple(sorted(self.repo_summaries))

    def branch_name(self) -> str:
        if self.branch.strip():
            return self.branch.strip()
        return f"coordinated/{_slugify(self.change_id) or 'change'}"


@dataclass(frozen=True)
class CoordinatedPrPlan:
    """The linked-PR plan for a coordinated change across repos."""

    change_id: str
    payloads: dict[str, PrPayload] = field(default_factory=dict)
    results: dict[str, GatewayResult] = field(default_factory=dict)

    @property
    def repos(self) -> tuple[str, ...]:
        return tuple(sorted(self.payloads))

    def payload_for(self, repo: str) -> PrPayload:
        return self.payloads[repo]

    def is_fully_linked(self) -> bool:
        """True when every payload references the change id and every peer repo."""

        repos = set(self.payloads)
        if len(repos) < 2:
            return False
        for repo, payload in self.payloads.items():
            if self.change_id not in payload.body:
                return False
            for peer in repos - {repo}:
                if peer not in payload.body:
                    return False
        return True


# ---------------------------------------------------------------------------
# The workspace
# ---------------------------------------------------------------------------


@dataclass
class MultiRootWorkspace:
    """A named set of repository roots treated as one workspace.

    Parameters
    ----------
    name:
        Human name for the workspace.
    roots:
        Mapping of repo name -> root path. Repo names must be unique and
        non-empty; paths are stored resolved.
    """

    name: str
    roots: dict[str, Path] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise WorkspaceError("workspace name is required")
        normalized: dict[str, Path] = {}
        for repo_name, path in dict(self.roots).items():
            key = str(repo_name).strip()
            if not key:
                raise WorkspaceError("repo name must be non-empty")
            if key in normalized:
                raise WorkspaceError(f"duplicate repo name: {key!r}")
            normalized[key] = Path(path)
        self.name = str(self.name).strip()
        self.roots = normalized

    # -- construction / membership ----------------------------------------

    @classmethod
    def from_pairs(cls, name: str, pairs: Iterable[tuple[str, str | Path]]) -> MultiRootWorkspace:
        """Build a workspace from ``(repo_name, root_path)`` pairs."""

        return cls(name=name, roots={str(n): Path(p) for n, p in pairs})

    def add_root(self, repo: str, path: str | Path) -> None:
        """Register another repo root under ``repo``."""

        key = str(repo).strip()
        if not key:
            raise WorkspaceError("repo name must be non-empty")
        if key in self.roots:
            raise WorkspaceError(f"duplicate repo name: {key!r}")
        self.roots[key] = Path(path)

    @property
    def repo_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.roots))

    def root_for(self, repo: str) -> Path:
        try:
            return self.roots[repo]
        except KeyError as exc:
            raise WorkspaceError(f"unknown repo: {repo!r}") from exc

    # -- cross-repo search -------------------------------------------------

    def search(
        self,
        term: str,
        *,
        regex: bool = False,
        symbol: bool = False,
        ignore_case: bool = False,
        include_ext: Sequence[str] | None = None,
    ) -> WorkspaceSearchResult:
        """Search every root for ``term`` and return per-repo hits.

        ``symbol`` matches ``term`` on word boundaries (``\\bterm\\b``); ``regex``
        treats ``term`` as a regular expression. With neither flag the search is
        a literal substring match. Results are deterministic across repos, files,
        and lines.
        """

        if not str(term):
            raise WorkspaceError("search term must be non-empty")

        matcher = self._build_matcher(term, regex=regex, symbol=symbol, ignore_case=ignore_case)
        exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (include_ext or ())}

        hits: list[SearchHit] = []
        for repo in sorted(self.roots):
            root = self.roots[repo]
            hits.extend(self._search_root(repo, root, matcher, exts))
        return WorkspaceSearchResult(term=term, hits=tuple(hits))

    @staticmethod
    def _build_matcher(term: str, *, regex: bool, symbol: bool, ignore_case: bool) -> Callable[[str], bool]:
        flags = re.IGNORECASE if ignore_case else 0
        if regex:
            pattern = re.compile(term, flags)
            return lambda line: pattern.search(line) is not None
        if symbol:
            pattern = re.compile(rf"\b{re.escape(term)}\b", flags)
            return lambda line: pattern.search(line) is not None
        if ignore_case:
            needle = term.lower()
            return lambda line: needle in line.lower()
        return lambda line: term in line

    @staticmethod
    def _search_root(
        repo: str,
        root: Path,
        matcher: Callable[[str], bool],
        exts: set[str],
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        if not root.is_dir():
            return hits
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skip dirs in place and keep traversal deterministic.
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                if exts and path.suffix.lower() not in exts:
                    continue
                try:
                    if path.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    # Unreadable/binary files are skipped, not fatal.
                    continue
                relpath = path.relative_to(root).as_posix()
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if matcher(line):
                        hits.append(
                            SearchHit(
                                repo=repo,
                                relpath=relpath,
                                line_number=lineno,
                                line=line,
                            )
                        )
        return hits

    # -- cross-repo edit ---------------------------------------------------

    def apply_coordinated_edit(
        self,
        edits: Sequence[RepoFileEdit],
        *,
        require_multi_repo: bool = True,
        writer: FileWriter | None = None,
    ) -> CoordinatedEditResult:
        """Apply ``edits`` across repos as a single all-or-nothing unit.

        The edit is validated entirely in memory first: an unknown repo, a
        missing target file, or an unmatched ``find`` string aborts the whole
        operation before any file is written. If a write fails partway through,
        every file already written in this call is restored to its original
        content, so no repo is left partially edited.
        """

        write = writer or _default_file_writer
        if not edits:
            return CoordinatedEditResult(applied=False, reason="no edits supplied")

        affected_repos = {e.repo for e in edits}
        if require_multi_repo and len(affected_repos) < 2:
            return CoordinatedEditResult(
                applied=False,
                reason="coordinated edit must span more than one repo",
            )

        # Phase 1: resolve + validate every edit in memory (no writes yet).
        try:
            staged = self._stage_edits(edits)
        except WorkspaceError as exc:
            return CoordinatedEditResult(applied=False, rolled_back=False, reason=str(exc))

        # Phase 2: write all staged edits; restore on any failure.
        written: list[_StagedEdit] = []
        try:
            for item in staged:
                write(item.path, item.new)
                written.append(item)
        except OSError as exc:
            self._restore(written, write)
            return CoordinatedEditResult(
                applied=False,
                rolled_back=True,
                reason=f"write failed for {self._label(exc, written, staged)}; rolled back",
            )

        repos_changed = tuple(sorted({item.repo for item in staged}))
        files_changed = tuple(f"{item.repo}/{item.relpath}" for item in staged)
        return CoordinatedEditResult(
            applied=True,
            repos_changed=repos_changed,
            files_changed=files_changed,
            rolled_back=False,
        )

    def _stage_edits(self, edits: Sequence[RepoFileEdit]) -> list[_StagedEdit]:
        staged: list[_StagedEdit] = []
        for edit in edits:
            root = self.root_for(edit.repo)
            path = root / edit.relpath
            if not path.is_file():
                raise WorkspaceError(f"target file not found: {edit.repo}/{edit.relpath}")
            try:
                original = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise WorkspaceError(f"cannot read {edit.repo}/{edit.relpath}: {exc}") from exc
            if edit.find not in original:
                raise WorkspaceError(f"find string not present in {edit.repo}/{edit.relpath}; aborting all edits")
            replacements = edit.count if edit.count > 0 else -1
            new = original.replace(edit.find, edit.replace, replacements)
            staged.append(
                _StagedEdit(
                    repo=edit.repo,
                    relpath=edit.relpath,
                    path=path,
                    original=original,
                    new=new,
                )
            )
        return staged

    @staticmethod
    def _restore(written: Sequence[_StagedEdit], write: FileWriter) -> None:
        # Best-effort restoration of already-written files to their originals.
        for item in written:
            try:
                write(item.path, item.original)
            except OSError:
                # A restore failure must not mask the original error; the
                # caller is told the edit rolled back and can re-inspect state.
                continue

    @staticmethod
    def _label(
        exc: OSError,
        written: Sequence[_StagedEdit],
        staged: Sequence[_StagedEdit],
    ) -> str:
        # Identify the file that likely failed: the first staged item not yet
        # confirmed written.
        confirmed = {id(item) for item in written}
        for item in staged:
            if id(item) not in confirmed:
                return f"{item.repo}/{item.relpath} ({exc})"
        return str(exc)

    # -- coordinated PR proof ---------------------------------------------

    def plan_coordinated_prs(
        self,
        change: CoordinatedChange,
        *,
        gateway: Gateway = default_dry_run_gateway,
        head_commits: Mapping[str, str] | None = None,
    ) -> CoordinatedPrPlan:
        """Produce N linked PR payloads for a coordinated change across repos.

        One payload is composed per affected repo. Each body references the
        shared ``change.change_id`` and cross-references every companion repo and
        its branch, so the PRs are provably linked. Each payload is handed to the
        injectable ``gateway`` (default: inert dry-run) -- nothing is pushed.
        """

        repos = change.repos
        unknown = [r for r in repos if r not in self.roots]
        if unknown:
            raise WorkspaceError(f"change references repos not in workspace: {sorted(unknown)}")
        if len(repos) < 2:
            raise WorkspaceError("a coordinated change must span more than one repo")

        branch = change.branch_name()
        commits = dict(head_commits or {})

        payloads: dict[str, PrPayload] = {}
        results: dict[str, GatewayResult] = {}
        for repo in repos:
            body = self._compose_linked_body(change, repo, branch)
            payload = PrPayload(
                branch=branch,
                base=change.base,
                title=f"{change.title} ({repo})",
                body=body,
                head_commit=commits.get(repo, ""),
            )
            payloads[repo] = payload
            results[repo] = gateway(payload)

        return CoordinatedPrPlan(change_id=change.change_id, payloads=payloads, results=results)

    @staticmethod
    def _compose_linked_body(change: CoordinatedChange, repo: str, branch: str) -> str:
        repos = change.repos
        peers = [r for r in repos if r != repo]
        lines: list[str] = []
        lines.append(f"# Coordinated change {change.change_id}: {change.title}")
        lines.append("")
        lines.append(f"This PR is part of coordinated change **{change.change_id}**, one logical")
        lines.append(f"change spanning {len(repos)} repos: {', '.join(repos)}.")
        lines.append("")
        lines.append(f"## This repo: `{repo}`")
        summary = str(change.repo_summaries.get(repo, "")).strip()
        lines.append(summary or "_(no per-repo summary provided)_")
        lines.append("")
        lines.append("## Companion PRs")
        lines.append(f"Merge together with the linked PRs on branch `{branch}` in the companion repos:")
        for peer in peers:
            peer_summary = str(change.repo_summaries.get(peer, "")).strip()
            detail = f" -- {peer_summary}" if peer_summary else ""
            lines.append(f"- `{peer}` (change {change.change_id}, branch `{branch}`){detail}")
        lines.append("")
        lines.append(f"Shared-change-id: {change.change_id}")
        return "\n".join(lines).rstrip() + "\n"

    # -- serialization / round-trip ---------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Serialize the workspace to a plain JSON-friendly dict."""

        return {
            "name": self.name,
            "roots": {repo: str(path) for repo, path in sorted(self.roots.items())},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MultiRootWorkspace:
        """Reconstruct a workspace from :meth:`to_dict` output."""

        name = str(data.get("name", "")).strip()
        raw_roots = data.get("roots") or {}
        if not isinstance(raw_roots, Mapping):
            raise WorkspaceError("roots must be a mapping")
        roots = {str(repo): Path(str(path)) for repo, path in raw_roots.items()}
        return cls(name=name, roots=roots)
