/** Shared utilities, provider labels, chat state, and game constants. */

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

