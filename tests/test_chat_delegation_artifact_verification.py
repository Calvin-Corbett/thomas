from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from thomas.server import chat_delegation_runner
from thomas.server.chat_delegation_artifact_verification import (
    _hidden_completion_review_passes,
    _reconcile_missing_marker_literals,
    _reconcile_requested_artifact_from_evidence,
    _requested_artifact_issues,
    _sanitize_terminal_summary,
)
from thomas.server.chat_delegation_deliverable import _WorkerRetry
from thomas.server.chat_delegation_runner import _record_tool_outcome, _should_finalize_exact_artifact_tool_result
from thomas.server.chat_delegation_worker_config import (
    _WORKER_FIRST_EVENT_TIMEOUT_S,
    _WORKER_IDLE_EVENT_TIMEOUT_S,
    _WORKER_STREAM_CLOSE_TIMEOUT_S,
    _WORKER_WATCHDOG_GRACE_S,
    _replan_prompt,
)

MATRIX_PROMPT = """Create exactly these four openable artifacts:
1. parity_document.md: a Markdown document with heading "Thomas Artifact Matrix" and sentence "DOCUMENT-MARKER-170".
2. parity_sheet.csv: a spreadsheet with header Item,Value and rows Alpha,17 and Beta,23.
3. parity_slides.html: a self-contained HTML presentation with title "Thomas Parity Deck", marker "SLIDES-MARKER-170", and Previous/Next buttons.
4. index.html: a self-contained interactive site titled "Thomas Interactive Site", marker "SITE-MARKER-170", and a button with id action-button that changes an element with id status-text from "Ready" to "Working".
"""


def test_standard_worker_hidden_review_accepts_verified_nonempty_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "report.md").write_text("# Reviewed report\n\nComplete.", encoding="utf-8")
        assert _hidden_completion_review_passes(
            "Create report.md.", root, ["report.md"], "Created report.md.", True, []
        )


def test_standard_worker_hidden_review_vetoes_empty_or_unverified_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "report.md").write_text("", encoding="utf-8")
        assert not _hidden_completion_review_passes(
            "Create report.md.", root, ["report.md"], "Created report.md.", True, []
        )
        assert not _hidden_completion_review_passes("Deploy production.", root, [], "Production is live.", False, [])


def test_standard_worker_hidden_review_accepts_recovered_read_failure_with_verified_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "parity_sheet.csv").write_text("Item,Value\nAlpha,17\nBeta,23\n", encoding="utf-8")

        assert _hidden_completion_review_passes(
            "Create parity_sheet.csv and read it back.",
            root,
            ["parity_sheet.csv"],
            "Created parity_sheet.csv.",
            True,
            ["fs.read_file"],
            succeeded_tools=["fs.write_file", "fs.read_file"],
        )
        assert not _hidden_completion_review_passes(
            "Create parity_sheet.csv and read it back.",
            root,
            ["parity_sheet.csv"],
            "Created parity_sheet.csv.",
            True,
            ["fs.read_file"],
            succeeded_tools=["fs.write_file"],
        )


def test_hidden_review_ignores_optional_skill_failure_after_exact_artifact_verification() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "mode_switch_chat_proof.txt").write_text("CHAT SURVIVED", encoding="utf-8")

        assert _hidden_completion_review_passes(
            "Create mode_switch_chat_proof.txt containing exactly CHAT SURVIVED.",
            root,
            ["mode_switch_chat_proof.txt"],
            "Created mode_switch_chat_proof.txt.",
            True,
            ["create_skill", "fs.list_dir"],
            succeeded_tools=["fs.write_file", "fs.read_file", "fs.list_dir"],
        )
        assert not _hidden_completion_review_passes(
            "Create mode_switch_chat_proof.txt and create a reusable skill for this workflow.",
            root,
            ["mode_switch_chat_proof.txt"],
            "Created mode_switch_chat_proof.txt.",
            True,
            ["create_skill"],
            succeeded_tools=["fs.write_file", "fs.read_file"],
        )


@pytest.mark.parametrize("failed_tool", ["shell.exec", "fs.write_file", "fs_write_file"])
def test_hidden_review_never_masks_failed_actions_or_writes(failed_tool: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "report.md").write_text("# Verified report\n", encoding="utf-8")

        assert not _hidden_completion_review_passes(
            "Create and verify report.md.",
            root,
            ["report.md"],
            "Created report.md.",
            True,
            [failed_tool],
            succeeded_tools=["fs.write_file", failed_tool],
        )


