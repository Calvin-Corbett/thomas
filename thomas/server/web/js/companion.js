import { attachCompanionRuntime } from "./companion_runtime.js";

const TOKEN_KEY = "thomas.companion.token";
const CHAT_SESSION_KEY = "thomas.infinite.chat.session.v1";
const CHAT_HISTORY_KEY = "thomas.infinite.chat.history.v1";
const CHAT_MODEL_KEY = "thomas.infinite.chat.model.v1";
const COMPANION_DEVICE_KEY = "thomas.infinite.device.v1";
const ACTIVE_PANEL_KEY = "thomas.infinite.panel.v1";

const state = {
  chat: {
    sessionId: "",
    sending: false,
    messages: [],
  },
  model: {
    profile: "",
    modelId: "",
    profiles: [],
    profileModels: new Map(),
  },
  device: {
    id: "",
    platform: "ios",
    distributionChannel: "app_store",
    storefrontRegion: "US",
    appVersion: "1.0.0",
    channel: "stable",
    capabilities: ["storage", "websocket", "push"],
    paired: false,
  },
  apps: {
    loading: false,
    rows: [],
    error: "",
  },
  panel: "chat",
};

const refs = {
  modelSetupBtn: document.getElementById("modelSetupBtn"),
  modelSetupModal: document.getElementById("modelSetupModal"),
  modelSetupBackdrop: document.getElementById("modelSetupBackdrop"),
  closeModelSetupBtn: document.getElementById("closeModelSetupBtn"),
  cancelModelSetupBtn: document.getElementById("cancelModelSetupBtn"),
  applyModelSetupBtn: document.getElementById("applyModelSetupBtn"),
  setupProfileSelector: document.getElementById("setupProfileSelector"),
  setupModelSelector: document.getElementById("setupModelSelector"),
  setupModelMeta: document.getElementById("setupModelMeta"),

  chatThread: document.getElementById("chatThread"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatSendBtn: document.getElementById("chatSendBtn"),
  panelChat: document.getElementById("panelChat"),
  panelApps: document.getElementById("panelApps"),
  panelAdd: document.getElementById("panelAdd"),
  tabChat: document.getElementById("tabChat"),
  tabApps: document.getElementById("tabApps"),
  tabAdd: document.getElementById("tabAdd"),
  appsRefreshBtn: document.getElementById("appsRefreshBtn"),
  appsList: document.getElementById("appsList"),
  appsMeta: document.getElementById("appsMeta"),
  deviceSetupForm: document.getElementById("deviceSetupForm"),
  deviceIdInput: document.getElementById("deviceIdInput"),
  devicePlatformInput: document.getElementById("devicePlatformInput"),
  deviceDistributionInput: document.getElementById("deviceDistributionInput"),
  deviceRegionInput: document.getElementById("deviceRegionInput"),
  deviceAppVersionInput: document.getElementById("deviceAppVersionInput"),
  deviceChannelInput: document.getElementById("deviceChannelInput"),
  deviceCapsInput: document.getElementById("deviceCapsInput"),
  deviceSetupMeta: document.getElementById("deviceSetupMeta"),
};

function asText(value, fallback = "") {
  const text = String(value == null ? "" : value).trim();
  return text || fallback;
}

function makeId(prefix = "id") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}-${window.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
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
    // Ignore storage failures.
  }
}

function captureTokenFromQuery() {
  const url = new URL(window.location.href);
  const token = asText(url.searchParams.get("token"), "");
  if (!token) {
    return;
  }
  persistToken(token);
  url.searchParams.delete("token");
  const query = url.searchParams.toString();
  const next = `${url.pathname}${query ? `?${query}` : ""}${url.hash || ""}`;
  window.history.replaceState({}, "", next);
}

function buildAuthHeaders(extra = {}) {
  const headers = new Headers(extra);
  const token = getStoredToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
    headers.set("X-Api-Token", token);
  }
  return headers;
}

function persistChatState() {
  try {
    localStorage.setItem(CHAT_SESSION_KEY, state.chat.sessionId);
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(state.chat.messages.slice(-160)));
  } catch (_error) {
    // Ignore storage failures.
  }
}

function persistModelState() {
  try {
    localStorage.setItem(
      CHAT_MODEL_KEY,
      JSON.stringify({
        profile: state.model.profile,
        modelId: state.model.modelId,
      }),
    );
  } catch (_error) {
    // Ignore storage failures.
  }
}

