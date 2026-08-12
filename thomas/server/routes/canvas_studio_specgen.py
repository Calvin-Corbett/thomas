"""Spec transforms for the UI Studio Canvas API.

Split out of ``canvas_studio_routes`` so each module stays small and cohesive:
this file is the pure, route-free logic — deterministic ``spec -> React+Tailwind``
codegen (mirrors the in-browser ``specToReact`` so server and preview agree) plus
the wave-2 LLM helpers that turn a prompt or a sketch *into* a spec. The HTTP
handlers, persistence, and registration live in ``canvas_studio_routes``.

Architecture: server -> core only. We import ``LLMClient`` and config from
``thomas.core`` (the allowed direction) and never reach into ``thomas.forge`` or
``thomas.tools``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# deterministic codegen  (mirrors the client's specToReact / tokens.css so the
# server route and the in-browser preview produce identical output)
# --------------------------------------------------------------------------- #
_NODE_TYPES = (
    "container",
    "text",
    "button",
    "image",
    "input",
    "card",
    "list",
    "nav",
    "table",
    "modal",
    "shape",
    "pen",
)


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _num(v: Any, fallback: float = 0) -> float:
    try:
        n = float(v)
        return n if n == n else fallback  # NaN guard
    except (TypeError, ValueError):
        return fallback


def _sp_to_tw(px: Any) -> str:
    n = round(_num(px) / 4)
    return str(max(0, min(int(n), 96)))


def _resolve_color(value: Any) -> str:
    v = str(value or "")
    if re.match(r"^color\.[A-Za-z0-9_]+$", v):
        return "var(--" + v.replace(".", "-") + ")"
    return v


def _tag_for(node_type: str) -> str:
    return {
        "button": "button",
        "input": "input",
        "image": "img",
        "nav": "nav",
        "list": "ul",
        "text": "span",
    }.get(node_type, "div")


def _tailwind_classes(node: dict[str, Any]) -> str:
    cls: list[str] = []
    layout = node.get("layout") or {}
    rect = node.get("rect") or {}
    absolute = bool(node.get("absolute"))
    mode = layout.get("mode")
    if not absolute and mode in ("flex", "grid"):
        if mode == "flex":
            cls.append("flex")
            cls.append("flex-row" if layout.get("direction") == "row" else "flex-col")
            cls.append("gap-" + _sp_to_tw(layout.get("gap")))
            cls.append("items-" + str(layout.get("align") or "start"))
            cls.append("justify-" + str(layout.get("justify") or "start"))
        else:
            cls.append("grid")
            cls.append("gap-" + _sp_to_tw(layout.get("gap")))
        if _num(layout.get("padding")) > 0:
            cls.append("p-" + _sp_to_tw(layout.get("padding")))
    if absolute:
        cls.append("absolute")
        cls.append(f"left-[{round(_num(rect.get('x')))}px]")
        cls.append(f"top-[{round(_num(rect.get('y')))}px]")
    cls.append(f"w-[{round(_num(rect.get('w')))}px]")
    cls.append(f"h-[{round(_num(rect.get('h')))}px]")
    return " ".join(cls)


def _style_attr(node: dict[str, Any]) -> str:
    s = node.get("style") or {}
    parts: list[str] = []
    if str(s.get("bg") or ""):
        parts.append(f"backgroundColor: {json.dumps(_resolve_color(s.get('bg')))}")
    if str(s.get("color") or ""):
        parts.append(f"color: {json.dumps(_resolve_color(s.get('color')))}")
    if _num(s.get("radius")) > 0:
        parts.append(f"borderRadius: {json.dumps(str(round(_num(s.get('radius')))) + 'px')}")
    if str(s.get("border") or ""):
        parts.append(f"border: {json.dumps('1px solid ' + _resolve_color(s.get('border')))}")
    if s.get("opacity") is not None and _num(s.get("opacity"), 1) != 1:
        parts.append(f"opacity: {_num(s.get('opacity'), 1)}")
    if _num(s.get("fontSize")) and _num(s.get("fontSize")) != 14:
        parts.append(f"fontSize: {json.dumps(str(round(_num(s.get('fontSize')))) + 'px')}")
    if _num(s.get("fontWeight")) and _num(s.get("fontWeight")) != 400:
        parts.append(f"fontWeight: {round(_num(s.get('fontWeight')))}")
    if str(s.get("shadow") or ""):
        parts.append(f"boxShadow: {json.dumps(str(s.get('shadow')))}")
    return "{{ " + ", ".join(parts) + " }}" if parts else ""


def _render_react_node(node: dict[str, Any], depth: int) -> str:
    pad = "  " * depth
    ntype = node.get("type") if node.get("type") in _NODE_TYPES else "container"
    tag = _tag_for(ntype)
    cls = _tailwind_classes(node)
    style = _style_attr(node)
    attrs = f" className={json.dumps(cls)}"
    if style:
        attrs += f" style={style}"
    if node.get("absolute"):
        attrs += " /* TODO: absolute — verify responsiveness */"
    content = node.get("content") or {}
    if ntype == "image":
        return f"{pad}<img{attrs} src={json.dumps(str(content.get('src') or ''))} alt={json.dumps(str(node.get('name') or ''))} />"
    if ntype == "input":
        return f"{pad}<input{attrs} placeholder={json.dumps(str(content.get('placeholder') or ''))} />"
    if ntype == "pen":
        return f'{pad}{{/* freehand drawing "{_esc(node.get("name"))}" — render as <svg><path/></svg> in wave 2 */}}'
    kids = node.get("children") if isinstance(node.get("children"), list) else []
    text = str(content.get("text") or "")
    if not kids:
        return f"{pad}<{tag}{attrs}>{_esc(text)}</{tag}>"
    inner: list[str] = []
    if text:
        inner.append(pad + "  " + _esc(text))
    for child in kids:
        inner.append(_render_react_node(child, depth + 1))
    return f"{pad}<{tag}{attrs}>\n" + "\n".join(inner) + f"\n{pad}</{tag}>"


def spec_to_react(spec: dict[str, Any]) -> str:
    root = spec.get("root") or {"type": "container", "rect": {"x": 0, "y": 0, "w": 0, "h": 0}, "children": []}
    lines = [
        "// Auto-generated by Thomas UI Studio — deterministic spec -> React + Tailwind",
        f'// Source of truth: UiStudioSpec "{spec.get("name", "")}" ({spec.get("id", "")})',
        "// Tokens are emitted to tokens.css — import it once at your app root.",
        "import './tokens.css';",
        "",
        "export default function GeneratedUI() {",
        "  return (",
        _render_react_node(root, 2),
        "  );",
        "}",
        "",
    ]
    return "\n".join(lines)


def spec_to_tokens_css(spec: dict[str, Any]) -> str:
    tokens = spec.get("tokens") or {}
    lines = [":root {"]
    for group in ("color", "space", "radius", "font"):
        obj = tokens.get(group) or {}
        if not isinstance(obj, dict):
            continue
        for key, val in obj.items():
            if group in ("space", "radius"):
                val = f"{round(_num(val))}px"
            lines.append(f"  --{group}-{key}: {val};")
    lines.append("}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# wave-2 LLM prompts (schema-pinned so output is bounded) + helpers
# --------------------------------------------------------------------------- #
_SCHEMA_HINT = (
    "Output ONLY valid JSON for a UiStudioSpec with this shape: "
    '{"version":1,"id":"spec_..","name":str,'
    '"canvas":{"width":int,"height":int,"background":str},'
    '"grid":{"size":8,"snap":true},'
    '"tokens":{"color":{..},"space":{..},"radius":{..},"font":{..}},'
    '"root":{"id":"node_..","type":"container","name":"Root",'
    '"rect":{"x":0,"y":0,"w":int,"h":int},'
    '"layout":{"mode":"flex|grid|none","direction":"col|row","gap":int,"padding":int,'
    '"align":str,"justify":str,"sizing":"fixed|fill|hug"},'
    '"absolute":false,"style":{..},"content":{"text":str},"owner":"ai","children":[..]}}. '
    "Every node id must be unique. type is one of: "
    + ", ".join(_NODE_TYPES)
    + ". rect coords are integers in canvas pixels. Prefer flow layout (flex/grid) over absolute."
)
_TEMPLATE_SYSTEM_PROMPT = (
    "You are a senior UI layout designer for Thomas. Given a description, produce a "
    "clean, realistic UI as a UiStudioSpec block tree. " + _SCHEMA_HINT
)
_SKETCH_SYSTEM_PROMPT = (
    "You are a UI digitizer. Convert the attached hand-drawn / wireframe sketch into a "
    "UiStudioSpec block tree that reproduces its layout. " + _SCHEMA_HINT
)


def _build_llm(root: Path, profile: str) -> Any | None:
    """Construct an LLMClient for ``profile`` (server->core import, guarded)."""
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_client import LLMClient

        cfg = load_config(Path(root) / "thomas.toml")
        model_cfg = cfg.get_model(profile or None)
        return LLMClient(model_cfg)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        log.warning("UI Studio: could not build LLM client: %s", exc)
        return None


def _extract_spec_json(text: str) -> dict[str, Any] | None:
    """Parse a UiStudioSpec out of a model reply (tolerant of code fences)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    # strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        # else take the outermost {...}
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None
