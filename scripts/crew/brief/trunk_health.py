#!/usr/bin/env python3
"""Trunk health: session start says whether the trunk can still sync.

WHY THIS EXISTS (branch-equilibrium plan, phase 2 Task 1, docs/superpowers/
plans/2026-08-27-branch-equilibrium.md): the 2026-08-27 cleanup found ``dev``
746 commits unpushed because the pre-push gate battery had been failing
silently for weeks -- nothing at session start ever said "the trunk cannot
sync" or "the last push attempt was blocked". Worktree sprawl and branch
sprawl already have a voice at session start (``_startup_worktree_inventory``,
``_startup_branch_inventory`` in ``startup_signals.py``); the trunk's own
syncability did not. This module is that voice: one ``TRUNK:`` line, printed
every session, that can never be silently wrong because it is either a live
git read or an honestly-aged cache, never a guess.

SEAM PRECEDENT (``incident_surfacing.py``, phase 1.5 Task 3): a self-contained
module with its own ``summarize()`` (never raises) and ``render_text()``
(turns the summary into the one line a human reads), imported by
``startup_signals.py``/``startup_router.py`` through a single defensive
wrapper call -- the same shape as ``_startup_incident_surfacing`` /
``incident_surfacing.render_text``. This module follows that shape exactly:
whatever goes wrong inside ``summarize()`` is caught and reported as
``{"ok": False, ...}``, never propagated, matching this program's hardening
rule that session start must never fail.

CHEAP LIVE READS, NEVER A FETCH: ``count_unpushed``/``count_branches``/
``count_stashes`` are ``for-each-ref``, ``stash list``, and
``rev-list --count`` against refs already on disk -- no network call, no
``git fetch``. A session-start check that silently fetched would be slow,
noisy (mutates ``FETCH_HEAD``/remote-tracking state), and wrong for the
"cheap" contract this line exists to satisfy. ``dev-origin`` is this repo's
actual push remote (see ``git remote -v``); a fixture repo, or a real repo
missing that remote-tracking ref, degrades honestly to ``unknown (<reason>)``
rather than guessing zero or raising -- "honest zero" and "unknown-not-fake"
are two different, deliberately distinct outcomes (see ``count_unpushed``'s
own docstring). One consequence of never fetching, found by adversarial
review and fixed in this file's fix round 1 (I1): the remote branch count
is the on-disk ``refs/remotes/<remote>`` MIRROR, not a live read -- it can
run persistently higher than the real remote (deleted-but-unpruned
branches), so ``render_text`` labels it ``(mirror)`` rather than printing
a bare number that would read as as-of-now (see ``count_branches``'s own
docstring for the measured gap).

THE PUSH-GATE CACHE, AND WHY ITS WRITER IS UNWIRED (investigated, not
assumed): the pre-push battery is three hooks in ``.pre-commit-config.yaml``
(``thomas-merge-readiness`` -> ``scripts/forge/gates/merge_readiness.py``,
``thomas-publish-preflight`` -> ``scripts/forge/publish/preflight.py``,
``thomas-dead-ref-gate`` -> ``scripts/forge/gates/dead_ref_gate.py``), every
one of them re-exec'd through ``scripts/_gate_python.py``. Checked against
``agent_safety.toml`` before writing a line of this module: ``.pre-commit-
config.yaml`` is a top-level ``protected_files`` entry, and all three gate
scripts plus ``scripts/_gate_python.py`` itself are individually listed under
``[protected].enforcement_scripts`` (integrity-checked by
``enforcement_integrity.py`` so an agent cannot silently neuter them). Every
candidate write-in point for "drop a result file when the battery runs" is
therefore pinned, and the plan's own fallback for exactly this case applies:
ship the reader (this module, wired into every session start) and the writer
function (``write_push_gate_cache``, below) without wiring the hook call,
and document the one-line wiring as tap material rather than touch a pinned
file without explicit approval. The one line a human (or an approved tap
commit) adds to make the cache real is, inside ``merge_readiness.run()``
after ``ok, results = evaluate_merge_readiness()``:

    from scripts.crew.brief.trunk_health import write_push_gate_cache
    write_push_gate_cache(
        ROOT, ok=ok, blocked_gates=[r["name"] for r in results if not r["ok"]]
    )

Until that line lands, every session reads an absent cache and reports
``push-gate unchecked (never)`` -- an honest "nobody has told me" rather than
a fabricated "ok".

CACHE LOCATION IS DELIBERATELY UNPINNED AND UNTRACKED: ``runtime/`` is
``.gitignore``d wholesale (see the repo's own ``.gitignore``,
"# Runtime state (memory index, logs, secrets, etc)") and carries no entry
in ``agent_safety.toml``'s ``[protected]`` tables or
``enforcement_manifest.json`` -- the same directory ``_detect_orphaned_dirty_
state`` already writes to. ``runtime/push_gate_cache.json`` follows that
precedent: a last-write-wins telemetry drop, not an audit trail, so it is
overwritten in place (temp file + ``os.replace``, atomic on the same volume
including Windows -- this repo's established atomic-write idiom, see
``scripts/forge/accepted_risks.py``) rather than appended like the graveyard
or accepted-risks registries, which need a durable history this does not.

STALENESS: a cached result older than ``STALE_AFTER_SECONDS`` (24h -- this
repo's commit cadence is measured in hours, not days; a day-old "the battery
passed" is no longer trustworthy evidence about code that has since changed)
is reported the same as no cache at all: ``unchecked (Nd)``, never a fake
``ok``. A cache that cannot be parsed (missing file, corrupt JSON, wrong
shape, unparseable timestamp) degrades to the same ``unchecked`` state with
a distinguishing reason -- ``read_push_gate_cache`` never raises.

CLI: ``python scripts/crew/brief/trunk_health.py [--repo-root PATH] [--json]``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = _REPO_ROOT

TRUNK_BRANCH = "dev"
TRUNK_REMOTE = "dev-origin"
CACHE_RELATIVE = Path("runtime") / "push_gate_cache.json"
STALE_AFTER_SECONDS = 24.0 * 3600.0
# A cache timestamp this far ahead of "now" is not benign clock skew (that's
# well under an hour on any real machine) -- it's corruption or an
# adversarial value, and treating it as fresh would let a bogus "ok" outlive
# the staleness window indefinitely (adversarial review, phase 2 Task 1 fix
# round 1, M1: repro was `write_push_gate_cache(..., now=now+365d)` reading
# `push-gate ok` forever, since `max(0.0, ...)` clamped the negative age to
# zero and staleness could never trigger until real time caught up to it).
FUTURE_TOLERANCE_SECONDS = 3600.0

# Every exception a git subprocess call or a cache read could plausibly
# raise, gathered in one tuple so every degrade-instead-of-raise catch here
# handles the same failure modes the same way (mirrors incident_surfacing.py's
# ``_PER_FILE_EXCEPTIONS`` convention).
_SAFE_EXCEPTIONS = (
    OSError,
    UnicodeDecodeError,
    ValueError,
    TypeError,
    AttributeError,
    RuntimeError,
    subprocess.SubprocessError,
)


def _run_git(args: list[str], repo_root: Path, *, timeout: float = 5.0) -> tuple[bool, str, str]:
    """Run one git plumbing command against ``repo_root``. Never raises --
    a missing git binary, a timeout, or any OS-level failure degrades to
    ``(False, "", "<reason>")`` exactly like a nonzero git exit code does,
    so every caller has one failure shape to handle.

    TIMEOUT BOUND (adversarial review, phase 2 Task 1 fix round 1, M2):
    ``subprocess.run(..., timeout=...)`` kills the child on expiry, but on
    Windows a killed git that itself spawned a pipe-holding remote helper
    (e.g. ``git-remote-http`` during ``ls-remote``/``fetch``) can block the
    post-kill ``communicate()`` on that orphaned grandchild well past the
    nominal timeout -- measured at ~21s on a 3s timeout. This module never
    calls a command that spawns a remote helper (only local plumbing:
    ``rev-parse``, ``rev-list``, ``for-each-ref``, ``stash list``), so that
    overshoot is not reachable through any call this file makes -- recorded
    here so a future addition doesn't assume a hard ceiling if it adds one
    that does (``fetch``, ``ls-remote``, ``push``, ``clone``)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode == 0, proc.stdout, proc.stderr
    except _SAFE_EXCEPTIONS as exc:  # pragma: no cover - defensive
        return False, "", str(exc)


