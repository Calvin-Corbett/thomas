"""aiohttp routes for the in-flow PR review surface (CAP-149, Level 2).

Exposes :mod:`thomas.tools.pr_review` over HTTP so the browser panel
(``thomas/server/web/js/pr_review_panel.js``) can drive the full acceptance
line: *risk-ranked hunks, comments, approval, and fix handoff*.

Routes
------
``POST   /api/pr-review/reviews``
    Ingest a unified diff and open a review. ``201`` + the ranked snapshot.
``GET    /api/pr-review/reviews``
    List open reviews (id, title, hunk count, approval state).
``GET    /api/pr-review/reviews/{review_id}``
    The full review snapshot (hunks highest-risk-first).
``POST   /api/pr-review/reviews/{review_id}/comments``
    Add a root comment anchored to a hunk (optionally ``blocking``).
``POST   /api/pr-review/reviews/{review_id}/comments/{comment_id}/replies``
    Reply into an existing thread.
``POST   /api/pr-review/reviews/{review_id}/comments/{comment_id}/resolve``
    Resolve a comment's whole thread.
``POST   /api/pr-review/reviews/{review_id}/comments/{comment_id}/fix-task``
    Hand an unresolved comment off as a structured fix task bound to its hunk.
``POST   /api/pr-review/reviews/{review_id}/approve``
    Approve. ``409`` + ``blocking_reasons`` while the gate holds.

State lives in a module-level :class:`PrReviewStore` singleton (see
:func:`get_review_store`) so every handler shares the same reviews; the store is
also stashed on the ``app`` under :data:`PR_REVIEW_STORE_KEY` so a test can
inject a clean one. All user error is reported as JSON with a 4xx status --
never a 500.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from thomas.tools.pr_review import (
    ApprovalBlockedError,
    DiffParseError,
    PrReview,
    PrReviewError,
    UnknownCommentError,
    UnknownHunkError,
)

log = logging.getLogger(__name__)

__all__ = [
    "PR_REVIEW_CONFIG_KEY",
    "PR_REVIEW_STORE_KEY",
    "PrReviewStore",
    "get_review_store",
    "register_pr_review_routes",
    "reset_review_store",
]

PR_REVIEW_STORE_KEY = web.AppKey("pr_review_store", object)
PR_REVIEW_CONFIG_KEY = web.AppKey("pr_review_config", object)

API_PREFIX = "/api/pr-review"

_MAX_DIFF_BYTES = 2_000_000
_MAX_BODY_CHARS = 8_000
_MAX_AUTHOR_CHARS = 120
_MAX_TITLE_CHARS = 200
_MAX_MARKERS = 200


# --------------------------------------------------------------------------- #
# Store (module-level singleton shared by every handler)
# --------------------------------------------------------------------------- #
class PrReviewStore:
    """In-memory registry of open :class:`PrReview` instances."""

    def __init__(self) -> None:
        self._reviews: dict[str, PrReview] = {}
        self._titles: dict[str, str] = {}
        self._order: list[str] = []
        self._seq = 0

    def open_review(
        self,
        diff_text: str,
        *,
        title: str = "",
        security_markers: list[str] | None = None,
    ) -> tuple[str, PrReview]:
        """Ingest ``diff_text`` into a new review. Raises :class:`DiffParseError`."""

        kwargs: dict[str, Any] = {"diff_text": diff_text}
        if security_markers:
            kwargs["security_markers"] = frozenset(security_markers)
        review = PrReview(**kwargs)
        self._seq += 1
        review_id = f"pr{self._seq}"
        self._reviews[review_id] = review
        self._titles[review_id] = title or f"Review {review_id}"
        self._order.append(review_id)
        return review_id, review

    def get(self, review_id: str) -> PrReview:
        """Return the review or raise :class:`KeyError`."""

        return self._reviews[review_id]

    def title(self, review_id: str) -> str:
        return self._titles.get(review_id, review_id)

    def summaries(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for review_id in self._order:
            review = self._reviews[review_id]
            out.append(
                {
                    "review_id": review_id,
                    "title": self._titles.get(review_id, review_id),
                    "hunk_count": len(review.ranked_hunks),
                    "approved": review.approved,
                    "can_approve": review.can_approve(),
                }
            )
        return out

    def clear(self) -> None:
        self._reviews.clear()
        self._titles.clear()
        self._order.clear()
        self._seq = 0


_STORE: PrReviewStore | None = None


def get_review_store() -> PrReviewStore:
    """Accessor for the process-wide review store (created on first use)."""

    global _STORE
    if _STORE is None:
        _STORE = PrReviewStore()
    return _STORE


def reset_review_store() -> PrReviewStore:
    """Replace the singleton with an empty store (test seam)."""

    global _STORE
    _STORE = PrReviewStore()
    return _STORE


# --------------------------------------------------------------------------- #
# JSON error helpers -- user error is always 4xx, never a 500
# --------------------------------------------------------------------------- #
def _error_body(code: str, message: str, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {"ok": False, "error": code, "message": message}
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _bad_request(code: str, message: str, extra: dict[str, Any] | None = None) -> web.HTTPBadRequest:
    return web.HTTPBadRequest(text=_error_body(code, message, extra), content_type="application/json")


def _not_found(code: str, message: str) -> web.HTTPNotFound:
    return web.HTTPNotFound(text=_error_body(code, message), content_type="application/json")


def _conflict(code: str, message: str, extra: dict[str, Any] | None = None) -> web.HTTPConflict:
    return web.HTTPConflict(text=_error_body(code, message, extra), content_type="application/json")


# --------------------------------------------------------------------------- #
# Request parsing / validation
# --------------------------------------------------------------------------- #
async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
        log.debug("pr-review: unreadable json body: %s", type(exc).__name__)
        raise _bad_request("invalid_json", "request body must be valid JSON")
    if not isinstance(payload, dict):
        raise _bad_request("invalid_json", "request body must be a JSON object")
    return payload


def _require_text(payload: dict[str, Any], key: str, *, max_chars: int, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(code, f"field '{key}' must be a non-empty string")
    if len(value) > max_chars:
        raise _bad_request(code, f"field '{key}' exceeds {max_chars} characters")
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str, *, max_chars: int, default: str = "") -> str:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise _bad_request("invalid_field", f"field '{key}' must be a string")
    if len(value) > max_chars:
        raise _bad_request("invalid_field", f"field '{key}' exceeds {max_chars} characters")
    return value.strip() or default


def _read_bool(payload: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    raise _bad_request("invalid_field", f"field '{key}' must be a boolean")


def _read_markers(payload: dict[str, Any]) -> list[str] | None:
    raw = payload.get("security_markers")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise _bad_request("invalid_field", "field 'security_markers' must be a list of strings")
    if len(raw) > _MAX_MARKERS:
        raise _bad_request("invalid_field", f"field 'security_markers' accepts at most {_MAX_MARKERS} entries")
    markers: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise _bad_request("invalid_field", "field 'security_markers' must contain non-empty strings")
        markers.append(item.strip().lower())
    return markers


def _store_for(request: web.Request) -> PrReviewStore:
    store = request.app.get(PR_REVIEW_STORE_KEY)
    if isinstance(store, PrReviewStore):
        return store
    return get_review_store()


def _lookup_review(request: web.Request) -> tuple[str, PrReview, PrReviewStore]:
    review_id = str(request.match_info.get("review_id") or "")
    store = _store_for(request)
    try:
        review = store.get(review_id)
    except KeyError:
        raise _not_found("unknown_review", f"no such review: {review_id}")
    return review_id, review, store


def _review_payload(review_id: str, review: PrReview, store: PrReviewStore) -> dict[str, Any]:
    snapshot = review.snapshot()
    snapshot["review_id"] = review_id
    snapshot["title"] = store.title(review_id)
    return snapshot


def _comment_dict(comment: Any) -> dict[str, Any]:
    return {
        "comment_id": comment.comment_id,
        "hunk_id": comment.hunk_id,
        "author": comment.author,
        "body": comment.body,
        "blocking": comment.blocking,
        "resolved": comment.resolved,
        "parent_id": comment.parent_id,
    }


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
async def handle_open_review(request: web.Request) -> web.Response:
    """POST /api/pr-review/reviews -- ingest a unified diff into a ranked review."""

    payload = await _read_json_object(request)
    diff_text = payload.get("diff")
    if diff_text is None:
        diff_text = payload.get("diff_text")
    if not isinstance(diff_text, str) or not diff_text.strip():
        raise _bad_request("missing_diff", "field 'diff' must be a non-empty unified diff string")
    if len(diff_text) > _MAX_DIFF_BYTES:
        raise _bad_request("diff_too_large", f"diff exceeds {_MAX_DIFF_BYTES} characters")

    title = _optional_text(payload, "title", max_chars=_MAX_TITLE_CHARS)
    markers = _read_markers(payload)

    store = _store_for(request)
    try:
        review_id, review = store.open_review(diff_text, title=title, security_markers=markers)
    except DiffParseError as exc:
        raise _bad_request("invalid_diff", str(exc))

    return web.json_response(
        {"ok": True, "review": _review_payload(review_id, review, store)},
        status=201,
    )


async def handle_list_reviews(request: web.Request) -> web.Response:
    """GET /api/pr-review/reviews -- the open reviews."""

    store = _store_for(request)
    return web.json_response({"ok": True, "reviews": store.summaries()})


async def handle_get_review(request: web.Request) -> web.Response:
    """GET /api/pr-review/reviews/{review_id} -- the ranked snapshot."""

    review_id, review, store = _lookup_review(request)
    return web.json_response({"ok": True, "review": _review_payload(review_id, review, store)})


async def handle_add_comment(request: web.Request) -> web.Response:
    """POST /api/pr-review/reviews/{review_id}/comments -- root comment on a hunk."""

    review_id, review, store = _lookup_review(request)
    payload = await _read_json_object(request)
    hunk_id = _require_text(payload, "hunk_id", max_chars=64, code="missing_hunk_id")
    body = _require_text(payload, "body", max_chars=_MAX_BODY_CHARS, code="missing_body")
    author = _optional_text(payload, "author", max_chars=_MAX_AUTHOR_CHARS, default="reviewer")
    blocking = _read_bool(payload, "blocking")

    try:
        comment = review.add_comment(hunk_id, author, body, blocking=blocking)
    except UnknownHunkError as exc:
        raise _not_found("unknown_hunk", str(exc))

    return web.json_response(
        {
            "ok": True,
            "comment": _comment_dict(comment),
            "review": _review_payload(review_id, review, store),
        },
        status=201,
    )


async def handle_reply_comment(request: web.Request) -> web.Response:
    """POST .../comments/{comment_id}/replies -- reply into an existing thread."""

    review_id, review, store = _lookup_review(request)
    comment_id = str(request.match_info.get("comment_id") or "")
    payload = await _read_json_object(request)
    body = _require_text(payload, "body", max_chars=_MAX_BODY_CHARS, code="missing_body")
    author = _optional_text(payload, "author", max_chars=_MAX_AUTHOR_CHARS, default="reviewer")
    blocking = _read_bool(payload, "blocking")

    try:
        reply = review.reply(comment_id, author, body, blocking=blocking)
    except UnknownCommentError as exc:
        raise _not_found("unknown_comment", str(exc))

    return web.json_response(
        {
            "ok": True,
            "comment": _comment_dict(reply),
            "review": _review_payload(review_id, review, store),
        },
        status=201,
    )


async def handle_resolve_comment(request: web.Request) -> web.Response:
    """POST .../comments/{comment_id}/resolve -- resolve the whole thread."""

    review_id, review, store = _lookup_review(request)
    comment_id = str(request.match_info.get("comment_id") or "")

    try:
        resolved = review.resolve_comment(comment_id)
    except UnknownCommentError as exc:
        raise _not_found("unknown_comment", str(exc))

    return web.json_response(
        {
            "ok": True,
            "resolved": [_comment_dict(c) for c in resolved],
            "review": _review_payload(review_id, review, store),
        }
    )


async def handle_create_fix_task(request: web.Request) -> web.Response:
    """POST .../comments/{comment_id}/fix-task -- hand off a structured fix task."""

    review_id, review, store = _lookup_review(request)
    comment_id = str(request.match_info.get("comment_id") or "")
    payload = await _read_json_object(request) if request.can_read_body else {}
    instruction = payload.get("instruction")
    if instruction is not None:
        if not isinstance(instruction, str) or not instruction.strip():
            raise _bad_request("invalid_field", "field 'instruction' must be a non-empty string when provided")
        if len(instruction) > _MAX_BODY_CHARS:
            raise _bad_request("invalid_field", f"field 'instruction' exceeds {_MAX_BODY_CHARS} characters")
        instruction = instruction.strip()

    try:
        task = review.create_fix_task(comment_id, instruction=instruction)
    except UnknownCommentError as exc:
        raise _not_found("unknown_comment", str(exc))
    except PrReviewError as exc:
        raise _conflict("fix_handoff_rejected", str(exc))

    return web.json_response(
        {
            "ok": True,
            "fix_task": task.as_dict(),
            "review": _review_payload(review_id, review, store),
        },
        status=201,
    )


async def handle_approve(request: web.Request) -> web.Response:
    """POST /api/pr-review/reviews/{review_id}/approve -- gated approval."""

    review_id, review, store = _lookup_review(request)
    payload = await _read_json_object(request) if request.can_read_body else {}
    approver = _optional_text(payload, "approver", max_chars=_MAX_AUTHOR_CHARS, default="reviewer")

    try:
        review.approve(approver)
    except ApprovalBlockedError as exc:
        raise _conflict(
            "approval_blocked",
            str(exc),
            {
                "blocking_reasons": list(exc.reasons),
                "review": _review_payload(review_id, review, store),
            },
        )

    return web.json_response(
        {
            "ok": True,
            "approved": True,
            "approved_by": review.approved_by,
            "review": _review_payload(review_id, review, store),
        }
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register_pr_review_routes(app: web.Application, config: Any = None) -> None:
    """Register the in-flow PR review surface on ``app``."""

    store = app.get(PR_REVIEW_STORE_KEY)
    if not isinstance(store, PrReviewStore):
        store = get_review_store()
        app[PR_REVIEW_STORE_KEY] = store
    app[PR_REVIEW_CONFIG_KEY] = config

    router = app.router
    router.add_post(f"{API_PREFIX}/reviews", handle_open_review)
    router.add_get(f"{API_PREFIX}/reviews", handle_list_reviews)
    router.add_get(f"{API_PREFIX}/reviews/{{review_id}}", handle_get_review)
    router.add_post(f"{API_PREFIX}/reviews/{{review_id}}/comments", handle_add_comment)
    router.add_post(f"{API_PREFIX}/reviews/{{review_id}}/comments/{{comment_id}}/replies", handle_reply_comment)
    router.add_post(f"{API_PREFIX}/reviews/{{review_id}}/comments/{{comment_id}}/resolve", handle_resolve_comment)
    router.add_post(f"{API_PREFIX}/reviews/{{review_id}}/comments/{{comment_id}}/fix-task", handle_create_fix_task)
    router.add_post(f"{API_PREFIX}/reviews/{{review_id}}/approve", handle_approve)

    log.info("PR review routes registered (%s/reviews)", API_PREFIX)
