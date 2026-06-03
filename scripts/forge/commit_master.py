#!/usr/bin/env python3
"""Commit-master: the only identity allowed to commit/sign/push in the cage.

Praxis "cage" finale (plans/thomas/problems/praxis-unbypassable-2026-05-29).

Why this exists
---------------
The Red/Blue exercise proved every *locally* fixable gate bypass closed, but
left one irreducible residual: **a same-OS-user shell controls local
filesystem state**, so the worker agent could forge the success marker, delete
hooks, reset the audit log, or self-approve. No purely-local control closes
that while the worker IS the committer.

This module changes the *shape* of the problem instead of patching another
string. It splits the worker's two roles apart:

* The worker agent becomes a **proposer**. Its ONLY sanctioned write to the
  repo is to drop a *submission* (a patch + a small JSON manifest) into a
  one-way ``inbox`` directory. It cannot commit, push, sign, or talk to the
  gatekeeper.
* A separate identity runs this **commit-master**. It treats each submission
  as inert *data*: it rebuilds the change in a throwaway clean-room worktree
  from pristine ``HEAD``, runs the gates with the trusted gate scripts and a
  sanitized environment, ignores any self-asserted approval in the
  submission, and only then commits + signs + pushes with a key the worker
  cannot read. Verdicts go back via a one-way ``outbox``.

Under the OS-level cage (``scripts/cage/provision_cage.ps1``) the channel ACLs
make this a real privilege boundary. Before provisioning it still runs — as an
advisory single-user pipeline — and degrades exactly like the existing local
gates: useful, but not yet a wall. The provisioning step is what flips it from
advisory to enforced; this module is written to be correct under separation.

Security properties (each maps to a closed bypass class)
--------------------------------------------------------
* clean-room rebuild from pristine HEAD -> B1' (no marker to mint), B6 (no hook
  to delete; the master runs gates directly).
* sanitized env -> B4 (GITHUB_ACTIONS CI-spoof), B5 (AGENT_ID identity-spoof),
  R4 (THOMAS_*_DISABLE / THOMAS_SKIP_* envs).
* submissions handled as data, master re-stamps its own trailers -> B12/B19
  (self-asserted approval trailers / deletion records carry no authority).
* external integrity anchor: the master hashes the clean-room gate files
  against a trusted manifest the worker cannot write, BEFORE running any gate
  -> B3/B7 (a patch that neuters a gate is a hash mismatch and is rejected).
* gates run from INSIDE the clean room (they resolve their repo via __file__,
  not cwd), so they actually inspect the submitted change, not the main repo.

This file is intentionally self-contained and stdlib-only so the gatekeeper
identity needs nothing from the worker's environment to run it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Environment sanitization
# --------------------------------------------------------------------------- #
# Environment variables that a worker agent could set to weaken a gate. The
# master strips these before running ANY gate so a poisoned env cannot reach
# the gatekeeper's clean context. Exact names + prefix patterns from the
# Red/Blue findings (B4/B5/R4) plus the marker-key override (B1 env-override).
_ENV_DENY_EXACT = frozenset(
    {
        "GITHUB_ACTIONS",  # B4: local CI-spoof -> "ci-trusted" breakglass
        "CI",
        "AGENT_ID",  # B5: identity spoof resets breakglass quota
        "CODEX_AGENT_NAME",
        "THOMAS_AGENT",
        "THOMAS_AGENT_ID",
        "THOMAS_PRAXIS_MARKER_KEY_FILE",  # B1: point marker HMAC key at attacker file
        "THOMAS_LEAK_BLOCKLIST_FILE",  # redirect leak-guard blocklist to drop competitor rules
        "THOMAS_SKIP_BREAKGLASS",  # B4: self-authorize a SKIP
        "THOMAS_SKIP_TICKET",
        "THOMAS_SKIP_REASON",
        "THOMAS_RUNTIME_PROTECTION_DISABLED",
        "THOMAS_AGENT_ROLE",  # core_overhead_guard SKIPs on role=orchestrator (unsigned bare env)
        "THOMAS_CORE_OVERHEAD_UNLOCK",  # core_overhead_guard full unlock via bare env
    }
)
# Any env var matching one of these prefixes/suffixes is stripped too — covers
# the family of THOMAS_*_DISABLE flags and CODEX_* identity vars (R4/B5).
_ENV_DENY_PREFIX = ("THOMAS_SKIP_", "CODEX_")
_ENV_DENY_SUFFIX = ("_DISABLE", "_GUARD_DISABLE")


def sanitize_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of the environment with worker-controllable bypass vars removed.

    We copy-then-strip rather than allowlist-build because git + Python on
    Windows need a broad set of system vars (SYSTEMROOT, PATHEXT, APPDATA, ...).
    Stripping the known-dangerous keys is both safer for portability and
    sufficient: the gates only honor the specific vars listed above.
    """
    src = dict(os.environ if base is None else base)
    out: dict[str, str] = {}
    for key, value in src.items():
        upper = key.upper()
        if upper in _ENV_DENY_EXACT:
            continue
        if any(upper.startswith(p) for p in _ENV_DENY_PREFIX):
            continue
        if any(upper.endswith(s) for s in _ENV_DENY_SUFFIX):
            continue
        out[key] = value
    # Positively mark that gates are running under the master, not CI or a
    # worker shell. Gates can treat this as "no breakglass shortcuts".
    out["THOMAS_COMMIT_MASTER"] = "1"
    return out


