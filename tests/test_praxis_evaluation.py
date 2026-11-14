"""Acceptance cannot be inferred from a builder saying the work is done."""

from thomas.server.praxis.evaluation import evaluate_acceptance

INSTRUCTIONS = "Build a bootable kernel and verify that the image exists."
CHECK = {
    "id": "image",
    "kind": "file_exists",
    "text": "Kernel image exists",
    "cites": "verify that the image exists",
}
RECEIPT = {
    "check_id": "image",
    "kind": "file_exists",
    "source": "verifier",
    "status": "pass",
    "evidence_ref": "checks/image.json",
}
CHILD = {
    "agent_id": "builder-1",
    "state": "completed",
    "report": {"text": "The image was produced and checked.", "evidence_refs": ["checks/image.json"]},
}


def settle(checks=None, receipts=None, children=None):
    return evaluate_acceptance(
        [CHECK] if checks is None else checks,
        [RECEIPT] if receipts is None else receipts,
        instructions=INSTRUCTIONS,
        child_rows=[CHILD] if children is None else children,
    )


def test_pass_requires_verifier_receipt_and_cited_child_report():
    verdict = settle()
    assert verdict["state"] == "completed"
    assert verdict["passed"] == verdict["total"] == 1
    assert verdict["acceptance"][0]["evidence_ref"] == "checks/image.json"


def test_done_event_and_builder_prose_without_verifier_evidence_are_unverified():
    verdict = settle(receipts=[])
    assert verdict["state"] == "completed_unverified"
    assert verdict["acceptance"][0]["status"] == "unverified"
    assert verdict["reports"][0]["status"] == "unverified"


def test_observed_failure_is_not_relabelled_as_infrastructure_or_success():
    verdict = settle(receipts=[{**RECEIPT, "status": "fail"}])
    assert verdict["state"] == "failed"
    assert verdict["acceptance"][0]["status"] == "fail"


def test_uncited_model_check_and_duplicate_receipt_never_pass():
    uncited = settle(checks=[{**CHECK, "cites": "a new requirement"}])
    duplicate = settle(receipts=[RECEIPT, RECEIPT])
    assert uncited["state"] == duplicate["state"] == "completed_unverified"
    assert "uncited_check" in uncited["acceptance"][0]["reasons"]
    assert "ambiguous_verifier_receipts" in duplicate["acceptance"][0]["reasons"]


def test_child_report_must_cite_observed_artifact():
    invented = {**CHILD, "report": {"text": "All good", "evidence_refs": ["made/up.txt"]}}
    verdict = settle(children=[invented])
    assert verdict["state"] == "completed_unverified"
    assert "unobserved_report_evidence" in verdict["reports"][0]["reasons"]


def test_incomplete_child_and_empty_acceptance_cannot_be_called_complete():
    stopped = settle(children=[{**CHILD, "state": "stopped"}])
    empty = settle(checks=[])
    assert stopped["state"] == empty["state"] == "completed_unverified"


def test_extra_receipts_are_reported_without_changing_declared_checks():
    verdict = settle(receipts=[RECEIPT, {**RECEIPT, "check_id": "unasked"}])
    assert verdict["state"] == "completed"
    assert verdict["unmatched_receipt_ids"] == ["unasked"]
