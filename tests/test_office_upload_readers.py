"""Actual Office bytes through the bounded upload parser, including hostile packages."""

from __future__ import annotations

import asyncio
import base64
import zipfile
from io import BytesIO

import pytest
from docx import Document
from openpyxl import Workbook

from thomas.tools import office_archive
from thomas.tools.bounded_worker import WorkerFailure, run_json_worker
from thomas.tools.file_readers import DocumentReadError, extract_uploaded_document


def word_bytes():
    doc = Document()
    doc.add_paragraph("Quarterly revenue is 43.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Unique table item"
    table.cell(0, 1).text = "31"
    doc.add_paragraph("After the table.")
    doc.sections[0].header.paragraphs[0].text = "Confidential header"
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Revenue"
    sheet.append(["Item", "Amount"])
    sheet.append(["First", 12])
    sheet.append(["Second", 31])
    sheet["B4"] = "=SUM(B2:B3)"
    sheet.merge_cells("D1:E1")
    sheet["D1"] = "Merged note"
    hidden = workbook.create_sheet("Private assumptions")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "Formula sources"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def package(parts):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def slide_bytes():
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    return package(
        {
            "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>',
            "ppt/presentation.xml": f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
            '<p:sldId id="256" r:id="second"/><p:sldId id="257" r:id="first"/></p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{rel}">'
            '<Relationship Id="first" Target="slides/slide1.xml"/><Relationship Id="second" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide2.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><a:p><a:r><a:t>Logical first slide</a:t></a:r></a:p>'
            "<a:tbl><a:tr><a:tc><a:p><a:r><a:t>Unique slide table</a:t></a:r></a:p></a:tc></a:tr></a:tbl></p:cSld></p:sld>",
            "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><a:p><a:r><a:t>Logical second slide</a:t></a:r></a:p></p:sld>',
            "ppt/slides/_rels/slide2.xml.rels": f'<Relationships xmlns="{rel}">'
            '<Relationship Id="notes" Target="../notesSlides/notesSlide1.xml"/>'
            '<Relationship Id="remote" TargetMode="External" Target="http://127.0.0.1:1/never-fetch"/></Relationships>',
            "ppt/notesSlides/notesSlide1.xml": f'<p:notes xmlns:p="{p}" xmlns:a="{a}"><a:p><a:r><a:t>Speaker evidence</a:t></a:r></a:p></p:notes>',
        }
    )


def replace_part(raw, name, content):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        parts = {item: archive.read(item) for item in archive.namelist()}
    parts[name] = content
    return package(parts)


def test_word_paragraph_table_and_header_are_labeled_without_double_counting():
    result = extract_uploaded_document(word_bytes(), "report.docx")
    text = result["text"]
    assert text.index("Quarterly revenue") < text.index("Unique table item") < text.index("After the table")
    assert text.count("Unique table item") == 1 and "Column 2: 31" in text
    assert "word/header1.xml" in text and "Confidential header" in text
    assert result["format"] == "docx" and not result["truncated"]


def test_workbook_preserves_formulas_coordinates_hidden_sheets_and_merge_labels():
    result = extract_uploaded_document(workbook_bytes(), "revenue.xlsx")
    text = result["text"]
    assert "[Sheet: Revenue (visible)]" in text
    assert "B2: 12" in text and "B3: 31" in text and "B4: =SUM(B2:B3); no cached value" in text
    assert "[Sheet: Private assumptions (hidden)]" in text and "Merged ranges: D1:E1" in text
    assert "never calculated" in text and "Dates may appear as Excel serial numbers" in text


def test_presentation_uses_logical_order_and_includes_notes_and_tables_once():
    result = extract_uploaded_document(slide_bytes(), "deck.pptx")
    text = result["text"]
    assert text.index("Logical first slide") < text.index("Logical second slide")
    assert "[Slide 1 speaker notes]" in text and "Speaker evidence" in text
    assert text.count("Unique slide table") == 1
    assert "external resources are not loaded" in result["warnings"][0]


@pytest.mark.parametrize("factory,name", [(word_bytes, "a.docx"), (workbook_bytes, "b.xlsx"), (slide_bytes, "c.pptx")])
def test_real_document_child_reads_each_office_container(factory, name):
    result = asyncio.run(
        run_json_worker(
            "thomas.tools.document_worker", {"name": name, "data": base64.b64encode(factory()).decode()}, timeout=8
        )
    )
    assert result["ok"] and result["document"]["format"] == name.rsplit(".", 1)[1]
    assert not result["document"]["text"].startswith("PK")


@pytest.mark.parametrize(
    "alter,error",
    [
        (lambda raw: raw[:100], "could not be read"),
        (lambda raw: replace_part(raw, "../escape.xml", "bad"), "unsafe package path"),
        (lambda raw: replace_part(raw, "word/vbaProject.bin", "macro"), "Macro-enabled"),
        (
            lambda raw: replace_part(raw, "word/document.xml", '<!DOCTYPE a [<!ENTITY x "unsafe">]><a>&x;</a>'),
            "entity declarations",
        ),
        (
            lambda raw: replace_part(
                raw, "word/document.xml", '<!DOCTYPE a [<!ENTITY x "unsafe">]><a>&x;</a>'.encode("utf-16-le")
            ),
            "unsupported encoding",
        ),
        (lambda raw: replace_part(raw, "Word/DOCUMENT.xml", "duplicate"), "duplicate"),
    ],
)
def test_malformed_or_active_packages_fail_clearly(alter, error):
    with pytest.raises(DocumentReadError, match=error):
        extract_uploaded_document(alter(word_bytes()), "bad.docx")


def test_mismatched_extension_and_expansion_budget_fail(monkeypatch):
    raw = word_bytes()
    with pytest.raises(DocumentReadError, match="does not match"):
        extract_uploaded_document(raw, "wrong.xlsx")
    monkeypatch.setattr(office_archive, "MAX_EXPANDED_BYTES", 1_000)
    with pytest.raises(DocumentReadError, match="expands beyond"):
        extract_uploaded_document(raw, "huge.docx")


def test_output_budget_and_worker_deadline_are_enforced():
    raw = replace_part(
        word_bytes(),
        "word/document.xml",
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + "long source " * 6_000 + "</w:t></w:r></w:p></w:body></w:document>",
    )
    result = extract_uploaded_document(raw, "long.docx")
    assert result["truncated"] and len(result["text"]) < 50_100
    payload = {"name": "long.docx", "data": base64.b64encode(raw).decode()}
    with pytest.raises(WorkerFailure, match="output limit"):
        asyncio.run(run_json_worker("thomas.tools.document_worker", payload, max_output=100))
    with pytest.raises(WorkerFailure, match="deadline"):
        asyncio.run(run_json_worker("thomas.tools.document_worker", payload, timeout=0.00001))
