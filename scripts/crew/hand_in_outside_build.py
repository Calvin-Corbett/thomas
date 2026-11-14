"""Build an outside agent's change as one hand-in for the promoter, and write it into an inbox.

The format is the one the promoter reads (scripts/cage/self_change_checks.read_submission) and the one the caged
server and the pipeline canary write: a folder ``self-<id>`` holding ``change.patch`` and ``submission.json``, put in
place by a rename so the promoter never reads half of one. See
docs/superpowers/plans/2026-11-03-handing-an-outside-agents-work-to-thomas.md.

Git runs through ``scripts.pipeline_canary.act._git`` (bytes in and out, already a counted process launch), so this
file starts no process of its own. The clone is somebody else's: :func:`git` here turns off everything its config or
attributes could use to start a program, and prefers plumbing (diff-tree, cat-file, ls-tree) to porcelain.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scripts.pipeline_canary.act import _git

# Config that names a program git would start, set to nothing for every call on a clone we did not make.
NEUTRAL = (
    "core.fsmonitor=false", "diff.external=", "core.hooksPath=" + os.devnull, "core.pager=cat",
    "core.sshCommand=", "core.askPass=", "protocol.ext.allow=never", "core.attributesFile=",
)  # fmt: skip
_EMPTY: list[str] = []  # an empty file, made once, that stands in for the user's global git config


def _empty_config() -> str:
    if not _EMPTY or not Path(_EMPTY[0]).is_file():
        handle, name = tempfile.mkstemp(prefix="outside-gitconfig-", suffix=".empty")
        os.close(handle)
        _EMPTY[:] = [name]
    return _EMPTY[0]


def safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for git on a clone we did not make: no inherited GIT_* variable (GIT_EXTERNAL_DIFF, GIT_DIR...),
    no system or global config, no system attributes. *extra* is put back after, e.g. a temporary GIT_INDEX_FILE."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=_empty_config(), GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0"
    )
    env.update(extra or {})
    return env


def git(clone: Path, *args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> bytes:
    """git on *clone* with a program-starting config turned off. Raises ValueError with git's words, like ``_git``."""
    flags = [part for pair in (("-c", item) for item in NEUTRAL) for part in pair]
    return _git(clone, *flags, *args, env=safe_env(env), stdin=stdin)


KIND = "self_change"
NO_EXECUTION = "none-outside-agent"  # shown by the promoter as "(execution none-outside-agent)", not as a blank
PROMOTER_FILE = "scripts/cage/self_change_promoter.py"
# The two sentences the promoter writes into every landing's commit message, whoever handed the change in.
FALSE_WORDING = (
    '"Made in green (execution ...), re-derived by the self-change promoter without running any of it, and approved '
    'by you ..."',
    '"passed by the checker and a second look" (when a window you opened lands it)',
)
ID_RE = re.compile(r"^self-[A-Za-z0-9_-]{1,80}$")
SUMMARY_MAX = 20000


class Refusal(Exception):  # noqa: N818 - reads as the answer it is
    """The hand-in cannot be made, for the reason given in plain words."""


@dataclass
class Change:
    """One squashed change, with everything the manifest needs."""

    clone: Path
    base: str
    tip: str
    patch: bytes
    files: list[str]
    commits: list[tuple[str, str]]  # (short sha, subject), oldest first
    messages: str
    notes: list[str] = field(default_factory=list)


