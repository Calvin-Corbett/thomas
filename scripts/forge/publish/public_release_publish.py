"""Publishing a previewed public release: one sign-in, one squashed commit, one review branch.

``confirm`` asks for a fresh Windows sign-in (the same prompt the chat limits use) for one exact preview and returns a
sealed record. ``publish`` refuses without a record for that preview, then makes a single commit on top of the public
copy's current ``main`` whose tree is the previewed tree, and pushes it to a branch named ``release/<version>-<date>``.
It never pushes to ``main``, never forces anything and never changes branch protection. A pull request is opened only
when asked for.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scripts.forge.publish.public_release_preview import (
    Preview,
    ReleaseError,
    display_remote,
    git,
    resolve_remote,
)
from thomas.core.git_process import run_git

#: Sealing key for this process only. A record cannot be forged by building one by hand, and it dies with the process.
_SEAL_KEY = secrets.token_bytes(32)
FRESH_FOR_S = 600.0
METHOD = "windows-sign-in"
Authorizer = Callable[[str, str], bool]
Gh = Callable[[list[str], Path], "tuple[int, str]"]


@dataclass(frozen=True)
class Confirmation:
    """Proof that a sign-in was accepted for the preview with this digest."""

    preview_digest: str
    method: str
    issued_at: float
    seal: str


@dataclass
class PublishResult:
    ok: bool
    refused: str = ""
    branch: str = ""
    commit: str = ""
    signed: bool = False
    pushed: bool = False
    dry_run: bool = False
    branch_url: str = ""
    pr_url: str = ""
    lines: list[str] = field(default_factory=list)


def _seal(digest: str, method: str, issued_at: float) -> str:
    return hmac.new(_SEAL_KEY, f"{digest}|{method}|{issued_at!r}".encode(), hashlib.sha256).hexdigest()


def native_sign_in(action: str, reason: str) -> bool:
    """Windows' own sign-in, checked by Windows, fresh each time: the prompt the chat limits already use."""
    from thomas.server.dial_elevation import _fresh_native_prompt

    return _fresh_native_prompt(action, reason)


def confirm(preview: Preview, authorize: Authorizer | None = None, *, now: float | None = None) -> Confirmation | None:
    """Ask for a sign-in for this preview. None means it was declined, cancelled or could not be shown."""
    action = (
        f"Publish a review copy to {preview.remote_url} as branch {preview.branch}"
        + chr(10) * 2
        + f"Thomas {preview.version}: {preview.files} files would be sent. "
        + f"{len(preview.removed)} private files are left out. The main branch is not changed."
    )
    reason = "Something asked to publish Thomas to the public repository. Approve only if you meant it."
    if not (authorize or native_sign_in)(action, reason):
        return None
    issued = time.time() if now is None else now
    return Confirmation(preview.digest(), METHOD, issued, _seal(preview.digest(), METHOD, issued))


def confirmation_problem(preview: Preview, confirmation: Confirmation | None, *, now: float | None = None) -> str:
    if confirmation is None:
        return "Nothing was published: you have not signed in for this release."
    genuine = hmac.compare_digest(
        confirmation.seal, _seal(confirmation.preview_digest, confirmation.method, confirmation.issued_at)
    )
    if not genuine:
        return "Nothing was published: the sign-in record is not one this program made."
    if not hmac.compare_digest(confirmation.preview_digest, preview.digest()):
        return "Nothing was published: your sign-in was for a different preview. Look at the preview again and sign in again."
    if (time.time() if now is None else now) - confirmation.issued_at > FRESH_FOR_S:
        return "Nothing was published: your sign-in is too old. Sign in again."
    return ""


def release_message(preview: Preview) -> str:
    """The commit message: the version's changelog headlines and the preview's counts. No commit of the private history."""
    heads = []
    for line in preview.notes.splitlines():
        if line.startswith("- "):
            bold = re.match(r"- \*\*(.+?)\*\*", line)
            heads.append((bold.group(1) if bold else line[2:].split(". ")[0]).strip()[:200])
    shown = "\n".join(f"- {h}" for h in heads[:40])
    more = f"\n- and {len(heads) - 40} more changes" if len(heads) > 40 else ""
    counts = f"{preview.files} files; {len(preview.removed)} private files left out"
    if preview.changed is not None:
        counts += f"; {preview.changed} differ from {preview.public_ref}"
    return f"Release {preview.version}\n\n{shown}{more}\n\n{counts}.\n"


def _names_someone(message: str, tree: Path) -> str:
    for key in ("user.name", "user.email"):
        value = run_git(["config", "--get", key], cwd=tree).output()
        if len(value) >= 3 and re.search(rf"(?<!\w){re.escape(value)}(?!\w)", message, re.I):
            return value
    return ""


def _github(remote: str) -> tuple[str, str]:
    found = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", remote)
    return (found.group(1), found.group(2)) if found else ("", "")


def _default_gh(args: list[str], cwd: Path) -> tuple[int, str]:
    from scripts.crew.land_checks import gh

    done = gh(cwd, *args)
    return done.returncode, (done.stdout or done.stderr or "").strip()


