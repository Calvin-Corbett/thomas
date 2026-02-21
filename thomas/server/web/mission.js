
const SERVER_TOKEN_STORAGE_KEY = "thomas.serverApiToken";
const AGENT_ALIAS_STORAGE_KEY = "thomas.mission.agentAliases.v1";
const MISSION_VIEW_STORAGE_KEY = "thomas.mission.savedViews.v1";
const ALERT_ROUTING_STORAGE_KEY = "thomas.mission.alertRouting.v1";

const ROOM_ORDER = ["inbox", "planning", "tools", "files", "review", "done"];
const MAX_VISIBLE_PER_ROOM = 8;
const CARD_WIDTH = 196;
const CARD_HEIGHT = 74;
const SLOT_GAP_X = 10;
const SLOT_GAP_Y = 8;
const POLL_INTERVAL_MS = 2200;
const OFFICE_MAX_VISIBLE_PER_ROOM = 12;
const OFFICE_SLOT_X = 56;
const OFFICE_SLOT_Y = 44;
const MAX_ACTIVITY_LINES = 220;
const ACTIVE_STATUSES = new Set(["running", "queued", "awaiting_approval", "blocked", "active"]);
const ATTENTION_STATUSES = new Set(["blocked", "failed", "cancelled", "dead", "error", "awaiting_approval"]);
const ALERT_NOTIFY_COOLDOWN_MS = 5 * 60 * 1000;
const SYSTEM_VIEW_PRESETS = {
  all: { label: "All Agents", filters: { status: "all", room: "all", query: "" } },
  active: { label: "Active Only", filters: { status: "active", room: "all", query: "" } },
  attention: { label: "Needs Attention", filters: { status: "attention", room: "all", query: "" } },
};

const CODENAMES = [
  "Jeff Gordon", "Ava Stone", "Milo Park", "Tess Monroe", "Rex Dalton", "Noah Reed", "Kira Lane", "Vera Quinn",
  "Cole Mercer", "Nina Hayes", "Zane Cross", "Lena Frost", "Ivy Morgan", "Finn Adler", "Luca Shaw", "Jade Ellis",
  "Maya Brooks", "Owen Pike", "Rina Knox", "Theo Gray", "June Carter", "Rafe Collins", "Skye Nolan", "Kai Turner",
  "Elise Hart", "Roman Vale", "Nora Wells", "Axel Price", "Liam Fox", "Tara Stone", "Seth Miller", "Riley James",
];

const state = {
  payload: null,
  selectedAgentId: "",
  cards: new Map(),
  officeAgents: new Map(),
  refreshing: false,
  intervalId: null,
  streamAbort: null,
  streamReconnectId: null,
  streamGeneration: 0,
  motionFrame: null,
  aliases: loadAliasMap(),
  officeVisible: false,
  showIdleAgents: false,
  activityOpen: false,
  activityAgentId: "",
  activityReplayByRun: new Map(),
  activityReplayAbort: null,
  timelineReplayAbort: null,
  replayRequestedByRun: new Set(),
  missionFilters: { status: "all", room: "all", query: "" },
  savedViews: loadMissionViews(),
  selectedViewPreset: "all",
  alerts: [],
  approvals: { autonomy: [], guardrails: [], pending_total: 0 },
  topology: { nodes: [], edges: [], timeline: [] },
  topologySourceFilter: "all",
  approvalSourceFilter: "all",
  alertRouting: loadAlertRouting(),
  alertNotifyCooldown: new Map(),
  notifyingAlert: false,
  benchmarkRuns: [],
  benchmarkJobs: [],
  benchmarkPacks: [],
  benchmarkDefaultPack: "",
  selectedBenchmarkPack: "",
  benchmarkProfiles: [],
  benchmarkDefaultProfile: "",
  selectedBenchmarkProfile: "",
  benchmarkRefreshBusy: false,
  benchmarkStatusError: false,
  benchmarkIntervalId: null,
};

const elSync = document.getElementById("syncStatus");
const elEventFeed = document.getElementById("eventFeed");
const elAgentLayer = document.getElementById("agentLayer");
const elWorkspaceGrid = document.getElementById("workspaceGrid");
const elRefresh = document.getElementById("refreshBtn");
const elOpenOffice = document.getElementById("openOfficeBtn");
const elCloseOffice = document.getElementById("closeOfficeBtn");
const elToggleIdle = document.getElementById("toggleIdleBtn");
const elOfficeWrap = document.getElementById("officeWrap");
const elOfficeMap = document.getElementById("officeMap");
const elOfficeAgentLayer = document.getElementById("officeAgentLayer");

const elStatAgents = document.getElementById("statAgents");
const elStatActive = document.getElementById("statActive");
const elStatEvents = document.getElementById("statEvents");
const elStatUpdated = document.getElementById("statUpdated");
const elViewStatusFilter = document.getElementById("viewStatusFilter");
const elViewRoomFilter = document.getElementById("viewRoomFilter");
const elViewSearchInput = document.getElementById("viewSearchInput");
const elClearFiltersBtn = document.getElementById("clearFiltersBtn");
const elSavedViewSelect = document.getElementById("savedViewSelect");
const elSaveViewBtn = document.getElementById("saveViewBtn");
const elDeleteViewBtn = document.getElementById("deleteViewBtn");
const elFocusLiveList = document.getElementById("focusLiveList");
const elFocusAttentionList = document.getElementById("focusAttentionList");
const elAlertList = document.getElementById("alertList");
const elTopologySourceFilter = document.getElementById("topologySourceFilter");
const elTopologyRefreshBtn = document.getElementById("topologyRefreshBtn");
const elTopologyNodesCount = document.getElementById("topologyNodesCount");
const elTopologyEdgesCount = document.getElementById("topologyEdgesCount");
const elTopologyTimelineList = document.getElementById("topologyTimelineList");
const elApprovalSourceFilter = document.getElementById("approvalSourceFilter");
const elApprovalRefreshBtn = document.getElementById("approvalRefreshBtn");
const elApprovalQueueList = document.getElementById("approvalQueueList");
const elAlertNotifyDesktop = document.getElementById("alertNotifyDesktop");
const elAlertNotifyWebhook = document.getElementById("alertNotifyWebhook");
const elAlertNotifyEmail = document.getElementById("alertNotifyEmail");
const elAlertNotifyNowBtn = document.getElementById("alertNotifyNowBtn");
const elAlertNotifyStatus = document.getElementById("alertNotifyStatus");

const elDetailWrap = document.getElementById("agentDetail");
const elDetailEmpty = document.getElementById("agentDetailEmpty");
const elDetailName = document.getElementById("detailName");
const elDetailMeta = document.getElementById("detailMeta");
const elDetailStatus = document.getElementById("detailStatus");
const elDetailSummary = document.getElementById("detailSummary");
const elDetailActions = document.getElementById("detailActions");
const elDetailJson = document.getElementById("detailJson");

const elActivityModal = document.getElementById("activityModal");
const elActivityBackdrop = document.getElementById("activityBackdrop");
const elActivityClose = document.getElementById("activityCloseBtn");
const elActivityRefresh = document.getElementById("activityRefreshBtn");
const elActivityTitle = document.getElementById("activityTitle");
const elActivityMeta = document.getElementById("activityMeta");
const elActivityLog = document.getElementById("activityLog");
const elReplayTimelineLog = document.getElementById("replayTimelineLog");
const elReplayRefreshBtn = document.getElementById("replayRefreshBtn");
const elReplayToolsOnly = document.getElementById("replayToolsOnly");
const elRunBenchmark = document.getElementById("runBenchmarkBtn");
const elRefreshBench = document.getElementById("refreshBenchBtn");
const elBenchStatus = document.getElementById("benchStatus");
const elBenchPackSelect = document.getElementById("benchPackSelect");
const elBenchProfileSelect = document.getElementById("benchProfileSelect");
const elBenchModeSelect = document.getElementById("benchModeSelect");
const elBenchEconomySelect = document.getElementById("benchEconomySelect");
const elBenchPackMeta = document.getElementById("benchPackMeta");
const elBenchPackSummary = document.getElementById("benchPackSummary");
const elBenchTaskList = document.getElementById("benchTaskList");
const elBenchRunsList = document.getElementById("benchRunsList");
const elBenchJobsList = document.getElementById("benchJobsList");

function readToken() {
  try {
    return String(window.localStorage.getItem(SERVER_TOKEN_STORAGE_KEY) || "").trim();
  } catch {
    return "";
  }
}

function withAuth(opts = {}) {
  const headers = new Headers(opts.headers || {});
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...opts, headers };
}

async function apiJson(url, opts = {}) {
  const res = await fetch(url, withAuth(opts));
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  return res.json();
}

