#!/usr/bin/env python3
"""Bulk commit guard for Thomas.

Prevents "snapshot" or "dump" commits that touch an unreasonable number of
files in a *single commit*.  These bulk dumps are the #1 vector for
smuggling monolith files past guards — when 1000+ files change at once,
review is impossible and bad things slip through.

Two modes:

  Local / staged mode (no --base/--head)
      Count the files staged for the commit that is about to be made and
      FAIL when that count exceeds --max-files.  Unchanged.

  Diff-range mode (--base/--head, used by CI)
      Enumerate every non-merge commit in ``base..head`` with
      ``git rev-list --reverse --no-merges base..head`` and measure EACH
      commit on its own (``git diff --name-only <sha>^ <sha>``).  Every
      commit is evaluated against the limit independently.

      Before 2026-08-12 this mode diffed only the two ENDPOINTS of the range
      and compared that one number against a per-commit limit.  Over a
      597-commit range it reported the two-month total (1923 files) as if a
      single commit had done it — the largest real commit was 539.  The
      limit is per commit, so the measurement is now per commit.

Approval scope:
  A ``Thomas-Bulk-Change-Approved:`` trailer approves ONLY the commit whose
  own message carries it.  Before 2026-08-12 the approval helper scanned
  every message in the range and returned True on the FIRST trailer found
  anywhere, so one trailer approved every oversized commit in the range.

Waivers for already-landed history:
  Commits that already merged cannot be given a trailer retroactively, so
  ``docs/ops/landed_history_waivers.json`` may waive a specific oversized
  commit.  A waiver applies ONLY to the exact 40-hex sha listed, ONLY for
  the guard it names, and ONLY while ``expires_on`` is still in the future.
  A waiver missing any required field, or carrying anything other than a
  full 40-hex sha, does not apply — there is no wildcard, prefix or "all"
  form.  Every applied waiver is printed, so a waived pass never looks like
  a clean pass.

Merge commits:
  ``--no-merges`` skips merge commits deliberately: a merge has multiple
  parents and ``<sha>^`` silently picks the first, which would attribute the
  entire merged branch to the merge commit.  Consequence: changes that exist
  ONLY inside a merge commit (conflict resolutions) are not measured by this
  guard — they are measured on the branch commits they came from.  A range
  that contains merge commits *and nothing else* is therefore reported as
  unmeasurable and FAILS rather than passing on an empty commit list.

There is no environment-variable bypass.  To land a genuinely large commit,
use the native-auth breakglass SKIP path (Windows sign-in, audited) which can
skip ``thomas-bulk-commit-guard``, or split the change.

Exit codes:
  0 — every measured commit is within budget, or each oversized commit is
      approved by its own trailer / covered by an active waiver (both are
      reported explicitly)
  1 — at least one commit is over budget, or the range could not be measured
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# Maximum number of files that may change in a single commit.
# 50 is generous — most real feature commits touch 5-15 files.
# If you genuinely need to commit 50+ files (e.g. a migration), use a
# non-empty Thomas-Bulk-Change-Approved trailer on *that* commit, or the
# audited breakglass SKIP path.
DEFAULT_MAX_FILES = 50
APPROVAL_TRAILERS = ("thomas-bulk-change-approved:", "thomas-bulk-approved:", "thomas-breakglass:")
COMMIT_MESSAGE_ENV = "THOMAS_COMMIT_MESSAGE"

# Name this guard answers to in waiver entries and in the breakglass SKIP list.
GUARD_NAME = "thomas-bulk-commit-guard"
DEFAULT_WAIVERS = "docs/ops/landed_history_waivers.json"
WAIVER_REQUIRED_FIELDS = ("id", "commit", "guard", "approved_by", "approved_on", "expires_on", "reason")
# A waiver must name one exact commit.  Full 40-hex only: no prefixes, no
# globs, no "all" — a short sha or pattern must never match a commit.
_FULL_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_GIT_TIMEOUT = 30


class GitRangeError(RuntimeError):
    """Raised when a range/commit cannot be measured. Always fails the guard."""


def _changed_files(repo_root: Path, *, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return files


def _staged_file_count(repo_root: Path) -> tuple[int, list[str]]:
    files = _changed_files(repo_root)
    return len(files), files


def _git_lines(repo_root: Path, args: list[str], *, what: str) -> list[str]:
    """Run a git command and return its non-empty output lines.

    Raises GitRangeError when git fails, so diff-range mode fails closed
    instead of silently measuring zero files.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitRangeError(f"{what}: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise GitRangeError(f"{what}: {detail[0] if detail else 'git exited ' + str(proc.returncode)}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _range_commits(repo_root: Path, base: str, head: str) -> list[str]:
    """Every non-merge commit in ``base..head``, oldest first.

    ``--no-merges`` is deliberate — see the module docstring for what it means
    for merge commits.  An empty list is a real answer (empty range), not an
    error; callers must handle it explicitly.
    """
    if not base or not head:
        raise GitRangeError("diff-range mode requires both base and head")
    if base == head:
        return []
    return _git_lines(
        repo_root,
        ["rev-list", "--reverse", "--no-merges", f"{base}..{head}"],
        what=f"rev-list {base}..{head}",
    )


def _commit_changed_files(repo_root: Path, sha: str) -> list[str]:
    """Files changed by ONE commit (``git diff --name-only <sha>^ <sha>``)."""
    try:
        return _git_lines(
            repo_root,
            ["diff", "--name-only", f"{sha}^", sha],
            what=f"diff {sha[:12]}^ {sha[:12]}",
        )
    except GitRangeError:
        # A root commit has no parent, so `<sha>^` does not resolve.  Measure
        # its own tree instead rather than reporting zero files.
        return _git_lines(
            repo_root,
            ["show", "--name-only", "--pretty=format:", sha],
            what=f"show {sha[:12]}",
        )


def _commit_message(repo_root: Path, sha: str) -> str:
    """The full message of ONE commit. Only this commit's own trailers."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitRangeError(f"log -1 {sha[:12]}: {exc}")
    if proc.returncode != 0:
        raise GitRangeError(f"log -1 {sha[:12]}: git exited {proc.returncode}")
    return str(proc.stdout or "")


def _bulk_approval(message: str) -> tuple[bool, str, str]:
    """Approval trailer carried by ONE commit message.

    Scope fix (2026-08-12): this used to take every message in the diff range
    and return True on the first trailer found anywhere, so a single trailer
    approved every oversized commit in a two-month range.  It now takes one
    commit's own message; callers must evaluate approval per commit.
    """
    if not isinstance(message, str):
        raise TypeError(
            "_bulk_approval takes a single commit message: a trailer approves only the commit whose message carries it"
        )
    for line in message.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        for trailer in APPROVAL_TRAILERS:
            if not lowered.startswith(trailer):
                continue
            reason = stripped.split(":", 1)[1].strip()
            if reason:
                return True, trailer.rstrip(":"), reason
    return False, "", ""


def _parse_iso_date(text: Any) -> date | None:
    value = str(text or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def load_waivers(path: Path) -> list[dict[str, Any]]:
    """Read the landed-history waiver registry.

    A missing file means "no waivers".  A malformed file raises, so a broken
    registry fails the guard instead of quietly waiving nothing/everything.
    """
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("waiver registry must be a JSON object")
    rows = doc.get("waivers")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("waiver registry 'waivers' must be a list")
    return [dict(row) for row in rows if isinstance(row, dict)]


def waiver_for_commit(
    waivers: list[dict[str, Any]],
    *,
    sha: str,
    guard: str = GUARD_NAME,
    today: date | None = None,
) -> dict[str, Any] | None:
    """The active waiver for exactly this commit and this guard, else None.

    A waiver applies only when every required field is present and non-empty,
    ``commit`` is the full 40-hex sha of this commit, ``guard`` names this
    guard, and ``expires_on`` is still in the future.  There is deliberately
    no wildcard/prefix/"all" form: a non-40-hex ``commit`` matches nothing.
    """
    target = str(sha or "").strip().lower()
    if not _FULL_SHA_RE.match(target):
        return None
    day = today or date.today()
    guard_name = str(guard or "").strip().lower()

    for row in waivers or []:
        if not isinstance(row, dict):
            continue
        if any(not str(row.get(field) or "").strip() for field in WAIVER_REQUIRED_FIELDS):
            continue
        listed = str(row.get("commit") or "").strip().lower()
        if not _FULL_SHA_RE.match(listed) or listed != target:
            continue
        if str(row.get("guard") or "").strip().lower() != guard_name:
            continue
        if _parse_iso_date(row.get("approved_on")) is None:
            continue
        expires = _parse_iso_date(row.get("expires_on"))
        if expires is None or expires <= day:
            continue
        return dict(row)
    return None


def evaluate_range(
    repo_root: Path,
    *,
    base: str,
    head: str,
    max_files: int,
    waivers: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Measure every non-merge commit in base..head against the per-commit limit."""
    waiver_rows = list(waivers or [])
    payload: dict[str, Any] = {
        "ok": False,
        "mode": "diff-range",
        "base": base,
        "head": head,
        "max_files": max_files,
        "commits_scanned": 0,
        "max_commit_files": 0,
        "endpoint_changed_files": None,
        "no_commits": False,
        "violations": [],
        "waived_commits": [],
        "approved_commits": [],
        "error": "",
    }

    try:
        commits = _range_commits(repo_root, base, head)
    except GitRangeError as exc:
        payload["error"] = f"range could not be resolved ({exc})"
        return payload

    payload["commits_scanned"] = len(commits)

    if not commits:
        # Explicit empty-range handling: never max() an empty sequence, never
        # pass silently.  base == head (or a truly empty range) is a real
        # "no commits" result; a range whose only commits are merges changed
        # files that --no-merges cannot attribute, so it is not measurable.
        try:
            endpoint = _git_lines(
                repo_root,
                ["diff", "--name-only", base, head],
                what=f"diff {base} {head}",
            )
        except GitRangeError as exc:
            payload["error"] = f"empty commit list and endpoint diff failed ({exc})"
            return payload
        payload["endpoint_changed_files"] = len(endpoint)
        payload["no_commits"] = True
        if endpoint:
            payload["error"] = (
                f"no non-merge commits in {base}..{head} but {len(endpoint)} file(s) differ — "
                "the range contains only merge commits, which --no-merges cannot attribute to a commit"
            )
            return payload
        payload["ok"] = True
        return payload

    try:
        payload["endpoint_changed_files"] = len(
            _git_lines(repo_root, ["diff", "--name-only", base, head], what=f"diff {base} {head}")
        )
    except GitRangeError:
        # Informational only (this is the OLD, wrong metric kept for context).
        payload["endpoint_changed_files"] = None

    counts: list[int] = []
    for sha in commits:
        try:
            files = _commit_changed_files(repo_root, sha)
        except GitRangeError as exc:
            payload["error"] = f"commit {sha[:12]} could not be measured ({exc})"
            return payload
        count = len(files)
        counts.append(count)
        if count <= max_files:
            continue

        try:
            message = _commit_message(repo_root, sha)
        except GitRangeError as exc:
            payload["error"] = f"commit {sha[:12]} message could not be read ({exc})"
            return payload
        subject = message.strip().splitlines()[0] if message.strip() else ""
        # Approval is evaluated against THIS commit's own message only.
        approved, trailer, reason = _bulk_approval(message)
        row: dict[str, Any] = {
            "sha": sha,
            "short_sha": sha[:12],
            "files": count,
            "subject": subject[:120],
        }
        if approved:
            row.update({"status": "approved", "approval_trailer": trailer, "approval_reason": reason})
            payload["approved_commits"].append(row)
            continue

        waiver = waiver_for_commit(waiver_rows, sha=sha, guard=GUARD_NAME, today=today)
        if waiver is not None:
            row.update(
                {
                    "status": "waived",
                    "waiver_id": str(waiver.get("id") or ""),
                    "waiver_approved_by": str(waiver.get("approved_by") or ""),
                    "waiver_expires_on": str(waiver.get("expires_on") or ""),
                    "waiver_reason": str(waiver.get("reason") or ""),
                }
            )
            payload["waived_commits"].append(row)
            continue

        row.update({"status": "violation", "sample_files": files[:15]})
        payload["violations"].append(row)

    payload["max_commit_files"] = max(counts) if counts else 0
    payload["ok"] = not payload["violations"]
    return payload


def _print_range_text(payload: dict[str, Any]) -> None:
    max_files = payload["max_files"]
    scanned = payload["commits_scanned"]
    violations = payload["violations"]
    waived = payload["waived_commits"]
    approved = payload["approved_commits"]

    if payload.get("error"):
        print(f"Bulk commit guard: FAIL — {payload['error']}")
        return

    if payload["ok"]:
        if payload.get("no_commits"):
            print(f"Bulk commit guard: PASS (no non-merge commits in {payload['base']}..{payload['head']})")
            return
        headline = (
            f"Bulk commit guard: PASS ({scanned} commit(s) measured individually, "
            f"worst commit {payload['max_commit_files']} file(s), limit {max_files})"
        )
        if waived or approved:
            headline = (
                f"Bulk commit guard: PASS WITH EXCEPTIONS ({scanned} commit(s) measured individually, "
                f"worst commit {payload['max_commit_files']} file(s), limit {max_files}; "
                f"{len(waived)} waived, {len(approved)} approved by trailer)"
            )
        print(headline)
        for row in approved:
            print(
                f"  - approved {row['short_sha']} ({row['files']} files) via "
                f"{row['approval_trailer']}: {str(row['approval_reason'])[:120]}"
            )
        for row in waived:
            print(
                f"  - WAIVED {row['short_sha']} ({row['files']} files) by waiver "
                f"{row['waiver_id']} [{row['waiver_approved_by']}, expires {row['waiver_expires_on']}]: "
                f"{str(row['waiver_reason'])[:120]}"
            )
        return

    print(
        f"Bulk commit guard: FAIL — {len(violations)} commit(s) exceed the {max_files}-file limit "
        f"(measured per commit across {scanned} non-merge commit(s) in {payload['base']}..{payload['head']})."
    )
    print(
        "  Bulk dump commits are banned.  Break your work into smaller, "
        "focused commits.  A genuine migration or refactor needs a non-empty "
        "Thomas-Bulk-Change-Approved trailer on that commit itself; already-landed "
        f"history needs an entry in {DEFAULT_WAIVERS}."
    )
    for row in violations[:20]:
        print(f"  - {row['short_sha']} — {row['files']} file(s): {row['subject']}")
    if len(violations) > 20:
        print(f"  ... and {len(violations) - 20} more oversized commit(s)")
    worst = max(violations, key=lambda r: r["files"])
    print(f"  Sample from worst commit {worst['short_sha']} ({worst['files']} files):")
    for name in worst.get("sample_files", []):
        print(f"    - {name}")
    if worst["files"] > len(worst.get("sample_files", [])):
        print(f"    ... and {worst['files'] - len(worst.get('sample_files', []))} more")
    for row in waived:
        print(f"  - WAIVED {row['short_sha']} ({row['files']} files) by waiver {row['waiver_id']}")


def run(
    repo_root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    json_output: bool = False,
    base: str | None = None,
    head: str | None = None,
    waivers_path: Path | str | None = None,
    today: date | None = None,
) -> int:
    # NOTE (R4, praxis-unbypassable-2026-05-29): the unauthenticated
    # THOMAS_BULK_COMMIT_GUARD_DISABLE escape valve was removed — any agent
    # could set it to skip the guard. To land a genuinely large commit, use the
    # native-auth breakglass SKIP path (Windows sign-in, audited) which can skip
    # `thomas-bulk-commit-guard`, or split the change. Server-side this var was
    # already neutralized (set to "") in .github/workflows/gates.yml.
    if base and head:
        # Diff-range mode: the limit is per commit, so measure per commit.
        waiver_file = Path(waivers_path) if waivers_path else (repo_root / DEFAULT_WAIVERS)
        try:
            waivers = load_waivers(waiver_file)
            waiver_error = ""
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            waivers = []
            waiver_error = f"waiver registry {waiver_file} could not be read ({exc})"

        if waiver_error:
            payload: dict[str, Any] = {
                "ok": False,
                "mode": "diff-range",
                "base": base,
                "head": head,
                "max_files": max_files,
                "commits_scanned": 0,
                "max_commit_files": 0,
                "endpoint_changed_files": None,
                "no_commits": False,
                "violations": [],
                "waived_commits": [],
                "approved_commits": [],
                "error": waiver_error,
            }
        else:
            payload = evaluate_range(
                repo_root,
                base=base,
                head=head,
                max_files=max_files,
                waivers=waivers,
                today=today,
            )
        payload["waivers_path"] = str(waiver_file)
        # Legacy keys, kept for existing JSON consumers. In range mode
        # `staged_count` is the WORST SINGLE COMMIT, never the range total.
        payload["staged_count"] = payload["max_commit_files"]
        cleared = payload["approved_commits"] or payload["waived_commits"]
        payload["approved_bulk_change"] = bool(cleared) and not payload["violations"]
        first_trailer = payload["approved_commits"][0] if payload["approved_commits"] else {}
        payload["approval_trailer"] = str(first_trailer.get("approval_trailer", ""))
        payload["approval_reason"] = str(first_trailer.get("approval_reason", ""))

        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_range_text(payload)
        return 0 if payload["ok"] else 1

    # Local / staged mode — unchanged.
    files = _staged_file_count(repo_root)[1]
    count = len(files)
    approved = False
    approval_trailer = ""
    approval_reason = ""
    # Local staged mode: no env-based self-approval (THOMAS_COMMIT_MESSAGE was a
    # self-approval bypass). Use the breakglass SKIP path for a legitimate local
    # large commit.
    ok = count <= max_files

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "staged_count": count,
                    "max_files": max_files,
                    "approved_bulk_change": approved,
                    "approval_trailer": approval_trailer,
                    "approval_reason": approval_reason,
                },
                indent=2,
            )
        )
    elif ok:
        print(f"Bulk commit guard: PASS ({count} staged file(s), limit {max_files})")
    else:
        print(f"Bulk commit guard: FAIL — {count} files staged (limit is {max_files}).")
        print(
            "  Bulk dump commits are banned.  Break your work into "
            "smaller, focused commits.  If this is a genuine migration "
            "or refactor, use a non-empty Thomas-Bulk-Change-Approved "
            "commit trailer with the review/approval reason."
        )
        sample = files[:15]
        for f in sample:
            print(f"  - {f}")
        if count > 15:
            print(f"  ... and {count - 15} more")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Block commits that change too many files at once.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help=f"Maximum changed files per commit (default: {DEFAULT_MAX_FILES}).",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred).",
    )
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    parser.add_argument(
        "--waivers",
        default=None,
        help=f"Landed-history waiver registry (default: {DEFAULT_WAIVERS} under the repo root).",
    )
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(
        repo_root,
        max_files=args.max_files,
        json_output=args.json,
        base=args.base,
        head=args.head,
        waivers_path=args.waivers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
