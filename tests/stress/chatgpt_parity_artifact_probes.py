"""Browser interaction proof for generated parity artifacts."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TERMINAL_DELEGATION_STATES = frozenset({"completed", "failed", "cancelled", "canceled", "abandoned"})


def map_artifact_executions(
    rows: Iterable[object],
    expected_names: Iterable[str],
) -> tuple[dict[str, str], dict[str, dict[str, Any]], list[str]]:
    """Map each expected artifact to its sole delegation and flag duplicate ownership."""
    expected = set(expected_names)
    execution_ids: dict[str, str] = {}
    owners: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for candidate in rows:
        if not isinstance(candidate, dict):
            continue
        execution_id = str(candidate.get("execution_id") or "")
        proof = candidate.get("proof") if isinstance(candidate.get("proof"), dict) else {}
        artifacts = proof.get("artifacts", []) if isinstance(proof, dict) else []
        for artifact in artifacts:
            name = str(artifact.get("name") or "") if isinstance(artifact, dict) else ""
            if not execution_id or name not in expected:
                continue
            previous = execution_ids.get(name)
            if previous and previous != execution_id:
                ambiguous.add(name)
                continue
            execution_ids[name] = execution_id
            owners[name] = candidate
    return execution_ids, owners, sorted(ambiguous)


def delegation_summaries(rows: Iterable[object]) -> list[dict[str, Any]]:
    """Return a secret-safe terminal evidence summary for each delegation row."""
    summaries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        proof = row.get("proof") if isinstance(row.get("proof"), dict) else {}
        artifacts = proof.get("artifacts", []) if isinstance(proof, dict) else []
        receipt = row.get("receipt") if isinstance(row.get("receipt"), dict) else {}
        summaries.append(
            {
                "execution_id": str(row.get("execution_id") or ""),
                "state": str(row.get("state") or ""),
                "proof_status": str(row.get("proof_status") or ""),
                "receipt_ok": receipt.get("ok"),
                "blocker": str(row.get("blocker") or ""),
                "artifacts": [str(item.get("name") or "") for item in artifacts if isinstance(item, dict)],
            }
        )
    return summaries


async def _extract_visible_slide(extract_tool: Any, session: str) -> tuple[Any, str]:
    """Support the two standard ways generated decks expose the active slide."""
    active = await extract_tool.execute({"selector": ".slide.active", "session": session})
    if active.ok and active.data:
        return active, ".slide.active"
    visible = await extract_tool.execute({"selector": ".slide:not([hidden])", "session": session})
    return visible, ".slide:not([hidden])"


async def matrix_browser_interactions(
    ctx: Any,
    execution_ids: Mapping[str, str],
) -> tuple[bool, dict[str, Any]]:
    """Exercise generated site and slide artifacts with Thomas's browser tools."""
    from thomas.tools.browser import (
        BrowserClickTool,
        BrowserCloseTool,
        BrowserExtractTool,
        BrowserOpenTool,
        BrowserScreenshotTool,
    )

    site_execution_id = str(execution_ids.get("index.html") or "")
    slides_execution_id = str(execution_ids.get("parity_slides.html") or "")
    if not site_execution_id or not slides_execution_id:
        return False, {"error": "site or slides execution mapping is missing"}
    session = f"artifact-matrix-{site_execution_id[-12:]}"
    base = ctx.base_url.rstrip("/")
    site_url = f"{base}/deliverable/{site_execution_id}/index.html"
    slides_url = f"{base}/deliverable/{slides_execution_id}/parity_slides.html"
    proof_dir = Path(tempfile.gettempdir()) / "thomas-chatgpt-parity"
    proof_dir.mkdir(parents=True, exist_ok=True)
    site_shot = proof_dir / f"{site_execution_id}-site.png"
    slides_shot = proof_dir / f"{slides_execution_id}-slides.png"
    try:
        site_open = await BrowserOpenTool().execute({"url": site_url, "session": session})
        site_before = await BrowserExtractTool().execute({"selector": "#status-text", "session": session})
        site_click = await BrowserClickTool().execute({"selector": "#action-button", "session": session})
        site_after = await BrowserExtractTool().execute({"selector": "#status-text", "session": session})
        site_screenshot = await BrowserScreenshotTool().execute({"path": str(site_shot), "session": session})

        slides_open = await BrowserOpenTool().execute({"url": slides_url, "session": session})
        slide_before, slide_selector = await _extract_visible_slide(BrowserExtractTool(), session)
        slide_click = await BrowserClickTool().execute({"selector": "Next", "session": session})
        slide_after = await BrowserExtractTool().execute({"selector": slide_selector, "session": session})
        slides_screenshot = await BrowserScreenshotTool().execute({"path": str(slides_shot), "session": session})

        tool_results = (
            site_open,
            site_before,
            site_click,
            site_after,
            site_screenshot,
            slides_open,
            slide_before,
            slide_click,
            slide_after,
            slides_screenshot,
        )
        results = {
            "site_execution_id": site_execution_id,
            "slides_execution_id": slides_execution_id,
            "site_open": site_open.ok,
            "site_before": site_before.data,
            "site_click": site_click.ok,
            "site_after": site_after.data,
            "site_screenshot": str(site_shot) if site_screenshot.ok and site_shot.is_file() else "",
            "slides_open": slides_open.ok,
            "slide_before": slide_before.data,
            "slide_selector": slide_selector,
            "slide_click": slide_click.ok,
            "slide_after": slide_after.data,
            "slides_screenshot": str(slides_shot) if slides_screenshot.ok and slides_shot.is_file() else "",
            "errors": [str(result.error) for result in tool_results if not result.ok and result.error],
        }
        slide_before_text = "\n".join(str(item) for item in (slide_before.data or []))
        slide_after_text = "\n".join(str(item) for item in (slide_after.data or []))
        passed = bool(
            site_open.ok
            and site_before.data == ["Ready"]
            and site_click.ok
            and site_after.data == ["Working"]
            and site_screenshot.ok
            and site_shot.is_file()
            and slides_open.ok
            and "Slide 1" in slide_before_text
            and slide_click.ok
            and "Slide 2" in slide_after_text
            and slides_screenshot.ok
            and slides_shot.is_file()
        )
        return passed, results
    finally:
        await BrowserCloseTool().execute({"session": session})


