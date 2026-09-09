//   MODULE SYSTEM (COMMAND CENTER)                                         
//   19 nav modes, seeds, surfaces, workbench config, module state machine  
// 

const MODULE_NAV_MODES = Object.freeze([
    'dashboard',
    'operations',
    'inbox',
    'notifications',
    'automations',
    'agents',
    'studio',
    'dev_studio',
    'app_builder',
    'vibe_code',
    'game_studio',
    'lab_3d',
    'research_lab',
    'people',
    'finance',
    'integrations',
    'my_stuff',
    'channels',
    'marketplace',
    'token_economy',
    'vault',
    'timeline',
    'infinite',
]);
const MODULE_NAV_MODE_SET = new Set(MODULE_NAV_MODES);
const MODULE_ITEM_DISMISS_ACTIONS = new Set(['done', 'archive', 'dismiss', 'ack', 'resolve', 'snooze', 'complete']);

const MODULE_MODE_SEEDS = Object.freeze({
    dashboard: {
        title: 'Dashboard',
        subtitle: 'What matters right now.',
        pill: 'Live',
        kpis: [
            { label: 'Task Jobs', key: 'task_jobs', meta: 'deterministic workflows' },
            { label: 'Cron Jobs', key: 'cron_jobs', meta: 'scheduled automation' },
            { label: 'Approvals', key: 'approvals_pending', meta: 'manual decisions' },
            { label: 'Connected', key: 'integrations_connected', meta: 'live integrations' },
        ],
        actions: [
            { id: 'start_focus', label: 'Start Focus', meta: '90-minute deep work block.' },
            { id: 'draft_reply', label: 'Draft Reply', meta: 'Prepare top inbox replies.' },
            { id: 'run_workflow', label: 'Run Workflow', meta: 'Execute selected flow now.' },
            { id: 'create_asset', label: 'Create Asset', meta: 'Open production action.' },
        ],
    },
    operations: {
        title: 'Operations',
        subtitle: 'Business control room for customers, orders, inventory, and schedule.',
        pill: 'Ops',
        kpis: [
            { label: 'Open Orders', key: 'task_jobs', meta: 'active operational tasks' },
            { label: 'Exceptions', key: 'flow_failures', meta: 'failed or blocked flows' },
            { label: 'Approvals', key: 'approvals_pending', meta: 'human decisions pending' },
            { label: 'Connected', key: 'integrations_connected', meta: 'live business integrations' },
        ],
        actions: [
            { id: 'open_today_queue', label: 'Open Today Queue', meta: 'Show highest-priority operations.' },
            { id: 'draft_customer_followup', label: 'Draft Customer Follow-up', meta: 'Prepare outreach for blocked orders.' },
            { id: 'run_reorder', label: 'Run Reorder Check', meta: 'Find low-stock items and supplier actions.' },
            { id: 'open_disputes', label: 'Open Disputes', meta: 'Review cases that need negotiation.' },
        ],
    },
    inbox: {
        title: 'Inbox',
        subtitle: 'Unified email, DMs, and SMS with triage.',
        pill: 'Triage',
        kpis: [
            { label: 'Unread', key: 'inbox_unread', meta: 'across channels' },
            { label: 'Urgent', key: 'inbox_urgent', meta: 'priority queue' },
            { label: 'Needs Reply', key: 'inbox_needs_reply', meta: 'open commitments' },
            { label: 'Newsletters', key: 'inbox_newsletters', meta: 'batch later' },
        ],
        actions: [
            { id: 'summarize_thread', label: 'Summarize Thread', meta: 'Create quick thread summary.' },
            { id: 'draft_reply', label: 'Draft Reply', meta: 'Generate response draft.' },
            { id: 'schedule_followup', label: 'Schedule Follow-up', meta: 'Create reminder with context.' },
            { id: 'create_rule', label: 'Create Rule', meta: 'Auto-label and route messages.' },
        ],
    },
    notifications: {
        title: 'Notifications Center',
        subtitle: 'Robot board: severity, bundling, and escalation.',
        pill: 'Rules',
        kpis: [
            { label: 'Rules', key: 'notif_rules', meta: 'active policies' },
            { label: 'Bundled', key: 'notif_bundled', meta: 'batched alerts' },
            { label: 'Escalations', key: 'notif_escalations', meta: 'second pings' },
            { label: 'Muted', key: 'notif_muted', meta: 'quiet-hour suppressions' },
        ],
        actions: [
            { id: 'ack_critical', label: 'Acknowledge Critical', meta: 'Mark critical queue reviewed.' },
            { id: 'snooze_all_30', label: 'Snooze 30m', meta: 'Pause non-critical notifications.' },
            { id: 'open_personalities', label: 'Robot Personalities', meta: 'Tune category robot behavior.' },
            { id: 'open_history', label: 'Open History', meta: 'Inspect fired alerts and reasons.' },
        ],
    },
    automations: {
        title: 'Automations',
        subtitle: 'Thomas orchestration board for triggers, logic, actions, and approvals.',
        pill: 'Flows',
        kpis: [
            { label: 'Active Flows', key: 'flow_active', meta: 'enabled workflows' },
            { label: 'Failing Runs', key: 'flow_failures', meta: 'needs debug' },
            { label: 'Approvals', key: 'flow_approvals', meta: 'manual gates' },
            { label: 'Webhook Rate', key: 'webhook_rate', meta: 'events per minute' },
        ],
        actions: [
            { id: 'new_flow', label: 'New Flow', meta: 'Create trigger -> logic -> action.' },
            { id: 'import_template', label: 'Import Template', meta: 'Use a prebuilt flow.' },
            { id: 'run_smoke', label: 'Run Smoke Test', meta: 'Validate flow execution path.' },
            { id: 'rollback', label: 'Rollback', meta: 'Return to prior flow version.' },
        ],
    },
    agents: {
        title: 'Agents',
        subtitle: 'Specialized agent team, permissions, and boundaries.',
        pill: 'Crew',
        kpis: [
            { label: 'Active Agents', key: 'agent_active', meta: 'currently running' },
            { label: 'Delegated', key: 'agent_delegated', meta: 'assigned tasks' },
            { label: 'Approval Only', key: 'agent_approval_only', meta: 'cannot act directly' },
            { label: 'Escalations', key: 'agent_escalations', meta: 'asked for review' },
        ],
        actions: [
            { id: 'create_agent', label: 'Create Agent', meta: 'Define role and goals.' },
            { id: 'assign_sources', label: 'Assign Sources', meta: 'Attach inboxes/docs/feeds.' },
            { id: 'set_approval_rule', label: 'Set Approval Rule', meta: 'Require human approval gates.' },
            { id: 'tune_behavior', label: 'Tune Behavior', meta: 'Adjust tone and escalation style.' },
        ],
    },
    studio: {
        title: 'Asset Studio',
        subtitle: 'Thomas-managed asset jobs, tool connectors, and output review.',
        pill: 'Asset Ops',
        kpis: [
            { label: 'Render Queue', key: 'render_queue', meta: 'queued jobs' },
            { label: 'Exports Today', key: 'exports_today', meta: 'completed outputs' },
            { label: 'Pipelines', key: 'brand_kits', meta: 'active presets' },
            { label: 'Library', key: 'assets_total', meta: 'managed assets' },
        ],
        actions: [
            { id: 'ingest_assets', label: 'Ingest Assets', meta: 'Import and classify media in the library.' },
            { id: 'configure_audio_chain', label: 'Audio Chain', meta: 'Prepare denoise, normalize, and loudness passes.' },
            { id: 'generate_concepts', label: 'Generate Concepts', meta: 'Produce visual concepts from local tools.' },
            { id: 'queue_render', label: 'Queue Master Export', meta: 'Send timeline to production presets.' },
        ],
    },
    dev_studio: {
        title: 'Dev Studio',
        subtitle: 'Thomas-run engineering tasks, CI checks, and deploy controls.',
        pill: 'Build',
        kpis: [
            { label: 'Open PRs', key: 'dev_pr_open', meta: 'awaiting review' },
            { label: 'Failing Tests', key: 'dev_failures', meta: 'CI failures' },
            { label: 'Deploys Today', key: 'deploys_today', meta: 'staging + prod' },
            { label: 'Hotfixes', key: 'hotfixes_open', meta: 'urgent patches' },
        ],
        actions: [
            { id: 'triage_issues', label: 'Triage Issues', meta: 'Sort by severity and owner.' },
            { id: 'ask_thomas_implement', label: 'Ask {{agent}} to Implement', meta: 'Launch coding run.' },
            { id: 'run_tests', label: 'Run Tests', meta: 'Execute smoke/regression checks.' },
            { id: 'deploy_staging', label: 'Deploy Staging', meta: 'Promote current candidate.' },
        ],
    },
    app_builder: {
        title: 'UI Editor',
        subtitle: 'Describe apps and let Thomas generate, wire, and publish them.',
        pill: 'Builder',
        kpis: [
            { label: 'Published Apps', key: 'apps_published', meta: 'live tools' },
            { label: 'Draft Apps', key: 'apps_draft', meta: 'in progress' },
            { label: 'Connectors', key: 'connectors_total', meta: 'data links' },
            { label: 'Roles', key: 'roles_total', meta: 'permission groups' },
        ],
        actions: [
            { id: 'new_app', label: 'New App', meta: 'Start blank or template app.' },
            { id: 'add_connector', label: 'Add Connector', meta: 'Link API, DB, or sheet.' },
            { id: 'preview', label: 'Preview Runtime', meta: 'Open test runtime environment.' },
            { id: 'publish', label: 'Publish', meta: 'Release app to selected users.' },
        ],
    },
    vibe_code: {
        title: 'Vibe Code',
        subtitle: 'Project-level flow chart with live runtime tracing and controllable edges.',
        pill: 'Flow',
        kpis: [
            { label: 'Traces', key: 'trace_count', meta: 'captured request runs' },
            { label: 'Runtime Steps', key: 'runtime_steps', meta: 'nodes in active trace' },
            { label: 'Active Nodes', key: 'runtime_active', meta: 'currently executing' },
            { label: 'Cut Edges', key: 'runtime_cut_edges', meta: 'manually disconnected links' },
            { label: 'Errors', key: 'runtime_errors', meta: 'failing path nodes' },
        ],
        actions: [
            { id: 'switch_chat', label: 'Open Chat', meta: 'Run a message and watch the flow animate.' },
            { id: 'disconnect_edges', label: 'Disconnect Edges', meta: 'Cut all currently visible links across enabled modules.' },
            { id: 'reconnect_edges', label: 'Reconnect Edges', meta: 'Restore visible links without resetting trace history.' },
            { id: 'reset_trace', label: 'Reset Active Trace', meta: 'Clear current view while keeping history.' },
        ],
    },
    game_studio: {
        title: 'Game Studio',
        subtitle: 'Thomas-managed game pipelines, builds, and playtest operations.',
        pill: 'Play',
        kpis: [
            { label: 'Projects', key: 'game_projects', meta: 'active game projects' },
            { label: 'Playtests', key: 'game_playtests', meta: 'sessions this week' },
            { label: 'Open Bugs', key: 'game_bugs', meta: 'triage backlog' },
            { label: 'Gen Jobs', key: 'game_gen_jobs', meta: 'content generation' },
        ],
        actions: [
            { id: 'launch_engine', label: 'Launch Engine', meta: 'Open active game project.' },
            { id: 'run_build', label: 'Run Build', meta: 'Compile/package branch.' },
            { id: 'capture_playtest', label: 'Capture Playtest', meta: 'Record and annotate session.' },
            { id: 'generate_content', label: 'Generate Content', meta: 'Create quests/dialogue/items.' },
        ],
    },
    lab_3d: {
        title: '3D Lab',
        subtitle: 'Thomas-managed modeling and fabrication pipelines with operator oversight.',
        pill: 'Fabrication',
        kpis: [
            { label: 'Print Queue', key: 'print_queue', meta: 'jobs waiting' },
            { label: 'Revisions', key: 'model_revisions', meta: 'design iterations' },
            { label: 'Materials', key: 'materials_total', meta: 'loaded profiles' },
            { label: 'Uptime', key: 'printer_uptime', meta: '7-day health' },
        ],
        actions: [
            { id: 'import_stl', label: 'Import STL/OBJ', meta: 'Bring model into pipeline.' },
            { id: 'run_cleanup', label: 'Mesh Cleanup', meta: 'Repair manifold/normals.' },
            { id: 'slice_print', label: 'Slice Print', meta: 'Generate printer profile output.' },
            { id: 'start_print', label: 'Start Print Queue', meta: 'Dispatch queued print jobs.' },
        ],
    },
    research_lab: {
        title: 'Research Lab',
        subtitle: 'Thomas-run research operations with citations and tracked findings.',
        pill: 'Citations',
        kpis: [
            { label: 'Open Briefs', key: 'research_briefs', meta: 'active deep dives' },
            { label: 'Citations', key: 'research_citations', meta: 'saved sources' },
            { label: 'Competitors', key: 'research_competitors', meta: 'watchlist set' },
            { label: 'Indexed Docs', key: 'research_docs', meta: 'searchable corpus' },
        ],
        actions: [
            { id: 'deep_research', label: 'Start Deep Research', meta: 'Run source-backed research flow.' },
            { id: 'ingest_docs', label: 'Ingest Documents', meta: 'Parse and index new material.' },
            { id: 'compare_competitors', label: 'Compare Competitors', meta: 'Produce side-by-side report.' },
            { id: 'export_brief', label: 'Export Brief', meta: 'Publish answer with receipts.' },
        ],
    },
    people: {
        title: 'People',
        subtitle: 'Relationship context, follow-ups, and commitment tracking.',
        pill: 'CRM',
        kpis: [
            { label: 'Contacts', key: 'people_contacts', meta: 'tracked profiles' },
            { label: 'Follow-ups', key: 'people_followups', meta: 'due reminders' },
            { label: 'At Risk', key: 'people_at_risk', meta: 'stale relationships' },
            { label: 'Commitments', key: 'people_commitments', meta: 'open promises' },
        ],
        actions: [
            { id: 'log_interaction', label: 'Log Interaction', meta: 'Capture notes and commitments.' },
            { id: 'draft_checkin', label: 'Draft Check-in', meta: 'Generate personalized outreach.' },
            { id: 'create_followup', label: 'Create Follow-up', meta: 'Schedule reminder with context.' },
            { id: 'open_contact_context', label: 'Open Contact Context', meta: 'View history and files.' },
        ],
    },
    finance: {
        title: 'Finance',
        subtitle: 'Transactions, anomalies, forecasting, receipts, and approvals.',
        pill: 'Money',
        kpis: [
            { label: 'Monthly Burn', key: 'finance_burn', meta: 'rolling 30 days' },
            { label: 'Subscriptions', key: 'finance_subscriptions', meta: 'active recurring' },
            { label: 'Anomalies', key: 'finance_anomalies', meta: 'spend outliers' },
            { label: 'Approvals', key: 'finance_approvals', meta: 'pending decisions' },
        ],
        actions: [
            { id: 'categorize', label: 'Categorize Expenses', meta: 'Auto-label transactions.' },
            { id: 'create_invoice', label: 'Create Invoice', meta: 'Generate invoice draft.' },
            { id: 'run_forecast', label: 'Run Forecast', meta: 'Project next spend window.' },
            { id: 'request_approval', label: 'Request Approval', meta: 'Route high-risk spend.' },
        ],
    },
    token_economy: {
        title: 'Token Economy',
        subtitle: 'AI spend tracking, budgets, and economy modes.',
        pill: 'Spend',
        kpis: [
            { label: 'Today Spend', key: 'spend_today_usd', meta: 'rolling 24h' },
            { label: 'Session Spend', key: 'spend_session_usd', meta: 'this session' },
            { label: 'Tokens Today', key: 'spend_tokens_today', meta: 'prompt + completion' },
            { label: 'Economy Mode', key: 'spend_economy_mode', meta: 'cheap / optimal / max' },
        ],
        actions: [
            { id: 'switch_cheap', label: 'Switch to Cheap', meta: '0.3× passes — single-shot.' },
            { id: 'switch_optimal', label: 'Switch to Optimal', meta: '1.0× passes — balanced.' },
            { id: 'switch_max', label: 'Switch to Max', meta: '2.5× passes — thorough.' },
            { id: 'export_spend', label: 'Export CSV', meta: 'Download spend history.' },
        ],
    },
    integrations: {
        title: 'Integrations',
        subtitle: 'Connector scopes, tokens, webhooks, and plugin health.',
        pill: 'Connectors',
        kpis: [
            { label: 'Connected', key: 'integrations_connected', meta: 'active links' },
            { label: 'Degraded', key: 'integrations_degraded', meta: 'needs fix' },
            { label: 'Reconnects', key: 'integrations_reconnects', meta: 'pending' },
            { label: 'Webhooks', key: 'webhooks_live', meta: 'live listeners' },
        ],
        actions: [
            { id: 'connect_app', label: 'Connect App', meta: 'Authorize new integration.' },
            { id: 'rotate_key', label: 'Rotate API Key', meta: 'Replace compromised/old key.' },
            { id: 'run_health_check', label: 'Run Health Check', meta: 'Validate connector status.' },
            { id: 'create_webhook', label: 'Create Webhook', meta: 'Register event callback.' },
        ],
    },
    my_stuff: {
        title: 'Library',
        subtitle: 'Project board with launch controls, troubleshooting, and project-scoped Thomas chats.',
        pill: 'Launchpad',
        kpis: [],
        actions: [],
    },
    channels: {
        title: 'Channels',
        subtitle: 'Own bridge lifecycle, permissions, and searchable Discord conversation context.',
        pill: 'Discord',
        kpis: [],
        actions: [],
    },
    marketplace: {
        title: 'Marketplace',
        subtitle: 'Browse and install Thomas upgrades from the marketplace catalog.',
        pill: 'Plugins',
        kpis: [],
        actions: [],
    },
    vault: {
        title: 'Vault',
        subtitle: 'Secrets, memory boundaries, retention, and backup controls.',
        pill: 'Secure',
        kpis: [
            { label: 'Secrets', key: 'vault_secrets', meta: 'stored credentials' },
            { label: 'Expiring', key: 'vault_expiring', meta: 'rotate soon' },
            { label: 'Sources', key: 'vault_sources', meta: 'knowledge inputs' },
            { label: 'Retention', key: 'vault_retention', meta: 'active policies' },
        ],
        actions: [
            { id: 'add_secret', label: 'Add Secret', meta: 'Store credential with scope.' },
            { id: 'revoke_token', label: 'Revoke Token', meta: 'Immediately disable access.' },
            { id: 'export_backup', label: 'Export Backup', meta: 'Create encrypted data export.' },
            { id: 'run_scan', label: 'Run Compliance Scan', meta: 'Audit access and policy drift.' },
        ],
    },
    timeline: {
        title: 'Timeline',
        subtitle: 'Action receipts, approvals, retries, and rollbacks.',
        pill: 'Audit',
        kpis: [
            { label: 'Events 24h', key: 'timeline_events', meta: 'logged actions' },
            { label: 'Automated', key: 'timeline_automated', meta: 'workflow/agent actions' },
            { label: 'Approvals', key: 'timeline_approvals', meta: 'manual sign-offs' },
            { label: 'Retries', key: 'timeline_retries', meta: 'recovery attempts' },
        ],
        actions: [
            { id: 'filter_errors', label: 'Filter Errors', meta: 'Show failed/retried actions.' },
            { id: 'export_receipts', label: 'Export Receipts', meta: 'Download action timeline.' },
            { id: 'rollback', label: 'Rollback Run', meta: 'Revert selected workflow version.' },
            { id: 'open_diff', label: 'Open Before/After', meta: 'Inspect state transitions.' },
        ],
    },
    infinite: {
        title: 'Infinite',
        subtitle: 'Companion HQ: pairing, handoff, push, and offline capture.',
        pill: 'Companion',
        kpis: [
            { label: 'Devices', key: 'devices_paired', meta: 'paired devices' },
            { label: 'Handoffs', key: 'handoffs_pending', meta: 'waiting handoff' },
            { label: 'Offline Captures', key: 'offline_captures', meta: 'awaiting sync' },
            { label: 'Push Routes', key: 'push_routes', meta: 'configured paths' },
        ],
        actions: [
            { id: 'pair_device', label: 'Pair Device', meta: 'Register trusted companion device.' },
            { id: 'send_handoff', label: 'Send Handoff', meta: 'Continue context on another device.' },
            { id: 'sync_offline', label: 'Sync Offline Captures', meta: 'Upload queued captures.' },
            { id: 'open_voice', label: 'Open Voice Mode', meta: 'Configure voice controls.' },
        ],
    },
});

