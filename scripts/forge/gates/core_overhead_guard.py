#!/usr/bin/env python3
"""Prevent accidental edits to shared Thomas overhead files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forge.gates import _commit_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "docs" / "core_overhead_manifest.json"
UNLOCK_ENV = "THOMAS_CORE_OVERHEAD_UNLOCK"
AGENT_ROLE_ENV = "THOMAS_AGENT_ROLE"
ORCHESTRATOR_ROLES = {"orchestrator", "thomas_orchestrator", "swarm_orchestrator"}
# A commit that already landed cannot be reworded, so its approval is read from its OWN message. Two things can approve it:
# * the promoter's block AND the promoter's own record under its cage folder saying the card landed as this very commit
#   (a verified record: a commit writer cannot write there); this is the only approval a range checked on the command
#   line or in CI accepts;
# * in a real local pre-push run only, a Thomas-Protected-Files-Approved / Thomas-Breakglass trailer with a reason. That
#   one is TEXT A COMMITTER WROTE, exactly as strong as it is in protected_files_gate.py, and is read from the message's
#   real trailer block only.
APPROVAL_TRAILERS = ("thomas-protected-files-approved", "thomas-breakglass")
PROMOTER_BLOCK = {
    "thomas-submitted-by": "thomas",
    "thomas-committed-by": "self-change-promoter",
    "thomas-gated": "owner-approved/windows-sign-in",
}
WINDOWS_LEDGER = r"C:\ProgramData\ThomasCage"  # outbox/<submission id>.verdict.json is written there when a card lands
SUBMISSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def _normalize(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _truthy(value: str | None) -> bool:
    v = str(value or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _is_orchestrator_role() -> bool:
    role = _normalize(os.environ.get(AGENT_ROLE_ENV, "")).lower()
    return role in ORCHESTRATOR_ROLES


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"invalid manifest JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {path}")
    return data


def _manifest_files(manifest: dict) -> set[str]:
    files = manifest.get("protected_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("manifest must define non-empty protected_files[]")
    out: set[str] = set()
    for item in files:
        rel = _normalize(item)
        if not rel:
            continue
        out.add(rel)
    if not out:
        raise RuntimeError("manifest protected_files[] resolved to empty")
    return out


def _git(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    """The one place this guard starts git, so the repository's count of direct launches goes down, not up."""
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, input=input_text)


def _git_changed(base: str, head: str) -> list[str]:
    cmd = ["git", "diff", "--name-only", base, head]
    proc = _git(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return sorted({_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)})


def _is_git_repo() -> bool:
    cmd = ["git", "rev-parse", "--is-inside-work-tree"]
    proc = _git(cmd)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _git_staged_changed() -> list[str]:
    candidates = [
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--staged", "--name-only"],
    ]
    errors: list[str] = []
    for cmd in candidates:
        proc = _git(cmd)
        if proc.returncode == 0:
            return sorted({_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)})
        errors.append(f"{' '.join(cmd)} :: {proc.stderr.strip() or proc.stdout.strip()}")
    raise RuntimeError("git diff failed:\n" + "\n".join(errors))


def _default_ledger() -> str | None:
    """Where the promoter keeps its records on this host. Not read from the environment; only Windows has one."""
    return WINDOWS_LEDGER if os.name == "nt" else None


