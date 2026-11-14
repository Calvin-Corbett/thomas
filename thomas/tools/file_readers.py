"""File content extractors for chat document uploads.

Extracts readable text from uploaded files so Thomas can understand
documents the user shares in chat. Supports PDF, DOCX, and XLSX.

Feature parity gap: Claude/ChatGPT/Grok all read uploaded PDFs and
Office docs natively. Thomas previously only handled plain text.

Architecture context for AI agents:
  - Called from chat_aiohttp_part02.py during document attachment processing
  - Returns plain text suitable for including in the LLM prompt
  - Dependencies: pypdf2, python-docx, openpyxl (install via pip)
  - Falls back gracefully if dependencies aren't installed

Usage:
    text = extract_file_text("/path/to/file.pdf")
    if text:
        # Include in prompt context
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Max characters to extract from any single file
_MAX_EXTRACT_CHARS = 100_000


UPLOAD_MAX_BYTES = 5_000_000
UPLOAD_MAX_CHARS = 50_000
PDF_MAX_PAGES = 100


class DocumentReadError(ValueError):
    """An attachment cannot be safely represented as readable document text."""


def is_readable_text(text: str) -> bool:
    """Reject raw container/binary content, including legacy readAsText PDFs."""
    if text.lstrip().startswith(("%PDF-", "PK\x03\x04")) or "\x00" in text:
        return False
    return not any(ord(char) < 32 and char not in "\t\r\n\f" for char in text)


def extract_uploaded_document(
    raw: bytes,
    name: str,
    content_type: str = "",
    *,
    pdf_max_pages: int | None = None,
    pdf_page_markers: bool = False,
) -> dict[str, object]:
    """Decode a bounded upload. Never reinterpret a failed binary parser as text.

    Runs in ``document_worker`` so malformed/compressed documents cannot own the
    HTTP event loop. Office packages are decoded without executing active content.
    """
    if not raw or len(raw) > UPLOAD_MAX_BYTES:
        raise DocumentReadError("Choose a non-empty document no larger than 5 MB.")
    suffix = Path(name).suffix.lower()
    extra: dict[str, object] = {}
    is_pdf = suffix == ".pdf" or content_type.split(";", 1)[0].lower() == "application/pdf"
    if raw.startswith(b"%PDF-"):
        is_pdf = True
    if is_pdf:
        if not raw.startswith(b"%PDF-"):
            raise DocumentReadError("This file is not a readable PDF. Export it again or attach plain text.")
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ImportError as exc:
            raise DocumentReadError(
                "PDF reading is unavailable; install the pypdf dependency and restart Thomas."
            ) from exc
        try:
            reader = PdfReader(BytesIO(raw), strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                raise DocumentReadError("This PDF is password-protected. Attach an unlocked copy.")
            if pdf_max_pages is not None and (
                isinstance(pdf_max_pages, bool)
                or not isinstance(pdf_max_pages, int)
                or not 1 <= pdf_max_pages <= PDF_MAX_PAGES
            ):
                raise DocumentReadError("max_pages must be an integer from 1 to 100.")
            if pdf_max_pages is None and len(reader.pages) > PDF_MAX_PAGES:
                raise DocumentReadError("This PDF exceeds 100 pages. Attach a smaller page range.")
            text = _pdf_reader_text(
                reader,
                UPLOAD_MAX_CHARS + 1,
                max_pages=pdf_max_pages,
                page_markers=pdf_page_markers,
            )
            pages_truncated = pdf_max_pages is not None and len(reader.pages) > pdf_max_pages
        except (PyPdfError, TypeError, KeyError, IndexError, RecursionError, OverflowError) as exc:
            raise DocumentReadError("This PDF could not be read. Export it again or attach plain text.") from exc
        if not text:
            raise DocumentReadError("This PDF has no extractable text. It may be scanned; OCR is required.")
    elif suffix in {".docx", ".xlsx", ".pptx"}:
        from thomas.tools.office_archive import OfficeReadError
        from thomas.tools.office_readers import extract_office_document

        try:
            extra = extract_office_document(raw, suffix[1:], UPLOAD_MAX_CHARS)
            text = str(extra.pop("text"))
        except OfficeReadError as exc:
            raise DocumentReadError(str(exc)) from exc
    else:
        if suffix in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"} or raw.startswith(b"PK\x03\x04"):
            raise DocumentReadError("This document format is not supported here yet. Export it as PDF or plain text.")
        try:
            encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = raw.decode(encoding)
        except UnicodeError as exc:
            raise DocumentReadError("This file is not readable text. Attach a UTF-8 text file or PDF.") from exc
        if not is_readable_text(text):
            raise DocumentReadError("This file contains binary data. Attach a readable PDF or text document.")
    truncated = len(text) > UPLOAD_MAX_CHARS or bool(extra.pop("truncated", False))
    text = text[:UPLOAD_MAX_CHARS]
    if truncated:
        text += "\n... (truncated at 50,000 characters)"
    if is_pdf and pages_truncated:
        text += f"\n... (limited to the first {pdf_max_pages} pages)"
        truncated = True
    if not text.strip():
        raise DocumentReadError("This document contains no readable text.")
    return {"name": name, "text": text, "truncated": truncated, **extra}


def _pdf_reader_text(
    reader: Any,
    max_chars: int,
    *,
    max_pages: int | None = None,
    page_markers: bool = False,
) -> str:
    pages: list[str] = []
    remaining = max_chars
    readable = False
    for index, page in enumerate(reader.pages):
        if max_pages is not None and index >= max_pages:
            break
        text = page.extract_text() or ""
        readable = readable or bool(text.strip())
        if page_markers:
            text = f"--- Page {index + 1} ---\n{text}"
        pages.append(text[:remaining])
        remaining -= len(text) + 2
        if remaining <= 0:
            break
    return "\n\n".join(pages).strip() if readable else ""


def extract_file_text(path: str | Path, *, max_chars: int = _MAX_EXTRACT_CHARS) -> str | None:
    """Extract readable text from a file.

    Auto-detects file type from extension. Returns None if the file type
    is unsupported or extraction fails.

    Supported formats:
      - .pdf (via pypdf)
      - .docx (via python-docx)
      - .xlsx / .csv (via openpyxl / stdlib csv)
      - .txt / .md / .json / .py / etc. (plain text)
    """
    p = Path(path)
    if not p.exists():
        return None

    suffix = p.suffix.lower()

    try:
        if suffix == ".pdf":
            return _extract_pdf(p, max_chars)
        elif suffix == ".docx":
            return _extract_docx(p, max_chars)
        elif suffix in (".xlsx", ".xls"):
            return _extract_xlsx(p, max_chars)
        elif suffix == ".csv":
            return _extract_csv(p, max_chars)
        elif suffix in (
            ".txt",
            ".md",
            ".json",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".yaml",
            ".yml",
            ".toml",
            ".xml",
            ".log",
            ".sh",
            ".bat",
            ".cmd",
            ".ps1",
            ".rs",
            ".go",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".rb",
            ".php",
            ".sql",
            ".r",
            ".swift",
            ".kt",
            ".lua",
            ".pl",
            ".env",
            ".ini",
            ".cfg",
        ):
            return _extract_text(p, max_chars)
        else:
            # Try as plain text
            return _extract_text(p, max_chars)
    except Exception as exc:
        log.warning("Failed to extract text from %s: %s", path, exc)
        return None


def _extract_pdf(path: Path, max_chars: int) -> str | None:
    """Extract text from a PDF file."""
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore[no-redef]
        except ImportError:
            log.debug("PDF extraction unavailable — install pypdf: pip install pypdf")
            return None

    reader = PdfReader(str(path))
    pages: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        if total + len(text) > max_chars:
            text = text[: max_chars - total]
            pages.append(text)
            break
        pages.append(text)
        total += len(text)

    result = "\n\n".join(pages).strip()
    return result if result else None


def _extract_docx(path: Path, max_chars: int) -> str | None:
    """Extract text from a Word document."""
    try:
        from docx import Document  # type: ignore[import-untyped]
    except ImportError:
        log.debug("DOCX extraction unavailable — install python-docx: pip install python-docx")
        return None

    doc = Document(str(path))
    paragraphs: list[str] = []
    total = 0
    for para in doc.paragraphs:
        text = para.text or ""
        if total + len(text) > max_chars:
            text = text[: max_chars - total]
            paragraphs.append(text)
            break
        paragraphs.append(text)
        total += len(text)

    result = "\n".join(paragraphs).strip()
    return result if result else None


def _extract_xlsx(path: Path, max_chars: int) -> str | None:
    """Extract text from an Excel spreadsheet."""
    try:
        from openpyxl import load_workbook  # type: ignore[import-untyped]
    except ImportError:
        log.debug("XLSX extraction unavailable — install openpyxl: pip install openpyxl")
        return None

    wb = load_workbook(str(path), read_only=True, data_only=True)
    sheets: list[str] = []
    total = 0

    for ws in wb.worksheets:
        rows: list[str] = []
        rows.append(f"--- Sheet: {ws.title} ---")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            row_text = "\t".join(cells)
            if total + len(row_text) > max_chars:
                break
            rows.append(row_text)
            total += len(row_text) + 1
        sheets.append("\n".join(rows))
        if total >= max_chars:
            break

    wb.close()
    result = "\n\n".join(sheets).strip()
    return result if result else None


def _extract_csv(path: Path, max_chars: int) -> str | None:
    """Extract text from a CSV file."""
    import csv

    rows: list[str] = []
    total = 0
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            row_text = "\t".join(row)
            if total + len(row_text) > max_chars:
                break
            rows.append(row_text)
            total += len(row_text) + 1
    result = "\n".join(rows).strip()
    return result if result else None


def _extract_text(path: Path, max_chars: int) -> str | None:
    """Read a plain text file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text.strip() if text.strip() else None
    except Exception:
        return None


def detect_and_extract(
    file_path: str | Path,
    file_name: str = "",
) -> tuple[str, str | None]:
    """Detect file type and extract text.

    Returns (display_name, extracted_text).
    If extraction fails, returns (display_name, None).
    """
    p = Path(file_path)
    name = file_name or p.name
    text = extract_file_text(p)
    return name, text
