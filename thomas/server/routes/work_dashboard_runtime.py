"""AI-designed per-job dashboards for Work mode.

The dashboard schema ({metrics, sections, artifacts}) shipped empty for every
real job because the only population path was a manual "Save dashboard item"
form. This module adds the generative core the product promised: an LLM reads
one job's real context (onboarding, workflows, automations, connectors) and
designs a bespoke dashboard — metrics, sections, ACTION BUTTONS bound to the
job's own workflows, and inboxes — persisted through the WorkStore.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

# A work_store lookup that fails because the job is absent or unreadable.
# The store arrives injected (typed Any), so its concrete error class cannot
# be named here; these are the shapes "not found / not readable" takes.
_WORK_STORE_FAULTS = (LookupError, ValueError, TypeError, AttributeError, OSError, sqlite3.Error)

log = logging.getLogger(__name__)

# Bounded spec: the model designs within these shapes; everything else is
# dropped. Buttons may ONLY bind to the job's existing workflows/automations —
# the model cannot invent an executable.
_MAX_METRICS = 8
_MAX_SECTIONS = 6
_MAX_ACTIONS = 6
_MAX_INBOXES = 4

_SCHEMA_HINT = """Return ONLY a JSON object, no prose, in exactly this shape:
{
  "headline": "one-line dashboard purpose in the job's own language",
  "tabs": [{"id": "overview", "label": "Overview"}, {"id": "data", "label": "Data"}, {"id": "ops", "label": "Operations"}],
  "metrics": [{"tab": "overview", "label": "...", "value": "...", "hint": "why this number matters", "tone": "good|warn|bad|neutral"}],
  "widgets": [
    {"tab": "overview", "kind": "bar_chart", "title": "...", "bars": [{"label": "Mon", "value": 12}, {"label": "Tue", "value": 8}]},
    {"tab": "overview", "kind": "progress", "title": "...", "label": "Compliant devices", "pct": 72, "tone": "good|warn|bad"},
    {"tab": "ops", "kind": "status_list", "title": "...", "items": [{"label": "Broker verified", "tone": "good"}, {"label": "Driver conflict", "tone": "bad"}]}
  ],
  "sheets": [
    {"tab": "data", "title": "Load Tracker", "columns": ["Date", "Driver", "Broker", "Rate", "Status"],
     "rows": [["2026-07-19", "J. Smith", "Acme Logistics", "$1,200", "Booked"], ["2026-07-19", "T. Reed", "Bulk Freight", "$980", "Pending"]]}
  ],
  "sections": [{"tab": "overview", "title": "...", "text": "2-4 sentences of standing guidance for this job"}],
  "actions": [{"workflow_id": "<id from the workflow list>", "label": "verb-first button label", "description": "what pressing it does"}],
  "inboxes": [{"tab": "ops", "label": "...", "source": "<connector id or 'activity'>", "description": "what lands here"}]
}
Rules: every action's workflow_id MUST come from the provided workflow list —
invent nothing. Design this dashboard like a small APP for this company:
2-4 TABS that organize the job (always start with an Overview tab; add the
tabs THIS job actually needs — Data, Operations, Fleet, Roster, Compliance,
whatever fits). Assign every metric/widget/sheet/section/inbox to one of your
tabs by its id. When the job is data-heavy (loads, devices, players, orders,
inventory), include a Data tab with 1-2 SPREADSHEETS whose columns fit the
real work and 3-8 realistic starter rows the user can edit in place. Design
1-3 widgets that fit the domain; use representative example numbers when live
data isn't wired yet; metrics without live data use value "—". Every job
should look visibly different."""


def _build_llm(root: Path, profile: str) -> Any | None:
    """Construct an LLMClient (server->core import, guarded)."""
    try:
        from thomas.core.config import load_config
        from thomas.core.llm_client import LLMClient

        cfg = load_config(Path(root) / "thomas.toml")
        model_cfg = cfg.get_model(profile or None)
        return LLMClient(model_cfg)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
        log.warning("Work dashboard: could not build LLM client: %s", exc)
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def job_design_context(app: dict[str, Any], job: dict[str, Any], workflows: list[dict[str, Any]]) -> str:
    """Compact, credential-free context the designer model reads."""
    onboarding = dict((app.get("onboarding") or {}).get("fields") or {})
    memory = dict(job.get("memory") or {})
    bindings = [
        {"connector": b.get("connector_id"), "scope": b.get("scope")}
        for b in (job.get("connector_bindings") or [])
        if isinstance(b, dict) and b.get("enabled", True)
    ]
    automations = [
        {"id": a.get("id"), "name": a.get("name"), "enabled": a.get("enabled")}
        for a in (job.get("automations") or [])
        if isinstance(a, dict)
    ]
    flows = [
        {
            "id": w.get("id"),
            "name": w.get("name"),
            "purpose": w.get("purpose"),
            "type": w.get("type"),
            "status": w.get("status"),
            "automation_id": w.get("automation_id"),
        }
        for w in workflows
        if isinstance(w, dict)
    ]
    context = {
        "app": {"name": app.get("name"), "description": app.get("description")},
        "job": {
            "name": job.get("name"),
            "description": job.get("description"),
            "status": job.get("status"),
            "settings": job.get("settings"),
        },
        "onboarding": {k: onboarding[k] for k in sorted(onboarding) if not str(k).startswith("_")},
        "workflows": flows,
        "automations": automations,
        "connectors": bindings,
        "memory_summary": str(memory.get("summary") or "")[:800],
    }
    return json.dumps(context, ensure_ascii=False, default=str)


def _clean_rows(rows: Any, allowed: tuple[str, ...], limit: int) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        item = {key: str(row.get(key) or "").strip()[:400] for key in allowed}
        if any(item.values()):
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


def validate_dashboard_spec(spec: dict[str, Any], workflows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bound the model's design to the schema and the job's REAL workflows."""
    known_flows = {str(w.get("id") or ""): w for w in workflows if isinstance(w, dict)}
    actions: list[dict[str, str]] = []
    for row in spec.get("actions") if isinstance(spec.get("actions"), list) else []:
        if not isinstance(row, dict):
            continue
        wf_id = str(row.get("workflow_id") or "").strip()
        flow = known_flows.get(wf_id)
        if flow is None:
            continue
        actions.append(
            {
                "id": f"action-{wf_id}",
                "workflow_id": wf_id,
                "label": str(row.get("label") or flow.get("name") or "Run workflow").strip()[:80],
                "description": str(row.get("description") or "").strip()[:240],
            }
        )
        if len(actions) >= _MAX_ACTIONS:
            break
    tabs = _clean_tabs(spec.get("tabs"))
    tab_ids = {t["id"] for t in tabs}
    default_tab = tabs[0]["id"] if tabs else ""

    def _with_tab(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            tab = str(row.pop("tab", "") or "").strip().lower()
            row["tab"] = tab if tab in tab_ids else default_tab
        return rows

    metrics = _clean_rows(spec.get("metrics"), ("label", "value", "hint", "tone", "tab"), _MAX_METRICS)
    widgets = _clean_widgets(spec.get("widgets"))
    sections = _clean_rows(spec.get("sections"), ("title", "text", "tab"), _MAX_SECTIONS)
    inboxes = _clean_rows(spec.get("inboxes"), ("label", "source", "description", "tab"), _MAX_INBOXES)
    sheets = _clean_sheets(spec.get("sheets"))
    return {
        "headline": str(spec.get("headline") or "").strip()[:200],
        "tabs": tabs,
        "metrics": _with_tab(metrics),
        "widgets": _with_tab(widgets),
        "sheets": _with_tab(sheets),
        "sections": _with_tab(sections),
        "actions": actions,
        "inboxes": _with_tab(inboxes),
    }


_MAX_WIDGETS = 4
_MAX_TABS = 5
_MAX_SHEETS = 4
_MAX_SHEET_COLS = 12
_MAX_SHEET_ROWS = 60
_TONES = {"good", "warn", "bad", "neutral"}


def _tone(value: Any) -> str:
    t = str(value or "neutral").strip().lower()
    return t if t in _TONES else "neutral"


def _clean_tabs(rows: Any) -> list[dict[str, str]]:
    """Bound the tab layout; always at least an Overview tab."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw_id = re.sub(r"[^a-z0-9_-]", "", str(row.get("id") or "").strip().lower())[:24]
        label = str(row.get("label") or "").strip()[:24]
        if not raw_id or not label or raw_id in seen:
            continue
        seen.add(raw_id)
        out.append({"id": raw_id, "label": label})
        if len(out) >= _MAX_TABS:
            break
    if not out:
        out = [{"id": "overview", "label": "Overview"}]
    return out


def _clean_sheets(rows: Any) -> list[dict[str, Any]]:
    """Bound AI-designed spreadsheets to safe, editable shapes."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        cols = [
            str(c).strip()[:40]
            for c in (row.get("columns") if isinstance(row.get("columns"), list) else [])
            if str(c).strip()
        ]
        cols = cols[:_MAX_SHEET_COLS]
        if not cols:
            continue
        cleaned_rows: list[list[str]] = []
        for r in row.get("rows") if isinstance(row.get("rows"), list) else []:
            if not isinstance(r, list):
                continue
            cells = [str(c if c is not None else "").strip()[:200] for c in r[: len(cols)]]
            cells += [""] * (len(cols) - len(cells))
            cleaned_rows.append(cells)
            if len(cleaned_rows) >= _MAX_SHEET_ROWS:
                break
        out.append(
            {
                "id": str(row.get("id") or f"sheet-{i + 1}").strip()[:40],
                "tab": row.get("tab"),
                "title": str(row.get("title") or f"Sheet {i + 1}").strip()[:80],
                "columns": cols,
                "rows": cleaned_rows,
            }
        )
        if len(out) >= _MAX_SHEETS:
            break
    return out


