#!/usr/bin/env python3
"""Evidence library: done gets something to be checked against (phase 1.4, task 1).

Grammar
-------
Evidence is a one-line string ``kind:payload``:

- ``commit:<sha>``            -- payload is 7-40 hex characters.
- ``run:<run_id>:<from>-<to>``  -- payload is a run_store run_id plus an
  inclusive seq range.
- ``gate:<gate_name>:<exit_code>`` -- payload is a gate name plus its exit
  code.

``parse_evidence`` rejects anything else with a ``ValueError`` that names the
defect. ``verify_evidence`` checks a parsed ``Evidence`` and returns a
``Verdict`` whose ``status`` is one of ``"verified"``, ``"attested"``, or
``"failed"``.

BINDING SEMANTICS (fix round 1, post-review)
---------------------------------------------
The first version of this library treated "landed" as synonymous with
"proof": a commit's evidence verified as long as its sha was an ancestor of
``dev``, with no check that the commit had anything to do with the task
claiming it. An external reviewer proved this empirically: the repository's
very first commit -- unrelated to any task by construction, since it
predates every task -- verified as evidence for ANY ``task_id`` handed to
it, because ancestry says nothing about which task a commit belongs to or
when it landed relative to the claim. Landing on ``dev`` is necessary but
was silently treated as sufficient. It is not: verified must mean BOUND
AND LANDED, never landed alone.

``verify_evidence`` now takes two optional parameters, ``task_id`` and
``not_before``, that establish the binding:

- ``commit``: ``"verified"`` requires BOTH (1) the sha is an ancestor of
  ``dev`` (landed) AND (2) at least one binding holds: (a) ``task_id``
  appears as a whole token in the commit's message/trailers (``git log -1
  --format=%B <sha>``), or (b) ``not_before`` was given and the commit's
  committer timestamp is at or after it. Landed-but-unbound (no ``task_id``
  match and no ``not_before``, or ``not_before`` given but the commit
  predates it) returns ``"attested"`` with reason ``landed on dev but not
  bound to this task - treat as claim, not proof`` -- exactly the shape of
  the first-commit attack, now labeled instead of silently accepted. Not an
  ancestor at all stays ``"failed"`` regardless of binding, since it never
  landed.
- ``run``: same pattern. ``"verified"`` requires the existing landed
  criteria (exists, finalized ok, claimed seq range present in replay) AND a
  binding: (a) ``task_id`` as a whole token in the run's metadata (``task_id``
  -- a real column ``create_run`` persists when supplied, recon #7a -- or the
  free-text fallback fields ``session_id``/``profile``/``mode``), or (b)
  ``not_before`` at or before ``started_at``. ``start_chat_v2_run`` takes an
  optional ``task_id`` and stamps it through, but neither of its two real
  callers has one in scope today -- both pass ``None``, honest absence.
  ``db_path`` remains REQUIRED for this kind: ``verify_evidence`` never
  falls back to the live server database, since guessing wrong would let a
  run "verify" against data the caller never intended to check.
- ``gate``: unchanged, ALWAYS ``"attested"``, never ``"verified"``, and
  ``task_id``/``not_before`` are accepted but ignored for this kind: phase
  1.4 records gate evidence but does not independently re-run the gate to
  confirm it, so the verdict says so instead of pretending otherwise. A gate
  result is not "landed" in the git/run-store sense binding even applies to.

WHOLE-TOKEN MATCHING (fix round 2, post-review)
-------------------------------------------------
Fix round 1 bound ``task_id`` with a plain ``in`` substring check. A
re-reviewer demonstrated this was itself unsound: ``task_id`` is a naive
substring test, so a task named ``T-1`` binds through any commit whose
message merely mentions the unrelated task ``T-12`` (``"T-1"`` is literally
a substring of ``"T-12"``). This repo's real task-id naming makes the same
shape common and severe: ``THOMAS-GITHUB-ISSUE-122`` and
``THOMAS-GITHUB-ISSUES-116-117-121-122-...`` share long overlapping runs of
characters despite naming unrelated tasks.

``task_id`` now binds only when it appears as a whole token: bounded on
both sides by the string's start/end or by a character outside
``[A-Za-z0-9_-]``, via
``re.search(rf"(?<![A-Za-z0-9_-]){re.escape(task_id)}(?![A-Za-z0-9_-])",
text)``. The subtlety: ``-`` IS treated as an id character (not a
delimiter), because it is one in this repo's naming convention
(``THOMAS-GITHUB-ISSUE-122``). This is why a naive ``\b`` word-boundary
regex would NOT have been enough -- ``\b`` treats ``-`` as a boundary, which
would let a short numeric task_id like ``122`` falsely bind inside a
dash-joined list such as ``116-117-122-130`` (the character before that
``122`` is ``-``, which a ``\b`` pattern reads as a boundary; this custom
character class reads it as still-inside-an-id, so no match). See
``_task_id_bound_in_text`` for the implementation and
``test_task_id_bound_in_text_is_delimiter_aware`` in the test file for the
pinned cases (prefix collision, dash-joined numeric collision, exact match,
start/end-of-string match, punctuation-delimited match).

Storage decision
-----------------
Global Constraints for this plan require reading ``workboard_claims.py``'s
Active Task validator FIRST to decide where evidence lives: if unknown
fields on an Active Task line are tolerated, evidence rides the task line;
if they are rejected, evidence must live in the task's unpinned
``PROBLEM.md`` record instead.

``workboard_claims.py`` (pinned, read-only) parses every Active Task entry
through ``_parse_kv_fields``, which builds a dict of every ``key=value``
segment on the line and checks it against a required-fields allowlist only:

    fields: dict[str, str] = {}
    for part in _split_field_segments(token):
        if "=" not in part:
            return None, f"line {line_no}: invalid field format `{part}` (expected key=value)"
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = _parse_field_value(value)
        if not key or not value:
            return None, f"line {line_no}: invalid field `{part}` (expected non-empty key=value)"
        fields[key] = value

    missing = [name for name in required_fields if not fields.get(name)]
    if missing:
        return None, f"line {line_no}: missing required field(s): {', '.join(missing)}"
    return fields, None

There is no companion check that rejects a key outside
``REQUIRED_ACTIVE_TASK_FIELDS`` -- ``_parse_active_task_entry`` (also in
that file) reads only the five known keys (``task_id``, ``agent``,
``scope``, ``summary``, ``status``) back out of that dict and silently
drops the rest when it builds the ``ActiveTask`` dataclass. An
``evidence=commit:abc1234`` field on an Active Task line parses cleanly and
raises zero violations.

DECISION: unknown fields are tolerated, so evidence rides the task line.
``record_evidence``/``read_evidence`` below write and read an
``evidence=`` (and ``evidence_recorded_at=``) field directly on the task's
``## Active Tasks`` line in the given workboard file. No pinned file is
touched to make this true; the tolerance already existed.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard import claim_evidence_storage
except ImportError:  # pragma: no cover
    from crew.workboard import claim_evidence_storage  # type: ignore

from thomas.marketplace.observability import run_store  # noqa: E402

# Split out (claim_evidence_storage.py; phase-2 batch-2 task 1) past the monolith
# guard's unbaselined 800-line soft limit -- see its docstring. Re-exported
# under original names; no caller changed. Precedent: worker.py/worker_pipeline.py.
DEFAULT_WORKBOARD = claim_evidence_storage.DEFAULT_WORKBOARD
_VALID_KINDS = claim_evidence_storage._VALID_KINDS
_COMMIT_SHA_RE = claim_evidence_storage._COMMIT_SHA_RE
_ACTIVE_TASKS_HEADING = claim_evidence_storage._ACTIVE_TASKS_HEADING
Evidence = claim_evidence_storage.Evidence
parse_evidence = claim_evidence_storage.parse_evidence
format_evidence_field = claim_evidence_storage.format_evidence_field
_validate_commit_payload = claim_evidence_storage._validate_commit_payload
_validate_run_payload = claim_evidence_storage._validate_run_payload
_validate_gate_payload = claim_evidence_storage._validate_gate_payload
_is_int = claim_evidence_storage._is_int
EvidenceRecord = claim_evidence_storage.EvidenceRecord
record_evidence = claim_evidence_storage.record_evidence
read_evidence = claim_evidence_storage.read_evidence
strip_evidence = claim_evidence_storage.strip_evidence
_utcnow_iso = claim_evidence_storage._utcnow_iso
_active_tasks_bounds = claim_evidence_storage._active_tasks_bounds
_find_task_line = claim_evidence_storage._find_task_line
_split_field_segments = claim_evidence_storage._split_field_segments
_parse_field_value = claim_evidence_storage._parse_field_value
_parse_task_line_fields = claim_evidence_storage._parse_task_line_fields
_format_task_line_fields = claim_evidence_storage._format_task_line_fields

# Ordered fallback (fix round 4, recon #6): a bare "dev" only resolves with a
# local `dev` branch, never true on a PR-CI checkout -- SHAPE mirrors
# release_update_gate.py:196, but NOT its trailing `origin/main`/`main`
# (different, unrelated branch -- would let a `main`-only checkout falsely
# stand in for `dev`; regression: test_an_unresolvable_target_ref_...py).
# FULLY QUALIFIED (fix round 5, review I-1): a bare name is DWIM-resolved,
# and a LOCAL branch can be created with any of these exact names (`git
# branch dev-origin/dev` is legal) -- refs/heads wins git's disambiguation
# over a same-named remote-tracking ref, so an accidental/adversarial local
# branch could silently become the target. Qualified paths resolve ONLY the
# named ref, no DWIM, no shadowing (`dev-origin` is this repo's real remote).
VERIFY_TARGET_BRANCH_FALLBACKS: tuple[str, ...] = (
    "refs/heads/dev",
    "refs/remotes/origin/dev",
    "refs/remotes/dev-origin/dev",
)

_VERDICT_STATUSES: tuple[str, ...] = ("verified", "attested", "failed")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The result of `verify_evidence`: status in {verified, attested, failed} + reason.

    `reason_code` (fix round, post-review) is an OPTIONAL machine-readable
    tag, default "", for callers that need to distinguish *why* a `"failed"`
    happened without parsing `reason` prose. It does not change `status`'s
    meaning or `verify_evidence`'s refuse/proceed contract at the done
    transition (`set_task_status` still refuses on `status == "failed"`
    regardless of `reason_code`) -- it exists so a caller like a periodic
    re-verification sweep can tell "the check apparatus itself was
    unavailable" (`REASON_CODE_DB_PATH_REQUIRED`) apart from "the check ran
    and the evidence is genuinely bad", since only the latter is a positive
    failure that should ever cause something to expire.
    """

    status: str
    reason: str
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VERDICT_STATUSES:
            raise ValueError(f"verdict status `{self.status}` is not one of {_VERDICT_STATUSES}")