const MODULE_MODE_SURFACES = Object.freeze({
    dashboard: { layout: 'hub', sections: ['Now', 'Timeline', 'Robot Feed', 'Projects'] },
    operations: { layout: 'ops', sections: ['Overview', 'Customers', 'Inventory', 'Disputes'] },
    inbox: { layout: 'tri_pane', sections: ['Urgent', 'Needs Reply', 'FYI', 'Receipts'] },
    notifications: { layout: 'board', sections: ['Rules', 'Channels', 'Robots', 'History'] },
    automations: { layout: 'canvas', sections: ['Triggers', 'Logic', 'Actions', 'Run Logs'] },
    agents: { layout: 'crew', sections: ['Roster', 'Assignments', 'Permissions', 'Memory'] },
    studio: { layout: 'editor_media', sections: ['Library', 'Creation', 'Audio', 'Delivery'] },
    dev_studio: { layout: 'editor_code', sections: ['Repo', 'Issues', 'PRs', 'Builds'] },
    app_builder: { layout: 'canvas', sections: ['UI', 'Data', 'Logic', 'Publish'] },
    vibe_code: { layout: 'canvas', sections: ['Project', 'Runtime', 'Events', 'Nodes'] },
    game_studio: { layout: 'editor_game', sections: ['Projects', 'Assets', 'Builds', 'Playtests'] },
    lab_3d: { layout: 'editor_3d', sections: ['Models', 'Materials', 'Repairs', 'Print Queue'] },
    research_lab: { layout: 'research', sections: ['Collections', 'Sources', 'Notes', 'Citations'] },
    people: { layout: 'tri_pane', sections: ['Segments', 'Timeline', 'Commitments', 'Follow-ups'] },
    finance: { layout: 'tri_pane', sections: ['Accounts', 'Transactions', 'Approvals', 'Forecast'] },
    token_economy: { layout: 'custom', sections: ['Overview', 'Models', 'History', 'Economy Mode'] },
    integrations: { layout: 'tri_pane', sections: ['Installed', 'Available', 'Permissions', 'Logs'] },
    my_stuff: { layout: 'catalog', sections: [] },
    channels: { layout: 'catalog', sections: [] },
    marketplace: { layout: 'catalog', sections: [] },
    vault: { layout: 'admin', sections: ['Secrets', 'Permissions', 'Memory', 'Retention'] },
    timeline: { layout: 'audit', sections: ['Events', 'Approvals', 'Retries', 'Rollbacks'] },
    infinite: { layout: 'device', sections: ['Devices', 'Routing', 'Capture', 'Offline'] },
});

