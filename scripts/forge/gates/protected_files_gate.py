#!/usr/bin/env python3
"""Prevent agent modification of protected policy and enforcement files.

Protected files include:
- GUARDRAILS.md (all instances) - immutable policy docs
- AGENTS.md and related policy docs - startup and repo rules
- tests/test_architecture.py - architecture enforcement tests
- thomas/_architecture.py RULES section - architecture limits

These files contain rules that agents must follow but must not change.
An agent modifying these files is either:
  (a) trying to relax a rule to make their code pass, or
  (b) making an honest mistake.
Either way, the commit should be blocked and the human should decide.

SCOPE: the unit of measurement is ONE COMMIT, in both modes.
- Local/staged mode measures the staged tree and fails closed.
- Diff-range mode (--base/--head) walks `git rev-list --reverse --no-merges
  base..head` and measures each commit against `<sha>^..<sha>`. It previously
  diffed only the two ENDPOINTS of the range, which reported two months of work
  (1923 files) as though a single commit had done it, when the largest real
  commit was 539. Approval is scoped the same way: a trailer approves ONLY the
  commit whose own message carries it, where one trailer anywhere in the range
  previously approved every violation in it.
- Commits that already merged cannot be reworded to carry a trailer. For those,
  a human adds a per-sha, per-guard, expiring entry to
  docs/ops/landed_history_waivers.json. A waived range passes but is reported
  as WAIVED, never as clean.

Audit reference: Adversarial Audit Findings 12, 13, 16 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
PRECOMMIT_BREADCRUMB = ROOT / ".git" / "thomas_precommit_ran"
APPROVAL_TRAILERS = ("thomas-protected-files-approved:", "thomas-breakglass:")
COMMIT_MESSAGE_ENV = "THOMAS_COMMIT_MESSAGE"

GATE_NAME = "protected_files_gate"

# Landed-history waivers: commits that already merged cannot be given an
# approval trailer retroactively (rewriting published history is worse than the
# violation). A waiver names ONE commit sha, for ONE guard, until ONE date.
LANDED_HISTORY_WAIVERS_REL = "docs/ops/landed_history_waivers.json"
LANDED_HISTORY_WAIVERS = ROOT / "docs" / "ops" / "landed_history_waivers.json"
WAIVER_REQUIRED_FIELDS = (
    "id",
    "commit",
    "guard",
    "approved_by",
    "approved_on",
    "expires_on",
    "reason",
)

# git's canonical empty tree; the diff base for a root commit, which has no `^`.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_HEX = frozenset("0123456789abcdef")

# Load protected file lists from config (agent_safety.toml).
# Falls back to empty lists if config doesn't exist.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.brief.safety_config import config as _cfg

    PROTECTED_FILES: tuple[str, ...] = tuple(
        _cfg.protected_policy_files() + _cfg.protected_guardrails_files() + _cfg.protected_enforcement_files()
    )
    PROTECTED_ENFORCEMENT_SCRIPTS: tuple[str, ...] = tuple(_cfg.protected_enforcement_scripts())
except ImportError:
    # Fail-closed fallback: if config can't load, protect the critical files
    # that an attacker would most want to modify. This list must be kept in
    # sync with agent_safety.toml but provides a safety net if the config
    # loader itself is compromised.
    # Audit Finding 4 (Cowork Adversarial Audit, 2026-03-19).
    import warnings

    warnings.warn(
        "agent_safety_config import failed — using hardcoded fallback. This may indicate a compromised config loader.",
        stacklevel=2,
    )
    PROTECTED_FILES = (
        "GUARDRAILS.md",
        "AGENTS.md",
        "AGENT_RULES_QUICK_REFERENCE.md",
        "AGENT_SAFETY_GATES.md",
        "WORKTREE_RULES.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "agent_safety.toml",
        "pyproject.toml",
        ".pre-commit-config.yaml",
        ".gitignore",
        "tests/test_architecture.py",
        "thomas/_architecture.py",
        "docs/monolith_guard_baseline.json",
    )
    PROTECTED_ENFORCEMENT_SCRIPTS = (
        "scripts/validate_agent_changes.py",
        "scripts/forge/gates/protected_files_gate.py",
        "scripts/forge/gates/precommit_skip_policy.py",
        "scripts/forge/gates/exception_handler_gate.py",
        "scripts/crew/brief/safety_config.py",
        "scripts/post_commit_audit.py",
        "scripts/crew/brief/commit.py",
    )


def _changed_files(*, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Fail closed: a git error must not present as an empty change set --
        # for THIS gate that would let protected-file edits slip through as a
        # clean PASS. Surface it so run() FAILs instead.
        raise RuntimeError(proc.stderr.strip() or "git diff --name-only failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _staged_files() -> list[str]:
    return _changed_files()


def _range_commits(base: str, head: str, *, include_merges: bool = False) -> list[str]:
    """Return the commit SHAs in ``base..head``, oldest first.

    Merge commits are excluded by default (``--no-merges``). What that means:
    a merge commit is never measured in its own right. Every commit it brings
    in is measured individually, because those commits are themselves in
    ``base..head``; only content that exists *nowhere but* the merge commit --
    i.e. conflict resolution written by hand during the merge -- goes
    unmeasured. Excluding merges is also what makes ``<sha>^`` unambiguous
    below: a non-merge commit has exactly zero or one parent, so there is no
    silent "first parent wins" guess. A range whose commits are ALL merges is
    therefore unmeasurable and is failed closed by _evaluate_range, never
    passed vacuously.
    """
    if str(base).strip() == str(head).strip():
        return []
    args = ["git", "rev-list", "--reverse"]
    if not include_merges:
        args.append("--no-merges")
    args.append(f"{base}..{head}")
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        # Fail closed: an unenumerable range must not read as "no commits".
        raise RuntimeError(f"git rev-list failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git rev-list failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _commit_diff_base(sha: str) -> str:
    """Resolve the diff base for one non-merge commit (``<sha>^``, or the
    empty tree when ``sha`` is a root commit and has no parent)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{sha}^"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return EMPTY_TREE_SHA
    if proc.returncode == 0 and proc.stdout.strip():
        return f"{sha}^"
    return EMPTY_TREE_SHA