UNBOUND_COMMIT_REASON = "landed on dev but not bound to this task - treat as claim, not proof"
UNBOUND_RUN_REASON = "run landed and finalized ok but not bound to this task - treat as claim, not proof"

# See Verdict.reason_code above: db-absence is infrastructure absence, not a
# positive finding that the evidence is bad -- a caller like the evidence
# sweep must be able to tell this apart from a real "run not found"/"not
# finalized"/"missing seq range" failure.
REASON_CODE_DB_PATH_REQUIRED = "db_path_required"

# Same category, the commit-kind counterpart (fix round 2, post-re-review):
# `git` itself failing to run (missing binary, permissions, etc.) is exactly
# as much "the check never ran" as a missing db_path -- not a finding that
# the commit sha is bad. Kept as its own distinct code rather than folded
# into REASON_CODE_DB_PATH_REQUIRED (that name is already specific and
# already load-bearing in tests/CHANGELOG from the prior fix round); callers
# that only care about the CATEGORY -- "was any real check even attempted"
# -- should test membership in UNAVAILABLE_REASON_CODES below instead of
# comparing to either constant individually, so a future third code (e.g. a
# run-store that exists but can't be opened) is one line to add here, not a
# new branch at every call site.
#
# WIDENED (fix round 3, reproduced in nodev.py): also covers `git` LAUNCHING
# fine but `merge-base --is-ancestor` exiting nonzero because NONE of
# VERIFY_TARGET_BRANCH_FALLBACKS resolve -- still "the check never ran".
# Fix round 4 (recon #6): resolution now happens BEFORE merge-base via
# `_resolve_verify_target_branch`, so a PR-CI checkout with only
# `origin/dev` now VERIFIES instead of skipping. An unresolvable/unknown SHA
# against a resolved target is UNCHANGED: real "failed", empty reason_code
# (T1 contract 2, pinned).
REASON_CODE_GIT_UNAVAILABLE = "git_unavailable"
UNAVAILABLE_REASON_CODES: tuple[str, ...] = (REASON_CODE_DB_PATH_REQUIRED, REASON_CODE_GIT_UNAVAILABLE)

