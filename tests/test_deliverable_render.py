"""Markdown report deliverables must arrive as readable PDFs, not raw `.md`.

Locks in the markdown -> HTML -> PDF renderer (`deliverable_render`) and the
finalize hook (`render_report_pdfs`): correct structural rendering, HTML-injection
escaping, and the skip rules (README/LICENSE, nested files, existing PDFs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.chat_delegation_deliverable import render_report_pdfs
from thomas.server.deliverable_render import markdown_to_html, render_markdown_to_pdf


def _browser_ok() -> bool:
    # Mirrors the tuple render_markdown_to_pdf() itself uses, so this gate skips
    # exactly when the renderer would return None. Playwright is an optional extra:
    # ImportError when absent, OSError when the package is there but its driver
    # files are not.
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except (ImportError, OSError):
        return False

    # PlaywrightError is how every browser fault arrives (no Chromium installed,
    # launch refused, sync API called from inside an event loop); OSError/
    # RuntimeError/ValueError/TypeError cover the driver handshake.
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except (PlaywrightError, OSError, RuntimeError, ValueError, TypeError):
        return False


def test_markdown_to_html_renders_core_constructs() -> None:
    html = markdown_to_html(
        "# Title\n\nA **bold** and _italic_ line with `code`.\n\n"
        "- one\n- two\n\n## Heading 2\n\n```python\nx = 1\n```\n\n"
        "| A | B |\n| - | - |\n| 1 | 2 |\n\n> a quote\n"
    )
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert "<ul><li>one</li><li>two</li></ul>" in html
    assert "<h2>Heading 2</h2>" in html
    assert "<pre><code" in html and "x = 1" in html
    assert "<table>" in html and "<th>A</th>" in html and "<td>1</td>" in html
    assert "<blockquote>a quote</blockquote>" in html


def test_markdown_to_html_escapes_html_injection() -> None:
    """A report's text must not inject live markup into the rendered doc."""
    html = markdown_to_html("Hello <script>alert(1)</script> and <img src=x onerror=boom()>")
    # Raw HTML tags are escaped to inert text (no LIVE tag survives).
    assert "<script" not in html.lower()
    assert "<img " not in html  # the raw <img...> is escaped, not a live element
    assert "&lt;script&gt;" in html


def test_markdown_link_and_image_urls_are_sanitized() -> None:
    """Markdown link/image syntax must not build javascript:/data: URL tags."""
    html = markdown_to_html("[click](javascript:alert(1)) and ![x](javascript:evil())")
    assert "javascript:" not in html  # dangerous schemes neutralised to '#'
    # A normal link still works.
    ok = markdown_to_html("[home](https://example.com)")
    assert 'href="https://example.com"' in ok


def test_markdown_to_html_survives_malformed_input() -> None:
    # Unclosed fence, ragged table, deep nesting — must not raise.
    markdown_to_html("```\nno close\n\n| a | b |\n| - |\n| 1 |\n\n> > > deep")
    markdown_to_html("")
    markdown_to_html("#" * 100)


@pytest.mark.skipif(not _browser_ok(), reason="headless Chromium unavailable")
def test_render_markdown_to_pdf_produces_real_pdf(tmp_path: Path) -> None:
    md = tmp_path / "report.md"
    md.write_text("# Q3 Report\n\nRevenue up **18%**.\n\n- a\n- b\n", encoding="utf-8")
    out = render_markdown_to_pdf(md)
    assert out is not None and out.is_file()
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 1000


@pytest.mark.skipif(not _browser_ok(), reason="headless Chromium unavailable")
def test_render_report_pdfs_skip_rules(tmp_path: Path) -> None:
    (tmp_path / "analysis.md").write_text("# Analysis\n\nbody", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "notes.md").write_text("# nested", encoding="utf-8")

    new = render_report_pdfs(tmp_path, ["analysis.md", "README.md", "src/notes.md"])

    assert new == ["analysis.pdf"]
    assert (tmp_path / "analysis.pdf").is_file()
    assert not (tmp_path / "README.pdf").exists()  # boilerplate skipped
    assert not (tmp_path / "src" / "notes.pdf").exists()  # nested skipped


def test_parenthesized_urls_are_not_truncated() -> None:
    """Wikipedia/citation links with balanced parens must keep their full href."""
    html = markdown_to_html("See [the article](https://en.wikipedia.org/wiki/Python_(programming_language)).")
    assert 'href="https://en.wikipedia.org/wiki/Python_(programming_language)"' in html
    assert "<em>" not in html  # no stray italic from a leaked underscore tail


def test_single_column_table_renders() -> None:
    html = markdown_to_html("| Metric |\n|--------|\n| Uptime |\n| Errors |")
    assert "<table>" in html and "<th>Metric</th>" in html and "<td>Uptime</td>" in html


def test_inline_formatting_does_not_corrupt_urls() -> None:
    # *, _, backtick in a URL must not splice tags into src/href.
    assert 'src="a**b**c"' in markdown_to_html("![x](a**b**c)")
    assert "<strong>" not in markdown_to_html("[x](a**b**c)")


def test_escaped_pipe_in_table_cell() -> None:
    html = markdown_to_html("| a\\|b | c |\n| --- | --- |\n| 1 | 2 |")
    assert "<th>a|b</th>" in html


def test_render_report_pdfs_never_raises_on_bad_input() -> None:
    assert render_report_pdfs(None, ["x.md"]) == []
    assert render_report_pdfs("/nonexistent/path/xyz", ["x.md"]) == []
    assert render_report_pdfs(".", []) == []
