"""The preview of a public release: the tree that would go public, and every check run against it.

``build`` copies one commit of the development repository into a scratch folder, leaves out the public file list
(``docs/ops/public_exclude.txt``, see ``public_tree``), commits what is left there, and runs the checks. Nothing is
pushed and the repository it reads is not changed. The returned :class:`Preview` says whether publishing is safe, and
its :meth:`Preview.digest` is what a sign-in has to confirm before ``public_release_publish`` will send anything.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from scripts.forge.publish import public_tree as pt
from thomas.core.git_process import run_git

SCRATCH_PREFIX = "thomas-public-release-"
#: Identity and settings for the commits made inside the scratch copy. No signing, no line-ending changes.
SCRATCH_GIT = (
    "-c",
    "user.name=Thomas release",
    "-c",
    "user.email=release@thomas.invalid",
    "-c",
    "commit.gpgsign=false",
)
_LONG = 900.0

Preflight = Callable[[Path], "tuple[bool, str]"]


class ReleaseError(RuntimeError):
    """Something git or the scratch copy refused, said in words a person can read."""


def git(args: list[str], cwd: Path, *, timeout: float = 120.0) -> str:
    result = run_git(args, cwd=cwd, timeout=timeout)
    if not result.ok:
        verb = next((a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] != "-c")), "")
        raise ReleaseError(f"git {verb} did not work: {result.message()}")
    return result.output()


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    reason: str


@dataclass
class Preview:
    version: str
    source: str
    tree: str
    parent: str | None
    remote: str
    public_ref: str
    files: int
    removed: dict[str, str]
    changed: int | None
    checks: list[Check] = field(default_factory=list)
    scratch: str = ""
    notes: str = ""
    remote_url: str = ""
    branch: str = ""
    repo: str = field(default="", repr=False)
    push_url: str = field(default="", repr=False)

    @property
    def safe_to_publish(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def facts(self) -> dict[str, object]:
        """Everything a person is shown and signs for. The scratch folder is not part of it."""
        return {
            "version": self.version,
            "source": self.source,
            "tree": self.tree,
            "parent": self.parent,
            "remote": self.remote,
            "remote_url": self.remote_url,
            "branch": self.branch,
            "public_ref": self.public_ref,
            "files": self.files,
            "removed": self.removed,
            "changed": self.changed,
            "checks": [asdict(check) for check in self.checks],
        }

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.facts(), sort_keys=True).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.facts(), "safe_to_publish": self.safe_to_publish, "digest": self.digest()}

    def close(self) -> None:
        """Remove the scratch copy this preview made. It only ever removes a folder this module created."""
        folder = Path(self.scratch) if self.scratch else None
        if folder is not None and folder.name.startswith(SCRATCH_PREFIX) and folder.is_dir():
            shutil.rmtree(folder, onerror=_make_writable_and_retry)
        self.scratch = ""


def _make_writable_and_retry(func: Callable[..., object], path: str, _exc: object) -> None:
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def resolve_remote(repo: Path, given: str) -> str:
    """The address a remote name stands for in ``repo``; anything that is not a configured name is the address itself."""
    found = run_git(["remote", "get-url", given], cwd=repo, timeout=30)
    return found.output() if found.ok and found.output() else given


def free_branch(version: str, url: str, tree: Path, today: str) -> str:
    """``release/<version>-<date>``, with a number added when the public repository already has that branch."""
    base = f"release/{version}-{today}"
    name, number = base, 1
    while run_git(["ls-remote", "--heads", url, f"refs/heads/{name}"], cwd=tree, timeout=120).output():
        number += 1
        name = f"{base}-{number}"
    return name


def display_remote(url: str) -> str:
    """The remote without any password or token it carries."""
    parts = urlsplit(url)
    if parts.password or parts.username:
        return urlunsplit(parts._replace(netloc=parts.hostname or ""))
    return url


def read_version(tree: Path) -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', (tree / "thomas/__init__.py").read_text("utf-8"), re.M)
    return match.group(1) if match else ""


def changelog_section(text: str, version: str) -> str | None:
    """The part of the changelog under ``## [version]``, up to the next heading, or None."""
    heading = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n", text, re.M)
    if not heading:
        return None
    rest = text[heading.end() :]
    following = re.search(r"^## \[", rest, re.M)
    return (rest[: following.start()] if following else rest).strip()


def default_preflight(tree: Path) -> tuple[bool, str]:
    """The publish preflight, deep and strict, run against the pruned tree."""
    from scripts.forge.publish import preflight

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = preflight.run(["--repo-root", str(tree), "--deep", "--strict", "--json"])
    try:
        errors = [str(item) for item in json.loads(captured.getvalue()).get("errors") or []]
    except ValueError:
        errors = [captured.getvalue().strip() or "the preflight printed nothing"]
    return code == 0, _plain_reason(errors)


def _plain_reason(errors: list[str]) -> str:
    if not errors:
        return "every check passed"
    lines: list[str] = []
    for error in errors:
        _head, _sep, tail = error.partition(" failed: ")
        try:
            violations = json.loads(tail).get("violations") or []
        except (ValueError, AttributeError):
            violations = []
        lines.extend(str(v) for v in violations or [error.splitlines()[0]])
    return "; ".join(lines)[:600]


