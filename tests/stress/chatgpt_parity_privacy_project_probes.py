"""Live privacy and project-isolation probes for the ChatGPT parity audit."""

from __future__ import annotations

import json
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

from chatgpt_parity_conversation_probe import _event_text, _privacy_chat, _privacy_http_json


def privacy_export_delete_temporary_probe(ctx: Any) -> tuple[bool, str]:
    """Prove export, deletion readback, and explicit no-retention chat behavior live."""
    token = str(time.time_ns())
    persistent_id = f"parity-privacy-export-{token}"
    temporary_id = f"parity-privacy-temporary-{token}"
    export_marker = f"PRIVACY-EXPORT-{token}"
    temporary_marker = f"PRIVACY-TEMP-{token}"
    persistent_headers: dict[str, str] = {}
    temporary_headers: dict[str, str] = {}
    persistent_events: list[dict[str, Any]] = []
    temporary_events: list[dict[str, Any]] = []
    export_status = delete_status = after_get_status = after_export_status = 0
    temporary_get_status = temporary_export_status = 0
    export_payload: Any = {}
    delete_payload: Any = {}
    try:
        persistent_headers, persistent_events = _privacy_chat(
            ctx,
            session_id=persistent_id,
            message=f"Reply exactly: {export_marker}",
            temporary=False,
            external_access=False,
            memory=False,
        )
        export_status, export_payload = _privacy_http_json(
            ctx,
            f"/api/v2/chat/session/{persistent_id}/export",
        )
        delete_status, delete_payload = _privacy_http_json(
            ctx,
            f"/api/v2/chat/session/{persistent_id}",
            method="DELETE",
        )
        after_get_status, _ = _privacy_http_json(ctx, f"/api/v2/chat/session/{persistent_id}")
        after_export_status, _ = _privacy_http_json(
            ctx,
            f"/api/v2/chat/session/{persistent_id}/export",
        )

        temporary_headers, temporary_events = _privacy_chat(
            ctx,
            session_id=temporary_id,
            message=f"Keep this only for this turn and reply exactly: {temporary_marker}",
            temporary=True,
            external_access=False,
            memory=False,
        )
        temporary_get_status, _ = _privacy_http_json(ctx, f"/api/v2/chat/session/{temporary_id}")
        temporary_export_status, _ = _privacy_http_json(
            ctx,
            f"/api/v2/chat/session/{temporary_id}/export",
        )
    finally:
        _privacy_http_json(ctx, f"/api/v2/chat/session/{persistent_id}", method="DELETE")
        _privacy_http_json(ctx, f"/api/v2/chat/session/{temporary_id}", method="DELETE")

    persistent_text = "".join(
        str(event.get("text") or "") for event in persistent_events if event.get("type") == "text"
    )
    temporary_text = "".join(str(event.get("text") or "") for event in temporary_events if event.get("type") == "text")
    persistent_privacy = next(
        (event for event in persistent_events if event.get("type") == "privacy_mode"),
        {},
    )
    temporary_privacy = next(
        (event for event in temporary_events if event.get("type") == "privacy_mode"),
        {},
    )
    export_json = json.dumps(export_payload, ensure_ascii=False)
    errors = [
        str(event.get("error") or "") for event in persistent_events + temporary_events if event.get("type") == "error"
    ]
    passed = bool(
        export_marker in persistent_text
        and persistent_headers.get("x-thomas-temporary") == "false"
        and persistent_headers.get("x-thomas-external-access") == "blocked"
        and persistent_privacy.get("retention") == "session"
        and persistent_privacy.get("external_access") == "blocked"
        and export_status == 200
        and export_payload.get("schema_version") == "thomas.chat.export.v1"
        and export_payload.get("session_id") == persistent_id
        and export_marker in export_json
        and delete_status == 200
        and delete_payload.get("deleted") is True
        and delete_payload.get("memory_purge", {}).get("completed") is True
        and not delete_payload.get("memory_purge", {}).get("error")
        and after_get_status == 404
        and after_export_status == 404
        and temporary_marker in temporary_text
        and temporary_headers.get("x-thomas-temporary") == "true"
        and temporary_headers.get("x-thomas-external-access") == "blocked"
        and temporary_privacy.get("retention") == "none"
        and temporary_privacy.get("memory") == "disabled"
        and temporary_privacy.get("external_access") == "blocked"
        and temporary_privacy.get("background_persistence") == "blocked"
        and temporary_get_status == 404
        and temporary_export_status == 404
        and not errors
    )
    actual = {
        "persistent_text": persistent_text,
        "persistent_headers": {
            "temporary": persistent_headers.get("x-thomas-temporary"),
            "external_access": persistent_headers.get("x-thomas-external-access"),
        },
        "persistent_privacy": persistent_privacy,
        "export_status": export_status,
        "export_schema": export_payload.get("schema_version") if isinstance(export_payload, dict) else None,
        "export_contains_marker": export_marker in export_json,
        "delete_status": delete_status,
        "delete_receipt": delete_payload,
        "after_delete_get_status": after_get_status,
        "after_delete_export_status": after_export_status,
        "temporary_text": temporary_text,
        "temporary_headers": {
            "temporary": temporary_headers.get("x-thomas-temporary"),
            "external_access": temporary_headers.get("x-thomas-external-access"),
        },
        "temporary_privacy": temporary_privacy,
        "temporary_get_status": temporary_get_status,
        "temporary_export_status": temporary_export_status,
        "errors": errors,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


def project_isolation_stale_share_probe(ctx: Any) -> tuple[bool, str]:
    """Prove project isolation, stale-file exclusion, path safety, share denial, and durable resume."""
    token = str(time.time_ns())
    marker_a = f"PROJECT-A-SECRET-{token}"
    marker_b = f"PROJECT-B-SECRET-{token}"
    stale_marker = f"PROJECT-STALE-FILE-{token}"
    session_a = f"parity-project-a-{token}"
    session_b = f"parity-project-b-{token}"
    session_resume = f"parity-project-resume-{token}"
    project_a = project_b = share_id = ""
    cross_attach_status = escape_status = stale_resume_status = share_denied_status = 0
    share_valid_status = revoke_status = after_revoke_status = 0
    resume_events: list[dict[str, Any]] = []
    project_b_resume: Any = {}
    stale_resume: Any = {}
    try:
        with tempfile.TemporaryDirectory(prefix="thomas-parity-project-isolation-") as temp_dir:
            root = Path(temp_dir)
            root_a = root / "a"
            root_b = root / "b"
            root_a.mkdir()
            root_b.mkdir()
            (root_a / "brief.md").write_text(f"Verified stale-file marker: {stale_marker}\n", encoding="utf-8")
            (root_b / "brief.md").write_text(f"Verified B marker: {marker_b}\n", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("OUTSIDE-PROJECT-SECRET", encoding="utf-8")
            _, imported_a = _privacy_http_json(
                ctx, "/api/local/projects/import", method="POST", body={"path": str(root_a), "name": "Project A"}
            )
            _, imported_b = _privacy_http_json(
                ctx, "/api/local/projects/import", method="POST", body={"path": str(root_b), "name": "Project B"}
            )
            project_a = str(imported_a.get("project", {}).get("id") or "")
            project_b = str(imported_b.get("project", {}).get("id") or "")
            _privacy_http_json(
                ctx,
                f"/api/local/projects/{project_a}/library",
                method="POST",
                body={"path": "brief.md", "title": "A brief"},
            )
            _privacy_chat(
                ctx,
                session_id=session_a,
                message=f"Keep {marker_a} inside Project A. Reply exactly: A-BOUND",
                temporary=False,
                external_access=False,
                memory=False,
                project_id=project_a,
            )
            _privacy_chat(
                ctx,
                session_id=session_b,
                message=f"Keep {marker_b} inside Project B. Reply exactly: B-BOUND",
                temporary=False,
                external_access=False,
                memory=False,
                project_id=project_b,
            )
            cross_attach_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/projects/{project_b}/chats",
                method="POST",
                body={"session_id": session_a},
            )
            escape_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/projects/{project_a}/library",
                method="POST",
                body={"path": "../outside.txt"},
            )
            _, project_b_resume = _privacy_http_json(ctx, f"/api/local/projects/{project_b}/resume")

            (root_a / "brief.md").write_text("Changed after it was pinned.\n", encoding="utf-8")
            stale_resume_status, stale_resume = _privacy_http_json(ctx, f"/api/local/projects/{project_a}/resume")
            _, resume_events = _privacy_chat(
                ctx,
                session_id=session_resume,
                message=(
                    "If a fresh bound project file contains a value beginning PROJECT-STALE-FILE-, repeat it. "
                    "Otherwise reply exactly: STALE-FILE-EXCLUDED."
                ),
                temporary=False,
                external_access=False,
                memory=False,
                project_id=project_a,
            )
            _, share_receipt = _privacy_http_json(
                ctx,
                f"/api/local/projects/{project_a}/shares",
                method="POST",
                body={"include_all_chats": True, "expires_in_seconds": 600},
            )
            share_id = str(share_receipt.get("share_id") or "")
            share_token = str(share_receipt.get("token") or "")
            share_denied_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/project-shares/{share_id}?token=forged",
            )
            share_valid_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/project-shares/{share_id}?token={urllib.parse.quote(share_token, safe='')}",
            )
            revoke_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/projects/{project_a}/shares/{share_id}",
                method="DELETE",
            )
            after_revoke_status, _ = _privacy_http_json(
                ctx,
                f"/api/local/project-shares/{share_id}?token={urllib.parse.quote(share_token, safe='')}",
            )
    finally:
        for sid in (session_a, session_b, session_resume):
            _privacy_http_json(ctx, f"/api/v2/chat/session/{sid}", method="DELETE")
        for pid in (project_a, project_b):
            if pid:
                _privacy_http_json(ctx, f"/api/local/projects/{pid}", method="DELETE")

    resume_text = _event_text(resume_events)
    resume_context = next((event for event in resume_events if event.get("type") == "project_context"), {})
    project_b_json = json.dumps(project_b_resume, ensure_ascii=False)
    passed = bool(
        cross_attach_status == 409
        and escape_status == 400
        and marker_a not in project_b_json
        and marker_b in project_b_json
        and stale_resume_status == 200
        and stale_resume.get("stale_library_count") == 1
        and "STALE-FILE-EXCLUDED" in resume_text
        and stale_marker not in resume_text
        and resume_context.get("stale_library_files_excluded") == 1
        and share_denied_status == 403
        and share_valid_status == 200
        and revoke_status == 200
        and after_revoke_status == 404
    )
    actual = {
        "cross_project_attach_status": cross_attach_status,
        "path_escape_status": escape_status,
        "project_b_contains_a_marker": marker_a in project_b_json,
        "project_b_contains_b_marker": marker_b in project_b_json,
        "stale_resume_status": stale_resume_status,
        "stale_library_count": stale_resume.get("stale_library_count") if isinstance(stale_resume, dict) else None,
        "resume_text": resume_text,
        "resume_context": resume_context,
        "share_denied_status": share_denied_status,
        "share_valid_status": share_valid_status,
        "revoke_status": revoke_status,
        "after_revoke_status": after_revoke_status,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


__all__ = ["privacy_export_delete_temporary_probe", "project_isolation_stale_share_probe"]
