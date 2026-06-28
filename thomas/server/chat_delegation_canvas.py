"""Canvas worker — a fast, STREAMING design/visual generator.

When the user asks for something visual (a chart, UI, diagram, drawing, design),
the task manager routes the task here instead of the slow file-building agent worker.
This worker does NOT build files step-by-step with tools — it streams a single
self-contained HTML document straight to the Canvas, so the user WATCHES it draw
itself live (the Claude-design effect). Its growing output is held in a per-execution
store that the /delegations poll surfaces, and the final HTML is written to the task
workspace so it also becomes a normal downloadable deliverable.
"""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable

# --------------------------------------------------------------------------- #
# Per-execution streaming store (process-local; the poll handler reads it).
# The canvas worker runs in the same process as the web app, so a module-level
# dict guarded by a lock is visible to both the worker and the poll handler.
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_STORE: dict[str, dict[str, Any]] = {}

# The gpt-5.5 / codex-OAuth provider silently HANGS (no first token, no error) when
# multiple streaming calls overlap. Serialize canvas generations through one lock so
# they never compete, and reuse one LLM client per profile to avoid connection churn.
_CANVAS_LLM_LOCK = asyncio.Lock()
_LLM_CACHE: dict[str, Any] = {}


def canvas_start(execution_id: str, title: str = "") -> None:
    with _LOCK:
        _STORE[str(execution_id)] = {"html": "", "status": "streaming", "title": str(title or "")}


def canvas_append(execution_id: str, chunk: str) -> None:
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["html"] += str(chunk or "")


def canvas_set_html(execution_id: str, html: str) -> None:
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["html"] = str(html or "")


def canvas_set_shell(execution_id: str, shell: dict[str, Any]) -> None:
    """Switch a canvas into live-CONSTRUCTION mode: the frontend mounts an empty shell sized
    to ``shell`` and elements stream in one-by-one (watch-it-build), instead of waiting for the
    finished doc."""
    sd = dict(shell or {})
    sw = int(_num(sd.get("w"), 720)) or 720
    sh = int(_num(sd.get("h"), 520)) or 520
    sd["html"] = build_construction_shell(sw, sh, str(sd.get("bg") or "#ffffff"), int(_num(sd.get("stagger"), 70)))
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["shell"] = sd
            rec["mode"] = "construct"
            rec.setdefault("elements", [])


def canvas_add_element(execution_id: str, layer: str, html: str) -> None:
    """Append one rendered element ({layer:'svg'|'div', html}) for the frontend to stream into
    the live construction shell the moment the planner defines it."""
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec.setdefault("elements", []).append({"layer": str(layer), "html": str(html)})


def canvas_finish(execution_id: str, status: str = "done") -> None:
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["status"] = str(status or "done")


def canvas_get(execution_id: str) -> dict[str, Any] | None:
    """Return {'html','status','title'} for an execution, or None if not a canvas task."""
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        return dict(rec) if rec else None


# --------------------------------------------------------------------------- #
# Canvas-task detection (server side). Mirrors the frontend's detectCanvasIntent
# so the task manager routes the same things the Canvas expects to render.
# --------------------------------------------------------------------------- #
# A FALLBACK HINT only — not a router. Routing is the model's call via send_task(surface=...);
# this is consulted ONLY when no surface was declared (narration backstop / forced launch).
# Kept to COMPOUND/unambiguous visual forms so it never grabs document/code/planning requests
# that merely carry a verb like design/draw/render (the old over-trigger bug).
_VISUAL_RE = re.compile(
    r"\b(pie\s*chart|bar\s*chart|line\s*chart|flow\s*chart|"
    r"mock\s*up|wireframe|infographic|logo|landing\s*page|illustration|"
    r"picture\s+of|image\s+of|ui\s+(?:design|mockup)|diagram\s+of)\b",
    re.I,
)


def is_canvas_task(prompt: str) -> bool:
    """True when the request is a visual/design task the Canvas should render live."""
    return bool(_VISUAL_RE.search(str(prompt or "")))


# --------------------------------------------------------------------------- #
# Deterministic renderer — compile a planner choreography spec (JSON) into ONE
# self-contained, self-animating HTML document with NO second LLM call. This is
# the speed win: the render is mechanical (the old _RENDER_SYSTEM was a fixed
# 7-point contract), so code does it instantly and identically every time. The 7
# motion verbs + a `raw` SVG escape hatch keep it general (no chart categories).
# --------------------------------------------------------------------------- #
import json as _json
import math as _math

_MOTION_CLASSES = {"sweep", "grow-y", "grow-x", "draw-stroke", "scale-in", "rise-fade", "count-up", "none"}


def _esc(s: Any) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def parse_spec(text: str) -> dict[str, Any] | None:
    """Tolerantly pull the planner's JSON spec out of its reply (it may add a fence
    or stray words). Returns the dict, or None if no usable object is found."""
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    candidate = fence.group(1) if fence else raw
    # find the outermost {...}
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = candidate[start : end + 1]
    try:
        obj = _json.loads(blob)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def _donut_path(cx: float, cy: float, outer: float, inner: float, a0: float, a1: float) -> str:
    """SVG path `d` for a donut wedge from angle a0 to a1 (degrees). Computed in code
    so the render needs no per-wedge JS."""

    def polar(r: float, a: float) -> tuple[float, float]:
        rad = a * _math.pi / 180.0
        return (cx + r * _math.cos(rad), cy + r * _math.sin(rad))

    large = 1 if (a1 - a0) % 360 > 180 else 0
    p1 = polar(outer, a0)
    p2 = polar(outer, a1)
    if inner and inner > 0:
        p3 = polar(inner, a1)
        p4 = polar(inner, a0)
        return (
            f"M{p1[0]:.2f} {p1[1]:.2f} A{outer:.2f} {outer:.2f} 0 {large} 1 {p2[0]:.2f} {p2[1]:.2f} "
            f"L{p3[0]:.2f} {p3[1]:.2f} A{inner:.2f} {inner:.2f} 0 {large} 0 {p4[0]:.2f} {p4[1]:.2f} Z"
        )
    return f"M{cx:.2f} {cy:.2f} L{p1[0]:.2f} {p1[1]:.2f} A{outer:.2f} {outer:.2f} 0 {large} 1 {p2[0]:.2f} {p2[1]:.2f} Z"