def count_unpushed(
    repo_root: Path,
    *,
    trunk_branch: str = TRUNK_BRANCH,
    trunk_remote: str = TRUNK_REMOTE,
) -> dict[str, Any]:
    """``rev-list --count <remote>/<branch>..<branch>`` -- how many commits on
    the local trunk the remote-tracking ref has never seen. The remote-
    tracking ref's existence is checked FIRST (``rev-parse --verify --quiet``)
    so a missing ref (fresh clone, fixture repo, remote renamed) degrades to
    ``{"ok": False, "reason": ...}`` -- unknown, not a fabricated zero. A
    real, honest zero (ref exists, nothing unpushed) is ``{"ok": True,
    "count": 0}``, a different, equally legitimate outcome."""
    ref_ok, _out, _err = _run_git(
        ["rev-parse", "--verify", "--quiet", f"refs/remotes/{trunk_remote}/{trunk_branch}"], repo_root
    )
    if not ref_ok:
        return {
            "ok": False,
            "count": 0,
            "reason": f"no remote-tracking ref {trunk_remote}/{trunk_branch}",
        }

    ok, out, err = _run_git(["rev-list", "--count", f"{trunk_remote}/{trunk_branch}..{trunk_branch}"], repo_root)
    if not ok:
        return {"ok": False, "count": 0, "reason": (err.strip() or "rev-list failed")[:200]}
    text = out.strip()
    if not text.isdigit():
        return {"ok": False, "count": 0, "reason": f"unexpected rev-list output: {text!r}"[:200]}
    return {"ok": True, "count": int(text), "reason": ""}


