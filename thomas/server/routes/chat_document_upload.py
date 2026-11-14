"""Bounded document upload/extraction before anything enters the chat prompt."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from urllib.parse import unquote

from aiohttp import web

from thomas.server.chat_attachment_store import AttachmentError, retain_original
from thomas.tools.bounded_worker import WorkerFailure, run_json_worker
from thomas.tools.file_readers import UPLOAD_MAX_BYTES


async def handle_document_extract(request: web.Request) -> web.Response:
    if request.content_length and request.content_length > UPLOAD_MAX_BYTES + 65_536:
        return web.json_response({"error": "Choose a document no larger than 5 MB."}, status=413)
    if request.content_type != "multipart/form-data":
        return web.json_response({"error": "Send one document as multipart form data."}, status=415)
    try:
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "document" or not field.filename:
            return web.json_response({"error": "A document file is required."}, status=400)
        # A filename is display text only, never a local path or temporary path.
        name = unquote(field.filename).replace("\\", "/").rsplit("/", 1)[-1][:160] or "document"
        raw = bytearray()
        while chunk := await field.read_chunk(65_536):
            raw.extend(chunk)
            if len(raw) > UPLOAD_MAX_BYTES:
                return web.json_response({"error": "Choose a document no larger than 5 MB."}, status=413)
        if await reader.next() is not None:
            return web.json_response({"error": "Send one document per extraction request."}, status=400)
        result = await run_json_worker(
            "thomas.tools.document_worker",
            {
                "name": name,
                "data": base64.b64encode(raw).decode("ascii"),
                "content_type": field.headers.get("Content-Type", ""),
            },
            timeout=8.0,
        )
        if result.get("ok"):
            result["document"] = await asyncio.to_thread(retain_original, bytes(raw), result["document"])
    except AttachmentError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except (ValueError, AssertionError) as exc:
        return web.json_response({"error": f"The document upload could not be read: {exc}"}, status=400)
    except WorkerFailure as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except (OSError, sqlite3.Error):
        return web.json_response(
            {"error": "The original document could not be retained. Try attaching it again."}, status=503
        )
    return web.json_response(result, status=200 if result.get("ok") else 422)
