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

from thomas.server.overlay.style_whitelist import clean_style
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

# The style whitelist and value guard live in thomas/server/overlay/style_whitelist.py,
# the one copy ui_edit_layout.js mirrors: the browser drops anything outside
# its own list, so a wider list here would only produce silent no-ops.

_INDEXED_KINDS = {"metric": "metrics", "widget": "widgets", "section": "sections", "inbox": "inboxes"}
_KEYED_KINDS = {"sheet": "sheets", "action": "actions", "tab": "tabs"}

_SCHEMA_HINT = """Return ONLY a JSON object, no prose, in exactly this shape:
{
  "layout": [{"target": 0, "style": {"fontSize": "20px", "color": "#8b8cff"}, "icon": "ph-gear-six", "text": "Start a build", "width": 420, "height": 260, "hidden": false}],
  "dashboard": [{"target": 1, "op": "update", "patch": {"label": "Late loads", "value": "3", "tone": "bad"}}],
  "theme": {"tokens": {"--c-accent": "#2ecc71"}, "identity": {"name": "Otto"}},
  "unsupported": [{"target": 2, "reason": "one short sentence, in plain language, saying why this one cannot be done"}]
}
Rules:
- "theme" is OPTIONAL and reaches the WHOLE app, every tab and every reload.
  Put a value under "theme.tokens" when the ask is about a colour, font or
  shape that is one of the DESIGN TOKENS listed above, or is clearly global
  ("everywhere", "the whole app", "warmer overall"). Put a per-element "style"
  in "layout" when the ask is about the element that was pointed at. Never
  both for one ask. "theme.identity" renames the assistant; its fields are
  name, tagline, placeholder, title, welcome.title, welcome.sub.
- "target" is the integer index from the TARGETS list. Never invent an index.
- Put a target in "layout" ONLY if it is marked layout-addressable.
- Put a target in "dashboard" ONLY if it is marked spec-addressable.
- A target may appear in BOTH lists when the instruction asks for a visual
  change and a content change at once.
- "op" is "update" (merge "patch" into the entry) or "remove" (delete it).
- Style values are plain CSS values; no url(), no semicolons.
- "text" changes what an element SAYS: its whole visible text, one plain line,
  no markup. Use it ONLY on a target marked TEXT (it shows text now). A target
  without TEXT has nothing to say; if the ask is about its words, put it in
  "unsupported" and say so.
- "icon" may ONLY be used on a target marked ICON, and its value MUST be one of
  the names in AVAILABLE ICONS. Any other name renders as a blank dot. If the
  icon the user asked for is not on that list, do not guess a near-miss — put
  the target in "unsupported" and say the icon does not exist yet.
- Every target you were given must appear in exactly one of the three lists.
  If you cannot do what was asked for a target, say so in "unsupported" with
  a concrete reason. Do not silently omit it, and do not invent a change you
  were not asked for just to have something to return.
- "width" and "height" are pixels and replace the element's size; each target
  line shows its current size, so a relative ask (twice as tall, half as wide)
  is that size multiplied. Never drop a size ask in silence: apply it, or put
  the target in "unsupported" saying why the size cannot change.
- You can only touch the targets that were locked. When the ask reaches
  beyond them (a whole section when only its heading is locked, every button
  when one is locked), do what the locked target allows AND ALSO list that
  target in "unsupported" saying exactly what remains and what to point at
  next. A change reported as complete when part of the ask is still undone
  is a false report; the admission is part of the work."""


def _size_note(box: Any) -> str:
    """'; size W×H px' from a target's box, or nothing when there is no usable size."""
    if not isinstance(box, dict):
        return ""
    try:
        width, height = int(box.get("width") or 0), int(box.get("height") or 0)
    except (TypeError, ValueError):
        return ""
    return f"; size {width}×{height} px" if width > 0 and height > 0 else ""


