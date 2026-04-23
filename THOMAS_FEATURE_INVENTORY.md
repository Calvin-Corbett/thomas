# Thomas Repository - Exhaustive Feature Inventory

## Overview
This inventory catalogs all major features and subsystems across Thomas (AI-first workspace platform). Thomas uses a tiered architecture: CORE (7 modules) → EXT (9 modules) → INFRA (6 modules) → SUPPORT (160+ marketplace modules).

---

## MEMORY FEATURES

### Location: `thomas/memory/`
**34 Python files** implementing unified memory engine with episodic, semantic, and graph-based storage.

#### Core Memory Files:
1. **`__init__.py`** - MemoryEngine facade with legacy fallback support
2. **`episodic.py`** - Episode and EpisodeStore base classes
3. **`episodic_embeddings.py`** - Vector embeddings for episodic memory
4. **`episodic_retrieval.py`** - Retrieval pipeline for episodes
5. **`episodic_store.py`** - Persistent storage for episodes
6. **`store.py`** - Storage layer (SQLite log, blob store, meta DB, derived DB)
7. **`graph.py`** - Knowledge graph with entity extraction & triples
8. **`indexer.py`** - Memory index maintenance and rebuilding
9. **`search.py`** - Memory search helpers for CLI/runtime
10. **`listing.py`** - Memory snapshot/listing for CLI
11. **`retrieval.py`** - Multi-source search, reranking, context packing
12. **`compaction.py`** - Memory compaction helpers for CLI
13. **`curator.py`** - Background curator for durable memory promotion
14. **`compiler.py`** - Delta ingestion & nightly base rebuilds
15. **`embedder.py`** - HashEmbedder (fallback) + DenseEmbedder (sentence-transformers)
16. **`rerank.py`** - Two-tier reranking system for retrieval candidates
17. **`summarization.py`** - Memory summarization (placeholder)
18. **`thought_signatures.py`** - Thought signature tracking
19. **`autonomy.py`** - Unified autonomy memory runtime

#### Memory v2 (Modern Implementation):
**10 files** - Upgraded memory fabric with contradiction detection and better scoring.

1. **`v2/fabric.py`** - Memory fabric: unified episodic + semantic + profile storage
2. **`v2/fabric_core.py`** - SQLite-backed hybrid memory (episodic + semantic + profile)
3. **`v2/fabric_retrieval.py`** - Retrieval, packing, diagnostics mixin
4. **`v2/fabric_compat.py`** - Compatibility shim for legacy call sites
5. **`v2/fabric_utils.py`** - MemorySettings, tokenization, overlap boost
6. **`v2/db.py`** - Wrapped sqlite3.Cursor with serialized fetch operations
7. **`v2/schema.py`** - Database schema definitions
8. **`v2/types.py`** - RetrievalItem, RetrievalResult types
9. **`v2/scoring.py`** - Deterministic salience scoring with age decay
10. **`v2/token.py`** - Cheap token estimation (1 token ~ 4 chars)
11. **`v2/contradictions.py`** - Contradiction signal detection
12. **`v2/contradiction_review.py`** - Contradiction severity routing & upsert
13. **`v2/profile_hints.py`** - Profile hint extraction

#### Memory Features Summary:
- **Episodic Memory**: Full conversation/action history with embeddings
- **Semantic Memory**: Extracted facts, entities, relationships
- **Graph Memory**: Entity extraction, triples, knowledge graph queries
- **Profile Memory**: User hints and persona tracking
- **Search**: Hybrid (keyword + vector), reranking, semantic search
- **Embeddings**: Dense + hash-based fallback
- **Summarization**: LLM-based context compaction
- **Indexer**: Nightly rebuilds, delta ingestion
- **Contradiction Detection**: Flagging conflicting facts
- **Token Budgeting**: Cheap estimation for context window management

---

## AUTONOMY FEATURES

### Location: `thomas/autonomy/` + `thomas/marketplace/autonomy/`

#### Root Module (`thomas/autonomy/`):
1. **`scheduler.py`** - Local tz-aware cron parsing (moved to marketplace)

#### Marketplace Implementation (`thomas/marketplace/autonomy/` - 16 files):

1. **`engine.py`** - AutonomyEngine: background runner for autonomous jobs
2. **`scheduler.py`** - Job scheduling with cron support
3. **`store.py`** - SQLite persistence for autonomy state
4. **`models.py`** - Job state, policy, error types (AutonomyError, RetryPolicy)
5. **`policy.py`** - AutonomyPolicy: permission checking, mode enforcement
6. **`agents.py`** - PlannerAgent: plan validation, risk detection
7. **`executor.py`** - ExecutorAgent: converts validated plans to job queues
8. **`adapters.py`** - ChatAdapter: interface with chat systems
9. **`workflows.py`** - Workflow-first execution patterns
10. **`nl_workflow_compiler.py`** - NL→workflow compilation
11. **`media_agents.py`** - OpenAI-compatible media client for multimodal
12. **`mode_policy.py`** - Autonomy mode enforcement
13. **`api.py`** - REST API + UI routes (aiohttp)
14. **`plugin.py`** - Plugin installation for autonomy
15. **`ui/`** - UI components for autonomy
16. **`integration_hooks.py`** - Integration with chat/agent systems