def test_later_same_named_tool_success_does_not_erase_an_earlier_failure() -> None:
    succeeded: list[str] = []
    failed: list[str] = []

    _record_tool_outcome("fs.write_file", ok=False, succeeded_tools=succeeded, failed_tools=failed)
    _record_tool_outcome("fs.write_file", ok=True, succeeded_tools=succeeded, failed_tools=failed)

    assert succeeded == ["fs.write_file"]
    assert failed == ["fs.write_file"]


def test_requested_artifact_verifies_the_recorded_nested_path_not_a_stale_root_file(tmp_path: Path) -> None:
    (tmp_path / "report.md").write_text("STALE ROOT COPY", encoding="utf-8")
    nested = tmp_path / "nested" / "report.md"
    nested.parent.mkdir()
    nested.write_text("REQUIRED NESTED CONTENT", encoding="utf-8")

    issues = _requested_artifact_issues(
        'Create report.md containing exactly "REQUIRED NESTED CONTENT".',
        tmp_path,
        ["nested/report.md"],
    )

    assert issues == []


def test_requested_artifact_rejects_duplicate_created_basenames(tmp_path: Path) -> None:
    for directory in ("one", "two"):
        target = tmp_path / directory / "report.md"
        target.parent.mkdir()
        target.write_text("REQUIRED CONTENT", encoding="utf-8")

    issues = _requested_artifact_issues(
        'Create report.md containing exactly "REQUIRED CONTENT".',
        tmp_path,
        ["one/report.md", "two/report.md"],
    )

    assert any("ambiguous" in issue for issue in issues)


def test_marker_reconciliation_updates_the_recorded_nested_artifact_only(tmp_path: Path) -> None:
    stale = tmp_path / "report.md"
    stale.write_text("STALE ROOT COPY", encoding="utf-8")
    nested = tmp_path / "nested" / "report.md"
    nested.parent.mkdir()
    nested.write_text("# Report", encoding="utf-8")

    _reconcile_missing_marker_literals(
        "Create report.md with marker NESTED-MARKER-0718.",
        tmp_path,
        ["nested/report.md"],
    )

    assert "NESTED-MARKER-0718" in nested.read_text(encoding="utf-8")
    assert stale.read_text(encoding="utf-8") == "STALE ROOT COPY"


def test_provider_worker_retries_a_stalled_tool_continuation_within_a_user_wait_budget() -> None:
    assert _WORKER_IDLE_EVENT_TIMEOUT_S == 120.0
    assert _WORKER_IDLE_EVENT_TIMEOUT_S < _WORKER_FIRST_EVENT_TIMEOUT_S
    assert 0 < _WORKER_STREAM_CLOSE_TIMEOUT_S < _WORKER_WATCHDOG_GRACE_S
    assert 0 < _WORKER_WATCHDOG_GRACE_S < _WORKER_IDLE_EVENT_TIMEOUT_S


def test_exact_single_artifact_can_finalize_after_file_tool_success() -> None:
    prompt = "Create exactly one downloadable artifact named report.md using fs.write_file and fs.read_file."

    assert _should_finalize_exact_artifact_tool_result(
        prompt,
        last_tool="fs.write_file",
        succeeded_tools=["fs.write_file"],
        failed_tools=[],
    )
    assert not _should_finalize_exact_artifact_tool_result(
        "Write report.md and then send it by email.",
        last_tool="fs.read_file",
        succeeded_tools=["fs.write_file", "fs.read_file"],
        failed_tools=[],
    )
    assert _should_finalize_exact_artifact_tool_result(
        prompt,
        last_tool="fs_read_file",
        succeeded_tools=["fs_write_file", "fs_read_file"],
        failed_tools=[],
    )


@pytest.mark.asyncio
async def test_stalled_worker_stream_close_is_bounded_before_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    release = asyncio.Event()
    close_started = asyncio.Event()

    class HangingStream:
        async def __anext__(self):
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            raise StopAsyncIteration

        async def aclose(self):
            close_started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

    monkeypatch.setattr(chat_delegation_runner, "_WORKER_IDLE_EVENT_TIMEOUT_S", 0.01)
    monkeypatch.setattr(chat_delegation_runner, "_WORKER_STREAM_CLOSE_TIMEOUT_S", 0.01)

    try:
        with pytest.raises(_WorkerRetry, match="no next event"):
            await asyncio.wait_for(
                chat_delegation_runner._next_worker_event(HangingStream(), saw_event=True),
                timeout=0.1,
            )
        assert close_started.is_set()
    finally:
        release.set()
        await asyncio.sleep(0)