def publish(
    preview: Preview,
    confirmation: Confirmation | None,
    *,
    open_pr: bool = False,
    gh: Gh | None = None,
    signing_key: str | None = None,
    dry_run: bool = False,
) -> PublishResult:
    """Send the previewed tree to the review branch the preview names. Every refusal says why and sends nothing.

    Where it goes is taken from the preview and nowhere else: the address its remote has now must still be the one the
    sign-in covered, and the branch must still be free.
    """
    refusal = _refusal(preview, confirmation)
    tree = Path(preview.scratch) / "tree"
    remote = preview.push_url
    if not refusal:
        refusal = _stale(preview, tree)
    owner, repo_name = _github(remote)
    if not refusal and open_pr and not owner:
        refusal = "Nothing was published: a pull request needs a GitHub address for the public repository."
    message = release_message(preview)
    if not refusal and (someone := _names_someone(message, tree)):
        refusal = f"Nothing was published: the release message would name {someone}."
    if refusal:
        return PublishResult(False, refused=refusal, lines=[refusal])
    name = preview.branch
    if not name.startswith("release/"):
        text = "Nothing was published: only a branch named release/... can be written."
        return PublishResult(False, refused=text, lines=[text])
    key = signing_key or run_git(["config", "--get", "user.signingkey"], cwd=tree).output()
    try:
        commit = _commit(preview, tree, message, key)
    except ReleaseError as exc:
        text = f"Nothing was published: the commit could not be made{' and signed' if key else ''}: {exc}"
        return PublishResult(False, refused=text, lines=[text])
    result = PublishResult(True, branch=name, commit=commit, signed=bool(key), dry_run=dry_run)
    how = "signed" if key else "not signed, because no signing key is set up"
    if dry_run:
        result.lines = [f"Dry run: nothing was sent. The commit would be {commit[:10]} on {name} ({how})."]
        return result
    pushed = run_git(["push", remote, f"{commit}:refs/heads/{name}"], cwd=tree, timeout=900)
    if not pushed.ok:
        text = f"Nothing was published: GitHub did not take the branch: {pushed.message()}"
        return PublishResult(False, refused=text, commit=commit, branch=name, lines=[text])
    result.pushed = True
    if owner:
        result.branch_url = f"https://github.com/{owner}/{repo_name}/tree/{name}"
    result.lines = [
        f"Sent version {preview.version} ({preview.files} files) to the branch {name}. The commit is {how}."
    ]
    result.lines.append(f"{preview.public_ref} was not changed.")
    if open_pr:
        _open_pr(result, preview, tree, (owner, repo_name), gh or _default_gh)
    else:
        result.lines.append("No pull request was opened. Changing main takes a pull request from this branch.")
    return result


def _refusal(preview: Preview, confirmation: Confirmation | None) -> str:
    if not preview.safe_to_publish:
        failed = [c for c in preview.checks if not c.ok]
        return "Nothing was published: " + "; ".join(f"{c.name}: {c.reason}" for c in failed)
    if not preview.scratch or not (Path(preview.scratch) / "tree").is_dir():
        return "Nothing was published: the copy this preview was made from is gone. Look at the preview again."
    return confirmation_problem(preview, confirmation)


def _stale(preview: Preview, tree: Path) -> str:
    if not preview.branch.startswith("release/"):
        return "Nothing was published: only a branch named release/... can be written."
    now_url = resolve_remote(Path(preview.repo), preview.remote) if preview.repo else preview.push_url
    if display_remote(now_url) != preview.remote_url or now_url != preview.push_url:
        return (
            f"Nothing was published: {preview.remote} no longer points at {preview.remote_url}, "
            "where your sign-in said to send it. Look at the preview again."
        )
    here = run_git(["rev-parse", "HEAD^{tree}"], cwd=tree)
    if here.output() != preview.tree:
        return "Nothing was published: the copy no longer matches the preview. Look at the preview again."
    asked = run_git(["ls-remote", now_url, f"refs/heads/{preview.public_ref}"], cwd=tree, timeout=120)
    if not asked.ok:
        return f"Nothing was published: the public repository could not be read: {asked.message()}"
    tip = asked.output().split(chr(9))[0] if asked.output() else None
    if tip != preview.parent:
        return f"Nothing was published: {preview.public_ref} changed on GitHub after the preview. Look at the preview again."
    taken = run_git(["ls-remote", "--heads", now_url, f"refs/heads/{preview.branch}"], cwd=tree, timeout=120)
    if taken.output():
        return f"Nothing was published: the branch {preview.branch} already exists there. Look at the preview again."
    return ""


def _commit(preview: Preview, tree: Path, message: str, key: str) -> str:
    (tree.parent / "message.txt").write_text(message, encoding="utf-8", newline="\n")
    args = ["-c", "user.name=Thomas release", "-c", "user.email=release@thomas.invalid", "-c", "commit.gpgsign=false"]
    if key:
        args += ["-c", f"user.signingkey={key}"]
    args += ["commit-tree", preview.tree, "-F", str(tree.parent / "message.txt")]
    if preview.parent:
        args += ["-p", preview.parent]
    if key:
        args.append("-S")
    return git(args, tree, timeout=300)


def _open_pr(result: PublishResult, preview: Preview, tree: Path, repo: tuple[str, str], gh: Gh) -> None:
    args = ["pr", "create", "--repo", "/".join(repo), "--base", preview.public_ref, "--head", result.branch]
    args += ["--title", f"Release {preview.version}", "--body", f"A review copy of version {preview.version}."]
    code, text = gh(args, tree)
    if code == 0:
        result.pr_url = text.splitlines()[-1] if text else ""
        result.lines.append(f"Opened a pull request: {result.pr_url}")
    else:
        result.lines.append(f"The branch is there, but the pull request could not be opened: {text[:300]}")
    result.lines.append(
        "The public repository asks for a review before main changes, so merging is your step in GitHub. "
        "Nothing here merges it or changes those rules."
    )