#### Autonomy Features Summary:
- **Background Jobs**: Async job execution with cron scheduling
- **Plan Validation**: Deterministic risk checking for autonomous actions
- **Execution**: Job queuing and monitoring
- **Mode Policy**: Autonomy levels (off, guided, semi-auto, fully-auto)
- **Human Loop**: Approval broker for sensitive operations
- **Workflow Compilation**: Natural language → executable workflows
- **Scheduling**: Cron expressions with local timezone support
- **Media**: Multimodal support via OpenAI-compatible APIs
- **Persistence**: SQLite-backed job/state tracking

---

## SCHEDULER FEATURES

### Location: `thomas/core/scheduler.py` + `thomas/marketplace/scheduler_deep/`

#### Core Scheduler (`thomas/core/scheduler.py`):
- Local timezone-aware time management
- Cron expression parsing helpers
- Atomic JSON write operations for configuration

#### Advanced Scheduler (`thomas/marketplace/scheduler_deep/` - 20 files):

1. **`scheduler.py`** - Main scheduler with job management and event loop
2. **`cron.py`** - CronExpression parser and evaluator
3. **`triggers.py`** - CalendarTrigger, CompoundTrigger, MissedFirePolicy
4. **`dag.py`** - DAGScheduler with dependency management
5. **`distributed.py`** - Distributed scheduling with leader election & failover
6. **`executor.py`** - JobExecutor with thread/process pool support
7. **`persistence.py`** - JobStore (SQLite + memory implementations)
8. **`monitoring.py`** - Health checks, job stats, metrics collection
9. **`rate_control.py`** - ExecutionWindow, BlackoutPeriod, throttling
10. **`calendar.py`** - BusinessCalendar, working hours/days
11. **`models.py`** - JobStatus, JobHistory, Calendar types
12. **`exceptions.py`** - SchedulerException hierarchy
13. **`tools.py`** - CLI tools: create/list/execute jobs & DAGs
14. **Test files (6)** - Comprehensive testing for cron, DAG, distributed, etc.

#### Scheduler Features Summary:
- **Job Scheduling**: Cron expressions, one-shot, recurring
- **DAG Support**: Dependency-based job execution
- **Distributed**: Leader election, job locking, failover
- **Rate Control**: Blackout periods, execution windows
- **Business Calendar**: Working days/hours, holiday support
- **Monitoring**: Metrics, health checks, job history
- **Persistence**: SQLite with fallback to in-memory
- **Executor**: Thread pool + process pool execution
- **Triggers**: Calendar, interval, compound, dependency-based

---

## BROWSER AUTOMATION FEATURES

### Location: `thomas/browser/` (221 files)

#### Core Browser Command Registry:
1. **`p001_browser_command_registry_scaffold.py`** - Base registry with error codes

#### Navigation & Interaction (P002-P008):
1. **`p002_browser_action_navigate_and_open.py`** - Navigate, open URLs
2. **`p003_browser_action_click.py`** - Click targets with coordinate mapping
3. **`p004_browser_action_type_and_press.py`** - Type text, press keys
4. **`p005_browser_action_hover_and_focus.py`** - Hover, focus elements
5. **`p006_browser_action_scroll_and_scroll_into_view.py`** - Viewport scroll, into-view
6. **`p007_browser_action_wait_conditions.py`** - Wait for conditions (selector, navigation)

#### Artifact Capture (P009-P017):
1. **`p009_browser_artifact_screenshot.py`** - Screenshot capture to disk
2. **`p010_browser_artifact_pdf_export.py`** - PDF export with natural sorting
3. **`p011_browser_artifact_dom_snapshot.py`** - DOM snapshot capture
4. **`p012_browser_artifact_accessibility_snapshot.py`** - Accessibility tree snapshot
5. **`p013_browser_telemetry_console_stream.py`** - Console log capture
6. **`p014_browser_telemetry_network_requests.py`** - Network request telemetry
7. **`p015_browser_telemetry_response_body_fetch.py`** - Response body fetching
8. **`p016_browser_data_cookies_export_and_import.py`** - Cookie export/import
9. **`p017_browser_data_storage_snapshot.py`** - localStorage/sessionStorage snapshot

#### Tab & Profile Management (P018-P019):
1. **`p018_browser_tab_management.py`** - Tab creation, switching, closing
2. **`p019_browser_profile_create_delete_list.py`** - Browser profile management

#### Lifecycle & Tracing (P020-P023):
1. **`p020_browser_lifecycle_start_stop_restart.py`** - Browser start/stop/restart
2. **`p021_browser_download_tracking.py`** - Download file tracking
3. **`p022_browser_upload_helper.py`** - File upload helpers
4. **`p023_browser_trace_start_stop_export.py`** - Trace recording (performance)

#### Integration (P024-P026):
1. **`p024_browser_error_normalization.py`** - Error normalization & categorization
2. **`p025_browser_json_output_contract.py`** - JSON schema validation
3. **`p026_browser_integration_into_top_level_cli.py`** - CLI integration

#### Workflows:
1. **`workflow_runtime.py`** - Profile & case file management
2. **`workflows/registry.py`** - Runtime workflow registry (170 profiles)
3. **`workflows/workflow_profile_*.py`** - 170 predefined browser automation profiles

