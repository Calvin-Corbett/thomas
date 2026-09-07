#!/usr/bin/env python3
"""Privileged commit-master for the Praxis cage.

Workers can only propose a patch and manifest through the one-way inbox. The
master rebuilds that submission from pristine ``HEAD`` in a clean worktree,
verifies protected gate code, strips bypass environment variables, runs the
trusted gate suite, and creates a verified commit object. It optionally signs
and pushes with credentials unavailable to the worker, then records a verdict
through the one-way outbox.

The operating-system cage makes this a privilege boundary by protecting this
facade and the helper modules under ``scripts/forge/gates``. Without those ACLs
the same flow is useful verification but remains advisory.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.brief import commit_integrity, coordination_barrier
from scripts.crew.brief import identity as agent_identity
from scripts.forge.gates import commit_master_cli as _commit_master_cli
from scripts.forge.gates import commit_master_inbox as _commit_master_inbox
from thomas.core import agent_session_identity

_PROTECTED_GATE_ROOT = (_REPO_ROOT / "scripts" / "forge" / "gates").resolve()


def _privileged_dependency_paths() -> tuple[Path, ...]:
    """Return resolved source paths for code trusted by the commit-master."""
    modules = (_commit_master_inbox, _commit_master_cli)
    return tuple(Path(str(module.__file__)).resolve(strict=True) for module in modules)


def _verify_privileged_dependencies_protected(
    dependency_paths: tuple[Path, ...] | None = None,
    *,
    protected_root: Path | None = None,
) -> tuple[Path, ...]:
    """Refuse helper code resolved outside the cage's protected gate directory."""
    root = (protected_root or _PROTECTED_GATE_ROOT).resolve(strict=True)
    paths = dependency_paths or _privileged_dependency_paths()
    unprotected = [path for item in paths if not (path := Path(item).resolve()).is_relative_to(root)]
    if unprotected:
        rendered = ", ".join(str(path) for path in unprotected)
        raise RuntimeError(f"commit-master privileged dependency outside protected gate boundary: {rendered}")
    return tuple(Path(path).resolve() for path in paths)


_verify_privileged_dependencies_protected()

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


def _session_binding_required(repo: Path) -> bool:
    has_session_source = any(
        str(os.getenv(key) or "").strip() for key in ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")
    )
    return has_session_source or repo.resolve() == _REPO_ROOT.resolve()


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        input=input_text,
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
# Coordination delivery enforcement (protected implementation + stable facade)
# --------------------------------------------------------------------------- #
InboxBlockedError = _commit_master_inbox.InboxBlockedError
_ALWAYS_BLOCK_KINDS = _commit_master_inbox.ALWAYS_BLOCK_KINDS
_PATH_TOKEN_RE = _commit_master_inbox.PATH_TOKEN_RE
_SUBMISSION_HOLD_RE = _commit_master_inbox.SUBMISSION_HOLD_RE


def _paths_from_patch(patch_text: str) -> list[str]:
    return _commit_master_inbox.paths_from_patch(patch_text)


def _submission_changed_files(repo: Path, patch_file: str | None) -> list[str]:
    return _commit_master_inbox.submission_changed_files(repo, patch_file, core=sys.modules[__name__])


def _co_norm_path(value: str) -> str:
    return _commit_master_inbox.norm_path(value)


def _co_paths_overlap(a: str, b: str) -> bool:
    return _commit_master_inbox.paths_overlap(a, b, core=sys.modules[__name__])


def _co_path_tokens(text: str) -> list[str]:
    return _commit_master_inbox.path_tokens(text, core=sys.modules[__name__])


def _co_submission_hold(text: str) -> bool:
    return _commit_master_inbox.submission_hold(text, core=sys.modules[__name__])


def _co_active_task_scopes(workboard_text: str) -> dict[str, list[str]]:
    return _commit_master_inbox.active_task_scopes(workboard_text)


def _co_unread_messages(workboard: Path, agent: str) -> list[dict[str, Any]]:
    return _commit_master_inbox.unread_messages(workboard, agent, core=sys.modules[__name__])


def _inbox_blocking(workboard: Path, agent: str, repo: Path, patch_file: str | None) -> list[dict[str, Any]]:
    return _commit_master_inbox.inbox_blocking(workboard, agent, repo, patch_file, core=sys.modules[__name__])


