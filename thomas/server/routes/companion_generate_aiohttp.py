"""Generate a companion app from a description, and install it.

This is the loop the rest of Infinite exists to serve: you describe something,
Thomas writes a surface for it, and an icon appears on the home screen. The
generated document is not trusted because Thomas wrote it — it goes through the
same signing, verification, and policy compliance as any other bundle, and it
runs in the same sandboxed frame with no network of its own.

Nothing here bypasses a gate. The only thing that is new is who writes the HTML.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.companion.audit import CompanionAuditLog
from thomas.companion.kernel import CompanionKernel
from thomas.companion.registry import ModuleRegistry
from thomas.companion.studio import BundleStudio
from thomas.companion.update import BundleVerifier, UpdateApplier
from thomas.server.routes.companion_runtime import _run_compliance_check

log = logging.getLogger(__name__)

RequireAccessFn = Callable[[web.Request], Any]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

MAX_DESCRIPTION_CHARS = 1200
MAX_DOCUMENT_BYTES = 256_000
MODULE_ID_PREFIX = "app."

# Generated apps get storage plus the model call. network.egress is what gates
# `thomas.ask` (see companion_surface_aiohttp), and an app that cannot reason is
# the thing that makes this different from a bookmark. It is still only ever a
# tool-less completion.
GENERATED_PERMISSIONS = ["network.egress", "storage.read", "storage.write", "ui.render"]

_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

SYSTEM_PROMPT = """You write single-file apps for Thomas Infinite, a private phone companion.

Return ONE complete HTML document and nothing else. No prose, no code fences.

The document runs inside a sandboxed frame with NO network access:
- No <script src>, no <link>, no <img src> to any URL, no fetch, no XHR, no webfonts.
- Anything fetched from the network is blocked and the app will look broken.
- Images only as inline SVG or data: URIs.

THOMAS'S DESIGN SYSTEM IS ALREADY LOADED. Do not write a colour palette, a font
stack, a reset, or button/input styling — it is there, and restyling it makes the
app look foreign. Write markup that uses it:

  <h1>            page title (one per app)
  <p class="t-sub">  one line under the title
  <div class="t-card">   grouped content
  <div class="t-stat">42</div><div class="t-stat-label">glasses today</div>
  <button>        primary action, full width
  <button class="t-btn-ghost">  secondary action
  <div class="t-btn-row">  two buttons side by side
  <input>, <select>, <textarea>   already styled
  <ul>/<li>       rows; <span class="t-item-meta"> for the trailing value
  <div class="t-empty">  the nothing-here-yet state
  <span class="t-chip">  small status pill
  .t-good / .t-warn / .t-bad  for semantic text colour

Variables available if you need them: --c-bg --c-surface --c-border --c-text
--c-dim --c-muted --c-accent --c-accent-ink --c-accent-soft --c-danger --c-warn
--c-success --r-card --r-control.

Only add a <style> block for layout genuinely specific to this app (a grid, a
chart, a calendar). Keep it short. Never override the palette or the font.

A `thomas` object is already available. Do not define it. It is async:
- await thomas.storage.get(key)        -> the stored value, or undefined
- await thomas.storage.set(key, value) -> persists any JSON-serialisable value
- await thomas.storage.remove(key)
- await thomas.storage.keys()          -> array of keys
- await thomas.ask(prompt)             -> a string answer from Thomas
Storage is private to this app and survives restarts. Use it for anything the
user enters — an app that forgets what they typed is not finished. Load existing
data on startup and render it before the user touches anything.