const MODULE_SECTION_ICONS = Object.freeze({
    now: 'ph-lightning',
    timeline: 'ph-timeline',
    robot_feed: 'ph-robot',
    projects: 'ph-kanban',
    overview: 'ph-gauge',
    customers: 'ph-users-three',
    inventory: 'ph-package',
    disputes: 'ph-scales',
    urgent: 'ph-warning-circle',
    needs_reply: 'ph-chat-centered-text',
    fyi: 'ph-info',
    receipts: 'ph-receipt',
    rules: 'ph-sliders',
    channels: 'ph-broadcast',
    robots: 'ph-robot',
    history: 'ph-clock-counter-clockwise',
    triggers: 'ph-bell-ringing',
    logic: 'ph-git-branch',
    actions: 'ph-play-circle',
    run_logs: 'ph-file-text',
    roster: 'ph-user-list',
    assignments: 'ph-check-square',
    permissions: 'ph-shield-check',
    memory: 'ph-brain',
    video: 'ph-film-strip',
    audio: 'ph-speaker-high',
    design: 'ph-pencil-ruler',
    render_queue: 'ph-hourglass',
    repo: 'ph-folder-simple',
    issues: 'ph-bug',
    prs: 'ph-git-pull-request',
    builds: 'ph-hammer',
    ui: 'ph-app-window',
    data: 'ph-database',
    project: 'ph-git-branch',
    runtime: 'ph-activity',
    publish: 'ph-paper-plane-tilt',
    nodes: 'ph-circles-three',
    assets: 'ph-image-square',
    playtests: 'ph-game-controller',
    models: 'ph-cube',
    materials: 'ph-squares-four',
    repairs: 'ph-wrench',
    print_queue: 'ph-printer',
    collections: 'ph-stack',
    sources: 'ph-book-open',
    notes: 'ph-note',
    citations: 'ph-quotes',
    segments: 'ph-funnel',
    commitments: 'ph-handshake',
    follow_ups: 'ph-arrow-bend-up-right',
    accounts: 'ph-wallet',
    transactions: 'ph-arrows-left-right',
    approvals: 'ph-stamp',
    forecast: 'ph-chart-line-up',
    installed: 'ph-plugs-connected',
    available: 'ph-plug',
    logs: 'ph-file-search',
    featured: 'ph-star',
    templates: 'ph-copy',
    agents: 'ph-robot',
    apps: 'ph-grid-four',
    secrets: 'ph-key',
    retention: 'ph-clock-countdown',
    events: 'ph-lightning',
    retries: 'ph-arrow-clockwise',
    rollbacks: 'ph-arrow-counter-clockwise',
    devices: 'ph-device-mobile-camera',
    routing: 'ph-signpost',
    capture: 'ph-camera',
    offline: 'ph-cloud-slash',
});

