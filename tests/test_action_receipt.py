from __future__ import annotations

from thomas.core.action_receipt import ActionReceipt, delegated_action_receipt, verify_action_receipt


def test_inline_receipt_keeps_compatibility_and_canonical_identity() -> None:
    receipt = ActionReceipt(
        action_id="inline-1",
        session_id="session-1",
        action="preferences.get",
        ok=True,
        evidence={"observed": {"theme": "dark"}},
    ).to_dict()

    assert receipt["receipt_id"] == "inline-1"
    assert receipt["action_id"] == "inline-1"
    assert receipt["session_id"] == "session-1"
    assert receipt["kind"] == "inline"
    assert receipt["state"] == "completed"


def test_delegated_receipt_requires_proof_for_success() -> None:
    verified = delegated_action_receipt(
        {
            "execution_id": "exec-1",
            "task_id": "task-1",
            "session_id": "session-1",
            "state": "completed",
            "summary": "Build the artifact",
            "last_progress": "Artifact created.",
            "proof_status": "verified",
            "proof": {"status": "verified", "summary": "Verified artifact.", "artifacts": [{"path": "x"}]},
        }
    ).to_dict()
    unproved = delegated_action_receipt(
        {
            "execution_id": "exec-2",
            "session_id": "session-1",
            "state": "completed",
            "proof_status": "missing",
        }
    ).to_dict()

    assert verified["kind"] == "delegated"
    assert verified["ok"] is True
    assert verified["interruptible"] is False
    assert verified["evidence"]["proof"]["summary"] == "Verified artifact."
    assert unproved["ok"] is False


def test_running_and_failed_delegations_have_honest_states() -> None:
    running = delegated_action_receipt({"execution_id": "exec-run", "state": "executing"}).to_dict()
    failed = delegated_action_receipt(
        {"execution_id": "exec-fail", "state": "failed", "blocker": "verification failed"}
    ).to_dict()

    assert running["ok"] is None
    assert running["interruptible"] is True
    assert failed["ok"] is False
    assert failed["error"] == "verification failed"


def test_signed_receipt_rejects_tampering_and_unsigned_claims() -> None:
    key = "parity-receipt-signing-key-32-bytes"
    receipt = ActionReceipt(
        action_id="provider-send-1",
        session_id="session-1",
        action="email.send",
        ok=True,
        evidence={"provider_result": {"id": "provider-send-1", "thread_id": "thread-1"}},
        approval="policy_checked",
    ).to_signed_dict(key, key_id="test-key")

    forged = {**receipt, "evidence": {"provider_result": {"id": "forged-send"}}}
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_signature"}

    assert verify_action_receipt(receipt, key) is True
    assert verify_action_receipt(forged, key) is False
    assert verify_action_receipt(unsigned, key) is False
    assert verify_action_receipt(receipt, "different-signing-key-32-bytes!!") is False
