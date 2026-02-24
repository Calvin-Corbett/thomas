const LOCAL_APPS_KEY = "thomas.infinite.launcher.apps.v1";
const TOKEN_KEY = "thomas.companion.token";
const WS_RETRY_MS = 5000;
const HTTP_POLL_MS = 30000;

const SEED_APPS = [
  {
    id: "portal-inbox",
    name: "Inbox",
    url: "https://example.com/inbox",
    streamUrl: "https://example.com/inbox",
    icon: "I",
    color: "#58a6ff",
    description: "Seed tile",
  },
  {
    id: "portal-jobs",
    name: "Jobs",
    url: "https://example.com/jobs",
    streamUrl: "https://example.com/jobs",
    icon: "J",
    color: "#47d7ac",
    description: "Seed tile",
  },
];

const state = {
  apps: [],
  selectedAppId: "",
  ws: null,
  wsReconnectTimer: null,
  httpPollTimer: null,
  launcherApiAvailable: false,
};

const refs = {
  appGrid: document.getElementById("appGrid"),
  appCount: document.getElementById("appCount"),
  emptyState: document.getElementById("emptyState"),
  stageTitle: document.getElementById("stageTitle"),
  streamFrame: document.getElementById("streamFrame"),
  streamPlaceholder: document.getElementById("streamPlaceholder"),
  launchBtn: document.getElementById("launchBtn"),
  openExternalBtn: document.getElementById("openExternalBtn"),
  deleteBtn: document.getElementById("deleteBtn"),
  appForm: document.getElementById("appForm"),
  appName: document.getElementById("appName"),
  appIcon: document.getElementById("appIcon"),
  appColor: document.getElementById("appColor"),
  appUrl: document.getElementById("appUrl"),
  eventLog: document.getElementById("eventLog"),
  connectionPill: document.getElementById("connectionPill"),
};

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function pushLog(message, level = "info") {
  if (!refs.eventLog) {
    return;
  }
  const entry = document.createElement("div");
  entry.className = `companion-log-entry${level === "info" ? "" : ` ${level}`}`;
  entry.textContent = `${nowLabel()} ${message}`;
  refs.eventLog.prepend(entry);
  while (refs.eventLog.children.length > 60) {
    refs.eventLog.removeChild(refs.eventLog.lastElementChild);
  }
}

function getStoredToken() {
  try {
    return String(localStorage.getItem(TOKEN_KEY) || "").trim();
  } catch (_error) {
    return "";
  }
}

function persistToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch (_error) {
    // Ignore storage failures and continue without persisted auth.
  }
}

function captureTokenFromQuery() {
  const url = new URL(window.location.href);
  const token = String(url.searchParams.get("token") || "").trim();
  if (!token) {
    return;
  }
  persistToken(token);
  url.searchParams.delete("token");
  const query = url.searchParams.toString();
  const next = `${url.pathname}${query ? `?${query}` : ""}${url.hash || ""}`;
  window.history.replaceState({}, "", next);
  pushLog("Stored launcher token from URL query.");
}

function asText(value, fallback = "") {
  const text = String(value == null ? "" : value).trim();
  return text || fallback;
}