async function apiPost(url, body = {}) {
  return apiJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function loadAliasMap() {
  try {
    const raw = window.localStorage.getItem(AGENT_ALIAS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch {
    // noop
  }
  return {};
}

function saveAliasMap() {
  try {
    window.localStorage.setItem(AGENT_ALIAS_STORAGE_KEY, JSON.stringify(state.aliases || {}));
  } catch {
    // noop
  }
}

function loadMissionViews() {
  try {
    const raw = window.localStorage.getItem(MISSION_VIEW_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out = {};
    for (const [k, v] of Object.entries(parsed)) {
      const key = String(k || "").trim();
      if (!key || !v || typeof v !== "object" || Array.isArray(v)) continue;
      const label = String(v.label || key).trim() || key;
      const filters = v.filters && typeof v.filters === "object" ? v.filters : {};
      out[key] = {
        label,
        filters: {
          status: String(filters.status || "all").trim().toLowerCase() || "all",
          room: String(filters.room || "all").trim().toLowerCase() || "all",
          query: String(filters.query || "").trim(),
        },
      };
    }
    return out;
  } catch {
    return {};
  }
}

function saveMissionViews() {
  try {
    window.localStorage.setItem(MISSION_VIEW_STORAGE_KEY, JSON.stringify(state.savedViews || {}));
  } catch {
    // noop
  }
}

function loadAlertRouting() {
  const fallback = { desktop: true, webhook_url: "", email_to: "" };
  try {
    const raw = window.localStorage.getItem(ALERT_ROUTING_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fallback;
    return {
      desktop: parsed.desktop !== false,
      webhook_url: String(parsed.webhook_url || "").trim(),
      email_to: String(parsed.email_to || "").trim(),
    };
  } catch {
    return fallback;
  }
}

function saveAlertRouting() {
  try {
    const row = state.alertRouting || {};
    const payload = {
      desktop: row.desktop !== false,
      webhook_url: String(row.webhook_url || "").trim(),
      email_to: String(row.email_to || "").trim(),
    };
    window.localStorage.setItem(ALERT_ROUTING_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // noop
  }
}

function syncAlertRoutingInputs() {
  const row = state.alertRouting || {};
  if (elAlertNotifyDesktop) elAlertNotifyDesktop.checked = row.desktop !== false;
  if (elAlertNotifyWebhook) elAlertNotifyWebhook.value = String(row.webhook_url || "");
  if (elAlertNotifyEmail) elAlertNotifyEmail.value = String(row.email_to || "");
}

function captureAlertRoutingInputs() {
  const prev = state.alertRouting || {};
  state.alertRouting = {
    desktop: elAlertNotifyDesktop ? !!elAlertNotifyDesktop.checked : prev.desktop !== false,
    webhook_url: elAlertNotifyWebhook ? String(elAlertNotifyWebhook.value || "").trim() : String(prev.webhook_url || "").trim(),
    email_to: elAlertNotifyEmail ? String(elAlertNotifyEmail.value || "").trim() : String(prev.email_to || "").trim(),
  };
}

function hashInt(text) {
  let h = 2166136261;
  const value = String(text || "");
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function fmtTime(isoText) {
  const text = String(isoText || "").trim();
  if (!text) return "--";
  try {
    return new Date(text).toLocaleTimeString();
  } catch {
    return text;
  }
}

function safeOpaqueId(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (!/^[A-Za-z0-9._:-]+$/.test(text)) return "";
  return text;
}
function setSync(text, isError = false) {
  if (!elSync) return;
  elSync.textContent = text;
  elSync.classList.toggle("error", !!isError);
}

function fmtDateTime(isoText) {
  const text = String(isoText || "").trim();
  if (!text) return "--";
  try {
    return new Date(text).toLocaleString();
  } catch {
    return text;
  }
}

function _tsOf(value) {
  const text = String(value || "").trim();
  if (!text) return 0;
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeFilterStatus(value) {
  const v = String(value || "all").trim().toLowerCase();
  if (!v) return "all";
  return v;
}

function normalizeFilterRoom(value) {
  const v = String(value || "all").trim().toLowerCase();
  if (!v) return "all";
  if (v === "all") return "all";
  return ROOM_ORDER.includes(v) ? v : "all";
}

function normalizeMissionFilters(filters = {}) {
  return {
    status: normalizeFilterStatus(filters.status),
    room: normalizeFilterRoom(filters.room),
    query: String(filters.query || "").trim(),
  };
}

function hasActiveFilters() {
  const f = state.missionFilters || {};
  return String(f.status || "all") !== "all" || String(f.room || "all") !== "all" || !!String(f.query || "").trim();
}

function isDoneStatus(status) {
  const st = String(status || "").trim().toLowerCase();
  return ["succeeded", "completed", "done"].includes(st);
}

function matchesStatusFilter(agent, statusFilter) {
  const wanted = normalizeFilterStatus(statusFilter);
  const st = String(agent?.status || "").trim().toLowerCase();
  if (wanted === "all") return true;
  if (wanted === "active") return isActiveAgent(agent);
  if (wanted === "attention") return ATTENTION_STATUSES.has(st);
  if (wanted === "done") return isDoneStatus(st);
  return st === wanted;
}

function matchesRoomFilter(agent, roomFilter) {
  const wanted = normalizeFilterRoom(roomFilter);
  if (wanted === "all") return true;
  return String(agent?.room || "").trim().toLowerCase() === wanted;
}

function matchesQueryFilter(agent, queryText) {
  const q = String(queryText || "").trim().toLowerCase();
  if (!q) return true;
  const hay = [
    String(agent?.id || ""),
    String(agent?.name || ""),
    String(agent?.summary || ""),
    String(agent?.run_id || ""),
    String(agent?.profile || ""),
    String(agent?.model_id || ""),
    String(agent?.status || ""),
    String(agent?.room || ""),
    String(agent?.job_kind || ""),
  ].join(" ").toLowerCase();
  return hay.includes(q);
}

function applyAgentFilters(agentsInput) {
  const all = Array.isArray(agentsInput) ? agentsInput : [];
  const f = normalizeMissionFilters(state.missionFilters || {});
  return all.filter((agent) => (
    matchesStatusFilter(agent, f.status)
    && matchesRoomFilter(agent, f.room)
    && matchesQueryFilter(agent, f.query)
  ));
}

function visibleAgentsForVisuals(agentsInput) {
  const all = Array.isArray(agentsInput) ? agentsInput : [];
  if (state.showIdleAgents) return all;

  const selectedId = String(state.selectedAgentId || "");
  const filtered = all.filter((a) => isActiveAgent(a) || String(a?.id || "") === selectedId);
  if (filtered.length) return filtered;
  return all.slice(0, 6);
}

function syncFilterInputs() {
  const f = normalizeMissionFilters(state.missionFilters || {});
  if (elViewStatusFilter) elViewStatusFilter.value = f.status;
  if (elViewRoomFilter) elViewRoomFilter.value = f.room;
  if (elViewSearchInput) elViewSearchInput.value = f.query;
}

function systemPresetIds() {
  return Object.keys(SYSTEM_VIEW_PRESETS);
}

function isSystemPresetId(presetId) {
  return systemPresetIds().includes(String(presetId || ""));
}

function resolvePresetById(presetId) {
  const id = String(presetId || "").trim();
  if (!id) return null;
  if (SYSTEM_VIEW_PRESETS[id]) return SYSTEM_VIEW_PRESETS[id];
  return state.savedViews?.[id] || null;
}

function renderViewPresets() {
  if (!elSavedViewSelect) return;
  const previous = String(state.selectedViewPreset || "");
  elSavedViewSelect.innerHTML = "";

  for (const [id, row] of Object.entries(SYSTEM_VIEW_PRESETS)) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = row.label;
    elSavedViewSelect.appendChild(opt);
  }

  const saved = state.savedViews && typeof state.savedViews === "object" ? state.savedViews : {};
  const keys = Object.keys(saved).sort((a, b) => String(saved[a]?.label || a).localeCompare(String(saved[b]?.label || b)));
  if (keys.length) {
    for (const id of keys) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = String(saved[id]?.label || id);
      elSavedViewSelect.appendChild(opt);
    }
  }

  const customOpt = document.createElement("option");
  customOpt.value = "__custom__";
  customOpt.textContent = "Custom (unsaved)";
  elSavedViewSelect.appendChild(customOpt);

  if (resolvePresetById(previous)) {
    elSavedViewSelect.value = previous;
    state.selectedViewPreset = previous;
  } else {
    elSavedViewSelect.value = "__custom__";
    state.selectedViewPreset = "__custom__";
  }
}

function applyMissionFilters(nextFilters, options = {}) {
  state.missionFilters = normalizeMissionFilters(nextFilters);
  if (options.presetId) {
    state.selectedViewPreset = String(options.presetId);
  } else {
    state.selectedViewPreset = "__custom__";
  }
  syncFilterInputs();
  if (elSavedViewSelect) elSavedViewSelect.value = state.selectedViewPreset;
  rerenderFromState();
}

function commitFilterInputs() {
  applyMissionFilters(
    {
      status: String(elViewStatusFilter?.value || state.missionFilters.status || "all"),
      room: String(elViewRoomFilter?.value || state.missionFilters.room || "all"),
      query: String(elViewSearchInput?.value || state.missionFilters.query || ""),
    },
    { presetId: null },
  );
}

function applyViewPreset(presetId) {
  const row = resolvePresetById(presetId);
  if (!row) return;
  applyMissionFilters(row.filters || {}, { presetId });
}

function saveCurrentViewPreset() {
  const label = window.prompt("Name for this mission view preset:", "My View");
  if (label === null) return;
  const clean = String(label || "").trim().replace(/\s+/g, " ");
  if (!clean) return;
  const baseId = clean.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `view-${Date.now()}`;
  let id = baseId;
  let n = 2;
  while (SYSTEM_VIEW_PRESETS[id] || (state.savedViews && Object.prototype.hasOwnProperty.call(state.savedViews, id))) {
    id = `${baseId}-${n}`;
    n += 1;
  }
  state.savedViews[id] = {
    label: clean,
    filters: normalizeMissionFilters(state.missionFilters || {}),
  };
  saveMissionViews();
  renderViewPresets();
  applyViewPreset(id);
}

function deleteSelectedViewPreset() {
  const id = String(state.selectedViewPreset || "").trim();
  if (!id || isSystemPresetId(id) || id === "__custom__") return;
  if (!state.savedViews || !Object.prototype.hasOwnProperty.call(state.savedViews, id)) return;
  const ok = window.confirm(`Delete view preset "${String(state.savedViews[id]?.label || id)}"?`);
  if (!ok) return;
  delete state.savedViews[id];
  saveMissionViews();
  renderViewPresets();
  applyViewPreset("all");
}

function setBenchStatus(text, isError = false) {
  if (!elBenchStatus) return;
  elBenchStatus.textContent = String(text || "idle");
  elBenchStatus.classList.toggle("error", !!isError);
}

function asNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function benchStatusClass(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["pass", "partial", "fail", "unknown"].includes(normalized)) return normalized;
  return "unknown";
}

function formatTaskResult(successCount, total) {
  const ok = Math.max(0, Math.trunc(asNumber(successCount, 0)));
  const all = Math.max(0, Math.trunc(asNumber(total, 0)));
  if (all <= 0) return "tests: n/a";
  return `${ok}/${all} tests passed`;
}

function formatSecondsCompact(value) {
  const n = asNumber(value, 0);
  if (!Number.isFinite(n) || n <= 0) return "--";
  if (n >= 60) return `${(n / 60).toFixed(1)}m`;
  return `${n.toFixed(1)}s`;
}

function benchmarkPackByKey(key) {
  const wanted = String(key || "").trim().toLowerCase();
  const packs = Array.isArray(state.benchmarkPacks) ? state.benchmarkPacks : [];
  return packs.find((row) => String(row?.key || "").trim().toLowerCase() === wanted) || null;
}

function ensureSelectedBenchmarkPack() {
  const packs = Array.isArray(state.benchmarkPacks) ? state.benchmarkPacks : [];
  if (!packs.length) {
    state.selectedBenchmarkPack = "";
    return "";
  }
  const existing = benchmarkPackByKey(state.selectedBenchmarkPack);
  if (existing) return String(existing.key || "");

  const fallback = benchmarkPackByKey(state.benchmarkDefaultPack) || packs[0];
  state.selectedBenchmarkPack = String(fallback?.key || "");
  return state.selectedBenchmarkPack;
}

function benchmarkProfileByName(name) {
  const wanted = String(name || "").trim();
  const profiles = Array.isArray(state.benchmarkProfiles) ? state.benchmarkProfiles : [];
  return profiles.find((row) => String(row?.name || "").trim() === wanted) || null;
}

function ensureSelectedBenchmarkProfile() {
  const profiles = Array.isArray(state.benchmarkProfiles) ? state.benchmarkProfiles : [];
  if (!profiles.length) {
    state.selectedBenchmarkProfile = "";
    return "";
  }
  const existing = benchmarkProfileByName(state.selectedBenchmarkProfile);
  if (existing) return String(existing?.name || "");

  const preferred = benchmarkProfileByName(state.benchmarkDefaultProfile);
  const fallback = preferred || profiles[0];
  state.selectedBenchmarkProfile = String(fallback?.name || "");
  return state.selectedBenchmarkProfile;
}

function renderBenchmarkProfileSelector() {
  if (!elBenchProfileSelect) return;
  const profiles = Array.isArray(state.benchmarkProfiles) ? state.benchmarkProfiles : [];
  elBenchProfileSelect.innerHTML = "";
  if (!profiles.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No profiles found";
    elBenchProfileSelect.appendChild(opt);
    elBenchProfileSelect.disabled = true;
    state.selectedBenchmarkProfile = "";
    return;
  }

  const selectedName = ensureSelectedBenchmarkProfile();
  for (const profile of profiles) {
    const name = String(profile?.name || "").trim();
    if (!name) continue;
    const provider = String(profile?.provider || "").trim();
    const model = String(profile?.model || "").trim();
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = `${name} (${provider || "provider"}${model ? `:${model}` : ""})`;
    elBenchProfileSelect.appendChild(opt);
  }
  elBenchProfileSelect.disabled = false;
  if (selectedName) {
    elBenchProfileSelect.value = selectedName;
  }
}

function renderBenchmarkPackSelector() {
  if (!elBenchPackSelect) return;
  const packs = Array.isArray(state.benchmarkPacks) ? state.benchmarkPacks : [];
  elBenchPackSelect.innerHTML = "";
  if (!packs.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No test suites found";
    elBenchPackSelect.appendChild(opt);
    elBenchPackSelect.disabled = true;
    state.selectedBenchmarkPack = "";
    return;
  }

  const selectedKey = ensureSelectedBenchmarkPack();
  for (const pack of packs) {
    const key = String(pack?.key || "").trim();
    if (!key) continue;
    const taskCount = Math.max(0, Math.trunc(asNumber(pack?.task_count, 0)));
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = `${String(pack?.name || key)} (${taskCount} task${taskCount === 1 ? "" : "s"})`;
    elBenchPackSelect.appendChild(opt);
  }
  elBenchPackSelect.disabled = false;
  if (selectedKey) {
    elBenchPackSelect.value = selectedKey;
  }
}

function renderSelectedBenchmarkPack() {
  const pack = benchmarkPackByKey(ensureSelectedBenchmarkPack());
  if (!pack) {
    if (elBenchPackMeta) elBenchPackMeta.textContent = "no suites available";
    if (elBenchPackSummary) elBenchPackSummary.textContent = "Add a task pack under demo/task_pack.agentic*.json";
    if (elBenchTaskList) elBenchTaskList.innerHTML = '<div class="empty">No tasks loaded.</div>';
    return;
  }

  const taskCount = Math.max(0, Math.trunc(asNumber(pack?.task_count, 0)));
  const budget = Math.max(0, Math.trunc(asNumber(pack?.duration_budget_seconds, 0)));
  const budgetText = budget > 0 ? `${Math.ceil(budget / 60)} min budget` : "no time budget";
  if (elBenchPackMeta) {
    elBenchPackMeta.textContent = `${taskCount} task${taskCount === 1 ? "" : "s"} | ${budgetText}`;
  }
  if (elBenchPackSummary) {
    const desc = String(pack?.description || "").trim();
    const protocol = Array.isArray(pack?.protocol) ? pack.protocol.filter(Boolean) : [];
    if (desc && protocol.length) {
      elBenchPackSummary.textContent = `${desc} Protocol: ${protocol.join(" | ")}`;
    } else if (desc) {
      elBenchPackSummary.textContent = desc;
    } else if (protocol.length) {
      elBenchPackSummary.textContent = `Protocol: ${protocol.join(" | ")}`;
    } else {
      elBenchPackSummary.textContent = "No description provided.";
    }
  }
  if (!elBenchTaskList) return;

  const tasks = Array.isArray(pack?.tasks) ? pack.tasks : [];
  elBenchTaskList.innerHTML = "";
  if (!tasks.length) {
    elBenchTaskList.innerHTML = '<div class="empty">This suite has no tasks.</div>';
    return;
  }
  for (const task of tasks) {
    const item = document.createElement("div");
    item.className = "bench-task-item";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = String(task?.title || task?.id || "task");
    const meta = document.createElement("span");
    meta.className = "meta";
    const taskId = String(task?.id || "").trim();
    const budgetS = Math.max(0, Math.trunc(asNumber(task?.time_budget_seconds, 0)));
    const criteria = String(task?.success_criteria || "").trim();
    const idPart = taskId ? `id=${taskId}` : "id=--";
    const budgetPart = budgetS > 0 ? `budget=${budgetS}s` : "budget=--";
    const criteriaPart = criteria ? `goal=${criteria}` : "";
    meta.textContent = [idPart, budgetPart, criteriaPart].filter(Boolean).join(" | ");
    item.appendChild(title);
    item.appendChild(meta);
    elBenchTaskList.appendChild(item);
  }
}

function renderBenchmarkRuns() {
  if (!elBenchRunsList) return;
  elBenchRunsList.innerHTML = "";
  const runs = Array.isArray(state.benchmarkRuns) ? state.benchmarkRuns : [];
  if (!runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No benchmark runs found.";
    elBenchRunsList.appendChild(empty);
    return;
  }

  for (const run of runs) {
    const runId = String(run?.run_id || "");
    const pack = run?.task_pack && typeof run.task_pack === "object" ? run.task_pack : {};
    const runOptions = run?.run_options && typeof run.run_options === "object" ? run.run_options : {};
    const topMetrics = run?.top_metrics && typeof run.top_metrics === "object" ? run.top_metrics : {};
    const tasksTotal = Math.max(
      0,
      Math.trunc(
        asNumber(topMetrics?.tasks_total, asNumber(pack?.task_count, 0)),
      ),
    );
    const successCount = Math.max(0, Math.trunc(asNumber(topMetrics?.success_count, 0)));
    const scoreValue = asNumber(run?.top_weighted_score, NaN);
    const scoreText = Number.isFinite(scoreValue) ? scoreValue.toFixed(1) : "--";
    const elapsedText = formatSecondsCompact(topMetrics?.avg_elapsed_seconds);
    const statusText = benchStatusClass(run?.status || "unknown");
    const passText = formatTaskResult(successCount, tasksTotal);
    const packName = String(pack?.name || pack?.id || "").trim() || "benchmark run";
    const profile = String(runOptions?.profile || "").trim();
    const mode = String(runOptions?.thomas_mode || "").trim();
    const economy = String(runOptions?.token_economy || "").trim();

    const item = document.createElement("article");
    item.className = "bench-item";

    const head = document.createElement("div");
    head.className = "bench-item-head";
    const name = document.createElement("strong");
    name.textContent = packName;
    const when = document.createElement("div");
    when.style.display = "inline-flex";
    when.style.alignItems = "center";
    when.style.gap = "6px";
    const whenText = document.createElement("span");
    whenText.textContent = fmtDateTime(run?.created_at);
    const pill = document.createElement("span");
    pill.className = `bench-result-pill ${statusText}`;
    pill.textContent = statusText;
    when.appendChild(whenText);
    when.appendChild(pill);
    head.appendChild(name);
    head.appendChild(when);

    const meta = document.createElement("div");
    meta.className = "bench-item-meta";
    const topCompetitor = String(run?.top_competitor || "").trim() || "--";
    const competitors = Array.isArray(run?.competitors) ? run.competitors.map((x) => String(x || "")).filter(Boolean) : [];
    const delta = Number(run?.before_after?.metrics?.weighted_score_delta);
    const deltaText = Number.isFinite(delta) ? delta.toFixed(3) : "n/a";
    const modeText = mode ? `mode=${mode}` : "";
    const economyText = economy ? `economy=${economy}` : "";
    meta.textContent = [
      `run=${runId || "--"}`,
      passText,
      `score=${scoreText}/100`,
      `avg_time=${elapsedText}`,
      `top=${topCompetitor}`,
      profile ? `model=${profile}` : "",
      modeText,
      economyText,
      `delta=${deltaText}`,
      `tracks=${competitors.join(", ") || "--"}`,
    ].filter(Boolean).join(" | ");

    const actions = document.createElement("div");
    actions.className = "bench-item-actions";
    const artifacts = run?.artifacts && typeof run.artifacts === "object" ? run.artifacts : {};
    for (const key of ["report.md", "scorecard.json", "before_after.delta.json"]) {
      const url = String(artifacts[key] || "");
      if (!url) continue;
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = key === "report.md" ? "Report" : key === "scorecard.json" ? "Scorecard" : "Delta";
      actions.appendChild(a);
    }

    item.appendChild(head);
    item.appendChild(meta);
    if (actions.childNodes.length) item.appendChild(actions);
    elBenchRunsList.appendChild(item);
  }
}

async function cancelBenchmarkJob(jobId) {
  const id = String(jobId || "").trim();
  if (!id) return;
  try {
    await apiPost(`/api/mission/benchmarks/jobs/${encodeURIComponent(id)}/cancel`, {});
    await refreshBenchmarks();
  } catch (e) {
    setBenchStatus(String(e?.message || e), true);
  }
}

function renderBenchmarkJobs() {
  if (!elBenchJobsList) return;
  elBenchJobsList.innerHTML = "";
  const jobs = Array.isArray(state.benchmarkJobs) ? state.benchmarkJobs : [];
  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No benchmark jobs queued.";
    elBenchJobsList.appendChild(empty);
    return;
  }

  for (const job of jobs) {
    const jobId = String(job?.id || "");
    const status = String(job?.status || "unknown");
    const item = document.createElement("article");
    item.className = "bench-item";

    const head = document.createElement("div");
    head.className = "bench-item-head";
    const name = document.createElement("strong");
    name.textContent = jobId || "job";
    const st = document.createElement("span");
    st.textContent = status;
    head.appendChild(name);
    head.appendChild(st);

    const meta = document.createElement("div");
    meta.className = "bench-item-meta";
    const runId = String(job?.run_id || "").trim();
    const exitCode = job?.exit_code;
    const options = job?.options && typeof job.options === "object" ? job.options : {};
    const packName = String(options?.task_pack_name || options?.task_pack_key || "").trim();
    const profile = String(options?.profile || "").trim();
    const mode = String(options?.thomas_mode || "").trim();
    const economy = String(options?.token_economy || "").trim();
    meta.textContent = [
      `created=${fmtDateTime(job?.created_at)}`,
      `run=${runId || "--"}`,
      `pack=${packName || "--"}`,
      profile ? `model=${profile}` : "",
      mode ? `mode=${mode}` : "",
      economy ? `economy=${economy}` : "",
      `exit=${exitCode === null || exitCode === undefined ? "--" : String(exitCode)}`,
    ].filter(Boolean).join(" | ");

    const actions = document.createElement("div");
    actions.className = "bench-item-actions";
    if (["queued", "running", "cancel_requested"].includes(status)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Cancel";
      btn.addEventListener("click", () => cancelBenchmarkJob(jobId));
      actions.appendChild(btn);
    }
    const runDir = String(job?.run_dir || "").trim();
    if (runId) {
      const a = document.createElement("a");
      a.href = `/api/mission/benchmarks/runs/${encodeURIComponent(runId)}/artifact/report.md`;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = "Report";
      actions.appendChild(a);
    } else if (runDir) {
      const hint = document.createElement("span");
      hint.textContent = "Run completed; refresh runs";
      actions.appendChild(hint);
    }

    item.appendChild(head);
    item.appendChild(meta);
    if (actions.childNodes.length) item.appendChild(actions);
    elBenchJobsList.appendChild(item);
  }
}

async function refreshBenchmarks() {
  if (state.benchmarkRefreshBusy) return;
  state.benchmarkRefreshBusy = true;
  setBenchStatus("syncing");
  try {
    const [packsPayload, runsPayload, jobsPayload, modelsPayload] = await Promise.all([
      apiJson("/api/mission/benchmarks/packs"),
      apiJson("/api/mission/benchmarks/runs?limit=40"),
      apiJson("/api/mission/benchmarks/jobs"),
      apiJson("/api/models"),
    ]);
    state.benchmarkPacks = Array.isArray(packsPayload?.packs) ? packsPayload.packs : [];
    state.benchmarkDefaultPack = String(packsPayload?.default_pack || "").trim().toLowerCase();
    state.benchmarkProfiles = Array.isArray(modelsPayload?.profiles) ? modelsPayload.profiles : [];
    state.benchmarkDefaultProfile = String(modelsPayload?.default || "").trim();
    ensureSelectedBenchmarkPack();
    ensureSelectedBenchmarkProfile();
    renderBenchmarkPackSelector();
    renderBenchmarkProfileSelector();
    renderSelectedBenchmarkPack();
    state.benchmarkRuns = Array.isArray(runsPayload?.runs) ? runsPayload.runs : [];
    state.benchmarkJobs = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
    renderBenchmarkRuns();
    renderBenchmarkJobs();
    const packKey = String(state.selectedBenchmarkPack || state.benchmarkDefaultPack || "").trim();
    const profileName = String(state.selectedBenchmarkProfile || state.benchmarkDefaultProfile || "").trim();
    setBenchStatus(
      `pack ${packKey || "--"} | model ${profileName || "--"} | runs ${state.benchmarkRuns.length} | jobs ${state.benchmarkJobs.length}`,
    );
  } catch (e) {
    state.benchmarkStatusError = true;
    setBenchStatus(String(e?.message || e), true);
  } finally {
    state.benchmarkRefreshBusy = false;
  }
}

async function startBenchmarkRun() {
  if (elRunBenchmark) elRunBenchmark.disabled = true;
  setBenchStatus("starting benchmark");
  try {
    const selectedPack = ensureSelectedBenchmarkPack();
    const selectedProfile = ensureSelectedBenchmarkProfile();
    const selectedMode = String(elBenchModeSelect?.value || "fast").trim().toLowerCase();
    const selectedEconomy = String(elBenchEconomySelect?.value || "optimal").trim().toLowerCase();
    if (!selectedPack) {
      throw new Error("No benchmark test suite available.");
    }
    if (!selectedProfile) {
      throw new Error("No model profile available for benchmark.");
    }
    const payload = {
      task_pack: selectedPack,
      profile: selectedProfile,
      include_baseline: false,
      thomas_mode: selectedMode || "fast",
      token_economy: selectedEconomy || "optimal",
      runner: "embedded",
    };
    const res = await apiPost("/api/mission/benchmarks/run", payload);
    const jobId = String(res?.job?.id || "").trim();
    setBenchStatus(
      jobId
        ? `queued ${jobId} (${selectedPack}, ${selectedProfile})`
        : `queued (${selectedPack}, ${selectedProfile})`,
    );
    await refreshBenchmarks();
  } catch (e) {
    setBenchStatus(String(e?.message || e), true);
  } finally {
    if (elRunBenchmark) elRunBenchmark.disabled = false;
  }
}

function shortName(text, max = 16) {
  const t = String(text || "").trim();
  if (!t) return "agent";
  return t.length > max ? `${t.slice(0, max - 1)}...` : t;
}

function statusClass(status) {
  return String(status || "").trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
}

function officeMood(status) {
  const st = String(status || "").trim().toLowerCase();
  if (["running", "active"].includes(st)) return "active";
  if (["queued", "awaiting_approval", "blocked", "pending"].includes(st)) return "waiting";
  if (["failed", "cancelled", "dead", "error"].includes(st)) return "error";
  if (["succeeded", "completed", "done"].includes(st)) return "done";
  return "waiting";
}

function roomCounts(agents) {
  const out = {};
  for (const r of ROOM_ORDER) out[r] = 0;
  for (const a of agents || []) {
    const room = String(a?.room || "");
    if (!Object.prototype.hasOwnProperty.call(out, room)) out[room] = 0;
    out[room] += 1;
  }
  return out;
}
function agentIdentityKey(agent) {
  const source = String(agent?.source || "unknown").trim();
  if (source === "chat_run") {
    const profile = String(agent?.profile || "default").trim() || "default";
    const model = String(agent?.model_id || "default").trim() || "default";
    const mode = String(agent?.mode || "auto").trim() || "auto";
    return `run:${profile}:${model}:${mode}`;
  }
  if (source === "autonomy_job") {
    const kind = String(agent?.job_kind || agent?.name || "job").trim() || "job";
    return `job:${kind.toLowerCase()}`;
  }
  if (source === "autonomy_objective") {
    const root = String(agent?.root_job_id || "").trim();
    if (root) return `objective:${root}`;
    const title = String(agent?.name || "objective").trim() || "objective";
    return `objective:${title.toLowerCase()}`;
  }
  return `${source}:${String(agent?.kind || "agent").trim().toLowerCase()}`;
}

function normalizeAlias(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function uniqueAliasForKey(key, proposed) {
  const base = normalizeAlias(proposed);
  if (!base) return "";

  const used = new Set();
  for (const [k, v] of Object.entries(state.aliases || {})) {
    if (String(k) === String(key)) continue;
    const vv = normalizeAlias(v);
    if (vv) used.add(vv.toLowerCase());
  }

  let candidate = base;
  let n = 2;
  while (used.has(candidate.toLowerCase())) {
    candidate = `${base} ${n}`;
    n += 1;
  }
  return candidate;
}

function ensureAlias(agent) {
  const key = agentIdentityKey(agent);
  const existing = normalizeAlias(state.aliases?.[key] || "");
  if (existing) {
    const uniqExisting = uniqueAliasForKey(key, existing);
    if (uniqExisting !== existing) {
      state.aliases[key] = uniqExisting;
      saveAliasMap();
      return uniqExisting;
    }
    return existing;
  }
  const generated = uniqueAliasForKey(key, CODENAMES[hashInt(key) % CODENAMES.length]);
  state.aliases[key] = generated || "Agent";
  saveAliasMap();
  return state.aliases[key];
}

function clearAlias(agent) {
  const key = agentIdentityKey(agent);
  if (state.aliases && Object.prototype.hasOwnProperty.call(state.aliases, key)) {
    delete state.aliases[key];
    saveAliasMap();
  }
}

function modelRef(agent) {
  const profile = String(agent?.profile || "").trim();
  const model = String(agent?.model_id || "").trim();
  const source = String(agent?.source || "").trim();
  const key = profile || model ? `${profile}:${model}` : `${source}:${String(agent?.kind || "agent")}`;
  const search = `${profile} ${model}`.toLowerCase();

  let icon = "AG";
  if (search.includes("grok") || profile.toLowerCase().includes("xai")) icon = "X";
  else if (search.includes("gpt") || profile.toLowerCase().includes("openai")) icon = "O";
  else if (search.includes("claude") || profile.toLowerCase().includes("anthropic")) icon = "A";
  else if (search.includes("gemini") || profile.toLowerCase().includes("google")) icon = "G";
  else if (search.includes("qwen")) icon = "Q";
  else if (search.includes("llama") || search.includes("ollama") || profile.toLowerCase().includes("local")) icon = "L";
  else if (profile) icon = profile.slice(0, 2).toUpperCase();

  const hue = hashInt(key || "agent") % 360;
  const color = `hsl(${hue} 74% 56%)`;
  const label = profile && model ? `${profile} / ${model}` : profile || model || source || "agent";
  return { key, icon, color, label: shortName(label, 34) };
}

function displayName(agent) {
  return shortName(ensureAlias(agent), 24);
}

function avatarInitials(agent) {
  const alias = ensureAlias(agent);
  const parts = alias.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
  return alias.slice(0, 2).toUpperCase();
}

function getAgents() {
  return Array.isArray(state.payload?.agents) ? state.payload.agents : [];
}

function isActiveAgent(agent) {
  const st = String(agent?.status || "").trim().toLowerCase();
  return ACTIVE_STATUSES.has(st);
}

function updateIdleToggleUI() {
  if (!elToggleIdle) return;
  elToggleIdle.classList.add("toggle-idle-btn");
  elToggleIdle.classList.toggle("active", state.showIdleAgents);
  elToggleIdle.textContent = state.showIdleAgents ? "Hide Idle" : "Show Idle";
}

function findAgentById(agentId) {
  const target = String(agentId || "").trim();
  if (!target) return null;
  return getAgents().find((a) => String(a?.id || "") === target) || null;
}

function selectAgent(agentId, options = {}) {
  const target = String(agentId || "").trim();
  if (!target) return;
  state.selectedAgentId = target;
  renderSelection();
  renderDetail();
  refreshReplayTimeline({ refreshReplay: false });
  if (options.openActivity) {
    const agent = findAgentById(target);
    if (agent) openActivity(agent, { refreshReplay: true });
  }
}

function applyPayload(payload, source = "poll") {
  state.payload = payload;
  renderStats(payload);
  renderFocus(payload);
  renderAlerts(payload);
  renderTopology(payload);
  renderApprovalQueue(payload);
  maybeDispatchAlertNotifications();
  renderEvents(payload);
  renderWorkspace(payload);
  renderOffice(payload);
  renderDetail();
  refreshReplayTimeline({ refreshReplay: false });
  if (state.activityOpen) refreshActivity({ refreshReplay: false });

  const stamp = fmtTime(payload?.generated_at);
  setSync(source === "stream" ? `live ${stamp}` : `synced ${stamp}`);
}

function renderStats(payload) {
  const totals = payload?.totals || {};
  const allAgents = Array.isArray(payload?.agents) ? payload.agents : [];
  const filteredAgents = applyAgentFilters(allAgents);
  const totalAgents = Number(totals.agents || allAgents.length || 0);
  if (elStatAgents) {
    elStatAgents.textContent = hasActiveFilters() ? `${filteredAgents.length}/${totalAgents}` : String(totalAgents);
  }
  if (elStatActive) elStatActive.textContent = String(totals.active_agents || 0);
  if (elStatEvents) elStatEvents.textContent = String(totals.events || 0);
  if (elStatUpdated) elStatUpdated.textContent = fmtTime(payload?.generated_at || "");
}

function renderFocusItem(agent) {
  const item = document.createElement("article");
  item.className = "focus-item";
  const status = String(agent?.status || "unknown").trim().toLowerCase();
  const summary = String(agent?.summary || "").trim() || "No summary";
  const room = String(agent?.room || "planning").trim();

  const head = document.createElement("div");
  head.className = "focus-item-head";
  const name = document.createElement("strong");
  name.textContent = displayName(agent);
  const badge = document.createElement("span");
  badge.className = `focus-badge ${statusClass(status)}`;
  badge.textContent = status || "unknown";
  head.appendChild(name);
  head.appendChild(badge);

  const meta = document.createElement("div");
  meta.className = "focus-item-meta";
  meta.textContent = `room=${room} | ${summary}`;

  item.appendChild(head);
  item.appendChild(meta);
  item.addEventListener("click", () => selectAgent(String(agent?.id || ""), { openActivity: false }));
  return item;
}

function renderFocus(payload) {
  const allAgents = Array.isArray(payload?.agents) ? payload.agents : [];
  const agents = applyAgentFilters(allAgents);
  if (elFocusLiveList) {
    elFocusLiveList.innerHTML = "";
    const live = agents
      .filter((a) => isActiveAgent(a))
      .sort((a, b) => _tsOf(b?.updated_at) - _tsOf(a?.updated_at))
      .slice(0, 8);
    if (!live.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No active agents right now.";
      elFocusLiveList.appendChild(empty);
    } else {
      for (const agent of live) elFocusLiveList.appendChild(renderFocusItem(agent));
    }
  }

  if (elFocusAttentionList) {
    elFocusAttentionList.innerHTML = "";
    const attention = agents
      .filter((a) => ATTENTION_STATUSES.has(String(a?.status || "").trim().toLowerCase()))
      .sort((a, b) => _tsOf(b?.updated_at) - _tsOf(a?.updated_at))
      .slice(0, 8);
    if (!attention.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Nothing blocked or failed.";
      elFocusAttentionList.appendChild(empty);
    } else {
      for (const agent of attention) elFocusAttentionList.appendChild(renderFocusItem(agent));
    }
  }
}

function computeAlerts(payload) {
  const agents = Array.isArray(payload?.agents) ? payload.agents : [];
  const out = [];
  const now = Date.now();
  const blocked = agents.filter((a) => String(a?.status || "").trim().toLowerCase() === "blocked");
  const failed = agents.filter((a) => ["failed", "error", "dead"].includes(String(a?.status || "").trim().toLowerCase()));
  const approvals = agents.filter((a) => String(a?.status || "").trim().toLowerCase() === "awaiting_approval");
  const stale = agents.filter((a) => {
    if (!isActiveAgent(a)) return false;
    const ageMs = Math.max(0, now - _tsOf(a?.updated_at));
    return ageMs > 15 * 60 * 1000;
  });

  if (blocked.length) {
    out.push({
      severity: "high",
      title: `${blocked.length} blocked agent${blocked.length === 1 ? "" : "s"}`,
      detail: blocked.slice(0, 3).map((a) => displayName(a)).join(", "),
      agentId: String(blocked[0]?.id || ""),
    });
  }
  if (failed.length) {
    out.push({
      severity: "high",
      title: `${failed.length} failed/errored agent${failed.length === 1 ? "" : "s"}`,
      detail: failed.slice(0, 3).map((a) => displayName(a)).join(", "),
      agentId: String(failed[0]?.id || ""),
    });
  }
  if (approvals.length) {
    out.push({
      severity: "medium",
      title: `${approvals.length} awaiting approval`,
      detail: approvals.slice(0, 3).map((a) => displayName(a)).join(", "),
      agentId: String(approvals[0]?.id || ""),
    });
  }
  if (stale.length) {
    out.push({
      severity: "medium",
      title: `${stale.length} stale active agent${stale.length === 1 ? "" : "s"}`,
      detail: "No updates for more than 15 minutes.",
      agentId: String(stale[0]?.id || ""),
    });
  }
  if (!out.length) {
    out.push({
      severity: "ok",
      title: "No active alerts",
      detail: "Mission looks healthy.",
      agentId: "",
    });
  }
  return out;
}

function renderAlerts(payload) {
  if (!elAlertList) return;
  const alerts = computeAlerts(payload);
  state.alerts = alerts;
  elAlertList.innerHTML = "";
  for (const alert of alerts) {
    const item = document.createElement("article");
    item.className = `alert-item ${statusClass(alert?.severity || "ok")}`;
    const head = document.createElement("div");
    head.className = "alert-item-head";
    const title = document.createElement("strong");
    title.textContent = String(alert?.title || "alert");
    const sev = document.createElement("span");
    sev.className = `alert-severity ${statusClass(alert?.severity || "ok")}`;
    sev.textContent = String(alert?.severity || "ok");
    head.appendChild(title);
    head.appendChild(sev);

    const meta = document.createElement("div");
    meta.className = "alert-item-meta";
    meta.textContent = String(alert?.detail || "");

    item.appendChild(head);
    item.appendChild(meta);
    const aid = String(alert?.agentId || "");
    if (aid) {
      item.classList.add("clickable");
      item.addEventListener("click", () => selectAgent(aid, { openActivity: false }));
    }
    elAlertList.appendChild(item);
  }
}

function setAlertNotifyStatus(text, isError = false) {
  if (!elAlertNotifyStatus) return;
  elAlertNotifyStatus.textContent = String(text || "");
  elAlertNotifyStatus.classList.toggle("error", !!isError);
}

function alertSignature(row) {
  return [
    String(row?.severity || ""),
    String(row?.title || ""),
    String(row?.detail || ""),
  ].join("|");
}

function collectHighAlerts() {
  const rows = Array.isArray(state.alerts) ? state.alerts : [];
  return rows.filter((row) => String(row?.severity || "").trim().toLowerCase() === "high");
}

function nextNotifiableAlerts(rows) {
  const now = Date.now();
  const out = [];
  for (const row of rows || []) {
    const sig = alertSignature(row);
    const last = Number(state.alertNotifyCooldown.get(sig) || 0);
    if (!last || (now - last) >= ALERT_NOTIFY_COOLDOWN_MS) {
      out.push(row);
      state.alertNotifyCooldown.set(sig, now);
    }
  }
  return out;
}

function routeChannelsPayload() {
  const row = state.alertRouting || {};
  return {
    webhook_url: String(row.webhook_url || "").trim(),
    email_to: String(row.email_to || "").trim(),
  };
}

async function sendAlertNotifications(alertRows, options = {}) {
  const rows = Array.isArray(alertRows) ? alertRows : [];
  if (!rows.length) return;
  const channels = routeChannelsPayload();
  const hasRemoteChannels = !!(channels.webhook_url || channels.email_to);
  const autoMode = !!options.auto;

  if (state.notifyingAlert) return;
  state.notifyingAlert = true;
  try {
    const desktopEnabled = state.alertRouting?.desktop !== false;
    if (desktopEnabled && typeof window.Notification !== "undefined") {
      let permission = String(window.Notification.permission || "");
      if (permission === "default" && !autoMode) {
        try {
          permission = await window.Notification.requestPermission();
        } catch {
          permission = String(window.Notification.permission || "");
        }
      }
      if (permission === "granted") {
        for (const row of rows.slice(0, 3)) {
          // Browser-local notifications for consumer-friendly alerting.
          new window.Notification(String(row?.title || "Thomas Alert"), {
            body: String(row?.detail || ""),
          });
        }
      }
    }

    if (!hasRemoteChannels) {
      setAlertNotifyStatus("Desktop routing only.");
      return;
    }
    const res = await apiPost("/api/mission/alerts/notify", {
      alerts: rows,
      channels,
    });
    setAlertNotifyStatus(`sent ${rows.length} alert${rows.length === 1 ? "" : "s"} to configured channels`);
    if (res && res.ok === false) {
      setAlertNotifyStatus(`notify error: ${JSON.stringify(res.channels || {})}`, true);
    }
  } catch (e) {
    setAlertNotifyStatus(String(e?.message || e), true);
  } finally {
    state.notifyingAlert = false;
  }
}

function maybeDispatchAlertNotifications() {
  const high = collectHighAlerts();
  const pending = nextNotifiableAlerts(high);
  if (!pending.length) return;
  sendAlertNotifications(pending, { auto: true });
}

function nodeMapFromTopology(topology) {
  const nodes = Array.isArray(topology?.nodes) ? topology.nodes : [];
  const out = new Map();
  for (const n of nodes) {
    const id = String(n?.id || "").trim();
    if (!id) continue;
    out.set(id, n);
  }
  return out;
}

function filteredTopology(topologyInput) {
  const topology = topologyInput && typeof topologyInput === "object"
    ? topologyInput
    : { nodes: [], edges: [], timeline: [] };
  const scope = String(state.topologySourceFilter || "all").trim().toLowerCase();
  const nodes = Array.isArray(topology.nodes) ? topology.nodes : [];
  const edges = Array.isArray(topology.edges) ? topology.edges : [];
  const timeline = Array.isArray(topology.timeline) ? topology.timeline : [];
  if (scope === "all") return { nodes, edges, timeline };
  const nodeIds = new Set(
    nodes
      .filter((n) => String(n?.source || "").trim().toLowerCase() === scope)
      .map((n) => String(n?.id || "").trim())
      .filter(Boolean),
  );
  return {
    nodes: nodes.filter((n) => nodeIds.has(String(n?.id || "").trim())),
    edges: edges.filter((e) => (
      nodeIds.has(String(e?.from || "").trim()) || nodeIds.has(String(e?.to || "").trim())
    )),
    timeline: timeline.filter((row) => {
      const aid = String(row?.agent_id || "").trim();
      return !aid || nodeIds.has(aid);
    }),
  };
}

function renderTopology(payload) {
  const topologyRaw = payload?.topology && typeof payload.topology === "object"
    ? payload.topology
    : { nodes: [], edges: [], timeline: [] };
  state.topology = topologyRaw;
  const topology = filteredTopology(topologyRaw);
  if (elTopologyNodesCount) elTopologyNodesCount.textContent = String((topology.nodes || []).length);
  if (elTopologyEdgesCount) elTopologyEdgesCount.textContent = String((topology.edges || []).length);
  if (!elTopologyTimelineList) return;

  const nodesById = nodeMapFromTopology(topology);
  elTopologyTimelineList.innerHTML = "";
  const edges = Array.isArray(topology.edges) ? topology.edges : [];
  const timeline = Array.isArray(topology.timeline) ? topology.timeline : [];

  if (!edges.length && !timeline.length) {
    elTopologyTimelineList.innerHTML = '<div class="empty">No topology data yet.</div>';
    return;
  }

  for (const edge of edges.slice(0, 14)) {
    const row = document.createElement("article");
    row.className = "topology-item";
    const fromNode = nodesById.get(String(edge?.from || "").trim());
    const toNode = nodesById.get(String(edge?.to || "").trim());
    const head = document.createElement("div");
    head.className = "head";
    const edgeStrong = document.createElement("strong");
    edgeStrong.textContent = `${String(fromNode?.label || edge?.from || "--")} -> ${String(toNode?.label || edge?.to || "--")}`;
    const edgeType = document.createElement("span");
    edgeType.textContent = String(edge?.type || "edge");
    head.appendChild(edgeStrong);
    head.appendChild(edgeType);
    const meta = document.createElement("div");
    meta.className = "meta";
    const fromStatus = String(fromNode?.status || "").trim();
    const toStatus = String(toNode?.status || "").trim();
    meta.textContent = `from=${fromStatus || "--"} | to=${toStatus || "--"}`;
    row.appendChild(head);
    row.appendChild(meta);
    elTopologyTimelineList.appendChild(row);
  }

  for (const event of timeline.slice(0, 40)) {
    const row = document.createElement("article");
    row.className = "topology-item";
    const head = document.createElement("div");
    head.className = "head";
    const eventTime = document.createElement("strong");
    eventTime.textContent = fmtTime(event?.ts);
    const eventMeta = document.createElement("span");
    eventMeta.textContent = `${String(event?.source || "--")}/${String(event?.type || "--")}`;
    head.appendChild(eventTime);
    head.appendChild(eventMeta);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = String(event?.text || "");
    row.appendChild(head);
    row.appendChild(meta);
    elTopologyTimelineList.appendChild(row);
  }
}

function allApprovals(payload) {
  const ap = payload?.approvals && typeof payload.approvals === "object"
    ? payload.approvals
    : state.approvals;
  const autonomy = Array.isArray(ap?.autonomy) ? ap.autonomy.map((x) => ({ ...x, source: "autonomy" })) : [];
  const guardrails = Array.isArray(ap?.guardrails) ? ap.guardrails.map((x) => ({ ...x, source: "guardrails" })) : [];
  return [...autonomy, ...guardrails];
}

function renderApprovalQueue(payload) {
  const ap = payload?.approvals && typeof payload.approvals === "object" ? payload.approvals : state.approvals;
  state.approvals = ap;
  if (!elApprovalQueueList) return;
  const scope = String(state.approvalSourceFilter || "all").trim().toLowerCase();
  const rows = allApprovals(payload).filter((row) => scope === "all" || String(row?.source || "") === scope);
  elApprovalQueueList.innerHTML = "";
  if (!rows.length) {
    elApprovalQueueList.innerHTML = '<div class="empty">No pending approvals.</div>';
    return;
  }
  for (const row of rows.slice(0, 120)) {
    const src = String(row?.source || "approval");
    const item = document.createElement("article");
    item.className = "approval-item";
    const head = document.createElement("div");
    head.className = "head";
    const title = src === "autonomy"
      ? `autonomy:${String(row?.id || "")}`
      : `guardrails:${String(row?.tool_name || row?.tool_call_id || "")}`;
    const approvalTitle = document.createElement("strong");
    approvalTitle.textContent = title;
    const approvalSource = document.createElement("span");
    approvalSource.textContent = src;
    head.appendChild(approvalTitle);
    head.appendChild(approvalSource);
    const meta = document.createElement("div");
    meta.className = "meta";
    if (src === "autonomy") {
      meta.textContent = [
        `job=${String(row?.job_id || "--")}`,
        `risk=${String(row?.risk_class || "--")}`,
        `requested=${fmtDateTime(row?.requested_at)}`,
      ].join(" | ");
    } else {
      meta.textContent = [
        `run=${String(row?.run_id || "--")}`,
        `tool=${String(row?.tool_name || "--")}`,
        `requested=${fmtDateTime(row?.requested_at)}`,
      ].join(" | ");
    }
    const actions = document.createElement("div");
    actions.className = "actions";
    const approveBtn = document.createElement("button");
    approveBtn.type = "button";
    approveBtn.textContent = "Approve";
    approveBtn.addEventListener("click", () => decideApproval(row, true));
    const denyBtn = document.createElement("button");
    denyBtn.type = "button";
    denyBtn.textContent = "Deny";
    denyBtn.className = "deny";
    denyBtn.addEventListener("click", () => decideApproval(row, false));
    actions.appendChild(approveBtn);
    actions.appendChild(denyBtn);
    item.appendChild(head);
    item.appendChild(meta);
    item.appendChild(actions);
    elApprovalQueueList.appendChild(item);
  }
}

async function decideApproval(row, approve) {
  const src = String(row?.source || "");
  try {
    if (src === "autonomy") {
      const approvalId = String(row?.id || "").trim();
      if (!approvalId) throw new Error("missing approval id");
      await apiPost(`/api/mission/approvals/autonomy/${encodeURIComponent(approvalId)}/decision`, {
        approve: !!approve,
        actor: "mission_control",
      });
    } else if (src === "guardrails") {
      const runId = String(row?.run_id || "").trim();
      const toolCallId = String(row?.tool_call_id || "").trim();
      if (!runId || !toolCallId) throw new Error("missing run/tool_call id");
      await apiPost("/api/mission/approvals/guardrails/resolve", {
        run_id: runId,
        tool_call_id: toolCallId,
        tool_name: String(row?.tool_name || "").trim(),
        session_id: String(row?.session_id || "").trim(),
        approve: !!approve,
        allow_session_tool: !!approve,
      });
    } else {
      throw new Error(`unsupported approval source: ${src}`);
    }
    await refreshMission();
  } catch (e) {
    setSync(String(e?.message || e), true);
  }
}

function renderEvents(payload) {
  if (!elEventFeed) return;
  const rawEvents = Array.isArray(payload?.events) ? payload.events : [];
  const allAgents = Array.isArray(payload?.agents) ? payload.agents : [];
  const filteredAgents = applyAgentFilters(allAgents);
  const allowedAgentIds = new Set(filteredAgents.map((a) => String(a?.id || "")).filter(Boolean));
  const allowedRunIds = new Set(filteredAgents.map((a) => String(a?.run_id || "")).filter(Boolean));
  const query = String(state.missionFilters?.query || "").trim().toLowerCase();
  const statusFilter = String(state.missionFilters?.status || "all").trim().toLowerCase();
  const roomFilter = String(state.missionFilters?.room || "all").trim().toLowerCase();
  const agentFiltersActive = statusFilter !== "all" || roomFilter !== "all";
  const events = rawEvents.filter((ev) => {
    if (agentFiltersActive) {
      if (!filteredAgents.length) return false;
      const evRun = String(ev?.run_id || "").trim();
      const evAgent = String(ev?.agent_id || "").trim();
      if (allowedAgentIds.size || allowedRunIds.size) {
        const runMatch = evRun && allowedRunIds.has(evRun);
        const agentMatch = evAgent && allowedAgentIds.has(evAgent);
        if (!(runMatch || agentMatch)) return false;
      }
    }
    if (query) {
      const hay = [
        String(ev?.source || ""),
        String(ev?.type || ""),
        String(ev?.text || ""),
        String(ev?.run_id || ""),
        String(ev?.agent_id || ""),
      ].join(" ").toLowerCase();
      return hay.includes(query);
    }
    return true;
  });
  elEventFeed.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No recent events.";
    elEventFeed.appendChild(empty);
    return;
  }
  for (const ev of events.slice(0, 60)) {
    const row = document.createElement("article");
    row.className = "event-item";
    const head = document.createElement("div");
    head.className = "event-head";
    const typeSpan = document.createElement("span");
    typeSpan.textContent = `${String(ev.source || "source")} / ${String(ev.type || "event")}`;
    const timeEl = document.createElement("time");
    timeEl.textContent = fmtTime(ev.ts);
    head.appendChild(typeSpan);
    head.appendChild(timeEl);

    const txt = document.createElement("div");
    txt.className = "event-text";
    txt.textContent = String(ev.text || "");

    row.appendChild(head);
    row.appendChild(txt);
    elEventFeed.appendChild(row);
  }
}

function renderRoomCounts(agents) {
  const counts = roomCounts(agents);
  for (const roomId of ROOM_ORDER) {
    const el = document.querySelector(`[data-count-for="${roomId}"]`);
    if (el) el.textContent = String(counts[roomId] || 0);
  }
}
function computeRoomAnchors() {
  if (!elAgentLayer || !elWorkspaceGrid) return {};
  const layerRect = elAgentLayer.getBoundingClientRect();
  const anchors = {};
  for (const roomId of ROOM_ORDER) {
    const roomEl = elWorkspaceGrid.querySelector(`.room[data-room="${roomId}"]`);
    if (!roomEl) continue;
    const r = roomEl.getBoundingClientRect();
    anchors[roomId] = {
      x: r.left - layerRect.left + 8,
      y: r.top - layerRect.top + 38,
      width: Math.max(120, r.width - 16),
      height: Math.max(90, r.height - 46),
    };
  }
  return anchors;
}

function createAgentCard(agent) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "agent-card";
  card.dataset.agentId = String(agent?.id || "");
  card.innerHTML = `
    <div class="agent-top">
      <div>
        <div class="agent-name"></div>
        <div class="agent-model-row">
          <span class="agent-model-dot"></span>
          <span class="agent-model-badge"></span>
        </div>
      </div>
      <span class="agent-status"></span>
    </div>
    <div class="agent-summary"></div>
  `;
  card.addEventListener("click", () => {
    selectAgent(String(card.dataset.agentId || ""), { openActivity: true });
  });
  return card;
}

function updateCard(card, agent) {
  const name = card.querySelector(".agent-name");
  const stat = card.querySelector(".agent-status");
  const summary = card.querySelector(".agent-summary");
  const modelDot = card.querySelector(".agent-model-dot");
  const modelBadge = card.querySelector(".agent-model-badge");
  const model = modelRef(agent);

  if (name) name.textContent = displayName(agent);
  if (stat) {
    const st = String(agent?.status || "unknown");
    stat.textContent = st;
    stat.className = `agent-status ${statusClass(st)}`;
  }
  if (summary) {
    const text = String(agent?.summary || "");
    summary.textContent = text;
    summary.classList.toggle("muted", !text);
  }
  if (modelDot) modelDot.style.background = model.color;
  if (modelBadge) modelBadge.textContent = `${model.icon} ${model.label}`;

  card.style.setProperty("--model-color", model.color);
  card.dataset.agentId = String(agent?.id || "");
  card.title = `${displayName(agent)}\n${String(agent?.summary || "")}`;
}

function renderSelection() {
  for (const [id, card] of state.cards.entries()) {
    card.classList.toggle("selected", id === state.selectedAgentId);
  }
  for (const [id, avatar] of state.officeAgents.entries()) {
    avatar.classList.toggle("selected", id === state.selectedAgentId);
  }
}

function renderWorkspace(payload) {
  if (!elAgentLayer) return;
  const allAgents = Array.isArray(payload?.agents) ? payload.agents : [];
  const filteredAgents = applyAgentFilters(allAgents);
  const agents = visibleAgentsForVisuals(filteredAgents);
  renderRoomCounts(filteredAgents);

  const anchors = computeRoomAnchors();
  const grouped = {};
  for (const roomId of ROOM_ORDER) grouped[roomId] = [];
  for (const a of agents) {
    const room = String(a?.room || "");
    if (!grouped[room]) grouped[room] = [];
    grouped[room].push(a);
  }

  const visibleIds = new Set();
  for (const roomId of ROOM_ORDER) {
    const roomAgents = (grouped[roomId] || []).slice(0, MAX_VISIBLE_PER_ROOM);
    const anchor = anchors[roomId];
    if (!anchor) continue;
    const columns = Math.max(1, Math.floor((anchor.width + SLOT_GAP_X) / (CARD_WIDTH + SLOT_GAP_X)));

    for (let i = 0; i < roomAgents.length; i += 1) {
      const agent = roomAgents[i];
      const agentId = String(agent?.id || "");
      if (!agentId) continue;
      visibleIds.add(agentId);

      let card = state.cards.get(agentId);
      if (!card) {
        card = createAgentCard(agent);
        state.cards.set(agentId, card);
        elAgentLayer.appendChild(card);
      }
      updateCard(card, agent);

      const col = i % columns;
      const row = Math.floor(i / columns);
      const x = anchor.x + col * (CARD_WIDTH + SLOT_GAP_X);
      const y = anchor.y + row * (CARD_HEIGHT + SLOT_GAP_Y);
      const prevX = Number(card.dataset.x || "nan");
      const prevY = Number(card.dataset.y || "nan");
      const moved = Number.isFinite(prevX) && (Math.abs(prevX - x) > 2 || Math.abs(prevY - y) > 2);
      if (moved) {
        card.classList.remove("moving");
        void card.offsetWidth;
        card.classList.add("moving");
      }
      card.style.transform = `translate(${x}px, ${y}px)`;
      card.dataset.x = String(x);
      card.dataset.y = String(y);
    }
  }

  for (const [id, card] of state.cards.entries()) {
    if (!visibleIds.has(id)) {
      state.cards.delete(id);
      card.remove();
    }
  }

  renderSelection();
}
function computeOfficeAnchors() {
  if (!elOfficeAgentLayer || !elOfficeMap) return {};
  const layerRect = elOfficeAgentLayer.getBoundingClientRect();
  const anchors = {};
  for (const roomId of ROOM_ORDER) {
    const roomEl = elOfficeMap.querySelector(`.office-zone[data-office-zone="${roomId}"]`);
    if (!roomEl) continue;
    const r = roomEl.getBoundingClientRect();
    anchors[roomId] = {
      x: r.left - layerRect.left + 8,
      y: r.top - layerRect.top + 34,
      width: Math.max(120, r.width - 16),
      height: Math.max(78, r.height - 42),
    };
  }
  return anchors;
}

function createOfficeAgent(agent) {
  const avatar = document.createElement("button");
  avatar.type = "button";
  avatar.className = "office-agent";
  avatar.dataset.agentId = String(agent?.id || "");
  avatar.innerHTML = `
    <span class="office-character">
      <span class="office-head"></span>
      <span class="office-body"></span>
    </span>
    <span class="office-bubble">
      <span class="office-agent-tag"></span>
      <span class="office-agent-model"></span>
    </span>
  `;
  avatar.addEventListener("click", () => {
    selectAgent(String(avatar.dataset.agentId || ""), { openActivity: true });
  });
  return avatar;
}

function updateOfficeAgent(avatar, agent) {
  const head = avatar.querySelector(".office-head");
  const body = avatar.querySelector(".office-body");
  const tag = avatar.querySelector(".office-agent-tag");
  const modelText = avatar.querySelector(".office-agent-model");
  const model = modelRef(agent);

  if (head) head.textContent = avatarInitials(agent).slice(0, 1);
  if (body) body.textContent = model.icon;
  if (tag) tag.textContent = shortName(displayName(agent), 18);
  if (modelText) modelText.textContent = model.label;

  avatar.dataset.agentId = String(agent?.id || "");
  avatar.style.setProperty("--model-color", model.color);
  avatar.classList.remove("active", "waiting", "done", "error");
  avatar.classList.add(officeMood(agent?.status));
  avatar.title = `${displayName(agent)}\n${model.label}\n${String(agent?.summary || "")}`;
}

function startOfficeMotionLoop() {
  if (state.motionFrame || !elOfficeAgentLayer) return;
  const tick = (ms) => {
    for (const avatar of state.officeAgents.values()) {
      const tx = Number(avatar.dataset.tx || 0);
      const ty = Number(avatar.dataset.ty || 0);
      const phase = Number(avatar.dataset.phase || 0);
      const driftX = Math.sin(ms * 0.0014 + phase) * 2.2;
      const driftY = Math.cos(ms * 0.0012 + phase * 1.7) * 1.6;
      avatar.style.transform = `translate(${(tx + driftX).toFixed(1)}px, ${(ty + driftY).toFixed(1)}px)`;
    }
    state.motionFrame = window.requestAnimationFrame(tick);
  };
  state.motionFrame = window.requestAnimationFrame(tick);
}

function stopOfficeMotionLoop() {
  if (!state.motionFrame) return;
  window.cancelAnimationFrame(state.motionFrame);
  state.motionFrame = null;
}

function renderOffice(payload) {
  if (!elOfficeAgentLayer || !elOfficeMap || !state.officeVisible) return;

  const allAgents = Array.isArray(payload?.agents) ? payload.agents : [];
  const filteredAgents = applyAgentFilters(allAgents);
  const agents = visibleAgentsForVisuals(filteredAgents);
  const anchors = computeOfficeAnchors();
  const grouped = {};
  for (const roomId of ROOM_ORDER) grouped[roomId] = [];
  for (const a of agents) {
    const room = String(a?.room || "");
    if (!grouped[room]) grouped[room] = [];
    grouped[room].push(a);
  }

  const visibleIds = new Set();
  for (const roomId of ROOM_ORDER) {
    const roomAgents = (grouped[roomId] || []).slice(0, OFFICE_MAX_VISIBLE_PER_ROOM);
    const anchor = anchors[roomId];
    if (!anchor) continue;
    const columns = Math.max(1, Math.floor((anchor.width + 8) / OFFICE_SLOT_X));

    for (let i = 0; i < roomAgents.length; i += 1) {
      const agent = roomAgents[i];
      const agentId = String(agent?.id || "");
      if (!agentId) continue;
      visibleIds.add(agentId);

      let avatar = state.officeAgents.get(agentId);
      if (!avatar) {
        avatar = createOfficeAgent(agent);
        state.officeAgents.set(agentId, avatar);
        elOfficeAgentLayer.appendChild(avatar);
      }
      updateOfficeAgent(avatar, agent);

      const row = Math.floor(i / columns);
      const col = i % columns;
      const jitterSeed = hashInt(`${agentId}:${roomId}`);
      const jitterX = ((jitterSeed % 17) - 8) * 0.8;
      const jitterY = ((Math.floor(jitterSeed / 17) % 13) - 6) * 0.7;
      const x = anchor.x + col * OFFICE_SLOT_X + jitterX;
      const y = anchor.y + row * OFFICE_SLOT_Y + jitterY;

      const prevX = Number(avatar.dataset.tx || "nan");
      const prevY = Number(avatar.dataset.ty || "nan");
      const moved = Number.isFinite(prevX) && (Math.abs(prevX - x) > 8 || Math.abs(prevY - y) > 8);
      if (moved) {
        avatar.classList.remove("moving");
        void avatar.offsetWidth;
        avatar.classList.add("moving");
      }
      avatar.dataset.tx = String(x);
      avatar.dataset.ty = String(y);
      avatar.dataset.phase = String((hashInt(agentId) % 628) / 100);
    }
  }

  for (const [id, avatar] of state.officeAgents.entries()) {
    if (!visibleIds.has(id)) {
      state.officeAgents.delete(id);
      avatar.remove();
    }
  }

  renderSelection();
  startOfficeMotionLoop();
}

function findSelectedAgent() {
  const agents = getAgents();
  if (!agents.length) return null;
  const filtered = applyAgentFilters(agents);
  const pool = filtered.length ? filtered : agents;
  const selected = agents.find((a) => String(a?.id || "") === state.selectedAgentId);
  if (selected) {
    if (!filtered.length || filtered.some((a) => String(a?.id || "") === String(selected?.id || ""))) {
      return selected;
    }
  }

  const active = pool.find((a) => ["running", "queued", "awaiting_approval", "blocked"].includes(String(a?.status || "").toLowerCase()));
  if (active) {
    state.selectedAgentId = String(active?.id || "");
    return active;
  }
  state.selectedAgentId = String(pool[0]?.id || "");
  return pool[0];
}

function actionButton(label, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

function actionLink(label, href) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noreferrer";
  a.textContent = label;
  return a;
}

function refreshDetailMeta(agent) {
  const model = modelRef(agent);
  const source = String(agent?.source || "");
  const room = String(agent?.room || "");
  const updated = fmtTime(agent?.updated_at);
  return `source=${source} room=${room} model=${model.label} updated=${updated}`;
}

function rerenderFromState() {
  if (!state.payload) return;
  renderStats(state.payload);
  renderFocus(state.payload);
  renderAlerts(state.payload);
  renderTopology(state.payload);
  renderApprovalQueue(state.payload);
  renderEvents(state.payload);
  renderWorkspace(state.payload);
  renderOffice(state.payload);
  renderDetail();
  refreshReplayTimeline({ refreshReplay: false });
}
function renderDetail() {
  const agent = findSelectedAgent();
  if (!agent) {
    if (elDetailWrap) elDetailWrap.hidden = true;
    if (elDetailEmpty) elDetailEmpty.hidden = false;
    return;
  }

  if (elDetailWrap) elDetailWrap.hidden = false;
  if (elDetailEmpty) elDetailEmpty.hidden = true;

  const alias = displayName(agent);
  const model = modelRef(agent);

  if (elDetailName) elDetailName.textContent = `${alias} (${model.icon})`;
  if (elDetailMeta) elDetailMeta.textContent = refreshDetailMeta(agent);
  if (elDetailStatus) {
    const st = String(agent?.status || "unknown");
    elDetailStatus.textContent = st;
    elDetailStatus.className = `status-pill ${statusClass(st)}`;
  }
  if (elDetailSummary) elDetailSummary.textContent = String(agent?.summary || "");
  if (elDetailJson) elDetailJson.textContent = JSON.stringify(agent, null, 2);

  if (!elDetailActions) return;
  elDetailActions.innerHTML = "";

  const id = String(agent?.id || "");
  const runId = String(agent?.run_id || "");
  const jobId = String(agent?.job_id || "");
  const source = String(agent?.source || "");

  elDetailActions.appendChild(actionButton("Open Activity", () => openActivity(agent, { refreshReplay: true })));

  elDetailActions.appendChild(
    actionButton("Rename Agent", () => {
      const key = agentIdentityKey(agent);
      const current = String(state.aliases?.[key] || ensureAlias(agent));
      const next = window.prompt("Name for this recurring agent role:", current);
      if (next === null) return;
      const clean = normalizeAlias(next || "");
      if (!clean) return;
      const unique = uniqueAliasForKey(key, clean);
      state.aliases[key] = unique || clean;
      saveAliasMap();
      if (unique && unique !== clean) {
        setSync(`name already used; assigned ${unique}`);
      }
      rerenderFromState();
      refreshActivity({ refreshReplay: false });
    }),
  );

  elDetailActions.appendChild(
    actionButton("Reset Name", () => {
      clearAlias(agent);
      rerenderFromState();
      refreshActivity({ refreshReplay: false });
    }),
  );

  const safeRunId = safeOpaqueId(runId);
  if (runId && !safeRunId) {
    setSync("run_id contains unsupported characters; run actions hidden", true);
  }
  if (safeRunId) {
    elDetailActions.appendChild(
      actionButton("Cancel Run", async () => {
        try {
          await apiPost(`/api/runs/${encodeURIComponent(safeRunId)}/cancel`, {});
          await refreshMission();
        } catch (e) {
          setSync(String(e?.message || e), true);
        }
      }),
    );
    elDetailActions.appendChild(actionLink("Replay", `/api/runs/${encodeURIComponent(safeRunId)}/replay`));
    elDetailActions.appendChild(actionLink("Export", `/api/runs/${encodeURIComponent(safeRunId)}/export`));
  }

  if (source === "autonomy_job" && jobId) {
    elDetailActions.appendChild(
      actionButton("Run Now", async () => {
        try {
          await apiPost(`/api/mission/jobs/${encodeURIComponent(jobId)}/run_now`, {});
          await refreshMission();
        } catch (e) {
          setSync(String(e?.message || e), true);
        }
      }),
    );
    elDetailActions.appendChild(
      actionButton("Cancel Job", async () => {
        try {
          await apiPost(`/api/mission/jobs/${encodeURIComponent(jobId)}/cancel`, {});
          await refreshMission();
        } catch (e) {
          setSync(String(e?.message || e), true);
        }
      }),
    );
    elDetailActions.appendChild(
      actionButton("Requeue", async () => {
        try {
          await apiPost(`/api/mission/jobs/${encodeURIComponent(jobId)}/requeue`, {});
          await refreshMission();
        } catch (e) {
          setSync(String(e?.message || e), true);
        }
      }),
    );
    elDetailActions.appendChild(actionLink("Autonomy UI", "/autonomy"));
  }

  elDetailActions.appendChild(
    actionButton("Copy ID", async () => {
      try {
        await navigator.clipboard.writeText(id);
        setSync(`copied ${id}`);
      } catch {
        setSync(`copy failed for ${id}`, true);
      }
    }),
  );
}

function formatReplayLine(evt) {
  const type = String(evt?.type || evt?.event || "event");
  const ts = fmtTime(evt?.ts || evt?.time || evt?.created_at || "");
  let body = "";

  if (type === "text" || type === "agent_text") body = String(evt?.text || evt?.content || "").trim();
  else if (type === "tool_start" || type === "agent_tool_start") body = `start ${String(evt?.name || evt?.tool || "tool")}`;
  else if (type === "tool_result" || type === "agent_tool_result") {
    const ok = evt?.ok === false ? "failed" : "ok";
    body = `${ok} ${String(evt?.name || evt?.tool || "tool")}`;
  } else if (type === "error") body = String(evt?.error || "run error").trim();
  else if (type === "route") body = `route mode=${String(evt?.mode || evt?.route?.path || "auto")}`;
  else if (type === "done") body = "run complete";
  else body = String(evt?.text || evt?.message || evt?.summary || "").trim() || JSON.stringify(evt);

  return `[${ts}] ${type}  ${body}`.trim();
}

function collectMissionLines(agent, payload) {
  const lines = [];
  const runId = String(agent?.run_id || "");
  const agentId = String(agent?.id || "");
  const events = Array.isArray(payload?.events) ? payload.events : [];

  for (const ev of events) {
    const evRun = String(ev?.run_id || "");
    const evAgent = String(ev?.agent_id || "");
    if (runId && evRun && evRun === runId) {
      lines.push(`[${fmtTime(ev?.ts)}] ${String(ev?.source || "source")}/${String(ev?.type || "event")}  ${String(ev?.text || "")}`);
      continue;
    }
    if (agentId && evAgent && evAgent === agentId) {
      lines.push(`[${fmtTime(ev?.ts)}] ${String(ev?.source || "source")}/${String(ev?.type || "event")}  ${String(ev?.text || "")}`);
    }
  }

  if (!lines.length) lines.push(`summary: ${String(agent?.summary || "no activity summary")}`);
  return lines.slice(-MAX_ACTIVITY_LINES);
}

async function fetchRunReplayLines(runId, options = {}) {
  if (!runId) return [];
  const scope = String(options.scope || "activity").trim().toLowerCase();
  const abortKey = scope === "timeline" ? "timelineReplayAbort" : "activityReplayAbort";

  if (state[abortKey]) {
    state[abortKey].abort();
    state[abortKey] = null;
  }

  const abort = new AbortController();
  state[abortKey] = abort;
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/replay`, withAuth({ signal: abort.signal, headers: { Accept: "application/x-ndjson" } }));

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
    }

    const body = await res.text();
    const lines = [];
    for (const raw of String(body || "").split("\n")) {
      const trimmed = raw.trim();
      if (!trimmed) continue;
      try {
        lines.push(formatReplayLine(JSON.parse(trimmed)));
      } catch {
        lines.push(trimmed);
      }
    }

    return lines.slice(-MAX_ACTIVITY_LINES);
  } finally {
    if (state[abortKey] === abort) state[abortKey] = null;
  }
}

function renderActivityLines(lines) {
  if (elActivityLog) elActivityLog.textContent = (lines || []).join("\n");
}

function lineMatchesReplayToolsFilter(line) {
  const text = String(line || "").toLowerCase();
  return text.includes("tool_start")
    || text.includes("tool_result")
    || text.includes("start ")
    || text.includes(" ok ")
    || text.includes(" failed ");
}

function renderReplayTimelineLines(lines) {
  if (!elReplayTimelineLog) return;
  const src = Array.isArray(lines) ? lines : [];
  const showToolsOnly = !!elReplayToolsOnly?.checked;
  const filtered = showToolsOnly ? src.filter((line) => lineMatchesReplayToolsFilter(line)) : src;
  elReplayTimelineLog.textContent = filtered.length ? filtered.join("\n") : "No replay lines for current filter.";
}

async function refreshReplayTimeline(options = {}) {
  if (!elReplayTimelineLog) return;
  const agent = findSelectedAgent();
  if (!agent) {
    elReplayTimelineLog.textContent = "Select an agent to inspect timeline replay.";
    return;
  }
  const runId = String(agent?.run_id || "");
  const missionLines = collectMissionLines(agent, state.payload);
  let replayLines = runId ? state.activityReplayByRun.get(runId) || [] : [];

  const refreshReplay = !!options.refreshReplay;
  const shouldFetch = runId && (refreshReplay || (!replayLines.length && !state.replayRequestedByRun.has(runId)));
  if (shouldFetch) {
    state.replayRequestedByRun.add(runId);
    renderReplayTimelineLines([`loading run replay ${runId}...`, "", ...missionLines]);
    try {
      replayLines = await fetchRunReplayLines(runId, { scope: "timeline" });
      state.activityReplayByRun.set(runId, replayLines);
    } catch (e) {
      if (refreshReplay) state.replayRequestedByRun.delete(runId);
      renderReplayTimelineLines([`replay unavailable: ${String(e?.message || e)}`, "", ...missionLines]);
      return;
    }
  }

  if (runId && replayLines.length) {
    renderReplayTimelineLines([`[run replay: ${runId}]`, ...replayLines, "", "[live mission events]", ...missionLines]);
  } else {
    renderReplayTimelineLines(missionLines);
  }
}

function closeActivity() {
  state.activityOpen = false;
  state.activityAgentId = "";
  if (elActivityModal) elActivityModal.hidden = true;
  if (state.activityReplayAbort) {
    state.activityReplayAbort.abort();
    state.activityReplayAbort = null;
  }
}

async function refreshActivity(options = {}) {
  if (!state.activityOpen) return;
  const agent = findAgentById(state.activityAgentId);
  if (!agent) {
    closeActivity();
    return;
  }

  const alias = displayName(agent);
  const model = modelRef(agent);
  if (elActivityTitle) elActivityTitle.textContent = `${alias} (${model.icon})`;
  if (elActivityMeta) elActivityMeta.textContent = `${refreshDetailMeta(agent)} id=${String(agent?.id || "")}`;

  const runId = String(agent?.run_id || "");
  const missionLines = collectMissionLines(agent, state.payload);
  const replayLines = runId ? state.activityReplayByRun.get(runId) || [] : [];

  if (replayLines.length) renderActivityLines([`[run replay: ${runId}]`, ...replayLines, "", "[live mission events]", ...missionLines]);
  else renderActivityLines(missionLines);

  if (runId && options.refreshReplay) {
    try {
      renderActivityLines([`loading run replay ${runId}...`, "", ...missionLines]);
      const lines = await fetchRunReplayLines(runId);
      state.activityReplayByRun.set(runId, lines);
      if (!state.activityOpen || state.activityAgentId !== String(agent?.id || "")) return;
      renderActivityLines([`[run replay: ${runId}]`, ...lines, "", "[live mission events]", ...missionLines]);
    } catch (e) {
      if (!state.activityOpen || state.activityAgentId !== String(agent?.id || "")) return;
      renderActivityLines([`replay unavailable: ${String(e?.message || e)}`, "", ...missionLines]);
    }
  }
}

function openActivity(agent, options = {}) {
  const agentId = String(agent?.id || "");
  if (!agentId) return;
  state.activityOpen = true;
  state.activityAgentId = agentId;
  if (elActivityModal) elActivityModal.hidden = false;
  refreshActivity({ refreshReplay: !!options.refreshReplay });
}

function setOfficeVisible(nextVisible) {
  state.officeVisible = !!nextVisible;
  if (elOfficeWrap) elOfficeWrap.hidden = !state.officeVisible;
  updateIdleToggleUI();
  if (elOpenOffice) {
    elOpenOffice.classList.toggle("active", state.officeVisible);
    elOpenOffice.classList.toggle("office-open-btn", true);
    elOpenOffice.textContent = state.officeVisible ? "Office Open" : "Open Office";
  }
  if (state.officeVisible) {
    if (state.payload) renderOffice(state.payload);
    elOfficeWrap?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    stopOfficeMotionLoop();
  }
}

async function refreshMission() {
  if (state.refreshing) return;
  state.refreshing = true;
  setSync("syncing");
  try {
    const payload = await apiJson("/api/mission/control");
    applyPayload(payload, "poll");
  } catch (e) {
    setSync(String(e?.message || e), true);
  } finally {
    state.refreshing = false;
  }
}

function stopBenchmarkPolling() {
  if (!state.benchmarkIntervalId) return;
  window.clearInterval(state.benchmarkIntervalId);
  state.benchmarkIntervalId = null;
}

function startBenchmarkPolling() {
  stopBenchmarkPolling();
  state.benchmarkIntervalId = window.setInterval(() => {
    refreshBenchmarks();
  }, 7000);
}

function stopPolling() {
  if (!state.intervalId) return;
  window.clearInterval(state.intervalId);
  state.intervalId = null;
}

function startPolling() {
  stopPolling();
  state.intervalId = window.setInterval(() => {
    refreshMission();
  }, POLL_INTERVAL_MS);
}

function clearStreamReconnect() {
  if (!state.streamReconnectId) return;
  window.clearTimeout(state.streamReconnectId);
  state.streamReconnectId = null;
}

function stopMissionStream() {
  clearStreamReconnect();
  if (state.streamAbort) {
    state.streamAbort.abort();
    state.streamAbort = null;
  }
}

function scheduleStreamReconnect(reason) {
  if (state.streamReconnectId) return;
  setSync(`stream paused (${reason}), retrying`, true);
  startPolling();
  state.streamReconnectId = window.setTimeout(() => {
    state.streamReconnectId = null;
    startMissionStream();
  }, 1400);
}

function handleStreamEvent(evt) {
  const type = String(evt?.type || "").trim();
  if (type === "snapshot" && evt?.payload && typeof evt.payload === "object") {
    applyPayload(evt.payload, "stream");
    return;
  }
  if (type === "heartbeat") {
    setSync(`live ${fmtTime(evt?.generated_at)}`);
    return;
  }
  if (type === "error") setSync(String(evt?.error || "stream error"), true);
}

async function startMissionStream() {
  if (typeof window.fetch !== "function" || typeof window.TextDecoder !== "function") {
    setSync("stream not supported; polling", true);
    startPolling();
    return;
  }

  stopMissionStream();
  const generation = state.streamGeneration + 1;
  state.streamGeneration = generation;
  const abort = new AbortController();
  state.streamAbort = abort;
  let reader = null;
  let streamClosedCleanly = false;

  try {
    const res = await fetch(`/api/mission/stream?interval=${encodeURIComponent(String(POLL_INTERVAL_MS / 1000))}`, withAuth({ signal: abort.signal, headers: { Accept: "application/x-ndjson" } }));
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
    }
    if (!res.body || typeof res.body.getReader !== "function") throw new Error("stream response body unavailable");

    stopPolling();
    setSync("stream connected");

    reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        streamClosedCleanly = true;
        break;
      }
      buf += decoder.decode(value || new Uint8Array(), { stream: true });
      let idx = buf.indexOf("\n");
      while (idx >= 0) {
        const raw = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (raw) {
          try {
            handleStreamEvent(JSON.parse(raw));
          } catch {
            // ignore malformed line
          }
        }
        idx = buf.indexOf("\n");
      }
    }

    const tail = decoder.decode();
    if (tail.trim()) {
      try {
        handleStreamEvent(JSON.parse(tail.trim()));
      } catch {
        // ignore malformed tail
      }
    }
  } catch (e) {
    if (!abort.signal.aborted) scheduleStreamReconnect(String(e?.message || e));
    return;
  } finally {
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        // noop
      }
    }
    if (state.streamGeneration === generation) state.streamAbort = null;
  }

  if (!abort.signal.aborted && state.streamGeneration === generation && streamClosedCleanly) {
    scheduleStreamReconnect("connection ended");
  }
}

function bind() {
  if (elTopologySourceFilter) {
    elTopologySourceFilter.value = String(state.topologySourceFilter || "all");
  }
  if (elApprovalSourceFilter) {
    elApprovalSourceFilter.value = String(state.approvalSourceFilter || "all");
  }
  syncAlertRoutingInputs();

  elRefresh?.addEventListener("click", () => refreshMission());
  elRunBenchmark?.addEventListener("click", () => startBenchmarkRun());
  elRefreshBench?.addEventListener("click", () => refreshBenchmarks());
  elViewStatusFilter?.addEventListener("change", () => commitFilterInputs());
  elViewRoomFilter?.addEventListener("change", () => commitFilterInputs());
  elViewSearchInput?.addEventListener("input", () => commitFilterInputs());
  elClearFiltersBtn?.addEventListener("click", () => applyViewPreset("all"));
  elSavedViewSelect?.addEventListener("change", () => {
    const id = String(elSavedViewSelect.value || "").trim();
    if (id === "__custom__") return;
    applyViewPreset(id);
  });
  elSaveViewBtn?.addEventListener("click", () => saveCurrentViewPreset());
  elDeleteViewBtn?.addEventListener("click", () => deleteSelectedViewPreset());
  elBenchPackSelect?.addEventListener("change", () => {
    state.selectedBenchmarkPack = String(elBenchPackSelect.value || "").trim().toLowerCase();
    renderSelectedBenchmarkPack();
  });
  elBenchProfileSelect?.addEventListener("change", () => {
    state.selectedBenchmarkProfile = String(elBenchProfileSelect.value || "").trim();
  });
  elOpenOffice?.addEventListener("click", () => setOfficeVisible(!state.officeVisible));
  elCloseOffice?.addEventListener("click", () => setOfficeVisible(false));
  elTopologySourceFilter?.addEventListener("change", () => {
    state.topologySourceFilter = String(elTopologySourceFilter.value || "all").trim().toLowerCase() || "all";
    renderTopology(state.payload);
  });
  elTopologyRefreshBtn?.addEventListener("click", () => refreshMission());
  elApprovalSourceFilter?.addEventListener("change", () => {
    state.approvalSourceFilter = String(elApprovalSourceFilter.value || "all").trim().toLowerCase() || "all";
    renderApprovalQueue(state.payload);
  });
  elApprovalRefreshBtn?.addEventListener("click", () => refreshMission());
  const persistAlertRouting = () => {
    captureAlertRoutingInputs();
    saveAlertRouting();
    setAlertNotifyStatus("routing saved");
  };
  elAlertNotifyDesktop?.addEventListener("change", () => {
    persistAlertRouting();
  });
  elAlertNotifyWebhook?.addEventListener("change", () => {
    persistAlertRouting();
  });
  elAlertNotifyEmail?.addEventListener("change", () => {
    persistAlertRouting();
  });
  elAlertNotifyNowBtn?.addEventListener("click", async () => {
    captureAlertRoutingInputs();
    saveAlertRouting();
    const high = collectHighAlerts();
    const rows = high.length
      ? high
      : [
        {
          severity: "high",
          title: "Mission Control test alert",
          detail: `Manual test at ${new Date().toLocaleString()}`,
        },
      ];
    await sendAlertNotifications(rows, { auto: false });
  });
  elToggleIdle?.addEventListener("click", () => {
    state.showIdleAgents = !state.showIdleAgents;
    updateIdleToggleUI();
    rerenderFromState();
  });
  elReplayRefreshBtn?.addEventListener("click", () => refreshReplayTimeline({ refreshReplay: true }));
  elReplayToolsOnly?.addEventListener("change", () => refreshReplayTimeline({ refreshReplay: false }));
  elActivityBackdrop?.addEventListener("click", () => closeActivity());
  elActivityClose?.addEventListener("click", () => closeActivity());
  elActivityRefresh?.addEventListener("click", () => refreshActivity({ refreshReplay: true }));

  window.addEventListener("keydown", (evt) => {
    if (evt.key === "Escape" && state.activityOpen) closeActivity();
  });

  window.addEventListener("resize", () => {
    if (!state.payload) return;
    renderWorkspace(state.payload);
    renderOffice(state.payload);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    refreshMission();
    if (!state.streamAbort && !state.streamReconnectId) startMissionStream();
  });

  window.addEventListener("beforeunload", () => {
    stopMissionStream();
    stopPolling();
    stopBenchmarkPolling();
    stopOfficeMotionLoop();
    if (state.timelineReplayAbort) {
      state.timelineReplayAbort.abort();
      state.timelineReplayAbort = null;
    }
    closeActivity();
  });
}

bind();
renderViewPresets();
syncFilterInputs();
applyViewPreset("all");
setOfficeVisible(false);
refreshMission();
refreshBenchmarks();
startMissionStream();
startBenchmarkPolling();