# --------------------------------------------------------------------------- #
# Gate suite (the master's trusted rulebook)
# --------------------------------------------------------------------------- #
# Curated, trusted invocations run against the clean-room worktree. Order
# matters: enforcement_integrity runs FIRST as the anti-tamper anchor — if the
# submitted patch edited any gate script, the clean-room hash no longer matches
# the trusted manifest and the whole submission is rejected before any other
# gate (whose code we'd then be unable to trust) runs.
#
# Each entry is (name, [args after the gate's .py path]). The master prepends
# `python <gates_root>/<name>.py`. gates.yml remains the exhaustive server-side
# runner; this set is the local hard-stop + structural core.
@dataclass(frozen=True)
class GateSpec:
    name: str
    # Repo-RELATIVE path to the gate script (e.g. "scripts/forge/gates/x.py").
    # The master runs the clean room's OWN copy at this path — see the note on
    # the suite below for why that is both necessary and safe.
    script: str
    args: tuple[str, ...] = ()


# Why gates run from INSIDE the clean room, not from an external trusted dir:
# every gate hard-resolves its repo root via `Path(__file__).parents[3]` and
# runs git with `cwd=that_root` — it ignores the process cwd. So a gate invoked
# from an external copy would inspect the MAIN repo, not the clean room, and
# silently pass a change it never looked at. The gates must therefore execute
# from the clean room. To stop a submitted patch from neutering those clean-room
# copies, the master runs its OWN external integrity anchor first
# (_verify_cleanroom_integrity): it hashes the clean-room gate files against a
# trusted manifest the worker cannot write. Tamper a gate -> hash mismatch ->
# reject, before any gate runs.
#
# IMPORTANT: only DIFF-SCOPED gates belong in the suite. A whole-tree scanner
# (monolith_filename_guard, duplicate_filename, circular_imports, ...) fails on
# PRE-EXISTING violations in the clean room and would falsely reject an innocent
# change. Those exhaustive quality scans are CI's job
# (.github/workflows/gates.yml) and the local pre-commit hook's. The default
# suite is the security HARD-STOP that reads the staged diff and is correct in a
# clean room:
#   * protected_files - blocks edits to protected paths in the staged diff.
# The anti-tamper anchor is the master's integrity check, not a suite entry.
DEFAULT_GATE_SUITE: tuple[GateSpec, ...] = (
    GateSpec("protected_files", "scripts/forge/gates/protected_files_gate.py", ("--json",)),
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class CageLayout:
    """Resolved locations of the one-way channels and the master's state.

    Defaults sit under ``runtime/cage`` so they are git-ignored. In the
    provisioned cage these are repointed (env / args) to a location outside the
    worktree, with cross-user ACLs applied by provision_cage.ps1.
    """

    root: Path
    inbox: Path = field(init=False)
    outbox: Path = field(init=False)
    audit: Path = field(init=False)
    work: Path = field(init=False)

    def __post_init__(self) -> None:
        self.inbox = self.root / "inbox"
        self.outbox = self.root / "outbox"
        self.audit = self.root / "audit"
        self.work = self.root / "work"

    def ensure(self) -> None:
        for d in (self.inbox, self.outbox, self.audit, self.work):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def audit_log(self) -> Path:
        return self.audit / "commit_master_audit.jsonl"


def _now() -> float:
    return time.time()


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------------------- #
# Audit (append-only)
# --------------------------------------------------------------------------- #
def append_audit(layout: CageLayout, record: dict[str, Any]) -> None:
    layout.audit.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    # Open in append mode only; the master never rewrites history. Under the
    # cage ACLs this file is master-write / agent-none, so the worker cannot
    # truncate it to reset quotas (closes B17 once provisioned).
    with layout.audit_log.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# Coordination delivery enforcement (cage PROBLEM 2)
# --------------------------------------------------------------------------- #
# The worker's ONLY sanctioned repo action is `submit`. That makes it the exact
# choke point at which to enforce "you cannot act past an unread directive":
# before a submission is accepted we check whether the submitting agent has any
# unread coordination messages and refuse if so. This is what turns the
# pull-only message lane into guaranteed delivery for caged agents. Import is
# LAZY + guarded so the gatekeeper's clean-room path stays stdlib-only and a
# missing surfacing module never bricks a submission.
class InboxBlockedError(RuntimeError):
    """Raised when a worker tries to submit with unread messages."""

    def __init__(self, agent: str, blocking: list[dict[str, Any]]) -> None:
        self.agent = str(agent or "")
        self.blocking = list(blocking or [])
        super().__init__(f"{len(self.blocking)} unread coordination message(s) must be acked before submitting")


def _paths_from_patch(patch_text: str) -> list[str]:
    """Extract changed repo paths from a unified diff's ``+++ b/<path>`` lines."""
    out: list[str] = []
    for line in str(patch_text or "").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null" and path not in out:
                out.append(path)
    return out


def _submission_changed_files(repo: Path, patch_file: str | None) -> list[str]:
    """Repo-relative paths in this submission: the patch file, else the staged diff."""
    if patch_file:
        try:
            return _paths_from_patch(Path(patch_file).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return []
    proc = _git(repo, "diff", "--cached", "--name-only")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


# Scope-aware relevance is Calvin's chosen policy (2026-06-02) and exact wording:
# "block commits to claimed paths until RELEVANT messages are acked". A focused
# worker must not be wedged by an unrelated FYI, so the cage blocks only when a
# message is a must-read kind OR concerns the files in THIS submission. Kept
# INLINE (not a separate importable module) so the cage's choke point is
# self-contained and cannot be silently disabled by deleting a helper. It reuses
# message.unread_messages -- the shared "what is unread for me" primitive -- so
# it composes with, rather than duplicates, the repo-wide block-on-any
# pre-commit gate (scripts/forge/gates/workboard_inbox.py).
_ALWAYS_BLOCK_KINDS = frozenset({"blocker", "scope_change"})
_PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]+")


def _co_norm_path(value: str) -> str:
    # Strip a leading "./" and surrounding slashes WITHOUT eating a leading dot
    # (str.lstrip("./") would turn ".github/x" into "github/x").
    raw = str(value or "").strip().replace("\\", "/").strip("`'\" ")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.strip("/")


def _co_paths_overlap(a: str, b: str) -> bool:
    a = _co_norm_path(a)
    b = _co_norm_path(b)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _co_path_tokens(text: str) -> list[str]:
    text = str(text or "")
    out: list[str] = []
    for match in _PATH_TOKEN_RE.finditer(text):
        # Skip URL bodies: the regex captures the host/path AFTER "scheme://",
        # so check the char run immediately preceding the match for a slash.
        if text[: match.start()].rstrip().endswith("/"):
            continue
        token = match.group(0).strip("`'\"()[] ").rstrip(".,;:")
        if "://" in token or "@" in token:
            continue
        token = _co_norm_path(token)
        if token and "/" in token and token not in out:
            out.append(token)
    return out


def _co_active_task_scopes(workboard_text: str) -> dict[str, list[str]]:
    """Map ``task_id`` -> scope paths from the ``## Active Tasks`` section."""
    scopes: dict[str, list[str]] = {}
    in_section = False
    for line in workboard_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped[3:].strip().lower().startswith("active tasks")
            continue
        if not in_section or not stripped.startswith("- "):
            continue
        fields: dict[str, str] = {}
        for part in [piece.strip() for piece in stripped[2:].split(";") if piece.strip()]:
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key.strip().lower()] = value.strip()
        task_id = str(fields.get("task_id", "")).strip().lower()
        if task_id and task_id not in {"none", "_none_"}:
            scopes[task_id] = [seg.strip() for seg in str(fields.get("scope", "")).split(",") if seg.strip()]
    return scopes