def _clean_widgets(rows: Any) -> list[dict[str, Any]]:
    """Bound AI-designed visual widgets to safe, renderable shapes."""
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        title = str(row.get("title") or "").strip()[:80]
        tab = row.get("tab")
        if kind == "bar_chart":
            bars = []
            for b in row.get("bars") if isinstance(row.get("bars"), list) else []:
                if not isinstance(b, dict):
                    continue
                try:
                    val = float(b.get("value"))
                except (TypeError, ValueError):
                    continue
                bars.append({"label": str(b.get("label") or "").strip()[:24], "value": max(0.0, val)})
                if len(bars) >= 12:
                    break
            if bars:
                out.append({"kind": "bar_chart", "title": title, "tab": tab, "bars": bars})
        elif kind == "progress":
            try:
                pct = max(0, min(100, int(float(row.get("pct")))))
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "kind": "progress",
                    "title": title,
                    "tab": tab,
                    "label": str(row.get("label") or "").strip()[:60],
                    "pct": pct,
                    "tone": _tone(row.get("tone")),
                }
            )
        elif kind == "status_list":
            items = []
            for it in row.get("items") if isinstance(row.get("items"), list) else []:
                if not isinstance(it, dict):
                    continue
                lbl = str(it.get("label") or "").strip()[:60]
                if lbl:
                    items.append({"label": lbl, "tone": _tone(it.get("tone"))})
                if len(items) >= 8:
                    break
            if items:
                out.append({"kind": "status_list", "title": title, "tab": tab, "items": items})
        if len(out) >= _MAX_WIDGETS:
            break
    return out