# Fields a run-kind binding searches for `task_id` (BINDING SEMANTICS
# above): `task_id` is a real column (fix round 2, recon #7a); the rest are
# the free-text fallback fields `create_run` stored before that column existed.
_RUN_BINDING_TEXT_FIELDS: tuple[str, ...] = ("task_id", "session_id", "profile", "mode")


def verify_evidence(
    ev: Evidence,
    repo_root: Path,
    db_path: Path | None = None,
    *,
    task_id: str | None = None,
    not_before: _dt.datetime | None = None,
) -> Verdict:
    """Check `ev` against reality. Never raises for well-formed evidence -- returns a Verdict.

    `task_id`/`not_before` establish binding (see module docstring's BINDING
    SEMANTICS section): landing on dev / in the run store is necessary but
    not sufficient for "verified" -- the evidence must also be tied to
    *this* task, either by name (`task_id` found in the commit message or
    run metadata) or by time (`not_before`, e.g. the task's claim time).
    Landed-but-unbound evidence is "attested", not "verified" -- it is a
    real, checkable claim, just not proof this task is the one that made it.
    """
    if ev.kind == "commit":
        return _verify_commit(ev, repo_root, task_id=task_id, not_before=not_before)
    if ev.kind == "run":
        return _verify_run(ev, db_path, task_id=task_id, not_before=not_before)
    if ev.kind == "gate":
        return Verdict(
            status="attested",
            reason=(
                f"gate evidence `{ev.gate_name}:{ev.exit_code}` is recorded but not independently verified in phase 1.4"
            ),
        )
    raise ValueError(f"evidence kind `{ev.kind}` has no verifier")  # unreachable via parse_evidence