#### Browser Features Summary:
- **Navigation**: URL navigation, tab management
- **Interaction**: Click, type, hover, scroll, focus
- **Screenshots**: Full-page, element, region screenshots
- **Artifacts**: PDF export, DOM snapshots, accessibility trees
- **Telemetry**: Console logs, network requests, response bodies
- **Data**: Cookies, localStorage, sessionStorage snapshots
- **Profiles**: Browser profile creation/management
- **Lifecycle**: Start, stop, restart, restart-with-args
- **Downloads**: Download file tracking and retrieval
- **Uploads**: File upload helpers
- **Traces**: Performance tracing via Playwright
- **Workflows**: 170 predefined automation profiles

---

## CHAT FEATURES

### Location: `thomas/chat/` (6 files)

1. **`__init__.py`** - Brain/Orchestrator architecture exports
2. **`conversation.py`** - ConversationManager with copy-on-write semantics
3. **`event_stream.py`** - Unified NDJSON event dispatcher
4. **`memory_layers.py`** - Three-layer memory coordinator (MemoryContext, MemoryCoordinator)
5. **`session_store.py`** - Persistent session storage with auto-save (SessionMeta, SessionStore)
6. **`thinking.py`** - ThinkingBlock, ThinkingTracker for extended cognition

#### Chat Features Summary:
- **Multi-turn Conversation**: Message history, context tracking
- **Copy-on-Write**: Efficient conversation branching
- **Event Streaming**: NDJSON-based event dispatch
- **Memory Layers**: Episodic + semantic + profile (3-tier)
- **Session Persistence**: Auto-saving conversations
- **Thinking Blocks**: Extended thinking/reasoning support

---

## AGENT FEATURES

### Location: `thomas/agent/` (36 files)

#### Core Loop & Execution:
1. **`loop.py`** - Main async ReAct agent loop with streaming
2. **`loop_core.py`** - Loop initialization, message building
3. **`loop_execution.py`** - Streaming, tool execution, token management
4. **`loop_planning.py`** - Response planning, routing, main loop
5. **`loop_tool_exec.py`** - Tool execution helpers
6. **`loop_tools.py`** - Tool selection, parsing, execution
7. **`loop_streaming.py`** - Streaming, token management, library integration
8. **`loop_completion.py`** - Post-loop completion, quality validation

#### Planning & Execution:
1. **`execution_plan.py`** - PlanStep, ExecutionPlan primitives
2. **`plan_mode.py`** - Plan mode support (show-before-do)
3. **`dispatch.py`** - DispatchDecision router (background delegation)
4. **`chat_dispatcher.py`** - /api/chat → task-manager dispatch bridge

#### Context & State:
1. **`context_tracker.py`** - ConversationContext, contextual awareness
2. **`conversation.py`** - TurnRecord, ConversationIntelligence for coherence
3. **`context_compaction.py`** - LLM-based context summarization
4. **`checkpointing.py`** - Crash recovery (placeholder for bytecode implementation)

#### Policy & Approval:
1. **`approval.py`** - PendingApproval, ApprovalBroker (async, stdlib-only)
2. **`guarded_tools.py`** - Policy evaluation, approval, tool execution, redaction
3. **`policy_runtime.py`** - Policy runtime (placeholder)
4. **`guidance.py`** - Startup guidance discovery

#### Response & Tone:
1. **`response_tone.py`** - Response tone helpers, testing-visibility utilities
2. **`project_guidelines.py`** - Project-scoped guideline discovery
3. **`project_instructions.py`** - Project instruction loading

#### Intelligence & Hooks:
1. **`intelligence.py`** - ConversationalIntelligenceLayer integration
2. **`integration_hooks.py`** - Hook registry for extension points
3. **`hooks_registry.py`** - Hook management

#### Support:
1. **`loop_helpers.py`** - Helper utilities for loop execution
2. **`prompt_templates.py`** - Prompt template management
3. **`swarm.py`** (44KB) - Multi-agent swarm orchestration
4. **`__init__.py`** - Thomas AI Agent Framework exports

#### Agent Features Summary:
- **ReAct Loop**: Async, streaming, with token budgeting
- **Tool Execution**: Parallel tool calls, parsing, execution
- **Context Compaction**: Automatic summarization of old turns
- **Checkpointing**: Crash recovery (bytecode-backed)
- **Approvals**: Broker for sensitive operations
- **Guarded Tools**: Policy-aware execution with redaction
- **Planning**: Show-before-do mode with plan validation
- **Dispatch**: Background task delegation
- **Conversation Intelligence**: Multi-turn coherence
- **Thinking Blocks**: Extended reasoning support
- **Swarm**: Multi-agent orchestration

---

## MODELS & CAPABILITIES

### Location: `thomas/models/` (9 files)

1. **`__init__.py`** - Model discovery, catalog helpers
2. **`batching.py`** - OpenAI-compatible batch API helpers (xAI-first)
3. **`capabilities.py`** - Provider capability registry
4. **`chat_capabilities.py`** - Chat-surface control capabilities
5. **`chat_controls.py`** - UiControlResolution for conversation-driven UI
6. **`discovery.py`** - DiscoveredModel, ModelsHandshake for onboarding
7. **`protocol.py`** - ToolSmokeResult, ModelValidationReport
8. **`local_recommendations.py`** - Hardware-aware local model recommendations
9. **`switching.py`** - Natural-language model switch parsing

