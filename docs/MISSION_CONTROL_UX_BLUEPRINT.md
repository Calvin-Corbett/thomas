# Mission Control UX Blueprint

## Goal
Make Mission Control understandable for non-technical users in under 10 seconds:

1. What is running now?
2. What is blocked or failing?
3. What should I do next?
4. How did quality/spend change over time?

## Reference Patterns (2026-02-20)
- Airflow UI: grid/graph views, per-run drilldown, retry/debug from task cells.
- Prefect UI: run filters, state-centric dashboards, run details with logs and task runs.
- Temporal Web UI: workflow list + status filters, history timeline, pending activities, call stack.
- LangSmith: trace/run/thread model, dashboards for cost/latency/errors, alerts and automations.
- AgentOps: session drilldown, waterfall timeline, tool-call + cost visibility, replay-oriented debugging.
- Reddit practitioner threads: repeated emphasis on traces-first debugging, structured logs, replay, alerts, and human review queues.

### Source Links
- Airflow UI docs: https://airflow.apache.org/docs/apache-airflow/stable/ui.html
- Prefect dashboard monitoring: https://docs.prefect.io/v3/how-to-guides/workflows/monitor-workflows-in-the-dashboard
- Temporal Web UI docs: https://deepwiki.com/temporalio/ui/1.1-getting-started
- Temporal webinar page (video + walkthrough): https://temporal.io/webinars/temporal-ui-showcase
- LangSmith observability + performance monitoring: https://docs.smith.langchain.com/observability/how_to_guides/monitor_performance
- AgentOps trace concepts: https://docs.agentops.ai/v2/concepts/traces
- OpenTelemetry tracing model: https://opentelemetry.io/docs/concepts/signals/traces/
- Reddit (agent observability discussion): https://www.reddit.com/r/ClaudeAI/comments/1m10w1x/help_me_decide_how_to_build_observability_and/

## UX Requirements
- Operations-first layout: live mission state above benchmark/evaluation.
- Explicit status surfaces: active, blocked, failed, awaiting approval.
- Drilldown parity: every summary item must deep-link to details/activity.
- Benchmark clarity: pass/fail shown separately from weighted score.
- User control: benchmark suite and model profile must be selectable in UI.

## Implemented In Current Patch
- Operations-first layout:
  - Benchmark section moved below live mission workspace.
- Mission clarity:
  - Added `Now Working` and `Needs Attention` strips.
  - Added clickable rows that select the associated agent.
- Mission operations controls:
  - Added status/room/query filters.
  - Added saved view presets (save/delete local presets).
- Alerting:
  - Added `Alert Center` with high/medium/ok severities.
  - Added blocked/failed/awaiting-approval/stale-active detectors.
- Replay:
  - Added embedded `Replay Timeline` panel with manual refresh.
  - Added `Tools Only` filter for replay lines.
- Benchmark controls:
  - Added suite selector, model profile selector, mode selector, token economy selector.
  - Added task list preview with success criteria/time budgets.
- Benchmark semantics:
  - Added pass/fail/partial badges and `x/y tests passed`.
  - Kept weighted score as secondary trend metric.
- Backend support:
  - Added benchmark task-pack discovery API.
  - Added richer run payload (task pack metadata, run options, top metrics).

## Next UX Milestones
1. Time-range controls (last 15m/1h/24h) for events, alerts, and focus strips
2. Run topology view (graph/gantt) for multi-agent plans, inspired by Airflow/Temporal workflows
3. Human approval queue panel with reason codes, SLA timers, and one-click approve/reject
4. Notification routing (desktop/webhook/email) for high-severity mission alerts
5. Replay diff mode (before/after state + tool-call waterfall per run)