function persistActivePanel() {
  try {
    localStorage.setItem(ACTIVE_PANEL_KEY, asText(state.panel, "chat"));
  } catch (_error) {
    // Ignore storage failures.
  }
}

function parseCsv(value) {
  return Array.from(
    new Set(
      String(value || "")
        .split(",")
        .map((part) => asText(part, ""))
        .filter(Boolean),
    ),
  );
}

function persistDeviceState() {
  try {
    localStorage.setItem(
      COMPANION_DEVICE_KEY,
      JSON.stringify({
        id: state.device.id,
        platform: state.device.platform,
        distributionChannel: state.device.distributionChannel,
        storefrontRegion: state.device.storefrontRegion,
        appVersion: state.device.appVersion,
        channel: state.device.channel,
        capabilities: state.device.capabilities,
        paired: Boolean(state.device.paired),
      }),
    );
  } catch (_error) {
    // Ignore storage failures.
  }
}

function hydrateChatState() {
  try {
    const storedSession = asText(localStorage.getItem(CHAT_SESSION_KEY), "");
    state.chat.sessionId = storedSession || makeId("session");
  } catch (_error) {
    state.chat.sessionId = makeId("session");
  }

  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      state.chat.messages = parsed
        .filter((item) => item && typeof item === "object")
        .map((item) => ({
          id: asText(item.id, makeId("msg")),
          role: asText(item.role, "assistant"),
          text: String(item.text || ""),
          error: Boolean(item.error),
        }));
    }
  } catch (_error) {
    state.chat.messages = [];
  }

  if (state.chat.messages.length === 0) {
    state.chat.messages.push({
      id: makeId("msg"),
      role: "system",
      text: "Connected. Send a message to Thomas.",
      error: false,
    });
  }
}

