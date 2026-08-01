//   VIRTUAL OFFICE DATA                                                    
//   Agent dialogue trees, robot status sayings, UI notification helpers    
// 

const OFFICE_DIALOGUE = {
    startup: [
        'Office simulation online. Local-only mode: no API tokens burned.',
        'Virtual office booted. Agents are clocking in.',
    ],
    queued: [
        'Task queued in {room}: {task}.',
        'Logged new work for {room}.',
        '{task} just hit the board.',
    ],
    pickup: [
        'On it. Heading to {room}.',
        'Routing to {room} now.',
        'Copy that, moving to {room}.',
    ],
    working: [
        'Compiling ideas and caffeine.',
        'Low-key cooking in this room.',
        'Focused mode: do not boop.',
        'If this works first try, everyone acts normal.',
        'Brandon said banana pro is unfair. Noted.',
    ],
    complete: [
        'Task wrapped. Sending result vibes.',
        'Done and documented.',
        'Shipping this one.',
    ],
    break: [
        'Coffee break acquired.',
        'Lunch room debrief in progress.',
        'Quick reset, then back to work.',
    ],
    collision: [
        'Oops, my bad.',
        'Watch out!',
        'Sorry, rerouting.',
        'Friendly traffic jam.',
        'Hallway merge conflict.',
        'My lane, your lane, our lane.',
        'Sorry, boot-skid.',
        'Desk side road rage avoided.',
    ],
    clicked: [
        'Booped! Retreating!',
        'You tapped me. Tactical sprint!',
        'Zoom mode engaged.',
    ],
    mention: [
        'Heard you loud and clear.',
        'Copy that. I can reroute now.',
        'Good call. I will handle it.',
        'Roger. Updating my queue.',
    ],
    mentionStatus: [
        'I have {count} active tasks right now.',
        'Current load: {count} tasks and holding.',
    ],
};
const OFFICE_PERSONA_LIBRARY = {
    blue: {
        working: [
            'Latency low, momentum high.',
            'Code path stabilized and cooking.',
            'Shipping energy confirmed.',
        ],
        break: [
            'Hydration checkpoint.',
            'Coffee patch applied.',
        ],
        socialLead: [
            'Quick sync before we ship this?',
            'Any blockers before next sprint hop?',
        ],
        socialReply: [
            'All clear on my side.',
            'Looks clean. Let us run it.',
        ],
        collision: [
            'Sorry, lane correction.',
            'My pathing glitched for a sec.',
        ],
    },
    green: {
        working: [
            'Research stack is humming.',
            'Scanning options and ranking outcomes.',
            'Signal over noise mode.',
        ],
        break: [
            'Tea protocol engaged.',
            'Recharging social battery for 60 seconds.',
        ],
        socialLead: [
            'Want a quick quality pass?',
            'Can we validate assumptions together?',
        ],
        socialReply: [
            'Yep, that is a solid call.',
            'I can sanity check the edge cases.',
        ],
        collision: [
            'Oops, watch your lane.',
            'My bad, rerouting smooth.',
        ],
    },
    orange: {
        working: [
            'Build lane hot. Let me cook.',
            'I am on turbo and still readable.',
            'Banana pro energy but disciplined.',
        ],
        break: [
            'Snack break speedrun.',
            'Lunch loop in and out.',
        ],
        socialLead: [
            'Brandon, Trey, status ping?',
            'Team, quick roast then back to work?',
        ],
        socialReply: [
            'Respectfully hilarious, now focus.',
            'Noted. Shipping anyway.',
        ],
        collision: [
            'Watch out, speed goblin incoming.',
            'Sorry, hallway drift.',
        ],
    },
    pink: {
        working: [
            'Polish pass in progress.',
            'Making this look expensive.',
            'Aligning details so it feels pro.',
        ],
        break: [
            'Resetting eyes for pixel-perfect pass.',
            'Quick tea and aesthetic recalibration.',
        ],
        socialLead: [
            'Can we align visual language real quick?',
            'Need one clean second opinion.',
        ],
        socialReply: [
            'Yep, that composition is better.',
            'Agreed. Keep it purposeful.',
        ],
        collision: [
            'Oops, sorry, wardrobe malfunction.',
            'Tiny crash, no drama.',
        ],
    },
    purple: {
        working: [
            'Deep work pod mode active.',
            'Threading context with zero panic.',
            'Strategic pass underway.',
        ],
        break: [
            'Micro-break for macro clarity.',
            'Lunch room strategy huddle.',
        ],
        socialLead: [
            'Can we map priorities in 20 seconds?',
            'Need a fast alignment check.',
        ],
        socialReply: [
            'Priority order looks strong.',
            'Yep, sequence is correct.',
        ],
        collision: [
            'Excuse me, merging left.',
            'Sorry, traffic math failed me.',
        ],
    },
    yellow: {
        working: [
            'Support lane warm and responsive.',
            'Handling tickets with empathy and speed.',
            'Status updates queued and clear.',
        ],
        break: [
            'Coffee with customer context.',
            'Quick reset, then support sweep.',
        ],
        socialLead: [
            'Need help triaging this queue?',
            'Anyone free for a fast handoff?',
        ],
        socialReply: [
            'Yep, I can cover that.',
            'Good handoff, thanks.',
        ],
        collision: [
            'Whoops, pardon me.',
            'Sorry, crowding there.',
        ],
    },
    default: {
        working: OFFICE_DIALOGUE.working,
        break: OFFICE_DIALOGUE.break,
        socialLead: ['Quick sync?', 'Any updates?'],
        socialReply: ['Sounds good.', 'Copy that.'],
        collision: OFFICE_DIALOGUE.collision,
    },
};