const MODULE_WORKBENCH_MODES = new Set([
    'automations',
    'app_builder',
    'vibe_code',
    'studio',
    'dev_studio',
    'game_studio',
    'lab_3d',
    'research_lab',
]);

function normalizeNavMode(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (mode === 'search' || mode === 'office' || mode === 'mission' || mode === 'content' || mode === 'evolution') return mode;
    if (MODULE_NAV_MODE_SET.has(mode)) return mode;
    return 'chat';
}

function moduleSeed(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (MODULE_MODE_SEEDS[mode]) return MODULE_MODE_SEEDS[mode];
    const plugin = moduleInstalledPluginForMode(mode);
    if (plugin) {
        return {
            title: safeString(plugin?.display_name) || 'Installed Plugin',
            subtitle: safeString(plugin?.subtitle) || safeString(plugin?.description) || 'Installed plugin surface.',
            pill: 'Plugin',
            kpis: [],
            actions: [],
        };
    }
    return MODULE_MODE_SEEDS.dashboard;
}

function moduleModeSurface(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (MODULE_MODE_SURFACES[mode]) return MODULE_MODE_SURFACES[mode];
    if (moduleInstalledPluginForMode(mode)) {
        return { layout: 'catalog', sections: [] };
    }
    return MODULE_MODE_SURFACES.dashboard;
}

function moduleSectionIcon(sectionLabelRaw) {
    const key = safeString(sectionLabelRaw).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    if (MODULE_SECTION_ICONS[key]) return MODULE_SECTION_ICONS[key];
    return 'ph-dot-outline';
}

function moduleEnsureRuntime() {
    if (!moduleWorkspace) return null;
    if (!moduleState) {
        moduleState = {
            controlsBound: false,
            timerId: 0,
            activeMode: 'dashboard',
            lastRenderedMode: '',
            modeEnterTimer: 0,
            triageFilters: {},
            subnavFocus: {},
            workbenchMode: '',
            workbench: {},
            hidden: {},
            activity: {},
            refreshedAt: {},
            marketplace: {
                apps: [],
                modules: [],
                plugins: [],
                categories: [],
                generatedAt: '',
                loading: false,
                error: '',
                warning: '',
                syncError: '',
                degraded: false,
                search: '',
                filter: 'all',
                storeUrl: '',
                pendingStoreUrl: moduleReadPreferredMarketplaceStoreUrl(),
                lastRefreshedAt: 0,
                refreshPromise: null,
                refreshSucceeded: false,
                catalogSignature: '',
                installedLastRefreshedAt: 0,
                installedRefreshPromise: null,
            },
        };
    }
    return moduleState;
}

function moduleEnsureHiddenBucket(mode, section) {
    const state = moduleEnsureRuntime();
    if (!state) return null;
    if (!state.hidden[mode]) {
        state.hidden[mode] = {
            queue: new Set(),
            health: new Set(),
            triage: new Set(),
        };
    }
    if (!state.hidden[mode][section]) {
        state.hidden[mode][section] = new Set();
    }
    return state.hidden[mode][section];
}

function moduleHideItem(mode, section, itemId) {
    const id = safeString(itemId);
    if (!id) return;
    const bucket = moduleEnsureHiddenBucket(mode, section);
    if (bucket) bucket.add(id);
}

function moduleIsItemHidden(mode, section, itemId) {
    const id = safeString(itemId);
    if (!id) return false;
    const bucket = moduleEnsureHiddenBucket(mode, section);
    return Boolean(bucket && bucket.has(id));
}

function moduleVisibleItems(mode, section, rowsRaw) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    return rows.filter((row) => !moduleIsItemHidden(mode, section, row?.id));
}

function moduleToneClass(toneRaw) {
    const tone = safeString(toneRaw).toLowerCase();
    if (tone === 'ok' || tone === 'success' || tone === 'live') return 'ok';
    if (tone === 'warn' || tone === 'warning' || tone === 'watch') return 'warn';
    if (tone === 'error' || tone === 'danger' || tone === 'critical') return 'error';
    if (tone === 'done' || tone === 'complete') return 'done';
    return '';
}

function moduleTouch(mode) {
    const state = moduleEnsureRuntime();
    if (!state) return;
    state.refreshedAt[mode] = Date.now();
}

function moduleRecordActivity(mode, title, tone = 'ok') {
    const state = moduleEnsureRuntime();
    if (!state) return;
    if (!Array.isArray(state.activity[mode])) {
        state.activity[mode] = [];
    }
    const badge = tone === 'error' ? 'Alert' : (tone === 'warn' ? 'Update' : 'Action');
    state.activity[mode].unshift({
        id: `act-${Date.now()}-${Math.round(Math.random() * 10_000)}`,
        title: safeString(title) || 'Action completed.',
        meta: 'just now',
        badge,
        tone,
    });
    if (state.activity[mode].length > 14) {
        state.activity[mode] = state.activity[mode].slice(0, 14);
    }
}

