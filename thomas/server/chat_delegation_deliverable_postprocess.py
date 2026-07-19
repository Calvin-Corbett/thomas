"""Best-effort rendering and executability checks for delegated deliverables."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def executability_warning(work_dir: Path | None, created_files: list[str] | None) -> str:
    """Return a warning when a produced web app fails static verification."""
    try:
        if work_dir is None:
            return ""
        files = [str(item) for item in (created_files or []) if str(item).strip()]
        htmls = [item for item in files if item.lower().endswith(".html")]
        if not htmls:
            return ""
        from thomas.server.deliverable_verify import verify_web_deliverable

        entry = next((item for item in htmls if Path(item).name.lower() == "index.html"), htmls[0])
        result = verify_web_deliverable(work_dir, entry=entry)
        if result.ok:
            return ""
        return " ⚠ Heads up: this app may not open correctly — " + "; ".join(result.problems[:3]) + "."
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("Static deliverable verification failed", exc_info=True)
        return " ⚠ Heads up: Thomas could not verify that this app opens correctly."


_SKIP_MD_TO_PDF = {"readme.md", "license.md", "changelog.md", "contributing.md", "agents.md"}


def render_report_pdfs(work_dir: Path | None, created_files: list[str] | None) -> list[str]:
    """Render top-level Markdown report deliverables to readable PDFs."""
    new_pdfs: list[str] = []
    try:
        if work_dir is None:
            return []
        base = Path(work_dir)
        from thomas.server.deliverable_render import render_markdown_to_pdf

        for rel in created_files or []:
            rel = str(rel or "").strip().replace("\\", "/")
            if not rel.lower().endswith(".md") or "/" in rel:
                continue
            if Path(rel).name.lower() in _SKIP_MD_TO_PDF:
                continue
            md_abs = base / rel
            pdf_abs = md_abs.with_suffix(".pdf")
            if pdf_abs.exists():
                continue
            output = render_markdown_to_pdf(md_abs, pdf_abs)
            if output is not None and Path(output).is_file():
                new_pdfs.append(Path(output).name)
        return new_pdfs
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("Markdown deliverable rendering failed", exc_info=True)
        return new_pdfs


def runtime_executability_warning(work_dir: Path | None, created_files: list[str] | None) -> str:
    """Return a warning when the opt-in browser smoke check fails."""
    try:
        import os

        if str(os.environ.get("THOMAS_RUNTIME_VERIFY", "")).strip().lower() not in ("1", "true", "yes", "on"):
            return ""
        if work_dir is None:
            return ""
        files = [str(item) for item in (created_files or []) if str(item).strip()]
        htmls = [item for item in files if item.lower().endswith(".html")]
        if not htmls:
            return ""
        from thomas.server.deliverable_runtime_verify import runtime_smoke_load

        entry = next((item for item in htmls if Path(item).name.lower() == "index.html"), htmls[0])
        result = runtime_smoke_load(work_dir, entry=entry)
        if result.ok or result.skipped:
            return ""
        return " ⚠ The app did not run cleanly when opened — " + (result.reason or "runtime check failed") + "."
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("Runtime deliverable verification failed", exc_info=True)
        return " ⚠ Thomas could not complete the browser verification for this app."
