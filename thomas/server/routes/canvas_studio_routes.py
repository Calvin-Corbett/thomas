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

Saving and reading a spec, the repo root and the default profile live in ``thomas.server.canvas_studio_shared``,
which the workspace helpers also use. Specs live under ``<root>/.thomas/canvas/<id>.json``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.canvas_studio_shared import (
    _default_repo_root,
    _read_spec,
    _resolve_default_profile,
    _write_spec,
)
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


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        # A malformed body is treated as empty; only decode faults belong here,
        # a transport failure should still surface.
        return {}
    return body if isinstance(body, dict) else {}


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