def _co_unread_messages(workboard: Path, agent: str) -> list[dict[str, Any]]:
    """Open messages addressed to ``agent`` via the shared message primitive."""
    try:
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.crew.workboard import message as message_mod
    except (ImportError, ModuleNotFoundError):
        return []
    fn = getattr(message_mod, "unread_messages", None)
    if fn is not None:
        ok, payload = fn(workboard, agent=agent)
    else:  # pragma: no cover - fallback if the helper is unavailable
        ok, payload = message_mod.list_messages(workboard, recipient=agent, state="open")
    return list(payload.get("messages") or []) if ok else []


def _inbox_blocking(workboard: Path, agent: str, repo: Path, patch_file: str | None) -> list[dict[str, Any]]:
    """Relevant unread messages that should block this submission ([] if none).

    Scope-aware: a message blocks only when it is a must-read kind
    (blocker/scope_change) OR its subject paths (its task scope, or repo paths
    named in its text) overlap the files in THIS submission. Fails OPEN (returns
    []) when the workboard, agent, or message module is unavailable, so a
    missing coordination surface never bricks a submission -- the cage's real
    security boundary is the clean-room gate + privilege separation, not this
    coordination-delivery check.
    """
    workboard = Path(workboard)
    if not workboard.exists() or not str(agent or "").strip():
        return []
    messages = _co_unread_messages(workboard, agent)
    if not messages:
        return []
    text = workboard.read_text(encoding="utf-8")
    task_scopes = _co_active_task_scopes(text)
    changed = [_co_norm_path(c) for c in _submission_changed_files(repo, patch_file) if _co_norm_path(c)]

    blocking: list[dict[str, Any]] = []
    for msg in messages:
        kind = str(msg.get("kind", "")).strip().lower()
        reasons: list[str] = []
        if kind in _ALWAYS_BLOCK_KINDS:
            reasons.append(f"{kind} addressed to you (must-read)")
        subject = list(task_scopes.get(str(msg.get("task_id", "")).strip().lower(), []))
        subject += _co_path_tokens(msg.get("summary", "")) + _co_path_tokens(msg.get("requested_action", ""))
        hits = sorted({c for c in changed for s in subject if _co_paths_overlap(c, s)})
        if hits:
            reasons.append("concerns paths you are committing: " + ", ".join(hits[:5]))
        if reasons:
            enriched = dict(msg)
            enriched["_reasons"] = reasons
            blocking.append(enriched)
    return blocking


