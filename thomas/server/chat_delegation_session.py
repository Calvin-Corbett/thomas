from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from thomas.core import task_bot_runtime
from thomas.core.action_receipt import delegated_action_receipt
from thomas.server.chat_delegation_worker_config import TASK_MANAGER_BACKEND

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

_TERMINAL_TASK_STATES = {"completed", "verified", "failed", "abandoned", "cancelled", "canceled", "done"}


def _resolve_repo_root(repo_root: str | Path | None = None) -> Path:
    return (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()


def _normalize_record(payload: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(payload or {})
    summary = str(row.get("summary") or row.get("progress_summary") or "").strip()
    progress = str(row.get("progress_summary") or summary).strip()
    bot_id = str(row.get("bot_id") or "").strip()
    bot_name = str(row.get("bot_name") or "").strip() or (bot_id[:1].upper() + bot_id[1:] if bot_id else "")
    execution_id = str(row.get("execution_id") or "")
    runtime_profile = row.get("runtime_profile") if isinstance(row.get("runtime_profile"), dict) else {}
    proof = dict(row.get("proof") or {}) if isinstance(row.get("proof"), dict) else {}
    proof_artifacts = proof.get("artifacts") if isinstance(proof.get("artifacts"), list) else []
    proof_status = str(row.get("proof_status") or proof.get("status") or "missing").strip().lower()
    state = str(row.get("state") or "requested").strip().lower()
    reviewed_success = bool(
        state in {"completed", "verified", "done", "succeeded", "passed"}
        and proof_status in {"verified", "attached"}
        and proof_artifacts
    )
    # If the worker produced a deliverable in its isolated workspace, expose a one-click
    # URL + its name and KIND so the chat can present it natively.
    artifact_url = ""
    artifact_name = ""
    artifact_kind = ""
    artifacts: list[dict[str, str]] = []
    try:
        from thomas.server.routes.deliverable_aiohttp import deliverable_entry, deliverable_kind, deliverable_url

        if reviewed_success:
            artifact_url = deliverable_url(execution_id)
            entry = deliverable_entry(execution_id) or ""
            artifact_name = entry.rsplit("/", 1)[-1]
            artifact_kind = deliverable_kind(execution_id)
    except (ImportError, RuntimeError, OSError, ValueError, TypeError, AttributeError):
        artifact_url = artifact_name = artifact_kind = ""
    for index, raw_artifact in enumerate(proof_artifacts if reviewed_success else []):
        if not isinstance(raw_artifact, dict):
            continue
        path = str(raw_artifact.get("path") or raw_artifact.get("file") or "").strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            continue
        suffix = Path(path).suffix.lower()
        kind = (
            "web"
            if suffix in {".html", ".htm"}
            else "pdf"
            if suffix == ".pdf"
            else "image"
            if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
            else "text"
            if suffix in {".md", ".txt", ".csv", ".json", ".log", ".rst"}
            else "file"
        )
        artifacts.append(
            {
                "id": f"{execution_id}:{index}:{path}",
                "path": path,
                "name": Path(path).name,
                "kind": str(raw_artifact.get("kind") or kind),
                "url": f"/deliverable/{quote(execution_id, safe='')}/{quote(path, safe='/')}",
            }
        )
    if not artifacts and (artifact_url or artifact_name):
        artifacts.append(
            {
                "id": f"{execution_id}:primary",
                "path": artifact_name,
                "name": artifact_name or "result",
                "kind": artifact_kind,
                "url": artifact_url,
            }
        )
    # Live canvas worker: surface the streaming HTML so the frontend Canvas renders it
    # as it draws (and knows this delegation is a canvas task to auto-open for).
    canvas_html = ""
    canvas_status = ""
    canvas_mode = ""
    canvas_shell = ""
    canvas_elements: list[dict[str, Any]] = []
    canvas_review_status = ""
    canvas_review_issues: list[str] = []
    canvas_review_evidence: dict[str, Any] = {}
    is_canvas = False
    try:
        from thomas.server.chat_delegation_canvas import canvas_get

        _cv = canvas_get(execution_id)
        if _cv is not None:
            is_canvas = True
            canvas_html = str(_cv.get("html") or "")
            canvas_status = str(_cv.get("status") or "")
            canvas_mode = str(_cv.get("mode") or "")
            _shell = _cv.get("shell") if isinstance(_cv.get("shell"), dict) else {}
            canvas_shell = str(_shell.get("html") or "")
            canvas_elements = list(_cv.get("elements") or [])
            canvas_review_status = str(_cv.get("review_status") or "")
            canvas_review_issues = [str(issue) for issue in (_cv.get("review_issues") or [])]
            canvas_review_evidence = (
                dict(_cv.get("review_evidence")) if isinstance(_cv.get("review_evidence"), dict) else {}
            )
            reviewed_canvas = reviewed_success and canvas_review_status.lower() == "passed"
            partial_construction = bool(
                canvas_status.lower() == "streaming"
                and canvas_mode == "construct"
                and canvas_review_status.lower() in {"", "pending"}
            )
            if not reviewed_canvas:
                canvas_html = ""
                if not partial_construction:
                    canvas_shell = ""
                    canvas_elements = []
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
        is_canvas = False
    normalized = {
        "execution_id": execution_id,
        "is_canvas": is_canvas,
        "canvas_html": canvas_html,
        "canvas_status": canvas_status,
        "canvas_mode": canvas_mode,
        "canvas_shell": canvas_shell,
        "canvas_elements": canvas_elements,
        "canvas_review_status": canvas_review_status,
        "canvas_review_issues": canvas_review_issues,
        "canvas_review_evidence": canvas_review_evidence,
        "task_id": str(row.get("task_id") or ""),
        "session_id": str(row.get("conversation_id") or row.get("thread_id") or ""),
        "execution_intent": str(row.get("execution_intent") or "task.execute"),
        "visibility": str(row.get("visibility") or "background"),
        "backend_type": str(row.get("backend_type") or TASK_MANAGER_BACKEND),
        "state": str(row.get("state") or "requested"),
        "summary": summary,
        "last_progress": progress,
        "artifact_url": artifact_url,
        "artifact_name": artifact_name,
        "artifact_kind": artifact_kind,
        "artifacts": artifacts,
        "bot_id": bot_id,
        "bot_name": bot_name,
        "runtime_profile": dict(runtime_profile),
        "proof_status": str(row.get("proof_status") or "missing"),
        "proof": proof,
        "blocker": str(row.get("blocker") or ""),
        "pending_instructions": list(row.get("pending_instructions") or []),
        "cancel_requested": bool(row.get("cancel_requested")),
        "reported_to_chat_at": str(row.get("reported_to_chat_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }
    normalized["receipt"] = delegated_action_receipt(normalized).to_dict()
    return normalized


def _execution_is_terminal(execution_id: str, repo_root: Path) -> bool:
    try:
        record = task_bot_runtime.get_execution(execution_id, repo_root)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError):
        log.debug("failed to inspect worker execution %s", execution_id, exc_info=True)
        return False
    return str((record or {}).get("state") or "").strip().lower() in _TERMINAL_TASK_STATES


def _heartbeat_age_s(record: dict[str, Any] | None) -> float | None:
    raw = str((record or {}).get("last_heartbeat_at") or (record or {}).get("updated_at") or "").strip()
    if not raw:
        return None
    try:
        stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamped.astimezone(timezone.utc)).total_seconds())


def _worker_has_started_progress(record: dict[str, Any] | None) -> bool:
    progress = str((record or {}).get("progress_summary") or "").strip()
    return bool(progress and progress != "Provider-native worker is running.")


def session_active_delegations(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = _resolve_repo_root(repo_root)
    rows = task_bot_runtime.list_executions(root, refresh=True)
    session_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("conversation_id") or "") != str(session_id or ""):
            continue
        execution_id = str(row.get("execution_id") or "")
        full = task_bot_runtime.get_execution(execution_id, root)
        session_rows.append(_normalize_record(full if isinstance(full, dict) else row))
    session_rows.sort(key=lambda item: (item.get("updated_at", ""), item.get("execution_id", "")), reverse=True)
    return session_rows


def build_active_task_digest(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
    limit: int = 3,
) -> str:
    rows = session_active_delegations(session_id, repo_root=repo_root)
    if not rows:
        return ""
    lines = ["Background work in this chat: to change or stop a RUNNING one, call update_task with its [task <ref>]:"]
    for row in rows[: max(1, int(limit or 1))]:
        bot = str(row.get("bot_id") or "worker").strip() or "worker"
        state = str(row.get("state") or "requested").replace("_", " ")
        backend = str(row.get("backend_type") or TASK_MANAGER_BACKEND).replace("_", " ")
        ref = str(row.get("execution_id") or "").strip()
        # Lead with WHAT the task is (its subject) so the model can match the user's
        # reference ("cancel the jazz report") to the right task. The subject lives in
        # `summary` (the task request); `last_progress` is only a status line and must
        # NOT replace it — burying the subject left the model unable to tell which task
        # the user meant. (chat sweep, 2026-06-27)
        subject = str(row.get("summary") or row.get("title") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        if subject and progress and progress.lower() not in subject.lower():
            detail = f"{subject} (status: {progress})"
        else:
            detail = subject or progress or "starting up"
        lines.append(f"- [task {ref}] {bot} [{state} via {backend}]: {detail}")
    return "\n".join(lines)


def resolve_active_task_ref(
    session_id: str,
    task_ref: str,
    *,
    repo_root: str | Path | None = None,
) -> str | None:
    """Map a model-supplied task ref to a live execution_id for this session.

    Prefers a RUNNING (non-terminal) task so an update lands on work still in
    flight. Returns None when nothing plausibly matches."""
    ref = str(task_ref or "").strip().lower().replace("[", "").replace("]", "")
    for token in ("task", "ref", "#", ":"):
        ref = ref.replace(token, "")
    ref = ref.strip()
    if not ref:
        return None
    rows = session_active_delegations(session_id, repo_root=repo_root)
    matches: list[tuple[str, bool]] = []
    for row in rows:
        eid = str(row.get("execution_id") or "").lower()
        if not eid:
            continue
        terminal = str(row.get("state") or "").lower() in _TERMINAL_TASK_STATES
        if eid == ref or eid.endswith(ref) or ref.endswith(eid) or (len(ref) >= 4 and ref in eid):
            matches.append((str(row.get("execution_id") or ""), terminal))
    for eid, terminal in matches:
        if not terminal:
            return eid
    if matches:
        return matches[0][0]
    # The model often references a task by a loose ref the opaque exec-id doesn't
    # contain. These are PLAUSIBLE interpretations of what it copied from the digest,
    # not blind guesses (an unrelated ref still resolves to None):
    #   (a) a pure ordinal ('[task 1]' -> '1') maps to the Nth task in digest order;
    #   (b) otherwise the ref's words are matched against each task's subject.
    # (chat sweep, 2026-06-27)
    digits = "".join(ch for ch in ref if ch.isdigit())
    if digits and digits == ref and 1 <= int(digits) <= len(rows):
        return str(rows[int(digits) - 1].get("execution_id") or "") or None
    ref_words = [w for w in ref.replace("-", " ").replace("_", " ").split() if len(w) >= 3]
    if ref_words:
        for r in rows:
            subject = str(r.get("summary") or r.get("title") or "").lower()
            if subject and any(w in subject for w in ref_words):
                return str(r.get("execution_id") or "") or None
    return None


def apply_task_update(
    session_id: str,
    task_ref: str,
    update: str = "",
    *,
    cancel: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Route a model-decided follow-up to the RIGHT running task."""
    eid = resolve_active_task_ref(session_id, task_ref, repo_root=repo_root)
    if not eid:
        return {"ok": False, "error": f"No running task matches reference '{task_ref}'."}
    root = _resolve_repo_root(repo_root)
    try:
        if cancel:
            record = task_bot_runtime.request_cancel(eid, actor="user", repo_root=root)
            normalized = _normalize_record(record)
            return {
                "ok": True,
                "execution_id": eid,
                "action": "cancel",
                "receipt": normalized["receipt"],
            }
        text = str(update or "").strip()
        if not text:
            return {"ok": False, "error": "No update instruction was provided."}
        record = task_bot_runtime.steer_execution(eid, text, actor="user", repo_root=root)
        normalized = _normalize_record(record)
        return {
            "ok": True,
            "execution_id": eid,
            "action": "steer",
            "receipt": normalized["receipt"],
        }
    except ValueError as exc:
        return {"ok": False, "execution_id": eid, "error": str(exc)}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}
