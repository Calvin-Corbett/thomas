/** Cross-surface runtime state and office palette constants. */

let currentPreferences = null;
let currentCodexStatus = null;
let pendingAvatarOverride = null;
let availableModelProfiles = [];
let setupProviderMenuShowMore = false;
let settingsSectionEntries = [];
let settingsNavBound = false;
let settingsNavTicking = false;
let sidebarSearchScope = 'chat';
let sidebarNavMode = 'chat';
let sidebarSessions = [];
// 'pending' until the FIRST /api/chats fetch answers, then 'loaded' (success)
// or 'error' (failure, and never loaded since). renderSidebarChatList consults
// this before claiming "No chats yet.": an empty sidebarSessions array means
// "no data yet" until the fetch has actually confirmed emptiness. Measured
// 2026-08-05: the sidebar asserted "No chats yet." over hundreds of existing
// chats because mode/scope switches render before the history fetch resolves.
let sidebarHistoryLoadState = 'pending';
let chatPersistInFlight = false;
let chatPersistQueued = false;
let activeAgentName = 'Thomas';
let taskContinuityAutoRefreshTimer = 0;
let taskContinuityInFlight = false;
let taskContinuityLatestState = null;
let taskContinuityLatestEvents = [];
let taskContinuityLatestSessionId = '';
let taskContinuityLatestActivity = null;
let taskContinuityLatestError = '';
let taskContinuityLatestTaskDefinition = null;
let taskContinuityLatestTaskEvaluation = null;
let taskContinuityLatestTaskDefinitionStatus = 'idle';
let taskContinuityCollapseOverride = null;
let taskContinuityMissionPayload = null;
let taskContinuityMissionJobs = null;
let taskContinuityActivityFallbackLastFetchAt = 0;
let evolveChatRepliesInFlight = false;
let evolveChatRepliesLastRefreshAt = 0;
let debugEvents = [];
let debugConsoleEntries = [];
let debugNetworkEntries = [];
let activeDebugTab = 'runtime';
let debugConsoleCaptureEnabled = false;
let debugNetworkCaptureEnabled = false;
let debugLiveLoading = false;
let debugOnboardingRepairInFlight = false;
let runtimeGuardMonitorTimer = 0;
let runtimeGuardLastAlertSignature = '';
let runtimeGuardLastAlertAt = 0;
let runtimeGuardLastState = '';
const debugLiveCache = {
    loadedAt: 0,
    system: null,
    models: null,
    tools: null,
    memory: null,
    runs: null,
    errors: [],
};
let robotAlertQueue = [];
let robotAlertShowing = false;
let robotAlertLastMessage = '';
let robotAlertLastAt = 0;
let officeState = null;
let officeDraftMapState = null;
let officeChatPreviewUntil = 0;
let officeChatPreviewTimer = 0;
let officeChatPreviewSessionId = '';
let chatTaskRuntimeTimer = 0;
const chatTaskStripStateByMessageId = new Map();
const chatTaskMessageBySessionId = new Map();
const chatAgentPresenceStateByActivityId = new Map();
let chatRobotWorldRaf = 0;
let chatRobotWorldLastFrameAt = 0;
let chatPrimaryPresenceState = null;
let chatRobotWorldLatestSnapshot = null;
let chatRobotWorldDebugSamples = [];
let chatHelperSpawnOrdinal = 0;
let chatRobotWorldDebugScenario = null;
let chatPhysicsWorldState = null;
let missionState = null;
let contentState = null;
const spendState = { payload: null, lastFetchedAt: 0 };
const goalsState = { payload: null, lastFetchedAt: 0 };
let moduleState = null;
let officeSpriteAtlasCache = null;
let settingsReturnNavMode = 'chat';
let chatListExpanded = true;
let officeReducedMotionListenerBound = false;
let officeLastHapticAt = 0;
let sidebarAnimationTimer = 0;
let debugDockAnimationTimer = 0;
let lastSidebarResponsiveViewport = '';

