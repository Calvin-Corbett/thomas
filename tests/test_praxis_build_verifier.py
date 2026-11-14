"""Post-run verifier reads actual changed project files, never builder claims."""

from thomas.server.praxis.build_verifier import verify_build_checks
from thomas.server.praxis.evaluation import evaluate_acceptance


def test_independent_file_content_check_produces_settleable_receipt(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Thomas OS</h1>", encoding="utf-8")
    checks = [
        {
            "id": "heading",
            "kind": "file_contains",
            "path": "index.html",
            "needle": "Thomas OS",
            "text": "show Thomas OS",
            "cites": "show Thomas OS",
        }
    ]
    receipts = verify_build_checks(tmp_path, acceptance=checks, changed_files=["index.html"])
    assert receipts == [
        {
            "check_id": "heading",
            "kind": "file_contains",
            "source": "verifier",
            "status": "pass",
            "evidence_ref": "index.html",
            "covered_files": ["index.html"],
        }
    ]
    verdict = evaluate_acceptance(checks, receipts, instructions="show Thomas OS", require_child_reports=False)
    assert verdict["state"] == "completed"


def test_unsupported_and_unrelated_checks_never_get_receipts(tmp_path):
    (tmp_path / "other.txt").write_text("looks good", encoding="utf-8")
    checks = [
        {"id": "boot", "kind": "project_test_command", "command": "make boot"},
        {"id": "old", "kind": "file_exists", "path": "other.txt"},
        {"id": "escape", "kind": "file_exists", "path": "../outside.txt"},
    ]
    assert verify_build_checks(tmp_path, acceptance=checks, changed_files=["new.txt"]) == []


def test_failed_content_check_is_a_real_failure_not_a_pass(tmp_path):
    (tmp_path / "kernel.c").write_text("void boot(void) {}", encoding="utf-8")
    checks = [
        {
            "id": "entry",
            "kind": "file_contains",
            "path": "kernel.c",
            "needle": "int main",
            "text": "entry exists",
            "cites": "entry exists",
        }
    ]
    receipts = verify_build_checks(tmp_path, acceptance=checks, changed_files=["kernel.c"])
    assert receipts[0]["status"] == "fail"
    assert (
        evaluate_acceptance(checks, receipts, instructions="entry exists", require_child_reports=False)["state"]
        == "failed"
    )