def _ensure_aware(value: _dt.datetime) -> _dt.datetime:
    """Treat a naive datetime as UTC rather than raising on comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value


def _parse_iso(text: str | None) -> _dt.datetime | None:
    if not text:
        return None
    token = str(text).strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    try:
        return _ensure_aware(_dt.datetime.fromisoformat(token))
    except ValueError:
        return None


def _commit_message(sha: str, repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return str(proc.stdout or "")


def _commit_committer_time(sha: str, repo_root: Path) -> _dt.datetime | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI", sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return _parse_iso(str(proc.stdout or "").strip())


# '-' is an id character in this repo's task-id naming (THOMAS-GITHUB-ISSUE-122),
# so it must NOT count as a token boundary the way \b would. See the
# WHOLE-TOKEN MATCHING section of the module docstring.
_ID_BOUNDARY_CHARS = "A-Za-z0-9_-"


def _task_id_bound_in_text(task_id: str, text: str) -> bool:
    """Whole-token match: `task_id` binds only when bounded by string
    start/end or a non-id character on both sides. A plain substring check
    (fix round 1) let a short task_id bind through any longer id that
    happens to contain it -- e.g. `T-1` inside `T-12`, or a numeric id like
    `122` inside a dash-joined list like `116-117-122-130`. Because `-` is
    itself part of this repo's id grammar, it is deliberately included in
    the "still an id character" class, not treated as a delimiter.
    """
    pattern = re.compile(rf"(?<![{_ID_BOUNDARY_CHARS}]){re.escape(task_id)}(?![{_ID_BOUNDARY_CHARS}])")
    return pattern.search(text) is not None


def _commit_binding(
    sha: str, repo_root: Path, task_id: str | None, not_before: _dt.datetime | None
) -> tuple[bool, str]:
    task_id = str(task_id or "").strip()
    if task_id:
        message = _commit_message(sha, repo_root)
        if message is not None and _task_id_bound_in_text(task_id, message):
            return True, f"task_id `{task_id}` found in commit message/trailers"
    if not_before is not None:
        committed_at = _commit_committer_time(sha, repo_root)
        if committed_at is not None and committed_at >= _ensure_aware(not_before):
            return True, f"committed at {committed_at.isoformat()} is at or after not_before {not_before.isoformat()}"
    return False, ""


def _run_binding(run: dict[str, object], task_id: str | None, not_before: _dt.datetime | None) -> tuple[bool, str]:
    task_id = str(task_id or "").strip()
    if task_id:
        haystack = " ".join(str(run.get(field) or "") for field in _RUN_BINDING_TEXT_FIELDS)
        if _task_id_bound_in_text(task_id, haystack):
            return True, f"task_id `{task_id}` found in run metadata ({', '.join(_RUN_BINDING_TEXT_FIELDS)})"
    if not_before is not None:
        started_at = _parse_iso(run.get("started_at") if isinstance(run.get("started_at"), str) else None)
        if started_at is not None and started_at >= _ensure_aware(not_before):
            return True, f"started at {started_at.isoformat()} is at or after not_before {not_before.isoformat()}"
    return False, ""


def _ref_resolves(ref: str, repo_root: Path) -> str | None:
    """Return the commit sha `ref` names in `repo_root` if it exists as an
    EXACT ref path, or `None` if it does not -- a fact about the CHECKOUT,
    not about any sha. Used by `_resolve_verify_target_branch` to pick a
    target before `_verify_commit` runs `merge-base`. Any OSError running
    the probe is treated as "does not resolve" -- if this process cannot
    even ask, it must not blame the sha.

    THE LAST REF TRICK (fix round 6, T3 review, "next touch" ruling): this
    used to run `git rev-parse --verify <ref>^{commit}`. `rev-parse`
    disambiguates a name that does not exist AS GIVEN by retrying it under
    `refs/`, `refs/tags/`, `refs/heads/`, and `refs/remotes/` in turn (see
    gitrevisions(7)'s search rules) -- so asking it to resolve the already
    fully-qualified `refs/heads/dev` when the REAL `dev` branch is ABSENT
    still finds a match if a branch literally named `refs/heads/dev`
    exists, because git happily stores one at `refs/heads/refs/heads/dev`
    (`git branch refs/heads/dev` is legal -- slashes are allowed in branch
    names, the exact same shape review I-1 already caught and fixed for
    `dev-origin/dev`, just one path segment further in). Qualifying the
    fallback names (fix round 5) was not enough on its own: `rev-parse`
    still DWIMs a qualified name that fails its own rule-1 exact lookup.
    `git show-ref --verify <ref>` performs NONE of that fallback
    disambiguation -- it is an exact match against the given path only, so
    a same-named nested branch can never stand in for the ref the
    qualified-path fix already intended to require. Returns the resolved
    sha straight from `show-ref`'s own `<sha> <ref>` output line rather
    than a bare bool, so `_verify_commit` can pass that sha on to
    `merge-base` directly instead of the ref name -- `merge-base` given a
    ref NAME would re-run the exact DWIM-capable resolution `show-ref` was
    just used to avoid, undoing the fix one call later.
    """
    try:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    line = str(proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
    if not line:
        return None
    sha = line.split(maxsplit=1)[0].strip()
    return sha or None


def _resolve_verify_target_branch(repo_root: Path) -> str | None:
    """First ref in VERIFY_TARGET_BRANCH_FALLBACKS that resolves in
    `repo_root`, or None if none do. Order is pinned: dev wins over
    origin/dev when both resolve.
    """
    for ref in VERIFY_TARGET_BRANCH_FALLBACKS:
        if _ref_resolves(ref, repo_root) is not None:
            return ref
    return None


def _verify_commit(
    ev: Evidence,
    repo_root: Path,
    *,
    task_id: str | None = None,
    not_before: _dt.datetime | None = None,
) -> Verdict:
    sha = ev.sha
    target = _resolve_verify_target_branch(repo_root)
    if target is None:
        return Verdict(
            status="failed",
            reason=(
                f"commit `{sha}` could not be checked: the `dev` ref does not resolve in this checkout, nor do "
                f"its fallbacks {VERIFY_TARGET_BRANCH_FALLBACKS} (shallow clone, worktree without the branch, "
                "or a PR-shaped checkout with only a remote-tracking ref) - not a finding about the commit"
            ),
            reason_code=REASON_CODE_GIT_UNAVAILABLE,
        )
    # Exact-path end to end (fix round 6): resolve `target`'s sha via the
    # same DWIM-free `show-ref` probe that picked it, and pass THAT sha to
    # `merge-base` -- never the ref name. `merge-base` given a ref name
    # would re-run git's ordinary DWIM-capable resolution, which could
    # still be fooled by a nested lookalike ref (see `_ref_resolves`'s
    # docstring) even though `target` itself was chosen safely.
    target_sha = _ref_resolves(target, repo_root)
    if target_sha is None:
        # Resolved a moment ago in `_resolve_verify_target_branch`, no
        # longer does now (a ref deleted/moved mid-check) -- same honest
        # skip as never resolving at all, not a finding about `sha`.
        return Verdict(
            status="failed",
            reason=(
                f"commit `{sha}` could not be checked: target ref `{target}` stopped resolving between "
                "selection and use - not a finding about the commit"
            ),
            reason_code=REASON_CODE_GIT_UNAVAILABLE,
        )
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, target_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return Verdict(
            status="failed",
            reason=f"commit `{sha}` could not be checked: git failed to run ({exc})",
            reason_code=REASON_CODE_GIT_UNAVAILABLE,
        )
    if proc.returncode != 0:
        # `target` already resolved above, so a nonzero exit is always a
        # real finding about `sha` -- no post-hoc `_ref_resolves` probe needed.
        detail = str(proc.stderr or "").strip()
        reason = f"commit `{sha}` is not an ancestor of {target}"
        if detail:
            reason += f": {detail}"
        return Verdict(status="failed", reason=reason)

    bound, bind_reason = _commit_binding(sha, repo_root, task_id, not_before)
    if bound:
        return Verdict(
            status="verified",
            reason=f"commit `{sha}` is an ancestor of {target} and bound to this task ({bind_reason})",
        )
    return Verdict(status="attested", reason=UNBOUND_COMMIT_REASON)


def _verify_run(
    ev: Evidence,
    db_path: Path | None,
    *,
    task_id: str | None = None,
    not_before: _dt.datetime | None = None,
) -> Verdict:
    if db_path is None:
        return Verdict(
            status="failed",
            reason="run evidence requires an explicit db_path; verify_evidence never falls back to the live run store",
            reason_code=REASON_CODE_DB_PATH_REQUIRED,
        )
    run_id = ev.run_id
    seq_from, seq_to = ev.seq_range
    run_store.init_db(db_path)
    try:
        record = run_store.get_run(run_id)
    except KeyError:
        return Verdict(status="failed", reason=f"run `{run_id}` was not found in the run store at {db_path}")
    run = record["run"]
    ok = run.get("ok")
    if not ok:
        return Verdict(status="failed", reason=f"run `{run_id}` is not finalized ok (ok={ok!r})")
    seqs = {int(event.get("seq")) for event in run_store.stream_replay(run_id)}
    missing = [s for s in range(seq_from, seq_to + 1) if s not in seqs]
    if missing:
        return Verdict(
            status="failed",
            reason=f"run `{run_id}` replay is missing seq {missing[0]} within claimed range {seq_from}-{seq_to}",
        )

    bound, bind_reason = _run_binding(run, task_id, not_before)
    if bound:
        return Verdict(
            status="verified",
            reason=(
                f"run `{run_id}` is finalized ok, seq range {seq_from}-{seq_to} is present in its replay, "
                f"and bound to this task ({bind_reason})"
            ),
        )
    return Verdict(status="attested", reason=UNBOUND_RUN_REASON)
