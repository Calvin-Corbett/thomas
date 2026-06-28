/**
 * Thomas UI - Super Cool & Neat Edition
 * Minimal, clean, vanilla JS to power the thoughtful interface.
 */

//
//   SHARED UTILITY FUNCTIONS (hoisted here for cross-file availability)
//

function safeString(value) {
    return String(value || '').trim();
}

function escapeHtml(unsafe) {
    return String(unsafe || '')
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function streamChunkString(value) {
    return value === undefined || value === null ? '' : String(value);
}

//
//   PROVIDER DISPLAY NAMES (single source of truth for user-facing labels)
//   The internal key/profile-name (e.g. "openai_codex", "codex") must NEVER be
//   shown to the user. Always render through formatProviderDisplay() at every
//   user-facing point: composer readout, top-nav button, thread labels, the
//   model-setup provider picker, etc. Internal values stay untouched.
//
const PROVIDER_DISPLAY_NAMES = {
    openai_codex: 'OpenAI (ChatGPT)',
    'openai-codex': 'OpenAI (ChatGPT)',
    codex: 'OpenAI',
    openai: 'OpenAI',
    chatgpt: 'OpenAI (ChatGPT)',
    anthropic: 'Anthropic',
    claude: 'Anthropic',
    gemini: 'Google (Gemini)',
    google: 'Google (Gemini)',
    mistral: 'Mistral',
    groq: 'Groq',
    together: 'Together',
    openrouter: 'OpenRouter',
    deepinfra: 'DeepInfra',
    fireworks: 'Fireworks',
    perplexity: 'Perplexity',
    xai: 'xAI (Grok)',
    x_ai: 'xAI (Grok)',
    grok: 'xAI (Grok)',
    glm: 'GLM',
    cerebras: 'Cerebras',
    litellm: 'LiteLLM',
    local: 'Local',
    ollama: 'Local',
};

/**
 * Map a provider key OR profile name to a user-facing display name.
 * Resolves the profile's real `.provider` from availableModelProfiles when the
 * supplied token is a profile name. `openai_codex` shows as "OpenAI (ChatGPT)"
 * in the compact form; pass { compact: false } to collapse it to plain "OpenAI"
 * (used for the chat-history thread subtitle, where space is tight).
 */
function formatProviderDisplay(nameOrProvider, { compact = true } = {}) {
    const raw = safeString(nameOrProvider);
    if (!raw) return '';
    const key = raw.toLowerCase();

    // Resolve a matching profile so a profile-name token uses its real provider.
    let providerKey = key;
    if (Array.isArray(availableModelProfiles)) {
        const profile = availableModelProfiles.find(
            (entry) => safeString(entry?.name).toLowerCase() === key,
        );
        if (profile && safeString(profile.provider)) {
            providerKey = safeString(profile.provider).toLowerCase();
        }
    }

    const direct = PROVIDER_DISPLAY_NAMES[providerKey] || PROVIDER_DISPLAY_NAMES[key];
    if (direct) {
        if (!compact && (direct === 'OpenAI (ChatGPT)')) return 'OpenAI';
        return direct;
    }

    // Unknown provider: title-case the token, never echo a raw "codex" string.
    return raw
        .replace(/[_-]+/g, ' ')
        .replace(/\b[a-z]/g, (match) => match.toUpperCase());
}

//
//   GLOBAL STATE & CONSTANTS
//   Chat state, game constants, composer presets, DOM element refs
//

// Basic State
let chatHistory = [];
let isGenerating = false;
let currentAbortController = null;
let pendingDocs = [];
let pendingImages = [];
let pendingSendQueue = [];
let queuedSendDrainActive = false;
let sessionId = "";
let activeChatId = "";
let composerInputLockUntil = 0;
let composerActionsOpen = false;
let composerModeSelection = null;
let bootPluginInstallPromise = null;
let bootPluginInstallHandled = false;

const CHAT_GAME_HIGHSCORE_STORAGE_KEYS = {
    cloud_jump: 'thomas.chat_game.cloud_jump.high_score.v1',
    jetpack_joyride: 'thomas.chat_game.jetpack_joyride.high_score.v1',
    dino_run: 'thomas.chat_game.dino_run.high_score.v1',
};
const CHAT_GAME_BOT_WRAP_SIZE = 34;
const CHAT_GAME_DOOR_BOT_MOUNT_LEFT = 8;
const CHAT_GAME_DOOR_BOT_MOUNT_BOTTOM = 8;
const CHAT_GAME_DOOR_BOT_ENTER_OFFSET_START = -8;
const CHAT_GAME_DOOR_BOT_ENTER_OFFSET_END = 12;
const CHAT_GAME_LAUNCH_PLATFORM_FALL_SPEED = 3.1;
const CHAT_GAME_START_X_RATIO = 0.5;
const CHAT_GAME_PLATFORM_MIN_WIDTH = 98;
const CHAT_GAME_PLATFORM_MAX_WIDTH = 154;
const CHAT_GAME_PLATFORM_GAP_MIN = 40;
const CHAT_GAME_PLATFORM_GAP_MAX = 58;
const CHAT_GAME_PLATFORM_PATH_STEP = 46;
const CHAT_GAME_PLATFORM_DRIFT_MAX = 0.11;
const CHAT_GAME_PLATFORM_DRIFT_CHANCE = 0.24;
const CHAT_GAME_PLATFORM_CENTER_RATIO = 0.5;
const CHAT_GAME_PLATFORM_CENTER_FOLLOW = 0.13;
const CHAT_GAME_PLATFORM_CENTER_CORRECTION = 0.26;
const CHAT_GAME_PLATFORM_SAFE_MARGIN = 14;
const CHAT_GAME_PLATFORM_RUNWAY_COUNT = 10;
const CHAT_GAME_PLATFORM_LAUNCH_RESPAWN_SECONDS = 6.2;
const JETPACK_GAME_ID = 'jetpack_joyride';
const DINO_GAME_ID = 'dino_run';
const JETPACK_INTRO_DURATION_SECONDS = 2.6;
const JETPACK_FLIGHT_START_X = -170;
const JETPACK_FLIGHT_START_Y = -122;
const JETPACK_PLAYER_X_RATIO = 0.22;
const JETPACK_PLAYER_Y_RATIO = 0.52;
const JETPACK_MOVE_SPEED = 5.7;
const JETPACK_PLAYER_TOP_PADDING = 8;
const JETPACK_PLAYER_BOTTOM_PADDING = 24;
const JETPACK_SCROLL_BASE = 4.1;
const JETPACK_SCROLL_MAX_BONUS = 3.1;
const JETPACK_SPAWN_FRAMES_MIN = 48;
const JETPACK_SPAWN_FRAMES_MAX = 86;
const JETPACK_ZAPPER_LENGTH_MIN = 112;
const JETPACK_ZAPPER_LENGTH_MAX = 182;
const JETPACK_ZAPPER_THICKNESS = 12;
const JETPACK_MISSILE_WIDTH = 52;
const JETPACK_MISSILE_HEIGHT = 18;
const JETPACK_LASER_WIDTH = 26;
const JETPACK_LASER_HEIGHT_MIN = 128;
const JETPACK_LASER_HEIGHT_MAX = 210;
const JETPACK_HITBOX_PADDING = 4;
const DINO_INTRO_DURATION_SECONDS = 2.1;
const DINO_GROUND_PADDING = 34;
const DINO_PLAYER_X_RATIO = 0.2;
const DINO_PLAYER_NORMAL_HEIGHT = 34;
const DINO_PLAYER_DUCK_HEIGHT = 24;
const DINO_PLAYER_WIDTH = 30;
const DINO_GRAVITY = 0.48;
const DINO_JUMP_VELOCITY = -10.4;
const DINO_SCROLL_BASE = 4.2;
const DINO_SCROLL_MAX_BONUS = 3.9;
const DINO_SPAWN_FRAMES_MIN = 52;
const DINO_SPAWN_FRAMES_MAX = 96;
const COMPOSER_MODE_PRESETS = {
    research: {
        id: 'research',
        label: 'Research',
        promptPrefix: 'Mode: Deep research. Provide a concise but thorough answer with prioritized findings and concrete next steps.',
    },
    evolve: {
        id: 'evolve',
        label: 'Evolve',
        promptPrefix: '',
    },
    create_image: {
        id: 'create_image',
        label: 'Create image',
        promptPrefix: 'Mode: Create image. Respond with a polished concept plus a final production-ready image prompt.',
    },
    create_video: {
        id: 'create_video',
        label: 'Create video',
        promptPrefix: 'Mode: Create video. Respond with concept, shot plan, and a final video generation prompt.',
    },
    create_song: {
        id: 'create_song',
        label: 'Create song',
        promptPrefix: 'Mode: Create song. Respond with mood, structure, lyrics, and a polished generation prompt.',
    },
    add_files: {
        id: 'add_files',
        label: 'Add files',
        promptPrefix: '',
    },
    games: {
        id: 'games',
        label: 'Games',
        promptPrefix: '',
    },
    cloud_jump: {
        id: 'cloud_jump',
        label: 'Cloud Jump',
        promptPrefix: '',
        kind: 'game',
    },
    jetpack_joyride: {
        id: 'jetpack_joyride',
        label: 'Jetpack Joyride',
        promptPrefix: '',
        kind: 'game',
    },
    dino_run: {
        id: 'dino_run',
        label: 'Dino Run',
        promptPrefix: '',
        kind: 'game',
    },
};

const chatGameRuntime = {
    activeGameId: '',
    rafId: 0,
    lastFrameMs: 0,
    input: {
        left: false,
        right: false,
        up: false,
        down: false,
        thrust: false,
    },
    cloudJump: null,
    jetpackJoyride: null,
    dinoRun: null,
};

// DOM Elements
const welcomeScreen = document.getElementById('welcomeScreen');
const chatScrollArea = document.getElementById('chatScrollArea');
const chatMessagesInner = document.getElementById('chatMessagesInner');
const composerTextarea = document.getElementById('composerTextarea');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const attachBtn = document.getElementById('attachBtn');
const attachmentsPreview = document.getElementById('attachmentsPreview');
const docFileInput = document.getElementById('docFileInput');
const composerActionPopover = document.getElementById('composerActionPopover');
const composerActionList = document.getElementById('composerActionList');
const composerGamesColumn = document.getElementById('composerGamesColumn');
const composerModeChip = document.getElementById('composerModeChip');
const composerModeChipLabel = document.getElementById('composerModeChipLabel');
const composerModeChipCloseBtn = document.getElementById('composerModeChipCloseBtn');
const composerBox = document.querySelector('.composer-box');
const composerStatusBar = document.getElementById('composerStatusBar');
const toastContainer = document.getElementById('toastContainer');
const composerDisclaimer = document.getElementById('composerDisclaimer');
const chatGamePanel = document.getElementById('chatGamePanel');
const chatGameLane = document.getElementById('chatGameLane');
const chatGameCanvas = document.getElementById('chatGameCanvas');
const chatGameDoor = document.getElementById('chatGameDoor');
const chatGameBotWrap = document.getElementById('chatGameBotWrap');
const chatGameBot = document.getElementById('chatGameBot');
const chatGameBotName = document.getElementById('chatGameBotName');
const chatGameControls = document.getElementById('chatGameControls');
const chatGameCloseBtn = document.getElementById('chatGameCloseBtn');
const chatGameRestartBtn = document.getElementById('chatGameRestartBtn');
const chatGameScore = document.getElementById('chatGameScore');
const chatGameHighScore = document.getElementById('chatGameHighScore');
const chatGameStatusText = document.getElementById('chatGameStatusText');
const composerDinoShell = document.getElementById('composerDinoShell');
const composerDinoCanvas = document.getElementById('composerDinoCanvas');
const composerDinoHud = document.getElementById('composerDinoHud');
const composerDinoScore = document.getElementById('composerDinoScore');
const composerDinoHighScore = document.getElementById('composerDinoHighScore');
const composerDinoStatusText = document.getElementById('composerDinoStatusText');
const chatGamePortal = document.getElementById('chatGamePortal');
const assistantSuggestionRail = document.getElementById('assistantSuggestionRail');
const assistantSuggestionTitle = document.getElementById('assistantSuggestionTitle');
const assistantSuggestionBubbles = document.getElementById('assistantSuggestionBubbles');
const assistantSuggestionDismissBtn = document.getElementById('assistantSuggestionDismissBtn');

// New Phase 5 Elements
const appRoot = document.getElementById('app');
const sidebar = document.getElementById('sidebar');
const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
const sidebarCollapseBtn = document.getElementById('sidebarCollapseBtn');
const modelSelector = document.getElementById('modelSelector');
const newChatSidebar = document.getElementById('newChatSidebar');
const navChatBtn = document.getElementById('navChatBtn');
const navOfficeBtn = document.getElementById('navOfficeBtn');
const navMissionBtn = document.getElementById('navMissionBtn');
const navEvolutionBtn = document.getElementById('navEvolutionBtn');
const navUiEditorBtn = document.getElementById('navUiEditorBtn');
const navMyStuffBtn = document.getElementById('navMyStuffBtn');
const navChannelsBtn = document.getElementById('navChannelsBtn');
const navMarketplaceBtn = document.getElementById('navMarketplaceBtn');
const navTokenEconomyBtn = document.getElementById('navTokenEconomyBtn');
const navContentBtn = document.getElementById('navContentBtn');
const navInfiniteBtn = document.getElementById('navInfiniteBtn');
const topNav = document.querySelector('.top-nav');
const mainContent = document.querySelector('.main-content');
const composerContainer = document.querySelector('.composer-container');
const officeWorkspace = document.getElementById('officeWorkspace');
const officeSceneWrap = document.querySelector('.office-scene-wrap');
const officeScenePanzoom = document.getElementById('officeScenePanzoom');
const officeScene = document.getElementById('officeScene');
const officeEditorModal = document.getElementById('officeEditorModal');
const officeEditorToggleBtn = document.getElementById('officeEditorToggleBtn');
const officeEditorDockBtn = document.getElementById('officeEditorDockBtn');
const officeEditorCloseBtn = document.getElementById('officeEditorCloseBtn');
const officeTaskList = document.getElementById('officeTaskList');
const officeAgentSelect = document.getElementById('officeAgentSelect');
const officeAgentNameInput = document.getElementById('officeAgentNameInput');
const officeAgentColorInput = document.getElementById('officeAgentColorInput');
const officeAgentCostumeSelect = document.getElementById('officeAgentCostumeSelect');
const officeActionSummonBtn = document.getElementById('officeActionSummonBtn');
const officeActionBreakBtn = document.getElementById('officeActionBreakBtn');
const officeActionResumeBtn = document.getElementById('officeActionResumeBtn');
const officeZoomOutBtn = document.getElementById('officeZoomOutBtn');
const officeZoomInBtn = document.getElementById('officeZoomInBtn');
const officeZoomResetBtn = document.getElementById('officeZoomResetBtn');
const officeDebugToggleBtn = document.getElementById('officeDebugToggleBtn');
const officeMinimap = document.getElementById('officeMinimap');
const officeMinimapCanvas = document.getElementById('officeMinimapCanvas');
const officeFollowToggleBtn = document.getElementById('officeFollowToggleBtn');
const officeDebugOverlay = document.getElementById('officeDebugOverlay');
const officeChatLog = document.getElementById('officeChatLog');
const officeChatInput = document.getElementById('officeChatInput');
const officeChatSendBtn = document.getElementById('officeChatSendBtn');
const missionWorkspace = document.getElementById('missionWorkspace');
const evolutionWorkspace = document.getElementById('evolutionWorkspace');
const contentWorkspace = document.getElementById('contentWorkspace');
const missionConnectionPill = document.getElementById('missionConnectionPill');
const missionUpdatedAt = document.getElementById('missionUpdatedAt');
const missionOpsNowTitle = document.getElementById('missionOpsNowTitle');
const missionOpsNowMeta = document.getElementById('missionOpsNowMeta');
const missionOpsNextTitle = document.getElementById('missionOpsNextTitle');
const missionOpsNextMeta = document.getElementById('missionOpsNextMeta');
const missionOpsBlockersTitle = document.getElementById('missionOpsBlockersTitle');
const missionOpsBlockersMeta = document.getElementById('missionOpsBlockersMeta');
const missionKpiActiveAgents = document.getElementById('missionKpiActiveAgents');
const missionKpiActiveMeta = document.getElementById('missionKpiActiveMeta');
const missionKpiApprovals = document.getElementById('missionKpiApprovals');
const missionKpiApprovalsMeta = document.getElementById('missionKpiApprovalsMeta');
const missionKpiRisks = document.getElementById('missionKpiRisks');
const missionKpiRisksMeta = document.getElementById('missionKpiRisksMeta');
const missionKpiEngine = document.getElementById('missionKpiEngine');
const missionKpiEngineMeta = document.getElementById('missionKpiEngineMeta');
const missionPriorityMeta = document.getElementById('missionPriorityMeta');
const missionPriorityList = document.getElementById('missionPriorityList');
const missionJobsMeta = document.getElementById('missionJobsMeta');
const missionJobsList = document.getElementById('missionJobsList');
const missionJobsTaskCount = document.getElementById('missionJobsTaskCount');
const missionJobsCronCount = document.getElementById('missionJobsCronCount');
const missionCreateMeta = document.getElementById('missionCreateMeta');
const missionJobForm = document.getElementById('missionJobForm');
const missionJobTemplates = document.getElementById('missionJobTemplates');
const missionJobNameInput = document.getElementById('missionJobNameInput');
const missionJobPromptInput = document.getElementById('missionJobPromptInput');
const missionJobModeSelect = document.getElementById('missionJobModeSelect');
const missionJobWorkflowInput = document.getElementById('missionJobWorkflowInput');
const missionJobOnceAtRow = document.getElementById('missionJobOnceAtRow');
const missionJobOnceAtInput = document.getElementById('missionJobOnceAtInput');
const missionJobEverySecondsRow = document.getElementById('missionJobEverySecondsRow');
const missionJobEverySecondsInput = document.getElementById('missionJobEverySecondsInput');
const missionJobAtRow = document.getElementById('missionJobAtRow');
const missionJobAtInput = document.getElementById('missionJobAtInput');
const missionJobWeekdayRow = document.getElementById('missionJobWeekdayRow');
const missionJobWeekdays = document.getElementById('missionJobWeekdays');
const missionJobTimezoneRow = document.getElementById('missionJobTimezoneRow');
const missionJobTimezoneInput = document.getElementById('missionJobTimezoneInput');
const missionJobProfileInput = document.getElementById('missionJobProfileInput');
const missionJobModelInput = document.getElementById('missionJobModelInput');
const missionJobApprovalToggle = document.getElementById('missionJobApprovalToggle');
const missionJobSubmitBtn = document.getElementById('missionJobSubmitBtn');
const missionApprovalsMeta = document.getElementById('missionApprovalsMeta');
const missionApprovalsList = document.getElementById('missionApprovalsList');
const missionRoomsList = document.getElementById('missionRoomsList');
const missionTimelineMeta = document.getElementById('missionTimelineMeta');
const missionTimelineList = document.getElementById('missionTimelineList');
const contentRefreshBtn = document.getElementById('contentRefreshBtn');
const contentConnectedCount = document.getElementById('contentConnectedCount');
const contentConnectedMeta = document.getElementById('contentConnectedMeta');
const contentAudienceCount = document.getElementById('contentAudienceCount');
const contentAudienceMeta = document.getElementById('contentAudienceMeta');
const contentQueuedCount = document.getElementById('contentQueuedCount');
const contentQueuedMeta = document.getElementById('contentQueuedMeta');
const contentWorkflowCount = document.getElementById('contentWorkflowCount');
const contentWorkflowMetaSummary = document.getElementById('contentWorkflowMetaSummary');
const contentPlatformMeta = document.getElementById('contentPlatformMeta');
const contentPlatformGrid = document.getElementById('contentPlatformGrid');
const contentWorkflowMeta = document.getElementById('contentWorkflowMeta');
const contentWorkflowGrid = document.getElementById('contentWorkflowGrid');
const contentSchedulerMeta = document.getElementById('contentSchedulerMeta');
const contentSchedulerRows = document.getElementById('contentSchedulerRows');
const contentToolsMeta = document.getElementById('contentToolsMeta');
const contentToolsGrid = document.getElementById('contentToolsGrid');
const contentControlMeta = document.getElementById('contentControlMeta');
const contentControlGrid = document.getElementById('contentControlGrid');
const contentNavMeta = document.getElementById('contentNavMeta');
const contentNavList = document.getElementById('contentNavList');
const contentAxisMeta = document.getElementById('contentAxisMeta');
const contentAxisList = document.getElementById('contentAxisList');
const contentChecklistMeta = document.getElementById('contentChecklistMeta');
const contentChecklistGrid = document.getElementById('contentChecklistGrid');
const moduleWorkspace = document.getElementById('moduleWorkspace');
const moduleWorkspaceTitle = document.getElementById('moduleWorkspaceTitle');
const moduleWorkspaceSubtitle = document.getElementById('moduleWorkspaceSubtitle');
const moduleWorkspaceModePill = document.getElementById('moduleWorkspaceModePill');
const moduleWorkspaceMeta = document.getElementById('moduleWorkspaceMeta');
const moduleKpiGrid = document.getElementById('moduleKpiGrid');
const moduleSubnavRow = document.getElementById('moduleSubnavRow');
const moduleSubnavList = document.getElementById('moduleSubnavList');
const moduleFlairRow = document.getElementById('moduleFlairRow');
const moduleFocusStrip = document.getElementById('moduleFocusStrip');
const moduleSpecialGrid = document.getElementById('moduleSpecialGrid');
const moduleWorkbench = document.getElementById('moduleWorkbench');
const moduleQueuePanel = document.getElementById('moduleQueuePanel');
const moduleQueueTitle = document.getElementById('moduleQueueTitle');
const moduleQueueMeta = document.getElementById('moduleQueueMeta');
const moduleQueueList = document.getElementById('moduleQueueList');
const moduleHealthPanel = document.getElementById('moduleHealthPanel');
const moduleHealthTitle = document.getElementById('moduleHealthTitle');
const moduleHealthMeta = document.getElementById('moduleHealthMeta');
const moduleHealthList = document.getElementById('moduleHealthList');
const moduleActionsPanel = document.getElementById('moduleActionsPanel');
const moduleActionsTitle = document.getElementById('moduleActionsTitle');
const moduleActionsMeta = document.getElementById('moduleActionsMeta');
const moduleActionsGrid = document.getElementById('moduleActionsGrid');
const moduleActivityPanel = document.getElementById('moduleActivityPanel');
const moduleActivityTitle = document.getElementById('moduleActivityTitle');
const moduleActivityMeta = document.getElementById('moduleActivityMeta');
const moduleActivityList = document.getElementById('moduleActivityList');
const moduleTriagePanel = document.getElementById('moduleTriagePanel');
const moduleTriageTitle = document.getElementById('moduleTriageTitle');
const moduleTriageMeta = document.getElementById('moduleTriageMeta');
const moduleTriageFilters = document.getElementById('moduleTriageFilters');
const moduleTriageMessages = document.getElementById('moduleTriageMessages');
const workspaceNavItems = document.getElementById('workspaceNavItems');
const pluginNavItems = document.getElementById('pluginNavItems');
const sidebarModeButtons = Array.from(document.querySelectorAll('.sidebar-nav [data-nav-mode]'));

const settingsModal = document.getElementById('settingsModal');
const settingsBtn = document.getElementById('settingsBtn');
const closeSettingsBtn = document.getElementById('closeSettingsBtn');
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
const settingTheme = document.getElementById('settingTheme');
const settingAutonomy = document.getElementById('settingAutonomy');
const settingFontSize = document.getElementById('settingFontSize');
const settingFontSizeValue = document.getElementById('settingFontSizeValue');
const settingBubbleStyle = document.getElementById('settingBubbleStyle');
const settingMemoryEnabled = document.getElementById('settingMemoryEnabled');
const settingDesktopNotifications = document.getElementById('settingDesktopNotifications');
const settingsAdvancedToggle = document.getElementById('settingsAdvancedToggle');
const settingsSuite = document.getElementById('settingsSuite');
const settingsSectionNav = document.getElementById('settingsSectionNav');
const settingsSectionSearch = document.getElementById('settingsSectionSearch');
const settingsNavEmpty = document.getElementById('settingsNavEmpty');
const settingsSections = document.getElementById('settingsSections');
const settingsDisplayName = document.getElementById('settingsDisplayName');
const settingProfileType = document.getElementById('settingProfileType');
const settingsAccountMeta = document.getElementById('settingsAccountMeta');
const settingsProfileAvatar = document.getElementById('settingsProfileAvatar');
const settingsAvatarInput = document.getElementById('settingsAvatarInput');
const changeAvatarBtn = document.getElementById('changeAvatarBtn');
const removeAvatarBtn = document.getElementById('removeAvatarBtn');
const settingVoice = document.getElementById('settingVoice');
const settingVoiceSpeed = document.getElementById('settingVoiceSpeed');
const settingVoiceSpeedValue = document.getElementById('settingVoiceSpeedValue');
const settingWakeWordEnabled = document.getElementById('settingWakeWordEnabled');
const settingMicDeviceId = document.getElementById('settingMicDeviceId');
const settingConcurrencyLimit = document.getElementById('settingConcurrencyLimit');
const settingWebPush = document.getElementById('settingWebPush');
const settingTelegram = document.getElementById('settingTelegram');
const settingApiKeyOpenai = document.getElementById('settingApiKeyOpenai');
const settingApiKeyAnthropic = document.getElementById('settingApiKeyAnthropic');
const settingApiKeyGoogle = document.getElementById('settingApiKeyGoogle');
const settingApiKeyElevenlabs = document.getElementById('settingApiKeyElevenlabs');
const settingApiKeyAzureOpenai = document.getElementById('settingApiKeyAzureOpenai');
const settingApiKeyCustom = document.getElementById('settingApiKeyCustom');
const settingAdvTemperature = document.getElementById('settingAdvTemperature');
const settingAdvTemperatureValue = document.getElementById('settingAdvTemperatureValue');
const settingAdvTopP = document.getElementById('settingAdvTopP');
const settingAdvTopPValue = document.getElementById('settingAdvTopPValue');
const settingAdvFrequencyPenalty = document.getElementById('settingAdvFrequencyPenalty');
const settingAdvFrequencyPenaltyValue = document.getElementById('settingAdvFrequencyPenaltyValue');
const settingAdvPresencePenalty = document.getElementById('settingAdvPresencePenalty');
const settingAdvPresencePenaltyValue = document.getElementById('settingAdvPresencePenaltyValue');
const settingAdvMaxOutputTokens = document.getElementById('settingAdvMaxOutputTokens');
const settingAdvReasoningEffort = document.getElementById('settingAdvReasoningEffort');
const settingAdvReasoningBudget = document.getElementById('settingAdvReasoningBudget');
const settingAdvDeterministicSeed = document.getElementById('settingAdvDeterministicSeed');
const settingAdvJsonMode = document.getElementById('settingAdvJsonMode');
const settingAdvStopSequences = document.getElementById('settingAdvStopSequences');
const settingAdvDefaultMode = document.getElementById('settingAdvDefaultMode');
const settingAdvDefaultTokenEconomy = document.getElementById('settingAdvDefaultTokenEconomy');
const settingAdvMaxAgentIterations = document.getElementById('settingAdvMaxAgentIterations');
const settingAdvLocalBackgroundAgents = document.getElementById('settingAdvLocalBackgroundAgents');
const settingAdvLocalGpuHeadroom = document.getElementById('settingAdvLocalGpuHeadroom');
const settingAdvPowerPcBadge = document.getElementById('settingAdvPowerPcBadge');
const settingAdvQualityEnforce = document.getElementById('settingAdvQualityEnforce');
const settingAdvQualityRequireVerification = document.getElementById('settingAdvQualityRequireVerification');
const settingAdvQualityRequireTests = document.getElementById('settingAdvQualityRequireTests');
const settingAdvQualityRequireMonolithGuard = document.getElementById('settingAdvQualityRequireMonolithGuard');
const settingAdvAutoToolThreshold = document.getElementById('settingAdvAutoToolThreshold');
const settingAdvAutoToolThresholdValue = document.getElementById('settingAdvAutoToolThresholdValue');
const settingAdvToolTimeoutS = document.getElementById('settingAdvToolTimeoutS');
const settingAdvMaxParallelTools = document.getElementById('settingAdvMaxParallelTools');
const settingAdvRequireCommandApproval = document.getElementById('settingAdvRequireCommandApproval');
const settingAdvBreakglassWindowEnabled = document.getElementById('settingAdvBreakglassWindowEnabled');
const settingAdvBreakglassWindowHours = document.getElementById('settingAdvBreakglassWindowHours');
const settingAdvAllowShell = document.getElementById('settingAdvAllowShell');
const settingAdvAllowFileWrite = document.getElementById('settingAdvAllowFileWrite');
const settingAdvAllowNetwork = document.getElementById('settingAdvAllowNetwork');
const settingAdvAllowBrowser = document.getElementById('settingAdvAllowBrowser');
const settingAdvAllowChannels = document.getElementById('settingAdvAllowChannels');
const settingAdvAllowGit = document.getElementById('settingAdvAllowGit');
const settingAdvAllowedPaths = document.getElementById('settingAdvAllowedPaths');
const settingAdvBlockedCommands = document.getElementById('settingAdvBlockedCommands');
const settingAdvIncludeGlobalMemory = document.getElementById('settingAdvIncludeGlobalMemory');
const settingAdvRetrievalTopK = document.getElementById('settingAdvRetrievalTopK');
const settingAdvMaxPackTokens = document.getElementById('settingAdvMaxPackTokens');
const settingAdvDecayHalfLifeHours = document.getElementById('settingAdvDecayHalfLifeHours');
const settingAdvAutoSummarizeThreshold = document.getElementById('settingAdvAutoSummarizeThreshold');
const settingAdvMemoryDecayDays = document.getElementById('settingAdvMemoryDecayDays');
const settingAdvAutoCompactEnabled = document.getElementById('settingAdvAutoCompactEnabled');
const settingAdvAutoCompactEpisodeThreshold = document.getElementById('settingAdvAutoCompactEpisodeThreshold');
const settingAdvAutoCompactMinIntervalHours = document.getElementById('settingAdvAutoCompactMinIntervalHours');
const settingAdvAutoOptimizeEnabled = document.getElementById('settingAdvAutoOptimizeEnabled');
const settingAdvAutoOptimizeWasteThreshold = document.getElementById('settingAdvAutoOptimizeWasteThreshold');
const settingAdvAutoOptimizeMinIntervalHours = document.getElementById('settingAdvAutoOptimizeMinIntervalHours');
const settingAdvContradictionPolicy = document.getElementById('settingAdvContradictionPolicy');
const settingAdvContextPruneStrategy = document.getElementById('settingAdvContextPruneStrategy');
const settingAdvIncludeProfileMemory = document.getElementById('settingAdvIncludeProfileMemory');
const settingAdvIncludeThreadMemory = document.getElementById('settingAdvIncludeThreadMemory');
const settingAdvPinsOnly = document.getElementById('settingAdvPinsOnly');
const settingAdvPinnedContext = document.getElementById('settingAdvPinnedContext');
const settingAdvSessionTokenBudget = document.getElementById('settingAdvSessionTokenBudget');
const settingAdvDailyTokenBudget = document.getElementById('settingAdvDailyTokenBudget');
const settingAdvMaxRetries = document.getElementById('settingAdvMaxRetries');
const settingAdvRetryBackoffMs = document.getElementById('settingAdvRetryBackoffMs');
const settingAdvThrottleOnBudget = document.getElementById('settingAdvThrottleOnBudget');
const settingAdvLowCostMode = document.getElementById('settingAdvLowCostMode');
const settingAdvProviderFailoverChain = document.getElementById('settingAdvProviderFailoverChain');
const settingAdvModelFailoverChain = document.getElementById('settingAdvModelFailoverChain');
const settingAdvFailoverEnabled = document.getElementById('settingAdvFailoverEnabled');
const settingAdvChatAutoFailover = document.getElementById('settingAdvChatAutoFailover');
const settingAdvFallbackOnAuthError = document.getElementById('settingAdvFallbackOnAuthError');
const settingAdvFailoverCooldownSeconds = document.getElementById('settingAdvFailoverCooldownSeconds');
const settingAdvRetentionDays = document.getElementById('settingAdvRetentionDays');
const settingAdvTelemetryEnabled = document.getElementById('settingAdvTelemetryEnabled');
const settingAdvRedactSecretsInLogs = document.getElementById('settingAdvRedactSecretsInLogs');
const settingAdvPiiGuardStrict = document.getElementById('settingAdvPiiGuardStrict');
const settingAdvLocalOnlyMode = document.getElementById('settingAdvLocalOnlyMode');
const settingAdvAuditLogEnabled = document.getElementById('settingAdvAuditLogEnabled');
const settingAdvExportOnExit = document.getElementById('settingAdvExportOnExit');
const settingAdvUiDensity = document.getElementById('settingAdvUiDensity');
const settingAdvCodeTheme = document.getElementById('settingAdvCodeTheme');
const settingAdvEventLogVerbosity = document.getElementById('settingAdvEventLogVerbosity');
const settingAdvShowTimestamps = document.getElementById('settingAdvShowTimestamps');
const settingAdvShowTokenMeter = document.getElementById('settingAdvShowTokenMeter');
const settingAdvAnimationFidelity = document.getElementById('settingAdvAnimationFidelity');
const settingAdvAnimationsEnabled = document.getElementById('settingAdvAnimationsEnabled');
const settingAdvDebugPanelEnabled = document.getElementById('settingAdvDebugPanelEnabled');
const settingAdvLabsFlags = document.getElementById('settingAdvLabsFlags');
// ── New Settings: Workspaces ──
const settingWsMission = document.getElementById('settingWsMission');
const settingWsAppBuilder = document.getElementById('settingWsAppBuilder');
const settingWsMyStuff = document.getElementById('settingWsMyStuff');
const settingWsChannels = document.getElementById('settingWsChannels');
const settingWsTokenEconomy = document.getElementById('settingWsTokenEconomy');
const settingWsMarketplace = document.getElementById('settingWsMarketplace');
const settingWsOffice = document.getElementById('settingWsOffice');
// ── New Settings: Token Economy ──
const settingTeMonthlyBudget = document.getElementById('settingTeMonthlyBudget');
const settingTeBudgetAlertPct = document.getElementById('settingTeBudgetAlertPct');
const settingTeShowSidebarSpend = document.getElementById('settingTeShowSidebarSpend');
const settingTeAutoSummarize = document.getElementById('settingTeAutoSummarize');
// ── New Settings: Channels ──
const settingChDefaultChannel = document.getElementById('settingChDefaultChannel');
const settingChMaxMessageLength = document.getElementById('settingChMaxMessageLength');
const settingChAutoRoute = document.getElementById('settingChAutoRoute');
const settingChNotifications = document.getElementById('settingChNotifications');
const settingChAllowUploads = document.getElementById('settingChAllowUploads');
// ── New Settings: Marketplace & Plugins ──
const settingMpAutoUpdate = document.getElementById('settingMpAutoUpdate');
const settingMpShowDomainModules = document.getElementById('settingMpShowDomainModules');
const settingMpPluginNetworkAccess = document.getElementById('settingMpPluginNetworkAccess');
// ── New Settings: Data & Storage ──
const settingDataPersistHistory = document.getElementById('settingDataPersistHistory');
const settingDataAutoArchive = document.getElementById('settingDataAutoArchive');
const sidebarUserAvatar = document.getElementById('sidebarUserAvatar');
const sidebarChatPanel = document.getElementById('sidebarChatPanel');
const searchOverlayBar = document.getElementById('searchOverlayBar');
const sidebarChatList = document.getElementById('sidebarChatList');
const sidebarSearchModeLabel = document.getElementById('sidebarSearchModeLabel');
const sidebarChatHeaderLabel = document.getElementById('sidebarChatHeaderLabel');
const taskContinuityPanel = document.getElementById('taskContinuityPanel');
const taskContinuityStatusPill = document.getElementById('taskContinuityStatusPill');
const taskContinuityGoal = document.getElementById('taskContinuityGoal');
const taskContinuityBlockersWrap = document.getElementById('taskContinuityBlockersWrap');
const taskContinuityBlockersList = document.getElementById('taskContinuityBlockersList');
const taskContinuityProgress = document.getElementById('taskContinuityProgress');
const taskContinuityEventsList = document.getElementById('taskContinuityEventsList');
const taskContinuityUpdatedAt = document.getElementById('taskContinuityUpdatedAt');
const taskContinuitySession = document.getElementById('taskContinuitySession');
const taskContinuityRefreshBtn = document.getElementById('taskContinuityRefreshBtn');
const debugDockToggleBtn = document.getElementById('debugDockToggleBtn');
const debugDock = document.getElementById('debugDock');
const debugDockCloseBtn = document.getElementById('debugDockCloseBtn');
const debugDockRefreshBtn = document.getElementById('debugDockRefreshBtn');
const debugDockTabs = document.getElementById('debugDockTabs');
const debugTabRuntime = document.getElementById('debugTabRuntime');
const debugTabSystem = document.getElementById('debugTabSystem');
const debugTabModels = document.getElementById('debugTabModels');
const debugTabTools = document.getElementById('debugTabTools');
const debugTabMemory = document.getElementById('debugTabMemory');
const debugTabRuns = document.getElementById('debugTabRuns');
const debugTabEvents = document.getElementById('debugTabEvents');
const debugTabConsole = document.getElementById('debugTabConsole');
const debugTabNetwork = document.getElementById('debugTabNetwork');
const debugPanelRuntime = document.getElementById('debugPanelRuntime');
const debugPanelSystem = document.getElementById('debugPanelSystem');
const debugPanelModels = document.getElementById('debugPanelModels');
const debugPanelTools = document.getElementById('debugPanelTools');
const debugPanelMemory = document.getElementById('debugPanelMemory');
const debugPanelRuns = document.getElementById('debugPanelRuns');
const debugPanelEvents = document.getElementById('debugPanelEvents');
const debugPanelConsole = document.getElementById('debugPanelConsole');
const debugPanelNetwork = document.getElementById('debugPanelNetwork');
const debugCopySnapshotBtn = document.getElementById('debugCopySnapshotBtn');
const debugClearEventsBtn = document.getElementById('debugClearEventsBtn');
const debugClearConsoleBtn = document.getElementById('debugClearConsoleBtn');
const debugClearNetworkBtn = document.getElementById('debugClearNetworkBtn');
const debugEventLog = document.getElementById('debugEventLog');
const debugConsoleLog = document.getElementById('debugConsoleLog');
const debugNetworkLog = document.getElementById('debugNetworkLog');
const debugSessionId = document.getElementById('debugSessionId');
const debugModel = document.getElementById('debugModel');
const debugMessageCount = document.getElementById('debugMessageCount');
const debugGenerating = document.getElementById('debugGenerating');
const debugSidebarState = document.getElementById('debugSidebarState');
const debugSearchScope = document.getElementById('debugSearchScope');
const debugThemeName = document.getElementById('debugThemeName');
const debugViewport = document.getElementById('debugViewport');
const debugEventCount = document.getElementById('debugEventCount');
const debugConsoleCount = document.getElementById('debugConsoleCount');
const debugNetworkCount = document.getElementById('debugNetworkCount');
const debugNetworkTotal = document.getElementById('debugNetworkTotal');
const debugNetworkErrors = document.getElementById('debugNetworkErrors');
const debugNetworkAvgMs = document.getElementById('debugNetworkAvgMs');
const debugSystemVersion = document.getElementById('debugSystemVersion');
const debugSystemReady = document.getElementById('debugSystemReady');
const debugSystemEngineCount = document.getElementById('debugSystemEngineCount');
const debugSystemStatus = document.getElementById('debugSystemStatus');
const debugSystemEngineList = document.getElementById('debugSystemEngineList');
const debugOnboardingGateStatusPill = document.getElementById('debugOnboardingGateStatusPill');
const debugOnboardingCompletionRate = document.getElementById('debugOnboardingCompletionRate');
const debugOnboardingMedianReadySeconds = document.getElementById('debugOnboardingMedianReadySeconds');
const debugOnboardingRepairBtn = document.getElementById('debugOnboardingRepairBtn');
const debugOnboardingGateStatus = document.getElementById('debugOnboardingGateStatus');
const debugOnboardingGateList = document.getElementById('debugOnboardingGateList');
const debugModelsDefault = document.getElementById('debugModelsDefault');
const debugModelsCount = document.getElementById('debugModelsCount');
const debugModelsHealthy = document.getElementById('debugModelsHealthy');
const debugModelHealthList = document.getElementById('debugModelHealthList');
const debugToolsTotal = document.getElementById('debugToolsTotal');
const debugToolsCategories = document.getElementById('debugToolsCategories');
const debugToolCategoryList = document.getElementById('debugToolCategoryList');
const debugToolRegistryList = document.getElementById('debugToolRegistryList');
const debugWebhooksCount = document.getElementById('debugWebhooksCount');
const debugWebhooksWithSecret = document.getElementById('debugWebhooksWithSecret');
const debugWebhooksInboxCount = document.getElementById('debugWebhooksInboxCount');
const debugWebhooksList = document.getElementById('debugWebhooksList');
const debugWebhooksInboxList = document.getElementById('debugWebhooksInboxList');
const debugMemoryEnabled = document.getElementById('debugMemoryEnabled');
const debugMemoryPins = document.getElementById('debugMemoryPins');
const debugMemoryContradictions = document.getElementById('debugMemoryContradictions');
const debugMemoryList = document.getElementById('debugMemoryList');
const debugRunsCount = document.getElementById('debugRunsCount');
const debugRunsFailed = document.getElementById('debugRunsFailed');
const debugRunsList = document.getElementById('debugRunsList');
const robotAlertStage = document.getElementById('robotAlertStage');
const robotAlertDoor = document.getElementById('robotAlertDoor');
const robotAlertBot = document.getElementById('robotAlertBot');
const robotAlertBubble = document.getElementById('robotAlertBubble');

// New Phase 7 Elements
const chatHistorySelector = document.getElementById('chatHistorySelector');
const globalSearchInput = document.getElementById('globalSearchInput');

// Phase 6 Model Setup Elements
const modelSetupBtn = document.getElementById('modelSetupBtn');
const modelSetupCurrentLabel = document.getElementById('modelSetupCurrentLabel');
const modelSetupModal = document.getElementById('modelSetupModal');
const closeModelSetupBtn = document.getElementById('closeModelSetupBtn');
const applyModelSetupBtn = document.getElementById('applyModelSetupBtn');
const setupProviderSelector = document.getElementById('setupProviderSelector');
const setupProviderPicker = document.getElementById('setupProviderPicker');
const setupProviderPickerBtn = document.getElementById('setupProviderPickerBtn');
const setupProviderPickerLabel = document.getElementById('setupProviderPickerLabel');
const setupProviderPickerState = document.getElementById('setupProviderPickerState');
const setupProviderMenu = document.getElementById('setupProviderMenu');
const setupPersonalitySelector = document.getElementById('setupPersonalitySelector');
const customPersonalityGroup = document.getElementById('customPersonalityGroup');
const setupCustomPrompt = document.getElementById('setupCustomPrompt');
const setupAutonomyGroup = document.getElementById('setupAutonomyGroup');
const setupEconomyGroup = document.getElementById('setupEconomyGroup');
const setupMemoryToggle = document.getElementById('setupMemoryToggle');
const setupModelSelector = document.getElementById('setupModelSelector');
const setupSpecialtyRoleSelector = document.getElementById('setupSpecialtyRoleSelector');
const setupSpecialtyProviderSelector = document.getElementById('setupSpecialtyProviderSelector');
const setupSpecialtyModelSelector = document.getElementById('setupSpecialtyModelSelector');
const setupSpecialtyClearBtn = document.getElementById('setupSpecialtyClearBtn');
const setupSpecialtyStatus = document.getElementById('setupSpecialtyStatus');
const restartServerBtn = document.getElementById('restartServerBtn');
const restartOverlay = document.getElementById('restartOverlay');
const rerunEasySetupBtn = document.getElementById('rerunEasySetupBtn');

const easySetupModal = document.getElementById('easySetupModal');
const easySetupBackdrop = document.getElementById('easySetupBackdrop');
const easySetupCloseBtn = document.getElementById('easySetupCloseBtn');
const easySetupProgressFill = document.getElementById('easySetupProgressFill');
const easySetupProgressText = document.getElementById('easySetupProgressText');
const easySetupStep1 = document.getElementById('easySetupStep1');
const easySetupStep2 = document.getElementById('easySetupStep2');
const easySetupStep3 = document.getElementById('easySetupStep3');
const easySetupStep4 = document.getElementById('easySetupStep4');
const easySetupStep5 = document.getElementById('easySetupStep5');
const easySetupPathGrid = document.getElementById('easySetupPathGrid');
const easySetupRecommendedHint = document.getElementById('easySetupRecommendedHint');
const easySetupConnectionMeta = document.getElementById('easySetupConnectionMeta');
const easySetupCodexBlock = document.getElementById('easySetupCodexBlock');
const easySetupManualBlock = document.getElementById('easySetupManualBlock');
const easySetupLocalBlock = document.getElementById('easySetupLocalBlock');
const easySetupCodexMeta = document.getElementById('easySetupCodexMeta');
const easySetupManualProfile = document.getElementById('easySetupManualProfile');
const easySetupManualApiKey = document.getElementById('easySetupManualApiKey');
const easySetupManualPersist = document.getElementById('easySetupManualPersist');
const easySetupLocalProfile = document.getElementById('easySetupLocalProfile');
const easySetupTestConnectionBtn = document.getElementById('easySetupTestConnectionBtn');
const easySetupAutoRepairBtn = document.getElementById('easySetupAutoRepairBtn');
const easySetupConnectionStatus = document.getElementById('easySetupConnectionStatus');
const easySetupDependencyList = document.getElementById('easySetupDependencyList');
const easySetupDependencyTrustNote = document.getElementById('easySetupDependencyTrustNote');
const easySetupApproveAllBtn = document.getElementById('easySetupApproveAllBtn');
const easySetupReviewDownloadsBtn = document.getElementById('easySetupReviewDownloadsBtn');
const easySetupReviewPanel = document.getElementById('easySetupReviewPanel');
const easySetupDependencyStatus = document.getElementById('easySetupDependencyStatus');
const easySetupAnimationGrid = document.getElementById('easySetupAnimationGrid');
const easySetupAnimationHint = document.getElementById('easySetupAnimationHint');
const easySetupReadyList = document.getElementById('easySetupReadyList');
const easySetupBackBtn = document.getElementById('easySetupBackBtn');
const easySetupDismissBtn = document.getElementById('easySetupDismissBtn');
const easySetupNextBtn = document.getElementById('easySetupNextBtn');

function getSettingAdvChatPhysicsToggle() {
    return document.getElementById('settingAdvChatPhysicsEnabled');
}

function getEasySetupPhysicsToggle() {
    return document.getElementById('easySetupPhysicsToggle');
}

let activeAutonomyLevel = 1;
let activeTokenEconomy = 'balanced';
let activeReasoningEffort = '';
let activeGuardrails = (() => { try { return localStorage.getItem('thomasGuardrails') || 'guarded'; } catch (e) { return 'guarded'; } })();
// File-access permission ladder for the worker: read_only | workspace | project | pc | full.
// Default 'workspace' (sandbox-confined) — dial up to let Thomas write to your PC.
let activeFileAccess = (() => { try { return localStorage.getItem('thomasFileAccess') || 'workspace'; } catch (e) { return 'workspace'; } })();
let activeModelOverride = '';
let activeChatMode = '';
let autonomyLevelManuallySet = false;
const KNOWN_MODEL_SUGGESTIONS = {
    codex: ['gpt-5.3-codex', 'gpt-5.2-codex', 'gpt-5.1-codex-max', 'gpt-5.2', 'gpt-5.1-codex-mini'],
    openai_codex: ['gpt-5.5', 'gpt-5.4', 'gpt-5.3-codex', 'gpt-5.2-codex'],
};
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
const OFFICE_MAX_DYNAMIC_ROOMS = 40;
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
const OFFICE_DRAFT_ASSET_LIBRARY = Object.freeze({
    couch: {
        label: 'Couch',
        width: 336,
        height: 188,
        defaultColorVariant: 'caramel',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Three-seat couch for breaks, waiting, and team chat.',
    },
    desk: {
        label: 'Desk',
        width: 260,
        height: 152,
        defaultColorVariant: 'walnut',
        category: 'Work',
        interaction: 'work',
        description: 'Task desk for writing, coding, planning, and review work.',
    },
    chair: {
        label: 'Chair',
        width: 116,
        height: 132,
        defaultColorVariant: 'ink',
        category: 'Work',
        interaction: 'sit',
        description: 'Movable chair that pairs with desks and tables.',
    },
    workstation: {
        label: 'Workstation',
        width: 300,
        height: 190,
        defaultColorVariant: 'neon',
        category: 'Engineering',
        interaction: 'work',
        description: 'Monitor station for code, game builds, tests, and tooling.',
    },
    whiteboard: {
        label: 'Whiteboard',
        width: 310,
        height: 174,
        defaultColorVariant: 'clean',
        category: 'Planning',
        interaction: 'present',
        description: 'Planning board for research maps, recipes, designs, and strategy.',
    },
    vending_machine: {
        label: 'Vending Machine',
        width: 150,
        height: 260,
        defaultColorVariant: 'cola',
        category: 'Break',
        interaction: 'vend',
        description: 'Break-room vending machine that lets robots grab a Coke.',
    },
    coffee_bar: {
        label: 'Coffee Bar',
        width: 310,
        height: 176,
        defaultColorVariant: 'copper',
        category: 'Break',
        interaction: 'drink',
        description: 'Coffee and drink counter for recharge animations.',
    },
    round_table: {
        label: 'Round Table',
        width: 210,
        height: 210,
        defaultColorVariant: 'oak',
        category: 'Meeting',
        interaction: 'meet',
        description: 'Small meeting table for syncs, recipe planning, and reviews.',
    },
    plant: {
        label: 'Plant',
        width: 116,
        height: 184,
        defaultColorVariant: 'fern',
        category: 'Decor',
        interaction: 'decor',
        description: 'Office plant for softening rooms without changing task logic.',
    },
    bookshelf: {
        label: 'Bookshelf',
        width: 250,
        height: 200,
        defaultColorVariant: 'archive',
        category: 'Research',
        interaction: 'research',
        description: 'Reference shelf for research, docs, writing, and content rooms.',
    },
    server_rack: {
        label: 'Server Rack',
        width: 150,
        height: 246,
        defaultColorVariant: 'datacenter',
        category: 'Ops',
        interaction: 'monitor',
        description: 'Ops rack for deploy, monitoring, and reliability work.',
    },
    focus_pod: {
        label: 'Focus Pod',
        width: 220,
        height: 250,
        defaultColorVariant: 'quiet',
        category: 'Focus',
        interaction: 'focus',
        description: 'Private pod for deep work and long-running agent tasks.',
    },
    reception_counter: {
        label: 'Reception Counter',
        width: 360,
        height: 154,
        defaultColorVariant: 'walnut',
        colorGroup: 'wood',
        shape: 'counter',
        category: 'Lobby',
        interaction: 'dispatch',
        description: 'Front desk for intake, dispatch, and office check-ins.',
    },
    conference_table: {
        label: 'Conference Table',
        width: 430,
        height: 190,
        defaultColorVariant: 'oak',
        colorGroup: 'wood',
        shape: 'table',
        category: 'Meeting',
        interaction: 'meet',
        description: 'Long meeting table for planning, reviews, and team work.',
    },
    kitchen_island: {
        label: 'Kitchen Island',
        width: 350,
        height: 176,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'counter',
        category: 'Break',
        interaction: 'food',
        description: 'Cafeteria prep island for recipes, snacks, and break traffic.',
    },
    fridge: {
        label: 'Fridge',
        width: 130,
        height: 236,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'cabinet',
        category: 'Break',
        interaction: 'food',
        description: 'Break-room fridge for food and drink interactions.',
    },
    microwave: {
        label: 'Microwave',
        width: 156,
        height: 104,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'appliance',
        category: 'Break',
        interaction: 'food',
        description: 'Countertop microwave for cafeteria detail.',
    },
    water_cooler: {
        label: 'Water Cooler',
        width: 104,
        height: 190,
        defaultColorVariant: 'glass',
        colorGroup: 'clean',
        shape: 'tower',
        category: 'Break',
        interaction: 'drink',
        description: 'Water cooler for quick recharge stops.',
    },
    snack_shelf: {
        label: 'Snack Shelf',
        width: 216,
        height: 178,
        defaultColorVariant: 'market',
        colorGroup: 'warm',
        shape: 'shelf',
        category: 'Break',
        interaction: 'food',
        description: 'Snack shelf for break-room and recipe spaces.',
    },
    printer: {
        label: 'Printer',
        width: 192,
        height: 136,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'machine',
        category: 'Office',
        interaction: 'print',
        description: 'Shared printer for support, docs, and office workflows.',
    },
    filing_cabinet: {
        label: 'Filing Cabinet',
        width: 142,
        height: 184,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'cabinet',
        category: 'Office',
        interaction: 'archive',
        description: 'File cabinet for admin, support, and research rooms.',
    },
    archive_box: {
        label: 'Archive Box',
        width: 124,
        height: 94,
        defaultColorVariant: 'cardboard',
        colorGroup: 'warm',
        shape: 'box',
        category: 'Office',
        interaction: 'archive',
        description: 'Movable archive box for storage corners and mail areas.',
    },
    floor_lamp: {
        label: 'Floor Lamp',
        width: 92,
        height: 220,
        defaultColorVariant: 'amber',
        colorGroup: 'light',
        shape: 'lamp',
        category: 'Decor',
        interaction: 'decor',
        description: 'Floor lamp for lounge, focus, and design spaces.',
    },
    wall_monitor: {
        label: 'Wall Monitor',
        width: 250,
        height: 145,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'screen',
        category: 'Engineering',
        interaction: 'monitor',
        description: 'Wall display for dashboards, game builds, and ops status.',
    },
    kanban_board: {
        label: 'Kanban Board',
        width: 270,
        height: 168,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'board',
        category: 'Planning',
        interaction: 'present',
        description: 'Task board for planning rooms and work queues.',
    },
    blueprint_table: {
        label: 'Blueprint Table',
        width: 320,
        height: 176,
        defaultColorVariant: 'blueprint',
        colorGroup: 'tech',
        shape: 'table',
        category: 'Planning',
        interaction: 'plan',
        description: 'Wide table for layouts, recipes, and build plans.',
    },
    lab_bench: {
        label: 'Lab Bench',
        width: 340,
        height: 162,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'bench',
        category: 'Engineering',
        interaction: 'work',
        description: 'Bench for testing, debugging, and build work.',
    },
    tool_cart: {
        label: 'Tool Cart',
        width: 162,
        height: 138,
        defaultColorVariant: 'warning',
        colorGroup: 'warm',
        shape: 'cart',
        category: 'Engineering',
        interaction: 'tools',
        description: 'Rolling cart for engineering and repair rooms.',
    },
    charging_dock: {
        label: 'Charging Dock',
        width: 236,
        height: 128,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'dock',
        category: 'Robots',
        interaction: 'charge',
        description: 'Robot charging dock for idle and lobby areas.',
    },
    router_node: {
        label: 'Router Node',
        width: 168,
        height: 118,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'node',
        category: 'Ops',
        interaction: 'network',
        description: 'Network node for ops, integrations, and automation rooms.',
    },
    security_console: {
        label: 'Security Console',
        width: 310,
        height: 168,
        defaultColorVariant: 'warning',
        colorGroup: 'tech',
        shape: 'console',
        category: 'Ops',
        interaction: 'monitor',
        description: 'Monitoring console for incidents and reliability work.',
    },
    standing_desk: {
        label: 'Standing Desk',
        width: 238,
        height: 168,
        defaultColorVariant: 'steel',
        colorGroup: 'wood',
        shape: 'desk',
        category: 'Work',
        interaction: 'work',
        description: 'Compact standing desk for active work rooms.',
    },
    drafting_table: {
        label: 'Drafting Table',
        width: 282,
        height: 172,
        defaultColorVariant: 'oak',
        colorGroup: 'wood',
        shape: 'tilt_table',
        category: 'Design',
        interaction: 'design',
        description: 'Angled table for visual design and product sketches.',
    },
    camera_tripod: {
        label: 'Camera Tripod',
        width: 120,
        height: 205,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'tripod',
        category: 'Content',
        interaction: 'record',
        description: 'Tripod camera for content, video, and product demos.',
    },
    light_panel: {
        label: 'Light Panel',
        width: 142,
        height: 214,
        defaultColorVariant: 'clean',
        colorGroup: 'light',
        shape: 'light',
        category: 'Content',
        interaction: 'record',
        description: 'Studio light panel for content and design rooms.',
    },
    acoustic_panel: {
        label: 'Acoustic Panel',
        width: 184,
        height: 116,
        defaultColorVariant: 'berry',
        colorGroup: 'soft',
        shape: 'panel',
        category: 'Content',
        interaction: 'decor',
        description: 'Sound panel for recording and focus areas.',
    },
    rug: {
        label: 'Rug',
        width: 360,
        height: 220,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'rug',
        category: 'Decor',
        interaction: 'decor',
        description: 'Soft rug that defines sitting and meeting zones.',
    },
    divider: {
        label: 'Divider',
        width: 220,
        height: 156,
        defaultColorVariant: 'slate',
        colorGroup: 'soft',
        shape: 'divider',
        category: 'Decor',
        interaction: 'decor',
        description: 'Low divider for shaping room flow without blocking editing.',
    },
    bean_bag: {
        label: 'Bean Bag',
        width: 150,
        height: 120,
        defaultColorVariant: 'berry',
        colorGroup: 'soft',
        shape: 'soft_seat',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Small casual seat for lounges and brainstorm rooms.',
    },
    arcade_cabinet: {
        label: 'Arcade Cabinet',
        width: 128,
        height: 230,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'cabinet',
        category: 'Lounge',
        interaction: 'play',
        description: 'Break-room arcade cabinet for personality and game tasks.',
    },
    trophy_shelf: {
        label: 'Trophy Shelf',
        width: 210,
        height: 168,
        defaultColorVariant: 'amber',
        colorGroup: 'light',
        shape: 'shelf',
        category: 'Decor',
        interaction: 'decor',
        description: 'Shelf for shipped wins, badges, and team trophies.',
    },
    package_station: {
        label: 'Package Station',
        width: 300,
        height: 170,
        defaultColorVariant: 'cardboard',
        colorGroup: 'warm',
        shape: 'counter',
        category: 'Ops',
        interaction: 'sort',
        description: 'Ops station for packages, files, and dispatch workflows.',
    },
    mail_sorter: {
        label: 'Mail Sorter',
        width: 220,
        height: 170,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'shelf',
        category: 'Support',
        interaction: 'sort',
        description: 'Inbox sorter for support tickets and admin flows.',
    },
    recipe_counter: {
        label: 'Recipe Counter',
        width: 318,
        height: 168,
        defaultColorVariant: 'mint',
        colorGroup: 'clean',
        shape: 'counter',
        category: 'Break',
        interaction: 'food',
        description: 'Kitchen counter for recipe tasks and food planning.',
    },
    floor_sign: {
        label: 'Floor Sign',
        width: 94,
        height: 142,
        defaultColorVariant: 'warning',
        colorGroup: 'warm',
        shape: 'sign',
        category: 'Decor',
        interaction: 'decor',
        description: 'Small wayfinding sign for corridors and room doors.',
    },
    bench: {
        label: 'Bench',
        width: 260,
        height: 112,
        defaultColorVariant: 'oak',
        colorGroup: 'wood',
        shape: 'bench',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Low bench for waiting areas, hall edges, and break rooms.',
    },
    side_table: {
        label: 'Side Table',
        width: 150,
        height: 118,
        defaultColorVariant: 'oak',
        colorGroup: 'wood',
        shape: 'table',
        category: 'Lounge',
        interaction: 'decor',
        description: 'Small table for seating clusters and coffee corners.',
    },
    task_lamp: {
        label: 'Task Lamp',
        width: 82,
        height: 156,
        defaultColorVariant: 'clean',
        colorGroup: 'light',
        shape: 'lamp',
        category: 'Decor',
        interaction: 'decor',
        description: 'Desk-style lamp for workstations and reading corners.',
    },
    ottoman: {
        label: 'Ottoman',
        width: 142,
        height: 104,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'soft_seat',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Soft movable seat for lounges and team rooms.',
    },
    lounge_chair: {
        label: 'Lounge Chair',
        width: 160,
        height: 146,
        defaultColorVariant: 'berry',
        colorGroup: 'soft',
        shape: 'soft_seat',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Single-seat chair that fits beside couches and small tables.',
    },
    loveseat: {
        label: 'Loveseat',
        width: 238,
        height: 154,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'soft_seat',
        category: 'Lounge',
        interaction: 'sit',
        description: 'Compact couch for smaller rooms and focus corners.',
    },
    meeting_chair: {
        label: 'Meeting Chair',
        width: 104,
        height: 116,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'soft_seat',
        category: 'Meeting',
        interaction: 'sit',
        description: 'Slim meeting chair for conference and planning tables.',
    },
    stool: {
        label: 'Stool',
        width: 84,
        height: 102,
        defaultColorVariant: 'walnut',
        colorGroup: 'wood',
        shape: 'soft_seat',
        category: 'Break',
        interaction: 'sit',
        description: 'Small stool for kitchen counters and quick work stops.',
    },
    monitor_stand: {
        label: 'Monitor Stand',
        width: 180,
        height: 108,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'screen',
        category: 'Engineering',
        interaction: 'monitor',
        description: 'Raised monitor stand for desk setups and review stations.',
    },
    laptop: {
        label: 'Laptop',
        width: 150,
        height: 96,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'screen',
        category: 'Work',
        interaction: 'work',
        description: 'Portable computer prop for flexible agent work spots.',
    },
    tablet_stand: {
        label: 'Tablet Stand',
        width: 104,
        height: 126,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'screen',
        category: 'Work',
        interaction: 'work',
        description: 'Small tablet station for checklists and quick prompts.',
    },
    keyboard_tray: {
        label: 'Keyboard Tray',
        width: 170,
        height: 72,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'panel',
        category: 'Engineering',
        interaction: 'work',
        description: 'Low tray for computer desks and coding stations.',
    },
    dual_monitor: {
        label: 'Dual Monitor',
        width: 238,
        height: 130,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'screen',
        category: 'Engineering',
        interaction: 'monitor',
        description: 'Dual screen setup for code, tests, and dashboards.',
    },
    code_terminal: {
        label: 'Code Terminal',
        width: 214,
        height: 142,
        defaultColorVariant: 'blueprint',
        colorGroup: 'tech',
        shape: 'console',
        category: 'Engineering',
        interaction: 'work',
        description: 'Terminal console for build and debugging rooms.',
    },
    testing_rig: {
        label: 'Testing Rig',
        width: 250,
        height: 150,
        defaultColorVariant: 'warning',
        colorGroup: 'tech',
        shape: 'machine',
        category: 'Engineering',
        interaction: 'tools',
        description: 'QA rig for running checks, devices, and build validation.',
    },
    game_console: {
        label: 'Game Console',
        width: 168,
        height: 108,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'machine',
        category: 'Lounge',
        interaction: 'play',
        description: 'Small game console for breaks and game-task flavor.',
    },
    vr_headset: {
        label: 'VR Headset',
        width: 120,
        height: 92,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'machine',
        category: 'Design',
        interaction: 'design',
        description: 'VR headset prop for visual and prototype work.',
    },
    sound_mixer: {
        label: 'Sound Mixer',
        width: 210,
        height: 126,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'console',
        category: 'Content',
        interaction: 'record',
        description: 'Audio mixer for video, music, and podcast rooms.',
    },
    microphone: {
        label: 'Microphone',
        width: 86,
        height: 176,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'tower',
        category: 'Content',
        interaction: 'record',
        description: 'Standing microphone for content and voice work.',
    },
    podcast_desk: {
        label: 'Podcast Desk',
        width: 310,
        height: 160,
        defaultColorVariant: 'walnut',
        colorGroup: 'wood',
        shape: 'desk',
        category: 'Content',
        interaction: 'record',
        description: 'Content desk with enough room for audio and notes.',
    },
    camera_case: {
        label: 'Camera Case',
        width: 130,
        height: 92,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'box',
        category: 'Content',
        interaction: 'record',
        description: 'Equipment case for studio corners and production spaces.',
    },
    green_screen: {
        label: 'Green Screen',
        width: 300,
        height: 178,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'panel',
        category: 'Content',
        interaction: 'record',
        description: 'Backdrop panel for recording and image generation spaces.',
    },
    prop_shelf: {
        label: 'Prop Shelf',
        width: 220,
        height: 166,
        defaultColorVariant: 'walnut',
        colorGroup: 'wood',
        shape: 'shelf',
        category: 'Content',
        interaction: 'archive',
        description: 'Shelf for video props, thumbnails, and creative assets.',
    },
    pinboard: {
        label: 'Pinboard',
        width: 240,
        height: 142,
        defaultColorVariant: 'cardboard',
        colorGroup: 'warm',
        shape: 'board',
        category: 'Planning',
        interaction: 'present',
        description: 'Pinned notes board for design, research, and planning.',
    },
    sticky_note_wall: {
        label: 'Sticky Note Wall',
        width: 270,
        height: 152,
        defaultColorVariant: 'warning',
        colorGroup: 'warm',
        shape: 'board',
        category: 'Planning',
        interaction: 'plan',
        description: 'Wall of notes for strategy, recipes, and task breakdowns.',
    },
    map_table: {
        label: 'Map Table',
        width: 300,
        height: 164,
        defaultColorVariant: 'blueprint',
        colorGroup: 'tech',
        shape: 'table',
        category: 'Research',
        interaction: 'research',
        description: 'Wide table for source maps, routes, and investigation plans.',
    },
    research_terminal: {
        label: 'Research Terminal',
        width: 232,
        height: 148,
        defaultColorVariant: 'blueprint',
        colorGroup: 'tech',
        shape: 'console',
        category: 'Research',
        interaction: 'research',
        description: 'Terminal for lookup-heavy research and analysis tasks.',
    },
    microscope: {
        label: 'Microscope',
        width: 108,
        height: 154,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'machine',
        category: 'Research',
        interaction: 'research',
        description: 'Detail prop for careful investigation rooms.',
    },
    sample_tray: {
        label: 'Sample Tray',
        width: 150,
        height: 86,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'box',
        category: 'Research',
        interaction: 'research',
        description: 'Small tray for grouped findings and reference items.',
    },
    data_wall: {
        label: 'Data Wall',
        width: 330,
        height: 182,
        defaultColorVariant: 'blueprint',
        colorGroup: 'tech',
        shape: 'screen',
        category: 'Ops',
        interaction: 'monitor',
        description: 'Large dashboard wall for metrics, data, and monitoring.',
    },
    server_console: {
        label: 'Server Console',
        width: 260,
        height: 150,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'console',
        category: 'Ops',
        interaction: 'monitor',
        description: 'Control console for servers and deployment tasks.',
    },
    power_panel: {
        label: 'Power Panel',
        width: 150,
        height: 188,
        defaultColorVariant: 'warning',
        colorGroup: 'tech',
        shape: 'cabinet',
        category: 'Ops',
        interaction: 'monitor',
        description: 'Utility panel for infra and automation rooms.',
    },
    network_switch: {
        label: 'Network Switch',
        width: 196,
        height: 92,
        defaultColorVariant: 'neon',
        colorGroup: 'tech',
        shape: 'node',
        category: 'Ops',
        interaction: 'network',
        description: 'Network switch for integration and reliability spaces.',
    },
    firewall_box: {
        label: 'Firewall Box',
        width: 152,
        height: 124,
        defaultColorVariant: 'warning',
        colorGroup: 'tech',
        shape: 'box',
        category: 'Ops',
        interaction: 'network',
        description: 'Security appliance for ops and infrastructure rooms.',
    },
    dispatch_board: {
        label: 'Dispatch Board',
        width: 280,
        height: 156,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'board',
        category: 'Support',
        interaction: 'dispatch',
        description: 'Assignment board for tickets, agents, and handoffs.',
    },
    ticket_kiosk: {
        label: 'Ticket Kiosk',
        width: 148,
        height: 210,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'tower',
        category: 'Support',
        interaction: 'support',
        description: 'Self-serve ticket kiosk for support desks and lobbies.',
    },
    phone_booth: {
        label: 'Phone Booth',
        width: 168,
        height: 238,
        defaultColorVariant: 'slate',
        colorGroup: 'soft',
        shape: 'cabinet',
        category: 'Support',
        interaction: 'focus',
        description: 'Private booth for calls, support replies, and focus work.',
    },
    copier: {
        label: 'Copier',
        width: 186,
        height: 132,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'machine',
        category: 'Office',
        interaction: 'print',
        description: 'Shared copier for admin and document-heavy rooms.',
    },
    shredder: {
        label: 'Shredder',
        width: 98,
        height: 140,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'machine',
        category: 'Office',
        interaction: 'archive',
        description: 'Office shredder for support and admin corners.',
    },
    mail_cart: {
        label: 'Mail Cart',
        width: 158,
        height: 124,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'cart',
        category: 'Support',
        interaction: 'sort',
        description: 'Rolling mail cart for dispatch and support rooms.',
    },
    storage_locker: {
        label: 'Storage Locker',
        width: 158,
        height: 220,
        defaultColorVariant: 'steel',
        colorGroup: 'metal',
        shape: 'cabinet',
        category: 'Office',
        interaction: 'archive',
        description: 'Tall locker for equipment, tools, and office supplies.',
    },
    trash_bin: {
        label: 'Trash Bin',
        width: 84,
        height: 108,
        defaultColorVariant: 'graphite',
        colorGroup: 'metal',
        shape: 'box',
        category: 'Office',
        interaction: 'decor',
        description: 'Small bin for realistic office corners.',
    },
    coat_rack: {
        label: 'Coat Rack',
        width: 84,
        height: 190,
        defaultColorVariant: 'walnut',
        colorGroup: 'wood',
        shape: 'tower',
        category: 'Lobby',
        interaction: 'decor',
        description: 'Coat rack for lobbies and reception spaces.',
    },
    wall_clock: {
        label: 'Wall Clock',
        width: 86,
        height: 86,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'panel',
        category: 'Decor',
        interaction: 'decor',
        description: 'Small wall clock for rooms that need office detail.',
    },
    tall_plant: {
        label: 'Tall Plant',
        width: 106,
        height: 236,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'tower',
        category: 'Decor',
        interaction: 'decor',
        description: 'Tall plant for corners and hallway-adjacent spaces.',
    },
    planter_box: {
        label: 'Planter Box',
        width: 220,
        height: 96,
        defaultColorVariant: 'moss',
        colorGroup: 'soft',
        shape: 'box',
        category: 'Decor',
        interaction: 'decor',
        description: 'Low planter for shaping room edges without looking empty.',
    },
    room_sign: {
        label: 'Room Sign',
        width: 134,
        height: 82,
        defaultColorVariant: 'clean',
        colorGroup: 'clean',
        shape: 'sign',
        category: 'Decor',
        interaction: 'decor',
        description: 'Small room sign for labels, wayfinding, and door detail.',
    },
    snack_table: {
        label: 'Snack Table',
        width: 238,
        height: 126,
        defaultColorVariant: 'market',
        colorGroup: 'warm',
        shape: 'table',
        category: 'Break',
        interaction: 'food',
        description: 'Snack table for break rooms and recipe work.',
    },
    soda_crate: {
        label: 'Soda Crate',
        width: 126,
        height: 88,
        defaultColorVariant: 'market',
        colorGroup: 'warm',
        shape: 'box',
        category: 'Break',
        interaction: 'drink',
        description: 'Crate of sodas for vending and break-room detail.',
    },
    tea_station: {
        label: 'Tea Station',
        width: 196,
        height: 122,
        defaultColorVariant: 'mint',
        colorGroup: 'clean',
        shape: 'counter',
        category: 'Break',
        interaction: 'drink',
        description: 'Small drink station for coffee, tea, and recharge stops.',
    },
});
const OFFICE_DRAFT_ASSET_COLORWAYS = Object.freeze({
    couch: Object.freeze({
        caramel: {
            label: 'Caramel',
            back: 'linear-gradient(180deg, rgba(212, 160, 117, 0.98), rgba(162, 105, 69, 0.98))',
            seat: 'linear-gradient(180deg, rgba(223, 176, 132, 1), rgba(175, 117, 78, 0.98))',
            arm: 'linear-gradient(180deg, rgba(190, 132, 92, 0.98), rgba(141, 87, 56, 0.98))',
            seam: 'rgba(112, 63, 37, 0.34)',
            swatch: 'linear-gradient(180deg, #d4a075, #9f6844)',
        },
        moss: {
            label: 'Moss',
            back: 'linear-gradient(180deg, rgba(146, 172, 126, 0.98), rgba(92, 118, 76, 0.98))',
            seat: 'linear-gradient(180deg, rgba(170, 195, 147, 1), rgba(108, 138, 89, 0.98))',
            arm: 'linear-gradient(180deg, rgba(126, 150, 106, 0.98), rgba(83, 106, 66, 0.98))',
            seam: 'rgba(52, 74, 42, 0.34)',
            swatch: 'linear-gradient(180deg, #9cbc81, #63814f)',
        },
        harbor: {
            label: 'Harbor',
            back: 'linear-gradient(180deg, rgba(123, 158, 198, 0.98), rgba(73, 104, 145, 0.98))',
            seat: 'linear-gradient(180deg, rgba(153, 187, 224, 1), rgba(86, 122, 168, 0.98))',
            arm: 'linear-gradient(180deg, rgba(100, 134, 176, 0.98), rgba(65, 94, 131, 0.98))',
            seam: 'rgba(38, 62, 94, 0.34)',
            swatch: 'linear-gradient(180deg, #8bb0d7, #5678a7)',
        },
        graphite: {
            label: 'Graphite',
            back: 'linear-gradient(180deg, rgba(122, 130, 143, 0.98), rgba(76, 83, 97, 0.98))',
            seat: 'linear-gradient(180deg, rgba(153, 161, 175, 1), rgba(92, 100, 116, 0.98))',
            arm: 'linear-gradient(180deg, rgba(106, 113, 126, 0.98), rgba(67, 74, 86, 0.98))',
            seam: 'rgba(42, 48, 59, 0.34)',
            swatch: 'linear-gradient(180deg, #98a0ac, #5f6773)',
        },
    }),
    desk: Object.freeze({
        walnut: {
            label: 'Walnut',
            body: 'linear-gradient(180deg, rgba(157, 112, 72, 0.98), rgba(103, 67, 42, 0.98))',
            surface: 'linear-gradient(180deg, rgba(214, 164, 102, 0.98), rgba(145, 91, 52, 0.98))',
            accent: 'rgba(248, 206, 142, 0.86)',
            line: 'rgba(80, 45, 24, 0.38)',
            swatch: 'linear-gradient(180deg, #d2a066, #805532)',
        },
        steel: {
            label: 'Steel',
            body: 'linear-gradient(180deg, rgba(121, 142, 166, 0.98), rgba(70, 84, 103, 0.98))',
            surface: 'linear-gradient(180deg, rgba(177, 194, 211, 0.98), rgba(105, 124, 146, 0.98))',
            accent: 'rgba(178, 215, 255, 0.84)',
            line: 'rgba(44, 58, 78, 0.42)',
            swatch: 'linear-gradient(180deg, #aebfd1, #677b91)',
        },
    }),
    chair: Object.freeze({
        ink: {
            label: 'Ink',
            body: 'linear-gradient(180deg, rgba(74, 90, 118, 0.98), rgba(38, 49, 70, 0.98))',
            surface: 'linear-gradient(180deg, rgba(107, 128, 165, 0.98), rgba(54, 70, 101, 0.98))',
            accent: 'rgba(169, 204, 255, 0.78)',
            line: 'rgba(23, 31, 47, 0.42)',
            swatch: 'linear-gradient(180deg, #6b80a5, #364665)',
        },
        berry: {
            label: 'Berry',
            body: 'linear-gradient(180deg, rgba(160, 87, 129, 0.98), rgba(99, 48, 82, 0.98))',
            surface: 'linear-gradient(180deg, rgba(214, 132, 177, 0.98), rgba(136, 70, 114, 0.98))',
            accent: 'rgba(255, 199, 226, 0.8)',
            line: 'rgba(83, 33, 64, 0.4)',
            swatch: 'linear-gradient(180deg, #d684b1, #874671)',
        },
    }),
    workstation: Object.freeze({
        neon: {
            label: 'Neon',
            body: 'linear-gradient(180deg, rgba(58, 75, 105, 0.98), rgba(24, 34, 54, 0.98))',
            surface: 'linear-gradient(180deg, rgba(91, 115, 151, 0.98), rgba(44, 61, 91, 0.98))',
            accent: 'rgba(99, 232, 255, 0.9)',
            line: 'rgba(11, 23, 38, 0.46)',
            swatch: 'linear-gradient(180deg, #63e8ff, #324a7a)',
        },
        amber: {
            label: 'Amber',
            body: 'linear-gradient(180deg, rgba(87, 83, 70, 0.98), rgba(42, 43, 44, 0.98))',
            surface: 'linear-gradient(180deg, rgba(134, 121, 92, 0.98), rgba(70, 68, 62, 0.98))',
            accent: 'rgba(255, 204, 112, 0.92)',
            line: 'rgba(41, 33, 22, 0.44)',
            swatch: 'linear-gradient(180deg, #ffc96e, #535047)',
        },
    }),
    whiteboard: Object.freeze({
        clean: {
            label: 'Clean',
            body: 'linear-gradient(180deg, rgba(238, 246, 255, 0.98), rgba(198, 214, 232, 0.98))',
            surface: 'linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(222, 234, 247, 0.98))',
            accent: 'rgba(77, 142, 234, 0.92)',
            line: 'rgba(94, 116, 145, 0.42)',
            swatch: 'linear-gradient(180deg, #f5fbff, #c9d8e8)',
        },
        lime: {
            label: 'Lime',
            body: 'linear-gradient(180deg, rgba(217, 245, 198, 0.98), rgba(164, 205, 134, 0.98))',
            surface: 'linear-gradient(180deg, rgba(242, 255, 230, 0.98), rgba(186, 226, 156, 0.98))',
            accent: 'rgba(65, 142, 83, 0.9)',
            line: 'rgba(68, 116, 60, 0.38)',
            swatch: 'linear-gradient(180deg, #efffde, #a7cc87)',
        },
    }),
    vending_machine: Object.freeze({
        cola: {
            label: 'Cola Red',
            body: 'linear-gradient(180deg, rgba(215, 68, 70, 0.98), rgba(122, 30, 41, 0.98))',
            surface: 'linear-gradient(180deg, rgba(255, 91, 88, 0.98), rgba(161, 41, 51, 0.98))',
            accent: 'rgba(255, 239, 214, 0.94)',
            line: 'rgba(93, 22, 31, 0.45)',
            swatch: 'linear-gradient(180deg, #ef5555, #8d2531)',
        },
        citrus: {
            label: 'Citrus',
            body: 'linear-gradient(180deg, rgba(110, 177, 92, 0.98), rgba(52, 101, 59, 0.98))',
            surface: 'linear-gradient(180deg, rgba(160, 222, 108, 0.98), rgba(77, 137, 71, 0.98))',
            accent: 'rgba(255, 244, 135, 0.95)',
            line: 'rgba(33, 72, 43, 0.42)',
            swatch: 'linear-gradient(180deg, #a2df6c, #4c8847)',
        },
    }),
    coffee_bar: Object.freeze({
        copper: {
            label: 'Copper',
            body: 'linear-gradient(180deg, rgba(171, 105, 61, 0.98), rgba(91, 56, 39, 0.98))',
            surface: 'linear-gradient(180deg, rgba(225, 158, 94, 0.98), rgba(133, 82, 50, 0.98))',
            accent: 'rgba(255, 219, 166, 0.86)',
            line: 'rgba(70, 41, 26, 0.43)',
            swatch: 'linear-gradient(180deg, #d9955a, #784a31)',
        },
        mint: {
            label: 'Mint',
            body: 'linear-gradient(180deg, rgba(92, 159, 145, 0.98), rgba(48, 92, 87, 0.98))',
            surface: 'linear-gradient(180deg, rgba(132, 213, 196, 0.98), rgba(73, 134, 125, 0.98))',
            accent: 'rgba(225, 255, 249, 0.86)',
            line: 'rgba(30, 72, 68, 0.42)',
            swatch: 'linear-gradient(180deg, #81d4c4, #49857c)',
        },
    }),
    round_table: Object.freeze({
        oak: {
            label: 'Oak',
            body: 'linear-gradient(180deg, rgba(194, 137, 79, 0.98), rgba(111, 73, 43, 0.98))',
            surface: 'linear-gradient(180deg, rgba(231, 180, 106, 0.98), rgba(153, 96, 54, 0.98))',
            accent: 'rgba(255, 222, 159, 0.82)',
            line: 'rgba(91, 52, 25, 0.42)',
            swatch: 'linear-gradient(180deg, #e2ae69, #935e38)',
        },
        glass: {
            label: 'Glass',
            body: 'linear-gradient(180deg, rgba(109, 149, 178, 0.56), rgba(58, 88, 117, 0.74))',
            surface: 'linear-gradient(180deg, rgba(186, 232, 255, 0.66), rgba(89, 142, 181, 0.74))',
            accent: 'rgba(228, 249, 255, 0.92)',
            line: 'rgba(60, 90, 119, 0.42)',
            swatch: 'linear-gradient(180deg, #c1eaff, #5d8db4)',
        },
    }),
    plant: Object.freeze({
        fern: {
            label: 'Fern',
            body: 'linear-gradient(180deg, rgba(68, 135, 76, 0.98), rgba(37, 82, 48, 0.98))',
            surface: 'linear-gradient(180deg, rgba(126, 193, 101, 0.98), rgba(54, 119, 65, 0.98))',
            accent: 'rgba(221, 176, 112, 0.9)',
            line: 'rgba(31, 67, 39, 0.4)',
            swatch: 'linear-gradient(180deg, #7bc166, #367842)',
        },
        blossom: {
            label: 'Blossom',
            body: 'linear-gradient(180deg, rgba(90, 151, 87, 0.98), rgba(51, 92, 54, 0.98))',
            surface: 'linear-gradient(180deg, rgba(148, 211, 118, 0.98), rgba(73, 135, 72, 0.98))',
            accent: 'rgba(255, 177, 210, 0.9)',
            line: 'rgba(42, 78, 43, 0.4)',
            swatch: 'linear-gradient(180deg, #93d276, #498648)',
        },
    }),
    bookshelf: Object.freeze({
        archive: {
            label: 'Archive',
            body: 'linear-gradient(180deg, rgba(139, 94, 61, 0.98), rgba(81, 55, 39, 0.98))',
            surface: 'linear-gradient(180deg, rgba(183, 125, 72, 0.98), rgba(103, 69, 43, 0.98))',
            accent: 'rgba(116, 178, 243, 0.9)',
            line: 'rgba(62, 39, 24, 0.42)',
            swatch: 'linear-gradient(180deg, #b47b49, #65442b)',
        },
        library: {
            label: 'Library',
            body: 'linear-gradient(180deg, rgba(86, 105, 119, 0.98), rgba(46, 59, 73, 0.98))',
            surface: 'linear-gradient(180deg, rgba(126, 145, 160, 0.98), rgba(68, 84, 101, 0.98))',
            accent: 'rgba(238, 206, 134, 0.92)',
            line: 'rgba(32, 42, 54, 0.45)',
            swatch: 'linear-gradient(180deg, #7f91a0, #465565)',
        },
    }),
    server_rack: Object.freeze({
        datacenter: {
            label: 'Datacenter',
            body: 'linear-gradient(180deg, rgba(57, 68, 83, 0.98), rgba(21, 29, 42, 0.98))',
            surface: 'linear-gradient(180deg, rgba(89, 104, 123, 0.98), rgba(36, 48, 66, 0.98))',
            accent: 'rgba(106, 255, 178, 0.92)',
            line: 'rgba(10, 18, 31, 0.5)',
            swatch: 'linear-gradient(180deg, #6affb2, #28364b)',
        },
        warning: {
            label: 'Warning',
            body: 'linear-gradient(180deg, rgba(78, 68, 53, 0.98), rgba(35, 33, 32, 0.98))',
            surface: 'linear-gradient(180deg, rgba(112, 95, 68, 0.98), rgba(55, 51, 47, 0.98))',
            accent: 'rgba(255, 197, 76, 0.94)',
            line: 'rgba(31, 25, 20, 0.46)',
            swatch: 'linear-gradient(180deg, #ffc54c, #37322f)',
        },
    }),
    focus_pod: Object.freeze({
        quiet: {
            label: 'Quiet',
            body: 'linear-gradient(180deg, rgba(93, 105, 135, 0.98), rgba(48, 57, 82, 0.98))',
            surface: 'linear-gradient(180deg, rgba(133, 151, 189, 0.98), rgba(72, 84, 119, 0.98))',
            accent: 'rgba(203, 225, 255, 0.88)',
            line: 'rgba(40, 49, 72, 0.43)',
            swatch: 'linear-gradient(180deg, #8797bc, #465476)',
        },
        sunrise: {
            label: 'Sunrise',
            body: 'linear-gradient(180deg, rgba(171, 112, 99, 0.98), rgba(96, 61, 65, 0.98))',
            surface: 'linear-gradient(180deg, rgba(223, 153, 125, 0.98), rgba(130, 80, 77, 0.98))',
            accent: 'rgba(255, 220, 152, 0.9)',
            line: 'rgba(75, 44, 45, 0.43)',
            swatch: 'linear-gradient(180deg, #de997d, #80514d)',
        },
    }),
    wood: Object.freeze({
        walnut: {
            label: 'Walnut',
            body: 'linear-gradient(180deg, rgba(151, 101, 62, 0.98), rgba(86, 55, 36, 0.98))',
            surface: 'linear-gradient(180deg, rgba(221, 164, 95, 0.98), rgba(138, 87, 48, 0.98))',
            accent: 'rgba(255, 213, 139, 0.9)',
            line: 'rgba(76, 43, 24, 0.45)',
            swatch: 'linear-gradient(180deg, #dba160, #80512d)',
        },
        oak: {
            label: 'Oak',
            body: 'linear-gradient(180deg, rgba(186, 143, 83, 0.98), rgba(111, 76, 39, 0.98))',
            surface: 'linear-gradient(180deg, rgba(232, 190, 116, 0.98), rgba(153, 102, 51, 0.98))',
            accent: 'rgba(255, 229, 158, 0.9)',
            line: 'rgba(88, 57, 28, 0.42)',
            swatch: 'linear-gradient(180deg, #e9bd75, #996633)',
        },
        steel: {
            label: 'Steel',
            body: 'linear-gradient(180deg, rgba(117, 135, 155, 0.98), rgba(63, 76, 95, 0.98))',
            surface: 'linear-gradient(180deg, rgba(180, 196, 211, 0.98), rgba(104, 121, 142, 0.98))',
            accent: 'rgba(190, 224, 255, 0.86)',
            line: 'rgba(47, 58, 75, 0.45)',
            swatch: 'linear-gradient(180deg, #b4c4d3, #667891)',
        },
    }),
    tech: Object.freeze({
        neon: {
            label: 'Neon',
            body: 'linear-gradient(180deg, rgba(49, 68, 103, 0.98), rgba(19, 29, 52, 0.98))',
            surface: 'linear-gradient(180deg, rgba(82, 105, 145, 0.98), rgba(38, 57, 91, 0.98))',
            accent: 'rgba(94, 232, 255, 0.94)',
            line: 'rgba(7, 16, 30, 0.5)',
            swatch: 'linear-gradient(180deg, #5ee8ff, #26395b)',
        },
        warning: {
            label: 'Warning',
            body: 'linear-gradient(180deg, rgba(82, 72, 54, 0.98), rgba(35, 34, 36, 0.98))',
            surface: 'linear-gradient(180deg, rgba(121, 102, 71, 0.98), rgba(58, 55, 51, 0.98))',
            accent: 'rgba(255, 203, 74, 0.96)',
            line: 'rgba(29, 24, 18, 0.5)',
            swatch: 'linear-gradient(180deg, #ffcb4a, #34312e)',
        },
        blueprint: {
            label: 'Blueprint',
            body: 'linear-gradient(180deg, rgba(59, 100, 146, 0.98), rgba(31, 56, 98, 0.98))',
            surface: 'linear-gradient(180deg, rgba(90, 146, 194, 0.98), rgba(45, 82, 136, 0.98))',
            accent: 'rgba(203, 238, 255, 0.95)',
            line: 'rgba(24, 49, 82, 0.45)',
            swatch: 'linear-gradient(180deg, #5b92c2, #2d5288)',
        },
    }),
    metal: Object.freeze({
        steel: {
            label: 'Steel',
            body: 'linear-gradient(180deg, rgba(135, 150, 166, 0.98), rgba(74, 87, 104, 0.98))',
            surface: 'linear-gradient(180deg, rgba(195, 207, 218, 0.98), rgba(112, 129, 148, 0.98))',
            accent: 'rgba(220, 239, 255, 0.9)',
            line: 'rgba(45, 56, 71, 0.46)',
            swatch: 'linear-gradient(180deg, #c2cfd9, #728295)',
        },
        graphite: {
            label: 'Graphite',
            body: 'linear-gradient(180deg, rgba(95, 103, 116, 0.98), rgba(43, 49, 61, 0.98))',
            surface: 'linear-gradient(180deg, rgba(136, 146, 160, 0.98), rgba(73, 82, 99, 0.98))',
            accent: 'rgba(178, 198, 226, 0.88)',
            line: 'rgba(30, 36, 47, 0.48)',
            swatch: 'linear-gradient(180deg, #87919f, #485263)',
        },
    }),
    clean: Object.freeze({
        clean: {
            label: 'Clean',
            body: 'linear-gradient(180deg, rgba(221, 232, 238, 0.98), rgba(159, 178, 190, 0.98))',
            surface: 'linear-gradient(180deg, rgba(250, 255, 255, 0.98), rgba(204, 222, 229, 0.98))',
            accent: 'rgba(94, 173, 220, 0.9)',
            line: 'rgba(94, 116, 130, 0.42)',
            swatch: 'linear-gradient(180deg, #f4fbff, #c9dde6)',
        },
        glass: {
            label: 'Glass',
            body: 'linear-gradient(180deg, rgba(121, 177, 207, 0.72), rgba(67, 112, 146, 0.82))',
            surface: 'linear-gradient(180deg, rgba(219, 248, 255, 0.88), rgba(141, 206, 228, 0.82))',
            accent: 'rgba(240, 255, 255, 0.96)',
            line: 'rgba(60, 101, 126, 0.42)',
            swatch: 'linear-gradient(180deg, #d7f8ff, #86cbdc)',
        },
        mint: {
            label: 'Mint',
            body: 'linear-gradient(180deg, rgba(90, 158, 143, 0.98), rgba(47, 91, 85, 0.98))',
            surface: 'linear-gradient(180deg, rgba(133, 214, 197, 0.98), rgba(72, 134, 124, 0.98))',
            accent: 'rgba(225, 255, 249, 0.9)',
            line: 'rgba(29, 70, 66, 0.44)',
            swatch: 'linear-gradient(180deg, #83d6c5, #48867c)',
        },
    }),
    warm: Object.freeze({
        cardboard: {
            label: 'Cardboard',
            body: 'linear-gradient(180deg, rgba(176, 128, 76, 0.98), rgba(116, 78, 43, 0.98))',
            surface: 'linear-gradient(180deg, rgba(214, 160, 93, 0.98), rgba(145, 94, 50, 0.98))',
            accent: 'rgba(255, 223, 159, 0.88)',
            line: 'rgba(91, 57, 29, 0.45)',
            swatch: 'linear-gradient(180deg, #d6a05d, #8f5e32)',
        },
        market: {
            label: 'Market',
            body: 'linear-gradient(180deg, rgba(166, 91, 72, 0.98), rgba(91, 58, 53, 0.98))',
            surface: 'linear-gradient(180deg, rgba(219, 139, 90, 0.98), rgba(130, 83, 63, 0.98))',
            accent: 'rgba(255, 211, 106, 0.94)',
            line: 'rgba(72, 40, 36, 0.45)',
            swatch: 'linear-gradient(180deg, #db8b5a, #80533f)',
        },
        warning: {
            label: 'Warning',
            body: 'linear-gradient(180deg, rgba(196, 132, 48, 0.98), rgba(107, 70, 38, 0.98))',
            surface: 'linear-gradient(180deg, rgba(240, 172, 67, 0.98), rgba(147, 94, 45, 0.98))',
            accent: 'rgba(255, 238, 148, 0.94)',
            line: 'rgba(89, 54, 24, 0.45)',
            swatch: 'linear-gradient(180deg, #f0ac43, #935e2d)',
        },
    }),
    soft: Object.freeze({
        berry: {
            label: 'Berry',
            body: 'linear-gradient(180deg, rgba(151, 88, 134, 0.98), rgba(88, 51, 93, 0.98))',
            surface: 'linear-gradient(180deg, rgba(207, 130, 178, 0.98), rgba(123, 74, 128, 0.98))',
            accent: 'rgba(255, 201, 230, 0.9)',
            line: 'rgba(68, 39, 75, 0.42)',
            swatch: 'linear-gradient(180deg, #cf82b2, #7b4a80)',
        },
        moss: {
            label: 'Moss',
            body: 'linear-gradient(180deg, rgba(120, 151, 99, 0.98), rgba(72, 99, 67, 0.98))',
            surface: 'linear-gradient(180deg, rgba(162, 194, 132, 0.98), rgba(94, 128, 83, 0.98))',
            accent: 'rgba(223, 255, 181, 0.86)',
            line: 'rgba(50, 73, 43, 0.42)',
            swatch: 'linear-gradient(180deg, #a1c183, #5d8052)',
        },
        slate: {
            label: 'Slate',
            body: 'linear-gradient(180deg, rgba(104, 119, 144, 0.98), rgba(58, 71, 93, 0.98))',
            surface: 'linear-gradient(180deg, rgba(145, 162, 192, 0.98), rgba(78, 95, 126, 0.98))',
            accent: 'rgba(208, 226, 255, 0.86)',
            line: 'rgba(39, 50, 72, 0.44)',
            swatch: 'linear-gradient(180deg, #91a2c0, #4e5f7e)',
        },
    }),
    light: Object.freeze({
        amber: {
            label: 'Amber',
            body: 'linear-gradient(180deg, rgba(117, 87, 54, 0.98), rgba(62, 51, 44, 0.98))',
            surface: 'linear-gradient(180deg, rgba(230, 179, 88, 0.98), rgba(139, 96, 48, 0.98))',
            accent: 'rgba(255, 225, 125, 0.98)',
            line: 'rgba(71, 52, 31, 0.45)',
            swatch: 'linear-gradient(180deg, #ffd86e, #895f31)',
        },
        clean: {
            label: 'Clean',
            body: 'linear-gradient(180deg, rgba(181, 199, 209, 0.98), rgba(91, 108, 123, 0.98))',
            surface: 'linear-gradient(180deg, rgba(244, 250, 255, 0.98), rgba(187, 211, 224, 0.98))',
            accent: 'rgba(238, 252, 255, 0.98)',
            line: 'rgba(75, 91, 107, 0.45)',
            swatch: 'linear-gradient(180deg, #f2fbff, #b8d1de)',
        },
    }),
});
const OFFICE_VIEWPORT_MARGIN = 0;
const OFFICE_MINIMAP_PAD_RATIO = 0.06;
const OFFICE_COLLISION_PAIR_COOLDOWN_MIN = 1300;
const OFFICE_COLLISION_PAIR_COOLDOWN_MAX = 2100;
const OFFICE_COLLISION_PAIR_PURGE_MS = 2600;
const OFFICE_RUNAWAY_DURATION_MS = 5600;
const OFFICE_RUNAWAY_EXIT_MARGIN = 6.2;
const OFFICE_HAPTIC_COOLDOWN_MS = 120;
const OFFICE_RUNTIME_TIMER_FIELDS = [
    'workUntil',
    'breakUntil',
    'idleUntil',
    'nextAmbientAt',
    'nextWorkLineAt',
    'nextSocialAt',
    'nextBreakAt',
    'bumpUntil',
    'jumpUntil',
    'collisionCooldownUntil',
    'crowdReliefUntil',
    'yieldUntil',
    'stuckSince',
    'returnAfterRunAt',
];
const MISSION_POLL_INTERVAL_MS = 6500;
const MISSION_STREAM_RETRY_MIN_MS = 900;
const MISSION_STREAM_RETRY_MAX_MS = 12000;
const MISSION_STREAM_URL = '/api/mission/stream?interval=1.2';
const MISSION_PRIORITY_LIMIT = 16;
const MISSION_TIMELINE_LIMIT = 10;
const MISSION_JOBS_LIMIT = 180;
const MISSION_TIMELINE_RECENT_MS = 1000 * 60 * 60 * 36;
const MISSION_RECURRING_SCHEDULE_TYPES = new Set(['interval', 'daily', 'weekly']);
const CONTENT_HUB_STALE_MS = 45_000;
const OFFICE_TASK_KEYWORDS = /\b(build|create|design|fix|update|refactor|research|compare|analy(?:z|s)e|write|draft|plan|test|deploy|ship|record|edit|summarize|review|debug|optimi(?:s|z)e|benchmark|publish|support|investigate|script|automation|website|landing|video|content)\b/i;
const OFFICE_STATIC_ROOMS = [
    { id: 'room-planning', label: 'Strategy Room', meta: 'Planning + roadmaps', x: 4, y: 7, w: 13, h: 11, kind: 'work', theme: 'planning', doorX: 17, doorY: 24, hallId: 'hall-north-west' },
    { id: 'room-engineering', label: 'Software Lab', meta: 'Code + automation', x: 20, y: 8, w: 30, h: 16, kind: 'work', theme: 'engineering', doorX: 35, doorY: 24, hallId: 'hall-north-mid' },
    { id: 'room-content', label: 'Content Studio', meta: 'Video + social', x: 53, y: 13, w: 17, h: 12, kind: 'work', theme: 'content', doorX: 61.5, doorY: 24, hallId: 'hall-north-mid' },
    { id: 'room-research', label: 'Research Bay', meta: 'Comparisons + docs', x: 72, y: 8, w: 22, h: 14, kind: 'work', theme: 'research', doorX: 82, doorY: 24, hallId: 'hall-north-east' },
    { id: 'room-support', label: 'Support Desk', meta: 'Tickets + feedback', x: 4, y: 37, w: 14, h: 12, kind: 'work', theme: 'support', doorX: 18, doorY: 48, hallId: 'hall-west' },
    { id: 'room-design', label: 'Design Loft', meta: 'UI + product polish', x: 24, y: 43, w: 20, h: 14, kind: 'work', theme: 'design', doorX: 34, doorY: 48, hallId: 'hall-center' },
    { id: 'room-ops', label: 'Ops Command', meta: 'Deploy + reliability', x: 48, y: 35, w: 26, h: 17, kind: 'work', theme: 'ops', doorX: 74, doorY: 48, hallId: 'hall-east' },
    { id: 'room-coffee', label: 'Cafeteria', meta: 'Gather + recharge', x: 6, y: 64, w: 36, h: 30, kind: 'break', theme: 'coffee', doorX: 24, doorY: 76, hallId: 'hall-south-west' },
    { id: 'room-break', label: 'Lounge', meta: 'Breaks + team chat', x: 45, y: 66, w: 24, h: 16, kind: 'break', theme: 'break', doorX: 57, doorY: 76, hallId: 'hall-south-mid' },
    { id: 'room-pods', label: 'Focus Pods', meta: 'Task swarms + deep work', x: 76, y: 54, w: 18, h: 12, kind: 'work', theme: 'pods', doorX: 76, doorY: 70, hallId: 'hall-south-east' },
    { id: 'room-lobby', label: 'Main Lobby', meta: 'Free roaming + dispatch', x: 56, y: 6, w: 16, h: 10, kind: 'lobby', theme: 'lobby', doorX: 64, doorY: 24, hallId: 'hall-north-mid' },
];
const OFFICE_MISSION_ROOM_TO_OFFICE_ROOM = Object.freeze({
    inbox: 'room-lobby',
    planning: 'room-planning',
    tools: 'room-engineering',
    files: 'room-engineering',
    review: 'room-support',
    done: 'room-lobby',
});
const OFFICE_HALL_NODES = [
    { id: 'hall-north-west', x: 20, y: 24 },
    { id: 'hall-north-mid', x: 48, y: 24 },
    { id: 'hall-north-east', x: 82, y: 24 },
    { id: 'hall-west', x: 20, y: 48 },
    { id: 'hall-center', x: 48, y: 48 },
    { id: 'hall-east', x: 82, y: 48 },
    { id: 'hall-south-west', x: 24, y: 76 },
    { id: 'hall-south-mid', x: 57, y: 76 },
    { id: 'hall-south-east', x: 82, y: 76 },
];
const OFFICE_HALL_EDGES = [
    ['hall-north-west', 'hall-north-mid'],
    ['hall-north-mid', 'hall-north-east'],
    ['hall-north-west', 'hall-west'],
    ['hall-west', 'hall-center'],
    ['hall-center', 'hall-east'],
    ['hall-north-east', 'hall-east'],
    ['hall-north-mid', 'hall-center'],
    ['hall-north-west', 'hall-center'],
    ['hall-north-east', 'hall-center'],
    ['hall-west', 'hall-south-west'],
    ['hall-center', 'hall-south-mid'],
    ['hall-east', 'hall-south-east'],
    ['hall-south-west', 'hall-south-mid'],
    ['hall-south-mid', 'hall-south-east'],
    ['hall-center', 'hall-south-west'],
    ['hall-center', 'hall-south-east'],
];
const OFFICE_CORRIDORS = [
    { x: 16.2, y: 20.2, w: 70.8, h: 7.8, orientation: 'h' },
    { x: 16.2, y: 44.0, w: 70.8, h: 8.4, orientation: 'h' },
    { x: 21.5, y: 72.0, w: 64.8, h: 8.8, orientation: 'h' },
    { x: 16.2, y: 20.2, w: 7.8, h: 60.8, orientation: 'v' },
    { x: 44.1, y: 20.2, w: 8.2, h: 60.8, orientation: 'v' },
    { x: 78.0, y: 20.2, w: 8.2, h: 60.8, orientation: 'v' },
];
const OFFICE_AMBIENT_DECOR = [
    { type: 'tree', x: 1.8, y: 10.4, w: 5.8, h: 8.8 },
    { type: 'tree', x: 1.8, y: 84.2, w: 5.8, h: 8.8 },
    { type: 'tree', x: 95.4, y: 10.4, w: 5.8, h: 8.8 },
    { type: 'tree', x: 95.4, y: 84.2, w: 5.8, h: 8.8 },
    { type: 'windowstrip', x: 24, y: 4.2, w: 18, h: 2.8 },
    { type: 'windowstrip', x: 46, y: 4.2, w: 18, h: 2.8 },
    { type: 'windowstrip', x: 68, y: 4.2, w: 18, h: 2.8 },
    { type: 'planterrow', x: 40, y: 24.6, w: 18, h: 3.4 },
    { type: 'planterrow', x: 22, y: 70.8, w: 12, h: 3.2 },
    { type: 'planterrow', x: 52, y: 70.8, w: 12, h: 3.2 },
    { type: 'planterrow', x: 78, y: 70.8, w: 10, h: 3.2 },
    { type: 'whiteboard', x: 8.4, y: 34, w: 7.2, h: 2.6 },
    { type: 'whiteboard', x: 62.8, y: 34, w: 7.2, h: 2.6 },
    { type: 'bookshelf', x: 8.6, y: 60.2, w: 8.4, h: 3.4 },
    { type: 'bookshelf', x: 88, y: 34, w: 7.2, h: 3.2 },
    { type: 'meetingtable', x: 30.4, y: 41.2, w: 11.2, h: 3.8 },
    { type: 'kiosk', x: 47.8, y: 66, w: 4, h: 4.6 },
    { type: 'watercooler', x: 18.2, y: 72.2, w: 3.3, h: 5 },
    { type: 'watercooler', x: 57.4, y: 72.2, w: 3.3, h: 5 },
    { type: 'vending', x: 12, y: 67.8, w: 3.8, h: 6 },
    { type: 'vending', x: 67.8, y: 67.8, w: 3.8, h: 6 },
    { type: 'sofa', x: 40.6, y: 72.4, w: 10.6, h: 3.2 },
    { type: 'bench', x: 79.8, y: 78.6, w: 8.8, h: 3.1 },
    { type: 'table', x: 26.4, y: 76, w: 4.8, h: 3.4 },
    { type: 'lamp', x: 64, y: 66.8, w: 2.4, h: 4.9 },
    { type: 'lamp', x: 70.2, y: 66.8, w: 2.4, h: 4.9 },
    { type: 'floor-art', x: 35.2, y: 49.4, w: 7.4, h: 3.4 },
    { type: 'floor-art', x: 49.2, y: 49.4, w: 7.4, h: 3.4 },
    { type: 'lounge-rug', x: 33, y: 61.8, w: 26, h: 17.5 },
];
const OFFICE_DYNAMIC_ROOM_SLOTS = [
    { x: 46, y: 84, w: 9, h: 5 },
    { x: 56, y: 84, w: 9, h: 5 },
    { x: 66, y: 84, w: 9, h: 5 },
    { x: 76, y: 84, w: 9, h: 5 },
    { x: 46, y: 90, w: 9, h: 5 },
    { x: 56, y: 90, w: 9, h: 5 },
    { x: 66, y: 90, w: 9, h: 5 },
    { x: 76, y: 90, w: 9, h: 5 },
    { x: 46, y: 95, w: 9, h: 5 },
    { x: 56, y: 95, w: 9, h: 5 },
    { x: 66, y: 95, w: 9, h: 5 },
    { x: 76, y: 95, w: 9, h: 5 },
];
const OFFICE_TASK_ROOM_RULES = [
    { pattern: /\b(code|coding|bug|fix|refactor|script|api|backend|frontend|test|suite|engineer(?:ing)?)\b/i, roomId: 'room-engineering' },
    { pattern: /\b(content|video|youtube|social|post|edit|thumbnail|brand|marketing)\b/i, roomId: 'room-content' },
    { pattern: /\b(research|compare|competitor|benchmark|analysis|document|docs|investigate)\b/i, roomId: 'room-research' },
    { pattern: /\b(deploy|infra|infrastructure|ops|monitor|reliability|performance|server|hosting)\b/i, roomId: 'room-ops' },
    { pattern: /\b(plan|roadmap|strategy|scope|milestone|timeline)\b/i, roomId: 'room-planning' },
    { pattern: /\b(support|ticket|customer|feedback|help)\b/i, roomId: 'room-support' },
    { pattern: /\b(design|ui|ux|landing|website|visual|brand)\b/i, roomId: 'room-design' },
    { pattern: /\b(focus|deep work|pod|quiet)\b/i, roomId: 'room-pods' },
];
const OFFICE_AGENT_SEEDS = [
    { name: 'Brandon', color: '#9ad8ff', costume: 'visor', tint: 'blue', specialty: 'Software builds', personality: 'Practical, fast, and precise with code tasks.' },
    { name: 'Trey', color: '#9becc9', costume: 'headset', tint: 'green', specialty: 'Research', personality: 'Patient, source-focused, and careful with claims.' },
    { name: 'Zach', color: '#ffd49f', costume: 'cap', tint: 'orange', specialty: 'Game builds', personality: 'Playful, iterative, and tuned for runnable prototypes.' },
    { name: 'Matt', color: '#ffc7eb', costume: 'bowtie', tint: 'pink', specialty: 'Design polish', personality: 'Visual, detail-oriented, and direct about UI tradeoffs.' },
    { name: 'Taylor', color: '#d7c8ff', costume: 'satchel', tint: 'purple', specialty: 'Planning', personality: 'Structured, strategic, and good at breaking work into steps.' },
    { name: 'John', color: '#ffeaa9', costume: 'badge', tint: 'yellow', specialty: 'Support review', personality: 'Calm, user-focused, and good at finding edge cases.' },
    { name: 'Nova', color: '#7df7ff', costume: 'toolbelt', tint: 'blue', specialty: 'Ops automation', personality: 'Steady, reliable, and comfortable with deploy paths.' },
    { name: 'Pixel', color: '#ff9bd2', costume: 'scarf', tint: 'pink', specialty: 'Content systems', personality: 'Concise, organized, and good at repeatable workflows.' },
    { name: 'Byte', color: '#c4ff72', costume: 'tablet', tint: 'green', specialty: 'Data tasks', personality: 'Analytical, skeptical, and careful with transformations.' },
    { name: 'Orbit', color: '#ffa66d', costume: 'wrench', tint: 'orange', specialty: 'Integration', personality: 'Connector-minded and good at tying systems together.' },
    { name: 'Echo', color: '#f6f09d', costume: 'visor', tint: 'yellow', specialty: 'Documentation', personality: 'Clear, complete, and good at preserving context.' },
    { name: 'Glitch', color: '#b497ff', costume: 'mug', tint: 'purple', specialty: 'Debugging', personality: 'Curious, persistent, and good at narrowing failures.' },
];
const OFFICE_AGENT_STYLE_COLOR_POOL = [
    '#9ad8ff',
    '#9becc9',
    '#ffd49f',
    '#ffc7eb',
    '#d7c8ff',
    '#ffeaa9',
    '#9fd9ff',
    '#b2ffc8',
    '#f4c4ff',
    '#ffd0a8',
    '#a7ffe3',
    '#b7d6ff',
    '#ffd8c2',
    '#e4ceff',
    '#c6f4ff',
];
const OFFICE_AGENT_COSTUME_POOL = ['none', 'cap', 'visor', 'headset', 'bowtie', 'toolbelt', 'satchel', 'scarf', 'badge', 'tablet', 'wrench', 'mug'];

// 