def count_branches(repo_root: Path, *, trunk_remote: str = TRUNK_REMOTE) -> dict[str, Any]:
    """Local branch count is always a live ``for-each-ref refs/heads`` read
    (a repo with zero heads is a legitimate, honest zero). The remote count
    is only reported when ``trunk_remote`` is actually configured -- checked
    via ``git remote`` first -- so an absent/renamed remote degrades to
    ``remote_ok: False`` with a reason instead of silently reporting 0
    remote branches (which would read as "trunk is clean" when the truth is
    "nobody knows"). ``<remote>/HEAD`` (the remote's symbolic default-branch
    pointer, not a real branch) is excluded from the remote count.

    THE NUMBER IS A MIRROR, NOT A LIVE READ (adversarial review, phase 2
    Task 1 fix round 1, I1): ``refs/remotes/<trunk_remote>`` is whatever the
    last ``fetch``/``push`` last wrote to disk -- it does NOT shrink when a
    branch is deleted on the remote until something prunes it, so this count
    can run persistently HIGHER than ``git ls-remote --heads`` (measured:
    157 on-disk vs. 151 live on the day this was found). That staleness is
    the intended tradeoff (session start must never touch the network, and
    a test enforces no ``fetch`` call happens here) -- but the number must
    say so. ``render_text`` labels this clause ``(mirror)`` for exactly that
    reason; do not silently drop that suffix if this function's return shape
    changes."""
    local_ok, out_local, _err_local = _run_git(["for-each-ref", "--format=%(refname)", "refs/heads"], repo_root)
    local = len([line for line in out_local.splitlines() if line.strip()]) if local_ok else 0

    cfg_ok, out_cfg, _err_cfg = _run_git(["remote"], repo_root)
    configured_remotes = {line.strip() for line in out_cfg.splitlines() if line.strip()} if cfg_ok else set()
    if trunk_remote not in configured_remotes:
        return {
            "local": local,
            "local_ok": local_ok,
            "remote": None,
            "remote_ok": False,
            "remote_reason": f"no such remote {trunk_remote!r}",
        }

    remote_ok, out_remote, err_remote = _run_git(
        ["for-each-ref", "--format=%(refname)", f"refs/remotes/{trunk_remote}"], repo_root
    )
    if not remote_ok:
        return {
            "local": local,
            "local_ok": local_ok,
            "remote": None,
            "remote_ok": False,
            "remote_reason": (err_remote.strip() or "for-each-ref failed")[:200],
        }
    remote = len([line for line in out_remote.splitlines() if line.strip() and not line.strip().endswith("/HEAD")])
    return {"local": local, "local_ok": local_ok, "remote": remote, "remote_ok": True, "remote_reason": ""}


