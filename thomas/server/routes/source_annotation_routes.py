"""HTTP API for CAP-147 inline annotation editing.

Exposes the already-tested backend core -- :class:`thomas.tools.source_annotations.AnnotationStore`
-- over aiohttp so the browser panel (``web/js/source_annotation_panel.js``) can
deliver the Level-2 acceptance line end to end:

    "Add user-authored anchored annotations that open agent conversations and
    create source diffs."

Routes (all JSON):

    GET  /api/source-annotations/source?file=<path>
        The file's lines (numbered, for the click-to-select gutter) plus every
        annotation attached to it, freshly re-anchored against current content so
        moved regions follow their code and vanished regions report ``orphaned``.

    GET  /api/source-annotations[?file=<path>]
        List annotations, optionally filtered (and re-anchored) for one file.

    POST /api/source-annotations
        {file, line_start, line_end, body, suggested_edit?} -> create a
        user-authored annotation anchored to that inclusive 1-based line range.

    POST /api/source-annotations/{annotation_id}/conversation
        {conversation_ref?} -> link (and return) the agent conversation ref.

    POST /api/source-annotations/{annotation_id}/diff
        {context_lines?} -> the unified source diff applying the suggested edit.

Design notes:

* The core's state lives behind a module-level singleton accessor
  (:func:`get_source_annotation_runtime`) so every route shares one store; tests
  swap in a hermetic runtime with :func:`set_source_annotation_runtime`.
* Every filesystem edge is behind the runtime's ``normalize``/``reader`` seams.
  The production normalizer confines annotated paths to the workspace root, so a
  client cannot walk out of the repo.
* User error never yields a 500: bad paths/ranges/bodies are 400, unknown ids are
  404, and "no suggested edit"/"anchor is orphaned" are 409 conflicts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import resolve_thomas_data_dir
from thomas.tools.source_annotations import (
    STATUS_ANCHORED,
    Annotation,
    AnnotationError,
    AnnotationNotFoundError,
    AnnotationStore,
    NoSuggestedEditError,
    OrphanedAnchorError,
)

log = logging.getLogger(__name__)

APP_SOURCE_ANNOTATION_RUNTIME = web.AppKey("source_annotation_runtime", object)

# Guard rails on user-supplied input (annotating a 40 MB blob is a mistake, not a feature).
MAX_SOURCE_BYTES = 2_000_000
MAX_BODY_CHARS = 20_000
MAX_SUGGESTED_EDIT_CHARS = 200_000
MAX_CONVERSATION_REF_CHARS = 200
MAX_DIFF_CONTEXT_LINES = 25

# Errors raised by the injectable file seams for input the user got wrong.
_SOURCE_READ_ERRORS = (OSError, LookupError, UnicodeDecodeError, ValueError, TypeError)
_JSON_BODY_ERRORS = (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError)


# ---------------------------------------------------------------------------
# Runtime (the shared core state behind the routes)
# ---------------------------------------------------------------------------


@dataclass
class SourceAnnotationRuntime:
    """Everything the routes need: the core store plus its file seams.

    ``normalize`` maps a client-supplied path to the canonical key the store
    anchors against (raising :class:`ValueError` for anything it refuses), and
    ``reader`` returns the current text for such a key.
    """

    store: AnnotationStore
    normalize: Callable[[str], str]
    reader: Callable[[str], str]


_RUNTIME: SourceAnnotationRuntime | None = None


def workspace_root() -> Path:
    """Repo root: ``thomas/server/routes/<this file>`` -> three parents up."""
    return Path(__file__).resolve().parents[3]


def make_workspace_normalizer(root: Path) -> Callable[[str], str]:
    """Build a path normalizer confined to ``root`` (production seam)."""
    root_resolved = Path(root).resolve()

    def normalize(file: str) -> str:
        raw = str(file or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("file is required")
        candidate = Path(raw)
        target = candidate if candidate.is_absolute() else root_resolved / candidate
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise ValueError(f"unreadable path: {raw}") from exc
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise ValueError("file must live inside the workspace root")
        if not resolved.is_file():
            raise ValueError(f"file not found: {raw}")
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError(f"file exceeds {MAX_SOURCE_BYTES} bytes")
        return resolved.relative_to(root_resolved).as_posix()

    return normalize


def make_workspace_reader(root: Path) -> Callable[[str], str]:
    """Build a text reader for normalized (root-relative) keys (production seam)."""
    root_resolved = Path(root).resolve()

    def read(file: str) -> str:
        return (root_resolved / file).read_text(encoding="utf-8", errors="replace")

    return read


def resolve_store_path(config: Any = None) -> Path:
    """Where the annotation JSON store lives for this config/profile."""
    root = getattr(getattr(config, "memory", None), "root", "") or ""
    base = Path(str(root)).expanduser().resolve() if str(root).strip() else resolve_thomas_data_dir()
    return (Path(base) / ".thomas" / "source_annotations.json").resolve()


def build_default_runtime(config: Any = None) -> SourceAnnotationRuntime:
    """Production runtime: disk-backed store rooted at the workspace."""
    root = workspace_root()
    reader = make_workspace_reader(root)
    return SourceAnnotationRuntime(
        store=AnnotationStore(resolve_store_path(config), reader=reader),
        normalize=make_workspace_normalizer(root),
        reader=reader,
    )


def get_source_annotation_runtime(config: Any = None) -> SourceAnnotationRuntime:
    """Return the shared runtime, building the default one on first use."""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_default_runtime(config)
    return _RUNTIME


def set_source_annotation_runtime(runtime: SourceAnnotationRuntime) -> None:
    """Install a runtime (tests inject a hermetic one before registering)."""
    global _RUNTIME
    _RUNTIME = runtime


def reset_source_annotation_runtime() -> None:
    """Drop the shared runtime so the next accessor call rebuilds it."""
    global _RUNTIME
    _RUNTIME = None


def _runtime(request: web.Request) -> SourceAnnotationRuntime:
    runtime = request.app.get(APP_SOURCE_ANNOTATION_RUNTIME)
    if isinstance(runtime, SourceAnnotationRuntime):
        return runtime
    return get_source_annotation_runtime()


# ---------------------------------------------------------------------------
# Request/response helpers
# ---------------------------------------------------------------------------


def _error(message: str, code: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": message, "code": code}, status=status)


def _annotation_payload(annotation: Annotation) -> dict[str, Any]:
    data = annotation.to_dict()
    data["anchored"] = annotation.status == STATUS_ANCHORED
    data["line_start"] = annotation.anchor.line_start
    data["line_end"] = annotation.anchor.line_end
    return data


async def _read_json_body(request: web.Request) -> dict[str, Any]:
    raw = await request.text()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except _JSON_BODY_ERRORS as exc:
        log.debug("source-annotations: invalid json body: %s", type(exc).__name__)
        raise web.HTTPBadRequest(text="invalid json body") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


def _require_line(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{key} is required and must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if number < 1:
        raise ValueError(f"{key} must be >= 1")
    return number


def _require_body_text(payload: dict[str, Any]) -> str:
    value = payload.get("body")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("body must be a non-empty string")
    if len(value) > MAX_BODY_CHARS:
        raise ValueError(f"body exceeds {MAX_BODY_CHARS} characters")
    return value


def _optional_suggested_edit(payload: dict[str, Any]) -> str | None:
    value = payload.get("suggested_edit")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("suggested_edit must be a string")
    if len(value) > MAX_SUGGESTED_EDIT_CHARS:
        raise ValueError(f"suggested_edit exceeds {MAX_SUGGESTED_EDIT_CHARS} characters")
    return value


def _normalized_file(runtime: SourceAnnotationRuntime, raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("file must be a string")
    return runtime.normalize(raw)


def _source_lines(runtime: SourceAnnotationRuntime, file: str) -> list[str]:
    return str(runtime.reader(file)).split("\n")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_get_source(request: web.Request) -> web.Response:
    """GET /api/source-annotations/source?file=<path> -- lines + live annotations."""
    runtime = _runtime(request)
    try:
        file = _normalized_file(runtime, request.query.get("file", ""))
        lines = _source_lines(runtime, file)
        annotations = runtime.store.reanchor_file(file)
    except _SOURCE_READ_ERRORS as exc:
        log.info("source-annotations: rejected source request: %s", exc)
        return _error(str(exc), "invalid_file", 400)
    except AnnotationError as exc:
        log.warning("source-annotations: store failure reading %s", exc)
        return _error(str(exc), "store_error", 409)
    return web.json_response(
        {
            "ok": True,
            "file": file,
            "line_count": len(lines),
            "lines": [{"number": index, "text": text} for index, text in enumerate(lines, start=1)],
            "annotations": [_annotation_payload(a) for a in annotations],
        }
    )


async def handle_list_annotations(request: web.Request) -> web.Response:
    """GET /api/source-annotations[?file=<path>] -- list (re-anchored when scoped)."""
    runtime = _runtime(request)
    raw_file = request.query.get("file")
    if raw_file is None or not str(raw_file).strip():
        annotations = runtime.store.list_annotations()
        return web.json_response(
            {"ok": True, "file": None, "annotations": [_annotation_payload(a) for a in annotations]}
        )
    try:
        file = _normalized_file(runtime, raw_file)
        annotations = runtime.store.reanchor_file(file)
    except _SOURCE_READ_ERRORS as exc:
        log.info("source-annotations: rejected list request: %s", exc)
        return _error(str(exc), "invalid_file", 400)
    except AnnotationError as exc:
        log.warning("source-annotations: store failure listing: %s", exc)
        return _error(str(exc), "store_error", 409)
    return web.json_response({"ok": True, "file": file, "annotations": [_annotation_payload(a) for a in annotations]})


async def handle_create_annotation(request: web.Request) -> web.Response:
    """POST /api/source-annotations -- author an annotation on a line range."""
    runtime = _runtime(request)
    payload = await _read_json_body(request)
    try:
        file = _normalized_file(runtime, payload.get("file", ""))
        line_start = _require_line(payload, "line_start")
        line_end = _require_line(payload, "line_end")
        if line_end < line_start:
            raise ValueError("line_end must be >= line_start")
        body = _require_body_text(payload)
        suggested_edit = _optional_suggested_edit(payload)
        annotation = runtime.store.create_annotation(
            file,
            line_start,
            line_end,
            body,
            suggested_edit=suggested_edit,
        )
    except _SOURCE_READ_ERRORS as exc:
        log.info("source-annotations: rejected create: %s", exc)
        return _error(str(exc), "invalid_request", 400)
    except AnnotationError as exc:
        log.warning("source-annotations: store failure on create: %s", exc)
        return _error(str(exc), "store_error", 409)
    return web.json_response({"ok": True, "annotation": _annotation_payload(annotation)}, status=201)


async def handle_open_conversation(request: web.Request) -> web.Response:
    """POST /api/source-annotations/{id}/conversation -- link an agent thread."""
    runtime = _runtime(request)
    annotation_id = str(request.match_info.get("annotation_id") or "").strip()
    if not annotation_id:
        return _error("annotation_id is required", "invalid_request", 400)
    payload = await _read_json_body(request)
    raw_ref = payload.get("conversation_ref")
    if raw_ref is None:
        conversation_ref = f"thread:annotation:{annotation_id}"
    elif isinstance(raw_ref, str) and raw_ref.strip():
        conversation_ref = raw_ref.strip()
    else:
        return _error("conversation_ref must be a non-empty string", "invalid_request", 400)
    if len(conversation_ref) > MAX_CONVERSATION_REF_CHARS:
        return _error(
            f"conversation_ref exceeds {MAX_CONVERSATION_REF_CHARS} characters",
            "invalid_request",
            400,
        )
    try:
        annotation = runtime.store.open_conversation(annotation_id, conversation_ref)
    except AnnotationNotFoundError:
        return _error(f"annotation not found: {annotation_id}", "not_found", 404)
    except ValueError as exc:
        return _error(str(exc), "invalid_request", 400)
    except AnnotationError as exc:
        log.warning("source-annotations: store failure opening conversation: %s", exc)
        return _error(str(exc), "store_error", 409)
    return web.json_response(
        {
            "ok": True,
            "conversation_ref": conversation_ref,
            "annotation": _annotation_payload(annotation),
        }
    )


async def handle_emit_diff(request: web.Request) -> web.Response:
    """POST /api/source-annotations/{id}/diff -- unified diff for the suggested edit."""
    runtime = _runtime(request)
    annotation_id = str(request.match_info.get("annotation_id") or "").strip()
    if not annotation_id:
        return _error("annotation_id is required", "invalid_request", 400)
    payload = await _read_json_body(request)
    context_lines = 3
    raw_context = payload.get("context_lines")
    if raw_context is not None:
        if isinstance(raw_context, bool):
            return _error("context_lines must be an integer", "invalid_request", 400)
        try:
            context_lines = int(raw_context)
        except (TypeError, ValueError):
            return _error("context_lines must be an integer", "invalid_request", 400)
        if context_lines < 0 or context_lines > MAX_DIFF_CONTEXT_LINES:
            return _error(
                f"context_lines must be between 0 and {MAX_DIFF_CONTEXT_LINES}",
                "invalid_request",
                400,
            )
    try:
        diff = runtime.store.emit_diff(annotation_id, context_lines=context_lines)
        annotation = runtime.store.get(annotation_id)
    except AnnotationNotFoundError:
        return _error(f"annotation not found: {annotation_id}", "not_found", 404)
    except NoSuggestedEditError:
        return _error(
            "annotation carries no suggested edit; add one to emit a diff",
            "no_suggested_edit",
            409,
        )
    except OrphanedAnchorError:
        return _error(
            "annotation anchor is orphaned; the annotated lines no longer exist",
            "orphaned_anchor",
            409,
        )
    except _SOURCE_READ_ERRORS as exc:
        log.info("source-annotations: rejected diff: %s", exc)
        return _error(str(exc), "invalid_file", 400)
    except AnnotationError as exc:
        log.warning("source-annotations: store failure emitting diff: %s", exc)
        return _error(str(exc), "store_error", 409)
    return web.json_response({"ok": True, "diff": diff, "annotation": _annotation_payload(annotation)})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_source_annotation_routes(app: web.Application, config: Any = None) -> None:
    """Register the CAP-147 inline annotation API onto ``app``."""
    app[APP_SOURCE_ANNOTATION_RUNTIME] = get_source_annotation_runtime(config)
    app.router.add_get("/api/source-annotations", handle_list_annotations)
    app.router.add_post("/api/source-annotations", handle_create_annotation)
    app.router.add_get("/api/source-annotations/source", handle_get_source)
    app.router.add_post("/api/source-annotations/{annotation_id}/conversation", handle_open_conversation)
    app.router.add_post("/api/source-annotations/{annotation_id}/diff", handle_emit_diff)