#### Models Features Summary:
- **Multi-Provider**: OpenAI, xAI, local, custom
- **Batch API**: OpenAI-compatible batch processing
- **Capability Registry**: Per-provider feature detection
- **Chat Controls**: UI control capability management
- **Model Discovery**: Automatic model detection & onboarding
- **Validation**: Tool smoke tests for compatibility
- **Local Recommendations**: Hardware-aware suggestions
- **Model Switching**: Natural language model selection in chat

---

## CHANNEL & INTEGRATION FEATURES

### Location: `thomas/channels/` (4 files) + `thomas/integrations/` (41 files)

#### Channels:
1. **`p084_channel_resolve_command.py`** - Command resolution
2. **`p087_channel_auth_validation_helper.py`** - OAuth/auth validation
3. **`p090_channel_webhook_bridge_adapter.py`** - Webhook adapter

#### Integrations (41 files):
**Supported Platforms**:
- **Slack**: Full integration (channels, messaging, files, users, OAuth)
- **Discord**: Bridge runtime with history, lifecycle, support
- **Google Workspace**: Gmail, Calendar, Drive, Docs
- **Microsoft Teams**: Webhook provider
- **Google Chat**: Webhook provider
- **Telegram**: Bot integration with command parsing
- **WhatsApp**: Cloud API
- **Signal**: Basic integration
- **Matrix**: Client-server protocol
- **iMessage**: macOS integration
- **Notion**: Full integration (blocks, databases, pages, rich text)

**Integration Infrastructure**:
1. **`_circuit_breaker.py`** - Circuit breaker pattern
2. **`_rate_limiter.py`** - Token bucket rate limiting
3. **`_retry.py`** - Exponential backoff retry decorator
4. **`_health.py`** - Integration health checking
5. **`_channel_provider_runtime.py`** - Shared sync helpers

#### Integrations Features Summary:
- **Chat Platforms**: Slack, Discord, Teams, Google Chat, Telegram, WhatsApp, Signal, Matrix, iMessage
- **Productivity**: Notion, Google Workspace (Gmail, Calendar, Drive)
- **Reliability**: Circuit breaker, rate limiting, retry logic, health checks
- **Webhooks**: Inbound webhook support for platforms
- **OAuth**: OAuth2 flows for Slack, Google, etc.
- **Bridge Runtime**: Discord bridge with history & lifecycle

---

## NOTIFICATION FEATURES

### Location: `thomas/notify/` (13 files) + `thomas/notifications/` (4 files)

#### Notify Module (13 files):
1. **`channels.py`** - Channel implementations (EmailChannel, SMS, Push)
2. **`delivery.py`** - DeliveryQueue with retry logic & status tracking
3. **`routing.py`** - RoutingEngine with preference-based selection
4. **`preferences.py`** - PreferenceManager for user preferences
5. **`templates.py`** - TemplateEngine for rendering
6. **`campaigns.py`** - CampaignManager with A/B testing
7. **`digest.py`** - DigestScheduler for batching notifications
8. **`engagement.py`** - EngagementTracker for metrics
9. **`analytics.py`** - Funnel analysis, channel comparison, ROI metrics
10. **`tools.py`** - NotifySendTool, SubscriptionTool
11. **`_types.py`** - ChannelType, DeliveryStatus, Priority enums
12. **`_exceptions.py`** - NotifyException, ChannelException, TemplateException

#### Notifications Module (4 files):
1. **`api.py`** - FastAPI routes, initialization
2. **`dispatcher.py`** - NotificationDispatcher with VAPID config
3. **`store.py`** - SQLite notification store
4. **`tools.py`** - Get store, create, list notifications

#### Notification Features Summary:
- **Delivery Channels**: Email, SMS, push notifications, webhooks
- **Routing**: Preference-based channel selection
- **Preference Management**: Per-user notification settings
- **Templates**: Jinja-based notification rendering
- **Campaigns**: Batch sending with A/B testing
- **Digest**: Aggregation and batching
- **Engagement**: Tracking opens, clicks, conversions
- **Analytics**: Funnel analysis, ROI metrics
- **Retry Logic**: Automatic retries with configurable backoff
- **Persistence**: SQLite-backed store

---

## WORKFLOW FEATURES

### Location: `thomas/workflows/` (10 files) + `thomas/workflow_v2/` (3 files)

#### Workflows v1 (10 files):
1. **`engine.py`** - WorkflowEngine orchestration
2. **`models.py`** - StepType, WorkflowStatus, StepStatus enums
3. **`persistence.py`** - WorkflowStore persistence
4. **`steps.py`** - StepExecutor, ToolCallExecutor, LLMPromptExecutor
5. **`templates.py`** - Predefined workflow templates
6. **`triggers.py`** - WorkflowTrigger, CronTrigger
7. **`checkpointing.py`** - Crash recovery checkpoints
8. **`concurrency.py`** - ConcurrencyLimiter
9. **`deadletter.py`** - DeadLetterQueue for failed workflows
10. **`__init__.py`** - Module exports

