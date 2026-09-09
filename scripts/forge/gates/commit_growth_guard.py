#!/usr/bin/env python3
"""Per-file, PER-COMMIT growth guard for Thomas.

Prevents any single file from growing by more than MAX_GROWTH_LINES in a
single commit.  This is the key defense against agents that dump thousands
of lines into a file in one shot.

Two modes, and the distinction matters:

  Local / staged mode (no --base/--head) — unchanged:
      1. For every staged file, compute the line count in the working tree.
      2. Compute the line count at HEAD (or 0 if the file is new).
      3. If the growth exceeds the threshold, FAIL.
     The staged tree IS one prospective commit, so "per commit" is already
     what this measures.

  Diff-range mode (--base and --head) — fixed 2026-08-12:
      The range is expanded into its individual commits and EACH COMMIT is
      measured against ITS OWN FIRST PARENT:

          git rev-list --reverse --no-merges <base>..<head>
          git diff --name-only --diff-filter=ACMR <sha>^ <sha>

      Previously this mode diffed only the two ENDPOINTS of base..head and
      compared that total against a *per-commit* cap.  Over a 597-commit
      range it therefore reported the two-month aggregate as though one
      commit did it (1923 files reported; the largest real commit touched
      539), and a single approval trailer anywhere in the range approved all
      of it.  Both defects are fixed here: the metric is per commit, and a
      trailer approves ONLY the commit whose own message carries it.

Merge commits (--no-merges):
  A merge commit has multiple parents, so `<sha>^` (first parent) would
  measure it against only one side and report the entire other side as
  "growth" that commit introduced.  Merge commits are therefore NOT
  evaluated; the non-merge commits they bring into the range ARE evaluated
  individually, which is where the lines actually originate.  The skipped
  merge SHAs are listed in the output so the omission is visible.  A range
  consisting of merge commits ONLY measures nothing, so it FAILS CLOSED
  rather than reporting a clean pass over zero evaluated content.

Empty range (base == head, or head already an ancestor of base):
  Reported explicitly as `no_commits_in_range` with commits_scanned=0.  It
  is never folded into an ordinary "no file grew too much" pass, and no
  aggregate is computed over the empty sequence.

Waivers for already-landed history:
  Commits that already merged cannot be given trailers retroactively.
  docs/ops/landed_history_waivers.json (same shape as
  docs/ops/monolith_baseline_approvals.json) may waive a violation for ONE
  exact 40-hex commit SHA, for THIS guard by name, until expires_on passes.
  There is no wildcard, prefix, or "all" form.  Every applied waiver is
  named in the output, so a waived pass never reads as a clean pass.

There is no environment-variable bypass.  Use the native-auth breakglass
SKIP path (Windows sign-in, audited) to skip `thomas-commit-growth-guard`,
or split the change.

Exit codes:
  0 — every evaluated commit is within the growth budget (or approved/waived)
  1 — one or more commits exceed the per-commit growth cap, or the range
      could not be evaluated
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# ── Configurable limits ──────────────────────────────────────────────────
# Maximum net lines a single file may grow in one commit.
DEFAULT_MAX_GROWTH = 300
APPROVAL_TRAILERS = (
    "thomas-commit-growth-approved:",
    "thomas-growth-approved:",
    "thomas-breakglass:",
)

# ── Landed-history waivers ───────────────────────────────────────────────
# Mirrors the docs/ops/monolith_baseline_approvals.json idiom.
GUARD_NAME = "commit-growth-guard"
WAIVERS_REL_PATH = "docs/ops/landed_history_waivers.json"
WAIVER_REQUIRED_FIELDS = (
    "id",
    "commit",
    "guard",
    "approved_by",
    "approved_on",
    "expires_on",
    "reason",
)
# Full 40-hex only.  This is what makes prefix / wildcard / "all" waivers
# structurally impossible rather than merely discouraged.
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# git's canonical empty tree — stands in as the "parent" of a root commit so
# every line in a root commit counts as growth instead of crashing on `<sha>^`.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# File extensions to monitor.  Only these are checked.
MONITORED_EXTENSIONS: set[str] = {
    "py",
    "js",
    "mjs",
    "cjs",
    "jsx",
    "ts",
    "tsx",
    "css",
    "html",
}

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "coverage",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    ".feature_backups",
}


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


def _is_skipped(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in SKIP_DIR_NAMES for p in parts)


def _is_monitored(rel: str) -> bool:
    if _is_skipped(rel):
        return False
    return Path(rel).suffix.lstrip(".").lower() in MONITORED_EXTENSIONS


def _changed_files(repo_root: Path, *, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only", "--diff-filter=ACMR"]
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
        # Fail CLOSED: a git error must not masquerade as an empty (clean) change set —
        # that would silently PASS the gate. Surface it so run() FAILs instead of treating
        # "0 files" and "git broke" the same.
        raise RuntimeError(proc.stderr.strip() or "git diff --name-only failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _staged_files(repo_root: Path) -> list[str]:
    return _changed_files(repo_root)


def _rev_list(repo_root: Path, base: str, head: str, *, no_merges: bool) -> list[str]:
    """Commit SHAs in base..head, oldest first.  Raises on git failure."""
    if base == head:
        return []
    args = ["git", "rev-list", "--reverse"]
    if no_merges:
        args.append("--no-merges")
    args.append(f"{base}..{head}")
    proc = subprocess.run(args, cwd=repo_root, capture_output=True, text=True)
    if proc.returncode != 0:
        # Fail CLOSED, same reasoning as _changed_files: an unreadable range must
        # not look like an empty (therefore clean) one.
        raise RuntimeError(proc.stderr.strip() or "git rev-list failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _range_commits(repo_root: Path, base: str, head: str) -> list[str]:
    """Non-merge commits in base..head, oldest first.  These get evaluated."""
    return _rev_list(repo_root, base, head, no_merges=True)


def _range_all_commits(repo_root: Path, base: str, head: str) -> list[str]:
    """Every commit in base..head, merges included.  Used to tell an empty range
    apart from a merges-only range — the latter measures nothing and must not pass."""
    return _rev_list(repo_root, base, head, no_merges=False)


def _commit_parent(repo_root: Path, sha: str) -> str:
    """First parent of `sha`, or the empty tree for a root commit.

    Only non-merge commits reach here, so "first parent" is the only parent —
    see the module docstring on --no-merges.
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{sha}^"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    parent = (proc.stdout or "").strip()
    if proc.returncode != 0 or not parent:
        return EMPTY_TREE_SHA
    return parent