function normalizeUrl(rawUrl) {
  const input = asText(rawUrl);
  if (!input) {
    return "";
  }
  if (/^https?:\/\//i.test(input) || input.startsWith("/")) {
    return input;
  }
  if (/^[\w.-]+\.[a-z]{2,}(?:[/:?#]|$)/i.test(input)) {
    return `https://${input}`;
  }
  return input;
}

function normalizeColor(rawColor) {
  const value = asText(rawColor, "#58a6ff");
  if (/^#[0-9a-f]{6}$/i.test(value)) {
    return value;
  }
  return "#58a6ff";
}

function normalizeIcon(rawIcon, fallbackName) {
  const icon = asText(rawIcon);
  if (icon) {
    return icon.slice(0, 2);
  }
  return asText(fallbackName, "A").slice(0, 1).toUpperCase();
}

function slugify(value) {
  return asText(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 48);
}

function createId(name) {
  const root = slugify(name);
  if (root) {
    return root;
  }
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `app-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function normalizeApp(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const name = asText(source.name || source.display_name || source.title || "Untitled App", "Untitled App");
  const id = asText(source.app_id || source.id || source.slug || "", createId(name));
  const url = normalizeUrl(source.url || source.launch_url || source.website_url || source.target_url || "");
  const streamUrl = normalizeUrl(source.stream_url || source.streamUrl || source.target_stream_url || url);
  const icon = normalizeIcon(source.icon || source.emoji || source.glyph, name);
  const color = normalizeColor(source.color || source.tint || source.accent);
  const description = asText(source.description || "");
  const updatedAt = Number(source.updated_at || source.updatedAt || Date.now()) || Date.now();
  return {
    id,
    name,
    url,
    streamUrl,
    icon,
    color,
    description,
    updatedAt,
  };
}

function dedupeApps(rows) {
  const byId = new Map();
  rows.forEach((row) => {
    const app = normalizeApp(row);
    byId.set(app.id, app);
  });
  return Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt);
}

function persistApps() {
  try {
    localStorage.setItem(LOCAL_APPS_KEY, JSON.stringify(state.apps));
  } catch (_error) {
    // Ignore local storage errors and keep runtime state only.
  }
}

function loadLocalApps() {
  try {
    const raw = localStorage.getItem(LOCAL_APPS_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return dedupeApps(parsed);
  } catch (_error) {
    return [];
  }
}

function hydrateLocalApps() {
  const localApps = loadLocalApps();
  state.apps = localApps.length > 0 ? localApps : dedupeApps(SEED_APPS);
  if (!localApps.length) {
    persistApps();
  }
  state.selectedAppId = state.apps[0] ? state.apps[0].id : "";
}

function applySnapshot(rows) {
  state.apps = dedupeApps(rows);
  if (!state.apps.some((app) => app.id === state.selectedAppId)) {
    state.selectedAppId = state.apps[0] ? state.apps[0].id : "";
  }
  persistApps();
  render();
}

function upsertApp(rawApp) {
  const app = normalizeApp(rawApp);
  const next = state.apps.filter((item) => item.id !== app.id);
  next.unshift(app);
  state.apps = dedupeApps(next);
  state.selectedAppId = app.id;
  persistApps();
  render();
}

function removeAppById(appId) {
  state.apps = state.apps.filter((app) => app.id !== appId);
  if (!state.apps.some((app) => app.id === state.selectedAppId)) {
    state.selectedAppId = state.apps[0] ? state.apps[0].id : "";
  }
  persistApps();
  render();
}

function setConnection(mode, text) {
  if (!refs.connectionPill) {
    return;
  }
  refs.connectionPill.classList.remove("status-live", "status-partial", "status-planned");
  if (mode === "ws") {
    refs.connectionPill.classList.add("status-live");
    refs.connectionPill.textContent = text || "WebSocket live";
    return;
  }
  if (mode === "http") {
    refs.connectionPill.classList.add("status-partial");
    refs.connectionPill.textContent = text || "HTTP sync";
    return;
  }
  refs.connectionPill.classList.add("status-planned");
  refs.connectionPill.textContent = text || "Local mode";
}

function selectedApp() {
  return state.apps.find((app) => app.id === state.selectedAppId) || null;
}

function setStageTitle(text) {
  if (!refs.stageTitle) {
    return;
  }
  refs.stageTitle.textContent = text;
}

function setStreamLive(live) {
  const streamShell = refs.streamFrame ? refs.streamFrame.closest(".companion-stream-shell") : null;
  if (!streamShell) {
    return;
  }
  streamShell.classList.toggle("is-live", live);
}

function renderTiles() {
  if (!refs.appGrid || !refs.appCount || !refs.emptyState) {
    return;
  }

  refs.appGrid.innerHTML = "";
  refs.appCount.textContent = `${state.apps.length} ${state.apps.length === 1 ? "app" : "apps"}`;
  refs.emptyState.classList.toggle("hidden", state.apps.length > 0);

  state.apps.forEach((app) => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "companion-app-tile";
    tile.dataset.appId = app.id;
    tile.style.setProperty("--tile-color", app.color);
    if (app.id === state.selectedAppId) {
      tile.classList.add("active");
    }

    const icon = document.createElement("span");
    icon.className = "companion-app-icon";
    icon.textContent = app.icon;

    const name = document.createElement("span");
    name.className = "companion-app-name";
    name.textContent = app.name;

    tile.append(icon, name);
    tile.addEventListener("click", () => {
      state.selectedAppId = app.id;
      render();
    });
    tile.addEventListener("dblclick", () => {
      state.selectedAppId = app.id;
      render();
      launchSelected({ notifyServer: true });
    });
    refs.appGrid.appendChild(tile);
  });
}

function renderActions() {
  const app = selectedApp();
  const hasApp = Boolean(app);
  if (refs.launchBtn) {
    refs.launchBtn.disabled = !hasApp;
  }
  if (refs.openExternalBtn) {
    refs.openExternalBtn.disabled = !hasApp;
  }
  if (refs.deleteBtn) {
    refs.deleteBtn.disabled = !hasApp;
  }
  if (!hasApp) {
    setStageTitle("Launch Surface");
    return;
  }
  setStageTitle(`Launch Surface • ${app.name}`);
}

function render() {
  renderTiles();
  renderActions();
}

function buildWebSocketUrl(pathname) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}${pathname}`);
  const token = getStoredToken();
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

async function requestJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
    headers.set("X-Api-Token", token);
  }
  const response = await fetch(path, { ...options, headers });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    const message = asText(payload && (payload.error || payload.message), `${response.status} ${response.statusText}`);
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function fetchLauncherApps() {
  try {
    const payload = await requestJson("/api/companion/v1/launcher/apps");
    const rows = Array.isArray(payload && payload.apps) ? payload.apps : [];
    applySnapshot(rows);
    state.launcherApiAvailable = true;
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      setConnection("ws", "WebSocket live");
    } else {
      setConnection("http", "HTTP sync");
    }
    return true;
  } catch (error) {
    state.launcherApiAvailable = false;
    setConnection("local", "Local mode");
    return false;
  }
}

