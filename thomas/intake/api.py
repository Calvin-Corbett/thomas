from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from ._internal.config import IntakeServerConfig
from ._internal.security import require_token_if_configured
from ._internal.store import IntakeStore, StoredIntake

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intake", tags=["intake"])


class ClipboardIntakeRequest(BaseModel):
    """JSON body for clipboard/screenshot intake."""

    source: str = Field(default="clipboard")
    content_type: str = Field(..., description="text/plain or image/png")
    text: str | None = None
    image_b64: str | None = Field(default=None, description="Base64 bytes. Prefer multipart for large images.")
    ocr_text: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> ClipboardIntakeRequest:
        if self.content_type.startswith("text") and not self.text:
            raise ValueError("text payload requires `text`")
        if self.content_type.startswith("image") and not self.image_b64:
            raise ValueError("image payload requires `image_b64` (or use multipart)")
        return self


class ClipboardIntakeResponse(BaseModel):
    ok: bool = True
    item_id: str
    deduped: bool = False
    chat_id: str | None = None
    summary: str
    action_suggestion: str


class ActiveChatRequest(BaseModel):
    chat_id: str


class ActiveChatResponse(BaseModel):
    chat_id: str | None = None


class ListItemsResponse(BaseModel):
    items: list[dict]


@dataclass(frozen=True)
class IntakeItem:
    item_id: str
    source: str
    content_type: str
    text: str | None
    blob: bytes | None
    ocr_text: str | None
    meta: dict[str, Any]
    content_hash: str


class DefaultIntakeProcessor:
    """Safe fallback processor: returns a useful summary + suggestion."""

    def process(self, item: IntakeItem, chat_id: str | None) -> dict[str, str]:
        if item.content_type.startswith("text") and item.text:
            txt = item.text.strip().replace("\r\n", "\n")
            snip = txt if len(txt) <= 280 else (txt[:280] + "…")
            return {
                "summary": f"Captured clipboard text ({len(txt)} chars). Snippet: {snip}",
                "action_suggestion": "I can extract action items, draft a reply, or turn this into structured notes.",
            }

        if item.content_type.startswith("image"):
            w = item.meta.get("width")
            h = item.meta.get("height")
            dims = f"{w}x{h}" if w and h else "unknown size"
            ocr = (item.ocr_text or "").strip()
            if ocr:
                ocr_snip = ocr if len(ocr) <= 280 else (ocr[:280] + "…")
                return {
                    "summary": f"Captured image ({dims}). OCR text: {ocr_snip}",
                    "action_suggestion": "I can summarize, extract fields, or convert OCR into clean notes.",
                }
            return {
                "summary": f"Captured image ({dims}). No OCR text available.",
                "action_suggestion": "Tell me what you want from this image (summary, extraction, instructions).",
            }

        return {"summary": f"Captured intake: {item.content_type}.", "action_suggestion": "Tell me what to do with it."}


def _cfg(request: Request) -> IntakeServerConfig:
    cfg = getattr(request.app.state, "intake_server_config", None)
    if cfg is None:
        cfg = IntakeServerConfig.from_env()
        request.app.state.intake_server_config = cfg
    return cfg


def _get_store(request: Request) -> IntakeStore:
    store = getattr(request.app.state, "intake_store", None)
    if store is None:
        store = IntakeStore()
        request.app.state.intake_store = store
    return store


def _get_active_chat_id(request: Request) -> str | None:
    hdr = request.headers.get("x-thomas-chat-id")
    if hdr:
        return hdr.strip() or None
    return getattr(request.app.state, "active_chat_id", None)


def _set_active_chat_id(request: Request, chat_id: str) -> None:
    request.app.state.active_chat_id = chat_id.strip()


def _get_processor(request: Request) -> Any:
    proc = getattr(request.app.state, "intake_processor", None)
    if proc is not None:
        return proc
    adapter = getattr(request.app.state, "chat_adapter", None)
    if adapter is not None:
        return adapter
    proc = DefaultIntakeProcessor()
    request.app.state.intake_processor = proc
    return proc


def _decode_image_b64(b64: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        return base64.b64decode(b64)


def _as_item_dict(st: StoredIntake) -> dict:
    return {
        "item_id": st.item_id,
        "created_at": st.created_at,
        "source": st.source,
        "content_type": st.content_type,
        "text": st.text,
        "blob_bytes": st.blob_bytes,
        "ocr_text": st.ocr_text,
        "meta": json.loads(st.meta_json),
        "content_hash": st.content_hash,
        "idempotency_key": st.idempotency_key,
        "chat_id": st.chat_id,
    }


async def _parse_request_any(request: Request) -> tuple[ClipboardIntakeRequest, bytes | None]:
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        data = await request.json()
        payload = ClipboardIntakeRequest(**data)
        blob = _decode_image_b64(payload.image_b64) if payload.image_b64 else None
        return payload, blob

    if "multipart/form-data" in ctype:
        form = await request.form()
        source = str(form.get("source") or "clipboard")
        content_type = str(form.get("content_type") or "image/png")
        ocr_text = form.get("ocr_text")
        meta_json = form.get("meta_json")
        meta: dict[str, Any] = {}
        if meta_json:
            try:
                meta = json.loads(str(meta_json))
            except json.JSONDecodeError:
                meta = {"meta_json_parse_error": True, "raw_meta_json": str(meta_json)}

        file = form.get("file")
        if file is None:
            raise HTTPException(status_code=400, detail="multipart requires file field 'file'")

        blob = await file.read()  # type: ignore[attr-defined]
        payload = ClipboardIntakeRequest(
            source=source,
            content_type=content_type,
            text=None,
            image_b64=base64.b64encode(blob).decode("ascii"),
            ocr_text=str(ocr_text) if ocr_text else None,
            meta=meta,
        )
        return payload, blob

    raise HTTPException(
        status_code=415, detail="Unsupported content-type. Use application/json or multipart/form-data."
    )


@router.post("/active", response_model=ActiveChatResponse)
async def set_active_chat(payload: ActiveChatRequest, request: Request) -> ActiveChatResponse:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)
    _set_active_chat_id(request, payload.chat_id)
    return ActiveChatResponse(chat_id=payload.chat_id)