def _points_to_d(points: list[Any]) -> str:
    pts = [p for p in points if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not pts:
        return ""
    d = f"M{_num(pts[0][0]):.2f} {_num(pts[0][1]):.2f}"
    for p in pts[1:]:
        d += f" L{_num(p[0]):.2f} {_num(p[1]):.2f}"
    return d


def _render_element(el: Any, i: int, sw: int, sh: int) -> tuple[str, str] | None:
    """Render ONE choreography element to (layer, html-snippet). layer is 'svg' (goes inside
    the vector <svg>) or 'div' (a stage child). None to skip. Shared by the full deterministic
    doc AND the live streaming construction, so both draw identically."""
    if not isinstance(el, dict):
        return None
    kind = str(el.get("kind") or "box").lower()
    motion = str(el.get("motion") or "").lower()
    if motion not in _MOTION_CLASSES:
        motion = "rise-fade"
    color = str(el.get("color") or "#2f6bff")
    dur = int(_num(el.get("dur_ms"), 520)) or 520
    ease = str(el.get("ease") or "ease-out")
    if ease == "overshoot":
        ease = "cubic-bezier(.2,.85,.25,1.1)"
    g = el.get("geometry") if isinstance(el.get("geometry"), dict) else {}
    common = f"--i:{i};--dur:{dur}ms;--ease:{ease}"

    if kind == "wedge":
        cx, cy = _num(g.get("cx"), sw / 2), _num(g.get("cy"), sh / 2)
        r = _num(g.get("r"), 120)
        r_in = _num(g.get("r_inner"), 0)
        a0, a1 = _num(g.get("a0"), 0), _num(g.get("a1"), 90)
        d = _donut_path(cx, cy, r, r_in, a0, a1)
        mcls = motion if motion in ("sweep", "grow-x", "scale-in", "rise-fade") else "sweep"
        return ("svg", f'<path d="{d}" fill="{_esc(color)}" class="vec {mcls}" style="{common}"></path>')
    if kind in ("line", "path"):
        d = str(g.get("d") or "")
        if not d and isinstance(g.get("points"), list):
            d = _points_to_d(g["points"])
        if not d:
            return None
        wdt = _num(g.get("w"), 3) or 3
        return (
            "svg",
            f'<path d="{_esc(d)}" fill="none" stroke="{_esc(color)}" stroke-width="{wdt:.0f}" '
            f'stroke-linecap="round" stroke-linejoin="round" data-draw class="vec draw-stroke" style="{common}"></path>',
        )
    if kind == "number":
        x, y = _num(g.get("x")), _num(g.get("y"))
        size = _num(g.get("size"), 30)
        weight = int(_num(g.get("weight"), 800))
        w = g.get("w")
        anchor = {"middle": "center", "end": "right"}.get(str(g.get("anchor") or "start"), "left")
        wstyle = f"width:{_num(w):.0f}px;text-align:{anchor};" if w else ""
        valstr = f"{_num(el.get('value'), 0):g}"
        return (
            "div",
            f'<div class="el count-up" data-count="{valstr}" style="{common};left:{x:.0f}px;top:{y:.0f}px;'
            f'{wstyle}font-size:{size:.0f}px;font-weight:{weight};color:{_esc(color)};white-space:nowrap;line-height:1.1">0</div>',
        )
    if kind == "text":
        x, y = _num(g.get("x")), _num(g.get("y"))
        size = _num(g.get("size"), 15)
        weight = int(_num(g.get("weight"), 600))
        w = g.get("w")
        anchor = {"middle": "center", "end": "right"}.get(str(g.get("anchor") or "start"), "left")
        wstyle = f"width:{_num(w):.0f}px;text-align:{anchor};" if w else ""
        mcls = motion if motion in ("rise-fade", "scale-in", "count-up") else "rise-fade"
        return (
            "div",
            f'<div class="el {mcls}" style="{common};left:{x:.0f}px;top:{y:.0f}px;{wstyle}font-size:{size:.0f}px;'
            f'font-weight:{weight};color:{_esc(color)};white-space:nowrap;line-height:1.2">{_esc(el.get("label"))}</div>',
        )
    if kind == "raw":
        x, y = _num(g.get("x")), _num(g.get("y"))
        svg = str(g.get("svg") or "")
        mcls = motion if motion in ("rise-fade", "scale-in", "grow-y", "grow-x", "sweep") else "rise-fade"
        return ("div", f'<div class="el {mcls}" style="{common};left:{x:.0f}px;top:{y:.0f}px">{svg}</div>')
    # box | shape | bar | image -> positioned div
    x, y = _num(g.get("x")), _num(g.get("y"))
    w = _num(g.get("w"), 80)
    h = _num(g.get("h"), 40)
    rx = _num(g.get("rx"), 0)
    mcls = (
        motion
        if motion in ("grow-y", "grow-x", "scale-in", "rise-fade")
        else ("grow-y" if kind == "bar" else "scale-in")
    )
    return (
        "div",
        f'<div class="el {mcls}" style="{common};left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;'
        f'border-radius:{rx:.0f}px;background:{_esc(color)}"></div>',
    )


def stream_elements(accumulated: str, already: int) -> list[dict[str, Any]]:
    """Pull COMPLETE element objects out of a partially-streamed spec's "elements":[...] array,
    skipping the first ``already`` already-seen. Lets the canvas construct element-by-element as
    the planner writes the recipe — the "watch it build" effect."""
    text = str(accumulated or "")
    key = text.find('"elements"')
    if key < 0:
        return []
    lb = text.find("[", key)
    if lb < 0:
        return []
    out: list[dict[str, Any]] = []
    depth = 0
    in_str = False
    esc = False
    start = -1
    i = lb + 1
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    blob = text[start : i + 1]
                    try:
                        obj = _json.loads(blob)
                        if isinstance(obj, dict):
                            out.append(obj)
                    except (ValueError, TypeError):
                        pass
                    start = -1
            elif c == "]" and depth == 0:
                break
        i += 1
    return out[already:]


def _partial_stage(acc: str) -> dict[str, Any] | None:
    """Pull stage {w,h,bg} from a partially-streamed spec (it streams before the elements)."""
    m = re.search(r'"stage"\s*:\s*\{([^}]*)\}', str(acc or ""))
    if not m:
        return None
    body = m.group(1)
    w = re.search(r'"w"\s*:\s*(\d+)', body)
    h = re.search(r'"h"\s*:\s*(\d+)', body)
    bg = re.search(r'"bg"\s*:\s*"([^"]+)"', body)
    return {
        "w": int(w.group(1)) if w else 720,
        "h": int(h.group(1)) if h else 520,
        "bg": bg.group(1) if bg else "#ffffff",
    }


def build_canvas_html(spec_text: str) -> str:
    """Compile a planner choreography spec into a finished self-animating HTML doc.
    Raises ValueError if the spec can't be parsed (caller falls back to the LLM render)."""
    spec = parse_spec(spec_text)
    if not spec or not isinstance(spec.get("elements"), list):
        raise ValueError("canvas spec missing or has no elements")

    stage = spec.get("stage") or {}
    sw = int(_num(stage.get("w"), 720)) or 720
    sh = int(_num(stage.get("h"), 520)) or 520
    bg = str(stage.get("bg") or "#ffffff")
    seq = spec.get("sequence") or {}
    order = [str(x) for x in (seq.get("order") or [])]
    stagger = int(_num(seq.get("stagger_ms"), 70)) or 70
    reveal_ms = int(_num(spec.get("reveal_ms"), 1300)) or 1300
    idx_of: dict[str, int] = {eid: i for i, eid in enumerate(order)}

    elements = spec["elements"]
    svg_nodes: list[tuple[int, str]] = []  # (z, markup) inside the vector <svg>
    div_nodes: list[tuple[int, str]] = []  # (z, markup) as stage children

    for pos, el in enumerate(elements):
        if not isinstance(el, dict):
            continue
        eid = str(el.get("id") or f"el{pos}")
        i = idx_of.get(eid, pos)
        rendered = _render_element(el, i, sw, sh)
        if rendered is None:
            continue
        layer, snippet = rendered
        (svg_nodes if layer == "svg" else div_nodes).append((i, snippet))

    svg_inner = "".join(m for _, m in sorted(svg_nodes, key=lambda t: t[0]))
    # z-order divs by sequence index so later elements stack on top
    div_inner = "".join(
        m.replace('style="', f'style="z-index:{z + 2};', 1) for z, m in sorted(div_nodes, key=lambda t: t[0])
    )
    # The vector SVG sits at the level of its EARLIEST vector's order index, so a background
    # box (low order) stays behind the chart and labels (higher order) stay in front of it.
    svg_z = (min((z for z, _ in svg_nodes), default=0) + 2) if svg_nodes else 1
    svg_layer = (
        f'<svg class="tc-vec" viewBox="0 0 {sw} {sh}" preserveAspectRatio="none" style="z-index:{svg_z}">{svg_inner}</svg>'
        if svg_inner
        else ""
    )

    css = (
        _CANVAS_CSS_TEMPLATE.replace("__BG__", _esc(bg))
        .replace("__REVEAL__", str(reveal_ms))
        .replace("__STAGGER__", str(stagger))
    )
    js = (
        _CANVAS_JS_TEMPLATE.replace("__STAGGER__", str(stagger))
        .replace("__REVEAL__", str(reveal_ms))
        .replace("__SW__", str(sw))
        .replace("__SH__", str(sh))
    )
    # #tc-fit scales the fixed-size stage down to the panel width so the canvas never needs
    # horizontal scrolling (the stage coords are absolute at sw x sh; the script fits them).
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{css}</style></head><body>"
        f'<div id="tc-fit" style="width:100%;overflow:hidden">'
        f'<div id="tc-stage" data-reveal="pending" style="width:{sw}px;height:{sh}px;background:{_esc(bg)};transform-origin:top left">'
        f"{svg_layer}{div_inner}</div></div>"
        f"<script>{js}</script></body></html>"
    )