def _commit_changed_files(sha: str) -> list[str]:
    """Files touched by ONE commit -- not by a whole range.

    The range-endpoint diff (``git diff base head``) reports the sum of every
    commit in between as though a single commit had made it. This gate's limit
    is per commit, so the measurement must be per commit too.
    """
    return _changed_files(base=_commit_diff_base(sha), head=sha)


def _commit_message(sha: str) -> str:
    """Return the full message of ONE commit ('' when it cannot be read)."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "")


def _protected_files_approval(message: str) -> tuple[bool, str, str]:
    """Find an explicit protected-file approval trailer in ONE commit message.

    Scope: a trailer approves only the commit whose own message carries it.
    This function therefore takes a single message, never a range's worth of
    them -- passing a sequence used to mean one trailer anywhere in a 597-commit
    range approved every protected-file edit in all of them. The TypeError below
    is deliberate: it makes that shape impossible to reintroduce by accident.

    Local staged commits still fail closed. This trailer path is only for
    server-side diff-range checks, where OS-native approval is unavailable but
    the authorization reason can be preserved in immutable commit history.
    """
    if not isinstance(message, str):
        raise TypeError(
            "_protected_files_approval takes ONE commit message; a sequence of "
            "messages would re-open the range-wide approval hole. Call it once "
            "per offending commit with that commit's own message."
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


def _load_waivers(path: Path | None = None) -> list[dict]:
    """Load landed-history waivers.

    Mirrors docs/ops/monolith_baseline_approvals.json: a versioned object with
    a list of fully-attributed entries. A missing file means "no waivers"; a
    malformed file is an error, not an empty list, so a corrupted registry can
    never read as a clean range.
    """
    target = Path(path) if path is not None else LANDED_HISTORY_WAIVERS
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise RuntimeError(f"landed-history waiver file unreadable ({target}): {exc}") from exc
    try:
        doc = json.loads(raw or "{}")
    except ValueError as exc:
        raise RuntimeError(f"landed-history waiver file is not valid JSON ({target}): {exc}") from exc
    if not isinstance(doc, dict):
        raise RuntimeError(f"landed-history waiver file must be a JSON object ({target})")
    rows = doc.get("waivers")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise RuntimeError(f"landed-history waiver file 'waivers' must be a list ({target})")
    return [dict(row) for row in rows if isinstance(row, dict)]


def _waiver_matches(entry: dict, *, sha: str, guard: str, today: date) -> bool:
    """True when ``entry`` waives exactly this commit, for exactly this guard,
    and has not expired.

    There is no wildcard, prefix or 'all' form on purpose: `commit` must be a
    full 40-character hex sha, so "*", "all", or a 7-char prefix never match.
    """
    values: dict[str, str] = {}
    for field in WAIVER_REQUIRED_FIELDS:
        text = str(entry.get(field) or "").strip()
        if not text:
            return False  # a waiver missing any field does not apply
        values[field] = text

    commit = values["commit"].lower()
    if len(commit) != 40 or not set(commit) <= _HEX:
        return False
    if commit != str(sha or "").strip().lower():
        return False
    if values["guard"] != guard:
        return False

    try:
        expires = date.fromisoformat(values["expires_on"])
    except ValueError:
        return False
    return expires > today  # strictly in the future; an expired waiver never applies


def _find_waiver(sha: str, *, waivers: list[dict], today: date, guard: str = GATE_NAME) -> dict | None:
    for entry in waivers:
        if _waiver_matches(entry, sha=sha, guard=guard, today=today):
            return dict(entry)
    return None


def _evaluate_range(
    base: str,
    head: str,
    protected: set[str],
    *,
    waivers: list[dict],
    today: date,
) -> dict:
    """Evaluate every commit in ``base..head`` against the per-commit limit.

    Each commit is measured on its own diff and judged against its own commit
    message. A commit is clean when it touches no protected file; otherwise it
    needs an approval trailer in its OWN message, or a live waiver naming its
    OWN sha.
    """
    commits = _range_commits(base, head)
    if not commits:
        # Empty-range case, handled explicitly rather than by an empty
        # aggregate that would silently look clean.
        with_merges = _range_commits(base, head, include_merges=True)
        if with_merges:
            return {
                "ok": False,
                "reason": "unmeasurable_merge_only_range",
                "detail": (
                    f"{len(with_merges)} commit(s) in {base}..{head} and every one is a merge; "
                    "--no-merges leaves nothing to measure per commit"
                ),
                "commit_count": 0,
                "merge_commits_skipped": len(with_merges),
                "no_commits": False,
                "violations": [],
                "offending_commits": [],
                "unapproved_commits": [],
                "waived_commits": [],
            }
        return {
            "ok": True,
            "reason": "empty_range",
            "detail": f"no commits in {base}..{head}; nothing was measured",
            "commit_count": 0,
            "merge_commits_skipped": 0,
            "no_commits": True,
            "violations": [],
            "offending_commits": [],
            "unapproved_commits": [],
            "waived_commits": [],
        }

    merge_skipped = max(len(_range_commits(base, head, include_merges=True)) - len(commits), 0)

    offending: list[dict] = []
    all_violations: list[str] = []
    waiver_registry_touched = False

    for sha in commits:
        files = _commit_changed_files(sha)
        if any(_normalize_repo_path(path) == LANDED_HISTORY_WAIVERS_REL for path in files):
            waiver_registry_touched = True
        hits = sorted({_normalize_repo_path(p) for p in files if _is_protected_path(p, protected)})
        if not hits:
            continue
        for path in hits:
            if path not in all_violations:
                all_violations.append(path)
        approved, trailer, reason = _protected_files_approval(_commit_message(sha))
        waiver = None if approved else _find_waiver(sha, waivers=waivers, today=today)
        offending.append(
            {
                "sha": sha,
                "files": hits,
                "approved": bool(approved),
                "approval_trailer": trailer,
                "approval_reason": reason,
                "waived": waiver is not None,
                "waiver_id": str(waiver.get("id") or "") if waiver else "",
                "waiver_approved_by": str(waiver.get("approved_by") or "") if waiver else "",
                "waiver_expires_on": str(waiver.get("expires_on") or "") if waiver else "",
                "waiver_reason": str(waiver.get("reason") or "") if waiver else "",
            }
        )

    unapproved = [row for row in offending if not row["approved"] and not row["waived"]]
    waived = [row for row in offending if row["waived"]]

    ok = not unapproved
    reason = ""
    detail = ""
    if unapproved:
        reason = "unapproved_protected_file_commits"
        detail = f"{len(unapproved)} commit(s) touched protected files with no approval trailer of their own"
    elif waived and waiver_registry_touched:
        # A range may not both write the waiver registry and lean on it.
        ok = False
        reason = "self_waived_range"
        detail = (
            f"{LANDED_HISTORY_WAIVERS_REL} is modified inside {base}..{head} and that same range "
            "relies on a waiver; landed-history waivers must be reviewed before the range that uses them"
        )

    return {
        "ok": ok,
        "reason": reason,
        "detail": detail,
        "commit_count": len(commits),
        "merge_commits_skipped": merge_skipped,
        "no_commits": False,
        "violations": all_violations,
        "offending_commits": offending,
        "unapproved_commits": unapproved,
        "waived_commits": waived,
    }


def _normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def _is_protected_path(path: str, protected: set[str]) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    if normalized in protected:
        return True
    for item in protected:
        prefix = _normalize_repo_path(item)
        if prefix and str(item).replace("\\", "/").endswith("/") and normalized.startswith(f"{prefix}/"):
            return True
    return _is_immutable_policy_doc(path)


def _is_immutable_policy_doc(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    basename = PurePosixPath(normalized).name
    return basename in {"AGENTS.md", "GUARDRAILS.md"}


def _drop_precommit_breadcrumb() -> None:
    """Signal to post-commit audit that pre-commit hooks ran."""
    try:
        PRECOMMIT_BREADCRUMB.parent.mkdir(parents=True, exist_ok=True)
        PRECOMMIT_BREADCRUMB.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Presence alone is not enough — an unsigned planted flag must not
    disable this gate. Mirrors thomas.tools.filesystem signed-flag validation."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    _drop_precommit_breadcrumb()

    # Honour the runtime protection toggle (requires Windows auth to disable).
    if _runtime_protection_disabled():
        if args.json:
            print(json.dumps({"gate": "protected_files_gate", "ok": True, "bypass": "runtime_protection_disabled"}))
        else:
            print("Protected files gate: PASS (runtime protection disabled by human)")
        return 0

    all_protected = set(PROTECTED_FILES) | set(PROTECTED_ENFORCEMENT_SCRIPTS)
    extra: dict = {}
    approved = False
    approval_trailer = ""
    approval_reason = ""
    waived = False

    if args.base and args.head:
        # Diff-range (CI/server-side) mode. Measured PER COMMIT: the range's two
        # endpoints diffed against each other report months of work as though
        # one commit did it, and one approval trailer anywhere in the range then
        # approved all of it. Both are scoped to the individual commit now.
        try:
            result = _evaluate_range(
                args.base,
                args.head,
                all_protected,
                waivers=_load_waivers(),
                today=date.today(),
            )
        except RuntimeError as exc:
            if args.json:
                print(json.dumps({"gate": "protected_files_gate", "ok": False, "error": str(exc)}, sort_keys=True))
            else:
                print(f"Protected files gate: FAIL ({exc})")
            return 1

        violations = list(result["violations"])
        offending = list(result["offending_commits"])
        ok = bool(result["ok"])
        approved = bool(offending) and all(row["approved"] or row["waived"] for row in offending)
        waived = bool(result["waived_commits"])
        for row in offending:
            if row["approval_trailer"]:
                approval_trailer = row["approval_trailer"]
                approval_reason = row["approval_reason"]
                break
        extra = {
            "mode": "diff_range",
            "commit_count": result["commit_count"],
            "merge_commits_skipped": result["merge_commits_skipped"],
            "no_commits": result["no_commits"],
            "reason": result["reason"],
            "detail": result["detail"],
            "offending_commits": offending,
            "unapproved_commits": result["unapproved_commits"],
            "waived_commits": result["waived_commits"],
            "waived": waived,
        }
    else:
        try:
            staged = _staged_files()
        except RuntimeError as exc:
            if args.json:
                print(json.dumps({"gate": "protected_files_gate", "ok": False, "error": str(exc)}, sort_keys=True))
            else:
                print(f"Protected files gate: FAIL ({exc})")
            return 1
        violations = [path for path in staged if _is_protected_path(path, all_protected)]
        # NOTE (R4, praxis-unbypassable-2026-05-29): local staged commits have NO
        # env-based self-approval. An earlier THOMAS_COMMIT_MESSAGE path let an
        # agent self-approve a protected-file edit by setting an env var. Local
        # protected-file edits must go through the native-auth breakglass SKIP path
        # (Windows sign-in, audited) — see precommit_skip_policy / commit_breakglass_guard.
        # Landed-history waivers do NOT apply here either: they exist only for
        # commits that already merged and can no longer carry a trailer.
        extra = {"mode": "staged"}
        ok = len(violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "protected_files_gate",
                    "ok": ok,
                    "violations": violations,
                    "approved_protected_files": approved,
                    "approval_trailer": approval_trailer,
                    "approval_reason": approval_reason,
                    "protected_file_count": len(all_protected),
                    **extra,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            if extra.get("no_commits"):
                print(f"Protected files gate: PASS (no commits in {args.base}..{args.head} — nothing was measured)")
            elif waived:
                print("Protected files gate: PASS (WAIVED — this is not a clean pass)")
                for row in extra.get("waived_commits", []):
                    print(
                        f"  - {row['sha'][:12]} waived by {row['waiver_id']} "
                        f"(approved_by={row['waiver_approved_by']}, expires_on={row['waiver_expires_on']}) "
                        f"for {len(row['files'])} protected file(s): {', '.join(row['files'])}"
                    )
                    print(f"    reason: {row['waiver_reason'][:160]}")
                approved_rows = [r for r in extra.get("offending_commits", []) if r["approved"]]
                for row in approved_rows:
                    print(f"  - {row['sha'][:12]} approved in its own message via {row['approval_trailer']}")
            elif approved:
                print(
                    "Protected files gate: PASS "
                    f"(protected-file approval via {approval_trailer}: {approval_reason[:120]})"
                )
            else:
                print("Protected files gate: PASS")
            if extra.get("merge_commits_skipped"):
                print(
                    f"  note: {extra['merge_commits_skipped']} merge commit(s) skipped (--no-merges); "
                    "their content is measured on the individual commits they merged"
                )
        elif extra.get("reason") in {"unmeasurable_merge_only_range", "self_waived_range"}:
            print("SAFETY GATE FAILED: Protected Files Range Not Measurable")
            print("=" * 70)
            print(f"{extra['reason']}: {extra['detail']}")
            print("=" * 70)
        else:
            print("SAFETY GATE FAILED: Protected Policy Files Modified")
            print("=" * 70)
            print(f"You modified {len(violations)} protected file(s):")
            print()
            print("WHAT YOU DID WRONG:")
            for path in violations:
                if _is_immutable_policy_doc(path):
                    print(f"  - {path}  (immutable policy document)")
                elif path == "tests/test_architecture.py":
                    print(f"  - {path}  (architecture enforcement - fix your code, not the test)")
                elif path.startswith("scripts/"):
                    print(f"  - {path}  (enforcement script - modifying this bypasses safety)")
                else:
                    print(f"  - {path}  (protected policy document)")
            if extra.get("unapproved_commits"):
                print()
                print("WHICH COMMITS (each judged on its own diff and its own message):")
                for row in extra["unapproved_commits"]:
                    print(f"  - {row['sha'][:12]}  {len(row['files'])} protected file(s): {', '.join(row['files'])}")
            print()
            print("HOW TO FIX IT:")
            print("1. Undo your changes to protected files:")
            print("   git checkout HEAD -- " + " ".join(violations))
            print()
            print("2. If you believe a rule needs changing:")
            print("   STOP and ask the user. Do not proceed.")
            print("   Explain what rule you want to change and why.")
            if args.base and args.head:
                print()
                print("   For CI/server-side review after explicit human approval,")
                print("   include a non-empty commit trailer such as:")
                print("   Thomas-Protected-Files-Approved: <ticket or approval reason>")
                print("   The trailer must be in the offending commit's OWN message.")
                print("   It approves that commit only — not the rest of the range.")
                print()
                print("   If the commit has already merged and cannot be reworded, a human")
                print(f"   adds a per-sha, per-guard, expiring entry to {LANDED_HISTORY_WAIVERS_REL}.")
            print()
            print("3. If a test in test_architecture.py fails:")
            print("   Fix your code to comply with the architecture.")
            print("   Do NOT modify the test to make your code pass.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