@router.get("/active", response_model=ActiveChatResponse)
async def get_active_chat(request: Request) -> ActiveChatResponse:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)
    return ActiveChatResponse(chat_id=_get_active_chat_id(request))


@router.get("/items", response_model=ListItemsResponse)
async def list_items(request: Request, limit: int = 50, chat_id: str | None = None) -> ListItemsResponse:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)
    store = _get_store(request)
    items = store.list_recent(limit=int(limit), chat_id=chat_id)
    return ListItemsResponse(items=[_as_item_dict(it) for it in items])


@router.get("/items/{item_id}")
async def get_item(request: Request, item_id: str) -> dict:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)
    store = _get_store(request)
    it = store.get(item_id)
    if not it:
        raise HTTPException(status_code=404, detail="item not found")
    return _as_item_dict(it)


@router.post("/items/{item_id}/reprocess", response_model=ClipboardIntakeResponse)
async def reprocess_item(request: Request, item_id: str) -> ClipboardIntakeResponse:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)
    store = _get_store(request)
    st = store.get(item_id)
    if not st:
        raise HTTPException(status_code=404, detail="item not found")

    blob = store.read_blob(item_id)
    meta = json.loads(st.meta_json)
    item = IntakeItem(
        item_id=st.item_id,
        source=st.source,
        content_type=st.content_type,
        text=st.text,
        blob=blob,
        ocr_text=st.ocr_text,
        meta=meta,
        content_hash=st.content_hash,
    )

    processor = _get_processor(request)
    chat_id = st.chat_id or _get_active_chat_id(request)

    try:
        if hasattr(processor, "append_to_chat") and chat_id:
            processor.append_to_chat(chat_id, item)  # type: ignore[attr-defined]
            result = processor.respond(chat_id, item) if hasattr(processor, "respond") else {}
        else:
            result = processor.process(item, chat_id)  # type: ignore[attr-defined]
        summary = str(result.get("summary", "")).strip() or "Reprocessed."
        action = str(result.get("action_suggestion", "")).strip() or "Tell me what to do with it."
    except Exception as e:
        logger.exception("Reprocess failed")
        summary = f"Reprocess failed: {type(e).__name__}"
        action = "Check server logs."

    return ClipboardIntakeResponse(
        ok=True, item_id=item_id, deduped=False, chat_id=chat_id, summary=summary, action_suggestion=action
    )


@router.post("/clipboard", response_model=ClipboardIntakeResponse)
async def intake_clipboard(request: Request) -> ClipboardIntakeResponse:
    cfg = _cfg(request)
    require_token_if_configured(request, cfg)

    payload, blob = await _parse_request_any(request)
    chat_id = _get_active_chat_id(request)
    idempotency_key = request.headers.get("idempotency-key") or None

    if blob is not None and len(blob) > cfg.max_bytes:
        raise HTTPException(status_code=413, detail=f"Image too large (>{cfg.max_bytes} bytes).")

    store = _get_store(request)
    content_hash = store.compute_hash(payload.content_type, payload.text, blob, payload.ocr_text)

    existing = store.find_by_idempotency_or_hash(idempotency_key, content_hash, window_s=cfg.dedupe_window_s)
    if existing:
        return ClipboardIntakeResponse(
            ok=True,
            item_id=existing.item_id,
            deduped=True,
            chat_id=existing.chat_id,
            summary="Duplicate intake ignored (deduped).",
            action_suggestion="If you intended to resend, add a unique Idempotency-Key header.",
        )

    item_id = str(uuid.uuid4())
    store.insert(
        item_id=item_id,
        source=payload.source,
        content_type=payload.content_type,
        text=payload.text,
        blob=blob,
        ocr_text=payload.ocr_text,
        meta=payload.meta or {},
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        chat_id=chat_id,
    )

    item = IntakeItem(
        item_id=item_id,
        source=payload.source,
        content_type=payload.content_type,
        text=payload.text,
        blob=blob,
        ocr_text=payload.ocr_text,
        meta=payload.meta or {},
        content_hash=content_hash,
    )

    processor = _get_processor(request)

    try:
        if hasattr(processor, "append_to_chat") and chat_id:
            processor.append_to_chat(chat_id, item)  # type: ignore[attr-defined]
            result = processor.respond(chat_id, item) if hasattr(processor, "respond") else {}
        else:
            result = processor.process(item, chat_id)  # type: ignore[attr-defined]
        summary = str(result.get("summary", "")).strip() or "Intake received."
        action = str(result.get("action_suggestion", "")).strip() or "Tell me what you want done with it."
    except Exception as e:
        logger.exception("Intake processing failed")
        summary = f"Intake stored but processing failed: {type(e).__name__}"
        action = "Check server logs. The intake is saved and can be reprocessed."

    return ClipboardIntakeResponse(
        ok=True, item_id=item_id, deduped=False, chat_id=chat_id, summary=summary, action_suggestion=action
    )