def build_construction_shell(sw: int, sh: int, bg: str, stagger: int = 70) -> str:
    """An EMPTY live-construction shell: an iframe document that receives elements via
    postMessage and pops each into place as it arrives, so the visual assembles itself in
    real time (the "watch it build" effect) instead of appearing finished with an entrance."""
    css = (
        "*{box-sizing:border-box}html,body{margin:0;background:#fff}"
        "#tc-stage{position:relative;contain:layout paint;overflow:hidden;margin:0 auto;"
        "font-family:Arial,Helvetica,sans-serif;color:#263238;transform-origin:top left}"
        ".tc-onevec{position:absolute;inset:0;width:100%;height:100%;overflow:visible}"
        ".el{position:absolute;transition:opacity .42s ease-out,transform .42s ease-out;will-change:opacity,transform}"
        ".vec{transition:opacity .5s ease-out,transform .55s ease-out,stroke-dashoffset .6s ease-out;"
        "transform-box:fill-box;transform-origin:center;will-change:opacity,transform,stroke-dashoffset}"
        ".tc-pre.rise-fade,.tc-pre.count-up{opacity:0}"
        ".tc-pre.scale-in{opacity:0;transform:scale(.94)}"
        ".tc-pre.grow-y{transform:scaleY(0)}.grow-y{transform-origin:bottom}"
        ".tc-pre.grow-x,.tc-pre.sweep{transform:scaleX(0)}.grow-x{transform-origin:left}"
        ".tc-in{opacity:1 !important;transform:none !important}"
        ".tc-in[data-draw]{stroke-dashoffset:0 !important}"
        # Shimmer skeleton: a placeholder of the element's exact size that pulses while the real
        # element is 'prepared', then fades as the content resolves in.
        ".tc-shim{position:absolute;border-radius:7px;pointer-events:none;transition:opacity .34s ease;"
        "background:linear-gradient(100deg,#e9eef4 28%,#f7fafd 50%,#e9eef4 72%);background-size:220% 100%;"
        "animation:tcShim 1.05s linear infinite}"
        "@keyframes tcShim{0%{background-position:220% 0}100%{background-position:-220% 0}}"
        "@media (prefers-reduced-motion:reduce){.el,.vec,.tc-shim{transition:none !important;animation:none !important}}"
    )
    js = (
        "(function(){var SW=__SW__,SH=__SH__;var stage=document.getElementById('tc-stage');"
        "function fit(){var w=document.documentElement.clientWidth||window.innerWidth||SW;"
        "var s=Math.min(1,w/SW);stage.style.transform='scale('+s+')';"
        "var f=document.getElementById('tc-fit');if(f)f.style.height=(SH*s)+'px';}"
        "window.addEventListener('resize',fit);fit();"
        "function cnt(el){var tg=parseFloat(el.getAttribute('data-count'))||0;var t0=null;"
        "function tk(t){if(!t0)t0=t;var k=Math.min(1,(t-t0)/600);"
        "el.textContent=String(Math.round(tg*(1-Math.pow(1-k,3))));"
        "if(k<1)requestAnimationFrame(tk);else el.textContent=String(tg);}requestAnimationFrame(tk);}"
        "function reveal(node){node.classList.remove('tc-pre');node.classList.add('tc-in');"
        "if(node.hasAttribute&&node.hasAttribute('data-draw'))node.style.strokeDashoffset=0;"
        "if(node.hasAttribute&&node.hasAttribute('data-count'))cnt(node);}"
        "function add(layer,html,idx){"
        "if(layer==='svg'){var s=document.createElementNS('http://www.w3.org/2000/svg','svg');"
        "s.setAttribute('class','tc-onevec');s.setAttribute('viewBox','0 0 '+SW+' '+SH);"
        "s.setAttribute('preserveAspectRatio','none');s.style.zIndex=idx;s.innerHTML=html;"
        "stage.appendChild(s);var n=s.firstElementChild;if(!n)return;n.classList.add('tc-pre');"
        "if(n.hasAttribute&&n.hasAttribute('data-draw')){try{var L=n.getTotalLength();n.style.strokeDasharray=L;n.style.strokeDashoffset=L;}catch(e){}}"
        "requestAnimationFrame(function(){requestAnimationFrame(function(){reveal(n);});});return;}"
        # div path: drop a shimmering skeleton of the element's box, then resolve the real content.
        "var t=document.createElement('div');t.innerHTML=html;var node=t.firstElementChild;if(!node)return;"
        "node.style.zIndex=idx+2;node.classList.add('tc-pre');stage.appendChild(node);"
        "var L=parseFloat(node.style.left)||0,T=parseFloat(node.style.top)||0,W=node.offsetWidth||40,H=node.offsetHeight||16;"
        "var shim=document.createElement('div');shim.className='tc-shim';shim.style.left=L+'px';shim.style.top=T+'px';"
        "shim.style.width=W+'px';shim.style.height=H+'px';shim.style.zIndex=(idx+3);stage.appendChild(shim);"
        "setTimeout(function(){shim.style.opacity='0';setTimeout(function(){if(shim.parentNode)shim.parentNode.removeChild(shim);},340);"
        "requestAnimationFrame(function(){reveal(node);});},340);}"
        "window.addEventListener('message',function(e){var d=e.data||{};"
        "if(d.t==='el'){add(d.layer,d.html,d.idx||0);}});"
        "try{if(window.parent)window.parent.postMessage({t:'ready'},'*');}catch(e){}"
        "})();"
    )
    js = js.replace("__SW__", str(sw)).replace("__SH__", str(sh))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{css}</style></head><body>"
        f'<div id="tc-fit" style="width:100%;overflow:hidden">'
        f'<div id="tc-stage" style="width:{sw}px;height:{sh}px;background:{_esc(bg)}"></div></div>'
        f"<script>{js}</script></body></html>"
    )


