# OpenClaw Architecture Overview

- id: `1771907866-openclaw-architecture-overview`
- category: `competitive-research`
- source: https://github.com/openclaw/openclaw
- created_ts_utc: 1771907866
- tags: openclaw, ai-agent, architecture, competitive-research, skills, tool-policy, failover, workflows

## Summary
Complete architecture research on OpenClaw AI agent runtime. Covers skills system (markdown-first), tool policy groups, Lobster pipeline engine, model failover with exponential backoff, browser automation, security model, multi-agent routing, and session persistence.

## Content
# OpenClaw (formerly Clawdbot/Moltbot) Architecture Research

OpenClaw is a free, open-source autonomous AI agent runtime (TypeScript, MIT license) created by Peter Steinberger. 100K+ GitHub stars. Runs locally, connects to messaging platforms as UI.

## Key Differentiator
OpenClaw is a RUNTIME, not a library. You install it, configure it, and it runs continuously. Unlike LangChain/CrewAI/AutoGen (developer libraries requiring Python code), OpenClaw is an end-user product.

## Architecture Pattern: Hub-and-Spoke
- WebSocket Gateway (port 18789) as central control plane
- Channel adapters normalize platform-specific formats into unified InboundContext
- Gateway routes inbound -> agent -> replies back to originating channel
- Deterministic routing: (channel, accountId, peer) -> agentId

## Skills System (Markdown-First)
- Skills are NOT compiled code -- they are SKILL.md files with YAML frontmatter
- Three types: bundled, managed (from ClawHub registry), workspace (custom)
- Live at ~/.openclaw/workspace/skills/<skill>/SKILL.md
- Two-layer separation: Tools (executable code) vs Skills (LLM instructions)
- Context injection: skill metadata extracted into compact XML list (~97 chars/skill) in system prompt
- ClawHub registry: 5,705 community skills across 26+ domains

## Tool Policy Groups (Cascading Deny/Allow)
- Named groups: group:fs, group:automation, group:runtime, group:git, group:db
- Profile-level defaults, per-agent overrides
- Separate from skills: skills teach LLM how, tool policies enforce what
- Dangerous tools explicitly listed: gateway, cron, sessions_spawn, sessions_send

## Lobster Pipeline Engine
- Typed, local-first macro engine for composable workflows
- YAML/JSON workflow definitions with steps, env, conditions
- Approval gates: side effects halt until explicitly approved
- Resumable with token (don't re-run completed steps)
- Step references: .stdout for data flow
- Deterministic execution (no model orchestration between steps)

## Model Failover
- Session-pinned auth profiles (tried first, warm caches)
- Two-tier: profile rotation -> model fallback
- Rate limit: short cooldown with Retry-After header
- Billing failure: 5hr initial, doubles per failure, caps at 24hr
- On success: clear backoff counter
- Manual override: /model ...@<profileId>

## Browser Automation
- Chrome DevTools Protocol (CDP) for control
- Three modes: Extension Relay, Managed instance, Remote CDP
- Playwright on top of CDP for actions
- Millisecond snapshots via direct CDP

## Security Model (Personal Assistant, Not Multi-Tenant)
- DM access: pairing (default), allowlist, open, disabled
- Tool policy framework: deny/allow by group + individual
- Sandbox modes: none, ro, rw workspace access
- Gateway auth: token (recommended), password, trusted proxy
- Session isolation: global (default) or per-channel-peer

## Multi-Agent Routing
- No cross-talk unless explicitly enabled
- Per-agent workspace with own SOUL.md, AGENTS.md, USER.md
- Session store isolation under ~/.openclaw/agents/<agentId>/sessions/
- Routing by (channel, accountId, peer) via bindings array

## Configuration
- Central ~/.openclaw/openclaw.json with live reload
-  directive for multi-file configs
- Plugin types: channel, tool, provider, memory
- Workspace bootstrap files: AGENTS.md, SOUL.md, USER.md, TOOLS.md, HEARTBEAT.md

## Session Persistence
- JSONL append-only transcripts (crash-safe)
- Durable memory written to markdown files
- Compaction: silent "write memory now" turn before context pruning
- Files are source of truth

## Queue-Based Message Interruption
- After each tool call: check for queued inbound messages
- If message waiting: defer remaining tool calls to next turn
- Reduces latency and improves interactive responsiveness