function clearWsReconnect() {
  if (state.wsReconnectTimer) {
    window.clearTimeout(state.wsReconnectTimer);
    state.wsReconnectTimer = null;
  }
}

function scheduleWsReconnect() {
  clearWsReconnect();
  state.wsReconnectTimer = window.setTimeout(() => {
    connectWebSocket();
  }, WS_RETRY_MS);
}

function handleLauncherEvent(raw) {
  let packet;
  try {
    packet = JSON.parse(raw);
  } catch (_error) {
    return;
  }
  const type = asText(packet.type || packet.event || packet.op);
  const payload = packet.payload || packet.data || packet;

  if (type === "ready") {
    pushLog("WebSocket channel ready.");
    return;
  }

  if (type === "apps.snapshot") {
    const rows = Array.isArray(payload && payload.apps) ? payload.apps : [];
    applySnapshot(rows);
    pushLog(`Snapshot synced (${rows.length} apps).`);
    return;
  }

  if (type === "apps.upsert") {
    const row = payload && (payload.app || payload);
    if (row && typeof row === "object") {
      upsertApp(row);
      pushLog(`Tile updated: ${asText(row.name || row.display_name || row.id, "app")}.`);
    }
    return;
  }

  if (type === "apps.delete") {
    const appId = asText(payload && (payload.app_id || payload.id));
    if (appId) {
      removeAppById(appId);
      pushLog(`Tile deleted: ${appId}.`, "warn");
    }
    return;
  }

  if (type === "apps.launch") {
    const appId = asText(payload && (payload.app_id || payload.id));
    if (appId) {
      state.selectedAppId = appId;
      render();
      launchSelected({ notifyServer: false });
      pushLog(`Launch signal received for ${appId}.`);
    }
  }
}

function closeWebSocket() {
  if (!state.ws) {
    return;
  }
  try {
    state.ws.close();
  } catch (_error) {
    // Ignore close failures.
  }
  state.ws = null;
}

function connectWebSocket() {
  if (!state.launcherApiAvailable || typeof WebSocket === "undefined") {
    return;
  }
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  let ws;
  try {
    ws = new WebSocket(buildWebSocketUrl("/api/companion/v1/launcher/ws"));
  } catch (_error) {
    scheduleWsReconnect();
    return;
  }

  state.ws = ws;
  ws.onopen = () => {
    clearWsReconnect();
    setConnection("ws", "WebSocket live");
    pushLog("Live launcher sync connected.");
  };
  ws.onmessage = (event) => {
    handleLauncherEvent(event.data);
  };
  ws.onerror = () => {
    setConnection("http", "Realtime unstable");
  };
  ws.onclose = () => {
    if (state.ws === ws) {
      state.ws = null;
    }
    if (state.launcherApiAvailable) {
      setConnection("http", "Reconnecting live sync");
      scheduleWsReconnect();
    }
  };
}

function startHttpPolling() {
  if (state.httpPollTimer) {
    window.clearInterval(state.httpPollTimer);
  }
  state.httpPollTimer = window.setInterval(async () => {
    const ok = await fetchLauncherApps();
    if (ok) {
      connectWebSocket();
    }
  }, HTTP_POLL_MS);
}