function moduleBuildSnapshot() {
    const missionPayload = missionState?.lastPayload && typeof missionState.lastPayload === 'object'
        ? missionState.lastPayload
        : {};
    const jobsPayload = missionState?.lastJobsPayload && typeof missionState.lastJobsPayload === 'object'
        ? missionState.lastJobsPayload
        : {};
    const contentPayload = contentState?.payload && typeof contentState.payload === 'object'
        ? contentState.payload
        : contentEmptyPayload();
    const summary = contentPayload?.summary && typeof contentPayload.summary === 'object'
        ? contentPayload.summary
        : {};
    const controlSurface = contentPayload?.control_surface && typeof contentPayload.control_surface === 'object'
        ? contentPayload.control_surface
        : {};
    const approvals = missionPayload?.approvals && typeof missionPayload.approvals === 'object'
        ? missionPayload.approvals
        : {};

    return {
        missionPayload,
        jobs: Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [],
        events: Array.isArray(missionPayload?.events) ? missionPayload.events : [],
        agents: Array.isArray(missionPayload?.agents) ? missionPayload.agents : [],
        platforms: Array.isArray(contentPayload?.platforms) ? contentPayload.platforms : [],
        workflows: Array.isArray(contentPayload?.workflows) ? contentPayload.workflows : [],
        scheduler: Array.isArray(contentPayload?.scheduler) ? contentPayload.scheduler : [],
        tools: Array.isArray(contentPayload?.tools) ? contentPayload.tools : [],
        healthChecks: Array.isArray(controlSurface?.health_checks) ? controlSurface.health_checks : [],
        summary,
        controlSurface,
        totals: missionPayload?.totals && typeof missionPayload.totals === 'object' ? missionPayload.totals : {},
        approvalsAutonomy: Array.isArray(approvals?.autonomy) ? approvals.autonomy : [],
        approvalsGuardrails: Array.isArray(approvals?.guardrails) ? approvals.guardrails : [],
        approvalsPending: contentToCount(
            missionPayload?.totals?.approvals_pending,
            contentToCount(approvals?.pending_total, 0),
        ),
        sessions: Array.isArray(sidebarSessions) ? sidebarSessions : [],
        spend: spendState?.payload && typeof spendState.payload === 'object' ? spendState.payload : {},
        goalStats: goalsState?.payload && typeof goalsState.payload === 'object' ? goalsState.payload : {},
        marketplace: moduleGetMarketplaceState(),
    };
}
function moduleGetMarketplaceState() {
    const state = moduleEnsureRuntime();
    if (!state || !state.marketplace || typeof state.marketplace !== 'object') {
        return {
            apps: [],
            modules: [],
            loading: false,
            error: '',
            warning: '',
            syncError: '',
            degraded: false,
            storeUrl: '',
            pendingStoreUrl: '',
            lastRefreshedAt: 0,
            refreshPromise: null,
        };
    }
    return {
        apps: Array.isArray(state.marketplace.apps) ? state.marketplace.apps : [],
        modules: Array.isArray(state.marketplace.modules) ? state.marketplace.modules : [],
        loading: Boolean(state.marketplace.loading),
        error: safeString(state.marketplace.error),
        warning: safeString(state.marketplace.warning),
        syncError: safeString(state.marketplace.syncError),
        degraded: Boolean(state.marketplace.degraded),
        storeUrl: safeString(state.marketplace.storeUrl),
        pendingStoreUrl: safeString(state.marketplace.pendingStoreUrl),
        lastRefreshedAt: Number(state.marketplace.lastRefreshedAt) || 0,
        refreshPromise: state.marketplace.refreshPromise || null,
    };
}

function normalizeMarketplaceStoreUrl(urlRaw) {
    const raw = safeString(urlRaw).trim();
    if (!raw) return '';
    const candidate = /^[a-z]+:\/\//i.test(raw) ? raw : `https://${raw}`;
    try {
        const parsed = new URL(candidate);
        const protocol = safeString(parsed.protocol).toLowerCase();
        if (protocol !== 'https:' && protocol !== 'http:') return '';
        parsed.hash = '';
        parsed.search = '';
        return parsed.toString().replace(/\/+$/, '');
    } catch {
        return '';
    }
}

function normalizePreferredMarketplaceStoreUrl(urlRaw) {
    const normalized = normalizeMarketplaceStoreUrl(urlRaw);
    if (!normalized) return '';
    if (normalized === LEGACY_MARKETPLACE_STORE_URL) {
        return DEFAULT_MARKETPLACE_STORE_URL;
    }
    return normalized;
}

function moduleReadPreferredMarketplaceStoreUrl() {
    try {
        if (!window?.localStorage) return '';
        return normalizePreferredMarketplaceStoreUrl(window.localStorage.getItem(UI_MARKETPLACE_STORE_URL_STORAGE_KEY));
    } catch {
        return '';
    }
}

function moduleWritePreferredMarketplaceStoreUrl(urlRaw) {
    const normalized = normalizePreferredMarketplaceStoreUrl(urlRaw);
    try {
        if (!window?.localStorage) return normalized;
        if (normalized) {
            window.localStorage.setItem(UI_MARKETPLACE_STORE_URL_STORAGE_KEY, normalized);
        } else {
            window.localStorage.removeItem(UI_MARKETPLACE_STORE_URL_STORAGE_KEY);
        }
    } catch {
        // Ignore storage failures.
    }
    return normalized;
}

function moduleMarketplaceSetUiContract(node, {
    id = '',
    label = '',
    component = '',
    policy = 'move resize',
    constraints = 'contain=parent,collision=avoid',
    instanceKey = '',
    group = '',
} = {}) {
    if (!(node instanceof Element)) return null;
    if (id) node.setAttribute('data-ui-id', safeString(id));
    if (label) node.setAttribute('data-ui-label', safeString(label));
    if (component) node.setAttribute('data-ui-component', safeString(component));
    if (policy) node.setAttribute('data-ui-policy', safeString(policy));
    if (constraints) node.setAttribute('data-ui-constraints', safeString(constraints));
    if (instanceKey) node.setAttribute('data-ui-instance-key', safeString(instanceKey));
    if (group) node.setAttribute('data-ui-group', safeString(group));
    return node;
}

function moduleMarketplaceStableKey(valueRaw) {
    return safeString(valueRaw)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9._:-]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'unknown';
}

function moduleMarketplaceEnsureIdentity(surface) {
    if (!(surface instanceof Element)) return null;
    const commandBar = surface.querySelector('.marketplace-command-bar');
    if (!(commandBar instanceof Element)) return null;
    let identity = commandBar.querySelector(':scope > .marketplace-identity');
    if (!identity) {
        identity = document.createElement('div');
        identity.className = 'marketplace-identity';
        identity.innerHTML = `
            <span class="thomas-eyes-mark marketplace-eyes-mark" aria-hidden="true"><i></i><i></i></span>
            <span class="marketplace-identity-copy"><strong>Thomas</strong><span>Marketplace</span></span>
        `;
        commandBar.prepend(identity);
    }
    return moduleMarketplaceSetUiContract(identity, {
        id: 'marketplace.identity',
        label: 'Thomas Marketplace identity',
        component: 'identity-lockup',
        policy: 'move',
        constraints: 'contain=parent,minWidth=140,minHeight=32,maxWidth=260,collision=avoid',
    });
}

