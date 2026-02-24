# OpenClaw Patterns Applied to Thomas

- id: `1771907866-openclaw-patterns-applied-to-thomas`
- category: `competitive-research`
- source: https://github.com/openclaw/openclaw
- created_ts_utc: 1771907866
- tags: openclaw, thomas, upgrades, tool-policy, failover, workflows, architecture

## Summary
Maps 5 specific OpenClaw architectural patterns to Thomas improvement opportunities: tool policy groups, exponential backoff cooldowns, workflow approval gates, message interruption, and markdown-first skills.

## Content
# OpenClaw Patterns Applicable to Thomas

## Pattern 1: Tool Policy Groups
OpenClaw uses named tool groups (group:fs, group:automation, group:runtime) with cascading deny/allow.
Thomas has 6 boolean toggles (allow_shell, allow_file_write, allow_network, allow_browser, allow_channels, allow_git) in AdvancedToolsPrefs that are dead UI toggles -- never wired to PolicyEngine.
FIX: Add DenyToolGroupRule to thomas/policy/rules.py, wire preferences booleans through PolicyConfig.

## Pattern 2: Exponential Backoff Cooldowns
OpenClaw pins provider per session, uses exponential backoff (5min base, doubles, 24hr cap), separates rate-limit from auth-failure cooldowns.
Thomas has flat 300s cooldown for ALL failure types in llm.py. No distinction between rate limit and billing failure. No exponential backoff.
FIX: Replace _FAILOVER_COOLDOWN_UNTIL dict with _ProviderCooldown dataclass. Add session pinning.

## Pattern 3: Workflow Approval Gates
OpenClaw halts side-effects in workflow steps until human approval. Resumable with token.
Thomas WorkflowRunner executes all steps end-to-end with no pause points. ApprovalBroker exists but only at tool-call level.
FIX: Add approval_required field to _StepSpec in workflows.py. Gate with ApprovalBroker before executing flagged steps.

## Pattern 4: Message Interruption
OpenClaw checks for queued messages after each tool call. Defers remaining calls to next turn.
Thomas agent loop executes all pending tool calls via asyncio.as_completed with no interrupt check.
FIX: Add message_queue to AgentLoop. Check between tool results. Cancel remaining on user interrupt.

## Pattern 5: Markdown-First Skills (Future)
OpenClaw skills are SKILL.md files, not compiled code. Injected as compact XML in system prompt.
Thomas uses 22 compiled Python plugin modules. Much heavier to create/modify.
FUTURE: Consider markdown skill format for user-defined agent capabilities.