#### Workflows v2 (3 files):
1. **`core.py`** - Improved execution, state management, RetryPolicy
2. **`tools.py`** - WorkflowExecutionTool, TaskManagementTool
3. **`__init__.py`** - Exports

#### Workflow Features Summary:
- **Step Execution**: Tool calls, LLM prompts, conditional logic
- **Persistence**: SQLite-backed workflow state
- **Triggering**: Cron, webhook, manual triggers
- **Checkpointing**: Crash recovery
- **Concurrency Control**: Throttling and rate limiting
- **Dead Letter Queue**: Failed job capture
- **Templates**: Predefined workflows (standup, file processing)
- **Retry Logic**: Configurable retry policies

---

## APPROVAL & HUMAN LOOP

### Location: `thomas/marketplace/approvals/` + `thomas/marketplace/human_loop/`

#### Approvals:
- Placeholder module (scaffolding for marketplace)

#### Human Loop (6 files):
1. **`approval.py`** - Approval skeleton
2. **`escalation.py`** - Escalation skeleton
3. **`handler.py`** - Handler skeleton
4. **`proxy.py`** - Proxy skeleton
5. **`types.py`** - Type skeleton
6. **`__init__.py`** - Exports

#### Features Summary:
- **Approval Workflows**: Async approval broker (stdlib-only implementation in agent/)
- **Escalation**: Escalation paths for urgent actions
- **Human Loop**: Manual intervention points

---

## TOOLS FEATURES

### Location: `thomas/tools/` (56 files)

#### Base Infrastructure:
1. **`base.py`** - Tool base class and result types
2. **`__init__.py`** - Tool registry

#### API & Code Tools:
1. **`api_import.py`** - ApiImportTool, ApiListImportedTool for OpenAPI
2. **`code_search.py`** - CodeSearchTool (regex, definitions, project structure)
3. **`engineering.py`** - SystemInfoTool, CodeComplexityTool, DeadCodeTool

#### Filesystem & Diff:
1. **`filesystem.py`** - ReadFileTool, WriteFileTool, ListFileTool, SearchFileTool
2. **`diff.py`** - CreateDiffTool, ApplyPatchTool, PreviewDiffTool

#### Cloud Providers:
1. **`cloud/base.py`** - CloudException, CloudAuthError, CloudResourceNotFoundError
2. **`cloud/aws.py`** - AWSProvider
3. **`cloud/gcp.py`** - GCPProvider
4. **`cloud/azure.py`** - AzureProvider

#### Database:
1. **`database.py`** - Database connectivity (placeholder)
2. **`database_commands.py`** - Query, schema, connection tools
3. **`database_safety.py`** - Query validation & safety checking

#### Dependency Scanning:
1. **`dep_scanner_core.py`** - Core vulnerability analysis
2. **`dep_scanner_npm.py`** - npm audit integration
3. **`dep_scanner_python.py`** - pip-audit + pyproject parsing
4. **`dep_scanner_osv.py`** - OSV enrichment with TTL cache
5. **`dep_scanner.py`** - Compatibility layer

#### Email & Calendar:
1. **`email_operations.py`** - Email service abstraction
2. **`email_providers.py`** - Gmail, Microsoft Graph providers
3. **`calendar_operations.py`** - CalendarTodayTool, CalendarWeekTool, CreateEventTool
4. **`email_calendar.py`** - Config management

#### Git & Web:
1. **`git.py`** (placeholder) - Git operations
2. **`web.py`** (placeholder) - Web tools

#### Additional Infrastructure:
- **`gateway/`** - API gateway implementations
- **`file_readers.py`** - File reading utilities
- Multiple specialized tool definitions

#### Tools Features Summary:
- **API Integration**: OpenAPI import, multi-provider support
- **Code Analysis**: Search, complexity, dead code detection
- **Filesystem**: Read, write, list, search with safety
- **Cloud**: AWS, GCP, Azure multi-cloud support
- **Database**: Query execution, schema inspection
- **Dependency Scanning**: npm, Python, OSV with caching
- **Email/Calendar**: Gmail, Microsoft Graph integration
- **Git**: Repository operations (placeholder)
- **Web**: HTTP utilities (placeholder)

---

## SKILLS FEATURES

### Location: `thomas/skills/` (5 files)

1. **`__init__.py`** - Skill system exports
2. **`_manifest.py`** - SkillBundle, manifest parsing (parse_frontmatter, _load_thomas_metadata)
3. **`_runtime.py`** - Skill execution runtime, repo root detection
4. **`_sandbox.py`** - Sandboxed skill execution
5. **`_security.py`** - File hashing, token counting, word-level redaction

#### Skills Features Summary:
- **Skill Bundles**: Packaged, discoverable skills with metadata
- **Manifest Parsing**: YAML/TOML frontmatter extraction
- **Runtime**: Skill execution environment
- **Sandboxing**: Isolated skill execution
- **Security**: File integrity, token counting, redaction

---

## CORE INFRASTRUCTURE

### Location: `thomas/core/` (54 files)

#### LLM & Providers:
1. **`llm_client.py`** - LLMClient: async multi-provider with streaming
2. **`llm_providers.py`** - Provider routing & configuration
3. **`llm_streaming.py`** - Provider-specific streaming implementations
4. **`llm_shared.py`** - LLMError, TokenUsage, StreamEvent, ToolCallAccumulator
5. **`llm.py`** - Main LLM exports

