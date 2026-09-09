"""Apply a reviewed candidate only with a readable, run-scoped Undo record."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from . import forge_code_redesign_undo as undo
from . import forge_code_self_edit as isolation


def apply_with_undo(
    candidate,
    receipt,
    commands,
    journal: Path,
    approved_paths: tuple[str, ...],
    *,
    catalog_root: Path,
    conversation_id: str,
    run_id: str,
) -> dict:
    """Bridge verified application to existing Undo; policy approval is external."""
    if not conversation_id or not run_id:
        raise isolation.SelfEditSnapshotError("Application needs an owning conversation and run")
    context = {"catalog_root": str(catalog_root.resolve()), "conversation_id": conversation_id, "run_id": run_id}
    manifest = undo._manifest_path(catalog_root, conversation_id, run_id)
    with isolation.source_application_gate(candidate.source_root):
        record = isolation._validated_application(candidate, receipt, commands, journal, approved_paths)
        if record.get("undo_context") not in (None, context):
            raise isolation.SelfEditSnapshotError("Application belongs to a different Undo run")
        if record.get("undo_context") is None and manifest.exists():
            raise isolation.SelfEditSnapshotError("An Undo record already exists for this run")
        preimages = {}
        staged_manifest = False
        application_started = False
        total = 0
        for relative, entry in record["files"].items():
            before = entry["before"]
            if before["kind"] == "missing":
                preimages[relative] = {"kind": "missing", "sha256": "missing"}
            else:
                total += len(base64.b64decode(before["data"], validate=True))
                preimages[relative] = {
                    "kind": "file",
                    "data": before["data"],
                    "mode": before["mode"],
                    "sha256": before["fingerprint"].rsplit(":", 1)[0],
                }
        if total > undo._MAX_PREIMAGE_BYTES * 2:
            raise isolation.SelfEditSnapshotError("Application exceeds the Undo pre-image limit")
        # The durable conversation-owned pre-image must exist before the first
        # live source write. The application journal is recovery evidence, but
        # it is not the Redesign card's Undo record and may live in staging.
        try:
            undo.stage_run_preimages(catalog_root, conversation_id, run_id, preimages)
            staged_manifest = True
            record.update(undo_context=context, undo_ready=False, undo_manifest=str(manifest))
            isolation._persist_application(journal, record)
            application_started = True
            changed = isolation._apply_source_application_locked(candidate, receipt, commands, journal, approved_paths)
            result = undo.finalize_staged_preimages(
                candidate.source_root, catalog_root, conversation_id, run_id, changed
            )
            if not result.get("available"):
                raise isolation.SelfEditSnapshotError(result.get("reason") or "Undo could not be prepared")
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            if saved.get("run_id") != run_id or set(saved.get("files", {})) != set(changed) or saved.get("undone"):
                raise isolation.SelfEditSnapshotError("Undo record does not match this application")
            for relative in changed:
                entry = saved["files"][relative]
                if (
                    isolation._current_fingerprint(isolation._source_path(candidate.source_root, relative))
                    != record["files"][relative]["after"]["fingerprint"]
                ):
                    raise isolation.SelfEditSnapshotError("Source changed while its Undo record was prepared")
                if entry.get("before") != preimages[relative] or not undo._same_state(
                    undo._file_state(candidate.source_root / relative), entry.get("after") or {}
                ):
                    raise isolation.SelfEditSnapshotError("Undo pre-images or output readback do not match")
            record = json.loads(journal.read_text(encoding="utf-8"))
            record.update(undo_ready=True, undo_manifest=str(manifest))
            isolation._persist_application(journal, record)
        except (OSError, RuntimeError, ValueError) as exc:
            if application_started:
                isolation._rollback_source_application_locked(candidate, receipt, commands, journal, approved_paths)
            if staged_manifest:
                undo.discard_run_preimages(catalog_root, conversation_id, run_id)
            detail = "source application was restored" if application_started else "source application did not start"
            raise isolation.SelfEditSnapshotError(f"Undo preparation failed; {detail}") from exc
        return {"applied": True, "changed_files": changed, "undo": result, "application_journal": str(journal)}
