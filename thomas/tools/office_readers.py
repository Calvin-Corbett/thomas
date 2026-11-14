"""Readable Office source labels; no macros, formulas, links or active content run."""

from __future__ import annotations

import re
import zipfile
import zlib
from xml.etree import ElementTree as ET

from thomas.tools.office_archive import OfficeArchive, OfficeReadError, TextBudget

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_SHEETS_OR_SLIDES = 100
MAX_CELLS = 25_000
MAX_SHARED_STRINGS = 100_000


def _text(element, namespace: str) -> str:
    return "".join(node.text or "" for node in element.iter(namespace + "t"))


def _word_section(root, output: TextBudget, label: str):
    output.add(label)
    paragraphs = 0

    def visit(node):
        nonlocal paragraphs
        if output.truncated:
            return
        if node.tag == W + "p":
            paragraphs += 1
            chunks = []
            for item in node.iter():
                if item.tag == W + "t":
                    chunks.append(item.text or "")
                elif item.tag == W + "tab":
                    chunks.append("\t")
                elif item.tag in {W + "br", W + "cr"}:
                    chunks.append("\n")
            text = "".join(chunks)
            if text.strip():
                output.add(f"Paragraph {paragraphs}: {text}")
        elif node.tag == W + "tr":
            cells = [_text(cell, W) for cell in node.findall(W + "tc")]
            if cells:
                output.add("Table row: " + " | ".join(f"Column {i + 1}: {v}" for i, v in enumerate(cells)))
        else:
            for child in node:
                visit(child)

    visit(root)


def _docx(archive: OfficeArchive, output: TextBudget):
    _word_section(archive.xml("word/document.xml"), output, "[Word document body]")
    for name in sorted(archive.zip.namelist()):
        if output.truncated:
            break
        if re.fullmatch(r"word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml", name):
            _word_section(archive.xml(name), output, "[Word source: " + name + "]")


def _xlsx(archive: OfficeArchive, output: TextBudget):
    workbook = archive.xml("xl/workbook.xml")
    rels = archive.relationships("xl/workbook.xml")
    strings = archive.xml("xl/sharedStrings.xml", optional=True)
    shared = []
    if strings is not None:
        if len(strings) > MAX_SHARED_STRINGS:
            raise OfficeReadError("This workbook has too many shared strings. Attach a smaller workbook.")
        shared = [_text(item, S) for item in strings]
    sheets = workbook.findall(S + "sheets/" + S + "sheet")
    if len(sheets) > MAX_SHEETS_OR_SLIDES:
        raise OfficeReadError("This workbook exceeds 100 sheets. Attach a smaller workbook.")
    cells_seen = 0
    output.add(
        "[Excel formulas are shown literally, never calculated. Cached values may be stale. Dates may appear as Excel serial numbers.]"
    )
    for sheet in sheets:
        if output.truncated:
            break
        path = rels.get(sheet.get(R + "id"))
        if not path or not path.startswith("xl/worksheets/"):
            raise OfficeReadError("This workbook has a missing or external worksheet.")
        label = f"[Sheet: {sheet.get('name', 'Unnamed')} ({sheet.get('state', 'visible')})]"
        if not output.add(label):
            break
        worksheet = archive.xml(path)
        for cell in worksheet.iter(S + "c"):
            cells_seen += 1
            if cells_seen > MAX_CELLS:
                output.add("... (worksheet extraction stopped at the 25,000-cell limit)")
                output.truncated = True
                return
            address = str(cell.get("r") or "")
            if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", address):
                raise OfficeReadError("This workbook contains an invalid cell address.")
            value = cell.findtext(S + "v", "")
            kind = cell.get("t", "")
            if kind == "s":
                try:
                    index = int(value)
                    if index < 0:
                        raise IndexError
                    value = shared[index]
                except (ValueError, IndexError) as exc:
                    raise OfficeReadError("This workbook contains an invalid shared-string reference.") from exc
            elif kind == "inlineStr":
                value = _text(cell, S)
            elif kind == "b":
                value = "TRUE" if value == "1" else "FALSE"
            formula = cell.find(S + "f")
            if formula is not None:
                formula_text = formula.text or "[shared/array formula; consult original workbook]"
                value = (
                    "=" + formula_text + (f"; cached value (may be stale): {value}" if value else "; no cached value")
                )
            if value and not output.add(f"{address}: {value}"):
                break
        merged = worksheet.find(S + "mergeCells")
        if merged is not None and not output.truncated:
            output.add("Merged ranges: " + ", ".join(item.get("ref", "") for item in merged))


def _slide_text(root, output: TextBudget):
    def visit(node):
        if output.truncated:
            return
        if node.tag == A + "p":
            text = _text(node, A)
            if text.strip():
                output.add(text)
        elif node.tag == A + "tr":
            cells = [_text(cell, A) for cell in node.findall(A + "tc")]
            output.add("Table row: " + " | ".join(f"Column {i + 1}: {v}" for i, v in enumerate(cells)))
        else:
            for child in node:
                visit(child)

    visit(root)


def _pptx(archive: OfficeArchive, output: TextBudget):
    presentation = archive.xml("ppt/presentation.xml")
    rels = archive.relationships("ppt/presentation.xml")
    slides = presentation.findall(P + "sldIdLst/" + P + "sldId")
    if len(slides) > MAX_SHEETS_OR_SLIDES:
        raise OfficeReadError("This presentation exceeds 100 slides. Attach a smaller deck.")
    for index, slide in enumerate(slides):
        if output.truncated:
            break
        path = rels.get(slide.get(R + "id"))
        if not path or not path.startswith("ppt/slides/"):
            raise OfficeReadError("This presentation has a missing or external slide.")
        output.add(f"[Slide {index + 1}]")
        _slide_text(archive.xml(path), output)
        for note in archive.relationships(path).values():
            if note.startswith("ppt/notesSlides/") and not output.truncated:
                output.add(f"[Slide {index + 1} speaker notes]")
                _slide_text(archive.xml(note), output)


def extract_office_document(raw: bytes, kind: str, max_chars: int) -> dict[str, object]:
    archive = None
    try:
        archive = OfficeArchive(raw)
        archive.validate_kind(kind)
        output = TextBudget(max_chars)
        {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}[kind](archive, output)
        return {
            "text": output.text(),
            "truncated": output.truncated,
            "format": kind,
            "warnings": [
                "Text extraction only: layout, embedded objects, charts and images are not rendered; external resources are not loaded."
            ],
        }
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, UnicodeError, zlib.error, RuntimeError) as exc:
        raise OfficeReadError(
            "This Office file could not be read. Export it again or attach an unlocked copy."
        ) from exc
    finally:
        if archive is not None:
            archive.close()
