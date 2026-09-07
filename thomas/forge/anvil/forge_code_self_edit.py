"""Per-run source snapshots and explicitly invoked source application/recovery.

The source inventory is Git's tracked and nonignored files, excluding runtime
and credential locations. A candidate is a copy, never a shared Git worktree.
This is filesystem separation, not a sandbox for arbitrary shell commands.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class SelfEditSnapshotError(RuntimeError):
    """A complete, stable source snapshot could not be established."""


@contextmanager
def source_application_gate(source_root: Path, *, purpose: str = "application"):
    """Serialize Thomas applications/recoveries across processes for one source.

    This cooperative OS lock does not lock out editors or arbitrary shell writes;
    baseline and per-file checks still detect those changes where observable.
    The file remains after release. OS lock ownership ends when its process exits.
    """
    root_name = os.path.normcase(str(source_root.resolve()))
    if purpose != "application":
        root_name = purpose + "\0" + root_name
    key = hashlib.sha256(root_name.encode("utf-8")).hexdigest()
    directory = Path.home() / ".thomas" / "source-application-locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{key}.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SelfEditSnapshotError("Another source application or recovery is active") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


_EXCLUDED_DIRS = {".git", ".thomas", "node_modules", ".venv", "venv", "__pycache__"}
_SECRET_NAMES = {".env", "credentials.json", "token.json", "secrets.json"}


@dataclass(frozen=True)
class SourceCandidate:
    source_root: Path
    candidate_root: Path
    baseline: dict[str, str]


def _source_path(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(part in {"..", "."} for part in name.parts):
        raise SelfEditSnapshotError("Invalid source inventory path")
    path = root.joinpath(*name.parts)
    # Reject junctions and symlinks at every component, including internal links.
    # Copying their referents would change both candidate identity and scope.
    current = root
    for part in name.parts:
        current /= part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise SelfEditSnapshotError(f"Source link cannot be snapshotted: {relative}")
    if not path.resolve().is_relative_to(root):
        raise SelfEditSnapshotError("Source inventory escaped its root")
    return path


def _inventory(root: Path) -> list[str]:
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            timeout=30,
        )
        if Path(top.stdout.decode("utf-8").strip()).resolve() != root:
            raise SelfEditSnapshotError("Source must be the repository root")
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
            timeout=30,
        )
        names = result.stdout.decode("utf-8").split("\0")
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise SelfEditSnapshotError("Source inventory is unavailable") from exc
    return sorted(
        {
            name
            for name in names
            if name
            and not (
                any(part.casefold() in _EXCLUDED_DIRS for part in PurePosixPath(name).parts)
                or PurePosixPath(name).parts[0].casefold() == "runtime"
                or PurePosixPath(name).name.casefold() in _SECRET_NAMES
                or PurePosixPath(name).name.casefold().startswith(".env.")
            )
        }
    )


def _file_state(path: Path) -> tuple[bytes, int, str]:
    payload = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    digest = hashlib.sha256(payload).hexdigest() + f":{mode:o}"
    return payload, mode, digest


def source_fingerprints(root: Path) -> dict[str, str]:
    """Fingerprint the current eligible source, including uncommitted deletions."""
    root = root.resolve()
    hashes = {}
    try:
        for relative in _inventory(root):
            path = _source_path(root, relative)
            if not path.exists():
                continue  # tracked deletion is intentionally absent in the copy
            if not path.is_file():
                raise SelfEditSnapshotError(f"Source entry is not a regular file: {relative}")
            hashes[relative] = _file_state(path)[2]
    except OSError as exc:
        raise SelfEditSnapshotError("Source bytes are unavailable") from exc
    return hashes


def prepare_candidate(source_root: Path, candidates_root: Path) -> SourceCandidate:
    """Copy a stable source view into a unique folder and retain its baseline.

    Failures leave only a private partial candidate for diagnosis. No source
    writes or promotion occur. Callers must not launch an unsuccessful copy.
    """
    source = source_root.resolve()
    parent = candidates_root.resolve()
    if parent == source or parent.is_relative_to(source):
        raise SelfEditSnapshotError("Candidates must be outside the live source tree")
    baseline = source_fingerprints(source)
    if not baseline:
        raise SelfEditSnapshotError("Source snapshot is empty")
    parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix="self-edit-", dir=parent))
    try:
        for relative, expected in baseline.items():
            payload, mode, digest = _file_state(_source_path(source, relative))
            if digest != expected:
                raise SelfEditSnapshotError("Source changed while preparing the candidate")
            target = candidate.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(mode)
        if source_fingerprints(source) != baseline:
            raise SelfEditSnapshotError("Source changed while preparing the candidate")
        # Keep supervisor evidence outside the worker's candidate root.
        candidate.with_suffix(".baseline.json").write_text(
            json.dumps({"source_root": str(source), "files": baseline}, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        raise SelfEditSnapshotError("Candidate copy could not be completed") from exc
    return SourceCandidate(source, candidate, baseline)


def discard_candidate(candidate_root: Path) -> None:
    """Remove a retained candidate and its supervisor-side evidence."""
    if candidate_root.is_symlink() or (hasattr(candidate_root, "is_junction") and candidate_root.is_junction()):
        raise SelfEditSnapshotError("Refusing to discard a redirected candidate folder")
    candidate = candidate_root.resolve()
    if not candidate.name.startswith("self-edit-"):
        raise SelfEditSnapshotError("Refusing to discard an unknown candidate folder")
    parent = candidate.parent
    paths = [
        candidate,
        candidate.with_suffix(".baseline.json"),
        parent / (candidate.name + ".runtime"),
        parent / (candidate.name + ".verification-runtime"),
    ]
    # Exact owned names only. Prefix globbing also selected other candidates
    # and unrelated user folders. Validate every target before any removal.
    for path in paths:
        if (
            path.resolve().parent != parent
            or path.is_symlink()
            or (hasattr(path, "is_junction") and path.is_junction())
        ):
            raise SelfEditSnapshotError("Refusing to discard redirected candidate material")
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        elif path.is_file():
            path.unlink()


def assert_source_unchanged(candidate: SourceCandidate) -> None:
    """Refuse stale candidates; success does not authorize promotion."""
    if source_fingerprints(candidate.source_root) != candidate.baseline:
        raise SelfEditSnapshotError("Live source changed after the candidate was created")


def candidate_snapshot(root: Path) -> dict[str, str]:
    """Attribute candidate bytes and modes, refusing unreadable or linked source."""
    base = root.resolve()
    if not base.is_dir():
        raise SelfEditSnapshotError("Candidate root is unavailable")
    fingerprints = {}
    total_bytes = 0

    def listing_error(exc: OSError) -> None:
        raise SelfEditSnapshotError("Candidate inventory is unreadable") from exc

    try:
        for folder, directories, files in os.walk(base, onerror=listing_error):
            here = Path(folder)
            directories[:] = sorted(name for name in directories if name.casefold() not in _EXCLUDED_DIRS)
            for name in directories:
                _source_path(base, (here / name).relative_to(base).as_posix())
            for name in sorted(files):
                relative = (here / name).relative_to(base).as_posix()
                path = _source_path(base, relative)
                size = path.stat().st_size
                total_bytes += size
                if len(fingerprints) >= 20_000 or size > 128 * 1024 * 1024 or total_bytes > 4 * 1024**3:
                    raise SelfEditSnapshotError("Candidate exceeds the complete attribution limit")
                if not path.is_file():
                    raise SelfEditSnapshotError("Candidate contains a non-file source entry")
                fingerprints[relative] = _file_state(path)[2]
    except OSError as exc:
        raise SelfEditSnapshotError("Candidate bytes are unreadable") from exc
    return fingerprints


def candidate_delta_since(root: Path, before: dict[str, str]) -> list[str]:
    current = candidate_snapshot(root)
    return sorted(path for path in before.keys() | current.keys() if before.get(path) != current.get(path))


@dataclass(frozen=True)
class CandidateCheckReceipt:
    """Supervisor-run check evidence, not permission to promote source changes."""

    source_root: str
    candidate_root: str
    baseline_digest: str
    candidate_digest: str
    plan_digest: str
    checks_passed: bool
    evidence_json: str


def _snapshot_digest(snapshot: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()


def _check_plan_digest(commands: tuple[tuple[str, ...], ...]) -> str:
    return hashlib.sha256(json.dumps(commands).encode("utf-8")).hexdigest()


def verification_environment(candidate: SourceCandidate) -> dict[str, str]:
    """Supply test processes a separate runtime and no inherited API credentials."""
    root = candidate.candidate_root.with_name(candidate.candidate_root.name + ".verification-runtime")
    if root.resolve() != root:
        raise SelfEditSnapshotError("Verification runtime redirects outside its assigned location")
    root.mkdir(parents=True, exist_ok=True)
    system_keys = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "NUMBER_OF_PROCESSORS",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in system_keys}
    locations = {
        "DATA_DIR": "",
        "HOME": "",
        "STATE_DIR": "",
        "MEMORY_DATA_DIR": "",
        "MEMORY_ROOT": "runtime",
        "RUNTIME_DIR": "runtime",
        "LOG_FILE": "logs/thomas.log",
        "CHAT_LOG_DIR": "logs/chat",
        "DOWNLOAD_DIR": "downloads",
        "BROWSER_DOWNLOAD_DIR": "downloads",
        "ARTIFACT_DIR": "artifacts",
        "ARTIFACTS_DIR": "artifacts",
        "SANDBOX_RUNS_DIR": "runtime/sandbox/runs",
        "SANDBOX_WHEELHOUSE_DIR": "runtime/sandbox/wheelhouse_cache",
        "RUNS_DB_PATH": ".thomas/runs.sqlite3",
        "TASK_LEDGER_DB_PATH": ".thomas/task_ledger.sqlite3",
        "DB_PATH": "thomas.db",
        "SQLITE_PATH": "thomas.db",
        "DB_CONNECTIONS_FILE": "thomas_db_connections.json",
        "WEBHOOKS_FILE": "json/thomas_webhooks.json",
        "WEBHOOK_RECEIPTS_FILE": "json/thomas_webhook_receipts.json",
        "WEBHOOK_STATS_FILE": "json/thomas_webhook_stats.json",
        "WEBHOOK_INBOX_FILE": "json/thomas_webhook_inbox.jsonl",
        "WEB_SEARCH_CACHE_DB_PATH": "runtime/cache/web_tools_cache.sqlite3",
        "STATE_FILE": "thomas_state.json",
        "DAILY_REPORT_DIR": "reports",
        "JOURNAL_DIR": "journal",
    }
    env.update({"THOMAS_" + key: str(root / relative) for key, relative in locations.items()})
    env.update(THOMAS_PROFILE="", THOMAS_MEMORY_PROFILE="", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def verify_candidate_checks(
    candidate: SourceCandidate,
    commands: tuple[tuple[str, ...], ...],
    *,
    timeout_seconds: int = 120,
) -> CandidateCheckReceipt:
    """Run supervisor-selected checks and bind every result to the exact bytes.

    Commands must come from the supervisor's check plan, never a worker success
    message. All checks must run and pass; a mixed pass/refusal is insufficient.
    Coverage, policy review, and source promotion remain separate requirements.
    """
    from evolve_supervisor.independent_verifier import (
        EVIDENCE_MATCHED,
        ClaimedCheck,
        CompletionClaim,
        verify_claim,
    )

    assert_source_unchanged(candidate)
    before = candidate_snapshot(candidate.candidate_root)
    verdict = verify_claim(
        CompletionClaim(
            description="Independent self-edit candidate checks",
            cwd=str(candidate.candidate_root),
            checks=tuple(ClaimedCheck(command=list(command)) for command in commands),
        ),
        timeout_seconds=timeout_seconds,
        environment=verification_environment(candidate),
    )
    after = candidate_snapshot(candidate.candidate_root)
    if before != after:
        raise SelfEditSnapshotError("Candidate changed during verification; checks must run again")
    assert_source_unchanged(candidate)
    passed = (
        bool(commands)
        and len(verdict.evidence) == len(commands)
        and all(
            row.status == EVIDENCE_MATCHED and row.actual_returncode == 0 and not row.timed_out
            for row in verdict.evidence
        )
    )
    return CandidateCheckReceipt(
        source_root=str(candidate.source_root),
        candidate_root=str(candidate.candidate_root),
        baseline_digest=_snapshot_digest(candidate.baseline),
        candidate_digest=_snapshot_digest(after),
        plan_digest=_check_plan_digest(commands),
        checks_passed=passed,
        evidence_json=json.dumps([row.to_dict() for row in verdict.evidence], sort_keys=True),
    )


def assert_check_receipt_current(
    candidate: SourceCandidate,
    receipt: CandidateCheckReceipt,
    commands: tuple[tuple[str, ...], ...],
) -> None:
    """Reject failed or stale check evidence; this does not authorize promotion."""
    if not receipt.checks_passed:
        raise SelfEditSnapshotError("Candidate checks did not all pass")
    if receipt.plan_digest != _check_plan_digest(commands):
        raise SelfEditSnapshotError("Verification receipt does not match the required check plan")
    if (
        receipt.source_root != str(candidate.source_root)
        or receipt.candidate_root != str(candidate.candidate_root)
        or receipt.baseline_digest != _snapshot_digest(candidate.baseline)
        or receipt.candidate_digest != _snapshot_digest(candidate_snapshot(candidate.candidate_root))
    ):
        raise SelfEditSnapshotError("Verification receipt does not match the current candidate")
    assert_source_unchanged(candidate)


def plan_candidate_checks(
    candidate: SourceCandidate, changed: list[str]
) -> tuple[tuple[tuple[str, ...], ...], list[str]]:
    """Select existing regression checks from live source, never worker prose.

    A reference selects a check; it does not prove behavioral coverage. Files
    without a selected regression check remain explicitly uncovered.
    """
    from evolve_supervisor.coverage_floor import select_blast_radius_tests

    assert_source_unchanged(candidate)
    tests = {
        path: _source_path(candidate.source_root, path).read_text(encoding="utf-8")
        for path in candidate.baseline
        if path.startswith("tests/") and Path(path).name.startswith("test_") and path.endswith(".py")
    }
    names: dict[str, int] = {}
    for path in candidate.baseline:
        names[Path(path).name] = names.get(Path(path).name, 0) + 1
    selected: set[str] = set()
    uncovered = []
    for path in changed:
        direct = {
            test
            for test, content in tests.items()
            if path in content or (names.get(Path(path).name, 0) == 1 and Path(path).name in content)
        }
        if path.endswith(".py"):
            direct.update(select_blast_radius_tests([path], candidate.source_root, max_files=len(tests) + 1))
        if direct:
            selected.update(direct)
        else:
            uncovered.append(path)
    current = candidate_snapshot(candidate.candidate_root)
    runner_modules = {"pytest", "_pytest", "pluggy", "py_compile", "coverage", "sitecustomize", "usercustomize"}
    for path in current:
        root_name = PurePosixPath(path).parts[0].casefold()
        stem = root_name.split(".", 1)[0]
        if stem in runner_modules and (root_name == stem or root_name.endswith((".py", ".pyc", ".pyo", ".pyd", ".so"))):
            raise SelfEditSnapshotError("Candidate shadows the independent test plan runner")
    protected_checks = selected | {
        path
        for path in candidate.baseline.keys() | current.keys()
        if path.casefold().startswith(("tests/", "pytest/", "_pytest/", "pluggy/"))
        or Path(path).name.casefold() in {"conftest.py", "sitecustomize.py", "usercustomize.py"}
        or path.casefold()
        in {"pytest.ini", ".pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.py", "py_compile.py"}
    }
    if any(current.get(path) != candidate.baseline.get(path) for path in protected_checks):
        raise SelfEditSnapshotError("Candidate changed the independent test plan or its configuration")
    commands = []
    python_files = [path for path in changed if path.endswith(".py") and path in current]
    if python_files:
        commands.append(("python", "-m", "py_compile", *sorted(python_files)))
    if selected:
        commands.append(("python", "-m", "pytest", "-p", "no:cacheprovider", "-q", *sorted(selected)))
    return tuple(commands), sorted(uncovered)


def check_prepared_candidate(candidate: SourceCandidate, changed: list[str]) -> dict:
    """Automatic check phase; its result never authorizes source promotion."""
    commands, uncovered = plan_candidate_checks(candidate, changed)
    result = {"commands": [list(command) for command in commands], "uncovered_files": uncovered, "checks_passed": False}
    if uncovered or not commands:
        result["reason"] = "Independent regression checks are missing for candidate changes"
        return result
    receipt = verify_candidate_checks(candidate, commands)
    result.update(
        checks_passed=receipt.checks_passed,
        evidence=json.loads(receipt.evidence_json),
        candidate_digest=receipt.candidate_digest,
        baseline_digest=receipt.baseline_digest,
        plan_digest=receipt.plan_digest,
    )
    if receipt.checks_passed:
        assert_check_receipt_current(candidate, receipt, commands)
    return result


def prepare_source_application(
    candidate: SourceCandidate,
    receipt: CandidateCheckReceipt,
    commands: tuple[tuple[str, ...], ...],
    approved_paths: tuple[str, ...],
) -> Path:
    """Persist exact application/rollback material without changing live source.

    The caller supplies the reviewed scope. Check evidence alone is not policy
    approval, and a prepared record never means a candidate has been applied.
    """
    assert_check_receipt_current(candidate, receipt, commands)
    if not approved_paths or len(set(approved_paths)) != len(approved_paths):
        raise SelfEditSnapshotError("A nonempty, unique reviewed application scope is required")
    if candidate.candidate_root.resolve().is_relative_to(candidate.source_root.resolve()):
        raise SelfEditSnapshotError("Application staging must stay outside live source")
    after_snapshot = candidate_snapshot(candidate.candidate_root)
    entries = {}
    total = 0

    def capture(root: Path, relative: str, expected: str | None) -> dict:
        nonlocal total
        path = _source_path(root, relative)
        if not path.exists():
            if expected is not None:
                raise SelfEditSnapshotError("Application source disappeared while staging")
            return {"kind": "missing", "fingerprint": None}
        if expected is None or not path.is_file():
            raise SelfEditSnapshotError("An application path is outside its verified file inventory")
        payload, mode, fingerprint = _file_state(path)
        if fingerprint != expected:
            raise SelfEditSnapshotError("Application source changed while staging")
        total += len(payload)
        if total > 100 * 1024 * 1024:
            raise SelfEditSnapshotError("Application recovery record exceeds its complete capture limit")
        return {
            "kind": "file",
            "fingerprint": fingerprint,
            "mode": mode,
            "data": base64.b64encode(payload).decode("ascii"),
        }

    for relative in sorted(approved_paths):
        # Validate both names before comparing inventories; an outside path
        # must not turn into a misleading 'unchanged' or 'missing' record.
        _source_path(candidate.source_root, relative)
        _source_path(candidate.candidate_root, relative)
        before_digest = candidate.baseline.get(relative)
        after_digest = after_snapshot.get(relative)
        if before_digest == after_digest:
            raise SelfEditSnapshotError(f"Reviewed application path has no verified change: {relative}")
        entries[relative] = {
            "before": capture(candidate.source_root, relative, before_digest),
            "after": capture(candidate.candidate_root, relative, after_digest),
        }
    assert_check_receipt_current(candidate, receipt, commands)
    full_delta = {
        path
        for path in candidate.baseline.keys() | after_snapshot.keys()
        if candidate.baseline.get(path) != after_snapshot.get(path)
    }
    record = {
        "schema": 1,
        "state": "prepared",
        "applied": False,
        "source_root": str(candidate.source_root),
        "candidate_root": str(candidate.candidate_root),
        "baseline_digest": receipt.baseline_digest,
        "candidate_digest": receipt.candidate_digest,
        "plan_digest": receipt.plan_digest,
        "commands": [list(command) for command in commands],
        "files": entries,
        "full_candidate_delta_selected": set(approved_paths) == full_delta,
        "unselected_candidate_paths": sorted(full_delta - set(approved_paths)),
    }
    directory = Path(tempfile.mkdtemp(prefix="source-application-", dir=candidate.candidate_root.parent))
    temporary = directory / "application.tmp"
    destination = directory / "application.json"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    if json.loads(destination.read_text(encoding="utf-8")) != record:
        raise SelfEditSnapshotError("Application recovery record could not be read back")
    return destination


def _persist_application(path: Path, record: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if json.loads(path.read_text(encoding="utf-8")) != record:
        raise SelfEditSnapshotError("Application journal readback failed")


def _entry_fingerprint(state: dict) -> str | None:
    if state.get("kind") == "missing" and state.get("fingerprint") is None:
        return None
    if state.get("kind") != "file":
        raise SelfEditSnapshotError("Invalid application file state")
    payload = base64.b64decode(state["data"], validate=True)
    mode = int(state["mode"])
    if mode < 0 or mode > 0o7777:
        raise SelfEditSnapshotError("Invalid application file mode")
    actual = hashlib.sha256(payload).hexdigest() + f":{mode:o}"
    if actual != state.get("fingerprint"):
        raise SelfEditSnapshotError("Application recovery bytes do not match their fingerprint")
    return actual


def _validated_application(candidate, receipt, commands, path: Path, approved_paths: tuple[str, ...]) -> dict:
    parent = candidate.candidate_root.parent
    try:
        relative = path.relative_to(parent).as_posix()
    except ValueError as exc:
        raise SelfEditSnapshotError("Application journal is outside its staging directory") from exc
    _source_path(parent, relative)
    if (
        path.name != "application.json"
        or path.parent.parent != parent
        or not path.parent.name.startswith("source-application-")
    ):
        raise SelfEditSnapshotError("Application journal location is invalid")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        not receipt.checks_passed
        or receipt.plan_digest != _check_plan_digest(commands)
        or receipt.baseline_digest != _snapshot_digest(candidate.baseline)
        or receipt.source_root != str(candidate.source_root)
        or receipt.candidate_root != str(candidate.candidate_root)
        or record.get("schema") != 1
        or record.get("source_root") != receipt.source_root
        or record.get("candidate_root") != receipt.candidate_root
        or record.get("baseline_digest") != receipt.baseline_digest
        or record.get("candidate_digest") != receipt.candidate_digest
        or record.get("plan_digest") != receipt.plan_digest
        or record.get("commands") != [list(command) for command in commands]
    ):
        raise SelfEditSnapshotError("Application record does not match verified evidence")
    files = record.get("files")
    if (
        not isinstance(files, dict)
        or not files
        or set(files) != set(approved_paths)
        or len(approved_paths) != len(files)
    ):
        raise SelfEditSnapshotError("Application scope does not match reviewed paths")
    reconstructed = dict(candidate.baseline)
    for relative, entry in files.items():
        _source_path(candidate.source_root, relative)
        before = _entry_fingerprint(entry["before"])
        after = _entry_fingerprint(entry["after"])
        if before != candidate.baseline.get(relative) or before == after:
            raise SelfEditSnapshotError("Application pre-image does not match verified source")
        if after is None:
            reconstructed.pop(relative, None)
        else:
            reconstructed[relative] = after
    if _snapshot_digest(reconstructed) != receipt.candidate_digest:
        raise SelfEditSnapshotError("Partial application requires verification of that exact subset")
    if record.get("state") not in {"prepared", "applying", "applied", "recovery_required", "rolled_back"}:
        raise SelfEditSnapshotError("Application journal state is invalid")
    return record


def _current_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise SelfEditSnapshotError("Application encountered a non-file source path")
    return _file_state(path)[2]


def _recoverable_states(entry: dict) -> set[str | None]:
    states = set()
    for state in (entry["before"], entry["after"]):
        fingerprint = _entry_fingerprint(state)
        states.add(fingerprint)
        if fingerprint is not None:
            # Windows may require clearing read-only before replacement. The
            # journal precedes that operation, so recovery recognizes this one
            # deliberate intermediate mode as well as exact before/after.
            digest = fingerprint.rsplit(":", 1)[0]
            states.add(digest + f":{int(state['mode']) | stat.S_IWRITE:o}")
    return states


def _install_application_state(target: Path, state: dict, allowed: set[str | None]) -> None:
    if _current_fingerprint(target) not in allowed:
        raise SelfEditSnapshotError("Source changed before its application write")
    expected = _entry_fingerprint(state)
    if _current_fingerprint(target) == expected:
        return
    if state["kind"] == "missing":
        if target.exists():
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWRITE)
            target.unlink()
        return
    payload = base64.b64decode(state["data"], validate=True)
    if target.is_file() and target.read_bytes() == payload:
        target.chmod(int(state["mode"]))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".source-application-", dir=target.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        staged.chmod(int(state["mode"]))
        if _current_fingerprint(target) not in allowed:
            raise SelfEditSnapshotError("Source changed while its application write was staged")
        if target.exists():
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWRITE)
        os.replace(staged, target)
    finally:
        if staged.exists():
            staged.chmod(stat.S_IMODE(staged.stat().st_mode) | stat.S_IWRITE)
            staged.unlink()


def rollback_source_application(candidate, receipt, commands, path: Path, approved_paths: tuple[str, ...]) -> list[str]:
    """Restore journaled files while preserving any unrecognized later edits."""
    with source_application_gate(candidate.source_root):
        return _rollback_source_application_locked(candidate, receipt, commands, path, approved_paths)


def _rollback_source_application_locked(candidate, receipt, commands, path, approved_paths) -> list[str]:
    record = _validated_application(candidate, receipt, commands, path, approved_paths)
    if record["state"] == "prepared":
        raise SelfEditSnapshotError("This application never started")
    files = record["files"]
    if record["state"] == "rolled_back":
        if any(
            _current_fingerprint(_source_path(candidate.source_root, name)) != entry["before"]["fingerprint"]
            for name, entry in files.items()
        ):
            raise SelfEditSnapshotError("Source changed after the completed recovery")
        return sorted(files)
    for relative, entry in files.items():
        if _current_fingerprint(_source_path(candidate.source_root, relative)) not in _recoverable_states(entry):
            raise SelfEditSnapshotError(f"Recovery refused a later source edit: {relative}")
    record.update(state="recovery_required", applied=False)
    _persist_application(path, record)
    for relative, entry in reversed(list(files.items())):
        target = _source_path(candidate.source_root, relative)
        _install_application_state(target, entry["before"], _recoverable_states(entry))
        if _current_fingerprint(target) != entry["before"]["fingerprint"]:
            raise SelfEditSnapshotError("Recovery file readback failed")
    record.update(state="rolled_back", applied=False)
    _persist_application(path, record)
    return sorted(files)


def apply_source_application(candidate, receipt, commands, path: Path, approved_paths: tuple[str, ...]) -> list[str]:
    """Apply one reviewed full delta with per-file recovery, not a tree-wide atomic swap.

    The source's cross-process coordination gate covers application and recovery.
    This primitive does not supply policy approval or activate a running desktop.
    """
    with source_application_gate(candidate.source_root):
        return _apply_source_application_locked(candidate, receipt, commands, path, approved_paths)


def _apply_source_application_locked(candidate, receipt, commands, path, approved_paths) -> list[str]:
    record = _validated_application(candidate, receipt, commands, path, approved_paths)
    files = record["files"]
    if record["state"] == "applied":
        if any(
            _current_fingerprint(_source_path(candidate.source_root, name)) != entry["after"]["fingerprint"]
            for name, entry in files.items()
        ):
            raise SelfEditSnapshotError("Applied source changed after this transaction")
        return sorted(files)
    if record["state"] not in {"prepared", "rolled_back"}:
        raise SelfEditSnapshotError("Recover the interrupted application before retrying")
    assert_check_receipt_current(candidate, receipt, commands)
    record.update(state="applying", applied=False)
    _persist_application(path, record)
    try:
        for relative, entry in files.items():
            target = _source_path(candidate.source_root, relative)
            _install_application_state(target, entry["after"], {entry["before"]["fingerprint"]})
            if _current_fingerprint(target) != entry["after"]["fingerprint"]:
                raise SelfEditSnapshotError("Application file readback failed")
        live = source_fingerprints(candidate.source_root)
        for relative in candidate.baseline.keys() | files.keys():
            fingerprint = _current_fingerprint(_source_path(candidate.source_root, relative))
            if fingerprint is None:
                live.pop(relative, None)
            else:
                live[relative] = fingerprint
        if _snapshot_digest(live) != receipt.candidate_digest:
            raise SelfEditSnapshotError("Source changed during application")
        record.update(state="applied", applied=True)
        _persist_application(path, record)
    except (OSError, RuntimeError, ValueError) as exc:
        try:
            _rollback_source_application_locked(candidate, receipt, commands, path, approved_paths)
        except (OSError, RuntimeError, ValueError) as recovery_error:
            raise SelfEditSnapshotError(
                f"Application interrupted; recovery required at {path}: {recovery_error}"
            ) from exc
        raise SelfEditSnapshotError("Application failed; journaled source files were restored") from exc
    return sorted(files)
