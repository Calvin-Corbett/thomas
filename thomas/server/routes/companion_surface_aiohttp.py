"""Surface host and bridge API for companion ``surface`` modules.

A ``surface`` module ships an HTML document instead of a JSON component tree.
The companion shell renders that document inside a sandboxed iframe that has
no same-origin privileges and no network of its own, so everything the surface
needs from the outside world arrives through this bridge.

The trust model:

* The document is served with a CSP that denies ``connect-src`` outright. A
  surface therefore cannot call out on its own — the shell brokers every call.
* Each bridge call names a module, and the handler re-reads that module's
  declared permissions from the registry before doing anything. A surface
  cannot widen its own grant by asking nicely.
* The store is addressed by ``module_id``; a surface never supplies a path, so
  one module's data is unreachable from another.
* ``ask`` runs a plain completion with ``tools=None``. Generated app code gets
  reasoning, never the tool belt.

These endpoints live here rather than in ``companion_aiohttp.py`` because that
module is already over its documented line budget.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from thomas.companion.kernel import CompanionKernel
from thomas.companion.registry import ModuleRegistry, ModuleState
from thomas.companion.runtime import entrypoint_fs_path
from thomas.companion.store import ModuleStore, ModuleStoreError, ModuleStoreQuotaError

log = logging.getLogger(__name__)

RequireAccessFn = Callable[[web.Request], Any]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

PERM_STORAGE_READ = "storage.read"
PERM_STORAGE_WRITE = "storage.write"
# `ask` is gated on network.egress: it is the module reaching outside itself for
# data, and it is the closest existing grant. A dedicated `agent.ask` permission
# would also need adding to every policy profile — tracked as follow-up.
PERM_ASK = "network.egress"

SURFACE_TYPE_SURFACE = "surface"
MAX_PROMPT_CHARS = 4000

# default-src 'none' plus no connect-src is the load-bearing line: the frame has
# an opaque origin (sandbox without allow-same-origin) AND cannot open a socket.
SURFACE_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'self'"
)


# Injected into every surface document. A generated app calls
# `thomas.storage.set(...)` / `thomas.ask(...)` and never sees postMessage.
# The frame has no network of its own, so this is its only way out.
SURFACE_META_CSP = (
    '<meta http-equiv="Content-Security-Policy" content="'
    "default-src &#39;none&#39;; "
    "script-src &#39;unsafe-inline&#39;; "
    "style-src &#39;unsafe-inline&#39;; "
    "img-src data: blob:; "
    "font-src data:; "
    "connect-src &#39;none&#39;; "
    "form-action &#39;none&#39;; "
    "base-uri &#39;none&#39;"
    '">'
)

# Thomas's design system, inlined into every surface.
#
# A surface has no network, so it cannot link tokens.css — and asking a model to
# reproduce a palette from a prompt gets a different-looking app every time.
# Injecting it makes the look structural instead of aspirational: apps come out
# consistent, and the model writes markup rather than a stylesheet.
#
# Values mirror the Nebula Core block in css/tokens.css. The font stack is
# system-ui deliberately: no webfont can be fetched here, and companion.html does
# not load Manrope either, so this matches how the shell actually renders.
#
# This is a floor, not a ceiling — it is injected first, so an app's own <style>
# still wins.
SURFACE_BASE_CSS = """<style>
:root{
  --c-bg:#070912; --c-surface:rgba(255,255,255,.04); --c-surface-2:rgba(255,255,255,.08);
  --c-border:rgba(255,255,255,.10); --c-border-2:rgba(255,255,255,.17);
  --c-text:#eef0fb; --c-dim:rgba(238,240,251,.66); --c-muted:rgba(238,240,251,.42);
  --c-accent:#8b8cff; --c-accent-ink:#0a0b16; --c-accent-soft:rgba(139,140,255,.16);
  --c-accent-line:rgba(139,140,255,.45); --c-composer-bg:rgba(16,19,34,.86);
  --c-danger:#ff9a9a; --c-warn:#e2b25f; --c-success:#47d7ac;
  --r-card:14px; --r-control:12px; --t-gap:14px;
  --font-sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color-scheme:dark;
}
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--c-bg); color:var(--c-text); font-family:var(--font-sans);
  font-size:15px; line-height:1.5;
  padding:20px 16px calc(20px + env(safe-area-inset-bottom));
  -webkit-font-smoothing:antialiased;
}
h1{font-size:1.45rem; font-weight:700; letter-spacing:-.01em; margin:0 0 4px}
h2{font-size:1.05rem; font-weight:650; margin:22px 0 8px}
p{margin:0 0 12px; color:var(--c-dim)}
.t-sub{margin:0 0 20px; color:var(--c-muted); font-size:.86rem}
.t-card{
  background:var(--c-surface); border:1px solid var(--c-border);
  border-radius:var(--r-card); padding:16px; margin-bottom:var(--t-gap);
}
.t-stat{
  font-size:3rem; font-weight:800; line-height:1.05; text-align:center;
  font-variant-numeric:tabular-nums; letter-spacing:-.02em; margin:6px 0 2px;
}
.t-stat-label{text-align:center; color:var(--c-muted); font-size:.8rem; margin-bottom:2px}
button,.t-btn{
  display:block; width:100%; min-height:48px; padding:13px 18px;
  border:0; border-radius:var(--r-control); background:var(--c-accent);
  color:var(--c-accent-ink); font-family:inherit; font-size:1rem; font-weight:650;
  cursor:pointer; margin-bottom:10px;
}
button:active,.t-btn:active{filter:brightness(.94)}
.t-btn-ghost{
  background:transparent; border:1px solid var(--c-border-2); color:var(--c-dim); font-weight:600;
}
.t-btn-row{display:flex; gap:10px}
.t-btn-row>button,.t-btn-row>.t-btn{margin-bottom:0}
input,select,textarea,.t-input{
  width:100%; min-height:46px; padding:11px 13px;
  background:var(--c-composer-bg); border:1px solid var(--c-border-2);
  border-radius:var(--r-control); color:var(--c-text);
  font-family:inherit; font-size:16px; /* 16px stops iOS zooming on focus */
  margin-bottom:10px;
}
input:focus,select:focus,textarea:focus{outline:none; border-color:var(--c-accent-line)}
input::placeholder,textarea::placeholder{color:var(--c-muted)}
ul,ol,.t-list{list-style:none; margin:0; padding:0}
li,.t-item{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:12px 14px; margin-bottom:8px;
  background:var(--c-surface); border:1px solid var(--c-border); border-radius:var(--r-control);
}
.t-item-meta{color:var(--c-muted); font-size:.8rem; font-variant-numeric:tabular-nums}
.t-empty{padding:26px 16px; text-align:center; color:var(--c-muted); font-size:.86rem}
.t-chip{
  display:inline-block; padding:4px 10px; border-radius:999px;
  background:var(--c-accent-soft); border:1px solid var(--c-accent-line);
  color:var(--c-text); font-size:.72rem; font-weight:600;
}
.t-good{color:var(--c-success)} .t-warn{color:var(--c-warn)} .t-bad{color:var(--c-danger)}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
</style>
"""

BRIDGE_SHIM = """<script>
(function () {
  var pending = {};
  var seq = 0;
  function call(method, params) {
    return new Promise(function (resolve, reject) {
      var id = "s" + (++seq);
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage(
        { __thomasBridge: 1, id: id, method: method, params: params || {} },
        "*"
      );
    });
  }
  window.addEventListener("message", function (event) {
    var msg = event.data;
    if (!msg || msg.__thomasBridge !== 1 || !msg.id) return;
    var slot = pending[msg.id];
    if (!slot) return;
    delete pending[msg.id];
    if (msg.ok) slot.resolve(msg.result);
    else slot.reject(new Error(msg.error || "bridge call failed"));
  });
  window.thomas = {
    storage: {
      get: function (key) { return call("storage.get", { key: key }); },
      set: function (key, value) { return call("storage.set", { key: key, value: value }); },
      remove: function (key) { return call("storage.delete", { key: key }); },
      keys: function () { return call("storage.keys", {}); }
    },
    ask: function (prompt) { return call("ask", { prompt: prompt }); },
    close: function () { return call("close", {}); }
  };
})();
</script>
"""


def _kernel_from_config(config: Any) -> CompanionKernel:
    return CompanionKernel.from_config(config)


def _inject_bridge_shim(html: str) -> str:
    """Put the CSP, the design system, and the bridge shim ahead of the app.

    The meta CSP matters because the shell renders this document via srcdoc (the
    only way to authenticate the fetch — an iframe navigation cannot carry a
    bearer header). srcdoc content does not inherit the response CSP header, so
    the policy has to travel inside the document to survive that trip.
    """
    preamble = SURFACE_META_CSP + SURFACE_BASE_CSS + BRIDGE_SHIM
    lowered = html.lower()
    head_open = lowered.find("<head>")
    if head_open != -1:
        cut = head_open + len("<head>")
        return html[:cut] + preamble + html[cut:]
    return preamble + html


def _module_or_404(kernel: CompanionKernel, module_id: str) -> ModuleState:
    row = ModuleRegistry(kernel).get(str(module_id or "").strip())
    if row is None:
        raise web.HTTPNotFound(text=f"module not found: {module_id}")
    if row.status != "enabled":
        raise web.HTTPForbidden(text=f"module is not enabled: {module_id}")
    return row


def _require_permission(module: ModuleState, permission: str) -> None:
    if permission not in list(module.permissions or []):
        raise web.HTTPForbidden(
            text=f"module {module.module_id} does not declare permission {permission}"
        )


def _payload_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _store_error_response(exc: ModuleStoreError) -> web.Response:
    status = 413 if isinstance(exc, ModuleStoreQuotaError) else 400
    return web.json_response({"ok": False, "error": str(exc)}, status=status)


def register_companion_surface_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
    config: Any,
) -> None:
    """Register /api/companion/v1/surface/* — document host and bridge calls."""

    def _store(kernel: CompanionKernel) -> ModuleStore:
        return ModuleStore(kernel)

    async def api_surface_document(request: web.Request) -> web.Response:
        """Serve a surface module's HTML for the sandboxed frame."""
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module_id = str(request.match_info.get("module_id") or "").strip()
        module = _module_or_404(kernel, module_id)

        if module.surface_type != SURFACE_TYPE_SURFACE:
            raise web.HTTPBadRequest(
                text=f"module {module_id} is surface_type={module.surface_type}, not surface"
            )
        try:
            path = entrypoint_fs_path(kernel, module)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=f"invalid entrypoint: {exc}") from exc
        if not path.exists() or not path.is_file():
            raise web.HTTPNotFound(text=f"surface document missing for {module_id}")

        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise web.HTTPInternalServerError(text=f"cannot read surface: {exc}") from exc

        body = _inject_bridge_shim(body)

        return web.Response(
            text=body,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Content-Security-Policy": SURFACE_CSP,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )

    async def api_surface_storage_get(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module = _module_or_404(kernel, request.match_info.get("module_id") or "")
        _require_permission(module, PERM_STORAGE_READ)
        payload = _payload_dict(await read_json(request))
        try:
            value = _store(kernel).get(module.module_id, str(payload.get("key") or ""))
        except ModuleStoreError as exc:
            return _store_error_response(exc)
        return web.json_response(
            {"ok": True, "module_id": module.module_id, "key": payload.get("key"), "value": value}
        )

    async def api_surface_storage_set(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module = _module_or_404(kernel, request.match_info.get("module_id") or "")
        _require_permission(module, PERM_STORAGE_WRITE)
        payload = _payload_dict(await read_json(request))
        if "value" not in payload:
            raise web.HTTPBadRequest(text="missing value")
        try:
            result = _store(kernel).set(
                module.module_id, str(payload.get("key") or ""), payload.get("value")
            )
        except ModuleStoreError as exc:
            return _store_error_response(exc)
        return web.json_response({"ok": True, **result})

    async def api_surface_storage_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module = _module_or_404(kernel, request.match_info.get("module_id") or "")
        _require_permission(module, PERM_STORAGE_WRITE)
        payload = _payload_dict(await read_json(request))
        try:
            removed = _store(kernel).delete(module.module_id, str(payload.get("key") or ""))
        except ModuleStoreError as exc:
            return _store_error_response(exc)
        return web.json_response({"ok": True, "module_id": module.module_id, "deleted": removed})

    async def api_surface_storage_keys(request: web.Request) -> web.Response:
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module = _module_or_404(kernel, request.match_info.get("module_id") or "")
        _require_permission(module, PERM_STORAGE_READ)
        store = _store(kernel)
        try:
            keys = store.keys(module.module_id)
            usage = store.usage(module.module_id)
        except ModuleStoreError as exc:
            return _store_error_response(exc)
        return web.json_response(
            {"ok": True, "module_id": module.module_id, "keys": keys, "usage": usage}
        )

    async def api_surface_ask(request: web.Request) -> web.Response:
        """One-shot completion for a surface. No tools, no history, no elevation."""
        require_api_access(request)
        kernel = _kernel_from_config(config)
        module = _module_or_404(kernel, request.match_info.get("module_id") or "")
        _require_permission(module, PERM_ASK)

        payload = _payload_dict(await read_json(request))
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise web.HTTPBadRequest(text="missing prompt")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_PROMPT_CHARS,
                actual_size=len(prompt),
                text=f"prompt exceeds {MAX_PROMPT_CHARS} characters",
            )

        try:
            from thomas.core.llm_client import LLMClient
            from thomas.core.llm_shared import LLMError
        except ImportError as exc:
            log.warning("Surface ask unavailable: %s", exc)
            raise web.HTTPServiceUnavailable(text="model client unavailable") from exc

        try:
            model_cfg = config.get_model(getattr(config, "default_model", "") or None)
            client = LLMClient(model_cfg)
        except (AttributeError, KeyError, ValueError) as exc:
            log.warning("Surface ask could not resolve a model: %s", exc)
            raise web.HTTPServiceUnavailable(text="no model configured") from exc

        system = (
            f"You are answering for the companion app '{module.display_name}' "
            f"(module {module.module_id} v{module.version}). Answer only what the app asks. "
            "You have no tools and cannot act on the host."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        try:
            result = await client.chat(messages, tools=None)
        except (LLMError, OSError, TimeoutError, ValueError, RuntimeError) as exc:
            log.warning("Surface ask failed for %s: %s", module.module_id, exc)
            return web.json_response({"ok": False, "error": "model call failed"}, status=502)

        return web.json_response(
            {"ok": True, "module_id": module.module_id, "text": str(result.get("text") or "")}
        )

    base = "/api/companion/v1/surface/{module_id}"
    app.router.add_get(f"{base}/document", api_surface_document)
    app.router.add_post(f"{base}/storage/get", api_surface_storage_get)
    app.router.add_post(f"{base}/storage/set", api_surface_storage_set)
    app.router.add_post(f"{base}/storage/delete", api_surface_storage_delete)
    app.router.add_get(f"{base}/storage/keys", api_surface_storage_keys)
    app.router.add_post(f"{base}/ask", api_surface_ask)
