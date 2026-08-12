"""Point-at-anything redesign: change only what the user selected.

The old "Redesign with AI" button posted an empty body and re-generated the
whole dashboard from job context. There was nowhere to say what you wanted,
so pressing it re-rolled the dice and usually landed somewhere close to where
it started — which reads, correctly, as a button that does nothing.

This module takes a SELECTION plus an INSTRUCTION and routes each target to
the highest-fidelity channel it has:

  * a target with a ``ui_id``            -> a layout/style patch, applied in
    the browser through the layout book (per workspace and breakpoint)
  * a target with a ``spec_kind``/``spec_id`` and a job in context
                                          -> a patch against the SAVED
    dashboard spec, persisted through the WorkStore

Anything neither channel can express is returned in ``unsupported`` with a
reason. Counts are computed by diffing the spec AFTER application, never from
what the model claimed it would do: a redesign that changed nothing must be
able to say so.
"""

from __future__ import annotations

import copy
import logging
import re
from pathlib import Path
from typing import Any

from thomas.server.routes.work_dashboard_runtime import (
    _build_llm,
    _extract_json,
    validate_dashboard_spec,
)

log = logging.getLogger(__name__)

_MAX_TARGETS = 24
_MAX_INSTRUCTION = 2000
_MAX_ICONS = 200
_ICON_NAME = re.compile(r"^ph-[a-z0-9-]+$")

# Mirrors STYLE_PROPS in ui_edit_layout.js. Kept in lockstep deliberately:
# the browser drops anything outside its own list, so letting the model
# return more here would only produce silent no-ops.
_STYLE_PROPS = {
    "color", "background", "backgroundColor", "borderColor", "borderRadius",
    "borderWidth", "borderStyle", "fontSize", "fontWeight", "fontStyle",
    "letterSpacing", "lineHeight", "textAlign", "textTransform", "padding",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "margin",
    "marginTop", "marginRight", "marginBottom", "marginLeft", "gap",
    "opacity", "boxShadow", "outline", "flexDirection", "justifyContent",
    "alignItems", "gridTemplateColumns", "order", "textDecoration",
}

_INDEXED_KINDS = {"metric": "metrics", "widget": "widgets", "section": "sections", "inbox": "inboxes"}
_KEYED_KINDS = {"sheet": "sheets", "action": "actions", "tab": "tabs"}

_SCHEMA_HINT = """Return ONLY a JSON object, no prose, in exactly this shape:
{
  "layout": [{"target": 0, "style": {"fontSize": "20px", "color": "#8b8cff"}, "icon": "ph-gear-six", "width": 420, "height": 260, "hidden": false}],
  "dashboard": [{"target": 1, "op": "update", "patch": {"label": "Late loads", "value": "3", "tone": "bad"}}],
  "unsupported": [{"target": 2, "reason": "one short sentence, in plain language, saying why this one cannot be done"}]
}
Rules:
- "target" is the integer index from the TARGETS list. Never invent an index.
- Put a target in "layout" ONLY if it is marked layout-addressable.
- Put a target in "dashboard" ONLY if it is marked spec-addressable.
- A target may appear in BOTH lists when the instruction asks for a visual
  change and a content change at once.
- "op" is "update" (merge "patch" into the entry) or "remove" (delete it).
- Style values are plain CSS values; no url(), no semicolons.
- "icon" may ONLY be used on a target marked ICON, and its value MUST be one of
  the names in AVAILABLE ICONS. Any other name renders as a blank dot. If the
  icon the user asked for is not on that list, do not guess a near-miss — put
  the target in "unsupported" and say the icon does not exist yet.
- Every target you were given must appear in exactly one of the three lists.
  If you cannot do what was asked for a target, say so in "unsupported" with
  a concrete reason. Do not silently omit it, and do not invent a change you
  were not asked for just to have something to return."""