def _commit_message(repo_root: Path, sha: str) -> str:
    """Full message of exactly ONE commit.

    This replaced `_commit_messages(base, head)`.  That helper handed the
    approval check every message in the range at once, which is what let a
    trailer in any one commit approve every other commit's violations.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _growth_approval(messages: list[str]) -> tuple[bool, str, str]:
    """Scan commit message(s) for an approval trailer.

    In diff-range mode this is now called with exactly ONE message — the
    offending commit's own — so a trailer never reaches past its own commit.
    """
    for msg in messages:
        for line in msg.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            for trailer in APPROVAL_TRAILERS:
                if not lowered.startswith(trailer):
                    continue
                reason = stripped.split(":", 1)[1].strip()
                if reason:
                    return True, trailer.rstrip(":"), reason
    return False, "", ""


def _load_waivers(repo_root: Path) -> list[dict]:
    """Read docs/ops/landed_history_waivers.json.

    A missing, unparseable or malformed registry yields NO waivers, which is
    the fail-closed direction: fewer waivers can only make the guard stricter.
    """
    path = repo_root / WAIVERS_REL_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        doc = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(doc, dict):
        return []
    rows = doc.get("waivers")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _waiver_for_commit(waivers: list[dict], sha: str, *, today: date) -> dict | None:
    """The waiver that applies to EXACTLY this commit, for EXACTLY this guard.

    A waiver applies only when all of the following hold:
      * every required field is present and non-empty;
      * `commit` is a full 40-hex SHA equal to `sha` — no prefix matching, so
        there is no wildcard / prefix / "all" form to abuse;
      * `guard` names this guard exactly;
      * `expires_on` parses as YYYY-MM-DD and is strictly in the future.
    Anything else does not apply — an expired or half-filled waiver is not a
    waiver.
    """
    target = str(sha or "").strip().lower()
    if not _FULL_SHA_RE.match(target):
        return None

    for row in waivers:
        fields = {key: str(row.get(key) or "").strip() for key in WAIVER_REQUIRED_FIELDS}
        if not all(fields.values()):
            continue
        commit = fields["commit"].lower()
        if not _FULL_SHA_RE.match(commit) or commit != target:
            continue
        if fields["guard"].lower() != GUARD_NAME:
            continue
        try:
            expires = date.fromisoformat(fields["expires_on"])
        except ValueError:
            continue
        if expires <= today:
            continue
        return {
            "id": fields["id"],
            "commit": commit,
            "guard": fields["guard"],
            "approved_by": fields["approved_by"],
            "approved_on": fields["approved_on"],
            "expires_on": fields["expires_on"],
            "reason": fields["reason"],
        }
    return None


def _working_tree_lines(repo_root: Path, rel: str) -> int:
    path = repo_root / rel
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _head_lines(repo_root: Path, rel: str) -> int:
    """Line count of the file at HEAD.  Returns 0 for new files."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if proc.returncode != 0:
        return 0  # new file
    text = proc.stdout
    if not text:
        return 0
    return len(text.splitlines())