def _checkout_trees() -> list[Path]:
    """The checkout and the main checkout of a linked worktree: folders the checked-out files can reach."""
    trees = [ROOT.resolve()]
    common = _git(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if common.returncode == 0 and common.stdout.strip():
        trees.append(Path(common.stdout.strip()).resolve().parent)
    return trees


def _ledger_problem(path: Path) -> str | None:
    if not path.is_absolute() or (os.name == "nt" and not path.drive):
        return "it is not an absolute path with a drive"
    resolved = path.resolve()
    for tree in _checkout_trees():
        if resolved == tree or tree in resolved.parents or resolved in tree.parents:
            return f"it is, or holds, the checkout {tree}"
    return None


def _trusted_ledger(requested: str | None) -> Path | None:
    """The folder the promoter's records are read from, or None: the promoter path is then OFF and approves nothing.

    A folder the checkout holds or sits inside is a folder a commit writer controls, so it is refused; a refused --ledger
    is ignored with a warning and the host's own folder is tried."""
    for label, raw in (("--ledger", requested), ("default", _default_ledger())):
        if not raw:
            continue
        problem = _ledger_problem(Path(raw))
        if problem is None:
            return Path(raw).resolve()
        print(f"Core overhead guard: ignoring the {label} promoter ledger {raw}: {problem}", file=sys.stderr)
    return None


def _real_trailers(message: str) -> dict[str, list[str]]:
    """Only the message's real trailer block (git's own reading of its last paragraph), never every line of it."""
    parsed = _git(["git", "interpret-trailers", "--parse"], input_text=message)
    out: dict[str, list[str]] = {}
    if parsed.returncode != 0:
        return out
    for line in parsed.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out.setdefault(key.strip().lower(), []).append(value.strip())
    return out


def _promoter_approved(sha: str, message: str, ledger: Path | None) -> bool:
    """The promoter's block counts only if its own record says this card landed AS THIS COMMIT (text alone is forgeable)."""
    if ledger is None:
        return False
    found = _real_trailers(message)
    for key, want in PROMOTER_BLOCK.items():
        if found.get(key) != [want]:
            return False
    ids = found.get("thomas-submission-id", [])
    if len(ids) != 1 or not SUBMISSION_ID.match(ids[0]):
        return False
    try:
        record = json.loads((ledger / "outbox" / f"{ids[0]}.verdict.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False  # a ledger that cannot be read approves nothing
    return (
        isinstance(record, dict)
        and record.get("submission_id") == ids[0]
        and record.get("status") == "landed"
        and str(record.get("commit_sha", "")).lower() == sha.lower()
    )


def _commit_approved(sha: str, message: str, ledger: Path | None, *, text_trailers: bool) -> bool:
    """True when ONE commit's own message carries an approval. Never takes a range's worth of messages."""
    if text_trailers:
        found = _real_trailers(message)
        if any(any(v for v in found.get(t, [])) for t in APPROVAL_TRAILERS):
            return True
    return _promoter_approved(sha, message, ledger)


def _push_mode(base: str | None, head: str | None, push: bool) -> tuple[str, str, bool] | None:
    """(from, to, text trailers count) for a range to judge, or None for an ordinary commit-time check.

    A range given on the command line (CI, a person) takes only a verified promoter record. Otherwise it must be a real
    local pre-push run (see _commit_base.pre_push_range); refs in the environment alone never make a run a push."""
    if base or head:
        return (base, head, False) if base and head and _commit_base.ZERO_SHA not in (base, head) else None
    pushed = _commit_base.pre_push_range(ROOT, forced=push)
    return (pushed[0], pushed[1], True) if pushed else None


def _staged_protected(protected: set[str]) -> bool:
    """True when a protected file is staged (a commit in the making) or the index cannot be read."""
    try:
        return any(rel in protected for rel in _git_staged_changed())
    except RuntimeError:
        return True


def _judge_range(
    base: str, head: str, protected: set[str], ledger: Path | None, *, text_trailers: bool
) -> tuple[list[str], set[str]]:
    """(commits with no approval of their own, protected files the range itself changes) for base..head.

    Merges are judged too, by what the merge adds that neither parent had (git diff-tree --cc)."""
    listing = _git(["git", "rev-list", "--reverse", f"{base}..{head}"])
    if listing.returncode != 0:
        raise RuntimeError(f"git rev-list failed: {listing.stderr.strip()}")
    bad: list[str] = []
    explained: set[str] = set()
    tree = ["git", "-c", "core.quotepath=false", "diff-tree", "--root", "--cc", "--no-commit-id", "--name-only", "-r"]
    for sha in listing.stdout.split():
        files = _git([*tree, sha])
        hits = {_normalize(f) for f in files.stdout.splitlines()} & protected
        if files.returncode == 0 and not hits:
            continue
        explained |= hits
        message = _git(["git", "show", "-s", "--format=%B", sha])
        if (
            files.returncode != 0
            or message.returncode != 0
            or not _commit_approved(sha, message.stdout, ledger, text_trailers=text_trailers)
        ):
            bad.append(sha)
    return bad, explained


def _resolve_changed_files(
    *,
    explicit_files: Iterable[str],
    base: str | None,
    head: str | None,
) -> list[str]:
    normalized_explicit = sorted({_normalize(p) for p in explicit_files if _normalize(p)})
    if normalized_explicit:
        return normalized_explicit
    if base and head:
        return _git_changed(base, head)
    if base or head:
        raise RuntimeError("both --base and --head are required together")
    if not _is_git_repo():
        return []
    return _git_staged_changed()


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block accidental edits to shared Thomas overhead files.")
    parser.add_argument("--base", default=None, help="base git SHA for diff mode")
    parser.add_argument("--head", default=None, help="head git SHA for diff mode")
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="path to core overhead manifest JSON",
    )
    parser.add_argument("--push", action="store_true", help="a pre-push run: read the range from pre-commit's refs")
    parser.add_argument(
        "--ledger", default=None, help="the promoter's own folder, if not the host's; it must be trusted"
    )
    parser.add_argument("files", nargs="*", help="optional explicit file list")
    args = parser.parse_args(argv)

    if _is_orchestrator_role():
        print("Core overhead guard: SKIP (orchestrator role exempt via THOMAS_AGENT_ROLE)")
        return 0

    try:
        manifest = _load_manifest(Path(args.manifest))
        protected = _manifest_files(manifest)
        changed = _resolve_changed_files(
            explicit_files=args.files,
            base=args.base,
            head=args.head,
        )
    except Exception as exc:
        print("Core overhead guard: FAIL")
        print(f"- {exc}")
        return 1

    touched = sorted(rel for rel in changed if rel in protected)
    if not touched:
        print("Core overhead guard: PASS")
        print("- no protected overhead files changed")
        return 0

    if _truthy(os.environ.get(UNLOCK_ENV)):
        print("Core overhead guard: PASS (unlocked)")
        for rel in touched:
            print(f"- intentional protected edit: {rel}")
        return 0

    pushed = _push_mode(args.base, args.head, args.push)
    if pushed is not None and not _staged_protected(protected):
        ledger = _trusted_ledger(args.ledger)
        try:
            unapproved, explained = _judge_range(pushed[0], pushed[1], protected, ledger, text_trailers=pushed[2])
        except (RuntimeError, OSError) as exc:
            print("Core overhead guard: FAIL")
            print(f"- {exc}")
            return 1
        unexplained = [rel for rel in touched if rel not in explained]
        if unexplained:
            print("Core overhead guard: FAIL")
            print("- the pushed range does not account for these protected files, so it is not judged as a push:")
            for rel in unexplained:
                print(f"- {rel}")
            return 1
        if not unapproved:
            print("Core overhead guard: PASS (every commit that touched a protected file carries its own approval)")
            for rel in touched:
                print(f"- approved protected edit: {rel}")
            return 0
        print("Core overhead guard: FAIL")
        print("- commits that touched protected overhead files with no approval in their own message:")
        for sha in unapproved:
            print(f"- {sha}")
        where = f"{ledger}" if ledger else "no trusted ledger on this host, so the promoter path is off"
        print(f"- the promoter's block counts only when its own record ({where}) says the card landed as that commit")
        if not pushed[2]:
            print(
                "- a range checked on the command line takes only that record; a trailer a committer wrote does not count"
            )
        return 1

    print("Core overhead guard: FAIL")
    print("- protected Thomas overhead files were modified:")
    for rel in touched:
        print(f"- {rel}")
    print(f"- to edit intentionally, set {UNLOCK_ENV}=1")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