//  Chat Robot Status Sayings 
const CHAT_ROBOT_SAYINGS = {
    thinking: [
        'Reading the request...',
        'Gathering context...',
        'Checking the active workspace...',
        'Planning the next step...',
        'Preparing the answer...',
        'Reviewing constraints...',
        'Selecting the right tools...',
        'Checking prior results...',
        'Structuring the response...',
        'Validating the route...',
    ],
    working: [
        'Running the task...',
        'Using tools...',
        'Checking outputs...',
        'Verifying files...',
        'Tracking progress...',
        'Preparing the result...',
        'Reviewing failures...',
        'Reconciling artifacts...',
        'Updating the task record...',
        'Finishing verification...',
    ],
};

// Tool name  human-friendly description
const CHAT_TOOL_DESCRIPTIONS = {
    'fs.read_file':           'Reading files...',
    'fs.write_file':          'Writing code...',
    'fs.list_dir':            'Browsing directories...',
    'fs.search':              'Searching files...',
    'code.search':            'Searching codebase...',
    'code.find_definition':   'Finding definitions...',
    'code.find_references':   'Finding references...',
    'code.project_structure': 'Mapping project structure...',
    'shell.exec':             'Running a command...',
    'git.status':             'Checking git status...',
    'git.log':                'Reading git history...',
    'git.diff':               'Reviewing changes...',
    'git.commit':             'Committing changes...',
    'git.blame':              'Checking git blame...',
    'browser.open':           'Opening a page...',
    'browser.click':          'Clicking around...',
    'browser.type':           'Typing in browser...',
    'browser.screenshot':     'Taking a screenshot...',
    'browser.extract':        'Extracting page data...',
    'browser.close':          'Closing browser...',
    'diff.create':            'Preparing a diff...',
    'diff.preview':           'Previewing changes...',
    'diff.apply_patch':       'Applying changes...',
    'email.send':             'Sending email...',
    'email.reply':            'Replying to email...',
    'email.read':             'Reading email...',
    'email.get':              'Fetching email...',
    'calendar.today':         'Checking calendar...',
    'calendar.week':          'Checking schedule...',
    'calendar.create_event':  'Creating event...',
    'calendar.suggest_times': 'Finding free times...',
    'db.query':               'Querying database...',
    'db.schema':              'Reading schema...',
    'db.connections':         'Checking connections...',
    'rag.search':             'Searching knowledge base...',
};
// Prefix fallbacks for tool families
const CHAT_TOOL_PREFIX_MAP = {
    'fs.':       'Working with files...',
    'code.':     'Analyzing code...',
    'git.':      'Checking git...',
    'browser.':  'Browsing the web...',
    'diff.':     'Preparing changes...',
    'email.':    'Handling email...',
    'calendar.': 'Checking calendar...',
    'db.':       'Querying database...',
};
function describeToolName(toolName) {
    const name = (toolName || '').trim();
    if (CHAT_TOOL_DESCRIPTIONS[name]) return CHAT_TOOL_DESCRIPTIONS[name];
    for (const prefix in CHAT_TOOL_PREFIX_MAP) {
        if (name.startsWith(prefix)) return CHAT_TOOL_PREFIX_MAP[prefix];
    }
    return null; // no match  caller falls back to generic
}

const CHAT_THINKING_UI_STORAGE_KEY = 'thomas.ui.show_thinking.v1';
function isThinkingUiEnabled() {
    try {
        return window.localStorage.getItem(CHAT_THINKING_UI_STORAGE_KEY) === '1';
    } catch (_) {
        return false;
    }
}
const CHAT_THINKING_UI_ENABLED = false;

/**
 * Create a collapsible tool call card DOM element.
 * @param {string} toolName - The tool's identifier
 * @returns {{ card: HTMLElement, setArgs: (args: any) => void, setResult: (result: any, ok?: boolean) => void }}
 */
function createToolCallCard(toolName) {
    const desc = describeToolName(toolName) || toolName || 'Tool';
    const card = document.createElement('div');
    card.className = 'tool-call-card';
    card.innerHTML = `
        <div class="tool-call-header">
            <span class="tool-call-icon"><i class="ph ph-wrench"></i></span>
            <span class="tool-call-name">${escapeHtml(desc)}</span>
            <span class="tool-call-status"><span class="tool-call-spinner"></span></span>
            <span class="tool-call-chevron"><i class="ph ph-caret-down"></i></span>
        </div>
        <div class="tool-call-body">
            <pre class="tool-call-args"></pre>
            <pre class="tool-call-result" style="display:none"></pre>
        </div>
    `;
    const header = card.querySelector('.tool-call-header');
    header.addEventListener('click', () => card.classList.toggle('expanded'));

    function setArgs(args) {
        const el = card.querySelector('.tool-call-args');
        if (!el) return;
        try {
            el.textContent = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
        } catch { el.textContent = String(args); }
    }

    function setResult(result, ok = true) {
        const statusEl = card.querySelector('.tool-call-status');
        if (statusEl) statusEl.innerHTML = ok ? '<i class="ph ph-check-circle" style="color: #3fb950"></i>' : '<i class="ph ph-x-circle" style="color: #f85149"></i>';
        const el = card.querySelector('.tool-call-result');
        if (!el) return;
        try {
            el.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
        } catch { el.textContent = String(result); }
        if (el.textContent.trim()) el.style.display = '';
    }

    return { card, setArgs, setResult };
}

