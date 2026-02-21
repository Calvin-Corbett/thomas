# Thomas Competitor Metric Framework

Use these metrics across all competitors so Thomas comparisons stay consistent.

| Metric ID | Unit | What it measures |
| --- | --- | --- |
| `surface.interface_coverage` | `score_0_5` | Breadth of usable surfaces (CLI, IDE, web, API, desktop). |
| `surface.tooling_depth` | `score_0_5` | Built-in tool depth for code, shell, browser, data, and workflows. |
| `ux.live_streaming` | `score_0_5` | Ability to stream tool events and model responses at the same time. |
| `ux.settings_depth` | `score_0_5` | Quality and granularity of settings, policy, and runtime controls. |
| `autonomy.supervision_modes` | `score_0_5` | Support for plan, approve, and autonomous execution modes. |
| `autonomy.parallelism` | `score_0_5` | Parallel agent/task execution capability and scheduling quality. |
| `integration.mcp_support` | `score_0_5` | MCP client/server support and ecosystem depth. |
| `integration.git_pr_workflows` | `score_0_5` | Native support for git/PR coding workflows. |
| `platform.self_hostability` | `score_0_5` | Ability to run privately or self-host with enterprise controls. |
| `security.governance_controls` | `score_0_5` | Approvals, policy enforcement, RBAC, auditability. |
| `reliability.task_success_rate` | `percent` | Success rate on fixed benchmark corpus. |
| `performance.p95_task_latency_seconds` | `seconds` | P95 end-to-end latency on standardized tasks. |
| `cost.usd_per_successful_task` | `usd` | Cost normalized by successful benchmark tasks. |
| `quality.test_pass_delta` | `percent` | Delta vs baseline competitor median pass rate. |
| `safety.risky_action_block_rate` | `percent` | Rate of unsafe action blocking or safe gating. |
| `observability.trace_replay` | `score_0_5` | Trace quality and replay/debug support. |

Default policy:

- Use measured values from benchmark artifacts when available.
- If only public documentation exists, mark values as provisional and include confidence tags.