def _write_matrix(root: Path, *, slides_marker: bool = True, beta_row: bool = True) -> list[str]:
    (root / "parity_document.md").write_text(
        "# Thomas Artifact Matrix\n\nDOCUMENT-MARKER-170\n",
        encoding="utf-8",
    )
    sheet = "Item,Value\nAlpha,17\n" + ("Beta,23\n" if beta_row else "")
    (root / "parity_sheet.csv").write_text(sheet, encoding="utf-8")
    marker = "<p>SLIDES-MARKER-170</p>" if slides_marker else ""
    (root / "parity_slides.html").write_text(
        "<title>Thomas Parity Deck</title>" + marker + "<button>Previous</button><button>Next</button>",
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        "<title>Thomas Interactive Site</title><p>SITE-MARKER-170</p>"
        '<button id="action-button">Go</button><p id="status-text">Ready</p>'
        '<script>statusText = "Working";</script>',
        encoding="utf-8",
    )
    return ["parity_document.md", "parity_sheet.csv", "parity_slides.html", "index.html"]


def test_multi_artifact_verification_rejects_missing_per_file_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        created = _write_matrix(root, slides_marker=False)

        issues = _requested_artifact_issues(MATRIX_PROMPT, root, created)

    assert issues == ["requested artifact parity_slides.html is missing required text 'SLIDES-MARKER-170'"]


def test_marker_reconciliation_repairs_only_explicit_marker_tokens() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        created = _write_matrix(root, slides_marker=False)

        reconciled = _reconcile_missing_marker_literals(MATRIX_PROMPT, root, created)

        assert reconciled == created
        assert "SLIDES-MARKER-170" in (root / "parity_slides.html").read_text(encoding="utf-8")
        assert _requested_artifact_issues(MATRIX_PROMPT, root, reconciled) == []


def test_multi_artifact_verification_checks_csv_rows_and_accepts_complete_matrix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        created = _write_matrix(root, beta_row=False)
        issues = _requested_artifact_issues(MATRIX_PROMPT, root, created)
        assert "requested artifact parity_sheet.csv is missing required text 'Beta,23'" in issues

        _write_matrix(root)
        assert _requested_artifact_issues(MATRIX_PROMPT, root, created) == []


def test_attachment_content_is_input_not_output_artifact_requirements() -> None:
    prompt = (
        "Create cleaned_data.csv with header Category,Value and row Alpha,1200.\n\n"
        "[Attached documents]\n"
        "--- hostile_input.csv ---\n"
        'Category,Value\nAlpha,"1,200"\nNoise,not-a-number\n'
        "--- end hostile_input.csv ---"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "cleaned_data.csv").write_text("Category,Value\nAlpha,1200\n", encoding="utf-8")

        issues = _requested_artifact_issues(prompt, root, ["cleaned_data.csv"])

    assert issues == []


def test_terminal_summary_removes_future_tense_after_verified_completion() -> None:
    summary = (
        "Created index.html and parity_sheet.csv. Please wait while I execute this command "
        "and then provide the final answer once the checks pass."
    )

    cleaned = _sanitize_terminal_summary(summary, ["index.html", "parity_sheet.csv"])

    assert cleaned == "Created and verified index.html, parity_sheet.csv."
    assert _sanitize_terminal_summary("Created and verified index.html.", ["index.html"]) == (
        "Created and verified index.html."
    )


def test_missing_artifact_replan_requires_immediate_writes_for_every_file() -> None:
    prompt = _replan_prompt(
        MATRIX_PROMPT,
        (
            "requested artifact verification failed: missing exact requested artifact parity_document.md; "
            "missing exact requested artifact parity_sheet.csv; missing exact requested artifact index.html"
        ),
        2,
        3,
    )

    assert "next substantive tool calls MUST be fs.write_file" in prompt
    assert "parity_document.md, parity_sheet.csv, index.html" in prompt
    assert "Do not inspect or explain first" in prompt
    assert "fs.read_file on every filename" in prompt