function hydrateModelState() {
  try {
    const raw = localStorage.getItem(CHAT_MODEL_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    state.model.profile = asText(parsed && parsed.profile, "");
    state.model.modelId = asText(parsed && parsed.modelId, "");
  } catch (_error) {
    state.model.profile = "";
    state.model.modelId = "";
  }
}

function hydrateDeviceState() {
  try {
    const raw = localStorage.getItem(COMPANION_DEVICE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const existingId = asText(parsed && parsed.id, "");
    const generated = `phone-${Math.random().toString(36).slice(2, 8)}`;
    state.device.id = existingId || generated;
    state.device.platform = asText(parsed && parsed.platform, "ios");
    state.device.distributionChannel = asText(parsed && parsed.distributionChannel, "app_store");
    state.device.storefrontRegion = asText(parsed && parsed.storefrontRegion, "US");
    state.device.appVersion = asText(parsed && parsed.appVersion, "1.0.0");
    state.device.channel = asText(parsed && parsed.channel, "stable");
    const caps = Array.isArray(parsed && parsed.capabilities) ? parsed.capabilities : [];
    state.device.capabilities = caps
      .map((item) => asText(item, ""))
      .filter(Boolean);
    if (state.device.capabilities.length === 0) {
      state.device.capabilities = ["storage", "websocket", "push"];
    }
    state.device.paired = Boolean(parsed && parsed.paired);
  } catch (_error) {
    state.device.id = `phone-${Math.random().toString(36).slice(2, 8)}`;
  }

  try {
    state.panel = asText(localStorage.getItem(ACTIVE_PANEL_KEY), "chat").toLowerCase();
  } catch (_error) {
    state.panel = "chat";
  }
}

function appendMessage(role, text, { error = false, id = makeId("msg") } = {}) {
  state.chat.messages.push({
    id,
    role,
    text: String(text || ""),
    error: Boolean(error),
  });
  persistChatState();
  return id;
}

function updateMessage(id, updater) {
  const index = state.chat.messages.findIndex((message) => message.id === id);
  if (index < 0) {
    return;
  }
  const current = state.chat.messages[index];
  state.chat.messages[index] = { ...current, ...updater(current) };
  persistChatState();
}

function renderChatThread() {
  if (!refs.chatThread) {
    return;
  }
  refs.chatThread.innerHTML = "";

  state.chat.messages.forEach((message) => {
    const row = document.createElement("div");
    const role = asText(message.role, "assistant");
    row.className = `infinite-message-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "infinite-message-bubble";
    if (message.error) {
      bubble.classList.add("error");
    }
    bubble.textContent = String(message.text || "");
    row.appendChild(bubble);
    refs.chatThread.appendChild(row);
  });

  refs.chatThread.scrollTop = refs.chatThread.scrollHeight;
}

function autoResizeInput() {
  if (!refs.chatInput) {
    return;
  }
  refs.chatInput.style.height = "auto";
  refs.chatInput.style.height = `${Math.min(refs.chatInput.scrollHeight, 180)}px`;
}

function renderComposer() {
  if (!refs.chatSendBtn || !refs.chatInput) {
    return;
  }
  const hasText = Boolean(asText(refs.chatInput.value, ""));
  refs.chatSendBtn.disabled = state.chat.sending || !hasText;
}

function renderModelButton() {
  if (!refs.modelSetupBtn) {
    return;
  }
  const label = asText(state.model.modelId, asText(state.model.profile, "loading..."));
  refs.modelSetupBtn.textContent = label;
}

function renderDeviceSetupForm() {
  if (refs.deviceIdInput) refs.deviceIdInput.value = asText(state.device.id, "");
  if (refs.devicePlatformInput) refs.devicePlatformInput.value = asText(state.device.platform, "ios");
  if (refs.deviceDistributionInput) refs.deviceDistributionInput.value = asText(state.device.distributionChannel, "app_store");
  if (refs.deviceRegionInput) refs.deviceRegionInput.value = asText(state.device.storefrontRegion, "US");
  if (refs.deviceAppVersionInput) refs.deviceAppVersionInput.value = asText(state.device.appVersion, "1.0.0");
  if (refs.deviceChannelInput) refs.deviceChannelInput.value = asText(state.device.channel, "stable");
  if (refs.deviceCapsInput) refs.deviceCapsInput.value = (state.device.capabilities || []).join(", ");
  if (refs.deviceSetupMeta) {
    refs.deviceSetupMeta.textContent = state.device.paired
      ? `Paired as ${asText(state.device.id, "device")} (${asText(state.device.channel, "stable")})`
      : "Device not paired yet.";
  }
}

function renderAppsPanel() {
  if (!refs.appsList) {
    return;
  }
  refs.appsList.innerHTML = "";

  if (refs.appsMeta) {
    if (state.apps.loading) {
      refs.appsMeta.textContent = "Loading app catalog...";
    } else if (state.apps.error) {
      refs.appsMeta.textContent = state.apps.error;
    } else {
      refs.appsMeta.textContent = `${state.apps.rows.length} app(s) available for channel ${asText(state.device.channel, "stable")}.`;
    }
  }

  if (state.apps.loading) {
    const row = document.createElement("div");
    row.className = "companion-app-card";
    row.innerHTML = "<h3>Loading...</h3>";
    refs.appsList.appendChild(row);
    return;
  }

  if (state.apps.rows.length === 0) {
    const row = document.createElement("div");
    row.className = "companion-app-card";
    row.innerHTML = "<h3>No apps yet</h3><div class=\"app-meta\">Publish a companion module, then refresh App Store.</div>";
    refs.appsList.appendChild(row);
    return;
  }

  state.apps.rows.forEach((item) => {
    const moduleId = asText(item && item.module_id, "");
    const displayName = asText(item && item.display_name, moduleId || "module");
    const description = asText(item && item.description, "No description.");
    const release = (item && item.latest_release) || {};
    const compat = (item && item.compatibility) || {};
    const eligible = Boolean(compat && compat.eligible);

    const card = document.createElement("article");
    card.className = "companion-app-card";
    card.dataset.moduleId = moduleId;
    card.innerHTML = `
      <h3>${displayName}</h3>
      <div class="app-meta">${description}</div>
      <div class="app-meta">Module: ${moduleId} | Version: ${asText(release.module_version, "n/a")}</div>
      <div class="app-actions">
        <span class="app-chip ${eligible ? "good" : "bad"}">${eligible ? "Eligible" : "Blocked"}</span>
        <button type="button" class="settings-mini-btn" data-app-push="${moduleId}" ${eligible ? "" : "disabled"}>Push</button>
      </div>
    `;
    refs.appsList.appendChild(card);
  });
}

function render() {
  renderChatThread();
  autoResizeInput();
  renderComposer();
  renderModelButton();
  renderDeviceSetupForm();
  renderAppsPanel();
}

function setActivePanel(panelKey) {
  const nextRaw = asText(panelKey, "chat").toLowerCase();
  const next = ["chat", "apps", "add"].includes(nextRaw) ? nextRaw : "chat";
  state.panel = next;
  persistActivePanel();
  const panelMap = {
    chat: refs.panelChat,
    apps: refs.panelApps,
    add: refs.panelAdd,
  };
  const tabMap = {
    chat: refs.tabChat,
    apps: refs.tabApps,
    add: refs.tabAdd,
  };

  Object.entries(panelMap).forEach(([key, node]) => {
    if (!node) {
      return;
    }
    if (key === next) {
      node.classList.add("active");
    } else {
      node.classList.remove("active");
    }
  });

  Object.entries(tabMap).forEach(([key, node]) => {
    if (!node) {
      return;
    }
    if (key === next) {
      node.classList.add("active");
      node.setAttribute("aria-current", "page");
    } else {
      node.classList.remove("active");
      node.removeAttribute("aria-current");
    }
  });

  if (next === "apps") {
    void loadAppStore();
  }
}

async function requestJson(path, options = {}) {
  const headers = buildAuthHeaders(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(asText(payload && (payload.error || payload.message), `${response.status} ${response.statusText}`));
  }
  return payload;
}

function syncDeviceFromInputs() {
  if (refs.deviceIdInput) state.device.id = asText(refs.deviceIdInput.value, state.device.id);
  if (refs.devicePlatformInput) state.device.platform = asText(refs.devicePlatformInput.value, state.device.platform || "ios");
  if (refs.deviceDistributionInput) state.device.distributionChannel = asText(refs.deviceDistributionInput.value, state.device.distributionChannel || "app_store");
  if (refs.deviceRegionInput) state.device.storefrontRegion = asText(refs.deviceRegionInput.value, state.device.storefrontRegion || "US");
  if (refs.deviceAppVersionInput) state.device.appVersion = asText(refs.deviceAppVersionInput.value, state.device.appVersion || "1.0.0");
  if (refs.deviceChannelInput) state.device.channel = asText(refs.deviceChannelInput.value, state.device.channel || "stable");
  if (refs.deviceCapsInput) {
    const caps = parseCsv(refs.deviceCapsInput.value);
    state.device.capabilities = caps.length > 0 ? caps : ["storage", "websocket", "push"];
  }
}

function appendSystemNotice(text, { error = false } = {}) {
  appendMessage("system", asText(text, ""), { error });
  render();
}

async function registerCurrentDevice() {
  syncDeviceFromInputs();
  const payload = {
    device_id: state.device.id,
    platform: state.device.platform,
    distribution_channel: state.device.distributionChannel,
    storefront_region: state.device.storefrontRegion,
    app_version: state.device.appVersion,
    channel: state.device.channel,
    runtime_capability_set: state.device.capabilities,
    actor: "companion-ui",
  };
  const out = await requestJson("/api/companion/v1/devices/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const paired = (out && out.device) || {};
  state.device.paired = true;
  state.device.id = asText(paired.device_id, state.device.id);
  state.device.channel = asText(paired.channel, state.device.channel);
  state.device.appVersion = asText(paired.app_version, state.device.appVersion);
  persistDeviceState();
  renderDeviceSetupForm();
  appendSystemNotice(`Device paired: ${state.device.id}`);
  return out;
}

function appStoreQuery() {
  const params = new URLSearchParams();
  if (state.device.paired && state.device.id) {
    params.set("device_id", state.device.id);
    params.set("include_ineligible", "0");
  }
  params.set("channel", asText(state.device.channel, "stable"));
  return `/api/companion/v1/app-store?${params.toString()}`;
}

async function loadAppStore() {
  if (!refs.appsList) {
    return;
  }
  state.apps.loading = true;
  state.apps.error = "";
  renderAppsPanel();
  try {
    const payload = await requestJson(appStoreQuery());
    state.apps.rows = Array.isArray(payload && payload.apps) ? payload.apps : [];
    state.apps.error = "";
  } catch (error) {
    state.apps.rows = [];
    state.apps.error = `App catalog unavailable: ${asText(error && error.message, "request failed")}`;
  } finally {
    state.apps.loading = false;
    renderAppsPanel();
  }
}

async function pushModuleToDevice(moduleId) {
  const deviceId = asText(state.device.id, "");
  const targetModule = asText(moduleId, "");
  if (!state.device.paired || !deviceId || !targetModule) {
    appendSystemNotice("Set up device pairing first.", { error: true });
    return;
  }
  const out = await requestJson(
    `/api/companion/v1/devices/${encodeURIComponent(deviceId)}/apps/${encodeURIComponent(targetModule)}/push`,
    {
      method: "POST",
      body: JSON.stringify({
        channel: asText(state.device.channel, "stable"),
        actor: "companion-ui",
        execute: true,
      }),
    },
  );
  const release = (out && out.release) || {};
  appendSystemNotice(
    `Pushed ${targetModule} ${asText(release.module_version, "")} to ${deviceId}. Check updates to apply.`,
  );
  state.device.paired = true;
  persistDeviceState();
  await loadAppStore();
}

async function loadProfiles() {
  const payload = await requestJson("/api/models");
  const profiles = Array.isArray(payload && payload.profiles) ? payload.profiles : [];
  state.model.profiles = profiles;

  const defaultProfile = asText(payload && payload.default, "");
  const availableNames = new Set(profiles.map((item) => asText(item && item.name, "")));
  if (!availableNames.has(state.model.profile)) {
    state.model.profile = defaultProfile || asText(profiles[0] && profiles[0].name, "");
  }
  if (!state.model.modelId) {
    const row = profiles.find((item) => asText(item && item.name, "") === state.model.profile) || {};
    state.model.modelId = asText(row.model, "");
  }
  persistModelState();
}

async function loadProfileModels(profile) {
  const profileName = asText(profile, "");
  if (!profileName) {
    return [];
  }
  if (state.model.profileModels.has(profileName)) {
    return state.model.profileModels.get(profileName) || [];
  }

  let ids = [];
  try {
    const payload = await requestJson(`/api/models/${encodeURIComponent(profileName)}/ids`);
    const rows = Array.isArray(payload && payload.models) ? payload.models : [];
    ids = rows
      .map((item) => asText(item && item.id, ""))
      .filter(Boolean);
  } catch (_error) {
    ids = [];
  }

  if (ids.length === 0) {
    const row = state.model.profiles.find((item) => asText(item && item.name, "") === profileName) || {};
    const fallback = asText(row.model, "");
    if (fallback) {
      ids = [fallback];
    }
  }

  state.model.profileModels.set(profileName, ids);
  return ids;
}

function openModelModal() {
  if (!refs.modelSetupModal || !refs.setupProfileSelector || !refs.setupModelSelector) {
    return;
  }
  refs.setupProfileSelector.innerHTML = "";
  state.model.profiles.forEach((profile) => {
    const option = document.createElement("option");
    option.value = asText(profile.name, "");
    option.textContent = asText(profile.name, "");
    refs.setupProfileSelector.appendChild(option);
  });
  refs.setupProfileSelector.value = state.model.profile;
  refs.modelSetupModal.classList.remove("hidden");
}

function closeModelModal() {
  if (refs.modelSetupModal) {
    refs.modelSetupModal.classList.add("hidden");
  }
}

async function refreshModelSelector(profileName, selectedModelId = "") {
  if (!refs.setupModelSelector) {
    return;
  }
  const ids = await loadProfileModels(profileName);
  refs.setupModelSelector.innerHTML = "";
  ids.forEach((id) => {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = id;
    refs.setupModelSelector.appendChild(option);
  });

  const next = asText(selectedModelId, asText(ids[0], ""));
  if (next) {
    refs.setupModelSelector.value = next;
  }

  const row = state.model.profiles.find((item) => asText(item && item.name, "") === profileName) || {};
  if (refs.setupModelMeta) {
    const provider = asText(row.provider, "");
    refs.setupModelMeta.textContent = provider ? `Provider: ${provider}` : "Select profile and model for this chat session.";
  }
}

function applyRuntimeModel(runtime) {
  const active = runtime && typeof runtime === "object" ? runtime.active || runtime : {};
  const profile = asText(active.profile || active.name, "");
  const model = asText(active.model || active.model_id, "");
  if (profile) {
    state.model.profile = profile;
  }
  if (model) {
    state.model.modelId = model;
  }
  persistModelState();
  renderModelButton();
}

const { bootstrap } = attachCompanionRuntime({
  state,
  refs,
  asText,
  appendMessage,
  updateMessage,
  render,
  renderComposer,
  renderModelButton,
  setActivePanel,
  buildAuthHeaders,
  loadAppStore,
  pushModuleToDevice,
  persistModelState,
  persistDeviceState,
  refreshModelSelector,
  registerCurrentDevice,
  loadProfiles,
  applyRuntimeModel,
  openModelModal,
  closeModelModal,
  appendSystemNotice,
  captureTokenFromQuery,
  hydrateChatState,
  hydrateModelState,
  hydrateDeviceState,
});

bootstrap();