def _default_workboard(repo: Path) -> Path:
    return _commit_master_inbox.default_workboard(repo)


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
    commit_integrity.validate_caller_message(message)
    binding = agent_identity.require_bound_identity(agent, repo_root=repo) if _session_binding_required(repo) else None
    board = workboard or _default_workboard(repo)
    if board.exists() or repo.resolve() == _REPO_ROOT.resolve():
        coordination_barrier.require_clear_p0(board, bound_agent=agent)
    layout.ensure()
    base_sha = _resolve_sha(repo, base)
    if not base_sha:
        raise ValueError(f"cannot resolve base ref: {base!r}")

    if enforce_inbox:
        blocking = _inbox_blocking(board, agent, repo, patch_file)
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
    if board.exists() or repo.resolve() == _REPO_ROOT.resolve():
        coordination_barrier.require_clear_p0(board, bound_agent=agent)
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
        "session_id": binding.session_id if binding is not None else "",
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
        agent = str(manifest.get("agent") or "")
        session_id = str(manifest.get("session_id") or "")
        try:
            commit_integrity.validate_caller_message(str(manifest.get("message") or ""))
            if session_id or self.repo.resolve() == _REPO_ROOT.resolve():
                agent_session_identity.validate_recorded_binding(
                    self.repo,
                    agent_id=agent,
                    session_id=session_id,
                )
            board = _default_workboard(self.repo)
            if board.exists() or self.repo.resolve() == _REPO_ROOT.resolve():
                coordination_barrier.require_clear_p0(board, bound_agent=agent)
        except (coordination_barrier.CoordinationBlocked, ValueError) as exc:
            return Verdict(sid, "rejected", detail=str(exc))

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

        # 5. All gates green. Create a commit object with MASTER-stamped
        #    trailers. --no-verify is correct HERE and only here: the master has
        #    already run the trusted gates in this clean room, so the worktree's
        #    shared hooks must not re-fire (they reference the worker's paths and
        #    could be tampered). The master IS the verification. Any approval
        #    trailer the worker wrote in `message` is advisory text only.
        try:
            sha = self._create_verified_commit(clean_room, base, manifest, env)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return Verdict(sid, "error", detail=f"commit failed verification: {exc}")

        verdict = Verdict(sid, "committed", commit_sha=sha, detail="all gates passed")

        # 5. Push, if configured and a target is set. The master holds the only
        #    push credential; the worker has none.
        remote = str(manifest.get("remote") or "")
        branch = str(manifest.get("branch") or "")
        if self.push and remote and branch:
            push = _git(clean_room, "push", remote, f"{sha}:refs/heads/{branch}", env=env)
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
            ("Thomas-Submitted-By", agent),
            ("Thomas-Committed-By", "commit-master"),
            ("Thomas-Submission-Id", sid),
            ("Thomas-Gated", "commit-master/clean-room"),
        ]
        return commit_integrity.compose_message(body, trailers)

    def _create_verified_commit(
        self,
        clean_room: Path,
        parent: str,
        manifest: dict[str, Any],
        env: dict[str, str],
    ) -> str:
        body = str(manifest.get("message") or "").strip() or "commit-master: gated change"
        trailers = [
            ("Thomas-Submitted-By", str(manifest.get("agent") or "unknown")),
            ("Thomas-Committed-By", "commit-master"),
            ("Thomas-Submission-Id", str(manifest.get("id") or "")),
            ("Thomas-Gated", "commit-master/clean-room"),
        ]
        message = commit_integrity.compose_message(body, trailers)
        tree_proc = _git(clean_room, "write-tree", env=env)
        if tree_proc.returncode != 0:
            raise RuntimeError(tree_proc.stderr.strip() or "git write-tree failed")
        tree = tree_proc.stdout.strip()
        sign_args = ("-S",) if self.sign else ()
        commit_proc = _git(
            clean_room,
            "commit-tree",
            tree,
            "-p",
            parent,
            *sign_args,
            env=env,
            input_text=message,
        )
        if commit_proc.returncode != 0:
            raise RuntimeError(commit_proc.stderr.strip() or "git commit-tree failed")
        sha = commit_proc.stdout.strip()
        commit_integrity.read_verified_commit(
            clean_room,
            sha,
            expected_tree=tree,
            expected_parent=parent,
            expected_body=body,
            expected_trailers=trailers,
            run=lambda repo, args: _git(repo, *args, env=env),
        )
        return sha

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
# CLI (protected implementation + stable facade)
# --------------------------------------------------------------------------- #
def _resolve_layout(args: Any, repo: Path) -> CageLayout:
    return _commit_master_cli.resolve_layout(args, repo, core=sys.modules[__name__])


def _cmd_submit(args: Any) -> int:
    return _commit_master_cli.cmd_submit(args, core=sys.modules[__name__])


def _cmd_run_once(args: Any) -> int:
    return _commit_master_cli.cmd_run_once(args, core=sys.modules[__name__])


def _cmd_watch(args: Any) -> int:
    return _commit_master_cli.cmd_watch(args, core=sys.modules[__name__])


def _cmd_status(args: Any) -> int:
    return _commit_master_cli.cmd_status(args, core=sys.modules[__name__])


def build_parser() -> Any:
    return _commit_master_cli.build_parser(core=sys.modules[__name__])


def main(argv: list[str] | None = None) -> int:
    return _commit_master_cli.main(argv, core=sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
