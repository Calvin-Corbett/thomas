"""Deterministic canvas renderer — planner choreography spec (JSON) -> finished HTML.

Split out of ``chat_delegation_canvas`` so that module stays under the architecture
line limit. This half is pure compilation: it takes the motion director's JSON spec
and produces a self-contained, self-animating HTML document, plus the live
"watch it build" construction shell that streams elements in one at a time. It holds
no state and calls no LLM.

``chat_delegation_canvas`` re-exports every name the rest of the codebase used to
import from it, so its public API is unchanged.
"""

from __future__ import annotations

import json as _json
import math as _math
import re
from typing import Any

# --------------------------------------------------------------------------- #
# Deterministic renderer — compile a planner choreography spec (JSON) into ONE
# self-contained, self-animating HTML document with NO second LLM call. This is
# the speed win: the render is mechanical (the old _RENDER_SYSTEM was a fixed
# 7-point contract), so code does it instantly and identically every time. The 7
# motion verbs + a `raw` SVG escape hatch keep it general (no chart categories).
# --------------------------------------------------------------------------- #

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
            # Ships its FINAL value, not "0". The count-up script zeroes every
            # [data-count] before the first paint, so the animation is unchanged
            # -- but when the script does not run, the chart reads its real
            # numbers instead of a full set of confident zeroes.
            f'{wstyle}font-size:{size:.0f}px;font-weight:{weight};color:{_esc(color)};'
            f'white-space:nowrap;line-height:1.1">{_esc(valstr)}</div>',
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
        return (
            "div",
            f'<div class="el raw-el {mcls}" style="{common};left:{x:.0f}px;top:{y:.0f}px">{svg}</div>',
        )
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
        f"<style>{css}</style>{_CANVAS_NOSCRIPT_FALLBACK}</head><body>"
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
        ".el{position:absolute;pointer-events:none;transition:opacity .42s ease-out,transform .42s ease-out;will-change:opacity,transform}"
        ".raw-el [role='button'],.raw-el button,.raw-el a,.raw-el input,.raw-el select,.raw-el textarea{pointer-events:auto}"
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
    ".el{position:absolute;pointer-events:none;transition-property:opacity,transform;transition-duration:var(--dur,460ms);"
    "transition-timing-function:var(--ease,ease-out);transition-delay:calc(var(--i,0)*__STAGGER__ms);"
    "will-change:opacity,transform}"
    ".raw-el [role='button'],.raw-el button,.raw-el a,.raw-el input,.raw-el select,.raw-el textarea{pointer-events:auto}"
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

# The reveal is driven entirely by script: the document ships with
# data-reveal="pending", which holds every element at opacity 0 behind an opaque
# full-bleed cover, and only JS flips it to "play". So if the script does not run
# -- JS disabled, a strict CSP where the file is opened, a frame sandboxed
# without allow-scripts, a mail or document preview pane -- the deliverable is a
# BLANK WHITE PAGE. Not a degraded diagram: nothing at all, and no error saying
# so. Someone who asked for a diagram cannot tell that from a broken product.
#
# This restates the reduced-motion escape hatch above, which already proves the
# static state is presentable -- it is the same declarations, applied when
# scripting rather than motion is unavailable. With JS the block is inert
# (browsers ignore noscript content when scripting is on), so the animation is
# untouched.
#
# `transition:none` is load-bearing, not tidiness. `.el` transitions opacity, so
# merely declaring the final opacity starts a transition toward it -- and a
# transition only advances while the document's animation timeline runs. In a
# background or throttled tab the timeline is frozen, the transition never
# progresses, and the computed opacity stays at 0: the page is blank again,
# through a rule that says `opacity:1 !important`. Verified by injecting these
# declarations into a real pending document: without this line 0 of 10 elements
# became visible, with it all 10 did. The reduced-motion block above kills
# transitions for the same reason.
_CANVAS_NOSCRIPT_FALLBACK = (
    "<noscript><style>"
    ".el,.vec,#tc-stage::after{transition:none !important;will-change:auto !important}"
    "#tc-stage::after{opacity:0 !important}"
    "#tc-stage[data-reveal='pending'] .rise-fade,#tc-stage[data-reveal='pending'] .count-up,"
    "#tc-stage[data-reveal='pending'] .scale-in,#tc-stage[data-reveal='pending'] .grow-y,"
    "#tc-stage[data-reveal='pending'] .grow-x,#tc-stage[data-reveal='pending'] .sweep"
    "{opacity:1 !important;transform:none !important}"
    "[data-draw]{stroke-dashoffset:0 !important}"
    "</style></noscript>"
)

_CANVAS_JS_TEMPLATE = (
    "(function(){var stage=document.getElementById('tc-stage');if(!stage)return;"
    "function __fit(){var w=document.documentElement.clientWidth||window.innerWidth||__SW__;"
    "var s=Math.min(1,w/__SW__);stage.style.transform='scale('+s+')';"
    "var f=document.getElementById('tc-fit');if(f)f.style.height=(__SH__*s)+'px';}"
    "window.addEventListener('resize',__fit);__fit();"
    "var reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;"
    # Each count-up ships its final value so a script-less render shows real
    # numbers. Zero them here -- this runs at end of body, before the first
    # paint, so the count-up still starts from 0 with no flash of the answer.
    "if(!reduced)document.querySelectorAll('[data-count]').forEach(function(el){el.textContent='0';});"
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
