"""Render Markdown report deliverables into something a human actually wants to
read — a styled PDF — instead of dropping raw `.md`.

Thomas's workers hand back reports as raw Markdown (35 `.md` vs 4 `.pdf` across the
generated workspaces). A user opening `report.md` gets `### headings` and `**bold**`
literals. Claude-grade delivery means the report arrives readable. This module
converts Markdown -> clean HTML -> a printed PDF via the headless Chromium that is
already installed (Playwright). A `reportlab` fallback path is intentionally
avoided in favour of real typography.

Dependency-free Markdown->HTML (no `markdown` package is installed): it covers the
constructs reports actually use — headings, bold/italic/code, fenced code blocks,
ordered/unordered lists, blockquotes, GFM pipe tables, links, horizontal rules and
paragraphs. Everything is HTML-escaped first so report text cannot inject markup.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)|(?<!_)_(?!_)([^_]+)_(?!_)")
# A URL may contain ONE level of balanced parentheses so Wikipedia/citation links such
# as ..._(programming_language) keep their closing paren instead of truncating.
_URL = r"((?:[^()\s]|\([^()\s]*\))+)"
_LINK = re.compile(r"\[([^\]]+)\]\(" + _URL + r"(?:\s+\"[^\"]*\")?\)")
_IMG = re.compile(r"!\[([^\]]*)\]\(" + _URL + r"\)")
_BAD_URL_SCHEME = re.compile(r"^\s*(?:javascript|vbscript)\s*:", re.IGNORECASE)


def _safe_url(url: str, *, allow_data_image: bool = False) -> str:
    """Neutralise dangerous URL schemes built from Markdown link/image syntax."""
    u = (url or "").strip()
    if allow_data_image and u.lower().startswith("data:image/"):
        return u
    if _BAD_URL_SCHEME.match(u) or u.lower().startswith("data:"):
        return "#"
    return u


def _inline_format(text: str) -> str:
    """Code / bold / italic on a span of (already-escaped) text — NOT URLs."""
    text = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    return text


def _inline(text: str) -> str:
    """Inline Markdown -> HTML on already-escaped text.

    Links/images are extracted to placeholders BEFORE inline formatting runs, so a URL
    containing ``*``/``_``/backtick is never corrupted by bold/italic/code (and tags can
    never be spliced into an href/src value). Their labels are still formatted.
    """
    stash: list[str] = []

    def _hold(snippet: str) -> str:
        stash.append(snippet)
        return f"\x00T{len(stash) - 1}\x00"

    text = _IMG.sub(
        lambda m: _hold(f'<img alt="{m.group(1)}" src="{_safe_url(m.group(2), allow_data_image=True)}">'),
        text,
    )
    text = _LINK.sub(
        lambda m: _hold(f'<a href="{_safe_url(m.group(2))}">{_inline_format(m.group(1))}</a>'),
        text,
    )
    text = _inline_format(text)
    for i, snippet in enumerate(stash):
        text = text.replace(f"\x00T{i}\x00", snippet)
    return text


def _is_table_separator(line: str) -> bool:
    """A GFM table separator row, e.g. ``|---|---|`` or single-column ``|----|``."""
    s = line.strip()
    if "-" not in s:
        return False
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", s.strip("|")) if c.strip() != ""]
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _table_cells(row: str) -> list[str]:
    """Split a table row on UNescaped pipes; restore literal ``\\|`` inside cells."""
    parts = re.split(r"(?<!\\)\|", row.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in parts]


def markdown_to_html(md: str) -> str:
    """Convert a Markdown document body to an HTML fragment (no <html> wrapper)."""
    lines = str(md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    def flush_para(buf: list[str]) -> None:
        if buf:
            out.append("<p>" + _inline(_html.escape(" ".join(buf).strip())) + "</p>")
            buf.clear()

    para: list[str] = []
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            flush_para(para)
            lang = stripped[3:].strip()
            code: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            cls = f' class="language-{_html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>" + _html.escape("\n".join(code)) + "</code></pre>")
            continue

        # Blank line -> paragraph break
        if not stripped:
            flush_para(para)
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            flush_para(para)
            out.append("<hr>")
            i += 1
            continue

        # ATX heading
        m = re.match(r"(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para(para)
            level = len(m.group(1))
            out.append(f"<h{level}>" + _inline(_html.escape(m.group(2).strip())) + f"</h{level}>")
            i += 1
            continue

        # Blockquote (collapse consecutive)
        if stripped.startswith(">"):
            flush_para(para)
            quote: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + _inline(_html.escape(" ".join(quote).strip())) + "</blockquote>")
            continue

        # GFM table: header row + separator row (multi- OR single-column)
        if "|" in stripped and i + 1 < n and _is_table_separator(lines[i + 1]):
            flush_para(para)
            header = _table_cells(lines[i])
            i += 2  # skip header + separator
            body_rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body_rows.append(_table_cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(_html.escape(c))}</th>" for c in header)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline(_html.escape(c))}</td>" for c in r) + "</tr>" for r in body_rows
            )
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue

        # Unordered / ordered list (flat — sufficient for reports)
        if re.match(r"[-*+]\s+", stripped) or re.match(r"\d+[.)]\s+", stripped):
            flush_para(para)
            ordered = bool(re.match(r"\d+[.)]\s+", stripped))
            items: list[str] = []
            while i < n and (re.match(r"\s*[-*+]\s+", lines[i]) or re.match(r"\s*\d+[.)]\s+", lines[i])):
                item = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", lines[i])
                items.append("<li>" + _inline(_html.escape(item.strip())) + "</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue

        # Plain text -> accumulate into a paragraph
        para.append(stripped)
        i += 1

    flush_para(para)
    return "\n".join(out)


_PRINT_CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
         color: #1a1f29; line-height: 1.55; font-size: 11.5pt; margin: 0; }
  h1 { font-size: 22pt; margin: 0 0 6pt; border-bottom: 2px solid #2d4a8a; padding-bottom: 5pt; }
  h2 { font-size: 16pt; margin: 18pt 0 6pt; color: #243a6b; }
  h3 { font-size: 13pt; margin: 14pt 0 4pt; color: #2d4a8a; }
  h4,h5,h6 { font-size: 11.5pt; margin: 12pt 0 4pt; }
  p { margin: 6pt 0; }
  ul,ol { margin: 6pt 0 6pt 18pt; }
  li { margin: 2pt 0; }
  code { font-family: 'SF Mono',Consolas,'Courier New',monospace; font-size: 10pt;
         background: #eef1f6; padding: 1px 5px; border-radius: 4px; }
  pre { background: #0f1626; color: #e6edf6; padding: 12pt; border-radius: 8px;
        overflow-x: auto; font-size: 9.5pt; line-height: 1.45; }
  pre code { background: transparent; color: inherit; padding: 0; }
  blockquote { margin: 8pt 0; padding: 4pt 12pt; border-left: 3px solid #94a8cc;
               color: #44506a; background: #f4f7fc; }
  table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 10.5pt; }
  th,td { border: 1px solid #cdd5e3; padding: 5pt 8pt; text-align: left; }
  th { background: #eef2f9; }
  hr { border: none; border-top: 1px solid #cdd5e3; margin: 14pt 0; }
  a { color: #2d4a8a; }
  img { max-width: 100%; }
"""


def _document_title(md: str, fallback: str) -> str:
    for line in str(md or "").splitlines():
        m = re.match(r"#\s+(.*)$", line.strip())
        if m:
            return m.group(1).strip()
    return fallback


def render_markdown_to_pdf(md_path: str | Path, pdf_path: str | Path | None = None) -> Path | None:
    """Render a Markdown file to a styled PDF. Returns the PDF path, or None if a
    browser is unavailable / rendering fails (caller keeps the .md as fallback)."""
    md_path = Path(md_path)
    if not md_path.is_file():
        return None
    md = md_path.read_text(encoding="utf-8", errors="replace")
    pdf_path = Path(pdf_path) if pdf_path else md_path.with_suffix(".pdf")
    title = _document_title(md, md_path.stem.replace("_", " ").replace("-", " ").title())
    body = markdown_to_html(md)
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{_PRINT_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(doc, wait_until="load")
                page.pdf(
                    path=str(pdf_path),
                    format="Letter",
                    print_background=True,
                    margin={"top": "0.7in", "bottom": "0.7in", "left": "0.75in", "right": "0.75in"},
                )
            finally:
                browser.close()
    except Exception:
        return None
    return pdf_path if pdf_path.is_file() else None
