"""Canvas worker — a fast, STREAMING design/visual generator.

When the user asks for something visual (a chart, UI, diagram, drawing, design),
the task manager routes the task here instead of the slow file-building agent worker.
This worker does NOT build files step-by-step with tools — it streams a single
self-contained HTML document straight to the Canvas, so the user WATCHES it draw
itself live (the Claude-design effect). Its growing output is held in a per-execution
store that the /delegations poll surfaces and writes the final HTML to the task workspace.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable

from thomas.server.chat_delegation_canvas_client import (
    CANVAS_LLM_LOCK as _CANVAS_LLM_LOCK,
)
from thomas.server.chat_delegation_canvas_client import (
    LLM_CACHE as _LLM_CACHE,
)
from thomas.server.chat_delegation_canvas_client import (
    build_canvas_llm,
    start_canvas_keepalive,
)
from thomas.server.chat_delegation_canvas_client import canvas_diag as _diag
from thomas.server.chat_delegation_canvas_client import evict_canvas_llm as _evict_canvas_llm

# The deterministic renderer lives in its own module. Re-exported here so that
# `from thomas.server.chat_delegation_canvas import build_canvas_html` and the
# worker's `canvas.<name>` attribute lookups keep resolving exactly as before.
from thomas.server.chat_delegation_canvas_render import (
    _donut_path,
    _num,
    _partial_stage,
    _render_element,
    build_canvas_html,
    build_construction_shell,
    parse_spec,
    stream_elements,
)
from thomas.server.chat_delegation_canvas_review import review_canvas_html

# Per-execution streaming store (process-local; the poll handler reads it).
_LOCK = threading.Lock()
_STORE: dict[str, dict[str, Any]] = {}


# The gpt-5.5 / codex-OAuth provider silently HANGS (no first token, no error) when
# Serialize canvas generations through one lock so overlapping calls cannot compete,
# they never compete, and reuse one LLM client per profile to avoid connection churn.
def canvas_start(execution_id: str, title: str = "") -> None:
    with _LOCK:
        _STORE[str(execution_id)] = {
            "html": "",
            "status": "streaming",
            "review_status": "pending",
            "review_issues": [],
            "review_evidence": {},
            "title": str(title or ""),
        }


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


def canvas_set_plan(execution_id: str, plan: str) -> None:
    """Persist the reviewed planner spec for matching PDF/data export."""

    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["plan"] = str(plan or "")


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


def canvas_set_review(execution_id: str, evidence: dict[str, Any]) -> None:
    """Persist structured semantic-review evidence beside the streamed render."""

    payload = dict(evidence or {})
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    with _LOCK:
        rec = _STORE.get(str(execution_id))
        if rec is not None:
            rec["review_status"] = str(payload.get("status") or "failed")
            rec["review_issues"] = [
                str(issue.get("message") if isinstance(issue, dict) else issue)
                for issue in issues
                if str(issue).strip()
            ]
            rec["review_evidence"] = payload


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
# --------------------------------------------------------------------------- #


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
    '               "stagger_from":"first|center|last","total_ms":<int ~1300>,"hero":"<primary id>"},\n'
    '  "data": [{"label":"<category>","value":<number>}, ...]   // charts only — see DATA\n'
    "}\n"
    "\n"
    # Everything downstream used to reverse-engineer the series back out of the
    # DRAWING -- pairing value labels to axis labels by pixel coordinates. That
    # works until the next plan draws the same chart differently: bar+number,
    # bar+text, donut with "Electricity 5.2 - 48.6%" as one legend string, donut
    # with the name and the figure as two separate elements. Each shape needed
    # its own rule and the one after it broke again, and when a rule missed, the
    # user got a chart with no data file. The planner already knows the exact
    # series -- it just was never asked to write it down.
    "DATA — if the visual is a chart (bars, columns, pie, donut, line, area, scatter), you MUST "
    'also emit the top-level "data" array: one {"label","value"} per category, the SAME numbers '
    "you drew, in the order they read in the chart. Labels are the category names a person would "
    "say out loud (Electricity, Drive alone, Cavendish) — never Series 1. Values are plain "
    "numbers: no % sign, no units, no thousands separators (write 5.2 and 1528, not 5.2 quads and "
    '1,528). Put the unit in the subtitle instead. Omit "data" only for non-charts (diagrams, UI '
    "mockups, illustrations). This is what the reader downloads as a spreadsheet, so it must match "
    "the picture exactly.\n"
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
    # Without this the model hedges on anything factual: "how people commute to
    # work" came back as ONE bar reading 100%, captioned "Illustrative
    # distribution". That is the shape of a chart with none of the information,
    # and it is what makes Thomas feel useless to someone who just wanted to
    # know how people get to work.
    "- CHART THE ACTUAL FIGURES. If the request names something real — a country, a market, a "
    "language, a species, a survey, a year — give the real breakdown as best you know it, with "
    "a small caption naming where the figures come from. NEVER invent a stand-in distribution, "
    "never caption a visual illustrative / sample / example / dummy / representative, and never "
    "collapse a real breakdown into a single 100% bar. If your numbers are approximate, still "
    "give the real breakdown and say approximate in the caption: an honest estimate of the real "
    "thing is useful, a made-up shape is not. A chart needs at least 2 categories to be a chart.\n"
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


async def run_canvas_worker(
    *,
    execution_id: str,
    prompt: str,
    root: Path,
    profile: str | None = None,
    model_id: str | None = None,
    emit_progress: Callable[[str], Awaitable[None]] | None = None,
    record_runtime: Callable[[dict[str, Any]], None] | None = None,
    session_llm: Any = None,
    runtime_policy: dict[str, Any] | None = None,
) -> str:
    """Run the Canvas generator while preserving this module's public API."""

    from thomas.server.chat_delegation_canvas_worker import run_canvas_worker as run_worker

    return await run_worker(
        execution_id=execution_id,
        prompt=prompt,
        root=root,
        profile=profile,
        model_id=model_id,
        emit_progress=emit_progress,
        record_runtime=record_runtime,
        session_llm=session_llm,
        runtime_policy=runtime_policy,
    )
