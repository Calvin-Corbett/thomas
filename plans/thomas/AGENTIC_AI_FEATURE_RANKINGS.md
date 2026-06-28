# Agentic AI Feature Rankings

> Last run: 2026-06-27 04:15 UTC by Codex visible Thomas Agentic AI Repo Ranker.
> Scope: markdown ranking maintenance only. No Thomas code edits or pushes; commit only this rankings file when changed.

## Top Ranked Recommendations

### 1. OpenAI Agents SDK for Python
- Score: 94/100
- Repo URL: https://github.com/openai/openai-agents-python
- Feature/ability: Multi-agent workflows with handoffs, guardrails, sessions, human-in-the-loop support, and tracing.
- Why Thomas should adopt it: Direct reference for visible orchestration evidence and explainable handoffs.
- Likely Thomas integration surface: Delegation event stream, chat delegation runner/session modules, run inspector UI, and tool-call audit logs.
- Risk/effort: Medium; borrow trace/event semantics before runtime replacement.
- Next implementation task shape: Design a Thomas run-event schema and instrument one delegation path.
- Source entry reference: `2026-06-26 - OpenAI Agents SDK for Python`.

### 2. LangGraph Durable Agent Graphs
- Score: 92/100
- Repo URL: https://github.com/langchain-ai/langgraph
- Feature/ability: Durable graph-based agent execution with checkpointing, resumable runs, and human-in-the-loop state inspection.
- Why Thomas should adopt it: Thomas needs inspectable long-running worker state under dirty-repo coordination pressure.
- Likely Thomas integration surface: `thomas/agent/loop_core.py`, `thomas/forge/anvil/*dispatch*`, delegation session state, and orchestration dashboard.
- Risk/effort: Medium-high; graph ideas fit, direct framework transplant is risky.
- Next implementation task shape: Prototype a persisted run-state graph for one worker lifecycle.
- Source entry reference: `2026-06-26 - LangGraph durable agent graphs`.

### 3. SWE-bench Repository Issue Benchmark
- Score: 91/100
- Repo URL: https://github.com/swe-bench/SWE-bench
- Feature/ability: Benchmark and harness for evaluating agents on real GitHub issue patches.
- Why Thomas should adopt it: Gives Thomas an external target for proving repo workers fix real software tasks.
- Likely Thomas integration surface: Agent eval suite, coding-worker regression tests, issue-to-patch scoring, and CI gates.
- Risk/effort: Medium-high; valuable but environment-heavy.
- Next implementation task shape: Add a small SWE-bench-inspired local fixture before full benchmark integration.
- Source entry reference: `2026-06-26 - SWE-bench repository issue benchmark`.

### 4. LiteLLM Spend Management Gateway
- Score: 91/100
- Repo URL: https://github.com/BerriAI/litellm
- Feature/ability: OpenAI-compatible LLM gateway with virtual keys, provider routing, retries/fallbacks, guardrails, multi-tenant cost tracking, and spend management.
- Why Thomas should adopt it: Thomas needs a central model gateway that can enforce budgets per worker, task, user, or repository area before autonomous loops create runaway cost. LiteLLM is mature enough to serve as a near-term reference for routing, virtual keys, and spend caps.
- Likely Thomas integration surface: Model gateway adapter, worker API-key policy, spend ledger, per-task budget gates, provider fallback routing, rate limits, and portal admin controls.
- Risk/effort: Medium-high effort and medium risk; direct value is high, but Thomas should avoid binding its internal worker model too tightly to one gateway's configuration and storage model.
- Next implementation task shape: Build a gateway comparison spike that routes one Thomas worker model call through a LiteLLM-compatible endpoint with request metadata, budget labels, and a hard per-task spend cap.
- Source entry reference: `2026-06-26 - LiteLLM spend management gateway`.

### 5. Microsoft Agent Governance Toolkit
- Score: 90/100
- Repo URL: https://github.com/microsoft/agent-governance-toolkit
- Feature/ability: Policy enforcement, zero-trust identity, execution sandboxing, and reliability controls for autonomous agents.
- Why Thomas should adopt it: Thomas needs explicit governance for identity, approvals, tool access, sandboxing, and auditability before native orchestration grows.
- Likely Thomas integration surface: Tool permission broker, agent identity model, sandbox policy, run audit logs, and publish/preflight guardrails.
- Risk/effort: High; governance touches trusted execution boundaries and must not become decorative policy.
- Next implementation task shape: Map OWASP-style agent risks to Thomas tool execution and delegation guardrails.
- Source entry reference: `2026-06-26 - Microsoft Agent Governance Toolkit`.

### 6. OpenHands Software Agent SDK
- Score: 90/100
- Repo URL: https://github.com/OpenHands/software-agent-sdk
- Feature/ability: SDK for code-working agents with isolated workspaces, REST APIs, and multi-agent refactor/rewrite tasks.
- Why Thomas should adopt it: Workspace separation and agent-server boundaries fit safer native repo execution.
- Likely Thomas integration surface: Native repo worker orchestration, workspace provisioning, live repo tracking, and isolated execution lanes.
- Risk/effort: High; touches process boundaries, file access, and verification policy.
- Next implementation task shape: Compare Thomas worker launch against OpenHands-style isolated workspace lifecycle.
- Source entry reference: `2026-06-26 - OpenHands software agent SDK`.

### 7. GenAI OpenTelemetry Semantic Conventions
- Score: 90/100
- Repo URL: https://github.com/open-telemetry/semantic-conventions-genai
- Feature/ability: Standard OpenTelemetry GenAI span and attribute conventions for model calls, prompts, tool execution, and agent operations.
- Why Thomas should adopt it: Thomas should not invent isolated telemetry names while the ecosystem is converging on portable OpenTelemetry semantics. Adopting the convention early would make worker traces easier to query, export, compare, and share with hosted or local observability stacks.
- Likely Thomas integration surface: Worker span schema, model/tool event taxonomy, prompt/run attributes, OpenTelemetry exporter compatibility, portal trace filters, and future cost or safety attribution queries.
- Risk/effort: Medium effort and low product risk; the main risk is spec churn, so Thomas should wrap the convention behind an internal schema mapper instead of scattering raw attribute names everywhere.
- Next implementation task shape: Draft a Thomas telemetry schema adapter that maps one coding-worker lifecycle into GenAI semantic-convention attributes, then add a fixture trace and a compatibility note for current OpenTelemetry exporters.
- Source entry reference: `2026-06-26 - GenAI OpenTelemetry semantic conventions`.

### 8. BenchFlow Universal Agent Evaluation Environments
- Score: 90/100
- Repo URL: https://github.com/benchflow-ai/BenchFlow
- Feature/ability: Universal environment framework for running agents against task environments with single-agent, multi-agent, multi-round, loop strategies, scored trajectories, and token/cost output.
- Why Thomas should adopt it: Thomas needs a durable way to replay worker strategies, compare agents/models, and plot capability against cost instead of judging runs only by final success. BenchFlow closely matches Thomas worker evaluation and reviewer patterns.
- Likely Thomas integration surface: Worker benchmark harness, route replay datasets, loop-strategy evaluation, scored trajectory export, sandbox integration, model routing experiments, and cost/capability dashboards.
- Risk/effort: Medium-high effort and low-medium risk; integration would touch evaluation architecture rather than product runtime first, but Thomas must keep benchmark tasks representative of real workboard flows.
- Next implementation task shape: Build a small Thomas worker-eval adapter that exports one completed task as a scored trajectory with tool calls, costs, loop decisions, verification results, and final outcome.
- Source entry reference: `2026-06-26 - BenchFlow universal agent evaluation environments`.

### 9. Microsoft Eval-Recipes
- Score: 90/100
- Repo URL: https://github.com/microsoft/eval-recipes
- Feature/ability: Benchmarking harness for evaluating AI agents on real-world tasks in isolated Docker containers with deterministic and semantic scoring.
- Why Thomas should adopt it: Thomas workers need sandboxed, reproducible task evals that can compare implementations and catch regressions before deployment. Dockerized recipes with deterministic and semantic scoring map directly to worker quality gates.
- Likely Thomas integration surface: Dockerized eval tasks, task recipe format, deterministic/semantic scoring, auditing-agent comparison, regression-suite authoring, and promotion gates.
- Risk/effort: Medium-high effort and low-medium risk; strong architectural fit, but Thomas should start with a small local task recipe before introducing broad Docker orchestration.
- Next implementation task shape: Convert one completed Thomas workboard task into an eval recipe with setup, allowed tools, expected artifact, deterministic checks, semantic review, and cost output.
- Source entry reference: `2026-06-26 - Microsoft eval-recipes`.

### 10. Sigstore Cosign
- Score: 90/100
- Repo URL: https://github.com/sigstore/cosign
- Feature/ability: Artifact signing and verification tooling for container images, blobs, attestations, and SBOMs.
- Why Thomas should adopt it: Thomas skill bundles, marketplace artifacts, and generated deliverables need verifiable signatures before workers trust or install them. Cosign is a mature foundation for signed skill publishing.
- Likely Thomas integration surface: Signed skill publishing, artifact verification gate, marketplace trust label, release provenance, CI signing workflow, and install-time signature checks.
- Risk/effort: Medium effort and low-medium risk; mature tooling reduces risk, but Thomas needs a clear policy for unsigned local development artifacts versus marketplace artifacts.
- Next implementation task shape: Prototype a Thomas skill artifact signing policy that signs one packaged skill, records its digest, verifies it before install, and emits a trust label in marketplace metadata.
- Source entry reference: `2026-06-26 - Sigstore cosign`.

### 11. Oktsec Local Agent Action Security Layer
- Score: 90/100
- Repo URL: https://github.com/oktsec/oktsec
- Feature/ability: Local runtime security layer between AI agents and tool surfaces, applying policy before MCP calls, shell/file/browser actions, agent-to-agent messages, and outbound requests execute.
- Why Thomas should adopt it: Thomas needs a central mediation point for high-risk actions across tools and worker lanes; Oktsec is a current reference for a local binary that signs, inspects, logs, and blocks actions before they become real changes.
- Likely Thomas integration surface: Tool-call proxy, shell/file/browser action middleware, inter-agent message gate, and audit log collector.
- Risk/effort: Medium-high; the fit is strong, but Thomas must preserve its existing claim and commit guardrails instead of adding an opaque duplicate gate.
- Next implementation task shape: Prototype a policy-before-action wrapper for one shell/file action and one MCP call with signed audit output.
- Source entry reference: `2026-06-26 - Oktsec local agent action security layer`.

### 12. Agent Replay Local Trace Time-Travel Debugger
- Score: 90/100
- Repo URL: https://github.com/clay-good/agent-replay
- Feature/ability: Local SQLite-backed CLI for replaying agent execution traces, diffing behavioral changes, forking runs, evaluating traces, applying guard policies, and exporting golden regression datasets.
- Why Thomas should adopt it: Thomas workers need a way to explain failures and turn known-good or known-bad runs into repeatable tests; trace diff/fork/golden export maps directly to worker regression and postmortem loops.
- Likely Thomas integration surface: Worker trace store, replay CLI, run diff viewer, guardrail policy checks, and export of Thomas task traces into regression fixtures.
- Risk/effort: Medium; small repo, but the local-first workflow is concrete enough to prototype against Thomas run traces.
- Next implementation task shape: Define a minimal Thomas trace schema and replay one captured worker action sequence into a golden regression fixture.
- Source entry reference: `2026-06-26 - Agent Replay local trace time-travel debugger`.

### 13. AIO Sandbox Unified Agent Workspace
- Score: 89/100
- Repo URL: https://github.com/agent-infra/sandbox
- Feature/ability: Docker sandbox combining browser, shell, file operations, MCP services, VNC, VSCode Server, and agent APIs.
- Why Thomas should adopt it: Thomas needs safer multi-tool execution spaces that do not contaminate the live checkout.
- Likely Thomas integration surface: Worker workspace provisioning, browser runtime, MCP tool execution, and isolated repo lanes.
- Risk/effort: High; security-sensitive isolation work.
- Next implementation task shape: Write a sandbox threat model against Thomas worker isolation needs.
- Source entry reference: `2026-06-26 - AIO Sandbox unified agent workspace`.

### 14. Pipelock AI Agent Firewall
- Score: 89/100
- Repo URL: https://github.com/luckyPipewrench/pipelock
- Feature/ability: Local AI egress proxy and MCP security control for HTTP, WebSocket, MCP, and A2A traffic with signed action receipts.
- Why Thomas should adopt it: Thomas agents will browse untrusted content and call powerful tools; outside-the-agent mediation is the right control point for auditable blocking.
- Likely Thomas integration surface: Tool egress proxy, MCP gateway layer, browser/network mediation, signed run receipts, and security preflight checks.
- Risk/effort: High; gateway policy must fail closed without breaking normal worker ergonomics.
- Next implementation task shape: Threat-model one Thomas browser/tool call path through an egress proxy and signed receipt flow.
- Source entry reference: `2026-06-26 - Pipelock AI agent firewall`.

### 15. GitTaskBench Repository-Aware Code-Agent Benchmark
- Score: 89/100
- Repo URL: https://github.com/QuantaAlpha/GitTaskBench
- Feature/ability: Benchmark for code agents on real-world repository tasks requiring repo setup, dependencies, execution, and deployment-style workflows.
- Why Thomas should adopt it: Thomas needs to measure end-to-end repo-worker success, including environment setup failures, not just synthetic patching.
- Likely Thomas integration surface: Repo-agent benchmark suite, worker regression testing, environment setup evaluation, and cost/success reporting.
- Risk/effort: Medium-high; benchmark setup and reproducibility need care.
- Next implementation task shape: Compare GitTaskBench task format against Thomas worker regression suite needs.
- Source entry reference: `2026-06-26 - GitTaskBench repository-aware code-agent benchmark`.

### 16. CyberArk Agent Guard Secrets And MCP Proxy
- Score: 89/100
- Repo URL: https://github.com/cyberark/agent-guard
- Feature/ability: Secure secrets retrieval for AI agents plus traceable MCP communications through an MCP proxy.
- Why Thomas should adopt it: Thomas needs secret access and MCP traffic controls that sit outside agent self-reporting before tool authority grows.
- Likely Thomas integration surface: Secrets provider integration, MCP proxy, tool-call audit logs, agent identity policy, and security preflight checks.
- Risk/effort: High; secret handling and proxy enforcement must fail closed without breaking routine worker flows.
- Next implementation task shape: Threat-model one Thomas MCP tool path and sketch a proxy-backed secret retrieval flow with audit evidence.
- Source entry reference: `2026-06-26 - CyberArk Agent Guard secrets and MCP proxy`.

### 17. Parallel Code Worktree Agent UI
- Score: 89/100
- Repo URL: https://github.com/johannesjo/parallel-code
- Feature/ability: Desktop UI for running Claude Code, Codex, Gemini, and other coding agents side-by-side in isolated git worktrees with diff review.
- Why Thomas should adopt it: It directly matches Thomas's visible-worker direction: parallel worker UX, worktree isolation, diff review, and merge ergonomics.
- Likely Thomas integration surface: Thomas portal worker dashboard, worktree spawn/import, diff-review pane, CI watcher, and task progress timeline.
- Risk/effort: High; useful UX reference, but Thomas must preserve its own workboard, claim, and safety semantics.
- Next implementation task shape: Compare Parallel Code's worker/worktree UI flow to Thomas native orchestration and portal status needs.
- Source entry reference: `2026-06-26 - Parallel Code worktree agent UI`.

### 18. Mem0 Universal Agent Memory Layer
- Score: 89/100
- Repo URL: https://github.com/mem0ai/mem0
- Feature/ability: Universal memory layer for AI agents with user/session/agent memories, entity linking, hybrid retrieval, temporal reasoning, and open evaluation assets.
- Why Thomas should adopt it: Thomas needs durable memory across worker threads without stuffing giant transcripts into prompts, and Mem0 is a strong reference for extraction, retrieval, and evals.
- Likely Thomas integration surface: Thomas memory backend, worker context bootstrap, user/project preference memory, memory evals, and agent-generated fact capture.
- Risk/effort: Medium-high; memory writes need provenance, conflict handling, and privacy boundaries before becoming trusted context.
- Next implementation task shape: Prototype a Thomas memory fact schema with source evidence, scope, recency, and retrieval tests.
- Source entry reference: `2026-06-26 - Mem0 universal agent memory layer`.

### 19. AG-UI Agent-User Interaction Protocol
- Score: 89/100
- Repo URL: https://github.com/ag-ui-protocol/ag-ui
- Feature/ability: Event-based protocol for connecting agent backends to user-facing apps with streaming, shared state, generative UI, frontend tools, and human-in-the-loop collaboration.
- Why Thomas should adopt it: Thomas is becoming a visible worker portal, and AG-UI gives a concrete protocol for state, approvals, and UI actions without bespoke one-off frontend plumbing.
- Likely Thomas integration surface: Thomas portal event stream, worker UI bridge, approval widgets, AG-UI compatible run state, and frontend tool invocation.
- Risk/effort: Medium-high; protocol adoption must align with Thomas workboard state and local security constraints.
- Next implementation task shape: Map one Thomas worker run and approval action into AG-UI event/state primitives.
- Source entry reference: `2026-06-26 - AG-UI agent-user interaction protocol`.

### 20. Adrian Runtime Agent Security Monitor
- Score: 89/100
- Repo URL: https://github.com/secureagentics/adrian
- Feature/ability: Runtime security monitoring and control for AI agents that analyzes tool calls, actions, outputs, and reasoning traces to detect malicious, misaligned, or out-of-remit behavior.
- Why Thomas should adopt it: Thomas workers are gaining more tool authority, so in-flight policy checks and runtime intervention before unsafe actions execute are directly relevant.
- Likely Thomas integration surface: Tool-call runtime guard, worker remit policy, audit/block modes, trace ingestion, and portal security alerts.
- Risk/effort: High; runtime blocking must be deterministic, explainable, and compatible with Thomas's existing commit/workboard gates.
- Next implementation task shape: Define one Thomas runtime-block decision record for a high-risk shell or MCP action.
- Source entry reference: `2026-06-26 - Adrian runtime agent security monitor`.

### 21. Portkey AI Gateway Guardrails
- Score: 89/100
- Repo URL: https://github.com/Portkey-AI/gateway
- Feature/ability: AI gateway with model routing, integrated guardrails, observability, retries, fallbacks, and policy controls across many LLM providers.
- Why Thomas should adopt it: Thomas worker execution needs a policy enforcement point that can route, block, retry, or downgrade requests based on cost, risk, and provider health instead of leaving every agent loop to decide locally.
- Likely Thomas integration surface: Gateway policy layer, guardrail hooks, model router, request metadata propagation, budget/rate-limit policy, provider health checks, and MCP/agent gateway comparison.
- Risk/effort: Medium effort and medium risk; guardrail and routing patterns are strong, but adoption should start as a reference design unless Thomas chooses to standardize on an external gateway.
- Next implementation task shape: Prototype a Thomas gateway policy document covering max spend, provider fallback, model downgrade, and blocked prompt/tool contexts, then compare how Portkey expresses the same policies.
- Source entry reference: `2026-06-26 - Portkey AI gateway guardrails`.

### 22. RouteLLM Router Serving and Evaluation
- Score: 89/100
- Repo URL: https://github.com/lm-sys/RouteLLM
- Feature/ability: Framework for serving and evaluating LLM routers that route between stronger and cheaper models using preference data.
- Why Thomas should adopt it: Thomas needs defensible model-routing thresholds so worker steps can trade cost against quality without relying on hand-written model-choice rules. RouteLLM is directly relevant to budget-aware gateway policy and route evaluation.
- Likely Thomas integration surface: Router benchmark harness, threshold calibration, model-choice audit logs, budget-aware gateway policy, per-task quality/cost evaluation, and route replay tests.
- Risk/effort: Medium effort and medium risk; routing quality depends on Thomas-specific task data, so this should start as an offline evaluation path before controlling live autonomous workers.
- Next implementation task shape: Build an offline route-evaluation fixture from Thomas worker transcripts, compare cheap-vs-strong model decisions, and record threshold, expected savings, and quality regression risk.
- Source entry reference: `2026-06-26 - RouteLLM router serving and evaluation`.

### 23. SkillsBench Skill-Use Benchmark
- Score: 89/100
- Repo URL: https://github.com/benchflow-ai/SkillsBench
- Feature/ability: Benchmark for evaluating how well agent skills work and how effectively agents discover and use them.
- Why Thomas should adopt it: Thomas has many agent skills and tools; it needs evidence that skills are discoverable and usable, not just present in a registry.
- Likely Thomas integration surface: Skill registry evals, task.md benchmark conversion, agent skill-selection telemetry, regression tasks for new skills, per-skill capability scoring, and skill discoverability reports.
- Risk/effort: Medium effort and low-medium risk; strong fit, but Thomas needs to define expected-skill-use labels without overfitting agents to benchmark phrasing.
- Next implementation task shape: Create a first Thomas skill-discovery regression set with tasks that require selecting the right local skill, then score whether the agent found, read, and applied it correctly.
- Source entry reference: `2026-06-26 - SkillsBench skill-use benchmark`.

### 24. Scorecard MCP Eval
- Score: 89/100
- Repo URL: https://github.com/scorecard-ai/mcp-eval
- Feature/ability: Evaluation framework for MCP servers and agents that can score tool-use behavior and MCP server quality.
- Why Thomas should adopt it: Thomas needs MCP server scorecards before trusting external tools in autonomous workflows, especially where tool descriptions and schemas drift. This is directly aligned with MCP onboarding and regression gates.
- Likely Thomas integration surface: MCP server regression suite, tool-quality scorecards, server onboarding gate, workboard problem generation from failed evals, portal score display, and trusted-tool policy.
- Risk/effort: Medium effort and low-medium risk; strong fit, but Thomas should keep the scoring adapter local and deterministic before relying on external platform assumptions.
- Next implementation task shape: Build a small Thomas MCP eval fixture that scores one local MCP server on tool discovery, schema accuracy, call success, error behavior, and result usefulness.
- Source entry reference: `2026-06-26 - Scorecard MCP Eval`.

### 25. Vercel Agent-Eval
- Score: 89/100
- Repo URL: https://github.com/vercel-labs/agent-eval
- Feature/ability: Agent eval framework that asserts on final artifacts and agent behavior such as shell commands, files read, tool calls, and transcript-derived results.
- Why Thomas should adopt it: Thomas must verify not only whether a worker produced a file, but whether it used acceptable methods and stayed within expected tool/command behavior.
- Likely Thomas integration surface: Worker behavior assertions, transcript parser, sandboxed eval fixtures, command/file access checks, tool-call policy checks, and acceptance criteria for coding tasks.
- Risk/effort: Medium effort and low-medium risk; unusually close fit for coding-agent behavior regression, but transcript parsing should be normalized to Thomas's own trace format.
- Next implementation task shape: Build a Thomas behavior assertion prototype for one worker transcript: files touched, commands run, forbidden paths avoided, verification present, and final artifact matches expected shape.
- Source entry reference: `2026-06-26 - Vercel agent-eval`.

### 26. Agent Skills Open Standard
- Score: 89/100
- Repo URL: https://github.com/agentskills/agentskills
- Feature/ability: Open standard and reference tooling for packaging, discovering, and running agent skills across assistants and IDEs.
- Why Thomas should adopt it: Thomas should avoid a one-off skill format if an ecosystem standard can provide import compatibility, metadata conventions, and portable installation. This is the strongest candidate for a provider-neutral skill compatibility layer.
- Likely Thomas integration surface: Skill package compatibility layer, marketplace metadata schema, import validation, trust-label propagation, skill runtime adapters, and skill installer UX.
- Risk/effort: Medium-high effort and medium risk; standard maturity needs verification, but aligning early with an open shape can reduce future migration cost.
- Next implementation task shape: Compare Agent Skills standard fields against Thomas skill needs and produce a proposed Thomas compatibility manifest with required, optional, and rejected fields.
- Source entry reference: `2026-06-26 - Agent Skills open standard`.

### 27. In-Toto Attestations
- Score: 89/100
- Repo URL: https://github.com/in-toto/attestation
- Feature/ability: Attestation framework and predicate specifications for supply-chain metadata.
- Why Thomas should adopt it: Thomas needs a standard way to represent provenance, test results, scans, and review decisions for skills and worker-generated artifacts.
- Likely Thomas integration surface: Skill provenance predicates, eval-result attestations, security scan metadata, review attestations, signed work artifact bundles, and marketplace trust records.
- Risk/effort: Medium effort and low-medium risk; standards-oriented model is valuable, but Thomas should start with a small predicate set rather than over-model every artifact.
- Next implementation task shape: Define a Thomas attestation predicate for skill validation: source repo, commit, tests run, scan result, reviewer, permissions, and signature digest.
- Source entry reference: `2026-06-26 - in-toto attestations`.

### 28. OpenFGA Fine-Grained Authorization
- Score: 89/100
- Repo URL: https://github.com/openfga/openfga
- Feature/ability: Relationship-based authorization engine for fine-grained access decisions.
- Why Thomas should adopt it: Thomas needs explicit authorization for which agents can read, write, call tools, install skills, or act for a user; OpenFGA is a mature reference for explainable relationship-based decisions.
- Likely Thomas integration surface: Agent/tool authorization graph, workboard permission model, skill install policy, portal access control, and explainable authorization decisions.
- Risk/effort: Medium-high; valuable policy model, but a direct service dependency would need careful migration and test fixtures.
- Next implementation task shape: Model one Thomas permission flow as tuples and checks, then compare OpenFGA-style decisions with current workboard and tool-scope rules.
- Source entry reference: `2026-06-26 - OpenFGA fine-grained authorization`.

### 29. Enforra Local-First Tool-Call Policy Enforcement
- Score: 89/100
- Repo URL: https://github.com/enforra/enforra
- Feature/ability: Runtime policy checks before agent tool callbacks execute, with allow, block, require-approval, and log-only decisions plus local JSONL audit output.
- Why Thomas should adopt it: Thomas needs deterministic enforcement in front of high-impact worker actions, not only prompt instructions; Enforra is a compact reference for putting policy at the tool execution boundary.
- Likely Thomas integration surface: Tool execution wrappers in `thomas/agent/`, workboard claim/commit gates, approval UX, and run audit logging.
- Risk/effort: Medium; small and direct, but Thomas must adapt the pattern to existing guardrails instead of layering on duplicate policy state.
- Next implementation task shape: Build a local policy-wrapper spike around one high-impact tool call and emit allow/block/approval audit records.
- Source entry reference: `2026-06-26 - Enforra local-first tool-call policy enforcement`.

### 30. Agent Audit Static Scanner For LLM Agents
- Score: 89/100
- Repo URL: https://github.com/HeadyZhang/agent-audit
- Feature/ability: Static security scanner for LLM agent code, prompt injection paths, MCP configuration, taint analysis, and rules mapped to OWASP Agentic Top 10.
- Why Thomas should adopt it: Thomas has a growing tool/plugin/agent surface where security review cannot stay manual; this could inform preflight checks before marketplace publishing, worker enablement, or release.
- Likely Thomas integration surface: Release preflight, plugin/skill marketplace scanner, MCP config audit, CI security checks, and workboard risk reports.
- Risk/effort: Medium; direct scanner value, but Thomas should start with a focused rule subset to avoid noisy gates.
- Next implementation task shape: Run a comparison spike over one Thomas skill or MCP config and map findings into existing preflight/report formats.
- Source entry reference: `2026-06-26 - Agent Audit static scanner for LLM agents`.

### 31. Engram Persistent Memory For Coding Agents
- Score: 89/100
- Repo URL: https://github.com/Gentleman-Programming/engram
- Feature/ability: Agent-agnostic persistent memory binary for AI coding agents using SQLite and FTS5, with MCP server, HTTP API, CLI, TUI, plugin docs, and team usage guidance.
- Why Thomas should adopt it: This is close to Thomas's developer-agent use case: local or cloud memory for coding workers with multiple access modes and inspectable local storage.
- Likely Thomas integration surface: Coding-worker memory, MCP memory server, local TUI inspection, team memory sharing, and plugin/extension memory adapters.
- Risk/effort: Medium; strong fit, but Thomas should preserve its own memory contracts and avoid coupling to an external binary too early.
- Next implementation task shape: Compare Engram's SQLite/FTS5 memory model with `thomas/memory/` and draft one MCP memory adapter spike.
- Source entry reference: `2026-06-26 - Engram persistent memory for coding agents`.

### 32. SWE-agent Issue-Solving Agent
- Score: 88/100
- Repo URL: https://github.com/SWE-agent/SWE-agent
- Feature/ability: Agent-computer interface for repo inspection, editing, and testing through constrained commands.
- Why Thomas should adopt it: Helps code workers preserve context, limit edits, and turn test feedback into next actions.
- Likely Thomas integration surface: CLI worker loop, repo-edit wrappers, test feedback summaries, and issue-to-task execution.
- Risk/effort: Medium; interface constraints can be adapted incrementally.
- Next implementation task shape: Define a constrained repo-worker command contract.
- Source entry reference: `2026-06-26 - SWE-agent issue-solving agent`.

### 33. Letta Advanced Agent Memory
- Score: 88/100
- Repo URL: https://github.com/letta-ai/letta
- Feature/ability: Explicit long-term agent memory with local/API operation and context management.
- Why Thomas should adopt it: Thomas needs durable worker context and user/repo lessons without prompt stuffing.
- Likely Thomas integration surface: `thomas/memory/`, worker run memory, preferences, and self-improvement context stores.
- Risk/effort: Medium-high; memory must distinguish verified facts from stale hints.
- Next implementation task shape: Define a Thomas memory record contract with trust levels.
- Source entry reference: `2026-06-26 - Letta advanced agent memory`.

### 34. Open Policy Agent for Agent Tool Policy
- Score: 88/100
- Repo URL: https://github.com/open-policy-agent/opa
- Feature/ability: General-purpose policy engine for context-aware authorization decisions.
- Why Thomas should adopt it: Thomas needs explicit policies for tool calls, filesystem writes, network access, public snapshots, and dirty-repo work.
- Likely Thomas integration surface: Tool execution middleware, publish/preflight gates, workboard claim authorization, and per-agent capability rules.
- Risk/effort: Medium-high; policy UX and audit reasons must be agent-specific.
- Next implementation task shape: Prototype one externalized policy check for a high-risk tool action.
- Source entry reference: `2026-06-26 - Open Policy Agent for agent tool policy`.

### 35. Agentgateway AI-Native Proxy
- Score: 88/100
- Repo URL: https://github.com/agentgateway/agentgateway
- Feature/ability: Open-source proxy for MCP and A2A traffic with security, observability, and governance for agent communication.
- Why Thomas should adopt it: Thomas needs a control plane between agents and tools rather than baking routing, policy, and telemetry into every worker.
- Likely Thomas integration surface: MCP/A2A gateway, delegation routing, tool access policy, and multi-agent observability.
- Risk/effort: High; a central gateway becomes critical infrastructure and must be simple to debug.
- Next implementation task shape: Compare Agentgateway's routing/policy model to Thomas delegation and tool execution boundaries.
- Source entry reference: `2026-06-26 - Agentgateway AI-native proxy`.

### 36. Rivet Sandbox-Agent Remote Coding-Agent Control
- Score: 88/100
- Repo URL: https://github.com/rivet-dev/sandbox-agent
- Feature/ability: HTTP server inside a sandbox that controls Claude Code, Codex, OpenCode, Cursor, Amp, or Pi while streaming events and handling permissions.
- Why Thomas should adopt it: Thomas needs isolated repo agents with visible progress, permissions, and session control.
- Likely Thomas integration surface: Sandboxed worker runner, event streaming, permission mediation, and remote agent session management.
- Risk/effort: High; sandbox/session control is a core trust boundary.
- Next implementation task shape: Compare sandbox-agent's event/permission model against Thomas delegated worker sessions.
- Source entry reference: `2026-06-26 - rivet sandbox-agent remote coding-agent control`.

### 37. Playwright MCP Official Browser Server
- Score: 88/100
- Repo URL: https://github.com/microsoft/playwright-mcp
- Feature/ability: Official MCP server for browser interaction through Playwright and structured accessibility snapshots.
- Why Thomas should adopt it: Thomas browser automation should prefer structured accessibility snapshots over screenshot-only control where possible.
- Likely Thomas integration surface: Browser automation backend, accessibility snapshot extraction, web QA worker, and MCP tool bridge.
- Risk/effort: Medium; official implementation, but integration must preserve permissions and evidence capture.
- Next implementation task shape: Compare Playwright MCP tools against Thomas browser tool contracts.
- Source entry reference: `2026-06-26 - Playwright MCP official browser server`.

### 38. Agent Policy Engine Hard Action Boundaries
- Score: 88/100
- Repo URL: https://github.com/kahalewai/agent-policy-engine
- Feature/ability: Policy enforcement runtime between agent reasoning and action execution for hard production boundaries.
- Why Thomas should adopt it: Thomas needs tool policy outside model prompts so approvals, blocked actions, and audit trails are enforceable.
- Likely Thomas integration surface: Tool execution middleware, command approval policy, sandbox egress control, and worker audit logs.
- Risk/effort: Medium-high; policy has to cover real actions without becoming prompt-only theater or blocking normal work.
- Next implementation task shape: Define a hard-action boundary list for Thomas shell, file, browser, MCP, and secret access.
- Source entry reference: `2026-06-26 - Agent Policy Engine hard action boundaries`.

### 39. Cognee Memory Engine
- Score: 88/100
- Repo URL: https://github.com/topoteretes/cognee
- Feature/ability: AI memory engine that builds structured knowledge graphs and retrieval layers from documents, conversations, and code-adjacent context.
- Why Thomas should adopt it: Thomas needs durable memory for decisions, evidence, and project facts across visible workers without relying on unbounded thread transcripts.
- Likely Thomas integration surface: Thomas memory backend, repo-research ingestion, workboard context retrieval, and evidence-linked run summaries.
- Risk/effort: Medium-high; memory quality depends on schema discipline, provenance, and conflict handling across workers.
- Next implementation task shape: Prototype a Thomas memory record shape that links facts to source evidence and retrieval scope.
- Source entry reference: `2026-06-26 - Cognee memory engine`.

### 40. Agent Orchestrator Feedback-Loop Supervisor
- Score: 88/100
- Repo URL: https://github.com/AgentWrapper/agent-orchestrator
- Feature/ability: Agent-agnostic orchestrator for parallel coding agents in isolated workspaces with CI failure, review comment, and merge-conflict feedback routing.
- Why Thomas should adopt it: Thomas needs feedback loops that route CI and review failures back to the responsible worker without losing ownership.
- Likely Thomas integration surface: Worker daemon, SCM/CI observer, feedback router, immutable run facts, and portal status stream.
- Risk/effort: High; close feature fit but must be reviewed for local security and repo-state assumptions.
- Next implementation task shape: Model one Thomas CI-failure feedback loop from observer event to responsible worker follow-up.
- Source entry reference: `2026-06-26 - Agent Orchestrator feedback-loop supervisor`.

### 41. Arcade MCP Authorized Tool Calling
- Score: 88/100
- Repo URL: https://github.com/ArcadeAI/arcade-mcp
- Feature/ability: Python MCP server framework with authorized tool calling, OAuth scopes, token refresh, secret injection, MCP spec coverage, and tool-call evals.
- Why Thomas should adopt it: Thomas needs tool authorization that keeps tokens out of prompts while permitting scoped, auditable external actions.
- Likely Thomas integration surface: MCP tool server framework, OAuth provider adapters, per-call scoped credentials, secret storage, and tool-call evaluation.
- Risk/effort: High; auth, token refresh, and secret injection must align with Thomas vault and tool guardrails.
- Next implementation task shape: Prototype one scoped OAuth-backed MCP tool call with explicit credential provenance and audit output.
- Source entry reference: `2026-06-26 - Arcade MCP authorized tool calling`.

### 42. Graphiti Temporal Knowledge Graph Memory
- Score: 88/100
- Repo URL: https://github.com/getzep/graphiti
- Feature/ability: Real-time temporal knowledge graph infrastructure for changing facts, relationships, and historical context in AI agents.
- Why Thomas should adopt it: Thomas must remember evolving project state, worker decisions, claims, releases, and user preferences without treating stale facts as current.
- Likely Thomas integration surface: Project knowledge graph, workboard memory, time-aware retrieval, provenance-linked facts, and conflict-aware memory lookup.
- Risk/effort: High; temporal graph memory needs clear update semantics, storage policy, and query guardrails.
- Next implementation task shape: Model Thomas claim and release history as temporal graph facts with current-versus-historical retrieval.
- Source entry reference: `2026-06-26 - Graphiti temporal knowledge graph memory`.

### 43. DBOS Durable OpenAI Agents
- Score: 88/100
- Repo URL: https://github.com/dbos-inc/dbos-openai-agents
- Feature/ability: Durable execution integration for the OpenAI Agents SDK, adding reliable multi-agent application execution.
- Why Thomas should adopt it: Thomas agent runs can be interrupted by process restarts, compaction, or transient failures; DBOS shows how to persist agent/tool steps as durable workflow state.
- Likely Thomas integration surface: OpenAI-agent runtime wrapper, durable task journal, tool-call step persistence, restart/resume mechanics, and Postgres-backed worker execution.
- Risk/effort: High; durable runtime choices affect storage, replay, idempotency, and failure semantics.
- Next implementation task shape: Map one Thomas worker run into durable steps with idempotency keys and resume points.
- Source entry reference: `2026-06-26 - DBOS Durable OpenAI Agents`.

### 44. A2A Agent-To-Agent Protocol
- Score: 88/100
- Repo URL: https://github.com/a2aproject/A2A
- Feature/ability: Open Agent2Agent protocol for communication and interoperability between opaque agentic applications.
- Why Thomas should adopt it: Thomas will coordinate heterogeneous workers, tools, and potentially external agents, so A2A can inform capability discovery, task submission, status reporting, and contracts.
- Likely Thomas integration surface: Worker-to-worker protocol adapter, external-agent bridge, task/status schema, and cross-agent capability registry.
- Risk/effort: High; Thomas must compare A2A against ACP/MCP boundaries and avoid premature external-agent exposure.
- Next implementation task shape: Draft an A2A-compatible Thomas worker capability card and task status exchange.
- Source entry reference: `2026-06-26 - A2A agent-to-agent protocol`.

### 45. Deterministic Agent Control Protocol
- Score: 88/100
- Repo URL: https://github.com/elliot35/deterministic-agent-control-protocol
- Feature/ability: Governance gateway for AI agents with bounded, auditable, session-aware control through MCP proxy, shell proxy, and HTTP API.
- Why Thomas should adopt it: Thomas needs deterministic control around shell and MCP actions at runtime, close to its commit/workboard gate model but earlier in the action path.
- Likely Thomas integration surface: MCP proxy, shell command proxy, session-aware policy, audit log, and deterministic replay/control layer.
- Risk/effort: High; action proxying touches core execution ergonomics and must fail closed without blocking safe routine work.
- Next implementation task shape: Model one Thomas shell-command flow through a session-aware proxy with allow/block/audit outcomes.
- Source entry reference: `2026-06-26 - Deterministic Agent Control Protocol`.

### 46. DeerFlow Long-Horizon SuperAgent Harness
- Score: 88/100
- Repo URL: https://github.com/bytedance/deer-flow
- Feature/ability: Long-horizon SuperAgent harness with sandboxes, memories, tools, skills, subagents, and a message gateway for tasks that run minutes to hours.
- Why Thomas should adopt it: Thomas needs long-running native worker orchestration with memory, sandboxes, subagents, and user-visible progress.
- Likely Thomas integration surface: Long-horizon worker harness, skill/subagent composition, sandbox integration, message gateway, and task progress model.
- Risk/effort: High; broad harness concepts must be sliced into Thomas-compatible run state, workboard, and security pieces.
- Next implementation task shape: Compare DeerFlow's long-horizon task loop against Thomas worker lifecycle and progress-report requirements.
- Source entry reference: `2026-06-26 - DeerFlow long-horizon SuperAgent harness`.

### 47. OpenLIT AI Engineering Observability
- Score: 88/100
- Repo URL: https://github.com/openlit/openlit
- Feature/ability: OpenTelemetry-native AI engineering platform with LLM observability, evaluations, prompt management, guardrails, and local coding-agent tracing hooks.
- Why Thomas should adopt it: OpenLIT explicitly targets Claude Code, Cursor, and Codex local coding-agent sessions, matching Thomas's local worker observability needs.
- Likely Thomas integration surface: Local coding-agent trace hooks, OTel collector, evaluation dashboards, prompt/tool metrics, and portal observability.
- Risk/effort: Medium-high; broad platform surface must be reduced to local trace hooks and backend-neutral export first.
- Next implementation task shape: Compare OpenLIT local coding-agent tracing hooks against Thomas worker trace event requirements.
- Source entry reference: `2026-06-26 - OpenLIT AI engineering observability`.

### 48. Helicone LLM Observability and Cost Control
- Score: 88/100
- Repo URL: https://github.com/helicone/helicone
- Feature/ability: Open-source LLM observability platform with request logging, model/user cost analytics, caching, and gateway-style routing.
- Why Thomas should adopt it: Thomas should make cost, latency, cache hit rate, and model behavior inspectable by worker and workflow instead of relying on provider billing dashboards after the fact.
- Likely Thomas integration surface: Gateway observability, request metadata propagation, cache analytics, model-cost API, portal dashboards, per-worker usage drilldowns, and run-level traces.
- Risk/effort: Medium effort and low-medium risk; strong observability fit, but Thomas needs a local-first story for sensitive prompt/request data before adopting hosted-style logging patterns.
- Next implementation task shape: Define the request metadata Thomas must attach to every model call, then test whether a Helicone-style log view can group by worker_id, task_id, repo area, model, cost, and latency.
- Source entry reference: `2026-06-26 - Helicone LLM observability and cost control`.

### 49. GPTCache Semantic Cache for LLMs
- Score: 88/100
- Repo URL: https://github.com/zilliztech/GPTCache
- Feature/ability: Semantic cache for LLM queries with LangChain and LlamaIndex integration, server mode, similarity matching, and configurable storage backends.
- Why Thomas should adopt it: Thomas can reduce repeated model calls from worker retries, duplicate research loops, and repeated repository-orientation prompts while improving response latency. GPTCache is mature enough to anchor a semantic-cache comparison.
- Likely Thomas integration surface: Gateway semantic cache, prompt fingerprinting, cache safety policy, worker retry de-duplication, cost reduction metrics, vector-store backed cache invalidation, and cache-hit audit logs.
- Risk/effort: Medium effort and medium risk; caching agent outputs can replay stale or context-mismatched answers, so Thomas needs conservative similarity thresholds and explicit bypass paths for high-risk tasks.
- Next implementation task shape: Prototype a read-only semantic-cache experiment for repeated low-risk orientation prompts, recording cache key, similarity score, source context, cost saved, and forced-miss reasons.
- Source entry reference: `2026-06-26 - GPTCache semantic cache for LLMs`.

### 50. Accenture MCP-Bench
- Score: 88/100
- Repo URL: https://github.com/Accenture/mcp-bench
- Feature/ability: Benchmark for tool-using LLM agents over complex real-world tasks via MCP servers.
- Why Thomas should adopt it: MCP tool quality and server orchestration should be benchmarked under realistic task pressure before Thomas relies on them for autonomous work.
- Likely Thomas integration surface: MCP tool benchmark suite, server-selection evals, task decomposition traces, tool-call scoring, MCP regression gates, and tool reliability scorecards.
- Risk/effort: Medium effort and medium risk; strong direct fit, but Thomas must isolate flaky external MCP servers and separate agent failure from server failure.
- Next implementation task shape: Define a Thomas MCP scorecard that measures tool discovery, argument correctness, call sequencing, error recovery, and final task success across a small server set.
- Source entry reference: `2026-06-26 - Accenture MCP-Bench`.

### 51. Agent Contracts
- Score: 88/100
- Repo URL: https://github.com/relari-ai/agent-contracts
- Feature/ability: Contract-style tests and assertions for AI agents, focused on expected behavior and regression detection.
- Why Thomas should adopt it: Thomas needs explicit behavioral contracts for agent tools, workboard handoffs, browser actions, and safety gates. Contract tests would turn expected agent behavior into repeatable acceptance criteria instead of prose-only review.
- Likely Thomas integration surface: Agent behavior contracts, contract-driven evals, CI regression gates, reviewer assertions, run acceptance criteria, and workboard claim completion checks.
- Risk/effort: Medium effort and low-medium risk; the pattern is highly aligned, but Thomas must keep contracts narrow enough that agents can understand and satisfy them without overfitting.
- Next implementation task shape: Define a first Thomas agent contract for a workboard handoff: required evidence, scoped file list, verification command, no-code-edit guarantee, and failure-summary behavior.
- Source entry reference: `2026-06-26 - Agent contracts`.

### 52. Microsoft Eval-Guide
- Score: 88/100
- Repo URL: https://github.com/microsoft/eval-guide
- Feature/ability: AI agent evaluation toolkit for planning evals, generating test cases, interpreting results, and triaging failures from Claude Code or GitHub Copilot.
- Why Thomas should adopt it: Thomas needs a guided path from vague worker failures to eval plans, concrete cases, and triaged improvements.
- Likely Thomas integration surface: Eval planning assistant, failure triage workflow, test-case generation, workboard issue conversion, reviewer/coordinator playbooks, and evaluation runbooks.
- Risk/effort: Low-medium effort and low-medium risk; useful as process guidance, but Thomas should encode the resulting workflow in its own workboard/eval artifacts.
- Next implementation task shape: Draft a Thomas eval triage playbook that turns one failed worker run into failure hypothesis, eval case, expected behavior, owner, and workboard issue.
- Source entry reference: `2026-06-26 - Microsoft eval-guide`.

### 53. Anthropic Skills
- Score: 88/100
- Repo URL: https://github.com/anthropics/skills
- Feature/ability: Official collection of Claude Skills with reusable instructions, assets, and examples for packaging domain-specific agent capabilities.
- Why Thomas should adopt it: Thomas needs a clear skill packaging convention that can include instructions, scripts, templates, and assets without turning every workflow into one-off prompt text. Anthropic's official pattern is a major compatibility target.
- Likely Thomas integration surface: Skill directory schema, installer compatibility, marketplace import, skill review checklist, first-party Thomas skill examples, and import validation.
- Risk/effort: Medium effort and low-medium risk; strong ecosystem relevance, but Thomas should support compatibility without forcing every Thomas-native skill into Claude-specific assumptions.
- Next implementation task shape: Compare the Anthropic skill layout with Thomas skill needs and draft a compatibility matrix for metadata, instructions, scripts, assets, examples, permissions, and tests.
- Source entry reference: `2026-06-26 - Anthropic skills`.

### 54. SLSA GitHub Generator
- Score: 88/100
- Repo URL: https://github.com/slsa-framework/slsa-github-generator
- Feature/ability: GitHub Actions generator for SLSA provenance attestations across build artifacts.
- Why Thomas should adopt it: Thomas should attach build provenance to packaged skills and release artifacts so marketplace consumers can verify how they were built.
- Likely Thomas integration surface: Skill build provenance, CI attestations, release artifact verification, marketplace metadata ingestion, trust-label generation, and promotion gates.
- Risk/effort: Medium effort and low-medium risk; direct CI integration is practical, but Thomas needs to decide which artifacts require provenance before adding process overhead.
- Next implementation task shape: Create a provenance requirement matrix for Thomas artifacts: first-party skills, marketplace skills, release bundles, generated reports, and worker-produced packages.
- Source entry reference: `2026-06-26 - SLSA GitHub Generator`.

### 55. SPIRE Workload Identity
- Score: 88/100
- Repo URL: https://github.com/spiffe/spire
- Feature/ability: SPIFFE Runtime Environment for issuing and verifying workload identities across distributed systems.
- Why Thomas should adopt it: Thomas worker, tool-server, and sidecar identities should be verifiable without relying on hostnames, local thread names, or implicit trust.
- Likely Thomas integration surface: Worker identity issuance, tool-server authentication, trust-domain model, workload attestation, and signed identity metadata.
- Risk/effort: High; strong architectural fit, but full SPIRE deployment would be infrastructure-heavy for a desktop-first Thomas setup.
- Next implementation task shape: Define a Thomas workload-identity contract inspired by SPIFFE IDs and verify it in one worker-to-tool call path.
- Source entry reference: `2026-06-26 - SPIRE workload identity`.

### 56. SpiceDB Fine-Grained Authorization Database
- Score: 88/100
- Repo URL: https://github.com/authzed/spicedb
- Feature/ability: Zanzibar-inspired fine-grained authorization database for scalable relationship-based permissions.
- Why Thomas should adopt it: If Thomas evolves multi-user, multi-worker, multi-repo access control, role flags will not be enough; SpiceDB is a mature reference for modeling user, worker, repo, claim, tool, secret, and approval relationships.
- Likely Thomas integration surface: Authorization backend, workspace/repo permission graph, claim-to-tool policy checks, and audit queries.
- Risk/effort: High; mature and powerful, but Thomas would need a thin policy layer and migration strategy before adopting a separate auth database.
- Next implementation task shape: Model a small Thomas relationship graph for user, worker, repo, claim, tool, and secret access, then compare SpiceDB and OpenFGA semantics.
- Source entry reference: `2026-06-26 - SpiceDB fine-grained authorization database`.

### 57. AI Agents Governed Software-Development System
- Score: 88/100
- Repo URL: https://github.com/rjmurillo/ai-agents
- Feature/ability: Multi-agent software-development system with session protocol, review gates, ADR-guided behavior, AI issue triage, AI PR quality gate, spec validation, and marketplace packaging for Claude Code/Copilot CLI.
- Why Thomas should adopt it: This maps closely to Thomas's need for reviewable software work and gate-heavy repo workflows, rather than generic agent orchestration.
- Likely Thomas integration surface: Workboard protocol, PR/issue triage workers, spec-to-implementation validation, plugin/skill packaging, and review gate automation.
- Risk/effort: Medium; strong fit, but Thomas should borrow protocol and gate shapes without assuming compatibility with its existing workboard and commit-helper contracts.
- Next implementation task shape: Compare its session protocol and PR quality gate to Thomas workboard claims and scoped commit checks.
- Source entry reference: `2026-06-26 - AI Agents governed software-development system`.

### 58. DashClaw Governance Runtime
- Score: 88/100
- Repo URL: https://github.com/ucsandman/DashClaw
- Feature/ability: Governance layer that evaluates policy on risky agent actions, routes required human approvals, records verifiable evidence, and tracks terminal outcomes to avoid silent double execution.
- Why Thomas should adopt it: Thomas already depends on claims, approvals, and commit gates; DashClaw's decision-trail and terminal-outcome concepts are useful for preventing retried workers from repeating irreversible actions.
- Likely Thomas integration surface: Approval router, workboard action receipts, risky-action middleware, retry/idempotency guard, and audit-ready run timeline.
- Risk/effort: Medium-high; strong conceptual fit, but implementation should be narrowed to action receipts and terminal outcome semantics first.
- Next implementation task shape: Add a design note for terminal action receipts covering allowed, denied, approved, and already-completed worker actions.
- Source entry reference: `2026-06-26 - DashClaw governance runtime`.

### 59. AgentProbe Cassette Regression Safety Net
- Score: 88/100
- Repo URL: https://github.com/cornhusk39/agentprobe
- Feature/ability: Regression safety net for LLM agents that records runs as cassettes, replays deterministically in CI, scores deterministic assertions plus LLM judge results, and fails builds on quality/cost/latency regression.
- Why Thomas should adopt it: Thomas needs to convert real worker runs into CI checks so prompt, model, or tool changes do not silently degrade behavior.
- Likely Thomas integration surface: CI regression harness, worker cassette format, quality/cost/latency baselines, LLM-judge gate, and release preflight.
- Risk/effort: Medium; tight workflow fit, but Thomas should first constrain the cassette format and deterministic assertions.
- Next implementation task shape: Record one Thomas worker fixture as a cassette and add deterministic pass/fail assertions before any LLM-judge layer.
- Source entry reference: `2026-06-26 - AgentProbe cassette regression safety net`.

### 60. SQLite-Memory Offline-First Agent Memory
- Score: 88/100
- Repo URL: https://github.com/sqliteai/sqlite-memory
- Feature/ability: Markdown-based persistent memory for AI agents with semantic search, hybrid retrieval, and offline-first sync between agents.
- Why Thomas should adopt it: Thomas needs agent memory that is inspectable, portable, and usable across worker processes; Markdown plus local retrieval fits the Bible/guardrail culture better than hidden provider memory.
- Likely Thomas integration surface: `thomas/memory/`, worker memory stores, local-first sync, semantic retrieval, and cross-agent context sharing.
- Risk/effort: Medium; architecture is highly relevant, but sync and privacy semantics need careful review.
- Next implementation task shape: Prototype a Markdown-native memory note indexed through SQLite for one worker handoff.
- Source entry reference: `2026-06-26 - SQLite-Memory offline-first agent memory`.

### 61. MemClaw Cross-Fleet Governed Memory
- Score: 88/100
- Repo URL: https://github.com/caura-ai/memclaw-cross-fleet-gov
- Feature/ability: Multi-agent memory governance demo with shared memory backend, fleet-scoped boundaries, query-time filtering, per-row ACLs, cross-fleet synthesis, and conflict detection.
- Why Thomas should adopt it: Thomas workers need shared memory without leaking unrelated project, repo, or role context; this is a concrete reference for memory boundaries and conflict detection across worker groups.
- Likely Thomas integration surface: Worker-team memory scopes, per-agent ACLs, query filters, cross-project synthesis controls, and memory-conflict reports.
- Risk/effort: Medium; demo-sized, but the governance pattern is directly aligned with multi-worker memory safety.
- Next implementation task shape: Prototype a worker-team memory ACL table and conflict report for two agents sharing project facts.
- Source entry reference: `2026-06-27 - MemClaw cross-fleet governed memory`.

### 62. Langfuse Open-Source LLM Observability and Evals
- Score: 87/100
- Repo URL: https://github.com/langfuse/langfuse
- Feature/ability: Self-hostable tracing, monitoring, eval, and debugging platform for AI apps.
- Why Thomas should adopt it: Thomas needs durable traces of model calls, tool calls, cost, latency, and failures.
- Likely Thomas integration surface: Telemetry backend, run trace viewer, cost accounting, and eval dashboards.
- Risk/effort: Medium-high; scope to trace schema before platform adoption.
- Next implementation task shape: Define Thomas's minimum trace record and compare against Langfuse.
- Source entry reference: `2026-06-26 - Langfuse open-source LLM observability and evals`.

### 63. Inspect AI Eval Framework
- Score: 87/100
- Repo URL: https://github.com/UKGovernmentBEIS/inspect_ai
- Feature/ability: Evals for tool usage, multi-turn dialog, model grading, coding tasks, and agentic tasks.
- Why Thomas should adopt it: Thomas needs repeatable tests for agent behavior beyond deterministic unit tests.
- Likely Thomas integration surface: `thomas/core/testing_suite.py`, benchmark tasks, tool-use evals, and CI gates.
- Risk/effort: Medium; fixture and scoring design matter.
- Next implementation task shape: Create one Thomas delegated-workflow eval.
- Source entry reference: `2026-06-26 - Inspect AI eval framework`.

### 64. AgentSeal Local Agent Security Scanner
- Score: 87/100
- Repo URL: https://github.com/getagentseal/agentseal
- Feature/ability: Local scanner for dangerous skills, poisoned MCP configs, data exfiltration paths, prompt-injection resistance, and live MCP tool poisoning.
- Why Thomas should adopt it: Thomas has skills, tools, MCP-like integrations, and local config risk that need runtime-specific security scanning.
- Likely Thomas integration surface: Local environment audit command, skill/plugin scanner, MCP config validator, and security report generation.
- Risk/effort: Medium; scanner findings must be actionable and not flood workers with low-confidence warnings.
- Next implementation task shape: Define a Thomas local agent-environment audit checklist from AgentSeal's categories.
- Source entry reference: `2026-06-26 - AgentSeal local agent security scanner`.

### 65. NVIDIA SkillSpector
- Score: 87/100
- Repo URL: https://github.com/NVIDIA/SkillSpector
- Feature/ability: Security scanner for AI agent skills that detects vulnerabilities, malicious patterns, and risky behavior before install.
- Why Thomas should adopt it: Thomas needs first-party preinstall scanning before skill/plugin instructions become trusted execution surfaces.
- Likely Thomas integration surface: Skill install gate, plugin marketplace scan, CI security check, and worker bootstrap validation.
- Risk/effort: Medium; scanner findings need clear severity and remediation guidance.
- Next implementation task shape: Compare SkillSpector's findings model with Thomas skill/plugin safety requirements.
- Source entry reference: `2026-06-26 - NVIDIA SkillSpector`.

### 66. AgentGuard Supply-Chain Command Interceptor
- Score: 87/100
- Repo URL: https://github.com/momenbasel/AgentGuard
- Feature/ability: Intercepts and validates package installs, `git clone`, and script downloads triggered by AI coding agents.
- Why Thomas should adopt it: Thomas workers can be tricked into installing packages or cloning malicious repositories; pre-execution command validation is a strong control.
- Likely Thomas integration surface: Shell/tool execution middleware, package install approval, clone/download guardrails, and security audit logging.
- Risk/effort: Medium-high; command interception must be precise enough to avoid both bypasses and developer-hostile false positives.
- Next implementation task shape: Define a Thomas command-risk policy for package installs, clones, and remote script execution.
- Source entry reference: `2026-06-26 - AgentGuard supply-chain command interceptor`.

### 67. OpenACP Messaging Bridge for Coding Agents
- Score: 87/100
- Repo URL: https://github.com/Open-ACP/OpenACP
- Feature/ability: Self-hosted ACP session bridge for Claude Code, Codex, and similar agents from messaging platforms.
- Why Thomas should adopt it: Thomas needs visible remote control over worker sessions without hiding work in one background process.
- Likely Thomas integration surface: Thomas chat-to-worker bridge, ACP session manager, remote worker control, and permission/event routing.
- Risk/effort: Medium-high; session bridge becomes a trust and audit boundary.
- Next implementation task shape: Compare OpenACP session routing with Thomas chat delegation and portal worker controls.
- Source entry reference: `2026-06-26 - OpenACP messaging bridge for coding agents`.

### 68. Dreadnode Agent Lens
- Score: 87/100
- Repo URL: https://github.com/dreadnode/agent-lens
- Feature/ability: Agent observability and replay tooling for AI safety and interpretability research, including Claude SDK sessions and trajectory validation models.
- Why Thomas should adopt it: Safety-oriented trajectory validation could turn raw Thomas worker traces into reviewer evidence and eval inputs.
- Likely Thomas integration surface: Agent trajectory schema, replay/eval pipeline, safety review artifacts, and Claude/Codex session analysis.
- Risk/effort: Medium-high; useful replay patterns but validation models need careful calibration against Thomas tasks.
- Next implementation task shape: Define a minimal Thomas trajectory record and compare it against Agent Lens replay fields.
- Source entry reference: `2026-06-26 - Dreadnode Agent Lens`.

### 69. Cordum Open Agent Control Plane
- Score: 87/100
- Repo URL: https://github.com/cordum-io/cordum
- Feature/ability: Open agent control plane with pre-execution policy enforcement, approval gates, and cross-framework audit trails.
- Why Thomas should adopt it: Thomas native orchestration needs one visible governance layer for heterogeneous workers and tools.
- Likely Thomas integration surface: Native agent control plane, approval queues, cross-framework policy adapter, and run audit dashboard.
- Risk/effort: High; control-plane work touches UX, policy, worker protocols, and audit storage.
- Next implementation task shape: Sketch a Thomas approval-gate state machine for one delegated worker action.
- Source entry reference: `2026-06-26 - Cordum open agent control plane`.

### 70. Phoenix AI Observability And Evaluation
- Score: 87/100
- Repo URL: https://github.com/arize-ai/phoenix
- Feature/ability: Open-source AI observability and evaluation platform with tracing, experiments, datasets, prompt management, and coding-agent observability skills.
- Why Thomas should adopt it: Thomas needs production-grade traces and eval workflows as agent runs become more complex.
- Likely Thomas integration surface: Agent trace backend, eval dashboard, prompt/run experiments, and worker observability skills.
- Risk/effort: Medium-high; platform is mature but Thomas should first define its own minimum trace/eval contract.
- Next implementation task shape: Compare Phoenix trace and dataset concepts against one Thomas worker run record.
- Source entry reference: `2026-06-26 - Phoenix AI observability and evaluation`.

### 71. Delegate Multi-Agent Worktree Orchestration
- Score: 87/100
- Repo URL: https://github.com/nikhilgarg28/delegate
- Feature/ability: CLI-driven multi-agent delegation across git worktrees with coordinated outputs back to a parent workflow.
- Why Thomas should adopt it: Thomas is already moving toward visible worker coordination, and worktree isolation plus merge-back ergonomics are directly relevant.
- Likely Thomas integration surface: Workboard claim spawning, worker workspace creation, branch/worktree lifecycle helpers, and merge-review handoff flows.
- Risk/effort: Medium-high; worktree orchestration must avoid dirty-state collisions and preserve clear review ownership.
- Next implementation task shape: Compare Delegate's worktree lifecycle against Thomas workboard claim and merge-coordinator flow.
- Source entry reference: `2026-06-26 - Delegate multi-agent worktree orchestration`.

### 72. Task Orchestrator MCP Quality Gates
- Score: 87/100
- Repo URL: https://github.com/jpicklyk/task-orchestrator
- Feature/ability: MCP server enforcing persistent work items, dependency graphs, quality gates, actor attribution, and required output schemas.
- Why Thomas should adopt it: Thomas workboard claims and commit helpers already act as gates; MCP-enforced schemas could make accountability consistent for every agent.
- Likely Thomas integration surface: Workboard MCP endpoint, deliverable schema validation, claim dependency graph, quality gates, and actor attribution logs.
- Risk/effort: Medium-high; strong fit, but schema enforcement must not slow legitimate fast maintenance loops.
- Next implementation task shape: Draft a Thomas workboard MCP schema for claim, dependency, deliverable, and gate status records.
- Source entry reference: `2026-06-26 - Task Orchestrator MCP quality gates`.

### 73. CopilotKit Agent-Native Frontend Stack
- Score: 87/100
- Repo URL: https://github.com/CopilotKit/CopilotKit
- Feature/ability: Agent-native frontend stack with generative UI, shared state, human-in-the-loop workflows, AG-UI protocol support, and agent skills for coding assistants.
- Why Thomas should adopt it: Thomas is becoming a portal for visible workers, and CopilotKit is a strong reference for connecting agent state, approvals, and UI controls without hiding the loop.
- Likely Thomas integration surface: Thomas portal agent UI, approval widgets, shared worker state, AG-UI/agent protocol bridge, and front-end run controls.
- Risk/effort: Medium-high; frontend patterns are useful, but Thomas must preserve local workboard and security semantics.
- Next implementation task shape: Map one Thomas worker approval/run-control flow onto a portal component/state contract.
- Source entry reference: `2026-06-26 - CopilotKit agent-native frontend stack`.

### 74. AWS CLI Agent Orchestrator
- Score: 87/100
- Repo URL: https://github.com/awslabs/cli-agent-orchestrator
- Feature/ability: CLI orchestrator for coordinating multiple coding agents across tasks, worktrees, execution, and review loops.
- Why Thomas should adopt it: Thomas needs native worker spawning and coordination while preserving local repo discipline; this is a direct CLI/worktree orchestration reference.
- Likely Thomas integration surface: Thomas worker CLI, worktree/task dispatcher, review handoff flow, and local orchestration scripts.
- Risk/effort: Medium-high; orchestration ideas must be reconciled with existing claims, commit helper, and dirty-worktree gates.
- Next implementation task shape: Compare AWS orchestrator task/worktree lifecycle against Thomas claim, worker, and merge handoff flows.
- Source entry reference: `2026-06-26 - AWS CLI Agent Orchestrator`.

### 75. AgentEvals Trajectory Evaluators
- Score: 87/100
- Repo URL: https://github.com/langchain-ai/agentevals
- Feature/ability: Ready-made evaluators and utilities focused on agent trajectories and intermediate execution steps.
- Why Thomas should adopt it: Thomas worker correctness often depends on the path taken, not just final output; trajectory evals can catch bad tool choices, wasted loops, and unsafe shortcuts.
- Likely Thomas integration surface: Worker trajectory evaluator, CI agent-behavior gates, trace-to-eval conversion, and ranker scoring criteria.
- Risk/effort: Medium; useful directly, but Thomas trace schemas need to be stable before broad evaluation.
- Next implementation task shape: Convert one Thomas worker trace into a trajectory-eval fixture with expected safe/unsafe path labels.
- Source entry reference: `2026-06-26 - AgentEvals trajectory evaluators`.

### 76. Restate Durable AI Examples
- Score: 87/100
- Repo URL: https://github.com/restatedev/ai-examples
- Feature/ability: Runnable durable AI workflow and agent examples using Restate, including agent, MCP, A2A, and orchestration patterns.
- Why Thomas should adopt it: Thomas workers need crash recovery, resumable tool calls, and durable orchestration without bespoke state machines for every worker.
- Likely Thomas integration surface: Worker durable-execution runtime, MCP/A2A workflow examples, restart-safe task orchestration, and run recovery prototypes.
- Risk/effort: Medium-high; examples are strong references, but Thomas still needs its own local persistence and security model.
- Next implementation task shape: Prototype a restart-safe Thomas task journal using a Restate-style durable invocation sequence.
- Source entry reference: `2026-06-26 - Restate durable AI examples`.

### 77. Symbol Delta Ledger MCP
- Score: 87/100
- Repo URL: https://github.com/GlitterKill/sdl-mcp
- Feature/ability: Policy-centered context-budget layer for coding agents using symbol-graph intelligence, precision tools, validation hooks, and MCP access.
- Why Thomas should adopt it: Thomas workers spend significant budget discovering code context, and compact symbol cards plus escalation policy directly fit local coding workflows.
- Likely Thomas integration surface: Repo intelligence MCP, context-budget policy, symbol-card cache, validation hooks, and worker code-navigation tools.
- Risk/effort: Medium-high; needs validation against Thomas's mixed Python/JS/docs repo and existing code-search/RAG boundaries.
- Next implementation task shape: Prototype a symbol-card context budget for one Thomas module and compare token/tool savings.
- Source entry reference: `2026-06-26 - Symbol Delta Ledger MCP`.

### 78. GoPlus AgentGuard
- Score: 87/100
- Repo URL: https://github.com/GoPlusSecurity/agentguard
- Feature/ability: Local security guard for AI agents that blocks malicious skills, prevents data leaks, protects secrets, evaluates runtime actions, and maintains a trust registry.
- Why Thomas should adopt it: Thomas needs local-first protection around skills, secrets, destructive commands, and action attribution.
- Likely Thomas integration surface: Local hook layer, skill trust registry, destructive-command guard, secret-protection rules, and tool action attribution.
- Risk/effort: Medium-high; direct controls fit well but need comparison with Thomas vault, skill, and command policies.
- Next implementation task shape: Compare AgentGuard's trust registry and command guard categories against Thomas skills/plugins and shell gates.
- Source entry reference: `2026-06-26 - GoPlus AgentGuard`.

### 79. DSPy Declarative Self-Improving Programs
- Score: 87/100
- Repo URL: https://github.com/stanfordnlp/dspy
- Feature/ability: Declarative programming framework for language-model systems, including self-improving pipelines and agent loops.
- Why Thomas should adopt it: Thomas needs eval-backed improvement of worker prompts and workflows rather than manual prompt tweaking.
- Likely Thomas integration surface: Worker prompt/program optimization, eval-backed workflow tuning, reusable task modules, and self-improvement experiments.
- Risk/effort: Medium-high; optimization must be constrained by Thomas safety gates and meaningful eval data.
- Next implementation task shape: Convert one repeatable Thomas worker prompt into a declarative module with a small evaluation set.
- Source entry reference: `2026-06-26 - DSPy declarative self-improving programs`.

### 80. OpenLLMetry OpenTelemetry LLM Observability
- Score: 87/100
- Repo URL: https://github.com/traceloop/openllmetry
- Feature/ability: OpenTelemetry-based observability extensions for LLM applications, including traces for prompts, model calls, vector DBs, and framework integrations.
- Why Thomas should adopt it: Thomas worker runs should emit standard telemetry that can flow into existing observability backends instead of staying trapped in per-thread logs.
- Likely Thomas integration surface: OpenTelemetry instrumentation, worker span schema, tool-call trace export, and observability backend adapters.
- Risk/effort: Medium; schema design matters more than adopting every integration.
- Next implementation task shape: Define a minimal Thomas OTel span schema for model call, tool call, memory lookup, and worker handoff.
- Source entry reference: `2026-06-26 - OpenLLMetry OpenTelemetry LLM observability`.

### 81. Cursor Agent-Trace Coding-Agent Observability
- Score: 87/100
- Repo URL: https://github.com/cursor/agent-trace
- Feature/ability: Coding-agent trace capture patterns for execution context, tool activity, and decision evidence useful in debugging autonomous edits.
- Why Thomas should adopt it: Thomas needs durable evidence for why coding workers changed files, retried actions, or stopped. A coding-agent-specific trace pattern can strengthen review handoff quality beyond generic logs.
- Likely Thomas integration surface: Coding-worker trace capture, review evidence links, per-turn event schema, timeline replay, local artifact storage, and workboard handoff attachments.
- Risk/effort: Medium effort and medium risk; direct fit is strong, but repo maturity and format stability need inspection before adopting any schema literally.
- Next implementation task shape: Inspect the trace format and design a small Thomas trace artifact prototype that records prompt, tool call, file-change, verification, and final-summary events for one worker run.
- Source entry reference: `2026-06-26 - Cursor agent-trace coding-agent observability`.

### 82. Verified Semantic Cache for LLM Agents
- Score: 87/100
- Repo URL: https://github.com/aws-samples/Reducing-Hallucinations-in-LLM-Agents-with-a-Verified-Semantic-Cache
- Feature/ability: Verified semantic cache pattern for LLM agents that checks cached answers against knowledge bases to reduce hallucinations while improving cost and latency.
- Why Thomas should adopt it: Thomas needs cache safety gates so semantic caching does not replay stale or unverifiable outputs into autonomous worker decisions. The verification pattern is more important than the AWS-specific implementation.
- Likely Thomas integration surface: Verified cache policy, RAG-backed cache validation, cache provenance, safe cache-hit criteria, agent answer grounding checks, and audit evidence for reused answers.
- Risk/effort: Medium effort and low-medium risk if used as a pattern; direct adoption is cloud-specific, but the guardrail model directly addresses semantic-cache failure modes.
- Next implementation task shape: Define a Thomas cache-hit verifier that requires matching repo snapshot, trusted source references, and a confidence threshold before reusing cached model output.
- Source entry reference: `2026-06-26 - Verified semantic cache for LLM agents`.

### 83. vLLM Semantic Router
- Score: 87/100
- Repo URL: https://github.com/vllm-project/semantic-router
- Feature/ability: System-level intelligent router for mixture-of-models across cloud, data center, and edge environments.
- Why Thomas should adopt it: Thomas needs routing policies that can pick cheaper, faster, or local models for low-risk worker steps while preserving stronger models for high-stakes decisions.
- Likely Thomas integration surface: Model routing policy, local/cloud provider selection, task-risk routing, benchmark-driven model choice, quota-aware scheduling, and gateway failover strategy.
- Risk/effort: Medium-high effort and medium risk; routing decisions must be explainable and bounded so cost optimization does not silently lower quality on critical actions.
- Next implementation task shape: Build a model-routing policy matrix for Thomas task classes, mapping risk level, expected reasoning depth, latency tolerance, context size, and allowed model tiers.
- Source entry reference: `2026-06-26 - vLLM semantic router`.

### 84. UIUC LLMRouter
- Score: 87/100
- Repo URL: https://github.com/ulab-uiuc/LLMRouter
- Feature/ability: Open-source LLM routing library that dynamically selects suitable models for single-round, multi-round, agentic, and personalized settings.
- Why Thomas should adopt it: Thomas worker routing should account for multi-turn and agentic task context, not only one-shot prompt difficulty. This maps closely to Thomas's long-running worker and reviewer loops.
- Likely Thomas integration surface: Agentic routing benchmark, personalized/user-aware model policy, route replay tests, scheduler integration, route telemetry, and task-risk model selection.
- Risk/effort: Medium effort and medium risk; the fit is strong, but Thomas needs explainable route decisions and strict guardrails for high-stakes code or security tasks.
- Next implementation task shape: Compare LLMRouter routing methods on a small Thomas task taxonomy: repo orientation, code edit, test failure analysis, security review, and final synthesis.
- Source entry reference: `2026-06-26 - UIUC LLMRouter`.

### 85. LastMile MCP Eval
- Score: 87/100
- Repo URL: https://github.com/lastmile-ai/mcp-eval
- Feature/ability: Developer-focused eval tooling for MCP servers, including tool-call testing and server behavior checks.
- Why Thomas should adopt it: Thomas already tracks MCP agent frameworks; it also needs a repeatable local eval loop for MCP servers before they enter trusted worker paths.
- Likely Thomas integration surface: MCP server CI checks, local server smoke tests, tool-call replay fixtures, contract drift detection, and eval summaries in workboard issues.
- Risk/effort: Low-medium effort and low-medium risk; practical fit is strong, but Thomas should avoid duplicating too many MCP eval harnesses without first defining a common scorecard schema.
- Next implementation task shape: Compare LastMile MCP Eval test structure with Scorecard MCP Eval and define a Thomas-neutral MCP server regression manifest.
- Source entry reference: `2026-06-26 - LastMile MCP Eval`.

### 86. MCP Inspector
- Score: 87/100
- Repo URL: https://github.com/modelcontextprotocol/inspector
- Feature/ability: Developer tool for inspecting, testing, and debugging MCP servers and tools interactively.
- Why Thomas should adopt it: Thomas should expose a practical MCP debugging path before treating a server as trusted infrastructure for workers. Official MCP inspection also complements automated scorecards and fuzzers.
- Likely Thomas integration surface: MCP server inspection, tool schema review, manual server smoke tests, developer portal diagnostics, onboarding checklist, and trusted-server acceptance evidence.
- Risk/effort: Low-medium effort and low risk; official tooling is mature enough for workflow adoption, with limited blast radius if used as an inspection aid rather than a runtime dependency.
- Next implementation task shape: Add an MCP server onboarding checklist that requires inspector evidence for tool discovery, schema shape, sample calls, error behavior, and auth assumptions.
- Source entry reference: `2026-06-26 - MCP Inspector`.

### 87. DeepEval LLM Eval Framework
- Score: 87/100
- Repo URL: https://github.com/confident-ai/deepeval
- Feature/ability: Pytest-like open-source framework for evaluating LLM systems with metrics for task completion, hallucination, relevancy, and LLM-as-judge checks.
- Why Thomas should adopt it: Thomas should turn agent expectations into code-level eval tests that can run locally and in CI, especially around failure clusters.
- Likely Thomas integration surface: Python eval tests, CI quality gates, agent contract assertions, local JSON result export, LLM-as-judge checks, and metric comparison with Thomas testing suite.
- Risk/effort: Medium effort and medium risk; mature framework ergonomics are strong, but LLM-as-judge drift needs pinned rubrics and calibration examples.
- Next implementation task shape: Write a small Thomas eval spike that uses a pytest-like structure to score a worker summary against expected evidence, task completion, and hallucination constraints.
- Source entry reference: `2026-06-26 - DeepEval LLM eval framework`.

### 88. GUAC Supply-Chain Graph
- Score: 87/100
- Repo URL: https://github.com/guacsec/guac
- Feature/ability: Graph for Understanding Artifact Composition that ingests SBOMs, attestations, vulnerabilities, and dependency relationships.
- Why Thomas should adopt it: Thomas marketplace moderation needs a graph of skill dependencies, provenance, vulnerability state, and trusted source relationships.
- Likely Thomas integration surface: Skill dependency graph, vulnerability disclosure queue, provenance ingestion, marketplace risk scoring, trust-label propagation, and artifact relationship queries.
- Risk/effort: Medium-high effort and medium risk; graph value is high, but Thomas should start with a lightweight internal trust graph before adopting a full GUAC stack.
- Next implementation task shape: Draft a Thomas skill trust graph model with nodes for skill, version, source, signer, dependency, vulnerability, review, and install event.
- Source entry reference: `2026-06-26 - GUAC supply-chain graph`.

### 89. Cedar Policy Language
- Score: 87/100
- Repo URL: https://github.com/cedar-policy/cedar
- Feature/ability: Readable policy language and authorization engine for fine-grained access control.
- Why Thomas should adopt it: Thomas needs reviewable policy for skill trust, tool calls, worker scopes, and prompt-time trust labels; Cedar is a clean reference for policy-as-code.
- Likely Thomas integration surface: Policy language comparison, skill install policy, trust-aware prompt assembly, worker action authorization, and policy test suite.
- Risk/effort: Medium; useful as a policy-shape reference, but competing policy engines should be compared before adopting runtime semantics.
- Next implementation task shape: Write a small policy-engine comparison note using one Thomas skill-install rule and one worker tool-call rule.
- Source entry reference: `2026-06-26 - Cedar policy language`.

### 90. Diffity Agent-Agnostic Diff Review
- Score: 87/100
- Repo URL: https://github.com/nilbuild/diffity
- Feature/ability: Agent-agnostic local diff viewer and code review tool for Claude Code, Cursor, Codex, and other AI coding agents, including AI review comments, guided code tours, and local PR review.
- Why Thomas should adopt it: Thomas needs a clean local workflow to inspect worker changes, request agent review, and push comments back to GitHub.
- Likely Thomas integration surface: Worker patch review UI, local PR review bridge, guided repo tours, AI reviewer comment capture, and task evidence pages.
- Risk/effort: Medium; high product fit, but Thomas should validate storage, GitHub sync, and local repo assumptions before borrowing UI flows.
- Next implementation task shape: Prototype a Thomas worker-patch review page outline using Diffity-style guided review and AI comment capture.
- Source entry reference: `2026-06-26 - Diffity agent-agnostic diff review`.

### 91. Memoirs Local Conflict-Resolved Agent Memory
- Score: 87/100
- Repo URL: https://github.com/misaelzapata/memoirs
- Feature/ability: Local-first long-term memory for agents with transcript ingestion, durable signal extraction, local LLM curation, ranked context retrieval, and conflict-resolved memory answers.
- Why Thomas should adopt it: Thomas needs memory that survives sessions while staying local and conflict-aware, especially for converting transcripts and tool calls into compact working context.
- Likely Thomas integration surface: `thomas/memory/`, worker transcript ingestion, context compaction, local LLM memory curation, and conflict resolution.
- Risk/effort: Medium; strong local fit, but implementation should be reviewed thoroughly before reuse.
- Next implementation task shape: Convert one Thomas worker transcript into durable memory facts and test conflict-aware retrieval.
- Source entry reference: `2026-06-27 - Memoirs local conflict-resolved agent memory`.

### 92. Carto Structural Codebase Intelligence
- Score: 86/100
- Repo URL: https://github.com/theanshsonkar/carto
- Feature/ability: Persistent architecture maps, import graphs, route/domain maps, blast-radius analysis, diff validation, MCP serving, and PR impact reports.
- Why Thomas should adopt it: Thomas workers repeatedly need live repo structure and blast-radius context before editing.
- Likely Thomas integration surface: Repo intelligence service, MCP tool server, workboard preflight checks, PR impact comments, and code-edit risk scoring.
- Risk/effort: Medium-high; repo maps must stay current and not override the Bible/live-code trust order.
- Next implementation task shape: Evaluate Carto-style import graph plus diff-risk report against one Thomas change.
- Source entry reference: `2026-06-26 - Carto structural codebase intelligence`.

### 93. AgentTrace Local-First Agent Debugger
- Score: 86/100
- Repo URL: https://github.com/Rxflex/agenttrace
- Feature/ability: Local-first step debugger for spans, tool calls, prompts, and responses in an interactive tree.
- Why Thomas should adopt it: Thomas needs readable local run traces for worker/reviewer/coordinator sessions.
- Likely Thomas integration surface: Delegation trace viewer, local run logs, tool-call tree UI, and post-run debugging.
- Risk/effort: Medium; strong fit if trace storage remains local-first and lightweight.
- Next implementation task shape: Compare AgentTrace tree model with Thomas delegation event stream.
- Source entry reference: `2026-06-26 - AgentTrace local-first agent debugger`.

### 94. Pydantic AI Typed Agents and Evals
- Score: 86/100
- Repo URL: https://github.com/pydantic/pydantic-ai
- Feature/ability: Type-safe agents, structured tool interfaces, dependency injection, and eval hooks.
- Why Thomas should adopt it: Typed tool contracts reduce schema drift across tools and CLI/server surfaces.
- Likely Thomas integration surface: `thomas/server/tool_extensions.py`, `thomas/tools/*`, testing suite checks, and CLI schemas.
- Risk/effort: Medium; incremental wrappers fit best.
- Next implementation task shape: Add a typed contract to one high-traffic tool path.
- Source entry reference: `2026-06-26 - Pydantic AI typed agents and evals`.

### 95. Snyk Agent Scan
- Score: 86/100
- Repo URL: https://github.com/snyk/agent-scan
- Feature/ability: Agent component supply-chain scanner for prompt injection, tool poisoning, toxic flows, and vulnerable agent skills.
- Why Thomas should adopt it: Thomas needs repeatable inspection of skills and tools before workers use them.
- Likely Thomas integration surface: Skill marketplace safety checks, MCP/tool inventory audit, CI security gates, and worker bootstrap validation.
- Risk/effort: Medium; valuable vendor-backed framing, but Thomas needs local policy ownership.
- Next implementation task shape: Map Thomas skill/tool inventory to an agent-component scan report format.
- Source entry reference: `2026-06-26 - Snyk Agent Scan`.

### 96. Promptfoo Agent Evals and Red Teaming
- Score: 86/100
- Repo URL: https://github.com/promptfoo/promptfoo
- Feature/ability: CLI-first prompt, agent, and RAG testing with red teaming, vulnerability scanning, model comparison, and repo-stored declarative configs.
- Why Thomas should adopt it: Thomas needs agent regression and red-team cases that run in normal developer workflows.
- Likely Thomas integration surface: Agent eval config, CI checks, red-team task suites, and prompt/tool policy regression tests.
- Risk/effort: Medium; mature tool, but test cases must be grounded in Thomas failure modes.
- Next implementation task shape: Draft one promptfoo-style config for a Thomas tool-policy or delegation regression.
- Source entry reference: `2026-06-26 - promptfoo agent evals and red teaming`.

### 97. InjecAgent Indirect Prompt-Injection Benchmark
- Score: 86/100
- Repo URL: https://github.com/uiuc-kang-lab/InjecAgent
- Feature/ability: Benchmark for evaluating tool-integrated LLM agents against indirect prompt-injection attacks across user tools and attacker tools.
- Why Thomas should adopt it: Thomas agents are tool-integrated and will process untrusted content, so prompt-injection tests need to exercise real tool behavior.
- Likely Thomas integration surface: Agent red-team test suite, tool-call policy checks, browser/research worker hardening, and CI security gates.
- Risk/effort: Medium; high value, but scenarios must be adapted to Thomas tools rather than copied verbatim.
- Next implementation task shape: Create one Thomas tool-integrated prompt-injection regression based on the benchmark shape.
- Source entry reference: `2026-06-26 - InjecAgent indirect prompt-injection benchmark`.

### 98. TraceRoot Production Agent Debugging
- Score: 86/100
- Repo URL: https://github.com/traceroot-ai/traceroot
- Feature/ability: Source-aware observability and self-healing layer for AI agents.
- Why Thomas should adopt it: Thomas needs traces that connect failures back to files, commits, PRs, and issues.
- Likely Thomas integration surface: Worker trace store, source-aware run debugger, incident monitor, and GitHub-history correlation.
- Risk/effort: Medium; self-healing must stay behind review gates.
- Next implementation task shape: Compare TraceRoot's source-aware trace model with Thomas delegation run logs.
- Source entry reference: `2026-06-26 - TraceRoot production agent debugging`.

### 99. ACP Bridge Multi-Agent Orchestrator
- Score: 86/100
- Repo URL: https://github.com/allvegetable/acp-bridge
- Feature/ability: ACP multi-agent orchestrator for Codex, Claude, Gemini, and OpenCode with parallel tasks, dependency chains, and diagnostics.
- Why Thomas should adopt it: Thomas needs visible provider-neutral orchestration and dependency management across worker lanes.
- Likely Thomas integration surface: Thomas-native ACP orchestrator, worker dependency graph, provider adapter registry, and diagnostic event stream.
- Risk/effort: Medium; small project but directly aligned with Thomas's orchestration direction.
- Next implementation task shape: Compare ACP Bridge task/dependency model against Thomas workboard delegation semantics.
- Source entry reference: `2026-06-26 - ACP Bridge multi-agent orchestrator`.

### 100. Agent-Replay Execution Trace Replay
- Score: 86/100
- Repo URL: https://github.com/manasvardhan/agent-replay
- Feature/ability: Agent execution trace recorder with step-by-step replay and behavior diffing across runs.
- Why Thomas should adopt it: Thomas workers need replayable evidence when runs fail or drift.
- Likely Thomas integration surface: Worker trace recorder, run replay UI, behavior diffing, and debugging artifacts for failed tasks.
- Risk/effort: Medium; trace capture must avoid leaking sensitive local data.
- Next implementation task shape: Define a minimal Thomas replay record for model/tool/action events.
- Source entry reference: `2026-06-26 - agent-replay execution trace replay`.

### 101. CyberArk Agentwatch Observability
- Score: 86/100
- Repo URL: https://github.com/cyberark/agentwatch
- Feature/ability: Framework-agnostic observability for intercepting, logging, and analyzing agent interactions across platforms.
- Why Thomas should adopt it: Thomas needs consistent visibility across Codex, Claude, Gemini, MCP, browser, and local tool workers.
- Likely Thomas integration surface: Agent interaction monitor, MCP/tool-call trace collection, multi-provider observability, and security review logs.
- Risk/effort: Medium; interception must preserve local privacy and avoid becoming a brittle shim around provider-specific formats.
- Next implementation task shape: Prototype a provider-neutral interaction envelope for one Thomas worker run.
- Source entry reference: `2026-06-26 - CyberArk agentwatch observability`.

### 102. Agent PR Replay
- Score: 86/100
- Repo URL: https://github.com/sshh12/agent-pr-replay
- Feature/ability: Converts merged PRs into replay tasks, runs Claude Code, and compares agent output against human-shipped changes.
- Why Thomas should adopt it: Thomas needs empirical repo-specific benchmarks based on real project history, not only synthetic tasks.
- Likely Thomas integration surface: Repo-specific coding-agent benchmark generator, PR replay harness, reviewer comparison reports, and regression suite.
- Risk/effort: Medium-high; replay quality depends on clean PR metadata, deterministic setup, and fair comparison rules.
- Next implementation task shape: Build a one-PR Thomas replay fixture that reconstructs the prompt, expected diff, and verification command.
- Source entry reference: `2026-06-26 - Agent PR Replay`.

### 103. AgentGate Human Approval Layer
- Score: 86/100
- Repo URL: https://github.com/agentkitai/agentgate
- Feature/ability: Human-in-the-loop approval gateway that pauses sensitive AI-agent tool calls until reviewed.
- Why Thomas should adopt it: Explicit approval gates can constrain code, commit, push, secret, and external-tool actions while preserving autonomy for low-risk work.
- Likely Thomas integration surface: Tool-call policy engine, workboard approval prompts, commit/push gates, and audit trail for approved or denied actions.
- Risk/effort: Medium-high; approval UX must be timely and enforceable outside the agent prompt.
- Next implementation task shape: Define Thomas high-impact actions and route one through an approval-request/decision record.
- Source entry reference: `2026-06-26 - AgentGate human approval layer`.

### 104. Task Graph MCP Multi-Agent Coordination
- Score: 86/100
- Repo URL: https://github.com/Oortonaut/task-graph-mcp
- Feature/ability: MCP coordination primitives for multi-agent codebase work, including worker task tracking and file-change coordination.
- Why Thomas should adopt it: It maps directly to Thomas's need for visible workers to avoid duplicate work, conflicting edits, and dependency mistakes.
- Likely Thomas integration surface: Workboard MCP server, file-scope claims, dependency graph tracking, and cross-agent coordination messages.
- Risk/effort: Medium-high; merge and security semantics need review before adopting coordination patterns.
- Next implementation task shape: Compare Task Graph MCP task/file models against Thomas workboard claim scope and message lanes.
- Source entry reference: `2026-06-26 - Task Graph MCP multi-agent coordination`.

### 105. Agent Tool Protocol Sandboxed Code Tools
- Score: 86/100
- Repo URL: https://github.com/mondaycom/agent-tool-protocol
- Feature/ability: Code-first tool protocol where agents execute TypeScript/JavaScript snippets in secure sandboxes with approvals, caching, logging, OpenAPI, and MCP compatibility.
- Why Thomas should adopt it: ATP offers a concrete alternative for complex multi-step tool interactions without stuffing prompts with oversized schemas.
- Likely Thomas integration surface: Tool execution gateway, MCP/OpenAPI bridge, tool-call approval flow, sandbox policy, and run observability.
- Risk/effort: High; protocol adoption would touch tool boundaries, sandbox policy, and approval semantics.
- Next implementation task shape: Evaluate one Thomas complex tool workflow against ATP-style sandboxed code execution.
- Source entry reference: `2026-06-26 - Agent Tool Protocol sandboxed code tools`.

### 106. EvoAgentX Self-Evolving Agent Workflows
- Score: 86/100
- Repo URL: https://github.com/EvoAgentX/EvoAgentX
- Feature/ability: Framework for building, evaluating, and evolving agentic workflows with automatic workflow construction, evaluators, memory, tools, and HITL checkpoints.
- Why Thomas should adopt it: Thomas needs disciplined workflow improvement loops instead of manual prompt surgery, with evaluation and human checkpoints around changes.
- Likely Thomas integration surface: Worker workflow generation, eval-backed improvement loops, tool library design, HITL checkpoints, and memory-backed run improvement.
- Risk/effort: High; self-improvement must be tightly gated so Thomas does not evolve unsafe or unverifiable worker behavior.
- Next implementation task shape: Define a Thomas workflow-improvement proposal record with required eval evidence and human approval.
- Source entry reference: `2026-06-26 - EvoAgentX self-evolving agent workflows`.

### 107. Scenario Agentic Testing Framework
- Score: 86/100
- Repo URL: https://github.com/langwatch/scenario
- Feature/ability: Agentic testing framework for exercising agentic codebases through scenarios rather than only static assertions.
- Why Thomas should adopt it: Thomas needs behavioral tests for claim, edit, verify, commit, recover, and approval workflows.
- Likely Thomas integration surface: Worker scenario tests, CI behavioral gates, runbook regression tests, and simulated user/tool interactions.
- Risk/effort: Medium; scenario tests need stable fake tools and deterministic assertions to avoid flaky gates.
- Next implementation task shape: Write a Thomas worker scenario fixture for claim, scoped edit, verification, commit, and release.
- Source entry reference: `2026-06-26 - Scenario agentic testing framework`.

### 108. Inngest AgentKit Deterministic Multi-Agent Routing
- Score: 86/100
- Repo URL: https://github.com/inngest/agent-kit
- Feature/ability: TypeScript kit for multi-agent networks with deterministic routing and rich MCP tooling.
- Why Thomas should adopt it: Deterministic routing would make worker handoffs, tool routing, and multi-agent decisions more inspectable and repeatable.
- Likely Thomas integration surface: Native orchestration router, MCP tool integration, workflow graph nodes, worker handoff policy, and deterministic test harnesses.
- Risk/effort: Medium-high; runtime ideas fit, but Thomas should adapt the routing semantics rather than replacing its Python/portal architecture.
- Next implementation task shape: Model one Thomas worker handoff as a deterministic route decision with testable inputs and outputs.
- Source entry reference: `2026-06-26 - Inngest AgentKit deterministic multi-agent routing`.

### 109. EvalView Behavior Regression Gate
- Score: 86/100
- Repo URL: https://github.com/hidai25/eval-view
- Feature/ability: Behavior regression gate for AI agents tracking drift across outputs, tools, model IDs, and runtime fingerprints.
- Why Thomas should adopt it: Thomas needs to distinguish real regressions from provider/model drift as worker behavior changes over time.
- Likely Thomas integration surface: Agent regression CI, drift classifier, run fingerprint capture, retry/review gate, and replayable eval artifacts.
- Risk/effort: Medium; requires consistent fingerprinting and stored artifacts to avoid noisy gates.
- Next implementation task shape: Add a Thomas run fingerprint concept covering model, tool set, prompt version, and runtime environment.
- Source entry reference: `2026-06-26 - EvalView behavior regression gate`.

### 110. A2A Python SDK
- Score: 86/100
- Repo URL: https://github.com/a2aproject/a2a-python
- Feature/ability: Official Python SDK for A2A servers with async operation, FastAPI/Starlette support, gRPC, OpenTelemetry, and database backends.
- Why Thomas should adopt it: Thomas is Python-heavy, making this the practical path for experimenting with A2A-compatible worker endpoints.
- Likely Thomas integration surface: Python worker A2A server, FastAPI/aiohttp adapter comparison, tracing hooks, persisted task backend, and interoperability tests.
- Risk/effort: Medium-high; SDK fit depends on Thomas server boundaries and existing aiohttp/FastAPI split.
- Next implementation task shape: Build a no-side-effect A2A worker endpoint spike around one read-only Thomas task.
- Source entry reference: `2026-06-26 - A2A Python SDK`.

### 111. CodeGraph Local Semantic Code Intelligence
- Score: 86/100
- Repo URL: https://github.com/colbymchenry/codegraph
- Feature/ability: Local semantic code intelligence and pre-indexed knowledge graph for Claude Code, Codex, Cursor, Gemini, OpenCode, and other agents.
- Why Thomas should adopt it: CodeGraph targets token and tool-call reduction for coding agents, mapping directly to Thomas worker cost and reliability concerns.
- Likely Thomas integration surface: Local code intelligence CLI, Codex/Claude worker setup, persistent repo graph, test-impact analysis, and context reduction metrics.
- Risk/effort: Medium; licensing, scale, and metric claims need review before adoption.
- Next implementation task shape: Run a small comparison plan for Thomas context retrieval using graph lookup versus plain file search.
- Source entry reference: `2026-06-26 - CodeGraph local semantic code intelligence`.

### 112. Agent Threat Rules
- Score: 86/100
- Repo URL: https://github.com/Agent-Threat-Rule/agent-threat-rules
- Feature/ability: Open detection-rule standard for AI agents, similar to Sigma, with rule coverage for agent threats and integrations.
- Why Thomas should adopt it: Thomas needs portable detection rules for suspicious tool use, prompt injection, data exfiltration, and unsafe agent behavior.
- Likely Thomas integration surface: Threat rule engine, tool-call detector, red-team rule pack, runtime guard test corpus, and security audit reports.
- Risk/effort: Medium; rule quality and coverage need validation, but the format could be adopted incrementally.
- Next implementation task shape: Express three Thomas agent-risk scenarios as portable detection rules.
- Source entry reference: `2026-06-26 - Agent Threat Rules`.

### 113. Latitude Agent Monitoring Platform
- Score: 86/100
- Repo URL: https://github.com/latitude-dev/latitude-llm
- Feature/ability: Open-source AI agent monitoring platform that groups failed traces into issues, supports human-aligned evals, and captures multi-turn traces.
- Why Thomas should adopt it: Thomas needs to convert worker trace failures into actionable issues instead of accumulating logs.
- Likely Thomas integration surface: Failed-run issue grouping, human judgment evals, trace-to-workboard problem records, drift tracking, and portal monitoring.
- Risk/effort: Medium-high; issue grouping and human evals need clear local data handling and signal thresholds.
- Next implementation task shape: Design a Thomas failed-run grouping record that links trace, suspected cause, and workboard follow-up.
- Source entry reference: `2026-06-26 - Latitude agent monitoring platform`.

### 114. Bifrost AI Gateway
- Score: 86/100
- Repo URL: https://github.com/maximhq/bifrost
- Feature/ability: High-performance AI gateway with unified provider access, automatic failover, load balancing, semantic caching, governance, guardrails, and observability.
- Why Thomas should adopt it: Long-running Thomas worker swarms need resilient provider routing so tasks are not brittle when a provider is slow, down, too expensive, or rate-limited.
- Likely Thomas integration surface: Provider gateway benchmark, failover policy, semantic cache evaluation, model routing controls, worker availability telemetry, and request governance.
- Risk/effort: Medium-high effort and medium risk; performance and failover value is clear, but semantic caching and provider abstraction need careful safety boundaries for coding-agent work.
- Next implementation task shape: Create a provider-failover benchmark plan for Thomas model calls, including timeout, retry, fallback-model, cost, and semantic-cache safety criteria.
- Source entry reference: `2026-06-26 - Bifrost AI gateway`.

### 115. Envoy AI Gateway
- Score: 86/100
- Repo URL: https://github.com/envoyproxy/ai-gateway
- Feature/ability: Envoy Gateway extension for unified access to generative AI services, focused on traffic management and AI service governance.
- Why Thomas should adopt it: Thomas can learn how cloud-native gateways expose AI traffic policy, routing, rate controls, and observability without baking those decisions into worker code.
- Likely Thomas integration surface: Gateway architecture comparison, Kubernetes deployment pattern, rate-limit policy, request metadata propagation, provider failover, and observability hooks.
- Risk/effort: Medium-high effort and medium risk; strong infrastructure reference, but likely too heavy as a near-term Thomas dependency unless Thomas moves toward cloud-native gateway deployment.
- Next implementation task shape: Extract a gateway-control checklist from Envoy AI Gateway covering route rules, provider abstraction, rate limits, auth, telemetry, and policy attachment points.
- Source entry reference: `2026-06-26 - Envoy AI Gateway`.

### 116. Salesforce MCP-Universe
- Score: 86/100
- Repo URL: https://github.com/SalesforceAIResearch/MCP-Universe
- Feature/ability: Framework for reinforcement-learning training, benchmarking, and developing AI agents for general tool use across MCP-style environments.
- Why Thomas should adopt it: Thomas should track whether tool-use policies improve over time and whether agents can generalize across tools, servers, and task domains.
- Likely Thomas integration surface: MCP environment harness, general tool-use benchmark, RL/eval data format comparison, tool policy scoring, agent training research, and policy improvement reports.
- Risk/effort: Medium-high effort and medium risk; valuable research surface, but training/RL workflows may be beyond near-term Thomas implementation unless reduced to evaluation adapters first.
- Next implementation task shape: Compare MCP-Universe task/env formats against Thomas workboard tasks and extract a minimal portable tool-use trace format for later regression scoring.
- Source entry reference: `2026-06-26 - Salesforce MCP-Universe`.

### 117. MCP Server Fuzzer
- Score: 86/100
- Repo URL: https://github.com/Agent-Hellboy/mcp-server-fuzzer
- Feature/ability: Fuzzer for testing MCP server tools, schemas, and robustness against unexpected inputs.
- Why Thomas should adopt it: Thomas should fuzz MCP/tool contracts before giving autonomous workers access to fragile or unsafe tool servers, especially when schemas are third-party or evolving.
- Likely Thomas integration surface: MCP contract fuzzing, tool schema robustness tests, server onboarding gate, CI fuzz fixtures, security regression artifacts, and tool trust scoring.
- Risk/effort: Medium effort and medium risk; the idea is directly useful, but fuzzing needs tight resource limits and safe targets to avoid noisy or destructive tests.
- Next implementation task shape: Build a non-destructive Thomas MCP fuzz profile for read-only tools, with schema mutation, invalid argument checks, timeout handling, and failure classification.
- Source entry reference: `2026-06-26 - MCP server fuzzer`.

### 118. IBM CLEAR
- Score: 86/100
- Repo URL: https://github.com/IBM/CLEAR
- Feature/ability: Comprehensive LLM error analysis and reporting with automated LLM-as-judge evaluation, recurring error-pattern discovery, and interactive dashboards.
- Why Thomas should adopt it: Thomas should cluster repeated worker failures by pattern and severity so the workboard gets prioritized defects instead of raw logs.
- Likely Thomas integration surface: Failure-cluster dashboard, trace-to-error-pattern pipeline, evaluator summaries, severity scoring, workboard issue generation, and recurring regression reports.
- Risk/effort: Medium effort and medium risk; failure clustering is valuable, but dashboard adoption should wait until Thomas has stable trace/failure schemas.
- Next implementation task shape: Create a failure-cluster schema for Thomas eval results with fields for root cause, severity, recurrence count, affected worker type, and suggested issue.
- Source entry reference: `2026-06-26 - IBM CLEAR`.

### 119. Trusted Agent Protocol
- Score: 86/100
- Repo URL: https://github.com/visa/trusted-agent-protocol
- Feature/ability: Protocol work for establishing trust, identity, and verification between agents and services.
- Why Thomas should adopt it: Thomas needs a trust story for agent-to-tool and agent-to-agent interactions that goes beyond local thread names and implicit authority.
- Likely Thomas integration surface: Agent identity, trust labels, tool access policy, signed agent metadata, MCP/A2A trust comparison, portal trust indicators, and worker permission UX.
- Risk/effort: Medium-high effort and medium risk; exact integration depends on maturity and ecosystem uptake, so Thomas should use it as a model while keeping internal trust primitives simple.
- Next implementation task shape: Define Thomas agent identity and trust metadata fields for agent name, origin, capability scope, signing key, delegated task, and permitted tools.
- Source entry reference: `2026-06-26 - Trusted Agent Protocol`.

### 120. Microsoft Identity-SPIFFE
- Score: 86/100
- Repo URL: https://github.com/microsoft/identity-spiffe
- Feature/ability: Prototype for sidecar-enforced agent-to-agent authorization using Microsoft Entra Agent Identity, SPIFFE/SPIRE workload identity, and cross-cloud federation.
- Why Thomas should adopt it: The sidecar authorization pattern maps closely to Thomas worker-to-worker and worker-to-tool trust boundaries without pretending local agent names are security identities.
- Likely Thomas integration surface: Agent identity sidecar, workload identity federation, A2A trust policy, sidecar authorization checks, and portal trust indicators.
- Risk/effort: High; appears prototype-oriented and cloud-identity-heavy, so Thomas should borrow the boundary pattern before any dependency.
- Next implementation task shape: Sketch a Thomas sidecar authorization flow for one A2A or MCP tool call and identify the minimal identity metadata needed.
- Source entry reference: `2026-06-26 - Microsoft identity-spiffe`.

### 121. MCP OAuth Proxy
- Score: 86/100
- Repo URL: https://github.com/obot-platform/mcp-oauth-proxy
- Feature/ability: OAuth proxy pattern for securing MCP servers and brokering authenticated tool access.
- Why Thomas should adopt it: Thomas needs a reusable authorization layer between workers and MCP servers so every tool server does not invent a different trust model.
- Likely Thomas integration surface: MCP auth proxy, tool-server gateway, token exchange, access policy enforcement, and audit logging.
- Risk/effort: Medium; narrow enough to prototype, but must fit Thomas credential vaulting and approval surfaces.
- Next implementation task shape: Prototype one MCP server behind an OAuth proxy with scoped token metadata and deny/allow audit records.
- Source entry reference: `2026-06-26 - MCP OAuth proxy`.

### 122. Sigbit MCP Auth Proxy For Client-Compatible OAuth
- Score: 86/100
- Repo URL: https://github.com/sigbit/mcp-auth-proxy
- Feature/ability: Drop-in OAuth 2.1/OIDC gateway for MCP servers with multiple IdPs, user matching rules, local-to-HTTP transport conversion, and cross-client compatibility testing.
- Why Thomas should adopt it: Client quirks are a practical risk for any Thomas tool gateway; compatibility across Claude, ChatGPT, Copilot, Cursor, and local MCP tools is directly relevant.
- Likely Thomas integration surface: MCP gateway compatibility matrix, auth middleware, user allowlist policy, and local tool publication.
- Risk/effort: Medium; useful and well-scoped, but Thomas should validate how its local-first flows map to proxy-mediated HTTP transport.
- Next implementation task shape: Create a compatibility checklist for Thomas MCP auth using one local tool and two client styles.
- Source entry reference: `2026-06-26 - Sigbit MCP Auth Proxy for client-compatible OAuth`.

### 123. LibreChat Self-Hosted Agent And MCP Portal
- Score: 86/100
- Repo URL: https://github.com/danny-avila/LibreChat
- Feature/ability: Self-hosted multi-provider chat/agent platform with agents, MCP, skills, artifacts, message search, code interpreter, OpenAPI actions, secure multi-user auth, presets, and model switching.
- Why Thomas should adopt it: Thomas's portal can learn from LibreChat's mature handling of agents, skills, model routing, auth, artifacts, and conversation search as one product surface.
- Likely Thomas integration surface: Portal UX, model/provider switching, skill/MCP integration, artifacts, auth/session design, and searchable worker transcripts.
- Risk/effort: Medium-high; mature broad app, but Thomas should mine patterns rather than adopt the platform wholesale.
- Next implementation task shape: Compare LibreChat's agent/MCP/artifact surfaces with Thomas portal needs and identify three transferable UI or data-model patterns.
- Source entry reference: `2026-06-26 - LibreChat self-hosted agent and MCP portal`.

### 124. Agent VCR Editable Execution Replay
- Score: 86/100
- Repo URL: https://github.com/ixchio/agent-vcr
- Feature/ability: Time-travel debugging for AI agents that can replay, edit, and resume executions without rerunning the whole agent flow.
- Why Thomas should adopt it: Thomas often needs to debug long-running delegated work where repeating the whole run is expensive or destructive; editable replay supports safer fix testing from the failing step.
- Likely Thomas integration surface: Run checkpoint store, partial replay/resume, failure reproduction harness, and worker timeline debugger.
- Risk/effort: Medium-high; high value, but editable replay requires disciplined checkpoint semantics before implementation.
- Next implementation task shape: Identify the minimum checkpoint fields needed to resume one Thomas worker from a failed tool-call boundary.
- Source entry reference: `2026-06-26 - Agent VCR editable execution replay`.

### 125. Repobase AI Repo Index With MCP Server
- Score: 86/100
- Repo URL: https://github.com/fernandoabolafio/repobase
- Feature/ability: AI-oriented Git repository indexing/search with a terminal UI and MCP server for agent-tool integration.
- Why Thomas should adopt it: Thomas workers need fast, explainable codebase context; Repobase is a compact reference for pairing local repo indexing, human inspection, and MCP access.
- Likely Thomas integration surface: Code-search/RAG layer, MCP code context server, terminal inspection UI, and worker context retrieval.
- Risk/effort: Medium; smaller project, but the TUI-plus-MCP shape maps directly to Thomas repo-worker ergonomics.
- Next implementation task shape: Compare Repobase indexing output with Thomas code-search/RAG needs and define a minimal MCP repo-context tool.
- Source entry reference: `2026-06-26 - Repobase AI repo index with MCP server`.

### 126. Nocturne Rollbackable MCP Long-Term Memory
- Score: 86/100
- Repo URL: https://github.com/Dataojitori/nocturne_memory
- Feature/ability: Lightweight MCP long-term memory server with persistent graph-like structured memory, SQLite/PostgreSQL support, visualization, and rollbackable memory behavior.
- Why Thomas should adopt it: Thomas needs memory that can be inspected and safely corrected when agents write stale or wrong project state.
- Likely Thomas integration surface: MCP memory server, memory rollback UI, graph-like project memory, model/session-spanning recall, and memory audit tools.
- Risk/effort: Medium; rollback and visualization fit well, but sovereignty/persona framing should be separated from Thomas's pragmatic memory requirements.
- Next implementation task shape: Design a rollbackable memory-write receipt for one Thomas memory update.
- Source entry reference: `2026-06-27 - Nocturne rollbackable MCP long-term memory`.

### 127. AgentOps Agent Observability
- Score: 85/100
- Repo URL: https://github.com/AgentOps-AI/agentops
- Feature/ability: Agent observability SDK for sessions, tool calls, costs, benchmarks, and framework integrations.
- Why Thomas should adopt it: Normalized telemetry helps delegated workers stay inspectable.
- Likely Thomas integration surface: Delegation event stream, session logs, run inspector UI, and testing metrics.
- Risk/effort: Medium; avoid binding core trace format too early.
- Next implementation task shape: Compare AgentOps event fields with Thomas delegation events.
- Source entry reference: `2026-06-26 - AgentOps agent observability`.

### 128. AgentDebug Failure Taxonomy and Recovery
- Score: 85/100
- Repo URL: https://github.com/ulab-uiuc/AgentDebug
- Feature/ability: Framework for detecting and recovering from LLM agent failures with taxonomy across memory, reflection, planning, action, and system errors.
- Why Thomas should adopt it: Thomas workers will fail in recurring ways; structured failure labels can turn post-run summaries into actionable fixes.
- Likely Thomas integration surface: Worker trace analyzer, failure classification in run logs, reviewer/coordinator diagnostics, and self-improvement backlog creation.
- Risk/effort: Medium; taxonomy must be kept practical and tied to observed Thomas traces.
- Next implementation task shape: Add a failure-classification field to one Thomas worker run summary format.
- Source entry reference: `2026-06-26 - AgentDebug failure taxonomy and recovery`.

### 129. Claude Context Semantic Code-Search MCP
- Score: 85/100
- Repo URL: https://github.com/zilliztech/claude-context
- Feature/ability: MCP plugin for semantic code search over large repositories.
- Why Thomas should adopt it: Thomas workers waste tokens rediscovering seams; semantic code search could improve focused edits and reduce repeated exploration.
- Likely Thomas integration surface: Code-search MCP server, worker bootstrap context, repo-aware search tools, and Bible drift investigations.
- Risk/effort: Medium; semantic hits must be verified against live code and not override Bible trust rules.
- Next implementation task shape: Compare semantic code-search results against `rg` for one Thomas feature-investigation task.
- Source entry reference: `2026-06-26 - Claude Context semantic code-search MCP`.

### 130. Agent Client Protocol Schema and SDKs
- Score: 85/100
- Repo URL: https://github.com/agentclientprotocol/agent-client-protocol
- Feature/ability: Standard protocol/schema for agent sessions, prompts, cancellation, tool calls, and permission messages.
- Why Thomas should adopt it: Thomas needs visible, provider-independent sessions across Codex, Gemini, Claude, OpenCode, and OpenClaw-like agents.
- Likely Thomas integration surface: Thomas portal agent protocol, worker session API, permission prompts, and multi-provider adapter layer.
- Risk/effort: Medium-high; protocol alignment could shape core portal APIs.
- Next implementation task shape: Map Thomas worker session events to ACP session and permission message types.
- Source entry reference: `2026-06-26 - Agent Client Protocol schema and SDKs`.

### 131. Browser MCP Browser Automation Server
- Score: 85/100
- Repo URL: https://github.com/BrowserMCP/mcp
- Feature/ability: MCP server plus Chrome extension for browser automation through MCP-compatible clients.
- Why Thomas should adopt it: Thomas browser workers need controlled access to a real browser through a standard tool interface.
- Likely Thomas integration surface: Browser MCP adapter, web research worker, browser permission model, and visual verification workflows.
- Risk/effort: Medium-high; browser permissions and evidence capture must be explicit.
- Next implementation task shape: Compare Browser MCP's action model against Thomas browser tool contracts.
- Source entry reference: `2026-06-26 - Browser MCP browser automation server`.

### 132. AgentReplay Local Desktop Evals And Memory
- Score: 85/100
- Repo URL: https://github.com/agentreplay/agentreplay
- Feature/ability: Local-first desktop app for agent observability, persistent memory, trace capture, and evals.
- Why Thomas should adopt it: Local trace browsing and memory fit Thomas's need to keep sensitive repo evidence on the user's machine.
- Likely Thomas integration surface: Local run inspector, worker memory store, desktop/portal observability, and eval artifact viewer.
- Risk/effort: Medium; strongest as a UX and storage reference rather than a direct runtime dependency.
- Next implementation task shape: Mock a local run-inspector view that links a worker trace, memory facts, and eval result.
- Source entry reference: `2026-06-26 - AgentReplay local desktop evals and memory`.

### 133. Agentic Contract Policy DSL
- Score: 85/100
- Repo URL: https://github.com/agentralabs/agentic-contract
- Feature/ability: Policy engine for AI agents with enforceable rules, risk limits, approval gates, obligation tracking, violation detection, and an MCP server.
- Why Thomas should adopt it: A contract DSL could express risk limits and approval obligations consistently across Thomas workers and tools.
- Likely Thomas integration surface: Policy-as-code layer, workboard claim constraints, tool approval gates, commit/push safety checks, and violation audit logs.
- Risk/effort: Medium-high; DSL maturity and interoperability must be proven before leaning on it for enforcement.
- Next implementation task shape: Write three Thomas policy obligations as plain-language contracts before evaluating DSL fit.
- Source entry reference: `2026-06-26 - Agentic Contract policy DSL`.

### 134. LangWatch Evaluations And Agent Testing
- Score: 85/100
- Repo URL: https://github.com/langwatch/langwatch
- Feature/ability: Open-source platform for LLM evaluations and AI agent testing.
- Why Thomas should adopt it: Implemented Thomas agent features need regression tests for behavior, traces, prompts, and tools, not just unit tests.
- Likely Thomas integration surface: Agent eval dashboard, run traces, regression datasets, prompt/tool behavior checks, and CI evaluation gates.
- Risk/effort: Medium-high; eval platform adoption requires stable datasets and careful signal-to-noise control.
- Next implementation task shape: Define one Thomas agent-behavior regression dataset and compare LangWatch-style reporting needs.
- Source entry reference: `2026-06-26 - LangWatch evaluations and agent testing`.

### 135. Memori Agent-Native Memory Infrastructure
- Score: 85/100
- Repo URL: https://github.com/memorilabs/memori
- Feature/ability: LLM-agnostic memory infrastructure that turns agent execution and conversations into structured persistent state for production systems.
- Why Thomas should adopt it: Thomas needs memory from actual worker execution, not only chat snippets, and Memori is a concrete production-oriented reference.
- Likely Thomas integration surface: Worker run memory, structured conversation extraction, persistent state store, and production memory APIs.
- Risk/effort: Medium-high; Thomas must compare its model against Mem0, Graphiti, and existing local memory before selecting an approach.
- Next implementation task shape: Compare Memori's execution-memory model against one Thomas worker run summary and workboard entry.
- Source entry reference: `2026-06-26 - Memori agent-native memory infrastructure`.

### 136. OpenSRE AI SRE Framework
- Score: 85/100
- Repo URL: https://github.com/Tracer-Cloud/opensre
- Feature/ability: Open-source AI SRE agents that investigate production incidents using logs, metrics, traces, runbooks, and memory.
- Why Thomas should adopt it: Thomas will need operational agents for CI, local app, and production incidents with evidence gathering and incident-resolution loops.
- Likely Thomas integration surface: Incident triage worker, observability ingestion, runbook retrieval, root-cause analysis, remediation proposals, and workboard incident memory.
- Risk/effort: Medium-high; production remediation must be gated and evidence-driven.
- Next implementation task shape: Define a Thomas incident worker evidence pack for logs, failing checks, candidate cause, and proposed remediation.
- Source entry reference: `2026-06-26 - OpenSRE AI SRE framework`.

### 137. Sourcebot Codebase Intelligence
- Score: 85/100
- Repo URL: https://github.com/sourcebot-dev/sourcebot
- Feature/ability: Self-hosted code search and codebase understanding platform for humans and agents.
- Why Thomas should adopt it: Thomas needs shared inspectable code intelligence that agents and the user can both verify, not hidden per-thread search state.
- Likely Thomas integration surface: Shared code search service, portal code navigation, agent context retrieval, repo-wide symbol search, and evidence links in worker reports.
- Risk/effort: Medium-high; hosting and indexing must stay local and align with Thomas privacy expectations.
- Next implementation task shape: Evaluate Sourcebot as a portal-visible code search backend for one Thomas repo snapshot.
- Source entry reference: `2026-06-26 - Sourcebot codebase intelligence`.

### 138. VisualWebArena Visual Web-Agent Benchmark
- Score: 85/100
- Repo URL: https://github.com/web-arena-x/visualwebarena
- Feature/ability: Visual web-agent benchmark for agents that use screenshots and web interaction to complete tasks.
- Why Thomas should adopt it: Browser automation with screenshots is central to user-facing workflows, and Thomas needs visual grounding and web interaction reliability tests.
- Likely Thomas integration surface: Browser-agent eval harness, visual task fixtures, screenshot-action scoring, and portal automation regression.
- Risk/effort: Medium-high; benchmark environments and scoring must be adapted before use in routine Thomas CI.
- Next implementation task shape: Pick one visual web task pattern and translate it into a Thomas browser-worker regression fixture.
- Source entry reference: `2026-06-26 - VisualWebArena visual web-agent benchmark`.

### 139. TraceAI OpenTelemetry Tracing Framework
- Score: 85/100
- Repo URL: https://github.com/future-agi/traceai
- Feature/ability: OpenTelemetry-based tracing framework for LLM calls, prompts, retrieval, and agent decisions.
- Why Thomas should adopt it: Thomas needs trace semantics that include agent decisions and retrieval/tool steps, not only model latency.
- Likely Thomas integration surface: Trace schema comparison, OTel export, agent-decision spans, retrieval/tool trace capture, and backend-neutral observability.
- Risk/effort: Medium; fit depends on whether trace semantics cover Thomas worker decisions and tool gates cleanly.
- Next implementation task shape: Compare traceAI agent-decision spans against one Thomas delegated worker run.
- Source entry reference: `2026-06-26 - traceAI OpenTelemetry tracing framework`.

### 140. LMCache Reusable KV Cache Layer
- Score: 85/100
- Repo URL: https://github.com/LMCache/LMCache
- Feature/ability: KV cache management layer for LLM inference that persists, reuses, monitors, and transforms caches across serving engines.
- Why Thomas should adopt it: Long-context agentic and multi-turn worker runs are expensive; reusable KV cache infrastructure could reduce time-to-first-token and improve throughput for local or self-hosted models.
- Likely Thomas integration surface: Local inference acceleration, long-context worker cache, vLLM/SGLang experiments, cache observability, multi-worker cache sharing, and local model scheduler research.
- Risk/effort: High effort and medium risk; value depends on Thomas running local/self-hosted inference, and cache reuse must not cross unsafe task or repository boundaries.
- Next implementation task shape: Create a local-inference acceleration research note that defines which Thomas worker contexts could safely reuse KV cache and what isolation metadata would be required.
- Source entry reference: `2026-06-26 - LMCache reusable KV cache layer`.

### 141. AgentBench Function-Calling Agent Benchmark
- Score: 85/100
- Repo URL: https://github.com/THUDM/AgentBench
- Feature/ability: Comprehensive benchmark for LLM agents, including function-calling tasks and containerized environments such as OS, database, knowledge graph, and webshop tasks.
- Why Thomas should adopt it: Thomas needs cross-domain agent capability signals beyond coding tasks, especially around OS/database operations and multi-turn tool use.
- Likely Thomas integration surface: Agent capability baseline, containerized task harness comparison, function-call scoring, environment adapters, and benchmark-driven model routing.
- Risk/effort: Medium effort and medium risk; mature benchmark value is high, but Thomas should adopt only task patterns that reflect real operator workflows.
- Next implementation task shape: Map AgentBench task categories to Thomas worker capabilities and identify two environment adapters that could become local regression fixtures.
- Source entry reference: `2026-06-26 - AgentBench function-calling agent benchmark`.

### 142. Stagehand Browser Automation Framework
- Score: 85/100
- Repo URL: https://github.com/browserbase/stagehand
- Feature/ability: Browser automation framework that combines Playwright-style actions with AI-assisted extraction and action planning.
- Why Thomas should adopt it: Thomas browser workers need deterministic browser primitives with AI assistance layered on top, plus traceable actions that can be replayed and tested.
- Likely Thomas integration surface: Browser-tool adapter, action replay fixtures, extraction validation, Playwright trace integration, browser-agent regression tests, and UI evidence capture.
- Risk/effort: Medium effort and medium risk; practical tooling value is high, but Thomas should keep deterministic Playwright actions as the core and treat AI action planning as a bounded assist.
- Next implementation task shape: Prototype a Thomas browser-task fixture that records Stagehand-like action/extract steps alongside Playwright traces and validates extracted outputs against assertions.
- Source entry reference: `2026-06-26 - Stagehand browser automation framework`.

### 143. SAP Agent-Quality-Inspect
- Score: 85/100
- Repo URL: https://github.com/SAP/agent-quality-inspect
- Feature/ability: Evaluation package for benchmarking agentic AIs across sources/frameworks with statistical result comparison, metrics, and error analysis.
- Why Thomas should adopt it: Thomas needs framework-neutral quality inspection for agents and worker configurations, not one-off scores tied to a single provider.
- Likely Thomas integration surface: Agent quality benchmark runner, cross-framework comparison, statistical reports, error-analysis ingestion, portal quality dashboards, and model/agent comparison reports.
- Risk/effort: Medium effort and medium risk; direct value is high, but Thomas should first define its canonical task sets and score fields.
- Next implementation task shape: Compare its metric model with Thomas's ranking/eval needs and draft a quality report format for agent, model, task class, score, confidence, and failure classes.
- Source entry reference: `2026-06-26 - SAP agent-quality-inspect`.

### 144. Mandate Runtime Authority Enforcement
- Score: 85/100
- Repo URL: https://github.com/kashaf12/mandate
- Feature/ability: Runtime enforcement layer for AI agent authority that intercepts LLM and tool calls, evaluates them against policies, and blocks unauthorized actions.
- Why Thomas should adopt it: Thomas workers make repo, filesystem, and coordination changes where authority must be mechanically enforceable, not inferred from prompts or thread labels.
- Likely Thomas integration surface: Workboard claim scope enforcement, tool-call authorization middleware, blocked-action receipts, and policy simulation tests.
- Risk/effort: Medium-high; strong fit for authority control, but maturity and compatibility with Thomas guardrails need inspection.
- Next implementation task shape: Prototype an authority check that blocks a worker action outside its claim scope and records a blocked-action receipt.
- Source entry reference: `2026-06-26 - Mandate runtime authority enforcement`.

### 145. Parley Recovery-First Coordination State
- Score: 85/100
- Repo URL: https://github.com/nkuhanas/Parley
- Feature/ability: Durable coordination state for long-running agents, including identity, obligations, plans, artifacts, effects, guidance, recovery, and plan lifecycle tools.
- Why Thomas should adopt it: Thomas loses leverage when worker continuity depends on chat history alone; Parley's obligations/effects model is relevant to resumable tasks, claim recovery, and post-crash auditability.
- Likely Thomas integration surface: Worker state store, claim recovery, obligation tracking, artifact/effect ledger, and resume/replay tooling.
- Risk/effort: Medium; early project, but the recovery-first model targets a concrete Thomas gap.
- Next implementation task shape: Map obligation, effect, artifact, and guidance fields onto one Thomas workboard claim lifecycle.
- Source entry reference: `2026-06-26 - Parley recovery-first coordination state`.

### 146. EverOS Portable User-Owned Memory Layer
- Score: 85/100
- Repo URL: https://github.com/EverMind-AI/EverOS
- Feature/ability: Portable local-first, Markdown-native, user-owned, self-evolving memory layer across agents, apps, tools, and workflows.
- Why Thomas should adopt it: Thomas needs user-owned continuity that survives individual agents and sessions; this is a strong product-direction reference for portable memory infrastructure.
- Likely Thomas integration surface: Local user memory vault, cross-agent memory sync, Markdown-native memory format, self-evolving memory workflows, and privacy controls.
- Risk/effort: Medium-high; product fit is strong, but durability and privacy guarantees need live review.
- Next implementation task shape: Draft a Thomas user-owned memory vault model with portability, deletion, and inspection requirements.
- Source entry reference: `2026-06-26 - EverOS portable user-owned memory layer`.

### 147. Reflect Memory User-Authored Privacy-First Memory
- Score: 85/100
- Repo URL: https://github.com/van-reflect/Reflect-Memory
- Feature/ability: Vendor-neutral memory layer where memories are explicitly user-authored, structured, editable, and deletable, exposed via TypeScript SDK, MCP server, REST API, and n8n nodes.
- Why Thomas should adopt it: Thomas memory should not silently accumulate sensitive or wrong facts; explicit editable/deletable memory is a strong privacy and UX reference.
- Likely Thomas integration surface: User memory editor, MCP memory adapter, REST memory API, deletion/export controls, and privacy-first memory policy.
- Risk/effort: Medium; small repo, but policy fit is strong for user-controlled memory.
- Next implementation task shape: Add memory CRUD, deletion, and export requirements to Thomas memory design notes.
- Source entry reference: `2026-06-27 - Reflect Memory user-authored privacy-first memory`.

### 148. MCP-Agent MCP-Native Agent Framework
- Score: 84/100
- Repo URL: https://github.com/lastmile-ai/mcp-agent
- Feature/ability: Composable agent framework built around MCP servers.
- Why Thomas should adopt it: Standardizes tool access while routing specialists through common capabilities.
- Likely Thomas integration surface: Tool registry, MCP bridge, delegation planner, and worker capability discovery.
- Risk/effort: Medium; define a narrow MCP boundary first.
- Next implementation task shape: Map Thomas tool registry concepts to MCP capability discovery.
- Source entry reference: `2026-06-26 - mcp-agent MCP-native agent framework`.

### 149. Official MCP Reference Servers
- Score: 84/100
- Repo URL: https://github.com/modelcontextprotocol/servers
- Feature/ability: Reference MCP server implementations for exposing tools to agents.
- Why Thomas should adopt it: Thomas needs stable examples for repo, browser, memory, GitHub, and internal tool exposure.
- Likely Thomas integration surface: Thomas MCP server design, adapter examples, capability discovery, and sandboxed tool contracts.
- Risk/effort: Medium; examples are not production security policy.
- Next implementation task shape: Compare one Thomas tool adapter against official MCP server patterns.
- Source entry reference: `2026-06-26 - Official MCP reference servers`.

### 150. PR-Agent Automated Pull Request Reviewer
- Score: 84/100
- Repo URL: https://github.com/The-PR-Agent/pr-agent
- Feature/ability: AI PR reviewer that summarizes changes and generates review comments across git hosts.
- Why Thomas should adopt it: Thomas needs reviewer/coordinator coverage for worker changes.
- Likely Thomas integration surface: Workboard reviewer role, PR/diff summarizer, code review checklist generation, and GitHub integration.
- Risk/effort: Medium; review output must stay evidence-based and avoid noisy comments.
- Next implementation task shape: Build a Thomas diff-summary/review checklist format from one local diff.
- Source entry reference: `2026-06-26 - PR-Agent automated pull request reviewer`.

### 151. CrewAI Role-Based Crews and Flows
- Score: 84/100
- Repo URL: https://github.com/crewAIInc/crewAI
- Feature/ability: Role-playing agents, crews, flows, task dependencies, memory, guardrails, and human review patterns.
- Why Thomas should adopt it: Thomas already uses worker/reviewer/coordinator roles; these should become explicit templates.
- Likely Thomas integration surface: Workboard claims, delegation templates, review/coordinator roles, and automation recipes.
- Risk/effort: Medium; avoid duplicating workboard semantics.
- Next implementation task shape: Create a Thomas role template spec.
- Source entry reference: `2026-06-26 - CrewAI role-based crews and flows`.

### 152. HAL Harness Reproducible Agent Leaderboard
- Score: 84/100
- Repo URL: https://github.com/princeton-pli/hal-harness
- Feature/ability: Evaluation harness with unified CLI, plugins, logging, cost tracking, and leaderboard publishing.
- Why Thomas should adopt it: Thomas needs repeatable quality and cost evidence for agent performance.
- Likely Thomas integration surface: Evaluation CLI, cost-aware logs, benchmark plugins, and dashboards.
- Risk/effort: Medium; leaderboard comes after local trustworthy evals.
- Next implementation task shape: Draft a benchmark plugin shape for Thomas.
- Source entry reference: `2026-06-26 - HAL Harness reproducible agent leaderboard`.

### 153. PandaProbe Agent Engineering Platform
- Score: 84/100
- Repo URL: https://github.com/chirpz-ai/pandaprobe
- Feature/ability: Agent engineering platform for tracing, evaluating, monitoring, and debugging agents across frameworks.
- Why Thomas should adopt it: Thomas needs a unified view of traces, evals, and metrics across worker types.
- Likely Thomas integration surface: Worker telemetry dashboard, eval result store, trace collection, and agent debugging UI.
- Risk/effort: Medium; overlaps with Langfuse, AgentOps, and AgentPulse, so it should inform the schema before becoming a dependency.
- Next implementation task shape: Compare PandaProbe's trace/eval/metric split against Thomas's ranking of observability options.
- Source entry reference: `2026-06-26 - PandaProbe agent engineering platform`.

### 154. Open Prompt Injection Toolkit
- Score: 84/100
- Repo URL: https://github.com/liu00222/Open-Prompt-Injection
- Feature/ability: Toolkit for implementing, evaluating, and extending prompt-injection attacks and defenses.
- Why Thomas should adopt it: Thomas agents read untrusted web, issue, and repository content; injection defense needs explicit tests.
- Likely Thomas integration surface: Security eval suite, browser/web research safeguards, tool-call policy tests, and prompt-injection regression corpus.
- Risk/effort: Medium; attack corpus should be filtered into realistic Thomas scenarios.
- Next implementation task shape: Build a small Thomas prompt-injection corpus for browser/repo research workers.
- Source entry reference: `2026-06-26 - Open Prompt Injection toolkit`.

### 155. Codebase-Memory-MCP Structural Knowledge Graph
- Score: 84/100
- Repo URL: https://github.com/DeusData/codebase-memory-mcp
- Feature/ability: MCP server indexing functions, classes, call chains, routes, and cross-service links into a persistent graph.
- Why Thomas should adopt it: Thomas workers should ask structural repo questions directly instead of repeatedly scanning files.
- Likely Thomas integration surface: Local code intelligence MCP, worker bootstrap, architecture queries, and refactor blast-radius analysis.
- Risk/effort: Medium-high; graph freshness and false authority need guardrails.
- Next implementation task shape: Compare structural graph output against Bible/live-code trust rules for one subsystem.
- Source entry reference: `2026-06-26 - codebase-memory-mcp structural knowledge graph`.

### 156. Zeroshot Autonomous Engineering Team
- Score: 84/100
- Repo URL: https://github.com/the-open-engine/zeroshot
- Feature/ability: Multi-agent coding workflow for implementation, review, test, and verification.
- Why Thomas should adopt it: It closely matches Thomas's visible worker plus independent reviewer direction.
- Likely Thomas integration surface: Native engineering worker loop, reviewer gate, issue-to-patch workflow, and verification policy.
- Risk/effort: Medium; preserve Thomas workboard and Bible guardrails.
- Next implementation task shape: Compare Zeroshot's implement-review-test loop against Thomas visible worker delegation.
- Source entry reference: `2026-06-26 - Zeroshot autonomous engineering team`.

### 157. OSU AgentSafety GUI Agent Benchmark
- Score: 84/100
- Repo URL: https://github.com/OSU-NLP-Group/AgentSafety
- Feature/ability: Benchmark suite for GUI-agent safety across harmful behavior, prompt injection, and desktop app misuse.
- Why Thomas should adopt it: Desktop automation must have safety evals before agents can click through email, browsers, editors, and files.
- Likely Thomas integration surface: GUI-agent safety tests, desktop permission policy, harmful-task red team, and release gates for computer-use features.
- Risk/effort: Medium-high; benchmark integration should precede broad GUI autonomy.
- Next implementation task shape: Define Thomas GUI-agent safety scenarios from AgentSafety categories.
- Source entry reference: `2026-06-26 - OSU AgentSafety GUI agent benchmark`.

### 158. Lightpanda AI-Native Browser
- Score: 84/100
- Repo URL: https://github.com/lightpanda-io/browser
- Feature/ability: Headless browser built for AI agents and automation with native agent mode for navigation, clicks, forms, and structured extraction.
- Why Thomas should adopt it: Thomas browser workers can benefit from agent-first browser ergonomics and faster structured web tasks.
- Likely Thomas integration surface: Browser tool runtime, web research worker, structured extraction, and lightweight browser sandbox.
- Risk/effort: Medium-high; browser compatibility and evidence capture need validation.
- Next implementation task shape: Compare Lightpanda agent-mode actions with Thomas browser tool requirements.
- Source entry reference: `2026-06-26 - Lightpanda AI-native browser`.

### 159. Neuledge Context Local-First Documentation MCP
- Score: 84/100
- Repo URL: https://github.com/neuledge/context
- Feature/ability: Local-first MCP server backed by a package-documentation registry for searchable library docs.
- Why Thomas should adopt it: Local docs context can reduce hallucinated APIs and repeated browsing while keeping worker research on-machine.
- Likely Thomas integration surface: MCP documentation server, worker bootstrap docs, package-aware code assistance, and offline context cache.
- Risk/effort: Medium; requires package indexing and freshness policy to avoid stale local guidance.
- Next implementation task shape: Pilot a local docs MCP/context cache for one Thomas dependency family.
- Source entry reference: `2026-06-26 - Neuledge Context local-first documentation MCP`.

### 160. Context7 Up-To-Date Code Docs MCP
- Score: 84/100
- Repo URL: https://github.com/upstash/context7
- Feature/ability: MCP/CLI platform for bringing current library documentation and examples into agent prompts and coding workflows.
- Why Thomas should adopt it: Context7 is a widely referenced docs-grounding pattern to compare against local-first documentation approaches.
- Likely Thomas integration surface: Documentation MCP adapter, coding-worker context source, dependency-specific guidance, and prompt grounding.
- Risk/effort: Medium; external docs source improves freshness but needs provenance and caching rules.
- Next implementation task shape: Compare Context7 and local docs MCP behavior on one Thomas coding task with a fast-changing dependency.
- Source entry reference: `2026-06-26 - Context7 up-to-date code docs MCP`.

### 161. AI Agent Checkpoint And Resume
- Score: 84/100
- Repo URL: https://github.com/AxmeAI/ai-agent-checkpoint-and-resume
- Feature/ability: Checkpoint-and-resume primitives for long-running agent tasks so interrupted runs continue from saved state.
- Why Thomas should adopt it: Thomas workers can be interrupted by compaction, tool failures, or machine restarts; durable checkpoints reduce waste and improve auditability.
- Likely Thomas integration surface: Worker run state store, task journal snapshots, queue/resume CLI, and claim recovery metadata.
- Risk/effort: Medium; concept is high-value, but repo maturity needs validation before copying implementation details.
- Next implementation task shape: Specify the minimum resumable state for one Thomas worker heartbeat or workboard task.
- Source entry reference: `2026-06-26 - AI Agent checkpoint and resume`.

### 162. Statewright State-Machine Guardrails
- Score: 84/100
- Repo URL: https://github.com/statewright/statewright
- Feature/ability: State-machine guardrails for AI agents that constrain behavior to explicit allowed transitions.
- Why Thomas should adopt it: Workboard tasks, claims, commits, approvals, and releases already have implicit states that should become enforceable transitions.
- Likely Thomas integration surface: Workboard lifecycle model, claim/release validation, worker step transitions, and approval-state enforcement.
- Risk/effort: Medium; useful guardrail idea, but implementation depth needs review and Thomas may only need the pattern.
- Next implementation task shape: Convert Thomas claim lifecycle into an explicit state-transition table.
- Source entry reference: `2026-06-26 - Statewright state-machine guardrails`.

### 163. Agentic Reliability Framework
- Score: 84/100
- Repo URL: https://github.com/petterjuan/agentic-reliability-framework
- Feature/ability: Reliability intelligence platform for autonomous operations with deterministic safety guarantees and separated decision intelligence versus governed execution.
- Why Thomas should adopt it: Thomas worker autonomy needs reliability contracts for when agents may decide, when execution must be governed, and how failures surface.
- Likely Thomas integration surface: Reliability policy layer, governed-execution boundary, operational risk scoring, and worker failure reporting.
- Risk/effort: Medium-high; concept fits, but implementation maturity and licensing posture need review before reuse.
- Next implementation task shape: Draft a Thomas reliability contract separating agent recommendation, approval, execution, and failure reporting.
- Source entry reference: `2026-06-26 - Agentic Reliability Framework`.

### 164. Mastra TypeScript Agent Framework
- Score: 84/100
- Repo URL: https://github.com/mastra-ai/mastra
- Feature/ability: TypeScript framework for AI agents, workflows, memory, integrations, observability, and deployment-oriented agent applications.
- Why Thomas should adopt it: Mastra is a large active reference for bridging product UI, durable workflows, memory, and agent execution.
- Likely Thomas integration surface: Agent runtime architecture, workflow definitions, memory adapters, observability hooks, and portal-facing agent app patterns.
- Risk/effort: Medium-high; broad framework ideas are useful, but Thomas should avoid a wholesale TypeScript runtime pivot.
- Next implementation task shape: Compare Mastra workflow/memory/observability primitives to Thomas native orchestration components.
- Source entry reference: `2026-06-26 - Mastra TypeScript agent framework`.

### 165. BMAD Method Structured AI Development Agents
- Score: 84/100
- Repo URL: https://github.com/bmad-code-org/BMAD-METHOD
- Feature/ability: Structured agile AI development method with specialized agent personas, scale-adaptive workflows, planning depth controls, and multi-persona collaboration.
- Why Thomas should adopt it: Thomas needs repeatable workflows that scale from quick fixes to larger implementation arcs with clear roles and handoffs.
- Likely Thomas integration surface: Worker role templates, task planning depth selection, workboard workflow presets, multi-agent review flows, and portal-guided execution modes.
- Risk/effort: Medium; useful workflow source, but Thomas should adopt selectively rather than importing a full method.
- Next implementation task shape: Extract three Thomas workflow presets from BMAD-style role/planning patterns.
- Source entry reference: `2026-06-26 - BMAD Method structured AI development agents`.

### 166. MemOS Self-Evolving Memory Operating System
- Score: 84/100
- Repo URL: https://github.com/MemTensor/MemOS
- Feature/ability: Self-evolving memory OS for LLMs and AI agents with persistent memory, hybrid retrieval, cross-task skill reuse, and token-saving claims.
- Why Thomas should adopt it: Thomas will accumulate repeated worker patterns and project facts; MemOS can inform separation of memories, skills, and reusable context.
- Likely Thomas integration surface: Memory operating layer, worker skill reuse, long-running project context, hybrid retrieval, and context-budget control.
- Risk/effort: High; ambitious architecture and self-evolving memory require careful maturity and safety review.
- Next implementation task shape: Define Thomas memory tiers for project facts, worker skills, user preferences, and run-local state.
- Source entry reference: `2026-06-26 - MemOS self-evolving memory operating system`.

### 167. Agent Sandbox Taxonomy
- Score: 84/100
- Repo URL: https://github.com/kajogo777/the-agent-sandbox-taxonomy
- Feature/ability: Open taxonomy and scoring framework for evaluating AI agent sandboxes across defense layers, threat categories, and scoring dimensions.
- Why Thomas should adopt it: Thomas needs comparable sandbox choices for worker execution instead of vague "isolated enough" claims.
- Likely Thomas integration surface: Tool-risk policy, sandbox selection rubric, worker execution profiles, marketplace security checks, and ranker safety criteria.
- Risk/effort: Low-medium; taxonomy can be adopted as a rubric before any runtime change.
- Next implementation task shape: Score Thomas current worker execution modes against the taxonomy and identify missing defense layers.
- Source entry reference: `2026-06-26 - Agent Sandbox Taxonomy`.

### 168. Axon Code Knowledge Graph
- Score: 84/100
- Repo URL: https://github.com/harshkedia177/axon
- Feature/ability: Graph-powered code intelligence engine that indexes codebases into a knowledge graph exposed through MCP tools and a CLI.
- Why Thomas should adopt it: Thomas repo-aware workers need relationships between symbols, files, and call paths without repeatedly reading whole files.
- Likely Thomas integration surface: Code graph indexer, MCP query tools, workboard context bootstrap, and code-review impact analysis.
- Risk/effort: Medium; scale and language coverage need review against Thomas's repo shape.
- Next implementation task shape: Compare Axon query output against one Thomas review-impact question.
- Source entry reference: `2026-06-26 - Axon code knowledge graph`.

### 169. Browser-Use Benchmark
- Score: 84/100
- Repo URL: https://github.com/browser-use/benchmark
- Feature/ability: Browser-use ecosystem benchmark suite for measuring browser-agent task execution.
- Why Thomas should adopt it: Thomas already tracks browser-use; this gives a distinct evaluation surface for browser workers.
- Likely Thomas integration surface: Browser-worker benchmark runner, task success scoring, regression fixtures, and browser-agent comparison matrix.
- Risk/effort: Medium; benchmark dependency and task stability need review.
- Next implementation task shape: Compare browser-use benchmark task format against Thomas browser tool contracts.
- Source entry reference: `2026-06-26 - browser-use benchmark`.

### 170. Panguard AI Agent Security Platform
- Score: 84/100
- Repo URL: https://github.com/panguard-ai/panguard-ai
- Feature/ability: Open-source AI agent security platform for pre-install skill audits, runtime monitoring, and shared threat intelligence.
- Why Thomas should adopt it: Thomas skills/plugins and agent tools need auditing before activation and monitoring after activation.
- Likely Thomas integration surface: Skill audit gate, plugin threat scoring, runtime monitor, shared rule feeds, and portal security dashboard.
- Risk/effort: Medium-high; lifecycle coverage is useful, but ecosystem maturity and rule quality need review.
- Next implementation task shape: Map Thomas skill/plugin install flow to pre-install audit, trust decision, and runtime monitoring states.
- Source entry reference: `2026-06-26 - Panguard AI agent security platform`.

### 171. Dify Agentic Workflow Platform
- Score: 84/100
- Repo URL: https://github.com/langgenius/dify
- Feature/ability: Production-ready platform for developing agentic workflows, applications, tools, and knowledge-connected agents.
- Why Thomas should adopt it: Dify is a large reference for visual workflow authoring, deployment, monitoring, knowledge integrations, and agent app operations.
- Likely Thomas integration surface: Portal workflow builder, agent app lifecycle, knowledge-tool integrations, workflow observability, and no-code/low-code orchestration comparisons.
- Risk/effort: High; Thomas should borrow patterns rather than adopt a full platform.
- Next implementation task shape: Compare Dify's workflow authoring and monitoring surfaces against Thomas portal workflow needs.
- Source entry reference: `2026-06-26 - Dify agentic workflow platform`.

### 172. Shekel LLM Budget Control
- Score: 84/100
- Repo URL: https://github.com/arieradle/shekel
- Feature/ability: Python budget-control library for AI agents with token budgets, usage limits, cost governance, and adapters for OpenAI, Anthropic, LangChain, and LangGraph.
- Why Thomas should adopt it: Thomas needs pre-call budget checks inside agent loops, not only after-the-fact dashboards. Shekel is narrowly aligned with denial-of-wallet protection and run-level cost caps.
- Likely Thomas integration surface: Worker preflight budget guard, LangGraph-style adapter comparison, budget exception handling, denial-of-wallet protection, and run-level usage limits.
- Risk/effort: Low-medium effort and medium risk; small project maturity limits direct dependency confidence, but the enforcement shape is valuable.
- Next implementation task shape: Implement a Thomas-native budget preflight interface inspired by Shekel that can approve, downgrade, or block a model call before tokens are spent.
- Source entry reference: `2026-06-26 - Shekel LLM budget control`.

### 173. Higress AI Gateway
- Score: 84/100
- Repo URL: https://github.com/higress-group/higress
- Feature/ability: AI-native API Gateway with LLM proxying, plugin extensibility, traffic governance, and cloud-native gateway controls.
- Why Thomas should adopt it: Thomas can compare AI gateway plugin models for adding budget, guardrail, observability, and provider policy without changing agent code.
- Likely Thomas integration surface: Gateway plugin architecture, LLM proxy comparison, traffic governance, rate/budget plugins, MCP/tool gateway policy research, and deployment tradeoff notes.
- Risk/effort: Medium-high effort and medium risk; mature gateway capabilities are relevant, but the integration surface may be broader than Thomas needs in the short term.
- Next implementation task shape: Compare Higress plugin extension points against Thomas gateway-policy needs: budget cap, model allowlist, audit event, guardrail block, and fallback routing.
- Source entry reference: `2026-06-26 - Higress AI Gateway`.

### 174. OpenZiti Zero-Trust LLM Gateway
- Score: 84/100
- Repo URL: https://github.com/openziti/llm-gateway
- Feature/ability: OpenAI-compatible gateway for routing to OpenAI, Anthropic, Ollama, vLLM, llama-server, SGLang, and other backends over zero-trust connectivity.
- Why Thomas should adopt it: Thomas may need to route workers to private local inference endpoints without exposing ports or relying on ad hoc VPN setup.
- Likely Thomas integration surface: Private model mesh, zero-trust worker connectivity, local inference gateway, provider routing, secure remote MCP/model access, and self-hosted model deployment.
- Risk/effort: Medium-high effort and medium risk; the differentiated security model is useful, but direct fit depends on whether Thomas prioritizes private distributed model deployments.
- Next implementation task shape: Draft a private-model gateway threat model for Thomas covering worker identity, endpoint exposure, model backend access, audit logs, and revocation.
- Source entry reference: `2026-06-26 - OpenZiti zero-trust LLM gateway`.

### 175. ToolBench Tool-Learning Evaluation
- Score: 84/100
- Repo URL: https://github.com/OpenBMB/ToolBench
- Feature/ability: Open platform for training, serving, and evaluating large language models for tool learning.
- Why Thomas should adopt it: Thomas should evaluate tool selection, tool-call ordering, and API-use reliability as first-class capabilities, not incidental model behavior.
- Likely Thomas integration surface: Tool-call benchmark adapter, tool selection metrics, API trajectory scoring, synthetic tool task generation, and tool-use training data review.
- Risk/effort: Medium effort and medium risk; established benchmark surface is useful, but Thomas must avoid large benchmark ingestion before defining its own tool-call quality metrics.
- Next implementation task shape: Extract ToolBench-style metrics into a Thomas tool-call rubric covering correct tool, correct arguments, minimal calls, error recovery, and final answer quality.
- Source entry reference: `2026-06-26 - ToolBench tool-learning evaluation`.

### 176. OSWorld-V2 Computer-Use Benchmark
- Score: 84/100
- Repo URL: https://github.com/xlang-ai/OSWorld-V2
- Feature/ability: Updated OSWorld benchmark for evaluating multimodal agents on real computer-use tasks.
- Why Thomas should adopt it: Thomas should benchmark desktop/computer-use abilities with task traces and observable state before relying on GUI automation for user-visible workflows.
- Likely Thomas integration surface: Computer-use eval harness, GUI action scoring, screenshot/state replay, worker capability routing, and safety gates for desktop automation.
- Risk/effort: High effort and medium risk; benchmark lineage is strong, but desktop automation is flaky and must be isolated from normal Thomas code and user environments.
- Next implementation task shape: Draft a computer-use evaluation lane for Thomas that runs only in disposable environments and captures screenshot/state/action traces for review.
- Source entry reference: `2026-06-26 - OSWorld-V2 computer-use benchmark`.

### 177. Agent-Native Research Artifact Provenance
- Score: 84/100
- Repo URL: https://github.com/AmberLJC/Agent-Native-Research-Artifact
- Feature/ability: Research artifact showing how agents can generate, organize, and preserve structured artifacts from research workflows.
- Why Thomas should adopt it: Thomas should treat task outputs, traces, notes, decisions, and evidence as durable artifacts that can be replayed, ranked, and converted into workboard items.
- Likely Thomas integration surface: Task artifact provenance, research-run package format, evidence bundles, queue-entry source trails, worker output lineage, and replayable decision records.
- Risk/effort: Medium effort and medium risk; research orientation limits direct adoption, but the provenance model fits Thomas queues and ranked artifacts well.
- Next implementation task shape: Draft a Thomas artifact bundle schema that links raw queue source, ranked recommendation, scoring rationale, evidence files, and later implementation task.
- Source entry reference: `2026-06-26 - Agent-native research artifact provenance`.

### 178. OpenFGA MCP Server
- Score: 84/100
- Repo URL: https://github.com/evansims/openfga-mcp
- Feature/ability: MCP server that lets AI agents design, query, and manage OpenFGA/Auth0 FGA authorization models.
- Why Thomas should adopt it: Thomas reviewer agents could use an MCP authorization tool to reason about access-control changes and simulate permission decisions before accepting them.
- Likely Thomas integration surface: MCP authorization tool, policy-model review, access-control simulation, permission-change audit, and agent-readable auth explanations.
- Risk/effort: Medium; direct MCP fit, but it depends on selecting or testing OpenFGA as a policy backend first.
- Next implementation task shape: Add a proof-of-concept policy-review task shape that asks a reviewer agent to query an FGA model through MCP.
- Source entry reference: `2026-06-26 - OpenFGA MCP server`.

### 179. Generative Agent Protocol
- Score: 84/100
- Repo URL: https://github.com/mikekelly/gap
- Feature/ability: Generative Agent Protocol reference for delegated access across agents, users, and resources with explicit authorization.
- Why Thomas should adopt it: Thomas workers need a clear delegated-access model when acting for a user across tools, repos, credentials, and external services.
- Likely Thomas integration surface: Agent credential exchange, delegated authorization model, tool access grants, prompt-time policy explanations, and A2A/MCP protocol comparison.
- Risk/effort: Medium-high; strong conceptual fit, but ecosystem adoption and runtime maturity need verification before implementation.
- Next implementation task shape: Compare GAP's delegated-access vocabulary with Thomas worker scopes and produce a minimal grant schema.
- Source entry reference: `2026-06-26 - Generative Agent Protocol`.

### 180. AthenZ MCP OAuth Proxy With Enterprise Policy
- Score: 84/100
- Repo URL: https://github.com/AthenZ/mcp-oauth-proxy
- Feature/ability: OAuth 2.1/OIDC authorization proxy for MCP and A2A use cases with multiple identity providers, AthenZ authorization, encrypted token storage, and mTLS support.
- Why Thomas should adopt it: Thomas will need clean trust-domain boundaries when workers access enterprise systems; this combines login, policy decisions, machine auth, and token storage around agent tools.
- Likely Thomas integration surface: Hosted Thomas portal auth, future MCP/A2A gateway, secret vault boundaries, and policy-denial audit trails.
- Risk/effort: High; enterprise-grade pattern with real value, but likely too heavy for near-term desktop-first implementation.
- Next implementation task shape: Extract enterprise gateway requirements into a comparison matrix against simpler MCP auth proxy designs.
- Source entry reference: `2026-06-26 - AthenZ MCP OAuth Proxy with enterprise policy`.

### 181. Agent Teams AI Desktop Multi-Team Workspace
- Score: 84/100
- Repo URL: https://github.com/777genius/agent-teams-ai
- Feature/ability: Desktop app for multiple AI agent teams with autonomous task handling, inter-agent messaging, work review, Kanban supervision, Codex/Claude/OpenCode provider support, and model routing.
- Why Thomas should adopt it: It is close to the UX Thomas wants: the human gives high-level commands and watches teams execute and review work through a board.
- Likely Thomas integration surface: Native orchestration portal, team Kanban, inter-agent message lanes, provider routing, supervisor controls, and review handoff UX.
- Risk/effort: Medium-high; strong UX relevance, but licensing and implementation quality need review before any direct adoption.
- Next implementation task shape: Extract a portal layout comparison focused on team boundaries, Kanban supervision, and review handoff loops.
- Source entry reference: `2026-06-26 - Agent Teams AI desktop multi-team workspace`.

### 182. Agent-MCP Collaboration Knowledge Graph
- Score: 84/100
- Repo URL: https://github.com/rinadelph/Agent-MCP
- Feature/ability: MCP-based multi-agent collaboration protocol for coordinated software development, shared context, intelligent task management, and real-time visualization of agent work.
- Why Thomas should adopt it: Thomas needs multiple agents to collaborate without losing context or stepping on each other's work; the living knowledge graph model is a useful reference for shared state and visibility.
- Likely Thomas integration surface: Native worker graph, shared task context, inter-agent coordination state, live visualization, and MCP collaboration adapters.
- Risk/effort: Medium-high; popular and relevant, but docs maturity and overlap with Thomas workboard state need review.
- Next implementation task shape: Compare Agent-MCP shared-context concepts with Thomas workboard claims, messages, and run timelines.
- Source entry reference: `2026-06-26 - Agent-MCP collaboration knowledge graph`.

### 183. AgentLens MCP-Native Agent DevTools
- Score: 84/100
- Repo URL: https://github.com/ModernOps888/agentlens
- Feature/ability: MCP-native "Chrome DevTools for AI agents" with time-travel debugging, cost tracking, anomaly detection, and multi-agent workflow visibility.
- Why Thomas should adopt it: Thomas needs an operator-grade view of agent runs, not only transcript text; the DevTools framing fits portal debug panels, cost anomalies, and workflow inspection.
- Likely Thomas integration surface: Native orchestration dashboard, MCP trace adapter, cost telemetry, anomaly alerts, and multi-agent timeline view.
- Risk/effort: Medium; early project, but useful as a portal/debugging product reference.
- Next implementation task shape: Draft a Thomas run-inspector panel that combines trace events, cost counters, anomaly markers, and MCP tool calls.
- Source entry reference: `2026-06-26 - AgentLens MCP-native agent DevTools`.

### 184. SimpleMem Lifelong Multimodal Agent Memory
- Score: 84/100
- Repo URL: https://github.com/aiming-lab/SimpleMem
- Feature/ability: Efficient lifelong memory for LLM agents with semantic lossless compression and multimodal support for text, image, audio, and video.
- Why Thomas should adopt it: Thomas memory will need to age, compress, and retrieve long-running project context without ballooning tokens.
- Likely Thomas integration surface: Memory compaction, multimodal artifact recall, long-running worker context, MCP memory adapter, and evals for retrieval fidelity.
- Risk/effort: Medium-high; valuable memory-research signal, but integration requires careful fidelity and privacy evaluation.
- Next implementation task shape: Add a memory-compaction evaluation fixture that measures whether compressed project context still supports a worker task.
- Source entry reference: `2026-06-26 - SimpleMem lifelong multimodal agent memory`.

### 185. Recall MCP-Native Self-Hosted Memory
- Score: 84/100
- Repo URL: https://github.com/RecallWorks/Recall
- Feature/ability: Self-hosted MCP-native memory server for one or many agents, packaged as a Docker image with Python/npm clients and multi-agent coordination guidance.
- Why Thomas should adopt it: Thomas could expose memory through MCP while keeping data local; the one-image packaging and multi-agent story are useful for practical deployment design.
- Likely Thomas integration surface: MCP memory server, local Docker deployment, multi-agent memory coordination, package/client APIs, and memory service quickstart.
- Risk/effort: Medium; early but concrete and operationally relevant.
- Next implementation task shape: Compare Recall's deployment model with a Thomas local memory service quickstart.
- Source entry reference: `2026-06-27 - Recall MCP-native self-hosted memory`.

### 186. GitHub MCP Server
- Score: 83/100
- Repo URL: https://github.com/github/github-mcp-server
- Feature/ability: MCP server for repository, issue, PR, code analysis, and GitHub workflow automation.
- Why Thomas should adopt it: Controlled GitHub issue/PR access is central to future repo workers.
- Likely Thomas integration surface: GitHub connector, issue-to-worker delegation, PR review automation, and MCP permission UX.
- Risk/effort: Medium-high; GitHub write actions require strict approval and audit trails.
- Next implementation task shape: Define read-only GitHub MCP capability boundaries for Thomas.
- Source entry reference: `2026-06-26 - GitHub MCP Server`.

### 187. Microsoft MCP Gateway
- Score: 83/100
- Repo URL: https://github.com/microsoft/mcp-gateway
- Feature/ability: Reverse proxy and management layer for MCP servers with session-aware routing, authorization, and Kubernetes lifecycle management.
- Why Thomas should adopt it: If Thomas exposes internal tools through MCP, it needs controlled routing and session handling.
- Likely Thomas integration surface: MCP server deployment, session-aware tool routing, authorization layer, and cloud/remote worker access.
- Risk/effort: Medium-high; production gateway patterns may be heavier than local-first Thomas needs.
- Next implementation task shape: Extract session-aware routing and auth concepts for a local Thomas MCP gateway sketch.
- Source entry reference: `2026-06-26 - Microsoft MCP Gateway`.

### 188. Aider Terminal Coding Agent
- Score: 83/100
- Repo URL: https://github.com/aider-ai/aider
- Feature/ability: Terminal AI pair programmer with git-aware editing, repo maps, automatic commits, and provider flexibility.
- Why Thomas should adopt it: Aider's repo-map and git-centered edit loop are strong references for understandable, reversible code-agent edits.
- Likely Thomas integration surface: Repo map generation, edit ergonomics, diff presentation, and optional patch helpers.
- Risk/effort: Medium; Thomas should not inherit auto-commit defaults.
- Next implementation task shape: Compare Aider repo-map/edit workflow against Thomas worker briefing and diff flow.
- Source entry reference: `2026-06-26 - Aider terminal coding agent`.

### 189. Agent Squad Intelligent Multi-Agent Router
- Score: 83/100
- Repo URL: https://github.com/2FastLabs/agent-squad
- Feature/ability: Intent classification, routing, conversation history, streaming, and SupervisorAgent coordination.
- Why Thomas should adopt it: Helps route work among worker, reviewer, coordinator, and specialist roles.
- Likely Thomas integration surface: Delegation router, worker role registry, chat delegation planner, and coordinator logic.
- Risk/effort: Medium; workboard ownership remains authoritative.
- Next implementation task shape: Design a role-router decision record.
- Source entry reference: `2026-06-26 - Agent Squad intelligent multi-agent router`.

### 190. Browser Use Web Agent Runtime
- Score: 83/100
- Repo URL: https://github.com/browser-use/browser-use
- Feature/ability: Browser agent runtime with real browser action space, persistent tools, and recovery loops.
- Why Thomas should adopt it: Thomas browser tooling needs reliable action recovery and evidence capture.
- Likely Thomas integration surface: `thomas/tools/browser.py`, `thomas/browser/`, web research workers, and visual verification flows.
- Risk/effort: Medium-high; browser autonomy needs strong policy and evidence.
- Next implementation task shape: Compare Browser Use recovery loops to Thomas browser contracts.
- Source entry reference: `2026-06-26 - Browser Use web agent runtime`.

### 191. Agent Desktop Accessibility-Tree CLI
- Score: 83/100
- Repo URL: https://github.com/lahfir/agent-desktop
- Feature/ability: Native desktop automation CLI using OS accessibility trees, structured JSON output, deterministic element refs, and MCP-oriented automation.
- Why Thomas should adopt it: Accessibility-tree-first automation is more inspectable than screenshot-only desktop control.
- Likely Thomas integration surface: Desktop automation tool, MCP desktop server, local permission UI, and deterministic UI action logs.
- Risk/effort: Medium-high; desktop control needs careful permissions and action replay.
- Next implementation task shape: Compare accessibility-tree action logs with Thomas browser/action evidence requirements.
- Source entry reference: `2026-06-26 - Agent Desktop accessibility-tree CLI`.

### 192. CUA Computer-Use Agent Infrastructure
- Score: 83/100
- Repo URL: https://github.com/trycua/cua
- Feature/ability: Infrastructure for computer-use agents, including sandboxes, SDKs, and benchmarks across macOS, Linux, and Windows.
- Why Thomas should adopt it: Thomas needs controlled desktop sandboxes and benchmarks before high-authority GUI automation.
- Likely Thomas integration surface: Desktop sandboxing, GUI-agent benchmark runner, computer-use SDK, and worker safety tests.
- Risk/effort: High; broad infrastructure with security and platform complexity.
- Next implementation task shape: Compare CUA's sandbox/benchmark model against Thomas desktop-worker threat model.
- Source entry reference: `2026-06-26 - CUA computer-use agent infrastructure`.

### 193. AIRTBench Autonomous AI Red-Team Benchmark
- Score: 83/100
- Repo URL: https://github.com/dreadnode/AIRTBench-Code
- Feature/ability: Dataset and implementation for measuring autonomous AI red-teaming capabilities in language-model agents.
- Why Thomas should adopt it: Thomas security workers and reviewers need realistic adversarial-task evaluation.
- Likely Thomas integration surface: Security benchmark runner, red-team worker evaluation, safety regression suite, and agent trace analysis.
- Risk/effort: Medium-high; red-team benchmark use needs containment and clear scoring.
- Next implementation task shape: Map one Thomas security-worker scenario to an AIRTBench-style evaluation.
- Source entry reference: `2026-06-26 - AIRTBench autonomous AI red-team benchmark`.

### 194. MCP-Browser-Use Persistent Browser-Use MCP
- Score: 83/100
- Repo URL: https://github.com/Saik0s/mcp-browser-use
- Feature/ability: Persistent HTTP MCP wrapper around Browser Use for long-running real-browser automation.
- Why Thomas should adopt it: Thomas web workers may need timeout-resistant browser jobs with explicit status reporting.
- Likely Thomas integration surface: Browser MCP service, long-running web research jobs, timeout-resistant tool transport, and browser task status reporting.
- Risk/effort: Medium; maturity and lifecycle control need review.
- Next implementation task shape: Compare persistent HTTP browser-MCP transport against Thomas long-running tool needs.
- Source entry reference: `2026-06-26 - mcp-browser-use persistent browser-use MCP`.

### 195. Agent-Inspect Local Execution Trees
- Score: 83/100
- Repo URL: https://github.com/rajudandigam/agent-inspect
- Feature/ability: Local execution-tree renderer for TypeScript AI agents covering manual steps, tool calls, LLM calls, logs, failures, durations, and metadata.
- Why Thomas should adopt it: Compact execution trees would make Thomas worker failures readable in terminals and reviewer summaries without a large dashboard.
- Likely Thomas integration surface: Terminal trace viewer, post-run summaries, task failure reports, and local worker debugging.
- Risk/effort: Low-medium; display format is tractable, but Thomas needs stable trace data first.
- Next implementation task shape: Add a text-tree formatter for one existing Thomas run-event or workboard history structure.
- Source entry reference: `2026-06-26 - agent-inspect local execution trees`.

### 196. XState-Powered LLM Agents
- Score: 83/100
- Repo URL: https://github.com/statelyai/agent
- Feature/ability: LLM agents modeled with XState state machines for predictable control flow and inspectable transitions.
- Why Thomas should adopt it: Statecharts could make worker UI status, resumption, and error handling easier to reason about.
- Likely Thomas integration surface: Native worker runtime, task status visualization, durable run state, and deterministic replay/test fixtures.
- Risk/effort: Medium; concept fits, but repo activity and API stability need verification.
- Next implementation task shape: Sketch one Thomas worker lifecycle as an XState-style statechart and compare it to current workboard states.
- Source entry reference: `2026-06-26 - XState-powered LLM agents`.

### 197. VoltAgent TypeScript Agent Engineering Platform
- Score: 83/100
- Repo URL: https://github.com/VoltAgent/voltagent
- Feature/ability: Open-source TypeScript AI agent framework and engineering platform with orchestration, observability, and developer-facing runtime patterns.
- Why Thomas should adopt it: VoltAgent can inform how Thomas exposes agents, tools, workflows, and runtime traces to developers.
- Likely Thomas integration surface: Worker runtime SDK, portal observability, agent registry, tool integration patterns, and developer-facing orchestration APIs.
- Risk/effort: Medium; strong ergonomics reference, but direct dependency fit is uncertain.
- Next implementation task shape: Extract portal/SDK affordances Thomas should support for visible agent engineering workflows.
- Source entry reference: `2026-06-26 - VoltAgent TypeScript agent engineering platform`.

### 198. Composio Agent Tool Platform
- Score: 83/100
- Repo URL: https://github.com/ComposioHQ/composio
- Feature/ability: Agent tool platform with a large toolkit catalog, tool search, context management, authentication, and sandboxed workbench.
- Why Thomas should adopt it: Thomas needs scalable integration discovery, auth brokerage, and sandboxed action execution without hand-building every connector.
- Likely Thomas integration surface: Tool marketplace, integration registry, auth broker, tool search, and sandboxed action runner.
- Risk/effort: Medium-high; mature ecosystem reference, but hosted-service assumptions and connector trust need separation.
- Next implementation task shape: Define a Thomas integration registry record with auth, risk, sandbox, and tool-search metadata.
- Source entry reference: `2026-06-26 - Composio agent tool platform`.

### 199. Azure Durable Agents Samples
- Score: 83/100
- Repo URL: https://github.com/Azure-Samples/durable-task-extension-for-agent-framework
- Feature/ability: Quickstarts and samples for durable AI agents using Durable Task with Microsoft Agent Framework.
- Why Thomas should adopt it: Provides concrete patterns for persistent sessions, durable orchestration, and distributed scaling around agent workflows.
- Likely Thomas integration surface: Durable worker lifecycle model, persistent session API, distributed worker orchestration, and long-running task UI patterns.
- Risk/effort: Medium; useful official sample, but tied to Azure and Microsoft stack assumptions.
- Next implementation task shape: Extract provider-neutral durable-session concepts and compare them against Thomas workboard tasks.
- Source entry reference: `2026-06-26 - Azure Durable Agents samples`.

### 200. Temporal AI Agent Workflow Demo
- Score: 83/100
- Repo URL: https://github.com/temporal-community/temporal-ai-agent
- Feature/ability: Multi-turn AI agent running inside a Temporal workflow with native tools and MCP tools.
- Why Thomas should adopt it: Temporal is a mature durable execution model, and the demo shows agent conversations and tools inside resumable workflows.
- Likely Thomas integration surface: Worker workflow engine comparison, MCP tool persistence, conversation state recovery, and deterministic workflow boundaries.
- Risk/effort: Medium-high; demo scope is narrower than a Thomas runtime, and Temporal-style determinism can constrain tool execution.
- Next implementation task shape: Compare Temporal workflow boundaries with Thomas tool-call replay and resume requirements.
- Source entry reference: `2026-06-26 - Temporal AI Agent workflow demo`.

### 201. CodeGraphContext Local Graph MCP
- Score: 83/100
- Repo URL: https://github.com/CodeGraphContext/CodeGraphContext
- Feature/ability: MCP server and CLI that indexes local code into a graph database for structured AI-assistant context.
- Why Thomas should adopt it: Thomas can compare graph-backed context delivery options before standardizing a code-intelligence layer.
- Likely Thomas integration surface: Local code graph service, MCP context tools, repo research context pack, and worker preflight indexing.
- Risk/effort: Medium; implementation maturity and indexing cost need evaluation.
- Next implementation task shape: Test its context-engineering model against one local Thomas worker preflight scenario.
- Source entry reference: `2026-06-26 - CodeGraphContext local graph MCP`.

### 202. Zenflow Declarative Multi-Agent Workflow Engine
- Score: 83/100
- Repo URL: https://github.com/zendev-sh/zenflow
- Feature/ability: Declarative YAML multi-agent workflow engine with LLM coordinator, hub-and-spoke mailboxes, race-safe delivery, and MCP tool calls.
- Why Thomas should adopt it: Thomas already has workboard messages, workers, and MCP/tool surfaces; Zenflow is a compact reference for race-safe routing and YAML-defined processes.
- Likely Thomas integration surface: Workboard workflow DSL, mailbox routing, race-safe event delivery, MCP tool orchestration, and replayable workflow specs.
- Risk/effort: Medium; new project, so API stability should be watched.
- Next implementation task shape: Sketch a Thomas YAML workflow for a two-worker implement/review loop with mailbox state.
- Source entry reference: `2026-06-26 - Zenflow declarative multi-agent workflow engine`.

### 203. Mind2Web Generalist Web-Agent Benchmark
- Score: 83/100
- Repo URL: https://github.com/OSU-NLP-Group/Mind2Web
- Feature/ability: Web-agent benchmark for learning and evaluating action prediction on real websites.
- Why Thomas should adopt it: Thomas browser automation should be measured on realistic web workflows, including action grounding and cross-site generalization.
- Likely Thomas integration surface: Browser-agent eval adapter, action prediction scoring, web task replay, screenshot/DOM trace comparison, and browser-tool regression tests.
- Risk/effort: Medium-high effort and medium risk; high value for browser capabilities, but direct use may require dataset/runtime adaptation and careful live-web flake control.
- Next implementation task shape: Build a browser-action replay rubric for Thomas using recorded DOM/screenshot/action traces before attempting full Mind2Web integration.
- Source entry reference: `2026-06-26 - Mind2Web generalist web-agent benchmark`.

### 204. MCP Atlas
- Score: 83/100
- Repo URL: https://github.com/scaleapi/mcp-atlas
- Feature/ability: Benchmark and dataset suite for evaluating MCP servers and their tool coverage.
- Why Thomas should adopt it: Thomas needs broader MCP server comparison data to choose which tools are worth wrapping, mirroring, or rejecting.
- Likely Thomas integration surface: MCP server catalog scoring, tool coverage matrix, benchmark ingestion, server-selection heuristics, portal scorecard summaries, and marketplace trust signals.
- Risk/effort: Medium effort and medium risk; useful for scorecards, but implementation maturity and dataset freshness need review.
- Next implementation task shape: Extract a Thomas MCP coverage matrix format from MCP Atlas fields: server, tools, schemas, task categories, success rate, failure class, and trust notes.
- Source entry reference: `2026-06-26 - MCP Atlas`.

### 205. Sigstore Policy-Controller
- Score: 83/100
- Repo URL: https://github.com/sigstore/policy-controller
- Feature/ability: Kubernetes admission controller that verifies signatures and attestations before admitting artifacts.
- Why Thomas should adopt it: Thomas can adapt the admission-control pattern for marketplace installs: skills should pass signature, provenance, and scan policies before activation.
- Likely Thomas integration surface: Skill install admission policy, trust policy engine, signature verification gate, provenance requirements, marketplace moderation automation, and blocked-install explanations.
- Risk/effort: Medium effort and medium risk; implementation is Kubernetes-specific, but the policy pattern maps cleanly to Thomas skill installs.
- Next implementation task shape: Draft a Thomas skill install policy file that requires signature, provenance, permission declaration, scan result, and reviewer approval by trust tier.
- Source entry reference: `2026-06-26 - Sigstore policy-controller`.

### 206. Open Agent Auth
- Score: 83/100
- Repo URL: https://github.com/alibaba/open-agent-auth
- Feature/ability: Open authorization framework for agent systems focused on agent identity and access control.
- Why Thomas should adopt it: Thomas should compare agent-specific auth frameworks before designing worker credentials, tool consent, and service-to-service trust.
- Likely Thomas integration surface: Agent auth framework comparison, identity exchange, scoped tool permissions, service trust boundary, and prompt-time authorization summaries.
- Risk/effort: Medium-high; vendor-backed and relevant, but Thomas should inspect portability and avoid overfitting to one ecosystem.
- Next implementation task shape: Add Open Agent Auth to an identity/auth comparison matrix beside SPIFFE, OpenFGA, OAuth proxy, and Sigstore.
- Source entry reference: `2026-06-26 - Open Agent Auth`.

### 207. Proxilion Runtime Security SDK
- Score: 83/100
- Repo URL: https://github.com/clay-good/proxilion-sdk
- Feature/ability: In-application runtime security guard layer for LLM apps that checks tool calls for prompt injection, data leakage, authorization attacks, and rogue agent behavior.
- Why Thomas should adopt it: Thomas needs live enforcement points inside the agent/tool path, not only preflight scans; Proxilion is a concise reference for deterministic checks around tool use.
- Likely Thomas integration surface: Agent tool middleware, prompt-injection gates, data egress checks, and run audit events.
- Risk/effort: Medium; low adoption suggests caution, but the runtime-security shape is directly applicable.
- Next implementation task shape: Extract one data-egress and one authorization rule into a Thomas tool middleware design note with test fixtures.
- Source entry reference: `2026-06-26 - Proxilion runtime security SDK`.

### 208. AgentUniverse Enterprise Multi-Agent Patterns
- Score: 83/100
- Repo URL: https://github.com/agentuniverse-ai/agentUniverse
- Feature/ability: Multi-agent framework with reusable collaborative pattern components and domain-expert agent construction from real-world financial business practices.
- Why Thomas should adopt it: Thomas should collect proven collaboration patterns, not just low-level tooling; agentUniverse is a mature reference for pattern factories and domain-experience integration.
- Likely Thomas integration surface: Multi-agent pattern registry, domain-specific worker templates, workflow orchestration primitives, and enterprise scenario examples.
- Risk/effort: Medium-high; valuable pattern library, but direct framework adoption would need deeper architecture review.
- Next implementation task shape: Extract two reusable collaboration patterns and translate them into Thomas worker-template terminology.
- Source entry reference: `2026-06-26 - agentUniverse enterprise multi-agent patterns`.

### 209. Memory MCP Enhanced Knowledge Graph Server
- Score: 83/100
- Repo URL: https://github.com/danielsimonjr/memory-mcp
- Feature/ability: Enhanced MCP memory server with timestamps, tags, importance, semantic search, hierarchy, compression, graph algorithms, archiving, import/export, RBAC, PII redaction, exclusions, and rationale memory.
- Why Thomas should adopt it: It is a dense checklist for memory governance features Thomas will need, including redaction, forget rules, RBAC, temporal validity, project context, and rationale capture.
- Likely Thomas integration surface: Memory governance API, PII redaction/export, project memory graph, do-not-remember policy, ADR/rationale memory, and MCP memory tooling.
- Risk/effort: Medium-high; broad feature list must be validated and narrowed before implementation.
- Next implementation task shape: Turn the feature list into a Thomas memory governance checklist with must-have vs. later columns.
- Source entry reference: `2026-06-27 - Memory MCP enhanced knowledge graph server`.

### 210. OpenCode Terminal Agent Plan/Build Modes
- Score: 82/100
- Repo URL: https://github.com/anomalyco/opencode
- Feature/ability: Terminal agent with separate build and read-only plan modes, shell permissions, and subagents.
- Why Thomas should adopt it: Thomas needs explicit research/review/worker modes that prevent accidental edits.
- Likely Thomas integration surface: Agent mode selector, delegation templates, read-only planning mode, shell prompts, and subagent invocation.
- Risk/effort: Medium; strong UX reference, but must fit Thomas portal and workboard rules.
- Next implementation task shape: Draft mode permissions for Thomas planning, review, and build workers.
- Source entry reference: `2026-06-26 - OpenCode terminal agent plan/build modes`.

### 211. Pydantic AI Harness Capability Library
- Score: 82/100
- Repo URL: https://github.com/pydantic/pydantic-ai-harness
- Feature/ability: Approval workflows, tool budgets, stuck-loop detection, secret masking, retry/backoff, and orphaned tool-call repair.
- Why Thomas should adopt it: Practical guardrails map to Thomas safety, cost, and diagnosis needs.
- Likely Thomas integration surface: Agent loop middleware, tool execution wrappers, `thomas/core/testing_suite.py`, and telemetry.
- Risk/effort: Medium; maturity needs follow-up.
- Next implementation task shape: Audit Thomas loop failure modes against the harness list.
- Source entry reference: `2026-06-26 - Pydantic AI Harness capability library`.

### 212. Codemogger Local Code Indexing MCP
- Score: 82/100
- Repo URL: https://github.com/glommer/codemogger
- Feature/ability: Local code indexing library and MCP server using tree-sitter chunks, local embeddings, and SQLite vector/full-text search.
- Why Thomas should adopt it: Thomas needs local-first code intelligence that avoids heavyweight services and external APIs.
- Likely Thomas integration surface: Local code index cache, MCP search tools, worker context retrieval, and offline repo analysis.
- Risk/effort: Medium; index freshness, storage size, and trust semantics need definition.
- Next implementation task shape: Prototype a local-index design note comparing codemogger, Carto, Claude Context, and Code Index MCP.
- Source entry reference: `2026-06-26 - codemogger local code indexing MCP`.

### 213. Agent S Computer-Use Framework
- Score: 82/100
- Repo URL: https://github.com/simular-ai/agent-s
- Feature/ability: Agent-computer interface for autonomous desktop interaction with experience learning.
- Why Thomas should adopt it: Thomas has browser and desktop-adjacent automation needs; Agent S is a strong GUI-agent reference.
- Likely Thomas integration surface: Desktop automation worker, GUI action abstraction, experience memory, and visual/task replay.
- Risk/effort: High; computer-use autonomy requires strict permissioning, replay, and evidence capture.
- Next implementation task shape: Compare Agent S action/memory abstractions against Thomas browser and desktop-control needs.
- Source entry reference: `2026-06-26 - Agent S computer-use framework`.

### 214. VS Code ACP Client Extension
- Score: 82/100
- Repo URL: https://github.com/formulahendry/vscode-acp
- Feature/ability: VS Code extension connecting to ACP-compatible agents such as Claude, Codex, Copilot, Gemini, Qwen, OpenCode, Kiro, and OpenClaw.
- Why Thomas should adopt it: Shows how editor-native ACP clients expose sessions, permissions, and multiple backend agents.
- Likely Thomas integration surface: Agent client UX, editor integration, ACP session model, and multi-provider worker controls.
- Risk/effort: Medium; client reference, not core backend.
- Next implementation task shape: Compare VS Code ACP session UI against Thomas portal worker controls.
- Source entry reference: `2026-06-26 - VS Code ACP client extension`.

### 215. Codex-ACP Bridge
- Score: 82/100
- Repo URL: https://github.com/cola-io/codex-acp
- Feature/ability: ACP-compatible bridge exposing OpenAI Codex runtime to ACP clients over stdio.
- Why Thomas should adopt it: Thomas needs to wrap Codex as a protocol-compatible worker rather than coupling the portal to one client.
- Likely Thomas integration surface: Codex worker adapter, ACP client compatibility testing, stdio agent bridge, and provider abstraction.
- Risk/effort: Medium; topic-sourced and maturity needs review.
- Next implementation task shape: Compare codex-acp stdio bridge shape against Thomas worker launch needs.
- Source entry reference: `2026-06-26 - codex-acp bridge`.

### 216. Pluribus Context Receipts
- Score: 82/100
- Repo URL: https://github.com/caioribeiroclw-pixel/pluribus
- Feature/ability: Privacy-safe context receipts proving which context, memory, tools, skills, compactions, and security findings crossed the agent boundary without logging raw content.
- Why Thomas should adopt it: Thomas needs auditability that does not leak sensitive repo contents into logs or coordination messages.
- Likely Thomas integration surface: Privacy-preserving audit logs, worker context receipts, skill/tool provenance records, and security review evidence.
- Risk/effort: Medium; concept is highly aligned, but small-project maturity means Thomas should adopt the pattern before code.
- Next implementation task shape: Design a hashed context-receipt schema for one worker prompt assembly path.
- Source entry reference: `2026-06-26 - Pluribus context receipts`.

### 217. Agent-Memory-MCP Persistent Memory Server
- Score: 82/100
- Repo URL: https://github.com/ipiton/agent-memory-mcp
- Feature/ability: MCP server for persistent agent memory exposed as observable tools instead of hidden prompt stuffing.
- Why Thomas should adopt it: A memory MCP gives Thomas a clean, permissionable boundary for cross-agent memory read/write operations.
- Likely Thomas integration surface: MCP adapter layer, Thomas memory read/write tools, worker context bootstrap, and audit logs for memory mutations.
- Risk/effort: Medium; scale, conflict handling, and memory provenance need deeper review.
- Next implementation task shape: Draft Thomas memory MCP tool contracts for create, retrieve, update, and audit.
- Source entry reference: `2026-06-26 - agent-memory-mcp persistent memory server`.

### 218. AgentBench Dynamic Reasoning Infrastructure Benchmark
- Score: 82/100
- Repo URL: https://github.com/VIA-Research/AgentBench
- Feature/ability: Agent implementations and benchmark harnesses for studying dynamic reasoning and test-time scaling from an infrastructure perspective.
- Why Thomas should adopt it: Thomas needs evidence for when deeper planning or more worker steps improve outcomes versus wasting compute.
- Likely Thomas integration surface: Evaluation harness, run-cost telemetry, planning-depth policy, and benchmark-driven worker configuration.
- Risk/effort: Medium; useful benchmark framing, but direct applicability to Thomas coding workflows needs validation.
- Next implementation task shape: Add a run-cost metric to one Thomas worker eval and compare shallow versus deeper planning.
- Source entry reference: `2026-06-26 - AgentBench dynamic reasoning infrastructure benchmark`.

### 219. A2A JavaScript SDK
- Score: 82/100
- Repo URL: https://github.com/a2aproject/a2a-js
- Feature/ability: Official JavaScript/TypeScript SDK for the Agent2Agent protocol.
- Why Thomas should adopt it: Thomas portal and frontend-adjacent worker tooling may need JS/TS interop with Python workers and external agents.
- Likely Thomas integration surface: Portal-side A2A client, TypeScript worker adapters, cross-language interoperability fixtures, and protocol conformance tests.
- Risk/effort: Medium; useful for full-stack experiments but secondary to Python worker support.
- Next implementation task shape: Define a portal-side A2A client fixture that consumes a Thomas worker status stream.
- Source entry reference: `2026-06-26 - A2A JavaScript SDK`.

### 220. OpenViking Context Database
- Score: 82/100
- Repo URL: https://github.com/volcengine/OpenViking
- Feature/ability: Open-source context database for AI agents managing memory, resources, and skills through a file-system-like paradigm with hierarchical context delivery.
- Why Thomas should adopt it: Thomas needs a unified way to manage project memory, repo resources, skills, and worker context without scattering context across unrelated files and prompts.
- Likely Thomas integration surface: Thomas context database, worker context filesystem, skill/resource registry, hierarchical context delivery, and self-evolving context store.
- Risk/effort: High; concept is strong but operational complexity and stack fit need careful review.
- Next implementation task shape: Sketch a Thomas context namespace that separates memory, skills, repo resources, and worker-local context.
- Source entry reference: `2026-06-26 - OpenViking context database`.

### 221. ClawBench Mobile GUI-Agent Benchmark
- Score: 82/100
- Repo URL: https://github.com/TIGER-AI-Lab/ClawBench
- Feature/ability: Benchmark for evaluating mobile GUI agents on realistic app-control tasks.
- Why Thomas should adopt it: If Thomas adopts mobile or GUI workers, it needs benchmark coverage for task success, safety, and interaction quality.
- Likely Thomas integration surface: GUI-agent eval suite, mobile task benchmark, worker scoring rubric, and visual action regression checks.
- Risk/effort: Medium-high; mobile environments are heavier than near-term browser evals.
- Next implementation task shape: Use ClawBench categories to define Thomas's minimum mobile/GUI worker evaluation rubric.
- Source entry reference: `2026-06-26 - ClawBench mobile GUI-agent benchmark`.

### 222. Open Operator Evals
- Score: 82/100
- Repo URL: https://github.com/nottelabs/open-operator-evals
- Feature/ability: Evaluation suite for open operator/browser agents and their web task performance.
- Why Thomas should adopt it: Thomas needs comparable browser-agent evaluations for browser-use, Playwright MCP, AG-UI, and custom portal agents.
- Likely Thomas integration surface: Browser-agent eval pipeline, task fixtures, benchmark runner, and operator-agent comparison.
- Risk/effort: Medium; scope and dependencies need review before integration.
- Next implementation task shape: Extract one operator-style browser task and define Thomas pass/fail evidence requirements.
- Source entry reference: `2026-06-26 - Open Operator Evals`.

### 223. Agent Discover Scanner
- Score: 82/100
- Repo URL: https://github.com/Defend-AI-Tech-Inc/agent-discover-scanner
- Feature/ability: Agentic identity and inventory scanner that discovers autonomous agents using static analysis, network heuristics, and eBPF.
- Why Thomas should adopt it: As Thomas grows native workers, MCP servers, plugins, and external agents, it needs inventory of what agents exist and what authority they have.
- Likely Thomas integration surface: Agent inventory scan, AIBOM-style metadata, workspace agent discovery, runtime network heuristics, and governance reports.
- Risk/effort: Medium-high; eBPF/network scanning may be heavyweight, but inventory ideas are valuable.
- Next implementation task shape: Define a Thomas agent inventory record for worker, tool, authority, and network surface.
- Source entry reference: `2026-06-26 - Agent Discover Scanner`.

### 224. Reyn Constrained Workflow OS
- Score: 82/100
- Repo URL: https://github.com/tya5/reyn
- Feature/ability: AI agent workflow OS focused on constrained, validated, replayable execution with predictability over unconstrained autonomy.
- Why Thomas should adopt it: Thomas values scoped claims, gates, and reviewable worker behavior, and Reyn's predictability-first model maps to that operating style.
- Likely Thomas integration surface: Worker workflow OS comparison, validation gates, replayable execution records, task constraints, and deterministic handoff model.
- Risk/effort: Medium; strong concept, but maturity and ecosystem size need review.
- Next implementation task shape: Compare Reyn constraints with Thomas claim scopes, commit helper gates, and release rules.
- Source entry reference: `2026-06-26 - Reyn constrained workflow OS`.

### 225. OpenLLMetry JS/TS Observability
- Score: 82/100
- Repo URL: https://github.com/traceloop/openllmetry-js
- Feature/ability: TypeScript/JavaScript OpenTelemetry instrumentation for LLM applications and agent workflows.
- Why Thomas should adopt it: Thomas portal and TypeScript-adjacent surfaces should emit telemetry compatible with Python worker traces.
- Likely Thomas integration surface: Portal telemetry, frontend/Node worker traces, AG-UI/A2A client spans, and cross-language trace correlation.
- Risk/effort: Medium; secondary to Python worker tracing but important for portal observability.
- Next implementation task shape: Define cross-language trace IDs linking a Thomas portal action to a worker run.
- Source entry reference: `2026-06-26 - OpenLLMetry JS/TS observability`.

### 226. NVIDIA LLM Router Blueprint
- Score: 82/100
- Repo URL: https://github.com/NVIDIA-AI-Blueprints/llm-router
- Feature/ability: Experimental router blueprint for choosing optimal text or multimodal models based on prompt analysis and speed/cost/accuracy tradeoffs.
- Why Thomas should adopt it: Thomas will need route replay and benchmark evidence before delegating worker steps to cheaper, faster, or multimodal models. This is a useful blueprint for router experiments.
- Likely Thomas integration surface: Model-router benchmark, multimodal route policy, NIM/local deployment comparison, Docker-based router experiments, and route telemetry.
- Risk/effort: Medium effort and medium risk; the blueprint is useful, but NVIDIA stack assumptions may not match Thomas's default deployment path.
- Next implementation task shape: Extract a model-router experiment plan that can run without NVIDIA-specific services first, then compare optional NIM/local deployment paths separately.
- Source entry reference: `2026-06-26 - NVIDIA LLM Router Blueprint`.

### 227. AgentTrek Browser Trajectory Benchmark
- Score: 82/100
- Repo URL: https://github.com/xlang-ai/AgentTrek
- Feature/ability: Benchmark and trajectory resource for web agents with browser-action traces and task execution data.
- Why Thomas should adopt it: Thomas browser tasks should be replayable and inspectable so failed browser actions can become reproducible workboard issues.
- Likely Thomas integration surface: Browser-action replay traces, DOM/screenshot trajectory storage, browser-tool regression tests, task failure triage, and route replay datasets.
- Risk/effort: Medium effort and medium risk; trajectory resources are relevant, but Thomas needs to normalize them into its own trace schema.
- Next implementation task shape: Define a browser trajectory artifact format for Thomas with URL, DOM anchor, screenshot reference, action, result, assertion, and failure reason.
- Source entry reference: `2026-06-26 - AgentTrek browser trajectory benchmark`.

### 228. Why Agents Fail Sample
- Score: 82/100
- Repo URL: https://github.com/aws-samples/sample-why-agents-fail
- Feature/ability: Sample code and examples for analyzing common AI agent failure modes such as tool misuse, planning errors, and missing context.
- Why Thomas should adopt it: Thomas needs failure clustering so repeated worker breakdowns become actionable bug classes instead of isolated anecdotes.
- Likely Thomas integration surface: Failure taxonomy, eval-failure clustering, reviewer diagnostics, workboard issue generation, regression examples for agent loops, and dashboard summaries.
- Risk/effort: Low-medium effort and medium risk; sample scope limits direct dependency value, but failure-mode taxonomy is immediately useful.
- Next implementation task shape: Create a Thomas failure taxonomy draft covering planning miss, stale context, wrong tool, bad arguments, unsafe action, incomplete verification, and summary mismatch.
- Source entry reference: `2026-06-26 - Why agents fail sample`.

### 229. Azure Agentic Evaluations
- Score: 82/100
- Repo URL: https://github.com/Azure-Samples/Agentic-Evaluations
- Feature/ability: Config-driven evaluation framework for agentic systems and GenAI applications with YAML experiment configuration.
- Why Thomas should adopt it: Thomas needs repeatable, declarative eval configs so worker quality checks can run in CI or before promotion without bespoke scripts each time.
- Likely Thomas integration surface: YAML eval specs, Foundry adapter comparison, CI evaluation jobs, multi-agent workflow tests, eval artifact outputs, and promotion criteria.
- Risk/effort: Medium effort and medium risk; the config pattern is portable, but Azure-specific dependencies should be isolated.
- Next implementation task shape: Draft a Thomas YAML eval spec for one worker flow, including inputs, allowed tools, expected artifacts, metrics, evaluator, and output paths.
- Source entry reference: `2026-06-26 - Azure Agentic Evaluations`.

### 230. NVIDIA Skills
- Score: 82/100
- Repo URL: https://github.com/NVIDIA/skills
- Feature/ability: NVIDIA-maintained agent skill collection with domain-specific reusable skill packages.
- Why Thomas should adopt it: Thomas should compare skill repo layout, metadata, and distribution conventions across major vendors before freezing its own skill marketplace shape.
- Likely Thomas integration surface: Skill package comparison, metadata schema review, import pipeline, trust metadata, skill quality gates, and vendor-specific compatibility notes.
- Risk/effort: Low-medium effort and medium risk; useful as a vendor reference, but the exact fit depends on package structure and domain assumptions.
- Next implementation task shape: Inspect the NVIDIA skill metadata and produce a field-by-field comparison against Anthropic skills and Thomas's expected skill registry fields.
- Source entry reference: `2026-06-26 - NVIDIA skills`.

### 231. Addy Osmani Agent-Skills
- Score: 82/100
- Repo URL: https://github.com/addyosmani/agent-skills
- Feature/ability: Practical agent skill examples and reusable workflows for software-development agents.
- Why Thomas should adopt it: Thomas should study high-signal skill examples for naming, scope boundaries, prompt assets, and developer workflow coverage.
- Likely Thomas integration surface: Skill example import, quality rubric, software-development skill templates, trust review, marketplace seed examples, and documentation examples.
- Risk/effort: Low-medium effort and medium risk; useful as a pattern source, but examples should be adapted to Thomas guardrails rather than imported blindly.
- Next implementation task shape: Sample three software-development skills and extract a Thomas skill quality rubric covering scope, inputs, tools, assets, tests, and expected outputs.
- Source entry reference: `2026-06-26 - Addy Osmani agent-skills`.

### 232. ACA-Py Digital Trust Agent
- Score: 82/100
- Repo URL: https://github.com/openwallet-foundation/acapy
- Feature/ability: Aries Cloud Agent Python for decentralized identity, DIDComm, verifiable credentials, and wallet-backed trust workflows.
- Why Thomas should adopt it: Portable verifiable credentials could give Thomas stronger identity proofs for workers, skill publishers, and tool providers.
- Likely Thomas integration surface: Agent identity wallet, verifiable credential issuance, DIDComm trust channels, credential-backed skill publisher metadata, and trust policy experiments.
- Risk/effort: High; mature ecosystem, but DID/VC workflows are heavier than Thomas needs for near-term local orchestration.
- Next implementation task shape: Document one VC-backed skill-publisher trust flow and compare it with simpler Sigstore-style publisher identity.
- Source entry reference: `2026-06-26 - ACA-Py digital trust agent`.

### 233. MCP GitHub OAuth
- Score: 82/100
- Repo URL: https://github.com/conshus/mcp-github-oauth
- Feature/ability: MCP server pattern for GitHub OAuth authentication and scoped repository access.
- Why Thomas should adopt it: Thomas GitHub-related tools should prefer explicit OAuth scopes and user consent over broad personal tokens in agent contexts.
- Likely Thomas integration surface: MCP OAuth flow, GitHub scoped token handling, user consent UX, repo access audit, and tool permission narrowing.
- Risk/effort: Medium; direct and useful, but narrower than a general MCP auth gateway and maturity should be checked.
- Next implementation task shape: Model a scoped GitHub OAuth grant for a Thomas repo worker and list audit events required for each token use.
- Source entry reference: `2026-06-26 - MCP GitHub OAuth`.

### 234. Babs MCP Auth Proxy For OIDC Bridge
- Score: 82/100
- Repo URL: https://github.com/babs/mcp-auth-proxy
- Feature/ability: Stateless OAuth 2.1 authorization-server bridge that fronts private MCP servers while delegating identity to an existing OIDC provider.
- Why Thomas should adopt it: It shows a low-friction path for protecting private MCP tools without rewriting every server, which fits local-tool sharing and user-scoped worker access.
- Likely Thomas integration surface: MCP proxy/gateway, local worker tool publication, auth/session middleware, and audit-defensible token exchange.
- Risk/effort: Medium; focused bridge pattern, but Thomas must test whether stateless proxying is enough for local approval and audit requirements.
- Next implementation task shape: Sketch a Thomas private-tool publication flow where OIDC identity gates worker access through a bridge.
- Source entry reference: `2026-06-26 - Babs MCP Auth Proxy for OIDC bridge`.

### 235. Nerve Self-Hosted Agent Runtime
- Score: 82/100
- Repo URL: https://github.com/ClickHouse/nerve
- Feature/ability: Self-hosted AI agent runtime for personal assistants and autonomous workers with setup, architecture, configuration, worker guide, and API reference.
- Why Thomas should adopt it: Thomas is moving toward native visible worker orchestration instead of hidden external loops; Nerve is a useful reference for packaging a self-hosted worker runtime with operational docs.
- Likely Thomas integration surface: Native orchestration service, worker lifecycle config, portal task views, and hosted/local deployment layout.
- Risk/effort: Medium-high; aligned product shape, but young and not a direct transplant for Thomas's existing worker model.
- Next implementation task shape: Compare Nerve's worker lifecycle/config surfaces with Thomas native orchestration requirements and identify one reusable documentation pattern.
- Source entry reference: `2026-06-26 - Nerve self-hosted agent runtime`.

### 236. HUMAN Verified AI Agent Signatures
- Score: 82/100
- Repo URL: https://github.com/HumanSecurity/human-verified-ai-agent
- Feature/ability: A2A multi-agent system using HTTP Message Signatures to authenticate agent requests to external services without relying only on API keys or user-agent strings.
- Why Thomas should adopt it: If Thomas workers interact with external services, signed agent requests and verifiable identity are stronger than opaque bearer-token calls.
- Likely Thomas integration surface: External service connector auth, A2A gateway, signed webhook requests, worker identity keys, and request verification logs.
- Risk/effort: Medium; demo repo, but the standards-backed signing pattern is important for trusted agent identity.
- Next implementation task shape: Prototype a signed outbound worker request record and verification log for one external connector.
- Source entry reference: `2026-06-26 - HUMAN verified AI agent signatures`.

### 237. Microsoft Trace Generative Optimization For Agents
- Score: 82/100
- Repo URL: https://github.com/microsoft/Trace
- Feature/ability: End-to-end generative optimization library that captures and propagates execution traces through AI systems using rewards, language critiques, or compiler errors.
- Why Thomas should adopt it: Thomas wants self-improvement, but needs grounded mechanisms tied to execution feedback rather than informal prompt edits.
- Likely Thomas integration surface: Evolve loop, run feedback propagation, compiler/test-error optimization experiments, prompt/program tuning, and trace-backed improvement candidates.
- Risk/effort: High; research-heavy and potentially powerful, so Thomas should treat it as an evolve-loop research reference before implementation.
- Next implementation task shape: Map one failed test or compiler error from a Thomas worker run into a trace-backed improvement candidate format.
- Source entry reference: `2026-06-26 - Microsoft Trace generative optimization for agents`.

### 238. Octopoda Memory Operating System
- Score: 82/100
- Repo URL: https://github.com/RyjoxTechnologies/Octopoda-OS
- Feature/ability: Memory operating system for AI agents with persistent memory, semantic search, loop detection, agent messaging, crash recovery, audit trails, and live observability.
- Why Thomas should adopt it: Thomas needs memory, loop detection, recovery, and observability as one operating surface for agents, not unrelated bolt-ons.
- Likely Thomas integration surface: Native worker runtime, memory observability dashboard, loop detector, crash recovery, inter-agent messaging, and audit trails.
- Risk/effort: Medium-high; strong feature fit but maturity needs inspection before adopting any architecture.
- Next implementation task shape: Compare Octopoda's combined memory/recovery/observability model with Thomas native orchestration requirements.
- Source entry reference: `2026-06-27 - Octopoda memory operating system`.

### 239. Continue Checks AI PR Quality Standards
- Score: 81/100
- Repo URL: https://github.com/continuedev/checks
- Feature/ability: Markdown-defined AI code quality standards that run on pull requests.
- Why Thomas should adopt it: Thomas can encode project-specific review rules as agent-readable checks rather than scattered prompt text.
- Likely Thomas integration surface: Reviewer prompts, CI-style agent checks, workboard completion gates, and Bible-derived rules.
- Risk/effort: Medium; small repo, but concept fits Thomas verification discipline.
- Next implementation task shape: Draft a `.checks`-style Thomas review rule for Bible/workboard compliance.
- Source entry reference: `2026-06-26 - Continue Checks AI PR quality standards`.

### 240. NVIDIA Garak LLM Vulnerability Scanner
- Score: 81/100
- Repo URL: https://github.com/NVIDIA/garak
- Feature/ability: Generative AI red-teaming and assessment kit for hallucination, leakage, prompt injection, misinformation, toxicity, jailbreaks, and related weaknesses.
- Why Thomas should adopt it: Thomas should test model/agent behavior against known failure modes before expanding autonomy.
- Likely Thomas integration surface: Security eval suite, model/provider acceptance checks, red-team reports, and pre-release safety gates.
- Risk/effort: Medium; not agent-specific, so Thomas must wrap it in task-relevant scenarios.
- Next implementation task shape: Identify one Thomas prompt/tool flow that can be probed with garak-style checks.
- Source entry reference: `2026-06-26 - NVIDIA garak LLM vulnerability scanner`.

### 241. OpenHands Benchmarks Evaluation Pipelines
- Score: 81/100
- Repo URL: https://github.com/OpenHands/benchmarks
- Feature/ability: Benchmark infrastructure for real-world agent task evaluation.
- Why Thomas should adopt it: Thomas needs repeatable runners, logs, and score reporting for worker changes.
- Likely Thomas integration surface: `thomas/core/testing_suite.py`, eval task registry, worker benchmark runner, and artifact storage.
- Risk/effort: Medium; migration status needs follow-up.
- Next implementation task shape: Design a first eval artifact format.
- Source entry reference: `2026-06-26 - OpenHands Benchmarks evaluation pipelines`.

### 242. Mnemon Agent Memory System
- Score: 81/100
- Repo URL: https://github.com/mnemon-dev/mnemon
- Feature/ability: Agent memory infrastructure for extracting, organizing, and retrieving durable memories from agent sessions.
- Why Thomas should adopt it: Thomas needs shared memory that separates durable project facts from transient run noise.
- Likely Thomas integration surface: Memory compaction service, conversation-to-memory extraction, worker bootstrap context, and ranker evidence stores.
- Risk/effort: Medium; promising model, but maturity and data model clarity need inspection.
- Next implementation task shape: Compare Mnemon extraction categories against Thomas memory and workboard summary needs.
- Source entry reference: `2026-06-26 - Mnemon agent memory system`.

### 243. LangChain Agent Evals Scripts
- Score: 81/100
- Repo URL: https://github.com/langchain-ai/agent-evals
- Feature/ability: Collection of evaluation scripts for benchmarking agents across specific tasks.
- Why Thomas should adopt it: Concrete task-level eval scripts can keep worker changes measurable and reproducible.
- Likely Thomas integration surface: Evaluation script library, CI benchmark tasks, ranking evidence, and worker capability regression checks.
- Risk/effort: Medium; scripts are useful but may need adaptation to Thomas-specific worker and repo tasks.
- Next implementation task shape: Select one script shape and rewrite it as a Thomas worker capability regression.
- Source entry reference: `2026-06-26 - LangChain Agent Evals scripts`.

### 244. A2A Protocol Samples
- Score: 81/100
- Repo URL: https://github.com/a2aproject/a2a-samples
- Feature/ability: Sample implementations using Agent2Agent across frameworks and agent scenarios.
- Why Thomas should adopt it: Samples help compare how A2A maps to real agent tasks, streaming updates, artifacts, and framework-specific worker patterns.
- Likely Thomas integration surface: Interop prototypes, sample-based tests, framework comparison, worker capability cards, and A2A task lifecycle experiments.
- Risk/effort: Low-medium; sample quality varies, so use as learning material rather than dependency.
- Next implementation task shape: Pick one sample closest to Thomas worker status/artifact exchange and adapt its lifecycle sketch.
- Source entry reference: `2026-06-26 - A2A protocol samples`.

### 245. CodeRAG Local Semantic Code Search
- Score: 81/100
- Repo URL: https://github.com/Neverdecel/CodeRAG
- Feature/ability: Local-first semantic code search using hybrid vector plus keyword retrieval with symbol-aware chunking, exposed as CLI, Python library, REST API, and web UI.
- Why Thomas should adopt it: Thomas needs retrieval over local codebases without hosted embeddings or source leakage.
- Likely Thomas integration surface: Local RAG service, symbol-aware chunking, Python worker library, REST lookup endpoint, and portal search UI.
- Risk/effort: Medium; benchmark quality and embedding/storage choices need review.
- Next implementation task shape: Compare CodeRAG-style hybrid retrieval to existing Thomas code-search/RAG expectations on one task.
- Source entry reference: `2026-06-26 - CodeRAG local semantic code search`.

### 246. Azure AI Gateway Labs for Agents
- Score: 81/100
- Repo URL: https://github.com/Azure-Samples/AI-Gateway
- Feature/ability: Reference labs for AI models, MCP servers, and agents behind an AI Gateway using Azure API Management and Microsoft Foundry.
- Why Thomas should adopt it: This provides enterprise gateway patterns for putting agents, MCP tools, and model calls behind one governed policy surface, useful even if Thomas remains provider-neutral.
- Likely Thomas integration surface: MCP gateway policy comparison, enterprise API-management patterns, agent access controls, rate/budget policies, provider-specific adapter research, and Foundry/Azure integration notes.
- Risk/effort: Medium effort and medium risk; reference architecture quality is high, but direct adoption is Azure-specific and may overfit Thomas to enterprise cloud infrastructure.
- Next implementation task shape: Extract an enterprise gateway control checklist from the labs covering auth, quotas, model routing, MCP exposure, audit logs, and per-agent policy boundaries.
- Source entry reference: `2026-06-26 - Azure AI Gateway labs for agents`.

### 247. Reproducible Trajectories for Web Agents
- Score: 81/100
- Repo URL: https://github.com/ASSERT-KTH/reproducible-trajectories
- Feature/ability: Research artifact for capturing and replaying reproducible web-agent trajectories.
- Why Thomas should adopt it: Thomas needs failed agent/browser runs to be replayable across machines and time, not trapped as screenshots and prose summaries.
- Likely Thomas integration surface: Trajectory serialization, browser replay harness, deterministic web-task evidence, regression fixture generation, and trace-to-issue conversion.
- Risk/effort: Medium effort and medium risk; research artifact maturity may limit direct reuse, but the reproducibility pattern is central to Thomas browser QA.
- Next implementation task shape: Compare its trajectory serialization model against Thomas browser traces and identify the minimum fields needed for replayable failure reports.
- Source entry reference: `2026-06-26 - Reproducible Trajectories for web agents`.

### 248. Agent Skills OCI Artifacts Spec
- Score: 81/100
- Repo URL: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- Feature/ability: Specification for packaging, distributing, signing, and tracking agent skills as OCI artifacts with manifest, config schemas, annotations, collections, lock files, and supply-chain security.
- Why Thomas should adopt it: Thomas skills and task artifacts need portable packaging, provenance, signing, and dependency locking as the skill ecosystem grows.
- Likely Thomas integration surface: Skill artifact bundle schema, signed skill registry, provenance annotations, lock-file format, OCI registry distribution, marketplace security gates, and skill trust metadata.
- Risk/effort: Medium effort and medium risk; early spec status makes direct adoption premature, but the provenance and packaging model is strategically relevant.
- Next implementation task shape: Map Thomas skill metadata to an OCI-style manifest draft with name, version, inputs, permissions, provenance, signature, dependencies, and lock-file fields.
- Source entry reference: `2026-06-26 - Agent skills OCI artifacts spec`.

### 249. AWS Agent Toolkit
- Score: 81/100
- Repo URL: https://github.com/aws/agent-toolkit-for-aws
- Feature/ability: AWS-focused agent toolkit that packages curated skills, tools, and guidance for building agents on AWS.
- Why Thomas should adopt it: Thomas can study how a platform vendor packages skills and tooling with cloud permissions, examples, and operational constraints.
- Likely Thomas integration surface: Skill/tool bundle schema, cloud tool trust metadata, permission documentation, marketplace import filters, platform-specific skill adapters, and install warnings.
- Risk/effort: Medium effort and medium risk; useful packaging reference, but AWS-specific pieces should remain optional and permission-gated.
- Next implementation task shape: Extract a Thomas cloud-skill review checklist from the toolkit covering required credentials, IAM scope, network access, cleanup behavior, and test fixtures.
- Source entry reference: `2026-06-26 - AWS Agent Toolkit`.

### 250. Web Quality Skills
- Score: 81/100
- Repo URL: https://github.com/addyosmani/web-quality-skills
- Feature/ability: Focused skill collection for web quality, performance, accessibility, and frontend engineering checks.
- Why Thomas should adopt it: Thomas web/site workers need reusable skills with concrete quality gates instead of free-form review prompts.
- Likely Thomas integration surface: Frontend QA skill import, accessibility/performance skill templates, visual-proof workflow integration, Lighthouse/Core Web Vitals checks, and skill acceptance tests.
- Risk/effort: Low-medium effort and low-medium risk; strong domain fit for Thomas web work, but should be mapped to existing Thomas visual-proof and UI guardrail workflows.
- Next implementation task shape: Draft a Thomas frontend quality skill template that includes accessibility, performance, responsive screenshots, visual evidence, and acceptance criteria.
- Source entry reference: `2026-06-26 - Web quality skills`.

### 251. JamJet Policy Layer
- Score: 81/100
- Repo URL: https://github.com/jamjet-labs/jamjet
- Feature/ability: Policy and safety layer for AI agents focused on governing agent actions and tool use.
- Why Thomas should adopt it: Thomas needs a runtime policy surface that can explain why a worker action is allowed, denied, or requires approval.
- Likely Thomas integration surface: Runtime policy layer, prompt-time policy explanations, tool-call guardrails, approval workflow, and action audit trail.
- Risk/effort: Medium-high; conceptually aligned, but implementation depth needs review before it becomes more than a pattern source.
- Next implementation task shape: Compare JamJet's policy primitives against Thomas tool-call guardrails and approval states.
- Source entry reference: `2026-06-26 - JamJet policy layer`.

### 252. OpenFGA Studio Authorization Modeling UI
- Score: 81/100
- Repo URL: https://github.com/prakashm88/openfga-studio
- Feature/ability: Open-source authorization modeling interface for OpenFGA/ReBAC models, deployable for local or air-gapped experimentation.
- Why Thomas should adopt it: Thomas needs policy simulation UX before enforcing complex worker/tool permissions, especially for explaining why a claim, tool, or secret access is allowed or denied.
- Likely Thomas integration surface: Policy playground, claim-scope simulator, permission graph editor, and local/offline admin tooling.
- Risk/effort: Medium; not agent-specific, but the local modeling UI is valuable if Thomas chooses a ReBAC-style permission model.
- Next implementation task shape: Mock one claim-scope permission graph in an OpenFGA-style model and document the explanation UX Thomas would need.
- Source entry reference: `2026-06-26 - OpenFGA Studio authorization modeling UI`.

### 253. SemanticDiff Graph-Based Code Review
- Score: 81/100
- Repo URL: https://github.com/wieslawsoltes/SemanticDiff
- Feature/ability: Desktop Git diff explorer that turns repository changes into an interactive semantic graph with syntax/semantic analysis, navigation state, and GitHub/GitLab review workflows.
- Why Thomas should adopt it: Thomas workers produce patches that need fast human and agent review; graph-based semantic diff can expose blast radius better than flat patches.
- Likely Thomas integration surface: Portal diff viewer, review workspace, code-change graph, PR discussion sync, and worker-output inspection.
- Risk/effort: Medium; not agent-specific, so Thomas should use it as a review UX reference rather than an agent runtime dependency.
- Next implementation task shape: Design a code-change graph view for one Thomas worker patch and identify the minimum metadata needed.
- Source entry reference: `2026-06-26 - SemanticDiff graph-based code review`.

### 254. TraceLens LangGraph Replay Debugger
- Score: 81/100
- Repo URL: https://github.com/certainly-param/tracelens
- Feature/ability: Visual debugger and replay engine for LangGraph workflows with real-time monitoring, time-travel debugging, and interactive graph visualization.
- Why Thomas should adopt it: Even without LangGraph adoption, the visual graph plus replay pattern is useful for showing where a worker run branched, stalled, or failed.
- Likely Thomas integration surface: Worker graph visualization, orchestration replay UI, checkpoint timeline, and trace-to-graph adapter.
- Risk/effort: Medium; low adoption and framework-specific roots make it a UX reference rather than a dependency.
- Next implementation task shape: Translate one Thomas worker trace into a node/edge replay sketch and identify missing event fields.
- Source entry reference: `2026-06-26 - TraceLens LangGraph replay debugger`.

### 255. AgentPulse Self-Hosted Agent Observability
- Score: 80/100
- Repo URL: https://github.com/jstuart0/agentpulse
- Feature/ability: Self-hosted dashboard for agent cost, tokens, latency, errors, and traces.
- Why Thomas should adopt it: Worker thread growth needs lightweight cost and run visibility.
- Likely Thomas integration surface: Token/cost accounting, run dashboard, worker telemetry, and monitoring.
- Risk/effort: Medium; overlaps with AgentOps/Langfuse but has a lightweight local angle.
- Next implementation task shape: Compare AgentPulse storage model against Thomas run telemetry needs.
- Source entry reference: `2026-06-26 - AgentPulse self-hosted agent observability`.

### 256. MCP Gateway and Registry
- Score: 80/100
- Repo URL: https://github.com/agentic-community/mcp-gateway-registry
- Feature/ability: Governed control plane and registry for MCP servers, AI agents, skills, and custom assets.
- Why Thomas should adopt it: Thomas will need governable inventory for tool servers, skills, and worker roles as orchestration grows.
- Likely Thomas integration surface: Tool/skill registry, MCP server catalog, worker capability inventory, and governance dashboard.
- Risk/effort: Medium-high; auth model and deployment maturity need follow-up.
- Next implementation task shape: Draft a Thomas capability inventory model for tools, MCP servers, skills, and worker roles.
- Source entry reference: `2026-06-26 - MCP Gateway and Registry`.

### 257. Google ADK Code-First Production Agents
- Score: 80/100
- Repo URL: https://github.com/google/adk-python
- Feature/ability: Code-first toolkit for building, evaluating, and deploying production agents.
- Why Thomas should adopt it: Thomas should treat agent definitions as versioned, testable software.
- Likely Thomas integration surface: Agent definition APIs, eval runner integration, packaging, and templates.
- Risk/effort: Medium; separate portable patterns from Google-service assumptions.
- Next implementation task shape: Draft a Thomas-native agent template format.
- Source entry reference: `2026-06-26 - Google ADK code-first production agents`.

### 258. PINT Prompt-Injection Detection Benchmark
- Score: 80/100
- Repo URL: https://github.com/lakeraai/pint-benchmark
- Feature/ability: Benchmark for evaluating prompt-injection detection systems, including custom dataset tooling.
- Why Thomas should adopt it: Thomas may need a local detector or policy layer for untrusted prompts, and detector quality needs measurement.
- Likely Thomas integration surface: Prompt-injection detector evaluation, security regression datasets, web/issue ingestion filters, and tool-call approval rules.
- Risk/effort: Medium; detector-focused benchmark must be tied to downstream tool-risk outcomes.
- Next implementation task shape: Define a small prompt-injection detector evaluation set from Thomas web/issue ingestion examples.
- Source entry reference: `2026-06-26 - PINT prompt-injection detection benchmark`.

### 259. BeeAI ACP Implementation
- Score: 80/100
- Repo URL: https://github.com/i-am-bee/acp
- Feature/ability: ACP-style server implementation, SDKs, model definitions, OpenAPI spec, and examples for agent/client communication.
- Why Thomas should adopt it: It provides implementation reference material for building a real agent communication server and SDK layer.
- Likely Thomas integration surface: Agent protocol server, client SDK, remote worker bridge, and agent discoverability experiments.
- Risk/effort: Medium; follow-up should distinguish this ACP lineage from the Agent Client Protocol spec.
- Next implementation task shape: Compare BeeAI's server/client SDK layout against Thomas portal protocol needs.
- Source entry reference: `2026-06-26 - BeeAI ACP implementation`.

### 260. Accessibility-Agents Specialist Review Skills
- Score: 80/100
- Repo URL: https://github.com/Community-Access/accessibility-agents
- Feature/ability: Accessibility review agents, skills, prompts, and custom instructions with explicit real-tool verification caveats.
- Why Thomas should adopt it: Specialist reviewer packs are a practical pattern for domain-specific review lanes.
- Likely Thomas integration surface: Specialist reviewer packs, accessibility guardrails, skill verification checklist, and UI review workflows.
- Risk/effort: Low-medium; strong review pattern, but output must be verified with actual accessibility tools.
- Next implementation task shape: Draft a Thomas specialist-reviewer pack format using accessibility as the first example.
- Source entry reference: `2026-06-26 - accessibility-agents specialist review skills`.

### 261. ACP Adapter for Codex and Claude
- Score: 80/100
- Repo URL: https://github.com/beyond5959/acp-adapter
- Feature/ability: ACP adapter for Codex, Claude Code, and Pi behind a shared runtime shape.
- Why Thomas should adopt it: Thomas needs a clean adapter boundary for Codex/Claude sessions without hardcoding each provider into the portal.
- Likely Thomas integration surface: ACP provider adapters, session runtime abstraction, backend config management, and interoperability tests.
- Risk/effort: Medium; maturity needs review.
- Next implementation task shape: Compare adapter boundaries against Thomas provider/session abstractions.
- Source entry reference: `2026-06-26 - ACP adapter for Codex and Claude`.

### 262. Browser Harness Self-Healing Browser Agent Harness
- Score: 80/100
- Repo URL: https://github.com/browser-use/browser-harness
- Feature/ability: Self-healing browser-task harness for LLM agents with recovery behavior.
- Why Thomas should adopt it: Thomas browser automation should recover from common web failures and produce evidence.
- Likely Thomas integration surface: Browser worker harness, web QA task runner, recovery-loop design, and browser evidence capture.
- Risk/effort: Medium; implementation details need direct follow-up.
- Next implementation task shape: Compare recovery-loop concepts with Thomas web research and visual verification flows.
- Source entry reference: `2026-06-26 - Browser Harness self-healing browser agent harness`.

### 263. Polos AI Agent Workforce Orchestration
- Score: 80/100
- Repo URL: https://github.com/polos-dev/polos
- Feature/ability: Multi-agent workforce orchestration with task routing, agent assignment, and coordination patterns.
- Why Thomas should adopt it: Thomas visible worker lanes need role modeling, task routing, and handoff patterns that do not hard-code every lane.
- Likely Thomas integration surface: Workboard scheduling, agent role registry, task-router heuristics, and multi-worker status surfaces.
- Risk/effort: Medium-high; architecture reference is useful, but fit depends on implementation maturity.
- Next implementation task shape: Map Thomas worker roles and handoff states against Polos-style workforce concepts.
- Source entry reference: `2026-06-26 - Polos AI agent workforce orchestration`.

### 264. MASLab Multi-Agent System Comparison Codebase
- Score: 80/100
- Repo URL: https://github.com/MASWorks/MASLab
- Feature/ability: Unified codebase for comparing 20+ LLM-based multi-agent system methods with shared preprocessing and evaluation protocols.
- Why Thomas should adopt it: Thomas is accumulating orchestration patterns and needs a comparative evaluation shape for multi-agent workflows.
- Likely Thomas integration surface: Multi-agent workflow experiments, comparative eval harnesses, agent-role taxonomy, and regression fixtures for orchestration changes.
- Risk/effort: Medium-high; research-code maturity and transferability to Thomas tasks need review.
- Next implementation task shape: Use MASLab's comparison style to define two Thomas orchestration variants and a common scoring fixture.
- Source entry reference: `2026-06-26 - MASLab multi-agent system comparison codebase`.

### 265. Auth For Agents Reference App
- Score: 80/100
- Repo URL: https://github.com/baristaGeek/auth-for-agents
- Feature/ability: Reference implementation for agent-aware authentication and authorization patterns.
- Why Thomas should adopt it: Thomas workers need delegated resource access without leaking credentials or over-scoping tool calls.
- Likely Thomas integration surface: Agent identity model, delegated authorization, tool risk classification, per-action auth checks, and portal approval UX.
- Risk/effort: Medium; narrower repo is best as a design comparison rather than a direct dependency.
- Next implementation task shape: Compare its auth boundary with Thomas vault, MCP, and approval-gate requirements.
- Source entry reference: `2026-06-26 - Auth for Agents reference app`.

### 266. Claude Code Subagents Collection
- Score: 80/100
- Repo URL: https://github.com/wshobson/agents
- Feature/ability: Collection of specialized Claude Code subagents with explicit domains, prompts, and delegation patterns.
- Why Thomas should adopt it: Thomas worker roles need crisp scopes and handoff semantics; this is a practical role-granularity reference.
- Likely Thomas integration surface: Worker role registry, prompt/skill catalog, task-to-agent routing, and review-specialist templates.
- Risk/effort: Medium; prompts require audit and Thomas-specific rewrite before reuse.
- Next implementation task shape: Compare the collection's role taxonomy with Thomas worker roles and identify missing specialist lanes.
- Source entry reference: `2026-06-26 - Claude Code subagents collection`.

### 267. Deep Agents Harness
- Score: 80/100
- Repo URL: https://github.com/langchain-ai/deepagents
- Feature/ability: Batteries-included agent harness with opinionated defaults and extension points.
- Why Thomas should adopt it: Comparing against an opinionated harness can clarify which Thomas worker runtime features should be built in versus configurable.
- Likely Thomas integration surface: Agent harness architecture, default worker loop design, extension points, prompt/tool runtime conventions, and prototype comparison.
- Risk/effort: Medium; useful reference, but Thomas should avoid overfitting to one framework.
- Next implementation task shape: Compare Deep Agents default loop and extension points against Thomas native worker loop requirements.
- Source entry reference: `2026-06-26 - Deep Agents harness`.

### 268. ReplayD Deterministic Agent Replay
- Score: 80/100
- Repo URL: https://github.com/TaimoorKhan10/replayd
- Feature/ability: Replay-oriented infrastructure for deterministic evaluation and regression testing of agent behavior.
- Why Thomas should adopt it: Thomas needs replayable evidence when a worker makes a bad tool call or when a future change alters a run path.
- Likely Thomas integration surface: Run replay store, deterministic fixture generation, regression replay CLI, and workboard incident reproduction.
- Risk/effort: Medium-high; promising concept, but implementation maturity needs review.
- Next implementation task shape: Define the minimum captured data needed to replay one Thomas worker tool-call sequence.
- Source entry reference: `2026-06-26 - ReplayD deterministic agent replay`.

### 269. Kube AI SRE Agent
- Score: 80/100
- Repo URL: https://github.com/aqrpole/kube-ai-sre-agent
- Feature/ability: Kubernetes AI SRE assistant for explainable incident correlation, root-cause explanations, remediation recommendations, and policy-based safety controls.
- Why Thomas should adopt it: Thomas needs operational agents that are auditable and policy-gated rather than opaque self-healing boxes.
- Likely Thomas integration surface: Kubernetes/infra incident worker, policy-gated remediation flow, evidence pack generation, and operator approval loop.
- Risk/effort: Medium-high; implementation maturity and remediation controls need deeper review.
- Next implementation task shape: Draft a policy-gated Kubernetes incident investigation workflow for Thomas.
- Source entry reference: `2026-06-26 - Kube AI SRE Agent`.

### 270. Code Review Graph
- Score: 80/100
- Repo URL: https://github.com/tirth8205/code-review-graph
- Feature/ability: Local-first code intelligence graph for MCP and CLI focused on review workflows, context reduction, and large-repo code understanding.
- Why Thomas should adopt it: Thomas reviewers and rankers need concise impact context when many workers touch adjacent files.
- Likely Thomas integration surface: Review context graph, MCP review tools, changed-file impact map, context-reduction metrics, and code-review worker support.
- Risk/effort: Medium; maturity and benchmark claims need validation.
- Next implementation task shape: Use one recent Thomas diff to define the desired changed-file impact graph output.
- Source entry reference: `2026-06-26 - Code Review Graph`.

### 271. MobileAgent Autonomous Mobile GUI Agent
- Score: 80/100
- Repo URL: https://github.com/X-PLUG/MobileAgent
- Feature/ability: Autonomous multimodal mobile device agent using visual perception to operate mobile apps.
- Why Thomas should adopt it: MobileAgent is a concrete reference for visual GUI action loops and mobile task execution.
- Likely Thomas integration surface: Mobile QA worker, visual action planner, Android/iOS test agent research, screenshot-to-action pipeline, and GUI-agent benchmark comparison.
- Risk/effort: High; production safety and device-control boundaries need review.
- Next implementation task shape: Compare MobileAgent's perception/action loop to Thomas browser and future mobile QA worker boundaries.
- Source entry reference: `2026-06-26 - MobileAgent autonomous mobile GUI agent`.

### 272. Dynatrace AI Agent Instrumentation Examples
- Score: 80/100
- Repo URL: https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples
- Feature/ability: Example instrumentation for AI/coding agents using OpenTelemetry-style observability in a production APM ecosystem.
- Why Thomas should adopt it: Thomas needs examples of instrumenting coding agents and distributed agent systems with production observability semantics.
- Likely Thomas integration surface: Coding-agent trace schema, Dynatrace/OTel adapter comparison, local worker instrumentation examples, and cost/performance dashboards.
- Risk/effort: Medium; vendor assumptions should remain optional.
- Next implementation task shape: Extract vendor-neutral instrumentation examples for Thomas worker spans and dashboard metrics.
- Source entry reference: `2026-06-26 - Dynatrace AI agent instrumentation examples`.

### 273. TokenTelemetry Local Token Dashboard
- Score: 80/100
- Repo URL: https://github.com/VasiHemanth/tokentelemetry
- Feature/ability: Local token telemetry dashboard for tracking token usage across AI coding tools and sessions.
- Why Thomas should adopt it: Thomas needs visible token spend by run, task, model, and worker so expensive loops and low-yield automation are obvious before they become operational waste.
- Likely Thomas integration surface: Local worker usage collector, portal budget dashboard, per-agent cost attribution, model/session usage ingestion, and heartbeat budget reporting.
- Risk/effort: Medium effort and medium risk; the product value is clear, but Thomas must verify data-source compatibility and avoid brittle scraping of vendor-specific local files.
- Next implementation task shape: Build a provider-neutral usage ledger spike with synthetic Codex/Claude worker session rows and a tiny portal or CLI summary before binding to any external dashboard assumptions.
- Source entry reference: `2026-06-26 - TokenTelemetry local token dashboard`.

### 274. Upstash Semantic-Cache
- Score: 80/100
- Repo URL: https://github.com/upstash/semantic-cache
- Feature/ability: Fuzzy key-value store based on semantic similarity rather than exact lexical equality.
- Why Thomas should adopt it: Thomas needs a simple cache abstraction for repeated agent prompts where exact string matching is too brittle but uncontrolled reuse would be risky.
- Likely Thomas integration surface: Prompt/result cache layer, similarity-threshold policy, cache audit trail, vector-backed cache experiments, low-latency worker context reuse, and cache invalidation tests.
- Risk/effort: Low-medium effort and medium risk; simpler cache mechanics are useful, but Thomas must add provenance and task-safety semantics around any fuzzy hit.
- Next implementation task shape: Implement a local semantic-cache contract test with threshold tuning, forced misses for changed repo state, and audit output for why a cached answer was reused.
- Source entry reference: `2026-06-26 - Upstash semantic-cache`.

### 275. Anyscale LLM-Router Tutorial
- Score: 80/100
- Repo URL: https://github.com/anyscale/llm-router
- Feature/ability: Tutorial implementation for training a classifier-based LLM router that chooses between high-quality and lower-cost models.
- Why Thomas should adopt it: Thomas can use this as a practical recipe for training or evaluating routers against its own task corpus and cost constraints.
- Likely Thomas integration surface: Router training notebook, offline route evaluation, worker transcript dataset, cheap/strong model thresholding, and cost-savings simulation.
- Risk/effort: Low-medium effort and medium risk; tutorial scope limits direct adoption, but it is valuable as a bridge from router theory to Thomas experiments.
- Next implementation task shape: Convert the tutorial approach into a Thomas route-simulation notebook using synthetic worker tasks and explicit cost/quality labels.
- Source entry reference: `2026-06-26 - Anyscale llm-router tutorial`.

### 276. MCP Security Hub
- Score: 80/100
- Repo URL: https://github.com/FuzzingLabs/mcp-security-hub
- Feature/ability: Collection of MCP security resources, tools, and testing references for MCP server and tool hardening.
- Why Thomas should adopt it: Thomas needs MCP security and fuzzing practices alongside functional scorecards, especially before accepting third-party tools into trusted worker paths.
- Likely Thomas integration surface: MCP security checklist, fuzzing tool map, server risk scoring, onboarding policy, security regression backlog, and tool trust documentation.
- Risk/effort: Low effort and medium risk; catalog-style sources can go stale, so Thomas should use it as a source map and verify individual tools before adopting them.
- Next implementation task shape: Convert its relevant MCP security themes into a Thomas server-onboarding checklist with threat class, test tool, expected evidence, and owner.
- Source entry reference: `2026-06-26 - MCP security hub`.

### 277. Walt.id Identity
- Score: 80/100
- Repo URL: https://github.com/walt-id/waltid-identity
- Feature/ability: Open-source identity and wallet toolkit for decentralized identifiers, verifiable credentials, and OpenID4VC workflows.
- Why Thomas should adopt it: Thomas may need lightweight tooling to issue, verify, and present trust credentials for skills, agents, and work artifacts.
- Likely Thomas integration surface: Credential issuance, trust credential verification, skill publisher identity, agent wallet experiments, and portal trust badges.
- Risk/effort: Medium-high; useful toolkit, but Thomas should first decide whether VC-style identity belongs in the near-term trust model.
- Next implementation task shape: Prototype a credential metadata schema for a skill publisher without wiring runtime wallet flows.
- Source entry reference: `2026-06-26 - Walt.id identity`.

### 278. AI Agent Workforce Teams-As-Code
- Score: 80/100
- Repo URL: https://github.com/muhamadto/ai-agent-workforce
- Feature/ability: Ansible-based deployment and management of multi-model AI agent teams with integrations, task orchestration, workspace management, and model-specific agent configurations.
- Why Thomas should adopt it: Treating agent teams as infrastructure-as-code is a useful reference for reproducible worker environments instead of one-off local thread setup.
- Likely Thomas integration surface: Native worker provisioning, model-specific worker profiles, workspace setup scripts, and portal-visible team templates.
- Risk/effort: Medium-high; useful provisioning idea, but Ansible-based deployment may be heavier than Thomas's local-first setup needs.
- Next implementation task shape: Define a Thomas team-template schema for model, tools, workspace, and review role configuration.
- Source entry reference: `2026-06-26 - AI Agent Workforce teams-as-code`.

### 279. Project Cognition System Local Governance Runtime
- Score: 80/100
- Repo URL: https://github.com/yunhaichu/project-cognition-system
- Feature/ability: Local cognition governance runtime for long-running coding agents, with compact world state, evidence weighting, conflict detection, hook-friendly memory control, and stable project facts.
- Why Thomas should adopt it: Thomas needs to distinguish verified project facts from noisy chat history; its "what qualifies as a fact" framing maps to Bible-backed state and workboard recovery.
- Likely Thomas integration surface: Project-state memory, evidence weighting, conflict detection, Bible/workboard fact reconciliation, and hook-based memory updates.
- Risk/effort: Medium; low adoption, but highly aligned with Thomas's factual-state problem.
- Next implementation task shape: Define evidence-weighted project facts for Bible, workboard, git status, and worker transcripts.
- Source entry reference: `2026-06-27 - Project Cognition System local governance runtime`.

### 280. TRACE Capability-Targeted Agent Self-Improvement
- Score: 79/100
- Repo URL: https://github.com/ScalingIntelligence/TRACE
- Feature/ability: System that turns recurrent agent failures into capability-targeted training environments for environment-specific self-improvement.
- Why Thomas should adopt it: Thomas accumulates repeated worker failure patterns that should become targeted eval/training tasks instead of only postmortems.
- Likely Thomas integration surface: Failure mining, eval generation, self-improvement backlog, and training/evaluation artifacts from worker traces.
- Risk/effort: Medium-high; research-oriented and should not bypass Thomas safety gates.
- Next implementation task shape: Mine one recurring Thomas worker failure into an eval-generation sketch.
- Source entry reference: `2026-06-26 - TRACE capability-targeted agent self-improvement`.

### 281. Open-Multi-Agent TypeScript Task DAG Orchestration
- Score: 79/100
- Repo URL: https://github.com/open-multi-agent/open-multi-agent
- Feature/ability: TypeScript backend framework where a coordinator decomposes goals into task DAGs, parallelizes independent work, and synthesizes results.
- Why Thomas should adopt it: Thomas needs visible worker threads plus explicit task decomposition and result synthesis.
- Likely Thomas integration surface: Native delegation planner, workboard task decomposition, parallel worker scheduling, and result synthesis.
- Risk/effort: Medium; newer project, useful mainly as a DAG orchestration reference.
- Next implementation task shape: Sketch a Thomas task-DAG record for one multi-worker implementation request.
- Source entry reference: `2026-06-26 - open-multi-agent TypeScript task DAG orchestration`.

### 282. Monte Carlo Agent Toolkit
- Score: 79/100
- Repo URL: https://github.com/monte-carlo-data/mc-agent-toolkit
- Feature/ability: Toolkit pattern for adding observability, monitoring, triage, troubleshooting, and health checks to AI coding-agent tools.
- Why Thomas should adopt it: The packaged-toolkit shape is relevant for Thomas specialist workers that need health checks and production issue triage.
- Likely Thomas integration surface: Worker health checks, data/SRE specialist skills, observability toolkit packaging, and troubleshooting commands.
- Risk/effort: Medium; domain-specific data observability may not transfer directly to Thomas core orchestration.
- Next implementation task shape: Extract a Thomas worker-health command checklist inspired by the toolkit pattern.
- Source entry reference: `2026-06-26 - Monte Carlo agent toolkit`.

### 283. Agent Network Protocol
- Score: 79/100
- Repo URL: https://github.com/agent-network-protocol/AgentNetworkProtocol
- Feature/ability: Open protocol for secure and efficient communication among agents in a collaborative network.
- Why Thomas should adopt it: Thomas needs to reason about agent identity, discovery, trust, and collaboration before exposing external agent connectivity.
- Likely Thomas integration surface: Agent identity layer, discovery protocol research, trust model, external-agent network bridge, and protocol comparison.
- Risk/effort: Medium-high; maturity must be compared against A2A and ACP before implementation.
- Next implementation task shape: Compare ANP identity/discovery concepts against Thomas worker registry and A2A capability cards.
- Source entry reference: `2026-06-26 - Agent Network Protocol`.

### 284. Arbigent Android AI Testing Agent
- Score: 79/100
- Repo URL: https://github.com/takahirom/arbigent
- Feature/ability: Android UI test generation and execution agent that uses AI to explore app behavior.
- Why Thomas should adopt it: Thomas needs practical QA-agent references for mobile flows where tests often rot or miss visual states.
- Likely Thomas integration surface: Mobile test worker, Android UI automation, test-case generation, screenshot evidence capture, and regression test synthesis.
- Risk/effort: Medium-high; Android-specific constraints limit immediate Thomas core relevance.
- Next implementation task shape: Extract an Android UI exploration pattern and compare it to Thomas browser QA flows.
- Source entry reference: `2026-06-26 - Arbigent Android AI testing agent`.

### 285. Usage AI Coding-Agent Cost Tracker
- Score: 79/100
- Repo URL: https://github.com/aqua5230/usage
- Feature/ability: Usage and cost tracking for AI coding agents, with local reporting around developer-agent sessions.
- Why Thomas should adopt it: Thomas should connect autonomous worker outcomes to spend so retries, stuck loops, and expensive task classes can be evaluated against delivered value.
- Likely Thomas integration surface: Cost ledger, worker run accounting, task-level spend summaries, retry attribution, model/provider normalization, and portal cost panels.
- Risk/effort: Medium effort and medium risk; provider coverage, price freshness, and local-data assumptions must be validated before relying on it.
- Next implementation task shape: Compare its cost model against Thomas worker metadata and define the minimum fields needed for run_id, agent, model, input tokens, output tokens, elapsed time, and estimated cost.
- Source entry reference: `2026-06-26 - Usage AI coding-agent cost tracker`.

### 286. GoModel Go AI Gateway
- Score: 79/100
- Repo URL: https://github.com/ENTERPILOT/GOModel
- Feature/ability: Go-based OpenAI-compatible AI gateway with observability, guardrails, streaming, costs, usage tracking, and provider abstraction.
- Why Thomas should adopt it: GoModel is a compact reference for gateway UX around request/user-path cost attribution, duplicate-call handling, and lightweight self-hosted provider abstraction.
- Likely Thomas integration surface: Gateway comparison, request-path attribution, cost-by-user/team ideas, caching policy, provider abstraction, and self-hosting options.
- Risk/effort: Medium effort and medium risk; claims align well with Thomas, but the Go stack and project maturity make it more useful as a reference than as a direct dependency.
- Next implementation task shape: Compare its request attribution fields against Thomas worker metadata and decide which fields belong in a provider-neutral gateway event schema.
- Source entry reference: `2026-06-26 - GoModel Go AI gateway`.

### 287. CodeFuse ModelCache
- Score: 79/100
- Repo URL: https://github.com/codefuse-ai/ModelCache
- Feature/ability: LLM semantic caching system with cache services, multiple storage options, embedding/ranking components, and API server examples.
- Why Thomas should adopt it: Thomas can compare cache service designs for multi-worker reuse, multi-tenant cache keys, and cache hit/miss latency measurement.
- Likely Thomas integration surface: Cache service prototype, vector-store backend comparison, multi-worker shared cache, response-rank validation, and latency/cost dashboards.
- Risk/effort: Medium effort and medium risk; useful architecture reference, but project momentum and safety primitives need review before it informs implementation choices.
- Next implementation task shape: Compare ModelCache service-mode design against a Thomas local cache service with per-repo namespace, worker identity, cache provenance, and hit/miss metrics.
- Source entry reference: `2026-06-26 - CodeFuse ModelCache`.

### 288. OpenClaw Multi-Agent Test Suite
- Score: 79/100
- Repo URL: https://github.com/ThinkOffApp/openclaw-multi-agent-test-suite
- Feature/ability: Reproducible benchmark for measuring LLM performance in multi-agent environments using a staged model-capability framework.
- Why Thomas should adopt it: Thomas coordination claims should be tested under multi-agent failure modes, not inferred from single-agent task success.
- Likely Thomas integration surface: Multi-agent benchmark tasks, coordinator/reviewer scoring, staged capability rubric, route replay, and agent-collaboration regression suite.
- Risk/effort: Medium effort and medium risk; concept fit is strong, but project maturity needs review before relying on its rubric.
- Next implementation task shape: Derive a Thomas coordinator/reviewer test scenario from the staged capability framework and run it with two workers plus a reviewer transcript.
- Source entry reference: `2026-06-26 - OpenClaw multi-agent test suite`.

### 289. Agent-Skills CLI
- Score: 79/100
- Repo URL: https://github.com/Karanjot786/agent-skills-cli
- Feature/ability: CLI for creating, validating, and managing agent skills from the command line.
- Why Thomas should adopt it: Thomas needs developer ergonomics for skill creation and local validation before skills enter the marketplace or worker prompts.
- Likely Thomas integration surface: Skill authoring CLI, validation command, package scaffolding, import compatibility tests, contributor workflow docs, and marketplace preflight checks.
- Risk/effort: Medium effort and medium risk; useful workflow reference, but maturity and schema coverage need review before direct dependency.
- Next implementation task shape: Define a Thomas `skill validate` command contract with manifest checks, required files, permission declarations, examples, and optional test hooks.
- Source entry reference: `2026-06-26 - agent-skills-cli`.

### 290. GUAC Visualizer
- Score: 79/100
- Repo URL: https://github.com/guacsec/guac-visualizer
- Feature/ability: Visual interface for exploring GUAC supply-chain artifact graphs.
- Why Thomas should adopt it: Skill marketplace trust should be visible to operators, showing why a skill is trusted, risky, stale, or blocked.
- Likely Thomas integration surface: Trust graph UI, marketplace moderation dashboard, dependency risk visualization, vulnerability disclosure workflow, and provenance explorer.
- Risk/effort: Medium effort and medium risk; useful UI reference, but Thomas should build the trust data model before investing in graph visualization.
- Next implementation task shape: Sketch a Thomas marketplace trust panel that displays source, signer, provenance status, dependencies, vulnerability flags, and review state for one skill.
- Source entry reference: `2026-06-26 - GUAC visualizer`.

### 291. Agent-Auth
- Score: 79/100
- Repo URL: https://github.com/kanoniv/agent-auth
- Feature/ability: Authentication and authorization patterns for AI agents, including delegated access workflows.
- Why Thomas should adopt it: Thomas workers should not inherit broad user authority by default; they need scoped, auditable credentials and clean denial paths.
- Likely Thomas integration surface: Delegated token flow, worker credential vaulting, consent UI, access-scope prompts, and auth audit logs.
- Risk/effort: Medium; directly relevant topic, but implementation maturity and maintenance evidence need inspection.
- Next implementation task shape: Extract concrete delegated-token examples and compare them to Thomas credential-vault requirements.
- Source entry reference: `2026-06-26 - agent-auth`.

### 292. AgentReady Agentic Web Readiness Scanner
- Score: 79/100
- Repo URL: https://github.com/swarmclawai/agentready
- Feature/ability: Readiness scanner for websites, APIs, marketplaces, MCP servers, and agent services covering discovery, authentication, transactions, refunds, and safe interaction.
- Why Thomas should adopt it: Thomas could use an analogous scanner to verify its portal, docs, APIs, and MCP endpoints are agent-ready before exposing them to external agents or marketplaces.
- Likely Thomas integration surface: Release preflight, website/API checks, MCP endpoint audit, documentation quality gates, and marketplace readiness reports.
- Risk/effort: Medium; early project, but the checklist/scanner concept is useful for deployment quality.
- Next implementation task shape: Create a Thomas agent-readiness checklist for portal, docs, API, and MCP endpoint exposure.
- Source entry reference: `2026-06-26 - AgentReady agentic web readiness scanner`.

### 293. SQLite-Agent Agents Inside SQLite
- Score: 79/100
- Repo URL: https://github.com/sqliteai/sqlite-agent
- Feature/ability: SQLite extension for defining agents in SQL, giving them tools and memory, and running them locally without a separate orchestration server.
- Why Thomas should adopt it: A database-native agent execution model could be useful for small local automations, tests, and durable workflows where the datastore is also the control plane.
- Likely Thomas integration surface: Local automation runtime, test fixtures, memory-backed tools, SQL-defined worker experiments, and portable offline agents.
- Risk/effort: Medium-high; novel and relevant, but SQL as an agent-definition layer is speculative for Thomas's main worker runtime.
- Next implementation task shape: Build a small comparison note for SQLite-defined local automations versus Thomas's existing worker loop.
- Source entry reference: `2026-06-26 - SQLite-Agent agents inside SQLite`.

### 294. Agent-o-rama End-to-End Agent Platform
- Score: 78/100
- Repo URL: https://github.com/redplanetlabs/agent-o-rama
- Feature/ability: Platform for building, tracing, testing, monitoring, storing state, and deploying agents.
- Why Thomas should adopt it: Useful full-stack reference for treating trace, test, state, and deployment as one platform.
- Likely Thomas integration surface: Native orchestration architecture, trace/test/monitoring integration, and stateful storage.
- Risk/effort: Medium-high; language/runtime fit needs review.
- Next implementation task shape: Extract platform capability map and compare to Thomas orchestration gaps.
- Source entry reference: `2026-06-26 - Agent-o-rama end-to-end agent platform`.

### 295. Hugging Face Smolagents Code Agents
- Score: 78/100
- Repo URL: https://github.com/huggingface/smolagents
- Feature/ability: Minimal code-writing/tool-calling agent runtime with agents-as-tools orchestration.
- Why Thomas should adopt it: Clarifies the smallest reliable worker loop.
- Likely Thomas integration surface: Agent loop simplification, tool metadata, and worker-to-worker delegation.
- Risk/effort: Low-medium; design reference more than dependency.
- Next implementation task shape: Compare minimal loop against Thomas current loop.
- Source entry reference: `2026-06-26 - Hugging Face smolagents code agents`.

### 296. Code Index MCP
- Score: 78/100
- Repo URL: https://github.com/johnhuang316/code-index-mcp
- Feature/ability: MCP server for intelligent code indexing, advanced search, and detailed code analysis.
- Why Thomas should adopt it: Thomas can benefit from code-index search exposed to agents without forcing repeated shell greps.
- Likely Thomas integration surface: MCP code intelligence server, code review/refactor assistants, documentation generation, and architectural analysis tools.
- Risk/effort: Medium; overlaps with Carto, Claude Context, and codemogger.
- Next implementation task shape: Compare query/result shape against Thomas code-search needs and local-first constraints.
- Source entry reference: `2026-06-26 - Code Index MCP`.

### 297. Multi-Agent Debugger for API Failures
- Score: 78/100
- Repo URL: https://github.com/VishApp/multiagent-debugger
- Feature/ability: Multi-agent log/code/question debugger for root-cause analysis.
- Why Thomas should adopt it: Specialized debugging agents can inspect separate signals and synthesize one root-cause report.
- Likely Thomas integration surface: CI failure analyzer, server incident diagnostics, reviewer/coordinator templates, and log-plus-code investigation flow.
- Risk/effort: Medium; smaller project, best as pattern reference.
- Next implementation task shape: Draft a Thomas multi-signal incident investigation template.
- Source entry reference: `2026-06-26 - Multi-Agent Debugger for API failures`.

### 298. ACP UI Cross-Platform Agent Client
- Score: 78/100
- Repo URL: https://github.com/formulahendry/acp-ui
- Feature/ability: Cross-platform desktop/mobile/web client for Agent Client Protocol across Claude, Codex, Copilot, Qwen, Gemini, OpenCode, and OpenClaw-style agents.
- Why Thomas should adopt it: Thomas needs a visible portal and should study client protocol abstractions before hardwiring provider UIs.
- Likely Thomas integration surface: Thomas portal client protocol, multi-provider session UI, mobile/web companion, and agent connection registry.
- Risk/effort: Medium; early project, but useful UX/protocol reference.
- Next implementation task shape: Compare ACP UI session/connection model with Thomas portal worker visibility needs.
- Source entry reference: `2026-06-26 - ACP UI cross-platform agent client`.

### 299. Agent Device Mobile/Desktop Test Automation
- Score: 78/100
- Repo URL: https://github.com/callstack/agent-device
- Feature/ability: Device automation CLI for AI mobile app testing across iOS, Android, TV, desktop, emulators, simulators, and physical devices.
- Why Thomas should adopt it: Thomas verification may eventually span mobile and desktop apps, not just web and Python tests.
- Likely Thomas integration surface: App QA worker, mobile simulator automation, desktop app verification, and visual test evidence collection.
- Risk/effort: Medium; fresh project, but strong app-testing relevance.
- Next implementation task shape: Compare Agent Device flows with Thomas visual verification and simulator testing needs.
- Source entry reference: `2026-06-26 - Agent Device mobile/desktop test automation`.

### 300. DataSciBench Data-Science Agent Benchmark
- Score: 78/100
- Repo URL: https://github.com/THUDM/DataSciBench
- Feature/ability: Benchmark for LLM agents on data-science tasks with code, data analysis, and evaluation artifacts.
- Why Thomas should adopt it: Thomas may need agents that analyze logs, metrics, traces, and data-heavy eval outputs.
- Likely Thomas integration surface: Data-analysis worker evaluation, SRE/log analysis benchmarks, notebook/task runner, and analytics-agent regression tests.
- Risk/effort: Medium; task format and evaluator stability need follow-up.
- Next implementation task shape: Inspect task format and decide whether it can seed Thomas analytics-worker evals.
- Source entry reference: `2026-06-26 - DataSciBench data-science agent benchmark`.

### 301. Siddhant-K Agent-Trace
- Score: 78/100
- Repo URL: https://github.com/Siddhant-K-code/agent-trace
- Feature/ability: Lightweight agent observability for actions, costs, and repair opportunities.
- Why Thomas should adopt it: Low-friction telemetry helps review worker cost, decisions, and what should be fixed.
- Likely Thomas integration surface: Agent run telemetry, cost tracing, tool-call summaries, and post-run review reports.
- Risk/effort: Low-medium; very new project.
- Next implementation task shape: Compare its trace summary fields with Thomas run-log needs.
- Source entry reference: `2026-06-26 - Siddhant-K agent-trace`.

### 302. Clens Claude Code Session Capture
- Score: 78/100
- Repo URL: https://github.com/silouone/clens
- Feature/ability: Local-first session capture for Claude Code with backtrack detection, decision analysis, edit chains, and plan drift.
- Why Thomas should adopt it: Codex/Claude-style workers need plan drift and edit-chain diagnostics.
- Likely Thomas integration surface: Worker transcript analyzer, plan-drift detector, edit-chain reviewer, and local session observability.
- Risk/effort: Medium; topic-sourced and small, but conceptually close.
- Next implementation task shape: Prototype plan-drift fields in Thomas worker summaries.
- Source entry reference: `2026-06-26 - clens Claude Code session capture`.

### 303. RunbookAI Operational Agent
- Score: 78/100
- Repo URL: https://github.com/Runbook-Agent/RunbookAI
- Feature/ability: Runbook-oriented AI workflows for operational diagnosis, guided remediation, and structured incident response.
- Why Thomas should adopt it: Runbook-style plans could make recurring CI/debug tasks repeatable, reviewable, and less dependent on ad hoc prompts.
- Likely Thomas integration surface: Workboard task templates, incident/debug playbooks, CI triage lanes, and verification checklist generation.
- Risk/effort: Medium; operational framing is useful, but reusable surface may be more process/template than code.
- Next implementation task shape: Convert one recurring Thomas CI/debug workflow into a runbook template with verification gates.
- Source entry reference: `2026-06-26 - RunbookAI operational agent`.

### 304. MARTI Multi-Agent Reinforced Training
- Score: 78/100
- Repo URL: https://github.com/TsinghuaC3I/MARTI
- Feature/ability: Framework for LLM-based multi-agent reinforced training and inference with graph workflows, async tool use, reward allocation, and multi-agent tree search for code generation.
- Why Thomas should adopt it: Reward allocation, branch exploration, and async workflow ideas can inform worker strategy evaluation even if Thomas does not train models.
- Likely Thomas integration surface: Long-horizon worker policy research, reward/eval model design, branch exploration for code tasks, and strategy comparison.
- Risk/effort: High; heavyweight research approach is likely too much for direct near-term implementation.
- Next implementation task shape: Extract a lightweight branch-exploration eval idea for one Thomas coding-agent benchmark.
- Source entry reference: `2026-06-26 - MARTI multi-agent reinforced training`.

### 305. Multiclaude Parallel Agent Runner
- Score: 78/100
- Repo URL: https://github.com/dlorenc/multiclaude
- Feature/ability: Lightweight runner for launching and comparing multiple Claude Code agents or attempts in parallel.
- Why Thomas should adopt it: Parallel attempts plus structured comparison can improve coding-task reliability when scoped and costed carefully.
- Likely Thomas integration surface: Worker attempt fan-out, branch comparison, review queue, cost tracking, and merge candidate selection.
- Risk/effort: Medium; small tool, and fan-out can waste tokens unless paired with selection and stopping rules.
- Next implementation task shape: Define a Thomas two-attempt branch comparison workflow with cost and merge-candidate gates.
- Source entry reference: `2026-06-26 - Multiclaude parallel agent runner`.

### 306. Agent Memory Techniques Cookbook
- Score: 78/100
- Repo URL: https://github.com/NirDiamant/Agent_Memory_Techniques
- Feature/ability: Practical cookbook of short-term, long-term, retrieval, summarization, and implementation examples for agent memory.
- Why Thomas should adopt it: Thomas needs implementation-level comparisons for what to store, when to summarize, and how to retrieve memory safely.
- Likely Thomas integration surface: Memory design prototypes, worker context experiments, ranker comparison criteria, and test fixtures for memory behavior.
- Risk/effort: Low-medium; useful for experiments but not a production dependency.
- Next implementation task shape: Turn three cookbook patterns into small Thomas memory behavior fixtures.
- Source entry reference: `2026-06-26 - Agent Memory Techniques cookbook`.

### 307. Kubernetes AI Agent
- Score: 78/100
- Repo URL: https://github.com/carlossg/kubernetes-agent
- Feature/ability: Autonomous Kubernetes debugging and remediation agent using Google's ADK and Gemini, including logs/events analysis and PR creation for fixes.
- Why Thomas should adopt it: It connects incident diagnosis to code-change remediation, relevant for CI and deployed-service recovery.
- Likely Thomas integration surface: Infra-debug worker, ADK comparison, incident-to-PR workflow, canary/rollout analysis, and remediation review gate.
- Risk/effort: High; end-to-end autonomous remediation needs strict review gates and environment isolation.
- Next implementation task shape: Compare its incident-to-PR pattern with Thomas workboard claim, verification, and commit flow.
- Source entry reference: `2026-06-26 - Kubernetes AI Agent`.

### 308. OpenGUI GUI-Agent Framework
- Score: 78/100
- Repo URL: https://github.com/Core-Mate/OpenGUI
- Feature/ability: GUI-agent framework and resources for open-ended graphical user interface automation.
- Why Thomas should adopt it: Thomas portal and desktop-facing workflows need GUI automation ideas grounded in actual UI-state/action models.
- Likely Thomas integration surface: GUI automation research, desktop/mobile task runners, visual state abstraction, action schema design, and UI benchmark sourcing.
- Risk/effort: Medium; implementation maturity needs review.
- Next implementation task shape: Compare its action/state schema ideas against Thomas browser and portal automation events.
- Source entry reference: `2026-06-26 - OpenGUI GUI-agent framework`.

### 309. LlamaIndex Agents Observability Demo
- Score: 78/100
- Repo URL: https://github.com/run-llama/agents-observability-demo
- Feature/ability: Demo of agent observability and tracing using LlamaIndex, OpenTelemetry, and MCP-served tools.
- Why Thomas should adopt it: Compact MCP/tool tracing examples can guide Thomas observability prototypes.
- Likely Thomas integration surface: MCP tool trace prototype, LlamaIndex comparison, worker trace demo, and observability proof-of-concept.
- Risk/effort: Low-medium; demo scope limits direct implementation value.
- Next implementation task shape: Recreate the core MCP-tool trace pattern with a Thomas read-only MCP tool.
- Source entry reference: `2026-06-26 - LlamaIndex agents observability demo`.

### 310. Tokscale Multi-Tool Token Usage Tracker
- Score: 78/100
- Repo URL: https://github.com/junhoyeo/tokscale
- Feature/ability: Multi-tool token usage tracking with CLI-style reporting and spend visibility across AI coding tools.
- Why Thomas should adopt it: Thomas will likely coordinate Codex, Claude, local agents, and model gateways, so a cross-tool usage normalization pattern is more valuable than a single-provider report.
- Likely Thomas integration surface: Multi-provider usage normalization, CLI reporting, portal trend charts, budget snapshots, and worker-run cost summaries.
- Risk/effort: Medium effort and medium risk; source compatibility and durability matter because token accounting often depends on vendor-local storage formats.
- Next implementation task shape: Evaluate its source adapters and derive a Thomas-native adapter interface for usage samples, then populate it from synthetic worker ledger events first.
- Source entry reference: `2026-06-26 - Tokscale multi-tool token usage tracker`.

### 311. llm-budget Autonomous Cost Governance
- Score: 78/100
- Repo URL: https://github.com/Mattbusel/llm-budget
- Feature/ability: Autonomous cost-governance primitives for hard budget enforcement across agent fleets, including spend tracking per model, agent, and fleet.
- Why Thomas should adopt it: Thomas needs fleet-level caps that can stop low-value autonomous work before it consumes the whole run budget, especially when multiple worker attempts run in parallel.
- Likely Thomas integration surface: Fleet budget ledger, hard-stop request guard, structured cost events, per-agent spend limits, task/fleet budget inheritance, and audit-trail export.
- Risk/effort: Low-medium effort and medium-high risk; concept fit is strong, but the queue notes early maturity, so Thomas should reuse the pattern rather than depend on it directly.
- Next implementation task shape: Draft Thomas fleet-budget semantics for task budget, child-worker budget, per-model cap, emergency stop, and audit event output.
- Source entry reference: `2026-06-26 - llm-budget autonomous cost governance`.

### 312. SmarterRouter Local AI Lab Gateway
- Score: 78/100
- Repo URL: https://github.com/peva3/SmarterRouter
- Feature/ability: Intelligent LLM gateway and VRAM-aware router for Ollama, llama.cpp, and OpenAI with semantic caching, model profiling, and automatic failover.
- Why Thomas should adopt it: Thomas should understand local-model capacity and failover when deciding whether a worker step can run locally, remotely, or on a smaller model.
- Likely Thomas integration surface: Local model scheduler, VRAM-aware routing, Ollama/llama.cpp gateway, semantic cache, model profiling, and provider failover policy.
- Risk/effort: Medium effort and medium risk; the local-routing pattern is highly relevant, but repo maturity and hardware-specific assumptions make it better as a research reference than a dependency.
- Next implementation task shape: Draft a Thomas local-model routing probe that records available VRAM, model profile, context limit, task class, and fallback reason before assigning work to local or remote models.
- Source entry reference: `2026-06-26 - SmarterRouter local AI lab gateway`.

### 313. Scorecard MCP Server
- Score: 78/100
- Repo URL: https://github.com/scorecard-ai/scorecard-mcp
- Feature/ability: MCP server exposing Scorecard evaluation workflows through MCP-native tools.
- Why Thomas should adopt it: Thomas can learn how to make evaluation results available as tools that agents can query during planning, review, and handoff.
- Likely Thomas integration surface: Eval-result MCP tools, benchmark-to-workboard issue conversion, reviewer-agent evidence fetch, scorecard API adapter, and MCP-native quality gates.
- Risk/effort: Low-medium effort and medium risk; useful wrapper pattern, but value depends on Scorecard assumptions and should follow, not precede, Thomas's local eval schema.
- Next implementation task shape: Sketch a Thomas eval-results MCP tool contract that exposes latest score, failed cases, trend, and suggested workboard issue for a server or skill.
- Source entry reference: `2026-06-26 - Scorecard MCP server`.

### 314. Nano-Step Eval Harness
- Score: 78/100
- Repo URL: https://github.com/nano-step/eval-harness
- Feature/ability: Harness for defining and running repeatable AI eval cases with structured expected outputs.
- Why Thomas should adopt it: Thomas needs lightweight eval scaffolding that can turn worker failures and task examples into repeatable regression cases quickly.
- Likely Thomas integration surface: Eval case format, regression harness, task artifact conversion, expected-output assertions, score summaries, and local CI smoke tests.
- Risk/effort: Low-medium effort and medium risk; useful if simple, but Thomas should avoid introducing another eval format without mapping it to existing workboard and trace artifacts.
- Next implementation task shape: Compare its eval case structure to a Thomas task artifact and identify the minimal fields for input, expected behavior, tools allowed, and scoring.
- Source entry reference: `2026-06-26 - Nano-step eval harness`.

### 315. Softaworks Agent-Toolkit
- Score: 78/100
- Repo URL: https://github.com/softaworks/agent-toolkit
- Feature/ability: Toolkit for authoring and distributing AI agent skills, tools, and reusable agent components.
- Why Thomas should adopt it: Thomas needs authoring ergonomics for new skills so contributors can create testable, documented, portable skill packages.
- Likely Thomas integration surface: Skill authoring templates, local validation, component metadata, marketplace submission flow, and contract tests for skills.
- Risk/effort: Medium effort and medium risk; promising authoring pattern, but maturity and compatibility should be verified before direct adoption.
- Next implementation task shape: Review its authoring workflow and draft a Thomas `new skill` scaffold checklist covering README, instructions, scripts, examples, tests, permissions, and manifest fields.
- Source entry reference: `2026-06-26 - Softaworks agent-toolkit`.

### 316. Agent Skills Registry CLI
- Score: 78/100
- Repo URL: https://github.com/agentskill-sh/ags
- Feature/ability: CLI and registry tooling for discovering and installing agent skills.
- Why Thomas should adopt it: Thomas needs a clean skill installation UX with search, versioning, trust metadata, and audit trails.
- Likely Thomas integration surface: Skill registry CLI comparison, install command UX, marketplace search, trust labels, install audit logging, and rollback behavior.
- Risk/effort: Medium effort and medium risk; registry UX is relevant, but ecosystem maturity must be verified.
- Next implementation task shape: Sketch a Thomas skill install workflow covering search, preview, trust label, permissions, version pin, install log, and uninstall.
- Source entry reference: `2026-06-26 - Agent Skills registry CLI`.

### 317. Verified Agent Identity Skill
- Score: 78/100
- Repo URL: https://github.com/BillionsNetwork/verified-agent-identity
- Feature/ability: Decentralized identity skill for AI agents using DIDs, human-owner linking, attestations, and cryptographic proofs.
- Why Thomas should adopt it: It is directly about Know Your Agent patterns, but Thomas should treat it as an emerging-signal reference until ecosystem maturity and operational fit are clearer.
- Likely Thomas integration surface: Agent identity wallet, proof presentation, human-agent linkage, signed payment/request headers, and trust-label display.
- Risk/effort: Medium-high; attractive concept, but the strongest Thomas value is comparative research rather than immediate adoption.
- Next implementation task shape: Capture its agent identity claims in a trust-model comparison alongside SPIFFE, Sigstore, and VC wallet approaches.
- Source entry reference: `2026-06-26 - Verified agent identity skill`.

### 318. OAuth MCP Proxy For Go Server Auth
- Score: 78/100
- Repo URL: https://github.com/tuannvm/oauth-mcp-proxy
- Feature/ability: OAuth 2.1 authentication library for Go MCP servers with token validation/caching and adapters for multiple MCP SDKs.
- Why Thomas should adopt it: Thomas needs to understand where OAuth enforcement belongs so future tool servers do not each reinvent auth.
- Likely Thomas integration surface: Future MCP server/gateway work, tool adapter auth middleware, and token-validation test fixtures.
- Risk/effort: Medium; implementation is Go-specific, so Thomas should borrow auth-placement tests rather than the code.
- Next implementation task shape: Define language-neutral token-validation fixtures for a Thomas MCP gateway.
- Source entry reference: `2026-06-26 - OAuth MCP Proxy for Go server auth`.

### 319. Browser-Only AI Agent Builder
- Score: 78/100
- Repo URL: https://github.com/david-spies/ai-agent-builder
- Feature/ability: Backend-less single-file browser app for authoring, configuring, packaging, and auditing AI agents with offline operation, guardrails, red-team probes, audit trail, agentskills compatibility, and MCP support.
- Why Thomas should adopt it: Thomas could benefit from an offline authoring surface for skills, worker profiles, and policies, especially for safe demos and portable review artifacts.
- Likely Thomas integration surface: Skill/profile builder, offline policy editor, red-team checklist, audit-trail export, and agent package preview.
- Risk/effort: Medium; small repo with useful shape, but Thomas needs to verify package compatibility and avoid parallel builder UX.
- Next implementation task shape: Mock a single-file export format for a Thomas worker profile and skill policy review artifact.
- Source entry reference: `2026-06-26 - Browser-only AI Agent Builder`.

### 320. OpenMemory Cognitive Memory Engine
- Score: 78/100
- Repo URL: https://github.com/CaviraOSS/OpenMemory
- Feature/ability: Self-hosted cognitive memory engine for LLMs and agents, with Python/Node packages and VS Code extension support.
- Why Thomas should adopt it: Thomas needs a user-visible local memory layer that works across coding assistants and workflows, but current rewrite status argues for tracking rather than direct adoption.
- Likely Thomas integration surface: Local memory service, editor integration, worker memory APIs, self-hosted user memory, and coding-agent continuity.
- Risk/effort: Medium-high; high adoption signal but unstable rewrite state.
- Next implementation task shape: Recheck stability later and compare editor integration patterns against Thomas coding-worker memory needs.
- Source entry reference: `2026-06-27 - OpenMemory cognitive memory engine`.

### 321. Vercel Agent Browser CLI
- Score: 77/100
- Repo URL: https://github.com/vercel-labs/agent-browser
- Feature/ability: Native Rust browser automation CLI for AI agents.
- Why Thomas should adopt it: CLI-first browser automation may be safer and more context-efficient for agents.
- Likely Thomas integration surface: Browser CLI wrapper, web research workers, screenshot capture, and command sandboxing.
- Risk/effort: Medium; newer project.
- Next implementation task shape: Compare CLI model against Thomas browser commands.
- Source entry reference: `2026-06-26 - Vercel Agent Browser CLI`.

### 322. GitHub Actions Failure Analysis
- Score: 77/100
- Repo URL: https://github.com/calebevans/gha-failure-analysis
- Feature/ability: GitHub Action for semantic workflow log preprocessing, PR-change correlation, and LLM root-cause reports.
- Why Thomas should adopt it: CI failures should become actionable handoffs or reviewer notes.
- Likely Thomas integration surface: CI failure triage, GitHub Actions integration, workboard blocker reports, and automated failure summaries.
- Risk/effort: Low-medium; narrow but practical.
- Next implementation task shape: Extract a CI failure report template for Thomas checks.
- Source entry reference: `2026-06-26 - GitHub Actions Failure Analysis`.

### 323. Gideon Autonomous Security Operations Agent
- Score: 77/100
- Repo URL: https://github.com/Cogensec/Gideon
- Feature/ability: Autonomous security-operations and red-teaming agent with auditable investigation, vulnerability analysis, and hardening guidance.
- Why Thomas should adopt it: Thomas could coordinate security/SRE agents and should study auditable security workflows.
- Likely Thomas integration surface: Security operations worker, red-team investigation flow, auditable action logs, and hardening recommendation pipeline.
- Risk/effort: Medium; fresh/smaller project, should be pattern reference first.
- Next implementation task shape: Extract an auditable security investigation workflow for Thomas.
- Source entry reference: `2026-06-26 - Gideon autonomous security operations agent`.

### 324. Browser Use Box Remote Browser Automation Agent
- Score: 77/100
- Repo URL: https://github.com/browser-use/bux
- Feature/ability: Always-on remote browser automation box with chat control and real browser task execution.
- Why Thomas should adopt it: Thomas may need persistent browser workers visible from chat or portal surfaces.
- Likely Thomas integration surface: Remote browser worker, chat control channel, browser session hosting, and visible long-running web automation.
- Risk/effort: Medium; topic-sourced and requires lifecycle/security review.
- Next implementation task shape: Compare persistent browser-worker lifecycle with Thomas web research needs.
- Source entry reference: `2026-06-26 - Browser Use Box remote browser automation agent`.

### 325. Devika Open-Source Agentic Software Engineer
- Score: 77/100
- Repo URL: https://github.com/stitionai/devika
- Feature/ability: Open-source agentic software engineer that decomposes high-level objectives into research, planning, code generation, and browser-assisted execution.
- Why Thomas should adopt it: Devika is a useful reference for autonomous-dev task decomposition, browsing loops, and generated-code workflow pitfalls.
- Likely Thomas integration surface: Research-to-plan pipeline, coding worker architecture, browser/tool loop references, and autonomous-dev UX comparisons.
- Risk/effort: Medium; historically influential, but current maintenance and robustness need review.
- Next implementation task shape: Audit Devika's task decomposition loop against Thomas worker planning and browser-tool guardrails.
- Source entry reference: `2026-06-26 - Devika open-source agentic software engineer`.

### 326. D2Snap Web Automation Benchmark
- Score: 77/100
- Repo URL: https://github.com/webfuse-com/D2Snap
- Feature/ability: Web automation benchmark/data source for evaluating agents on browser tasks and page-state interaction.
- Why Thomas should adopt it: Thomas browser workers need reproducible tasks beyond ad hoc Playwright smoke tests.
- Likely Thomas integration surface: Browser-agent benchmark, web task replay, DOM/vision action evaluation, and regression test scenarios.
- Risk/effort: Medium; coverage and maintenance need review.
- Next implementation task shape: Inspect D2Snap task format and decide whether it can seed lightweight Thomas browser-agent fixtures.
- Source entry reference: `2026-06-26 - D2Snap web automation benchmark`.

### 327. Runtime Guard
- Score: 77/100
- Repo URL: https://github.com/runtimeguard/runtime-guard
- Feature/ability: Runtime guard project for AI/agent execution safety.
- Why Thomas should adopt it: Runtime guardrails are now a first-class need, but this candidate has thinner public metadata than Adrian, AgentGuard, and DACP.
- Likely Thomas integration surface: Runtime policy enforcement, execution monitor, guardrail comparison, and tool-call risk adapter.
- Risk/effort: Medium; needs deeper maturity review before prioritizing implementation work.
- Next implementation task shape: Compare its enforcement model against Adrian, AgentGuard, and DACP in a runtime guard matrix.
- Source entry reference: `2026-06-26 - Runtime Guard`.

### 328. Swarms YAML Workflow Format
- Score: 77/100
- Repo URL: https://github.com/The-Swarm-Corporation/swarms.yaml
- Feature/ability: YAML-based multi-agent workflow specification for defining agents, tools, tasks, and orchestration.
- Why Thomas should adopt it: Human-readable workflow specs could make repeatable worker teams possible without hard-coding every orchestration pattern.
- Likely Thomas integration surface: Worker-team YAML spec, workflow import/export, ranker-readable feature templates, and portal workflow editor schema.
- Risk/effort: Medium; should be compared with Zenflow and Thomas workboard semantics before adoption.
- Next implementation task shape: Draft a Thomas workflow-spec comparison table covering Swarms YAML, Zenflow, and native workboard concepts.
- Source entry reference: `2026-06-26 - Swarms YAML workflow format`.

### 329. Tokentop Terminal Usage Monitor
- Score: 77/100
- Repo URL: https://github.com/tokentopapp/tokentop
- Feature/ability: Top-like terminal monitor for live token usage and agent session activity.
- Why Thomas should adopt it: A live view of worker spend, throughput, and stuck sessions would let operators spot runaway or idle automation without opening every thread.
- Likely Thomas integration surface: `thomas top` style CLI, portal live monitor, worker heartbeat stream, token/cost counters, and active-run table.
- Risk/effort: Medium effort and medium risk; the UX idea is strong, but Thomas should drive the monitor from its own heartbeat ledger rather than depending on external terminal parsing.
- Next implementation task shape: Sketch a `thomas workers top` data contract using current heartbeat/run fields, then implement a read-only terminal table once usage and status counters are stable.
- Source entry reference: `2026-06-26 - Tokentop terminal usage monitor`.

### 330. Vercel Skills
- Score: 77/100
- Repo URL: https://github.com/vercel-labs/skills
- Feature/ability: Skill collection from Vercel Labs oriented toward agent workflows and developer tasks.
- Why Thomas should adopt it: Thomas should compare how a developer-platform team packages skills for repeatable agent use, especially for web and deployment workflows.
- Likely Thomas integration surface: Skill import compatibility, deployment/web skill templates, metadata comparison, marketplace trust review, and hosted-app workflow examples.
- Risk/effort: Low-medium effort and medium risk; relevant vendor skill set, with contents needing review before prioritization.
- Next implementation task shape: Inspect the Vercel skill layout and compare it against Anthropic Skills and Agent Skills standard compatibility requirements.
- Source entry reference: `2026-06-26 - Vercel skills`.

### 331. OpenGAP
- Score: 77/100
- Repo URL: https://github.com/open-gitagent/opengap
- Feature/ability: Open Git Agent Protocol work for coordinating repository-working agents.
- Why Thomas should adopt it: Thomas is repo-working and multi-agent, so git-agent protocol work can inform trust, handoff, and repo-scope boundaries.
- Likely Thomas integration surface: Repo-agent protocol comparison, worktree scope metadata, agent handoff records, git operation authorization, and worker prompt contracts.
- Risk/effort: Medium-high; promising direction, but maturity and overlap with Thomas's existing workboard/claim flow need review.
- Next implementation task shape: Map OpenGAP concepts to Thomas claim scopes, handoff records, and commit helper metadata.
- Source entry reference: `2026-06-26 - OpenGAP`.

### 332. Qred MCP Proxy With OAuth Sidecar
- Score: 77/100
- Repo URL: https://github.com/qred/qred-mcp-proxy
- Feature/ability: Enterprise MCP proxy with OAuth 2.1 sidecar, Google Workspace integration, one endpoint for multiple backend services, and AWS CDK deployment.
- Why Thomas should adopt it: A single managed endpoint plus standardized client config is a useful UX and operations model for non-technical users managing worker/tool access.
- Likely Thomas integration surface: Hosted MCP gateway deployment, portal-managed tool catalog, organization auth settings, and deployment runbooks.
- Risk/effort: Medium-high; useful architecture reference, but deployment-specific and with security caveats that need review before copying.
- Next implementation task shape: Capture the single-endpoint proxy pattern in Thomas hosted gateway notes without adopting its deployment stack.
- Source entry reference: `2026-06-26 - Qred MCP Proxy with OAuth sidecar`.

### 333. AgenticMail Enterprise Agent Workforce Platform
- Score: 77/100
- Repo URL: https://github.com/agenticmail/enterprise
- Feature/ability: Enterprise agent workforce platform with per-agent identity, email, calendar, browser, tools, memory, compliance, multi-tenant isolation, and GitHub issue/PR agent integration.
- Why Thomas should adopt it: The product shape is relevant for named agents with identities, communications, compliance logs, and issue/PR workflows, even if Thomas should not copy the platform.
- Likely Thomas integration surface: Worker identity model, portal-managed agent accounts, issue/PR responder workflows, compliance logs, and multi-tenant separation.
- Risk/effort: Medium-high; broad platform reference with uncertain implementation depth, so it should inform UX and identity modeling rather than near-term code.
- Next implementation task shape: Extract agent-account and compliance-log concepts into a Thomas worker identity comparison note.
- Source entry reference: `2026-06-26 - AgenticMail enterprise agent workforce platform`.

### 334. AgentHER Hindsight Experience Replay
- Score: 77/100
- Repo URL: https://github.com/alphadl/AgentHER
- Feature/ability: Hindsight Experience Replay approach for LLM agents, using failed trajectories as learning/evaluation material by relabeling or reusing experience after the fact.
- Why Thomas should adopt it: Thomas could mine failed worker runs into better prompts, policies, and regression cases instead of treating them as dead logs.
- Likely Thomas integration surface: Evolve-loop eval corpus, failed-run mining, trajectory relabeling, regression generation, and postmortem-to-test workflows.
- Risk/effort: Medium; relevant to self-improvement, but research-oriented and not ready as an implementation dependency.
- Next implementation task shape: Add failed-run mining notes to the evolve-loop evaluation backlog and define guardrails against blind promotion.
- Source entry reference: `2026-06-26 - AgentHER hindsight experience replay`.

### 335. AI Agent Rules Workflow Standardization
- Score: 77/100
- Repo URL: https://github.com/baneeishaque/ai-agent-rules
- Feature/ability: Standardized Markdown rule framework for AI-assisted development workflows covering trust, transparency, consistency, rule categories, architecture, examples, and integration guidance.
- Why Thomas should adopt it: Thomas already depends on Bible/guardrail discipline and recurring worker instructions; visible versioned rule packs can reduce hidden prompt drift.
- Likely Thomas integration surface: Worker profile rule packs, onboarding docs, prompt policy registry, skill/agent configuration, and guardrail review checklists.
- Risk/effort: Low-medium; useful packaging pattern, not a runtime dependency.
- Next implementation task shape: Define a minimal Thomas worker rule-pack template that references Bible trust order, scope, commit behavior, and verification expectations.
- Source entry reference: `2026-06-26 - AI Agent Rules workflow standardization`.

### 336. Microsoft Agent Framework
- Score: 76/100
- Repo URL: https://github.com/microsoft/agent-framework
- Feature/ability: Agent workflows with graphs, handoffs, checkpointing, and human-in-the-loop interaction.
- Why Thomas should adopt it: Microsoft's forward path after AutoGen maintenance mode is worth tracking.
- Likely Thomas integration surface: Orchestration architecture, durable workflows, and handoff guardrails.
- Risk/effort: Medium-high; needs maturity follow-up.
- Next implementation task shape: Extract stable orchestration patterns after deeper evidence pass.
- Source entry reference: `2026-06-26 - Microsoft Agent Framework`.

### 337. Firecrawl Web Agent Research Agent
- Score: 76/100
- Repo URL: https://github.com/firecrawl/web-agent
- Feature/ability: Structured autonomous web research agent with swappable models, skills, and deployable architecture.
- Why Thomas should adopt it: Thomas needs research workers that gather evidence, cite sources, and produce durable notes.
- Likely Thomas integration surface: Web research worker, source extraction, markdown evidence generation, and browser/search orchestration.
- Risk/effort: Medium; implementation depth needs follow-up.
- Next implementation task shape: Compare its flow to this ranking queue workflow.
- Source entry reference: `2026-06-26 - Firecrawl Web Agent research agent`.

### 338. AWS Operational AI Agent Sample
- Score: 76/100
- Repo URL: https://github.com/aws-samples/sample-operational-ai-agent
- Feature/ability: Operational agent sample for incident detection, monitoring, root-cause analysis, deployment verification, fixes, and notifications.
- Why Thomas should adopt it: Thomas needs operational incident patterns beyond code-edit tasks.
- Likely Thomas integration surface: Runtime monitoring, operational incident worker, deployment verification, and remediation suggestions.
- Risk/effort: Medium; AWS-specific implementation, portable pattern value.
- Next implementation task shape: Translate the incident-analysis loop into a Thomas-local operational worker sketch.
- Source entry reference: `2026-06-26 - AWS operational AI agent sample`.

### 339. UnityAgentClient ACP Editor Integration
- Score: 76/100
- Repo URL: https://github.com/nuskey8/UnityAgentClient
- Feature/ability: Unity Editor integration for ACP-compatible agents with editor/assets context and built-in MCP server support.
- Why Thomas should adopt it: Shows how ACP can embed agents into domain tools rather than forcing all work through a terminal.
- Likely Thomas integration surface: ACP adapter examples, domain-specific agent context, editor/tool integration, and MCP-backed workspace context.
- Risk/effort: Medium; specialized to Unity, mostly reference value.
- Next implementation task shape: Extract ACP domain-adapter design notes for Thomas tool/editor integrations.
- Source entry reference: `2026-06-26 - UnityAgentClient ACP editor integration`.

### 340. Kontex-CLI Local Agent Network Observability
- Score: 76/100
- Repo URL: https://github.com/pankaj-agrawalla/kontex-cli
- Feature/ability: Local HTTP proxy and dashboard for inspecting, replaying, and forking LLM calls in an agent network.
- Why Thomas should adopt it: Thomas needs local-first observability and replay controls for sensitive repo/desktop work.
- Likely Thomas integration surface: Local model-call proxy, replay/fork UI, network observability, and privacy-preserving trace store.
- Risk/effort: Medium; small project, but local proxy idea is relevant.
- Next implementation task shape: Compare local proxy/replay with Thomas privacy and trace requirements.
- Source entry reference: `2026-06-26 - kontex-cli local agent network observability`.

### 341. Evaluating AI Agents Course Repo
- Score: 76/100
- Repo URL: https://github.com/ksm26/Evaluating-AI-Agents
- Feature/ability: Hands-on course material for evaluating, debugging, and improving AI agents with observability tools, experiments, and metrics.
- Why Thomas should adopt it: Thomas needs a repeatable evaluation practice and reviewer checklist, not just scattered tool integrations.
- Likely Thomas integration surface: Agent eval playbook, reviewer/ranker methodology, worker regression criteria, and internal docs.
- Risk/effort: Low-medium; educational source is useful for process but not a direct implementation dependency.
- Next implementation task shape: Extract a Thomas eval checklist from the repo's observability and metrics exercises.
- Source entry reference: `2026-06-26 - Evaluating AI Agents course repo`.

### 342. Gas Town Claude Code Orchestration
- Score: 76/100
- Repo URL: https://github.com/gastownhall/gastown
- Feature/ability: Claude Code multi-agent orchestration patterns for coordinating task-focused agent roles.
- Why Thomas should adopt it: Lightweight local orchestration patterns may inform Thomas worker team presets and role-specific handoffs.
- Likely Thomas integration surface: Worker team presets, local orchestration conventions, task decomposition, and role-specific handoffs.
- Risk/effort: Medium; pattern value depends on maturity and maintenance quality.
- Next implementation task shape: Inspect its team/role conventions and compare against Thomas visible worker lane needs.
- Source entry reference: `2026-06-26 - Gas Town Claude Code orchestration`.

### 343. Python-A2A Library
- Score: 76/100
- Repo URL: https://github.com/themanojdesai/python-a2a
- Feature/ability: Python library for implementing Google's Agent-to-Agent protocol with interoperable agent communication patterns.
- Why Thomas should adopt it: A non-official implementation can reveal simpler API ergonomics or shortcuts compared with the official SDK.
- Likely Thomas integration surface: A2A API comparison, Python interop prototype, agent collaboration examples, and protocol ergonomics review.
- Risk/effort: Medium; official SDK should remain the primary implementation reference.
- Next implementation task shape: Compare its API ergonomics with the official A2A Python SDK for one read-only worker endpoint.
- Source entry reference: `2026-06-26 - python-a2a library`.

### 344. Weaver Multi-Agent Workflow Framework
- Score: 76/100
- Repo URL: https://github.com/sherkevin/Weaver
- Feature/ability: Multi-agent workflow framework for composing and coordinating agent roles.
- Why Thomas should adopt it: Thomas needs practical references for defining agent teams, shared context, and role-specific handoffs beyond one-off worker prompts.
- Likely Thomas integration surface: Worker role composition, multi-agent workflow patterns, role handoff schema, and workflow test fixtures.
- Risk/effort: Medium; maturity and documentation depth need inspection.
- Next implementation task shape: Compare Weaver's role composition pattern to Thomas worker role registry needs.
- Source entry reference: `2026-06-26 - Weaver multi-agent workflow framework`.

### 345. LMCache Agent Trace Corpus
- Score: 76/100
- Repo URL: https://github.com/LMCache/lmcache-agent-trace
- Feature/ability: Repository for collecting and analyzing agent application, benchmark, and workload traces.
- Why Thomas should adopt it: Thomas needs real trace corpora to test replay, caching, latency, and context-reuse strategies on agentic workloads.
- Likely Thomas integration surface: Agent trace dataset intake, replay benchmark, context-cache evaluation, and worker performance analysis.
- Risk/effort: Medium; trace corpus idea is valuable but current depth appears modest.
- Next implementation task shape: Define a Thomas trace-corpus format and compare it with LMCache trace fields.
- Source entry reference: `2026-06-26 - LMCache agent trace corpus`.

### 346. TokenBBQ AI Usage Cost Dashboard
- Score: 76/100
- Repo URL: https://github.com/offbyone1/tokenbbq
- Feature/ability: Dashboard for analyzing AI token usage, session consumption, and cost trends.
- Why Thomas should adopt it: Thomas operators need cumulative spend views by worker, repository area, task type, and model, but the dashboard should follow Thomas's local run/accounting model.
- Likely Thomas integration surface: Usage warehouse, cost dashboards, CSV/JSON export, portal analytics, run-level billing annotations, and budget review reports.
- Risk/effort: Medium effort and medium risk; dashboard patterns are reusable, but project health and model coverage need verification.
- Next implementation task shape: Use it as a UX reference while defining Thomas's own usage fact table and a first portal panel for cost by worker over time.
- Source entry reference: `2026-06-26 - TokenBBQ AI usage cost dashboard`.

### 347. Databricks Semantic-Caching
- Score: 76/100
- Repo URL: https://github.com/databricks-industry-solutions/semantic-caching
- Feature/ability: Databricks solution accelerator for semantic caching to reduce redundant AI computation and improve latency/server load.
- Why Thomas should adopt it: Thomas can study cache hit criteria and enterprise notebook patterns for scaling repeated agent queries without hiding provenance.
- Likely Thomas integration surface: Semantic-cache benchmark, cache hit/miss instrumentation, cost reduction experiment, notebook-to-service extraction, and cache provenance reporting.
- Risk/effort: Medium effort and medium risk; the pattern is useful, but platform-specific assumptions need to be separated from the portable Thomas design.
- Next implementation task shape: Extract cache measurement ideas from the accelerator into a Thomas-neutral benchmark for hit rate, latency, cost saved, and unsafe-hit rejection.
- Source entry reference: `2026-06-26 - Databricks semantic-caching`.

### 348. LLM Agents Study Trajectory Analysis
- Score: 76/100
- Repo URL: https://github.com/sola-st/llm-agents-study
- Feature/ability: Study tooling and materials for observing, analyzing, and comparing LLM agent behavior.
- Why Thomas should adopt it: Thomas should preserve enough run data to compare agent behavior across prompts, models, and tool policies rather than only final pass/fail.
- Likely Thomas integration surface: Agent trajectory analysis, behavior clustering, trace annotation schema, experiment logs, model/prompt comparison, and capability regression research.
- Risk/effort: Low-medium effort and medium risk; relevance depends on the repository contents, so it is better as a research reference than an implementation target.
- Next implementation task shape: Extract a trace annotation checklist for Thomas agent runs: decision point, context available, tool choice, outcome, error class, and reviewer note.
- Source entry reference: `2026-06-26 - LLM agents study trajectory analysis`.

### 349. Agent Skills Marketplace
- Score: 76/100
- Repo URL: https://github.com/DiversioTeam/agent-skills-marketplace
- Feature/ability: Marketplace-style repository for discovering, sharing, and organizing agent skills.
- Why Thomas should adopt it: Thomas will need a marketplace UX and review queue for skills that is searchable, categorized, and safe to install.
- Likely Thomas integration surface: Skill marketplace catalog, submission metadata, search facets, review status, trust labels, install history, and moderation workflow.
- Risk/effort: Medium effort and medium risk; marketplace concept is relevant, but implementation depth and trust model need inspection.
- Next implementation task shape: Draft a Thomas skill marketplace record format with category, compatibility, permissions, provenance, review status, trust labels, and install command.
- Source entry reference: `2026-06-26 - Agent skills marketplace`.

### 350. Microsoft Skills
- Score: 76/100
- Repo URL: https://github.com/microsoft/skills
- Feature/ability: Microsoft skill collection for agent workflows and developer productivity.
- Why Thomas should adopt it: Cross-vendor skill repositories help Thomas avoid tight coupling to one provider's skill format and expose common metadata needs.
- Likely Thomas integration surface: Skill schema comparison, import compatibility, marketplace source trust, Microsoft ecosystem adapters, and skill quality checks.
- Risk/effort: Low-medium effort and medium risk; useful if the repository structure is compatible with emerging agent-skill conventions.
- Next implementation task shape: Add it to the Thomas skill-format comparison table and identify whether it needs a custom importer or maps to common skill metadata.
- Source entry reference: `2026-06-26 - Microsoft skills`.

### 351. Predicate Systems Secure Finance Multi-Agent Demo
- Score: 76/100
- Repo URL: https://github.com/PredicateSystems/account-payable-multi-ai-agent-demo
- Feature/ability: Multi-agent finance workflow with local LLMs, authorization, deterministic verification, silent-failure detection, and policy-blocked payment release.
- Why Thomas should adopt it: The blocked-action and deterministic-verification pattern maps well to Thomas workboard/commit gates and other high-impact task blockers.
- Likely Thomas integration surface: Workboard gate explanations, run verification receipts, local-model workflow tests, and policy-block evidence in task timelines.
- Risk/effort: Low-medium; demo-sized repository limits direct adoption, but it can inspire focused verification fixtures.
- Next implementation task shape: Convert the policy-blocked payment idea into a Thomas-style gate fixture for one irreversible action.
- Source entry reference: `2026-06-26 - Predicate Systems secure finance multi-agent demo`.

### 352. YokeBot AI Agent Workforce Workspace
- Score: 76/100
- Repo URL: https://github.com/yokebots/yokebot
- Feature/ability: Agent workforce workspace with pre-built agents, skills, multiple models, browser automation, voice meetings, production workflows, shared context, goals, calendar, and real-time collaboration.
- Why Thomas should adopt it: It is a concrete product-shape reference for organizing agent teams as a workspace rather than isolated chats.
- Likely Thomas integration surface: Thomas portal worker dashboard, shared task context, calendar/goal surfaces, skill catalog, and browser-automation worker lanes.
- Risk/effort: Medium-high; broad and low-adoption, so it should inform workspace UX rather than near-term runtime architecture.
- Next implementation task shape: Compare YokeBot's workspace surfaces to Thomas portal needs for shared context, goals, and visible workers.
- Source entry reference: `2026-06-26 - YokeBot AI agent workforce workspace`.

### 353. Room Peer-To-Peer Signed Agent Transcripts
- Score: 76/100
- Repo URL: https://github.com/agree-able/room
- Feature/ability: Lightweight peer-to-peer bot communication protocol with identity verification and complete signed chat transcripts.
- Why Thomas should adopt it: Thomas's inter-worker lanes need durable evidence of who said what and when; signed transcripts are useful for cross-agent accountability and replay.
- Likely Thomas integration surface: Inter-agent message bus, workboard lane audit, signed transcript export, peer worker identity, and offline coordination tests.
- Risk/effort: Low-medium; the concept is relevant, but the repo is small and older.
- Next implementation task shape: Define a signed transcript export format for one Thomas workboard lane conversation.
- Source entry reference: `2026-06-26 - Room peer-to-peer signed agent transcripts`.

### 354. Microsoft Semantic Kernel Multi-Agent Orchestration
- Score: 75/100
- Repo URL: https://github.com/microsoft/semantic-kernel
- Feature/ability: Model-agnostic SDK for AI agents and multi-agent systems.
- Why Thomas should adopt it: Mature plugin/function abstraction reference.
- Likely Thomas integration surface: Tool/plugin schema, orchestration definitions, and long-running process workflows.
- Risk/effort: Medium; overlap with Microsoft Agent Framework needs mapping.
- Next implementation task shape: Compare plugin/function contracts to Thomas tool schemas.
- Source entry reference: `2026-06-26 - Microsoft Semantic Kernel multi-agent orchestration`.

### 355. Replay MCP Time-Travel Debugging
- Score: 75/100
- Repo URL: https://github.com/replayio/replay-mcp
- Feature/ability: MCP tool surface for inspecting Replay recordings with console output, source, variables, React components, and performance data.
- Why Thomas should adopt it: Thomas UI/browser workers could inspect replayable debug recordings instead of only screenshots and logs.
- Likely Thomas integration surface: Browser/UI debug MCP, replay recording analysis, frontend failure investigation, and time-travel debugging.
- Risk/effort: Medium; evidence came from docs, repository/source follow-up needed.
- Next implementation task shape: Test whether Replay MCP can support one Thomas frontend failure-investigation workflow.
- Source entry reference: `2026-06-26 - Replay MCP time-travel debugging`.

### 356. L2MAC Automatic Computer Framework
- Score: 75/100
- Repo URL: https://github.com/samholt/l2mac
- Feature/ability: LLM Automatic Computer Framework for constructing computer-use agents and action loops.
- Why Thomas should adopt it: L2MAC adds a framework-level view of automatic computer interaction to Thomas's browser, GUI, and computer-use references.
- Likely Thomas integration surface: Computer-use worker architecture, action loop abstraction, UI-control comparisons, and GUI-agent benchmark wiring.
- Risk/effort: Medium-high; activity and robustness need review before borrowing patterns.
- Next implementation task shape: Compare its computer-use loop with Thomas browser tool and GUI-agent evaluation needs.
- Source entry reference: `2026-06-26 - L2MAC automatic computer framework`.

### 357. Medical Pre-Authorization Multi-Agent Decision Audit
- Score: 75/100
- Repo URL: https://github.com/aniket-work/medical-preauth-agent
- Feature/ability: Multi-agent prior-authorization workflow with policy analyst, clinical reviewer, decision engine, confidence score, rationale, and explainable audit trail.
- Why Thomas should adopt it: The domain is unrelated, but the parse-policy, extract-evidence, decide, and explain-denial pattern can transfer to workboard gates and policy denial UX.
- Likely Thomas integration surface: Gate rationale generation, workboard verification receipts, policy-document parsing, and denial explanation templates.
- Risk/effort: Low-medium; useful as a pattern demo, not a dependency.
- Next implementation task shape: Adapt the auditable decision workflow into a Thomas gate-rationale template for one blocked action.
- Source entry reference: `2026-06-26 - Medical pre-authorization multi-agent decision audit`.

### 358. Adam Embeddable C Agent Library
- Score: 75/100
- Repo URL: https://github.com/sqliteai/adam
- Feature/ability: Embeddable cross-platform C agent loop with cloud/local LLMs, tool calling, memory, sessions, voice, streaming, structured output, research mode, and self-evolving loops.
- Why Thomas should adopt it: Thomas may eventually need lightweight local agents embedded in desktop, mobile, offline, or WASM contexts, but this is farther from current Python/server surfaces.
- Likely Thomas integration surface: Local desktop runtime, offline helper agents, portable test harnesses, WASM/mobile experiments, and low-level session/memory primitives.
- Risk/effort: High; portability signal is useful, but direct adoption would be a major runtime bet.
- Next implementation task shape: Track as a portability reference and extract any session/memory primitives that could inform future local helper agents.
- Source entry reference: `2026-06-26 - Adam embeddable C agent library`.

### 359. OpenHands Platform and Agent Canvas
- Score: 74/100
- Repo URL: https://github.com/OpenHands/openhands
- Feature/ability: Cloud coding-agent platform and visual workflow control direction.
- Why Thomas should adopt it: Product direction overlaps with visible worker threads and portal-native orchestration.
- Likely Thomas integration surface: Portal task delegation UI, worker visibility, and task-to-repo flow.
- Risk/effort: Medium; main-repo transition lowers immediate confidence.
- Next implementation task shape: Compare Agent Canvas UX with Thomas portal delegation states.
- Source entry reference: `2026-06-26 - OpenHands platform and Agent Canvas`.

### 360. Agentmemory Shared Coding-Agent Memory Server
- Score: 74/100
- Repo URL: https://github.com/rohitg00/agentmemory
- Feature/ability: Persistent coding-agent memory server through hooks, MCP, and REST.
- Why Thomas should adopt it: Shared memory could reduce rediscovery across visible workers.
- Likely Thomas integration surface: Worker bootstrap hooks, MCP memory service, shared repo facts, and workboard task memory.
- Risk/effort: Medium; conflict handling and trust levels need scrutiny.
- Next implementation task shape: Inspect storage semantics and draft a shared-memory trust model.
- Source entry reference: `2026-06-26 - agentmemory shared coding-agent memory server`.

### 361. Actions AI Advisor
- Score: 74/100
- Repo URL: https://github.com/ratibor78/actions-ai-advisor
- Feature/ability: GitHub Action that cleans failed workflow logs, extracts file paths, and publishes markdown root-cause analysis.
- Why Thomas should adopt it: File-link and log-noise-reduction patterns are useful for concise repair tasks.
- Likely Thomas integration surface: CI log summarizer, failed-check reviewer, workboard incident entry, and test failure report.
- Risk/effort: Low; low-star but concrete mechanics.
- Next implementation task shape: Reuse its report shape as inspiration for Thomas failed-check summaries.
- Source entry reference: `2026-06-26 - Actions AI Advisor`.

### 362. DesktopAgent Safety-First Local Automation
- Score: 74/100
- Repo URL: https://github.com/alessiobianchini/DesktopAgent
- Feature/ability: Safety-first local desktop automation with cross-platform core, OS adapters, UI-tree-first automation, OCR fallback, tray chat UI, and auto-updates.
- Why Thomas should adopt it: Thomas can learn from UI-tree-first control and OS adapter isolation for local actions.
- Likely Thomas integration surface: Desktop control worker, permission UI, OS adapter boundaries, and local automation safety model.
- Risk/effort: Medium; small project and desktop automation remains high-risk.
- Next implementation task shape: Extract a Thomas desktop-action permission model from UI-tree-first automation patterns.
- Source entry reference: `2026-06-26 - DesktopAgent safety-first local automation`.

### 363. Awesome-Copilot Agent Supply-Chain Skill
- Score: 74/100
- Repo URL: https://github.com/github/awesome-copilot
- Feature/ability: GitHub skill library with an agent supply-chain integrity skill covering manifests, version pinning, tamper detection, and provenance.
- Why Thomas should adopt it: Thomas needs explicit manifest and provenance patterns around skills/tools.
- Likely Thomas integration surface: Skill manifest format, plugin provenance, marketplace integrity checks, and installation policy.
- Risk/effort: Low-medium; official reference, but a skill/checklist rather than a runtime.
- Next implementation task shape: Draft a Thomas skill manifest/provenance checklist from the supply-chain skill.
- Source entry reference: `2026-06-26 - awesome-copilot agent supply-chain skill`.

### 364. Apigee Semantic Cache Sample
- Score: 74/100
- Repo URL: https://github.com/GoogleCloudPlatform/apigee-samples
- Feature/ability: Apigee sample set including an LLM semantic-cache notebook and API-proxy examples for gateway-side cache measurement.
- Why Thomas should adopt it: Gateway-side cache experiments should include repeat-prompt measurement, latency visualization, and deployment policy examples, even if Thomas does not adopt Apigee.
- Likely Thomas integration surface: API gateway cache comparison, semantic-cache measurement notebook, gateway policy examples, cache performance charts, and enterprise proxy research.
- Risk/effort: Low-medium effort and medium risk; it is sample-focused rather than an agent framework, so its main value is measurement scaffolding and proxy-policy reference.
- Next implementation task shape: Pull out the measurement dimensions into Thomas's semantic-cache evaluation checklist: repeat rate, similarity threshold, latency change, cost savings, and policy bypass rate.
- Source entry reference: `2026-06-26 - Apigee semantic cache sample`.

### 365. NPM AgentSkills
- Score: 74/100
- Repo URL: https://github.com/onmax/npm-agentskills
- Feature/ability: NPM-oriented distribution path for agent skills.
- Why Thomas should adopt it: Thomas may need to distribute or consume skills through common package managers, not only git URLs or internal registries.
- Likely Thomas integration surface: Skill package distribution, npm install workflow, semantic versioning, lock-file metadata, supply-chain scanning, and package provenance.
- Risk/effort: Low-medium effort and medium risk; narrow distribution reference, but package-manager compatibility will matter if skills become portable artifacts.
- Next implementation task shape: Draft package-manager requirements for Thomas skills: version pinning, lockfile, integrity hash, provenance, permissions, and install sandbox.
- Source entry reference: `2026-06-26 - npm-agentskills`.

### 366. Agent Protocols Legal Research
- Score: 74/100
- Repo URL: https://github.com/harvard-lil/agent-protocols
- Feature/ability: Research and prototype materials around safe, auditable, accountable agent interactions.
- Why Thomas should adopt it: Thomas should preserve accountability metadata when workers exchange tasks, credentials, evidence, and decisions.
- Likely Thomas integration surface: Agent protocol source map, accountability metadata, audit log schema, consent records, and trust-aware handoff design.
- Risk/effort: Low implementation risk but medium adoption risk; this is research-heavy and should inform governance rather than drive code.
- Next implementation task shape: Pull accountability metadata ideas into the trust-model notes and identify which fields belong in Thomas handoff events.
- Source entry reference: `2026-06-26 - Agent protocols legal research`.

### 367. Smartnose Deterministic Policy Enforcer Demo
- Score: 74/100
- Repo URL: https://github.com/smartnose/policy-enforcer
- Feature/ability: LangChain ReAct agent demo with deterministic business-rule enforcement, explainable failures, state tracking, and prompted-vs-external policy comparison.
- Why Thomas should adopt it: It reinforces that prompt rules are insufficient and that blocked tool/action explanations should be available to users and reviewers.
- Likely Thomas integration surface: Tool policy tests, approval-denial explanation templates, rule-engine adapters, and agent safety docs.
- Risk/effort: Low; useful as a small demo pattern, but too narrow to become a primary implementation dependency.
- Next implementation task shape: Build a minimal denial-explanation fixture comparing prompt-only and external-policy enforcement.
- Source entry reference: `2026-06-26 - Smartnose deterministic policy enforcer demo`.

### 368. Cyanheads Repo-Map Repository Summaries
- Score: 73/100
- Repo URL: https://github.com/cyanheads/repo-map
- Feature/ability: AI-enhanced repo summaries of structure, file purposes, and cross-language considerations.
- Why Thomas should adopt it: Could bootstrap worker context and reduce repeated exploration.
- Likely Thomas integration surface: Repository onboarding, worker context packs, Bible drift assistance, and research summaries.
- Risk/effort: Low-medium; more documentation-oriented than Carto.
- Next implementation task shape: Generate a comparison sample against Thomas Bible companion needs.
- Source entry reference: `2026-06-26 - cyanheads repo-map repository summaries`.

### 369. Awesome-Agent-Failures Failure Mode Catalog
- Score: 73/100
- Repo URL: https://github.com/vectara/awesome-agent-failures
- Feature/ability: Curated catalog of known AI agent failure modes, real-world failures, mitigation strategies, and related resources.
- Why Thomas should adopt it: Thomas needs a durable failure-mode checklist close to worker/reviewer design.
- Likely Thomas integration surface: Reviewer checklist, agent risk taxonomy, security/eval backlog, and documentation for worker failure patterns.
- Risk/effort: Low; catalog only, but useful for taxonomy and test ideas.
- Next implementation task shape: Extract a Thomas reviewer checklist section from the highest-relevance failure categories.
- Source entry reference: `2026-06-26 - awesome-agent-failures failure mode catalog`.

### 370. AI Agent Benchmark Compendium
- Score: 73/100
- Repo URL: https://github.com/philschmid/ai-agent-benchmark-compendium
- Feature/ability: Curated compendium of 50+ agent benchmarks across tool use, reasoning, coding/software engineering, and computer interaction.
- Why Thomas should adopt it: The ranker needs benchmark coverage criteria so feature ideas map to evidence categories instead of anecdotal appeal.
- Likely Thomas integration surface: Research taxonomy, ranking criteria, benchmark selection for worker features, and gap analysis for Thomas evals.
- Risk/effort: Low; it is a research map, not an implementation dependency.
- Next implementation task shape: Tag current top-25 ranking entries with benchmark categories from the compendium.
- Source entry reference: `2026-06-26 - AI agent benchmark compendium`.

### 371. cc-statistics Claude Code Session Analytics
- Score: 73/100
- Repo URL: https://github.com/androidZzT/cc-statistics
- Feature/ability: Local Claude Code session analytics with usage, session statistics, and token/cost summaries.
- Why Thomas should adopt it: Provider-specific analytics can inform Thomas's session-history UX, especially around elapsed time, budget burn-down, and local history ingestion, but it should not become the central accounting design.
- Likely Thomas integration surface: Claude/Codex worker session parser, portal analytics cards, budget warning thresholds, local history ingestion, and provider-specific adapter tests.
- Risk/effort: Low-medium effort and medium risk; useful as a narrow reference, but the Claude Code focus limits direct architectural leverage for Thomas's multi-agent target.
- Next implementation task shape: Review the session parsing approach and extract a provider-adapter checklist for Thomas usage ingestion without adopting provider-specific assumptions globally.
- Source entry reference: `2026-06-26 - cc-statistics Claude Code session analytics`.

### 372. Tech Leads Club Agent-Skills
- Score: 73/100
- Repo URL: https://github.com/tech-leads-club/agent-skills
- Feature/ability: Curated agent-skill repository oriented around software engineering leadership and developer workflows.
- Why Thomas should adopt it: Thomas should test skill import compatibility against multiple real-world skill repositories, including community-maintained workflow packs.
- Likely Thomas integration surface: Skill import compatibility tests, community skill quality rubric, trust-label defaults, marketplace moderation queue, and category mapping.
- Risk/effort: Low effort and medium risk; useful as a compatibility sample set, but direct implementation value depends on repository depth and quality.
- Next implementation task shape: Use it as one fixture in a Thomas skill-import compatibility test suite and record any missing metadata, unsafe assumptions, or conversion gaps.
- Source entry reference: `2026-06-26 - Tech Leads Club agent-skills`.

### 373. Repo Atlas Persistent Agent On-Ramp Docs
- Score: 72/100
- Repo URL: https://github.com/cathrynlavery/repo-atlas
- Feature/ability: Skill-driven repository atlas docs for agent onboarding.
- Why Thomas should adopt it: Can inspire generated supplements without displacing the Bible as truth.
- Likely Thomas integration surface: Repo onboarding docs, worker briefing generation, Codex review pass, and Bible companion artifacts.
- Risk/effort: Low-medium; smaller project.
- Next implementation task shape: Draft a Thomas Bible companion artifact outline.
- Source entry reference: `2026-06-26 - Repo Atlas persistent agent on-ramp docs`.

### 374. OpenAI Agents SDK for JavaScript/TypeScript
- Score: 72/100
- Repo URL: https://github.com/openai/openai-agents-js
- Feature/ability: TypeScript SDK for agent workflows with tracing and handoff concepts.
- Why Thomas should adopt it: Could inform frontend timeline object shapes.
- Likely Thomas integration surface: `thomas/server/web/js/*`, delegation visualization, and live task timeline.
- Risk/effort: Low-medium; follow Python trace model unless JS adds UI value.
- Next implementation task shape: Derive a frontend timeline view model.
- Source entry reference: `2026-06-26 - OpenAI Agents SDK for JavaScript/TypeScript`.

### 375. AG2 AgentOS Multi-Agent Framework
- Score: 72/100
- Repo URL: https://github.com/ag2ai/ag2
- Feature/ability: Cooperative agents, conversation patterns, tool use, human-in-loop workflows, and autonomous solving.
- Why Thomas should adopt it: Practical AutoGen lineage can inform visible-worker/reviewer conversations.
- Likely Thomas integration surface: Conversation manager, handoff policy, and approval checkpoints.
- Risk/effort: Medium; distinguish from Microsoft Agent Framework first.
- Next implementation task shape: Compare AG2 patterns to Thomas message-lane semantics.
- Source entry reference: `2026-06-26 - AG2 AgentOS multi-agent framework`.

### 376. Awesome-AI-Sandboxes Provider Catalog
- Score: 72/100
- Repo URL: https://github.com/tizkovatereza/awesome-ai-sandboxes
- Feature/ability: Curated list of cloud sandbox providers for AI agents.
- Why Thomas should adopt it: Thomas needs to compare local, cloud, and hybrid sandbox options without one-off infrastructure choices.
- Likely Thomas integration surface: Sandbox provider evaluation, worker isolation roadmap, deployment planning, and cost/security comparison.
- Risk/effort: Low; catalog only.
- Next implementation task shape: Use it to seed a sandbox provider comparison matrix.
- Source entry reference: `2026-06-26 - awesome-ai-sandboxes provider catalog`.

### 377. Xacpx Remote ACP Session Control
- Score: 72/100
- Repo URL: https://github.com/gadzan/xacpx
- Feature/ability: Remote ACP agent-session control for Codex, Claude Code, and Gemini from chat channels without a terminal.
- Why Thomas should adopt it: Thomas portal/chat control may need remote commands and visible agent status from non-terminal surfaces.
- Likely Thomas integration surface: Chat-to-agent bridge, remote session controls, no-terminal worker monitoring, and ACP command routing.
- Risk/effort: Medium; smaller topic-sourced project.
- Next implementation task shape: Compare xacpx remote commands with Thomas chat/portal worker controls.
- Source entry reference: `2026-06-26 - xacpx remote ACP session control`.

### 378. GenAI Agents Implementation Tutorial Library
- Score: 72/100
- Repo URL: https://github.com/NirDiamant/GenAI_Agents
- Feature/ability: Broad tutorial and implementation library covering conversational agents, multi-agent systems, RAG, workflows, and practical patterns.
- Why Thomas should adopt it: Useful for pattern mining and prototype comparison before building custom features.
- Likely Thomas integration surface: Research backlog, prototype references, implementation examples, and ranker follow-up targets.
- Risk/effort: Low; broad examples can distract unless converted into specific implementation tickets.
- Next implementation task shape: Mine three concrete patterns from the library and create separate queue entries only when they map to Thomas surfaces.
- Source entry reference: `2026-06-26 - GenAI Agents implementation tutorial library`.

### 379. Awesome Agent Security
- Score: 72/100
- Repo URL: https://github.com/ucsb-mlsec/Awesome-Agent-Security
- Feature/ability: Curated security and safety threat catalog for LLM-enabled agents.
- Why Thomas should not adopt it directly: It is a catalog, not an implementation, but useful for threat coverage and future targeted checks.
- Likely Thomas integration surface: Security research queue, tool-risk taxonomy, threat-model checklist, ranker criteria, and red-team test sourcing.
- Risk/effort: Low; value depends on converting catalog items into concrete Thomas checks.
- Next implementation task shape: Extract a Thomas agent-threat checklist covering prompt injection, tool misuse, data leakage, and autonomy risks.
- Source entry reference: `2026-06-26 - Awesome Agent Security`.

### 380. Awesome Agent Skills Security
- Score: 72/100
- Repo URL: https://github.com/LLMSecurity/awesome-agent-skills-security
- Feature/ability: Curated resources on agent skills security, including attacks, defenses, frameworks, and benchmarks for securing tool use and skill ecosystems.
- Why Thomas should not adopt it directly: It is a catalog for coverage and threat-model breadth, not a direct implementation candidate.
- Likely Thomas integration surface: Skill supply-chain research, security checklist, benchmark sourcing, ranker criteria, and future targeted scanner searches.
- Risk/effort: Low; useful after mining concrete tools and benchmarks.
- Next implementation task shape: Extract concrete skill-security scanners and benchmarks into separate queue entries.
- Source entry reference: `2026-06-26 - Awesome Agent Skills Security`.

### 381. VoltAgent Awesome Agent Skills
- Score: 72/100
- Repo URL: https://github.com/VoltAgent/awesome-agent-skills
- Feature/ability: Curated source map of agent skills and skill ecosystems across providers.
- Why Thomas should adopt it: Thomas needs broad skill ecosystem awareness to avoid building a closed skill format without migration or import paths.
- Likely Thomas integration surface: Skill ecosystem source map, import candidate backlog, compatibility taxonomy, marketplace seed catalog, and duplicate detection.
- Risk/effort: Low effort and medium risk; catalog-style resources are useful for discovery but can go stale quickly.
- Next implementation task shape: Use it as a source map to identify skill package formats Thomas should explicitly support, reject, or convert.
- Source entry reference: `2026-06-26 - VoltAgent awesome agent skills`.

### 382. MHN AI Agent Memory Deterministic Associative Recall
- Score: 72/100
- Repo URL: https://github.com/shahzebqazi/mhn-ai-agent-memory
- Feature/ability: Deterministic associative memory for AI agents using Modern Hopfield Networks, with no LLM calls, no database, and MCP support for coding agents.
- Why Thomas should adopt it: It is a useful counterexample to vector-search plus LLM summarization, but it labels itself toy/research and should stay exploratory.
- Likely Thomas integration surface: Experimental memory backend, deterministic recall tests, offline coding-agent memory, MCP memory adapter, and benchmark comparisons against vector stores.
- Risk/effort: Medium; low production confidence, but small enough for a bounded benchmark experiment.
- Next implementation task shape: Add to memory-backend comparison notes as a deterministic recall baseline, not a near-term dependency.
- Source entry reference: `2026-06-27 - MHN AI Agent Memory deterministic associative recall`.

### 383. CAMEL Large-Scale Multi-Agent Society
- Score: 71/100
- Repo URL: https://github.com/camel-ai/camel
- Feature/ability: Research framework for agent societies, role-playing, toolkits, memory, and simulated environments.
- Why Thomas should adopt it: Useful for scaling beyond single-worker loops.
- Likely Thomas integration surface: Worker team templates, memory-backed context, and multi-agent eval harnesses.
- Risk/effort: Medium-high; reference only.
- Next implementation task shape: Extract team-pattern ideas for Thomas roles.
- Source entry reference: `2026-06-26 - CAMEL large-scale multi-agent society`.

### 384. Awesome Self-Evolving Agents Survey Repository
- Score: 71/100
- Repo URL: https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents
- Feature/ability: Survey-backed catalog of self-evolving agent systems, concepts, datasets, and evaluation directions.
- Why Thomas should not adopt it directly: It is a source list and safety research input, not a feature implementation.
- Likely Thomas integration surface: Research intake, self-improvement roadmap, eval taxonomy, and ranker source material for evolution features.
- Risk/effort: Low; useful only after extracting concrete candidates and anti-patterns.
- Next implementation task shape: Mine the survey for specific self-improvement mechanisms with strong evaluation evidence.
- Source entry reference: `2026-06-26 - Awesome Self-Evolving Agents survey repository`.

### 385. Awesome Memory For Agents Catalog
- Score: 71/100
- Repo URL: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- Feature/ability: Research catalog of memory mechanisms, datasets, benchmarks, and systems for LLM agents.
- Why Thomas should not adopt it directly: It is a source map, not an implementation surface, though it can improve future memory ranking.
- Likely Thomas integration surface: Research taxonomy, memory benchmark selection, ranker inputs, and memory architecture gap analysis.
- Risk/effort: Low; individual sources need later filtering.
- Next implementation task shape: Use it to identify benchmark-backed memory systems not already represented in the queue.
- Source entry reference: `2026-06-26 - Awesome Memory for Agents catalog`.

### 386. Awesome AI Agents Security
- Score: 71/100
- Repo URL: https://github.com/ProjectRecon/awesome-ai-agents-security
- Feature/ability: Security-lifecycle catalog for autonomous AI agents covering red teaming, runtime protection, sandboxing, and governance.
- Why Thomas should not adopt it directly: It is a discovery index for lifecycle protections rather than a feature candidate.
- Likely Thomas integration surface: Agent security lifecycle checklist, governance backlog, runtime-protection source discovery, and red-team candidate sourcing.
- Risk/effort: Low; broad catalog needs follow-up filtering.
- Next implementation task shape: Map its lifecycle categories to existing Thomas guardrails and note missing protection phases.
- Source entry reference: `2026-06-26 - Awesome AI Agents Security`.

### 387. Awesome Claude Skills
- Score: 71/100
- Repo URL: https://github.com/ComposioHQ/awesome-claude-skills
- Feature/ability: Curated collection of Claude skills and skill examples for different tools and workflows.
- Why Thomas should adopt it: Thomas can mine common skill categories, metadata expectations, and install risks from the emerging Claude Skills ecosystem.
- Likely Thomas integration surface: Skill category taxonomy, marketplace seed entries, trust review checklist, skill import compatibility, and examples for Thomas documentation.
- Risk/effort: Low effort and medium risk; discovery-heavy lists should inform taxonomy rather than drive implementation directly.
- Next implementation task shape: Sample the collection for recurring skill categories and derive candidate marketplace facets for Thomas skill search and review.
- Source entry reference: `2026-06-26 - Awesome Claude Skills`.

### 388. Mini-SWE-Agent Minimal Coding Agent
- Score: 70/100
- Repo URL: https://github.com/SWE-agent/mini-swe-agent
- Feature/ability: Small command-line coding agent for SWE-bench-style tasks.
- Why Thomas should adopt it: Baseline for smallest reliable repo worker.
- Likely Thomas integration surface: Agent loop cleanup, worker bootstrap, and simple issue-to-fix mode.
- Risk/effort: Low; design probe.
- Next implementation task shape: Use it in a loop simplification review.
- Source entry reference: `2026-06-26 - mini-SWE-agent minimal coding agent`.

### 389. GUI Agents Paper List
- Score: 70/100
- Repo URL: https://github.com/OSU-NLP-Group/GUI-Agents-Paper-List
- Feature/ability: Curated GUI-agent papers, benchmarks, environments, and task domains.
- Why Thomas should adopt it: GUI-agent roadmap and benchmark coverage should be systematic.
- Likely Thomas integration surface: GUI-agent research backlog, desktop benchmark selection, safety/eval matrix, and computer-use roadmap.
- Risk/effort: Low; catalog/reference only.
- Next implementation task shape: Use it to expand the GUI-agent benchmark shortlist.
- Source entry reference: `2026-06-26 - GUI Agents Paper List`.

### 390. Awesome-Agent-Harness Engineering Resources
- Score: 70/100
- Repo URL: https://github.com/Picrew/awesome-agent-harness
- Feature/ability: Curated harness-engineering resources spanning frameworks, tools, benchmarks, and reliability guides.
- Why Thomas should adopt it: Thomas is becoming a native agent harness and needs systematic coverage of harness patterns.
- Likely Thomas integration surface: Research backlog, ranker input, harness pattern comparison, and reliability roadmap.
- Risk/effort: Low; catalog only.
- Next implementation task shape: Use it to seed a Thomas harness-pattern checklist.
- Source entry reference: `2026-06-26 - awesome-agent-harness engineering resources`.

### 391. Awesome-Harness-Engineering
- Score: 70/100
- Repo URL: https://github.com/ai-boost/awesome-harness-engineering
- Feature/ability: Awesome list for AI agent harness engineering across tools, evals, memory, MCP, permissions, observability, and orchestration.
- Why Thomas should adopt it: It organizes the systems concerns Thomas must handle across permissions, memory, evals, and orchestration.
- Likely Thomas integration surface: Harness architecture research, queue/ranking input, permission/eval comparison, and feature taxonomy.
- Risk/effort: Low; catalog only.
- Next implementation task shape: Cross-check Thomas ranking categories against this harness taxonomy.
- Source entry reference: `2026-06-26 - awesome-harness-engineering`.

### 392. General Agents Benchmark Catalog
- Score: 70/100
- Repo URL: https://github.com/supernalintelligence/Awesome-General-Agents-Benchmark
- Feature/ability: Curated list of general-agent benchmarks for evaluating broad agent capabilities across tasks and environments.
- Why Thomas should not adopt it directly: It is a broad benchmark index; Thomas should use it to discover targeted benchmark candidates rather than treating it as a feature.
- Likely Thomas integration surface: Benchmark taxonomy, evaluation backlog, ranker scoring rubric, and worker capability coverage map.
- Risk/effort: Low; value depends on filtering individual benchmarks for Thomas relevance.
- Next implementation task shape: Identify three non-coding benchmarks that could test Thomas tool use, planning, or memory.
- Source entry reference: `2026-06-26 - General agents benchmark catalog`.

### 393. Computer Browser Phone Use Agent Datasets
- Score: 69/100
- Repo URL: https://github.com/Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets
- Feature/ability: Curated dataset and benchmark list for computer-use, browser-use, and phone-use agents.
- Why Thomas should adopt it: Future automation should be evaluated across browser, desktop, and phone tasks.
- Likely Thomas integration surface: Agent benchmark backlog, desktop/mobile/browser eval selection, and QA automation roadmap.
- Risk/effort: Low; catalog quality needs follow-up.
- Next implementation task shape: Use it to select candidate benchmark datasets for Thomas automation.
- Source entry reference: `2026-06-26 - Computer Browser Phone Use Agent Datasets`.

### 394. Awesome Code-as-Agent Harness Papers
- Score: 69/100
- Repo URL: https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers
- Feature/ability: Paper list around harness interfaces, mechanisms, scaling, coding assistants, GUI/OS automation, scientific discovery, and embodied agents.
- Why Thomas should adopt it: Gives Thomas a theory-backed view of harness layers before adopting disconnected tools.
- Likely Thomas integration surface: Research queue taxonomy, architecture notes, benchmark selection, and long-term agent runtime roadmap.
- Risk/effort: Low; research catalog.
- Next implementation task shape: Use it to refine Thomas's harness-layer taxonomy.
- Source entry reference: `2026-06-26 - Awesome Code-as-Agent Harness Papers`.

### 395. Awesome Devins Autonomous Software Engineer Catalog
- Score: 69/100
- Repo URL: https://github.com/e2b-dev/awesome-devins
- Feature/ability: Curated catalog of Devin-inspired autonomous software-engineering agents.
- Why Thomas should not adopt it directly: It is a discovery map, not a feature implementation.
- Likely Thomas integration surface: Research intake, ranking taxonomy, coding-agent comparison matrix, sandbox pattern discovery, and future targeted repo searches.
- Risk/effort: Low; catalog quality varies and must be converted into concrete candidates.
- Next implementation task shape: Mine the catalog for three high-evidence autonomous coding-agent repos not already in the ranking.
- Source entry reference: `2026-06-26 - Awesome Devins autonomous software engineer catalog`.

### 396. Awesome Graph Memory
- Score: 69/100
- Repo URL: https://github.com/DEEP-PolyU/Awesome-GraphMemory
- Feature/ability: Curated graph-memory resources for LLMs and agents, including graph-based reasoning and retrieval systems.
- Why Thomas should not adopt it directly: It is a catalog for graph-memory research, not a feature implementation.
- Likely Thomas integration surface: Graph-memory research intake, project dependency memory, workboard relationship modeling, and retrieval architecture comparisons.
- Risk/effort: Low; value depends on extracting concrete graph-memory candidates.
- Next implementation task shape: Mine concrete graph-memory repos that support temporal facts, provenance, or codebase relationships.
- Source entry reference: `2026-06-26 - Awesome Graph Memory`.

### 397. Awesome SRE Agents Catalog
- Score: 69/100
- Repo URL: https://github.com/last9/awesome-sre-agents
- Feature/ability: Curated list of AI-powered DevOps and SRE agents, tools, and resources for reliability automation.
- Why Thomas should not adopt it directly: It is a discovery catalog rather than an implementation candidate.
- Likely Thomas integration surface: Research intake, SRE-agent taxonomy, operational benchmark sourcing, and future targeted searches for Thomas incident workflows.
- Risk/effort: Low; useful only after extracting concrete, high-evidence operational-agent repos.
- Next implementation task shape: Use it to seed targeted searches for incident triage, observability, and safe remediation tools.
- Source entry reference: `2026-06-26 - Awesome SRE Agents catalog`.

### 398. Claude Skills Collection
- Score: 69/100
- Repo URL: https://github.com/alirezarezvani/claude-skills
- Feature/ability: Community collection of Claude-compatible skills with practical examples across workflows.
- Why Thomas should adopt it: Community skill collections reveal real packaging patterns, naming conventions, and quality variance that Thomas should handle during import and review.
- Likely Thomas integration surface: Skill import parser, community quality checks, trust metadata defaults, compatibility warnings, marketplace review queue, and unsafe-skill rejection rules.
- Risk/effort: Low effort and medium risk; useful as a sample set, but not a core dependency and quality variance should be assumed.
- Next implementation task shape: Run a manual sampling pass to catalog common community-skill defects: missing manifest, unclear permissions, brittle scripts, no examples, or unsafe instructions.
- Source entry reference: `2026-06-26 - Claude skills collection`.

### 399. Awesome MCP Servers Ecosystem Directory
- Score: 68/100
- Repo URL: https://github.com/punkpeye/awesome-mcp-servers
- Feature/ability: Curated directory of MCP servers across categories.
- Why Thomas should adopt it: Useful reconnaissance for safe, high-value tool integrations and marketplace thinking.
- Likely Thomas integration surface: Marketplace/tool catalog, MCP allowlist, capability discovery UI, and research backlog.
- Risk/effort: Low; directory, not runtime.
- Next implementation task shape: Use it to seed a vetted MCP integration shortlist.
- Source entry reference: `2026-06-26 - awesome-mcp-servers ecosystem directory`.

### 400. Awesome GUI Agent
- Score: 68/100
- Repo URL: https://github.com/showlab/awesome-gui-agent
- Feature/ability: Curated list of multi-modal GUI-agent papers, projects, and resources.
- Why Thomas should adopt it: Useful wider discovery source before committing to desktop automation architecture.
- Likely Thomas integration surface: GUI-agent research backlog, model/tool comparison, visual automation roadmap, and evaluation matrix.
- Risk/effort: Low; catalog only.
- Next implementation task shape: Use it to cross-check GUI-agent research coverage.
- Source entry reference: `2026-06-26 - Awesome GUI Agent`.

### 401. Awesome AI Memory
- Score: 68/100
- Repo URL: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- Feature/ability: Broad AI memory resource collection covering memory architectures, evaluation, and agent memory systems.
- Why Thomas should not adopt it directly: It is a broad discovery source rather than an implementation candidate.
- Likely Thomas integration surface: Research intake, memory-system shortlist, benchmark mapping, and ranker evidence sources.
- Risk/effort: Low; broad catalogs can dilute focus unless converted into specific candidates.
- Next implementation task shape: Use it only to seed targeted memory benchmark and implementation searches.
- Source entry reference: `2026-06-26 - Awesome AI Memory`.

### 402. Awesome A2A Catalog
- Score: 68/100
- Repo URL: https://github.com/pab1it0/awesome-a2a
- Feature/ability: Curated list of A2A agents, tools, servers, clients, and examples.
- Why Thomas should not adopt it directly: It is a discovery map, not an implementation candidate.
- Likely Thomas integration surface: Research intake, A2A ecosystem taxonomy, agent-card examples, server/client discovery, and ranker source material.
- Risk/effort: Low; catalog quality varies and should feed targeted follow-up searches.
- Next implementation task shape: Mine concrete A2A servers or clients with strong evidence and add them as separate queue candidates.
- Source entry reference: `2026-06-26 - Awesome A2A catalog`.

### 403. Issue AI Agent GitHub Triage Action
- Score: 67/100
- Repo URL: https://github.com/alexyan0431/issue-ai-agent
- Feature/ability: GitHub Action for issue classification, labeling, duplicate detection, and contextual replies.
- Why Thomas should adopt it: Maps to future issue-to-workboard intake and coordinator triage.
- Likely Thomas integration surface: GitHub issue ingestion, workboard task creation, triage labels, and coordinator prompts.
- Risk/effort: Low-medium; narrow and smaller project.
- Next implementation task shape: Extract issue intake fields for a Thomas workboard task template.
- Source entry reference: `2026-06-26 - Issue AI Agent GitHub triage action`.

### 404. Awesome-LLM-AIOps Incident-Agent Research Map
- Score: 67/100
- Repo URL: https://github.com/Jun-jie-Huang/awesome-LLM-AIOps
- Feature/ability: Curated research map for LLM-based incident management, postmortems, log analysis, and infrastructure management.
- Why Thomas should adopt it: Useful research source for future incident/postmortem agents and log-analysis benchmarks.
- Likely Thomas integration surface: Research backlog, incident-agent roadmap, log-analysis evals, and operational worker design.
- Risk/effort: Low; catalog, not implementation.
- Next implementation task shape: Use it to seed an incident-agent research shortlist.
- Source entry reference: `2026-06-26 - awesome-LLM-AIOps incident-agent research map`.

### 405. Agent Blackboard Shared Coordination Memory
- Score: 66/100
- Repo URL: https://github.com/claudioed/agent-blackboard
- Feature/ability: Blackboard-pattern multi-agent coordination with MCP shared knowledge, specialized agents, coordinator, and search.
- Why Thomas should adopt it: Pattern reference for shared cross-agent state.
- Likely Thomas integration surface: Workboard/message lane evolution, shared memory, coordinator state, and task decomposition records.
- Risk/effort: Medium; lower apparent maturity than major frameworks.
- Next implementation task shape: Use as a design reference, not a direct dependency.
- Source entry reference: `2026-06-26 - Agent Blackboard shared coordination memory`.

### 406. LLM Agents Papers Catalog
- Score: 66/100
- Repo URL: https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- Feature/ability: Broad paper catalog for LLM-based agents covering memory, planning, tool use, and multi-agent systems.
- Why Thomas should adopt it: Provides durable research backstop for future agent architecture choices.
- Likely Thomas integration surface: Long-term research backlog, ranking evidence, architecture survey, and planned-feature citations.
- Risk/effort: Low; broad catalog, not implementation.
- Next implementation task shape: Use it only for deeper evidence passes on high-ranked categories.
- Source entry reference: `2026-06-26 - LLM Agents Papers catalog`.

### 407. Awesome_AI_Agents Broad Agent Catalog
- Score: 66/100
- Repo URL: https://github.com/jim-schwoebel/awesome_ai_agents
- Feature/ability: Curated hub of AI-agent tools, frameworks, datasets, projects, and workflows.
- Why Thomas should not adopt it directly: It is a discovery source rather than a feature or implementation substrate.
- Likely Thomas integration surface: Research backlog source, ranking input, feature taxonomy, and ongoing dedupe discovery.
- Risk/effort: Low; value depends on extracting concrete repo candidates instead of treating the catalog itself as implementation work.
- Next implementation task shape: Use it as a seed list for future targeted searches, not as a Thomas feature ticket.
- Source entry reference: `2026-06-26 - awesome_ai_agents broad agent catalog`.

### 408. Awesome-Web-Agents Browser-Agent Catalog
- Score: 65/100
- Repo URL: https://github.com/steel-dev/awesome-web-agents
- Feature/ability: Curated catalog of browser automation APIs, trace viewers, and web interaction frameworks.
- Why Thomas should adopt it: Helps keep browser-agent research systematic rather than tied to one implementation.
- Likely Thomas integration surface: Browser-tool research backlog, web-agent evaluation matrix, trace viewer comparisons, and browser worker capability planning.
- Risk/effort: Low; catalog only.
- Next implementation task shape: Use it to build a browser-agent comparison matrix.
- Source entry reference: `2026-06-26 - awesome-web-agents browser-agent catalog`.

## Score Rubric

Candidates are scored from 0-100 using these factors:

- Direct Thomas value: how clearly the feature improves Thomas as an agentic software-building system.
- Implementation leverage: whether the feature unlocks repeated downstream wins rather than a narrow one-off.
- Maturity/evidence: quality of repository evidence, usage, maintainability, and proof that the idea works.
- Fit with Thomas architecture: alignment with current Thomas runtime, forge/anvil, tools, workboard, verification, and guardrail patterns.
- Safety/guardrail compatibility: whether the feature can preserve Thomas's public Bible truth model, verification discipline, private-marker rules, and self-evolve isolation requirements.
- Effort/risk: implementation complexity, blast radius, security exposure, and likelihood of creating brittle or fake-roadmap work.

## Recently Ranked

- 2026-06-26 14:21 UTC: Ranked 12 raw queue entries. Top three: OpenAI Agents SDK for Python (94), LangGraph durable agent graphs (92), OpenHands software agent SDK (90).
- 2026-06-26 14:25 UTC: Ranked 19 new raw queue entries and merged them into the sorted list. Highest-ranked additions: SWE-bench repository issue benchmark (91), AIO Sandbox unified agent workspace (89), Letta advanced agent memory (88), Langfuse open-source LLM observability and evals (87), Inspect AI eval framework (87).
- 2026-06-26 14:32 UTC: Ranked 17 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Microsoft Agent Governance Toolkit (90), Open Policy Agent for agent tool policy (88), Carto structural codebase intelligence (86), AgentTrace local-first agent debugger (86), PR-Agent automated pull request reviewer (84).
- 2026-06-26 14:43 UTC: Ranked 10 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Pipelock AI agent firewall (89), Agentgateway AI-native proxy (88), AgentSeal local agent security scanner (87), Snyk Agent Scan (86), promptfoo agent evals and red teaming (86).
- 2026-06-26 14:43 UTC: Ranked 9 more raw queue entries that arrived during the heartbeat. Highest-ranked additions: InjecAgent indirect prompt-injection benchmark (86), AgentDebug failure taxonomy and recovery (85), Claude Context semantic code-search MCP (85), Open Prompt Injection toolkit (84), codemogger local code indexing MCP (82).
- 2026-06-26 14:54 UTC: Ranked 8 live raw queue entries and merged them into the sorted list. Highest-ranked additions: TraceRoot production agent debugging (86), codebase-memory-mcp structural knowledge graph (84), Zeroshot autonomous engineering team (84), Multi-Agent Debugger for API failures (78), GitHub Actions Failure Analysis (77).
- 2026-06-26 15:03 UTC: Ranked 6 new raw queue entries and merged them into the sorted list. Highest-ranked additions: NVIDIA SkillSpector (87), AgentGuard supply-chain command interceptor (87), Agent S computer-use framework (82), ACP UI cross-platform agent client (78), DesktopAgent safety-first local automation (74).
- 2026-06-26 15:03 UTC: Ranked 6 more raw queue entries that arrived during the heartbeat. Highest-ranked additions: Agent Client Protocol schema and SDKs (85), OSU AgentSafety GUI agent benchmark (84), Agent Desktop accessibility-tree CLI (83), CUA computer-use agent infrastructure (83), BeeAI ACP implementation (80).
- 2026-06-26 15:06 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: rivet sandbox-agent remote coding-agent control (88), VS Code ACP client extension (82), accessibility-agents specialist review skills (80), UnityAgentClient ACP editor integration (76), awesome-ai-sandboxes provider catalog (72).
- 2026-06-26 15:20 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: GitTaskBench repository-aware code-agent benchmark (89), ACP Bridge multi-agent orchestrator (86), Lightpanda AI-native browser (84), AIRTBench autonomous AI red-team benchmark (83), ACP adapter for Codex and Claude (80).
- 2026-06-26 15:33 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: OpenACP messaging bridge for coding agents (87), Browser MCP browser automation server (85), codex-acp bridge (82), Browser Harness self-healing browser agent harness (80), awesome-agent-harness engineering resources (70).
- 2026-06-26 15:39 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Playwright MCP official browser server (88), agent-replay execution trace replay (86), mcp-browser-use persistent browser-use MCP (83), Siddhant-K agent-trace (78), clens Claude Code session capture (78).
- 2026-06-26 15:47 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: CyberArk Agent Guard secrets and MCP proxy (89), Dreadnode Agent Lens (87), CyberArk agentwatch observability (86), Agent PR Replay (86), AgentReplay local desktop evals and memory (85).
- 2026-06-26 15:47 UTC: Queue grew during the heartbeat; ranked 8 more raw queue entries. Highest-ranked additions: Agent Policy Engine hard action boundaries (88), Cordum open agent control plane (87), Phoenix AI observability and evaluation (87), Neuledge Context local-first documentation MCP (84), Context7 up-to-date code docs MCP (84).
- 2026-06-26 16:17 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Cognee memory engine (88), Delegate multi-agent worktree orchestration (87), AgentGate human approval layer (86), AI Agent checkpoint and resume (84), agent-memory-mcp persistent memory server (82).
- 2026-06-26 16:17 UTC: Queue grew during final verification; ranked 8 more raw queue entries. Highest-ranked additions: Parallel Code worktree agent UI (89), Agent Orchestrator feedback-loop supervisor (88), Task Orchestrator MCP quality gates (87), Task Graph MCP multi-agent coordination (86), Agent Tool Protocol sandboxed code tools (86).
- 2026-06-26 16:57 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: EvoAgentX self-evolving agent workflows (86), Agentic Reliability Framework (84), AgentBench dynamic reasoning infrastructure benchmark (82), MASLab multi-agent system comparison codebase (80), MARTI multi-agent reinforced training (78).
- 2026-06-26 17:21 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Arcade MCP authorized tool calling (88), Scenario agentic testing framework (86), Inngest AgentKit deterministic multi-agent routing (86), LangWatch evaluations and agent testing (85), Mastra TypeScript agent framework (84).
- 2026-06-26 17:30 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: CopilotKit agent-native frontend stack (87), AWS CLI Agent Orchestrator (87), BMAD Method structured AI development agents (84), Claude Code subagents collection (80), Multiclaude parallel agent runner (78).
- 2026-06-26 17:38 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Mem0 universal agent memory layer (89), Graphiti temporal knowledge graph memory (88), Memori agent-native memory infrastructure (85), MemOS self-evolving memory operating system (84), Agent Memory Techniques cookbook (78).
- 2026-06-26 17:46 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: AgentEvals trajectory evaluators (87), EvalView behavior regression gate (86), Agent Sandbox Taxonomy (84), LangChain Agent Evals scripts (81), Deep Agents harness (80).
- 2026-06-26 17:54 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: DBOS Durable OpenAI Agents (88), Restate durable AI examples (87), OpenSRE AI SRE framework (85), Azure Durable Agents samples (83), Temporal AI Agent workflow demo (83).
- 2026-06-26 18:05 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: AG-UI agent-user interaction protocol (89), A2A agent-to-agent protocol (88), A2A Python SDK (86), A2A JavaScript SDK (82), A2A protocol samples (81).
- 2026-06-26 18:12 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Symbol Delta Ledger MCP (87), CodeGraph local semantic code intelligence (86), Sourcebot codebase intelligence (85), Axon code knowledge graph (84), CodeGraphContext local graph MCP (83).
- 2026-06-26 18:22 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: VisualWebArena visual web-agent benchmark (85), browser-use benchmark (84), ClawBench mobile GUI-agent benchmark (82), Open Operator Evals (82), MobileAgent autonomous mobile GUI agent (80).
- 2026-06-26 18:32 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Adrian runtime agent security monitor (89), Deterministic Agent Control Protocol (88), GoPlus AgentGuard (87), Agent Threat Rules (86), Panguard AI agent security platform (84).
- 2026-06-26 18:40 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: DeerFlow long-horizon SuperAgent harness (88), DSPy declarative self-improving programs (87), Dify agentic workflow platform (84), Zenflow declarative multi-agent workflow engine (83), Reyn constrained workflow OS (82).
- 2026-06-26 18:48 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: OpenLIT AI engineering observability (88), OpenLLMetry OpenTelemetry LLM observability (87), Latitude agent monitoring platform (86), traceAI OpenTelemetry tracing framework (85), OpenLLMetry JS/TS observability (82).
- 2026-06-26 19:02 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: GenAI OpenTelemetry semantic conventions (90), Cursor agent-trace coding-agent observability (87), TokenTelemetry local token dashboard (80), Usage AI coding-agent cost tracker (79), Tokscale multi-tool token usage tracker (78).
- 2026-06-26 19:09 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: LiteLLM spend management gateway (91), Portkey AI gateway guardrails (89), Helicone LLM observability and cost control (88), Bifrost AI gateway (86), Shekel LLM budget control (84).
- 2026-06-26 19:21 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: GPTCache semantic cache for LLMs (88), verified semantic cache for LLM agents (87), vLLM semantic router (87), Envoy AI Gateway (86), Higress AI Gateway (84).
- 2026-06-26 19:33 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: RouteLLM router serving and evaluation (89), UIUC LLMRouter (87), LMCache reusable KV cache layer (85), OpenZiti zero-trust LLM gateway (84), NVIDIA LLM Router Blueprint (82).
- 2026-06-26 19:45 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: BenchFlow universal agent evaluation environments (90), SkillsBench skill-use benchmark (89), Accenture MCP-Bench (88), Salesforce MCP-Universe (86), AgentBench function-calling agent benchmark (85).
- 2026-06-26 19:58 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Scorecard MCP Eval (89), LastMile MCP Eval (87), Stagehand browser automation framework (85), OSWorld-V2 computer-use benchmark (84), MCP Atlas (83).
- 2026-06-26 20:06 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Agent contracts (88), MCP Inspector (87), MCP server fuzzer (86), agent-native research artifact provenance (84), Why agents fail sample (82).
- 2026-06-26 20:25 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Microsoft eval-recipes (90), Vercel agent-eval (89), Microsoft eval-guide (88), DeepEval LLM eval framework (87), IBM CLEAR (86).
- 2026-06-26 20:36 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Anthropic skills (88), NVIDIA skills (82), AWS Agent Toolkit (81), Softaworks agent-toolkit (78), Agent skills marketplace (76).
- 2026-06-26 20:50 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Agent Skills open standard (89), Addy Osmani agent-skills (82), Web quality skills (81), agent-skills-cli (79), Agent Skills registry CLI (78).
- 2026-06-26 21:02 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Sigstore cosign (90), in-toto attestations (89), SLSA GitHub Generator (88), GUAC supply-chain graph (87), Trusted Agent Protocol (86).
- 2026-06-26 21:16 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: OpenFGA fine-grained authorization (89), SPIRE workload identity (88), Cedar policy language (87), Microsoft identity-spiffe (86), OpenFGA MCP server (84).
- 2026-06-26 21:30 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: MCP OAuth proxy (86), Generative Agent Protocol (84), Open Agent Auth (83), MCP GitHub OAuth (82), JamJet policy layer (81).
- 2026-06-26 21:44 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Enforra local-first tool-call policy enforcement (89), Sigbit MCP Auth Proxy (86), AthenZ MCP OAuth Proxy (84), Babs MCP Auth Proxy (82), OAuth MCP Proxy for Go server auth (78).
- 2026-06-26 21:54 UTC: Ranked 8 new raw queue entries and merged them into the sorted list. Highest-ranked additions: SpiceDB fine-grained authorization database (88), Mandate runtime authority enforcement (85), Proxilion runtime security SDK (83), Nerve self-hosted agent runtime (82), OpenFGA Studio authorization modeling UI (81).
- 2026-06-26 22:05 UTC: Ranked 7 new raw queue entries and merged them into the sorted list. Highest-ranked additions: AI Agents governed software-development system (88), Diffity agent-agnostic diff review (87), Agent Teams AI desktop multi-team workspace (84), SemanticDiff graph-based code review (81), AI Agent Workforce teams-as-code (80).
- 2026-06-26 22:16 UTC: Ranked 9 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Oktsec local agent action security layer (90), Agent Audit static scanner for LLM agents (89), DashClaw governance runtime (88), LibreChat self-hosted agent and MCP portal (86), Parley recovery-first coordination state (85).
- 2026-06-26 22:27 UTC: Ranked 6 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Agent Replay local trace time-travel debugger (90), AgentProbe cassette regression safety net (88), Agent VCR editable execution replay (86), AgentLens MCP-native agent DevTools (84), TraceLens LangGraph replay debugger (81).
- 2026-06-27 04:15 UTC: Ranked 9 new raw queue entries and merged them into the sorted list. Highest-ranked additions: Engram persistent memory for coding agents (89), SQLite-Memory offline-first agent memory (88), Repobase AI repo index with MCP server (86), EverOS portable user-owned memory layer (85), SimpleMem lifelong multimodal agent memory (84).
- 2026-06-27 04:15 UTC: Ranked 10 new raw queue entries that arrived during final verification and merged them into the sorted list. Highest-ranked additions: MemClaw cross-fleet governed memory (88), Memoirs local conflict-resolved agent memory (87), Nocturne rollbackable MCP long-term memory (86), Reflect Memory user-authored privacy-first memory (85), Recall MCP-native self-hosted memory (84).

## Rejected or Deferred

- AutoGen: Deferred as a primary target because the raw queue notes the GitHub page says it is in maintenance mode and points toward Microsoft Agent Framework as the newer direction.

## Run Log

- 2026-06-26: Initial pass verified `C:\Users\corbe\Thomas` exists and is a git repository, read the beginning of `docs/THOMAS_BIBLE.md`, and wrote a waiting-state ranking file because the raw queue was absent at that time.
- 2026-06-26 14:21 UTC: Heartbeat pass found `plans/thomas/AGENTIC_AI_FEATURE_RESEARCH_QUEUE.md` with 12 raw entries and ranked all 12. Existing worktree dirt and unrelated claims were left untouched.
- 2026-06-26 14:25 UTC: Heartbeat pass found 19 additional raw entries, ranked them, and updated this file to 31 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 14:32 UTC: Heartbeat pass found 17 additional raw entries, ranked them, and updated this file to 48 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 14:43 UTC: Heartbeat pass found 10 additional raw entries, ranked them, and updated this file to 58 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 14:43 UTC: Queue grew during the heartbeat; ranked 9 additional entries and updated this file to 67 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 14:54 UTC: Heartbeat pass reconciled against the live queue, removed stale entries that disappeared from the queue, ranked 8 live unranked entries, and updated this file to 75 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:03 UTC: Heartbeat pass found 6 additional raw entries, ranked them, and updated this file to 81 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:03 UTC: Queue grew during the heartbeat; ranked 6 additional entries and updated this file to 87 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:06 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 95 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:20 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 103 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:33 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 111 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:39 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 119 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:47 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 127 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 15:47 UTC: Queue grew during the heartbeat; ranked 8 additional entries and updated this file to 135 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 16:17 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 143 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 16:17 UTC: Queue grew during final verification; ranked 8 additional entries and updated this file to 151 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 16:57 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 159 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 17:21 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 167 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 17:30 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 175 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 17:38 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 183 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 17:46 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 191 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 17:54 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 199 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:05 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 207 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:12 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 215 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:22 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 223 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:32 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 231 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:40 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 239 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 18:48 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 247 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:02 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 255 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:09 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 263 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:21 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 271 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:33 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 279 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:45 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 287 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 19:58 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 295 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 20:06 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 303 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 20:25 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 311 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 20:36 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 319 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 20:50 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 327 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 21:02 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 335 total ranked candidates. Existing worktree dirt was left untouched.
- 2026-06-26 21:16 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 343 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 21:30 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 351 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 21:44 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 359 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 21:54 UTC: Heartbeat pass found 8 additional raw entries, ranked them, and updated this file to 367 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 22:05 UTC: Heartbeat pass found 7 additional raw entries, ranked them, and updated this file to 374 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 22:16 UTC: Heartbeat pass found 9 additional raw entries, ranked them, and updated this file to 383 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-26 22:27 UTC: Heartbeat pass found 6 additional raw entries, ranked them, and updated this file to 389 total ranked candidates. No active claim existed, so commit scope used the explicit fallback for this rankings file.
- 2026-06-27 04:15 UTC: Heartbeat pass found 9 additional raw entries, ranked them, and updated this file to 398 total ranked candidates. Existing unrelated workboard claims were left untouched; no active claim covered this rankings file, so commit scope used the explicit fallback.
- 2026-06-27 04:15 UTC: Final verification saw the raw queue advance by 10 more entries, ranked them, and updated this file to 408 total ranked candidates. The raw queue was left dirty and uncommitted because it was not this ranker's edit.








