def resolve(clone: Path, rev: str, what: str) -> str:
    try:
        return git(clone, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").decode().strip()
    except ValueError:
        raise Refusal(f"{what} '{rev}' is not a commit in {clone}.") from None


def read_change(clone: Path, base: str, tip: str) -> Change:
    """The patch for base..tip, or a Refusal. *base* and *tip* are full shas (see :func:`resolve`)."""
    try:
        git(clone, "merge-base", "--is-ancestor", base, tip)
    except ValueError:
        raise Refusal(
            f"{base[:8]} is not an ancestor of {tip[:8]}: hand in the commits you made on top of {base[:8]}, "
            "in a straight line."
        ) from None
    raw = git(
        clone,
        "log",
        "--reverse",
        "--no-textconv",
        "--no-ext-diff",
        "--no-show-signature",
        "--format=%h%x1f%s%x1f%B%x1e",
        f"{base}..{tip}",
    ).decode("utf-8", "replace")
    commits, bodies = [], []
    for record in filter(None, (r.strip("\n") for r in raw.split("\x1e"))):
        short, subject, body = (record.split("\x1f") + ["", ""])[:3]
        commits.append((short.strip(), subject.strip()))
        bodies.append(f"{short.strip()} {body.strip()}")
    if not commits:
        raise Refusal(f"There are no commits between {base[:8]} and {tip[:8]}, so there is nothing to hand in.")
    patch = git(
        clone, "diff-tree", "-r", "-p", "--binary", "--no-renames", "--full-index", "--no-color", "--no-ext-diff",
        "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", base, tip,
    )  # fmt: skip
    if not patch.strip():
        raise Refusal(f"The commits between {base[:8]} and {tip[:8]} change nothing once squashed.")
    names = git(clone, "diff-tree", "-r", "--name-only", "-z", "--no-renames", "--no-ext-diff", base, tip).decode(
        "utf-8", "replace"
    )
    files = [name for name in names.split("\0") if name]
    return Change(clone, base, tip, patch, files, commits, "\n\n".join(bodies))


def submission_id(tip: str, now: float) -> str:
    return f"self-outside-{tip[:8]}-{int(now)}"


def manifest_for(
    change: Change, *, sid: str, dev_tip: str, checkout: Path, title: str, agent: str, checked: str, now: float
) -> dict[str, object]:
    listed = "\n".join(f"- {short} {subject}" for short, subject in change.commits)
    summary = (
        f"Outside agent {agent}: {title}\n\nHanded in by the outside agent {agent} from a clone, {len(change.commits)} commit(s) squashed "
        f"into one change:\n{listed}\n\n{change.messages}"
    )[:SUMMARY_MAX]
    return {
        "id": sid,
        "kind": KIND,
        "agent": agent,
        "source": "outside agent",
        "base": dev_tip,
        "message": title[:200],
        "patch": "change.patch",
        "patch_sha256": hashlib.sha256(change.patch).hexdigest(),
        "execution_id": NO_EXECUTION,
        "checked": checked,
        "chat": "",
        "summary": summary,
        "files": change.files,
        "blue": str(checkout),
        "submitted_at": now,
    }


def drop(inbox: Path, manifest: dict[str, object], patch: bytes) -> Path:
    """Write the hand-in into *inbox* with the staging-then-rename protocol. Writes nothing outside *inbox*."""
    sid = str(manifest["id"])
    if not ID_RE.match(sid):
        raise Refusal(f"'{sid}' is not an id the promoter accepts.")
    inbox.mkdir(parents=True, exist_ok=True)
    final = inbox / sid
    if final.exists():
        raise Refusal(f"{final} already exists: that change was already handed in.")
    staging = inbox / f".tmp-{sid}-{os.getpid()}"
    staging.mkdir()
    placed = False
    try:
        (staging / "change.patch").write_bytes(patch)  # bytes: write_text would turn each LF into CRLF
        (staging / "submission.json").write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        staging.rename(final)
        placed = True
    finally:
        if not placed:
            shutil.rmtree(staging, ignore_errors=True)
    return final


def card_text(manifest: dict[str, object]) -> tuple[str, str]:
    """The commit message the promoter would write for this hand-in, as your card and the log will show it: once for
    a landing you approve on a card, once for a landing inside a window you opened. Read from the promoter's own
    ``_message``, not copied. ("", "") with the reason in the first when the promoter cannot be loaded."""
    try:
        from types import SimpleNamespace

        from scripts.cage.self_change_promoter import Promoter

        stub = SimpleNamespace(_meta={k: str(v) for k, v in manifest.items() if not isinstance(v, (list, dict))})
        stub._cards = [{"state": "approved"}]
        stub._trailers = lambda gated: Promoter._trailers(stub, gated)  # type: ignore[arg-type]
        files = [str(f) for f in manifest.get("files", [])]  # type: ignore[union-attr]
        window = {"opened_at": "<when you opened it>", "window_id": "<window>", "pairing_code": "<code>"}
        return Promoter._message(stub, files)[0], Promoter._message(stub, files, window=window)[0]  # type: ignore[arg-type]
    except (ImportError, AttributeError, TypeError) as exc:
        return f"(the promoter's message could not be read: {exc})", ""