def _rev_lines(repo_root: Path, rev: str, rel: str) -> int:
    proc = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if proc.returncode != 0 or not proc.stdout:
        return 0
    return len(proc.stdout.splitlines())


def _evaluate_commit(
    repo_root: Path,
    sha: str,
    *,
    max_growth: int,
    waivers: list[dict],
    today: date,
) -> dict:
    """Measure ONE commit against ITS OWN parent, then resolve ITS OWN approval."""
    parent = _commit_parent(repo_root, sha)
    files = _changed_files(repo_root, base=parent, head=sha)

    violations: list[dict] = []
    scanned = 0
    for rel in files:
        if not _is_monitored(rel):
            continue
        scanned += 1
        current = _rev_lines(repo_root, sha, rel)
        prior = _rev_lines(repo_root, parent, rel)
        growth = current - prior
        if growth > max_growth:
            violations.append(
                {
                    "commit": sha,
                    "parent": parent,
                    "path": rel,
                    "prior_lines": prior,
                    "current_lines": current,
                    "growth": growth,
                    "max_growth": max_growth,
                    "is_new_file": prior == 0,
                }
            )

    record: dict = {
        "commit": sha,
        "parent": parent,
        "files_scanned": scanned,
        "violations": violations,
        "approved": False,
        "approval_trailer": "",
        "approval_reason": "",
        "waived": False,
        "waiver": None,
        "ok": not violations,
    }
    if not violations:
        return record

    # Per-commit approval: this commit's OWN message, and nothing else.
    approved, trailer, reason = _growth_approval([_commit_message(repo_root, sha)])
    if approved:
        record["approved"] = True
        record["approval_trailer"] = trailer
        record["approval_reason"] = reason
        record["ok"] = True
        return record

    waiver = _waiver_for_commit(waivers, sha, today=today)
    if waiver is not None:
        record["waived"] = True
        record["waiver"] = waiver
        record["ok"] = True
    return record


def _emit(payload: dict, *, json_output: bool, max_growth: int) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    violations = list(payload.get("violations") or [])
    waived = list(payload.get("waived_commits") or [])
    approved = list(payload.get("approved_commits") or [])
    skipped_merges = list(payload.get("merge_commits_skipped") or [])

    if payload.get("reason") == "no_commits_in_range":
        print(
            "Commit growth guard: NO COMMITS IN RANGE "
            f"({payload.get('base')}..{payload.get('head')}) — 0 commits evaluated, nothing measured."
        )
        return

    if payload.get("ok"):
        if waived:
            print(
                f"Commit growth guard: PASS (WAIVED) — {len(violations)} violation(s) across "
                f"{len(waived)} commit(s) resolved by landed-history waiver, NOT by a clean measurement."
            )
            for row in waived:
                print(
                    f"  - waiver {row['waiver_id']} covers {row['commit'][:12]} "
                    f"(approved_by={row['approved_by']}, expires_on={row['expires_on']}): {row['reason'][:120]}"
                )
        for row in approved:
            print(
                f"Commit growth guard: PASS (approved) — {row['commit'][:12]} via "
                f"{row['trailer']}: {row['reason'][:120]}"
            )
        if not waived and not approved:
            print(
                f"Commit growth guard: PASS (no file grew by more than {max_growth} lines "
                f"in any of {payload.get('commits_scanned', 0)} commit(s))"
            )
    elif payload.get("error"):
        print(f"Commit growth guard: FAIL ({payload['error']})")
    else:
        unapproved = list(payload.get("unapproved_commits") or [])
        unapproved_set = set(unapproved)
        print(
            f"Commit growth guard: FAIL — {len(violations)} file-growth violation(s) across "
            f"{len(unapproved)} unapproved commit(s) (of {payload.get('commits_scanned', 0)} evaluated)."
        )
        print(
            f"  The per-commit growth cap is {max_growth} lines.  "
            f"Split your changes across multiple files or "
            f"multiple commits with meaningful intermediate states."
        )
        for v in violations:
            # Only the still-unapproved commits' violations are actionable here;
            # approved/waived ones are named by their own lines above.
            if unapproved_set and v.get("commit") not in unapproved_set:
                continue
            tag = " (NEW FILE)" if v["is_new_file"] else ""
            prefix = f"{str(v.get('commit') or '')[:12]} " if v.get("commit") else ""
            print(f"  - {prefix}{v['path']}: {v['prior_lines']} -> {v['current_lines']} (+{v['growth']} lines){tag}")

    if skipped_merges:
        print(
            f"  note: {len(skipped_merges)} merge commit(s) not evaluated (--no-merges); "
            "their content is measured in the non-merge commits they bring in: "
            + ", ".join(sha[:12] for sha in skipped_merges[:10])
        )