def _target_lines(targets: list[dict[str, Any]]) -> str:
    lines = []
    for index, target in enumerate(targets):
        channels = []
        if target.get("isIcon"):
            current = str(target.get("icon") or "(none)")
            channels.append(f'ICON, currently {current} — you may set a new one with "icon"')
        if str(target.get("uiId") or ""):
            channels.append("layout-addressable")
        if str(target.get("text") or "").strip():
            channels.append('TEXT — you may change what it says with "text"')
        if str(target.get("specKind") or ""):
            channels.append(f"spec-addressable ({target.get('specKind')} {target.get('specId')})")
        if not channels:
            owner = str(target.get("ownerUiId") or "")
            channels.append(
                "NOT addressable — describe why in unsupported"
                + (f" (it sits inside {owner}, which is NOT the same thing)" if owner else "")
            )
        text = str(target.get("text") or "").strip()
        # The current size, so a relative ask ("twice as tall") has a number to
        # work from; without it the model dropped the size in silence.
        size = _size_note(target.get("box"))
        lines.append(
            f"[{index}] {target.get('label') or 'element'} "
            f"<{target.get('component') or 'element'}> — {', '.join(channels)}{size}"
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
            rejected.append(
                {
                    "target_index": index,
                    "label": label,
                    "reason": "this is not a saved dashboard item, so its content cannot be rewritten",
                }
            )
            continue
        located = _spec_entry(working, kind, key)
        if located is None:
            rejected.append(
                {"target_index": index, "label": label, "reason": "the saved dashboard no longer has this item"}
            )
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
                    rejected.append(
                        {"target_index": index, "label": label, "reason": "no replacement headline text was returned"}
                    )
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
            rejected.append(
                {"target_index": index, "label": label, "reason": "no replacement content was returned for it"}
            )
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
    targets = [row for row in (raw_targets if isinstance(raw_targets, list) else []) if isinstance(row, dict)][
        :_MAX_TARGETS
    ]
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
        name for name in (payload.get("icon_vocabulary") or []) if isinstance(name, str) and _ICON_NAME.match(name)
    ][:_MAX_ICONS]
    icon_note = ""
    if vocabulary and any(row.get("isIcon") for row in targets):
        icon_note = "\n\nAVAILABLE ICONS (the complete set that renders — anything else is a blank dot):\n" + ", ".join(
            vocabulary
        )

    active_theme, in_effect = _tokens_in_effect(payload.get("theme"))
    tokens_note = (
        "\n\nDESIGN TOKENS (theme "
        + active_theme
        + "; the value in effect today):\n"
        + ", ".join(f"{key}={value}" for key, value in in_effect.items())
    )

    prompt = (
        "The user pointed at specific parts of their Thomas workspace and said "
        "what they want changed. Change ONLY what they pointed at.\n\n"
        f"THEIR INSTRUCTION:\n{instruction}\n\n"
        f"TARGETS:\n{_target_lines(targets)}"
        f"{spec_note}{icon_note}{tokens_note}\n\n"
        f"{_SCHEMA_HINT}"
    )

    try:
        result = await llm.chat([{"role": "user", "content": prompt}])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, f"model call failed: {exc}"

    plan = _extract_json(str((result or {}).get("text") or ""))
    if plan is None:
        return None, "model did not return a valid edit plan"

    theme_result = _plan_theme(plan.get("theme"), active_theme, in_effect)
    layout_rows, layout_rejected = _plan_layout(plan.get("layout"), targets, vocabulary)
    dashboard_result: dict[str, Any] = {"changed": 0, "applied": [], "dashboard": None}
    spec_rejected: list[dict[str, Any]] = []
    ops = [row for row in (plan.get("dashboard") or []) if isinstance(row, dict)]
    if ops and not job:
        for op in ops:
            index = op.get("target")
            if isinstance(index, int) and 0 <= index < len(targets):
                spec_rejected.append(
                    {
                        "target_index": index,
                        "label": str(targets[index].get("label") or "that element"),
                        "reason": "content edits need an open job; this element is part of the app shell",
                    }
                )
    elif ops:
        baseline, after, applied, spec_rejected = _apply_dashboard_ops(dashboard, ops, targets, workflows)
        changed = _changed_count(baseline, after, applied)
        # An op that landed but moved nothing is reported as untouched, not
        # as a success: "I set it to what it already was" is not a change.
        for row in applied:
            index = row.get("target_index")
            field = _INDEXED_KINDS.get(row.get("kind", "")) or _KEYED_KINDS.get(row.get("kind", ""))
            same = (
                baseline.get("headline") == after.get("headline")
                if row.get("kind") == "headline"
                else (field is not None and baseline.get(field) == after.get(field))
            )
            if same and isinstance(index, int) and 0 <= index < len(targets):
                spec_rejected.append(
                    {
                        "target_index": index,
                        "label": str(targets[index].get("label") or "that element"),
                        "reason": "the edit Thomas returned matched what was already there",
                    }
                )
        dashboard_result = {
            "changed": changed,
            "applied": [
                row
                for row in applied
                if not any(r.get("target_index") == row.get("target_index") for r in spec_rejected)
            ],
            "dashboard": after,
        }

    unsupported = _plan_unsupported(plan.get("unsupported"), targets)
    unsupported.extend(layout_rejected)
    unsupported.extend(spec_rejected)
    return {
        "layout": layout_rows,
        "dashboard": dashboard_result,
        "theme": theme_result,
        "unsupported": unsupported,
        "instruction": instruction,
        "targets": targets,
    }, ""


