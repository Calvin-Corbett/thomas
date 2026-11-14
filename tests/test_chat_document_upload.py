"""Upload actual document bytes, then prove only readable text enters Chat."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from thomas.server.routes import chat_document_upload
from thomas.server.routes.chat_prompt_attachments import images_for_request, prompt_with_documents
from thomas.server.routes.chat_v2_session_routes import guard_chat_v2_read
from thomas.tools.file_readers import DocumentReadError, extract_uploaded_document


@pytest.fixture(autouse=True)
def isolated_attachment_store(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))


def pdf_bytes(text="Manifest total is 43"):
    buffer = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    writer.write(buffer)
    return buffer.getvalue()


async def upload(raw, name, content_type="application/octet-stream"):
    app = web.Application(client_max_size=6_000_000)
    app.router.add_post("/extract", chat_document_upload.handle_document_extract)
    async with TestClient(TestServer(app)) as client:
        form = aiohttp.FormData()
        form.add_field("document", raw, filename=name, content_type=content_type)
        async with client.post("/extract", data=form) as response:
            return response.status, await response.json()


def test_real_pdf_upload_extracts_sentence_instead_of_binary():
    status, result = asyncio.run(upload(pdf_bytes(), "manifest.pdf", "application/pdf"))
    assert status == 200
    prompt = prompt_with_documents("What is the total?", [result["document"]])
    assert "Manifest total is 43" in prompt
    assert "%PDF" not in prompt and "endstream" not in prompt


def test_plaintext_upload_and_image_path_remain_supported():
    status, result = asyncio.run(upload(b"12 + 31 = 43", "manifest.txt", "text/plain"))
    assert status == 200 and result["document"]["text"] == "12 + 31 = 43"
    image = {"name": "image.png", "data_url": "data:image/png;base64,abc"}
    blocks, prompt = images_for_request("look", [image])
    assert len(blocks) == 1 and prompt == "look"


@pytest.mark.parametrize(
    "raw,name,mime",
    [
        (b"not a pdf", "bad.pdf", "application/pdf"),
        (b"PK\x03\x04binary", "notes.docx", "application/octet-stream"),
        (b"binary\x00data", "notes.txt", "text/plain"),
        (b"\xffbroken", "bad.txt", "text/plain"),
        (b"", "empty.txt", "text/plain"),
    ],
)
def test_unreadable_files_are_rejected_explicitly(raw, name, mime):
    status, result = asyncio.run(upload(raw, name, mime))
    assert status == 422 and result.get("error")
    assert "document" not in result


def test_password_pdf_and_scanned_pdf_have_specific_errors():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("secret")
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(DocumentReadError, match="password-protected"):
        extract_uploaded_document(stream.getvalue(), "locked.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(DocumentReadError, match="OCR"):
        extract_uploaded_document(stream.getvalue(), "scan.pdf")


def test_huge_upload_rejected_before_worker(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Oversized upload reached parser")

    monkeypatch.setattr(chat_document_upload, "run_json_worker", forbidden)
    status, result = asyncio.run(upload(b"x" * 5_000_001, "huge.txt"))
    assert status == 413 and "5 MB" in result["error"]


def test_truncation_is_visible_and_filename_is_not_a_path():
    status, result = asyncio.run(upload(b"x" * 60_000, "../../note.txt", "text/plain"))
    assert status == 200
    assert result["document"]["name"] == "note.txt"
    assert result["document"]["truncated"]
    assert "truncated" in result["document"]["text"]


def test_legacy_raw_pdf_and_rejected_document_are_named_not_read():
    docs = [
        {"name": "raw.pdf", "text": "%PDF-1.7\ncompressed payload"},
        {"name": "failed.docx", "error": "unsupported"},
    ]
    prompt = prompt_with_documents("summarize", docs)
    assert "raw.pdf" in prompt and "failed.docx" in prompt and "NOT read" in prompt
    assert "%PDF" not in prompt and "compressed payload" not in prompt


def test_extraction_endpoint_guard_checks_access_before_reading():
    calls = []

    def deny(request):
        calls.append("guard")
        raise web.HTTPUnauthorized()

    async def check():
        app = web.Application()
        app.router.add_post("/extract", guard_chat_v2_read(chat_document_upload.handle_document_extract, deny))
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/extract", data=b"not parsed")
            assert response.status == 401

    asyncio.run(check())
    assert calls == ["guard"]


def test_document_picker_ownership_errors_and_pending_send():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node, "Node is required for the composer regression checks"
    result = subprocess.run(
        [
            node,
            str(root / "tests/web_node/chat_document_attachments.mjs"),
            str(root / "thomas/server/web/js/chat_composer_panels.js"),
            str(root / "thomas/server/web/chat.html"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_registered_upload_and_chat_followup_use_retained_readable_source(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
    from thomas.server.app import create_app
    from thomas.server.routes import chat_v2
    from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE

    prompts = []

    class Brain:
        def __init__(self, **kwargs):
            pass

        async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):
            prompts.append(prompt)
            updated = conversation.append_message("user", kwargs.get("display_prompt") or prompt)
            await dispatcher.emit_text("The total is 43.")
            return updated.append_message("assistant", "The total is 43.")

    async def model(*args, **kwargs):
        return SimpleNamespace(), None, "local"

    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr("thomas.server.routes.chat_v2_support.OrchestratorBrain", Brain)
    monkeypatch.setattr(chat_v2, "initialize_chat_v2_llm", model)
    config = AppConfig(
        models={
            "local": ModelConfig(
                name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="offline"
            )
        },
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
        server=ServerConfig(access_mode="local"),
    )
    app = create_app(config)
    async with TestClient(TestServer(app)) as client:
        form = aiohttp.FormData()
        form.add_field("document", pdf_bytes(), filename="manifest.pdf", content_type="application/pdf")
        upload_response = await client.post("/api/v2/chat/documents/extract", data=form)
        assert upload_response.status == 200, await upload_response.text()
        document = (await upload_response.json())["document"]
        document["text"] = "Forged browser text must not replace retained source"
        base = {"session_id": "docs-route", "profile": "local", "message": "What is the total?"}
        response = await client.post("/api/v2/chat", json={**base, "docs": [document]})
        assert response.status == 200, await response.text()
        await response.read()
        assert "Manifest total is 43" in prompts[-1] and "Forged browser text" not in prompts[-1]
        response = await client.post(
            "/api/v2/chat", json={**base, "message": "What number did the attachment contain?"}
        )
        assert response.status == 200, await response.text()
        await response.read()
        assert "Manifest total is 43" in prompts[-1]
        saved = await app[APP_SESSION_STORE].load("docs-route")
        user_messages = [message["content"] for message in saved.get_messages() if message["role"] == "user"]
        assert user_messages == ["What is the total?", "What number did the attachment contain?"]
        response = await client.post("/api/v2/chat", json={**base, "session_id": "different-chat", "docs": [document]})
        assert response.status == 422 and "another conversation" in await response.text()