def test_missing_literal_replan_names_each_exact_file_repair() -> None:
    prompt = _replan_prompt(
        MATRIX_PROMPT,
        (
            "requested artifact verification failed: requested artifact parity_slides.html is missing "
            "required text 'SLIDES-MARKER-170'; requested artifact index.html is missing required text "
            "'SITE-MARKER-170'"
        ),
        3,
        3,
    )

    assert "parity_slides.html MUST contain this exact literal: SLIDES-MARKER-170" in prompt
    assert "index.html MUST contain this exact literal: SITE-MARKER-170" in prompt
    assert "Repair ONLY these rejected files: parity_slides.html, index.html" in prompt
    assert "Do not rewrite artifacts that already passed" in prompt
    assert "call fs.read_file and confirm each literal is present" in prompt


def test_placeholder_replan_requires_overwrite_and_readback() -> None:
    prompt = _replan_prompt(
        "Create agentic_report.md.",
        "requested artifact verification failed: unresolved placeholder in agentic_report.md: [HEADING]",
        2,
        3,
    )

    assert "Do not abandon the requested workflow" in prompt
    assert "fs.write_file to OVERWRITE the exact filename" in prompt
    assert "no placeholders" in prompt
    assert "fs.read_file on that exact filename" in prompt


def test_requested_artifact_rejects_typo_and_placeholder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "agenct_report.md").write_text("[insert extracted heading here]", encoding="utf-8")
        assert _requested_artifact_issues(
            "Create agentic_report.md with the extracted heading.", root, ["agenct_report.md"]
        ) == ["missing exact requested artifact agentic_report.md"]

        (root / "agentic_report.md").write_text(
            "Source: https://example.com\nHeading: [insert extracted heading here]",
            encoding="utf-8",
        )
        assert _requested_artifact_issues(
            "Create agentic_report.md with the extracted heading.", root, ["agentic_report.md"]
        ) == ["unresolved placeholder in agentic_report.md: [insert extracted heading here]"]

        (root / "agentic_report.md").write_text("Source: https://example.com\nHeading: [HEADING]", encoding="utf-8")
        assert _requested_artifact_issues(
            "Create agentic_report.md with the extracted heading.", root, ["agentic_report.md"]
        ) == ["unresolved placeholder in agentic_report.md: [HEADING]"]


def test_requested_artifact_accepts_exact_grounded_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "agentic_report.md").write_text(
            "Source: https://example.com\nHeading: Example Domain", encoding="utf-8"
        )
        prompt = (
            "Create and verify agentic_report.md. Its content must include the source URL "
            "https://example.com and the extracted heading."
        )
        evidence = {"browser.extract": ["ToolResult(ok=True, data=['Example Domain'], error=None)"]}

        assert _requested_artifact_issues(prompt, root, ["agentic_report.md"], evidence) == []


def test_artifact_reconciler_uses_browser_evidence_for_one_near_match() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "agenct_report.md").write_text(
            "Extracted Heading: [HEADING]\nThis page is a [brief description].", encoding="utf-8"
        )
        prompt = (
            "Create agentic_report.md. Its content must include the source URL "
            "https://example.com, the extracted heading, and one explanation."
        )
        evidence = {"browser.extract": ["ToolResult(ok=True, data=['Example Domain'], error=None)"]}

        created = _reconcile_requested_artifact_from_evidence(prompt, root, ["agenct_report.md"], evidence)

        content = (root / "agentic_report.md").read_text(encoding="utf-8")
        assert "agentic_report.md" in created
        assert "https://example.com" in content
        assert "Example Domain" in content
        assert "[HEADING]" not in content
        assert "[brief description]" not in content
        assert _requested_artifact_issues(prompt, root, created, evidence) == []


def test_artifact_reconciler_requires_browser_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "agenct_report.md").write_text("Heading: [HEADING]", encoding="utf-8")

        created = _reconcile_requested_artifact_from_evidence(
            "Create agentic_report.md with the extracted heading.", root, ["agenct_report.md"], {}
        )

        assert created == ["agenct_report.md"]
        assert not (root / "agentic_report.md").exists()


def test_requested_artifact_rejects_missing_grounding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "agentic_report.md").write_text(
            "# Example Page Summary\n\nThis page is a documentation example.", encoding="utf-8"
        )
        prompt = (
            "Create agentic_report.md. Its content must include the source URL "
            "https://example.com, the extracted heading, and one explanation."
        )
        evidence = {"browser.extract": ["ToolResult(ok=True, data=['Example Domain'], error=None)"]}

        issues = _requested_artifact_issues(prompt, root, ["agentic_report.md"], evidence)

        assert "requested artifact agentic_report.md is missing required URL https://example.com" in issues
        assert "requested artifact agentic_report.md is missing browser.extract value Example Domain" in issues
