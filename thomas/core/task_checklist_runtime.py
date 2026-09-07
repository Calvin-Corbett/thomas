"""Attach a task's completion checklist to its execution record and hold
completion until the checklist is met.

Recovered from the June 2026 task-checklists work (PR #35). Lives beside
``task_bot_runtime`` rather than inside it so the record store stays under the
size limit; ``task_bot_runtime`` re-exports the public names.

Flag-gated by ``THOMAS_TASK_CHECKLISTS`` via ``task_checklist.checklists_enabled``
(off by default → today's behaviour). Evidence is real observed reads and the
produced text - never words in the reply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core import acceptance_contract as ac
from thomas.core import task_checklist

__all__ = [
    "attach_checklist_at_creation",
    "attach_contract",
    "set_task_type",
    "record_checklist_evidence",
    "hold_if_unmet",
    "has_satisfied_checklist",
]


def attach_contract(
    execution_id: str,
    prompt_text: str,
    workspace: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> str:
    """Derive the acceptance contract for a delegated task before the worker starts,
    store it on the record, and return the block to put in the worker's brief."""

    from thomas.core import task_bot_runtime as rt

    if not ac.contract_enabled():
        return ""
    payload = rt.get_execution(execution_id, repo_root)
    if payload is None:
        return ""
    items = ac.build_contract(prompt_text, workspace)
    payload["acceptance_contract"] = ac.items_to_dicts(items)
    payload["workspace"] = str(workspace)
    payload["contract_started_at"] = ac.now()
    rt._write_json(rt.execution_path(execution_id, repo_root), payload)
    return ac.contract_prompt_block(items)


def _evaluate_stored_contract(payload: dict[str, Any], *, output_text: str) -> list[ac.ContractItem]:
    rows = payload.get("acceptance_contract")
    workspace = str(payload.get("workspace") or "")
    if not isinstance(rows, list) or not rows or not workspace or not ac.contract_enabled():
        return []
    evaluated = ac.evaluate_contract(
        ac.items_from_dicts(rows),
        workspace=workspace,
        response_text=output_text,
        started_at=float(payload.get("contract_started_at") or 0.0) or None,
        run_commands=True,
    )
    payload["acceptance_contract"] = ac.items_to_dicts(evaluated)
    return evaluated


def _unmet_contract_lines(payload: dict[str, Any]) -> list[str]:
    if not ac.contract_enabled():
        return []
    rows = payload.get("acceptance_contract")
    items = ac.items_from_dicts(rows if isinstance(rows, list) else [])
    return [f"{it.item_id}: {it.detail or it.description}" for it in items if it.checked and not it.satisfied]


def attach_checklist_at_creation(payload: dict[str, Any], task_type: str) -> None:
    """The MODEL labels a task's type; the per-type checklist is fixed at creation.
    A blank label means "not labelled yet" (no checklist), distinct from a garbled
    label, which ``coerce`` fails closed to the strictest type."""

    labelled = str(task_type or "").strip()
    payload["task_type"] = labelled
    payload.setdefault("checklist", [])
    if labelled and task_checklist.checklists_enabled():
        payload["checklist"] = task_checklist.checklist_to_dicts(task_checklist.build_checklist(labelled))


def set_task_type(
    execution_id: str,
    task_type: str,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Record the model-declared task type on a live execution and attach its
    checklist once (an existing checklist is left untouched). No-op unless the flag
    is on and the label is non-blank."""

    from thomas.core import task_bot_runtime as rt

    payload = rt.get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    labelled = str(task_type or "").strip()
    payload["task_type"] = labelled
    rows = payload.get("checklist")
    if labelled and task_checklist.checklists_enabled() and (not isinstance(rows, list) or not rows):
        payload["checklist"] = task_checklist.checklist_to_dicts(task_checklist.build_checklist(labelled))
    rt._write_json(rt.execution_path(execution_id, repo_root), payload)
    rt._write_summary(repo_root)
    return payload


def _evaluate_stored_checklist(
    payload: dict[str, Any], *, read_paths: list[str] | None, output_text: str
) -> list[task_checklist.ChecklistItem]:
    rows = payload.get("checklist")
    if not isinstance(rows, list) or not rows:
        return []
    evaluated = task_checklist.evaluate_checklist(
        task_checklist.checklist_from_dicts(rows),
        read_paths=read_paths,
        output_text=output_text,
        scope=payload.get("scope") or (),
    )
    payload["checklist"] = task_checklist.checklist_to_dicts(evaluated)
    return evaluated


def record_checklist_evidence(
    execution_id: str,
    *,
    read_paths: list[str] | None = None,
    output_text: str = "",
    actor: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Record REAL read evidence + produced output against the checklist and persist
    the re-evaluated result. No-op when the flag is off or there is no checklist."""

    from thomas.core import task_bot_runtime as rt

    payload = rt.get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    changed = bool(
        task_checklist.checklists_enabled()
        and _evaluate_stored_checklist(payload, read_paths=read_paths, output_text=output_text)
    )
    changed = bool(_evaluate_stored_contract(payload, output_text=output_text)) or changed
    if not changed:
        return payload
    rt._write_json(rt.execution_path(execution_id, repo_root), payload)
    rt._write_summary(repo_root)
    return payload


def hold_if_unmet(
    execution_id: str,
    payload: dict[str, Any],
    *,
    read_paths: list[str] | None,
    output_text: str,
    summary: str,
    actor: str,
    repo_root: str | Path | None,
) -> dict[str, Any] | None:
    """At completion: if the record carries a checklist and it is unmet, park the
    task in ``awaiting_proof`` with a blocker naming what is missing and return that
    record. Return ``None`` when completion may proceed. Never raises."""

    from thomas.core import task_bot_runtime as rt

    unmet_lines: list[str] = []
    rows = payload.get("checklist")
    if task_checklist.checklists_enabled() and isinstance(rows, list) and rows:
        if read_paths is not None or output_text:
            evaluated = _evaluate_stored_checklist(payload, read_paths=read_paths, output_text=output_text)
            rt._write_json(rt.execution_path(execution_id, repo_root), payload)
        else:
            evaluated = task_checklist.checklist_from_dicts(rows)
        unmet_lines += [f"{it.item_id}: {it.detail or it.description}" for it in task_checklist.unmet_items(evaluated)]
    unmet_lines += _unmet_contract_lines(payload)  # evaluated when the worker's evidence was recorded
    if not unmet_lines:
        return None
    blocker = "Checklist not met - " + "; ".join(unmet_lines)
    return rt.update_execution(
        execution_id,
        state="awaiting_proof",
        proof_status="pending",
        progress_summary=summary or str(payload.get("progress_summary") or ""),
        blocker=blocker,
        heartbeat=True,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


def has_satisfied_checklist(payload: dict[str, Any]) -> bool:
    """True when the record carries a checklist whose stored evaluation is met."""

    if not task_checklist.checklists_enabled():
        return False
    rows = payload.get("checklist")
    if not isinstance(rows, list) or not rows:
        return False
    return task_checklist.checklist_satisfied(task_checklist.checklist_from_dicts(rows))
