/* ============================================================
   Thomas State Store
   ============================================================
   Minimal reactive pub/sub store. Single source of truth for
   all UI state. Subscribers get called when their key changes.
   ============================================================ */

/** @returns {string} */
function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

const _state = {
  /* Chat management */
  chats: new Map(),        // id -> {id, title, messages[], createdAt, updatedAt, pinned, sessionId}
  activeChatId: null,      // string | null

  /* Models */
  models: {
    profiles: [],          // [{name, provider, base_url, model, context_window, max_tokens}]
    defaultProfile: null,  // string
    discovered: new Map(), // profileName -> [modelId, ...]
    handshakes: new Map(), // profileName -> {ok, status, http_status, url, models, error, checkedAt}
  },
  activeProfile: null,     // string
  activeModelId: '',       // string (override, or '' for profile default)
  mode: 'fast',           // 'fast' | 'auto' | 'thinking' | 'swarm'

  /* Settings */
  settings: {
    theme: 'system',       // 'light' | 'dark' | 'system'
    accentColor: 'teal',   // preset name
    gpuVram: 10,           // GB (default RTX 3080)
    showInspector: false,
    fontSize: 'default',
    preferredProfile: null, // string | null
    preferredModelByProfile: {}, // profileName -> modelId override
    promptLibrary: [],     // [{id, title, text}]
    ttsEnabled: false,
    ttsRate: 1.0,
    ttsVoice: null,        // voiceURI or null
    voiceConversation: false, // hands-free back-and-forth STT<->TTS loop
    voiceAutoSend: true,      // auto-send after speech recognition ends (when voiceConversation is on)
    sidebarWidth: 280,      // px
    inspectorWidth: 380,    // px
    sidebarCollapsed: false,
    showToolDetails: false,
    autonomyLevel: 3,       // 1..4
  },

  /* UI state */
  ui: {
    sidebarOpen: true,     // desktop: always true; mobile: toggle
    inspectorOpen: false,
    inspectorTab: 'run',   // 'run' | 'jobs' | 'trace' | 'tools' | 'memory' | 'artifacts' | 'files'
    streaming: false,
    abortController: null, // AbortController for current stream
    queuedMessages: 0,
    queuedForActiveChat: 0,
    concurrentRuns: 0,
    activeChatRuns: 0,
    commandPaletteOpen: false,
    modelPickerOpen: false,
    settingsOpen: false,
    connected: false,
    selectionMode: false,
    selectedMessageIds: [],
  },

  /* Active run (inspector data) */
  activeRun: null,         // {id, status, steps[], startedAt, tokenEstimate, contextWindow, error} | null

  /* Background job list */
  jobs: [],                // [{id, chatId, status, ...}]

  /* Tools list (from /api/tools) */
  tools: [],               // [{name, category, description}]
};

const _listeners = new Map(); // key -> Set<callback>

/**
 * Get the current state (read-only reference).
 * @returns {typeof _state}
 */
export function getState() {
  return _state;
}

/**
 * Get a nested value using dot notation.
 * @param {string} path - e.g. 'settings.theme' or 'ui.sidebarOpen'
 */
export function get(path) {
  return path.split('.').reduce((o, k) => o?.[k], _state);
}

/**
 * Update state and notify subscribers.
 * @param {string} key - top-level key (e.g. 'activeChatId', 'ui', 'settings')
 * @param {*} value - new value (shallow merge for objects)
 */
export function setState(key, value) {
  const old = _state[key];

  if (typeof old === 'object' && old !== null && !Array.isArray(old) && !(old instanceof Map) && typeof value === 'object' && value !== null) {
    // Shallow merge for plain objects
    _state[key] = { ...old, ...value };
  } else {
    _state[key] = value;
  }

  _notify(key);
}

/**
 * Subscribe to changes on a state key.
 * @param {string} key
 * @param {(state: typeof _state) => void} callback
 * @returns {() => void} unsubscribe function
 */
export function subscribe(key, callback) {
  if (!_listeners.has(key)) {
    _listeners.set(key, new Set());
  }
  _listeners.get(key).add(callback);
  return () => _listeners.get(key)?.delete(callback);
}

/**
 * Subscribe to multiple keys.
 * @param {string[]} keys
 * @param {(state: typeof _state) => void} callback
 * @returns {() => void} unsubscribe function
 */
export function subscribeMany(keys, callback) {
  const unsubs = keys.map(k => subscribe(k, callback));
  return () => unsubs.forEach(fn => fn());
}

function _notify(key) {
  const subs = _listeners.get(key);
  if (subs) {
    for (const cb of subs) {
      try { cb(_state); } catch (e) { console.error('[store] subscriber error:', e); }
    }
  }
  // Also notify wildcard subscribers
  const wildcards = _listeners.get('*');
  if (wildcards) {
    for (const cb of wildcards) {
      try { cb(_state); } catch (e) { console.error('[store] subscriber error:', e); }
    }
  }
}

/* ---- Chat helpers ---- */

export function createChat(title = 'New Chat') {
  const id = generateId();
  const now = Date.now();
  const chat = {
    id,
    title,
    messages: [],
    createdAt: now,
    updatedAt: now,
    pinned: false,
    sessionId: null,
  };
  _state.chats.set(id, chat);
  _state.activeChatId = id;
  _notify('chats');
  _notify('activeChatId');
  return chat;
}

export function getActiveChat() {
  if (!_state.activeChatId) return null;
  return _state.chats.get(_state.activeChatId) || null;
}

export function updateChat(id, updates) {
  const chat = _state.chats.get(id);
  if (!chat) return;
  Object.assign(chat, updates, { updatedAt: Date.now() });
  _notify('chats');
}

export function deleteChat(id) {
  _state.chats.delete(id);
  if (_state.activeChatId === id) {
    // Switch to most recent chat or null
    const sorted = getChatsArray();
    _state.activeChatId = sorted.length > 0 ? sorted[0].id : null;
    _notify('activeChatId');
  }
  _notify('chats');
}

export function setActiveChat(id) {
  if (_state.activeChatId === id) return;
  _state.activeChatId = id;
  _notify('activeChatId');
}

export function addMessage(chatId, message) {
  const chat = _state.chats.get(chatId);
  if (!chat) return;
  chat.messages.push({
    id: generateId(),
    createdAt: Date.now(),
    status: 'complete',
    toolCalls: [],
    ...message,
  });
  chat.updatedAt = Date.now();
  // Auto-title from first user message
  if (chat.title === 'New Chat' && message.role === 'user' && typeof message.content === 'string') {
    chat.title = message.content.slice(0, 50).trim() || 'New Chat';
  }
  _notify('chats');
}

export function getChatsArray() {
  const arr = Array.from(_state.chats.values());
  // Pinned first, then by updatedAt desc
  return arr.sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}

/* ---- Run helpers ---- */

export function startRun() {
  const run = {
    id: generateId(),
    status: 'thinking',
    steps: [],
    startedAt: Date.now(),
    tokenEstimate: 0,
    contextWindow: 0,
    tokenReport: null,
    error: null,
  };
  _state.activeRun = run;
  _notify('activeRun');
  return run;
}

export function addRunStep(step) {
  if (!_state.activeRun) return;
  _state.activeRun.steps.push({ timestamp: Date.now(), ...step });
  _notify('activeRun');
}

export function updateRun(updates) {
  if (!_state.activeRun) return;
  Object.assign(_state.activeRun, updates);
  _notify('activeRun');
}

export function endRun(status = 'done') {
  if (!_state.activeRun) return;
  _state.activeRun.status = status;
  _notify('activeRun');
}

export { generateId };