function moduleApplyMarketplaceUiContracts(surfaceRaw) {
    const surface = surfaceRaw instanceof Element
        ? surfaceRaw
        : document.querySelector('#moduleWorkspace[data-mode="marketplace"] .marketplace-surface');
    if (!(surface instanceof Element)) return null;

    surface.setAttribute('data-ui-workspace', 'marketplace');
    moduleMarketplaceSetUiContract(surface, {
        id: 'marketplace.shell',
        label: 'Marketplace workspace',
        component: 'workspace-shell',
        policy: 'root protected',
        constraints: 'preserve-runtime-ids,preserve-handlers',
    });
    moduleMarketplaceEnsureIdentity(surface);

    const register = (selector, contract) => {
        const node = surface.querySelector(selector);
        if (node) moduleMarketplaceSetUiContract(node, contract);
        return node;
    };
    register('.marketplace-sticky-head', {
        id: 'marketplace.header', label: 'Marketplace header', component: 'workspace-header',
        constraints: 'contain=parent,minWidth=300,minHeight=96,maxHeight=360,collision=avoid',
    });
    register('.marketplace-command-bar', {
        id: 'marketplace.controls', label: 'Marketplace controls', component: 'control-bar',
        policy: 'move resize protected-controls',
        constraints: 'contain=parent,minWidth=300,minHeight=44,maxHeight=220,collision=avoid,preserve-handlers',
    });
    register('.marketplace-search-wrap', {
        id: 'marketplace.search', label: 'Search Marketplace', component: 'search-control',
        policy: 'move resize protected',
        constraints: 'contain=parent,minWidth=220,minHeight=44,maxWidth=900,maxHeight=96,collision=avoid,preserve-handlers',
    });
    register('.marketplace-filter-rail', {
        id: 'marketplace.filters', label: 'Marketplace category filters', component: 'repeating-control-group',
        policy: 'move resize protected live-control-group',
        constraints: 'items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,contain=parent,minWidth=260,minHeight=40,maxHeight=180,collision=avoid,preserve-handlers',
    });
    register('.marketplace-card-grid', {
        id: 'marketplace.catalog', label: 'Marketplace package catalog', component: 'repeating-card-group',
        policy: 'move resize',
        constraints: 'items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,contain=parent,minWidth=280,minHeight=320,maxHeight=2400,collision=avoid,preserve-handlers',
    });
    register('.marketplace-selected-strip', {
        id: 'marketplace.detail', label: 'Selected package details', component: 'detail-panel',
        constraints: 'contain=parent,minWidth=280,minHeight=180,maxHeight=900,collision=avoid,preserve-handlers',
    });
    register('.marketplace-empty-state', {
        id: 'marketplace.catalog.empty', label: 'Marketplace empty state', component: 'status-panel',
        policy: 'move resize protected',
        constraints: 'contain=parent,minWidth=260,minHeight=120,maxHeight=420,collision=avoid',
    });

    surface.querySelectorAll('.marketplace-summary-row').forEach((node, index) => {
        moduleMarketplaceSetUiContract(node, {
            id: index === 0 ? 'marketplace.status' : 'marketplace.status.notice',
            label: index === 0 ? 'Marketplace catalog status' : 'Marketplace sync notice',
            component: 'status-region',
            policy: 'move resize protected',
            constraints: 'contain=parent,minWidth=260,minHeight=28,maxHeight=160,collision=avoid',
        });
    });
    surface.querySelectorAll('.marketplace-filter-chip').forEach((node) => {
        const key = moduleMarketplaceStableKey(node.getAttribute('data-module-marketplace-filter'));
        moduleMarketplaceSetUiContract(node, {
            id: 'marketplace.filter', label: `Marketplace filter ${key}`, component: 'filter-control',
            policy: 'protected live-control', constraints: 'preserve-handlers,reposition-deny,resize-deny',
            instanceKey: key, group: 'marketplace.filters',
        });
    });
    surface.querySelectorAll('.marketplace-card').forEach((card) => {
        const keyedControl = card.querySelector('[data-module-marketplace-select], [data-module-item-id]');
        const packageId = moduleMarketplaceStableKey(
            keyedControl?.getAttribute('data-module-marketplace-select') || keyedControl?.getAttribute('data-module-item-id'),
        );
        moduleMarketplaceSetUiContract(card, {
            id: 'marketplace.package', label: `Marketplace package ${packageId}`, component: 'live-record',
            policy: 'protected live-record',
            constraints: 'items-runtime-owned,reposition-deny,resize-deny,add-deny,remove-deny,preserve-handlers',
            instanceKey: packageId, group: 'marketplace.packages',
        });
    });
    surface.querySelectorAll('.marketplace-selected-fact').forEach((node) => {
        const key = moduleMarketplaceStableKey(node.querySelector('span')?.textContent);
        moduleMarketplaceSetUiContract(node, {
            id: 'marketplace.detail.fact', label: `Package detail ${key}`, component: 'detail-fact',
            policy: 'protected live-record', constraints: 'reposition-deny,resize-deny',
            instanceKey: key, group: 'marketplace.detail-facts',
        });
    });
    surface.querySelectorAll('button, input[type="search"], input[type="file"]').forEach((control) => {
        const packageId = moduleMarketplaceStableKey(
            control.getAttribute('data-module-item-id') || control.getAttribute('data-module-marketplace-select'),
        );
        const actionId = moduleMarketplaceStableKey(
            control.getAttribute('data-module-action-id')
            || (control.hasAttribute('data-module-marketplace-copy-id') ? 'copy-id' : '')
            || (control.hasAttribute('data-module-marketplace-refresh') ? 'sync' : '')
            || (control.hasAttribute('data-marketplace-import') || control.hasAttribute('data-marketplace-import-input') ? 'install-file' : '')
            || (control.hasAttribute('data-module-marketplace-clear') ? 'clear-search' : '')
            || (control.hasAttribute('data-module-marketplace-search') ? 'search' : '')
            || (control.hasAttribute('data-module-marketplace-filter') ? `filter-${control.getAttribute('data-module-marketplace-filter')}` : ''),
        );
        moduleMarketplaceSetUiContract(control, {
            id: packageId !== 'unknown' ? 'marketplace.package.action' : 'marketplace.control',
            label: safeString(control.getAttribute('data-module-action-label') || control.textContent || actionId).trim(),
            component: 'protected-control', policy: 'protected control',
            constraints: 'preserve-runtime-ids,preserve-handlers,reposition-deny,resize-deny',
            instanceKey: packageId !== 'unknown' ? `${packageId}:${actionId}` : actionId,
            group: packageId !== 'unknown' ? 'marketplace.package-actions' : 'marketplace.controls',
        });
    });
    return surface;
}


function moduleFetchJsonSafe(url, options = {}) {
    const normalizedUrl = safeString(url);
    if (!normalizedUrl) {
        return Promise.reject(new Error('Missing request URL'));
    }
    return fetch(normalizedUrl, {
        headers: {
            Accept: 'application/json',
            ...(options.headers || {}),
        },
        ...options,
    }).then(async (response) => {
        const text = await response.text();
        let payload = null;
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch {
                payload = null;
            }
        }
        if (!response.ok) {
            const message = safeString(payload?.error) || safeString(payload?.message) || text || `${response.status} ${response.statusText}`;
            const err = new Error(message || 'Request failed');
            err.status = response.status;
            throw err;
        }
        return payload;
    });
}

function moduleParseVersionParts(versionRaw) {
    const raw = safeString(versionRaw).replace(/^\s*v/i, '');
    const matches = String(raw || '').match(/\d+/g) || [];
    const parts = matches.slice(0, 3).map((part) => {
        const n = Number.parseInt(part, 10);
        return Number.isFinite(n) ? n : 0;
});
    while (parts.length < 3) {
        parts.push(0);
    }
    return parts;
}

function moduleIsVersionNewer(candidateRaw, currentRaw) {
    const candidate = moduleParseVersionParts(candidateRaw);
    const current = moduleParseVersionParts(currentRaw);
    for (let i = 0; i < 3; i += 1) {
        const c = Number.isFinite(candidate[i]) ? candidate[i] : 0;
        const p = Number.isFinite(current[i]) ? current[i] : 0;
        if (c > p) return true;
        if (c < p) return false;
    }
    return false;
}

function moduleMarketplaceSectionId(value) {
    const section = safeString(value).toLowerCase();
    if (!section || section === 'all') return 'all';
    if (section === 'templates' || section === 'template') return 'templates';
    if (section === 'agents' || section === 'agent') return 'agents';
    if (section === 'apps' || section === 'app' || section === 'tools') return 'apps';
    return 'featured';
}

function moduleMarketplaceGuessSection(appRaw = {}, moduleId = '', title = '', description = '') {
    const hints = [
        safeString(appRaw?.section),
        safeString(appRaw?.category),
        safeString(appRaw?.kind),
        safeString(appRaw?.type),
        safeString(appRaw?.module_type),
        safeString(moduleId),
        safeString(title),
        safeString(description),
    ];
    const blob = hints.join(' ').toLowerCase();
    if (/(template|workflow|prompt|playbook|preset)/.test(blob)) return 'templates';
    if (/(agent|assistant|operator|crew|bot)/.test(blob)) return 'agents';
    if (/(integration|tool|connector|plugin|utility|app)/.test(blob)) return 'apps';
    return 'featured';
}

function moduleMarketplaceSectionLabel(sectionRaw = 'featured') {
    const section = safeString(sectionRaw).toLowerCase();
    if (section === 'templates') return 'Templates';
    if (section === 'agents') return 'Agents';
    if (section === 'apps') return 'Apps';
    return 'Featured';
}