def _empty_range_payload(
    *,
    ok: bool,
    base: str,
    head: str,
    max_growth: int,
    reason: str,
    commits_in_range: int,
    merge_shas: list[str],
) -> dict:
    """Payload for a range where ZERO commits were measured.

    Kept explicit (rather than falling through to the normal aggregation) so
    "we measured nothing" can never print as "nothing grew too much".
    """
    return {
        "ok": ok,
        "mode": "diff-range",
        "base": base,
        "head": head,
        "reason": reason,
        "max_growth": max_growth,
        "commits_in_range": commits_in_range,
        "commits_scanned": 0,
        "staged_count": 0,
        "files_scanned": 0,
        "violations": [],
        "commits": [],
        "approved_growth": False,
        "approval_trailer": "",
        "approval_reason": "",
        "waived_growth": False,
        "approved_commits": [],
        "waived_commits": [],
        "unapproved_commits": [],
        "merge_commits_skipped": list(merge_shas),
    }


def _run_diff_range(
    repo_root: Path,
    *,
    max_growth: int,
    json_output: bool,
    base: str,
    head: str,
    today: date,
) -> int:
    try:
        all_commits = _range_all_commits(repo_root, base, head)
        commits = _range_commits(repo_root, base, head)
    except RuntimeError as exc:
        payload = {"ok": False, "mode": "diff-range", "base": base, "head": head, "error": str(exc)}
        _emit(payload, json_output=json_output, max_growth=max_growth)
        return 1

    non_merge = set(commits)
    merge_shas = [sha for sha in all_commits if sha not in non_merge]

    # Empty range (base == head, or head already an ancestor of base).  Reported
    # explicitly — never as an ordinary "nothing grew" pass, and never by taking
    # an aggregate over an empty sequence.
    if not all_commits:
        payload = _empty_range_payload(
            ok=True,
            base=base,
            head=head,
            max_growth=max_growth,
            reason="no_commits_in_range",
            commits_in_range=0,
            merge_shas=[],
        )
        _emit(payload, json_output=json_output, max_growth=max_growth)
        return 0

    # Merges-only range: --no-merges leaves nothing to measure, so a "pass" here
    # would be a pass over zero evaluated content.  Fail closed instead.
    if not commits:
        payload = _empty_range_payload(
            ok=False,
            base=base,
            head=head,
            max_growth=max_growth,
            reason="merge_commits_only",
            commits_in_range=len(all_commits),
            merge_shas=merge_shas,
        )
        payload["error"] = (
            f"{len(merge_shas)} merge commit(s) and no non-merge commits in {base}..{head}; "
            "nothing could be measured per commit"
        )
        _emit(payload, json_output=json_output, max_growth=max_growth)
        return 1

    waivers = _load_waivers(repo_root)

    records: list[dict] = []
    for sha in commits:
        try:
            records.append(_evaluate_commit(repo_root, sha, max_growth=max_growth, waivers=waivers, today=today))
        except RuntimeError as exc:
            payload = {
                "ok": False,
                "mode": "diff-range",
                "base": base,
                "head": head,
                "error": f"{sha}: {exc}",
            }
            _emit(payload, json_output=json_output, max_growth=max_growth)
            return 1

    violations = [v for rec in records for v in rec["violations"]]
    approved_commits = [
        {"commit": r["commit"], "trailer": r["approval_trailer"], "reason": r["approval_reason"]}
        for r in records
        if r["approved"]
    ]
    waived_commits = [
        {
            "commit": r["commit"],
            "waiver_id": r["waiver"]["id"],
            "approved_by": r["waiver"]["approved_by"],
            "approved_on": r["waiver"]["approved_on"],
            "expires_on": r["waiver"]["expires_on"],
            "reason": r["waiver"]["reason"],
        }
        for r in records
        if r["waived"] and r["waiver"]
    ]
    unapproved_commits = [r["commit"] for r in records if not r["ok"]]
    ok = not unapproved_commits

    files_scanned = sum(r["files_scanned"] for r in records)
    payload = {
        "ok": ok,
        "mode": "diff-range",
        "base": base,
        "head": head,
        "max_growth": max_growth,
        "commits_in_range": len(all_commits),
        "commits_scanned": len(records),
        "files_scanned": files_scanned,
        # Back-compat key: files examined by this run.
        "staged_count": files_scanned,
        "violations": violations,
        "commits": records,
        # True only when violations existed AND every offending commit carried
        # its own trailer.  A mixed run (one approved, one not) is False.
        "approved_growth": bool(violations) and not unapproved_commits and bool(approved_commits),
        "approval_trailer": approved_commits[0]["trailer"] if approved_commits else "",
        "approval_reason": approved_commits[0]["reason"] if approved_commits else "",
        "waived_growth": bool(waived_commits),
        "approved_commits": approved_commits,
        "waived_commits": waived_commits,
        "unapproved_commits": unapproved_commits,
        "merge_commits_skipped": merge_shas,
    }
    _emit(payload, json_output=json_output, max_growth=max_growth)
    return 0 if ok else 1