def _default_workboard(repo: Path) -> Path:
    return repo / "plans" / "thomas" / "WORKBOARD.md"


# --------------------------------------------------------------------------- #
# Submission (the agent's only sanctioned action)
# --------------------------------------------------------------------------- #
def create_submission(
    *,
    layout: CageLayout,
    repo: Path,
    agent: str,
    message: str,
    base: str = "HEAD",
    patch_file: str | None = None,
    remote: str = "",
    branch: str = "",
    submission_id: str | None = None,
    workboard: Path | None = None,
    enforce_inbox: bool = True,
) -> Path:
    """Write a well-formed submission into the inbox and return its directory.

    If ``patch_file`` is None the patch is generated from the repo's currently
    staged changes (``git diff --cached``). This is deliberately the *only*
    repo-affecting helper exposed to the worker.

    Coordination enforcement: unless ``enforce_inbox`` is False, the submission
    is refused (``InboxBlockedError``) when the submitting ``agent`` has unread
    coordination messages, making the cage runtime guarantee delivery of
    "don't touch X" directives at the worker's only choke point.
    """
    layout.ensure()
    base_sha = _resolve_sha(repo, base)
    if not base_sha:
        raise ValueError(f"cannot resolve base ref: {base!r}")

    if enforce_inbox:
        blocking = _inbox_blocking(workboard or _default_workboard(repo), agent, repo, patch_file)
        if blocking:
            append_audit(
                layout,
                {
                    "event": "submit_blocked",
                    "agent": agent,
                    "blocking": [b.get("msg_id") for b in blocking],
                    "ts": _now(),
                },
            )
            raise InboxBlockedError(agent, blocking)

    sid = submission_id or f"sub-{int(_now() * 1000)}-{_slug(agent)}"
    sub_dir = layout.inbox / sid
    if sub_dir.exists():
        raise FileExistsError(f"submission already exists: {sub_dir}")
    sub_dir.mkdir(parents=True)

    patch_text: str
    if patch_file:
        patch_text = Path(patch_file).read_text(encoding="utf-8")
    else:
        proc = _git(repo, "diff", "--cached", "--binary")
        patch_text = proc.stdout
    if not patch_text.strip():
        shutil.rmtree(sub_dir, ignore_errors=True)
        raise ValueError("empty patch: nothing staged and no patch_file given")

    (sub_dir / "change.patch").write_text(patch_text, encoding="utf-8")
    manifest = {
        "id": sid,
        "agent": str(agent or "unknown"),
        "base": base_sha,
        "message": str(message or "").strip(),
        "patch": "change.patch",
        "remote": str(remote or ""),
        "branch": str(branch or ""),
        "submitted_at": _now(),
    }
    (sub_dir / "submission.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    append_audit(layout, {"event": "submitted", "id": sid, "agent": agent, "base": base_sha, "ts": _now()})
    return sub_dir


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in str(value or "").lower()).strip("-") or "agent"


