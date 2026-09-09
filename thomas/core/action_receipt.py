"""Canonical evidence receipt for actions performed or delegated by Thomas."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

_SUCCEEDED_STATES = {"completed", "verified", "done"}
_FAILED_STATES = {"failed", "abandoned", "cancelled", "canceled", "dead"}


@dataclass(frozen=True)
class ActionReceipt:
    """One stable result contract across inline actions and delegated tasks."""

    action_id: str
    action: str
    ok: bool | None
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    reversible: bool = False
    approval: str = "not_required"
    session_id: str = ""
    kind: str = "inline"
    state: str = ""
    task_id: str = ""
    execution_id: str = ""
    interruptible: bool = False

    def to_dict(self) -> dict[str, Any]:
        state = str(self.state or ("completed" if self.ok else "failed" if self.ok is False else "running"))
        return {
            "receipt_id": self.action_id,
            # Compatibility while clients migrate to receipt_id.
            "action_id": self.action_id,
            "session_id": self.session_id,
            "kind": self.kind,
            "action": self.action,
            "state": state,
            "ok": self.ok,
            "evidence": dict(self.evidence),
            "error": self.error,
            "reversible": self.reversible,
            "interruptible": self.interruptible,
            "approval": self.approval,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
        }

    def to_signed_dict(self, signing_key: str | bytes, *, key_id: str = "local") -> dict[str, Any]:
        """Return a tamper-evident receipt for transport or durable storage."""
        return sign_action_receipt(self.to_dict(), signing_key, key_id=key_id)


def _receipt_key_bytes(signing_key: str | bytes) -> bytes:
    key = signing_key if isinstance(signing_key, bytes) else str(signing_key or "").encode("utf-8")
    if len(key) < 16:
        raise ValueError("Receipt signing keys must be at least 16 bytes.")
    return key


def _canonical_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    payload = {str(key): value for key, value in receipt.items() if str(key) != "receipt_signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sign_action_receipt(
    receipt: Mapping[str, Any],
    signing_key: str | bytes,
    *,
    key_id: str = "local",
) -> dict[str, Any]:
    """Attach an HMAC-SHA256 signature covering every receipt field."""
    payload = dict(receipt)
    payload["receipt_signature_alg"] = "hmac-sha256"
    payload["receipt_key_id"] = str(key_id or "local")
    payload["receipt_signature"] = hmac.new(
        _receipt_key_bytes(signing_key),
        _canonical_receipt_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return payload


def verify_action_receipt(receipt: Mapping[str, Any] | None, signing_key: str | bytes) -> bool:
    """Verify receipt identity/state invariants and its tamper-evident signature."""
    if not isinstance(receipt, Mapping):
        return False
    payload = dict(receipt)
    receipt_id = str(payload.get("receipt_id") or "").strip()
    action_id = str(payload.get("action_id") or "").strip()
    action = str(payload.get("action") or "").strip()
    state = str(payload.get("state") or "").strip().lower()
    ok = payload.get("ok")
    signature = str(payload.get("receipt_signature") or "").strip().lower()
    if not receipt_id or receipt_id != action_id or not action:
        return False
    if state in _SUCCEEDED_STATES and ok is not True:
        return False
    if state in _FAILED_STATES and ok is not False:
        return False
    if payload.get("receipt_signature_alg") != "hmac-sha256" or len(signature) != 64:
        return False
    try:
        expected = hmac.new(
            _receipt_key_bytes(signing_key),
            _canonical_receipt_bytes(payload),
            hashlib.sha256,
        ).hexdigest()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(signature, expected)


def delegated_action_receipt(
    record: Mapping[str, Any] | None,
    *,
    session_id: str = "",
) -> ActionReceipt:
    """Normalize a task-ledger record into the same receipt used by inline work."""

    row = dict(record or {})
    execution_id = str(row.get("execution_id") or "").strip()
    task_id = str(row.get("task_id") or "").strip()
    state = str(row.get("state") or "requested").strip().lower()
    proof = dict(row.get("proof") or {}) if isinstance(row.get("proof"), Mapping) else {}
    proof_status = str(row.get("proof_status") or proof.get("status") or "missing").strip().lower()
    terminal = state in (_SUCCEEDED_STATES | _FAILED_STATES)

    if state in _SUCCEEDED_STATES:
        ok: bool | None = proof_status in {"verified", "attached"}
    elif state in _FAILED_STATES:
        ok = False
    else:
        ok = None

    evidence: dict[str, Any] = {
        "summary": str(row.get("summary") or "").strip(),
        "last_progress": str(row.get("last_progress") or row.get("progress_summary") or "").strip(),
        "proof_status": proof_status,
        "proof": proof,
    }
    pending_instructions = list(row.get("pending_instructions") or [])
    if pending_instructions:
        evidence["pending_instruction_count"] = len(pending_instructions)
    if bool(row.get("cancel_requested")):
        evidence["cancel_requested"] = True
    artifact = {
        "url": str(row.get("artifact_url") or "").strip(),
        "name": str(row.get("artifact_name") or "").strip(),
        "kind": str(row.get("artifact_kind") or "").strip(),
    }
    if any(artifact.values()):
        evidence["artifact"] = artifact

    error = ""
    if ok is False:
        error = str(row.get("blocker") or evidence["last_progress"] or "Delegated action failed.").strip()

    return ActionReceipt(
        action_id=execution_id or task_id,
        session_id=str(session_id or row.get("session_id") or row.get("conversation_id") or "").strip(),
        kind="delegated",
        action=str(row.get("execution_intent") or "task.execute").strip() or "task.execute",
        state=state,
        ok=ok,
        evidence=evidence,
        error=error,
        reversible=False,
        interruptible=not terminal,
        approval="task_manager_policy",
        task_id=task_id,
        execution_id=execution_id,
    )


__all__ = [
    "ActionReceipt",
    "delegated_action_receipt",
    "sign_action_receipt",
    "verify_action_receipt",
]