#### Configuration & Persistence:
1. **`config.py`** - Configuration system (config file validation)
2. **`persistence.py`** - TurnRecord, PersistenceEngine for conversation storage
3. **`tokens.py`** - Token counting, message trimming

#### Cost & Token Management:
1. **`cost_tracker.py`** - Token usage extraction from provider responses
2. **`token_economy.py`** - RuntimeOverheadPolicy, token budget enforcement
3. **`runtime_profile.py`** - RuntimeProfile (autonomy × token economy)

#### RAG & Search:
1. **`rag_index.py`** - RagIndex with hybrid search
2. **`rag_indexer.py`** - Chunking, indexing, index management
3. **`rag_embeddings.py`** - Embedding model management
4. **`rag_search.py`** - Search and retrieval operations
5. **`rag_format.py`** - Result formatting, snippet rendering

#### Safety & Validation:
1. **`safe_expression.py`** - Safe expression evaluation
2. **`safe_pickle.py`** - RestrictedUnpickler for safe deserialization
3. **`rules_of_road.py`** - Quality gate for task completion
4. **`placeholder_policy.py`** - Placeholder detection and validation

#### Agent Management:
1. **`agent_presence.py`** - Agent session detection and coordination
2. **`agent_presence_inference.py`** - Infer active agents from activity
3. **`local_agent_engine.py`** - LocalAgentEngine for background maintenance

#### Utilities:
1. **`boot_doctor.py`** - Deterministic startup repair (1140 lines)
2. **`scheduler.py`** - Local tz-aware scheduling (900+ lines)
3. **`workspace_sync_engine.py`** - Auto commits for workflow (840+ lines)
4. **`code_issue_engine.py`** - Autonomous code issue detection/fixing
5. **`api_importer.py`** - Construct ToolSpec from API specs
6. **`api_importer_http_tool.py`** - HTTP tool execution
7. **`api_importer_importer.py`** - ApiImporter class
8. **`autonomy.py`** - AutonomyLevelSpec definitions
9. **`initiative.py`** - InitiativeEngine for ROI-based goal picking
10. **`model_resolution.py`** - Case-insensitive model profile resolution
11. **`dep_monitor.py`** - Integration with testing_suite
12. **`engine_manager.py`** - EngineStatus, EngineManager
13. **`search_history.py`** - ConversationSearch with FTS5
14. **`search_history_shared.py`** - SearchResult, TurnContext, Bookmark
15. **`ui_effects_catalog.py`** - Curated UI effects
16. **`ui_review.py`** - UI edit safety review
17. **`ui_workflow_engine.py`** - UI workflow orchestration
18. **`self_upgrade_engine.py`** - Meaningful upgrade goal creation
19. **`task_bot_runtime.py`** - RuntimeTransition for task execution
20. **`testing_suite.py`** - Cycle result metrics
21. **`event_schemas.py`** - Event schema definitions
22. **`events.py`** - EventType, AgentEvent
23. **`py_compile_safe.py`** - Safe compilation without repo pollution
24. **`redaction.py`** - Lightweight log/JSON redaction
25. **`retry.py`** - ErrorSeverity, ErrorCategory, RetryPolicy
26. **`secrets_v2.py`** - Secret management (placeholder)
27. **`user_space.py`** - User space utilities
28. **`workspace_sync_coordination.py`** - Active-folder coordination
29. **`tool_factory.py`** - GeneratedTool, ToolFactory for reusable tools

#### Core Features Summary:
- **Multi-Provider LLM**: OpenAI, Anthropic, xAI, local models
- **Streaming**: Async streaming with token tracking
- **Token Economy**: Budget enforcement, overhead tracking
- **RAG**: Hybrid search, embeddings, chunking, indexing
- **Search History**: FTS5-based conversation search
- **Persistence**: Conversation storage, recovery
- **Cost Tracking**: Per-provider token usage
- **Agent Presence**: Session detection & coordination
- **Auto Sync**: Git auto-commits for workspace
- **Startup Repair**: Boot doctor for corruption recovery
- **API Import**: Automatic OpenAPI integration

---

## OBSERVABILITY & TELEMETRY

### Location: `thomas/observability/` + `thomas/telemetry/` + `thomas/system/`

#### Observability Bridge:
- `thomas/observability/__init__.py` - Re-export (moved to marketplace)

#### Telemetry Bridge:
- `thomas/telemetry/__init__.py` - Re-export (moved to marketplace)

#### System Module (6 files):
1. **`config_validator.py`** - Runtime configuration validation
2. **`heartbeat.py`** - Token-free automated health checks
3. **`perf_profiler.py`** - Latency/perf probing, baselining
4. **`release_contracts.py`** - Versioned compatibility discipline
5. **`soak_runner.py`** - Long-running soak test utilities

#### Features Summary:
- **Health Checks**: Automated via heartbeat
- **Config Validation**: Runtime configuration audit
- **Perf Profiling**: Command-level latency baselining
- **Release Contracts**: Compatibility verification
- **Soak Testing**: Long-duration test support

---

## SECURITY & PLUGINS