def _tokens_in_effect(theme: Any) -> tuple[str, dict[str, str]]:
    """The active theme's name and every stock token with the value in effect.

    Merged exactly as render.render_css paints it: stock nebula, the stock
    parent (the theme itself when stock, its derives_from when it is an overlay
    theme), the overlay's global records, the parent's records, the theme's own.
    """
    from thomas.server.overlay import render, stock_tokens
    from thomas.server.overlay.records import THEME_NAME

    name = str(theme or "").strip().lower()
    if not THEME_NAME.match(name):
        name = "nebula"
    stock = stock_tokens.load_stock()
    view = render.current_view()
    spec = (view.get("themes") or {}).get(name)
    base = str(spec.get("derives_from") or "nebula") if isinstance(spec, dict) else name
    values = dict(stock.get("nebula", {}))
    values.update(stock.get(base, {}))
    overlay_tokens = view.get("tokens") or {}
    values.update(overlay_tokens.get("*", {}))
    if base != name:
        values.update(overlay_tokens.get(base, {}))
    values.update(overlay_tokens.get(name, {}))
    return name, values


def _plan_theme(raw: Any, active_theme: str, in_effect: dict[str, str]) -> dict[str, Any]:
    """Validate the model's theme channel: stock keys only, guarded values, and a DIFF against what is in effect."""
    from thomas.server.overlay.records import IDENTITY_FIELDS, RESERVED_IDENTITY_FIELDS
    from thomas.server.overlay.style_whitelist import value_ok

    result: dict[str, Any] = {"theme": active_theme, "tokens": {}, "identity": {}, "rejected": []}
    if not isinstance(raw, dict):
        return result
    for key, value in (raw.get("tokens") or {}).items() if isinstance(raw.get("tokens"), dict) else []:
        key = str(key)
        text = str(value or "").strip()
        if key not in in_effect:
            result["rejected"].append({"address": key, "reason": f"{key} is not a design token on tokens.css :root"})
        elif not value_ok(text):
            result["rejected"].append({"address": key, "reason": "the value did not pass the style guard"})
        elif " ".join(text.split()).lower() == " ".join(str(in_effect[key]).split()).lower():
            result["rejected"].append(
                {"address": key, "reason": "the value Thomas returned matched what was already in effect"}
            )
        else:
            result["tokens"][key] = text
    for field, value in (raw.get("identity") or {}).items() if isinstance(raw.get("identity"), dict) else []:
        field = str(field)
        text = str(value or "").strip()
        if field in RESERVED_IDENTITY_FIELDS:
            result["rejected"].append(
                {"address": f"identity:{field}", "reason": f"{field} is reserved: no surface applies it yet"}
            )
        elif field not in IDENTITY_FIELDS:
            result["rejected"].append(
                {"address": f"identity:{field}", "reason": f"{field} is not a surface the overlay renames"}
            )
        elif not 0 < len(text) <= 80:
            result["rejected"].append(
                {"address": f"identity:{field}", "reason": "identity text must be 1-80 characters"}
            )
        else:
            result["identity"][field] = text
    return result


FENCE_BRIEF_LIMIT = 40
_CLAIM_LINE_RE = re.compile(r"^\s*-\s*agent=(?P<agent>[^;]+);(?P<rest>.*)$")
_CLAIM_SCOPE_RE = re.compile(r"(?:^|;)\s*scope=(?P<scope>[^;]*)")