def _compile_failures(tree: Path, kept: list[str]) -> list[str]:
    bad: list[str] = []
    for path, source in pt.read_sources(tree, kept).items():
        try:
            compile(source, path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            bad.append(f"{path} ({type(exc).__name__})")
    return bad


def _read_public(remote: str, public_ref: str, tree: Path, new_tree: str) -> tuple[str | None, int | None, Check]:
    result = run_git(["ls-remote", remote, f"refs/heads/{public_ref}"], cwd=tree, timeout=120)
    if not result.ok:
        return None, None, Check("Public copy", False, f"the public repository could not be read: {result.message()}")
    parent = result.output().split("\t")[0] if result.output() else None
    if parent is None:
        return (
            None,
            None,
            Check("Public copy", True, f"{public_ref} does not exist there yet, so this would be its first"),
        )
    git(["fetch", "--no-tags", "--quiet", remote, f"refs/heads/{public_ref}"], tree, timeout=_LONG)
    if git(["rev-parse", f"{parent}^{{tree}}"], tree) == new_tree:
        return (
            parent,
            0,
            Check("Public copy", False, f"{public_ref} already holds exactly this tree, so there is nothing new"),
        )
    changed = len(git(["diff", "--name-only", parent, new_tree], tree, timeout=_LONG).splitlines())
    return parent, changed, Check("Public copy", True, f"{changed} files differ from {public_ref}")


def build(
    repo: Path,
    *,
    ref: str = "HEAD",
    remote: str | None = None,
    public_ref: str = "main",
    rules: list[pt.Rule] | None = None,
    preflight: Preflight | None = None,
    scratch_parent: Path | None = None,
    branch: str | None = None,
    today: str | None = None,
) -> Preview:
    """Make the public tree of ``ref`` in a scratch copy, check it, and return what would go public.

    ``remote`` is the public repository (a URL or a path). Without it nothing can be compared, so the preview is
    never safe to publish. The remote's address and the branch name that would be written are part of the preview, so
    the sign-in for it covers where it goes. The caller owns the result and calls :meth:`Preview.close` when done with it.
    """
    repo = Path(repo).resolve()
    source = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo)
    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=scratch_parent))
    finished = False
    try:
        url = resolve_remote(repo, remote) if remote else ""
        preview = _build_in(repo, source, scratch, url, public_ref, rules, preflight or default_preflight)
        preview.remote, preview.remote_url = display_remote(remote or ""), display_remote(url)
        preview.repo, preview.push_url = str(repo), url
        if url:
            name = branch or free_branch(preview.version, url, scratch / "tree", today or date.today().isoformat())
            preview.branch = name
        finished = True
        return preview
    finally:
        if not finished:
            Preview("", source, "", None, "", public_ref, 0, {}, None, scratch=str(scratch)).close()


def _build_in(
    repo: Path,
    source: str,
    scratch: Path,
    remote: str | None,
    public_ref: str,
    rules: list[pt.Rule] | None,
    preflight: Preflight,
) -> Preview:
    tree = scratch / "tree"
    git(
        ["clone", "--no-local", "--no-checkout", "-c", "core.autocrlf=false", str(repo), str(tree)],
        scratch,
        timeout=_LONG,
    )
    git(["checkout", "--quiet", "--detach", source], tree, timeout=_LONG)
    used = rules if rules is not None else pt.public_rules(tree, pt.tracked_files(tree))
    report = pt.prune_tree(tree, used)
    git(["add", "-A"], tree, timeout=_LONG)
    git([*SCRATCH_GIT, "commit", "--quiet", "--allow-empty", "-m", "the public tree, for review"], tree)
    new_tree = git(["rev-parse", "HEAD^{tree}"], tree)

    leftover = pt.split_paths(git(["ls-tree", "-r", "--name-only", new_tree], tree, timeout=_LONG).splitlines(), used)[
        1
    ]
    version = read_version(tree)
    notes = changelog_section((tree / "CHANGELOG.md").read_text("utf-8"), version) if version else None
    ok_pre, pre_reason = preflight(tree)
    bad = _compile_failures(tree, report.kept)
    checks = [
        Check(
            "Private files are left out",
            not leftover,
            f"{len(report.removed)} files left out"
            if not leftover
            else "still in the tree: " + ", ".join(sorted(leftover)[:5]),
        ),
        Check(
            "Nothing kept needs a left-out file",
            not report.importers,
            "no kept file imports one" if not report.importers else "; ".join(report.problems[:3]),
        ),
        Check(
            "Every Python file compiles", not bad, f"{len(report.kept)} files kept" if not bad else ", ".join(bad[:5])
        ),
        Check(
            "Version and release notes",
            bool(version and notes),
            f"version {version}, release notes found"
            if version and notes
            else f"no release notes under version {version or '(none found)'} in the changelog",
        ),
        Check("Publish safety checks", ok_pre, pre_reason),
    ]
    parent, changed = None, None
    if remote:
        parent, changed, public_check = _read_public(remote, public_ref, tree, new_tree)
        checks.append(public_check)
    else:
        checks.append(
            Check("Public copy", False, "no public repository was named, so there is nothing to compare or publish to")
        )
    return Preview(
        version,
        source,
        new_tree,
        parent,
        display_remote(remote or ""),
        public_ref,
        len(report.kept),
        report.removed,
        changed,
        checks,
        str(scratch),
        notes or "",
    )