const SIDEBAR_ANIMATION_LOCK_MS = 280;
const DEBUG_DOCK_ANIMATION_LOCK_MS = 300;
const TASK_CONTINUITY_REFRESH_INTERVAL_MS = 2800;
const TASK_CONTINUITY_IDLE_ACTIVITY_REFRESH_INTERVAL_MS = 60000;
const EVOLVE_CHAT_REPLY_IDLE_REFRESH_INTERVAL_MS = 30000;
const TASK_CONTINUITY_HEARTBEAT_STALE_MS = 18000;
const OFFICE_CHAT_PREVIEW_GRACE_MS = 9000;
const TASK_CONTINUITY_HEARTBEAT_DEAD_MS = 45000;
const CHAT_TASK_STRIP_CHECKPOINT_LIMIT = 5;
const CHAT_AGENT_PRESENCE_EXIT_MS = 760;
const CHAT_PRIMARY_ROBOT_LINGER_MS = 10_000;
const CHAT_PRIMARY_ROBOT_MIN_ACTION_MS = 2_600;
const CHAT_PRIMARY_ROBOT_MAX_ACTION_MS = 5_600;
const CHAT_PRIMARY_ROBOT_WORLD_HEIGHT = 108;
const CHAT_PRIMARY_ROBOT_WORLD_PADDING_X = 18;
const CHAT_PRIMARY_ROBOT_GROUND_OFFSET = 26;
const CHAT_PRIMARY_ROBOT_PERCH_LIFT = 36;
const CHAT_PRIMARY_ROBOT_GRAVITY = 0.62;
const CHAT_PRIMARY_ROBOT_FALL_SPEED_MAX = 11.5;
const CHAT_PRIMARY_ROBOT_WALK_SPEED = 1.7;
const CHAT_PRIMARY_ROBOT_JUMP_SPEED = -7.6;
const CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT = 56;
const CHAT_PRIMARY_ROBOT_FOOT_OFFSET = 42;
const CHAT_PRIMARY_ROBOT_DEBUG_KEY = '__THOMAS_CHAT_WORLD_DEBUG__';
const CHAT_PRIMARY_ROBOT_DEBUG_SAMPLE_LIMIT = 240;
const CHAT_PRIMARY_ROBOT_TASK_FOCUS_DELAY_MS = 1800;
const CHAT_PRIMARY_ROBOT_TASK_FOCUS_RETURN_DELAY_MS = 1200;
const CHAT_AGENT_PRESENCE_PORTAL_OUT_MS = 720;
const CHAT_AGENT_DEBUG_HELPER_ID = 'debug-helper';
const ANIMATION_FIDELITY_HIGH = 'high';
const ANIMATION_FIDELITY_BALANCED = 'balanced';
const ANIMATION_FIDELITY_MINIMAL = 'minimal';
const ANIMATION_FIDELITY_VALUES = new Set([
    ANIMATION_FIDELITY_HIGH,
    ANIMATION_FIDELITY_BALANCED,
    ANIMATION_FIDELITY_MINIMAL,
]);
const CHAT_WORLD_MODE_AMBIENT = 'ambient';
const CHAT_WORLD_MODE_PHYSICS = 'physics';
const EASY_SETUP_TOTAL_STEPS = 5;
const CHAT_AGENT_PRESENCE_FLOAT_PAD_X = 26;
const CHAT_AGENT_PRESENCE_FLOAT_PAD_TOP = 92;
const CHAT_AGENT_PRESENCE_FLOAT_PAD_BOTTOM = 168;
const EVOLVE_TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'dead']);
const DEBUG_EVENT_LIMIT = 80;
const DEBUG_CONSOLE_LIMIT = 120;
const DEBUG_NETWORK_LIMIT = 120;
const DEBUG_LIVE_CACHE_TTL_MS = 20_000;
const RUNTIME_GUARD_POLL_INTERVAL_MS = 45_000;
const RUNTIME_GUARD_ALERT_DEDUPE_MS = 180_000;
const DEBUG_TAB_SEQUENCE = ['runtime', 'system', 'models', 'tools', 'memory', 'runs', 'events', 'console', 'network'];
const UI_NAV_MODE_STORAGE_KEY = 'thomas.ui.nav_mode.v1';
const UI_WORKSPACE_NAV_ORDER_STORAGE_KEY = 'thomas.ui.workspace_nav_order.v1';
const UI_SIDEBAR_COLLAPSED_STORAGE_KEY = 'thomas.ui.sidebar_collapsed.v1';
const UI_MARKETPLACE_STORE_URL_STORAGE_KEY = 'thomas.ui.marketplace_store_url.v1';
const DEFAULT_MARKETPLACE_STORE_URL = 'https://thomas-site.thomasdevhub.workers.dev';
const LEGACY_MARKETPLACE_STORE_URL = 'https://thomas.dev';
const UI_CHAT_LIST_EXPANDED_STORAGE_KEY = 'thomas.ui.chat_list_expanded.v1';
const UI_ACTIVE_CHAT_STORAGE_KEY = 'thomas.ui.active_chat.v1';
const UI_COMPACT_LAYOUT_MEDIA_QUERY = '(max-width: 760px)';
const OFFICE_CAMERA_STORAGE_KEY = 'thomas.ui.office.camera.v1';
const OFFICE_LAYOUT_STORAGE_KEY = 'thomas.ui.office.layout.v1';
const OFFICE_AGENT_PREFS_STORAGE_KEY = 'thomas.ui.office.agent_prefs.v1';
const OFFICE_RUNTIME_STORAGE_KEY = 'thomas.ui.office.runtime.v1';
const OFFICE_RUNTIME_SCHEMA_VERSION = 2;
const DEFAULT_AGENT_NAME = 'Thomas';
const MODULE_REFRESH_INTERVAL_MS = 15_000;
const MODULE_CHANNELS_REFRESH_TTL_MS = 12_000;
const UI_CHANNELS_CATALOG_ORDER_STORAGE_KEY = 'thomas.channels.catalog.order.v1';
let moduleChannelsDraggedCardId = '';
const MODULE_MARKETPLACE_REFRESH_TTL_MS = 75_000;
const OFFICE_MAX_TASKS = 24;
const OFFICE_MAX_CHAT_LINES = 48;
const OFFICE_EVENT_SCHEMA_VERSION = 1;
const OFFICE_EVENT_LOG_LIMIT = 120;
const OFFICE_DEBUG_REFRESH_MS = 180;
const OFFICE_RUNTIME_PERSIST_INTERVAL_MS = 1200;
const OFFICE_BACKGROUND_TICK_MS = 1000;
const OFFICE_STREAM_RETRY_MIN_MS = 1100;
const OFFICE_STREAM_RETRY_MAX_MS = 12_000;
const OFFICE_ZOOM_MIN = 0.22;
const OFFICE_ZOOM_RENDER_FLOOR = 0.22;
const OFFICE_ZOOM_MAX = 2.6;
const OFFICE_ZOOM_STEP = 0.07;
const OFFICE_WHEEL_ZOOM_SENSITIVITY = 0.00044;
const OFFICE_AGENT_AVOID_RADIUS = 9.4;
const OFFICE_AGENT_COLLISION_DISTANCE = 1.85;
const OFFICE_CROWD_RELIEF_RADIUS = 9.2;
const OFFICE_CROWD_RELIEF_NEIGHBORS = 3;
const OFFICE_CROWD_RELIEF_COOLDOWN_MS = 900;
const OFFICE_MAP_WIDTH = 4200;
const OFFICE_MAP_HEIGHT = 2700;
const OFFICE_DRAFT_MAP_SIZE = 8400;
const OFFICE_DRAFT_MAP_MIN_ZOOM = 0.12;
const OFFICE_DRAFT_MAP_MAX_ZOOM = 2.2;
const OFFICE_DRAFT_MAP_DEFAULT_ZOOM = 0.72;
const OFFICE_DRAFT_MAP_MINOR_GRID = 32;
const OFFICE_DRAFT_MAP_MAJOR_GRID = 160;
const OFFICE_DRAFT_MINIMAP_SIZE = 220;
const OFFICE_DRAFT_LAYOUT_STORAGE_KEY = 'thomas.office.draft.layout.v1';
const OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY = 'thomas.office.draft.autosave.v1';
const OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION = 19;
const OFFICE_DRAFT_UNDO_LIMIT = 48;
const OFFICE_DRAFT_ASSET_SCALE_MIN = 0.6;
const OFFICE_DRAFT_ASSET_SCALE_MAX = 1.25;
const OFFICE_DRAFT_ASSET_SCALE_OPTIONS = Object.freeze([0.6, 0.75, 0.9, 1, 1.15, 1.25]);
const OFFICE_DRAFT_ASSET_RENDER_SCALE = 0.74;
const OFFICE_DRAFT_ROOM_FLOOR_PALETTES = Object.freeze({
    tan: {
        label: 'Tan',
        shell: 'linear-gradient(180deg, rgba(188, 160, 127, 0.98), rgba(148, 117, 88, 0.98))',
        floor: 'linear-gradient(180deg, rgba(222, 196, 164, 0.96), rgba(180, 146, 111, 0.96))',
        floorBorder: 'rgba(247, 228, 205, 0.18)',
        pattern: 'linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(rgba(90,65,42,0.12) 1px, transparent 1px)',
        patternSize: '96px 96px',
    },
    sand: {
        label: 'Sand',
        shell: 'linear-gradient(180deg, rgba(202, 183, 148, 0.98), rgba(164, 141, 104, 0.98))',
        floor: 'linear-gradient(180deg, rgba(232, 216, 188, 0.96), rgba(195, 170, 132, 0.96))',
        floorBorder: 'rgba(255, 241, 216, 0.18)',
        pattern: 'repeating-linear-gradient(45deg, rgba(255,255,255,0.08) 0 8px, transparent 8px 48px)',
        patternSize: '160px 160px',
    },
    clay: {
        label: 'Clay',
        shell: 'linear-gradient(180deg, rgba(177, 139, 112, 0.98), rgba(135, 97, 72, 0.98))',
        floor: 'linear-gradient(180deg, rgba(216, 181, 154, 0.95), rgba(176, 134, 105, 0.95))',
        floorBorder: 'rgba(255, 226, 200, 0.16)',
        pattern: 'radial-gradient(circle at 24px 24px, rgba(92,54,33,0.16) 0 5px, transparent 6px)',
        patternSize: '92px 92px',
    },
    slate: {
        label: 'Slate',
        shell: 'linear-gradient(180deg, rgba(110, 124, 148, 0.98), rgba(76, 90, 112, 0.98))',
        floor: 'linear-gradient(180deg, rgba(161, 174, 196, 0.96), rgba(121, 136, 159, 0.96))',
        floorBorder: 'rgba(228, 237, 252, 0.15)',
        pattern: 'linear-gradient(90deg, rgba(255,255,255,0.10) 1px, transparent 1px), linear-gradient(rgba(18,29,48,0.16) 1px, transparent 1px)',
        patternSize: '120px 120px',
    },
    carpet: {
        label: 'Carpet',
        shell: 'linear-gradient(180deg, rgba(128, 99, 139, 0.98), rgba(80, 67, 106, 0.98))',
        floor: 'linear-gradient(180deg, rgba(166, 136, 179, 0.96), rgba(118, 97, 147, 0.96))',
        floorBorder: 'rgba(236, 218, 255, 0.18)',
        pattern: 'repeating-linear-gradient(90deg, rgba(255,255,255,0.07) 0 3px, transparent 3px 18px)',
        patternSize: '84px 84px',
    },
    terrazzo: {
        label: 'Terrazzo',
        shell: 'linear-gradient(180deg, rgba(172, 184, 180, 0.98), rgba(115, 135, 132, 0.98))',
        floor: 'linear-gradient(180deg, rgba(220, 231, 226, 0.96), rgba(174, 193, 190, 0.96))',
        floorBorder: 'rgba(238, 255, 250, 0.18)',
        pattern: 'radial-gradient(circle at 18px 22px, rgba(57,92,96,0.18) 0 4px, transparent 5px), radial-gradient(circle at 64px 50px, rgba(139,93,78,0.16) 0 3px, transparent 4px)',
        patternSize: '110px 110px',
    },
});