def _run_staged(repo_root: Path, *, max_growth: int, json_output: bool) -> int:
    """Local/staged mode — unchanged behaviour.

    The staged tree is a single prospective commit, so this is already a
    per-commit measurement.  There is no trailer self-approval here
    (THOMAS_COMMIT_MESSAGE was a self-approval bypass, R4) and no waiver
    path: waivers exist only for history that already landed.
    """
    try:
        staged = _staged_files(repo_root)
    except RuntimeError as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Commit growth guard: FAIL ({exc})")
        return 1

    violations: list[dict] = []
    for rel in staged:
        if not _is_monitored(rel):
            continue
        current = _working_tree_lines(repo_root, rel)
        prior = _head_lines(repo_root, rel)
        growth = current - prior
        if growth > max_growth:
            violations.append(
                {
                    "path": rel,
                    "prior_lines": prior,
                    "current_lines": current,
                    "growth": growth,
                    "max_growth": max_growth,
                    "is_new_file": prior == 0,
                }
            )

    ok = len(violations) == 0

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "mode": "staged",
                    "max_growth": max_growth,
                    "staged_count": len(staged),
                    "violations": violations,
                    "approved_growth": False,
                    "approval_trailer": "",
                    "approval_reason": "",
                },
                indent=2,
            )
        )
    elif ok:
        print(f"Commit growth guard: PASS (no file grew by more than {max_growth} lines)")
    else:
        print(
            f"Commit growth guard: FAIL — {len(violations)} file(s) "
            f"grew by more than {max_growth} lines in this commit."
        )
        print(
            f"  The per-commit growth cap is {max_growth} lines.  "
            f"Split your changes across multiple files or "
            f"multiple commits with meaningful intermediate states."
        )
        for v in violations:
            tag = " (NEW FILE)" if v["is_new_file"] else ""
            print(f"  - {v['path']}: {v['prior_lines']} -> {v['current_lines']} (+{v['growth']} lines){tag}")

    return 0 if ok else 1


def run(
    repo_root: Path,
    *,
    max_growth: int = DEFAULT_MAX_GROWTH,
    json_output: bool = False,
    base: str | None = None,
    head: str | None = None,
    today: date | None = None,
) -> int:
    if _runtime_protection_disabled():
        if not json_output:
            print("Commit growth guard: PASS (runtime protection disabled by human)")
        return 0

    # NOTE (R4, praxis-unbypassable-2026-05-29): the unauthenticated
    # THOMAS_COMMIT_GROWTH_GUARD_DISABLE escape valve was removed — any agent
    # could set it to skip the guard. Use the native-auth breakglass SKIP path
    # (Windows sign-in, audited) to skip `thomas-commit-growth-guard`, or split
    # the change.

    if base and head:
        return _run_diff_range(
            repo_root,
            max_growth=max_growth,
            json_output=json_output,
            base=base,
            head=head,
            today=today or date.today(),
        )
    return _run_staged(repo_root, max_growth=max_growth, json_output=json_output)


def main() -> int:
    parser = argparse.ArgumentParser(description=("Block commits where any single file grows by too many lines."))
    parser.add_argument(
        "--max-growth",
        type=int,
        default=DEFAULT_MAX_GROWTH,
        help=f"Max net line growth per file (default: {DEFAULT_MAX_GROWTH}).",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred).",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Optional git base ref/SHA for diff-range mode (each commit in base..head is measured separately).",
    )
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(repo_root, max_growth=args.max_growth, json_output=args.json, base=args.base, head=args.head)


if __name__ == "__main__":
    raise SystemExit(main())