_CANVAS_CSS_TEMPLATE = (
    "*{box-sizing:border-box}html,body{margin:0;background:#fff}"
    "#tc-stage{position:relative;contain:layout paint;overflow:hidden;margin:0 auto;"
    "font-family:Arial,Helvetica,sans-serif;color:#263238}"
    "#tc-stage::after{content:'';position:absolute;inset:0;background:__BG__;opacity:1;"
    "pointer-events:none;z-index:60;transition:opacity __REVEAL__ms ease-out}"
    "#tc-stage[data-reveal='play']::after{opacity:0}"
    ".tc-vec{position:absolute;inset:0;width:100%;height:100%;overflow:visible}"
    ".el{position:absolute;transition-property:opacity,transform;transition-duration:var(--dur,460ms);"
    "transition-timing-function:var(--ease,ease-out);transition-delay:calc(var(--i,0)*__STAGGER__ms);"
    "will-change:opacity,transform}"
    ".vec{transition-property:opacity,transform,stroke-dashoffset;transition-duration:var(--dur,560ms);"
    "transition-timing-function:var(--ease,ease-out);transition-delay:calc(var(--i,0)*__STAGGER__ms);"
    "transform-box:fill-box;transform-origin:center;will-change:opacity,transform,stroke-dashoffset}"
    "#tc-stage[data-reveal='pending'] .rise-fade,#tc-stage[data-reveal='pending'] .count-up{opacity:0}"
    "#tc-stage[data-reveal='pending'] .scale-in{opacity:0;transform:scale(.94)}"
    "#tc-stage[data-reveal='pending'] .grow-y{transform:scaleY(0)}"
    "#tc-stage[data-reveal='pending'] .grow-x,#tc-stage[data-reveal='pending'] .sweep{transform:scaleX(0)}"
    "#tc-stage[data-reveal='play'] .rise-fade,#tc-stage[data-reveal='play'] .count-up,"
    "#tc-stage[data-reveal='play'] .scale-in,#tc-stage[data-reveal='play'] .grow-y,"
    "#tc-stage[data-reveal='play'] .grow-x,#tc-stage[data-reveal='play'] .sweep{opacity:1;transform:none}"
    "#tc-stage[data-reveal='play'] [data-draw]{stroke-dashoffset:0}"
    ".grow-y{transform-origin:bottom}.grow-x{transform-origin:left}"
    "@media (prefers-reduced-motion: reduce){.el,.vec,#tc-stage::after{transition:none !important;will-change:auto !important}"
    "#tc-stage::after{opacity:0 !important}"
    "#tc-stage[data-reveal='pending'] .rise-fade,#tc-stage[data-reveal='pending'] .count-up,"
    "#tc-stage[data-reveal='pending'] .scale-in,#tc-stage[data-reveal='pending'] .grow-y,"
    "#tc-stage[data-reveal='pending'] .grow-x,#tc-stage[data-reveal='pending'] .sweep{opacity:1 !important;transform:none !important}"
    "[data-draw]{stroke-dashoffset:0 !important}}"
)

_CANVAS_JS_TEMPLATE = (
    "(function(){var stage=document.getElementById('tc-stage');if(!stage)return;"
    "function __fit(){var w=document.documentElement.clientWidth||window.innerWidth||__SW__;"
    "var s=Math.min(1,w/__SW__);stage.style.transform='scale('+s+')';"
    "var f=document.getElementById('tc-fit');if(f)f.style.height=(__SH__*s)+'px';}"
    "window.addEventListener('resize',__fit);__fit();"
    "var reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;"
    "document.querySelectorAll('[data-draw]').forEach(function(p){try{var L=p.getTotalLength();"
    "p.style.strokeDasharray=L;p.style.strokeDashoffset=L;}catch(e){}});"
    "var played=false;"
    "function countUp(){var instant=stage.getAttribute('data-static')==='1';document.querySelectorAll('[data-count]').forEach(function(el){"
    "var target=parseFloat(el.getAttribute('data-count'))||0;if(reduced||instant){el.textContent=String(target);return;}"
    "var dur=parseFloat(getComputedStyle(el).getPropertyValue('--dur'))||600;"
    "var delay=(parseFloat(getComputedStyle(el).getPropertyValue('--i'))||0)*__STAGGER__;"
    "var start=performance.now()+delay;function tick(now){var t=Math.max(0,Math.min(1,(now-start)/dur));"
    "var e=1-Math.pow(1-t,3);el.textContent=String(Math.round(target*e));"
    "if(t<1)requestAnimationFrame(tick);else el.textContent=String(target);}requestAnimationFrame(tick);});}"
    "function play(){if(played)return;played=true;stage.setAttribute('data-reveal','play');countUp();"
    "setTimeout(function(){document.querySelectorAll('.el,.vec').forEach(function(n){n.style.willChange='auto';});},Math.max(2000,__REVEAL__+800));}"
    "setTimeout(play,2500);"
    "var fr=(document.fonts&&document.fonts.ready)?document.fonts.ready:Promise.resolve();"
    "fr.then(function(){requestAnimationFrame(function(){requestAnimationFrame(play);});})"
    ".catch(function(){requestAnimationFrame(function(){requestAnimationFrame(play);});});})();"
)