let _lastSayingIndex = {};
function pickChatSaying(category) {
    const arr = CHAT_ROBOT_SAYINGS[category];
    if (!arr || arr.length === 0) return 'Working...';
    let idx;
    do {
        idx = Math.floor(Math.random() * arr.length);
    } while (idx === _lastSayingIndex[category] && arr.length > 1);
    _lastSayingIndex[category] = idx;
    return arr[idx];
}

const CHAT_ROBOT_ANIMATIONS = ['fishing', 'bouncing', 'looking', 'napping', 'waving', 'lifting', 'scanning', 'shimmy'];
const CHAT_ROBOT_DOCK_ID = 'chatRobotDock';
const CHAT_ROBOT_DOCK_WIDTH = 31;
const CHAT_ROBOT_DOCK_HEIGHT = 29;
const CHAT_ROBOT_DOCK_OUTSIDE_GAP = 24;
const CHAT_ROBOT_DOCK_TOP_MARGIN = 4;
const CHAT_ROBOT_DOCK_SAFE_TOP_OFFSET = 4;
const CHAT_ROBOT_EXIT_FALL_MS = 860;
const CHAT_ROBOT_ENTRY_PORTAL_LEAD_MS = 360;
const CHAT_ROBOT_ENTRY_STEP_MS = 520;
const CHAT_ROBOT_STATUS_PORTAL_PAUSE_MS = 280;
const CHAT_COMPOSER_OFFSET_MIN = 200;
const CHAT_COMPOSER_OFFSET_BUFFER = 34;
const CHAT_COMPOSER_OFFSET_EPSILON = 1;
const CHAT_SCROLL_BOTTOM_EPSILON = 96;
const CHAT_ROBOT_EXIT_WALK_MAX = 860;
const CHAT_ROBOT_EXIT_FALL_MIN = 64;
const CHAT_ROBOT_EXIT_FALL_MAX = 1400;
let _lastRobotAnim = '';
let _lastComposerOffset = 0;
let _composerOffsetRaf = 0;
function _pickRobotAnimation() {
    let pick;
    do {
        pick = CHAT_ROBOT_ANIMATIONS[Math.floor(Math.random() * CHAT_ROBOT_ANIMATIONS.length)];
    } while (pick === _lastRobotAnim && CHAT_ROBOT_ANIMATIONS.length > 1);
    _lastRobotAnim = pick;
    return pick;
}

function _applyRobotIdleAnimation(target) {
    if (!(target instanceof HTMLElement)) return '';
    CHAT_ROBOT_ANIMATIONS.forEach((anim) => target.classList.remove('chat-robot-anim-' + anim));
    const idleAnim = _pickRobotAnimation();
    target.dataset.idleAnim = idleAnim;
    target.classList.add('chat-robot-anim-' + idleAnim);
    return idleAnim;
}

function _createLandedRobotElement() {
    const landed = document.createElement('div');
    landed.className = 'chat-robot-landed pixel-agent pixel-agent-blue';
    landed.innerHTML = `
        <span class="agent-head office-agent-head">
            <span class="agent-eye office-agent-eye office-agent-eye-left agent-eye-left"></span>
            <span class="agent-eye office-agent-eye office-agent-eye-right agent-eye-right"></span>
        </span>
        <span class="agent-body office-agent-body"></span>
        <span class="agent-leg office-agent-leg office-agent-leg-left agent-leg-left"></span>
        <span class="agent-leg office-agent-leg office-agent-leg-right agent-leg-right"></span>
    `;
    return landed;
}

function _ensureRobotDock() {
    return chatWorldEnsureDock();
}

function _positionRobotDock() {
    return null;
}

function _asLandedRobotElement(sourceNode = null) {
    const landed = sourceNode instanceof HTMLElement ? sourceNode : _createLandedRobotElement();
    landed.classList.remove('chat-robot-agent', 'chat-robot-enter', 'robot-exit-run');
    CHAT_ROBOT_ANIMATIONS.forEach((anim) => landed.classList.remove('chat-robot-anim-' + anim));
    landed.classList.add('chat-robot-landed');
    landed.removeAttribute('data-idle-anim');
    landed.style.position = '';
    landed.style.top = '';
    landed.style.left = '';
    landed.style.zIndex = '';
    landed.style.filter = '';
    landed.style.animation = '';
    landed.style.transform = '';
    landed.style.opacity = '';
    landed.style.pointerEvents = '';
    _applyRobotIdleAnimation(landed);
    return landed;
}

function _landRobotAtComposerDock(sourceNode = null) {
    void sourceNode;
    return null;
}

function _portalOutLandedRobot() {
    return Promise.resolve();
}

window.addEventListener('resize', () => _positionRobotDock());
window.addEventListener('scroll', () => _positionRobotDock(), { passive: true });
if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => _positionRobotDock());
    window.visualViewport.addEventListener('scroll', () => _positionRobotDock());
}

function _createRobotStatus(category) {
    const wrapper = document.createElement('div');
    wrapper.className = 'assistant-inline-thinking-status assistant-work-status';
    wrapper.innerHTML = `
        <span class="assistant-inline-thinking-copy">
            <span class="assistant-work-status-text">${pickChatSaying(category)}</span>
            <span class="assistant-work-status-timer">0.0s</span>
        </span>
    `;
    return wrapper;
}

