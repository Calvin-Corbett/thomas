# Agentic AI Feature Research Queue

Research-only queue for agentic AI repositories and implementation ideas Thomas may consider. This file is intentionally unranked; prioritization belongs to the ranker thread.

## Raw Research Queue

### 2026-06-26 - LangGraph durable agent graphs

- Repo URL: https://github.com/langchain-ai/langgraph
- Repo name: langchain-ai/langgraph
- Feature or ability Thomas should consider: Durable graph-based agent execution with checkpointing, resumable runs, human-in-the-loop state inspection, and long-running workflow support.
- Why it matters for Thomas: Thomas already has long-running delegated work, visible worker threads, and dirty-repo coordination pressure. LangGraph's explicit state graph model is a strong reference for making runs resumable and inspectable instead of depending on ad hoc loop state.
- Integration surface guess: `thomas/agent/loop_core.py`, `thomas/forge/anvil/*dispatch*`, delegation session state, and any future native orchestration dashboard.
- Evidence/source URL: https://github.com/langchain-ai/langgraph
- Date found: 2026-06-26
- Confidence note: High. Active, widely used framework; evidence page explicitly highlights durable execution, memory, and human-in-the-loop control.

### 2026-06-26 - Pydantic AI typed agents and evals

- Repo URL: https://github.com/pydantic/pydantic-ai
- Repo name: pydantic/pydantic-ai
- Feature or ability Thomas should consider: Type-safe agent definitions, structured tool interfaces, dependency injection, and first-class eval hooks for agent behavior.
- Why it matters for Thomas: Thomas has many tools and command surfaces where schema drift and runtime-only mistakes are expensive. Pydantic AI is a good reference for pushing agent/tool contracts into typed structures and testable eval flows.
- Integration surface guess: Tool registration and validation layers in `thomas/server/tool_extensions.py`, `thomas/tools/*`, testing suite health checks, and CLI command schemas.
- Evidence/source URL: https://github.com/pydantic/pydantic-ai
- Date found: 2026-06-26
- Confidence note: High. Strong match for typed contracts and agent evals; especially relevant to Thomas reliability work.

### 2026-06-26 - Pydantic AI Harness capability library

- Repo URL: https://github.com/pydantic/pydantic-ai-harness
- Repo name: pydantic/pydantic-ai-harness
- Feature or ability Thomas should consider: Agent capability harnesses for approval workflows, tool budgets, stuck-loop detection, secret masking, retry/backoff, and orphaned tool-call repair.
- Why it matters for Thomas: These are practical guardrails around agent execution rather than another orchestration abstraction. Thomas could adapt the ideas to make delegated agents safer, cheaper, and easier to diagnose.
- Integration surface guess: Agent loop safety middleware, server-side tool execution wrappers, `thomas/core/testing_suite.py`, and run telemetry.
- Evidence/source URL: https://github.com/pydantic/pydantic-ai-harness
- Date found: 2026-06-26
- Confidence note: Medium-high. The repository is newer, but the listed capabilities map tightly to Thomas pain points.

### 2026-06-26 - Hugging Face smolagents code agents

- Repo URL: https://github.com/huggingface/smolagents
- Repo name: huggingface/smolagents
- Feature or ability Thomas should consider: Minimal agent runtime with both code-writing agents and standard tool-calling agents, plus multi-agent orchestration where agents can call other agents as tools.
- Why it matters for Thomas: Thomas has accumulated substantial orchestration code. smolagents is a useful counterexample for keeping the core agent loop small and making tool-vs-code execution an explicit design choice.
- Integration surface guess: Agent loop simplification, tool metadata contracts, and future worker-to-worker delegation primitives.
- Evidence/source URL: https://github.com/huggingface/smolagents
- Date found: 2026-06-26
- Confidence note: High. Active, compact, and directly relevant to tool execution ergonomics.

### 2026-06-26 - OpenAI Agents SDK for Python

- Repo URL: https://github.com/openai/openai-agents-python
- Repo name: openai/openai-agents-python
- Feature or ability Thomas should consider: Lightweight multi-agent workflows with handoffs, guardrails, sessions, human-in-the-loop support, and built-in tracing of model calls, tool calls, handoffs, and guardrails.
- Why it matters for Thomas: Thomas needs visible orchestration evidence, not just final output. The tracing model is a concrete reference for run timelines that explain what an agent did and why a handoff happened.
- Integration surface guess: Delegation event stream, chat delegation runner/session modules, run inspector UI, and tool-call audit logs.
- Evidence/source URL: https://github.com/openai/openai-agents-python
- Date found: 2026-06-26
- Confidence note: High. Current releases and built-in tracing/handoff concepts are directly applicable.

### 2026-06-26 - OpenAI Agents SDK for JavaScript/TypeScript

- Repo URL: https://github.com/openai/openai-agents-js
- Repo name: openai/openai-agents-js
- Feature or ability Thomas should consider: Provider-agnostic multi-agent workflow SDK for TypeScript with tracing UI concepts and handoff-oriented orchestration.
- Why it matters for Thomas: Thomas has a web UI and browser-facing runtime. The JS SDK is useful as a reference for how agent run events and handoffs can be represented in frontend-friendly objects.
- Integration surface guess: `thomas/server/web/js/*`, delegation visualization, and any browser-side live task timeline.
- Evidence/source URL: https://github.com/openai/openai-agents-js
- Date found: 2026-06-26
- Confidence note: Medium-high. The Python SDK is likely closer to Thomas backend code, but the JS SDK may inform UI/state representation.

### 2026-06-26 - OpenHands software agent SDK

- Repo URL: https://github.com/OpenHands/software-agent-sdk
- Repo name: OpenHands/software-agent-sdk
- Feature or ability Thomas should consider: Modular SDK for code-working agents that supports local or ephemeral Docker/Kubernetes workspaces, REST APIs, and multi-agent tasks such as refactors and rewrites.
- Why it matters for Thomas: Thomas workers often operate in dirty live repos. OpenHands' workspace separation and agent-server split are useful references for safer task isolation and reproducible execution.
- Integration surface guess: Native repo worker orchestration, workspace provisioning, live repo tracking, and future isolated execution lanes.
- Evidence/source URL: https://github.com/OpenHands/software-agent-sdk
- Date found: 2026-06-26
- Confidence note: High. Strong match for software-agent execution and workspace isolation.

### 2026-06-26 - OpenHands platform and Agent Canvas

- Repo URL: https://github.com/OpenHands/openhands
- Repo name: OpenHands/openhands
- Feature or ability Thomas should consider: Cloud coding-agent platform pattern with transparent engineering work execution, issue fixing, and an agent canvas direction for visual workflow control.
- Why it matters for Thomas: The product direction overlaps with Thomas's visible worker threads and portal-native orchestration. The Agent Canvas transition is worth tracking for UX ideas around assigning, observing, and interrupting agents.
- Integration surface guess: Thomas portal task delegation UI, worker thread visibility, and task-to-repo execution flow.
- Evidence/source URL: https://github.com/OpenHands/openhands
- Date found: 2026-06-26
- Confidence note: Medium-high. The main repo is in transition, but the platform/product ideas are relevant.

### 2026-06-26 - SWE-agent issue-solving agent

- Repo URL: https://github.com/SWE-agent/SWE-agent
- Repo name: SWE-agent/SWE-agent
- Feature or ability Thomas should consider: Agent-computer interface for letting language models inspect, edit, and test real repositories through constrained commands and feedback formats.
- Why it matters for Thomas: Thomas needs agents that can work on code without losing context or damaging unrelated files. SWE-agent's command and feedback interface is a useful reference for limiting how agents browse, patch, and verify changes.
- Integration surface guess: CLI worker loop, repo-edit command wrappers, test feedback summarization, and issue-to-task execution.
- Evidence/source URL: https://github.com/SWE-agent/SWE-agent
- Date found: 2026-06-26
- Confidence note: High. Mature research lineage and directly aligned with repository-fixing agents.

### 2026-06-26 - mini-SWE-agent minimal coding agent

- Repo URL: https://github.com/SWE-agent/mini-swe-agent
- Repo name: SWE-agent/mini-swe-agent
- Feature or ability Thomas should consider: Extremely small command-line software agent that keeps configuration and orchestration minimal while still targeting SWE-bench-style issue solving.
- Why it matters for Thomas: Thomas can use this as a reference for separating essential agent loop mechanics from accumulated orchestration complexity. It may help identify what the smallest reliable repo worker needs.
- Integration surface guess: Agent loop cleanup, worker bootstrap, and simple issue-to-fix command mode.
- Evidence/source URL: https://github.com/SWE-agent/mini-swe-agent
- Date found: 2026-06-26
- Confidence note: Medium-high. Minimal implementation is valuable as a design probe, even if Thomas needs more guardrails.

### 2026-06-26 - CrewAI role-based crews and flows

- Repo URL: https://github.com/crewAIInc/crewAI
- Repo name: crewAIInc/crewAI
- Feature or ability Thomas should consider: Role-playing agents, crews, flows, task dependencies, memory, guardrails, and human review patterns for multi-agent collaboration.
- Why it matters for Thomas: Thomas already delegates across worker/reviewer/coordinator roles. CrewAI is a strong reference for making those roles explicit and composable instead of embedding them only in prompts.
- Integration surface guess: Workboard task claims, native delegation templates, review/coordinator worker roles, and multi-step automation recipes.
- Evidence/source URL: https://github.com/crewAIInc/crewAI
- Date found: 2026-06-26
- Confidence note: High. Active and directly aligned with multi-agent role orchestration.

### 2026-06-26 - Microsoft Agent Framework

- Repo URL: https://github.com/microsoft/agent-framework
- Repo name: microsoft/agent-framework
- Feature or ability Thomas should consider: Python/.NET framework for building, orchestrating, and deploying agents and multi-agent workflows, including graph workflows, handoffs, checkpointing, and human-in-the-loop interaction.
- Why it matters for Thomas: AutoGen is now maintenance-mode, and Microsoft Agent Framework appears to be the forward path. Thomas should track the newer framework for production-oriented orchestration patterns rather than older AutoGen APIs.
- Integration surface guess: Native orchestration architecture, durable workflow definitions, and enterprise-style guardrails around agent handoffs.
- Evidence/source URL: https://github.com/microsoft/agent-framework
- Date found: 2026-06-26
- Confidence note: Medium-high. Promising strategic reference; needs deeper follow-up because it is newer than AutoGen.

### 2026-06-26 - AgentOps agent observability

- Repo URL: https://github.com/AgentOps-AI/agentops
- Repo name: AgentOps-AI/agentops
- Feature or ability Thomas should consider: Lightweight agent observability SDK for tracing sessions, tool calls, costs, benchmarks, and integrations with CrewAI, AG2, OpenAI Agents SDK, LangChain, AutoGen, and CAMEL.
- Why it matters for Thomas: Thomas needs visible run evidence for delegated work, especially when multiple workers operate against a dirty repo. AgentOps is a useful reference for normalized agent telemetry across frameworks.
- Integration surface guess: Delegation event stream, chat delegation session logs, run inspector UI, and testing suite metrics.
- Evidence/source URL: https://github.com/AgentOps-AI/agentops
- Date found: 2026-06-26
- Confidence note: High. Strong observability fit with broad agent-framework integrations.

### 2026-06-26 - AIO Sandbox unified agent workspace

- Repo URL: https://github.com/agent-infra/sandbox
- Repo name: agent-infra/sandbox
- Feature or ability Thomas should consider: All-in-one Docker sandbox combining browser, shell, file operations, MCP services, VNC, VSCode Server, and agent-ready APIs.
- Why it matters for Thomas: Thomas workers need safer places to execute browser/file/shell tasks without contaminating the live checkout or host environment. A unified sandbox model could simplify file sharing across tool modes while preserving isolation.
- Integration surface guess: Future worker workspace provisioning, browser tool runtime, MCP tool execution, and isolated repo task lanes.
- Evidence/source URL: https://github.com/agent-infra/sandbox
- Date found: 2026-06-26
- Confidence note: High. Directly addresses secure multi-tool execution for agents.

### 2026-06-26 - Agent Squad intelligent multi-agent router

- Repo URL: https://github.com/2FastLabs/agent-squad
- Repo name: 2FastLabs/agent-squad
- Feature or ability Thomas should consider: Multi-agent orchestration with intent classification, conversation history, agent routing, streaming support, and a SupervisorAgent that coordinates specialized agents in parallel.
- Why it matters for Thomas: Thomas already distinguishes worker, reviewer, and coordinator roles. Agent Squad provides concrete routing and supervisor patterns for assigning work to the right specialist while maintaining cross-agent context.
- Integration surface guess: Native delegation router, worker role registry, chat delegation planner, and visible coordinator thread logic.
- Evidence/source URL: https://github.com/2FastLabs/agent-squad
- Date found: 2026-06-26
- Confidence note: High. Clear fit for role-based routing and supervisor coordination.

### 2026-06-26 - CAMEL large-scale multi-agent society

- Repo URL: https://github.com/camel-ai/camel
- Repo name: camel-ai/camel
- Feature or ability Thomas should consider: Research-oriented multi-agent framework covering agent societies, role-playing tasks, toolkits, memory modules, simulated environments, and large-scale agent behavior study.
- Why it matters for Thomas: CAMEL can inform how Thomas scales beyond single-worker loops into repeatable agent teams with memory and tool specialization.
- Integration surface guess: Worker team templates, memory-backed delegation context, and multi-agent experiment/eval harnesses.
- Evidence/source URL: https://github.com/camel-ai/camel
- Date found: 2026-06-26
- Confidence note: High. Mature and active; best used as a reference for scalable agent-team patterns rather than copied wholesale.

### 2026-06-26 - AG2 AgentOS multi-agent framework

- Repo URL: https://github.com/ag2ai/ag2
- Repo name: ag2ai/ag2
- Feature or ability Thomas should consider: AgentOS-style framework for cooperative agents, multi-agent conversation patterns, tool use, human-in-the-loop workflows, and autonomous task solving.
- Why it matters for Thomas: AG2 continues the practical AutoGen lineage while Microsoft AutoGen is in maintenance mode. Thomas can compare AG2's conversation patterns against its current visible-worker and reviewer flows.
- Integration surface guess: Multi-agent conversation manager, worker/reviewer handoff policy, and human approval checkpoints.
- Evidence/source URL: https://github.com/ag2ai/ag2
- Date found: 2026-06-26
- Confidence note: High. Strong conceptual fit; follow-up should distinguish AG2 from Microsoft Agent Framework before adoption.

### 2026-06-26 - Google ADK code-first production agents

- Repo URL: https://github.com/google/adk-python
- Repo name: google/adk-python
- Feature or ability Thomas should consider: Code-first agent toolkit for building, evaluating, and deploying sophisticated agents with production-oriented control.
- Why it matters for Thomas: Thomas needs agent behavior to feel like software development: versioned, testable, deployable, and debuggable. ADK is a useful reference for production agent ergonomics.
- Integration surface guess: Agent definition APIs, eval runner integration, deployment packaging, and future Thomas agent templates.
- Evidence/source URL: https://github.com/google/adk-python
- Date found: 2026-06-26
- Confidence note: Medium-high. Strong production framing, but follow-up should check how much is tied to Google services versus portable local patterns.

### 2026-06-26 - Microsoft Semantic Kernel multi-agent orchestration

- Repo URL: https://github.com/microsoft/semantic-kernel
- Repo name: microsoft/semantic-kernel
- Feature or ability Thomas should consider: Model-agnostic SDK for building, orchestrating, and deploying AI agents and multi-agent systems across Python, .NET, and Java.
- Why it matters for Thomas: Semantic Kernel is a mature reference for plugin/function abstractions and enterprise-grade agent orchestration. Thomas can borrow architectural ideas for stable tool contracts without taking on the full ecosystem.
- Integration surface guess: Tool/plugin schema, agent orchestration definitions, and long-running process workflows.
- Evidence/source URL: https://github.com/microsoft/semantic-kernel
- Date found: 2026-06-26
- Confidence note: Medium-high. Mature and relevant; overlap with Microsoft Agent Framework needs deeper mapping.

### 2026-06-26 - Inspect AI eval framework

- Repo URL: https://github.com/UKGovernmentBEIS/inspect_ai
- Repo name: UKGovernmentBEIS/inspect_ai
- Feature or ability Thomas should consider: Evaluation framework with built-in support for prompt engineering, tool usage, multi-turn dialog, model-graded evaluations, coding tasks, and agentic tasks.
- Why it matters for Thomas: Thomas needs repeatable tests for agent behavior, not just unit tests around deterministic code. Inspect's solver/scorer/task model is a strong reference for agent regression suites.
- Integration surface guess: `thomas/core/testing_suite.py`, agent benchmark tasks, tool-use evals, and CI gates for delegated workflows.
- Evidence/source URL: https://github.com/UKGovernmentBEIS/inspect_ai
- Date found: 2026-06-26
- Confidence note: High. Strong fit for rigorous agent evaluation and safety-oriented testing.

### 2026-06-26 - Langfuse open-source LLM observability and evals

- Repo URL: https://github.com/langfuse/langfuse
- Repo name: langfuse/langfuse
- Feature or ability Thomas should consider: Self-hostable LLM engineering platform for tracing, monitoring, evaluating, and debugging AI applications.
- Why it matters for Thomas: Thomas needs a durable trail of model calls, tool calls, cost, latency, and failure modes. Langfuse is a strong open-source reference for trace storage and eval dashboards.
- Integration surface guess: Server-side telemetry backend, run trace viewer, cost accounting, and evaluation dashboards.
- Evidence/source URL: https://github.com/langfuse/langfuse
- Date found: 2026-06-26
- Confidence note: High. Strong observability/evals match; integration depth would need careful scoping.

### 2026-06-26 - Agent Blackboard shared coordination memory

- Repo URL: https://github.com/claudioed/agent-blackboard
- Repo name: claudioed/agent-blackboard
- Feature or ability Thomas should consider: Blackboard-pattern multi-agent coordination for software engineering tasks with an MCP-based shared knowledge repository, specialized agents, coordinator, embedding search, monitoring, and A2A communication.
- Why it matters for Thomas: Thomas already has workboard and message-lane concepts. A blackboard-style shared state could make cross-agent context more explicit than ad hoc thread summaries.
- Integration surface guess: Workboard/message lane evolution, shared agent memory, coordinator/reviewer state, and task decomposition records.
- Evidence/source URL: https://github.com/claudioed/agent-blackboard
- Date found: 2026-06-26
- Confidence note: Medium. Conceptually relevant, but repository maturity appears lower than the major frameworks; useful as a pattern reference.

### 2026-06-26 - mcp-agent MCP-native agent framework

- Repo URL: https://github.com/lastmile-ai/mcp-agent
- Repo name: lastmile-ai/mcp-agent
- Feature or ability Thomas should consider: Composable agent framework built around Model Context Protocol servers, with the design claim that simple MCP-based patterns can ship robust agents without heavyweight architecture.
- Why it matters for Thomas: Thomas is accumulating tool and delegation surfaces. MCP-native composition could keep tool access standardized while letting Thomas route specialist agents through the same interface.
- Integration surface guess: Tool registry, MCP bridge, native delegation planner, and future worker capability discovery.
- Evidence/source URL: https://github.com/lastmile-ai/mcp-agent
- Date found: 2026-06-26
- Confidence note: High. Strong match for Thomas tool standardization and agent interoperability.

### 2026-06-26 - Letta advanced agent memory

- Repo URL: https://github.com/letta-ai/letta
- Repo name: letta-ai/letta
- Feature or ability Thomas should consider: Advanced memory agents that can learn, self-improve, run locally in a terminal, expose an API, and manage long-term context explicitly.
- Why it matters for Thomas: Thomas needs durable memory for worker context, repeated repo lessons, and user preferences without stuffing every run into the prompt. Letta is a major reference for explicit memory blocks and context management.
- Integration surface guess: `thomas/memory/`, worker run memory, agent preference storage, and future self-improvement context repositories.
- Evidence/source URL: https://github.com/letta-ai/letta
- Date found: 2026-06-26
- Confidence note: High. Mature memory-focused project and directly relevant to Thomas's repeated-worker context problem.

### 2026-06-26 - agentmemory shared coding-agent memory server

- Repo URL: https://github.com/rohitg00/agentmemory
- Repo name: rohitg00/agentmemory
- Feature or ability Thomas should consider: Persistent memory server for coding agents, exposed through hooks, MCP, and REST so multiple agents can share one memory layer.
- Why it matters for Thomas: Thomas has visible worker threads and cross-agent coordination. A shared memory server pattern could reduce repeated rediscovery and preserve repo-specific facts across workers.
- Integration surface guess: Worker bootstrap hooks, MCP memory service, shared repo facts, and coordination memory attached to workboard tasks.
- Evidence/source URL: https://github.com/rohitg00/agentmemory
- Date found: 2026-06-26
- Confidence note: Medium-high. Practical integration model is relevant; follow-up should inspect storage semantics and conflict handling.

### 2026-06-26 - Browser Use web agent runtime

- Repo URL: https://github.com/browser-use/browser-use
- Repo name: browser-use/browser-use
- Feature or ability Thomas should consider: Browser agent runtime with a Rust core, browser harness, real browser/computer action space, persistent tools, and recovery loops inspired by coding agents.
- Why it matters for Thomas: Thomas already has browser tooling but needs reliable agent-friendly web interaction, recovery, and evidence capture. Browser Use is a strong reference for making browser actions first-class agent steps.
- Integration surface guess: `thomas/tools/browser.py`, browser contracts under `thomas/browser/`, web research workers, and visual verification flows.
- Evidence/source URL: https://github.com/browser-use/browser-use
- Date found: 2026-06-26
- Confidence note: High. Active and directly relevant to browser-capable agents.

### 2026-06-26 - Vercel Agent Browser CLI

- Repo URL: https://github.com/vercel-labs/agent-browser
- Repo name: vercel-labs/agent-browser
- Feature or ability Thomas should consider: Fast native Rust browser automation CLI for AI agents, packaged for npm/cargo use with Chrome for Testing management.
- Why it matters for Thomas: A CLI-first browser tool may be easier to expose safely to worker agents than a full browser automation library. Its context-efficient command shape is worth studying for Thomas browser tooling.
- Integration surface guess: Browser CLI wrapper, web research workers, screenshot/evidence capture, and agent command sandboxing.
- Evidence/source URL: https://github.com/vercel-labs/agent-browser
- Date found: 2026-06-26
- Confidence note: Medium-high. Newer project but highly relevant to agent-oriented browser automation.

### 2026-06-26 - Firecrawl Web Agent research agent

- Repo URL: https://github.com/firecrawl/web-agent
- Repo name: firecrawl/web-agent
- Feature or ability Thomas should consider: Open-source foundation for a structured autonomous web research agent with swappable models, skills, and deployable architecture.
- Why it matters for Thomas: Thomas needs repo and web research workers that can gather evidence, cite sources, and produce durable notes. Firecrawl's web-agent shape is relevant to the research queue workflow itself.
- Integration surface guess: Web research worker, source extraction pipeline, evidence-backed markdown generation, and browser/search tool orchestration.
- Evidence/source URL: https://github.com/firecrawl/web-agent
- Date found: 2026-06-26
- Confidence note: Medium-high. Relevant to research workflows; follow-up should inspect depth of open-source implementation.

### 2026-06-26 - SWE-bench repository issue benchmark

- Repo URL: https://github.com/swe-bench/SWE-bench
- Repo name: swe-bench/SWE-bench
- Feature or ability Thomas should consider: Benchmark and harness for evaluating agents on real GitHub software issues where the task is to generate patches against existing repositories.
- Why it matters for Thomas: Thomas is increasingly a repo-working agent. SWE-bench gives a reference target for measuring whether Thomas workers actually fix software tasks rather than only completing local demos.
- Integration surface guess: Agent eval suite, coding-worker regression tests, issue-to-patch workflow scoring, and CI gates for repo-agent improvements.
- Evidence/source URL: https://github.com/swe-bench/SWE-bench
- Date found: 2026-06-26
- Confidence note: High. Standard benchmark for coding agents; useful as an external evaluation anchor.

### 2026-06-26 - OpenHands Benchmarks evaluation pipelines

- Repo URL: https://github.com/OpenHands/benchmarks
- Repo name: OpenHands/benchmarks
- Feature or ability Thomas should consider: Standardized benchmark evaluation infrastructure for testing agent capabilities across real-world tasks, with migration toward OpenHands Software Agent SDK V1.
- Why it matters for Thomas: Thomas needs repeatable evaluation pipelines for worker changes. OpenHands Benchmarks can inform how to organize task suites, runners, logs, and score reporting for repo agents.
- Integration surface guess: `thomas/core/testing_suite.py`, eval task registry, worker benchmark runner, and run artifact storage.
- Evidence/source URL: https://github.com/OpenHands/benchmarks
- Date found: 2026-06-26
- Confidence note: Medium-high. Good evaluation infrastructure reference, though migration status means follow-up is needed.

### 2026-06-26 - HAL Harness reproducible agent leaderboard

- Repo URL: https://github.com/princeton-pli/hal-harness
- Repo name: princeton-pli/hal-harness
- Feature or ability Thomas should consider: Standardized evaluation harness for reproducible agent evaluations across benchmarks, with unified CLI, agent/benchmark plugins, Weave logging, cost tracking, and leaderboard publishing.
- Why it matters for Thomas: Thomas needs honest, repeatable agent performance evidence. HAL Harness is a useful model for plugging multiple benchmark tasks into one CLI and tracking both quality and cost.
- Integration surface guess: Evaluation CLI, cost-aware run logging, benchmark plugins, and external comparison dashboards.
- Evidence/source URL: https://github.com/princeton-pli/hal-harness
- Date found: 2026-06-26
- Confidence note: High. Strong fit for rigorous agent evaluation and cost tracking.

### 2026-06-26 - PR-Agent automated pull request reviewer

- Repo URL: https://github.com/The-PR-Agent/pr-agent
- Repo name: The-PR-Agent/pr-agent
- Feature or ability Thomas should consider: Open-source AI pull-request reviewer that summarizes changes, generates review comments, and supports developer workflow integrations across major git hosts.
- Why it matters for Thomas: Thomas needs reviewer/coordinator coverage for worker changes. PR-Agent is a direct reference for turning code diffs into structured review output that humans can inspect quickly.
- Integration surface guess: Workboard reviewer role, PR/diff summarizer, code review checklist generation, and future GitHub integration.
- Evidence/source URL: https://github.com/The-PR-Agent/pr-agent
- Date found: 2026-06-26
- Confidence note: High. Mature and directly aligned with automated code review.

### 2026-06-26 - Continue Checks AI PR quality standards

- Repo URL: https://github.com/continuedev/checks
- Repo name: continuedev/checks
- Feature or ability Thomas should consider: Markdown-defined code quality standards that run as full AI agents on pull requests, reading files, running commands, and applying judgment beyond linters/tests.
- Why it matters for Thomas: Thomas already leans on guardrails and focused verification. A `.checks/`-style system could let Thomas encode project-specific review rules as agent-readable checks rather than scattered prompt text.
- Integration surface guess: Reviewer worker prompts, CI-style agent checks, workboard completion gates, and `AGENTS.md`/Bible-derived rules.
- Evidence/source URL: https://github.com/continuedev/checks
- Date found: 2026-06-26
- Confidence note: Medium-high. Small repo, but the concept is sharply relevant to Thomas verification discipline.

### 2026-06-26 - Microsoft Agent Governance Toolkit

- Repo URL: https://github.com/microsoft/agent-governance-toolkit
- Repo name: microsoft/agent-governance-toolkit
- Feature or ability Thomas should consider: Policy enforcement, zero-trust identity, execution sandboxing, and reliability engineering controls for autonomous AI agents aligned to OWASP Agentic Top 10 risks.
- Why it matters for Thomas: Thomas is moving toward native agent orchestration. Governance controls should be designed early so tool access, identity, approvals, and auditability do not remain informal prompt conventions.
- Integration surface guess: Tool permission broker, agent identity model, sandbox policy, run audit logs, and publish/preflight guardrails.
- Evidence/source URL: https://github.com/microsoft/agent-governance-toolkit
- Date found: 2026-06-26
- Confidence note: High. Current and highly relevant to safe autonomous-agent operation.

### 2026-06-26 - Open Policy Agent for agent tool policy

- Repo URL: https://github.com/open-policy-agent/opa
- Repo name: open-policy-agent/opa
- Feature or ability Thomas should consider: General-purpose policy engine for unified, context-aware authorization decisions that could gate agent tool calls, filesystem writes, network access, and publish actions.
- Why it matters for Thomas: Thomas needs explicit policies around what agents may do in a dirty repo or public snapshot path. OPA is not agent-specific, but it is a proven reference for externalizing policy from application logic.
- Integration surface guess: Tool execution middleware, publish/preflight gates, workboard claim authorization, and per-agent capability rules.
- Evidence/source URL: https://github.com/open-policy-agent/opa
- Date found: 2026-06-26
- Confidence note: Medium-high. Strong policy foundation; requires adaptation to agent-specific UX and audit needs.

### 2026-06-26 - Official MCP reference servers

- Repo URL: https://github.com/modelcontextprotocol/servers
- Repo name: modelcontextprotocol/servers
- Feature or ability Thomas should consider: Reference MCP server implementations that demonstrate MCP features and SDK usage for exposing external tools to agents.
- Why it matters for Thomas: Thomas needs a stable way to expose repo, browser, memory, GitHub, and internal tools to agents. The reference servers help define expected MCP behavior and security caveats.
- Integration surface guess: Thomas MCP server design, tool adapter examples, capability discovery, and sandboxed tool contracts.
- Evidence/source URL: https://github.com/modelcontextprotocol/servers
- Date found: 2026-06-26
- Confidence note: High. Official reference material; should be treated as examples, not production security policy.

### 2026-06-26 - GitHub MCP Server

- Repo URL: https://github.com/github/github-mcp-server
- Repo name: github/github-mcp-server
- Feature or ability Thomas should consider: MCP server that lets AI tools read repositories, manage issues and pull requests, analyze code, and automate GitHub workflows through natural-language tool access.
- Why it matters for Thomas: Thomas's repo workers eventually need controlled GitHub issue/PR access. Studying the official GitHub MCP server can guide capability boundaries and audit trails.
- Integration surface guess: GitHub connector, issue-to-worker delegation, PR review automation, and MCP permission UX.
- Evidence/source URL: https://github.com/github/github-mcp-server
- Date found: 2026-06-26
- Confidence note: High. Official GitHub project and directly aligned with repo automation.

### 2026-06-26 - awesome-mcp-servers ecosystem directory

- Repo URL: https://github.com/punkpeye/awesome-mcp-servers
- Repo name: punkpeye/awesome-mcp-servers
- Feature or ability Thomas should consider: Curated directory of MCP servers across categories, useful for discovering integration targets and common server patterns.
- Why it matters for Thomas: Thomas will benefit from a curated catalog mindset for tool capabilities instead of one-off hardcoded integrations. This directory can seed future research into safe, high-value MCP tools.
- Integration surface guess: Marketplace/tool catalog, MCP server allowlist, capability discovery UI, and research backlog generation.
- Evidence/source URL: https://github.com/punkpeye/awesome-mcp-servers
- Date found: 2026-06-26
- Confidence note: Medium-high. It is a directory rather than a runtime, but useful as MCP ecosystem reconnaissance.

### 2026-06-26 - Aider terminal coding agent

- Repo URL: https://github.com/aider-ai/aider
- Repo name: aider-ai/aider
- Feature or ability Thomas should consider: Terminal-first AI pair programmer with git-aware editing, automatic commits, broad language support, repo maps, and model-provider flexibility.
- Why it matters for Thomas: Aider's git-centered workflow is a strong reference for making code-agent edits understandable and reversible. Thomas can borrow ideas without adopting auto-commit behavior by default.
- Integration surface guess: Repo map generation, code edit loop ergonomics, diff presentation, and optional patch commit helpers.
- Evidence/source URL: https://github.com/aider-ai/aider
- Date found: 2026-06-26
- Confidence note: High. Mature coding-agent tool with practical repo-editing patterns.

### 2026-06-26 - OpenCode terminal agent plan/build modes

- Repo URL: https://github.com/anomalyco/opencode
- Repo name: anomalyco/opencode
- Feature or ability Thomas should consider: Terminal coding agent with separate build and read-only plan agents, permission prompts for shell use, and subagent support for complex searches and multistep tasks.
- Why it matters for Thomas: Thomas already separates research-only/reviewer/worker roles. OpenCode's explicit plan-vs-build agent modes are a concrete UX reference for preventing accidental edits during research or review runs.
- Integration surface guess: Agent mode selector, delegation templates, read-only planning mode, shell permission prompts, and subagent invocation.
- Evidence/source URL: https://github.com/anomalyco/opencode
- Date found: 2026-06-26
- Confidence note: High. Directly relevant to Thomas's need for visible, constrained worker modes.

### 2026-06-26 - Carto structural codebase intelligence

- Repo URL: https://github.com/theanshsonkar/carto
- Repo name: theanshsonkar/carto
- Feature or ability Thomas should consider: Persistent codebase architecture map for AI tools, including import graphs, routes, domains, blast radius analysis, diff validation, MCP serving, and PR impact reports.
- Why it matters for Thomas: Thomas workers repeatedly need to understand live repo structure before editing. Carto's architectural context and diff-risk model could help Thomas avoid broad, high-blast-radius changes in dirty repos.
- Integration surface guess: Repo intelligence service, MCP tool server, workboard preflight checks, PR impact comments, and code-edit risk scoring.
- Evidence/source URL: https://github.com/theanshsonkar/carto
- Date found: 2026-06-26
- Confidence note: High. Strong direct fit for repo-aware agents and includes Codex/MCP integration paths.

### 2026-06-26 - cyanheads repo-map repository summaries

- Repo URL: https://github.com/cyanheads/repo-map
- Repo name: cyanheads/repo-map
- Feature or ability Thomas should consider: AI-enhanced repository mapper that generates summaries and analysis of project structures, file purposes, and cross-language considerations.
- Why it matters for Thomas: Thomas could use repo-map-style outputs to bootstrap worker context and reduce repeated manual exploration before each task.
- Integration surface guess: Repository onboarding, worker context packs, Bible drift assistance, and repo research summaries.
- Evidence/source URL: https://github.com/cyanheads/repo-map
- Date found: 2026-06-26
- Confidence note: Medium-high. More documentation-oriented than Carto, but valuable for agent onboarding.

### 2026-06-26 - Repo Atlas persistent agent on-ramp docs

- Repo URL: https://github.com/cathrynlavery/repo-atlas
- Repo name: cathrynlavery/repo-atlas
- Feature or ability Thomas should consider: Skill-driven repository atlas generation that creates structured docs such as directory trees, entrypoints, architecture notes, and an agent on-ramp for Claude Code/Codex workflows.
- Why it matters for Thomas: Thomas's Bible is already a repo truth source. Repo Atlas could inspire a scoped, generated supplement that helps new workers orient without changing the Bible's authoritative role.
- Integration surface guess: Repo onboarding docs, worker briefing generation, Codex review pass, and Thomas Bible companion artifacts.
- Evidence/source URL: https://github.com/cathrynlavery/repo-atlas
- Date found: 2026-06-26
- Confidence note: Medium-high. Smaller project, but very aligned with agent onboarding and Codex review workflows.

### 2026-06-26 - AgentTrace local-first agent debugger

- Repo URL: https://github.com/Rxflex/agenttrace
- Repo name: Rxflex/agenttrace
- Feature or ability Thomas should consider: Local-first step debugger for AI agents with a Python SDK and web UI for inspecting spans, tool calls, prompts, and responses as an interactive tree.
- Why it matters for Thomas: Thomas needs visible run traces for worker/reviewer/coordinator sessions. A local-first debugger fits the user's preference for readable progress without forcing everything into SaaS dashboards.
- Integration surface guess: Delegation trace viewer, local run logs, tool-call tree UI, and post-run debugging.
- Evidence/source URL: https://github.com/Rxflex/agenttrace
- Date found: 2026-06-26
- Confidence note: High. Direct fit for agent run inspectability and local-first debugging.

### 2026-06-26 - AgentPulse self-hosted agent observability

- Repo URL: https://github.com/jstuart0/agentpulse
- Repo name: jstuart0/agentpulse
- Feature or ability Thomas should consider: Self-hosted observability dashboard for AI agents, focused on monitoring costs, tokens, latency, errors, and run traces with local or Postgres-backed storage.
- Why it matters for Thomas: Thomas needs cost and run visibility as worker thread counts grow. AgentPulse is a useful reference for lightweight observability that can start local and grow into persistent storage.
- Integration surface guess: Token/cost accounting, run dashboard, worker telemetry, and long-running agent monitoring.
- Evidence/source URL: https://github.com/jstuart0/agentpulse
- Date found: 2026-06-26
- Confidence note: Medium-high. Overlaps with AgentOps/Langfuse but has a self-hosted lightweight angle worth tracking.

### 2026-06-26 - Issue AI Agent GitHub triage action

- Repo URL: https://github.com/alexyan0431/issue-ai-agent
- Repo name: alexyan0431/issue-ai-agent
- Feature or ability Thomas should consider: GitHub Action that classifies issues, labels priority/category, detects duplicates, replies contextually, and handles follow-up comments.
- Why it matters for Thomas: Thomas can learn from issue triage automation for future issue-to-workboard flows, especially around duplicate detection and structured intake questions.
- Integration surface guess: GitHub issue ingestion, workboard task creation, triage labels, and coordinator worker prompts.
- Evidence/source URL: https://github.com/alexyan0431/issue-ai-agent
- Date found: 2026-06-26
- Confidence note: Medium. Narrow and small, but directly maps to issue triage automation.

### 2026-06-26 - Agent-o-rama end-to-end agent platform

- Repo URL: https://github.com/redplanetlabs/agent-o-rama
- Repo name: redplanetlabs/agent-o-rama
- Feature or ability Thomas should consider: End-to-end LLM agent platform for building, tracing, testing, monitoring, storing state, and deploying agents.
- Why it matters for Thomas: Agent-o-rama is another full-stack reference for treating tracing, testing, storage, and deployment as one agent platform rather than disconnected utilities.
- Integration surface guess: Native orchestration architecture, trace/test/monitoring integration, and stateful agent storage.
- Evidence/source URL: https://github.com/redplanetlabs/agent-o-rama
- Date found: 2026-06-26
- Confidence note: Medium-high. Good broad platform reference; language/runtime fit needs later review.

### 2026-06-26 - awesome-web-agents browser-agent catalog

- Repo URL: https://github.com/steel-dev/awesome-web-agents
- Repo name: steel-dev/awesome-web-agents
- Feature or ability Thomas should consider: Curated catalog of web-agent projects including browser automation APIs, trace viewers, and web interaction frameworks.
- Why it matters for Thomas: Thomas already uses browser tooling for research and verification. A web-agent catalog can keep future browser automation research from getting stuck on only one implementation.
- Integration surface guess: Browser-tool research backlog, web-agent evaluation matrix, trace viewer comparisons, and browser worker capability planning.
- Evidence/source URL: https://github.com/steel-dev/awesome-web-agents
- Date found: 2026-06-26
- Confidence note: Medium-high. It is a catalog rather than a runtime, but it is useful for systematic future discovery.

### 2026-06-26 - Pipelock AI agent firewall

- Repo URL: https://github.com/luckyPipewrench/pipelock
- Repo name: luckyPipewrench/pipelock
- Feature or ability Thomas should consider: Local AI egress proxy and MCP security control that scans outbound/inbound HTTP, WebSocket, MCP, and A2A traffic for credential leaks, prompt injection, SSRF, and tool poisoning while emitting signed action receipts.
- Why it matters for Thomas: Thomas agents will increasingly browse untrusted content and call powerful tools. Pipelock's outside-the-agent mediation pattern is a strong reference for making tool/network actions auditable and blockable before damage happens.
- Integration surface guess: Tool egress proxy, MCP gateway layer, browser/network tool mediation, signed run receipts, and security preflight checks.
- Evidence/source URL: https://github.com/luckyPipewrench/pipelock
- Date found: 2026-06-26
- Confidence note: High. Current, directly agent-security focused, and explicitly supports Codex/OpenCode/Agents SDK-style tools.

### 2026-06-26 - AgentSeal local agent security scanner

- Repo URL: https://github.com/getagentseal/agentseal
- Repo name: getagentseal/agentseal
- Feature or ability Thomas should consider: Security toolkit that scans local AI agent environments for dangerous skills, poisoned MCP configs, data exfiltration paths, prompt-injection resistance, and live MCP tool poisoning.
- Why it matters for Thomas: Thomas has skills, tools, MCP-like integrations, and local configuration risk. AgentSeal is a concrete reference for scanning the agent runtime itself, not just application code.
- Integration surface guess: Local environment audit command, skill/plugin scanner, MCP config validator, and security report generation.
- Evidence/source URL: https://github.com/getagentseal/agentseal
- Date found: 2026-06-26
- Confidence note: High. Narrow but highly relevant to agent runtime hardening.

### 2026-06-26 - Snyk Agent Scan

- Repo URL: https://github.com/snyk/agent-scan
- Repo name: snyk/agent-scan
- Feature or ability Thomas should consider: Agent component supply-chain scanner for prompt injection, tool poisoning, toxic flows, and vulnerable agent skills.
- Why it matters for Thomas: Thomas needs a repeatable way to inspect skills/tools before letting workers use them. Snyk's scan/inspect framing can guide a first-party Thomas scanner or an integration.
- Integration surface guess: Skill marketplace safety checks, MCP/tool inventory audit, CI security gates, and worker bootstrap validation.
- Evidence/source URL: https://github.com/snyk/agent-scan
- Date found: 2026-06-26
- Confidence note: High. Strong supply-chain security fit from a credible security vendor.

### 2026-06-26 - Agentgateway AI-native proxy

- Repo URL: https://github.com/agentgateway/agentgateway
- Repo name: agentgateway/agentgateway
- Feature or ability Thomas should consider: Open-source proxy for MCP and A2A traffic that provides drop-in security, observability, and governance for agent-to-LLM, agent-to-tool, and agent-to-agent communication.
- Why it matters for Thomas: Thomas's native orchestration direction needs a control plane between agents and tools. Agentgateway is a reference for centralizing routing, policy, and telemetry rather than baking those concerns into every worker.
- Integration surface guess: MCP/A2A gateway, delegation routing, tool access policy, and multi-agent observability.
- Evidence/source URL: https://github.com/agentgateway/agentgateway
- Date found: 2026-06-26
- Confidence note: High. Direct match for agent connectivity and governance.

### 2026-06-26 - Microsoft MCP Gateway

- Repo URL: https://github.com/microsoft/mcp-gateway
- Repo name: microsoft/mcp-gateway
- Feature or ability Thomas should consider: Reverse proxy and management layer for MCP servers with scalable, session-aware routing, authorization, and Kubernetes lifecycle management.
- Why it matters for Thomas: If Thomas exposes internal tools through MCP, it will need session handling and controlled routing. Microsoft MCP Gateway provides production-oriented patterns for managing many MCP servers without each client wiring them manually.
- Integration surface guess: MCP server deployment, session-aware tool routing, authorization layer, and cloud/remote worker access.
- Evidence/source URL: https://github.com/microsoft/mcp-gateway
- Date found: 2026-06-26
- Confidence note: High. Official Microsoft project with clear production gateway scope.

### 2026-06-26 - MCP Gateway and Registry

- Repo URL: https://github.com/agentic-community/mcp-gateway-registry
- Repo name: agentic-community/mcp-gateway-registry
- Feature or ability Thomas should consider: Governed control plane and registry for MCP servers, AI agents, skills, and custom assets.
- Why it matters for Thomas: Thomas will need a catalog/registry if it grows tool servers, skills, and worker roles. This project is a reference for treating AI assets as governable inventory rather than loose scripts.
- Integration surface guess: Tool/skill registry, MCP server catalog, worker capability inventory, and governance dashboard.
- Evidence/source URL: https://github.com/agentic-community/mcp-gateway-registry
- Date found: 2026-06-26
- Confidence note: Medium-high. Strong architectural relevance; follow-up should inspect deployment maturity and auth model.

### 2026-06-26 - PandaProbe agent engineering platform

- Repo URL: https://github.com/chirpz-ai/pandaprobe
- Repo name: chirpz-ai/pandaprobe
- Feature or ability Thomas should consider: Open-source agent engineering platform for tracing, evaluating, monitoring, and debugging AI agents, with integrations for LangGraph, CrewAI, Claude Agent SDK, and more.
- Why it matters for Thomas: Thomas needs a unified view of traces, evals, and metrics across different worker types. PandaProbe is a useful self-hostable reference for stitching those signals together.
- Integration surface guess: Worker telemetry dashboard, eval result store, trace collection, and agent debugging UI.
- Evidence/source URL: https://github.com/chirpz-ai/pandaprobe
- Date found: 2026-06-26
- Confidence note: High. Active and closely aligned with agent observability/evaluation.

### 2026-06-26 - promptfoo agent evals and red teaming

- Repo URL: https://github.com/promptfoo/promptfoo
- Repo name: promptfoo/promptfoo
- Feature or ability Thomas should consider: CLI-first prompt, agent, and RAG testing with red teaming, pentesting, vulnerability scanning, model comparison, and declarative configs that can live in the repo.
- Why it matters for Thomas: Thomas needs security and behavior checks that run in normal developer workflows. Promptfoo's repo-stored config model could help encode repeatable agent regression and red-team cases.
- Integration surface guess: Agent eval config, CI checks, red-team task suites, and prompt/tool policy regression tests.
- Evidence/source URL: https://github.com/promptfoo/promptfoo
- Date found: 2026-06-26
- Confidence note: High. Mature, active, and directly relevant to agent/RAG evaluation plus security testing.

### 2026-06-26 - NVIDIA garak LLM vulnerability scanner

- Repo URL: https://github.com/NVIDIA/garak
- Repo name: NVIDIA/garak
- Feature or ability Thomas should consider: Generative AI red-teaming and assessment kit that probes for hallucination, data leakage, prompt injection, misinformation, toxicity, jailbreaks, and other LLM weaknesses.
- Why it matters for Thomas: Thomas should test agent/model behavior against known failure modes before exposing broader autonomy. Garak can inform a vulnerability-scanning lane for model prompts and agent outputs.
- Integration surface guess: Security eval suite, model/provider acceptance checks, red-team reports, and pre-release agent safety gates.
- Evidence/source URL: https://github.com/NVIDIA/garak
- Date found: 2026-06-26
- Confidence note: High. Established LLM security scanner from NVIDIA; not agent-specific but valuable for safety gates.

### 2026-06-26 - TRACE capability-targeted agent self-improvement

- Repo URL: https://github.com/ScalingIntelligence/TRACE
- Repo name: ScalingIntelligence/TRACE
- Feature or ability Thomas should consider: End-to-end system that turns recurrent agent failures into capability-targeted training environments for environment-specific agent self-improvement.
- Why it matters for Thomas: Thomas accumulates repeated failure patterns across workers. TRACE is a research reference for converting those failures into targeted eval/training environments instead of only writing postmortems.
- Integration surface guess: Failure mining, eval generation, self-improvement backlog, and training/evaluation artifacts from worker traces.
- Evidence/source URL: https://github.com/ScalingIntelligence/TRACE
- Date found: 2026-06-26
- Confidence note: Medium-high. Research-oriented, but valuable for long-term self-improvement strategy.

### 2026-06-26 - AgentDebug failure taxonomy and recovery

- Repo URL: https://github.com/ulab-uiuc/AgentDebug
- Repo name: ulab-uiuc/AgentDebug
- Feature or ability Thomas should consider: Framework for understanding, detecting, and recovering from LLM agent failures, with a taxonomy spanning memory, reflection, planning, action, and system errors plus annotated failure trajectories.
- Why it matters for Thomas: Thomas workers will fail in recurring ways. A structured failure taxonomy could make post-run summaries more useful than free-form "it broke" notes and guide targeted fixes.
- Integration surface guess: Worker trace analyzer, failure classification in run logs, reviewer/coordinator diagnostics, and self-improvement backlog creation.
- Evidence/source URL: https://github.com/ulab-uiuc/AgentDebug
- Date found: 2026-06-26
- Confidence note: High. Directly relevant to agent failure analysis and recovery loops.

### 2026-06-26 - Claude Context semantic code-search MCP

- Repo URL: https://github.com/zilliztech/claude-context
- Repo name: zilliztech/claude-context
- Feature or ability Thomas should consider: MCP plugin that provides semantic code search over entire codebases so coding agents can retrieve relevant context from large repositories without repeated manual discovery.
- Why it matters for Thomas: Thomas workers spend time rediscovering the codebase and current seams. A semantic code-search MCP pattern could reduce token waste and improve focused edits in the live repo.
- Integration surface guess: Code-search MCP server, worker bootstrap context, repo-aware search tools, and Bible drift investigations.
- Evidence/source URL: https://github.com/zilliztech/claude-context
- Date found: 2026-06-26
- Confidence note: High. Strong fit for codebase-scale agent context retrieval.

### 2026-06-26 - Open Prompt Injection toolkit

- Repo URL: https://github.com/liu00222/Open-Prompt-Injection
- Repo name: liu00222/Open-Prompt-Injection
- Feature or ability Thomas should consider: Open-source toolkit for implementing, evaluating, and extending prompt-injection attacks and defenses for LLM-integrated applications and agents.
- Why it matters for Thomas: Thomas agents will read untrusted web, issue, and repository content. Prompt-injection defense should be tested explicitly rather than handled only by prompt wording.
- Integration surface guess: Security eval suite, browser/web research safeguards, tool-call policy tests, and prompt-injection regression corpus.
- Evidence/source URL: https://github.com/liu00222/Open-Prompt-Injection
- Date found: 2026-06-26
- Confidence note: High. Focused prompt-injection toolkit with direct agent-safety relevance.

### 2026-06-26 - open-multi-agent TypeScript task DAG orchestration

- Repo URL: https://github.com/open-multi-agent/open-multi-agent
- Repo name: open-multi-agent/open-multi-agent
- Feature or ability Thomas should consider: TypeScript backend framework where a coordinator decomposes goals into task DAGs, parallelizes independent work, and synthesizes results.
- Why it matters for Thomas: Thomas already has visible worker threads and coordinator needs. A task-DAG decomposition model is a concrete reference for making parallelism explicit and inspectable.
- Integration surface guess: Native delegation planner, workboard task decomposition, parallel worker scheduling, and result synthesis.
- Evidence/source URL: https://github.com/open-multi-agent/open-multi-agent
- Date found: 2026-06-26
- Confidence note: Medium-high. Newer project, but its coordinator/DAG design maps directly to Thomas orchestration goals.

### 2026-06-26 - Code Index MCP

- Repo URL: https://github.com/johnhuang316/code-index-mcp
- Repo name: johnhuang316/code-index-mcp
- Feature or ability Thomas should consider: MCP server for intelligent code indexing, advanced search, and detailed code analysis to help AI assistants navigate complex projects.
- Why it matters for Thomas: Thomas can benefit from a lightweight code-index service that exposes search and analysis tools to agents without forcing them to shell out and grep blindly.
- Integration surface guess: MCP code intelligence server, code review/refactor assistants, documentation generation, and architectural analysis tools.
- Evidence/source URL: https://github.com/johnhuang316/code-index-mcp
- Date found: 2026-06-26
- Confidence note: Medium-high. Good code-indexing fit; follow-up should compare against Carto, Claude Context, and codemogger.

### 2026-06-26 - InjecAgent indirect prompt-injection benchmark

- Repo URL: https://github.com/uiuc-kang-lab/InjecAgent
- Repo name: uiuc-kang-lab/InjecAgent
- Feature or ability Thomas should consider: Benchmark for evaluating tool-integrated LLM agents against indirect prompt-injection attacks, with test cases across user tools and attacker tools.
- Why it matters for Thomas: Thomas agents are tool-integrated and will process untrusted content. InjecAgent can inform concrete adversarial tests for whether tools leak data or obey malicious instructions.
- Integration surface guess: Agent red-team test suite, tool-call policy checks, browser/research worker hardening, and CI security gates.
- Evidence/source URL: https://github.com/uiuc-kang-lab/InjecAgent
- Date found: 2026-06-26
- Confidence note: High. Directly targets tool-integrated agent prompt-injection risk.

### 2026-06-26 - PINT prompt-injection detection benchmark

- Repo URL: https://github.com/lakeraai/pint-benchmark
- Repo name: lakeraai/pint-benchmark
- Feature or ability Thomas should consider: Benchmark for evaluating prompt-injection detection systems, including tooling for running the benchmark against custom datasets.
- Why it matters for Thomas: Thomas may need a local detector or policy layer for untrusted prompts. PINT can help evaluate whether a detector catches realistic injection attempts before integration.
- Integration surface guess: Prompt-injection detector evaluation, security regression datasets, web/issue ingestion filters, and tool-call approval rules.
- Evidence/source URL: https://github.com/lakeraai/pint-benchmark
- Date found: 2026-06-26
- Confidence note: Medium-high. More detector-focused than agent-runtime-focused, but useful for measurable defenses.

### 2026-06-26 - codemogger local code indexing MCP

- Repo URL: https://github.com/glommer/codemogger
- Repo name: glommer/codemogger
- Feature or ability Thomas should consider: Local code indexing library and MCP server that parses source code with tree-sitter, chunks semantic units, embeds locally, and stores vector plus full-text search in a single SQLite file.
- Why it matters for Thomas: Thomas needs local-first code intelligence that avoids heavyweight services and external APIs. A single-file SQLite index is a pragmatic reference for portable repo context.
- Integration surface guess: Local code index cache, MCP search tools, worker context retrieval, and offline repo analysis.
- Evidence/source URL: https://github.com/glommer/codemogger
- Date found: 2026-06-26
- Confidence note: High. Strong local-first implementation shape for coding agents.

### 2026-06-26 - awesome-agent-failures failure mode catalog

- Repo URL: https://github.com/vectara/awesome-agent-failures
- Repo name: vectara/awesome-agent-failures
- Feature or ability Thomas should consider: Curated catalog of known AI agent failure modes, real-world failures, mitigation strategies, and related resources.
- Why it matters for Thomas: Thomas should keep a failure-mode checklist close to its worker/reviewer design. A catalog can seed test cases, review rubrics, and risk labels for new agent features.
- Integration surface guess: Reviewer checklist, agent risk taxonomy, security/eval backlog, and documentation for worker failure patterns.
- Evidence/source URL: https://github.com/vectara/awesome-agent-failures
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog rather than runtime, but valuable as a durable taxonomy source.

### 2026-06-26 - TraceRoot production agent debugging

- Repo URL: https://github.com/traceroot-ai/traceroot
- Repo name: traceroot-ai/traceroot
- Feature or ability Thomas should consider: Open-source observability and self-healing layer for AI agents that captures traces, monitors production issues, and debugs with source-code and GitHub history context.
- Why it matters for Thomas: Thomas needs worker traces that connect failures back to source files, commits, PRs, and issues. TraceRoot is a concrete reference for moving from raw logs to source-aware agent debugging.
- Integration surface guess: Worker trace store, source-aware run debugger, incident monitor, and GitHub-history correlation.
- Evidence/source URL: https://github.com/traceroot-ai/traceroot
- Date found: 2026-06-26
- Confidence note: High. Strong fit for source-aware agent observability and production debugging.

### 2026-06-26 - codebase-memory-mcp structural knowledge graph

- Repo URL: https://github.com/DeusData/codebase-memory-mcp
- Repo name: DeusData/codebase-memory-mcp
- Feature or ability Thomas should consider: High-performance MCP server that indexes codebases into a persistent knowledge graph of functions, classes, call chains, HTTP routes, and cross-service links.
- Why it matters for Thomas: Thomas workers should ask structural repo questions directly instead of repeatedly scanning files. A fast knowledge graph could reduce token waste and improve task scoping.
- Integration surface guess: Local code intelligence MCP, worker context bootstrap, code-search/architecture queries, and refactor blast-radius analysis.
- Evidence/source URL: https://github.com/DeusData/codebase-memory-mcp
- Date found: 2026-06-26
- Confidence note: High. Direct match for local codebase memory and MCP-backed agent context.

### 2026-06-26 - Multi-Agent Debugger for API failures

- Repo URL: https://github.com/VishApp/multiagent-debugger
- Repo name: VishApp/multiagent-debugger
- Feature or ability Thomas should consider: CrewAI-based multi-agent debugging system that analyzes logs, code, and user questions to uncover root causes across a stack.
- Why it matters for Thomas: Thomas can borrow the pattern of specialized debugging agents, each responsible for a different signal, then synthesize one root-cause summary.
- Integration surface guess: CI failure analyzer, server incident diagnostics, reviewer/coordinator worker templates, and log-plus-code investigation flow.
- Evidence/source URL: https://github.com/VishApp/multiagent-debugger
- Date found: 2026-06-26
- Confidence note: Medium-high. Smaller project, but directly maps to multi-agent diagnostic workflows.

### 2026-06-26 - GitHub Actions Failure Analysis

- Repo URL: https://github.com/calebevans/gha-failure-analysis
- Repo name: calebevans/gha-failure-analysis
- Feature or ability Thomas should consider: GitHub Action for AI-powered workflow failure analysis using semantic log preprocessing, PR-change correlation, and LLM-generated root-cause reports.
- Why it matters for Thomas: Thomas has had repeated CI and focused-test failures. A CI failure analyzer could turn logs into actionable workboard handoffs or reviewer notes.
- Integration surface guess: CI failure triage, GitHub Actions integration, workboard blocker reports, and automated failure summaries.
- Evidence/source URL: https://github.com/calebevans/gha-failure-analysis
- Date found: 2026-06-26
- Confidence note: Medium-high. Narrow but practical; useful as a CI-specific diagnostic reference.

### 2026-06-26 - Actions AI Advisor

- Repo URL: https://github.com/ratibor78/actions-ai-advisor
- Repo name: ratibor78/actions-ai-advisor
- Feature or ability Thomas should consider: GitHub Action that fetches failed workflow logs, removes noise, extracts file paths, asks an LLM for root-cause analysis, and publishes formatted markdown with clickable file links.
- Why it matters for Thomas: The file-link and log-noise-reduction pattern is directly useful for turning CI failures into concise, navigable repair tasks for agents.
- Integration surface guess: CI log summarizer, failed-check reviewer, workboard incident entry, and test failure markdown report.
- Evidence/source URL: https://github.com/ratibor78/actions-ai-advisor
- Date found: 2026-06-26
- Confidence note: Medium. Low-star but concrete implementation; worth mining for workflow mechanics.

### 2026-06-26 - Zeroshot autonomous engineering team

- Repo URL: https://github.com/the-open-engine/zeroshot
- Repo name: the-open-engine/zeroshot
- Feature or ability Thomas should consider: CLI that orchestrates multi-agent coding workflows to implement, review, test, and verify code changes with independent reviewer feedback.
- Why it matters for Thomas: Thomas's worker/reviewer/coordinator split has the same core goal. Zeroshot is worth studying for how it makes independent review non-negotiable in an autonomous engineering loop.
- Integration surface guess: Native engineering worker loop, reviewer gate, issue-to-patch workflow, and multi-agent verification policy.
- Evidence/source URL: https://github.com/the-open-engine/zeroshot
- Date found: 2026-06-26
- Confidence note: High. Very close conceptual match to Thomas's visible worker plus reviewer direction.

### 2026-06-26 - AWS operational AI agent sample

- Repo URL: https://github.com/aws-samples/sample-operational-ai-agent
- Repo name: aws-samples/sample-operational-ai-agent
- Feature or ability Thomas should consider: Sample operational agent with automated incident detection, OpenSearch monitoring, error correlation, root-cause analysis, deployment verification, fixes, and context-aware notifications.
- Why it matters for Thomas: Thomas can adapt the incident-analysis pattern for its own worker failures, server errors, and deployment verification without assuming all problems are code-edit tasks.
- Integration surface guess: Runtime monitoring, operational incident worker, deployment verification, and post-failure remediation suggestions.
- Evidence/source URL: https://github.com/aws-samples/sample-operational-ai-agent
- Date found: 2026-06-26
- Confidence note: Medium-high. AWS-specific sample, but operational-agent patterns are portable.

### 2026-06-26 - awesome-LLM-AIOps incident-agent research map

- Repo URL: https://github.com/Jun-jie-Huang/awesome-LLM-AIOps
- Repo name: Jun-jie-Huang/awesome-LLM-AIOps
- Feature or ability Thomas should consider: Curated research map for LLM-based incident management, root-cause analysis, incident mitigation, postmortems, log analysis, and infrastructure management.
- Why it matters for Thomas: Thomas's agent failures and future operational features need a broader AIOps research base. This catalog can seed deeper dives into incident/postmortem agents and log-analysis benchmarks.
- Integration surface guess: Research backlog, incident-agent roadmap, log-analysis evals, and operational worker design.
- Evidence/source URL: https://github.com/Jun-jie-Huang/awesome-LLM-AIOps
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog rather than implementation, but broad and relevant to operational agent research.

### 2026-06-26 - NVIDIA SkillSpector

- Repo URL: https://github.com/NVIDIA/SkillSpector
- Repo name: NVIDIA/SkillSpector
- Feature or ability Thomas should consider: Security scanner for AI agent skills that detects vulnerabilities, malicious patterns, and risky behavior before installing agent skills.
- Why it matters for Thomas: Thomas is accumulating skill/plugin and worker instruction surfaces. SkillSpector is a strong reference for a first-party preinstall scanner before skills become trusted instructions.
- Integration surface guess: Skill install gate, plugin marketplace scan, CI security check, and worker bootstrap validation.
- Evidence/source URL: https://github.com/nvidia/skillspector
- Date found: 2026-06-26
- Confidence note: High. Published by NVIDIA and directly targeted at agent skill supply-chain risk.

### 2026-06-26 - AgentGuard supply-chain command interceptor

- Repo URL: https://github.com/momenbasel/AgentGuard
- Repo name: momenbasel/AgentGuard
- Feature or ability Thomas should consider: Agent supply-chain security layer that intercepts and validates package installs, `git clone`, and script downloads triggered by AI coding agents before execution.
- Why it matters for Thomas: Thomas workers can be tricked into installing packages or cloning malicious repositories. AgentGuard's pre-execution command validation model is a useful complement to static skill scanning.
- Integration surface guess: Shell/tool execution middleware, package install approval, clone/download guardrails, and security audit logging.
- Evidence/source URL: https://github.com/momenbasel/AgentGuard
- Date found: 2026-06-26
- Confidence note: High. Directly applies to Codex/Claude-style coding-agent supply-chain risk.

### 2026-06-26 - Agent S computer-use framework

- Repo URL: https://github.com/simular-ai/agent-s
- Repo name: simular-ai/agent-s
- Feature or ability Thomas should consider: Open agentic framework for autonomous computer interaction through an agent-computer interface, with experience learning for complex desktop tasks.
- Why it matters for Thomas: Thomas already has browser and desktop-adjacent automation needs. Agent S is a reference for GUI agents that learn from past experiences and operate across computer interfaces.
- Integration surface guess: Desktop automation worker, GUI action abstraction, experience memory, and visual/task replay.
- Evidence/source URL: https://github.com/simular-ai/agent-s
- Date found: 2026-06-26
- Confidence note: High. Active and directly relevant to computer-use agents.

### 2026-06-26 - ACP UI cross-platform agent client

- Repo URL: https://github.com/formulahendry/acp-ui
- Repo name: formulahendry/acp-ui
- Feature or ability Thomas should consider: Cross-platform desktop/mobile/web client for Agent Client Protocol that can connect to compatible agents such as Claude, Codex, Copilot, Qwen, Gemini, OpenCode, and redacted-acp-peer.
- Why it matters for Thomas: Thomas needs a visible portal for running and monitoring agents. ACP UI is a useful reference for a client protocol abstraction instead of hardwiring each provider UI separately.
- Integration surface guess: Thomas portal client protocol, multi-provider session UI, mobile/web companion, and agent connection registry.
- Evidence/source URL: https://github.com/formulahendry/acp-ui
- Date found: 2026-06-26
- Confidence note: Medium-high. Early but strongly relevant to multi-agent client UX.

### 2026-06-26 - DesktopAgent safety-first local automation

- Repo URL: https://github.com/alessiobianchini/DesktopAgent
- Repo name: alessiobianchini/DesktopAgent
- Feature or ability Thomas should consider: Safety-first local desktop automation agent with cross-platform core, OS adapters, UI-tree-first automation, OCR fallback, tray chat UI, and auto-updates.
- Why it matters for Thomas: Thomas can learn from safety-first desktop automation architecture, especially UI-tree-first control and OS adapter isolation for local actions.
- Integration surface guess: Desktop control worker, permission UI, OS adapter boundaries, and local automation safety model.
- Evidence/source URL: https://github.com/topics/desktop-agent?o=desc&s=forks
- Date found: 2026-06-26
- Confidence note: Medium. Small project, but the safety-first desktop architecture is relevant.

### 2026-06-26 - awesome-copilot agent supply-chain skill

- Repo URL: https://github.com/github/awesome-copilot
- Repo name: github/awesome-copilot
- Feature or ability Thomas should consider: Repository of Copilot prompts/instructions/skills, including an agent supply-chain integrity skill for manifests, version pinning, tamper detection, and provenance.
- Why it matters for Thomas: Thomas needs an explicit pattern for integrity manifests and provenance around skills/tools. This is useful both as a skill-library format reference and as a concrete supply-chain checklist.
- Integration surface guess: Skill manifest format, plugin provenance, marketplace integrity checks, and installation policy.
- Evidence/source URL: https://github.com/github/awesome-copilot/blob/main/skills/agent-supply-chain/SKILL.md
- Date found: 2026-06-26
- Confidence note: Medium-high. Official GitHub repo; the specific artifact is a skill/reference rather than a runtime.

### 2026-06-26 - Agent Client Protocol schema and SDKs

- Repo URL: https://github.com/agentclientprotocol/agent-client-protocol
- Repo name: agentclientprotocol/agent-client-protocol
- Feature or ability Thomas should consider: Standardized protocol and schema for connecting editors/clients to agents through common session, prompt, cancel, tool-call, and permission message flows.
- Why it matters for Thomas: Thomas needs visible, provider-independent agent sessions. ACP is a concrete candidate for decoupling the Thomas portal/client from individual agents like Codex, Gemini, Claude, OpenCode, and redacted-acp-peer.
- Integration surface guess: Thomas portal agent protocol, worker session API, permission prompts, and multi-provider adapter layer.
- Evidence/source URL: https://github.com/agentclientprotocol/agent-client-protocol
- Date found: 2026-06-26
- Confidence note: High. Active official protocol repository and directly relevant to interoperable agent clients.

### 2026-06-26 - BeeAI ACP implementation

- Repo URL: https://github.com/i-am-bee/acp
- Repo name: i-am-bee/acp
- Feature or ability Thomas should consider: ACP-style server implementation, client libraries, model definitions, OpenAPI spec, Python SDK, TypeScript SDK, and runnable examples for agent/client communication.
- Why it matters for Thomas: Thomas can use this as a practical reference for implementing a real agent communication server and SDK layer, not just reading the protocol spec.
- Integration surface guess: Agent protocol server, client SDK, remote worker bridge, and agent discoverability experiments.
- Evidence/source URL: https://github.com/i-am-bee/acp
- Date found: 2026-06-26
- Confidence note: Medium-high. Useful implementation reference; follow-up should distinguish this ACP lineage from Agent Client Protocol naming.

### 2026-06-26 - Agent Desktop accessibility-tree CLI

- Repo URL: https://github.com/lahfir/agent-desktop
- Repo name: lahfir/agent-desktop
- Feature or ability Thomas should consider: Native desktop automation CLI for AI agents using OS accessibility trees, structured JSON output, deterministic element refs, and MCP-oriented desktop automation.
- Why it matters for Thomas: Thomas can borrow the accessibility-tree-first design for desktop control that is more inspectable than screenshot-only automation.
- Integration surface guess: Desktop automation tool, MCP desktop server, local permission UI, and deterministic UI action logs.
- Evidence/source URL: https://github.com/lahfir/agent-desktop
- Date found: 2026-06-26
- Confidence note: High. Fresh, focused, and directly aligned with safe desktop automation.

### 2026-06-26 - CUA computer-use agent infrastructure

- Repo URL: https://github.com/trycua/cua
- Repo name: trycua/cua
- Feature or ability Thomas should consider: Open-source infrastructure for computer-use agents, including sandboxes, SDKs, and benchmarks for training and evaluating agents that control full desktops across macOS, Linux, and Windows.
- Why it matters for Thomas: Thomas may need controlled desktop sandboxes and benchmarks before exposing high-authority GUI automation. CUA is a high-signal reference for that infrastructure layer.
- Integration surface guess: Desktop sandboxing, GUI-agent benchmark runner, computer-use SDK, and worker safety tests.
- Evidence/source URL: https://github.com/topics/computer-use-agent?l=html&o=asc&s=forks
- Date found: 2026-06-26
- Confidence note: High. Large, active computer-use infrastructure project; source page was the GitHub topic listing.

### 2026-06-26 - OSU AgentSafety GUI agent benchmark

- Repo URL: https://github.com/OSU-NLP-Group/AgentSafety
- Repo name: OSU-NLP-Group/AgentSafety
- Feature or ability Thomas should consider: Benchmark suite for measuring safety of computer-use and GUI agents, including harmful behavior, prompt-injection attacks, and model misbehavior across desktop applications.
- Why it matters for Thomas: If Thomas adds desktop automation, it needs safety evals before letting agents click through email, browsers, code editors, and local files.
- Integration surface guess: GUI-agent safety tests, desktop permission policy, harmful-task red team, and release gates for computer-use features.
- Evidence/source URL: https://github.com/OSU-NLP-Group/AgentSafety
- Date found: 2026-06-26
- Confidence note: High. Directly addresses GUI-agent safety risks.

### 2026-06-26 - Agent Device mobile/desktop test automation

- Repo URL: https://github.com/callstack/agent-device
- Repo name: callstack/agent-device
- Feature or ability Thomas should consider: Device automation CLI for AI mobile app testing across iOS, Android, TV, desktop, simulators, emulators, and physical devices.
- Why it matters for Thomas: Thomas verification may eventually span mobile/desktop apps, not just web and Python tests. Agent Device is a useful reference for agent-driven app QA with real devices and simulators.
- Integration surface guess: App QA worker, mobile simulator automation, desktop app verification, and visual test evidence collection.
- Evidence/source URL: https://github.com/callstack/agent-device
- Date found: 2026-06-26
- Confidence note: Medium-high. Very fresh but from an established React Native tooling team; useful for app-testing workflows.

### 2026-06-26 - UnityAgentClient ACP editor integration

- Repo URL: https://github.com/nuskey8/UnityAgentClient
- Repo name: nuskey8/UnityAgentClient
- Feature or ability Thomas should consider: Unity Editor integration for any ACP-compatible agent, including Codex, Claude Code, Gemini CLI, Qwen, and others, with editor/assets context and built-in MCP server support.
- Why it matters for Thomas: Thomas may eventually need app/editor-specific agent adapters. UnityAgentClient shows how ACP can embed agents into a domain tool rather than forcing all work through a terminal.
- Integration surface guess: ACP adapter examples, domain-specific agent context, editor/tool integration, and MCP-backed workspace context.
- Evidence/source URL: https://github.com/nuskey8/UnityAgentClient
- Date found: 2026-06-26
- Confidence note: Medium-high. Specialized to Unity, but useful as an ACP integration pattern.

### 2026-06-26 - VS Code ACP client extension

- Repo URL: https://github.com/formulahendry/vscode-acp
- Repo name: formulahendry/vscode-acp
- Feature or ability Thomas should consider: VS Code extension that connects to ACP-compatible agents such as Claude, Codex, Copilot, Gemini, Qwen, OpenCode, Kiro, and redacted-acp-peer.
- Why it matters for Thomas: Thomas can study how editor-native ACP clients expose sessions, permissions, and multiple backend agents through a familiar developer surface.
- Integration surface guess: Agent client UX, editor integration, ACP session model, and multi-provider worker controls.
- Evidence/source URL: https://github.com/formulahendry/vscode-acp
- Date found: 2026-06-26
- Confidence note: High. Direct ACP client reference, distinct from the broader ACP UI.

### 2026-06-26 - rivet sandbox-agent remote coding-agent control

- Repo URL: https://github.com/rivet-dev/sandbox-agent
- Repo name: rivet-dev/sandbox-agent
- Feature or ability Thomas should consider: HTTP server that runs inside a sandbox and controls Claude Code, Codex, OpenCode, Cursor, Amp, or Pi while streaming events, handling permissions, and managing sessions.
- Why it matters for Thomas: Thomas needs a safer way to run repo agents in isolated sandboxes while still providing visible progress, permissions, and session control.
- Integration surface guess: Sandboxed worker runner, event streaming, permission mediation, and remote agent session management.
- Evidence/source URL: https://github.com/rivet-dev/sandbox-agent
- Date found: 2026-06-26
- Confidence note: High. Directly maps to sandboxed coding-agent orchestration.

### 2026-06-26 - GUI Agents Paper List

- Repo URL: https://github.com/OSU-NLP-Group/GUI-Agents-Paper-List
- Repo name: OSU-NLP-Group/GUI-Agents-Paper-List
- Feature or ability Thomas should consider: Curated list of GUI-agent papers, benchmarks, environments, and task domains including long-horizon professional workflows.
- Why it matters for Thomas: Desktop agents need systematic benchmark coverage. This list can seed future ranking and evaluation work across GUI tasks rather than relying on a single benchmark.
- Integration surface guess: GUI-agent research backlog, desktop benchmark selection, safety/eval matrix, and computer-use roadmap.
- Evidence/source URL: https://github.com/OSU-NLP-Group/GUI-Agents-Paper-List
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog rather than runtime, but valuable for broad GUI-agent coverage.

### 2026-06-26 - Awesome GUI Agent

- Repo URL: https://github.com/showlab/awesome-gui-agent
- Repo name: showlab/awesome-gui-agent
- Feature or ability Thomas should consider: Curated list of multi-modal GUI-agent papers, projects, and resources for assistants that operate on user screens.
- Why it matters for Thomas: Thomas can use this as a wider discovery source for GUI-agent models, datasets, toolkits, and evaluation methods before committing to a desktop automation architecture.
- Integration surface guess: GUI-agent research backlog, model/tool comparison, visual automation roadmap, and evaluation matrix.
- Evidence/source URL: https://github.com/showlab/awesome-gui-agent
- Date found: 2026-06-26
- Confidence note: Medium-high. Active catalog; useful for ongoing discovery rather than direct integration.

### 2026-06-26 - accessibility-agents specialist review skills

- Repo URL: https://github.com/Community-Access/accessibility-agents
- Repo name: Community-Access/accessibility-agents
- Feature or ability Thomas should consider: Accessibility review agents, skills, prompts, and custom instructions for Claude Code, GitHub Copilot, and Claude Desktop, with explicit caution to verify with real accessibility tools.
- Why it matters for Thomas: Thomas reviewer lanes could include specialist review packs. Accessibility agents are a good example of domain-specific reviewer skills with clear boundaries and verification expectations.
- Integration surface guess: Specialist reviewer packs, accessibility guardrails, skill verification checklist, and UI review workflows.
- Evidence/source URL: https://github.com/Community-Access/accessibility-agents
- Date found: 2026-06-26
- Confidence note: High. Practical specialist-agent material with explicit verification caveats.

### 2026-06-26 - Computer Browser Phone Use Agent Datasets

- Repo URL: https://github.com/Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets
- Repo name: Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets
- Feature or ability Thomas should consider: Curated dataset and benchmark list for computer-use, browser-use, and phone-use agents, including mobile and web settings.
- Why it matters for Thomas: If Thomas expands automation beyond repo work, it needs dataset coverage across browsers, desktops, and phones. This catalog can drive benchmark selection.
- Integration surface guess: Agent benchmark backlog, desktop/mobile/browser eval selection, and QA automation roadmap.
- Evidence/source URL: https://github.com/Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets
- Date found: 2026-06-26
- Confidence note: Medium. Catalog quality needs follow-up, but the scope matches Thomas's future automation surface.

### 2026-06-26 - awesome-ai-sandboxes provider catalog

- Repo URL: https://github.com/tizkovatereza/awesome-ai-sandboxes
- Repo name: tizkovatereza/awesome-ai-sandboxes
- Feature or ability Thomas should consider: Curated list of cloud sandbox providers for AI agents, sourced from official docs and landing pages.
- Why it matters for Thomas: Thomas will need to compare local, cloud, and hybrid sandbox options for repo and desktop agents. A sandbox-provider catalog helps avoid one-off infrastructure choices.
- Integration surface guess: Sandbox provider evaluation, worker isolation roadmap, deployment planning, and cost/security comparison.
- Evidence/source URL: https://github.com/tizkovatereza/awesome-ai-sandboxes
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog, but the official-source policy makes it useful for procurement-style research.

### 2026-06-26 - Lightpanda AI-native browser

- Repo URL: https://github.com/lightpanda-io/browser
- Repo name: lightpanda-io/browser
- Feature or ability Thomas should consider: Headless browser built from scratch for AI agents and automation, including native agent mode for navigating pages, clicking flows, filling forms, and extracting structured data.
- Why it matters for Thomas: Thomas browser workers currently depend on conventional browser automation assumptions. Lightpanda is a reference for agent-first browser ergonomics and faster web task execution.
- Integration surface guess: Browser tool runtime, web research worker, structured extraction, and lightweight browser sandbox.
- Evidence/source URL: https://github.com/lightpanda-io/browser
- Date found: 2026-06-26
- Confidence note: High. Active, purpose-built browser infrastructure for agents.

### 2026-06-26 - GitTaskBench repository-aware code-agent benchmark

- Repo URL: https://github.com/QuantaAlpha/GitTaskBench
- Repo name: QuantaAlpha/GitTaskBench
- Feature or ability Thomas should consider: Benchmark for evaluating code agents on real-world tasks that require leveraging existing repositories, environment setup, dependency handling, execution, and deployment-style workflows.
- Why it matters for Thomas: Thomas needs to measure whether repo workers can solve realistic end-to-end tasks, not only synthetic patch tasks. GitTaskBench's focus on repo leveraging and setup failures matches Thomas's pain points.
- Integration surface guess: Repo-agent benchmark suite, worker regression testing, environment setup evaluation, and cost/success reporting.
- Evidence/source URL: https://github.com/QuantaAlpha/GitTaskBench
- Date found: 2026-06-26
- Confidence note: High. Strong external benchmark fit for Thomas's repository-worker ambitions.

### 2026-06-26 - AIRTBench autonomous AI red-team benchmark

- Repo URL: https://github.com/dreadnode/AIRTBench-Code
- Repo name: dreadnode/AIRTBench-Code
- Feature or ability Thomas should consider: Implementation and dataset for measuring autonomous AI red-teaming capabilities in language-model agents.
- Why it matters for Thomas: Thomas security agents and reviewers should be tested against realistic adversarial tasks. AIRTBench can inform red-team evaluation, trace capture, and safety benchmarks.
- Integration surface guess: Security benchmark runner, red-team worker evaluation, safety regression suite, and agent trace analysis.
- Evidence/source URL: https://github.com/dreadnode/AIRTBench-Code
- Date found: 2026-06-26
- Confidence note: High. Directly relevant to autonomous security-agent evaluation.

### 2026-06-26 - ACP Bridge multi-agent orchestrator

- Repo URL: https://github.com/allvegetable/acp-bridge
- Repo name: allvegetable/acp-bridge
- Feature or ability Thomas should consider: Multi-agent orchestrator for redacted-acp-peer that manages Codex, Claude, Gemini, and OpenCode through Agent Client Protocol with parallel tasks, dependency chains, and diagnostics.
- Why it matters for Thomas: Thomas needs visible multi-agent orchestration across providers. ACP Bridge is a direct reference for provider-neutral task orchestration and dependency management.
- Integration surface guess: Thomas-native ACP orchestrator, worker dependency graph, provider adapter registry, and diagnostic event stream.
- Evidence/source URL: https://github.com/allvegetable/acp-bridge
- Date found: 2026-06-26
- Confidence note: High. Small but sharply aligned with Thomas's multi-agent/provider orchestration direction.

### 2026-06-26 - ACP adapter for Codex and Claude

- Repo URL: https://github.com/beyond5959/acp-adapter
- Repo name: beyond5959/acp-adapter
- Feature or ability Thomas should consider: ACP adapter implementation for Codex, Claude Code, and Pi, with backend-specific configs hidden behind a shared runtime shape.
- Why it matters for Thomas: Thomas can study the adapter boundary for normalizing Codex/Claude sessions without hardcoding each provider into the portal.
- Integration surface guess: ACP provider adapters, session runtime abstraction, backend config management, and interoperability tests.
- Evidence/source URL: https://github.com/beyond5959/acp-adapter
- Date found: 2026-06-26
- Confidence note: Medium-high. Directly relevant adapter pattern; maturity needs review.

### 2026-06-26 - DataSciBench data-science agent benchmark

- Repo URL: https://github.com/THUDM/DataSciBench
- Repo name: THUDM/DataSciBench
- Feature or ability Thomas should consider: Benchmark for evaluating LLM agents on data-science tasks with code, data analysis, and benchmark evaluation artifacts.
- Why it matters for Thomas: Thomas may need agents that can analyze logs, metrics, traces, and data-heavy evaluation results. DataSciBench can broaden the test suite beyond software patching.
- Integration surface guess: Data-analysis worker evaluation, SRE/log analysis benchmarks, notebook/task runner, and analytics-agent regression tests.
- Evidence/source URL: https://github.com/THUDM/DataSciBench
- Date found: 2026-06-26
- Confidence note: Medium-high. Relevant benchmark, though follow-up should inspect task format and evaluator stability.

### 2026-06-26 - Gideon autonomous security operations agent

- Repo URL: https://github.com/Cogensec/Gideon
- Repo name: Cogensec/Gideon
- Feature or ability Thomas should consider: Autonomous security-operations and red-teaming agent that investigates threats, analyzes vulnerabilities, assesses indicators, generates hardening guidance, and executes security research through an auditable workflow.
- Why it matters for Thomas: Thomas could eventually coordinate security and SRE agents. Gideon is a reference for auditable security workflows rather than one-off red-team prompts.
- Integration surface guess: Security operations worker, red-team investigation flow, auditable action logs, and hardening recommendation pipeline.
- Evidence/source URL: https://github.com/topics/ai-red-team?l=typescript&o=desc&s=updated
- Date found: 2026-06-26
- Confidence note: Medium. Fresh/smaller project, but the auditable security-agent workflow is relevant.

### 2026-06-26 - xacpx remote ACP session control

- Repo URL: https://github.com/gadzan/xacpx
- Repo name: gadzan/xacpx
- Feature or ability Thomas should consider: Remote control layer for ACP agent sessions, including Codex, Claude Code, and Gemini, from chat channels such as WeChat, Feishu, and Yuanbao without a terminal.
- Why it matters for Thomas: Thomas portal/chat control may need remote session commands and visible agent status from non-terminal surfaces. xacpx is a reference for chat-driven ACP control.
- Integration surface guess: Chat-to-agent bridge, remote session controls, no-terminal worker monitoring, and ACP command routing.
- Evidence/source URL: https://github.com/topics/acpx
- Date found: 2026-06-26
- Confidence note: Medium. Topic-sourced and smaller, but relevant to remote ACP control patterns.

### 2026-06-26 - OpenACP messaging bridge for coding agents

- Repo URL: https://github.com/Open-ACP/OpenACP
- Repo name: Open-ACP/OpenACP
- Feature or ability Thomas should consider: Self-hosted bridge that manages ACP coding-agent sessions for Claude Code, Codex, and similar agents from messaging platforms such as Telegram and Discord.
- Why it matters for Thomas: Thomas needs visible remote control over agent sessions without hiding work in one process. OpenACP provides a concrete session-layer reference for spawning agents, routing messages, and surfacing permissions.
- Integration surface guess: Thomas chat-to-worker bridge, ACP session manager, remote worker control, and permission/event routing.
- Evidence/source URL: https://github.com/Open-ACP/OpenACP
- Date found: 2026-06-26
- Confidence note: High. Directly relevant to provider-neutral session orchestration over ACP.

### 2026-06-26 - codex-acp bridge

- Repo URL: https://github.com/cola-io/codex-acp
- Repo name: cola-io/codex-acp
- Feature or ability Thomas should consider: ACP-compatible bridge that exposes the OpenAI Codex runtime to ACP clients over stdio.
- Why it matters for Thomas: Thomas can use this as a narrow reference for wrapping Codex as a protocol-compatible worker rather than coupling the portal directly to one client implementation.
- Integration surface guess: Codex worker adapter, ACP client compatibility testing, stdio agent bridge, and provider abstraction.
- Evidence/source URL: https://github.com/topics/agent-client-protocol?o=desc&s=forks
- Date found: 2026-06-26
- Confidence note: Medium-high. Topic-sourced but focused on exactly the Codex-to-ACP bridge shape Thomas needs to study.

### 2026-06-26 - Browser MCP browser automation server

- Repo URL: https://github.com/BrowserMCP/mcp
- Repo name: BrowserMCP/mcp
- Feature or ability Thomas should consider: MCP server plus Chrome extension that lets AI applications automate a user's browser through MCP-compatible clients.
- Why it matters for Thomas: Thomas browser workers need controlled access to a real browser. Browser MCP is a practical reference for exposing browser automation through MCP instead of custom one-off APIs.
- Integration surface guess: Browser MCP adapter, web research worker, browser permission model, and visual verification workflows.
- Evidence/source URL: https://github.com/BrowserMCP/mcp
- Date found: 2026-06-26
- Confidence note: High. Directly maps to browser automation for agent clients.

### 2026-06-26 - Browser Harness self-healing browser agent harness

- Repo URL: https://github.com/browser-use/browser-harness
- Repo name: browser-use/browser-harness
- Feature or ability Thomas should consider: Self-healing harness from the Browser Use organization for enabling LLMs to complete browser tasks with recovery behavior.
- Why it matters for Thomas: Thomas browser automation should recover from common web failures and report evidence, not just click once and fail. Browser Harness is a strong reference for resilient browser-agent loops.
- Integration surface guess: Browser worker harness, web QA task runner, recovery-loop design, and browser evidence capture.
- Evidence/source URL: https://github.com/browser-use
- Date found: 2026-06-26
- Confidence note: Medium-high. Organization page confirms the repository; follow-up should inspect implementation details directly.

### 2026-06-26 - awesome-agent-harness engineering resources

- Repo URL: https://github.com/Picrew/awesome-agent-harness
- Repo name: Picrew/awesome-agent-harness
- Feature or ability Thomas should consider: Curated harness-engineering resource list spanning agent frameworks, tools, benchmarks, and practical guides for making agents reliable.
- Why it matters for Thomas: Thomas is essentially becoming a native agent harness. This catalog can seed future ranking and prevent blind spots around harness patterns.
- Integration surface guess: Research backlog, ranker input, harness pattern comparison, and reliability roadmap.
- Evidence/source URL: https://github.com/Picrew/awesome-agent-harness
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog, but recent and aligned with Thomas's harness direction.

### 2026-06-26 - awesome-harness-engineering

- Repo URL: https://github.com/ai-boost/awesome-harness-engineering
- Repo name: ai-boost/awesome-harness-engineering
- Feature or ability Thomas should consider: Awesome list for AI agent harness engineering covering tools, patterns, evals, memory, MCP, permissions, observability, and orchestration.
- Why it matters for Thomas: This complements the research queue by organizing the exact systems concerns Thomas must handle: permissions, memory, evals, and orchestration.
- Integration surface guess: Harness architecture research, queue/ranking input, permission/eval comparison, and future Thomas feature taxonomy.
- Evidence/source URL: https://github.com/ai-boost/awesome-harness-engineering
- Date found: 2026-06-26
- Confidence note: Medium-high. Catalog rather than runtime, but broad and directly scoped to Thomas's agent-harness problem.

### 2026-06-26 - Awesome Code-as-Agent Harness Papers

- Repo URL: https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers
- Repo name: YennNing/Awesome-Code-as-Agent-Harness-Papers
- Feature or ability Thomas should consider: Paper list organized around harness interface, harness mechanisms, and scaling the harness across coding assistants, GUI/OS automation, scientific discovery, and embodied agents.
- Why it matters for Thomas: Thomas needs a theory-backed view of harness layers so feature adoption does not collapse into disconnected tools.
- Integration surface guess: Research queue taxonomy, architecture notes, benchmark selection, and long-term agent runtime roadmap.
- Evidence/source URL: https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers
- Date found: 2026-06-26
- Confidence note: Medium. Research catalog, but useful for framing future deeper reviews.

### 2026-06-26 - LLM Agents Papers catalog

- Repo URL: https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- Repo name: AGI-Edgerunners/LLM-Agents-Papers
- Feature or ability Thomas should consider: Broad paper catalog for LLM-based agents, covering memory, planning, tool use, multi-agent systems, and related agent research areas.
- Why it matters for Thomas: The queue has many implementation repos; this catalog provides a durable research backstop for ideas that should be evaluated before being built into Thomas.
- Integration surface guess: Long-term research backlog, ranking evidence, agent architecture survey, and planned-feature citations.
- Evidence/source URL: https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- Date found: 2026-06-26
- Confidence note: Medium. Broad catalog, so value is in discovery and citations rather than direct integration.

### 2026-06-26 - agent-replay execution trace replay

- Repo URL: https://github.com/manasvardhan/agent-replay
- Repo name: manasvardhan/agent-replay
- Feature or ability Thomas should consider: Agent execution trace recorder that captures LLM calls, tool use, decisions, and state changes, then replays runs step by step and diffs behavior across runs.
- Why it matters for Thomas: Thomas workers need replayable evidence when runs fail or drift. A replay/diff layer could make reviewer and coordinator work much more concrete than summaries alone.
- Integration surface guess: Worker trace recorder, run replay UI, behavior diffing, and debugging artifacts for failed tasks.
- Evidence/source URL: https://github.com/manasvardhan/agent-replay
- Date found: 2026-06-26
- Confidence note: High. Direct match for agent observability and replay needs.

### 2026-06-26 - Siddhant-K agent-trace

- Repo URL: https://github.com/Siddhant-K-code/agent-trace
- Repo name: Siddhant-K-code/agent-trace
- Feature or ability Thomas should consider: Agent observability package for seeing what an agent did, why it cost that much, and what should be fixed.
- Why it matters for Thomas: Thomas needs low-friction telemetry around worker cost, decisions, and repair opportunities. agent-trace is a compact reference for exposing those signals.
- Integration surface guess: Agent run telemetry, cost tracing, tool-call summaries, and post-run review reports.
- Evidence/source URL: https://github.com/Siddhant-K-code/agent-trace
- Date found: 2026-06-26
- Confidence note: Medium-high. Very new but directly relevant to lightweight agent tracing.

### 2026-06-26 - clens Claude Code session capture

- Repo URL: https://github.com/silouone/clens
- Repo name: silouone/clens
- Feature or ability Thomas should consider: Local-first Claude Code session capture and analysis that traces tool calls, detects backtracks, analyzes decisions, tracks edit chains, and measures plan drift.
- Why it matters for Thomas: Thomas uses Codex/Claude-like workers where plan drift and edit chains are key review signals. clens is a relevant local-first pattern for transcript diagnostics.
- Integration surface guess: Worker transcript analyzer, plan-drift detector, edit-chain reviewer, and local session observability.
- Evidence/source URL: https://github.com/topics/agent-tracing
- Date found: 2026-06-26
- Confidence note: Medium. Topic-sourced and small, but the feature set maps tightly to Thomas worker reviews.

### 2026-06-26 - mcp-browser-use persistent browser-use MCP

- Repo URL: https://github.com/Saik0s/mcp-browser-use
- Repo name: Saik0s/mcp-browser-use
- Feature or ability Thomas should consider: MCP wrapper around Browser Use that exposes long-running real-browser automation over HTTP rather than stdio to avoid timeout failures.
- Why it matters for Thomas: Thomas web workers may need browser tasks that take longer than standard MCP timeouts. A persistent HTTP browser MCP daemon is a practical design reference.
- Integration surface guess: Browser MCP service, long-running web research jobs, timeout-resistant tool transport, and browser task status reporting.
- Evidence/source URL: https://github.com/Saik0s/mcp-browser-use
- Date found: 2026-06-26
- Confidence note: Medium-high. Practical browser-use adaptation; needs maturity review.

### 2026-06-26 - Playwright MCP official browser server

- Repo URL: https://github.com/microsoft/playwright-mcp
- Repo name: microsoft/playwright-mcp
- Feature or ability Thomas should consider: MCP server that lets LLMs interact with web pages through Playwright and structured accessibility snapshots rather than screenshots.
- Why it matters for Thomas: Thomas browser automation should prefer structured accessibility snapshots when possible. Playwright MCP is a strong official reference for stable browser tool contracts.
- Integration surface guess: Browser automation backend, accessibility snapshot extraction, web QA worker, and MCP tool bridge.
- Evidence/source URL: https://github.com/microsoft/playwright-mcp
- Date found: 2026-06-26
- Confidence note: High. Official Microsoft Playwright MCP implementation and directly relevant.

### 2026-06-26 - Browser Use Box remote browser automation agent

- Repo URL: https://github.com/browser-use/bux
- Repo name: browser-use/bux
- Feature or ability Thomas should consider: Always-on browser automation agent that runs on a user-controlled box with Browser Use Cloud, Telegram, and a real browser for Playwright-style tasks.
- Why it matters for Thomas: Thomas may need remote browser workers that remain visible and controllable from chat or portal surfaces. Browser Use Box is a relevant pattern for persistent browser agents.
- Integration surface guess: Remote browser worker, chat control channel, browser session hosting, and visible long-running web automation.
- Evidence/source URL: https://github.com/topics/browser-use?l=python
- Date found: 2026-06-26
- Confidence note: Medium-high. Topic-sourced but from the Browser Use org and aligned with remote browser worker design.

### 2026-06-26 - kontex-cli local agent network observability

- Repo URL: https://github.com/pankaj-agrawalla/kontex-cli
- Repo name: pankaj-agrawalla/kontex-cli
- Feature or ability Thomas should consider: Local HTTP proxy and dashboard for intercepting, inspecting, replaying, and forking every LLM call in an AI agent network without cloud dependency.
- Why it matters for Thomas: Thomas needs local-first observability and replay controls for agent calls, especially when running sensitive repo or desktop tasks.
- Integration surface guess: Local model-call proxy, replay/fork UI, network observability, and privacy-preserving trace store.
- Evidence/source URL: https://github.com/topics/ai-agent-observability
- Date found: 2026-06-26
- Confidence note: Medium. Small project, but the local proxy/replay idea is useful.

### 2026-06-26 - Replay MCP time-travel debugging

- Repo URL: https://github.com/replayio/replay-mcp
- Repo name: replayio/replay-mcp
- Feature or ability Thomas should consider: MCP tool surface for time-travel debugging Replay recordings, including console output, source, variables, React components, and performance data.
- Why it matters for Thomas: Thomas UI and browser workers could benefit from replayable debug recordings that agents can inspect through MCP rather than only screenshots/logs.
- Integration surface guess: Browser/UI debug MCP, replay recording analysis, frontend failure investigation, and agent-assisted time-travel debugging.
- Evidence/source URL: https://docs.replay.io/basics/replay-mcp/overview
- Date found: 2026-06-26
- Confidence note: Medium-high. Evidence is docs, but the MCP capability is directly relevant if repository/source is available.

### 2026-06-26 - AgentReplay local desktop evals and memory

- Repo URL: https://github.com/agentreplay/agentreplay
- Repo name: agentreplay/agentreplay
- Feature or ability Thomas should consider: Local-first desktop application for agent observability, persistent memory, trace capture, and evals that keeps data on the user's machine.
- Why it matters for Thomas: Thomas needs local-first run evidence and memory without forcing sensitive repo work into SaaS. AgentReplay is a strong UX reference for local trace browsing plus persistent agent memory.
- Integration surface guess: Local run inspector, worker memory store, desktop/portal observability, and eval artifact viewer.
- Evidence/source URL: https://github.com/agentreplay/agentreplay
- Date found: 2026-06-26
- Confidence note: High. Directly matches local-first observability and memory goals.

### 2026-06-26 - agent-inspect local execution trees

- Repo URL: https://github.com/rajudandigam/agent-inspect
- Repo name: rajudandigam/agent-inspect
- Feature or ability Thomas should consider: Local execution-tree renderer for TypeScript AI agents that turns manual steps, tool calls, LLM calls, logs, failures, durations, and metadata into readable terminal trees.
- Why it matters for Thomas: Thomas worker traces should be readable without requiring a large dashboard. Execution trees are a compact representation for reviewer/coordinator triage.
- Integration surface guess: Terminal trace viewer, post-run summaries, task failure reports, and local worker debugging.
- Evidence/source URL: https://github.com/rajudandigam/agent-inspect
- Date found: 2026-06-26
- Confidence note: High. Focused local observability concept with immediate fit for worker trace output.

### 2026-06-26 - CyberArk agentwatch observability

- Repo URL: https://github.com/cyberark/agentwatch
- Repo name: cyberark/agentwatch
- Feature or ability Thomas should consider: AI observability framework for intercepting, logging, and analyzing agent interactions across platforms and frameworks.
- Why it matters for Thomas: Thomas needs framework-agnostic visibility as it evaluates Codex, Claude, Gemini, MCP, browser, and local tool workers. agentwatch is relevant as an interception and analysis layer.
- Integration surface guess: Agent interaction monitor, MCP/tool-call trace collection, multi-provider observability, and security review logs.
- Evidence/source URL: https://github.com/cyberark/agentwatch
- Date found: 2026-06-26
- Confidence note: Medium-high. Credible security vendor and relevant observability scope.

### 2026-06-26 - Dreadnode Agent Lens

- Repo URL: https://github.com/dreadnode/agent-lens
- Repo name: dreadnode/agent-lens
- Feature or ability Thomas should consider: Agent observability and replay tooling for AI safety and interpretability research, including Claude agent SDK sessions and trajectory validation models.
- Why it matters for Thomas: Thomas can use safety-oriented trajectory validation to turn raw worker traces into reviewable evidence and eval inputs.
- Integration surface guess: Agent trajectory schema, replay/eval pipeline, safety review artifacts, and Claude/Codex session analysis.
- Evidence/source URL: https://github.com/dreadnode/agent-lens
- Date found: 2026-06-26
- Confidence note: High. Strong fit for replay plus safety interpretation.

### 2026-06-26 - CyberArk Agent Guard secrets and MCP proxy

- Repo URL: https://github.com/cyberark/agent-guard
- Repo name: cyberark/agent-guard
- Feature or ability Thomas should consider: Agent security toolkit with secure secrets retrieval for AI agents and traceability of MCP communications through an MCP proxy.
- Why it matters for Thomas: Thomas needs secure secret access and auditable MCP traffic before broadening tool authority. Agent Guard offers a concrete security-control reference.
- Integration surface guess: Secrets provider integration, MCP proxy, tool-call auditing, and agent identity/security policy.
- Evidence/source URL: https://github.com/cyberark/agent-guard
- Date found: 2026-06-26
- Confidence note: High. Directly relevant security control from a security-focused vendor.

### 2026-06-26 - Monte Carlo agent toolkit

- Repo URL: https://github.com/monte-carlo-data/mc-agent-toolkit
- Repo name: monte-carlo-data/mc-agent-toolkit
- Feature or ability Thomas should consider: Toolkit for AI coding agents that brings data and agent observability, monitoring, triaging, troubleshooting, and health checks into tools such as Claude Code and Cursor.
- Why it matters for Thomas: Thomas can adapt this kind of domain toolkit pattern for agent health, data quality, and production issue triage inside worker sessions.
- Integration surface guess: Worker health checks, data/SRE specialist skills, observability toolkit packaging, and troubleshooting commands.
- Evidence/source URL: https://github.com/topics/agent-observability
- Date found: 2026-06-26
- Confidence note: Medium-high. Topic-sourced but associated with an established data observability vendor.

### 2026-06-26 - Pluribus context receipts

- Repo URL: https://github.com/caioribeiroclw-pixel/pluribus
- Repo name: caioribeiroclw-pixel/pluribus
- Feature or ability Thomas should consider: Privacy-safe context receipts for AI coding agents that prove which context, memory, tools, skills, compactions, and security findings crossed the boundary without logging raw content.
- Why it matters for Thomas: Thomas needs auditability without leaking sensitive content. Context receipts could help prove what an agent saw and used while preserving privacy.
- Integration surface guess: Privacy-preserving audit logs, worker context receipts, skill/tool provenance records, and security review evidence.
- Evidence/source URL: https://github.com/topics/ai-agent-observability
- Date found: 2026-06-26
- Confidence note: Medium. Small project, but the context-receipt idea is highly relevant.

### 2026-06-26 - Agent PR Replay

- Repo URL: https://github.com/sshh12/agent-pr-replay
- Repo name: sshh12/agent-pr-replay
- Feature or ability Thomas should consider: Tool that takes merged PRs, reverse-engineers task prompts, runs Claude Code against them, and compares agent output with what humans actually shipped.
- Why it matters for Thomas: Thomas needs empirical replay benchmarks based on real repo history. PR replay can turn a project's past work into targeted evaluation tasks for coding agents.
- Integration surface guess: Repo-specific coding-agent benchmark generator, PR replay harness, reviewer comparison reports, and regression suite.
- Evidence/source URL: https://github.com/sshh12/agent-pr-replay
- Date found: 2026-06-26
- Confidence note: High. Directly relevant to repo-aware benchmark generation and agent evaluation.

### 2026-06-26 - Agent Policy Engine hard action boundaries

- Repo URL: https://github.com/kahalewai/agent-policy-engine
- Repo name: kahalewai/agent-policy-engine
- Feature or ability Thomas should consider: Policy enforcement runtime that sits between agent reasoning and action execution, enforcing hard boundaries for real production environments.
- Why it matters for Thomas: Thomas needs tool policy outside the model prompt. A policy enforcement point can make approvals, blocked actions, and audit trails explicit instead of relying on agent self-restraint.
- Integration surface guess: Tool execution middleware, command approval policy, sandbox egress control, and worker audit logs.
- Evidence/source URL: https://github.com/kahalewai/agent-policy-engine
- Date found: 2026-06-26
- Confidence note: High. Directly maps to Thomas's need for hard tool-call boundaries.

### 2026-06-26 - Cordum open agent control plane

- Repo URL: https://github.com/cordum-io/cordum
- Repo name: cordum-io/cordum
- Feature or ability Thomas should consider: Open agent control plane for autonomous AI agents with pre-execution policy enforcement, approval gates, and audit trails across frameworks including MCP, LangChain, and CrewAI.
- Why it matters for Thomas: Thomas's native orchestration needs a central control plane that can govern heterogeneous workers and tools. Cordum is a concrete reference for approvals and auditability.
- Integration surface guess: Native agent control plane, approval queues, cross-framework policy adapter, and run audit dashboard.
- Evidence/source URL: https://github.com/topics/policy-engine
- Date found: 2026-06-26
- Confidence note: Medium-high. Topic-sourced, but the positioning is highly relevant.

### 2026-06-26 - Neuledge Context local-first documentation MCP

- Repo URL: https://github.com/neuledge/context
- Repo name: neuledge/context
- Feature or ability Thomas should consider: Local-first MCP server backed by a package-documentation registry so agents can search and query library docs locally.
- Why it matters for Thomas: Thomas workers repeatedly need current library/API context without wasting tokens or browsing unreliable pages. A local docs MCP can reduce hallucinated API usage and repeated research.
- Integration surface guess: MCP documentation server, worker bootstrap docs, package-aware code assistance, and offline context cache.
- Evidence/source URL: https://github.com/neuledge/context
- Date found: 2026-06-26
- Confidence note: High. Strong fit for local-first agent context retrieval.

### 2026-06-26 - Context7 up-to-date code docs MCP

- Repo URL: https://github.com/upstash/context7
- Repo name: upstash/context7
- Feature or ability Thomas should consider: MCP/CLI platform for bringing up-to-date library documentation and examples into agent prompts and coding workflows.
- Why it matters for Thomas: Context7 is a major docs-context pattern that Thomas can compare against Neuledge Context for API grounding in worker sessions.
- Integration surface guess: Documentation MCP adapter, coding-worker context source, dependency-specific guidance, and prompt grounding.
- Evidence/source URL: https://github.com/upstash/context7
- Date found: 2026-06-26
- Confidence note: High. Active, widely referenced docs-context tool for agents.

### 2026-06-26 - Phoenix AI observability and evaluation

- Repo URL: https://github.com/arize-ai/phoenix
- Repo name: arize-ai/phoenix
- Feature or ability Thomas should consider: Open-source AI observability and evaluation platform with tracing, experiments, datasets, prompt management, and coding-agent skills for adding observability.
- Why it matters for Thomas: Thomas needs production-grade tracing and evals as agent runs become more complex. Phoenix is a strong reference for combining observability and evaluation workflows.
- Integration surface guess: Agent trace backend, eval dashboard, prompt/run experiments, and worker observability skills.
- Evidence/source URL: https://github.com/arize-ai/phoenix
- Date found: 2026-06-26
- Confidence note: High. Mature open-source observability/eval platform with agent-specific material.

### 2026-06-26 - Evaluating AI Agents course repo

- Repo URL: https://github.com/ksm26/Evaluating-AI-Agents
- Repo name: ksm26/Evaluating-AI-Agents
- Feature or ability Thomas should consider: Hands-on course repository for evaluating, debugging, and improving AI agents using observability tools, experiments, and metrics.
- Why it matters for Thomas: Thomas needs a repeatable eval practice, not just a list of tools. This repo can inform training material and evaluation checklists for Thomas workers.
- Integration surface guess: Agent eval playbook, reviewer/ranker methodology, worker regression criteria, and internal docs.
- Evidence/source URL: https://github.com/ksm26/Evaluating-AI-Agents
- Date found: 2026-06-26
- Confidence note: Medium-high. Educational repo, but directly aligned with agent evaluation practice.

### 2026-06-26 - GenAI Agents implementation tutorial library

- Repo URL: https://github.com/NirDiamant/GenAI_Agents
- Repo name: NirDiamant/GenAI_Agents
- Feature or ability Thomas should consider: Large tutorial and implementation repository covering conversational agents, multi-agent systems, RAG, workflows, and practical agent patterns.
- Why it matters for Thomas: Thomas can mine this for concrete implementation examples and compare patterns before building custom features.
- Integration surface guess: Research backlog, prototype references, implementation examples, and ranker follow-up targets.
- Evidence/source URL: https://github.com/nirdiamant/genai_agents
- Date found: 2026-06-26
- Confidence note: Medium-high. Broad educational implementation library; best used for pattern mining rather than direct dependency.

### 2026-06-26 - awesome_ai_agents broad agent catalog

- Repo URL: https://github.com/jim-schwoebel/awesome_ai_agents
- Repo name: jim-schwoebel/awesome_ai_agents
- Feature or ability Thomas should consider: Curated hub of AI-agent tools, frameworks, datasets, projects, and workflows.
- Why it matters for Thomas: The queue is large enough that discovery should become systematic. This catalog can seed future targeted searches and help the ranker spot gaps.
- Integration surface guess: Research backlog source, ranking input, feature taxonomy, and ongoing dedupe discovery.
- Evidence/source URL: https://github.com/jim-schwoebel/awesome_ai_agents
- Date found: 2026-06-26
- Confidence note: Medium. Catalog, but useful for sustained agent ecosystem discovery.

### 2026-06-26 - Delegate multi-agent worktree orchestration

- Repo URL: https://github.com/nikhilgarg28/delegate
- Repo name: nikhilgarg28/delegate
- Feature or ability Thomas should consider: CLI-driven multi-agent delegation that fans tasks out across git worktrees and coordinates agent outputs back to a parent workflow.
- Why it matters for Thomas: Thomas is already moving from hidden heartbeats toward visible worker coordination. Delegate is a focused reference for worktree isolation, subtask dispatch, and merge-back ergonomics.
- Integration surface guess: Workboard claim spawning, worker workspace creation, branch/worktree lifecycle helpers, and merge-review handoff flows.
- Evidence/source URL: https://github.com/nikhilgarg28/delegate
- Date found: 2026-06-26
- Confidence note: Medium confidence; very relevant orchestration shape, but implementation maturity should be checked before borrowing patterns.

### 2026-06-26 - AI Agent checkpoint and resume

- Repo URL: https://github.com/AxmeAI/ai-agent-checkpoint-and-resume
- Repo name: AxmeAI/ai-agent-checkpoint-and-resume
- Feature or ability Thomas should consider: Checkpoint-and-resume primitives for long-running agent tasks so interrupted runs can continue from saved state rather than restarting.
- Why it matters for Thomas: Heartbeat and worker runs can be interrupted by context compaction, tool failures, or machine restarts. Durable checkpoints would make Thomas workers less wasteful and more auditable.
- Integration surface guess: Worker run state store, task journal snapshots, queue/resume CLI, and claim recovery metadata.
- Evidence/source URL: https://github.com/AxmeAI/ai-agent-checkpoint-and-resume
- Date found: 2026-06-26
- Confidence note: Medium-low confidence; concept is high-value, but repo depth and production readiness need review by the ranker.

### 2026-06-26 - Cognee memory engine

- Repo URL: https://github.com/topoteretes/cognee
- Repo name: topoteretes/cognee
- Feature or ability Thomas should consider: AI memory engine that builds structured knowledge graphs and retrieval layers from documents, conversations, and code-adjacent context.
- Why it matters for Thomas: Thomas needs memory that preserves decisions, evidence, and project facts across many visible workers without turning every thread into an unbounded transcript.
- Integration surface guess: Thomas memory backend, repo-research ingestion, workboard context retrieval, and evidence-linked run summaries.
- Evidence/source URL: https://github.com/topoteretes/cognee
- Date found: 2026-06-26
- Confidence note: High confidence; active, broadly adopted memory/RAG project with a direct fit for durable agent context.

### 2026-06-26 - RunbookAI operational agent

- Repo URL: https://github.com/Runbook-Agent/RunbookAI
- Repo name: Runbook-Agent/RunbookAI
- Feature or ability Thomas should consider: Runbook-oriented AI agent workflows for operational diagnosis, guided remediation, and structured incident response.
- Why it matters for Thomas: Thomas has recurring maintenance and CI/debug tasks. Runbook-style plans could make worker actions more repeatable, reviewable, and less dependent on ad hoc prompting.
- Integration surface guess: Workboard task templates, incident/debug playbooks, CI triage lanes, and verification checklist generation.
- Evidence/source URL: https://github.com/Runbook-Agent/RunbookAI
- Date found: 2026-06-26
- Confidence note: Medium confidence; the operational workflow framing is strong, but Thomas should inspect how much is reusable versus app-specific.

### 2026-06-26 - agent-memory-mcp persistent memory server

- Repo URL: https://github.com/ipiton/agent-memory-mcp
- Repo name: ipiton/agent-memory-mcp
- Feature or ability Thomas should consider: MCP server for persistent agent memory exposed as tools instead of hidden prompt stuffing.
- Why it matters for Thomas: A memory MCP gives Thomas a clean boundary for storing and retrieving facts across agents, while keeping memory operations observable and permissionable.
- Integration surface guess: MCP adapter layer, Thomas memory read/write tools, worker context bootstrap, and audit logs for memory mutations.
- Evidence/source URL: https://github.com/ipiton/agent-memory-mcp
- Date found: 2026-06-26
- Confidence note: Medium confidence; focused implementation with useful interface ideas, though scale and conflict-handling need review.

### 2026-06-26 - Mnemon agent memory system

- Repo URL: https://github.com/mnemon-dev/mnemon
- Repo name: mnemon-dev/mnemon
- Feature or ability Thomas should consider: Agent memory infrastructure for extracting, organizing, and retrieving durable memories from agent sessions.
- Why it matters for Thomas: Thomas worker threads need shared memory that can distinguish durable project facts from transient run noise. Mnemon is another concrete memory model to compare against Cognee and MCP memory servers.
- Integration surface guess: Memory compaction service, conversation-to-memory extraction, worker bootstrap context, and ranker evidence stores.
- Evidence/source URL: https://github.com/mnemon-dev/mnemon
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising memory specialization, but should be evaluated for data model clarity and operational maturity.

### 2026-06-26 - Polos AI agent workforce orchestration

- Repo URL: https://github.com/polos-dev/polos
- Repo name: polos-dev/polos
- Feature or ability Thomas should consider: Multi-agent workforce orchestration with task routing, agent assignment, and coordination patterns.
- Why it matters for Thomas: Thomas is converging on native visible worker lanes. Polos can inform how to model worker pools, roles, and handoffs without hard-coding every lane.
- Integration surface guess: Workboard scheduling, agent role registry, task-router heuristics, and multi-worker status surfaces.
- Evidence/source URL: https://github.com/polos-dev/polos
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful architecture reference, with implementation details needing deeper inspection.

### 2026-06-26 - AgentGate human approval layer

- Repo URL: https://github.com/agentkitai/agentgate
- Repo name: agentkitai/agentgate
- Feature or ability Thomas should consider: Human-in-the-loop approval gateway for AI agent actions, including pausing sensitive tool calls until reviewed.
- Why it matters for Thomas: As Thomas automates code, commits, and external tools, explicit approval gateways can prevent unsafe high-impact actions while preserving worker autonomy for low-risk steps.
- Integration surface guess: Tool-call policy engine, workboard approval prompts, commit/push gates, and audit trail for approved or denied actions.
- Evidence/source URL: https://github.com/agentkitai/agentgate
- Date found: 2026-06-26
- Confidence note: Medium confidence; high-value control-plane idea, but Thomas should compare it with existing workboard/commit gate semantics.

### 2026-06-26 - Agent Tool Protocol sandboxed code tools

- Repo URL: https://github.com/mondaycom/agent-tool-protocol
- Repo name: mondaycom/agent-tool-protocol
- Feature or ability Thomas should consider: Code-first tool protocol where agents execute TypeScript/JavaScript snippets in secure sandboxes with approvals, caching, logging, OpenAPI, and MCP compatibility.
- Why it matters for Thomas: Thomas currently relies on structured tool calls and commit gates. ATP is a concrete alternative for complex multi-step tool interactions without bloating prompts with giant schemas.
- Integration surface guess: Tool execution gateway, MCP/OpenAPI bridge, tool-call approval flow, sandbox policy, and run observability.
- Evidence/source URL: https://github.com/mondaycom/agent-tool-protocol
- Date found: 2026-06-26
- Confidence note: High confidence; active implementation with direct relevance to secure agent tool use, though protocol fit needs architecture review.

### 2026-06-26 - Statewright state-machine guardrails

- Repo URL: https://github.com/statewright/statewright
- Repo name: statewright/statewright
- Feature or ability Thomas should consider: State-machine guardrails for AI agents that constrain agent behavior to explicit allowed transitions.
- Why it matters for Thomas: Workboard tasks, claims, commits, approvals, and releases already have implicit states. Making those transitions explicit would reduce stuck claims and unsafe state jumps.
- Integration surface guess: Workboard lifecycle model, claim/release validation, worker step transitions, and approval-state enforcement.
- Evidence/source URL: https://github.com/statewright/statewright
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; focused match for guardrail design, with implementation depth to be checked by the ranker.

### 2026-06-26 - XState-powered LLM agents

- Repo URL: https://github.com/statelyai/agent
- Repo name: statelyai/agent
- Feature or ability Thomas should consider: LLM agents modeled with XState state machines for predictable control flow and inspectable state transitions.
- Why it matters for Thomas: Thomas can borrow the idea of representing worker runs as statecharts, making UI status, resumption, and error handling easier to reason about.
- Integration surface guess: Native worker runtime, task status visualization, durable run state, and deterministic replay/test fixtures.
- Evidence/source URL: https://github.com/statelyai/agent
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful concept and ecosystem fit, but Thomas should verify activity and API stability.

### 2026-06-26 - Task Graph MCP multi-agent coordination

- Repo URL: https://github.com/Oortonaut/task-graph-mcp
- Repo name: Oortonaut/task-graph-mcp
- Feature or ability Thomas should consider: MCP coordination primitives for multi-agent codebase work, including worker task tracking and file-change coordination.
- Why it matters for Thomas: This maps directly to Thomas’s problem of multiple visible workers avoiding duplicate work, conflicting edits, and dependency mistakes.
- Integration surface guess: Workboard MCP server, file-scope claims, dependency graph tracking, and cross-agent coordination messages.
- Evidence/source URL: https://github.com/Oortonaut/task-graph-mcp
- Date found: 2026-06-26
- Confidence note: High confidence; direct match for Thomas multi-agent coordination, though security and merge semantics need review.

### 2026-06-26 - Parallel Code worktree agent UI

- Repo URL: https://github.com/johannesjo/parallel-code
- Repo name: johannesjo/parallel-code
- Feature or ability Thomas should consider: Desktop UI for running Claude Code, Codex, Gemini, and other coding agents side-by-side in isolated git worktrees with diff review.
- Why it matters for Thomas: The user explicitly prefers visible worker threads and readable progress. Parallel Code is a strong reference for parallel worker UX, worktree isolation, diff review, and merge ergonomics.
- Integration surface guess: Thomas portal worker dashboard, worktree spawn/import, diff-review pane, CI watcher, and task progress timeline.
- Evidence/source URL: https://github.com/johannesjo/parallel-code
- Date found: 2026-06-26
- Confidence note: High confidence; active, concrete, and closely aligned with Thomas’s native orchestration direction.

### 2026-06-26 - Agent Orchestrator feedback-loop supervisor

- Repo URL: https://github.com/AgentWrapper/agent-orchestrator
- Repo name: AgentWrapper/agent-orchestrator
- Feature or ability Thomas should consider: Agent-agnostic orchestrator for parallel coding agents in isolated workspaces with CI failure, review comment, and merge-conflict feedback routing.
- Why it matters for Thomas: Thomas needs more than spawn-and-watch; it needs feedback loops that route CI and review failures back to the responsible worker without losing ownership.
- Integration surface guess: Worker daemon, SCM/CI observer, feedback router, immutable run facts, and portal status stream.
- Evidence/source URL: https://github.com/AgentWrapper/agent-orchestrator
- Date found: 2026-06-26
- Confidence note: High confidence; very close feature fit, but Thomas should review local security assumptions before adopting patterns.

### 2026-06-26 - Agentic Contract policy DSL

- Repo URL: https://github.com/agentralabs/agentic-contract
- Repo name: agentralabs/agentic-contract
- Feature or ability Thomas should consider: Policy engine for AI agents with enforceable rules, risk limits, approval gates, obligation tracking, violation detection, and an MCP server.
- Why it matters for Thomas: Thomas already has scoped commit gates and claims. A contract DSL could express risk limits and approval obligations consistently across workers and tools.
- Integration surface guess: Policy-as-code layer, workboard claim constraints, tool approval gates, commit/push safety checks, and violation audit logs.
- Evidence/source URL: https://github.com/agentralabs/agentic-contract
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong policy fit, but DSL maturity and interoperability need review.

### 2026-06-26 - Task Orchestrator MCP quality gates

- Repo URL: https://github.com/jpicklyk/task-orchestrator
- Repo name: jpicklyk/task-orchestrator
- Feature or ability Thomas should consider: MCP server that enforces persistent work items, dependency graphs, quality gates, actor attribution, and required schemas for agent outputs.
- Why it matters for Thomas: Thomas workboard claims and commit helpers already act as gates. A server-enforced schema and quality-gate model could make those rules consistent for all agents.
- Integration surface guess: Workboard MCP endpoint, deliverable schema validation, claim dependency graph, quality gates, and actor attribution logs.
- Evidence/source URL: https://github.com/jpicklyk/task-orchestrator
- Date found: 2026-06-26
- Confidence note: High confidence; excellent conceptual fit for Thomas's workboard discipline and multi-agent accountability.

### 2026-06-26 - EvoAgentX self-evolving agent workflows

- Repo URL: https://github.com/EvoAgentX/EvoAgentX
- Repo name: EvoAgentX/EvoAgentX
- Feature or ability Thomas should consider: Framework for building, evaluating, and evolving agentic workflows with automatic workflow construction, evaluators, memory, tools, and HITL checkpoints.
- Why it matters for Thomas: Thomas needs a disciplined way to improve worker workflows over time without turning every improvement into manual prompt surgery. EvoAgentX is a concrete reference for workflow evolution loops.
- Integration surface guess: Worker workflow generation, eval-backed improvement loops, tool library design, HITL checkpoints, and memory-backed run improvement.
- Evidence/source URL: https://github.com/EvoAgentX/EvoAgentX
- Date found: 2026-06-26
- Confidence note: High confidence; active, substantial project with direct self-improvement and evaluation features.

### 2026-06-26 - AgentBench dynamic reasoning infrastructure benchmark

- Repo URL: https://github.com/VIA-Research/AgentBench
- Repo name: VIA-Research/AgentBench
- Feature or ability Thomas should consider: Agent implementations and benchmark harnesses for studying dynamic reasoning and test-time scaling from an infrastructure perspective.
- Why it matters for Thomas: Thomas needs to know when deeper planning or more agent steps actually help versus burning compute. AgentBench can inform cost-aware worker policies.
- Integration surface guess: Evaluation harness, run-cost telemetry, planning-depth policy, and benchmark-driven worker configuration.
- Evidence/source URL: https://github.com/VIA-Research/AgentBench
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful benchmark framing, with implementation applicability needing ranker review.

### 2026-06-26 - AI agent benchmark compendium

- Repo URL: https://github.com/philschmid/ai-agent-benchmark-compendium
- Repo name: philschmid/ai-agent-benchmark-compendium
- Feature or ability Thomas should consider: Curated compendium of 50+ agent benchmarks across tool use, reasoning, coding/software engineering, and computer interaction.
- Why it matters for Thomas: The ranking thread needs benchmark coverage criteria. This compendium can help map Thomas feature ideas to evidence categories instead of anecdotal appeal.
- Integration surface guess: Research taxonomy, ranking criteria, benchmark selection for worker features, and gap analysis for Thomas evals.
- Evidence/source URL: https://github.com/philschmid/ai-agent-benchmark-compendium
- Date found: 2026-06-26
- Confidence note: High confidence as a research map; not an implementation dependency.

### 2026-06-26 - MASLab multi-agent system comparison codebase

- Repo URL: https://github.com/MASWorks/MASLab
- Repo name: MASWorks/MASLab
- Feature or ability Thomas should consider: Unified codebase for comparing 20+ LLM-based multi-agent system methods with shared preprocessing and evaluation protocols.
- Why it matters for Thomas: Thomas is accumulating many multi-agent ideas. MASLab can help compare patterns like debate, agentverse-style collaboration, and parallel inference under a common evaluation shape.
- Integration surface guess: Multi-agent workflow experiments, comparative eval harnesses, agent-role taxonomy, and regression fixtures for orchestration changes.
- Evidence/source URL: https://github.com/MASWorks/MASLab
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong comparison structure, but young repo and research-code maturity need review.

### 2026-06-26 - MARTI multi-agent reinforced training

- Repo URL: https://github.com/TsinghuaC3I/MARTI
- Repo name: TsinghuaC3I/MARTI
- Feature or ability Thomas should consider: Framework for LLM-based multi-agent reinforced training and inference, including graph workflows, async tool use, reward allocation, and multi-agent tree search for code generation.
- Why it matters for Thomas: Thomas may not train models directly, but MARTI's reward allocation, tree-search exploration, and async workflow ideas are relevant for evaluating and improving worker strategies.
- Integration surface guess: Long-horizon worker policy research, reward/eval model design, branch exploration for code tasks, and strategy comparison.
- Evidence/source URL: https://github.com/TsinghuaC3I/MARTI
- Date found: 2026-06-26
- Confidence note: Medium confidence; technically rich but heavyweight and research-oriented.

### 2026-06-26 - Awesome Self-Evolving Agents survey repository

- Repo URL: https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents
- Repo name: EvoAgentX/Awesome-Self-Evolving-Agents
- Feature or ability Thomas should consider: Survey-backed repository cataloging self-evolving agent systems, concepts, datasets, and evaluation directions.
- Why it matters for Thomas: Thomas's automation should improve from experience, but only with clear safety boundaries. This catalog can seed careful self-improvement designs and anti-pattern checks.
- Integration surface guess: Research intake, self-improvement roadmap, eval taxonomy, and ranker source material for evolution features.
- Evidence/source URL: https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong as a research catalog, not a direct implementation.

### 2026-06-26 - General agents benchmark catalog

- Repo URL: https://github.com/supernalintelligence/Awesome-General-Agents-Benchmark
- Repo name: supernalintelligence/Awesome-General-Agents-Benchmark
- Feature or ability Thomas should consider: Curated list of general-agent benchmarks for evaluating broad agent capabilities across tasks and environments.
- Why it matters for Thomas: Thomas needs to avoid optimizing only for coding tasks. A broader benchmark catalog can guide coverage for tool use, planning, memory, and computer interaction.
- Integration surface guess: Benchmark taxonomy, evaluation backlog, ranker scoring rubric, and worker capability coverage map.
- Evidence/source URL: https://github.com/supernalintelligence/Awesome-General-Agents-Benchmark
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog value is high, but individual benchmarks require later filtering.

### 2026-06-26 - Agentic Reliability Framework

- Repo URL: https://github.com/petterjuan/agentic-reliability-framework
- Repo name: petterjuan/agentic-reliability-framework
- Feature or ability Thomas should consider: Reliability intelligence platform for autonomous operations with deterministic safety guarantees and separated decision intelligence versus governed execution.
- Why it matters for Thomas: Thomas's worker autonomy should have reliability contracts around when an agent can decide, when execution must be governed, and how failures are surfaced.
- Integration surface guess: Reliability policy layer, governed-execution boundary, operational risk scoring, and worker failure reporting.
- Evidence/source URL: https://github.com/petterjuan/agentic-reliability-framework
- Date found: 2026-06-26
- Confidence note: Medium confidence; conceptually aligned, but implementation maturity and licensing posture need review.

### 2026-06-26 - Mastra TypeScript agent framework

- Repo URL: https://github.com/mastra-ai/mastra
- Repo name: mastra-ai/mastra
- Feature or ability Thomas should consider: TypeScript framework for AI agents, workflows, memory, integrations, observability, and deployment-oriented agent applications.
- Why it matters for Thomas: Thomas needs native orchestration patterns that can bridge product UI, durable workflows, memory, and agent execution. Mastra is a large active reference for that full-stack agent shape.
- Integration surface guess: Agent runtime architecture, workflow definitions, memory adapters, observability hooks, and portal-facing agent app patterns.
- Evidence/source URL: https://github.com/mastra-ai/mastra
- Date found: 2026-06-26
- Confidence note: High confidence; large active project with direct agent/workflow relevance.

### 2026-06-26 - VoltAgent TypeScript agent engineering platform

- Repo URL: https://github.com/VoltAgent/voltagent
- Repo name: VoltAgent/voltagent
- Feature or ability Thomas should consider: Open-source TypeScript AI agent framework and engineering platform with orchestration, observability, and developer-facing agent runtime patterns.
- Why it matters for Thomas: Thomas is moving toward native visible worker orchestration. VoltAgent can inform how an agent engineering platform exposes agents, tools, workflows, and runtime traces to developers.
- Integration surface guess: Worker runtime SDK, portal observability, agent registry, tool integration patterns, and developer-facing orchestration APIs.
- Evidence/source URL: https://github.com/VoltAgent/voltagent
- Date found: 2026-06-26
- Confidence note: High confidence; active and directly aligned with agent-platform ergonomics.

### 2026-06-26 - Auth for Agents reference app

- Repo URL: https://github.com/baristaGeek/auth-for-agents
- Repo name: baristaGeek/auth-for-agents
- Feature or ability Thomas should consider: Reference implementation for agent-aware authentication and authorization patterns.
- Why it matters for Thomas: Thomas workers will need delegated access to user resources without leaking credentials or over-scoping tool calls. Auth-for-agents gives a focused pattern source for that boundary.
- Integration surface guess: Agent identity model, delegated authorization, tool risk classification, per-action auth checks, and portal approval UX.
- Evidence/source URL: https://github.com/baristaGeek/auth-for-agents
- Date found: 2026-06-26
- Confidence note: Medium confidence; narrower repo, useful for design comparison rather than direct dependency.

### 2026-06-26 - Arcade MCP authorized tool calling

- Repo URL: https://github.com/ArcadeAI/arcade-mcp
- Repo name: ArcadeAI/arcade-mcp
- Feature or ability Thomas should consider: Python MCP server framework with authorized tool calling, OAuth scopes, token refresh, secret injection, MCP spec coverage, and tool-call evals.
- Why it matters for Thomas: Tool authorization is becoming a core Thomas concern. Arcade's pattern keeps tokens out of the LLM/client while still enabling rich external actions.
- Integration surface guess: MCP tool server framework, OAuth provider adapters, per-call scoped credentials, secret storage, and tool-call evaluation.
- Evidence/source URL: https://github.com/ArcadeAI/arcade-mcp
- Date found: 2026-06-26
- Confidence note: High confidence; very strong fit for safe tool execution and agent integrations.

### 2026-06-26 - Composio agent tool platform

- Repo URL: https://github.com/ComposioHQ/composio
- Repo name: ComposioHQ/composio
- Feature or ability Thomas should consider: Agent tool platform with large toolkit catalog, tool search, context management, authentication, and sandboxed workbench.
- Why it matters for Thomas: Thomas needs a scalable way to expose useful integrations without hand-building every connector. Composio offers a concrete reference for tool discovery, auth, and sandboxed execution.
- Integration surface guess: Tool marketplace, integration registry, auth broker, tool search, and sandboxed action runner.
- Evidence/source URL: https://github.com/ComposioHQ/composio
- Date found: 2026-06-26
- Confidence note: High confidence; mature ecosystem reference, but Thomas should separate reusable patterns from hosted-service assumptions.

### 2026-06-26 - LangWatch evaluations and agent testing

- Repo URL: https://github.com/langwatch/langwatch
- Repo name: langwatch/langwatch
- Feature or ability Thomas should consider: Open-source platform for LLM evaluations and AI agent testing.
- Why it matters for Thomas: As the queue turns into implemented features, Thomas needs regression tests for agent behavior, not just unit tests for code paths.
- Integration surface guess: Agent eval dashboard, run traces, regression datasets, prompt/tool behavior checks, and CI evaluation gates.
- Evidence/source URL: https://github.com/langwatch/langwatch
- Date found: 2026-06-26
- Confidence note: High confidence; directly relevant to Thomas eval and agent testing needs.

### 2026-06-26 - Scenario agentic testing framework

- Repo URL: https://github.com/langwatch/scenario
- Repo name: langwatch/scenario
- Feature or ability Thomas should consider: Agentic testing framework for agentic codebases, focused on testing agents through scenarios rather than only static assertions.
- Why it matters for Thomas: Thomas workers will need behavioral scenario tests for workflows like claim, edit, verify, commit, and recover. Scenario can inform how to model those tests.
- Integration surface guess: Worker scenario tests, CI behavioral gates, runbook regression tests, and simulated user/tool interactions.
- Evidence/source URL: https://github.com/langwatch/scenario
- Date found: 2026-06-26
- Confidence note: High confidence; focused and very relevant for agent behavior regression.

### 2026-06-26 - Inngest AgentKit deterministic multi-agent routing

- Repo URL: https://github.com/inngest/agent-kit
- Repo name: inngest/agent-kit
- Feature or ability Thomas should consider: TypeScript kit for building multi-agent networks with deterministic routing and rich MCP tooling.
- Why it matters for Thomas: Deterministic routing would help Thomas make worker handoffs, tool routing, and multi-agent decisions more inspectable and repeatable.
- Integration surface guess: Native orchestration router, MCP tool integration, workflow graph nodes, worker handoff policy, and deterministic test harnesses.
- Evidence/source URL: https://github.com/inngest/agent-kit
- Date found: 2026-06-26
- Confidence note: High confidence; strong fit for routing and multi-agent runtime design.

### 2026-06-26 - CopilotKit agent-native frontend stack

- Repo URL: https://github.com/CopilotKit/CopilotKit
- Repo name: CopilotKit/CopilotKit
- Feature or ability Thomas should consider: Agent-native frontend stack with generative UI, shared state, human-in-the-loop workflows, AG-UI protocol support, and agent skills for coding assistants.
- Why it matters for Thomas: Thomas is becoming a portal for visible workers. CopilotKit is a strong reference for connecting agent state, user approvals, and UI components without hiding the agent loop.
- Integration surface guess: Thomas portal agent UI, approval widgets, shared worker state, AG-UI/agent protocol bridge, and front-end run controls.
- Evidence/source URL: https://github.com/CopilotKit/CopilotKit
- Date found: 2026-06-26
- Confidence note: High confidence; large active project with direct portal and HITL relevance.

### 2026-06-26 - BMAD Method structured AI development agents

- Repo URL: https://github.com/bmad-code-org/BMAD-METHOD
- Repo name: bmad-code-org/BMAD-METHOD
- Feature or ability Thomas should consider: Structured agile AI development method with specialized agent personas, scale-adaptive workflows, planning depth controls, and multi-persona collaboration.
- Why it matters for Thomas: Thomas needs repeatable workflows that scale from quick fixes to larger implementation arcs. BMAD is a concrete reference for persona roles, planning gates, and structured handoffs.
- Integration surface guess: Worker role templates, task planning depth selection, workboard workflow presets, multi-agent review flows, and portal-guided execution modes.
- Evidence/source URL: https://github.com/bmad-code-org/BMAD-METHOD
- Date found: 2026-06-26
- Confidence note: High confidence; very active and workflow-rich, though Thomas should adopt selectively rather than importing the full method.

### 2026-06-26 - Awesome Devins autonomous software engineer catalog

- Repo URL: https://github.com/e2b-dev/awesome-devins
- Repo name: e2b-dev/awesome-devins
- Feature or ability Thomas should consider: Curated catalog of Devin-inspired autonomous software-engineering agents.
- Why it matters for Thomas: This gives the ranker a discovery map for autonomous coding-agent design choices, sandbox patterns, and task execution loops beyond the already-added OpenHands/SWE-agent set.
- Integration surface guess: Research intake, ranking taxonomy, coding-agent comparison matrix, sandbox pattern discovery, and future targeted repo searches.
- Evidence/source URL: https://github.com/e2b-dev/awesome-devins
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog quality varies, but it is useful for discovery and gap analysis.

### 2026-06-26 - Devika open-source agentic software engineer

- Repo URL: https://github.com/stitionai/devika
- Repo name: stitionai/devika
- Feature or ability Thomas should consider: Open-source agentic software engineer that decomposes high-level objectives into research, planning, code generation, and browser-assisted execution.
- Why it matters for Thomas: Devika is an early concrete implementation of Devin-like autonomous development. Thomas can mine it for task decomposition, browsing, and generated-code workflow pitfalls.
- Integration surface guess: Research-to-plan pipeline, coding worker architecture, browser/tool loop references, and autonomous-dev UX comparisons.
- Evidence/source URL: https://github.com/stitionai/devika
- Date found: 2026-06-26
- Confidence note: Medium confidence; historically influential, but current maintenance and robustness need review.

### 2026-06-26 - AWS CLI Agent Orchestrator

- Repo URL: https://github.com/awslabs/cli-agent-orchestrator
- Repo name: awslabs/cli-agent-orchestrator
- Feature or ability Thomas should consider: CLI orchestrator for coordinating multiple coding agents across tasks, worktrees, execution, and review loops.
- Why it matters for Thomas: Thomas needs native worker spawning and coordination while preserving local repo discipline. This AWS Labs reference can inform CLI ergonomics and orchestration boundaries.
- Integration surface guess: Thomas worker CLI, worktree/task dispatcher, review handoff flow, and local orchestration scripts.
- Evidence/source URL: https://github.com/awslabs/cli-agent-orchestrator
- Date found: 2026-06-26
- Confidence note: High confidence; reputable source and directly aligned with multi-agent CLI orchestration.

### 2026-06-26 - Claude Code subagents collection

- Repo URL: https://github.com/wshobson/agents
- Repo name: wshobson/agents
- Feature or ability Thomas should consider: Collection of specialized Claude Code subagents with explicit domains, prompts, and delegation patterns.
- Why it matters for Thomas: Thomas worker roles need crisp scopes and handoff semantics. This collection is a practical reference for role granularity and reusable subagent prompts.
- Integration surface guess: Worker role registry, prompt/skill catalog, task-to-agent routing, and review-specialist templates.
- Evidence/source URL: https://github.com/wshobson/agents
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical role catalog, though prompts should be audited before reuse.

### 2026-06-26 - Gas Town Claude Code orchestration

- Repo URL: https://github.com/gastownhall/gastown
- Repo name: gastownhall/gastown
- Feature or ability Thomas should consider: Claude Code multi-agent orchestration patterns for coordinating task-focused agent roles.
- Why it matters for Thomas: Thomas is already coordinating separate agent roles and needs examples of how lightweight local orchestration tools model team behavior.
- Integration surface guess: Worker team presets, local orchestration conventions, task decomposition, and role-specific handoffs.
- Evidence/source URL: https://github.com/gastownhall/gastown
- Date found: 2026-06-26
- Confidence note: Medium confidence; likely useful as a pattern reference, but maturity and maintenance need deeper review.

### 2026-06-26 - Multiclaude parallel agent runner

- Repo URL: https://github.com/dlorenc/multiclaude
- Repo name: dlorenc/multiclaude
- Feature or ability Thomas should consider: Lightweight runner for launching and comparing multiple Claude Code agents or attempts in parallel.
- Why it matters for Thomas: Parallel attempts plus structured comparison can improve coding-task reliability when scoped carefully. Thomas could use similar patterns for branch/attempt exploration.
- Integration surface guess: Worker attempt fan-out, branch comparison, review queue, cost tracking, and merge candidate selection.
- Evidence/source URL: https://github.com/dlorenc/multiclaude
- Date found: 2026-06-26
- Confidence note: Medium confidence; small but directly relevant to parallel-agent experimentation.

### 2026-06-26 - Mem0 universal agent memory layer

- Repo URL: https://github.com/mem0ai/mem0
- Repo name: mem0ai/mem0
- Feature or ability Thomas should consider: Universal memory layer for AI agents with user/session/agent memories, entity linking, hybrid retrieval, temporal reasoning, and open evaluation assets.
- Why it matters for Thomas: Thomas needs durable memory that survives worker threads while avoiding giant transcript stuffing. Mem0 is a strong reference for memory extraction, retrieval, and evaluation.
- Integration surface guess: Thomas memory backend, worker context bootstrap, user/project preference memory, memory evals, and agent-generated fact capture.
- Evidence/source URL: https://github.com/mem0ai/mem0
- Date found: 2026-06-26
- Confidence note: High confidence; large active repo with direct memory-layer fit and published benchmark framing.

### 2026-06-26 - Graphiti temporal knowledge graph memory

- Repo URL: https://github.com/getzep/graphiti
- Repo name: getzep/graphiti
- Feature or ability Thomas should consider: Real-time temporal knowledge graph infrastructure for AI agents, designed to represent changing facts, relationships, and historical context.
- Why it matters for Thomas: Thomas needs to remember evolving project state, worker decisions, claims, releases, and user preferences without treating old facts as always current.
- Integration surface guess: Project knowledge graph, workboard memory, time-aware retrieval, provenance-linked facts, and conflict-aware memory lookup.
- Evidence/source URL: https://github.com/getzep/graphiti
- Date found: 2026-06-26
- Confidence note: High confidence; strong temporal-memory fit for long-lived agentic systems.

### 2026-06-26 - MemOS self-evolving memory operating system

- Repo URL: https://github.com/MemTensor/MemOS
- Repo name: MemTensor/MemOS
- Feature or ability Thomas should consider: Self-evolving memory OS for LLMs and AI agents with persistent memory, hybrid retrieval, cross-task skill reuse, and token-saving claims.
- Why it matters for Thomas: Thomas will accumulate repeated worker patterns and project facts. MemOS can inform how to separate memories, skills, and cross-task reusable context.
- Integration surface guess: Memory operating layer, worker skill reuse, long-running project context, hybrid retrieval, and context-budget control.
- Evidence/source URL: https://github.com/MemTensor/MemOS
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; ambitious and relevant, but architecture and maturity need deeper review.

### 2026-06-26 - Memori agent-native memory infrastructure

- Repo URL: https://github.com/memorilabs/memori
- Repo name: MemoriLabs/Memori
- Feature or ability Thomas should consider: LLM-agnostic memory infrastructure that turns agent execution and conversations into structured persistent state for production systems.
- Why it matters for Thomas: Thomas needs memory that captures actual worker execution, not just chat snippets. Memori is a concrete reference for production-oriented agent state persistence.
- Integration surface guess: Worker run memory, structured conversation extraction, persistent state store, and production memory APIs.
- Evidence/source URL: https://github.com/memorilabs/memori
- Date found: 2026-06-26
- Confidence note: High confidence; directly aligned with production agent memory, though Thomas should compare its model against Mem0 and Graphiti.

### 2026-06-26 - Agent Memory Techniques cookbook

- Repo URL: https://github.com/NirDiamant/Agent_Memory_Techniques
- Repo name: NirDiamant/Agent_Memory_Techniques
- Feature or ability Thomas should consider: Practical cookbook of agent memory techniques, including short-term, long-term, retrieval, summarization, and implementation examples.
- Why it matters for Thomas: Before selecting one memory system, Thomas needs implementation-level comparisons for what to store, when to summarize, and how to retrieve memory safely.
- Integration surface guess: Memory design prototypes, worker context experiments, ranker comparison criteria, and test fixtures for memory behavior.
- Evidence/source URL: https://github.com/NirDiamant/Agent_Memory_Techniques
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful implementation cookbook, not necessarily a production dependency.

### 2026-06-26 - Awesome Memory for Agents catalog

- Repo URL: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- Repo name: TsinghuaC3I/Awesome-Memory-for-Agents
- Feature or ability Thomas should consider: Research catalog of memory mechanisms, datasets, benchmarks, and systems for LLM agents.
- Why it matters for Thomas: Memory is central enough that Thomas should track benchmark-backed options rather than relying on one library. This catalog can seed ranking and future targeted runs.
- Integration surface guess: Research taxonomy, memory benchmark selection, ranker inputs, and memory architecture gap analysis.
- Evidence/source URL: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- Date found: 2026-06-26
- Confidence note: Medium confidence; strong catalog value, with individual sources needing later filtering.

### 2026-06-26 - Awesome Graph Memory

- Repo URL: https://github.com/DEEP-PolyU/Awesome-GraphMemory
- Repo name: DEEP-PolyU/Awesome-GraphMemory
- Feature or ability Thomas should consider: Curated graph-memory resources for LLMs and agents, including graph-based reasoning and retrieval systems.
- Why it matters for Thomas: Graph memory may be better than flat vector recall for project state, dependencies, ownership, and worker decisions. This catalog helps evaluate that direction.
- Integration surface guess: Graph-memory research intake, project dependency memory, workboard relationship modeling, and retrieval architecture comparisons.
- Evidence/source URL: https://github.com/DEEP-PolyU/Awesome-GraphMemory
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog source, useful for ranking but not implementation by itself.

### 2026-06-26 - Awesome AI Memory

- Repo URL: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- Repo name: IAAR-Shanghai/Awesome-AI-Memory
- Feature or ability Thomas should consider: Broad AI memory resource collection covering memory architectures, evaluation, and agent memory systems.
- Why it matters for Thomas: Thomas needs durable memory choices that can be justified by evidence. This catalog broadens the source pool for memory evaluation and long-horizon agent design.
- Integration surface guess: Research intake, memory-system shortlist, benchmark mapping, and ranker evidence sources.
- Evidence/source URL: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- Date found: 2026-06-26
- Confidence note: Medium confidence; broad catalog, best used for discovery and benchmark mapping.

### 2026-06-26 - Agent Sandbox Taxonomy

- Repo URL: https://github.com/kajogo777/the-agent-sandbox-taxonomy
- Repo name: kajogo777/the-agent-sandbox-taxonomy
- Feature or ability Thomas should consider: Open taxonomy and scoring framework for evaluating AI agent sandboxes across defense layers, threat categories, and scoring dimensions.
- Why it matters for Thomas: Thomas is adding tool-risk and worker execution boundaries. A sandbox taxonomy can make sandbox choices comparable instead of relying on vague "isolated enough" claims.
- Integration surface guess: Tool-risk policy, sandbox selection rubric, worker execution profiles, marketplace security checks, and ranker safety criteria.
- Evidence/source URL: https://github.com/kajogo777/the-agent-sandbox-taxonomy
- Date found: 2026-06-26
- Confidence note: High confidence; directly relevant safety framework with concrete scoring vocabulary.

### 2026-06-26 - Awesome Agent Security

- Repo URL: https://github.com/ucsb-mlsec/Awesome-Agent-Security
- Repo name: ucsb-mlsec/Awesome-Agent-Security
- Feature or ability Thomas should consider: Curated security and safety threat catalog for LLM-enabled agents.
- Why it matters for Thomas: Thomas needs a durable threat vocabulary for prompt injection, tool misuse, unsafe autonomy, data leakage, and worker-to-worker trust boundaries.
- Integration surface guess: Security research queue, tool-risk taxonomy, threat-model checklist, ranker criteria, and red-team test sourcing.
- Evidence/source URL: https://github.com/ucsb-mlsec/Awesome-Agent-Security
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; catalog source, useful for threat coverage and future targeted checks.

### 2026-06-26 - Awesome AI Agents Security

- Repo URL: https://github.com/ProjectRecon/awesome-ai-agents-security
- Repo name: ProjectRecon/awesome-ai-agents-security
- Feature or ability Thomas should consider: Security-lifecycle catalog for autonomous AI agents covering red teaming, runtime protection, sandboxing, and governance.
- Why it matters for Thomas: Thomas needs security controls across the whole agent lifecycle, not just a commit gate. This catalog can map missing protections by phase.
- Integration surface guess: Agent security lifecycle checklist, governance backlog, runtime-protection source discovery, and red-team candidate sourcing.
- Evidence/source URL: https://github.com/ProjectRecon/awesome-ai-agents-security
- Date found: 2026-06-26
- Confidence note: Medium confidence; broad catalog, best used as a discovery index for ranker follow-up.

### 2026-06-26 - AgentEvals trajectory evaluators

- Repo URL: https://github.com/langchain-ai/agentevals
- Repo name: langchain-ai/agentevals
- Feature or ability Thomas should consider: Ready-made evaluators and utilities focused on agent trajectories and intermediate execution steps.
- Why it matters for Thomas: Worker correctness is often about the path taken, not just final output. Thomas can use trajectory eval ideas to catch bad tool choices, wasted loops, and unsafe shortcuts.
- Integration surface guess: Worker trajectory evaluator, CI agent-behavior gates, trace-to-eval conversion, and ranker scoring criteria.
- Evidence/source URL: https://github.com/langchain-ai/agentevals
- Date found: 2026-06-26
- Confidence note: High confidence; direct fit for evaluating Thomas worker runs and tool-call paths.

### 2026-06-26 - EvalView behavior regression gate

- Repo URL: https://github.com/hidai25/eval-view
- Repo name: hidai25/eval-view
- Feature or ability Thomas should consider: Behavior regression gate for AI agents that tracks drift across outputs, tools, model IDs, and runtime fingerprints.
- Why it matters for Thomas: Thomas needs to distinguish real regressions from provider/model drift as worker behavior changes over time.
- Integration surface guess: Agent regression CI, drift classifier, run fingerprint capture, retry/review gate, and replayable eval artifacts.
- Evidence/source URL: https://github.com/hidai25/eval-view
- Date found: 2026-06-26
- Confidence note: High confidence; very relevant to ongoing worker behavior regression control.

### 2026-06-26 - ReplayD deterministic agent replay

- Repo URL: https://github.com/TaimoorKhan10/replayd
- Repo name: TaimoorKhan10/replayd
- Feature or ability Thomas should consider: Replay-oriented infrastructure for deterministic evaluation and regression testing of agent behavior.
- Why it matters for Thomas: Thomas needs replayable evidence when a worker makes a bad tool call or a future change alters a run path.
- Integration surface guess: Run replay store, deterministic fixture generation, regression replay CLI, and workboard incident reproduction.
- Evidence/source URL: https://github.com/TaimoorKhan10/replayd
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising concept, but implementation maturity needs ranker review.

### 2026-06-26 - LangChain Agent Evals scripts

- Repo URL: https://github.com/langchain-ai/agent-evals
- Repo name: langchain-ai/agent-evals
- Feature or ability Thomas should consider: Collection of evaluation scripts for benchmarking agents across specific tasks.
- Why it matters for Thomas: Thomas needs concrete task-level eval scripts to keep worker changes measurable and reproducible.
- Integration surface guess: Evaluation script library, CI benchmark tasks, ranking evidence, and worker capability regression checks.
- Evidence/source URL: https://github.com/langchain-ai/agent-evals
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful eval script source, complementary to trajectory-focused AgentEvals.

### 2026-06-26 - Deep Agents harness

- Repo URL: https://github.com/langchain-ai/deepagents
- Repo name: langchain-ai/deepagents
- Feature or ability Thomas should consider: Batteries-included agent harness with opinionated defaults and extension points.
- Why it matters for Thomas: Thomas can compare its native worker runtime against an opinionated harness to clarify what should be built in versus configurable.
- Integration surface guess: Agent harness architecture, default worker loop design, extension points, prompt/tool runtime conventions, and prototype comparison.
- Evidence/source URL: https://github.com/langchain-ai/deepagents
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong reference harness, though Thomas should avoid overfitting to one framework.

### 2026-06-26 - Restate durable AI examples

- Repo URL: https://github.com/restatedev/ai-examples
- Repo name: restatedev/ai-examples
- Feature or ability Thomas should consider: Runnable examples of durable AI workflows and agents using Restate, including agent, MCP, A2A, and orchestration patterns.
- Why it matters for Thomas: Thomas workers need crash recovery, resumable tool calls, and durable orchestration without turning every worker into a bespoke state machine.
- Integration surface guess: Worker durable-execution runtime, MCP/A2A workflow examples, restart-safe task orchestration, and run recovery prototypes.
- Evidence/source URL: https://github.com/restatedev/ai-examples
- Date found: 2026-06-26
- Confidence note: High confidence; direct durable-agent examples from an active durable execution project.

### 2026-06-26 - DBOS Durable OpenAI Agents

- Repo URL: https://github.com/dbos-inc/dbos-openai-agents
- Repo name: dbos-inc/dbos-openai-agents
- Feature or ability Thomas should consider: Durable execution integration for the OpenAI Agents SDK, adding reliable and scalable multi-agent application execution.
- Why it matters for Thomas: Thomas uses agent runs that can be interrupted by process restarts, context compaction, or transient failures. DBOS shows how to persist agent/tool steps as durable workflow state.
- Integration surface guess: OpenAI-agent runtime wrapper, durable task journal, tool-call step persistence, restart/resume mechanics, and Postgres-backed worker execution.
- Evidence/source URL: https://github.com/dbos-inc/dbos-openai-agents
- Date found: 2026-06-26
- Confidence note: High confidence; production-oriented successor to Durable Swarm with direct relevance to resilient agent runs.

### 2026-06-26 - Azure Durable Agents samples

- Repo URL: https://github.com/Azure-Samples/durable-task-extension-for-agent-framework
- Repo name: Azure-Samples/durable-task-extension-for-agent-framework
- Feature or ability Thomas should consider: Quickstarts and samples for building durable AI agents using Durable Task with Microsoft Agent Framework.
- Why it matters for Thomas: This is a concrete reference for persistent sessions, durable orchestration, and distributed scaling around agent workflows.
- Integration surface guess: Durable worker lifecycle model, persistent session API, distributed worker orchestration, and long-running task UI patterns.
- Evidence/source URL: https://github.com/Azure-Samples/durable-task-extension-for-agent-framework
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; official sample source with strong durability concepts, though tied to Azure/Microsoft stack.

### 2026-06-26 - Temporal AI Agent workflow demo

- Repo URL: https://github.com/temporal-community/temporal-ai-agent
- Repo name: temporal-community/temporal-ai-agent
- Feature or ability Thomas should consider: Multi-turn AI agent running inside a Temporal workflow with native tools and MCP tools.
- Why it matters for Thomas: Temporal is a mature durable execution model. This demo shows how agent conversations and tools can live inside resumable workflows.
- Integration surface guess: Worker workflow engine comparison, MCP tool persistence, conversation state recovery, and deterministic workflow boundaries.
- Evidence/source URL: https://github.com/temporal-community/temporal-ai-agent
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful durable-agent reference, with demo scope rather than full product scope.

### 2026-06-26 - OpenSRE AI SRE framework

- Repo URL: https://github.com/Tracer-Cloud/opensre
- Repo name: Tracer-Cloud/opensre
- Feature or ability Thomas should consider: Open-source framework for AI SRE agents that investigate production incidents using logs, metrics, traces, runbooks, and memory.
- Why it matters for Thomas: Thomas will need operational agents for CI, local app, and production incidents. OpenSRE gives a concrete pattern for evidence gathering and incident-resolution loops.
- Integration surface guess: Incident triage worker, observability ingestion, runbook retrieval, root-cause analysis, remediation proposals, and workboard incident memory.
- Evidence/source URL: https://github.com/Tracer-Cloud/opensre
- Date found: 2026-06-26
- Confidence note: High confidence; active and directly aligned with agentic incident response.

### 2026-06-26 - Kube AI SRE Agent

- Repo URL: https://github.com/aqrpole/kube-ai-sre-agent
- Repo name: aqrpole/kube-ai-sre-agent
- Feature or ability Thomas should consider: Kubernetes AI SRE assistant for explainable incident correlation, root-cause explanations, remediation recommendations, and policy-based safety controls.
- Why it matters for Thomas: Thomas needs operational agents that are auditable and policy-gated rather than opaque self-healing boxes.
- Integration surface guess: Kubernetes/infra incident worker, policy-gated remediation flow, evidence pack generation, and operator approval loop.
- Evidence/source URL: https://github.com/aqrpole/kube-ai-sre-agent
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong operational safety framing, with implementation maturity needing review.

### 2026-06-26 - Kubernetes AI Agent

- Repo URL: https://github.com/carlossg/kubernetes-agent
- Repo name: carlossg/kubernetes-agent
- Feature or ability Thomas should consider: Autonomous Kubernetes debugging/remediation agent powered by Google's ADK and Gemini, including logs/events analysis and PR creation for fixes.
- Why it matters for Thomas: This bridges incident diagnosis to code-change remediation, a workflow Thomas may need for CI and deployed-service recovery.
- Integration surface guess: Infra-debug worker, ADK comparison, incident-to-PR workflow, canary/rollout analysis, and remediation review gate.
- Evidence/source URL: https://github.com/carlossg/kubernetes-agent
- Date found: 2026-06-26
- Confidence note: Medium confidence; concrete end-to-end operational agent, but scope and safety controls need deeper review.

### 2026-06-26 - Awesome SRE Agents catalog

- Repo URL: https://github.com/last9/awesome-sre-agents
- Repo name: last9/awesome-sre-agents
- Feature or ability Thomas should consider: Curated list of AI-powered DevOps and SRE agents, tools, and resources for reliability automation.
- Why it matters for Thomas: Operational-agent discovery is broad and fast-moving. This catalog can feed ranker coverage for incident response, observability, and remediation agents.
- Integration surface guess: Research intake, SRE-agent taxonomy, operational benchmark sourcing, and future targeted searches for Thomas incident workflows.
- Evidence/source URL: https://github.com/last9/awesome-sre-agents
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog source rather than implementation dependency, useful for discovery breadth.

### 2026-06-26 - AG-UI agent-user interaction protocol

- Repo URL: https://github.com/ag-ui-protocol/ag-ui
- Repo name: ag-ui-protocol/ag-ui
- Feature or ability Thomas should consider: Event-based protocol for connecting agent backends to user-facing applications with streaming, shared state, generative UI, frontend tools, and human-in-the-loop collaboration.
- Why it matters for Thomas: Thomas is becoming a visible portal for worker agents. AG-UI gives a concrete protocol for surfacing worker state, approvals, and UI actions without bespoke one-off front-end plumbing.
- Integration surface guess: Thomas portal event stream, worker UI bridge, approval widgets, AG-UI compatible run state, and frontend tool invocation.
- Evidence/source URL: https://github.com/ag-ui-protocol/ag-ui
- Date found: 2026-06-26
- Confidence note: High confidence; large active protocol repo and directly relevant to Thomas portal UX.

### 2026-06-26 - A2A agent-to-agent protocol

- Repo URL: https://github.com/a2aproject/A2A
- Repo name: a2aproject/A2A
- Feature or ability Thomas should consider: Open Agent2Agent protocol for communication and interoperability between opaque agentic applications.
- Why it matters for Thomas: Thomas will coordinate heterogeneous workers, tools, and possibly external agents. A2A can inform capability discovery, task submission, status reporting, and cross-agent contracts.
- Integration surface guess: Worker-to-worker protocol adapter, external-agent bridge, task/status schema, and cross-agent capability registry.
- Evidence/source URL: https://github.com/a2aproject/A2A
- Date found: 2026-06-26
- Confidence note: High confidence; canonical protocol source, but Thomas should compare against ACP/MCP boundaries before implementation.

### 2026-06-26 - A2A Python SDK

- Repo URL: https://github.com/a2aproject/a2a-python
- Repo name: a2aproject/a2a-python
- Feature or ability Thomas should consider: Official Python SDK for running agentic applications as A2A servers, with async operation, FastAPI/Starlette support, gRPC, OpenTelemetry, and database backends.
- Why it matters for Thomas: Thomas is Python-heavy, so this SDK is the practical path for experimenting with A2A-compatible worker endpoints.
- Integration surface guess: Python worker A2A server, FastAPI/aiohttp adapter comparison, tracing hooks, persisted task backend, and interoperability tests.
- Evidence/source URL: https://github.com/a2aproject/a2a-python
- Date found: 2026-06-26
- Confidence note: High confidence; official SDK with direct Python integration relevance.

### 2026-06-26 - A2A JavaScript SDK

- Repo URL: https://github.com/a2aproject/a2a-js
- Repo name: a2aproject/a2a-js
- Feature or ability Thomas should consider: Official JavaScript/TypeScript SDK for the Agent2Agent protocol.
- Why it matters for Thomas: Thomas portal and frontend-adjacent worker tooling may need JS/TS interop with Python workers and external agents.
- Integration surface guess: Portal-side A2A client, TypeScript worker adapters, cross-language interoperability fixtures, and protocol conformance tests.
- Evidence/source URL: https://github.com/a2aproject/a2a-js
- Date found: 2026-06-26
- Confidence note: High confidence; official SDK, useful for full-stack A2A experiments.

### 2026-06-26 - A2A protocol samples

- Repo URL: https://github.com/a2aproject/a2a-samples
- Repo name: a2aproject/a2a-samples
- Feature or ability Thomas should consider: Sample implementations using the Agent2Agent protocol across frameworks and agent scenarios.
- Why it matters for Thomas: Samples make it easier to compare how A2A maps to real agent tasks, streaming updates, artifacts, and framework-specific worker patterns.
- Integration surface guess: Interop prototypes, sample-based tests, framework comparison, worker capability cards, and A2A task lifecycle experiments.
- Evidence/source URL: https://github.com/a2aproject/a2a-samples
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical examples, though sample maturity varies by framework.

### 2026-06-26 - Agent Network Protocol

- Repo URL: https://github.com/agent-network-protocol/AgentNetworkProtocol
- Repo name: agent-network-protocol/AgentNetworkProtocol
- Feature or ability Thomas should consider: Open protocol for secure and efficient communication among agents in a collaborative network.
- Why it matters for Thomas: Thomas needs to reason about agent identity, discovery, trust, and cross-agent collaboration before exposing external agent connectivity.
- Integration surface guess: Agent identity layer, discovery protocol research, trust model, external-agent network bridge, and protocol comparison.
- Evidence/source URL: https://github.com/agent-network-protocol/AgentNetworkProtocol
- Date found: 2026-06-26
- Confidence note: Medium confidence; conceptually relevant, but Thomas should compare maturity against A2A and ACP.

### 2026-06-26 - Awesome A2A catalog

- Repo URL: https://github.com/pab1it0/awesome-a2a
- Repo name: pab1it0/awesome-a2a
- Feature or ability Thomas should consider: Curated list of A2A agents, tools, servers, clients, and examples.
- Why it matters for Thomas: A2A is a broad ecosystem; this catalog can seed targeted future runs for concrete servers, clients, and interop patterns.
- Integration surface guess: Research intake, A2A ecosystem taxonomy, agent-card examples, server/client discovery, and ranker source material.
- Evidence/source URL: https://github.com/pab1it0/awesome-a2a
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog quality varies, but useful as a discovery map.

### 2026-06-26 - python-a2a library

- Repo URL: https://github.com/themanojdesai/python-a2a
- Repo name: themanojdesai/python-a2a
- Feature or ability Thomas should consider: Python library for implementing Google's Agent-to-Agent protocol with interoperable agent communication patterns.
- Why it matters for Thomas: A non-official Python implementation can reveal simpler API ergonomics or practical shortcuts compared with the official SDK.
- Integration surface guess: A2A API comparison, Python interop prototype, agent collaboration examples, and protocol ergonomics review.
- Evidence/source URL: https://github.com/themanojdesai/python-a2a
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful comparison source, but official SDK should remain the primary reference.

### 2026-06-26 - Symbol Delta Ledger MCP

- Repo URL: https://github.com/GlitterKill/sdl-mcp
- Repo name: GlitterKill/sdl-mcp
- Feature or ability Thomas should consider: Policy-centered context-budget layer for coding agents using symbol-graph intelligence, precision tools, validation hooks, and MCP access.
- Why it matters for Thomas: Thomas workers spend a lot of budget discovering code context. SDL-MCP is a concrete reference for serving compact symbol cards and escalating context only when needed.
- Integration surface guess: Repo intelligence MCP, context-budget policy, symbol-card cache, validation hooks, and worker code-navigation tools.
- Evidence/source URL: https://github.com/GlitterKill/sdl-mcp
- Date found: 2026-06-26
- Confidence note: High confidence; direct fit for code-context efficiency and MCP-based agent tooling.

### 2026-06-26 - Axon code knowledge graph

- Repo URL: https://github.com/harshkedia177/axon
- Repo name: harshkedia177/axon
- Feature or ability Thomas should consider: Graph-powered code intelligence engine that indexes codebases into a knowledge graph exposed through MCP tools and a CLI.
- Why it matters for Thomas: Thomas needs repo-aware workers that understand relationships between symbols, files, and call paths without reading whole files repeatedly.
- Integration surface guess: Code graph indexer, MCP query tools, workboard context bootstrap, and code-review impact analysis.
- Evidence/source URL: https://github.com/harshkedia177/axon
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; focused MCP/code graph fit, with scale and language coverage needing review.

### 2026-06-26 - CodeGraphContext local graph MCP

- Repo URL: https://github.com/CodeGraphContext/CodeGraphContext
- Repo name: CodeGraphContext/CodeGraphContext
- Feature or ability Thomas should consider: MCP server and CLI that indexes local code into a graph database to provide structured context to AI assistants.
- Why it matters for Thomas: Thomas can compare graph-backed context delivery options before standardizing on one code-intelligence layer.
- Integration surface guess: Local code graph service, MCP context tools, repo research context pack, and worker preflight indexing.
- Evidence/source URL: https://github.com/CodeGraphContext/CodeGraphContext
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; direct context-engineering fit, implementation maturity should be checked.

### 2026-06-26 - OpenViking context database

- Repo URL: https://github.com/volcengine/OpenViking
- Repo name: volcengine/OpenViking
- Feature or ability Thomas should consider: Open-source context database for AI agents that manages memory, resources, and skills through a file-system-like paradigm with hierarchical context delivery.
- Why it matters for Thomas: Thomas needs to unify project memory, repo resources, skills, and worker context without scattering context across unrelated files and prompts.
- Integration surface guess: Thomas context database, worker context filesystem, skill/resource registry, hierarchical context delivery, and self-evolving context store.
- Evidence/source URL: https://github.com/volcengine/OpenViking
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; conceptually strong, but stack fit and operational complexity need review.

### 2026-06-26 - CodeGraph local semantic code intelligence

- Repo URL: https://github.com/colbymchenry/codegraph
- Repo name: colbymchenry/codegraph
- Feature or ability Thomas should consider: Local semantic code intelligence and pre-indexed knowledge graph for Claude Code, Codex, Cursor, Gemini, OpenCode, and other agents.
- Why it matters for Thomas: CodeGraph is directly aimed at reducing token use and tool calls for coding agents, which maps to Thomas worker cost and reliability concerns.
- Integration surface guess: Local code intelligence CLI, Codex/Claude worker setup, persistent repo graph, test-impact analysis, and context reduction metrics.
- Evidence/source URL: https://github.com/colbymchenry/codegraph
- Date found: 2026-06-26
- Confidence note: High confidence; high-signal fit for local agent code intelligence, though licensing and claims should be reviewed.

### 2026-06-26 - Sourcebot codebase intelligence

- Repo URL: https://github.com/sourcebot-dev/sourcebot
- Repo name: sourcebot-dev/sourcebot
- Feature or ability Thomas should consider: Self-hosted code search and codebase understanding platform for humans and agents.
- Why it matters for Thomas: Thomas needs shared code intelligence that both agents and the user can inspect, not hidden per-thread search state.
- Integration surface guess: Shared code search service, portal code navigation, agent context retrieval, repo-wide symbol search, and evidence links in worker reports.
- Evidence/source URL: https://github.com/sourcebot-dev/sourcebot
- Date found: 2026-06-26
- Confidence note: High confidence; mature shared-code-search direction with human and agent value.

### 2026-06-26 - CodeRAG local semantic code search

- Repo URL: https://github.com/Neverdecel/CodeRAG
- Repo name: Neverdecel/CodeRAG
- Feature or ability Thomas should consider: Local-first semantic code search using hybrid vector plus keyword retrieval with symbol-aware chunking, exposed as CLI, Python library, REST API, and web UI.
- Why it matters for Thomas: Thomas needs retrieval that works on custom/local codebases without depending on hosted embeddings or leaking source.
- Integration surface guess: Local RAG service, symbol-aware chunking, Python worker library, REST lookup endpoint, and portal search UI.
- Evidence/source URL: https://github.com/Neverdecel/CodeRAG
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical local-first retrieval pattern, but benchmark quality needs review.

### 2026-06-26 - Code Review Graph

- Repo URL: https://github.com/tirth8205/code-review-graph
- Repo name: tirth8205/code-review-graph
- Feature or ability Thomas should consider: Local-first code intelligence graph for MCP and CLI focused on review workflows, context reduction, and large-repo code understanding.
- Why it matters for Thomas: Thomas reviewers and rankers need concise impact context for code changes, especially when many workers are modifying adjacent files.
- Integration surface guess: Review context graph, MCP review tools, changed-file impact map, context-reduction metrics, and code-review worker support.
- Evidence/source URL: https://github.com/tirth8205/code-review-graph
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; closely aligned with review context, with maturity and benchmark claims needing validation.

### 2026-06-26 - MobileAgent autonomous mobile GUI agent

- Repo URL: https://github.com/X-PLUG/MobileAgent
- Repo name: X-PLUG/MobileAgent
- Feature or ability Thomas should consider: Autonomous multimodal mobile device agent that uses visual perception to operate mobile apps.
- Why it matters for Thomas: Thomas may need mobile/GUI QA and app-control workers. MobileAgent is a concrete reference for visual GUI action loops and mobile task execution.
- Integration surface guess: Mobile QA worker, visual action planner, Android/iOS test agent research, screenshot-to-action pipeline, and GUI-agent benchmark comparison.
- Evidence/source URL: https://github.com/X-PLUG/MobileAgent
- Date found: 2026-06-26
- Confidence note: High confidence; widely referenced mobile-agent project, though production safety and device-control boundaries need review.

### 2026-06-26 - OpenGUI GUI-agent framework

- Repo URL: https://github.com/Core-Mate/OpenGUI
- Repo name: Core-Mate/OpenGUI
- Feature or ability Thomas should consider: GUI-agent framework and resources for open-ended graphical user interface automation.
- Why it matters for Thomas: Thomas’s portal and desktop-facing workflows need GUI automation ideas grounded in actual UI-state/action models.
- Integration surface guess: GUI automation research, desktop/mobile task runners, visual state abstraction, action schema design, and UI benchmark sourcing.
- Evidence/source URL: https://github.com/Core-Mate/OpenGUI
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; relevant GUI-agent resource, implementation maturity needs ranker review.

### 2026-06-26 - Arbigent Android AI testing agent

- Repo URL: https://github.com/takahirom/arbigent
- Repo name: takahirom/arbigent
- Feature or ability Thomas should consider: Android UI test generation and execution agent that uses AI to explore app behavior.
- Why it matters for Thomas: Thomas needs practical QA-agent references, especially for mobile flows where tests often rot or miss visual states.
- Integration surface guess: Mobile test worker, Android UI automation, test-case generation, screenshot evidence capture, and regression test synthesis.
- Evidence/source URL: https://github.com/takahirom/arbigent
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical implementation angle, with Android-specific constraints to evaluate.

### 2026-06-26 - ClawBench mobile GUI-agent benchmark

- Repo URL: https://github.com/TIGER-AI-Lab/ClawBench
- Repo name: TIGER-AI-Lab/ClawBench
- Feature or ability Thomas should consider: Benchmark for evaluating mobile GUI agents on realistic app-control tasks.
- Why it matters for Thomas: If Thomas adopts mobile/GUI workers, it needs benchmark coverage for task success, safety, and interaction quality.
- Integration surface guess: GUI-agent eval suite, mobile task benchmark, worker scoring rubric, and visual action regression checks.
- Evidence/source URL: https://github.com/TIGER-AI-Lab/ClawBench
- Date found: 2026-06-26
- Confidence note: High confidence; strong benchmark value for mobile agent evaluation.

### 2026-06-26 - D2Snap web automation benchmark

- Repo URL: https://github.com/webfuse-com/D2Snap
- Repo name: webfuse-com/D2Snap
- Feature or ability Thomas should consider: Web automation benchmark/data source for evaluating agents on browser tasks and page-state interaction.
- Why it matters for Thomas: Thomas browser workers need reproducible test tasks beyond ad hoc Playwright smoke tests.
- Integration surface guess: Browser-agent benchmark, web task replay, DOM/vision action evaluation, and regression test scenarios.
- Evidence/source URL: https://github.com/webfuse-com/D2Snap
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising benchmark source, but coverage and maintenance need review.

### 2026-06-26 - VisualWebArena visual web-agent benchmark

- Repo URL: https://github.com/web-arena-x/visualwebarena
- Repo name: web-arena-x/visualwebarena
- Feature or ability Thomas should consider: Visual web-agent benchmark for evaluating agents that must use screenshots and web interaction to complete tasks.
- Why it matters for Thomas: Browser automation with screenshots is core to many user-facing workflows. VisualWebArena can help Thomas test visual grounding and web interaction reliability.
- Integration surface guess: Browser-agent eval harness, visual task fixtures, screenshot-action scoring, and portal automation regression.
- Evidence/source URL: https://github.com/web-arena-x/visualwebarena
- Date found: 2026-06-26
- Confidence note: High confidence; established visual web benchmark with direct relevance to browser workers.

### 2026-06-26 - Open Operator Evals

- Repo URL: https://github.com/nottelabs/open-operator-evals
- Repo name: nottelabs/open-operator-evals
- Feature or ability Thomas should consider: Evaluation suite for open operator/browser agents and their web task performance.
- Why it matters for Thomas: Thomas needs comparable browser-agent evaluations to choose between browser-use, Playwright MCP, AG-UI, and custom portal agents.
- Integration surface guess: Browser-agent eval pipeline, task fixtures, benchmark runner, and operator-agent comparison.
- Evidence/source URL: https://github.com/nottelabs/open-operator-evals
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; directly relevant evaluation source, but scope and dependencies need review.

### 2026-06-26 - browser-use benchmark

- Repo URL: https://github.com/browser-use/benchmark
- Repo name: browser-use/benchmark
- Feature or ability Thomas should consider: Benchmark suite from the browser-use ecosystem for measuring browser-agent task execution.
- Why it matters for Thomas: Thomas already tracks browser-use itself; a separate benchmark repo can provide concrete evaluation tasks for browser workers.
- Integration surface guess: Browser-worker benchmark runner, task success scoring, regression fixtures, and browser-agent comparison matrix.
- Evidence/source URL: https://github.com/browser-use/benchmark
- Date found: 2026-06-26
- Confidence note: High confidence; same ecosystem as an existing queue item, but a distinct evaluation surface.

### 2026-06-26 - Adrian runtime agent security monitor

- Repo URL: https://github.com/secureagentics/adrian
- Repo name: secureagentics/adrian
- Feature or ability Thomas should consider: Runtime security monitoring and control for AI agents that analyzes tool calls, actions, outputs, and reasoning traces to detect malicious, misaligned, or out-of-remit behavior.
- Why it matters for Thomas: Thomas workers are gaining more tool authority. Adrian is a concrete reference for in-flight policy checks and runtime intervention before an unsafe action executes.
- Integration surface guess: Tool-call runtime guard, worker remit policy, audit/block modes, trace ingestion, and portal security alerts.
- Evidence/source URL: https://github.com/secureagentics/adrian
- Date found: 2026-06-26
- Confidence note: High confidence; active and directly aligned with runtime control for agent actions.

### 2026-06-26 - Agent Discover Scanner

- Repo URL: https://github.com/Defend-AI-Tech-Inc/agent-discover-scanner
- Repo name: Defend-AI-Tech-Inc/agent-discover-scanner
- Feature or ability Thomas should consider: Agentic identity and inventory scanner that discovers autonomous agents using static analysis, network heuristics, and eBPF.
- Why it matters for Thomas: As Thomas grows native workers, MCP servers, plugins, and external agents, it needs an inventory of what agents exist and what authority they have.
- Integration surface guess: Agent inventory scan, AIBOM-style metadata, workspace agent discovery, runtime network heuristics, and governance reports.
- Evidence/source URL: https://github.com/Defend-AI-Tech-Inc/agent-discover-scanner
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong governance angle, with practical integration cost needing review.

### 2026-06-26 - Deterministic Agent Control Protocol

- Repo URL: https://github.com/elliot35/deterministic-agent-control-protocol
- Repo name: elliot35/deterministic-agent-control-protocol
- Feature or ability Thomas should consider: Governance gateway for AI agents with bounded, auditable, session-aware control through MCP proxy, shell proxy, and HTTP API.
- Why it matters for Thomas: Thomas needs deterministic control around shell and MCP actions. This project is close to Thomas’s commit/workboard gate shape but at runtime action level.
- Integration surface guess: MCP proxy, shell command proxy, session-aware policy, audit log, and deterministic replay/control layer.
- Evidence/source URL: https://github.com/elliot35/deterministic-agent-control-protocol
- Date found: 2026-06-26
- Confidence note: High confidence; direct fit for tool gateway and bounded execution design.

### 2026-06-26 - Panguard AI agent security platform

- Repo URL: https://github.com/panguard-ai/panguard-ai
- Repo name: panguard-ai/panguard-ai
- Feature or ability Thomas should consider: Open-source AI agent security platform for pre-install skill audits, runtime monitoring, and shared threat intelligence.
- Why it matters for Thomas: Thomas has skills/plugins and agent tools that should be audited before activation and monitored after activation.
- Integration surface guess: Skill audit gate, plugin threat scoring, runtime monitor, shared rule feeds, and portal security dashboard.
- Evidence/source URL: https://github.com/panguard-ai/panguard-ai
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; relevant lifecycle coverage, but ecosystem maturity and rule quality need review.

### 2026-06-26 - GoPlus AgentGuard

- Repo URL: https://github.com/GoPlusSecurity/agentguard
- Repo name: GoPlusSecurity/agentguard
- Feature or ability Thomas should consider: Local security guard for AI agents that blocks malicious skills, prevents data leaks, protects secrets, evaluates runtime actions, and maintains a trust registry.
- Why it matters for Thomas: Thomas can use AgentGuard as a reference for local-first protection around skills, secrets, destructive commands, and action attribution.
- Integration surface guess: Local hook layer, skill trust registry, destructive-command guard, secret-protection rules, and tool action attribution.
- Evidence/source URL: https://github.com/GoPlusSecurity/agentguard
- Date found: 2026-06-26
- Confidence note: High confidence; concrete local runtime guard with directly comparable controls.

### 2026-06-26 - Runtime Guard

- Repo URL: https://github.com/runtimeguard/runtime-guard
- Repo name: runtimeguard/runtime-guard
- Feature or ability Thomas should consider: Runtime guard project for AI/agent execution safety.
- Why it matters for Thomas: Runtime guardrails are becoming a first-class requirement for Thomas workers. This repo should be compared against Adrian, AgentGuard, and DACP for enforcement model and ergonomics.
- Integration surface guess: Runtime policy enforcement, execution monitor, guardrail comparison, and tool-call risk adapter.
- Evidence/source URL: https://github.com/runtimeguard/runtime-guard
- Date found: 2026-06-26
- Confidence note: Medium confidence; potentially relevant, but needs deeper maturity review because public metadata is thinner than other candidates.

### 2026-06-26 - Agent Threat Rules

- Repo URL: https://github.com/Agent-Threat-Rule/agent-threat-rules
- Repo name: Agent-Threat-Rule/agent-threat-rules
- Feature or ability Thomas should consider: Open detection-rule standard for AI agents, similar to Sigma, with rule coverage for agent threats and integrations.
- Why it matters for Thomas: Thomas needs portable detection rules for suspicious tool use, prompt injection, data exfiltration, and unsafe agent behavior.
- Integration surface guess: Threat rule engine, tool-call detector, red-team rule pack, runtime guard test corpus, and security audit reports.
- Evidence/source URL: https://github.com/Agent-Threat-Rule/agent-threat-rules
- Date found: 2026-06-26
- Confidence note: High confidence; strong ruleset/reference standard for Thomas security controls.

### 2026-06-26 - Awesome Agent Skills Security

- Repo URL: https://github.com/LLMSecurity/awesome-agent-skills-security
- Repo name: LLMSecurity/awesome-agent-skills-security
- Feature or ability Thomas should consider: Curated resources on agent skills security, including attacks, defenses, frameworks, and benchmarks for securing tool use and skill ecosystems.
- Why it matters for Thomas: Thomas has skills, plugins, MCP tools, and worker instructions that need security review as a supply chain.
- Integration surface guess: Skill supply-chain research, security checklist, benchmark sourcing, ranker criteria, and future targeted scanner searches.
- Evidence/source URL: https://github.com/LLMSecurity/awesome-agent-skills-security
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; catalog source, valuable for coverage and threat-model breadth.

### 2026-06-26 - DSPy declarative self-improving programs

- Repo URL: https://github.com/stanfordnlp/dspy
- Repo name: stanfordnlp/dspy
- Feature or ability Thomas should consider: Declarative programming framework for language-model systems, including self-improving pipelines and agent loops.
- Why it matters for Thomas: Thomas needs to improve worker prompts and workflows with measurable feedback rather than manual prompt tweaking. DSPy provides a mature model for declarative, optimizable LM programs.
- Integration surface guess: Worker prompt/program optimization, eval-backed workflow tuning, reusable task modules, and self-improvement experiments.
- Evidence/source URL: https://github.com/stanfordnlp/dspy
- Date found: 2026-06-26
- Confidence note: High confidence; mature, active, and directly relevant to optimizing agent workflows.

### 2026-06-26 - Dify agentic workflow platform

- Repo URL: https://github.com/langgenius/dify
- Repo name: langgenius/dify
- Feature or ability Thomas should consider: Production-ready platform for developing agentic workflows, applications, tools, and knowledge-connected agents.
- Why it matters for Thomas: Dify is a large reference for visual workflow authoring, deployment, monitoring, knowledge integrations, and agent app operations.
- Integration surface guess: Portal workflow builder, agent app lifecycle, knowledge-tool integrations, workflow observability, and no-code/low-code orchestration comparisons.
- Evidence/source URL: https://github.com/langgenius/dify
- Date found: 2026-06-26
- Confidence note: High confidence; major active platform, but Thomas should borrow patterns rather than adopt wholesale.

### 2026-06-26 - DeerFlow long-horizon SuperAgent harness

- Repo URL: https://github.com/bytedance/deer-flow
- Repo name: bytedance/deer-flow
- Feature or ability Thomas should consider: Long-horizon SuperAgent harness with sandboxes, memories, tools, skills, subagents, and a message gateway for tasks that run minutes to hours.
- Why it matters for Thomas: Thomas needs long-running native worker orchestration with memory, sandboxes, subagents, and user-visible progress. DeerFlow is a concrete end-to-end reference.
- Integration surface guess: Long-horizon worker harness, skill/subagent composition, sandbox integration, message gateway, and task progress model.
- Evidence/source URL: https://github.com/bytedance/deer-flow
- Date found: 2026-06-26
- Confidence note: High confidence; strong feature fit and active implementation.

### 2026-06-26 - Zenflow declarative multi-agent workflow engine

- Repo URL: https://github.com/zendev-sh/zenflow
- Repo name: zendev-sh/zenflow
- Feature or ability Thomas should consider: Declarative YAML multi-agent workflow engine with LLM coordinator, hub-and-spoke mailboxes, race-safe delivery, and MCP tool calls.
- Why it matters for Thomas: Thomas already has workboard messages, workers, and MCP/tool surfaces. Zenflow is a compact reference for race-safe workflow routing and YAML-defined agent processes.
- Integration surface guess: Workboard workflow DSL, mailbox routing, race-safe event delivery, MCP tool orchestration, and replayable workflow specs.
- Evidence/source URL: https://github.com/zendev-sh/zenflow
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; very relevant but explicitly new, so API stability should be watched.

### 2026-06-26 - Reyn constrained workflow OS

- Repo URL: https://github.com/tya5/reyn
- Repo name: tya5/reyn
- Feature or ability Thomas should consider: AI agent workflow OS focused on constrained, validated, replayable execution with predictability over unconstrained autonomy.
- Why it matters for Thomas: Thomas values scoped claims, gates, and reviewable worker behavior. Reyn's predictability-first model maps closely to that operating style.
- Integration surface guess: Worker workflow OS comparison, validation gates, replayable execution records, task constraints, and deterministic handoff model.
- Evidence/source URL: https://github.com/tya5/reyn
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong conceptual fit, with maturity and ecosystem size needing review.

### 2026-06-26 - Swarms YAML workflow format

- Repo URL: https://github.com/The-Swarm-Corporation/swarms.yaml
- Repo name: The-Swarm-Corporation/swarms.yaml
- Feature or ability Thomas should consider: YAML-based multi-agent workflow specification for defining agents, tools, tasks, and orchestration.
- Why it matters for Thomas: Thomas could benefit from human-readable workflow specs for repeatable worker teams without hard-coding every orchestration pattern.
- Integration surface guess: Worker-team YAML spec, workflow import/export, ranker-readable feature templates, and portal workflow editor schema.
- Evidence/source URL: https://github.com/The-Swarm-Corporation/swarms.yaml
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful spec reference, but should be compared with Zenflow and Thomas workboard semantics.

### 2026-06-26 - Weaver multi-agent workflow framework

- Repo URL: https://github.com/sherkevin/Weaver
- Repo name: sherkevin/Weaver
- Feature or ability Thomas should consider: Multi-agent workflow framework for composing and coordinating agent roles.
- Why it matters for Thomas: Thomas needs practical references for how to define agent teams, shared context, and role-specific handoffs beyond one-off worker prompts.
- Integration surface guess: Worker role composition, multi-agent workflow patterns, role handoff schema, and workflow test fixtures.
- Evidence/source URL: https://github.com/sherkevin/Weaver
- Date found: 2026-06-26
- Confidence note: Medium confidence; relevant pattern source, but ranker should inspect maturity and documentation depth.

### 2026-06-26 - L2MAC automatic computer framework

- Repo URL: https://github.com/samholt/l2mac
- Repo name: samholt/L2MAC
- Feature or ability Thomas should consider: LLM Automatic Computer Framework for constructing computer-use agents and action loops.
- Why it matters for Thomas: Thomas is collecting browser, GUI, and computer-use references; L2MAC adds a framework-level view of automatic computer interaction.
- Integration surface guess: Computer-use worker architecture, action loop abstraction, UI-control comparisons, and GUI-agent benchmark wiring.
- Evidence/source URL: https://github.com/samholt/l2mac
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful as a computer-use framework reference, with activity and robustness needing review.

### 2026-06-26 - OpenLLMetry OpenTelemetry LLM observability

- Repo URL: https://github.com/traceloop/openllmetry
- Repo name: traceloop/openllmetry
- Feature or ability Thomas should consider: OpenTelemetry-based observability extensions for LLM applications, including traces for prompts, model calls, vector DBs, and framework integrations.
- Why it matters for Thomas: Thomas worker runs should emit standard telemetry that can flow into existing observability backends instead of being trapped in per-thread logs.
- Integration surface guess: OpenTelemetry instrumentation, worker span schema, tool-call trace export, and observability backend adapters.
- Evidence/source URL: https://github.com/traceloop/openllmetry
- Date found: 2026-06-26
- Confidence note: High confidence; mature OTel-native reference and broad ecosystem support.

### 2026-06-26 - OpenLLMetry JS/TS observability

- Repo URL: https://github.com/traceloop/openllmetry-js
- Repo name: traceloop/openllmetry-js
- Feature or ability Thomas should consider: TypeScript/JavaScript OpenTelemetry instrumentation for LLM applications and agent workflows.
- Why it matters for Thomas: Thomas has portal and TypeScript-adjacent surfaces where JS-side agent/portal interactions should emit compatible telemetry.
- Integration surface guess: Portal telemetry, frontend/Node worker traces, AG-UI/A2A client spans, and cross-language trace correlation.
- Evidence/source URL: https://github.com/traceloop/openllmetry-js
- Date found: 2026-06-26
- Confidence note: High confidence; useful companion to Python OpenLLMetry for full-stack tracing.

### 2026-06-26 - Dynatrace AI agent instrumentation examples

- Repo URL: https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples
- Repo name: dynatrace-oss/dynatrace-ai-agent-instrumentation-examples
- Feature or ability Thomas should consider: Example instrumentation for AI/coding agents using OpenTelemetry-style observability in a production APM ecosystem.
- Why it matters for Thomas: Thomas needs examples of instrumenting coding agents and distributed agent systems with production observability semantics.
- Integration surface guess: Coding-agent trace schema, Dynatrace/OTel adapter comparison, local worker instrumentation examples, and cost/performance dashboards.
- Evidence/source URL: https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical examples from an observability vendor, but vendor assumptions need review.

### 2026-06-26 - Latitude agent monitoring platform

- Repo URL: https://github.com/latitude-dev/latitude-llm
- Repo name: latitude-dev/latitude-llm
- Feature or ability Thomas should consider: Open-source AI agent monitoring platform that groups failed traces into issues, supports human-aligned evals, and captures agent-native multi-turn traces.
- Why it matters for Thomas: Thomas needs to convert worker trace failures into actionable issues, not just accumulate logs.
- Integration surface guess: Failed-run issue grouping, human judgment evals, trace-to-workboard problem records, drift tracking, and portal monitoring.
- Evidence/source URL: https://github.com/latitude-dev/latitude-llm
- Date found: 2026-06-26
- Confidence note: High confidence; very close to Thomas needs around worker failure triage and trace review.

### 2026-06-26 - LMCache agent trace corpus

- Repo URL: https://github.com/LMCache/lmcache-agent-trace
- Repo name: LMCache/lmcache-agent-trace
- Feature or ability Thomas should consider: Repository for collecting and analyzing agent application, benchmark, and workload traces.
- Why it matters for Thomas: Thomas needs real trace corpora to test replay, caching, latency, and context-reuse strategies on agentic workloads.
- Integration surface guess: Agent trace dataset intake, replay benchmark, context-cache evaluation, and worker performance analysis.
- Evidence/source URL: https://github.com/LMCache/lmcache-agent-trace
- Date found: 2026-06-26
- Confidence note: Medium confidence; trace corpus idea is valuable, but current repo depth appears modest.

### 2026-06-26 - LlamaIndex agents observability demo

- Repo URL: https://github.com/run-llama/agents-observability-demo
- Repo name: run-llama/agents-observability-demo
- Feature or ability Thomas should consider: Demo of agent observability and tracing using LlamaIndex, OpenTelemetry, and MCP-served tools.
- Why it matters for Thomas: This is a compact reference for instrumenting agent tool use and MCP interactions with OTel traces.
- Integration surface guess: MCP tool trace prototype, LlamaIndex comparison, worker trace demo, and observability proof-of-concept.
- Evidence/source URL: https://github.com/run-llama/agents-observability-demo
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; demo scope, but directly relevant to Thomas MCP/tool tracing.

### 2026-06-26 - OpenLIT AI engineering observability

- Repo URL: https://github.com/openlit/openlit
- Repo name: openlit/openlit
- Feature or ability Thomas should consider: OpenTelemetry-native AI engineering platform with LLM observability, evaluations, prompt management, guardrails, and local coding-agent tracing hooks.
- Why it matters for Thomas: OpenLIT explicitly targets Claude Code, Cursor, and Codex local coding-agent sessions, matching Thomas’s local worker observability needs.
- Integration surface guess: Local coding-agent trace hooks, OTel collector, evaluation dashboards, prompt/tool metrics, and portal observability.
- Evidence/source URL: https://github.com/openlit/openlit
- Date found: 2026-06-26
- Confidence note: High confidence; strong local-agent tracing fit and broad observability surface.

### 2026-06-26 - traceAI OpenTelemetry tracing framework

- Repo URL: https://github.com/future-agi/traceai
- Repo name: future-agi/traceai
- Feature or ability Thomas should consider: Open-source OpenTelemetry-based tracing framework for LLM calls, prompts, retrieval, and agent decisions.
- Why it matters for Thomas: Thomas needs trace semantics that include agent decisions and retrieval/tool steps, not only model latency.
- Integration surface guess: Trace schema comparison, OTel export, agent-decision spans, retrieval/tool trace capture, and backend-neutral observability.
- Evidence/source URL: https://github.com/future-agi/traceai
- Date found: 2026-06-26
- Confidence note: High confidence; backend-neutral OTel approach with direct agent decision tracing value.

### 2026-06-26 - GenAI OpenTelemetry semantic conventions

- Repo URL: https://github.com/open-telemetry/semantic-conventions-genai
- Repo name: open-telemetry/semantic-conventions-genai
- Feature or ability Thomas should consider: Standard GenAI semantic conventions for OpenTelemetry spans and attributes across model, prompt, tool, and agent operations.
- Why it matters for Thomas: Thomas should align worker traces with emerging standards so observability data can move between local dashboards, hosted APM, and future MCP/agent tooling.
- Integration surface guess: Worker span schema, trace attribute naming, model/tool event taxonomy, OpenTelemetry exporter compatibility, and dashboard query conventions.
- Evidence/source URL: https://github.com/open-telemetry/semantic-conventions-genai
- Date found: 2026-06-26
- Confidence note: High confidence; standards-track reference that can prevent Thomas from inventing isolated telemetry names.

### 2026-06-26 - Cursor agent-trace coding-agent observability

- Repo URL: https://github.com/cursor/agent-trace
- Repo name: cursor/agent-trace
- Feature or ability Thomas should consider: Tooling and conventions for capturing coding-agent traces, including execution context useful for debugging agent edits and decisions.
- Why it matters for Thomas: Thomas needs durable trace evidence for coding-worker decisions so reviewers can inspect why an agent edited, skipped, retried, or failed.
- Integration surface guess: Coding-worker trace capture, review evidence links, timeline replay, per-turn event schema, and local trace artifact storage.
- Evidence/source URL: https://github.com/cursor/agent-trace
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; directly relevant to coding-agent workflow, but repo maturity should be reviewed before adoption.

### 2026-06-26 - TokenTelemetry local token dashboard

- Repo URL: https://github.com/VasiHemanth/tokentelemetry
- Repo name: VasiHemanth/tokentelemetry
- Feature or ability Thomas should consider: Local token telemetry dashboard for tracking token usage across AI coding tools and sessions.
- Why it matters for Thomas: Thomas workers need visible token spend and usage drift by run, thread, model, and task instead of relying on coarse billing totals.
- Integration surface guess: Local worker usage collector, portal budget dashboard, per-agent cost attribution, model/session usage ingestion, and heartbeat budget reporting.
- Evidence/source URL: https://github.com/VasiHemanth/tokentelemetry
- Date found: 2026-06-26
- Confidence note: Medium confidence; feature fit is strong, but implementation depth and data-source assumptions need inspection.

### 2026-06-26 - Usage AI coding-agent cost tracker

- Repo URL: https://github.com/aqua5230/usage
- Repo name: aqua5230/usage
- Feature or ability Thomas should consider: Usage and cost tracking for AI coding agents, with local reporting oriented around developer-agent sessions.
- Why it matters for Thomas: Thomas needs to connect autonomous worker outcomes to spend so expensive loops, retries, or low-yield workers are obvious.
- Integration surface guess: Cost ledger, worker run accounting, task-level spend summaries, retry attribution, and portal cost panels.
- Evidence/source URL: https://github.com/aqua5230/usage
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising local-cost pattern, with activity and provider coverage needing review.

### 2026-06-26 - cc-statistics Claude Code session analytics

- Repo URL: https://github.com/androidZzT/cc-statistics
- Repo name: androidZzT/cc-statistics
- Feature or ability Thomas should consider: Local analytics for Claude Code usage, including session statistics and token/cost summaries.
- Why it matters for Thomas: Even provider-specific session analytics can inform how Thomas should expose local worker usage, elapsed time, and budget burn-down.
- Integration surface guess: Claude/Codex worker session parser, portal analytics cards, budget warning thresholds, and local history ingestion.
- Evidence/source URL: https://github.com/androidZzT/cc-statistics
- Date found: 2026-06-26
- Confidence note: Medium confidence; narrower Claude Code focus, but useful for local coding-agent usage UX.

### 2026-06-26 - Tokscale multi-tool token usage tracker

- Repo URL: https://github.com/junhoyeo/tokscale
- Repo name: junhoyeo/tokscale
- Feature or ability Thomas should consider: Token usage tracking across AI coding tools with CLI-style reporting and spend visibility.
- Why it matters for Thomas: Thomas needs a cross-tool usage model because its work may involve Codex, Claude, local agents, and future model gateways.
- Integration surface guess: Multi-provider usage normalization, CLI reporting, portal trend charts, and per-worker budget snapshots.
- Evidence/source URL: https://github.com/junhoyeo/tokscale
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful cross-tool tracking idea, but should be evaluated for source compatibility and durability.

### 2026-06-26 - Tokentop terminal usage monitor

- Repo URL: https://github.com/tokentopapp/tokentop
- Repo name: tokentopapp/tokentop
- Feature or ability Thomas should consider: Terminal-style live monitor for token usage and agent session activity.
- Why it matters for Thomas: A top-like view could make live worker spend, throughput, and stuck sessions visible without opening every thread.
- Integration surface guess: `thomas top` or portal live monitor, worker heartbeat stream, token/cost counters, and active-run table.
- Evidence/source URL: https://github.com/tokentopapp/tokentop
- Date found: 2026-06-26
- Confidence note: Medium confidence; strong UX analogy, with repo health and data adapters needing review.

### 2026-06-26 - TokenBBQ AI usage cost dashboard

- Repo URL: https://github.com/offbyone1/tokenbbq
- Repo name: offbyone1/tokenbbq
- Feature or ability Thomas should consider: Dashboard for analyzing AI token usage, cost, and session-level consumption.
- Why it matters for Thomas: Thomas should give operators a lightweight way to inspect cumulative cost by worker, repository area, task type, and model.
- Integration surface guess: Usage warehouse, cost dashboards, CSV/JSON export, portal analytics, and run-level billing annotations.
- Evidence/source URL: https://github.com/offbyone1/tokenbbq
- Date found: 2026-06-26
- Confidence note: Medium confidence; relevant dashboard pattern, but project activity and model coverage need verification.

### 2026-06-26 - LiteLLM spend management gateway

- Repo URL: https://github.com/BerriAI/litellm
- Repo name: BerriAI/litellm
- Feature or ability Thomas should consider: OpenAI-compatible LLM gateway with virtual keys, provider routing, retries/fallbacks, guardrails, multi-tenant cost tracking, and spend management.
- Why it matters for Thomas: Thomas needs a central model gateway that can enforce budgets per worker, task, user, or repository area before autonomous loops create runaway cost.
- Integration surface guess: Model gateway adapter, worker API-key policy, spend ledger, per-task budget gates, provider fallback routing, and portal admin controls.
- Evidence/source URL: https://github.com/BerriAI/litellm
- Date found: 2026-06-26
- Confidence note: High confidence; mature and directly aligned with gateway-level budget enforcement.

### 2026-06-26 - Helicone LLM observability and cost control

- Repo URL: https://github.com/helicone/helicone
- Repo name: helicone/helicone
- Feature or ability Thomas should consider: Open-source LLM observability platform with request logging, model/user cost analytics, caching, and gateway-style routing.
- Why it matters for Thomas: Thomas should make cost, latency, cache hit rate, and model behavior inspectable by worker and workflow instead of only by provider billing account.
- Integration surface guess: Gateway observability, request metadata propagation, cache analytics, model-cost API, portal dashboards, and per-worker usage drilldowns.
- Evidence/source URL: https://github.com/helicone/helicone
- Date found: 2026-06-26
- Confidence note: High confidence; strong LLMOps cost/observability reference with active ecosystem usage.

### 2026-06-26 - Portkey AI gateway guardrails

- Repo URL: https://github.com/Portkey-AI/gateway
- Repo name: Portkey-AI/gateway
- Feature or ability Thomas should consider: AI gateway with model routing, integrated guardrails, observability, retries, fallbacks, and policy controls across many LLM providers.
- Why it matters for Thomas: Thomas worker execution needs a policy enforcement point that can route, block, retry, or downgrade requests based on cost, risk, and provider health.
- Integration surface guess: Gateway policy layer, guardrail hooks, model router, request metadata, budget/rate-limit policy, and MCP/agent gateway comparison.
- Evidence/source URL: https://github.com/Portkey-AI/gateway
- Date found: 2026-06-26
- Confidence note: High confidence; mature gateway pattern with guardrails that map well to Thomas autonomy controls.

### 2026-06-26 - Bifrost AI gateway

- Repo URL: https://github.com/maximhq/bifrost
- Repo name: maximhq/bifrost
- Feature or ability Thomas should consider: High-performance AI gateway with unified provider access, automatic failover, load balancing, semantic caching, governance, guardrails, and observability.
- Why it matters for Thomas: Thomas needs resilient provider routing so long-running worker swarms are not brittle when a provider is slow, down, too expensive, or rate-limited.
- Integration surface guess: Provider gateway benchmark, failover policy, semantic cache evaluation, model routing controls, and worker availability telemetry.
- Evidence/source URL: https://github.com/maximhq/bifrost
- Date found: 2026-06-26
- Confidence note: High confidence; strong gateway architecture reference, especially for performance and fallback design.

### 2026-06-26 - GoModel Go AI gateway

- Repo URL: https://github.com/ENTERPILOT/GOModel
- Repo name: ENTERPILOT/GOModel
- Feature or ability Thomas should consider: Go-based OpenAI-compatible AI gateway with observability, guardrails, streaming, costs, usage tracking, and provider abstraction.
- Why it matters for Thomas: GoModel is a compact reference for gateway UX around request/user-path cost attribution and cheap duplicate-call handling.
- Integration surface guess: Gateway comparison, request-path attribution, cost-by-user/team ideas, caching policy, provider abstraction, and lightweight self-hosting options.
- Evidence/source URL: https://github.com/ENTERPILOT/GOModel
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; active gateway with directly relevant usage/cost tracking claims.

### 2026-06-26 - Shekel LLM budget control

- Repo URL: https://github.com/arieradle/shekel
- Repo name: arieradle/shekel
- Feature or ability Thomas should consider: Python budget-control library for AI agents with token budgets, usage limits, cost governance, and adapters for OpenAI, Anthropic, LangChain, and LangGraph.
- Why it matters for Thomas: Thomas can use this as a concrete reference for pre-call budget checks inside agent loops, not just after-the-fact dashboards.
- Integration surface guess: Worker preflight budget guard, LangGraph-style adapter comparison, denial-of-wallet protection, budget exception handling, and run-level usage limits.
- Evidence/source URL: https://github.com/arieradle/shekel
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; small project but highly targeted to agentic cost governance.

### 2026-06-26 - llm-budget autonomous cost governance

- Repo URL: https://github.com/Mattbusel/llm-budget
- Repo name: Mattbusel/llm-budget
- Feature or ability Thomas should consider: Autonomous cost-governance primitives for hard budget enforcement across agent fleets, including spend tracking per model, agent, and fleet.
- Why it matters for Thomas: Thomas needs fleet-level budget caps that can stop low-value autonomous work before it consumes the whole run budget.
- Integration surface guess: Fleet budget ledger, hard-stop request guard, structured cost events, per-agent spend limits, and audit-trail export.
- Evidence/source URL: https://github.com/Mattbusel/llm-budget
- Date found: 2026-06-26
- Confidence note: Medium confidence; concept matches Thomas well, but project maturity appears early.

### 2026-06-26 - Azure AI Gateway labs for agents

- Repo URL: https://github.com/Azure-Samples/AI-Gateway
- Repo name: Azure-Samples/AI-Gateway
- Feature or ability Thomas should consider: Labs for AI models, MCP servers, and agents behind an AI Gateway using Azure API Management and Microsoft Foundry.
- Why it matters for Thomas: This provides enterprise gateway patterns for putting agents, MCP tools, and model calls behind one governed policy surface.
- Integration surface guess: MCP gateway policy comparison, enterprise API-management patterns, agent access controls, rate/budget policies, and Foundry/Azure adapter research.
- Evidence/source URL: https://github.com/Azure-Samples/AI-Gateway
- Date found: 2026-06-26
- Confidence note: High confidence as a reference architecture; direct adoption depends on whether Thomas wants Azure-specific integrations.

### 2026-06-26 - GPTCache semantic cache for LLMs

- Repo URL: https://github.com/zilliztech/GPTCache
- Repo name: zilliztech/GPTCache
- Feature or ability Thomas should consider: Semantic cache for LLM queries with LangChain and LlamaIndex integration, server mode, similarity matching, and configurable storage backends.
- Why it matters for Thomas: Thomas can reduce repeated model calls from worker retries, duplicate research loops, and repeated repository-orientation prompts while improving response latency.
- Integration surface guess: Gateway semantic cache, prompt fingerprinting, cache safety policy, worker retry de-duplication, cost reduction metrics, and vector-store backed cache invalidation.
- Evidence/source URL: https://github.com/zilliztech/GPTCache
- Date found: 2026-06-26
- Confidence note: High confidence; mature semantic-cache reference with broad adoption and clear cost/latency benefit.

### 2026-06-26 - vLLM semantic router

- Repo URL: https://github.com/vllm-project/semantic-router
- Repo name: vllm-project/semantic-router
- Feature or ability Thomas should consider: System-level intelligent router for mixture-of-models across cloud, data center, and edge environments.
- Why it matters for Thomas: Thomas needs routing policies that can pick cheaper, faster, or local models for low-risk worker steps while preserving stronger models for high-stakes decisions.
- Integration surface guess: Model routing policy, local/cloud provider selection, task-risk routing, benchmark-driven model choice, and gateway failover strategy.
- Evidence/source URL: https://github.com/vllm-project/semantic-router
- Date found: 2026-06-26
- Confidence note: High confidence; strong fit for quota-aware model selection and local/cloud scheduling research.

### 2026-06-26 - Envoy AI Gateway

- Repo URL: https://github.com/envoyproxy/ai-gateway
- Repo name: envoyproxy/ai-gateway
- Feature or ability Thomas should consider: Envoy Gateway extension for unified access to generative AI services, focused on traffic management and AI service governance.
- Why it matters for Thomas: Thomas can learn how cloud-native gateways expose AI traffic policy, routing, rate controls, and observability without baking those choices into worker code.
- Integration surface guess: Gateway architecture comparison, Kubernetes deployment pattern, rate-limit policy, request metadata propagation, provider failover, and observability hooks.
- Evidence/source URL: https://github.com/envoyproxy/ai-gateway
- Date found: 2026-06-26
- Confidence note: High confidence; credible infrastructure reference from the Envoy ecosystem.

### 2026-06-26 - Upstash semantic-cache

- Repo URL: https://github.com/upstash/semantic-cache
- Repo name: upstash/semantic-cache
- Feature or ability Thomas should consider: Fuzzy key-value store based on semantic similarity rather than exact lexical equality.
- Why it matters for Thomas: Thomas needs a simple cache abstraction for repeated agent prompts where exact string matching is too brittle but uncontrolled reuse could be risky.
- Integration surface guess: Prompt/result cache layer, similarity-threshold policy, cache audit trail, vector-backed cache experiments, and low-latency worker context reuse.
- Evidence/source URL: https://github.com/upstash/semantic-cache
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; compact semantic-cache reference that is easier to reason about than a full gateway stack.

### 2026-06-26 - CodeFuse ModelCache

- Repo URL: https://github.com/codefuse-ai/ModelCache
- Repo name: codefuse-ai/ModelCache
- Feature or ability Thomas should consider: LLM semantic caching system with cache services, multiple storage options, embedding/ranking components, and API server examples.
- Why it matters for Thomas: Thomas can compare cache service designs for multi-worker reuse, multi-tenant cache keys, and cache hit/miss latency measurement.
- Integration surface guess: Cache service prototype, vector-store backend comparison, multi-worker shared cache, response-rank validation, and latency/cost dashboards.
- Evidence/source URL: https://github.com/codefuse-ai/ModelCache
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful architecture and service-mode reference, though project momentum should be checked before adoption.

### 2026-06-26 - Verified semantic cache for LLM agents

- Repo URL: https://github.com/aws-samples/Reducing-Hallucinations-in-LLM-Agents-with-a-Verified-Semantic-Cache
- Repo name: aws-samples/Reducing-Hallucinations-in-LLM-Agents-with-a-Verified-Semantic-Cache
- Feature or ability Thomas should consider: Verified semantic cache pattern for LLM agents that checks cached answers against knowledge bases to reduce hallucinations while improving cost and latency.
- Why it matters for Thomas: Thomas needs cache safety gates so semantic caching does not replay stale or unverifiable outputs into autonomous worker decisions.
- Integration surface guess: Verified cache policy, RAG-backed cache validation, cache provenance, safe cache-hit criteria, and agent answer grounding checks.
- Evidence/source URL: https://github.com/aws-samples/Reducing-Hallucinations-in-LLM-Agents-with-a-Verified-Semantic-Cache
- Date found: 2026-06-26
- Confidence note: High confidence as a safety pattern; implementation is AWS-specific but the verification idea is portable.

### 2026-06-26 - Higress AI Gateway

- Repo URL: https://github.com/higress-group/higress
- Repo name: higress-group/higress
- Feature or ability Thomas should consider: AI-native API Gateway with LLM proxying, plugin extensibility, traffic governance, and cloud-native gateway controls.
- Why it matters for Thomas: Thomas can compare AI gateway plugin models for adding budget, guardrail, observability, and provider policy without changing agent code.
- Integration surface guess: Gateway plugin architecture, LLM proxy comparison, traffic governance, rate/budget plugins, and MCP/tool gateway policy research.
- Evidence/source URL: https://github.com/higress-group/higress
- Date found: 2026-06-26
- Confidence note: High confidence; mature gateway project with explicit AI Gateway positioning.

### 2026-06-26 - SmarterRouter local AI lab gateway

- Repo URL: https://github.com/peva3/SmarterRouter
- Repo name: peva3/SmarterRouter
- Feature or ability Thomas should consider: Intelligent LLM gateway and VRAM-aware router for Ollama, llama.cpp, and OpenAI with semantic caching, model profiling, and automatic failover.
- Why it matters for Thomas: Thomas should understand local-model capacity and failover when deciding whether a worker step can run locally, remotely, or on a smaller model.
- Integration surface guess: Local model scheduler, VRAM-aware routing, Ollama/llama.cpp gateway, semantic cache, model profiling, and provider failover policy.
- Evidence/source URL: https://github.com/peva3/SmarterRouter
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; smaller project, but the local-capacity routing pattern is highly relevant.

### 2026-06-26 - RouteLLM router serving and evaluation

- Repo URL: https://github.com/lm-sys/RouteLLM
- Repo name: lm-sys/RouteLLM
- Feature or ability Thomas should consider: Framework for serving and evaluating LLM routers that route between stronger and cheaper models using preference data.
- Why it matters for Thomas: Thomas needs defensible model-routing thresholds so worker steps can trade cost against quality without hand-written model-choice rules.
- Integration surface guess: Router benchmark harness, threshold calibration, model-choice audit logs, budget-aware gateway policy, and per-task quality/cost evaluation.
- Evidence/source URL: https://github.com/lm-sys/RouteLLM
- Date found: 2026-06-26
- Confidence note: High confidence; strong research-backed router framework with direct cost-quality relevance.

### 2026-06-26 - UIUC LLMRouter

- Repo URL: https://github.com/ulab-uiuc/LLMRouter
- Repo name: ulab-uiuc/LLMRouter
- Feature or ability Thomas should consider: Open-source library for LLM routing that dynamically selects suitable models for single-round, multi-round, agentic, and personalized settings.
- Why it matters for Thomas: Thomas worker routing should account for multi-turn and agentic task context, not only one-shot prompt difficulty.
- Integration surface guess: Agentic routing benchmark, personalized/user-aware model policy, route replay tests, scheduler integration, and model-selection telemetry.
- Evidence/source URL: https://github.com/ulab-uiuc/LLMRouter
- Date found: 2026-06-26
- Confidence note: High confidence; explicitly covers agentic routing and fair comparison across routing methods.

### 2026-06-26 - Anyscale llm-router tutorial

- Repo URL: https://github.com/anyscale/llm-router
- Repo name: anyscale/llm-router
- Feature or ability Thomas should consider: Tutorial implementation for training a classifier-based LLM router that chooses between high-quality and lower-cost models.
- Why it matters for Thomas: Thomas can use this as a practical recipe for training or evaluating routers against its own task corpus and cost constraints.
- Integration surface guess: Router training notebook, offline route evaluation, worker transcript dataset, cheap/strong model thresholding, and cost-savings simulation.
- Evidence/source URL: https://github.com/anyscale/llm-router
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; tutorial scope, but useful as an implementation bridge from router theory to Thomas experiments.

### 2026-06-26 - LMCache reusable KV cache layer

- Repo URL: https://github.com/LMCache/LMCache
- Repo name: LMCache/LMCache
- Feature or ability Thomas should consider: KV cache management layer for LLM inference that persists, reuses, monitors, and transforms caches across serving engines.
- Why it matters for Thomas: Long-context agentic and multi-turn worker runs are expensive; reusable KV cache infrastructure could reduce TTFT and improve throughput for local or self-hosted models.
- Integration surface guess: Local inference acceleration, long-context worker cache, vLLM/SGLang experiments, cache observability, and multi-worker cache sharing.
- Evidence/source URL: https://github.com/LMCache/LMCache
- Date found: 2026-06-26
- Confidence note: High confidence; active infrastructure project aimed at agentic and long-context workloads.

### 2026-06-26 - OpenZiti zero-trust LLM gateway

- Repo URL: https://github.com/openziti/llm-gateway
- Repo name: openziti/llm-gateway
- Feature or ability Thomas should consider: OpenAI-compatible gateway for routing to OpenAI, Anthropic, Ollama, vLLM, llama-server, SGLang, and other backends over zero-trust connectivity.
- Why it matters for Thomas: Thomas may need to route workers to private local inference endpoints without exposing ports or relying on ad hoc VPN setup.
- Integration surface guess: Private model mesh, zero-trust worker connectivity, local inference gateway, provider routing, and secure remote MCP/model access.
- Evidence/source URL: https://github.com/openziti/llm-gateway
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; differentiated security model, but Thomas fit depends on private model deployment plans.

### 2026-06-26 - Databricks semantic-caching

- Repo URL: https://github.com/databricks-industry-solutions/semantic-caching
- Repo name: databricks-industry-solutions/semantic-caching
- Feature or ability Thomas should consider: Databricks solution accelerator for semantic caching to reduce redundant AI computation and improve latency/server load.
- Why it matters for Thomas: Thomas can study cache hit criteria and enterprise notebook patterns for scaling repeated agent queries without hiding provenance.
- Integration surface guess: Semantic-cache benchmark, cache hit/miss instrumentation, cost reduction experiment, notebook-to-service extraction, and cache provenance reporting.
- Evidence/source URL: https://github.com/databricks-industry-solutions/semantic-caching
- Date found: 2026-06-26
- Confidence note: Medium confidence; good enterprise pattern, with platform-specific assumptions to separate from the portable design.

### 2026-06-26 - Apigee semantic cache sample

- Repo URL: https://github.com/GoogleCloudPlatform/apigee-samples
- Repo name: GoogleCloudPlatform/apigee-samples
- Feature or ability Thomas should consider: Apigee sample set including an LLM semantic-cache notebook and API-proxy examples for gateway-side cache measurement.
- Why it matters for Thomas: Gateway-side cache experiments should include repeat-prompt measurement, latency visualization, and deployment policy examples.
- Integration surface guess: API gateway cache comparison, semantic-cache measurement notebook, gateway policy examples, cache performance charts, and enterprise proxy research.
- Evidence/source URL: https://github.com/GoogleCloudPlatform/apigee-samples/blob/main/llm-semantic-cache/llm_semantic_cache_v1.ipynb
- Date found: 2026-06-26
- Confidence note: Medium confidence; sample-focused rather than agent framework, but useful for gateway cache measurement.

### 2026-06-26 - NVIDIA LLM Router Blueprint

- Repo URL: https://github.com/NVIDIA-AI-Blueprints/llm-router
- Repo name: NVIDIA-AI-Blueprints/llm-router
- Feature or ability Thomas should consider: Experimental router blueprint for choosing optimal text or multimodal models based on prompt analysis and speed/cost/accuracy tradeoffs.
- Why it matters for Thomas: Thomas will need route replay and benchmark evidence before delegating worker steps to cheaper, faster, or multimodal models.
- Integration surface guess: Model-router benchmark, multimodal route policy, NIM/local deployment comparison, Docker-based router experiments, and route telemetry.
- Evidence/source URL: https://github.com/NVIDIA-AI-Blueprints/llm-router
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong blueprint for route experimentation, though NVIDIA stack assumptions need review.

### 2026-06-26 - BenchFlow universal agent evaluation environments

- Repo URL: https://github.com/benchflow-ai/BenchFlow
- Repo name: benchflow-ai/benchflow
- Feature or ability Thomas should consider: Universal environment framework for running agents against task environments with single-agent, multi-agent, multi-round, loop strategies, scored trajectories, and token/cost output.
- Why it matters for Thomas: Thomas needs a durable way to replay worker strategies, compare agents/models, and plot capability against cost instead of judging runs only by final success.
- Integration surface guess: Worker benchmark harness, route replay datasets, loop-strategy evaluation, scored trajectory export, sandbox integration, and cost/capability dashboards.
- Evidence/source URL: https://github.com/benchflow-ai/BenchFlow
- Date found: 2026-06-26
- Confidence note: High confidence; very close match to Thomas worker evaluation and multi-agent reviewer patterns.

### 2026-06-26 - SkillsBench skill-use benchmark

- Repo URL: https://github.com/benchflow-ai/SkillsBench
- Repo name: benchflow-ai/skillsbench
- Feature or ability Thomas should consider: Benchmark for evaluating how well agent skills work and how effectively agents discover and use them.
- Why it matters for Thomas: Thomas has many agent skills/tools; it needs evidence that skills are usable, not just present in a registry.
- Integration surface guess: Skill registry evals, task.md benchmark conversion, agent skill-selection telemetry, regression tasks for new skills, and per-skill capability scoring.
- Evidence/source URL: https://github.com/benchflow-ai/SkillsBench
- Date found: 2026-06-26
- Confidence note: High confidence; directly relevant to evaluating Thomas skills and tool discoverability.

### 2026-06-26 - Accenture MCP-Bench

- Repo URL: https://github.com/Accenture/mcp-bench
- Repo name: Accenture/mcp-bench
- Feature or ability Thomas should consider: Benchmark for tool-using LLM agents over complex real-world tasks via MCP servers.
- Why it matters for Thomas: MCP tool quality and server orchestration should be benchmarked under realistic task pressure before Thomas relies on them for autonomous work.
- Integration surface guess: MCP tool benchmark suite, server-selection evals, task decomposition traces, tool-call scoring, and MCP regression gates.
- Evidence/source URL: https://github.com/Accenture/mcp-bench
- Date found: 2026-06-26
- Confidence note: High confidence; strong direct fit for Thomas MCP tool-use evaluation.

### 2026-06-26 - Salesforce MCP-Universe

- Repo URL: https://github.com/SalesforceAIResearch/MCP-Universe
- Repo name: SalesforceAIResearch/MCP-Universe
- Feature or ability Thomas should consider: Framework for reinforcement-learning training, benchmarking, and developing AI agents for general tool use across MCP-style environments.
- Why it matters for Thomas: Thomas should track whether tool-use policies improve over time and whether agents can generalize across tools, servers, and task domains.
- Integration surface guess: MCP environment harness, general tool-use benchmark, RL/eval data format comparison, tool policy scoring, and agent training research.
- Evidence/source URL: https://github.com/SalesforceAIResearch/MCP-Universe
- Date found: 2026-06-26
- Confidence note: High confidence; broad MCP/tool-use evaluation surface with active research value.

### 2026-06-26 - AgentBench function-calling agent benchmark

- Repo URL: https://github.com/THUDM/AgentBench
- Repo name: THUDM/AgentBench
- Feature or ability Thomas should consider: Comprehensive benchmark for LLM agents, including function-calling tasks and containerized environments such as OS, database, knowledge graph, and webshop tasks.
- Why it matters for Thomas: Thomas needs cross-domain agent capability signals beyond coding tasks, especially around OS/database operations and multi-turn tool use.
- Integration surface guess: Agent capability baseline, containerized task harness comparison, function-call scoring, environment adapters, and benchmark-driven model routing.
- Evidence/source URL: https://github.com/THUDM/AgentBench
- Date found: 2026-06-26
- Confidence note: High confidence; mature benchmark with broad agent-task coverage.

### 2026-06-26 - ToolBench tool-learning evaluation

- Repo URL: https://github.com/OpenBMB/ToolBench
- Repo name: OpenBMB/ToolBench
- Feature or ability Thomas should consider: Open platform for training, serving, and evaluating large language models for tool learning.
- Why it matters for Thomas: Thomas should evaluate tool selection, tool-call ordering, and API-use reliability as first-class capabilities, not incidental model behavior.
- Integration surface guess: Tool-call benchmark adapter, tool selection metrics, API trajectory scoring, synthetic tool task generation, and tool-use training data review.
- Evidence/source URL: https://github.com/OpenBMB/ToolBench
- Date found: 2026-06-26
- Confidence note: High confidence; established tool-use benchmark relevant to Thomas agent tools.

### 2026-06-26 - Mind2Web generalist web-agent benchmark

- Repo URL: https://github.com/OSU-NLP-Group/Mind2Web
- Repo name: OSU-NLP-Group/Mind2Web
- Feature or ability Thomas should consider: Web-agent benchmark for learning and evaluating action prediction on real websites.
- Why it matters for Thomas: Thomas browser automation should be measured on realistic web workflows, including action grounding and cross-site generalization.
- Integration surface guess: Browser-agent eval adapter, action prediction scoring, web task replay, screenshot/DOM trace comparison, and browser-tool regression tests.
- Evidence/source URL: https://github.com/OSU-NLP-Group/Mind2Web
- Date found: 2026-06-26
- Confidence note: High confidence; strong web-agent benchmark that complements Thomas browser tooling.

### 2026-06-26 - redacted-acp-peer multi-agent test suite

- Repo URL: https://github.com/ThinkOffApp/redacted-acp-peer-multi-agent-test-suite
- Repo name: ThinkOffApp/redacted-acp-peer-multi-agent-test-suite
- Feature or ability Thomas should consider: Reproducible benchmark for measuring LLM performance in multi-agent environments using a staged model-capability framework.
- Why it matters for Thomas: Thomas coordination claims should be tested under multi-agent failure modes, not inferred from single-agent task success.
- Integration surface guess: Multi-agent benchmark tasks, coordinator/reviewer scoring, staged capability rubric, route replay, and agent-collaboration regression suite.
- Evidence/source URL: https://github.com/ThinkOffApp/redacted-acp-peer-multi-agent-test-suite
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; directly relevant to multi-agent capability scoring, though project maturity needs review.

### 2026-06-26 - Scorecard MCP Eval

- Repo URL: https://github.com/scorecard-ai/mcp-eval
- Repo name: scorecard-ai/mcp-eval
- Feature or ability Thomas should consider: Evaluation framework for MCP servers and agents that can score tool-use behavior and MCP server quality.
- Why it matters for Thomas: Thomas needs MCP server scorecards before trusting external tools in autonomous workflows, especially where tool descriptions and schemas drift.
- Integration surface guess: MCP server regression suite, tool-quality scorecards, server onboarding gate, workboard problem generation from failed evals, and portal score display.
- Evidence/source URL: https://github.com/scorecard-ai/mcp-eval
- Date found: 2026-06-26
- Confidence note: High confidence; directly aligned with MCP server scoring and regression gates.

### 2026-06-26 - Scorecard MCP server

- Repo URL: https://github.com/scorecard-ai/scorecard-mcp
- Repo name: scorecard-ai/scorecard-mcp
- Feature or ability Thomas should consider: MCP server exposing Scorecard evaluation workflows through MCP-native tools.
- Why it matters for Thomas: Thomas can learn how to make evaluation results available as tools that agents can query during planning, review, and handoff.
- Integration surface guess: Eval-result MCP tools, benchmark-to-workboard issue conversion, reviewer-agent evidence fetch, scorecard API adapter, and MCP-native quality gates.
- Evidence/source URL: https://github.com/scorecard-ai/scorecard-mcp
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful MCP-native wrapper pattern, with depth depending on Scorecard platform assumptions.

### 2026-06-26 - LastMile MCP Eval

- Repo URL: https://github.com/lastmile-ai/mcp-eval
- Repo name: lastmile-ai/mcp-eval
- Feature or ability Thomas should consider: Developer-focused eval tooling for MCP servers, including tool-call testing and server behavior checks.
- Why it matters for Thomas: Thomas already tracks MCP agent frameworks; it also needs a repeatable local eval loop for MCP servers before they enter trusted worker paths.
- Integration surface guess: MCP server CI checks, local server smoke tests, tool-call replay fixtures, contract drift detection, and eval summaries in workboard issues.
- Evidence/source URL: https://github.com/lastmile-ai/mcp-eval
- Date found: 2026-06-26
- Confidence note: High confidence; adjacent to already queued `lastmile-ai/mcp-agent` but focused on evaluation.

### 2026-06-26 - MCP Atlas

- Repo URL: https://github.com/scaleapi/mcp-atlas
- Repo name: scaleapi/mcp-atlas
- Feature or ability Thomas should consider: Benchmark and dataset suite for evaluating MCP servers and their tool coverage.
- Why it matters for Thomas: Thomas needs broader MCP server comparison data to choose which tools are worth wrapping, mirroring, or rejecting.
- Integration surface guess: MCP server catalog scoring, tool coverage matrix, benchmark ingestion, server-selection heuristics, and portal scorecard summaries.
- Evidence/source URL: https://github.com/scaleapi/mcp-atlas
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful for MCP server scorecards, with implementation maturity to verify.

### 2026-06-26 - AgentTrek browser trajectory benchmark

- Repo URL: https://github.com/xlang-ai/AgentTrek
- Repo name: xlang-ai/AgentTrek
- Feature or ability Thomas should consider: Benchmark and trajectory resource for web agents with browser-action traces and task execution data.
- Why it matters for Thomas: Thomas browser tasks should be replayable and inspectable so failed browser actions can become reproducible workboard issues.
- Integration surface guess: Browser-action replay traces, DOM/screenshot trajectory storage, browser-tool regression tests, task failure triage, and route replay datasets.
- Evidence/source URL: https://github.com/xlang-ai/AgentTrek
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong fit for replayable browser-agent traces.

### 2026-06-26 - Reproducible Trajectories for web agents

- Repo URL: https://github.com/ASSERT-KTH/reproducible-trajectories
- Repo name: ASSERT-KTH/reproducible-trajectories
- Feature or ability Thomas should consider: Research artifact for capturing and replaying reproducible web-agent trajectories.
- Why it matters for Thomas: Thomas needs failed agent/browser runs to be replayable across machines and time, not trapped as screenshots and prose summaries.
- Integration surface guess: Trajectory serialization, browser replay harness, deterministic web-task evidence, regression fixture generation, and trace-to-issue conversion.
- Evidence/source URL: https://github.com/ASSERT-KTH/reproducible-trajectories
- Date found: 2026-06-26
- Confidence note: Medium confidence; research artifact, but the reproducibility pattern is central to Thomas browser-agent QA.

### 2026-06-26 - OSWorld-V2 computer-use benchmark

- Repo URL: https://github.com/xlang-ai/OSWorld-V2
- Repo name: xlang-ai/OSWorld-V2
- Feature or ability Thomas should consider: Updated OSWorld benchmark for evaluating multimodal agents on real computer-use tasks.
- Why it matters for Thomas: Thomas should benchmark desktop/computer-use abilities with task traces and observable state before relying on GUI automation for user-visible workflows.
- Integration surface guess: Computer-use eval harness, GUI action scoring, screenshot/state replay, worker capability routing, and safety gates for desktop automation.
- Evidence/source URL: https://github.com/xlang-ai/OSWorld-V2
- Date found: 2026-06-26
- Confidence note: High confidence; strong benchmark lineage and directly relevant to computer-use worker capability.

### 2026-06-26 - Stagehand browser automation framework

- Repo URL: https://github.com/browserbase/stagehand
- Repo name: browserbase/stagehand
- Feature or ability Thomas should consider: Browser automation framework that combines Playwright-style actions with AI-assisted extraction and action planning.
- Why it matters for Thomas: Thomas browser workers need deterministic browser primitives with AI assistance layered on top, plus traceable actions that can be replayed and tested.
- Integration surface guess: Browser-tool adapter, action replay fixtures, extraction validation, Playwright trace integration, and browser-agent regression tests.
- Evidence/source URL: https://github.com/browserbase/stagehand
- Date found: 2026-06-26
- Confidence note: High confidence; active browser-agent framework with practical tooling patterns for Thomas browser work.

### 2026-06-26 - Agent-native research artifact provenance

- Repo URL: https://github.com/AmberLJC/Agent-Native-Research-Artifact
- Repo name: AmberLJC/Agent-Native-Research-Artifact
- Feature or ability Thomas should consider: Research artifact showing how agents can generate, organize, and preserve structured artifacts from research workflows.
- Why it matters for Thomas: Thomas should treat task outputs, traces, notes, decisions, and evidence as durable artifacts that can be replayed, ranked, and converted into workboard items.
- Integration surface guess: Task artifact provenance, research-run package format, evidence bundles, queue-entry source trails, and worker output lineage.
- Evidence/source URL: https://github.com/AmberLJC/Agent-Native-Research-Artifact
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; research-oriented, but the artifact/provenance pattern maps cleanly to Thomas queues.

### 2026-06-26 - Why agents fail sample

- Repo URL: https://github.com/aws-samples/sample-why-agents-fail
- Repo name: aws-samples/sample-why-agents-fail
- Feature or ability Thomas should consider: Sample code and examples for analyzing common AI agent failure modes such as tool misuse, planning errors, and missing context.
- Why it matters for Thomas: Thomas needs failure clustering so repeated worker breakdowns become actionable bug classes instead of isolated anecdotes.
- Integration surface guess: Failure taxonomy, eval-failure clustering, reviewer diagnostics, workboard issue generation, and regression examples for agent loops.
- Evidence/source URL: https://github.com/aws-samples/sample-why-agents-fail
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; sample scope, but useful for failure-mode taxonomy and education.

### 2026-06-26 - LLM agents study trajectory analysis

- Repo URL: https://github.com/sola-st/llm-agents-study
- Repo name: sola-st/llm-agents-study
- Feature or ability Thomas should consider: Study tooling and materials for observing, analyzing, and comparing LLM agent behavior.
- Why it matters for Thomas: Thomas should preserve enough run data to compare agent behavior across prompts, models, and tool policies rather than only final pass/fail.
- Integration surface guess: Agent trajectory analysis, behavior clustering, trace annotation schema, experiment logs, and capability regression research.
- Evidence/source URL: https://github.com/sola-st/llm-agents-study
- Date found: 2026-06-26
- Confidence note: Medium confidence; research utility depends on contents, but it fits the trajectory-analysis lane.

### 2026-06-26 - MCP server fuzzer

- Repo URL: https://github.com/Agent-Hellboy/mcp-server-fuzzer
- Repo name: Agent-Hellboy/mcp-server-fuzzer
- Feature or ability Thomas should consider: Fuzzer for testing MCP server tools, schemas, and robustness against unexpected inputs.
- Why it matters for Thomas: Thomas should fuzz MCP/tool contracts before giving autonomous workers access to fragile or unsafe tool servers.
- Integration surface guess: MCP contract fuzzing, tool schema robustness tests, server onboarding gate, CI fuzz fixtures, and security regression artifacts.
- Evidence/source URL: https://github.com/Agent-Hellboy/mcp-server-fuzzer
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; small but directly targeted at MCP tool hardening.

### 2026-06-26 - Agent contracts

- Repo URL: https://github.com/relari-ai/agent-contracts
- Repo name: relari-ai/agent-contracts
- Feature or ability Thomas should consider: Contract-style tests and assertions for AI agents, focused on expected behavior and regression detection.
- Why it matters for Thomas: Thomas needs explicit behavioral contracts for agent tools, workboard handoffs, browser actions, and safety gates.
- Integration surface guess: Agent behavior contracts, contract-driven evals, CI regression gates, reviewer assertions, and run acceptance criteria.
- Evidence/source URL: https://github.com/relari-ai/agent-contracts
- Date found: 2026-06-26
- Confidence note: High confidence; contract-testing pattern is directly valuable for Thomas agent reliability.

### 2026-06-26 - Nano-step eval harness

- Repo URL: https://github.com/nano-step/eval-harness
- Repo name: nano-step/eval-harness
- Feature or ability Thomas should consider: Harness for defining and running repeatable AI eval cases with structured expected outputs.
- Why it matters for Thomas: Thomas needs lightweight eval scaffolding that can turn worker failures and task examples into repeatable regression cases quickly.
- Integration surface guess: Eval case format, regression harness, task artifact conversion, expected-output assertions, and score summaries.
- Evidence/source URL: https://github.com/nano-step/eval-harness
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful lightweight pattern if the harness is simple enough to adapt.

### 2026-06-26 - MCP Inspector

- Repo URL: https://github.com/modelcontextprotocol/inspector
- Repo name: modelcontextprotocol/inspector
- Feature or ability Thomas should consider: Developer tool for inspecting, testing, and debugging MCP servers and tools interactively.
- Why it matters for Thomas: Thomas should expose a practical MCP debugging path before treating a server as trusted infrastructure for workers.
- Integration surface guess: MCP server inspection, tool schema review, manual server smoke tests, developer portal diagnostics, and onboarding checklist.
- Evidence/source URL: https://github.com/modelcontextprotocol/inspector
- Date found: 2026-06-26
- Confidence note: High confidence; official MCP tooling and directly relevant to server quality gates.

### 2026-06-26 - MCP security hub

- Repo URL: https://github.com/FuzzingLabs/mcp-security-hub
- Repo name: FuzzingLabs/mcp-security-hub
- Feature or ability Thomas should consider: Collection of MCP security resources, tools, and testing references for MCP server and tool hardening.
- Why it matters for Thomas: Thomas needs MCP security and fuzzing practices alongside functional scorecards, especially before accepting third-party tools.
- Integration surface guess: MCP security checklist, fuzzing tool map, server risk scoring, onboarding policy, and security regression backlog.
- Evidence/source URL: https://github.com/FuzzingLabs/mcp-security-hub
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; partly catalog-style, but relevant as a security and fuzzing source map.

### 2026-06-26 - Microsoft eval-guide

- Repo URL: https://github.com/microsoft/eval-guide
- Repo name: microsoft/eval-guide
- Feature or ability Thomas should consider: AI agent evaluation toolkit for planning evals, generating test cases, interpreting results, and triaging failures from Claude Code or GitHub Copilot.
- Why it matters for Thomas: Thomas needs a guided path from vague worker failures to eval plans, concrete cases, and triaged improvements.
- Integration surface guess: Eval planning assistant, failure triage workflow, test-case generation, workboard issue conversion, and reviewer/coordinator playbooks.
- Evidence/source URL: https://github.com/microsoft/eval-guide
- Date found: 2026-06-26
- Confidence note: High confidence; directly aligned with agent eval planning and failure triage.

### 2026-06-26 - IBM CLEAR

- Repo URL: https://github.com/IBM/CLEAR
- Repo name: IBM/CLEAR
- Feature or ability Thomas should consider: Comprehensive LLM error analysis and reporting with automated LLM-as-judge evaluation, recurring error-pattern discovery, and interactive dashboards.
- Why it matters for Thomas: Thomas should cluster repeated worker failures by pattern and severity so the workboard gets prioritized defects instead of raw logs.
- Integration surface guess: Failure-cluster dashboard, trace-to-error-pattern pipeline, evaluator summaries, severity scoring, and workboard issue generation.
- Evidence/source URL: https://github.com/IBM/CLEAR
- Date found: 2026-06-26
- Confidence note: High confidence; strong match for eval-failure clustering and dashboarding.

### 2026-06-26 - SAP agent-quality-inspect

- Repo URL: https://github.com/SAP/agent-quality-inspect
- Repo name: SAP/agent-quality-inspect
- Feature or ability Thomas should consider: Evaluation package for benchmarking agentic AIs across sources/frameworks with statistical result comparison, metrics, and error analysis.
- Why it matters for Thomas: Thomas needs framework-neutral quality inspection for agents and worker configurations, not one-off scores tied to a single provider.
- Integration surface guess: Agent quality benchmark runner, cross-framework comparison, statistical reports, error-analysis ingestion, and portal quality dashboards.
- Evidence/source URL: https://github.com/SAP/agent-quality-inspect
- Date found: 2026-06-26
- Confidence note: High confidence; directly agentic and evaluation-focused.

### 2026-06-26 - Vercel agent-eval

- Repo URL: https://github.com/vercel-labs/agent-eval
- Repo name: vercel-labs/agent-eval
- Feature or ability Thomas should consider: Agent eval framework that asserts on final artifacts and agent behavior such as shell commands, files read, tool calls, and transcript-derived results.
- Why it matters for Thomas: Thomas must verify not only whether a worker produced a file, but whether it used acceptable methods and stayed within expected tool/command behavior.
- Integration surface guess: Worker behavior assertions, transcript parser, sandboxed eval fixtures, command/file access checks, and acceptance criteria for coding tasks.
- Evidence/source URL: https://github.com/vercel-labs/agent-eval
- Date found: 2026-06-26
- Confidence note: High confidence; unusually close fit for coding-agent behavior regression tests.

### 2026-06-26 - Azure Agentic Evaluations

- Repo URL: https://github.com/Azure-Samples/Agentic-Evaluations
- Repo name: Azure-Samples/Agentic-Evaluations
- Feature or ability Thomas should consider: Config-driven evaluation framework for agentic systems and GenAI applications with YAML experiment configuration.
- Why it matters for Thomas: Thomas needs repeatable, declarative eval configs so worker quality checks can run in CI or before promotion without bespoke scripts each time.
- Integration surface guess: YAML eval specs, Foundry adapter comparison, CI evaluation jobs, multi-agent workflow tests, and eval artifact outputs.
- Evidence/source URL: https://github.com/Azure-Samples/Agentic-Evaluations
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong config-driven pattern, with Azure-specific dependencies to isolate.

### 2026-06-26 - Microsoft eval-recipes

- Repo URL: https://github.com/microsoft/eval-recipes
- Repo name: microsoft/eval-recipes
- Feature or ability Thomas should consider: Benchmarking harness for evaluating AI agents on real-world tasks in isolated Docker containers with deterministic and semantic scoring.
- Why it matters for Thomas: Thomas workers need sandboxed, reproducible task evals that can compare implementations and catch regressions before deployment.
- Integration surface guess: Dockerized eval tasks, task recipe format, deterministic/semantic scoring, auditing-agent comparison, and regression-suite authoring.
- Evidence/source URL: https://github.com/microsoft/eval-recipes
- Date found: 2026-06-26
- Confidence note: High confidence; excellent match for repeatable worker task evaluation.

### 2026-06-26 - DeepEval LLM eval framework

- Repo URL: https://github.com/confident-ai/deepeval
- Repo name: confident-ai/deepeval
- Feature or ability Thomas should consider: Pytest-like open-source framework for evaluating LLM systems with metrics for task completion, hallucination, relevancy, and LLM-as-judge checks.
- Why it matters for Thomas: Thomas should turn agent expectations into code-level eval tests that can run locally and in CI, especially around failure clusters.
- Integration surface guess: Python eval tests, CI quality gates, agent contract assertions, local JSON result export, and metric comparison with Thomas testing suite.
- Evidence/source URL: https://github.com/confident-ai/deepeval
- Date found: 2026-06-26
- Confidence note: High confidence; mature general eval framework with strong regression-test ergonomics.

### 2026-06-26 - Agent skills OCI artifacts spec

- Repo URL: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- Repo name: ThomasVitale/agents-skills-oci-artifacts-spec
- Feature or ability Thomas should consider: Specification for packaging, distributing, signing, and tracking agent skills as OCI artifacts with manifest, config schemas, annotations, collections, lock files, and supply-chain security.
- Why it matters for Thomas: Thomas skills and task artifacts need portable packaging, provenance, signing, and dependency locking as the skill ecosystem grows.
- Integration surface guess: Skill artifact bundle schema, signed skill registry, provenance annotations, lock-file format, OCI registry distribution, and marketplace security gates.
- Evidence/source URL: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; early spec, but highly relevant to artifact bundle schemas and skill provenance.

### 2026-06-26 - Anthropic skills

- Repo URL: https://github.com/anthropics/skills
- Repo name: anthropics/skills
- Feature or ability Thomas should consider: Official collection of Claude Skills with reusable instructions, assets, and examples for packaging domain-specific agent capabilities.
- Why it matters for Thomas: Thomas needs a clear skill packaging convention that can include instructions, scripts, templates, and assets without turning every workflow into one-off prompt text.
- Integration surface guess: Skill directory schema, installer compatibility, marketplace import, skill review checklist, and examples for first-party Thomas skills.
- Evidence/source URL: https://github.com/anthropics/skills
- Date found: 2026-06-26
- Confidence note: High confidence; official source for a skill packaging pattern Thomas should track.

### 2026-06-26 - NVIDIA skills

- Repo URL: https://github.com/NVIDIA/skills
- Repo name: NVIDIA/skills
- Feature or ability Thomas should consider: NVIDIA-maintained agent skill collection with domain-specific reusable skill packages.
- Why it matters for Thomas: Thomas should compare skill repo layout, metadata, and distribution conventions across major vendors before freezing its own skill marketplace shape.
- Integration surface guess: Skill package comparison, metadata schema review, import pipeline, trust metadata, and skill quality gates.
- Evidence/source URL: https://github.com/NVIDIA/skills
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong vendor reference, with exact fit depending on package structure.

### 2026-06-26 - AWS Agent Toolkit

- Repo URL: https://github.com/aws/agent-toolkit-for-aws
- Repo name: aws/agent-toolkit-for-aws
- Feature or ability Thomas should consider: AWS-focused agent toolkit that packages curated skills, tools, and guidance for building agents on AWS.
- Why it matters for Thomas: Thomas can study how a platform vendor packages skills/tooling with cloud permissions, examples, and operational constraints.
- Integration surface guess: Skill/tool bundle schema, cloud tool trust metadata, permission documentation, marketplace import filters, and platform-specific skill adapters.
- Evidence/source URL: https://github.com/aws/agent-toolkit-for-aws
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful vendor packaging reference, even if AWS-specific pieces stay optional.

### 2026-06-26 - Softaworks agent-toolkit

- Repo URL: https://github.com/softaworks/agent-toolkit
- Repo name: softaworks/agent-toolkit
- Feature or ability Thomas should consider: Toolkit for authoring and distributing AI agent skills, tools, and reusable agent components.
- Why it matters for Thomas: Thomas needs authoring ergonomics for new skills so contributors can create testable, documented, portable skill packages.
- Integration surface guess: Skill authoring templates, local validation, component metadata, marketplace submission flow, and contract tests for skills.
- Evidence/source URL: https://github.com/softaworks/agent-toolkit
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising authoring pattern, with maturity needing inspection.

### 2026-06-26 - Agent skills marketplace

- Repo URL: https://github.com/DiversioTeam/agent-skills-marketplace
- Repo name: DiversioTeam/agent-skills-marketplace
- Feature or ability Thomas should consider: Marketplace-style repository for discovering, sharing, and organizing agent skills.
- Why it matters for Thomas: Thomas will need a marketplace UX and review queue for skills that is searchable, categorized, and safe to install.
- Integration surface guess: Skill marketplace catalog, submission metadata, search facets, review status, trust labels, and install history.
- Evidence/source URL: https://github.com/DiversioTeam/agent-skills-marketplace
- Date found: 2026-06-26
- Confidence note: Medium confidence; marketplace concept is relevant, but implementation depth should be reviewed.

### 2026-06-26 - VoltAgent awesome agent skills

- Repo URL: https://github.com/VoltAgent/awesome-agent-skills
- Repo name: VoltAgent/awesome-agent-skills
- Feature or ability Thomas should consider: Curated source map of agent skills and skill ecosystems across providers.
- Why it matters for Thomas: Thomas needs broad skill ecosystem awareness to avoid building a closed skill format without migration/import paths.
- Integration surface guess: Skill ecosystem source map, import candidate backlog, compatibility taxonomy, and marketplace seed catalog.
- Evidence/source URL: https://github.com/VoltAgent/awesome-agent-skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; catalog-style, useful for discovery rather than direct implementation.

### 2026-06-26 - Awesome Claude Skills

- Repo URL: https://github.com/ComposioHQ/awesome-claude-skills
- Repo name: ComposioHQ/awesome-claude-skills
- Feature or ability Thomas should consider: Curated collection of Claude skills and skill examples for different tools and workflows.
- Why it matters for Thomas: Thomas can mine common skill categories, metadata expectations, and install risks from the emerging Claude Skills ecosystem.
- Integration surface guess: Skill category taxonomy, marketplace seed entries, trust review checklist, skill import compatibility, and examples for Thomas documentation.
- Evidence/source URL: https://github.com/ComposioHQ/awesome-claude-skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; discovery-heavy, but relevant for skill marketplace planning.

### 2026-06-26 - Claude skills collection

- Repo URL: https://github.com/alirezarezvani/claude-skills
- Repo name: alirezarezvani/claude-skills
- Feature or ability Thomas should consider: Community collection of Claude-compatible skills with practical examples across workflows.
- Why it matters for Thomas: Community skill collections reveal real packaging patterns, naming conventions, and quality variance that Thomas should handle during import/review.
- Integration surface guess: Skill import parser, community quality checks, trust metadata defaults, compatibility warnings, and marketplace review queue.
- Evidence/source URL: https://github.com/alirezarezvani/claude-skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful as a community-skill sample set rather than a core dependency.

### 2026-06-26 - Agent Skills open standard

- Repo URL: https://github.com/agentskills/agentskills
- Repo name: agentskills/agentskills
- Feature or ability Thomas should consider: Open standard and reference tooling for packaging, discovering, and running agent skills across assistants and IDEs.
- Why it matters for Thomas: Thomas should avoid a one-off skill format if an ecosystem standard can provide import compatibility, metadata conventions, and portable installation.
- Integration surface guess: Skill package compatibility layer, marketplace metadata schema, import validation, trust-label propagation, and skill runtime adapters.
- Evidence/source URL: https://github.com/agentskills/agentskills
- Date found: 2026-06-26
- Confidence note: High confidence; directly targets interoperable agent skill packaging.

### 2026-06-26 - agent-skills-cli

- Repo URL: https://github.com/Karanjot786/agent-skills-cli
- Repo name: Karanjot786/agent-skills-cli
- Feature or ability Thomas should consider: CLI for creating, validating, and managing agent skills from the command line.
- Why it matters for Thomas: Thomas needs developer ergonomics for skill creation and local validation before skills enter the marketplace or worker prompts.
- Integration surface guess: Skill authoring CLI, validation command, package scaffolding, import compatibility tests, and contributor workflow docs.
- Evidence/source URL: https://github.com/Karanjot786/agent-skills-cli
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful workflow reference, with maturity and schema coverage needing review.

### 2026-06-26 - npm-agentskills

- Repo URL: https://github.com/onmax/npm-agentskills
- Repo name: onmax/npm-agentskills
- Feature or ability Thomas should consider: npm-oriented distribution path for agent skills.
- Why it matters for Thomas: Thomas may need to distribute or consume skills through common package managers, not only git URLs or internal registries.
- Integration surface guess: Skill package distribution, npm install workflow, semantic versioning, lock-file metadata, and supply-chain scanning.
- Evidence/source URL: https://github.com/onmax/npm-agentskills
- Date found: 2026-06-26
- Confidence note: Medium confidence; narrow but relevant to package-manager compatibility.

### 2026-06-26 - Addy Osmani agent-skills

- Repo URL: https://github.com/addyosmani/agent-skills
- Repo name: addyosmani/agent-skills
- Feature or ability Thomas should consider: Practical agent skill examples and reusable workflows for software-development agents.
- Why it matters for Thomas: Thomas should study high-signal skill examples for naming, scope boundaries, prompt assets, and developer workflow coverage.
- Integration surface guess: Skill example import, quality rubric, software-development skill templates, trust review, and documentation examples.
- Evidence/source URL: https://github.com/addyosmani/agent-skills
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; practical skill samples from a strong software-agent practitioner.

### 2026-06-26 - Web quality skills

- Repo URL: https://github.com/addyosmani/web-quality-skills
- Repo name: addyosmani/web-quality-skills
- Feature or ability Thomas should consider: Focused skill collection for web quality, performance, accessibility, and frontend engineering checks.
- Why it matters for Thomas: Thomas web/site workers need reusable skills with concrete quality gates instead of free-form review prompts.
- Integration surface guess: Frontend QA skill import, accessibility/performance skill templates, visual-proof workflow integration, and skill acceptance tests.
- Evidence/source URL: https://github.com/addyosmani/web-quality-skills
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful domain-specific skill pack pattern for Thomas web work.

### 2026-06-26 - Vercel skills

- Repo URL: https://github.com/vercel-labs/skills
- Repo name: vercel-labs/skills
- Feature or ability Thomas should consider: Skill collection from Vercel Labs oriented toward agent workflows and developer tasks.
- Why it matters for Thomas: Thomas should compare how a developer-platform team packages skills for repeatable agent use, especially for web and deployment workflows.
- Integration surface guess: Skill import compatibility, deployment/web skill templates, metadata comparison, and marketplace trust review.
- Evidence/source URL: https://github.com/vercel-labs/skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; relevant vendor skill set, with contents needing review before prioritization.

### 2026-06-26 - Microsoft skills

- Repo URL: https://github.com/microsoft/skills
- Repo name: microsoft/skills
- Feature or ability Thomas should consider: Microsoft skill collection for agent workflows and developer productivity.
- Why it matters for Thomas: Cross-vendor skill repositories help Thomas avoid tight coupling to one provider’s skill format and expose common metadata needs.
- Integration surface guess: Skill schema comparison, import compatibility, marketplace source trust, Microsoft ecosystem adapters, and skill quality checks.
- Evidence/source URL: https://github.com/microsoft/skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful if the repo structure is compatible with emerging agent-skill conventions.

### 2026-06-26 - Agent Skills registry CLI

- Repo URL: https://github.com/agentskill-sh/ags
- Repo name: agentskill-sh/ags
- Feature or ability Thomas should consider: CLI and registry tooling for discovering and installing agent skills.
- Why it matters for Thomas: Thomas needs a clean skill installation UX with search, versioning, trust metadata, and audit trails.
- Integration surface guess: Skill registry CLI comparison, install command UX, marketplace search, trust labels, and install audit logging.
- Evidence/source URL: https://github.com/agentskill-sh/ags
- Date found: 2026-06-26
- Confidence note: Medium confidence; potentially valuable registry UX reference, with ecosystem maturity to verify.

### 2026-06-26 - Tech Leads Club agent-skills

- Repo URL: https://github.com/tech-leads-club/agent-skills
- Repo name: tech-leads-club/agent-skills
- Feature or ability Thomas should consider: Curated agent-skill repository oriented around software engineering leadership and developer workflows.
- Why it matters for Thomas: Thomas should test skill import compatibility against multiple real-world skill repositories, including community-maintained workflow packs.
- Integration surface guess: Skill import compatibility tests, community skill quality rubric, trust-label defaults, marketplace moderation queue, and category mapping.
- Evidence/source URL: https://github.com/tech-leads-club/agent-skills
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful compatibility sample set, with implementation depth to inspect.

### 2026-06-26 - Trusted Agent Protocol

- Repo URL: https://github.com/visa/trusted-agent-protocol
- Repo name: visa/trusted-agent-protocol
- Feature or ability Thomas should consider: Protocol work for establishing trust, identity, and verification between agents and services.
- Why it matters for Thomas: Thomas needs a trust story for agent-to-tool and agent-to-agent interactions that goes beyond local thread names and implicit authority.
- Integration surface guess: Agent identity, trust labels, tool access policy, signed agent metadata, MCP/A2A trust comparison, and portal trust indicators.
- Evidence/source URL: https://github.com/visa/trusted-agent-protocol
- Date found: 2026-06-26
- Confidence note: High confidence as a trust-model reference; exact integration depends on protocol maturity and ecosystem uptake.

### 2026-06-26 - Sigstore cosign

- Repo URL: https://github.com/sigstore/cosign
- Repo name: sigstore/cosign
- Feature or ability Thomas should consider: Artifact signing and verification tooling for container images, blobs, attestations, and SBOMs.
- Why it matters for Thomas: Thomas skill bundles, marketplace artifacts, and generated deliverables need verifiable signatures before workers trust or install them.
- Integration surface guess: Signed skill publishing, artifact verification gate, marketplace trust label, release provenance, and CI signing workflow.
- Evidence/source URL: https://github.com/sigstore/cosign
- Date found: 2026-06-26
- Confidence note: High confidence; mature supply-chain signing foundation directly applicable to skill artifacts.

### 2026-06-26 - SLSA GitHub Generator

- Repo URL: https://github.com/slsa-framework/slsa-github-generator
- Repo name: slsa-framework/slsa-github-generator
- Feature or ability Thomas should consider: GitHub Actions generator for SLSA provenance attestations across build artifacts.
- Why it matters for Thomas: Thomas should attach build provenance to packaged skills and release artifacts so marketplace consumers can verify how they were built.
- Integration surface guess: Skill build provenance, CI attestations, release artifact verification, marketplace metadata ingestion, and trust-label generation.
- Evidence/source URL: https://github.com/slsa-framework/slsa-github-generator
- Date found: 2026-06-26
- Confidence note: High confidence; established provenance generator with direct CI integration value.

### 2026-06-26 - in-toto attestations

- Repo URL: https://github.com/in-toto/attestation
- Repo name: in-toto/attestation
- Feature or ability Thomas should consider: Attestation framework and predicate specifications for supply-chain metadata.
- Why it matters for Thomas: Thomas needs a standard way to represent provenance, test results, scans, and review decisions for skills and worker-generated artifacts.
- Integration surface guess: Skill provenance predicates, eval-result attestations, security scan metadata, review attestations, and signed work artifact bundles.
- Evidence/source URL: https://github.com/in-toto/attestation
- Date found: 2026-06-26
- Confidence note: High confidence; standards-oriented metadata layer for artifact trust.

### 2026-06-26 - Sigstore policy-controller

- Repo URL: https://github.com/sigstore/policy-controller
- Repo name: sigstore/policy-controller
- Feature or ability Thomas should consider: Kubernetes admission controller that verifies signatures and attestations before admitting artifacts.
- Why it matters for Thomas: Thomas can adapt the admission-control pattern for marketplace installs: skills should pass signature, provenance, and scan policies before activation.
- Integration surface guess: Skill install admission policy, trust policy engine, signature verification gate, provenance requirements, and marketplace moderation automation.
- Evidence/source URL: https://github.com/sigstore/policy-controller
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; Kubernetes-specific implementation, but policy pattern maps well to Thomas skill installs.

### 2026-06-26 - GUAC supply-chain graph

- Repo URL: https://github.com/guacsec/guac
- Repo name: guacsec/guac
- Feature or ability Thomas should consider: Graph for Understanding Artifact Composition that ingests SBOMs, attestations, vulnerabilities, and dependency relationships.
- Why it matters for Thomas: Thomas marketplace moderation needs a graph of skill dependencies, provenance, vulnerability state, and trusted source relationships.
- Integration surface guess: Skill dependency graph, vulnerability disclosure queue, provenance ingestion, marketplace risk scoring, and trust-label propagation.
- Evidence/source URL: https://github.com/guacsec/guac
- Date found: 2026-06-26
- Confidence note: High confidence; strong model for artifact trust graphs and dependency risk.

### 2026-06-26 - GUAC visualizer

- Repo URL: https://github.com/guacsec/guac-visualizer
- Repo name: guacsec/guac-visualizer
- Feature or ability Thomas should consider: Visual interface for exploring GUAC supply-chain artifact graphs.
- Why it matters for Thomas: Skill marketplace trust should be visible to operators, showing why a skill is trusted, risky, stale, or blocked.
- Integration surface guess: Trust graph UI, marketplace moderation dashboard, dependency risk visualization, vulnerability disclosure workflow, and provenance explorer.
- Evidence/source URL: https://github.com/guacsec/guac-visualizer
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; companion UI pattern for surfacing artifact trust metadata.

### 2026-06-26 - Microsoft identity-spiffe

- Repo URL: https://github.com/microsoft/identity-spiffe
- Repo name: microsoft/identity-spiffe
- Feature or ability Thomas should consider: Prototype for sidecar-enforced agent-to-agent authorization using Microsoft Entra Agent Identity, SPIFFE/SPIRE workload identity, and cross-cloud federation.
- Why it matters for Thomas: Thomas needs agent identity and authorization for worker-to-worker and worker-to-tool traffic, not just local thread names and implicit trust.
- Integration surface guess: Agent identity sidecar, workload identity federation, A2A trust policy, sidecar authorization checks, and portal trust indicators.
- Evidence/source URL: https://github.com/microsoft/identity-spiffe
- Date found: 2026-06-26
- Confidence note: High confidence; very close to Thomas agent identity and sidecar policy needs.

### 2026-06-26 - SPIRE workload identity

- Repo URL: https://github.com/spiffe/spire
- Repo name: spiffe/spire
- Feature or ability Thomas should consider: SPIFFE Runtime Environment for issuing and verifying workload identities across distributed systems.
- Why it matters for Thomas: Thomas can use SPIFFE/SPIRE patterns to give workers, tool servers, and sidecars verifiable identities independent of hostnames or API keys.
- Integration surface guess: Worker identity issuance, tool-server authentication, trust-domain model, workload attestation, and signed identity metadata.
- Evidence/source URL: https://github.com/spiffe/spire
- Date found: 2026-06-26
- Confidence note: High confidence; mature workload-identity foundation.

### 2026-06-26 - OpenFGA fine-grained authorization

- Repo URL: https://github.com/openfga/openfga
- Repo name: openfga/openfga
- Feature or ability Thomas should consider: Relationship-based authorization engine inspired by Google Zanzibar for fine-grained access decisions.
- Why it matters for Thomas: Thomas needs policy decisions around which agents can read, write, call tools, install skills, or act on behalf of a user.
- Integration surface guess: Agent/tool authorization graph, workboard permission model, skill install policy, portal access control, and explainable auth decisions.
- Evidence/source URL: https://github.com/openfga/openfga
- Date found: 2026-06-26
- Confidence note: High confidence; mature authorization engine with direct policy relevance.

### 2026-06-26 - OpenFGA MCP server

- Repo URL: https://github.com/evansims/openfga-mcp
- Repo name: evansims/openfga-mcp
- Feature or ability Thomas should consider: MCP server that lets AI agents design, query, and manage OpenFGA/Auth0 FGA authorization models.
- Why it matters for Thomas: Thomas could expose authorization modeling and audits through MCP so reviewer agents can reason about access-control changes before accepting them.
- Integration surface guess: MCP authorization tool, policy-model review, access-control simulation, permission-change audit, and agent-readable auth explanations.
- Evidence/source URL: https://github.com/evansims/openfga-mcp
- Date found: 2026-06-26
- Confidence note: High confidence; direct bridge between MCP agents and fine-grained authorization.

### 2026-06-26 - Cedar policy language

- Repo URL: https://github.com/cedar-policy/cedar
- Repo name: cedar-policy/cedar
- Feature or ability Thomas should consider: Policy language and authorization engine for defining and evaluating fine-grained access control.
- Why it matters for Thomas: Thomas needs readable, reviewable policy language for skill trust, tool calls, worker scopes, and prompt-time trust labels.
- Integration surface guess: Policy language comparison, skill install policy, trust-aware prompt assembly, worker action authorization, and policy test suite.
- Evidence/source URL: https://github.com/cedar-policy/cedar
- Date found: 2026-06-26
- Confidence note: High confidence; well-scoped policy language with strong fit for explicit authorization rules.

### 2026-06-26 - Verified agent identity skill

- Repo URL: https://github.com/BillionsNetwork/verified-agent-identity
- Repo name: BillionsNetwork/verified-agent-identity
- Feature or ability Thomas should consider: Decentralized identity skill for AI agents using DIDs, human-owner linking, attestations, and cryptographic proofs.
- Why it matters for Thomas: Thomas should track emerging Know Your Agent patterns so agent identity can be tied to provenance, ownership, payments, and authorization.
- Integration surface guess: Agent identity wallet, proof presentation, human-agent linkage, signed payment/request headers, and trust-label display.
- Evidence/source URL: https://github.com/BillionsNetwork/verified-agent-identity
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; directly agent-identity focused, with ecosystem maturity to verify.

### 2026-06-26 - ACA-Py digital trust agent

- Repo URL: https://github.com/openwallet-foundation/acapy
- Repo name: openwallet-foundation/acapy
- Feature or ability Thomas should consider: Aries Cloud Agent Python for decentralized identity, DIDComm, verifiable credentials, and wallet-backed trust workflows.
- Why it matters for Thomas: Agent identity wallets and verifiable credentials could give Thomas portable trust proofs for workers, skill publishers, and tool providers.
- Integration surface guess: Agent identity wallet, verifiable credential issuance, DIDComm trust channels, credential-backed skill publisher metadata, and trust policy experiments.
- Evidence/source URL: https://github.com/openwallet-foundation/acapy
- Date found: 2026-06-26
- Confidence note: High confidence as a mature digital identity agent framework.

### 2026-06-26 - Walt.id identity

- Repo URL: https://github.com/walt-id/waltid-identity
- Repo name: walt-id/waltid-identity
- Feature or ability Thomas should consider: Open-source identity and wallet toolkit for decentralized identifiers, verifiable credentials, and OpenID4VC workflows.
- Why it matters for Thomas: Thomas may need lightweight tooling to issue, verify, and present trust credentials for skills, agents, and work artifacts.
- Integration surface guess: Credential issuance, trust credential verification, skill publisher identity, agent wallet experiments, and portal trust badges.
- Evidence/source URL: https://github.com/walt-id/waltid-identity
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful identity toolkit with broader VC ecosystem support.

### 2026-06-26 - Generative Agent Protocol

- Repo URL: https://github.com/mikekelly/gap
- Repo name: mikekelly/gap
- Feature or ability Thomas should consider: Generative Agent Protocol reference that frames agents, users, and resources around delegated access and explicit authorization.
- Why it matters for Thomas: Thomas needs a clear delegated-access model when workers act for a user across tools, repos, credentials, and external services.
- Integration surface guess: Agent credential exchange, delegated authorization model, tool access grants, prompt-time policy explanations, and A2A/MCP protocol comparison.
- Evidence/source URL: https://github.com/mikekelly/gap
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; strong conceptual fit, with ecosystem adoption to verify.

### 2026-06-26 - agent-auth

- Repo URL: https://github.com/kanoniv/agent-auth
- Repo name: kanoniv/agent-auth
- Feature or ability Thomas should consider: Authentication and authorization patterns for AI agents, including delegated access workflows.
- Why it matters for Thomas: Thomas workers should not inherit broad user authority by default; they need scoped, auditable credentials and denial paths.
- Integration surface guess: Delegated token flow, worker credential vaulting, consent UI, access-scope prompts, and auth audit logs.
- Evidence/source URL: https://github.com/kanoniv/agent-auth
- Date found: 2026-06-26
- Confidence note: Medium confidence; directly relevant topic, but implementation maturity should be inspected.

### 2026-06-26 - Open Agent Auth

- Repo URL: https://github.com/alibaba/open-agent-auth
- Repo name: alibaba/open-agent-auth
- Feature or ability Thomas should consider: Open authorization framework for agent systems from Alibaba, focused on agent identity and access control.
- Why it matters for Thomas: Thomas should compare agent-specific authorization frameworks before designing worker credentials, tool consent, and service-to-service trust.
- Integration surface guess: Agent auth framework comparison, identity exchange, scoped tool permissions, service trust boundary, and prompt-time authorization summaries.
- Evidence/source URL: https://github.com/alibaba/open-agent-auth
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; useful agent-auth reference with vendor backing.

### 2026-06-26 - MCP GitHub OAuth

- Repo URL: https://github.com/conshus/mcp-github-oauth
- Repo name: conshus/mcp-github-oauth
- Feature or ability Thomas should consider: MCP server pattern for GitHub OAuth authentication and scoped repository access.
- Why it matters for Thomas: Thomas GitHub-related tools should use explicit OAuth scopes and user consent rather than broad personal tokens in agent contexts.
- Integration surface guess: MCP OAuth flow, GitHub scoped token handling, user consent UX, repo access audit, and tool permission narrowing.
- Evidence/source URL: https://github.com/conshus/mcp-github-oauth
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; narrow but directly relevant to GitHub tool access.

### 2026-06-26 - MCP OAuth proxy

- Repo URL: https://github.com/obot-platform/mcp-oauth-proxy
- Repo name: obot-platform/mcp-oauth-proxy
- Feature or ability Thomas should consider: OAuth proxy pattern for securing MCP servers and brokering authenticated tool access.
- Why it matters for Thomas: Thomas needs a reusable authorization layer between workers and MCP servers so every server does not implement trust differently.
- Integration surface guess: MCP auth proxy, tool-server gateway, token exchange, access policy enforcement, and audit logging.
- Evidence/source URL: https://github.com/obot-platform/mcp-oauth-proxy
- Date found: 2026-06-26
- Confidence note: High confidence; practical infrastructure pattern for remote MCP security.

### 2026-06-26 - OpenGAP

- Repo URL: https://github.com/open-gitagent/opengap
- Repo name: open-gitagent/opengap
- Feature or ability Thomas should consider: Open Git Agent Protocol work for coordinating repository-working agents.
- Why it matters for Thomas: Thomas is repo-working and multi-agent; protocol work around git-agent interactions can inform trust, handoff, and repo-scope boundaries.
- Integration surface guess: Repo-agent protocol comparison, worktree scope metadata, agent handoff records, git operation authorization, and worker prompt contracts.
- Evidence/source URL: https://github.com/open-gitagent/opengap
- Date found: 2026-06-26
- Confidence note: Medium confidence; promising repo-agent protocol direction, with maturity needing review.

### 2026-06-26 - Agent protocols legal research

- Repo URL: https://github.com/harvard-lil/agent-protocols
- Repo name: harvard-lil/agent-protocols
- Feature or ability Thomas should consider: Research and prototype materials around agent protocols for safe, auditable, accountable agent interactions.
- Why it matters for Thomas: Thomas should preserve protocol-level accountability when workers exchange tasks, credentials, evidence, and decisions.
- Integration surface guess: Agent protocol source map, accountability metadata, audit log schema, consent records, and trust-aware handoff design.
- Evidence/source URL: https://github.com/harvard-lil/agent-protocols
- Date found: 2026-06-26
- Confidence note: Medium confidence; research-heavy, but useful for protocol governance thinking.

### 2026-06-26 - JamJet policy layer

- Repo URL: https://github.com/jamjet-labs/jamjet
- Repo name: jamjet-labs/jamjet
- Feature or ability Thomas should consider: Policy and safety layer for AI agents focused on governing agent actions and tool use.
- Why it matters for Thomas: Thomas needs a runtime policy surface that can explain why a worker action is allowed, denied, or requires approval.
- Integration surface guess: Runtime policy layer, prompt-time policy explanations, tool-call guardrails, approval workflow, and action audit trail.
- Evidence/source URL: https://github.com/jamjet-labs/jamjet
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; directly relevant policy-layer shape, with implementation depth to verify.

### 2026-06-26 - Enforra local-first tool-call policy enforcement

- Repo URL: https://github.com/enforra/enforra
- Repo name: enforra/enforra
- Feature or ability Thomas should consider: Runtime policy checks before agent tool callbacks execute, with decisions such as allow, block, require approval, and log-only plus local audit JSONL output.
- Why it matters for Thomas: Thomas needs real enforcement in front of high-impact worker actions, not just prompt instructions. Enforra is a compact reference for making tool approval policy deterministic and auditable at the execution boundary.
- Integration surface guess: Tool execution wrappers in `thomas/agent/`, workboard claim/commit gates, approval UX, and run audit logging.
- Evidence/source URL: https://github.com/enforra/enforra
- Date found: 2026-06-26
- Confidence note: High confidence for concept fit; repo is small but recently active and directly framed around agent tool-call governance.

### 2026-06-26 - OAuth MCP Proxy for Go server auth

- Repo URL: https://github.com/tuannvm/oauth-mcp-proxy
- Repo name: tuannvm/oauth-mcp-proxy
- Feature or ability Thomas should consider: OAuth 2.1 authentication library for Go MCP servers, with token validation/caching and adapters for multiple MCP SDKs.
- Why it matters for Thomas: Thomas will likely need to expose some local or hosted tools through MCP-like boundaries. This repo is useful for studying where OAuth enforcement belongs so tool servers do not each reinvent auth.
- Integration surface guess: Future MCP server/gateway work, tool adapter auth middleware, and token-validation test fixtures.
- Evidence/source URL: https://github.com/tuannvm/oauth-mcp-proxy
- Date found: 2026-06-26
- Confidence note: Medium confidence; implementation is language-specific, but the auth-placement pattern is portable.

### 2026-06-26 - AthenZ MCP OAuth Proxy with enterprise policy

- Repo URL: https://github.com/AthenZ/mcp-oauth-proxy
- Repo name: AthenZ/mcp-oauth-proxy
- Feature or ability Thomas should consider: OAuth 2.1/OIDC authorization proxy for MCP and A2A use cases with multiple identity providers, AthenZ fine-grained authorization, encrypted token storage, and mTLS support.
- Why it matters for Thomas: Thomas will need clean trust-domain boundaries if workers access enterprise systems. This is a concrete reference for combining identity provider login, policy decisions, machine auth, and token storage around agent tools.
- Integration surface guess: Hosted Thomas portal auth, future MCP/A2A gateway, secret vault boundaries, and policy-denial audit trails.
- Evidence/source URL: https://github.com/AthenZ/mcp-oauth-proxy
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; low-star but current and backed by a mature authorization-system ecosystem.

### 2026-06-26 - Babs MCP Auth Proxy for OIDC bridge

- Repo URL: https://github.com/babs/mcp-auth-proxy
- Repo name: babs/mcp-auth-proxy
- Feature or ability Thomas should consider: Stateless OAuth 2.1 authorization-server bridge that fronts private MCP servers while delegating identity to an existing OIDC provider.
- Why it matters for Thomas: It shows a low-friction path for protecting private MCP tools without rewriting every server. Thomas could adapt the bridge shape for local-tool sharing and user-scoped worker access.
- Integration surface guess: MCP proxy/gateway, local worker tool publication, auth/session middleware, and audit-defensible token exchange.
- Evidence/source URL: https://github.com/babs/mcp-auth-proxy
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; focused implementation with current activity and clear security posture.

### 2026-06-26 - Qred MCP Proxy with OAuth sidecar

- Repo URL: https://github.com/qred/qred-mcp-proxy
- Repo name: qred/qred-mcp-proxy
- Feature or ability Thomas should consider: Enterprise MCP proxy pattern with OAuth 2.1 sidecar, Google Workspace integration, one endpoint for multiple backend services, and AWS CDK deployment.
- Why it matters for Thomas: Thomas has repeated pressure to make worker/tool access manageable for non-technical users. A single managed endpoint plus standardized client config is a useful UX and operations model.
- Integration surface guess: Hosted MCP gateway deployment, portal-managed tool catalog, organization auth settings, and deployment runbooks.
- Evidence/source URL: https://github.com/qred/qred-mcp-proxy
- Date found: 2026-06-26
- Confidence note: Medium confidence; useful architecture reference, with adopter-maintained security caveats to review before copying.

### 2026-06-26 - Predicate Systems secure finance multi-agent demo

- Repo URL: https://github.com/PredicateSystems/account-payable-multi-ai-agent-demo
- Repo name: PredicateSystems/account-payable-multi-ai-agent-demo
- Feature or ability Thomas should consider: Multi-agent finance workflow with local LLMs, authorization, deterministic verification, silent-failure detection, and policy-blocked payment release.
- Why it matters for Thomas: Thomas needs examples where agent action is allowed only after verifiable preconditions pass. This demo maps well to workboard/commit gates and high-impact task blockers.
- Integration surface guess: Workboard gate explanations, run verification receipts, local-model workflow tests, and policy-block evidence in task timelines.
- Evidence/source URL: https://github.com/PredicateSystems/account-payable-multi-ai-agent-demo
- Date found: 2026-06-26
- Confidence note: Medium confidence; demo-sized repository, but the blocked-action and deterministic-verification pattern is highly relevant.

### 2026-06-26 - Smartnose deterministic policy enforcer demo

- Repo URL: https://github.com/smartnose/policy-enforcer
- Repo name: smartnose/policy-enforcer
- Feature or ability Thomas should consider: LangChain ReAct agent demo with deterministic business-rule enforcement, explainable failures, state tracking, and comparison of prompted versus external policy checks.
- Why it matters for Thomas: It reinforces that prompt rules are not enough and that policy explanations should be available when a tool/action is blocked. Thomas could use similar simple demos to test denial UX.
- Integration surface guess: Tool policy tests, approval-denial explanation templates, rule-engine adapters, and agent safety docs.
- Evidence/source URL: https://github.com/smartnose/policy-enforcer
- Date found: 2026-06-26
- Confidence note: Medium confidence; small demo, but directly aligned with deterministic policy checks and explainable failure behavior.

### 2026-06-26 - Sigbit MCP Auth Proxy for client-compatible OAuth

- Repo URL: https://github.com/sigbit/mcp-auth-proxy
- Repo name: sigbit/mcp-auth-proxy
- Feature or ability Thomas should consider: Drop-in OAuth 2.1/OIDC gateway for MCP servers, supporting multiple IdPs, user matching rules, local-to-HTTP transport conversion, and compatibility testing across major MCP clients.
- Why it matters for Thomas: Client quirks are a practical risk for any Thomas tool gateway. Sigbit's compatibility-focused proxy is a strong reference for making auth work across Claude, ChatGPT, Copilot, Cursor, and local MCP tools.
- Integration surface guess: MCP gateway compatibility matrix, auth middleware, user allowlist policy, and local tool publication.
- Evidence/source URL: https://github.com/sigbit/mcp-auth-proxy
- Date found: 2026-06-26
- Confidence note: High confidence; active, well-scoped, and directly relevant to MCP auth UX.

### 2026-06-26 - Nerve self-hosted agent runtime

- Repo URL: https://github.com/ClickHouse/nerve
- Repo name: ClickHouse/nerve
- Feature or ability Thomas should consider: Self-hosted AI agent runtime for personal assistants and autonomous workers, with documented setup, architecture, configuration, worker guide, and API reference.
- Why it matters for Thomas: Thomas is moving toward native visible worker orchestration instead of hidden external loops. Nerve is a current reference for packaging a self-hosted worker runtime with configuration and operational docs.
- Integration surface guess: Native orchestration service, worker lifecycle config, portal task views, and hosted/local deployment layout.
- Evidence/source URL: https://github.com/ClickHouse/nerve
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; young but active and directly aligned with self-hosted autonomous worker runtime design.

### 2026-06-26 - Proxilion runtime security SDK

- Repo URL: https://github.com/clay-good/proxilion-sdk
- Repo name: clay-good/proxilion-sdk
- Feature or ability Thomas should consider: In-application runtime security guard layer for LLM apps that enforces rules at every tool call against prompt injection, data leakage, authorization attacks, and rogue agent behavior.
- Why it matters for Thomas: Thomas needs enforcement points inside the agent/tool path, not only preflight scans. Proxilion is a reference for lightweight deterministic checks around live tool use.
- Integration surface guess: Agent tool middleware, prompt-injection gates, data egress checks, and run audit events.
- Evidence/source URL: https://github.com/clay-good/proxilion-sdk
- Date found: 2026-06-26
- Confidence note: Medium confidence; small repo with low adoption, but a sharply relevant runtime-security model.

### 2026-06-26 - Mandate runtime authority enforcement

- Repo URL: https://github.com/kashaf12/mandate
- Repo name: kashaf12/mandate
- Feature or ability Thomas should consider: Runtime enforcement layer for AI agent authority that intercepts LLM and tool calls, evaluates them against policies, and blocks unauthorized actions.
- Why it matters for Thomas: Thomas workers make repo, filesystem, and coordination changes where authority must be explicit. Mandate's "mechanically enforceable authority" framing is a useful design target for claim scopes and tool permissions.
- Integration surface guess: Workboard claim scope enforcement, tool-call authorization middleware, blocked-action receipts, and policy simulation tests.
- Evidence/source URL: https://github.com/kashaf12/mandate
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; recently active and maps tightly to delegated-agent authority control.

### 2026-06-26 - Medical pre-authorization multi-agent decision audit

- Repo URL: https://github.com/aniket-work/medical-preauth-agent
- Repo name: aniket-work/medical-preauth-agent
- Feature or ability Thomas should consider: Multi-agent prior-authorization workflow with policy analyst, clinical reviewer, decision engine, confidence score, rationale, and explainable audit trail.
- Why it matters for Thomas: Even though the domain is medical, the structure is useful: parse policy, extract evidence, decide, and explain denial/approval. Thomas can adapt that pattern for workboard gate decisions and policy-denial UX.
- Integration surface guess: Gate rationale generation, workboard verification receipts, policy-document parsing, and denial explanation templates.
- Evidence/source URL: https://github.com/aniket-work/medical-preauth-agent
- Date found: 2026-06-26
- Confidence note: Medium confidence; domain demo, but the auditable decision workflow is directly transferable.

### 2026-06-26 - OpenFGA Studio authorization modeling UI

- Repo URL: https://github.com/prakashm88/openfga-studio
- Repo name: prakashm88/openfga-studio
- Feature or ability Thomas should consider: Open-source authorization modeling interface for OpenFGA/ReBAC models, intended for deployable or air-gapped experimentation beyond hosted playground limits.
- Why it matters for Thomas: Thomas needs policy simulation UX before enforcing complex worker/tool permissions. A local authorization modeling UI could help agents and humans understand why a claim, tool, or secret access is allowed or denied.
- Integration surface guess: Policy playground, claim-scope simulator, permission graph editor, and local/offline admin tooling.
- Evidence/source URL: https://github.com/prakashm88/openfga-studio
- Date found: 2026-06-26
- Confidence note: Medium confidence; not agent-specific, but highly relevant to local authorization simulation and explanation.

### 2026-06-26 - SpiceDB fine-grained authorization database

- Repo URL: https://github.com/authzed/spicedb
- Repo name: authzed/spicedb
- Feature or ability Thomas should consider: Zanzibar-inspired fine-grained authorization database for scalable relationship-based permissions.
- Why it matters for Thomas: If Thomas evolves multi-user, multi-worker, multi-repo access control, hand-rolled role flags will not be enough. SpiceDB is a mature reference for modeling relationships such as user, worker, repo, claim, tool, secret, and approval.
- Integration surface guess: Authorization backend, workspace/repo permission graph, claim-to-tool policy checks, and audit queries.
- Evidence/source URL: https://github.com/authzed/spicedb
- Date found: 2026-06-26
- Confidence note: High confidence for authorization infrastructure quality; agent-specific fit would need a thin Thomas policy layer.

### 2026-06-26 - AgentReady agentic web readiness scanner

- Repo URL: https://github.com/swarmclawai/agentready
- Repo name: swarmclawai/agentready
- Feature or ability Thomas should consider: Readiness scanner for websites, APIs, marketplaces, MCP servers, and agent services to check whether agents can discover, authenticate, transact, request refunds, and interact safely.
- Why it matters for Thomas: Thomas could use an analogous scanner to evaluate whether its own portal, docs, APIs, and MCP endpoints are agent-ready before exposing them to external agents or marketplaces.
- Integration surface guess: Release preflight, website/API checks, MCP endpoint audit, documentation quality gates, and marketplace readiness reports.
- Evidence/source URL: https://github.com/swarmclawai/agentready
- Date found: 2026-06-26
- Confidence note: Medium confidence; early project, but the checklist/scanner concept is timely and useful for Thomas deployment quality.

### 2026-06-26 - AgenticMail enterprise agent workforce platform

- Repo URL: https://github.com/agenticmail/enterprise
- Repo name: agenticmail/enterprise
- Feature or ability Thomas should consider: Enterprise agent workforce platform with per-agent identity, email, calendar, browser, tools, memory, compliance, multi-tenant isolation, and GitHub issue/PR agent integration.
- Why it matters for Thomas: Thomas needs a coherent model for agent identities, communication channels, and compliance when workers become first-class participants. This repo is useful as a product-shape reference for named agents with tools and communications.
- Integration surface guess: Worker identity model, portal-managed agent accounts, issue/PR responder workflows, compliance logs, and multi-tenant separation.
- Evidence/source URL: https://github.com/agenticmail/enterprise
- Date found: 2026-06-26
- Confidence note: Medium confidence; product-platform repo, but current and directly relevant to agent identity/workforce UX.

### 2026-06-26 - AI Agent Workforce teams-as-code

- Repo URL: https://github.com/muhamadto/ai-agent-workforce
- Repo name: muhamadto/ai-agent-workforce
- Feature or ability Thomas should consider: Ansible-based deployment and management of multi-model AI agent teams with pluggable integrations, task orchestration, workspace management, and model-specific agent configurations.
- Why it matters for Thomas: Thomas is trying to make worker setup repeatable and visible. Treating agent teams as infrastructure-as-code is a useful reference for reproducible worker environments instead of one-off local thread setup.
- Integration surface guess: Native worker provisioning, model-specific worker profiles, workspace setup scripts, and portal-visible team templates.
- Evidence/source URL: https://github.com/muhamadto/ai-agent-workforce
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; young repo but active and directly aligned with deployable agent teams.

### 2026-06-26 - YokeBot AI agent workforce workspace

- Repo URL: https://github.com/yokebots/yokebot
- Repo name: yokebots/yokebot
- Feature or ability Thomas should consider: Agent workforce workspace with pre-built agents, skills, multiple models, browser automation, voice meetings, production workflows, shared context, goals, calendar, and real-time collaboration.
- Why it matters for Thomas: Thomas needs a coherent first-screen operating model for multiple visible workers, shared context, and goals. YokeBot is a concrete product-shape reference for organizing agent teams as a workspace rather than as isolated chats.
- Integration surface guess: Thomas portal worker dashboard, shared task context, calendar/goal surfaces, skill catalog, and browser-automation worker lanes.
- Evidence/source URL: https://github.com/yokebots/yokebot
- Date found: 2026-06-26
- Confidence note: Medium confidence; low-star but current and feature-aligned with multi-worker UX.

### 2026-06-26 - AI Agents governed software-development system

- Repo URL: https://github.com/rjmurillo/ai-agents
- Repo name: rjmurillo/ai-agents
- Feature or ability Thomas should consider: Multi-agent software-development system with session protocol, review gates, ADR-guided behavior, AI issue triage, AI PR quality gate, spec validation, and marketplace packaging for Claude Code/Copilot CLI.
- Why it matters for Thomas: This maps closely to Thomas' own need for reviewable software work, not just generic agent orchestration. The session protocol and gate-heavy CI workflows are good references for enforcing agent behavior around real repos.
- Integration surface guess: Workboard protocol, PR/issue triage workers, spec-to-implementation validation, plugin/skill packaging, and review gate automation.
- Evidence/source URL: https://github.com/rjmurillo/ai-agents
- Date found: 2026-06-26
- Confidence note: High confidence for fit; active, software-development-specific, and governance-oriented.

### 2026-06-26 - SemanticDiff graph-based code review

- Repo URL: https://github.com/wieslawsoltes/SemanticDiff
- Repo name: wieslawsoltes/SemanticDiff
- Feature or ability Thomas should consider: Desktop Git diff explorer that turns repository changes into an interactive semantic graph with syntax/semantic analysis, navigation state, and GitHub/GitLab review workflows.
- Why it matters for Thomas: Thomas workers often produce patches that need fast human/agent review. A graph-based semantic diff can help reviewers understand blast radius and code relationships better than flat patches.
- Integration surface guess: Portal diff viewer, review workspace, code-change graph, PR discussion sync, and worker-output inspection.
- Evidence/source URL: https://github.com/wieslawsoltes/SemanticDiff
- Date found: 2026-06-26
- Confidence note: Medium confidence; not an agent repo, but highly relevant to agent-produced code review UX.

### 2026-06-26 - Diffity agent-agnostic diff review

- Repo URL: https://github.com/nilbuild/diffity
- Repo name: nilbuild/diffity
- Feature or ability Thomas should consider: Agent-agnostic local diff viewer and code review tool that works with Claude Code, Cursor, Codex, and other AI coding agents, including AI review comments, guided code tours, and local PR review.
- Why it matters for Thomas: Thomas needs a clean way to inspect worker changes, ask an agent to review them, and push comments back to GitHub. Diffity is a strong reference for making review a first-class local workflow.
- Integration surface guess: Worker patch review UI, local PR review bridge, guided repo tours, AI reviewer comment capture, and task evidence pages.
- Evidence/source URL: https://github.com/nilbuild/diffity
- Date found: 2026-06-26
- Confidence note: High confidence; active, agent-tool-friendly, and directly relevant to coding worker review ergonomics.

### 2026-06-26 - Browser-only AI Agent Builder

- Repo URL: https://github.com/david-spies/ai-agent-builder
- Repo name: david-spies/ai-agent-builder
- Feature or ability Thomas should consider: Backend-less single-file browser app for authoring, configuring, packaging, and auditing AI agents, with offline operation, no telemetry, guardrails, red-team probes, audit trail, agentskills compatibility, and MCP support.
- Why it matters for Thomas: Thomas could benefit from a local/offline agent authoring surface for skills, worker profiles, and policies. The single-file/no-backend approach is also useful for safe enterprise demos and portable review artifacts.
- Integration surface guess: Skill/profile builder, offline policy editor, red-team checklist, audit-trail export, and agent package preview.
- Evidence/source URL: https://github.com/david-spies/ai-agent-builder
- Date found: 2026-06-26
- Confidence note: Medium confidence; small repo, but the offline authoring and packaging model is directly useful.

### 2026-06-26 - Agent Teams AI desktop multi-team workspace

- Repo URL: https://github.com/777genius/agent-teams-ai
- Repo name: 777genius/agent-teams-ai
- Feature or ability Thomas should consider: Desktop app for multiple AI agent teams with autonomous task handling, inter-agent messaging, work review, Kanban board supervision, Codex/Claude/OpenCode provider support, and many-model routing.
- Why it matters for Thomas: This is close to the UX Thomas wants: the human gives high-level commands and watches teams execute/review work through a board. It is worth studying for portal layout, team boundaries, and review loops.
- Integration surface guess: Native orchestration portal, team Kanban, inter-agent message lanes, provider routing, supervisor controls, and review handoff UX.
- Evidence/source URL: https://github.com/777genius/agent-teams-ai
- Date found: 2026-06-26
- Confidence note: High confidence for UX relevance; licensing and implementation quality need separate review before adoption.

### 2026-06-26 - Oktsec local agent action security layer

- Repo URL: https://github.com/oktsec/oktsec
- Repo name: oktsec/oktsec
- Feature or ability Thomas should consider: Local runtime security layer between AI agents and their tool surfaces, applying policy before MCP calls, shell/file/browser actions, agent-to-agent messages, and outbound requests execute.
- Why it matters for Thomas: Thomas needs a central mediation point for high-risk actions across tools and worker lanes. Oktsec is a current reference for one local binary that signs, inspects, logs, and blocks actions before they become production changes.
- Integration surface guess: Tool-call proxy, shell/file/browser action middleware, inter-agent message gate, and audit log collector.
- Evidence/source URL: https://github.com/oktsec/oktsec
- Date found: 2026-06-26
- Confidence note: High confidence; recently active and directly aligned with local, policy-before-action agent security.

### 2026-06-26 - Agent Audit static scanner for LLM agents

- Repo URL: https://github.com/HeadyZhang/agent-audit
- Repo name: HeadyZhang/agent-audit
- Feature or ability Thomas should consider: Static security scanner for LLM agent code, prompt injection paths, MCP configuration, taint analysis, and rules mapped to OWASP Agentic Top 10.
- Why it matters for Thomas: Thomas has a growing tool/plugin/agent surface where security review cannot stay manual. A scanner like this could become a preflight gate before marketplace publishing, worker enablement, or release.
- Integration surface guess: Release preflight, plugin/skill marketplace scanner, MCP config audit, CI security checks, and workboard risk reports.
- Evidence/source URL: https://github.com/HeadyZhang/agent-audit
- Date found: 2026-06-26
- Confidence note: High confidence; active, well-scoped, and directly relevant to agent-specific security scanning.

### 2026-06-26 - DashClaw governance runtime

- Repo URL: https://github.com/ucsandman/DashClaw
- Repo name: ucsandman/DashClaw
- Feature or ability Thomas should consider: Governance layer that evaluates policy on every risky agent action, routes required human approvals, records verifiable evidence, and tracks terminal outcomes to avoid silent double execution.
- Why it matters for Thomas: Thomas already depends on claims, approvals, and commit gates. DashClaw's decision-trail and terminal-outcome concepts are useful for preventing retried workers from repeating irreversible actions.
- Integration surface guess: Approval router, workboard action receipts, risky-action middleware, retry/idempotency guard, and audit-ready run timeline.
- Evidence/source URL: https://github.com/ucsandman/DashClaw
- Date found: 2026-06-26
- Confidence note: High confidence; strong conceptual fit and explicitly supports Codex/Claude-style agents.

### 2026-06-26 - Agent-MCP collaboration knowledge graph

- Repo URL: https://github.com/rinadelph/Agent-MCP
- Repo name: rinadelph/Agent-MCP
- Feature or ability Thomas should consider: MCP-based multi-agent collaboration protocol for coordinated software development, shared context, intelligent task management, and real-time visualization of agent work.
- Why it matters for Thomas: Thomas needs multiple agents to collaborate without losing context or stepping on each other's work. The "living knowledge graph" model is a useful reference for shared state and visibility.
- Integration surface guess: Native worker graph, shared task context, inter-agent coordination state, live visualization, and MCP collaboration adapters.
- Evidence/source URL: https://github.com/rinadelph/Agent-MCP
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; popular and directly targeted at multi-agent software development, though docs maturity should be reviewed.

### 2026-06-26 - LibreChat self-hosted agent and MCP portal

- Repo URL: https://github.com/danny-avila/LibreChat
- Repo name: danny-avila/LibreChat
- Feature or ability Thomas should consider: Self-hosted multi-provider chat/agent platform with agents, MCP, skills, artifacts, message search, code interpreter, OpenAPI actions, secure multi-user auth, presets, and model switching.
- Why it matters for Thomas: Thomas' portal could learn from LibreChat's mature handling of agents, skills, model routing, auth, artifacts, and conversation search as one user-facing product surface.
- Integration surface guess: Portal UX, model/provider switching, skill/MCP integration, artifacts, auth/session design, and searchable worker transcripts.
- Evidence/source URL: https://github.com/danny-avila/LibreChat
- Date found: 2026-06-26
- Confidence note: High confidence for product-surface reference; broad app, so Thomas should mine patterns rather than adopt wholesale.

### 2026-06-26 - HUMAN verified AI agent signatures

- Repo URL: https://github.com/HumanSecurity/human-verified-ai-agent
- Repo name: HumanSecurity/human-verified-ai-agent
- Feature or ability Thomas should consider: A2A multi-agent system using HTTP Message Signatures to authenticate agent requests to external services without relying only on API keys or user-agent strings.
- Why it matters for Thomas: If Thomas workers interact with external services, signed agent requests and verifiable identity are stronger than opaque bearer-token calls. This is a practical standards-backed demo for agent identity on the wire.
- Integration surface guess: External service connector auth, A2A gateway, signed webhook requests, worker identity keys, and request verification logs.
- Evidence/source URL: https://github.com/HumanSecurity/human-verified-ai-agent
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; demo repo, but the RFC-backed signing pattern is important for trusted agent identity.

### 2026-06-26 - Room peer-to-peer signed agent transcripts

- Repo URL: https://github.com/agree-able/room
- Repo name: agree-able/room
- Feature or ability Thomas should consider: Lightweight peer-to-peer bot communication protocol with identity verification and complete signed chat transcripts.
- Why it matters for Thomas: Thomas' inter-worker lanes need durable evidence of who said what and when. Signed transcripts are a useful primitive for cross-agent accountability and replay.
- Integration surface guess: Inter-agent message bus, workboard lane audit, signed transcript export, peer worker identity, and offline coordination tests.
- Evidence/source URL: https://github.com/agree-able/room
- Date found: 2026-06-26
- Confidence note: Medium confidence; small and older, but the signed-transcript concept is directly useful.

### 2026-06-26 - agentUniverse enterprise multi-agent patterns

- Repo URL: https://github.com/agentuniverse-ai/agentUniverse
- Repo name: agentuniverse-ai/agentUniverse
- Feature or ability Thomas should consider: Multi-agent framework with reusable collaborative pattern components and domain-expert agent construction, originating from real-world financial business practices.
- Why it matters for Thomas: Thomas should collect proven collaboration patterns, not just low-level tooling. agentUniverse is a mature reference for pattern factories and domain-experience integration in multi-agent systems.
- Integration surface guess: Multi-agent pattern registry, domain-specific worker templates, workflow orchestration primitives, and enterprise scenario examples.
- Evidence/source URL: https://github.com/agentuniverse-ai/agentUniverse
- Date found: 2026-06-26
- Confidence note: High confidence for pattern-library value; integration details require deeper architecture review.

### 2026-06-26 - Parley recovery-first coordination state

- Repo URL: https://github.com/nkuhanas/Parley
- Repo name: nkuhanas/Parley
- Feature or ability Thomas should consider: Durable coordination state for long-running agents, including identity, obligations, plans, artifacts, effects, guidance, recovery, and plan lifecycle tools.
- Why it matters for Thomas: Thomas loses leverage when worker continuity depends on chat history alone. Parley's explicit obligations/effects model is relevant to resumable tasks, claim recovery, and post-crash auditability.
- Integration surface guess: Worker state store, claim recovery, obligation tracking, artifact/effect ledger, and resume/replay tooling.
- Evidence/source URL: https://github.com/nkuhanas/Parley
- Date found: 2026-06-26
- Confidence note: Medium confidence; early project, but the recovery-first state model targets a real Thomas gap.

### 2026-06-26 - Agent Replay local trace time-travel debugger

- Repo URL: https://github.com/clay-good/agent-replay
- Repo name: clay-good/agent-replay
- Feature or ability Thomas should consider: Local SQLite-backed CLI for replaying agent execution traces, diffing behavioral changes, forking runs, evaluating traces, applying guard policies, and exporting golden regression datasets.
- Why it matters for Thomas: Thomas workers need a way to explain failures and turn known-good or known-bad runs into repeatable tests. Agent Replay's trace diff/fork/golden export workflow maps directly to worker regression and postmortem loops.
- Integration surface guess: Worker trace store, replay CLI, run diff viewer, guardrail policy checks, and export of Thomas task traces into regression fixtures.
- Evidence/source URL: https://github.com/clay-good/agent-replay
- Date found: 2026-06-26
- Confidence note: High confidence for workflow fit; small repo but unusually concrete and local-first.

### 2026-06-26 - Agent VCR editable execution replay

- Repo URL: https://github.com/ixchio/agent-vcr
- Repo name: ixchio/agent-vcr
- Feature or ability Thomas should consider: Time-travel debugging for AI agents that can replay, edit, and resume executions without rerunning the whole agent flow.
- Why it matters for Thomas: Thomas often needs to debug long-running delegated work where repeating the whole run is expensive or destructive. VCR-style editable replay could support safer fix testing from the exact failing step.
- Integration surface guess: Run checkpoint store, partial replay/resume, failure reproduction harness, and worker timeline debugger.
- Evidence/source URL: https://github.com/ixchio/agent-vcr
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; focused concept with direct value for long-running worker debugging.

### 2026-06-26 - AgentHER hindsight experience replay

- Repo URL: https://github.com/alphadl/AgentHER
- Repo name: alphadl/AgentHER
- Feature or ability Thomas should consider: Hindsight Experience Replay approach for LLM agents, using failed trajectories as learning/evaluation material by relabeling or reusing experience after the fact.
- Why it matters for Thomas: Thomas could mine failed worker runs into better prompts, policies, and regression cases instead of treating them as dead logs. Hindsight replay is a useful research direction for self-improvement without blindly promoting fixes.
- Integration surface guess: Evolve-loop eval corpus, failed-run mining, trajectory relabeling, regression generation, and postmortem-to-test workflows.
- Evidence/source URL: https://github.com/alphadl/AgentHER
- Date found: 2026-06-26
- Confidence note: Medium confidence; more research-oriented than product-ready, but relevant to self-improvement and failure reuse.

### 2026-06-26 - AgentLens MCP-native agent DevTools

- Repo URL: https://github.com/ModernOps888/agentlens
- Repo name: ModernOps888/agentlens
- Feature or ability Thomas should consider: MCP-native "Chrome DevTools for AI agents" with time-travel debugging, cost tracking, anomaly detection, and multi-agent workflow visibility.
- Why it matters for Thomas: Thomas needs an operator-grade view of agent runs, not only transcript text. AgentLens is a useful product reference for live debug panels, cost anomalies, and agent workflow inspection.
- Integration surface guess: Native orchestration dashboard, MCP trace adapter, cost telemetry, anomaly alerts, and multi-agent timeline view.
- Evidence/source URL: https://github.com/ModernOps888/agentlens
- Date found: 2026-06-26
- Confidence note: Medium confidence; early project, but the MCP-native DevTools framing fits Thomas' portal direction.

### 2026-06-26 - TraceLens LangGraph replay debugger

- Repo URL: https://github.com/certainly-param/tracelens
- Repo name: certainly-param/tracelens
- Feature or ability Thomas should consider: Visual debugger and replay engine for LangGraph workflows, with real-time monitoring, time-travel debugging, and interactive graph visualization.
- Why it matters for Thomas: Even if Thomas does not use LangGraph directly, the visual graph/replay pairing is a strong reference for showing where a worker run branched, stalled, or failed.
- Integration surface guess: Worker graph visualization, orchestration replay UI, checkpoint timeline, and trace-to-graph adapter.
- Evidence/source URL: https://github.com/certainly-param/tracelens
- Date found: 2026-06-26
- Confidence note: Medium confidence; low adoption, but the UX target is directly applicable.

### 2026-06-26 - AgentProbe cassette regression safety net

- Repo URL: https://github.com/cornhusk39/agentprobe
- Repo name: cornhusk39/agentprobe
- Feature or ability Thomas should consider: Regression safety net for LLM agents that records runs as cassettes, replays deterministically in CI, scores deterministic assertions plus LLM judge results, and fails builds on quality/cost/latency regression.
- Why it matters for Thomas: Thomas needs to convert real worker runs into CI checks. AgentProbe's cassette and baseline regression model is a practical reference for preventing agent behavior drift after prompt, model, or tool changes.
- Integration surface guess: CI regression harness, worker cassette format, quality/cost/latency baselines, LLM-judge gate, and release preflight.
- Evidence/source URL: https://github.com/cornhusk39/agentprobe
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; small repo but a very tight match for trace-to-regression workflows.

### 2026-06-26 - SQLite-Memory offline-first agent memory

- Repo URL: https://github.com/sqliteai/sqlite-memory
- Repo name: sqliteai/sqlite-memory
- Feature or ability Thomas should consider: Markdown-based persistent memory for AI agents with semantic search, hybrid retrieval, and offline-first sync between agents.
- Why it matters for Thomas: Thomas needs agent memory that is inspectable, portable, and usable across worker processes. SQLite-Memory is a reference for combining human-readable Markdown state with local semantic retrieval and sync.
- Integration surface guess: `thomas/memory/`, worker memory stores, local-first sync, semantic retrieval, and cross-agent context sharing.
- Evidence/source URL: https://github.com/sqliteai/sqlite-memory
- Date found: 2026-06-26
- Confidence note: High confidence for memory architecture relevance; adoption is emerging but the design is directly useful.

### 2026-06-26 - SQLite-Agent agents inside SQLite

- Repo URL: https://github.com/sqliteai/sqlite-agent
- Repo name: sqliteai/sqlite-agent
- Feature or ability Thomas should consider: SQLite extension for defining agents in SQL, giving them tools and memory, and running them locally without a separate orchestration server.
- Why it matters for Thomas: Thomas could use a database-native agent execution model for small local automations, tests, and durable workflows where the data store is also the execution control plane.
- Integration surface guess: Local automation runtime, test fixtures, memory-backed tools, SQL-defined worker experiments, and portable offline agents.
- Evidence/source URL: https://github.com/sqliteai/sqlite-agent
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; novel and relevant, though deeper evaluation is needed before treating SQL as an agent-definition layer.

### 2026-06-26 - Adam embeddable C agent library

- Repo URL: https://github.com/sqliteai/adam
- Repo name: sqliteai/adam
- Feature or ability Thomas should consider: Embeddable cross-platform C agent loop with cloud/local LLMs, tool calling, memory, sessions, voice, streaming, structured output, research mode, and self-evolving loops.
- Why it matters for Thomas: Thomas may eventually need lightweight local agents embedded in desktop/mobile/offline contexts. Adam is a compact reference for a portable agent runtime rather than a Python service.
- Integration surface guess: Local desktop runtime, offline helper agents, portable test harnesses, WASM/mobile experiments, and low-level session/memory primitives.
- Evidence/source URL: https://github.com/sqliteai/adam
- Date found: 2026-06-26
- Confidence note: Medium confidence; good portability signal, but adoption and maturity should be reviewed before borrowing patterns.

### 2026-06-26 - AI Agent Rules workflow standardization

- Repo URL: https://github.com/baneeishaque/ai-agent-rules
- Repo name: baneeishaque/ai-agent-rules
- Feature or ability Thomas should consider: Standardized Markdown rule framework for AI-assisted development workflows, covering trust, transparency, consistency, rule categories, architecture, examples, and integration guidance.
- Why it matters for Thomas: Thomas already depends on Bible/guardrail discipline and recurring worker instructions. A structured rule-pack reference could help package worker behavior as visible, versioned policy rather than hidden prompt text.
- Integration surface guess: Worker profile rule packs, onboarding docs, prompt policy registry, skill/agent configuration, and guardrail review checklists.
- Evidence/source URL: https://github.com/baneeishaque/ai-agent-rules
- Date found: 2026-06-26
- Confidence note: Medium confidence; lightweight rules repo, useful as a packaging idea rather than an implementation dependency.

### 2026-06-26 - Microsoft Trace generative optimization for agents

- Repo URL: https://github.com/microsoft/Trace
- Repo name: microsoft/Trace
- Feature or ability Thomas should consider: End-to-end generative optimization library that captures and propagates execution traces through AI systems using feedback such as rewards, language critiques, or compiler errors.
- Why it matters for Thomas: Thomas wants self-improvement but needs grounded mechanisms. Trace offers a research-backed way to optimize agent components from execution feedback without relying only on informal prompt edits.
- Integration surface guess: Evolve loop, run feedback propagation, compiler/test-error optimization experiments, prompt/program tuning, and trace-backed improvement candidates.
- Evidence/source URL: https://github.com/microsoft/Trace
- Date found: 2026-06-26
- Confidence note: Medium-high confidence; research-heavy but from a strong source and directly tied to execution-trace optimization.

### 2026-06-26 - Repobase AI repo index with MCP server

- Repo URL: https://github.com/fernandoabolafio/repobase
- Repo name: fernandoabolafio/repobase
- Feature or ability Thomas should consider: AI-oriented Git repository indexing/search with a terminal UI and MCP server for agent-tool integration.
- Why it matters for Thomas: Thomas workers need fast, explainable codebase context. Repobase is a compact reference for pairing local repo indexing, a human terminal UI, and MCP access for agents.
- Integration surface guess: Code-search/RAG layer, MCP code context server, terminal inspection UI, and worker context retrieval.
- Evidence/source URL: https://github.com/fernandoabolafio/repobase
- Date found: 2026-06-26
- Confidence note: Medium confidence; smaller project, but the TUI-plus-MCP shape is highly relevant.

### 2026-06-26 - SimpleMem lifelong multimodal agent memory

- Repo URL: https://github.com/aiming-lab/SimpleMem
- Repo name: aiming-lab/SimpleMem
- Feature or ability Thomas should consider: Efficient lifelong memory for LLM agents with semantic lossless compression and multimodal support for text, image, audio, and video.
- Why it matters for Thomas: Thomas memory will need to age, compress, and retrieve long-running project context without ballooning tokens. SimpleMem is a useful research/implementation reference for compressed lifelong memory.
- Integration surface guess: Memory compaction, multimodal artifact recall, long-running worker context, MCP memory adapter, and evals for retrieval fidelity.
- Evidence/source URL: https://github.com/aiming-lab/SimpleMem
- Date found: 2026-06-26
- Confidence note: High confidence for memory-research value; integration would require careful fidelity and privacy evaluation.

### 2026-06-26 - Engram persistent memory for coding agents

- Repo URL: https://github.com/Gentleman-Programming/engram
- Repo name: Gentleman-Programming/engram
- Feature or ability Thomas should consider: Agent-agnostic persistent memory binary for AI coding agents using SQLite and FTS5, with MCP server, HTTP API, CLI, TUI, plugin docs, and team usage guidance.
- Why it matters for Thomas: This is close to Thomas' developer-agent use case: local or cloud memory for coding workers with multiple access modes. The single-binary + MCP/HTTP/CLI/TUI design is worth studying.
- Integration surface guess: Coding-worker memory, MCP memory server, local TUI inspection, team memory sharing, and plugin/extension memory adapters.
- Evidence/source URL: https://github.com/Gentleman-Programming/engram
- Date found: 2026-06-26
- Confidence note: High confidence; active, popular, and directly aligned with AI coding-agent memory.

### 2026-06-26 - EverOS portable user-owned memory layer

- Repo URL: https://github.com/EverMind-AI/EverOS
- Repo name: EverMind-AI/EverOS
- Feature or ability Thomas should consider: Portable local-first, Markdown-native, user-owned, self-evolving memory layer across agents, apps, tools, and workflows.
- Why it matters for Thomas: Thomas needs user-owned continuity that survives individual agents and sessions. EverOS is a strong reference for treating memory as portable infrastructure rather than a hidden model/provider feature.
- Integration surface guess: Local user memory vault, cross-agent memory sync, Markdown-native memory format, self-evolving memory workflows, and privacy controls.
- Evidence/source URL: https://github.com/EverMind-AI/EverOS
- Date found: 2026-06-26
- Confidence note: High confidence for product-direction relevance; actual implementation should be reviewed for durability and privacy guarantees.

### 2026-06-27 - Memoirs local conflict-resolved agent memory

- Repo URL: https://github.com/misaelzapata/memoirs
- Repo name: misaelzapata/memoirs
- Feature or ability Thomas should consider: Local-first long-term memory for agents with transcript ingestion, durable signal extraction, local LLM curation, ranked context retrieval, and conflict-resolved memory answers.
- Why it matters for Thomas: Thomas needs memory that survives sessions while staying local and conflict-aware. Memoirs is a useful reference for converting transcripts/tool calls into compact, ranked working context without sending private data to cloud services.
- Integration surface guess: `thomas/memory/`, worker transcript ingestion, context compaction, local LLM memory curation, and conflict resolution.
- Evidence/source URL: https://github.com/misaelzapata/memoirs
- Date found: 2026-06-27
- Confidence note: High confidence for local worker-memory fit; implementation is still small enough to review thoroughly.

### 2026-06-27 - Nocturne rollbackable MCP long-term memory

- Repo URL: https://github.com/Dataojitori/nocturne_memory
- Repo name: Dataojitori/nocturne_memory
- Feature or ability Thomas should consider: Lightweight MCP long-term memory server with persistent graph-like structured memory, SQLite/PostgreSQL support, visualization, and rollbackable memory behavior.
- Why it matters for Thomas: Thomas needs agent memory that can be inspected and safely corrected. Rollbackable memory is particularly relevant when agents write bad facts or stale project state.
- Integration surface guess: MCP memory server, memory rollback UI, graph-like project memory, model/session-spanning recall, and memory audit tools.
- Evidence/source URL: https://github.com/Dataojitori/nocturne_memory
- Date found: 2026-06-27
- Confidence note: Medium-high confidence; strong feature fit, with sovereignty/persona framing to separate from Thomas' pragmatic memory needs.

### 2026-06-27 - MemClaw cross-fleet governed memory

- Repo URL: https://github.com/caura-ai/memclaw-cross-fleet-gov
- Repo name: caura-ai/memclaw-cross-fleet-gov
- Feature or ability Thomas should consider: Multi-agent memory governance demo with shared memory backend, fleet-scoped boundaries, query-time filtering, per-row ACLs, cross-fleet synthesis, and conflict detection.
- Why it matters for Thomas: Thomas workers need shared memory without leaking unrelated project, repo, or role context. This is a concrete demo of memory boundaries and conflict detection across multiple agent groups.
- Integration surface guess: Worker-team memory scopes, per-agent ACLs, query filters, cross-project synthesis controls, and memory-conflict reports.
- Evidence/source URL: https://github.com/caura-ai/memclaw-cross-fleet-gov
- Date found: 2026-06-27
- Confidence note: High confidence for governance pattern relevance; demo-sized but directly aligned with multi-worker memory safety.

### 2026-06-27 - Reflect Memory user-authored privacy-first memory

- Repo URL: https://github.com/van-reflect/Reflect-Memory
- Repo name: van-reflect/Reflect-Memory
- Feature or ability Thomas should consider: Vendor-neutral memory layer where memories are explicitly user-authored, structured, editable, and deletable, exposed via TypeScript SDK, MCP server, REST API, and n8n nodes.
- Why it matters for Thomas: Thomas memory should not silently accumulate sensitive or wrong facts. Reflect's explicit user-authored/editable/deletable memory stance is a strong privacy and UX reference.
- Integration surface guess: User memory editor, MCP memory adapter, REST memory API, deletion/export controls, and privacy-first memory policy.
- Evidence/source URL: https://github.com/van-reflect/Reflect-Memory
- Date found: 2026-06-27
- Confidence note: Medium-high confidence; small repo but strong alignment with user-controlled memory requirements.

### 2026-06-27 - OpenMemory cognitive memory engine

- Repo URL: https://github.com/CaviraOSS/OpenMemory
- Repo name: CaviraOSS/OpenMemory
- Feature or ability Thomas should consider: Self-hosted cognitive memory engine for LLMs and agents, with Python/Node packages and VS Code extension support.
- Why it matters for Thomas: Thomas needs a user-visible, local memory layer that works across coding assistants and workflows. OpenMemory is worth tracking as a productized memory system even though it is currently being rewritten.
- Integration surface guess: Local memory service, editor integration, worker memory APIs, self-hosted user memory, and coding-agent continuity.
- Evidence/source URL: https://github.com/CaviraOSS/OpenMemory
- Date found: 2026-06-27
- Confidence note: Medium confidence; high adoption signal but current rewrite status means defer any direct adoption until stability improves.

### 2026-06-27 - Recall MCP-native self-hosted memory

- Repo URL: https://github.com/RecallWorks/Recall
- Repo name: RecallWorks/Recall
- Feature or ability Thomas should consider: Self-hosted MCP-native memory server for one or many agents, packaged as a Docker image with Python/npm clients and multi-agent coordination guidance.
- Why it matters for Thomas: Thomas could expose memory through MCP while keeping data local. Recall's one-image packaging and explicit multi-agent scaling story are useful for practical deployment design.
- Integration surface guess: MCP memory server, local Docker deployment, multi-agent memory coordination, package/client APIs, and memory service quickstart.
- Evidence/source URL: https://github.com/RecallWorks/Recall
- Date found: 2026-06-27
- Confidence note: Medium-high confidence; early but concrete and operationally relevant.

### 2026-06-27 - Memory MCP enhanced knowledge graph server

- Repo URL: https://github.com/danielsimonjr/memory-mcp
- Repo name: danielsimonjr/memory-mcp
- Feature or ability Thomas should consider: Enhanced MCP memory server with timestamps, tags, importance, semantic search, hierarchy, compression, graph algorithms, archiving, import/export, role-based access control, PII redaction, do-not-remember exclusions, and decision rationale memory.
- Why it matters for Thomas: This is a dense reference for memory governance features Thomas will need: redaction, forget rules, RBAC, temporal validity, project context, and rationale capture.
- Integration surface guess: Memory governance API, PII redaction/export, project memory graph, do-not-remember policy, ADR/rationale memory, and MCP memory tooling.
- Evidence/source URL: https://github.com/danielsimonjr/memory-mcp
- Date found: 2026-06-27
- Confidence note: Medium confidence; broad feature list should be validated, but it is directly relevant to memory policy design.

### 2026-06-27 - Octopoda memory operating system

- Repo URL: https://github.com/RyjoxTechnologies/Octopoda-OS
- Repo name: RyjoxTechnologies/Octopoda-OS
- Feature or ability Thomas should consider: Memory operating system for AI agents with persistent memory, semantic search, loop detection, agent messaging, crash recovery, audit trails, and live observability.
- Why it matters for Thomas: Thomas needs memory, loop detection, recovery, and observability as one operating surface for agents. Octopoda is a relevant reference for bundling those concerns instead of treating them as unrelated features.
- Integration surface guess: Native worker runtime, memory observability dashboard, loop detector, crash recovery, inter-agent messaging, and audit trails.
- Evidence/source URL: https://github.com/RyjoxTechnologies/Octopoda-OS
- Date found: 2026-06-27
- Confidence note: Medium-high confidence; feature fit is strong, with implementation maturity to inspect later.

### 2026-06-27 - Project Cognition System local governance runtime

- Repo URL: https://github.com/yunhaichu/project-cognition-system
- Repo name: yunhaichu/project-cognition-system
- Feature or ability Thomas should consider: Local cognition governance runtime for long-running coding agents, with compact world state, evidence weighting, conflict detection, hook-friendly memory control, and stable project facts.
- Why it matters for Thomas: Thomas needs to distinguish project facts from noisy chat history. This repo's "what qualifies as a fact" framing maps well to Bible-backed state, claim state, and long-running worker recovery.
- Integration surface guess: Project-state memory, evidence weighting, conflict detection, Bible/workboard fact reconciliation, and hook-based memory updates.
- Evidence/source URL: https://github.com/yunhaichu/project-cognition-system
- Date found: 2026-06-27
- Confidence note: Medium confidence; very low adoption but highly aligned with Thomas' factual-state problem.

### 2026-06-27 - MHN AI Agent Memory deterministic associative recall

- Repo URL: https://github.com/shahzebqazi/mhn-ai-agent-memory
- Repo name: shahzebqazi/mhn-ai-agent-memory
- Feature or ability Thomas should consider: Deterministic associative memory for AI agents using Modern Hopfield Networks, with no LLM calls, no database, and MCP support for coding agents.
- Why it matters for Thomas: Most agent memory relies on vector search plus LLM summarization. This is a useful small-scale counterexample for deterministic project working memory and offline experiments.
- Integration surface guess: Experimental memory backend, deterministic recall tests, offline coding-agent memory, MCP memory adapter, and benchmark comparisons against vector stores.
- Evidence/source URL: https://github.com/shahzebqazi/mhn-ai-agent-memory
- Date found: 2026-06-27
- Confidence note: Low-medium confidence for production adoption; repo labels itself toy/research, but the deterministic-memory idea is worth tracking.

## Dedupe Notes

- 2026-06-26: Queue created; no prior queue entries existed, so duplicate skips were 0.
- 2026-06-26: AutoGen was checked but not added as a primary entry because the GitHub page states it is in maintenance mode and points toward Microsoft Agent Framework as the newer direction.
- 2026-06-26 heartbeat 14:23Z: Existing queue URLs were checked before appending. Added 10 fresh entries. Duplicate URL skips: 0. Maintenance/staleness skip: `microsoft/autogen` remained excluded.
- 2026-06-26 heartbeat 14:25Z: Existing queue URLs were checked before appending. Added 9 fresh entries. Duplicate URL skips: 0.
- 2026-06-26 heartbeat 14:30Z: Existing queue URLs were checked before appending. Added 9 fresh entries. Duplicate URL skips: 0. Staleness skip: `continuedev/continue` because the repo page says it is no longer actively maintained.
- 2026-06-26 heartbeat 14:32Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 2 (`langfuse/langfuse`, `aider-ai/aider` appeared again in search results).
- 2026-06-26 heartbeat 14:40Z: Existing queue URLs were checked before appending. Added 10 fresh entries. Duplicate URL skips: 0. Staleness skip: `Not-Diamond/self-care` because its repository page says it is not in active development.
- 2026-06-26 heartbeat 14:43Z: Existing queue URLs were checked before appending. Added 9 fresh entries. Duplicate URL skips: 1 (`promptfoo/promptfoo` appeared again in search results). Non-repo skips: GitHub Agentic Workflows docs and Sourcegraph comparison page.
- 2026-06-26 heartbeat 14:49Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Non-repo skips: marketplace-only action pages, Reddit/Dev.to/LinkedIn examples, and GitHub Agentic Workflows docs.
- 2026-06-26 heartbeat 15:00Z: Existing queue URLs were checked before appending. Added 6 fresh entries. Duplicate URL skips: 3 (`Nayjest/Gito`, `The-PR-Agent/pr-agent`, `snyk/agent-scan`). Non-repo skips: Copilot docs/discussions, marketplace pages, Reddit/LinkedIn/Medium/YouTube/forum/social results.
- 2026-06-26 heartbeat 15:03Z: Existing queue URLs were checked before appending. Added 6 fresh entries. Duplicate URL skips: 2 (`simular-ai/agent-s`, `formulahendry/acp-ui`). Non-repo skips: ACP docs/blog/issues and GUI-agent survey pages.
- 2026-06-26 heartbeat 15:06Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`lahfir/agent-desktop`, `agent-infra/sandbox`, `simular-ai/agent-s`, `formulahendry/acp-ui`). Non-repo skips: Reddit posts, docs, issues, article pages, and topic pages not tied to a repo entry.
- 2026-06-26 heartbeat 15:13Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 2 (`formulahendry/vscode-acp`, `vercel-labs/agent-browser`). Non-repo skips: arXiv/PDF mirrors, Reddit/LinkedIn/Instagram posts, NPM package page, and project marketing pages.
- 2026-06-26 heartbeat 15:20Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`vercel-labs/agent-browser`, `browser-use/browser-use`, `rohitg00/agentmemory`, `agentclientprotocol/agent-client-protocol`). Non-repo skips: Reddit posts, arXiv pages, docs/changelog pages, marketing pages, and GitHub topic pages not tied to a new queue entry.
- 2026-06-26 heartbeat 15:33Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 5 (`Picrew/awesome-agent-harness`, `BrowserMCP/mcp`, `AGI-Edgerunners/LLM-Agents-Papers`, `browser-use/browser-harness`, `browser-use/browser-use`). Non-repo skips: Reddit posts, arXiv pages, YouTube links, Browser Use article, GitHub discussions, GitHub topics, and project marketing/docs pages.
- 2026-06-26 heartbeat 15:39Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 5 (`Siddhant-K-code/agent-trace`, `replayio/replay-mcp`, `vercel-labs/agent-browser`, `promptfoo/promptfoo`, `jstuart0/agentpulse`). Non-repo skips: Reddit posts, LinkedIn post, PyPI page, YouTube links, news/blog pages, and GitHub discussions.
- 2026-06-26 heartbeat 15:47Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`microsoft/agent-governance-toolkit`, `lastmile-ai/mcp-agent`, `snyk/agent-scan`, `modelcontextprotocol/servers`). Non-repo skips: GitHub docs/blog/changelog, Reddit, YouTube, Medium, LinkedIn, TechRadar, GitHub discussions, and arXiv/ResearchGate pages.
- 2026-06-26 heartbeat 16:02Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Non-repo skips: product pages, GitHub topic pages, papers, blog/news posts, and social/video results.
- 2026-06-26 heartbeat 16:17Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Non-repo skips: marketing pages, GitHub topic/search pages, papers, social/video pages, and package/docs-only results.
- 2026-06-26 heartbeat 16:36Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: memory/search-agent catalogs and generic awesome lists held for later targeted runs. Non-repo skips: papers, benchmark articles, GitHub topic/search pages, docs-only pages, and social/video results.
- 2026-06-26 heartbeat 17:00Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: durable-execution example repos and docs-only auth articles held for later targeted runs. Non-repo skips: product pages, articles, docs-only pages, GitHub topic/search pages, and social/video results.
- 2026-06-26 heartbeat 17:24Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: additional Claude Code subagent catalogs held for a focused role-template pass. Non-repo skips: docs, articles, GitHub topic/search pages, and package-only results.
- 2026-06-26 heartbeat 17:34Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: duplicate prior memory mentions were only source-log skips, not raw entries. Non-repo skips: papers, project home pages, GitHub topic/search pages, and docs-only pages.
- 2026-06-26 heartbeat 17:40Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Non-repo skips: arXiv/paper pages, marketplace pages, GitHub issues/discussions, docs pages, YouTube/social posts, and generic topic pages.
- 2026-06-26 heartbeat 17:49Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: older Durable Swarm repo and generic SRE catalogs held as secondary sources. Non-repo skips: blogs, docs, discussions, Reddit/social pages, topic pages, and podcast/news mirrors.
- 2026-06-26 heartbeat 17:57Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: duplicate A2A catalog mirrors and package/docs-only pages held as secondary sources. Non-repo skips: protocol docs pages, product pages, GitHub topics, package pages, and social/video results.
- 2026-06-26 heartbeat 18:07Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: generic hosted code-search products and docs-only pages held for later comparison. Non-repo skips: product pages, blog posts, GitHub topics, and package-only results.
- 2026-06-26 heartbeat 18:16Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: broader GUI-agent catalogs held for later taxonomy work. Non-repo skips: arXiv/paper pages, docs pages, GitHub topics, product pages, and social/video results.
- 2026-06-26 heartbeat 18:27Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: already-queued MCP gateway/security projects and policy engines. Non-repo skips: product pages, blog posts, docs-only pages, GitHub issues/discussions, and social/video results.
- 2026-06-26 heartbeat 18:35Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: generic prompt-engineering lists and docs-only workflow pages held for later comparison. Non-repo skips: papers, product pages, documentation-only pages, topic pages, and social/video results.
- 2026-06-26 heartbeat 18:43Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 3 (`AgentOps-AI/agentops`, `chirpz-ai/pandaprobe`, `Siddhant-K-code/agent-trace`). Non-repo skips: blog posts, docs pages, GitHub issues/discussions/topics, LinkedIn/Reddit/YouTube, and news articles.
- 2026-06-26 heartbeat 18:52Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 1 (`rajudandigam/agent-inspect`). Non-repo skips: docs pages, product pages, blog posts, GitHub topics/issues, package registries, and social/video results.
- 2026-06-26 heartbeat 19:05Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 1 (`agentgateway/agentgateway`). Related skips: small one-off token calculators and provider SDK wrappers held for later only if they show active agent-loop enforcement. Non-repo skips: docs pages, product pages, blog posts, package registries, and GitHub issues/discussions/topics.
- 2026-06-26 heartbeat 19:13Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`BerriAI/litellm`, `Portkey-AI/gateway`, `maximhq/bifrost`, `Azure-Samples/AI-Gateway`). Related skips: generic model-router demos without policy/cost hooks. Non-repo skips: docs pages, cloud product pages, package registries, blogs, and GitHub issues/topics.
- 2026-06-26 heartbeat 19:29Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`zilliztech/GPTCache`, `vllm-project/semantic-router`, `upstash/semantic-cache`, `codefuse-ai/ModelCache`). Related skips: papers and awesome lists retained only as future source maps. Non-repo skips: docs pages, product pages, blog posts, and GitHub issues/topics.
- 2026-06-26 heartbeat 19:41Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 5 (`lm-sys/RouteLLM`, `ulab-uiuc/LLMRouter`, `swe-bench/SWE-bench`, `OpenHands/benchmarks`, `philschmid/ai-agent-benchmark-compendium`). Related skips: benchmark catalogs without runnable harnesses. Non-repo skips: papers, blogs, docs pages, GitHub topics/issues, and leaderboard-only pages.
- 2026-06-26 heartbeat 19:50Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 7 (`lastmile-ai/mcp-agent`, `benchflow-ai/BenchFlow`, `benchflow-ai/SkillsBench`, `Accenture/mcp-bench`, `SalesforceAIResearch/MCP-Universe`, `agentreplay/agentreplay`, `hidai25/eval-view`). Related skips: paper-only browser-agent resources and scorecard marketing pages. Non-repo skips: docs pages, product pages, blog posts, GitHub issues/topics, and leaderboard pages.
- 2026-06-26 heartbeat 20:01Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 2 (`ulab-uiuc/AgentDebug`, `vectara/awesome-agent-failures`). Related skips: adjacent MCP toolboxes without fuzz/eval focus. Non-repo skips: papers, blogs, docs-only pages, GitHub issues/topics, and product pages.
- 2026-06-26 heartbeat 20:08Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 1 (`langfuse/langfuse`). Related skips: generic eval leaderboards and provider-specific notebook demos without reusable harnesses. Non-repo skips: docs pages, product pages, blogs, GitHub issues/topics, and model cards.
- 2026-06-26 heartbeat 20:28Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 2 (`NVIDIA/SkillSpector`, `ThomasVitale/agents-skills-oci-artifacts-spec`). Related skips: generic prompt libraries without package metadata. Non-repo skips: docs pages, product pages, blog posts, GitHub issues/topics, and package registry pages.
- 2026-06-26 heartbeat 20:39Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 6 (`anthropics/skills`, `NVIDIA/skills`, `VoltAgent/awesome-agent-skills`, `ComposioHQ/awesome-claude-skills`, `github/awesome-copilot`, `wshobson/agents`). Related skips: generic prompt libraries and non-skill agent catalogs. Non-repo skips: docs pages, product pages, package registry pages, GitHub issues/topics, and blog posts.
- 2026-06-26 heartbeat 20:52Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 3 (`agentskills/agentskills`, `NVIDIA/SkillSpector`, `ThomasVitale/agents-skills-oci-artifacts-spec`). Related skips: generic signing articles and package pages. Non-repo skips: docs pages, product pages, blog posts, GitHub issues/topics, and standards pages without code repositories.
- 2026-06-26 heartbeat 21:06Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 4 (`open-policy-agent/opa`, `tech-leads-club/agent-skills`, `visa/trusted-agent-protocol`, `guacsec/guac`). Related skips: generic identity wallet demos without agent/tool trust relevance. Non-repo skips: standards pages, docs pages, product pages, blog posts, and GitHub issues/topics.
- 2026-06-26 heartbeat 21:19Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 6 (`microsoft/identity-spiffe`, `evansims/openfga-mcp`, `BillionsNetwork/verified-agent-identity`, `openwallet-foundation/acapy`, `agentic-community/mcp-gateway-registry`, `kahalewai/agent-policy-engine`). Related skips: broad identity specs without repository code and generic OAuth examples not tied to agents/MCP. Non-repo skips: standards pages, docs pages, product pages, GitHub issues/discussions, and blog posts.
- 2026-06-26 heartbeat 21:32Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 2 (`microsoft/agent-governance-toolkit`, `agentralabs/agentic-contract`). Related skips: archived `achetronic/mcp-proxy`, broad OAuth docs without repository code, and generic identity-provider demos not tied to agent/MCP tool execution.
- 2026-06-26 heartbeat 21:46Z: Existing queue URLs were checked before appending. Added 8 fresh entries. Duplicate URL skips: 0. Related skips: broad paper/catalog repo `tmgthb/Autonomous-Agents`, speculative safety-contract repo `TheNovacene/verse-ality-agents`, and generic consent/OAuth pages without implementation repositories.
- 2026-06-26 heartbeat 21:56Z: Existing queue URLs were checked before appending. Added 7 fresh entries. Duplicate URL skips: 3 (`elliot35/deterministic-agent-control-protocol`, `AgentOps-AI/agentops`, `Picrew/awesome-agent-harness`). Related skips: tutorial-style `FareedKhan-dev/Multi-Agent-AI-System` and broad search-result pages without implementation repositories.
- 2026-06-26 heartbeat 22:07Z: Existing queue URLs were checked before appending. Added 9 fresh entries. Duplicate URL skips: 3 (`microsoft/agent-governance-toolkit`, `luckyPipewrench/pipelock`, `elliot35/deterministic-agent-control-protocol`). Related skips: broad docs/search pages, generic protocol examples without durable implementation, and marketing pages.
- 2026-06-26 heartbeat 22:19Z: Existing queue URLs were checked before appending. Added 6 fresh entries. Duplicate URL skips: 8 (`Siddhant-K-code/agent-trace`, `ASSERT-KTH/reproducible-trajectories`, `LMCache/lmcache-agent-trace`, `agentreplay/agentreplay`, `callstack/agent-device`, `hidai25/eval-view`, `aws-samples/sample-why-agents-fail`, `xlang-ai/AgentTrek`). Related skips: security-forensics demos not specific to agent trajectories and GitHub API 403 candidates that could not be verified enough for this pass.
- 2026-06-26 heartbeat 22:30Z: Existing queue URLs were checked before appending. Added 9 fresh entries. Duplicate URL skips: 3 (`cursor/agent-trace`, `neuledge/context`, `rohitg00/agentmemory`). Related skips: broad search pages, generic trace docs without implementation repos, and unverified GitHub API 403 candidates.
- 2026-06-27 heartbeat 04:15Z: Existing queue URLs were checked before appending. Added 10 fresh entries. Duplicate URL skips: 4 (`mem0ai/mem0`, `IAAR-Shanghai/Awesome-AI-Memory`, `SalesforceAIResearch/MCP-Universe`, `ipiton/agent-memory-mcp`). Related skips: broad memory catalogs already represented, generic privacy docs without implementation repos, and broad assistant projects where memory governance was not the primary lesson.

## Sources Checked

- 2026-06-26: Query set: `GitHub AutoGen multi-agent framework agent orchestration memory tools`; `GitHub CrewAI multi-agent framework tools memory planning`; `GitHub OpenHands AI software development agent repository`; `GitHub SWE-agent agent computer use repository`.
- 2026-06-26: Query set: `site:github.com langgraph agent orchestration memory human in loop repository`; `site:github.com pydantic ai agents tool calling evals repository`; `site:github.com smolagents code agents tool calling repository`; `site:github.com OpenAI Agents SDK GitHub tracing handoffs agents`.
- 2026-06-26 heartbeat 14:23Z: Query set: `GitHub agent evaluation framework agentic AI tool use repository SWE bench active`; `GitHub AI agent observability tracing workflow replay repository`; `GitHub secure AI agent sandbox tool execution repository`; `GitHub multi agent workflow framework blackboard memory planning repository`.
- 2026-06-26 heartbeat 14:23Z: Query set: `GitHub CAMEL AI multi agent society framework tools memory agents`; `GitHub AG2 agent framework AutoGen multi agent tool use active`; `GitHub google adk agent development kit python multi agent tools`; `GitHub semantic kernel agent framework multi agent orchestration process framework`.
- 2026-06-26 heartbeat 14:23Z: Query set: `GitHub Braintrust autoevals agent evaluations LLM eval repository`; `GitHub LangSmith OpenTelemetry agent observability tracing repository open source`; `GitHub Inspect AI agent evaluation framework tool use repository`; `GitHub Ragas agent evaluation repository tool use agents`.
- 2026-06-26 heartbeat 14:25Z: Query set: `GitHub MCP agent framework permission broker tool calling agent memory repo`; `GitHub AI agent memory vector store long term memory repository MemGPT Letta`; `GitHub AI agent browser automation framework web agent repository active`; `GitHub coding agent benchmark harness SWE-bench pipeline repository active`.
- 2026-06-26 heartbeat 14:30Z: Query set: `GitHub autonomous PR review AI agent code review repository`; `GitHub AI code review agent pull request repository LLM active`; `GitHub MCP server registry marketplace repository awesome mcp servers`; `GitHub tool permission policy engine AI agents sandbox repository`.
- 2026-06-26 heartbeat 14:30Z: Query set: `GitHub aider ai coding agent repository`; `GitHub continue dev AI coding agent repository`; `GitHub sourcegraph amp ai coding agent repository`; `GitHub opencode AI coding agent terminal repository`.
- 2026-06-26 heartbeat 14:32Z: Query set: `GitHub AI coding agent repo map codebase map repository`; `GitHub agent code search repository AI coding agent codebase retrieval`; `GitHub issue triage AI agent repository GitHub issues LLM`; `GitHub agent run UI trace viewer open source LLM agent repository`.
- 2026-06-26 heartbeat 14:32Z: Query set: `site:github.com "Issue AI Agent" "issue triage"`; `site:github.com "BrowserTrace" "web-agent"`; `site:github.com "AgentPulse" "observability" "AI agents"`; `site:github.com "Repo Atlas" "Codex" "Claude Code"`.
- 2026-06-26 heartbeat 14:40Z: Query set: `GitHub AI agent security scanner prompt injection tool calling repository`; `GitHub MCP gateway security agent tool policy repository`; `GitHub AI agent workflow automation repository multi agent state machine`; `GitHub LLM agent replay trace evaluation repository open source`.
- 2026-06-26 heartbeat 14:40Z: Query set: `GitHub promptfoo agent red teaming evals repository`; `GitHub NVIDIA garak LLM vulnerability scanner repository`; `GitHub Not-Diamond self-care Claude Code agent trace analysis`; `GitHub chirpz-ai pandaprobe agent engineering platform traces evals metrics`.
- 2026-06-26 heartbeat 14:40Z: Query set: `GitHub Microsoft MCP gateway reverse proxy repository tool-gateway`; `GitHub agentgateway mcp a2a proxy security observability governance repository`; `GitHub luckyPipewrench pipelock AI agent firewall MCP security`; `GitHub getagentseal agentseal security toolkit AI agents MCP configs`.
- 2026-06-26 heartbeat 14:43Z: Query set: `GitHub agent failure analysis LLM agent debugging repository`; `GitHub local codebase indexing AI agent repository code search MCP`; `GitHub prompt injection benchmark agents tool use repository`; `GitHub multi agent workflow runtime DAG agents repository`.
- 2026-06-26 heartbeat 14:49Z: Query set: `GitHub AI agent CI failure analysis GitHub Actions repository`; `GitHub AI production incident agent repository root cause analysis LLM`; `GitHub agent loop detector feedback loop LLM agents repository`; `GitHub codebase memory MCP server AI coding agents repository`.
- 2026-06-26 heartbeat 14:49Z: Query set: `calebevans github actions failure analysis repository`; `ratibor78 Actions AI Advisor github repository`; `the-open-engine zeroshot GitHub`; `AI agent CI failure analysis repository "GitHub Actions" "Claude"`.
- 2026-06-26 heartbeat 15:00Z: Query set: `GitHub AI agent PR comment dedupe review comments repository`; `GitHub AI reviewer re-review pull request comments repository`; `GitHub SKILL.md supply chain scanner AI agent repository`; `GitHub local desktop agent permission UI open source repository`.
- 2026-06-26 heartbeat 15:03Z: Query set: `GitHub Agent Client Protocol server repository ACP agents`; `GitHub ACP agent client protocol server implementation repository`; `GitHub GUI agent safety benchmark repository computer use agents`; `GitHub desktop automation permission model AI agent open source repository`.
- 2026-06-26 heartbeat 15:06Z: Query set: `GitHub ACP adapter implementation Claude Code Codex Gemini agents repository`; `GitHub GUI agent red team dataset benchmark computer use repository`; `GitHub accessibility tree command wrapper AI agent desktop repository`; `GitHub sandboxed desktop session recorder AI agent repository`.
- 2026-06-26 heartbeat 15:13Z: Query set: `GitHub Lightpanda semantic browser agent API repository`; `GitHub GitTaskBench agent benchmark repository`; `GitHub AIRTBench red team agents benchmark repository`; `GitHub ACP server adapter Codex Claude Code Gemini repository`.
- 2026-06-26 heartbeat 15:20Z: Query set: `GitHub MCP browser engine AI agent browser automation repository`; `GitHub OpenACP bridge agent client protocol repository`; `GitHub agent replay session recorder repository LLM agents`; `GitHub repo-aware benchmark harness code agents repository`.
- 2026-06-26 heartbeat 15:33Z: Query set: `GitHub AI agent replay session recorder trace repository`; `GitHub AgentRR implementation repo record replay LLM agents`; `GitHub browser harness agent comparison repository`; `GitHub MCP browser automation agent replay repository`.
- 2026-06-26 heartbeat 15:39Z: Query set: `GitHub agent replay storage schema LLM trace repository`; `GitHub browser MCP security comparison repository AI agents`; `GitHub run forking observability tools LLM agents repository`; `GitHub replay to eval conversion agents repository`.
- 2026-06-26 heartbeat 15:39Z: Query set: `github agent-strace replay agent observability repository`; `github agent-inspect local execution trees TypeScript AI agents`; `github cyberark agentwatch AI observability framework repository`; `github agent replay local-first desktop evals agentreplay`.
- 2026-06-26 heartbeat 15:47Z: Query set: `GitHub context receipt schemas AI agent repository`; `GitHub agent secret handling policy engine repository AI agents`; `GitHub PR replay datasets coding agents repository`; `GitHub observability to eval conversion LLM agent repository`.
- 2026-06-26 heartbeat 15:47Z: Query set: `GitHub AI agent policy engine action approval repository`; `GitHub AI agent secrets security scanner repository MCP tools`; `GitHub AI agent context repository MCP local documentation`; `GitHub agent evaluation observability course repository Arize`.
- 2026-06-26 heartbeat 16:02Z: Query set: `GitHub AI agent durable execution workflow repository checkpoints rollback`; `GitHub LLM agent task delegation workboard repository`; `GitHub context engineering AI agent repository memory tools`; `GitHub AI agent human approval workflow repository`.
- 2026-06-26 heartbeat 16:02Z: Query set: `site:github.com AI agent runbook eval memory MCP repository "agent" "workflow"`; `site:github.com "AI agents" "human-in-the-loop" "approval" "tools" repository`; `site:github.com "multi-agent" "worktree" "message bus" "Claude Code"`; `site:github.com "LLM agent" "knowledge graph" "memory" repository`.
- 2026-06-26 heartbeat 16:02Z: Query set: `nikhilgarg28 delegate GitHub AI agents`; `AxmeAI ai-agent-checkpoint-and-resume GitHub`; `topoteretes cognee GitHub agent memory`; `Runbook-Agent RunbookAI GitHub`; `ipiton agent-memory-mcp GitHub`; `mnemon dev mnemon GitHub agent memory`; `polos-dev polos GitHub AI agent`; `agentkitai agentgate GitHub human approval AI agents`.
- 2026-06-26 heartbeat 16:17Z: Query set: `GitHub AI agent protocol runtime repository approval memory tools 2026`; `GitHub AI agent task graph runtime repository durable execution MCP`; `GitHub coding agent orchestrator worktree review repository Claude Code Codex`; `GitHub LLM agent state machine workflow engine repository tools human approval`.
- 2026-06-26 heartbeat 16:17Z: Query set: `GitHub ORCA cognitive runtime layer agent systems repository`; `GitHub local-first work model AI agents commitments approval gates repository AccInt`; `GitHub LLM agent guardrails state machine tools repository codex claude`; `GitHub agent task graph MCP server quality gates repository`.
- 2026-06-26 heartbeat 16:36Z: Query set: `GitHub AI agent evaluation benchmark repository tool use planning 2026`; `GitHub LLM agent reliability framework repository self healing planning memory`; `GitHub agent prompt optimization self improvement repository tools memory`; `GitHub multi-agent coding benchmark repository issue repair pull request`.
- 2026-06-26 heartbeat 16:36Z: Query set: `EvoAgentX GitHub automated framework evolving agentic workflows`; `MASLab multi-agent system GitHub LLM codebase 2026`; `AI agent benchmark compendium GitHub philschmid`; `VIA-Research AgentBench GitHub dynamic reasoning agents`.
- 2026-06-26 heartbeat 17:00Z: Query set: `GitHub TypeScript AI agent framework workflows memory evals Mastra VoltAgent`; `GitHub AI agent tool authorization human approval OAuth repository`; `GitHub production LLM agent observability evaluation open source repository`; `GitHub workflow engine AI agents durable human in loop tools`.
- 2026-06-26 heartbeat 17:00Z: Query set: `humanlayer human-in-the-loop agents github`; `arcadeai arcade-ai github agent tools authorization`; `composiohq composio github AI agents tools`; `langwatch langwatch github agent observability evals`; `GitHub Restate durable AI loops agents repository`; `GitHub DBOS crashproof AI agents durable execution repository`; `GitHub langwatch scenario agentic testing repository`; `GitHub inngest agent kit AI agents workflows repository`.
- 2026-06-26 heartbeat 17:24Z: Query set: `GitHub agent UX framework copilots human in loop repository CopilotKit`; `GitHub AI agent workflow method markdown personas repository BMAD METHOD`; `GitHub autonomous software engineer agent repo "devika" "OpenDevin"`; `GitHub agent orchestration CLI subagents workflow repository Claude Code`.
- 2026-06-26 heartbeat 17:24Z: Query set: `GitHub agent teams CLI Claude Code multi-agent orchestration`; `GitHub Gas Town Claude Code agents repository`; `GitHub Multiclaude multi agent Claude Code repository`; `GitHub agent squad CLI persistent memory cost monitoring Claude Code`.
- 2026-06-26 heartbeat 17:34Z: Query set: `GitHub AI agent memory graph episodic semantic memory repository MemOS Mem0 Zep`; `GitHub agent memory operating system repository memos mem0 zep graphiti`; `GitHub LLM agent long term memory repository temporal graph open source`; `GitHub AI agent memory MCP semantic episodic repository 2026`.
- 2026-06-26 heartbeat 17:34Z: Query set: `mem0ai mem0 GitHub memory layer AI agents`; `MemTensor MemOS GitHub AI memory operating system agents`; `GibsonAI memori GitHub AI agent memory`; `Zep Graphiti MCP server GitHub AI agent memory`.
- 2026-06-26 heartbeat 17:40Z: Query set: `GitHub AI agent red team benchmark tool use repository 2026 safety evals`; `GitHub LLM agent runtime safety monitor repository tool calls policy evals`; `GitHub agent benchmark web automation tasks repository visual web agent`; `GitHub AI agent regression testing repository trajectory evaluation`.
- 2026-06-26 heartbeat 17:40Z: Query set: `ucsb-mlsec Awesome-Agent-Security GitHub`; `kajogo777 the-agent-sandbox-taxonomy GitHub`; `hidai25 eval-view GitHub agent trajectory evaluation`; `langchain-ai agentevals GitHub`.
- 2026-06-26 heartbeat 17:49Z: Query set: `GitHub durable execution AI agents workflow engine repository Restate DBOS Temporal agents`; `GitHub self healing incident remediation AI agent repository Kubernetes SRE`; `GitHub AI SRE agent incident response repository runbook automation`; `GitHub durable agent workflow crash recovery TypeScript Python repository`.
- 2026-06-26 heartbeat 17:49Z: Query set: `restatedev ai-examples GitHub agents`; `dbos-inc durable-swarm GitHub AI agents`; `Azure-Samples durable task extension agent framework GitHub`; `temporal-community temporal-ai-agent GitHub`; `aqrpole kube-ai-sre-agent GitHub`; `Tracer-Cloud opensre GitHub AI SRE agent`; `agamm awesome-ai-sre GitHub`; `last9 awesome-sre-agents GitHub`.
- 2026-06-26 heartbeat 17:57Z: Query set: `GitHub agent communication protocol AG-UI agent UI repository`; `GitHub A2A agent protocol repository Python JavaScript server`; `GitHub agent network protocol multi-agent communication repository`; `GitHub agent UI protocol human in the loop repository`.
- 2026-06-26 heartbeat 17:57Z: Query set: `GitHub agent UI AG-UI implementation repository FastAPI agents`; `GitHub awesome a2a agent2agent tools servers clients repository`; `GitHub NLIP natural language interaction protocol agents repository`; `GitHub agent communication protocol examples repository`.
- 2026-06-26 heartbeat 18:07Z: Query set: `GitHub codebase intelligence AI agent repository map context engineering`; `GitHub repo map LLM coding agent context repository semantic code graph`; `GitHub context engineering codebase agent repository code graph RAG`; `GitHub AI coding agent codebase indexing repository symbols graph`.
- 2026-06-26 heartbeat 18:07Z: Query set: `GitHub "sdl-mcp" Symbol Delta Ledger coding agents`; `GitHub CodeGraphContext MCP code graph AI assistants`; `GitHub OpenViking context database AI agents repository`; `GitHub colbymchenry codegraph pre-built knowledge graph codebase`; `GitHub sourcebot code search AI agents repository`; `GitHub codebase RAG MCP server AI coding agents repository tree-sitter`; `GitHub static analysis MCP code context AI agents repository`; `GitHub code knowledge graph MCP coding assistant repository`.
- 2026-06-26 heartbeat 18:16Z: Query set: `GitHub GUI agents browser mobile computer use repository 2026`; `GitHub computer use agent browser automation benchmark repository visual agent`; `GitHub mobile GUI agent repository android iOS autonomous testing`; `GitHub web agent DOM vision hybrid benchmark repository`.
- 2026-06-26 heartbeat 18:16Z: Query set: `x-plug mobileagent GitHub GUI agent`; `Core-Mate OpenGUI GitHub GUI agents`; `takahirom arbigent GitHub AI mobile testing`; `TIGER-AI-Lab ClawBench GitHub`; `surfly D2Snap GitHub web agent benchmark`; `web-arena-x visualwebarena GitHub visual web agent benchmark`; `nottelabs open-operator-evals GitHub browser agents`; `OS-Agent-Survey OS-Agent-Survey GitHub`.
- 2026-06-26 heartbeat 18:27Z: Query set: `GitHub AI agent tool permission policy MCP gateway repository`; `GitHub MCP security gateway AI agents policy repository`; `GitHub agent tool call authorization policy engine repository`; `GitHub AI agent runtime monitor tool calls security repository`.
- 2026-06-26 heartbeat 18:27Z: Query set: `secureagentics adrian GitHub AI agent security runtime`; `Defend-AI-Tech-Inc agent-discover-scanner GitHub`; `deterministic-agent-control-protocol GitHub elliot35`; `panguard-ai panguard-ai GitHub agent safety`; `GitHub agentguard runtime guard AI agents malicious skills`; `GitHub ghostsecurity skills AI coding agent security`; `GitHub AI agent firewall runtime guard repository tool calls`; `GitHub agent threat rules ATR repository AI agent security`.
- 2026-06-26 heartbeat 18:35Z: Query set: `GitHub declarative AI agent workflow DSL repository agents yaml tools`; `GitHub prompt programming framework AI agents repository DSPy agent workflows`; `GitHub agent workflow DSL visual programming repository LLM agents`; `GitHub AI agent low code workflow repository declarative tools memory`.
- 2026-06-26 heartbeat 18:35Z: Query set: `GitHub "declarative YAML" "multi-agent workflows" "LLM" repository`; `GitHub "agent workflow" "YAML DSL" "multi-agent" repository`; `GitHub "LLM workflow" "DSL" "agents" "tools" repository`; `GitHub "prompt program" "agent" "workflow" repository`.
- 2026-06-26 heartbeat 18:43Z: Query set: `GitHub AI agent observability tracing production repository OpenTelemetry agents`; `GitHub LLM agent trace viewer replay analysis repository`; `GitHub agent telemetry OpenTelemetry evals repository`; `GitHub production agent monitoring dashboard repository traces tools`.
- 2026-06-26 heartbeat 18:43Z: Query set: `traceloop openllmetry GitHub OpenTelemetry LLM agents`; `dynatrace ai agent instrumentation examples GitHub`; `latitude-dev latitude-llm GitHub evaluations agents prompts`; `LMCache agent trace GitHub`; `GitHub AI agent observability dashboard traces open source "agent" "OpenTelemetry"`; `GitHub "agent observability" "OpenTelemetry" "traces" "GitHub"`; `GitHub "AI agent monitoring" "failed traces" repository`.
- 2026-06-26 heartbeat 18:52Z: Query set: `GitHub LLM cost tracking observability OpenTelemetry agents repository`; `GitHub AI agent cost attribution traces repository`; `GitHub LLM gateway observability cost tracking repository agents`; `GitHub OpenTelemetry semantic conventions generative AI agents repository`.
- 2026-06-26 heartbeat 18:52Z: Query set: `GitHub "Token telemetry dashboard" "Claude Code" "Codex"`; `GitHub "Local execution trees" "TypeScript AI agents" agent-inspect`; `GitHub "AI agent" "cost tracking" "Claude Code" "Codex" repository`; `GitHub "tracks tokens" "Claude Code" "Codex" "Gemini CLI"`.
- 2026-06-26 heartbeat 19:05Z: Query set: `GitHub AI agent budget enforcement cost guardrails repository`; `GitHub LLM token budget enforcement agent repository`; `GitHub AI agent cost guardrails spend limits repository`; `GitHub model gateway budget rate limit LLM agent repository`.
- 2026-06-26 heartbeat 19:05Z: Query set: `site:github.com "LLM budget" "token budget" "agent"`; `site:github.com "AI budget" "LLM" "spend limit" repository`; `site:github.com "token budget" "OpenAI" "Anthropic" "GitHub"`; `BerriAI litellm budget spend tracking GitHub`; `helicone helicone GitHub cost tracking rate limits LLM`; `Portkey-AI gateway GitHub AI gateway guardrails rate limits`.
- 2026-06-26 heartbeat 19:13Z: Query set: `GitHub LLM semantic cache gateway repository agents`; `GitHub AI gateway semantic cache provider failover repository`; `GitHub model routing failover LLM gateway semantic cache`; `GitHub quota aware scheduler AI agents LLM`.
- 2026-06-26 heartbeat 19:13Z: Query set: `zilliztech GPTCache GitHub semantic cache LLM`; `vllm-project semantic-router GitHub`; `redis langcache GitHub semantic cache LLM`; `envoyproxy ai-gateway GitHub LLM`; `upstash semantic cache GitHub`; `alibaba higress AI gateway GitHub LLM`; `peva3 SmarterRouter GitHub LLM router`.
- 2026-06-26 heartbeat 19:29Z: Query set: `GitHub LLM cache invalidation provenance repository`; `GitHub semantic cache provenance LLM agents repository`; `GitHub local model routing benchmark LLM router repository`; `GitHub LLM route replay testing gateway repository`.
- 2026-06-26 heartbeat 19:29Z: Query set: `lm-sys RouteLLM GitHub router`; `ulab-uiuc LLMRouter GitHub`; `anyscale llm-router GitHub`; `LMCache LMCache GitHub LLM cache`; `openziti llm-gateway GitHub`; `databricks-industry-solutions semantic-caching GitHub`; `GoogleCloudPlatform apigee-samples semantic caching GitHub`; `NVIDIA AI Blueprints llm-router GitHub`.
- 2026-06-26 heartbeat 19:41Z: Query set: `GitHub model capability scoring LLM evaluation router repository`; `GitHub LLM router telemetry benchmark dataset repository`; `GitHub route evaluation dataset LLM routers repository`; `GitHub model capability router agent benchmark repository`.
- 2026-06-26 heartbeat 19:41Z: Query set: `GitHub agent capability benchmark repository coding agents 2026`; `GitHub AI agent benchmark real world tasks repository`; `GitHub coding agent benchmark repository model capability scoring`; `GitHub MCP agent benchmark repository capability evaluation`; `MilkThink-Lab RouterEval GitHub`; `Accenture mcp-bench GitHub`; `SalesforceAIResearch MCP-Universe GitHub`; `benchflow-ai BenchFlow GitHub`.
- 2026-06-26 heartbeat 19:50Z: Query set: `GitHub benchmark to issue conversion AI agent work items repository`; `GitHub agent benchmark failure triage issue generation repository`; `GitHub MCP server scorecard repository evaluation`; `GitHub skill discovery regression suite AI agent repository`.
- 2026-06-26 heartbeat 19:50Z: Query set: `GitHub browser action replay traces AI agent benchmark repository`; `GitHub web agent replay trace benchmark repository`; `GitHub browser agent trajectory replay repository`; `GitHub AI agent behavior regression gate repository`; `scorecard-ai mcp-eval GitHub`; `lastmile-ai mcp-eval GitHub`; `scaleapi mcp-atlas GitHub`; `xlang-ai OSWorld-V2 GitHub`.
- 2026-06-26 heartbeat 20:01Z: Query set: `GitHub eval failure clustering LLM agent repository`; `GitHub agent trajectory compression repository LLM`; `GitHub task artifact provenance AI agent repository`; `GitHub MCP tool contract fuzzing repository`.
- 2026-06-26 heartbeat 20:01Z: Query set: `GitHub MCP fuzz testing server tools schema repository`; `GitHub tool contract testing LLM agents repository`; `GitHub LLM agent failure modes repository code examples`; `GitHub agent trajectory analysis automated program repair repository`; `AmberLJC Agent-Native-Research-Artifact GitHub`; `FuzzingLabs mcp-security-hub GitHub`; `Agent-Hellboy mcp-server-fuzzer GitHub`; `relari-ai agent-contracts GitHub`.
- 2026-06-26 heartbeat 20:08Z: Query set: `GitHub artifact bundle schema AI agents provenance repository`; `GitHub MCP fuzz corpus generation repository`; `GitHub contract test authoring AI agent repository`; `GitHub failure cluster dashboard LLM agent repository`.
- 2026-06-26 heartbeat 20:08Z: Query set: `GitHub AI agent eval dashboard failure clustering repository LangSmith open source`; `GitHub LLM evaluation dashboard failure clustering repository`; `GitHub agent eval results dashboard repository`; `GitHub AI evaluation failure analysis repository`; `microsoft eval-guide GitHub AI evaluation`; `IBM CLEAR GitHub LLM evaluation clustering`; `SAP agent-quality-inspect GitHub`; `vercel-labs agent-eval GitHub`.
- 2026-06-26 heartbeat 20:28Z: Query set: `GitHub eval cookbook AI agents repository`; `GitHub LLM judge drift dashboard repository`; `GitHub skill packaging trust metadata AI agents repository`; `GitHub workboard issue synthesis from eval traces AI agent repository`.
- 2026-06-26 heartbeat 20:28Z: Query set: `GitHub LLM judge drift repository eval dashboard`; `GitHub LLM-as-judge evaluation drift monitoring repository`; `GitHub agent skills registry packaging repository`; `GitHub AI agent skill marketplace metadata repository`; `anthropics skills GitHub Claude skills`; `NVIDIA skills GitHub agent skills`; `softaworks agent-toolkit GitHub`; `DiversioTeam agent-skills-marketplace GitHub`.
- 2026-06-26 heartbeat 20:39Z: Query set: `GitHub agent skill import compatibility test repository`; `GitHub agent skill signing marketplace trust labels repository`; `GitHub AI agent marketplace moderation workflow repository`; `GitHub agent skill security metadata repository`.
- 2026-06-26 heartbeat 20:39Z: Query set: `agentskills agentskills GitHub`; `callstackincubator agent-skills GitHub`; `datalayer agent-skills GitHub`; `heilcheng awesome-agent-skills GitHub`; `Publish Agent Skills GitHub action skr repository`; `agent skills CLI GitHub agentskills npm package repository`; `skills sh GitHub agent skills registry`.
- 2026-06-26 heartbeat 20:52Z: Query set: `GitHub signed agent skills publishing repository`; `GitHub skill dependency lockfile agent skills repository`; `GitHub AI agent prompt trust labels repository`; `GitHub skill vulnerability disclosure agent skills repository`.
- 2026-06-26 heartbeat 20:52Z: Query set: `GitHub sigstore cosign agent skills signing provenance`; `GitHub SLSA provenance AI agent artifacts repository`; `GitHub in-toto attestations AI agent artifact provenance`; `GitHub OpenSSF Scorecard agent skills repository`; `visa trusted-agent-protocol GitHub`; `tech-leads-club agent-skills GitHub`; `sigstore policy-controller GitHub`; `GUAC graph for understanding artifact composition GitHub`.
- 2026-06-26 heartbeat 21:06Z: Query set: `GitHub agent identity wallet AI agents repository`; `GitHub AI agent trust policy language repository`; `GitHub supply chain graph queries skills provenance repository`; `GitHub trust aware prompt assembly AI agent repository`.
- 2026-06-26 heartbeat 21:06Z: Query set: `GitHub OPA policy language AI agent trust policy repository`; `GitHub Cedar policy language agent authorization repository`; `GitHub OpenFGA AI agent authorization policy repository`; `GitHub SPIFFE agent identity workload identity repository`; `microsoft identity-spiffe GitHub`; `evansims openfga-mcp GitHub`; `BillionsNetwork verified-agent-identity GitHub`; `openwallet-foundation acapy GitHub`.
- 2026-06-26 heartbeat 21:19Z: Query set: `GitHub agent identity credential exchange repository AI agents`; `GitHub authorization simulation UX policy AI agents repository`; `GitHub trust-domain isolation AI agents repository`; `GitHub prompt-time policy explanations AI agent repository`.
- 2026-06-26 heartbeat 21:19Z: Query set: `GitHub secure agent account access delegated credentials repository`; `GitHub AI agent scoped token delegated auth repository`; `GitHub MCP OAuth authorization AI agents repository`; `GitHub AI agent prompt policy enforcement repository`; `mikekelly gap GitHub generative agent protocol`; `kanoniv agent-auth GitHub AI agent authentication`; `smartnose policy-enforcer GitHub AI agent`; `conshus mcp-github-oauth GitHub`.
- 2026-06-26: Source checked: https://github.com/microsoft/autogen
- 2026-06-26: Source checked: https://github.com/microsoft/agent-framework
- 2026-06-26: Source checked: https://github.com/langchain-ai/langgraph
- 2026-06-26: Source checked: https://github.com/pydantic/pydantic-ai
- 2026-06-26: Source checked: https://github.com/pydantic/pydantic-ai-harness
- 2026-06-26: Source checked: https://github.com/huggingface/smolagents
- 2026-06-26: Source checked: https://github.com/openai/openai-agents-python
- 2026-06-26: Source checked: https://github.com/openai/openai-agents-js
- 2026-06-26: Source checked: https://github.com/OpenHands/software-agent-sdk
- 2026-06-26: Source checked: https://github.com/OpenHands/openhands
- 2026-06-26: Source checked: https://github.com/SWE-agent/SWE-agent
- 2026-06-26: Source checked: https://github.com/SWE-agent/mini-swe-agent
- 2026-06-26: Source checked: https://github.com/crewAIInc/crewAI
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/AgentOps-AI/agentops
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/agent-infra/sandbox
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/2FastLabs/agent-squad
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/camel-ai/camel
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/ag2ai/ag2
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/google/adk-python
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/microsoft/semantic-kernel
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/UKGovernmentBEIS/inspect_ai
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/langfuse/langfuse
- 2026-06-26 heartbeat 14:23Z: Source checked: https://github.com/claudioed/agent-blackboard
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/lastmile-ai/mcp-agent
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/letta-ai/letta
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/rohitg00/agentmemory
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/browser-use/browser-use
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/vercel-labs/agent-browser
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/firecrawl/web-agent
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/swe-bench/SWE-bench
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/OpenHands/benchmarks
- 2026-06-26 heartbeat 14:25Z: Source checked: https://github.com/princeton-pli/hal-harness
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/The-PR-Agent/pr-agent
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/continuedev/checks
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/microsoft/agent-governance-toolkit
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/open-policy-agent/opa
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/modelcontextprotocol/servers
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/github/github-mcp-server
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/punkpeye/awesome-mcp-servers
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/aider-ai/aider
- 2026-06-26 heartbeat 14:30Z: Source checked: https://github.com/anomalyco/opencode
- 2026-06-26 heartbeat 14:30Z: Source checked but skipped: https://github.com/continuedev/continue
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/theanshsonkar/carto
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/cyanheads/repo-map
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/cathrynlavery/repo-atlas
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/Rxflex/agenttrace
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/jstuart0/agentpulse
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/alexyan0431/issue-ai-agent
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/redplanetlabs/agent-o-rama
- 2026-06-26 heartbeat 14:32Z: Source checked: https://github.com/steel-dev/awesome-web-agents
- 2026-06-26 heartbeat 14:32Z: Source checked but skipped as duplicate: https://github.com/langfuse/langfuse
- 2026-06-26 heartbeat 14:32Z: Source checked but skipped as duplicate: https://github.com/aider-ai/aider
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/luckyPipewrench/pipelock
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/getagentseal/agentseal
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/snyk/agent-scan
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/agentgateway/agentgateway
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/microsoft/mcp-gateway
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/agentic-community/mcp-gateway-registry
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/chirpz-ai/pandaprobe
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/promptfoo/promptfoo
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/NVIDIA/garak
- 2026-06-26 heartbeat 14:40Z: Source checked: https://github.com/ScalingIntelligence/TRACE
- 2026-06-26 heartbeat 14:40Z: Source checked but skipped as stale: https://github.com/Not-Diamond/self-care
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/ulab-uiuc/AgentDebug
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/zilliztech/claude-context
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/liu00222/Open-Prompt-Injection
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/open-multi-agent/open-multi-agent
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/johnhuang316/code-index-mcp
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/uiuc-kang-lab/InjecAgent
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/lakeraai/pint-benchmark
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/glommer/codemogger
- 2026-06-26 heartbeat 14:43Z: Source checked: https://github.com/vectara/awesome-agent-failures
- 2026-06-26 heartbeat 14:43Z: Source checked but skipped as duplicate: https://github.com/promptfoo/promptfoo
- 2026-06-26 heartbeat 14:43Z: Source checked but skipped as non-repo: https://github.github.com/gh-aw/
- 2026-06-26 heartbeat 14:43Z: Source checked but skipped as non-repo: https://sourcegraph.com/resources/context-compare
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/traceroot-ai/traceroot
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/DeusData/codebase-memory-mcp
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/VishApp/multiagent-debugger
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/calebevans/gha-failure-analysis
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/ratibor78/actions-ai-advisor
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/the-open-engine/zeroshot
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/aws-samples/sample-operational-ai-agent
- 2026-06-26 heartbeat 14:49Z: Source checked: https://github.com/Jun-jie-Huang/awesome-LLM-AIOps
- 2026-06-26 heartbeat 14:49Z: Source checked but skipped as non-repo: https://github.github.com/gh-aw/
- 2026-06-26 heartbeat 14:49Z: Source checked but skipped as non-repo/example: Reddit, Dev.to, LinkedIn, and GitHub Marketplace result pages.
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/NVIDIA/SkillSpector
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/momenbasel/AgentGuard
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/simular-ai/agent-s
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/formulahendry/acp-ui
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/alessiobianchini/DesktopAgent
- 2026-06-26 heartbeat 15:00Z: Source checked: https://github.com/github/awesome-copilot/blob/main/skills/agent-supply-chain/SKILL.md
- 2026-06-26 heartbeat 15:00Z: Source checked but skipped as duplicate: https://github.com/Nayjest/Gito
- 2026-06-26 heartbeat 15:00Z: Source checked but skipped as duplicate: https://github.com/The-PR-Agent/pr-agent
- 2026-06-26 heartbeat 15:00Z: Source checked but skipped as duplicate: https://github.com/snyk/agent-scan
- 2026-06-26 heartbeat 15:00Z: Source checked but skipped as non-repo: GitHub Copilot docs/discussions, marketplace pages, Reddit, LinkedIn, Medium, YouTube, StackOverflow, Fortinet community post, and OpenRefine forum page.
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/agentclientprotocol/agent-client-protocol
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/i-am-bee/acp
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/lahfir/agent-desktop
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/trycua/cua
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/OSU-NLP-Group/AgentSafety
- 2026-06-26 heartbeat 15:03Z: Source checked: https://github.com/callstack/agent-device
- 2026-06-26 heartbeat 15:03Z: Source checked but skipped as duplicate: https://github.com/simular-ai/agent-s
- 2026-06-26 heartbeat 15:03Z: Source checked but skipped as duplicate: https://github.com/formulahendry/acp-ui
- 2026-06-26 heartbeat 15:03Z: Source checked but skipped as non-repo: ACP docs/blog/issues, LangChain ACP docs, GUI-agent surveys, and generic topic pages.
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/nuskey8/UnityAgentClient
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/formulahendry/vscode-acp
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/rivet-dev/sandbox-agent
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/OSU-NLP-Group/GUI-Agents-Paper-List
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/showlab/awesome-gui-agent
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/Community-Access/accessibility-agents
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets
- 2026-06-26 heartbeat 15:06Z: Source checked: https://github.com/tizkovatereza/awesome-ai-sandboxes
- 2026-06-26 heartbeat 15:06Z: Source checked but skipped as duplicate: https://github.com/lahfir/agent-desktop
- 2026-06-26 heartbeat 15:06Z: Source checked but skipped as duplicate: https://github.com/agent-infra/sandbox
- 2026-06-26 heartbeat 15:06Z: Source checked but skipped as duplicate: https://github.com/simular-ai/agent-s
- 2026-06-26 heartbeat 15:06Z: Source checked but skipped as duplicate: https://github.com/formulahendry/acp-ui
- 2026-06-26 heartbeat 15:06Z: Source checked but skipped as non-repo: Reddit sandbox/replay posts, ACP article/docs/issues, GUI-agent survey pages, webMCP issue, YouTube link, and topic pages.
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/lightpanda-io/browser
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/QuantaAlpha/GitTaskBench
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/dreadnode/AIRTBench-Code
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/allvegetable/acp-bridge
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/beyond5959/acp-adapter
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/THUDM/DataSciBench
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/Cogensec/Gideon
- 2026-06-26 heartbeat 15:13Z: Source checked: https://github.com/gadzan/xacpx
- 2026-06-26 heartbeat 15:13Z: Source checked but skipped as duplicate: https://github.com/formulahendry/vscode-acp
- 2026-06-26 heartbeat 15:13Z: Source checked but skipped as duplicate: https://github.com/vercel-labs/agent-browser
- 2026-06-26 heartbeat 15:13Z: Source checked but skipped as non-repo: arXiv/PDF mirrors, Reddit/LinkedIn/Instagram posts, NPM package page, Lightpanda marketing site, and project discussion pages.
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/Open-ACP/OpenACP
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/cola-io/codex-acp
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/BrowserMCP/mcp
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/browser-use/browser-harness
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/Picrew/awesome-agent-harness
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/ai-boost/awesome-harness-engineering
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/YennNing/Awesome-Code-as-Agent-Harness-Papers
- 2026-06-26 heartbeat 15:20Z: Source checked: https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- 2026-06-26 heartbeat 15:20Z: Source checked but skipped as duplicate: https://github.com/vercel-labs/agent-browser
- 2026-06-26 heartbeat 15:20Z: Source checked but skipped as duplicate: https://github.com/browser-use/browser-use
- 2026-06-26 heartbeat 15:20Z: Source checked but skipped as duplicate: https://github.com/rohitg00/agentmemory
- 2026-06-26 heartbeat 15:20Z: Source checked but skipped as duplicate: https://github.com/agentclientprotocol/agent-client-protocol
- 2026-06-26 heartbeat 15:20Z: Source checked but skipped as non-repo: Reddit replay post, arXiv AgentRR/GitTaskBench pages, BrowserMCP marketing page, ACP docs, GitHub changelog, YouTube link, and generic topic pages.
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/manasvardhan/agent-replay
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/Siddhant-K-code/agent-trace
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/silouone/clens
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/Saik0s/mcp-browser-use
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/microsoft/playwright-mcp
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/browser-use/bux
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/pankaj-agrawalla/kontex-cli
- 2026-06-26 heartbeat 15:33Z: Source checked: https://github.com/replayio/replay-mcp
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as duplicate: https://github.com/Picrew/awesome-agent-harness
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as duplicate: https://github.com/BrowserMCP/mcp
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as duplicate: https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as duplicate: https://github.com/browser-use/browser-harness
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as duplicate: https://github.com/browser-use/browser-use
- 2026-06-26 heartbeat 15:33Z: Source checked but skipped as non-repo: Reddit session replay posts, arXiv AgentRR page, YouTube browser-harness links, Browser Use article, Replay MCP docs, GitHub topics, and MCP discussion pages.
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/agentreplay/agentreplay
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/rajudandigam/agent-inspect
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/cyberark/agentwatch
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/dreadnode/agent-lens
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/cyberark/agent-guard
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/monte-carlo-data/mc-agent-toolkit
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/caioribeiroclw-pixel/pluribus
- 2026-06-26 heartbeat 15:39Z: Source checked: https://github.com/sshh12/agent-pr-replay
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as duplicate: https://github.com/Siddhant-K-code/agent-trace
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as duplicate: https://github.com/replayio/replay-mcp
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as duplicate: https://github.com/vercel-labs/agent-browser
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as duplicate: https://github.com/promptfoo/promptfoo
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as duplicate: https://github.com/jstuart0/agentpulse
- 2026-06-26 heartbeat 15:39Z: Source checked but skipped as non-repo: Reddit posts, LinkedIn post, PyPI package, YouTube links, arXiv AgentRR page, GitHub discussions, and news/blog pages.
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/kahalewai/agent-policy-engine
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/cordum-io/cordum
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/neuledge/context
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/upstash/context7
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/arize-ai/phoenix
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/ksm26/Evaluating-AI-Agents
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/NirDiamant/GenAI_Agents
- 2026-06-26 heartbeat 15:47Z: Source checked: https://github.com/jim-schwoebel/awesome_ai_agents
- 2026-06-26 heartbeat 15:47Z: Source checked but skipped as duplicate: https://github.com/microsoft/agent-governance-toolkit
- 2026-06-26 heartbeat 15:47Z: Source checked but skipped as duplicate: https://github.com/lastmile-ai/mcp-agent
- 2026-06-26 heartbeat 15:47Z: Source checked but skipped as duplicate: https://github.com/snyk/agent-scan
- 2026-06-26 heartbeat 15:47Z: Source checked but skipped as duplicate: https://github.com/modelcontextprotocol/servers
- 2026-06-26 heartbeat 15:47Z: Source checked but skipped as non-repo: GitHub docs/blog/changelog, GitHub discussions, Reddit posts, YouTube videos, Medium/LinkedIn/Facebook/Instagram posts, TechRadar/news pages, arXiv/ResearchGate pages, and topic pages.
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/nikhilgarg28/delegate
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/AxmeAI/ai-agent-checkpoint-and-resume
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/topoteretes/cognee
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/Runbook-Agent/RunbookAI
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/ipiton/agent-memory-mcp
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/mnemon-dev/mnemon
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/polos-dev/polos
- 2026-06-26 heartbeat 16:02Z: Source checked: https://github.com/agentkitai/agentgate
- 2026-06-26 heartbeat 16:02Z: Source checked but skipped as non-repo: product home pages, GitHub topic/search pages, docs/blog/news/social/video pages, and paper-only results.
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/mondaycom/agent-tool-protocol
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/statewright/statewright
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/statelyai/agent
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/Oortonaut/task-graph-mcp
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/johannesjo/parallel-code
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/AgentWrapper/agent-orchestrator
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/agentralabs/agentic-contract
- 2026-06-26 heartbeat 16:17Z: Source checked: https://github.com/jpicklyk/task-orchestrator
- 2026-06-26 heartbeat 16:17Z: Source checked but skipped as related but lower priority: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- 2026-06-26 heartbeat 16:17Z: Source checked but skipped as related but lower priority: https://github.com/hatchet-dev/durable-execution-the-hard-way
- 2026-06-26 heartbeat 16:17Z: Source checked but skipped as related but lower priority: https://github.com/gfernandf/agent-skills
- 2026-06-26 heartbeat 16:17Z: Source checked but skipped as related but lower priority: https://github.com/rohitg00/awesome-claude-code-toolkit
- 2026-06-26 heartbeat 16:17Z: Source checked but skipped as non-repo: marketing pages, GitHub topic/search pages, papers, social/video pages, package pages, and docs-only results.
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/EvoAgentX/EvoAgentX
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/VIA-Research/AgentBench
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/philschmid/ai-agent-benchmark-compendium
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/MASWorks/MASLab
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/TsinghuaC3I/MARTI
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/supernalintelligence/Awesome-General-Agents-Benchmark
- 2026-06-26 heartbeat 16:36Z: Source checked: https://github.com/petterjuan/agentic-reliability-framework
- 2026-06-26 heartbeat 16:36Z: Source checked but skipped as related but lower priority: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- 2026-06-26 heartbeat 16:36Z: Source checked but skipped as related but lower priority: https://github.com/YunjiaXi/Awesome-Search-Agent-Papers
- 2026-06-26 heartbeat 16:36Z: Source checked but skipped as related but lower priority: https://github.com/weitianxin/Awesome-Agentic-Reasoning
- 2026-06-26 heartbeat 16:36Z: Source checked but skipped as related but lower priority: https://github.com/ARUNAGIRINATHAN-K/awesome-ai-agents-2026
- 2026-06-26 heartbeat 16:36Z: Source checked but skipped as non-repo: arXiv/paper pages, benchmark articles, GitHub topic/search pages, docs-only pages, and social/video results.
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/mastra-ai/mastra
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/VoltAgent/voltagent
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/baristaGeek/auth-for-agents
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/ArcadeAI/arcade-mcp
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/ComposioHQ/composio
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/langwatch/langwatch
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/langwatch/scenario
- 2026-06-26 heartbeat 17:00Z: Source checked: https://github.com/inngest/agent-kit
- 2026-06-26 heartbeat 17:00Z: Source checked but skipped as related but lower priority: HumanLayer repo/pages because current project status needed deeper maintenance review.
- 2026-06-26 heartbeat 17:00Z: Source checked but skipped as related but lower priority: Restate/DBOS durable-execution example repos for a later durability-focused run.
- 2026-06-26 heartbeat 17:00Z: Source checked but skipped as non-repo: product pages, articles, docs-only pages, GitHub topic/search pages, and social/video results.
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/CopilotKit/CopilotKit
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/bmad-code-org/BMAD-METHOD
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/e2b-dev/awesome-devins
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/stitionai/devika
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/awslabs/cli-agent-orchestrator
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/wshobson/agents
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/gastownhall/gastown
- 2026-06-26 heartbeat 17:24Z: Source checked: https://github.com/dlorenc/multiclaude
- 2026-06-26 heartbeat 17:24Z: Source checked but skipped as related but lower priority: https://github.com/zircote/claude-team-orchestration
- 2026-06-26 heartbeat 17:24Z: Source checked but skipped as related but lower priority: https://github.com/VoltAgent/awesome-claude-code-subagents
- 2026-06-26 heartbeat 17:24Z: Source checked but skipped as non-repo: docs, articles, GitHub topic/search pages, and package-only results.
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/mem0ai/mem0
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/getzep/graphiti
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/MemTensor/MemOS
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/memorilabs/memori
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/NirDiamant/Agent_Memory_Techniques
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/DEEP-PolyU/Awesome-GraphMemory
- 2026-06-26 heartbeat 17:34Z: Source checked: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- 2026-06-26 heartbeat 17:34Z: Source checked but skipped as non-repo: papers, project home pages, GitHub topic/search pages, and docs-only pages.
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/kajogo777/the-agent-sandbox-taxonomy
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/ucsb-mlsec/Awesome-Agent-Security
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/ProjectRecon/awesome-ai-agents-security
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/langchain-ai/agentevals
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/hidai25/eval-view
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/TaimoorKhan10/replayd
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/langchain-ai/agent-evals
- 2026-06-26 heartbeat 17:40Z: Source checked: https://github.com/langchain-ai/deepagents
- 2026-06-26 heartbeat 17:40Z: Source checked but skipped as non-repo: arXiv/paper pages, marketplace pages, GitHub issues/discussions, docs pages, YouTube/social posts, and generic topic pages.
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/restatedev/ai-examples
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/dbos-inc/dbos-openai-agents
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/Azure-Samples/durable-task-extension-for-agent-framework
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/temporal-community/temporal-ai-agent
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/Tracer-Cloud/opensre
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/aqrpole/kube-ai-sre-agent
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/carlossg/kubernetes-agent
- 2026-06-26 heartbeat 17:49Z: Source checked: https://github.com/last9/awesome-sre-agents
- 2026-06-26 heartbeat 17:49Z: Source checked but skipped as related but lower priority: https://github.com/dbos-inc/durable-swarm
- 2026-06-26 heartbeat 17:49Z: Source checked but skipped as related but lower priority: https://github.com/agamm/awesome-ai-sre
- 2026-06-26 heartbeat 17:49Z: Source checked but skipped as non-repo: blogs, docs, discussions, Reddit/social pages, topic pages, podcasts, and news mirrors.
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/ag-ui-protocol/ag-ui
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/a2aproject/A2A
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/a2aproject/a2a-python
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/a2aproject/a2a-js
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/a2aproject/a2a-samples
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/agent-network-protocol/AgentNetworkProtocol
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/pab1it0/awesome-a2a
- 2026-06-26 heartbeat 17:57Z: Source checked: https://github.com/themanojdesai/python-a2a
- 2026-06-26 heartbeat 17:57Z: Source checked but skipped as related but lower priority: https://github.com/ai-boost/awesome-a2a
- 2026-06-26 heartbeat 17:57Z: Source checked but skipped as non-repo: protocol docs pages, product pages, GitHub topics, package pages, and social/video results.
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/GlitterKill/sdl-mcp
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/harshkedia177/axon
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/CodeGraphContext/CodeGraphContext
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/volcengine/OpenViking
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/colbymchenry/codegraph
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/sourcebot-dev/sourcebot
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/Neverdecel/CodeRAG
- 2026-06-26 heartbeat 18:07Z: Source checked: https://github.com/tirth8205/code-review-graph
- 2026-06-26 heartbeat 18:07Z: Source checked but skipped as non-repo: hosted product pages, blog posts, GitHub topics, package pages, and docs-only pages.
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/X-PLUG/MobileAgent
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/Core-Mate/OpenGUI
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/takahirom/arbigent
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/TIGER-AI-Lab/ClawBench
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/webfuse-com/D2Snap
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/web-arena-x/visualwebarena
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/nottelabs/open-operator-evals
- 2026-06-26 heartbeat 18:16Z: Source checked: https://github.com/browser-use/benchmark
- 2026-06-26 heartbeat 18:16Z: Source checked but skipped as related but lower priority: https://github.com/OS-Agent-Survey/OS-Agent-Survey
- 2026-06-26 heartbeat 18:16Z: Source checked but skipped as related but lower priority: https://github.com/ZJU-REAL/Awesome-GUI-Agents
- 2026-06-26 heartbeat 18:16Z: Source checked but skipped as non-repo: arXiv/paper pages, docs pages, GitHub topics, product pages, and social/video results.
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/secureagentics/adrian
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/Defend-AI-Tech-Inc/agent-discover-scanner
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/elliot35/deterministic-agent-control-protocol
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/panguard-ai/panguard-ai
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/GoPlusSecurity/agentguard
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/runtimeguard/runtime-guard
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/Agent-Threat-Rule/agent-threat-rules
- 2026-06-26 heartbeat 18:27Z: Source checked: https://github.com/LLMSecurity/awesome-agent-skills-security
- 2026-06-26 heartbeat 18:27Z: Source checked but skipped as duplicate: `agentgateway/agentgateway`, `microsoft/mcp-gateway`, `getagentseal/agentseal`, `snyk/agent-scan`, `open-policy-agent/opa`.
- 2026-06-26 heartbeat 18:27Z: Source checked but skipped as non-repo: product pages, blog posts, docs-only pages, GitHub issues/discussions, and social/video results.
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/stanfordnlp/dspy
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/langgenius/dify
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/bytedance/deer-flow
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/zendev-sh/zenflow
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/tya5/reyn
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/The-Swarm-Corporation/swarms.yaml
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/sherkevin/Weaver
- 2026-06-26 heartbeat 18:35Z: Source checked: https://github.com/samholt/l2mac
- 2026-06-26 heartbeat 18:35Z: Source checked but skipped as related but lower priority: https://github.com/yzmw123/dify-workflow-dsl-skill
- 2026-06-26 heartbeat 18:35Z: Source checked but skipped as non-repo: papers, product pages, documentation-only pages, topic pages, and social/video results.
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/traceloop/openllmetry
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/traceloop/openllmetry-js
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/latitude-dev/latitude-llm
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/LMCache/lmcache-agent-trace
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/run-llama/agents-observability-demo
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/openlit/openlit
- 2026-06-26 heartbeat 18:43Z: Source checked: https://github.com/future-agi/traceai
- 2026-06-26 heartbeat 18:43Z: Source checked but skipped as duplicate: https://github.com/AgentOps-AI/agentops
- 2026-06-26 heartbeat 18:43Z: Source checked but skipped as duplicate: https://github.com/chirpz-ai/pandaprobe
- 2026-06-26 heartbeat 18:43Z: Source checked but skipped as duplicate: https://github.com/Siddhant-K-code/agent-trace
- 2026-06-26 heartbeat 18:43Z: Source checked but skipped as non-repo: blog posts, docs pages, GitHub issues/discussions/topics, LinkedIn/Reddit/YouTube, and news articles.
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/open-telemetry/semantic-conventions-genai
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/cursor/agent-trace
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/VasiHemanth/tokentelemetry
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/aqua5230/usage
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/androidZzT/cc-statistics
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/junhoyeo/tokscale
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/tokentopapp/tokentop
- 2026-06-26 heartbeat 18:52Z: Source checked: https://github.com/offbyone1/tokenbbq
- 2026-06-26 heartbeat 18:52Z: Source checked but skipped as duplicate: https://github.com/rajudandigam/agent-inspect
- 2026-06-26 heartbeat 18:52Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, GitHub topics/issues, package registries, and social/video results.
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/BerriAI/litellm
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/helicone/helicone
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/Portkey-AI/gateway
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/maximhq/bifrost
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/ENTERPILOT/GOModel
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/arieradle/shekel
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/Mattbusel/llm-budget
- 2026-06-26 heartbeat 19:05Z: Source checked: https://github.com/Azure-Samples/AI-Gateway
- 2026-06-26 heartbeat 19:05Z: Source checked but skipped as duplicate: https://github.com/agentgateway/agentgateway
- 2026-06-26 heartbeat 19:05Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, package registries, and GitHub issues/discussions/topics.
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/zilliztech/GPTCache
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/vllm-project/semantic-router
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/envoyproxy/ai-gateway
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/upstash/semantic-cache
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/codefuse-ai/ModelCache
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/aws-samples/Reducing-Hallucinations-in-LLM-Agents-with-a-Verified-Semantic-Cache
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/higress-group/higress
- 2026-06-26 heartbeat 19:13Z: Source checked: https://github.com/peva3/SmarterRouter
- 2026-06-26 heartbeat 19:13Z: Source checked but skipped as duplicate: https://github.com/BerriAI/litellm
- 2026-06-26 heartbeat 19:13Z: Source checked but skipped as duplicate: https://github.com/Portkey-AI/gateway
- 2026-06-26 heartbeat 19:13Z: Source checked but skipped as duplicate: https://github.com/maximhq/bifrost
- 2026-06-26 heartbeat 19:13Z: Source checked but skipped as duplicate: https://github.com/Azure-Samples/AI-Gateway
- 2026-06-26 heartbeat 19:13Z: Source checked but skipped as non-repo: docs pages, cloud product pages, package registries, blogs, and GitHub issues/topics.
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/lm-sys/RouteLLM
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/ulab-uiuc/LLMRouter
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/anyscale/llm-router
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/LMCache/LMCache
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/openziti/llm-gateway
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/databricks-industry-solutions/semantic-caching
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/GoogleCloudPlatform/apigee-samples/blob/main/llm-semantic-cache/llm_semantic_cache_v1.ipynb
- 2026-06-26 heartbeat 19:29Z: Source checked: https://github.com/NVIDIA-AI-Blueprints/llm-router
- 2026-06-26 heartbeat 19:29Z: Source checked but skipped as duplicate: https://github.com/zilliztech/GPTCache
- 2026-06-26 heartbeat 19:29Z: Source checked but skipped as duplicate: https://github.com/vllm-project/semantic-router
- 2026-06-26 heartbeat 19:29Z: Source checked but skipped as duplicate: https://github.com/upstash/semantic-cache
- 2026-06-26 heartbeat 19:29Z: Source checked but skipped as duplicate: https://github.com/codefuse-ai/ModelCache
- 2026-06-26 heartbeat 19:29Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, and GitHub issues/topics.
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/benchflow-ai/BenchFlow
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/benchflow-ai/SkillsBench
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/Accenture/mcp-bench
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/SalesforceAIResearch/MCP-Universe
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/THUDM/AgentBench
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/OpenBMB/ToolBench
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/OSU-NLP-Group/Mind2Web
- 2026-06-26 heartbeat 19:41Z: Source checked: https://github.com/ThinkOffApp/redacted-acp-peer-multi-agent-test-suite
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as duplicate: https://github.com/lm-sys/RouteLLM
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as duplicate: https://github.com/ulab-uiuc/LLMRouter
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as duplicate: https://github.com/swe-bench/SWE-bench
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as duplicate: https://github.com/OpenHands/benchmarks
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as duplicate: https://github.com/philschmid/ai-agent-benchmark-compendium
- 2026-06-26 heartbeat 19:41Z: Source checked but skipped as non-repo: papers, blogs, docs pages, GitHub topics/issues, and leaderboard-only pages.
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/scorecard-ai/mcp-eval
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/scorecard-ai/scorecard-mcp
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/lastmile-ai/mcp-eval
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/scaleapi/mcp-atlas
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/xlang-ai/AgentTrek
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/ASSERT-KTH/reproducible-trajectories
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/xlang-ai/OSWorld-V2
- 2026-06-26 heartbeat 19:50Z: Source checked: https://github.com/browserbase/stagehand
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/lastmile-ai/mcp-agent
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/benchflow-ai/BenchFlow
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/benchflow-ai/SkillsBench
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/Accenture/mcp-bench
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/SalesforceAIResearch/MCP-Universe
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/agentreplay/agentreplay
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as duplicate: https://github.com/hidai25/eval-view
- 2026-06-26 heartbeat 19:50Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, GitHub issues/topics, and leaderboard pages.
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/AmberLJC/Agent-Native-Research-Artifact
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/aws-samples/sample-why-agents-fail
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/sola-st/llm-agents-study
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/Agent-Hellboy/mcp-server-fuzzer
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/relari-ai/agent-contracts
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/nano-step/eval-harness
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/modelcontextprotocol/inspector
- 2026-06-26 heartbeat 20:01Z: Source checked: https://github.com/FuzzingLabs/mcp-security-hub
- 2026-06-26 heartbeat 20:01Z: Source checked but skipped as duplicate: https://github.com/ulab-uiuc/AgentDebug
- 2026-06-26 heartbeat 20:01Z: Source checked but skipped as duplicate: https://github.com/vectara/awesome-agent-failures
- 2026-06-26 heartbeat 20:01Z: Source checked but skipped as non-repo: papers, blogs, docs-only pages, GitHub issues/topics, and product pages.
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/microsoft/eval-guide
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/IBM/CLEAR
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/SAP/agent-quality-inspect
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/vercel-labs/agent-eval
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/Azure-Samples/Agentic-Evaluations
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/microsoft/eval-recipes
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/confident-ai/deepeval
- 2026-06-26 heartbeat 20:08Z: Source checked: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- 2026-06-26 heartbeat 20:08Z: Source checked but skipped as duplicate: https://github.com/langfuse/langfuse
- 2026-06-26 heartbeat 20:08Z: Source checked but skipped as non-repo: docs pages, product pages, blogs, GitHub issues/topics, and model cards.
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/anthropics/skills
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/NVIDIA/skills
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/aws/agent-toolkit-for-aws
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/softaworks/agent-toolkit
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/DiversioTeam/agent-skills-marketplace
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/VoltAgent/awesome-agent-skills
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/ComposioHQ/awesome-claude-skills
- 2026-06-26 heartbeat 20:28Z: Source checked: https://github.com/alirezarezvani/claude-skills
- 2026-06-26 heartbeat 20:28Z: Source checked but skipped as duplicate: https://github.com/NVIDIA/SkillSpector
- 2026-06-26 heartbeat 20:28Z: Source checked but skipped as duplicate: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- 2026-06-26 heartbeat 20:28Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, GitHub issues/topics, and package registry pages.
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/agentskills/agentskills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/Karanjot786/agent-skills-cli
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/onmax/npm-agentskills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/addyosmani/agent-skills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/addyosmani/web-quality-skills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/vercel-labs/skills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/microsoft/skills
- 2026-06-26 heartbeat 20:39Z: Source checked: https://github.com/agentskill-sh/ags
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/anthropics/skills
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/NVIDIA/skills
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/VoltAgent/awesome-agent-skills
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/ComposioHQ/awesome-claude-skills
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/github/awesome-copilot
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as duplicate: https://github.com/wshobson/agents
- 2026-06-26 heartbeat 20:39Z: Source checked but skipped as non-repo: docs pages, product pages, package registry pages, GitHub issues/topics, and blog posts.
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/tech-leads-club/agent-skills
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/visa/trusted-agent-protocol
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/sigstore/cosign
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/slsa-framework/slsa-github-generator
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/in-toto/attestation
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/sigstore/policy-controller
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/guacsec/guac
- 2026-06-26 heartbeat 20:52Z: Source checked: https://github.com/guacsec/guac-visualizer
- 2026-06-26 heartbeat 20:52Z: Source checked but skipped as duplicate: https://github.com/agentskills/agentskills
- 2026-06-26 heartbeat 20:52Z: Source checked but skipped as duplicate: https://github.com/NVIDIA/SkillSpector
- 2026-06-26 heartbeat 20:52Z: Source checked but skipped as duplicate: https://github.com/ThomasVitale/agents-skills-oci-artifacts-spec
- 2026-06-26 heartbeat 20:52Z: Source checked but skipped as non-repo: docs pages, product pages, blog posts, GitHub issues/topics, and standards pages without code repositories.
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/microsoft/identity-spiffe
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/spiffe/spire
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/openfga/openfga
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/evansims/openfga-mcp
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/cedar-policy/cedar
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/BillionsNetwork/verified-agent-identity
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/openwallet-foundation/acapy
- 2026-06-26 heartbeat 21:06Z: Source checked: https://github.com/walt-id/waltid-identity
- 2026-06-26 heartbeat 21:06Z: Source checked but skipped as duplicate: https://github.com/open-policy-agent/opa
- 2026-06-26 heartbeat 21:06Z: Source checked but skipped as duplicate: https://github.com/tech-leads-club/agent-skills
- 2026-06-26 heartbeat 21:06Z: Source checked but skipped as duplicate: https://github.com/visa/trusted-agent-protocol
- 2026-06-26 heartbeat 21:06Z: Source checked but skipped as duplicate: https://github.com/guacsec/guac
- 2026-06-26 heartbeat 21:06Z: Source checked but skipped as non-repo: standards pages, docs pages, product pages, blog posts, and GitHub issues/topics.
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/mikekelly/gap
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/kanoniv/agent-auth
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/alibaba/open-agent-auth
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/conshus/mcp-github-oauth
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/obot-platform/mcp-oauth-proxy
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/open-gitagent/opengap
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/harvard-lil/agent-protocols
- 2026-06-26 heartbeat 21:19Z: Source checked: https://github.com/jamjet-labs/jamjet
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/microsoft/identity-spiffe
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/evansims/openfga-mcp
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/BillionsNetwork/verified-agent-identity
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/openwallet-foundation/acapy
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/agentic-community/mcp-gateway-registry
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as duplicate: https://github.com/kahalewai/agent-policy-engine
- 2026-06-26 heartbeat 21:19Z: Source checked but skipped as non-repo: standards pages, docs pages, product pages, GitHub issues/discussions, and blog posts.
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/enforra/enforra
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/tuannvm/oauth-mcp-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/AthenZ/mcp-oauth-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/babs/mcp-auth-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/qred/qred-mcp-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/PredicateSystems/account-payable-multi-ai-agent-demo
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/smartnose/policy-enforcer
- 2026-06-26 heartbeat 21:32Z: Source checked: https://github.com/sigbit/mcp-auth-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked but skipped as duplicate: https://github.com/microsoft/agent-governance-toolkit
- 2026-06-26 heartbeat 21:32Z: Source checked but skipped as duplicate: https://github.com/agentralabs/agentic-contract
- 2026-06-26 heartbeat 21:32Z: Source checked but skipped as archived: https://github.com/achetronic/mcp-proxy
- 2026-06-26 heartbeat 21:32Z: Source checked but deferred for a broader IAM/MCP-gateway pass: https://github.com/casdoor/casdoor
- 2026-06-26 heartbeat 21:32Z: Source checked but deferred for a broader MCP-framework pass: https://github.com/PrefectHQ/fastmcp
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/ClickHouse/nerve
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/clay-good/proxilion-sdk
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/kashaf12/mandate
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/aniket-work/medical-preauth-agent
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/prakashm88/openfga-studio
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/authzed/spicedb
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/swarmclawai/agentready
- 2026-06-26 heartbeat 21:46Z: Source checked: https://github.com/agenticmail/enterprise
- 2026-06-26 heartbeat 21:46Z: Source checked but skipped as catalog-only: https://github.com/tmgthb/Autonomous-Agents
- 2026-06-26 heartbeat 21:46Z: Source checked but skipped as speculative/low-fit for this pass: https://github.com/TheNovacene/verse-ality-agents
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/muhamadto/ai-agent-workforce
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/yokebots/yokebot
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/rjmurillo/ai-agents
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/wieslawsoltes/SemanticDiff
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/nilbuild/diffity
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/david-spies/ai-agent-builder
- 2026-06-26 heartbeat 21:56Z: Source checked: https://github.com/777genius/agent-teams-ai
- 2026-06-26 heartbeat 21:56Z: Source checked but skipped as duplicate: https://github.com/elliot35/deterministic-agent-control-protocol
- 2026-06-26 heartbeat 21:56Z: Source checked but skipped as duplicate: https://github.com/AgentOps-AI/agentops
- 2026-06-26 heartbeat 21:56Z: Source checked but skipped as duplicate: https://github.com/Picrew/awesome-agent-harness
- 2026-06-26 heartbeat 21:56Z: Source checked but skipped as tutorial-style: https://github.com/FareedKhan-dev/Multi-Agent-AI-System
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/oktsec/oktsec
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/HeadyZhang/agent-audit
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/ucsandman/DashClaw
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/rinadelph/Agent-MCP
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/danny-avila/LibreChat
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/HumanSecurity/human-verified-ai-agent
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/agree-able/room
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/agentuniverse-ai/agentUniverse
- 2026-06-26 heartbeat 22:07Z: Source checked: https://github.com/nkuhanas/Parley
- 2026-06-26 heartbeat 22:07Z: Source checked but skipped as duplicate: https://github.com/microsoft/agent-governance-toolkit
- 2026-06-26 heartbeat 22:07Z: Source checked but skipped as duplicate: https://github.com/luckyPipewrench/pipelock
- 2026-06-26 heartbeat 22:07Z: Source checked but skipped as duplicate: https://github.com/elliot35/deterministic-agent-control-protocol
- 2026-06-26 heartbeat 22:07Z: Source checked but skipped as lower-fit implementation sample: https://github.com/sap156/Agent-to-Agent-A2A-Protocol-Implementation
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/clay-good/agent-replay
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/ixchio/agent-vcr
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/alphadl/AgentHER
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/ModernOps888/agentlens
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/certainly-param/tracelens
- 2026-06-26 heartbeat 22:19Z: Source checked: https://github.com/cornhusk39/agentprobe
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/Siddhant-K-code/agent-trace
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/ASSERT-KTH/reproducible-trajectories
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/LMCache/lmcache-agent-trace
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/agentreplay/agentreplay
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/callstack/agent-device
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/hidai25/eval-view
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/aws-samples/sample-why-agents-fail
- 2026-06-26 heartbeat 22:19Z: Source checked but skipped as duplicate: https://github.com/xlang-ai/AgentTrek
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/sqliteai/sqlite-memory
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/sqliteai/sqlite-agent
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/sqliteai/adam
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/baneeishaque/ai-agent-rules
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/microsoft/Trace
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/fernandoabolafio/repobase
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/aiming-lab/SimpleMem
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/Gentleman-Programming/engram
- 2026-06-26 heartbeat 22:30Z: Source checked: https://github.com/EverMind-AI/EverOS
- 2026-06-26 heartbeat 22:30Z: Source checked but skipped as duplicate: https://github.com/cursor/agent-trace
- 2026-06-26 heartbeat 22:30Z: Source checked but skipped as duplicate: https://github.com/neuledge/context
- 2026-06-26 heartbeat 22:30Z: Source checked but skipped as duplicate: https://github.com/rohitg00/agentmemory
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/misaelzapata/memoirs
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/Dataojitori/nocturne_memory
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/caura-ai/memclaw-cross-fleet-gov
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/van-reflect/Reflect-Memory
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/CaviraOSS/OpenMemory
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/RecallWorks/Recall
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/danielsimonjr/memory-mcp
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/RyjoxTechnologies/Octopoda-OS
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/yunhaichu/project-cognition-system
- 2026-06-27 heartbeat 04:15Z: Source checked: https://github.com/shahzebqazi/mhn-ai-agent-memory
- 2026-06-27 heartbeat 04:15Z: Source checked but skipped as duplicate: https://github.com/mem0ai/mem0
- 2026-06-27 heartbeat 04:15Z: Source checked but skipped as duplicate: https://github.com/IAAR-Shanghai/Awesome-AI-Memory
- 2026-06-27 heartbeat 04:15Z: Source checked but skipped as duplicate: https://github.com/SalesforceAIResearch/MCP-Universe
- 2026-06-27 heartbeat 04:15Z: Source checked but skipped as duplicate: https://github.com/ipiton/agent-memory-mcp
- 2026-06-27 heartbeat 04:15Z: Source checked but skipped as broad assistant platform for this pass: https://github.com/agentscope-ai/QwenPaw

## Run Log

- 2026-06-26: Verified `C:\Users\corbe\Thomas` exists and is a git repo. Read the top of `docs/THOMAS_BIBLE.md`; preserved trust order: Bible, live code, tests, other docs, then STATUS.md. Repo was already dirty, so this run only created `plans/thomas/AGENTIC_AI_FEATURE_RESEARCH_QUEUE.md` and did not touch Thomas code, commit, or push.
- 2026-06-26: Added 12 new raw research entries. Duplicate skips: 0. Next query ideas: agent state blackboard repos, code-agent eval harnesses, agent run replay/trace viewers, secure tool sandbox projects, AI reviewer/coordinator workflow repos, and self-improving skill libraries.
- 2026-06-26 heartbeat 14:23Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 10 new raw research entries. Duplicate URL skips: 0. Maintenance/staleness skips: 1 (`microsoft/autogen`). Next query ideas: deterministic agent replay systems, MCP permission brokers, SWE-bench pipeline repos, agent memory compaction libraries, PR-review agent frameworks, local-first trace viewers, and tool-call policy engines.
- 2026-06-26 heartbeat 14:25Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 9 new raw research entries. Duplicate URL skips: 0. Next query ideas: agent permission UIs, memory conflict resolution, browser trace compression, autonomous PR review agents, MCP server marketplaces, and benchmark-to-workboard adapters.
- 2026-06-26 heartbeat 14:30Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 9 new raw research entries. Duplicate URL skips: 0. Staleness skips: 1 (`continuedev/continue`). Next query ideas: repo-map algorithms, agent run UIs, policy-as-code for tool approval, code search MCP servers, issue triage agents, and agent-generated PR review rubrics.
- 2026-06-26 heartbeat 14:32Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 2. Next query ideas: browser trace viewers by name (`BrowserTrace`, `webagent-cloud`), OpenTelemetry-native agent tracing, code-search MCP servers, issue duplicate-detection agents, and local transcript monitors for Codex/Claude workers.
- 2026-06-26 heartbeat 14:40Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 10 new raw research entries. Duplicate URL skips: 0. Staleness skips: 1 (`Not-Diamond/self-care`). Next query ideas: agent firewall benchmark suites, MCP gateway comparisons, A2A registry implementations, skill supply-chain scanners, prompt-injection benchmark repos, and agent failure-mining systems.
- 2026-06-26 heartbeat 14:43Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 9 new raw research entries. Duplicate URL skips: 1. Non-repo skips: 2. Next query ideas: GitHub Actions agent workflow repos, CI failure-analysis agents, codebase-memory MCP variants, production incident agents, and agent loop/feedback-loop detectors.
- 2026-06-26 heartbeat 14:49Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Non-repo skips: marketplace and article examples. Next query ideas: agentic GitHub workflow source repos, production incident agent benchmarks, reviewer-loop CLI comparisons, CI log compression algorithms, and SRE agent memory stores.
- 2026-06-26 heartbeat 15:00Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 6 new raw research entries. Duplicate URL skips: 3. Non-repo skips: docs/articles/forums/marketplace/social pages. Next query ideas: Agent Client Protocol servers, ACP-compatible local clients, GUI-agent safety benchmarks, desktop automation permission models, and skill provenance manifest tools.
- 2026-06-26 heartbeat 15:03Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 6 new raw research entries. Duplicate URL skips: 2. Non-repo skips: protocol docs/issues and survey pages. Next query ideas: ACP adapter implementations for specific agents, GUI-agent red-team datasets, accessibility-tree command wrappers, mobile-app agent QA, and sandboxed desktop session recorders.
- 2026-06-26 heartbeat 15:06Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Non-repo skips: docs/articles/issues/topic pages. Next query ideas: coding-review-agent-loop source if published, Lightpanda semantic browser agent APIs, GitTaskBench implementation repo, AIRTBench red-team agent follow-up, and ACP server adapters for Thomas-native workers.
- 2026-06-26 heartbeat 15:13Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 2. Non-repo skips: mirrors/social/docs/package pages. Next query ideas: MCP browser engines beyond Lightpanda, OpenACP bridge source if available, agent replay/session recorder implementations, and repo-aware benchmark harness comparisons.
- 2026-06-26 heartbeat 15:20Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Non-repo skips: docs/changelog/topic/social/arXiv/marketing pages. Next query ideas: concrete replay-layer repos if they surface, AgentRR implementation code, browser harness direct comparisons, ACP bridge security reviews, and harness-engineering ranking criteria.
- 2026-06-26 heartbeat 15:33Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 5. Non-repo skips: Reddit/arXiv/YouTube/docs/topic/discussion pages. Next query ideas: agent replay storage schemas, browser MCP security comparisons, run-forking observability tools, local LLM proxy dashboards, and replay-to-eval conversion systems.
- 2026-06-26 heartbeat 15:39Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 5. Non-repo skips: social/package/video/news/discussion pages. Next query ideas: context receipt schemas, agent secret-handling policy engines, PR replay datasets, and observability-to-eval conversion pipelines.
- 2026-06-26 heartbeat 15:47Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Non-repo skips: docs/blog/social/video/news/research pages. Next query ideas: concrete AGENT.md/AGENTS.md interoperability repos, GitHub agentic workflow source examples, agent policy DSL comparisons, and local docs-cache MCP benchmarks.
- 2026-06-26 heartbeat 16:02Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Non-repo skips: product/topic/paper/blog/social/video pages. Next query ideas: checkpoint schema comparisons, worker merge-back UX, memory conflict resolution repos, runbook-to-agent conversion systems, and approval-gateway threat models.
- 2026-06-26 heartbeat 16:17Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Non-repo skips: marketing/topic/paper/social/video/docs/package pages. Next query ideas: agent terminal multiplexers with audit logs, SCM feedback routers, schema-enforced deliverable MCP servers, and policy DSL red-team benchmarks.
- 2026-06-26 heartbeat 16:36Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Related skips: memory/search/reasoning catalogs deferred. Next query ideas: code-agent benchmark executors, self-healing task loop source repos, worker-cost telemetry, and replay-to-regression pipelines.
- 2026-06-26 heartbeat 17:00Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Related skips: durable-execution examples and HumanLayer held for deeper status review. Next query ideas: OAuth-for-agent threat models, tool marketplace governance, scenario-test fixtures for coding agents, and deterministic route replay.
- 2026-06-26 heartbeat 17:24Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Related skips: extra Claude Code subagent catalogs deferred. Next query ideas: front-end agent state protocols, Claude Code role-template taxonomies, parallel attempt selection metrics, and autonomous engineer UX comparisons.
- 2026-06-26 heartbeat 17:34Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: memory conflict resolution, temporal fact invalidation, memory eval adapters, and graph memory for workboard dependencies.
- 2026-06-26 heartbeat 17:40Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: runtime monitors for live tool calls, red-team suites for code agents, sandbox composition scores, and trajectory eval adapters for Thomas traces.
- 2026-06-26 heartbeat 17:49Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: durable tool-call journal schemas, incident-to-PR remediation agents, agentic SRE benchmarks, and Temporal/DBOS/ReState tradeoff comparisons.
- 2026-06-26 heartbeat 17:57Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: AG-UI portal adapters, A2A capability cards, agent identity/trust protocols, and protocol conformance tests for Thomas workers.
- 2026-06-26 heartbeat 18:07Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: code-intelligence benchmark comparisons, symbol-card schemas, context-budget policies, and repo graph freshness strategies.
- 2026-06-26 heartbeat 18:16Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: GUI-agent action schemas, mobile QA safety gates, browser benchmark normalization, and screenshot evidence capture for Thomas workers.
- 2026-06-26 heartbeat 18:27Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 5. Next query ideas: runtime guard comparative matrix, skill supply-chain scanners, MCP proxy policy enforcement, and agent inventory/AIBOM workflows.
- 2026-06-26 heartbeat 18:35Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: workflow DSL schema comparison, prompt-program optimization evals, visual workflow builders, and replayable YAML worker specs.
- 2026-06-26 heartbeat 18:43Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 3. Next query ideas: OpenTelemetry semantic conventions for worker events, trace-to-workboard issue grouping, cost attribution graphs, and local coding-agent trace hooks.
- 2026-06-26 heartbeat 18:52Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 1. Next query ideas: budget enforcement gates, token-ledger schemas, live worker top views, and OpenTelemetry cost-attribution attributes.
- 2026-06-26 heartbeat 19:05Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 1. Next query ideas: quota-aware worker schedulers, provider failover scoring, semantic cache safety, and budget-stop UX patterns.
- 2026-06-26 heartbeat 19:13Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Next query ideas: cache invalidation policies, local-model routing benchmarks, route replay tests, and semantic-cache provenance UX.
- 2026-06-26 heartbeat 19:29Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Next query ideas: router telemetry schemas, KV-cache safety for agents, model-capability scoring, and replayable route-evaluation datasets.
- 2026-06-26 heartbeat 19:41Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 5. Next query ideas: benchmark-to-workboard issue conversion, skill-discovery regression suites, MCP server scorecards, and browser-action replay traces.
- 2026-06-26 heartbeat 19:50Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 7. Next query ideas: eval-failure clustering, agent trajectory compression, task artifact provenance, and MCP/tool contract fuzzing.
- 2026-06-26 heartbeat 20:01Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 2. Next query ideas: artifact bundle schemas, MCP fuzz corpus generation, contract-test authoring UX, and failure-cluster dashboards.
- 2026-06-26 heartbeat 20:08Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 1. Next query ideas: eval cookbook comparisons, skill packaging trust metadata, LLM-judge drift dashboards, and workboard issue synthesis from eval traces.
- 2026-06-26 heartbeat 20:28Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 2. Next query ideas: skill import compatibility tests, skill signing UX, marketplace moderation workflows, and trust-label propagation into worker prompts.
- 2026-06-26 heartbeat 20:39Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 6. Next query ideas: prompt trust-label rendering, skill dependency lockfiles, signed skill publishing flows, and skill vulnerability disclosure queues.
- 2026-06-26 heartbeat 20:52Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 3. Next query ideas: agent identity wallets, skill provenance policy language, supply-chain graph queries for skills, and trust-aware prompt assembly.
- 2026-06-26 heartbeat 21:06Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 4. Next query ideas: agent identity credential exchange, authorization simulation UX, trust-domain isolation, and prompt-time policy explanations.
- 2026-06-26 heartbeat 21:19Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 6. Next query ideas: scoped OAuth consent UX, delegated account recovery, MCP auth proxy comparison, and policy-denial explanation templates.
- 2026-06-26 heartbeat 21:32Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 2. Next query ideas: OAuth consent copy patterns, auth proxy compatibility matrices, policy-denial UX tests, MCP gateway IAM comparisons, and deterministic block evidence schemas.
- 2026-06-26 heartbeat 21:46Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 8 new raw research entries. Duplicate URL skips: 0. Next query ideas: authorization graph diff UX, worker identity lifecycle, agent workforce compliance logs, portal readiness scanners, and policy-simulation fixtures.
- 2026-06-26 heartbeat 21:56Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 7 new raw research entries. Duplicate URL skips: 3. Next query ideas: inter-agent message audit logs, local PR review surfaces, agent team IaC templates, portable skill/profile builders, and semantic patch review graphs.
- 2026-06-26 heartbeat 22:07Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 9 new raw research entries. Duplicate URL skips: 3. Next query ideas: signed worker transcript schemas, agent security scanners by framework, action idempotency ledgers, A2A identity proof UX, and recovery-first state stores.
- 2026-06-26 heartbeat 22:19Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 6 new raw research entries. Duplicate URL skips: 8. Next query ideas: trace schema normalization, cassette redaction policies, failed-run clustering, local SQLite trace stores, and model-swap regression replay.
- 2026-06-26 heartbeat 22:30Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 9 new raw research entries. Duplicate URL skips: 3. Next query ideas: memory privacy controls, repo-context MCP benchmarks, SQL-native agent runtimes, Markdown memory conflict resolution, and trace-to-optimization feedback loops.
- 2026-06-27 heartbeat 04:15Z: Verified `C:\Users\corbe\Thomas` is still a git repo and re-read the Bible header/trust order. Appended 10 new raw research entries. Duplicate URL skips: 4. Next query ideas: memory redaction benchmark suites, user-editable memory UX, fleet-scoped memory attacks, recall rollback tests, and factual-state conflict-resolution harnesses.