def _clean_style(value: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(value, dict):
        return out
    for key, raw in value.items():
        prop = str(key)
        if "-" in prop:
            head, *rest = prop.split("-")
            prop = head + "".join(part[:1].upper() + part[1:] for part in rest)
        if prop not in _STYLE_PROPS:
            continue
        text = str(raw or "").strip()
        if not text or len(text) > 160:
            continue
        lowered = text.lower()
        if "url(" in lowered or "expression(" in lowered or "@import" in lowered:
            continue
        if any(char in text for char in ";{}<>"):
            continue
        out[prop] = text
    return out


def _target_lines(targets: list[dict[str, Any]]) -> str:
    lines = []
    for index, target in enumerate(targets):
        channels = []
        if target.get("isIcon"):
            current = str(target.get("icon") or "(none)")
            channels.append(f"ICON, currently {current} — you may set a new one with \"icon\"")
        if str(target.get("uiId") or ""):
            channels.append("layout-addressable")
        if str(target.get("specKind") or ""):
            channels.append(f"spec-addressable ({target.get('specKind')} {target.get('specId')})")
        if not channels:
            owner = str(target.get("ownerUiId") or "")
            channels.append(
                "NOT addressable — describe why in unsupported"
                + (f" (it sits inside {owner}, which is NOT the same thing)" if owner else "")
            )
        text = str(target.get("text") or "").strip()
        lines.append(
            f"[{index}] {target.get('label') or 'element'} "
            f"<{target.get('component') or 'element'}> — {', '.join(channels)}"
            + (f'\n     shows: "{text[:120]}"' if text else "")
        )
    return "\n".join(lines)


def _spec_entry(dashboard: dict[str, Any], kind: str, key: str) -> tuple[str, Any] | None:
    """Locate one saved dashboard entry from a selection's spec address."""
    if kind == "headline":
        return ("headline", dashboard.get("headline", ""))
    if kind in _INDEXED_KINDS:
        rows = dashboard.get(_INDEXED_KINDS[kind])
        if not isinstance(rows, list):
            return None
        try:
            position = int(key)
        except (TypeError, ValueError):
            return None
        if position < 0 or position >= len(rows):
            return None
        return (_INDEXED_KINDS[kind], position)
    if kind in _KEYED_KINDS:
        rows = dashboard.get(_KEYED_KINDS[kind])
        if not isinstance(rows, list):
            return None
        for position, row in enumerate(rows):
            if isinstance(row, dict) and str(row.get("id") or "") == str(key):
                return (_KEYED_KINDS[kind], position)
        return None
    return None


def _apply_dashboard_ops(
    dashboard: dict[str, Any],
    ops: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply spec ops. Returns (baseline, new_spec, applied, rejected).

    The baseline is the UNEDITED spec put through the same validation as the
    result. Comparing raw-before against validated-after would score schema
    normalisation as a user-visible change, and this feature's whole job is
    to not overstate what it did.
    """
    baseline = validate_dashboard_spec(copy.deepcopy(dashboard), workflows)
    working = copy.deepcopy(dashboard)
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for op in ops:
        index = op.get("target")
        if not isinstance(index, int) or index < 0 or index >= len(targets):
            continue
        target = targets[index]
        kind = str(target.get("specKind") or "")
        key = str(target.get("specId") or "")
        label = str(target.get("label") or "that element")
        if not kind:
            rejected.append({"target_index": index, "label": label, "reason": "this is not a saved dashboard item, so its content cannot be rewritten"})
            continue
        located = _spec_entry(working, kind, key)
        if located is None:
            rejected.append({"target_index": index, "label": label, "reason": "the saved dashboard no longer has this item"})
            continue
        field, position = located
        action = str(op.get("op") or "update").lower()
        if field == "headline":
            if action == "remove":
                working["headline"] = ""
            else:
                patch = op.get("patch")
                text = str((patch or {}).get("text") or (patch or {}).get("headline") or "").strip()
                if not text:
                    rejected.append({"target_index": index, "label": label, "reason": "no replacement headline text was returned"})
                    continue
                working["headline"] = text
            applied.append({"target_index": index, "kind": kind, "id": key})
            continue
        rows = working.get(field)
        if action == "remove":
            rows.pop(position)
            applied.append({"target_index": index, "kind": kind, "id": key})
            continue
        patch = op.get("patch")
        if not isinstance(patch, dict) or not patch:
            rejected.append({"target_index": index, "label": label, "reason": "no replacement content was returned for it"})
            continue
        current = rows[position]
        if not isinstance(current, dict):
            rejected.append({"target_index": index, "label": label, "reason": "the saved entry is malformed"})
            continue
        current.update(patch)
        applied.append({"target_index": index, "kind": kind, "id": key})
    validated = validate_dashboard_spec(working, workflows)
    return baseline, validated, applied, rejected


def _changed_count(before: dict[str, Any], after: dict[str, Any], applied: list[dict[str, Any]]) -> int:
    """Count entries that genuinely differ. A no-op patch is not a change."""
    if not applied:
        return 0
    changed = 0
    for row in applied:
        kind = str(row.get("kind") or "")
        field = _INDEXED_KINDS.get(kind) or _KEYED_KINDS.get(kind)
        if kind == "headline":
            if before.get("headline") != after.get("headline"):
                changed += 1
            continue
        if not field:
            continue
        if before.get(field) != after.get(field):
            changed += 1
    return changed


async def redesign_from_selection(
    root: Path,
    profile: str,
    payload: dict[str, Any],
    *,
    job_context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    """Turn a selection plus an instruction into typed, applied edits."""
    instruction = str(payload.get("instruction") or "").strip()[:_MAX_INSTRUCTION]
    raw_targets = payload.get("targets")
    targets = [row for row in (raw_targets if isinstance(raw_targets, list) else []) if isinstance(row, dict)][:_MAX_TARGETS]
    if not instruction:
        return None, "no instruction was given"
    if not targets:
        return None, "nothing was selected"

    llm = _build_llm(root, profile)
    if llm is None:
        return None, "no model available"

    job = (job_context or {}).get("job") or {}
    dashboard = dict(job.get("dashboard") or {})
    workflows = list((job_context or {}).get("workflows") or [])
    spec_note = ""
    if dashboard:
        spec_note = (
            "\n\nThe SAVED dashboard spec for the job these elements belong to "
            "(spec-addressable targets index into this):\n"
            f"{_extract_spec_summary(dashboard)}"
        )

    # Thomas's icons are a Unicode map in chat_shell.css, not a webfont, so the
    # renderable set is small and exact. The browser reads it off the stylesheet
    # and sends it; without it the model invents plausible Phosphor names that
    # come out as a bullet.
    vocabulary = [
        name for name in (payload.get("icon_vocabulary") or [])
        if isinstance(name, str) and _ICON_NAME.match(name)
    ][:_MAX_ICONS]
    icon_note = ""
    if vocabulary and any(row.get("isIcon") for row in targets):
        icon_note = "\n\nAVAILABLE ICONS (the complete set that renders — anything else is a blank dot):\n" + ", ".join(vocabulary)

    prompt = (
        "The user pointed at specific parts of their Thomas workspace and said "
        "what they want changed. Change ONLY what they pointed at.\n\n"
        f"THEIR INSTRUCTION:\n{instruction}\n\n"
        f"TARGETS:\n{_target_lines(targets)}"
        f"{spec_note}{icon_note}\n\n"
        f"{_SCHEMA_HINT}"
    )

    try:
        result = await llm.chat([{"role": "user", "content": prompt}])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, f"model call failed: {exc}"

    plan = _extract_json(str((result or {}).get("text") or ""))
    if plan is None:
        return None, "model did not return a valid edit plan"

    layout_rows, layout_rejected = _plan_layout(plan.get("layout"), targets, vocabulary)
    dashboard_result: dict[str, Any] = {"changed": 0, "applied": [], "dashboard": None}
    spec_rejected: list[dict[str, Any]] = []
    ops = [row for row in (plan.get("dashboard") or []) if isinstance(row, dict)]
    if ops and not job:
        for op in ops:
            index = op.get("target")
            if isinstance(index, int) and 0 <= index < len(targets):
                spec_rejected.append({
                    "target_index": index,
                    "label": str(targets[index].get("label") or "that element"),
                    "reason": "content edits need an open job; this element is part of the app shell",
                })
    elif ops:
        baseline, after, applied, spec_rejected = _apply_dashboard_ops(dashboard, ops, targets, workflows)
        changed = _changed_count(baseline, after, applied)
        # An op that landed but moved nothing is reported as untouched, not
        # as a success: "I set it to what it already was" is not a change.
        for row in applied:
            index = row.get("target_index")
            field = _INDEXED_KINDS.get(row.get("kind", "")) or _KEYED_KINDS.get(row.get("kind", ""))
            same = baseline.get("headline") == after.get("headline") if row.get("kind") == "headline" else (
                field is not None and baseline.get(field) == after.get(field)
            )
            if same and isinstance(index, int) and 0 <= index < len(targets):
                spec_rejected.append({
                    "target_index": index,
                    "label": str(targets[index].get("label") or "that element"),
                    "reason": "the edit Thomas returned matched what was already there",
                })
        dashboard_result = {
            "changed": changed,
            "applied": [row for row in applied if not any(
                r.get("target_index") == row.get("target_index") for r in spec_rejected
            )],
            "dashboard": after,
        }

    unsupported = _plan_unsupported(plan.get("unsupported"), targets)
    unsupported.extend(layout_rejected)
    unsupported.extend(spec_rejected)
    return {
        "layout": layout_rows,
        "dashboard": dashboard_result,
        "unsupported": unsupported,
        "instruction": instruction,
        "targets": targets,
    }, ""


def code_thread_prompt(instruction: str, targets: list[dict[str, Any]], workspace: str) -> str:
    """The brief waiting in the Code thread if the user wants to go deeper."""
    lines = []
    for target in targets:
        bits = [f"- {target.get('label') or 'element'} (<{target.get('component') or 'element'}>)"]
        if target.get("uiId"):
            bits.append(f"ui id `{target['uiId']}`")
        if target.get("specKind"):
            bits.append(f"dashboard {target['specKind']} {target.get('specId')}")
        if target.get("isIcon"):
            bits.append(f"icon `{target.get('icon') or '(none)'}`")
        lines.append(", ".join(bits))
    return (
        "This started as a Redesign-with-AI tweak in the Thomas UI, which only "
        "changes how it looks for this browser. Make it real in the source.\n\n"
        f"What was asked for:\n{instruction}\n\n"
        f"What was pointed at (workspace `{workspace}`):\n" + "\n".join(lines) + "\n\n"
        "The UI regions live in thomas/server/web/ — chat.html for the shell, "
        "js/unified_work_support.js for the Work surface, and the matching css/ "
        "file for styling. Icons are a Unicode map in css/chat_shell.css "
        "(`.ph-<name>::before`), not a webfont, so a new icon means adding a "
        "glyph there. Find where this element is authored and change it "
        "properly, rather than reproducing the per-browser style override."
    )


def _extract_spec_summary(dashboard: dict[str, Any]) -> str:
    import json

    summary = {
        "headline": dashboard.get("headline", ""),
        "tabs": dashboard.get("tabs", []),
        "metrics": dashboard.get("metrics", []),
        "widgets": dashboard.get("widgets", []),
        "sheets": [
            {"id": row.get("id"), "title": row.get("title"), "columns": row.get("columns")}
            for row in (dashboard.get("sheets") or [])
            if isinstance(row, dict)
        ],
        "sections": dashboard.get("sections", []),
        "inboxes": dashboard.get("inboxes", []),
    }
    return json.dumps(summary, ensure_ascii=False)[:6000]


def _plan_layout(
    rows: Any,
    targets: list[dict[str, Any]],
    vocabulary: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    known_icons = set(vocabulary or [])
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        index = row.get("target")
        if not isinstance(index, int) or index < 0 or index >= len(targets):
            continue
        target = targets[index]
        ui_id = str(target.get("uiId") or "")
        label = str(target.get("label") or "that element")
        icon = str(row.get("icon") or "").strip()
        if icon:
            # Caught here rather than in the browser: an unknown name renders
            # as a bullet, which reads as a broken button instead of an error.
            if not target.get("isIcon"):
                rejected.append({"target_index": index, "label": label, "reason": "this is not an icon, so it has no glyph to swap"})
                icon = ""
            elif not _ICON_NAME.match(icon):
                rejected.append({"target_index": index, "label": label, "reason": f'"{icon}" is not a valid icon name'})
                icon = ""
            elif known_icons and icon not in known_icons:
                rejected.append({
                    "target_index": index,
                    "label": label,
                    "reason": f'"{icon}" is not in Thomas\'s icon set yet — open this in Code to add the glyph',
                })
                icon = ""
        if not ui_id:
            rejected.append({
                "target_index": index,
                "label": label,
                "reason": "this part of the page has no stable identity yet, so a saved style cannot be pinned to it",
            })
            continue
        entry: dict[str, Any] = {"target_index": index, "ui_id": ui_id}
        style = _clean_style(row.get("style"))
        if style:
            entry["style"] = style
        if icon:
            entry["icon"] = icon
        for key in ("x", "y", "width", "height", "z"):
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[key] = float(value)
        if isinstance(row.get("hidden"), bool):
            entry["hidden"] = row["hidden"]
        if len(entry) <= 2:
            rejected.append({
                "target_index": index,
                "label": label,
                "reason": "the change asked for is not something a style or size edit can express",
            })
            continue
        out.append(entry)
    return out, rejected


def _plan_unsupported(rows: Any, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        index = row.get("target")
        if not isinstance(index, int) or index < 0 or index >= len(targets):
            continue
        out.append({
            "target_index": index,
            "label": str(targets[index].get("label") or "that element"),
            "reason": str(row.get("reason") or "Thomas did not say why").strip()[:240],
        })
    return out