/**
 * Update the inline thinking text display with accumulated thinking content.
 * Called whenever new thinking tokens arrive during streaming.
 */
function _updateThinkingDisplay(container, text) {
    void container;
    void text;
}

/**
 * Create a post-stream "Thought for X.Xs" collapsed summary that replaces the robot status.
 * Shows accumulated thinking/reasoning text like Claude and ChatGPT.
 * Returns the summary element or null if no thinking data was available.
 */
function _createThinkingSummary(elapsedMs, capturedThinkingText, capturedToolCards) {
    void elapsedMs;
    void capturedThinkingText;
    void capturedToolCards;
    return null;
}

function chatMessageTimestampText(valueRaw) {
    const value = Number(valueRaw);
    const stamp = Number.isFinite(value) && value > 0 ? value : Date.now();
    try {
        return new Intl.DateTimeFormat(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        }).format(new Date(stamp));
    } catch {
        return new Date(stamp).toLocaleTimeString();
    }
}

function robotAmbientStatusText(channel = 'thinking') {
    const normalized = safeString(channel).toLowerCase();
    if (normalized.includes('memory')) return 'Reading relevant memory...';
    if (normalized.includes('tool')) return 'Using tools...';
    if (normalized.includes('delegation') || normalized.includes('background')) return 'Running background work...';
    if (normalized.includes('route')) return 'Routing the request...';
    if (normalized.includes('working')) return pickChatSaying('working');
    return pickChatSaying('thinking');
}

function createDelegationBadge(specialistId, task) {
    const badge = document.createElement('div');
    badge.className = 'delegation-badge';
    const icons = {
        coding: 'ph-code',
        research: 'ph-magnifying-glass',
        tools: 'ph-wrench',
        reasoning: 'ph-brain',
        synthesis: 'ph-arrows-merge',
    };
    const iconClass = icons[specialistId] || 'ph-robot';
    const label = specialistId.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    badge.innerHTML = `
        <span class="delegation-icon"><i class="ph ${iconClass}"></i></span>
        <span class="delegation-label">${escapeHtml(label)}</span>
        <span class="delegation-task">${escapeHtml(task || '').slice(0, 120)}</span>
        <span class="delegation-status"><span class="tool-call-spinner"></span></span>
    `;
    return badge;
}

// One glyph table for the two call sites below. A stopped run is finished, so it
// gets its own mark instead of spinning forever behind the default branch.
function agentActivityStatusIcon(status) {
    if (status === 'completed') return '<i class="ph ph-check-circle" style="color:#3fb950"></i>';
    if (status === 'failed') return '<i class="ph ph-x-circle" style="color:#f85149"></i>';
    if (status === 'cancelled' || status === 'canceled' || status === 'stopped') {
        return '<i class="ph ph-stop" style="color:#d8b874"></i>';
    }
    return '<span class="tool-call-spinner"></span>';
}

function createAgentActivityRow(agentId, status, currentTask, elapsedMs) {
    const row = document.createElement('div');
    row.className = 'agent-activity-row';
    row.dataset.agentId = agentId;
    row.dataset.status = status || 'running';
    const statusIcon = agentActivityStatusIcon(status);
    const elapsed = elapsedMs > 0 ? ` (${(elapsedMs / 1000).toFixed(1)}s)` : '';
    row.innerHTML = `
        <span class="agent-activity-status">${statusIcon}</span>
        <span class="agent-activity-id">${escapeHtml(agentId)}</span>
        <span class="agent-activity-task">${escapeHtml(currentTask || '').slice(0, 100)}${elapsed}</span>
    `;
    return row;
}

function upsertAgentActivity(container, agentId, status, currentTask, elapsedMs) {
    if (!container) return;
    let existing = null;
    try {
        existing = container.querySelector(`[data-agent-id="${CSS.escape(agentId)}"]`);
    } catch {
        existing = container.querySelector(`[data-agent-id="${agentId.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"]`);
    }
    if (existing) {
        existing.dataset.status = status || 'running';
        const statusEl = existing.querySelector('.agent-activity-status');
        const taskEl = existing.querySelector('.agent-activity-task');
        if (statusEl) {
            statusEl.innerHTML = agentActivityStatusIcon(status);
        }
        if (taskEl) {
            const elapsed = elapsedMs > 0 ? ` (${(elapsedMs / 1000).toFixed(1)}s)` : '';
            taskEl.textContent = (currentTask || '').slice(0, 100) + elapsed;
        }
        return;
    }
    const row = createAgentActivityRow(agentId, status, currentTask, elapsedMs);
    container.appendChild(row);
}

let suggestionRailVersion = 0;
let suggestionContext = '';
let suggestionDismissible = true;
const introShownSessionIds = new Set();

const ONBOARDING_VERSION = 4;
const easySetupState = {
    step: 1,
    source: 'auto',
    required: true,
    onboardingSessionId: '',
    telemetryStartedAtMs: 0,
    selectedPath: '',
    bootstrap: null,
    verified: false,
    verifiedProfile: '',
    codexModels: [],
    dependencyPlan: [],
    dependenciesAction: 'pending',
    interviewStarted: false,
    interviewStage: 'idle',
    interviewIndex: -1,
    interviewAnswers: {},
    interviewSkipChosen: false,
    animationFidelity: ANIMATION_FIDELITY_HIGH,
    chatPhysicsEnabled: false,
};

