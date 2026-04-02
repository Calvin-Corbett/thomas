/**
 * Thomas UI - Super Cool & Neat Edition
 * Minimal, clean, vanilla JS to power the thoughtful interface.
 */

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
        label: 'Cloud Jump: Office Bot',
        promptPrefix: '',
        kind: 'game',
    },
    jetpack_joyride: {
        id: 'jetpack_joyride',
        label: 'Jetpack Joyride: Office Bot',
        promptPrefix: '',
        kind: 'game',
    },
    dino_run: {
        id: 'dino_run',
        label: 'Dino Run: Office Bot',
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
let activeModelOverride = '';
let activeChatMode = '';
let autonomyLevelManuallySet = false;
const KNOWN_MODEL_SUGGESTIONS = {
    codex: ['gpt-5.3-codex', 'gpt-5.2-codex', 'gpt-5.1-codex-max', 'gpt-5.2', 'gpt-5.1-codex-mini'],
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
let evolveChatRepliesInFlight = false;
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
const OFFICE_RUNTIME_SCHEMA_VERSION = 1;
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
const OFFICE_DRAFT_MAP_SIZE = 24000;
const OFFICE_DRAFT_MAP_MIN_ZOOM = 0.015;
const OFFICE_DRAFT_MAP_MAX_ZOOM = 2.2;
const OFFICE_DRAFT_MAP_DEFAULT_ZOOM = 0.72;
const OFFICE_DRAFT_MAP_MINOR_GRID = 32;
const OFFICE_DRAFT_MAP_MAJOR_GRID = 160;
const OFFICE_DRAFT_MINIMAP_SIZE = 220;
const OFFICE_DRAFT_LAYOUT_STORAGE_KEY = 'thomas.office.draft.layout.v1';
const OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY = 'thomas.office.draft.autosave.v1';
const OFFICE_DRAFT_UNDO_LIMIT = 48;
const OFFICE_DRAFT_ASSET_SCALE_MIN = 0.8;
const OFFICE_DRAFT_ASSET_SCALE_MAX = 1.4;
const OFFICE_DRAFT_ASSET_SCALE_OPTIONS = Object.freeze([0.8, 1, 1.2, 1.4]);
const OFFICE_DRAFT_ROOM_FLOOR_PALETTES = Object.freeze({
    tan: {
        label: 'Tan',
        shell: 'linear-gradient(180deg, rgba(188, 160, 127, 0.98), rgba(148, 117, 88, 0.98))',
        floor: 'linear-gradient(180deg, rgba(222, 196, 164, 0.96), rgba(180, 146, 111, 0.96))',
        floorBorder: 'rgba(247, 228, 205, 0.18)',
    },
    sand: {
        label: 'Sand',
        shell: 'linear-gradient(180deg, rgba(202, 183, 148, 0.98), rgba(164, 141, 104, 0.98))',
        floor: 'linear-gradient(180deg, rgba(232, 216, 188, 0.96), rgba(195, 170, 132, 0.96))',
        floorBorder: 'rgba(255, 241, 216, 0.18)',
    },
    clay: {
        label: 'Clay',
        shell: 'linear-gradient(180deg, rgba(177, 139, 112, 0.98), rgba(135, 97, 72, 0.98))',
        floor: 'linear-gradient(180deg, rgba(216, 181, 154, 0.95), rgba(176, 134, 105, 0.95))',
        floorBorder: 'rgba(255, 226, 200, 0.16)',
    },
    slate: {
        label: 'Slate',
        shell: 'linear-gradient(180deg, rgba(110, 124, 148, 0.98), rgba(76, 90, 112, 0.98))',
        floor: 'linear-gradient(180deg, rgba(161, 174, 196, 0.96), rgba(121, 136, 159, 0.96))',
        floorBorder: 'rgba(228, 237, 252, 0.15)',
    },
});
const OFFICE_DRAFT_ASSET_LIBRARY = Object.freeze({
    couch: {
        label: 'Couch',
        width: 336,
        height: 188,
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
    { name: 'Brandon', color: '#9ad8ff', costume: 'visor', tint: 'blue' },
    { name: 'Trey', color: '#9becc9', costume: 'headset', tint: 'green' },
    { name: 'Zach', color: '#ffd49f', costume: 'cap', tint: 'orange' },
    { name: 'Matt', color: '#ffc7eb', costume: 'bowtie', tint: 'pink' },
    { name: 'Taylor', color: '#d7c8ff', costume: 'none', tint: 'purple' },
    { name: 'John', color: '#ffeaa9', costume: 'visor', tint: 'yellow' },
    { name: 'Nova', color: '#9ad8ff', costume: 'cap', tint: 'blue' },
    { name: 'Pixel', color: '#9becc9', costume: 'headset', tint: 'green' },
    { name: 'Byte', color: '#f4c4ff', costume: 'bowtie', tint: 'purple' },
    { name: 'Orbit', color: '#9fd9ff', costume: 'none', tint: 'blue' },
    { name: 'Echo', color: '#b2ffc8', costume: 'visor', tint: 'green' },
    { name: 'Glitch', color: '#ffd0a8', costume: 'cap', tint: 'orange' },
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
const OFFICE_AGENT_COSTUME_POOL = ['none', 'cap', 'visor', 'headset', 'bowtie'];

// 
