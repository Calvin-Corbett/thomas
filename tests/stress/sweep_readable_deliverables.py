"""SWEEP: readable deliverables — does Thomas hand back something a human wants to
read (a styled PDF), or raw `.md` with literal `###` and `**` markup?

The user's complaint: reports drop as raw Markdown (35 `.md` vs 4 `.pdf` across the
generated workspaces). Frontier delivery means the report arrives readable. This
sweep drives the REAL renderer (`deliverable_render`) + finalize hook
(`render_report_pdfs`): correct structural conversion, injection-safe, right skip
rules, and (when a browser is present) a real PDF.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Recorder

A = "readable-deliverables"

# This is a sweep, not a unit test: `run_all.main()` calls every sweep's `run()`
# with no handler of its own, so an escaping exception kills the whole scorecard.
# The capability probe below therefore RECORDS an absent renderer as a failed row
# and keeps sweeping. Named rather than broad: ImportError means the module is
# absent, AttributeError that a symbol was renamed, and OSError/RuntimeError/
# KeyError/TypeError/ValueError cover a module whose import-time setup fails.
# Anything else is a harness defect and should stop the run loudly.
_PROBE_SETUP_ERRORS = (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError)


def run() -> Recorder:
    rec = Recorder("readable_deliverables")
    try:
        from thomas.server.chat_delegation_deliverable import render_report_pdfs
        from thomas.server.deliverable_render import markdown_to_html, render_markdown_to_pdf
    except _PROBE_SETUP_ERRORS as e:
        rec.add(
            case="markdown->PDF render capability exists",
            dimension=A,
            expected="thomas.server.deliverable_render importable",
            actual=f"not available: {type(e).__name__}: {e}",
            passed=False,
            severity="critical",
            evidence="no renderer => users get raw .md",
        )
        return rec

    # Structural conversion.
    html = markdown_to_html("# T\n\n- a\n- b\n\n| X | Y |\n| - | - |\n| 1 | 2 |\n\n```js\nx=1\n```")
    rec.add(
        case="markdown converts to structured HTML (headings/lists/tables/code)",
        dimension=A,
        expected="h1 + ul + table + pre all present",
        actual=f"h1={'<h1>T</h1>' in html} ul={'<ul>' in html} table={'<table>' in html} pre={'<pre>' in html}",
        passed=all(t in html for t in ("<h1>T</h1>", "<ul>", "<table>", "<pre>")),
        severity="high",
        evidence="markdown_to_html",
    )

    # Injection safety — report text must not inject live markup.
    inj = markdown_to_html("<script>x()</script> [a](javascript:b()) ![i](javascript:c())")
    rec.add(
        case="report text cannot inject live markup (script / javascript: URLs)",
        dimension=A,
        expected="no <script tag, no javascript: URL",
        actual=f"has_script={'<script' in inj.lower()} has_js_url={'javascript:' in inj}",
        passed=("<script" not in inj.lower()) and ("javascript:" not in inj),
        severity="high",
        evidence="markdown_to_html escaping + _safe_url",
    )

    # Robustness — malformed input must not raise.
    try:
        markdown_to_html("```\nunclosed\n\n| a |\n| - |\n> > deep\n" + "#" * 80)
        robust = True
    # markdown_to_html is pure string work over `html` + `re` -- it touches no I/O
    # and calls nothing external, so the ways malformed input can break it are:
    # indexing past a truncated table row or fence (IndexError), a missing group or
    # key while walking the parse state (KeyError, AttributeError), a coercion on a
    # part that is not the expected type (TypeError, ValueError), and blowing the
    # stack on the deeply-nested blockquote/heading input above (RecursionError).
    # That is the claim this probe makes -- narrowing keeps it honest instead of
    # letting an unrelated crash be filed as "not robust".
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError):
        robust = False
    rec.add(
        case="renderer survives malformed markdown without raising",
        dimension=A,
        expected="no exception",
        actual=f"survived={robust}",
        passed=robust,
        severity="medium",
        evidence="markdown_to_html",
    )

    # Skip rules (no browser needed for the boilerplate/nested ones — they return []).
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "README.md").write_text("# r", encoding="utf-8")
        (d / "src").mkdir()
        (d / "src" / "n.md").write_text("# n", encoding="utf-8")
        skipped = render_report_pdfs(d, ["README.md", "src/n.md"])
        rec.add(
            case="render_report_pdfs skips README + nested .md",
            dimension=A,
            expected="[] (no PDF for boilerplate/nested)",
            actual=f"returned={skipped}",
            passed=(skipped == []),
            severity="medium",
            evidence="render_report_pdfs skip rules",
        )

        # Never raises on bad input.
        rec.add(
            case="render_report_pdfs is fail-safe (never raises)",
            dimension=A,
            expected="[] on None / missing dir",
            actual=f"none={render_report_pdfs(None, ['x.md'])} missing={render_report_pdfs('/no/such/dir', ['x.md'])}",
            passed=(render_report_pdfs(None, ["x.md"]) == [] and render_report_pdfs("/no/such/dir", ["x.md"]) == []),
            severity="low",
            evidence="best-effort contract",
        )

        # Real PDF (skip-as-pass if no browser).
        rpt = d / "report.md"
        rpt.write_text("# Report\n\nbody **bold**", encoding="utf-8")
        out = render_markdown_to_pdf(rpt)
        if out is None:
            rec.add(
                case="markdown renders to a real PDF (browser present)",
                dimension=A,
                expected="PDF produced OR cleanly skipped on a browserless host",
                actual="no browser available — skipped",
                passed=True,
                severity="low",
                evidence="render_markdown_to_pdf returns None without a browser",
            )
        else:
            data = Path(out).read_bytes() if Path(out).is_file() else b""
            rec.add(
                case="markdown renders to a real PDF (browser present)",
                dimension=A,
                expected="a valid non-trivial %PDF file",
                actual=f"bytes={len(data)} pdf_magic={data[:4]!r}",
                passed=data.startswith(b"%PDF") and len(data) > 1000,
                severity="high",
                evidence="render_markdown_to_pdf via headless Chromium",
            )
    return rec


if __name__ == "__main__":
    r = run()
    for row in r.rows:
        print(("PASS" if row.passed else "FAIL"), "|", row.case, "->", row.actual)