def count_stashes(repo_root: Path) -> dict[str, Any]:
    """``git stash list`` -- an empty result is a legitimate, honest zero,
    not a failure. Only a genuine git failure (not a repo, corrupted refs)
    degrades this to ``ok: False``."""
    ok, out, err = _run_git(["stash", "list", "--format=%H"], repo_root)
    if not ok:
        return {"ok": False, "count": 0, "reason": (err.strip() or "stash list failed")[:200]}
    count = len([line for line in out.splitlines() if line.strip()])
    return {"ok": True, "count": count, "reason": ""}


def read_push_gate_cache(
    repo_root: Path,
    *,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The cached last-battery-result, normalized to one of three states --
    ``"ok"``, ``"blocked"``, or ``"unchecked"`` -- never a fourth. Absent,
    corrupt, wrong-shaped, too old, or dated implausibly in the future
    (beyond ``FUTURE_TOLERANCE_SECONDS`` -- see that constant's own comment
    for the M1 finding this closes) are all folded into ``"unchecked"``
    (a distinguishing ``reason``/``age_days`` is still carried so
    ``render_text`` can print WHY), because every one of those is the same
    fact from the reader's perspective: nothing trustworthy is known right
    now. Never raises."""
    now = now or datetime.now(timezone.utc)
    cache_path = Path(repo_root) / CACHE_RELATIVE
    if not cache_path.exists():
        return {
            "state": "unchecked",
            "blocked_gates": [],
            "age_days": None,
            "reason": "no cache file (battery has not recorded a result yet)",
        }

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("cache file is not a JSON object")
        ts_raw = str(data.get("ts") or "")
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ok = bool(data.get("ok"))
        blocked_gates = [str(gate) for gate in (data.get("blocked_gates") or []) if str(gate).strip()]
    except _SAFE_EXCEPTIONS as exc:
        return {
            "state": "unchecked",
            "blocked_gates": [],
            "age_days": None,
            "reason": f"cache unreadable: {exc}"[:200],
        }

    if ts > now + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        # A timestamp more than an hour ahead of "now" is not clock skew --
        # see FUTURE_TOLERANCE_SECONDS' own comment. Folded into the same
        # "cache unreadable" bucket as corrupt JSON (not a fourth state, not
        # "stale" -- staleness measures a real past run being too old, this
        # is a value that cannot be a real past run at all).
        return {
            "state": "unchecked",
            "blocked_gates": [],
            "age_days": None,
            "reason": "cache unreadable: timestamp is in the future",
        }

    age_seconds = max(0.0, (now - ts).total_seconds())
    age_days = int(age_seconds // 86400)
    if age_seconds > stale_after_seconds:
        return {
            "state": "unchecked",
            "blocked_gates": [],
            "age_days": age_days,
            "reason": f"stale (last battery run {age_days}d ago)",
        }
    if ok:
        return {"state": "ok", "blocked_gates": [], "age_days": age_days, "reason": ""}
    return {"state": "blocked", "blocked_gates": blocked_gates, "age_days": age_days, "reason": ""}


def write_push_gate_cache(
    repo_root: Path,
    *,
    ok: bool,
    blocked_gates: list[str] | None = None,
    battery: str = "pre-push",
    now: datetime | None = None,
) -> bool:
    """Record one battery result. TAP MATERIAL, not yet called by any hook
    (see the module docstring's "the push-gate cache, and why its writer is
    unwired") -- every current call site is a test or a future one-line
    addition inside ``merge_readiness.run()``. Atomic write (temp file in the
    same directory + ``os.replace``) so a reader never observes a half-
    written file; never raises -- a write failure (read-only filesystem, disk
    full) returns ``False`` rather than breaking whatever called it, since
    this must be safe to call from inside a pre-push hook that has real work
    to finish regardless of whether the cache write lands."""
    now = now or datetime.now(timezone.utc)
    cache_path = Path(repo_root) / CACHE_RELATIVE
    payload = {
        "ts": now.isoformat(),
        "ok": bool(ok),
        "blocked_gates": [str(gate) for gate in (blocked_gates or [])],
        "battery": str(battery),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(cache_path.name + f".tmp{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
        return True
    except OSError:  # pragma: no cover - defensive
        return False


def summarize(
    repo_root: Path,
    *,
    trunk_branch: str = TRUNK_BRANCH,
    trunk_remote: str = TRUNK_REMOTE,
) -> dict[str, Any]:
    """The session-start-safe summary: every sub-read already degrades
    honestly instead of raising, but this outer call is still wrapped (the
    same last-resort-backstop shape as ``incident_surfacing.summarize``) so a
    failure this module's author did not anticipate still cannot break
    session start."""
    try:
        return {
            "ok": True,
            "unpushed": count_unpushed(repo_root, trunk_branch=trunk_branch, trunk_remote=trunk_remote),
            "branches": count_branches(repo_root, trunk_remote=trunk_remote),
            "stashes": count_stashes(repo_root),
            "push_gate": read_push_gate_cache(repo_root),
        }
    except _SAFE_EXCEPTIONS as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": str(exc)}


def render_text(summary: dict[str, Any]) -> str:
    """The one TRUNK line: ``TRUNK: <N> unpushed | branches
    <local>/<remote>(mirror) | stashes <N> | push-gate <ok|blocked:
    gate1,gate2|unchecked (age)>``. Degrades to ``TRUNK: unavailable
    (<reason>)`` only when ``summarize()`` itself reported ``ok=False`` --
    every other degradation (unknown remote, absent/stale/corrupt cache) is
    rendered inline, clause by clause, never silently dropped and never a
    fabricated healthy value.

    ``(mirror)`` (adversarial review, phase 2 Task 1 fix round 1, I1): the
    remote count is the on-disk ``refs/remotes/<remote>`` mirror
    (``count_branches``'s own docstring explains why it is never a live
    ``ls-remote``), which can run persistently stale relative to the real
    remote. Printing a bare number here read as an as-of-now fact when it
    is really an as-of-last-fetch one -- the suffix is the one-word fix,
    present whenever a remote count is actually known (never appended to
    the ``unknown (<reason>)`` branch, which already names its own gap)."""
    if not summary.get("ok", False):
        reason = str(summary.get("error") or "unknown error")
        return f"TRUNK: unavailable ({reason})"

    unpushed = summary.get("unpushed") or {}
    branches = summary.get("branches") or {}
    stashes = summary.get("stashes") or {}
    push_gate = summary.get("push_gate") or {}

    if unpushed.get("ok"):
        clause_unpushed = f"{int(unpushed.get('count') or 0)} unpushed"
    else:
        clause_unpushed = f"unpushed unknown ({unpushed.get('reason') or 'unavailable'})"

    local = int(branches.get("local") or 0)
    if branches.get("remote_ok"):
        clause_branches = f"branches {local}/{int(branches.get('remote') or 0)}(mirror)"
    else:
        clause_branches = f"branches {local}/unknown ({branches.get('remote_reason') or 'unavailable'})"

    if stashes.get("ok"):
        clause_stashes = f"stashes {int(stashes.get('count') or 0)}"
    else:
        clause_stashes = f"stashes unknown ({stashes.get('reason') or 'unavailable'})"

    state = str(push_gate.get("state") or "unchecked")
    if state == "ok":
        gate_text = "ok"
    elif state == "blocked":
        gates = ",".join(push_gate.get("blocked_gates") or []) or "unnamed"
        gate_text = f"blocked: {gates}"
    else:
        age_days = push_gate.get("age_days")
        reason = str(push_gate.get("reason") or "")
        if age_days is not None:
            # A real past run, too old to trust (STALE_AFTER_SECONDS).
            gate_text = f"unchecked ({age_days}d)"
        elif reason.startswith("cache unreadable"):
            # M1: corrupt JSON, wrong shape, or a future-dated timestamp --
            # a cache that exists but cannot be trusted, distinct from one
            # that was simply never written (see read_push_gate_cache).
            gate_text = "unchecked (cache unreadable)"
        else:
            gate_text = "unchecked (never)"
    clause_gate = f"push-gate {gate_text}"

    return "TRUNK: " + " | ".join([clause_unpushed, clause_branches, clause_stashes, clause_gate])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root (default: inferred).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = summarize(Path(args.repo_root))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