function moduleLatestReleaseVersion(appRaw) {
    const app = appRaw && typeof appRaw === 'object' ? appRaw : {};
    const release = app?.latest_release && typeof app.latest_release === 'object' ? app.latest_release : {};
    return safeString(release?.module_version || app?.module_version || app?.version);
}

function moduleBuildMarketplaceInstalledMap(modulesRaw = []) {
    const modules = Array.isArray(modulesRaw) ? modulesRaw : [];
    const out = {};
    modules.forEach((row) => {
        const moduleId = safeString(row?.module_id);
        if (!moduleId) return;
        out[moduleId] = {
            module_id: moduleId,
            display_name: safeString(row?.display_name) || moduleId,
            description: safeString(row?.description),
            version: safeString(row?.version),
            status: safeString(row?.status).toLowerCase(),
            installed_at: safeString(row?.installed_at),
            updated_at: safeString(row?.updated_at),
        };
    });
    return out;
}

function moduleNormalizeInstalledPluginRow(pluginRaw = {}) {
    const plugin = pluginRaw && typeof pluginRaw === 'object' ? pluginRaw : {};
    const pluginId = safeString(plugin?.plugin_id || plugin?.id);
    const modeId = safeString(plugin?.mode_id || plugin?.mode).toLowerCase();
    return {
        ...plugin,
        plugin_id: pluginId,
        mode_id: modeId,
        display_name: safeString(plugin?.display_name || plugin?.name) || pluginId || modeId,
        subtitle: safeString(plugin?.subtitle),
        description: safeString(plugin?.description),
        icon: safeString(plugin?.icon),
        surface_url: safeString(plugin?.surface_url),
        surface_mode: safeString(plugin?.surface_mode),
        surface_title: safeString(plugin?.surface?.title || plugin?.surface_title),
        version: safeString(plugin?.version),
        installed: plugin?.installed !== false,
        enabled: Boolean(plugin?.enabled),
        marketplace_type: safeString(plugin?.marketplace_type) || 'plugin',
        left_nav_behavior: safeString(plugin?.left_nav_behavior),
        default_nav_section: safeString(plugin?.default_nav_section),
        default_nav_order: Number(plugin?.default_nav_order) || 0,
        workspace_id: safeString(plugin?.workspace_id || modeId),
        installed_at: safeString(plugin?.installed_at),
        updated_at: safeString(plugin?.updated_at),
        publisher_id: safeString(plugin?.publisher_id),
        publisher_name: safeString(plugin?.publisher_name),
    };
}

function moduleSetInstalledPluginRows(rowsRaw = [], { render = true } = {}) {
    const state = moduleEnsureRuntime();
    if (!state?.marketplace) return [];
    const rows = (Array.isArray(rowsRaw) ? rowsRaw : [])
        .map((plugin) => moduleNormalizeInstalledPluginRow(plugin))
        .filter((plugin) => plugin.plugin_id && plugin.mode_id);
    rows.forEach((plugin) => {
        const modeId = safeString(plugin?.mode_id).toLowerCase();
        if (modeId) MODULE_NAV_MODE_SET.add(modeId);
    });
    state.marketplace.plugins = rows;
    state.marketplace.modules = rows.map((plugin) => ({
        module_id: plugin.plugin_id,
        display_name: plugin.display_name,
        description: plugin.description || plugin.subtitle,
        version: plugin.version,
        status: plugin.enabled ? 'enabled' : 'disabled',
        installed_at: plugin.installed_at,
        updated_at: plugin.updated_at,
    }));
    if (render) moduleRenderInstalledPluginNav();
    return rows;
}

function moduleRefreshInstalledPluginNav({ force = false } = {}) {
    const state = moduleEnsureRuntime();
    if (!state?.marketplace) return null;
    if (state.marketplace.installedRefreshPromise) {
        return state.marketplace.installedRefreshPromise;
    }
    const installedFresh = Number(state.marketplace.installedLastRefreshedAt) > 0
        && Date.now() - Number(state.marketplace.installedLastRefreshedAt) < MODULE_MARKETPLACE_REFRESH_TTL_MS;
    if (!force && installedFresh && Array.isArray(state.marketplace.plugins)) {
        moduleRenderInstalledPluginNav();
        return null;
    }
    const refreshPromise = (async () => {
        try {
            const payload = await moduleFetchJsonSafe('/api/marketplace/installed');
            const rows = Array.isArray(payload?.plugins)
                ? payload.plugins
                : (Array.isArray(payload?.installed) ? payload.installed : []);
            moduleSetInstalledPluginRows(rows);
            state.marketplace.installedError = '';
        } catch (error) {
            state.marketplace.installedError = safeString(error?.message) || 'Unable to load installed plugins.';
            moduleRenderInstalledPluginNav();
        } finally {
            state.marketplace.installedRefreshPromise = null;
            state.marketplace.installedLastRefreshedAt = Date.now();
        }
    })();
    state.marketplace.installedRefreshPromise = refreshPromise;
    return refreshPromise;
}