async function notifyLaunch(app) {
  if (!state.launcherApiAvailable || !app) {
    return;
  }
  try {
    await requestJson(`/api/companion/v1/launcher/apps/${encodeURIComponent(app.id)}/launch`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  } catch (_error) {
    // Best-effort only.
  }
}

function launchSelected({ notifyServer = false } = {}) {
  const app = selectedApp();
  if (!app) {
    return;
  }
  const url = asText(app.streamUrl || app.url);
  if (!url) {
    pushLog(`App "${app.name}" is missing a launch URL.`, "error");
    return;
  }
  if (refs.streamFrame) {
    refs.streamFrame.src = url;
    setStreamLive(true);
  }
  if (notifyServer) {
    notifyLaunch(app);
  }
  pushLog(`Launching "${app.name}" on Thomas.`);
}

function openSelectedExternally() {
  const app = selectedApp();
  if (!app) {
    return;
  }
  const url = asText(app.streamUrl || app.url);
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

async function deleteSelected() {
  const app = selectedApp();
  if (!app) {
    return;
  }
  if (!window.confirm(`Delete "${app.name}" from this homescreen?`)) {
    return;
  }

  if (state.launcherApiAvailable) {
    try {
      await requestJson(`/api/companion/v1/launcher/apps/${encodeURIComponent(app.id)}`, { method: "DELETE" });
      pushLog(`Deleted "${app.name}" from launcher.`);
    } catch (_error) {
      pushLog(`Could not delete "${app.name}" on launcher API, removed locally.`, "warn");
    }
  } else {
    pushLog(`Deleted "${app.name}" locally.`, "warn");
  }

  removeAppById(app.id);
}

async function saveFromForm(event) {
  event.preventDefault();
  const name = asText(refs.appName && refs.appName.value, "");
  const url = normalizeUrl(refs.appUrl && refs.appUrl.value);
  if (!name || !url) {
    pushLog("Name and URL are required.", "error");
    return;
  }

  const draft = normalizeApp({
    id: createId(name),
    name,
    icon: asText(refs.appIcon && refs.appIcon.value, ""),
    color: asText(refs.appColor && refs.appColor.value, "#58a6ff"),
    url,
    stream_url: url,
    updated_at: Date.now(),
  });

  if (state.launcherApiAvailable) {
    try {
      const payload = await requestJson("/api/companion/v1/launcher/apps", {
        method: "POST",
        body: JSON.stringify({
          app_id: draft.id,
          name: draft.name,
          icon: draft.icon,
          color: draft.color,
          url: draft.url,
          stream_url: draft.streamUrl,
        }),
      });
      const serverApp = payload && (payload.app || payload);
      if (serverApp && typeof serverApp === "object") {
        upsertApp(serverApp);
      } else {
        upsertApp(draft);
      }
      pushLog(`Saved "${draft.name}" to launcher API.`);
    } catch (_error) {
      upsertApp(draft);
      pushLog(`Launcher API unavailable. Saved "${draft.name}" locally.`, "warn");
    }
  } else {
    upsertApp(draft);
    pushLog(`Saved "${draft.name}" locally.`);
  }

  if (refs.appForm) {
    refs.appForm.reset();
  }
  if (refs.appColor) {
    refs.appColor.value = "#58a6ff";
  }
}

function wireUi() {
  if (refs.launchBtn) {
    refs.launchBtn.addEventListener("click", () => launchSelected({ notifyServer: true }));
  }
  if (refs.openExternalBtn) {
    refs.openExternalBtn.addEventListener("click", openSelectedExternally);
  }
  if (refs.deleteBtn) {
    refs.deleteBtn.addEventListener("click", deleteSelected);
  }
  if (refs.appForm) {
    refs.appForm.addEventListener("submit", saveFromForm);
  }
}

async function bootstrap() {
  captureTokenFromQuery();
  hydrateLocalApps();
  render();
  pushLog("Companion UI ready.");

  const launcherOk = await fetchLauncherApps();
  if (launcherOk) {
    pushLog("Launcher API detected.");
    connectWebSocket();
  } else {
    pushLog("Launcher API not detected, running local cache mode.", "warn");
  }

  startHttpPolling();
}

function init() {
  wireUi();
  bootstrap();

  window.addEventListener("beforeunload", () => {
    closeWebSocket();
    clearWsReconnect();
    if (state.httpPollTimer) {
      window.clearInterval(state.httpPollTimer);
      state.httpPollTimer = null;
    }
  });
}

init();
