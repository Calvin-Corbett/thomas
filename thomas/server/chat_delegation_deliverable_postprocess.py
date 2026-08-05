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
    """Say what happened when the app was opened — including that it was not.

    This is the only check in Thomas that opens a generated app and watches it
    load. Its own module docstring names the case it exists for: an app can have
    every file present and still render a blank page. Every static check passes on
    a crashing app, because every file really is there.

    It used to require `THOMAS_RUNTIME_VERIFY` to be switched on, and that variable
    is set in exactly one place in this repository: a test file. So the check had
    never run for a real user. Measured 2026-08-05: Thomas built a three-file
    expense tracker whose app.js referenced an undeclared `refreshButton` on its
    last line; the page threw on load and rendered nothing, and Thomas handed it
    over with no warning because nothing ever opened it.

    It now runs unless explicitly switched OFF. Nothing here can reject a run — the
    function only returns a sentence to append, and every failure path inside it
    returns a sentence too.
    """

    try:
        import os

        if str(os.environ.get("THOMAS_RUNTIME_VERIFY", "")).strip().lower() in ("0", "false", "no", "off"):
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
        if result.ok:
            return ""
        # "We looked and it was fine" and "we never looked" are different facts and
        # used to return the same empty string. Silence from a step advertised as
        # "I open the app and watch it run" reads to a person as "someone checked".
        if result.skipped:
            return " ⚠ I could not open this to check that it runs — " + (
                result.reason or "no browser available"
            ) + "."
        return " ⚠ The app did not run cleanly when opened — " + (result.reason or "runtime check failed") + "."
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("Runtime deliverable verification failed", exc_info=True)
        return " ⚠ Thomas could not complete the browser verification for this app."


def subject_mismatch_warning(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str] | None,
) -> str:
    """Say so when a deliverable shares no subject with what was asked for.

    This REPORTS; it does not gate. `verified_success` is untouched by design.

    The check itself (`chat_delegation_artifact_intent`) shipped on 2026-07-24
    with a call site inside `_hidden_completion_review_passes`, where a mismatch
    scored the review 0.0 and failed the run. `87ae37e5` replaced that whole file
    with a branch version written before the gate existed, and the call site went
    with it -- so since 2026-07-27 nothing has called this, while the changelog
    told the owner "Thomas no longer calls a deliverable 'verified' when it has
    nothing to do with what you asked".

    Reconnecting it as a GATE is the wrong repair. A verification probe that
    rejects a run grades the model rather than reporting honestly, and the
    measurement behind this is a token overlap, which is exactly the kind of
    judgement that should not decide pass/fail on its own. Restoring the original
    wiring flips a real recorded case from pass to fail.

    So the promise is kept the other way round: the owner is TOLD, in the run
    summary, next to the executability warning that already works this way, and
    the verdict stays whatever the evidence made it. `artifact_intent_issues`
    returns [] whenever the question cannot be answered honestly -- no request,
    no artifacts, a request too vague to have a subject, unreadable files -- so
    silence here means "not checkable", never "checked and fine".
    """

    try:
        from thomas.server.chat_delegation_artifact_intent import artifact_intent_issues

        issues = artifact_intent_issues(prompt, work_dir, list(created_files or []))
        if not issues:
            return ""
        shown = "; ".join(str(issue) for issue in issues[:2])
        return f" ⚠ This may not be what you asked for — {shown}."
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        log.warning("Artifact subject check failed", exc_info=True)
        return ""