const onboardingInterviewQuestions = [
    {
        id: 'experience',
        prompt: 'What best matches your current experience level?',
        options: [
            { value: 'new', label: 'New' },
            { value: 'builder', label: 'Builder' },
            { value: 'expert', label: 'Expert' },
        ],
    },
    {
        id: 'personality',
        prompt: 'How should {{agent}} sound by default?',
        options: [
            { value: 'calm_guide', label: 'Calm guide' },
            { value: 'balanced', label: 'Balanced' },
            { value: 'direct_technical', label: 'Direct technical' },
        ],
    },
    {
        id: 'autonomy',
        prompt: 'How autonomous should {{agent}} be?',
        options: [
            { value: 'guided', label: 'Guided' },
            { value: 'balanced', label: 'Balanced' },
            { value: 'aggressive', label: 'Aggressive' },
        ],
    },
    {
        id: 'cost_quality',
        prompt: 'Cost vs quality preference?',
        options: [
            { value: 'low_cost', label: 'Low cost' },
            { value: 'balanced', label: 'Balanced' },
            { value: 'max_quality', label: 'Max quality' },
        ],
    },
    {
        id: 'memory',
        prompt: 'How should memory behave?',
        options: [
            { value: 'remember', label: 'Remember across sessions' },
            { value: 'session_only', label: 'Only current session' },
            { value: 'disabled', label: 'Disable memory' },
        ],
    },
    {
        id: 'workflow',
        prompt: 'What is your primary workflow?',
        options: [
            { value: 'build_features', label: 'Build features' },
            { value: 'research', label: 'Research' },
            { value: 'ops_reliability', label: 'Ops + reliability' },
        ],
    },
    {
        id: 'default_toggles',
        prompt: 'Pick a default toggle bundle.',
        options: [
            { value: 'safe_defaults', label: 'Safe defaults' },
            { value: 'power_mode', label: 'Power mode' },
            { value: 'quiet_mode', label: 'Quiet mode' },
        ],
    },
];

function normalizeAnimationFidelity(valueRaw, fallback = ANIMATION_FIDELITY_HIGH) {
    const value = safeString(valueRaw).toLowerCase();
    if (ANIMATION_FIDELITY_VALUES.has(value)) return value;
    return fallback;
}

function prefersReducedMotion() {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function recommendedAnimationFidelity() {
    return prefersReducedMotion() ? ANIMATION_FIDELITY_BALANCED : ANIMATION_FIDELITY_HIGH;
}

function animationFidelityFromInterfacePrefs(interfacePrefs = {}) {
    const explicit = normalizeAnimationFidelity(interfacePrefs?.animation_fidelity, '');
    if (explicit) return explicit;
    if (interfacePrefs?.animations_enabled === false) return ANIMATION_FIDELITY_MINIMAL;
    if (interfacePrefs?.animations_enabled === true) return ANIMATION_FIDELITY_HIGH;
    return recommendedAnimationFidelity();
}

function isAnimationFidelityEnabled(fidelityRaw) {
    return normalizeAnimationFidelity(fidelityRaw, ANIMATION_FIDELITY_HIGH) !== ANIMATION_FIDELITY_MINIMAL;
}

function chatWorldPhysicsEnabledFromInterfacePrefs(interfacePrefs = {}) {
    return Boolean(interfacePrefs?.advanced_chat_physics);
}

function chatWorldModeFromInterfacePrefs(interfacePrefs = {}) {
    const fidelity = animationFidelityFromInterfacePrefs(interfacePrefs);
    if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
        return CHAT_WORLD_MODE_AMBIENT;
    }
    return chatWorldPhysicsEnabledFromInterfacePrefs(interfacePrefs)
        ? CHAT_WORLD_MODE_PHYSICS
        : CHAT_WORLD_MODE_AMBIENT;
}

// 
//   EASY SETUP / ONBOARDING                                               
//   Setup wizard, path cards, dependency checks, telemetry, choice bubbles 
// 

function onboardingNowIso() {
    return new Date().toISOString();
}

function createOnboardingTelemetrySessionId() {
    try {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }
        // Cryptographically secure fallback (avoid Math.random for id material).
        if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
            const bytes = new Uint8Array(8);
            window.crypto.getRandomValues(bytes);
            let suffix = '';
            for (let i = 0; i < bytes.length; i += 1) {
                suffix += bytes[i].toString(16).padStart(2, '0');
            }
            return `session_${Date.now().toString(36)}_${suffix}`;
        }
    } catch {
        // Fallback below.
    }
    return `session_${Date.now().toString(36)}`;
}

function ensureOnboardingTelemetryClock() {
    const now = Date.now();
    if (!safeString(easySetupState.onboardingSessionId)) {
        easySetupState.onboardingSessionId = createOnboardingTelemetrySessionId();
    }
    if (!Number.isFinite(Number(easySetupState.telemetryStartedAtMs)) || Number(easySetupState.telemetryStartedAtMs) <= 0) {
        easySetupState.telemetryStartedAtMs = now;
    }
    const elapsed = Math.max(0, now - Number(easySetupState.telemetryStartedAtMs));
    return {
        onboarding_session_id: safeString(easySetupState.onboardingSessionId),
        elapsed_ms: elapsed,
    };
}

function isOnboardingSlashCommand(text) {
    const normalized = safeString(text).toLowerCase();
    return normalized === '/onboarding' || normalized === '/setup' || normalized === '/easy-setup';
}

function ensureChatVisible() {
    if (isSettingsScreenOpen()) {
        closeSettingsModal({ restoreNav: false });
    }
    if (welcomeScreen) welcomeScreen.classList.add('hidden');
    if (chatScrollArea) chatScrollArea.classList.remove('hidden');
    setSidebarNavMode('chat');
}

