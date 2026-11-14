"""Supervisor-owned run identities, private snapshots, and independent checks."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from thomas.forge.anvil import forge_code_self_edit as isolation

from .evolve_agent_self_edit_policy import validate_delta, validate_scope


def record_path(catalog: Path, cid: str, run_id: str) -> Path:
    key = hashlib.sha256((cid + "\0" + run_id).encode()).hexdigest()
    return catalog / ".thomas" / "evolve" / "agent" / "self-edit" / (key + ".json")


def save_record(catalog: Path, record: dict) -> None:
    path = record_path(catalog, record["conversation_id"], record["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def read_record(catalog: Path, cid: str, run_id: str) -> dict:
    path = record_path(catalog, cid, run_id)
    if not cid or not run_id or not path.is_file():
        raise isolation.SelfEditSnapshotError("This self-edit run was not found")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("conversation_id") != cid or record.get("run_id") != run_id:
        raise isolation.SelfEditSnapshotError("Self-edit run identity does not match")
    return record


def candidate_for(record: dict) -> isolation.SourceCandidate:
    root = Path(record["candidate_root"])
    baseline = json.loads(root.with_suffix(".baseline.json").read_text(encoding="utf-8"))
    if baseline["source_root"] != record["source_root"]:
        raise isolation.SelfEditSnapshotError("Self-edit source binding does not match")
    return isolation.SourceCandidate(Path(record["source_root"]), root, baseline["files"])


def prepare_run(source: Path, catalog: Path, conv: dict, run_id: str) -> dict:
    scope = validate_scope(source, conv.get("self_edit_scope"))
    candidates = isolation.self_edit_home() / "self-edit-candidates"
    with isolation.source_application_gate(source):
        candidate = isolation.prepare_candidate(source, candidates)
    record = {
        "conversation_id": conv["id"],
        "run_id": run_id,
        "source_root": str(source),
        "candidate_root": str(candidate.candidate_root),
        "scope": scope,
        "status": "running",
        "runtime_verified": False,
        "changed_files": [],
        "reason": "Working in a private copy of Thomas",
    }
    save_record(catalog, record)
    return record


def finish_run(catalog: Path, record: dict, *, successful: bool) -> dict:
    """Run trusted regression selection after the worker exits, never its verdict alone."""
    try:
        candidate = candidate_for(record)
        changed = isolation.candidate_delta_since(candidate.candidate_root, candidate.baseline)
        record["changed_files"] = changed
        validate_delta(candidate, record["scope"], changed)
        if not successful:
            raise isolation.SelfEditSnapshotError("The build stopped before a successful completion")
        commands, uncovered = isolation.plan_candidate_checks(candidate, changed)
        record.update(commands=[list(c) for c in commands], uncovered_files=uncovered)
        if not changed or uncovered or not commands:
            raise isolation.SelfEditSnapshotError("Every changed file needs an existing independent regression check")
        receipt = isolation.verify_candidate_checks(candidate, commands)
        record.update(receipt=asdict(receipt), evidence=json.loads(receipt.evidence_json))
        isolation.assert_check_receipt_current(candidate, receipt, commands)
        record.update(status="ready", reason="Independent checks passed; review before applying")
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        record.update(status="failed", reason=str(exc))
    save_record(catalog, record)
    return public_record(record)


def public_record(record: dict) -> dict:
    return {
        key: record[key]
        for key in (
            "conversation_id",
            "run_id",
            "status",
            "runtime_verified",
            "scope",
            "changed_files",
            "reason",
            "commands",
            "uncovered_files",
            "evidence",
            "python_changed",
        )
        if key in record
    }