# --------------------------------------------------------------------------- #
# HTML extraction — tolerate a stray markdown fence or lead-in text.
# --------------------------------------------------------------------------- #
def extract_html(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    fence = re.search(r"```(?:html)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    m = re.search(r"(<!doctype html|<html\b|<svg\b)", raw, re.IGNORECASE)
    if m:
        return raw[m.start() :].strip()
    return raw


_CANVAS_SYSTEM = (
    "You are Thomas's canvas/design worker. You receive a request for something visual "
    "and you PRODUCE it as a single self-contained HTML document that renders it.\n"
    "RULES:\n"
    "- Output ONLY the HTML. Start your reply with <!DOCTYPE html>. No explanation, no "
    "commentary, no markdown code fences.\n"
    "- Everything inline: CSS in a <style> tag, any JS in a <script> tag, charts/graphics "
    "as inline <svg>. NO external files, CDNs, web fonts, or network requests of any kind.\n"
    "- Make it look genuinely good and finished: a clear title, real colors, proper spacing, "
    "axis/labels/legend for charts with correct proportions, realistic polished layout for UIs.\n"
    "- ANIMATE IT DRAWING ITSELF ON LOAD: with inline CSS/JS, make the visual build in over "
    "about 1-1.5 seconds — SVG strokes draw in via stroke-dasharray/stroke-dashoffset, bars "
    "and pie wedges grow from zero, points/labels stagger-fade in. It should visibly DRAW "
    "itself the moment it appears, not just pop in finished.\n"
    "- It must render correctly when dropped straight into an <iframe srcdoc> with no server.\n"
    "- Fit one screen (about 720x520) unless the content truly needs more; use a clean light "
    "background so it reads on the Canvas."
)

# Stage 1 — the MOTION DIRECTOR. It designs the visual AND a custom build choreography for
# THIS specific visual, emitted as a strict JSON spec (no HTML). The 7 motion verbs compose
# to ANY visual — chart, UI, diagram, drawing — with no hardcoded chart-type categories.
_PLAN_SYSTEM = (
    "You are the MOTION DIRECTOR for Thomas's canvas. A user asked for a visual. You design "
    "the finished visual AND its magical build animation, then hand a strict JSON spec to a "
    "render bot. You write NO HTML and NO CSS — only the JSON spec below.\n"
    "\n"
    "THINK FIRST (do this, do not output it):\n"
    "1. Decide the finished visual and its REAL content: exact data, labels, hex colors, title.\n"
    "2. Break it into ELEMENTS. Give each a role: exactly ONE 'primary' (the hero); the rest "
    "'secondary' / 'text' / 'background'.\n"
    "3. For each element pick ONE MOTION VERB that mimics how that thing behaves in reality — "
    "NOT from a chart-type recipe:\n"
    "   bars -> grow-y (up from the axis); pie/gauge/arc wedges -> sweep (around their center); "
    "lines, diagram strokes, freehand drawings, any path -> draw-stroke (trace on); "
    "cards/boxes/nodes/panels -> scale-in; labels/legends/axis text/captions -> rise-fade; "
    "KPIs/totals/scores/big numbers -> count-up; backgrounds/grids -> rise-fade and settle "
    "first, quietly.\n"
    "4. Sequence it so it reads as ASSEMBLING ITSELF in about 1.3s: background settles first, "
    "siblings (legend swatches, axis ticks, list rows, bars) wave in via a stagger, and the "
    "hero animates LAST with a slight overshoot — its climactic moment.\n"
    "\n"
    "OUTPUT ONLY this JSON (no prose, no markdown fence):\n"
    "{\n"
    '  "result": "<one line: layout + visual style>",\n'
    '  "stage": {"w":720,"h":520,"bg":"#ffffff"},\n'
    '  "palette": ["#hex", "..."],\n'
    '  "title": "<exact title text>",\n'
    '  "reveal_ms": 1300,\n'
    '  "elements": [\n'
    '    {"id":"<slug>","kind":"wedge|bar|box|shape|line|path|text|number|raw",\n'
    '     "role":"primary|secondary|text|background","label":"<text for text kinds>","value":<num for number>,\n'
    '     "color":"#hex","geometry":{ ...see GEOMETRY below... },\n'
    '     "motion":"sweep|grow-y|grow-x|draw-stroke|scale-in|rise-fade|count-up|none",\n'
    '     "ease":"ease-out|overshoot|cubic-bezier(...)","dur_ms":<int>}\n'
    "  ],\n"
    '  "sequence": {"order":["id", "..."],"stagger_ms":<int 50-90>,\n'
    '               "stagger_from":"first|center|last","total_ms":<int ~1300>,"hero":"<primary id>"}\n'
    "}\n"
    "\n"
    "GEOMETRY — a code renderer draws these, so give EXACT pixel numbers in the 720x520 stage, "
    "top-left origin. Per kind:\n"
    '  bar / box / shape : {"x":,"y":,"w":,"h":,"rx":<corner radius, 0 if none>}\n'
    '  wedge (pie/donut) : {"cx":,"cy":,"r":<outer>,"r_inner":<0 for full pie>,"a0":<start deg>,"a1":<end deg>}  (0deg = 3 o\'clock, clockwise)\n'
    '  line / path       : {"d":"<SVG path d>"}  OR  {"points":[[x,y],[x,y],...]}  (+ optional "w":<stroke width>)\n'
    '  text / number     : {"x":,"y":,"size":<px>,"w":<optional box width>,"anchor":"start|middle|end","weight":<400-800>}\n'
    '  raw (escape hatch): {"svg":"<raw inline SVG markup>","x":,"y":}  — use ONLY for things the primitives cannot express (freehand art, a novel diagram). The renderer drops the SVG in and animates it with your motion verb.\n'
    "\n"
    "LAYOUT QUALITY — this is what makes it look GOOD, not amateur. Be exact:\n"
    "- NOTHING OVERLAPS unless intentional (a label centered in a donut hole is fine; two labels on "
    "top of each other is NOT). Text never wraps (it is rendered nowrap) so it WILL bleed into its "
    "neighbor if you crowd it — give every text/number enough room.\n"
    "- TEXT SIZING: a text box must be wide enough for its content. Estimate width ≈ chars * size * 0.6. "
    "Either give text a `w` (box width) that fits and matches the `anchor`, or leave ≥ that much clear "
    "space to its right. Stack list/legend rows with ≥ (size + 12) px vertical gap so they never touch.\n"
    "- MARGINS: keep all content ≥ 32px from the stage edges. Inside a card, pad ≥ 24px.\n"
    "- ALIGN to a tidy grid: shared left edges for stacked text, even spacing between repeated items "
    "(bars, legend rows, icons). Even spacing reads as 'designed'.\n"
    "- STACKING = ORDER: sequence.order is ALSO the front-to-back stack — elements LATER in the order "
    "render ON TOP. So order strictly BACK TO FRONT: every container/panel/window background goes BEFORE "
    "the things that sit inside it, and the contents go AFTER so they're visible. NEVER place a large "
    "opaque panel AFTER the content it would cover — that buries it (a window's body must not hide its "
    "own title bar or another window's contents).\n"
    "- NO EMPTY PANELS: every box that reads as a window/card/content-area MUST be filled with real "
    "content elements layered on top of it (title text, buttons, list rows, an icon, a chart) — never a "
    "bare empty rectangle. If you draw a window, you must also draw what's inside it.\n"
    "- CHARTS: a titled card = a background box behind everything; title top-left, optional subtitle "
    "under it; the plot centered with clear room; a legend to the side or below with swatch + label "
    "rows that don't collide. Pie/donut wedges each get their own a0/a1 that tile the full 360 with no "
    "gaps. Bars share a baseline and equal width/spacing; value labels sit just above each bar, axis "
    "labels just below.\n"
    "- UIs / APP WINDOWS / MOCKUPS (e.g. 'a Windows 7 UI', a settings page, a dashboard): build it like "
    "a REAL interface with MANY elements (commonly 20-45). A window, BACK TO FRONT = outer frame box -> "
    "title bar box across the top -> control dots/buttons at the right of the title bar -> the title bar "
    "TEXT -> the content-area background -> THEN the real content that fills it (sidebar items, toolbar "
    "buttons ~32px tall, list rows, input boxes, icons, text) at realistic sizes and even spacing with "
    "real labels. Use `box`/`shape` for panels/buttons, `text` for labels, and the `raw` escape hatch "
    "for any icon/glyph/gradient the primitives can't express. Make it dense and convincing — fill every "
    "window; no empty rectangles, no panel covering another's content.\n"
    "\n"
    "RULES:\n"
    "- Real numbers and real hex colors only — never placeholders or prose in geometry.\n"
    "- The CASCADE comes from sequence.stagger_ms across sequence.order. Pick motion from the "
    "CONTENT, never a chart category: a diagram arrow and a line series are both draw-stroke; a KPI "
    "and a chart total are both count-up. Background settles first; the hero animates last.\n"
    "- Give every element id/kind/role/color/geometry/motion/ease/dur_ms so the renderer invents nothing."
)

# Stage 2 — the RENDER BOT. Turns the choreography spec into ONE self-contained HTML doc that
# obeys a FIXED render contract (#tc-stage + data-reveal + --i + reduced-motion + safety net),
# using render-then-reveal so it performs its entrance once with NO flashing. The contract is
# validated by _conforms_to_contract before the doc goes live.
_RENDER_SYSTEM = (
    "You are a RENDER BOT. You turn a JSON design plan into ONE finished, self-contained HTML "
    "document that renders the visual and plays its build animation. You do NOT redesign or "
    "second-guess the plan — you render exactly what it specifies.\n"
    "\n"
    "OUTPUT: ONLY the HTML. Start with <!DOCTYPE html>. No prose, no commentary, no markdown "
    "fences. Everything inline: CSS in <style>, JS in <script>, graphics as inline <svg>. NO "
    "external files, CDNs, web fonts, or network requests. It must render dropped straight into "
    "<iframe srcdoc> with no server.\n"
    "\n"
    "YOU MUST FOLLOW THIS EXACT RENDER CONTRACT (the harness depends on it):\n"
    "1. STAGE: put the entire visual inside one element: "
    '<div id="tc-stage" data-reveal="pending"> ... </div>. Lock its width/height to stage.w/h '
    "(default 720x520) and set position:relative; contain:layout paint; overflow:hidden; "
    "background:stage.bg. Lay everything out at FINAL position/size — never move layout during "
    "the animation.\n"
    "2. ORDER your document: <style> first, then the #tc-stage markup, then the reveal <script> "
    "LAST, so the first paint is already styled.\n"
    "3. HIDE EACH ELEMENT VIA THE SAME CHANNEL YOU WILL ANIMATE, scoped under "
    '#tc-stage[data-reveal="pending"]. NEVER display:none. Specifically:\n'
    "   rise-fade / scale-in / count-up -> start opacity:0 (scale-in also transform:scale(.96));\n"
    "   grow-y -> transform:scaleY(0) with transform-origin per origin (default bottom);\n"
    "   grow-x / sweep -> transform:scaleX(0) (origin left) or a 0-length conic/arc for wedges;\n"
    "   draw-stroke -> give the <path>/<line>/<polyline> the attribute data-draw; the script "
    "sets stroke-dasharray and stroke-dashoffset to its measured length so it starts undrawn.\n"
    "4. STAGGER with an index variable, NOT per-element keyframes. Give each animatable element "
    'style="--i:N" where N is its position in sequence.order, and delay each transition with '
    "transition-delay: calc(var(--i) * <sequence.stagger_ms>ms). (Honor stagger_from: for "
    "'last' use reversed index, for 'center' use distance from the middle.)\n"
    '5. REVEAL: under #tc-stage[data-reveal="play"], set every channel to its FINAL value '
    "(opacity:1; transform:none; stroke-dashoffset:0) with one shared transition of duration "
    "~dur_ms and the element's ease (map 'overshoot' to a slight cubic-bezier overshoot). Add a "
    "#tc-stage::after full-stage scrim that goes opacity:1 -> 0 on the same flip (the soft wash).\n"
    "6. THE SCRIPT (runs last) MUST: measure every [data-draw] length and set its dasharray/"
    "dashoffset; then wait for document.fonts.ready and a DOUBLE requestAnimationFrame before "
    'setting #tc-stage data-reveal to "play"; run count-up elements by interpolating 0 -> value '
    "over dur_ms with one rAF loop; AND include a safety net: "
    "setTimeout(()=>stage.setAttribute('data-reveal','play'), 2500) so nothing is ever left "
    "stuck hidden. After the entrance finishes, remove will-change from animated nodes.\n"
    "7. ANIMATE ONLY transform, opacity, and stroke-dashoffset (GPU). Add a "
    "@media (prefers-reduced-motion: reduce) block that puts every element at its final state "
    "with no transition.\n"
    "\n"
    "Use a clean light background, target ~720x520, fit one screen. The result must visibly draw "
    "itself in ONCE over ~1.2-1.4s and then sit still."
)


def _conforms_to_contract(html: str) -> bool:
    """Cheap static check that the render bot honored the entrance contract, so a
    non-conforming doc never reaches the canvas (Change #5). Mirrors the static asserts
    in the frame-slice test. A doc that lacks the stage/reveal markers can't reveal; one
    that hides via display:none would pop instead of animate."""
    h = str(html or "")
    if "tc-stage" not in h:
        return False
    if 'data-reveal="pending"' not in h and "data-reveal='pending'" not in h:
        return False
    if "--i" not in h:  # per-element stagger index
        return False
    return True


def build_canvas_llm(root: Path, profile: str | None) -> Any | None:
    """Get a WARM, cached LLMClient for ``profile``. A cold OAuth client stalls on its
    first token (the chat works because its session client is already warm), so we keep
    one warm client per profile and only rebuild it if it actually breaks (see
    _evict_canvas_llm, called on a stall)."""
    key = str(profile or "")
    cached = _LLM_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_client import LLMClient

        cfg = load_config(Path(root) / "thomas.toml")
        model_cfg = cfg.get_model(profile or None)
        # The canvas stages (especially render: transcribe a plan into HTML) are mostly
        # mechanical. gpt-5.5 reasons BEFORE emitting any output token, so heavy effort
        # delays the first token past our timeout. Low effort keeps it responsive.
        try:
            from dataclasses import replace as _replace

            model_cfg = _replace(model_cfg, reasoning_effort="low")
        except Exception:
            pass
        try:
            _diag(
                f"[build] profile={profile!r} provider={getattr(model_cfg, 'provider', None)!r} "
                f"model={getattr(model_cfg, 'model', None)!r} base_url={getattr(model_cfg, 'base_url', None)!r} "
                f"has_api_key={bool(getattr(model_cfg, 'api_key', None))} "
                f"backend={getattr(model_cfg, 'backend', None)!r}"
            )
        except Exception:
            pass
        client = LLMClient(model_cfg)
        _LLM_CACHE[key] = client
        return client
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return None


def _evict_canvas_llm(profile: str | None) -> None:
    _LLM_CACHE.pop(str(profile or ""), None)


def _diag(msg: str) -> None:
    """Append a line to _canvas_diag.log for runtime debugging of the canvas worker.
    Off by default; set THOMAS_CANVAS_DIAG=1 to enable (used to trace stream stalls)."""
    import os

    if not os.environ.get("THOMAS_CANVAS_DIAG"):
        return
    try:
        with open(Path(__file__).resolve().parents[2] / "_canvas_diag.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Keep-alive: the chat's gpt-5.5 connection is fast because it's used every turn.
# The dedicated canvas client goes idle between requests and its OAuth stream then
# stalls on the next first token. A tiny periodic ping keeps that one connection
# warm, so real canvas requests never cold-start.
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[2]
_keepalive_started = False


def start_canvas_keepalive(root: Path | None = None) -> None:
    """Start (once) the background task that keeps the canvas LLM connection warm."""
    global _keepalive_started
    if _keepalive_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop yet; caller will retry from an async context
    _keepalive_started = True
    loop.create_task(_keepalive_loop(Path(root) if root else _REPO_ROOT))


async def _keepalive_loop(root: Path) -> None:
    import contextlib

    while True:
        try:
            client = build_canvas_llm(root, None)
            if client is not None and hasattr(client, "stream_chat"):
                async with _CANVAS_LLM_LOCK:  # never compete with a real generation
                    aiter = client.stream_chat(
                        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                        tools=None,
                    ).__aiter__()
                    got = 0
                    try:
                        while got < 2:
                            await asyncio.wait_for(aiter.__anext__(), timeout=12)
                            got += 1
                    except (StopAsyncIteration, asyncio.TimeoutError):
                        pass
                    except Exception:  # noqa: BLE001 - a failed ping is harmless
                        pass
                    with contextlib.suppress(Exception):
                        await aiter.aclose()
        except Exception:  # noqa: BLE001 - keep the loop alive no matter what
            pass
        await asyncio.sleep(18)


async def run_canvas_worker(
    *,
    execution_id: str,
    prompt: str,
    root: Path,
    profile: str | None = None,
    emit_progress: Callable[[str], Awaitable[None]] | None = None,
    session_llm: Any = None,
) -> str:
    """Stream a self-contained HTML document for ``prompt`` into the per-execution
    store (so the Canvas can render it live), and return the final cleaned HTML.

    Raises RuntimeError if no streaming LLM is available or generation errors.
    """
    canvas_start(execution_id, title=str(prompt or "")[:80])
    # Use a DEDICATED canvas client (pinned key ""), NOT the chat's session client: the
    # chat's stream loop breaks early without closing, so its connection stays "busy" and
    # a second stream on it hangs. A dedicated client kept warm by the keep-alive avoids
    # both that conflict and the cold-start stall.
    profile = None
    _ = session_llm  # accepted for API compatibility; intentionally not reused (see above)
    llm = build_canvas_llm(root, profile)
    if llm is None or not hasattr(llm, "stream_chat"):
        canvas_finish(execution_id, "failed")
        raise RuntimeError("No streaming LLM available for the canvas worker")

    # The render stage reads a large plan and reasons before its first token, so the
    # time-to-first-token is much longer than a small prompt. Give it real room rather
    # than killing it at 8s (the old value that made every render attempt "stall").
    _FIRST_TOKEN_TIMEOUT_S = 75.0
    _IDLE_TIMEOUT_S = 30.0
    _MAX_ATTEMPTS = 2
    _BACKOFF_S = 1.5  # let a throttled provider breathe before the next attempt

    class _Stall(Exception):
        pass

    async def _stream(
        stage_messages: list[dict[str, Any]],
        *,
        to_canvas: bool,
        label: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """Retryable streaming call against the warm client. Returns the accumulated text.
        When to_canvas, tokens are also appended to the per-execution store for the poll.
        on_text(accumulated) is called as tokens arrive (used to stream the live construction).
        Raises _Stall if every attempt hangs (no first token) or errors."""
        last_err = "stalled"
        for _attempt in range(_MAX_ATTEMPTS):
            parts: list[str] = []
            count = 0
            got_first = False
            try:
                _diag(
                    f"[stream] {label} a{_attempt}: opening; client={type(llm).__name__} failover={getattr(llm, '_failover_enabled', '?')}"
                )
                aiter = llm.stream_chat(messages=stage_messages, tools=None).__aiter__()
                _evn = 0
                while True:
                    timeout = _IDLE_TIMEOUT_S if got_first else _FIRST_TOKEN_TIMEOUT_S
                    try:
                        ev = await asyncio.wait_for(aiter.__anext__(), timeout=timeout)
                    except StopAsyncIteration:
                        _diag(f"[stream] {label} a{_attempt}: StopAsyncIteration after {_evn} events, {count} tokens")
                        break
                    except asyncio.TimeoutError as exc:
                        raise _Stall("no first token" if not got_first else "stalled mid-stream") from exc
                    etype = str(getattr(ev, "type", "") or "")
                    data = getattr(ev, "data", {}) or {}
                    _evn += 1
                    if _evn <= 8:
                        _peek = (
                            (str(data.get("text") or data.get("error") or "")[:50])
                            if isinstance(data, dict)
                            else str(data)[:50]
                        )
                        _diag(
                            f"[stream] {label} a{_attempt}: ev#{_evn} type={etype!r} keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__} peek={_peek!r}"
                        )
                    if etype == "token":
                        tok = str(data.get("text", "") or "")
                        if tok:
                            got_first = True
                            parts.append(tok)
                            if to_canvas:
                                canvas_append(execution_id, tok)
                            count += 1
                            if on_text is not None and count % 8 == 0:
                                try:
                                    on_text("".join(parts))
                                except Exception:
                                    pass
                            if emit_progress is not None and count % 30 == 0:
                                try:
                                    await emit_progress(label)
                                except Exception:
                                    pass
                    elif etype == "error":
                        raise _Stall(str(data.get("error") or "provider error"))
                text = "".join(parts)
                if on_text is not None:
                    try:
                        on_text(text)  # final flush — catch the last elements
                    except Exception:
                        pass
                if text.strip():
                    return text
                last_err = "empty output"
            except _Stall as exc:
                last_err = str(exc)
                _diag(f"[stream] {label} a{_attempt}: STALL {exc}")
            except Exception as exc:  # noqa: BLE001 - any provider error -> retry
                last_err = f"{type(exc).__name__}: {exc}"
                _diag(f"[stream] {label} a{_attempt}: EXC {type(exc).__name__}: {exc}")
            if _attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_S)
        raise _Stall(f"{_MAX_ATTEMPTS} attempts: {last_err}")

    # Serialize the whole two-stage generation behind one lock (the provider hangs when
    # streams overlap). STAGE 1 plans; STAGE 2 (the render bot) renders the plan.
    await _CANVAS_LLM_LOCK.acquire()
    try:
        if emit_progress is not None:
            try:
                await emit_progress("Planning the design…")
            except Exception:
                pass
        # STAGE 1 — planning worker. As it WRITES the recipe, we stream each finished element
        # into the live construction shell, so the user WATCHES the visual assemble itself in
        # real time (the Claude-design effect) rather than seeing a canned entrance at the end.
        _build_state: dict[str, Any] = {"n": 0, "sw": 720, "sh": 520, "shell": False}

        def _on_plan(acc: str) -> None:
            st = _partial_stage(acc)
            if st:
                _build_state["sw"], _build_state["sh"] = st["w"], st["h"]
                if not _build_state["shell"]:
                    canvas_set_shell(execution_id, {**st, "stagger": 70})
                    _build_state["shell"] = True
            if not _build_state["shell"]:
                return  # hold until we know the stage size, so elements land in the right place
            for el in stream_elements(acc, _build_state["n"]):
                rendered = _render_element(el, _build_state["n"], _build_state["sw"], _build_state["sh"])
                _build_state["n"] += 1
                if rendered is not None:
                    canvas_add_element(execution_id, rendered[0], rendered[1])

        plan = await _stream(
            [{"role": "system", "content": _PLAN_SYSTEM}, {"role": "user", "content": str(prompt or "")}],
            to_canvas=False,
            label="Building it on the canvas…",
            on_text=_on_plan,
        )
        # STAGE 2 — DETERMINISTIC renderer (NO second LLM call): compile the spec into the
        # self-animating HTML in code. This is the big speed win (~140s -> ~15-25s) and it can
        # never drop the contract. The LLM render bot stays only as a fallback if the spec
        # somehow won't compile.
        if emit_progress is not None:
            try:
                await emit_progress("Drawing it on the canvas…")
            except Exception:
                pass
        html = ""
        try:
            built = build_canvas_html(plan)
            if built.strip() and _conforms_to_contract(built):
                html = built
                _diag(f"[render] deterministic OK, {len(html)} chars")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:  # noqa: BLE001
            _diag(f"[render] deterministic compile failed: {exc}")
        if not html.strip():
            # FALLBACK — the old LLM render bot, when the spec won't compile deterministically.
            _diag("[render] falling back to LLM render bot")
            render_user = f"USER REQUEST:\n{str(prompt or '')}\n\nDESIGN PLAN TO RENDER EXACTLY:\n{plan}"
            for _render_pass in range(2):
                html_text = await _stream(
                    [{"role": "system", "content": _RENDER_SYSTEM}, {"role": "user", "content": render_user}],
                    to_canvas=True,
                    label="Drawing it on the canvas…",
                )
                html = extract_html(html_text)
                if html.strip() and _conforms_to_contract(html):
                    break
                render_user += (
                    "\n\nIMPORTANT: your previous attempt did NOT follow the render contract. The "
                    'document MUST contain <div id="tc-stage" data-reveal="pending"> wrapping the visual, '
                    'every animatable element must carry style="--i:N", and a final script must flip '
                    'data-reveal to "play" after document.fonts.ready + a double requestAnimationFrame, '
                    "with a setTimeout(...,2500) safety net. Redo it following the contract exactly."
                )
        if not html.strip():
            raise _Stall("render produced empty HTML")
        canvas_set_html(execution_id, html)
        canvas_finish(execution_id, "done")
        return html
    except _Stall as exc:
        canvas_finish(execution_id, "failed")
        raise RuntimeError(f"canvas generation failed: {exc}")
    finally:
        _CANVAS_LLM_LOCK.release()