def board_fenced_paths(workboard_text: str, *, exempt_agents: set[str]) -> list[str]:
    """Every scope entry another agent claims on the workboard, sorted, deduplicated.

    Only lines in the "## Agent Claims" section count; an agent in
    ``exempt_agents`` (the server's own environment decides who) is not fenced.
    A self-edit run gets this list as ``protected_paths`` so the write tools,
    not the prose, keep it out of other agents' files.
    """

    fenced: set[str] = set()
    in_claims = False
    for raw in str(workboard_text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_claims = line.strip().lower() == "## agent claims"
            continue
        if not in_claims:
            continue
        match = _CLAIM_LINE_RE.match(line)
        if not match:
            continue
        agent = match.group("agent").strip()
        if agent in exempt_agents:
            continue
        scope = _CLAIM_SCOPE_RE.search(match.group("rest"))
        if not scope:
            continue
        for entry in scope.group("scope").split(","):
            entry = entry.strip().replace("\\", "/")
            if entry and entry != "unknown":
                fenced.add(entry)
    return sorted(fenced)


def code_thread_prompt(
    instruction: str,
    targets: list[dict[str, Any]],
    workspace: str,
    *,
    unsupported: list[dict[str, Any]] | None = None,
    applied: list[str] | None = None,
    server_url: str = "",
    protected_paths: list[str] | None = None,
) -> str:
    """The brief the Code thread runs with: change Thomas's own UI to meet the ask."""
    from thomas.server.overlay import paths

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
    # Redesign is "edit this thing however I say" (the owner, 2026-09-06). The
    # overlay carries the small cases (a colour, a label, a size); everything
    # else is this brief, and it is a directive to change Thomas's own UI
    # source, not a note that the change is already done.
    not_done = [
        f"- {row.get('label') or 'that element'}: {row.get('reason') or 'no reason given'}"
        for row in (unsupported or [])
        if isinstance(row, dict)
    ]
    done = [f"- {row}" for row in (applied or []) if str(row).strip()]
    parts = [
        # Paths are given from the repository root: the acceptance contract turns
        # a path the task names into an output check, and a bare `css/chat_shell.css`
        # resolved against the root became an output that could never exist.
        "Change Thomas's own UI so that this ask is met, in the stock files under "
        "thomas/server/web/: the shell in thomas/server/web/chat.html, styles in "
        "thomas/server/web/css/, behaviour in thomas/server/web/js/ (icons are a Unicode "
        "map in thomas/server/web/css/chat_shell.css, `.ph-<name>::before`).",
        f"The ask, in the user's words:\n{instruction}",
        f"What was pointed at (workspace `{workspace}`):\n" + "\n".join(lines),
    ]
    if done:
        parts.append(
            "What the per-user overlay already applied (recorded at "
            f"{paths.overlay_dir()}); make the stock UI match it:\n" + "\n".join(done)
        )
    if not_done:
        parts.append("What the overlay could NOT do; do these in the source:\n" + "\n".join(not_done))
    # No imperative sentences here beyond the one verification instruction:
    # the acceptance contract turns imperatives into judged requirements, and
    # "keep the change minimal" was judged against the whole checkout's
    # uncommitted diff, other agents' work included, and ruled unmet on every
    # pass. Scope and taste are guidance; the ask above is the requirement.
    parts.append(
        "Guidance, not a checklist: a small change in keeping with the rest of the shell is "
        "the goal; the diff that is yours is the files this run touched, and other uncommitted "
        "changes in the checkout belong to other work and are not yours to judge or undo."
    )
    parts.append(
        "Verify it in the browser against the running server"
        + (f" at {server_url}" if server_url else "")
        + " (static files reload from disk; after the edit call web.playtest with that server URL as the "
        "page, e.g. page=http://127.0.0.1:8977/, and look at what rendered; never open the html from disk "
        "and never write scratch pages into the product folder), then say exactly what changed and where."
    )
    fenced = [str(p).strip() for p in (protected_paths or []) if str(p).strip()]
    if fenced:
        # The record carries every fenced path and the tools refuse all of them;
        # the brief only needs enough for the model to decline the right asks,
        # not 400 paths pasted into the prompt.
        shown = fenced[:FENCE_BRIEF_LIMIT]
        more = len(fenced) - len(shown)
        parts.append(
            f"Fenced files ({len(fenced)} in all), held by other agents on the workboard right now; the write tools "
            "will refuse every one of them and a change that needs one is not yours to make, say so instead of "
            "trying: " + ", ".join(shown) + (f", and {more} more" if more else "")
        )
    return "\n\n".join(parts)


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
                rejected.append(
                    {"target_index": index, "label": label, "reason": "this is not an icon, so it has no glyph to swap"}
                )
                icon = ""
            elif not _ICON_NAME.match(icon):
                rejected.append({"target_index": index, "label": label, "reason": f'"{icon}" is not a valid icon name'})
                icon = ""
            elif known_icons and icon not in known_icons:
                rejected.append(
                    {
                        "target_index": index,
                        "label": label,
                        "reason": f'"{icon}" is not in Thomas\'s icon set yet — open this in Code to add the glyph',
                    }
                )
                icon = ""
        if not ui_id:
            rejected.append(
                {
                    "target_index": index,
                    "label": label,
                    "reason": "this part of the page has no stable identity yet, so a saved style cannot be pinned to it",
                }
            )
            continue
        entry: dict[str, Any] = {"target_index": index, "ui_id": ui_id}
        style = clean_style(row.get("style"))
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
        text = " ".join(str(row.get("text") or "").split())
        if text:
            if not str(target.get("text") or "").strip():
                rejected.append(
                    {
                        "target_index": index,
                        "label": label,
                        "reason": "this element shows no text, so there is no text to change",
                    }
                )
            elif len(text) > 120 or "<" in text or ">" in text:
                rejected.append(
                    {
                        "target_index": index,
                        "label": label,
                        "reason": "the new text must be one plain line of at most 120 characters",
                    }
                )
            else:
                entry["text"] = text
        if len(entry) <= 2:
            rejected.append(
                {
                    "target_index": index,
                    "label": label,
                    "reason": "the change asked for is not something a style or size edit can express",
                }
            )
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
        out.append(
            {
                "target_index": index,
                "label": str(targets[index].get("label") or "that element"),
                "reason": str(row.get("reason") or "Thomas did not say why").strip()[:240],
            }
        )
    return out