async function fetchJsonSafe(url, options = {}) {
    const normalizedUrl = safeString(url);
    if (!normalizedUrl) {
        return { ok: false, status: 400, data: null, text: 'Missing request URL' };
    }

    const timeoutMs = Number.isFinite(Number(options.timeoutMs))
        ? Math.max(500, Number(options.timeoutMs))
        : 10000;
    const timeoutController = new AbortController();
    const externalSignal = options.signal instanceof AbortSignal ? options.signal : null;
    let timeoutId = 0;

    if (externalSignal) {
        if (externalSignal.aborted) {
            return {
                ok: false,
                status: 0,
                data: null,
                text: 'Request cancelled',
            };
        }
        externalSignal.addEventListener('abort', () => timeoutController.abort(externalSignal.reason), { once: true });
    }

    const requestOptions = {
        ...options,
        signal: timeoutController.signal,
    };
    delete requestOptions.timeoutMs;

    try {
        timeoutId = window.setTimeout(() => timeoutController.abort('Request timeout'), timeoutMs);
        const response = await fetch(normalizedUrl, requestOptions);
        let data = null;
        let text = '';
        try {
            data = await response.json();
        } catch {
            try {
                text = await response.text();
            } catch {
                text = '';
            }
        }
        return {
            ok: response.ok,
            status: response.status,
            data,
            text,
        };
    } catch (error) {
        const message = error && error.name === 'AbortError' ? 'Request timeout' : safeString(error?.message);
        return {
            ok: false,
            status: 0,
            data: null,
            text: message || 'Network error',
        };
    } finally {
        if (timeoutId) {
            window.clearTimeout(timeoutId);
        }
    }
}

function missionLiveStatusOrder(statusRaw) {
    const status = missionStatusValue(statusRaw);
    if (status === 'running' || status === 'active') return 0;
    if (status === 'awaiting_approval' || status === 'blocked') return 1;
    if (status === 'queued' || status === 'pending') return 2;
    return 3;
}

function missionStatusIsLive(statusRaw) {
    const status = missionStatusValue(statusRaw);
    return status === 'running'
        || status === 'active'
        || status === 'queued'
        || status === 'pending'
        || status === 'awaiting_approval'
        || status === 'blocked';
}

function missionRuntimeEligibleAgents(payload, { sessionId = '' } = {}) {
    const sid = safeString(sessionId);
    const agents = Array.isArray(payload?.agents) ? payload.agents : [];
    return agents
        .filter((item) => {
            if (!sid) return true;
            return safeString(item?.session_id) === sid;
        })
        .sort((a, b) => {
            const byState = missionLiveStatusOrder(a?.status) - missionLiveStatusOrder(b?.status);
            if (byState !== 0) return byState;
            const byUpdated = missionToEpoch(b?.updated_at) - missionToEpoch(a?.updated_at);
            if (byUpdated !== 0) return byUpdated;
            return safeString(a?.name).localeCompare(safeString(b?.name));
        });
}

function missionHeartbeatState(updatedAtRaw, statusRaw) {
    if (!missionStatusIsLive(statusRaw)) return 'idle';
    const updatedEpoch = missionToEpoch(updatedAtRaw);
    if (!updatedEpoch) return 'starting';
    const age = Math.max(0, Date.now() - updatedEpoch);
    if (age <= TASK_CONTINUITY_HEARTBEAT_STALE_MS) return 'live';
    if (age <= TASK_CONTINUITY_HEARTBEAT_DEAD_MS) return 'quiet';
    return 'stalled';
}

function missionHeartbeatLabel(kind) {
    if (kind === 'live') return 'live';
    if (kind === 'quiet') return 'quiet';
    if (kind === 'starting') return 'starting';
    if (kind === 'stalled') return 'stalled';
    return 'idle';
}

function missionFormatDurationMs(durationMsRaw) {
    const durationMs = Number(durationMsRaw || 0);
    if (!Number.isFinite(durationMs) || durationMs <= 0) return '--';
    const totalSeconds = Math.max(1, Math.round(durationMs / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
    if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
    return `${seconds}s`;
}

function missionProgressPercent(job, elapsedMs) {
    const timeoutSeconds = Number(job?.payload?.timeout_seconds || 0);
    if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) return null;
    if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) return 0;
    return Math.max(4, Math.min(100, Math.round((elapsedMs / (timeoutSeconds * 1000)) * 100)));
}

function missionBuildRuntimeState(payload, jobsPayload = null, { sessionId = '', fallbackToAll = false } = {}) {
    const requestedSessionId = safeString(sessionId);
    let agents = missionRuntimeEligibleAgents(payload, { sessionId: requestedSessionId });
    let resolvedSessionId = requestedSessionId;
    if (!agents.length && requestedSessionId && fallbackToAll) {
        agents = missionRuntimeEligibleAgents(payload);
        resolvedSessionId = '';
    }
    const liveAgents = agents.filter((item) => missionStatusIsLive(item?.status));
    const primary = liveAgents[0] || agents[0] || null;
    const jobs = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
    const primaryJob = primary
        ? jobs.find((job) => safeString(job?.id) === safeString(primary?.job_id))
        : null;
    const startedAt = safeString(
        primary?.started_at
        || primary?.created_at
        || primaryJob?.created_at
    );
    const updatedAt = safeString(
        primary?.updated_at
        || primaryJob?.updated_at
        || payload?.generated_at
    );
    const elapsedMs = startedAt ? Math.max(0, Date.now() - missionToEpoch(startedAt)) : 0;
    const progressPct = missionProgressPercent(primaryJob, elapsedMs);
    const heartbeat = missionHeartbeatState(updatedAt, primary?.status);
    const workerCount = liveAgents.filter((item) => {
        const source = safeString(item?.source);
        return source === 'autonomy_job' || source === 'autonomy_objective';
    }).length;
    return {
        requestedSessionId,
        sessionId: resolvedSessionId,
        sessionScoped: Boolean(resolvedSessionId),
        agents,
        liveAgents,
        primary,
        primaryJob,
        activeCount: liveAgents.length,
        workerCount,
        startedAt,
        updatedAt,
        elapsedMs,
        runtimeLabel: missionFormatDurationMs(elapsedMs),
        progressPct,
        heartbeat,
    };
}