def _resolve_sha(repo: Path, ref: str) -> str:
    proc = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 else ""


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    submission_id: str
    status: str  # committed | rejected | error
    detail: str = ""
    commit_sha: str = ""
    failures: list[dict[str, Any]] = field(default_factory=list)
    pushed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "status": self.status,
            "detail": self.detail,
            "commit_sha": self.commit_sha,
            "failures": self.failures,
            "pushed": self.pushed,
            "ts": _now(),
        }


def _write_verdict(layout: CageLayout, verdict: Verdict) -> Path:
    layout.outbox.mkdir(parents=True, exist_ok=True)
    out = layout.outbox / f"{verdict.submission_id}.verdict.json"
    out.write_text(json.dumps(verdict.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    append_audit(layout, {"event": "verdict", **verdict.to_dict()})
    return out


# --------------------------------------------------------------------------- #
# Core: process one submission
# --------------------------------------------------------------------------- #
class CommitMaster:
    def __init__(
        self,
        *,
        repo: Path,
        layout: CageLayout,
        gates_root: Path | None = None,
        gate_suite: tuple[GateSpec, ...] = DEFAULT_GATE_SUITE,
        manifest_path: Path | None = None,
        sign: bool = True,
        push: bool = True,
        python_exe: str | None = None,
    ) -> None:
        self.repo = repo
        self.layout = layout
        # Trusted root for the integrity manifest. In the cage this points at the
        # Calvin-owned, read-only-to-agent copy. Default to the repo's gate dir.
        self.gates_root = gates_root or (repo / "scripts" / "forge" / "gates")
        # The integrity anchor: a manifest of {repo-relative path -> sha256 of
        # CRLF-normalized content} that the worker cannot write. When present,
        # the clean-room gate files are verified against it before any gate runs.
        # When absent, the integrity check is a logged no-op (the clean-room
        # gates still run, and CI's enforcement_integrity remains the backstop).
        self.manifest_path = manifest_path or (self.gates_root / "enforcement_manifest.json")
        self.gate_suite = gate_suite
        self.sign = sign
        self.push = push
        self.python_exe = python_exe or sys.executable

    # -- submission discovery -------------------------------------------- #
    def pending(self) -> list[Path]:
        if not self.layout.inbox.exists():
            return []
        subs = [p for p in self.layout.inbox.iterdir() if p.is_dir() and (p / "submission.json").exists()]
        subs.sort(key=lambda p: (p / "submission.json").stat().st_mtime)
        return subs

    def run_once(self) -> Verdict | None:
        subs = self.pending()
        if not subs:
            return None
        return self.process(subs[0])

    # -- the heart -------------------------------------------------------- #
    def process(self, sub_dir: Path) -> Verdict:
        sid = sub_dir.name
        manifest = self._load_manifest(sub_dir)
        if manifest is None:
            verdict = Verdict(sid, "rejected", detail="malformed submission.json")
            self._finish(sub_dir, verdict)
            return verdict

        sid = str(manifest.get("id") or sid)
        base = str(manifest.get("base") or "")
        if not _resolve_sha(self.repo, base):
            verdict = Verdict(sid, "rejected", detail=f"base commit not found: {base!r}")
            self._finish(sub_dir, verdict)
            return verdict

        clean_room = self.layout.work / f"{sid}-{int(_now())}"
        try:
            verdict = self._process_in_clean_room(sid, manifest, base, sub_dir, clean_room)
        except Exception as exc:  # noqa: BLE001 — gatekeeper must never crash on bad input
            verdict = Verdict(sid, "error", detail=f"{type(exc).__name__}: {exc}")
        finally:
            self._teardown_clean_room(clean_room)
        self._finish(sub_dir, verdict)
        return verdict

    def _process_in_clean_room(
        self,
        sid: str,
        manifest: dict[str, Any],
        base: str,
        sub_dir: Path,
        clean_room: Path,
    ) -> Verdict:
        # 1. Build the pristine clean room at the submission's base. The worker
        #    never touched this tree; nothing it staged or tampered locally
        #    carries over.
        add = _git(self.repo, "worktree", "add", "--detach", str(clean_room), base)
        if add.returncode != 0:
            return Verdict(sid, "error", detail=f"worktree add failed: {add.stderr.strip()}")

        # 2. Apply the submitted patch as DATA. We never import/exec it.
        patch_path = sub_dir / str(manifest.get("patch") or "change.patch")
        if not patch_path.exists():
            return Verdict(sid, "rejected", detail="patch file missing from submission")
        applied, apply_err = self._apply_patch(clean_room, patch_path)
        if not applied:
            return Verdict(sid, "rejected", detail=f"patch does not apply cleanly: {apply_err[:500]}")

        # 3. ANTI-TAMPER ANCHOR (external): verify the clean-room gate scripts
        #    against the trusted manifest BEFORE trusting any of them. A patch
        #    that rewrote a gate to pass changes its hash -> mismatch -> reject.
        tampered = self._verify_cleanroom_integrity(clean_room)
        if tampered:
            return Verdict(
                sid,
                "rejected",
                detail=f"clean-room gate tampering detected: {', '.join(tampered[:8])}",
                failures=[{"name": "integrity", "returncode": 1, "stdout": "", "stderr": ", ".join(tampered)}],
            )

        # 4. Run the gate suite from the clean room (so each gate's __file__-based
        #    repo root resolves to the clean room and it inspects THIS change),
        #    with a sanitized environment that strips worker bypass vars.
        env = sanitize_env()
        env.setdefault("PYTHONPATH", str(clean_room))
        failures: list[dict[str, Any]] = []
        for spec in self.gate_suite:
            result = self._run_gate(spec, clean_room, env)
            if result["returncode"] != 0:
                failures.append(result)

        if failures:
            names = ", ".join(f["name"] for f in failures)
            return Verdict(sid, "rejected", detail=f"gate(s) failed: {names}", failures=failures)

        # 5. All gates green. Commit in the clean room with MASTER-stamped
        #    trailers. --no-verify is correct HERE and only here: the master has
        #    already run the trusted gates in this clean room, so the worktree's
        #    shared hooks must not re-fire (they reference the worker's paths and
        #    could be tampered). The master IS the verification. Any approval
        #    trailer the worker wrote in `message` is advisory text only.
        message = self._compose_message(manifest)
        # Disable ALL hooks for the master's commit. --no-verify alone is not
        # enough: it skips pre-commit/commit-msg but NOT prepare-commit-msg, and
        # the worktree shares the repo's hooks (incl. Thomas's python-based
        # prepare-commit-msg choke point), which can't resolve in the clean room.
        # core.hooksPath -> an empty dir turns every hook off; the master has
        # already run the trusted gates, so it IS the verification.
        nohooks = self.layout.root / "_nohooks"
        nohooks.mkdir(parents=True, exist_ok=True)
        commit_args = [
            "-c",
            f"commit.gpgsign={'true' if self.sign else 'false'}",
            "-c",
            f"core.hooksPath={str(nohooks).replace(chr(92), '/')}",
            "commit",
            "--no-verify",
            "--allow-empty-message",
            "-m",
            message,
        ]
        if self.sign:
            commit_args.append("-S")
        commit = _git(clean_room, *commit_args, env=env)
        if commit.returncode != 0:
            return Verdict(sid, "error", detail=f"commit failed: {commit.stderr.strip()[:500]}")
        sha = _resolve_sha(clean_room, "HEAD")

        verdict = Verdict(sid, "committed", commit_sha=sha, detail="all gates passed")

        # 5. Push, if configured and a target is set. The master holds the only
        #    push credential; the worker has none.
        remote = str(manifest.get("remote") or "")
        branch = str(manifest.get("branch") or "")
        if self.push and remote and branch:
            push = _git(clean_room, "push", remote, f"HEAD:refs/heads/{branch}", env=env)
            verdict.pushed = push.returncode == 0
            if not verdict.pushed:
                verdict.detail += f"; push failed: {push.stderr.strip()[:300]}"
        return verdict

    def _apply_patch(self, clean_room: Path, patch_path: Path) -> tuple[bool, str]:
        """Apply the submitted patch resiliently, fail-closed.

        Tries plain apply first, then a 3-way merge (uses the blob OIDs embedded
        in the diff so it survives line-ending / context drift between the
        worker's checkout and the clean room), then a whitespace-tolerant pass.
        Any leftover conflict or failure returns False -> the submission is
        rejected, never partially applied.
        """
        attempts = (
            ("--index", "--whitespace=nowarn"),
            ("--index", "--3way", "--whitespace=nowarn"),
            ("--index", "--whitespace=nowarn", "--ignore-whitespace"),
        )
        last_err = ""
        for flags in attempts:
            proc = _git(clean_room, "apply", *flags, str(patch_path))
            if proc.returncode == 0:
                return True, ""
            last_err = proc.stderr.strip()
            # Reset any partial 3-way state before the next attempt.
            _git(clean_room, "checkout", "--", ".")
            _git(clean_room, "reset", "-q")
        return False, last_err

    @staticmethod
    def _normalize(content: bytes) -> bytes:
        """Match enforcement_integrity._normalize: CRLF -> LF before hashing."""
        return content.replace(b"\r\n", b"\n")

    def _verify_cleanroom_integrity(self, clean_room: Path) -> list[str]:
        """Hash the clean-room gate files against the trusted manifest.

        Returns the list of repo-relative paths whose clean-room content does
        NOT match the trusted manifest (tampered or missing). Empty list = OK.
        A no-op (returns []) when no manifest is configured/present — the
        clean-room gates still run and CI's enforcement_integrity is the
        server-side backstop.
        """
        if not self.manifest_path or not self.manifest_path.exists():
            return []
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            # A manifest we cannot parse is treated as tampering, fail-closed.
            return ["<unreadable integrity manifest>"]
        if not isinstance(manifest, dict):
            return ["<malformed integrity manifest>"]
        bad: list[str] = []
        for rel_path, expected in manifest.items():
            target = clean_room / rel_path
            if not target.exists():
                bad.append(rel_path)
                continue
            actual = hashlib.sha256(self._normalize(target.read_bytes())).hexdigest()
            if actual != str(expected).strip().lower():
                bad.append(rel_path)
        return bad

    def _run_gate(self, spec: GateSpec, clean_room: Path, env: dict[str, str]) -> dict[str, Any]:
        # Run the clean room's OWN copy of the gate (verified untampered in
        # step 3) so its __file__-based repo root resolves to the clean room.
        script = clean_room / spec.script
        if not script.exists():
            # Fail closed: a missing gate script is a failure, never a skip.
            return {"name": spec.name, "returncode": 127, "stdout": "", "stderr": f"gate script not found: {script}"}
        proc = subprocess.run(
            [self.python_exe, str(script), *spec.args],
            cwd=str(clean_room),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "name": spec.name,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }

    def _compose_message(self, manifest: dict[str, Any]) -> str:
        body = str(manifest.get("message") or "").strip() or "commit-master: gated change"
        agent = str(manifest.get("agent") or "unknown")
        sid = str(manifest.get("id") or "")
        trailers = [
            "",
            f"Thomas-Submitted-By: {agent}",
            "Thomas-Committed-By: commit-master",
            f"Thomas-Submission-Id: {sid}",
            "Thomas-Gated: commit-master/clean-room",
        ]
        return body + "\n" + "\n".join(trailers) + "\n"

    # -- bookkeeping ------------------------------------------------------ #
    def _load_manifest(self, sub_dir: Path) -> dict[str, Any] | None:
        path = sub_dir / "submission.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        # Shape validation only — we trust nothing here as authority.
        if not str(raw.get("base") or "").strip():
            return None
        return raw

    def _finish(self, sub_dir: Path, verdict: Verdict) -> None:
        _write_verdict(self.layout, verdict)
        # Move the processed submission out of the inbox so it isn't reprocessed.
        processed = self.layout.root / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        dest = processed / sub_dir.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.move(str(sub_dir), str(dest))
        except Exception:
            shutil.rmtree(sub_dir, ignore_errors=True)

    def _teardown_clean_room(self, clean_room: Path) -> None:
        if clean_room.exists():
            _git(self.repo, "worktree", "remove", "--force", str(clean_room))
            if clean_room.exists():
                shutil.rmtree(clean_room, ignore_errors=True)
        _git(self.repo, "worktree", "prune")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve_layout(args: argparse.Namespace, repo: Path) -> CageLayout:
    root = args.cage_root or os.environ.get("THOMAS_CAGE_ROOT") or str(repo / "runtime" / "cage")
    return CageLayout(root=Path(root).expanduser())


def _cmd_submit(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    layout = _resolve_layout(args, repo)
    workboard = Path(args.workboard).resolve() if getattr(args, "workboard", "") else None
    try:
        sub_dir = create_submission(
            layout=layout,
            repo=repo,
            agent=args.agent,
            message=args.message,
            base=args.base,
            patch_file=args.patch_file,
            remote=args.remote,
            branch=args.branch,
            workboard=workboard,
        )
    except InboxBlockedError as exc:
        ack = [
            f"python scripts/crew/workboard/message.py --ack --msg-id {m.get('msg_id')} --by {exc.agent}"
            for m in exc.blocking
        ]
        payload = {
            "ok": False,
            "status": "blocked_unread_messages",
            "agent": exc.agent,
            "blocking": [
                {
                    "msg_id": m.get("msg_id"),
                    "from": m.get("from"),
                    "kind": m.get("kind"),
                    "summary": m.get("summary"),
                    "reasons": m.get("_reasons"),
                }
                for m in exc.blocking
            ],
            "ack": ack,
            "detail": "Read and ACK these coordination messages, then resubmit.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "submission": str(sub_dir), "id": sub_dir.name}))
    return 0


def _cmd_run_once(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    layout = _resolve_layout(args, repo)
    layout.ensure()
    master = CommitMaster(
        repo=repo,
        layout=layout,
        gates_root=Path(args.gates_root).resolve() if args.gates_root else None,
        sign=not args.no_sign,
        push=not args.no_push,
    )
    verdict = master.run_once()
    if verdict is None:
        print(json.dumps({"ok": True, "status": "idle", "detail": "no pending submissions"}))
        return 0
    print(json.dumps({"ok": verdict.status == "committed", **verdict.to_dict()}))
    return 0 if verdict.status == "committed" else 1


def _cmd_watch(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    layout = _resolve_layout(args, repo)
    layout.ensure()
    master = CommitMaster(
        repo=repo,
        layout=layout,
        gates_root=Path(args.gates_root).resolve() if args.gates_root else None,
        sign=not args.no_sign,
        push=not args.no_push,
    )
    print(f"commit-master watching {layout.inbox} (interval={args.interval}s)")
    while True:
        verdict = master.run_once()
        if verdict is not None:
            print(json.dumps(verdict.to_dict()))
        else:
            time.sleep(max(1.0, float(args.interval)))


def _cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    layout = _resolve_layout(args, repo)
    pending = [p.name for p in (layout.inbox.iterdir() if layout.inbox.exists() else []) if p.is_dir()]
    verdicts = [p.name for p in (layout.outbox.iterdir() if layout.outbox.exists() else [])]
    print(
        json.dumps({"cage_root": str(layout.root), "pending": sorted(pending), "verdicts": sorted(verdicts)}, indent=2)
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Commit-master: gated proposer/committer split for the Praxis cage.")
    parser.add_argument("--repo", default=str(_REPO_ROOT), help="repository root (default: this repo)")
    parser.add_argument(
        "--cage-root", default="", help="cage channel root (default: $THOMAS_CAGE_ROOT or <repo>/runtime/cage)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="[worker] drop a submission into the inbox")
    p_submit.add_argument("--agent", required=True)
    p_submit.add_argument("--message", required=True)
    p_submit.add_argument("--base", default="HEAD")
    p_submit.add_argument("--patch-file", default="")
    p_submit.add_argument("--remote", default="")
    p_submit.add_argument("--branch", default="")
    p_submit.add_argument(
        "--workboard", default="", help="WORKBOARD.md for inbox enforcement (default: <repo>/plans/thomas/WORKBOARD.md)"
    )
    p_submit.set_defaults(func=_cmd_submit)

    p_run = sub.add_parser("run-once", help="[master] process the oldest pending submission")
    p_run.add_argument("--gates-root", default="")
    p_run.add_argument("--no-sign", action="store_true")
    p_run.add_argument("--no-push", action="store_true")
    p_run.set_defaults(func=_cmd_run_once)

    p_watch = sub.add_parser("watch", help="[master] poll the inbox forever")
    p_watch.add_argument("--gates-root", default="")
    p_watch.add_argument("--interval", default="5")
    p_watch.add_argument("--no-sign", action="store_true")
    p_watch.add_argument("--no-push", action="store_true")
    p_watch.set_defaults(func=_cmd_watch)

    p_status = sub.add_parser("status", help="show pending submissions and verdicts")
    p_status.set_defaults(func=_cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Normalize empty patch_file/remote/branch to falsy for submit.
    if getattr(args, "patch_file", None) == "":
        args.patch_file = None
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