### Location: `thomas/security/` + `thomas/plugins/` (37 files)

#### Security Bridge:
- `thomas/security/__init__.py` - Re-export (moved to marketplace)

#### Plugins (37 files):
1. **`p097_plugin_package_bootstrap.py`** - Plugin bootstrapping
2. **`p098_plugin_manifest_schema.py`** - Manifest JSON schema
3. **`p100_plugin_discovery_scanner.py`** - Discovery scanning
4. **`p101_plugin_enable_and_disable_state_store.py`** - Enablement state
5. **`p102_plugin_install_from_local_path.py`** - Local installation
6. **`p103_plugin_uninstall_cleanup.py`** - Uninstall cleanup
7. **`p104_plugin_update_planner.py`** - Update planning
8. **`p105_plugin_registry_core_model.py`** - Registry model
9. **`p106_plugin_command_registry_bridge.py`** - Command registry
10. **`p107_plugin_hook_types_contract.py`** - Hook contract
11. **`p108_plugin_hook_runner_core.py`** - Hook execution
12. **`p109_plugin_hook_before_model.py`** - Pre-model hook
13. **`p110_plugin_hook_before_tool.py`** - Pre-tool hook
14. **`p111_plugin_hook_after_tool.py`** - Post-tool hook
15. **`p112_plugin_hook_after_response.py`** - Post-response hook
16. **`p113_plugin_tool_provider_injection.py`** - Tool provider injection
17. **`p114_plugin_service_lifecycle_manager.py`** - Service lifecycle
18. **`p115_plugin_gateway_handler_registry.py`** - Gateway handlers
19. **`p116_plugin_http_route_registry.py`** - HTTP routes
20. **`p117_plugin_config_schema_validator.py`** - Config validation
21. **`p118_plugin_diagnostics_collector.py`** - Diagnostics collection
22. **`catalog_index.py`** - Plugin catalog indexing
23. **`certification.py`** - Extension certification
24. **`competitor_evo_scope.py`** - Competitor tracking (placeholder)
25. **`competitor_intel_store.py`** - Competitor storage (placeholder)
26. **`extension_catalog_runtime.py`** - Extension pack loading
27. **`external_skill_adapter.py`** - External skill adaptation
28. **`github_marketplace.py`** - GitHub marketplace integration
29. **`benchmark_program.py`** - Benchmarking (placeholder)

#### Plugins Features Summary:
- **Plugin Lifecycle**: Bootstrap, install, enable, disable, uninstall, update
- **Manifest Schema**: JSON schema validation
- **Discovery**: Automatic plugin detection
- **Registry**: Plugin command registry
- **Hooks**: Pre-model, pre-tool, post-tool, post-response hooks
- **Tool Injection**: Dynamic tool provider injection
- **Service Management**: Plugin service lifecycle
- **Gateway Integration**: HTTP route registration
- **Configuration**: Plugin config validation
- **Diagnostics**: Collection and reporting
- **Marketplace**: GitHub marketplace integration
- **Certification**: Plugin quality certification

---

## SCRIPT UTILITIES

### Location: `scripts/` (147 files)

#### Agent Management:
- `agent_startup_router.py` - Agent initialization routing
- `agent_bootstrap_claim.py` - Bootstrap claim detection
- `agent_briefing.py` - Agent briefing generation
- `agent_commit.py` - Agent-driven commits
- `agent_identity.py` - Agent identity management
- `agent_preflight.py` - Pre-execution checks
- `agent_presence.py` - Presence detection
- `agent_safety_config.py` - Safety configuration
- `agent_safety_init.py` - Safety initialization
- `agent_session_report.py` - Session reporting

#### Workboard & Task Management:
- `workboard_claim.py` - Task claiming
- `workboard_claim_cleanup.py` - Claim cleanup
- `workboard_claim_dispatch.py` - Claim dispatch
- `workboard_claim_ops.py` - Claim operations
- `workboard_issue.py` - Issue management
- `workboard_message.py` - Message routing
- `workboard_problem_record.py` - Problem recording
- `workboard_swarm.py` - Multi-agent swarm
- `workboard_task_manager.py` - Task management
- `workboard_task_manager_*.py` (5 variants) - Task manager modules

#### Quality Gates & Checks:
- `check_*.py` (65+ check scripts) covering:
  - Boot smoke tests
  - Circular imports
  - Commit scope/growth
  - Core overhead
  - Feature catalog
  - Module audit
  - Monolith guards
  - Type safety
  - Test coverage
  - Protected files
  - Dependency policy
  - Release hygiene
  - Placeholder completion
  - Verification records

#### Build & Release:
- `package_release.py` - Release packaging
- `github_publish_preflight.py` - GitHub publication prep
- `github_publish_snapshot.py` - GitHub snapshot export
- `release_contract_check.py` - Compatibility check
- `setup_github_release_lanes.py` - Release lane setup
- `check_release_*.py` - Release gate checks

#### Development:
- `code_intake.py` - Code intake pipeline
- `create_shortcut.py` - Shortcut creation
- `create_verification_record.py` - Verification recording
- `fix_sandbox.py` - Sandbox repair
- `generate_full_coverage_contract.py` - Coverage tracking
- `heartbeat.py` - Health checks
- `perf_probe.py` - Performance profiling
- `audit_secrets.py` - Secret scanning
- `security_audit.py` - Security review
- `repo_orphan_inventory.py` - Orphan file detection