function moduleRefreshMarketplace({ force = false, storeUrl = '' } = {}) {
    const state = moduleEnsureRuntime();
    if (!state) return null;
    const now = Date.now();
    if (state.marketplace.refreshPromise) {
        return state.marketplace.refreshPromise;
    }
    if (
        !force &&
        Number(state.marketplace.lastRefreshedAt) > 0 &&
        now - Number(state.marketplace.lastRefreshedAt) < MODULE_MARKETPLACE_REFRESH_TTL_MS &&
        state.marketplace.refreshSucceeded === true &&
        Array.isArray(state.marketplace.apps)
    ) {
        return null;
    }
    state.marketplace.loading = true;
    state.marketplace.error = '';
    state.marketplace.warning = '';
    state.marketplace.syncError = '';
    state.marketplace.degraded = false;
    const preferredStoreUrl = normalizePreferredMarketplaceStoreUrl(storeUrl);
    const refreshPromise = (async () => {
        try {
            const syncUrl = preferredStoreUrl
                ? `/api/marketplace/sync?limit=600&store=${encodeURIComponent(preferredStoreUrl)}`
                : '/api/marketplace/sync?limit=600';
            const syncPayload = await moduleFetchJsonSafe(syncUrl);
            const plugins = Array.isArray(syncPayload?.plugins) ? syncPayload.plugins : [];
            const installedPlugins = Array.isArray(syncPayload?.installed)
                ? syncPayload.installed
                : plugins.filter((plugin) => Boolean(plugin?.installed));
            state.marketplace.generatedAt = safeString(syncPayload?.generated_at || syncPayload?.synced_at);
            state.marketplace.syncedAt = safeString(syncPayload?.synced_at || syncPayload?.generated_at);
            state.marketplace.sourceLabel = safeString(syncPayload?.source_label);
            state.marketplace.storeUrl = normalizePreferredMarketplaceStoreUrl(syncPayload?.store_url || preferredStoreUrl);
            state.marketplace.pendingStoreUrl = state.marketplace.storeUrl || '';
            const nextCategories = Array.isArray(syncPayload?.categories) ? syncPayload.categories : [];
            state.marketplace.warning = safeString(syncPayload?.warning);
            state.marketplace.syncError = safeString(syncPayload?.sync_error);
            state.marketplace.degraded = Boolean(syncPayload?.degraded);
            moduleSetInstalledPluginRows(installedPlugins, { render: false });
            const nextApps = plugins.map((plugin) => {
                const categoryId = safeString(plugin?.category).toLowerCase() || 'other';
                const categoryLabel = safeString(plugin?.category_label) || safeString(plugin?.category) || 'Plugin';
                const target = safeString(plugin?.target);
                const mode = safeString(plugin?.mode);
                const downloadUrl = safeString(plugin?.manual_download_url || plugin?.download_url);
                const downloadAvailable = Boolean(plugin?.download_available || downloadUrl);
                const storeUrl = safeString(plugin?.store_url || syncPayload?.store_url);
                const channel = safeString(plugin?.channel || syncPayload?.channel) || 'stable';
                return {
                    module_id: safeString(plugin?.id),
                    display_name: safeString(plugin?.display_name || plugin?.name) || safeString(plugin?.id) || 'Marketplace item',
                    subtitle: safeString(plugin?.subtitle),
                    description: safeString(plugin?.description) || 'No description available.',
                    section: 'apps',
                    kind: safeString(plugin?.kind) || 'extension_pack',
                    type: safeString(plugin?.marketplace_type) || 'plugin',
                    marketplace_type: safeString(plugin?.marketplace_type) || 'plugin',
                    marketplace_type_label: safeString(plugin?.marketplace_type_label),
                    category: categoryLabel,
                    category_id: categoryId,
                    category_label: categoryLabel,
                    target,
                    mode,
                    mode_id: safeString(plugin?.mode_id),
                    entrypoint: safeString(plugin?.entrypoint),
                    tags: [categoryLabel, target, mode].filter(Boolean),
                    requirements: Array.isArray(plugin?.requires) ? plugin.requires : [],
                    requires: Array.isArray(plugin?.requires) ? plugin.requires : [],
                    capabilities: Array.isArray(plugin?.capabilities) ? plugin.capabilities : [],
                    version: safeString(plugin?.version),
                    latest_release: { module_version: safeString(plugin?.version) },
                    install: {
                        install_endpoint: safeString(plugin?.install_url),
                        uninstall_endpoint: safeString(plugin?.uninstall_url),
                        enable_endpoint: safeString(plugin?.enable_url),
                        disable_endpoint: safeString(plugin?.disable_url),
                        release_manifest_endpoint: downloadUrl,
                        release_download_endpoint: downloadUrl,
                        repo_url: safeString(plugin?.source) || 'website marketplace',
                        store_url: storeUrl,
                        channel,
                        detail_url: safeString(plugin?.detail_url),
                        open_in_thomas_url: safeString(plugin?.open_in_thomas_url),
                    },
                    download_available: downloadAvailable,
                    installable: Boolean(plugin?.installable),
                    installed: Boolean(plugin?.installed),
                    verified: plugin?.verified !== false,
                    enabled: Boolean(plugin?.enabled),
                    update_available: Boolean(plugin?.update_available),
                    installed_version: safeString(plugin?.installed_version),
                    surface_url: safeString(plugin?.surface_url),
                    surface_mode: safeString(plugin?.surface_mode),
                    surface_title: safeString(plugin?.surface?.title || plugin?.surface_title),
                    left_nav_behavior: safeString(plugin?.left_nav_behavior),
                    default_nav_section: safeString(plugin?.default_nav_section),
                    default_nav_order: Number(plugin?.default_nav_order) || 0,
                    workspace_id: safeString(plugin?.workspace_id),
                    icon: safeString(plugin?.icon),
                    compatibility: { eligible: Boolean(plugin?.installable || downloadAvailable) },
                    publisher: safeString(plugin?.publisher_name || plugin?.publisher_id || plugin?.source) || 'Thomas',
                    publisher_id: safeString(plugin?.publisher_id),
                    publisher_name: safeString(plugin?.publisher_name),
                };
            }).filter((plugin) => safeString(plugin?.module_id));
            const nextCatalogSignature = JSON.stringify({
                storeUrl: state.marketplace.storeUrl,
                channel: safeString(syncPayload?.channel) || 'stable',
                categories: nextCategories,
                plugins: nextApps,
            });
            state.marketplace.catalogChanged = nextCatalogSignature !== safeString(state.marketplace.catalogSignature);
            if (state.marketplace.catalogChanged) {
                state.marketplace.apps = nextApps;
                state.marketplace.categories = nextCategories;
                state.marketplace.catalogSignature = nextCatalogSignature;
            }
            state.marketplace.error = '';
            state.marketplace.refreshSucceeded = true;
            moduleWritePreferredMarketplaceStoreUrl(state.marketplace.storeUrl);
            moduleRenderInstalledPluginNav();
        } catch (error) {
            state.marketplace.error = safeString(error?.message) || 'Unable to refresh marketplace catalog.';
            state.marketplace.refreshSucceeded = false;
            if (!Array.isArray(state.marketplace.apps)) state.marketplace.apps = [];
            if (!Array.isArray(state.marketplace.modules)) state.marketplace.modules = [];
            if (!Array.isArray(state.marketplace.plugins)) state.marketplace.plugins = [];
            moduleRenderInstalledPluginNav();
        } finally {
            state.marketplace.loading = false;
            state.marketplace.refreshPromise = null;
            if (state.marketplace.refreshSucceeded) {
                state.marketplace.lastRefreshedAt = Date.now();
            }
        }
    })();
    state.marketplace.refreshPromise = refreshPromise;
    return refreshPromise;
}

async function moduleInstallMarketplacePlugin(moduleIdRaw, payload = {}) {
    const moduleId = safeString(moduleIdRaw);
    if (!moduleId) {
        return { ok: false, error: 'Missing module id.' };
    }
    try {
        const result = await moduleFetchJsonSafe(`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/install`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        return { ok: Boolean(result?.ok), data: result, plugin: result?.plugin || null };
    } catch (error) {
        return { ok: false, error: safeString(error?.message) || 'Unable to install plugin.' };
    }
}

async function moduleInstallMarketplacePluginFromDeepLink(deepLinkRaw) {
    const deepLink = safeString(deepLinkRaw);
    if (!deepLink) {
        return { ok: false, error: 'Missing plugin install link.' };
    }
    try {
        const result = await moduleFetchJsonSafe('/api/marketplace/install-from-deep-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deep_link: deepLink }),
        });
        return { ok: Boolean(result?.ok), data: result, plugin: result?.plugin || null, request: result?.request || null };
    } catch (error) {
        return { ok: false, error: safeString(error?.message) || 'Unable to install plugin from Thomas link.' };
    }
}

async function moduleUninstallMarketplacePlugin(moduleIdRaw) {
    const moduleId = safeString(moduleIdRaw);
    if (!moduleId) {
        return { ok: false, error: 'Missing module id.' };
    }
    try {
        const result = await moduleFetchJsonSafe(`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/uninstall`, { method: 'POST' });
        return { ok: Boolean(result?.ok), data: result };
    } catch (error) {
        return { ok: false, error: safeString(error?.message) || 'Unable to uninstall plugin.' };
    }
}

async function moduleSetMarketplacePluginEnabled(moduleIdRaw, enabled = false) {
    const moduleId = safeString(moduleIdRaw);
    if (!moduleId) {
        return { ok: false, error: 'Missing module id.' };
    }
    const action = enabled ? 'enable' : 'disable';
    try {
        const result = await moduleFetchJsonSafe(`/api/marketplace/plugins/${encodeURIComponent(moduleId)}/${action}`, { method: 'POST' });
        return { ok: Boolean(result?.ok), data: result, plugin: result?.plugin || null };
    } catch (error) {
        return { ok: false, error: safeString(error?.message) || 'Unable to update plugin state.' };
    }
}

async function moduleImportMarketplacePlugin(source) {
    // One import contract for both shapes: a File posts multipart, a
    // { url } object posts JSON - the response handling must not fork.
    let body = null;
    let headers;
    if (source instanceof File) {
        body = new FormData();
        body.append('file', source, source.name || 'plugin.zip');
    } else if (safeString(source?.url).trim()) {
        headers = { 'Content-Type': 'application/json' };
        body = JSON.stringify({ url: safeString(source.url).trim() });
    } else {
        return { ok: false, error: 'Pick a plugin ZIP or paste a plugin URL first.' };
    }
    try {
        const response = await fetch('/api/marketplace/import', {
            method: 'POST',
            headers,
            body,
        });
        const text = await response.text();
        let payload = {};
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch {
                payload = {};
            }
        }
        if (!response.ok) {
            throw new Error(safeString(payload?.error) || text || 'Unable to import plugin.');
        }
        return { ok: Boolean(payload?.ok), data: payload, plugin: payload?.plugin || null };
    } catch (error) {
        return { ok: false, error: safeString(error?.message) || 'Unable to import plugin.' };
    }
}