async def revision_browser_interactions(
    ctx: Any,
    original_execution_ids: Mapping[str, str],
    revised_execution_ids: Mapping[str, str],
) -> tuple[bool, dict[str, Any]]:
    """Reopen the original artifact and operate the separately revised artifact."""
    from thomas.tools.browser import (
        BrowserClickTool,
        BrowserCloseTool,
        BrowserExtractTool,
        BrowserOpenTool,
        BrowserScreenshotTool,
    )

    original_site_execution_id = str(original_execution_ids.get("index.html") or "")
    revised_site_execution_id = str(revised_execution_ids.get("index.html") or "")
    revised_slides_execution_id = str(revised_execution_ids.get("parity_slides.html") or "")
    if not original_site_execution_id or not revised_site_execution_id or not revised_slides_execution_id:
        return False, {"error": "original site, revised site, or revised slides execution mapping is missing"}
    session = f"artifact-revision-{revised_site_execution_id[-12:]}"
    base = ctx.base_url.rstrip("/")
    original_url = f"{base}/deliverable/{original_site_execution_id}/index.html"
    revised_url = f"{base}/deliverable/{revised_site_execution_id}/index.html"
    slides_url = f"{base}/deliverable/{revised_slides_execution_id}/parity_slides.html"
    proof_dir = Path(tempfile.gettempdir()) / "thomas-chatgpt-parity"
    proof_dir.mkdir(parents=True, exist_ok=True)
    revised_shot = proof_dir / f"{revised_site_execution_id}-revision.png"
    try:
        original_open = await BrowserOpenTool().execute({"url": original_url, "session": session})
        original_marker = await BrowserExtractTool().execute({"selector": "body", "session": session})
        original_status = await BrowserExtractTool().execute({"selector": "#status-text", "session": session})

        revised_open = await BrowserOpenTool().execute({"url": revised_url, "session": session})
        revised_marker = await BrowserExtractTool().execute({"selector": "body", "session": session})
        revised_before = await BrowserExtractTool().execute({"selector": "#status-text", "session": session})
        revised_click = await BrowserClickTool().execute({"selector": "#action-button", "session": session})
        revised_after = await BrowserExtractTool().execute({"selector": "#status-text", "session": session})
        screenshot = await BrowserScreenshotTool().execute({"path": str(revised_shot), "session": session})

        slides_open = await BrowserOpenTool().execute({"url": slides_url, "session": session})
        slide_before, slide_selector = await _extract_visible_slide(BrowserExtractTool(), session)
        slide_click = await BrowserClickTool().execute({"selector": "Next", "session": session})
        slide_after = await BrowserExtractTool().execute({"selector": slide_selector, "session": session})

        original_text = "\n".join(str(item) for item in (original_marker.data or []))
        revised_text = "\n".join(str(item) for item in (revised_marker.data or []))
        slide_before_text = "\n".join(str(item) for item in (slide_before.data or []))
        slide_after_text = "\n".join(str(item) for item in (slide_after.data or []))
        tool_results = (
            original_open,
            original_marker,
            original_status,
            revised_open,
            revised_marker,
            revised_before,
            revised_click,
            revised_after,
            screenshot,
            slides_open,
            slide_before,
            slide_click,
            slide_after,
        )
        results = {
            "original_site_execution_id": original_site_execution_id,
            "revised_site_execution_id": revised_site_execution_id,
            "revised_slides_execution_id": revised_slides_execution_id,
            "original_open": original_open.ok,
            "original_marker_present": "SITE-MARKER-170" in original_text,
            "original_status": original_status.data,
            "revised_open": revised_open.ok,
            "revised_marker_present": "SITE-MARKER-170-REV2" in revised_text,
            "revised_before": revised_before.data,
            "revised_click": revised_click.ok,
            "revised_after": revised_after.data,
            "screenshot": str(revised_shot) if screenshot.ok and revised_shot.is_file() else "",
            "slides_open": slides_open.ok,
            "slide_before": slide_before.data,
            "slide_selector": slide_selector,
            "slide_click": slide_click.ok,
            "slide_after": slide_after.data,
            "errors": [str(result.error) for result in tool_results if not result.ok and result.error],
        }
        passed = bool(
            original_open.ok
            and "SITE-MARKER-170" in original_text
            and "SITE-MARKER-170-REV2" not in original_text
            and original_status.data == ["Ready"]
            and revised_open.ok
            and "SITE-MARKER-170-REV2" in revised_text
            and revised_before.data == ["Ready"]
            and revised_click.ok
            and revised_after.data == ["Revised"]
            and screenshot.ok
            and revised_shot.is_file()
            and slides_open.ok
            and "Revised Slide 1" in slide_before_text
            and slide_click.ok
            and "Revised Slide 2" in slide_after_text
        )
        return passed, results
    finally:
        await BrowserCloseTool().execute({"session": session})


__all__ = [
    "TERMINAL_DELEGATION_STATES",
    "delegation_summaries",
    "map_artifact_executions",
    "matrix_browser_interactions",
    "revision_browser_interactions",
]