Build for a phone held in one hand. Show the real state of the data, handle the
empty case, and make it genuinely useful for the thing described — not a demo."""


def _kernel_from_config(config: Any) -> CompanionKernel:
    return CompanionKernel.from_config(config)


def _secret() -> str:
    return str(os.environ.get("THOMAS_COMPANION_UPDATE_SECRET") or "").strip()


def _require_signature(kernel: CompanionKernel) -> bool:
    return bool(kernel.load_policy().get("require_signed_updates", True))


def _slugify_module_id(text: str) -> str:
    base = _SLUG_RE.sub("-", str(text or "").strip().lower()).strip("-")
    base = base[:40].strip("-") or "surface"
    candidate = f"{MODULE_ID_PREFIX}{base}"
    # Contract requires ^[a-z0-9][a-z0-9_.-]{2,63}$ and the prefix supplies the
    # leading alphanumeric, so only length needs bounding.
    return candidate[:64]


def _unique_module_id(registry: ModuleRegistry, base_id: str) -> str:
    if registry.get(base_id) is None:
        return base_id
    for suffix in range(2, 100):
        candidate = f"{base_id}-{suffix}"[:64]
        if registry.get(candidate) is None:
            return candidate
    raise web.HTTPConflict(text=f"too many apps named like {base_id}")


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.match(str(text or ""))
    return match.group("body") if match else str(text or "")


def _extract_document(raw: str) -> str:
    """Pull the HTML document out of a model reply."""
    body = _strip_fences(raw).strip()
    lowered = body.lower()
    start = lowered.find("<!doctype")
    if start == -1:
        start = lowered.find("<html")
    if start > 0:
        body = body[start:]
    return body.strip()


def _looks_like_document(text: str) -> bool:
    lowered = str(text or "").lower()
    return "<html" in lowered or "<!doctype html" in lowered or "<body" in lowered


def _clean_title(text: str) -> str:
    """Names come from the model, so keep markup characters out of them.

    The name is rendered with textContent today, but app names elsewhere in this
    codebase are interpolated into innerHTML. Stripping here means a generated
    name can never become the thing that makes that matter.
    """
    stripped = re.sub(r"[<>&\"'\\]+", "", str(text or ""))
    return re.sub(r"\s+", " ", stripped).strip()


def _derive_title(description: str, document: str) -> str:
    match = re.search(r"<title>(.*?)</title>", document, re.IGNORECASE | re.DOTALL)
    if match:
        title = _clean_title(match.group(1))
        if title:
            return title[:60]
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", description).split()
    return (" ".join(words[:4]) or "New App").title()[:60]


def register_companion_generate_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
    config: Any,
) -> None:
    """Register POST /api/companion/v1/surface/generate."""

    async def api_surface_generate(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        payload = await read_json(request)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="payload must be an object")

        description = str(payload.get("description") or payload.get("prompt") or "").strip()
        if not description:
            raise web.HTTPBadRequest(text="missing description")
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_DESCRIPTION_CHARS,
                actual_size=len(description),
                text=f"description exceeds {MAX_DESCRIPTION_CHARS} characters",
            )

        document = await _generate_document(config, description)
        if not _looks_like_document(document):
            return web.json_response(
                {"ok": False, "error": "the model did not return an HTML document"},
                status=502,
            )
        if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            return web.json_response(
                {"ok": False, "error": "generated document is too large to install"},
                status=413,
            )

        display_name = _clean_title(payload.get("display_name") or "")[:60] or _derive_title(
            description, document
        )
        registry = ModuleRegistry(kernel)
        module_id = _unique_module_id(registry, _slugify_module_id(display_name))

        studio = BundleStudio(kernel, secret=_secret(), require_signature=_require_signature(kernel))
        try:
            build = studio.build_bundle(
                {
                    "module": {
                        "id": module_id,
                        "version": "0.1.0",
                        "slots": ["home.main"],
                        "permissions": list(GENERATED_PERMISSIONS),
                        "ui_schema_version": "0.1.0",
                        "display_name": display_name,
                        "description": description[:200],
                        "surface_type": "surface",
                    },
                    "surface_html": document,
                    "release_notes": "generated by Thomas",
                }
            )
        except (ValueError, OSError) as exc:
            log.warning("Surface build failed for %s: %s", module_id, exc)
            return web.json_response({"ok": False, "error": f"build failed: {exc}"}, status=400)

        # StudioBuildResult carries the path as a string; downstream wants a Path.
        bundle_dir = Path(build.bundle_dir)
        verifier = BundleVerifier(kernel, secret=_secret(), require_signature=_require_signature(kernel))
        verify_report = verifier.verify_bundle(bundle_dir)
        if not verify_report.ok:
            return web.json_response(
                {"ok": False, "error": "generated bundle failed verification",
                 "errors": list(verify_report.errors), "bundle_dir": str(bundle_dir)},
                status=400,
            )

        compliance = _run_compliance_check(
            kernel=kernel,
            payload=payload,
            bundle_dir=bundle_dir,
            verify_report=verify_report,
            actor="companion-generate",
            peer_identity="local",
        )
        if not bool(compliance.get("ok")):
            return web.json_response(
                {"ok": False, "error": "generated app failed policy compliance",
                 "compliance": compliance, "bundle_dir": str(bundle_dir)},
                status=400,
            )

        result = UpdateApplier(kernel, verifier=verifier).apply_bundle(bundle_dir, dry_run=False)
        CompanionAuditLog(kernel).append(
            "surface.generate",
            actor="companion-generate",
            peer_identity="local",
            details={
                "module_id": module_id,
                "display_name": display_name,
                "ok": bool(result.get("ok")),
                "bytes": len(document.encode("utf-8")),
            },
        )
        if not bool(result.get("ok")):
            return web.json_response(
                {"ok": False, "error": "install failed", "result": result}, status=400
            )

        row = registry.get(module_id)
        return web.json_response(
            {
                "ok": True,
                "module_id": module_id,
                "display_name": display_name,
                "module": row.to_dict() if row is not None else None,
            }
        )

    app.router.add_post("/api/companion/v1/surface/generate", api_surface_generate)


async def _generate_document(config: Any, description: str) -> str:
    """Ask the configured model for one self-contained HTML document."""
    try:
        from thomas.core.llm_client import LLMClient
        from thomas.core.llm_shared import LLMError
    except ImportError as exc:
        raise web.HTTPServiceUnavailable(text="model client unavailable") from exc

    try:
        model_cfg = config.get_model(getattr(config, "default_model", "") or None)
        client = LLMClient(model_cfg)
    except (AttributeError, KeyError, ValueError) as exc:
        log.warning("Surface generate could not resolve a model: %s", exc)
        raise web.HTTPServiceUnavailable(text="no model configured") from exc

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": description},
    ]
    try:
        result = await client.chat(messages, tools=None)
    except (LLMError, OSError, TimeoutError, ValueError, RuntimeError) as exc:
        log.warning("Surface generate model call failed: %s", exc)
        raise web.HTTPBadGateway(text="model call failed") from exc

    return _extract_document(str(result.get("text") or ""))