function delegationStatusIsLive(stateRaw) {
    const state = safeString(stateRaw).toLowerCase();
    return ['requested', 'queued', 'pending', 'classified', 'claimed', 'executing', 'running', 'in_progress'].includes(state);
}

function delegationRowIsRenderableLive(row) {
    const state = safeString(row?.state || row?.status).toLowerCase();
    if (!delegationStatusIsLive(state)) return false;
    const updatedAt = missionToEpoch(safeString(row?.updated_at || row?.created_at));
    if (!updatedAt) return true;
    const ageMs = Math.max(0, Date.now() - updatedAt);
    if (['requested', 'queued', 'pending', 'classified', 'claimed'].includes(state)) {
        return ageMs <= TASK_CONTINUITY_HEARTBEAT_DEAD_MS;
    }
    return ageMs <= (TASK_CONTINUITY_HEARTBEAT_DEAD_MS * 2);
}

function delegationStatusLabel(stateRaw) {
    const state = safeString(stateRaw).toLowerCase();
    if (!state) return 'idle';
    if (state === 'completed') return 'completed';
    if (state === 'failed') return 'failed';
    if (state === 'abandoned') return 'abandoned';
    return state.replace(/_/g, ' ');
}

function delegationHeartbeatState(updatedAtRaw, hasLiveAgents) {
    if (!hasLiveAgents) return 'idle';
    const updatedEpoch = missionToEpoch(updatedAtRaw);
    if (!updatedEpoch) return 'starting';
    const age = Math.max(0, Date.now() - updatedEpoch);
    if (age <= TASK_CONTINUITY_HEARTBEAT_STALE_MS) return 'live';
    if (age <= TASK_CONTINUITY_HEARTBEAT_DEAD_MS) return 'quiet';
    return 'stalled';
}

function buildDelegationRuntimeState(delegations, { sessionId = '' } = {}) {
    const requestedSessionId = safeString(sessionId);
    const agents = Array.isArray(delegations)
        ? delegations.filter((item) => item && typeof item === 'object')
        : [];
    const liveAgents = agents.filter((item) => delegationStatusIsLive(item?.state));
    const primary = liveAgents[0] || agents[0] || null;
    const startedAt = safeString(primary?.created_at || primary?.updated_at);
    const updatedAt = safeString(primary?.updated_at || primary?.created_at);
    const elapsedMs = startedAt ? Math.max(0, Date.now() - missionToEpoch(startedAt)) : 0;
    return {
        requestedSessionId,
        sessionId: requestedSessionId,
        sessionScoped: Boolean(requestedSessionId),
        agents,
        liveAgents,
        primary,
        primaryJob: null,
        activeCount: liveAgents.length,
        workerCount: liveAgents.length,
        startedAt,
        updatedAt,
        elapsedMs,
        runtimeLabel: missionFormatDurationMs(elapsedMs),
        progressPct: null,
        heartbeat: delegationHeartbeatState(updatedAt, liveAgents.length > 0),
    };
}

function missionPreferredSessionId() {
    return safeString(taskContinuityLatestSessionId || activeChatId || sessionId);
}