#### Utilities:
- `doc.py` - Documentation generation
- `git_paths.py` - Git path utilities
- `quick_env_report.py` - Environment reporting
- `virtual_office_identity.py` - Office identity setup

#### Features Summary:
- **Agent Lifecycle**: Startup, claims, briefings, presence
- **Task Management**: Workboard, claims, dispatch, execution
- **Quality Enforcement**: 65+ automated checks
- **Release Management**: Packaging, publishing, contracts
- **Development Support**: Intake, profiling, auditing
- **Safety**: Boot repair, secret scanning, security audit

---

## VOICE & AUDIO

### Location: `thomas/voice/` + `thomas/audio_engine/`

#### Voice Bridge:
- `thomas/voice/__init__.py` - Re-export (moved to marketplace)

#### Audio Engine Bridge:
- `thomas/audio_engine/__init__.py` - Re-export (moved to marketplace)

---

## ADDITIONAL KEY MODULES

### Marketplace Modules (Support Tier - 160+ modules)

Key marketplace modules NOT covered above:

- **`jobs`**: Job scheduling with cron, one-shot, recurring, dependencies
- **`behavior_tree`**: Behavior tree AI with selector, sequence, decorator nodes
- **`conversations`**: Conversation management (moved/placeholder)
- **`sandbox`**: Sandboxed execution environment
- **`learning`**: Learning system (domain-specific)
- **`library`**: Tool/pattern library management
- **`marketplace`**: Marketplace core and MANIFEST.json registry
- **`knowledge_graph`**: Knowledge graph construction and querying
- **`prompts`**: Prompt engineering and management
- **`rules`**: Rules engine for decision logic
- **`patterns`**: Architectural patterns
- **`validation`**: Data validation framework
- **`event_bus`**: Event bus for pub/sub
- **`message_queue`**: Message queue abstraction
- **`orchestration`/`orchestrator`**: Workflow orchestration
- **`data_catalog`**: Data asset cataloging
- **`metadata`** operations across multiple domains

Plus 100+ domain-specific modules: agriculture, blockchain, CAD, climate, EDA, HR, legal, supply chain, etc.

---

## SUMMARY STATISTICS

### File Counts by Module:
- **Memory**: 34 files (episodic, semantic, graph, embeddings, search)
- **Browser**: 221 files (actions, artifacts, telemetry, workflows)
- **Tools**: 56 files (API, code, cloud, DB, email, git)
- **Plugins**: 37 files (lifecycle, hooks, registry, validation)
- **Core**: 54 files (LLM, RAG, persistence, safety)
- **Agent**: 36 files (loop, planning, approval, intelligence)
- **Autonomy (marketplace)**: 16 files (engine, scheduler, policy, workflows)
- **Scheduler (deep)**: 20 files (cron, DAG, distributed, monitoring)
- **Integrations**: 41 files (Slack, Discord, Notion, etc.)
- **Chat**: 6 files (conversation, memory, session, thinking)
- **Notify**: 13 files (channels, delivery, routing, campaigns)
- **Workflows**: 10 files (engine, persistence, triggers, templates)
- **Skills**: 5 files (runtime, sandbox, security)
- **System**: 6 files (heartbeat, perf, validation)
- **Scripts**: 147 files (agent, workboard, checks, release)

### Total: 600+ Python files across core, infrastructure, and domain modules

### Feature Categories:
1. **Memory**: 7 major subsystems (episodic, semantic, graph, embeddings, search, reranking, compaction)
2. **Autonomy**: 8 major subsystems (engine, scheduler, policy, planning, execution, workflows)
3. **Browser**: 14 major subsystems (navigation, interaction, artifacts, telemetry, data, profiles, lifecycle)
4. **Integration**: 10+ platforms (Slack, Discord, Notion, Google, Microsoft, Telegram, etc.)
5. **Notifications**: 6 major subsystems (delivery, routing, templates, campaigns, digest, analytics)
6. **Workflows**: 7 major subsystems (engine, persistence, triggers, checkpointing, concurrency, templates)
7. **Tools**: 8+ categories (API, code, cloud, DB, email, git, filesystem, dependency scanning)
8. **Scheduling**: 7 major subsystems (cron, DAG, distributed, executor, persistence, monitoring, rate control)
9. **Skills**: 4 subsystems (manifest, runtime, sandbox, security)
10. **Safety**: Approval broker, guarded tools, redaction, policy runtime

---

## ARCHITECTURE NOTES

- **Core Tier Dependencies**: `core` → `tools`, `codex`, `server`
- **Agent Loop**: Streaming ReAct with parallel tools, checkpointing, context compaction
- **Memory**: Hybrid episodic/semantic with v2 fabric modernization
- **Autonomy**: Job-based with plan validation and deterministic policies
- **Browser**: 221-file scaffold with 170+ workflow profiles
- **Extensibility**: Plugin hooks at pre-model, pre-tool, post-tool, post-response
- **Marketplace**: 160+ domain modules with unified integration layer

---

End of inventory. This catalog represents the current state as of April 3, 2026.