async def design_job_dashboard(
    root: Path,
    profile: str,
    app: dict[str, Any],
    job: dict[str, Any],
    workflows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Ask the model to design this job's dashboard. Returns (spec, error)."""
    llm = _build_llm(root, profile)
    if llm is None:
        return None, "no model available"
    prompt = (
        "You are designing the operator dashboard for ONE specific job inside "
        "the user's Thomas workspace. Job context (real data, JSON):\n"
        f"{job_design_context(app, job, workflows)}\n\n"
        f"{_SCHEMA_HINT}"
    )
    try:
        result = await llm.chat([{"role": "user", "content": prompt}])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, f"model call failed: {exc}"
    spec = _extract_json(str((result or {}).get("text") or ""))
    if spec is None:
        return None, "model did not return valid dashboard JSON"
    validated = validate_dashboard_spec(spec, workflows)
    if not (validated["metrics"] or validated["widgets"] or validated["sections"] or validated["actions"]):
        return None, "model design was empty after validation"
    return validated, ""


def register_work_dashboard_routes(
    app: Any,
    *,
    guard: Any,
    work_store: Any,
    expected_errors: Any,
    ok: Any,
    deploy_automation: Any,
) -> None:
    """Register the generative-dashboard endpoints (called from work.py)."""
    from aiohttp import web

    from thomas.work import WorkConflictError, WorkNotFoundError

    root = Path(__file__).resolve().parents[3]

    def _resolve_profile(request_profile: str) -> str:
        if request_profile:
            return request_profile
        try:
            from thomas.server.routes.canvas_studio_routes import _resolve_default_profile

            return _resolve_default_profile(root)
        except (ImportError, OSError, ValueError, TypeError, AttributeError):
            return ""

    async def dashboard_design(request: web.Request) -> web.Response:
        guard(request)
        app_id = request.match_info["app_id"]
        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        body = body if isinstance(body, dict) else {}
        app_row = work_store.get_app(app_id)
        job = work_store.get_job(app_id, job_id)
        workflows = work_store.list_workflows(app_id, job_id)
        profile = _resolve_profile(str(body.get("profile") or "").strip())
        spec, error = await design_job_dashboard(root, profile, app_row, job, workflows)
        if spec is None:
            status = 503 if "no model" in error else 502
            return web.json_response({"ok": False, "error": error, "code": "dashboard_design_failed"}, status=status)
        dashboard = work_store.update_job_dashboard(app_id, job_id, spec)
        return ok(dashboard=dashboard, designed=True)

    async def dashboard_action_run(request: web.Request) -> web.Response:
        guard(request)
        app_id = request.match_info["app_id"]
        job_id = request.match_info["job_id"]
        action_id = request.match_info["action_id"]
        job = work_store.get_job(app_id, job_id)
        actions = (job.get("dashboard") or {}).get("actions") or []
        action = next((row for row in actions if isinstance(row, dict) and row.get("id") == action_id), None)
        if action is None:
            raise WorkNotFoundError("dashboard action not found")
        workflow = work_store.get_workflow(app_id, job_id, str(action.get("workflow_id") or ""))
        automation_id = str(workflow.get("automation_id") or "")
        if not automation_id:
            raise WorkConflictError("this button's workflow needs a linked automation before it can run")
        automation, mission = await deploy_automation(app_id, job_id, automation_id, workflow=workflow)
        return ok(status=202, action=action, workflow=workflow, automation=automation, mission=mission)

    async def ui_redesign(request: web.Request) -> web.Response:
        """Change only what the user pointed at — see ui_redesign_runtime."""
        guard(request)
        from thomas.server.routes.ui_redesign_runtime import redesign_from_selection

        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        body = body if isinstance(body, dict) else {}
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        app_id = str(context.get("app_id") or "").strip()
        job_id = str(context.get("job_id") or "").strip()
        job_context: dict[str, Any] | None = None
        if app_id and job_id:
            # A missing job is not fatal: layout edits still work everywhere,
            # and the spec channel reports itself unavailable instead.
            try:
                job_context = {
                    "job": work_store.get_job(app_id, job_id),
                    "workflows": work_store.list_workflows(app_id, job_id),
                }
            except _WORK_STORE_FAULTS as exc:
                # The store is injected, so its concrete error type is not
                # knowable here — but "this job is not there / not readable"
                # is exactly this set. Anything else is a bug and must
                # surface rather than be logged as a missing job.
                log.info("UI redesign: no job context for %s/%s: %s", app_id, job_id, exc)
                job_context = None
        profile = _resolve_profile(str(body.get("profile") or "").strip())
        plan, error = await redesign_from_selection(root, profile, body, job_context=job_context)
        if plan is None:
            status = 503 if "no model" in error else 400 if "nothing was selected" in error or "no instruction" in error else 502
            return web.json_response({"ok": False, "error": error, "code": "redesign_failed"}, status=status)
        spec = (plan.get("dashboard") or {}).get("dashboard")
        # Persist ONLY when the diff says something actually moved. Writing an
        # identical spec back would let "changed 0" render as a save.
        if spec and (plan.get("dashboard") or {}).get("changed"):
            saved = work_store.update_job_dashboard(app_id, job_id, spec)
            plan["dashboard"]["dashboard"] = saved
        # The brief for going deeper. The BROWSER opens the Code thread with it,
        # because it already holds the session — a self-directed HTTP call from
        # here would mean forwarding cookies to ourselves to reach a handler in
        # another module's closure.
        from thomas.server.routes.ui_redesign_runtime import code_thread_prompt

        instruction = str(plan.get("instruction") or "").strip()
        targets = list(plan.get("targets") or [])
        return ok(
            layout=plan.get("layout") or [],
            dashboard=plan.get("dashboard") or {"changed": 0, "applied": []},
            unsupported=plan.get("unsupported") or [],
            code_thread={
                "title": f"Redesign: {instruction}"[:70],
                "project_root": str(root),
                "prompt": code_thread_prompt(instruction, targets, str(body.get("workspace") or "chat")),
            } if instruction and targets else None,
        )

    app.router.add_post(
        "/api/work/apps/{app_id}/jobs/{job_id}/dashboard/design",
        expected_errors(dashboard_design),
    )
    app.router.add_post("/api/ui/redesign", expected_errors(ui_redesign))
    app.router.add_post(
        "/api/work/apps/{app_id}/jobs/{job_id}/dashboard/actions/{action_id}/run",
        expected_errors(dashboard_action_run),
    )