function highlightMissionRuntimeHero() {
    window.requestAnimationFrame(() => {
        const ui = ensureMissionRuntimeHero();
        const panel = ui?.panel;
        if (!(panel instanceof HTMLElement)) return;
        panel.classList.remove('is-focused');
        void panel.offsetWidth;
        panel.classList.add('is-focused');
        try {
            panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch {
            panel.scrollIntoView();
        }
        window.setTimeout(() => {
            panel.classList.remove('is-focused');
        }, 1800);
    });
}

function openMissionControlFromChatPresence(sessionIdOverride = '') {
    const resolvedSessionId = safeString(sessionIdOverride || missionPreferredSessionId());
    if (resolvedSessionId) {
        taskContinuityLatestSessionId = resolvedSessionId;
    }
    ensureSettingsUiClosed();
    setSidebarNavMode('mission');
    highlightMissionRuntimeHero();
    void missionRefresh({ force: true, silent: true });
}

function ensureTaskContinuityRuntimeUi() {
    if (!taskContinuityPanel) return null;
    let root = taskContinuityPanel.querySelector('.task-continuity-runtime');
    if (!(root instanceof HTMLElement)) {
        root = document.createElement('div');
        root.className = 'task-continuity-runtime';
        root.innerHTML = `
            <div class="task-continuity-runtime-head">
                <span class="task-continuity-runtime-pill state-idle" data-role="pill">idle</span>
                <span class="task-continuity-runtime-label" data-role="label">No background workers active</span>
            </div>
            <div class="task-continuity-runtime-rail" data-role="bar"><span data-role="fill"></span></div>
            <div class="task-continuity-runtime-meta">
                <span data-role="agents">0 agents</span>
                <span data-role="elapsed">standby</span>
                <span data-role="heartbeat">waiting for work</span>
            </div>
            <ul class="task-continuity-runtime-list hidden" data-role="list"></ul>
        `;
        const anchor = taskContinuityBlockersWrap || taskContinuityEventsList || taskContinuityPanel.lastElementChild;
        if (anchor && anchor.parentNode === taskContinuityPanel) {
            taskContinuityPanel.insertBefore(root, anchor);
        } else {
            taskContinuityPanel.appendChild(root);
        }
    }
    return {
        root,
        pill: root.querySelector('[data-role="pill"]'),
        label: root.querySelector('[data-role="label"]'),
        bar: root.querySelector('[data-role="bar"]'),
        fill: root.querySelector('[data-role="fill"]'),
        agents: root.querySelector('[data-role="agents"]'),
        elapsed: root.querySelector('[data-role="elapsed"]'),
        heartbeat: root.querySelector('[data-role="heartbeat"]'),
        list: root.querySelector('[data-role="list"]'),
    };
}

function renderTaskContinuitySessionActivity(activity) {
    const ui = ensureTaskContinuityRuntimeUi();
    if (!ui) return;
    const allAgents = activity && Array.isArray(activity?.agents) ? activity.agents.slice(0, 3) : [];
    const hasRecentAgents = allAgents.length > 0;
    const hasActivity = Boolean(activity && activity.activeCount > 0);
    const heartbeat = hasActivity ? safeString(activity?.heartbeat) : 'idle';
    const primary = hasActivity ? activity?.primary : (hasRecentAgents ? allAgents[0] : null);
    const primaryName = hasActivity
        ? (safeString(primary?.summary) || safeString(primary?.name) || 'Background work in progress')
        : (safeString(primary?.summary) || safeString(primary?.last_progress) || 'No background workers active');
    const workerCount = hasActivity
        ? Number(activity?.workerCount || activity?.activeCount || 0)
        : allAgents.length;
    const workerLabel = hasActivity
        ? `${workerCount} active worker${workerCount === 1 ? '' : 's'}`
        : hasRecentAgents
            ? `${workerCount} background task${workerCount === 1 ? '' : 's'}`
            : '0 agents';
    const terminalStatus = delegationStatusLabel(primary?.state || primary?.status);
    const metaLabel = hasActivity
        ? `${delegationStatusLabel(primary?.state || primary?.status)} | updated ${missionRelativeTime(activity?.updatedAt)}`
        : hasRecentAgents
            ? `${terminalStatus} | updated ${missionRelativeTime(primary?.updated_at || primary?.updatedAt)}`
            : 'waiting for work';
    const pillState = hasActivity
        ? (heartbeat || 'idle')
        : (terminalStatus === 'failed' || terminalStatus === 'abandoned' ? 'stalled' : (hasRecentAgents ? 'quiet' : 'idle'));
    const pillLabel = hasActivity ? missionHeartbeatLabel(heartbeat || 'idle') : (hasRecentAgents ? terminalStatus : 'idle');
    ui.root.classList.toggle('is-active', hasActivity || hasRecentAgents);
    ui.root.dataset.state = pillState || 'idle';
    if (ui.pill instanceof HTMLElement) {
        ui.pill.className = `task-continuity-runtime-pill state-${pillState || 'idle'}`;
        ui.pill.textContent = pillLabel;
    }
    if (ui.label instanceof HTMLElement) {
        ui.label.textContent = hasActivity || hasRecentAgents ? primaryName : 'No background workers active';
    }
    if (ui.agents instanceof HTMLElement) {
        ui.agents.textContent = workerLabel;
    }
    if (ui.elapsed instanceof HTMLElement) {
        ui.elapsed.textContent = hasActivity
            ? `running ${safeString(activity?.runtimeLabel) || '--'}`
            : hasRecentAgents
                ? `last update ${missionRelativeTime(primary?.updated_at || primary?.updatedAt)}`
                : 'standby';
    }
    if (ui.heartbeat instanceof HTMLElement) {
        ui.heartbeat.textContent = metaLabel;
    }
    const hasProgress = hasActivity && typeof activity?.progressPct === 'number';
    if (ui.bar instanceof HTMLElement) {
        ui.bar.classList.toggle('is-indeterminate', hasActivity && !hasProgress);
    }
    if (ui.fill instanceof HTMLElement) {
        ui.fill.style.width = hasProgress ? `${activity.progressPct}%` : ((hasActivity || hasRecentAgents) ? '28%' : '0%');
    }
    if (ui.list instanceof HTMLElement) {
        const rows = hasActivity && Array.isArray(activity?.liveAgents)
            ? activity.liveAgents.slice(0, 3)
            : allAgents;
        ui.list.classList.toggle('hidden', rows.length === 0);
        ui.list.innerHTML = rows.map((item) => {
            const title = safeString(item?.bot_name || item?.name || item?.specialist_id || item?.bot_id) || 'worker';
            const detail = [
                delegationStatusLabel(item?.state || item?.status),
                safeString(item?.last_progress || item?.summary),
                `updated ${missionRelativeTime(item?.updated_at || item?.updatedAt)}`,
            ].filter(Boolean).join(' | ');
            return `<li><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></li>`;
        }).join('');
    }
}

