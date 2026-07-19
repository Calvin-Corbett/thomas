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
from pathlib import Path
from typing import Any

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
  "metrics": [{"label": "...", "value": "...", "hint": "why this number matters", "tone": "good|warn|bad|neutral"}],
  "widgets": [
    {"kind": "bar_chart", "title": "...", "bars": [{"label": "Mon", "value": 12}, {"label": "Tue", "value": 8}]},
    {"kind": "progress", "title": "...", "label": "Compliant devices", "pct": 72, "tone": "good|warn|bad"},
    {"kind": "status_list", "title": "...", "items": [{"label": "Broker verified", "tone": "good"}, {"label": "Driver conflict", "tone": "bad"}]}
  ],
  "sections": [{"title": "...", "text": "2-4 sentences of standing guidance for this job"}],
  "actions": [{"workflow_id": "<id from the workflow list>", "label": "verb-first button label", "description": "what pressing it does"}],
  "inboxes": [{"label": "...", "source": "<connector id or 'activity'>", "description": "what lands here"}]
}
Rules: every action's workflow_id MUST come from the provided workflow list —
invent nothing. Design 1-3 WIDGETS that fit THIS job's real work: a dispatcher
might get a weekly-loads bar_chart and a booking-progress meter; an MDM admin a
compliance progress meter and a device-status_list; a coach a win/loss
bar_chart. Use representative example numbers when live data isn't wired yet.
Metrics without live data use value "—". Every job should look visibly
different — vary which widget kinds you choose to match the domain."""


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
    return {
        "headline": str(spec.get("headline") or "").strip()[:200],
        "metrics": _clean_rows(spec.get("metrics"), ("label", "value", "hint", "tone"), _MAX_METRICS),
        "widgets": _clean_widgets(spec.get("widgets")),
        "sections": _clean_rows(spec.get("sections"), ("title", "text"), _MAX_SECTIONS),
        "actions": actions,
        "inboxes": _clean_rows(spec.get("inboxes"), ("label", "source", "description"), _MAX_INBOXES),
    }


_MAX_WIDGETS = 4
_TONES = {"good", "warn", "bad", "neutral"}


def _tone(value: Any) -> str:
    t = str(value or "neutral").strip().lower()
    return t if t in _TONES else "neutral"


def _clean_widgets(rows: Any) -> list[dict[str, Any]]:
    """Bound AI-designed visual widgets to safe, renderable shapes."""
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        title = str(row.get("title") or "").strip()[:80]
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
                out.append({"kind": "bar_chart", "title": title, "bars": bars})
        elif kind == "progress":
            try:
                pct = max(0, min(100, int(float(row.get("pct")))))
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "kind": "progress",
                    "title": title,
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
                out.append({"kind": "status_list", "title": title, "items": items})
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

    app.router.add_post(
        "/api/work/apps/{app_id}/jobs/{job_id}/dashboard/design",
        expected_errors(dashboard_design),
    )
    app.router.add_post(
        "/api/work/apps/{app_id}/jobs/{job_id}/dashboard/actions/{action_id}/run",
        expected_errors(dashboard_action_run),
    )
