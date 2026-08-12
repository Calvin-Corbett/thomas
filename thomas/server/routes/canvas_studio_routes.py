"""HTTP API for the UI Studio Canvas (Tab B of the app_builder workbench).

Architecture: server -> core only. We import ``LLMClient`` and config from
``thomas.core`` (the allowed direction) and never reach into ``thomas.forge`` or
``thomas.tools``. The route factory mirrors ``evolve_loop_routes`` exactly:
``build_canvas_studio_handlers(app, *, require_api_access, root_resolver)`` +
``register_canvas_studio_routes(...)`` so the routes are unit-testable against a
temp ``.thomas/`` directory.

The pure spec transforms — deterministic ``spec -> React+Tailwind`` codegen and
the wave-2 LLM ``prompt/sketch -> spec`` helpers — live in
``canvas_studio_specgen`` (kept separate so each module stays small). They are
re-exported here (``spec_to_react`` / ``spec_to_tokens_css``) so this module's
public surface is unchanged.

MVP routes (no LLM, deterministic):
    POST /api/canvas/spec            -> persist a UiStudioSpec atomically
    GET  /api/canvas/spec/{id}       -> load a saved spec
    POST /api/canvas/codegen         -> spec -> React+Tailwind + tokens.css

WAVE-2 routes (LLM; resolve the persisted default profile, read result['text']):
    POST /api/canvas/template        -> {prompt, spec?, selection_id?} -> spec
    POST /api/canvas/spec-from-sketch-> vision: {image_data_url} -> spec

Persistence uses the SessionStore idiom: write to a temp file in the same
directory then ``os.replace`` for atomicity. Specs live under
``<root>/.thomas/canvas/<id>.json``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.routes.canvas_studio_specgen import (
    _SKETCH_SYSTEM_PROMPT,
    _TEMPLATE_SYSTEM_PROMPT,
    _build_llm,
    _extract_spec_json,
    spec_to_react,
    spec_to_tokens_css,
)

log = logging.getLogger(__name__)

# Re-exported so importers (and the test suite) can keep using
# ``canvas_studio_routes.spec_to_react`` / ``spec_to_tokens_css``.
__all__ = [
    "build_canvas_studio_handlers",
    "register_canvas_studio_routes",
    "spec_to_react",
    "spec_to_tokens_css",
]

_REPO_MARKERS = ("pyproject.toml", "thomas", ".git")
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


# --------------------------------------------------------------------------- #
# root / profile resolution (mirrors evolve_loop_routes)
# --------------------------------------------------------------------------- #
def _default_repo_root() -> Path:
    here = Path.cwd()
    for base in (here, *here.parents):
        if any((base / marker).exists() for marker in _REPO_MARKERS):
            return base
    return here


def _canvas_dir(root: Path) -> Path:
    return Path(root) / ".thomas" / "canvas"


def _resolve_default_profile(root: Path) -> str:
    """Resolve the user's persisted default model profile (evolve idiom).

    A UI-Studio AI action should think with the model the user picked in the
    chat UI. Resolved once at the API boundary; fully guarded so a config/import
    failure never hard-fails the route (it degrades to an empty profile, and the
    LLM routes then return a clear error instead of crashing).
    """
    try:
        from thomas.core.config import load_config
        from thomas.core.model_resolution import resolve_effective_model

        cfg = load_config(Path(root) / "thomas.toml")
        profile, _ = resolve_effective_model(cfg, user_id="default")
        return str(profile or "").strip()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return ""


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        # A malformed body is treated as empty; only decode faults belong here,
        # a transport failure should still surface.
        return {}
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------- #
# persistence (atomic temp-file + os.replace — SessionStore idiom)
# --------------------------------------------------------------------------- #
def _safe_spec_id(spec: dict[str, Any]) -> str:
    raw = str(spec.get("id") or "").strip()
    if raw and _ID_RE.match(raw):
        return raw
    return "spec_" + uuid.uuid4().hex


def _write_spec(root: Path, spec: dict[str, Any]) -> str:
    directory = _canvas_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    spec_id = _safe_spec_id(spec)
    spec["id"] = spec_id
    target = directory / f"{spec_id}.json"
    tmp = directory / f".{spec_id}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return spec_id


def _read_spec(root: Path, spec_id: str) -> dict[str, Any] | None:
    if not _ID_RE.match(spec_id or ""):
        return None
    path = _canvas_dir(root) / f"{spec_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# handler factory
# --------------------------------------------------------------------------- #
def build_canvas_studio_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> dict[str, Any]:
    """Build the canvas-studio handlers as a name->handler map."""

    def _root() -> Path:
        return Path(root_resolver())

    async def save_spec(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _json_body(request)
        spec = body.get("spec") if isinstance(body.get("spec"), dict) else body
        if not isinstance(spec, dict) or not spec.get("root"):
            return web.json_response({"ok": False, "error": "missing spec.root"}, status=400)
        spec_id = _write_spec(_root(), spec)
        return web.json_response({"ok": True, "id": spec_id})

    async def load_spec(request: web.Request) -> web.Response:
        require_api_access(request)
        spec_id = str(request.match_info.get("id", ""))
        spec = _read_spec(_root(), spec_id)
        if spec is None:
            return web.json_response({"ok": False, "error": "not found"}, status=404)
        return web.json_response({"ok": True, "spec": spec})

    async def codegen(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _json_body(request)
        spec = body.get("spec") if isinstance(body.get("spec"), dict) else body
        if not isinstance(spec, dict) or not spec.get("root"):
            return web.json_response({"ok": False, "error": "missing spec.root"}, status=400)
        react = spec_to_react(spec)
        tokens = spec_to_tokens_css(spec)
        return web.json_response(
            {"ok": True, "files": {"App.jsx": react, "tokens.css": tokens}, "react": react, "tokens_css": tokens}
        )

    async def template(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _json_body(request)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"ok": False, "error": "missing prompt"}, status=400)
        root = _root()
        profile = str(body.get("profile") or "").strip() or _resolve_default_profile(root)
        llm = _build_llm(root, profile)
        if llm is None:
            return web.json_response({"ok": False, "error": "no model available", "profile": profile}, status=503)
        current = body.get("spec") if isinstance(body.get("spec"), dict) else {}
        messages = [
            {"role": "system", "content": _TEMPLATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompt
                + "\n\nCurrent spec (JSON, may be empty):\n"
                + json.dumps(current, ensure_ascii=False),
            },
        ]
        try:
            result = await llm.chat(messages)
        # The set every other model call in the server names: transport/auth
        # faults arrive as OSError, provider and failover faults as RuntimeError,
        # and a malformed provider payload as TypeError/ValueError. Surfaced as a
        # clean 502, never a 500.
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("UI Studio template LLM call failed: %s", exc)
            return web.json_response({"ok": False, "error": "llm call failed"}, status=502)
        spec = _extract_spec_json(result.get("text", ""))
        if spec is None:
            return web.json_response({"ok": False, "error": "model did not return valid spec JSON"}, status=502)
        return web.json_response({"ok": True, "spec": spec, "profile": profile})

    async def spec_from_sketch(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _json_body(request)
        image_url = str(body.get("image_data_url") or "").strip()
        if not image_url.startswith("data:"):
            return web.json_response({"ok": False, "error": "missing image_data_url (data URI)"}, status=400)
        root = _root()
        profile = str(body.get("profile") or "").strip() or _resolve_default_profile(root)
        llm = _build_llm(root, profile)
        if llm is None:
            return web.json_response({"ok": False, "error": "no model available", "profile": profile}, status=503)
        extra = str(body.get("prompt") or "").strip()
        # vision message: image_url data-URI is auto-converted to an Anthropic
        # base64 image block by LLMClient (llm_client.py image_url handling).
        user_content = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": (_SKETCH_SYSTEM_PROMPT + ("\n\n" + extra if extra else ""))},
        ]
        messages = [{"role": "user", "content": user_content}]
        try:
            result = await llm.chat(messages)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:  # same set as the template call above
            log.warning("UI Studio sketch LLM call failed: %s", exc)
            return web.json_response({"ok": False, "error": "llm call failed"}, status=502)
        spec = _extract_spec_json(result.get("text", ""))
        if spec is None:
            return web.json_response({"ok": False, "error": "model did not return valid spec JSON"}, status=502)
        return web.json_response({"ok": True, "spec": spec, "profile": profile})

    return {
        "save_spec": save_spec,
        "load_spec": load_spec,
        "codegen": codegen,
        "template": template,
        "spec_from_sketch": spec_from_sketch,
    }


def register_canvas_studio_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    """Register the UI Studio Canvas API onto the aiohttp app."""
    handlers = build_canvas_studio_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    app.router.add_post("/api/canvas/spec", handlers["save_spec"])
    app.router.add_get("/api/canvas/spec/{id}", handlers["load_spec"])
    app.router.add_post("/api/canvas/codegen", handlers["codegen"])
    # wave-2 LLM routes (inert without a caller; resolve the persisted profile)
    app.router.add_post("/api/canvas/template", handlers["template"])
    app.router.add_post("/api/canvas/spec-from-sketch", handlers["spec_from_sketch"])
