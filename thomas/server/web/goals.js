/* Thomas Goals Board  v4 consumer love edition (still vanilla JS)
   Big upgrades:
   - Details drawer (notes, tags, due, estimate, archive)
   - Quick add with natural-language-ish tokens (#tags !priority @date/time tomorrow in 3 days)
   - Multi-select + bulk actions
   - Command palette (Ctrl+K) for export/import/focus/archive/search
   - Stats strip using /api/goals/stats (ETag-aware)
   - Local cache renders instantly on load
   - Persistent drag-reorder with rank
*/

const API = {
  goals: "/api/goals",
  stats: "/api/goals/stats",
  create: "/api/goals",
  update: (id) => `/api/goals/${encodeURIComponent(id)}`,
  del: (id) => `/api/goals/${encodeURIComponent(id)}`,
  run: (id) => `/api/goals/${encodeURIComponent(id)}/run`,
};

const LS = {
  filter: "thomas.goals.filter",
  search: "thomas.goals.search",
  cache: "thomas.goals.cache.v4",
  statsCache: "thomas.goals.stats.cache.v4",
};

const els = {
  statusline: document.getElementById("statusline"),
  btnAddGoal: document.getElementById("btnAddGoal"),
  btnPalette: document.getElementById("btnPalette"),
  btnRefresh: document.getElementById("btnRefresh"),
  pills: Array.from(document.querySelectorAll(".pill")),
  addwrap: document.getElementById("addwrap"),
  addtext: document.getElementById("addtext"),
  addpriority: document.getElementById("addpriority"),
  addsave: document.getElementById("addsave"),
  quickAdd: document.getElementById("quickAdd"),
  search: document.getElementById("search"),
  toasts: document.getElementById("toasts"),
  zones: {
    open: document.getElementById("zone-open"),
    in_progress: document.getElementById("zone-in_progress"),
    done: document.getElementById("zone-done"),
  },
  counts: {
    open: document.getElementById("count-open"),
    in_progress: document.getElementById("count-in_progress"),
    done: document.getElementById("count-done"),
  },
  stats: {
    open: document.getElementById("statOpen"),
    ip: document.getElementById("statIP"),
    done: document.getElementById("statDone"),
    doneToday: document.getElementById("statDoneToday"),
    lead: document.getElementById("statLead"),
  },
  drawer: {
    root: document.getElementById("drawer"),
    close: document.getElementById("drawerClose"),
    title: document.getElementById("drawerTitle"),
    text: document.getElementById("dText"),
    status: document.getElementById("dStatus"),
    priority: document.getElementById("dPriority"),
    due: document.getElementById("dDue"),
    est: document.getElementById("dEst"),
    tags: document.getElementById("dTags"),
    notes: document.getElementById("dNotes"),
    save: document.getElementById("dSave"),
    run: document.getElementById("dRun"),
    del: document.getElementById("dDelete"),
    archive: document.getElementById("dArchive"),
  },
  bulk: {
    bar: document.getElementById("bulkbar"),
    count: document.getElementById("bulkcount"),
    moveOpen: document.getElementById("bulkMoveOpen"),
    moveIP: document.getElementById("bulkMoveIP"),
    moveDone: document.getElementById("bulkMoveDone"),
    priority: document.getElementById("bulkPriority"),
    run: document.getElementById("bulkRun"),
    del: document.getElementById("bulkDelete"),
    clear: document.getElementById("bulkClear"),
  },
  pal: {
    root: document.getElementById("palette"),
    backdrop: document.getElementById("palBackdrop"),
    input: document.getElementById("palInput"),
    list: document.getElementById("palList"),
  }
};

let state = {
  filter: "all",
  search: "",
  data: { open: [], in_progress: [], done: [] },
  etag: null,
  statsEtag: null,
  inflight: null,
  busy: false,
  dragging: { id: null, from: null },
  selected: new Set(), // goal ids
  drawer: { id: null },
  lastDeleted: null, // {text, priority, status, tags, due_at, notes, estimate_minutes}
};

function toast(kind, title, message, opts = {}) {
  const { ttlMs = 3600, actionLabel = null, onAction = null } = opts;

  const t = document.createElement("div");
  t.className = `toast ${kind || ""}`.trim();

  const icon = document.createElement("div");
  icon.className = "icon";
  t.appendChild(icon);

  const wrap = document.createElement("div");
  wrap.style.width = "100%";

  const row3 = document.createElement("div");
  row3.className = "row3";

  const left = document.createElement("div");
  const h = document.createElement("div");
  h.className = "t";
  h.textContent = title || "Notice";
  const m = document.createElement("div");
  m.className = "m";
  m.textContent = message || "";
  left.appendChild(h);
  left.appendChild(m);
  row3.appendChild(left);

  if (actionLabel && typeof onAction === "function") {
    const btn = document.createElement("button");
    btn.className = "action";
    btn.textContent = actionLabel;
    btn.addEventListener("click", () => {
      try { onAction(); } catch {}
      dismiss();
    });
    row3.appendChild(btn);
  }

  wrap.appendChild(row3);
  t.appendChild(wrap);

  function dismiss() {
    t.style.opacity = "0";
    t.style.transform = "translateY(6px)";
    setTimeout(() => t.remove(), 220);
  }

  els.toasts.appendChild(t);
  setTimeout(dismiss, ttlMs);
}

function setStatus(msg) {
  const now = new Date();
  els.statusline.textContent = `${msg}  ${now.toLocaleTimeString()}`;
}

function setBusy(b) {
  state.busy = b;
  for (const btn of [els.btnAddGoal, els.btnRefresh, els.btnPalette]) btn.disabled = b;
}

async function apiFetch(url, opts = {}) {
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
    ...opts,
  });

  if (res.status === 304) {
    return { __not_modified: true, headers: res.headers };
  }

  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch {}
  if (!res.ok) {
    const detail = (json && (json.detail || json.error)) ? (json.detail || json.error) : text;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return { json, headers: res.headers };
}

function fmtDate(v) {
  if (!v) return "unknown";
  if (typeof v === "number") {
    const n = v > 2000000000 ? v : v * 1000;
    const d = new Date(n);
    if (isNaN(d.getTime())) return "unknown";
    return d.toLocaleString();
  }
  const s = String(v);
  const d = new Date(s);
  if (!isNaN(d.getTime())) return d.toLocaleString();
  return s;
}

function parseLocalDateTime(s) {
  // Accept: YYYY-MM-DD, YYYY-MM-DD HH:MM, YYYY-MM-DDTHH:MM
  const t = String(s || "").trim();
  if (!t) return null;
  const m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/);
  if (!m) return null;
  const [_, yy, mm, dd, hh, mi] = m;
  const y = parseInt(yy, 10);
  const mo = parseInt(mm, 10) - 1;
  const d = parseInt(dd, 10);
  const H = hh ? parseInt(hh, 10) : 9;
  const M = mi ? parseInt(mi, 10) : 0;
  const dt = new Date(y, mo, d, H, M, 0, 0); // local time
  if (isNaN(dt.getTime())) return null;
  return dt;
}

function dueChip(goal) {
  if (!goal.due_at) return null;
  const due = new Date(goal.due_at);
  if (isNaN(due.getTime())) return { text: `Due: ${goal.due_at}`, cls: "" };
  const now = new Date();
  const diffMs = due - now;
  const diffH = diffMs / 3600000;
  const cls = diffH < 0 ? "overdue" : (diffH < 36 ? "due-soon" : "");
  const pretty = due.toLocaleString();
  return { text: `Due: ${pretty}`, cls };
}

function pickAttribution(goal) {
  const candidates = [
    goal.initiative_engine,
    goal.initiative,
    goal.created_by,
    goal.source,
    goal.attribution,
    goal.origin,
    goal.auto_created_by,
    goal.auto,
  ];
  const val = candidates.find((x) => x !== undefined && x !== null && String(x).trim().length);
  if (!val) return null;
  const s = String(val).trim();
  return s || null;
}

function matchesFilter(goal) {
  if (goal.archived) return false; // archived hidden by default; palette can show archived count
  if (state.filter !== "all") {
    if ((goal.priority || "").toLowerCase() !== state.filter) return false;
  }
  if (state.search) {
    const hay = `${goal.text || ""} ${(goal.notes || "")} ${(goal.tags || []).join(" ")} ${(goal.source || "")} ${(goal.created_by || "")}`.toLowerCase();
    if (!hay.includes(state.search.toLowerCase())) return false;
  }
  return true;
}

function makeHint(msg) {
  const div = document.createElement("div");
  div.className = "hintbox";
  div.textContent = msg;
  return div;
}

function cyclePriority(cur) {
  const p = (cur || "medium").toLowerCase();
  if (p === "high") return "medium";
  if (p === "medium") return "low";
  return "high";
}

async function patchGoal(id, payload) {
  await apiFetch(API.update(id), { method: "PATCH", body: JSON.stringify(payload) });
}

async function setGoalPriority(id, nextPriority) {
  try {
    setBusy(true);
    setStatus("Updating priority");
    await patchGoal(id, { priority: nextPriority });
    await fetchAll({ quiet: true, force: true });
    toast("", "Priority", `Set to ${nextPriority}`);
    setStatus("Priority updated");
  } catch (err) {
    toast("bad", "Priority update failed", err.message || "Unknown error");
    setStatus(`Priority update failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function setSelected(id, on) {
  if (on) state.selected.add(String(id));
  else state.selected.delete(String(id));
  updateBulkBar();
}

function clearSelection() {
  state.selected.clear();
  updateBulkBar();
  render(); // remove selected style
}

function updateBulkBar() {
  const n = state.selected.size;
  els.bulk.count.textContent = `${n} selected`;
  els.bulk.bar.classList.toggle("show", n > 0);
  els.bulk.bar.setAttribute("aria-hidden", n > 0 ? "false" : "true");
}

function allGoalsFlat() {
  return [...state.data.open, ...state.data.in_progress, ...state.data.done];
}

function getGoalById(id) {
  return allGoalsFlat().find((g) => String(g.id) === String(id)) || null;
}

function tagsChips(goal) {
  const tags = Array.isArray(goal.tags) ? goal.tags : [];
  return tags.slice(0, 3).map((t) => ({ text: `#${t.replace(/^#/, "")}`, cls: "tag" }));
}

function cardClickSelect(e, goalId) {
  // selection rules: click selects; ctrl toggles; shift selects range within a column (best effort)
  const id = String(goalId);
  const ctrl = e.ctrlKey || e.metaKey;
  const shift = e.shiftKey;

  if (!ctrl && !shift) {
    // single select -> open drawer
    clearSelection();
    openDrawer(id);
    return;
  }

  if (ctrl) {
    setSelected(id, !state.selected.has(id));
    render();
    return;
  }

  if (shift) {
    // range select within same zone: from last selected to clicked
    const zone = e.currentTarget.closest(".dropzone");
    if (!zone) return;
    const cards = Array.from(zone.querySelectorAll(".card"));
    const ids = cards.map((c) => String(c.dataset.id));
    const clickedIndex = ids.indexOf(id);
    const last = Array.from(state.selected).slice(-1)[0];
    const lastIndex = last ? ids.indexOf(String(last)) : -1;

    if (clickedIndex !== -1 && lastIndex !== -1) {
      const [a, b] = clickedIndex < lastIndex ? [clickedIndex, lastIndex] : [lastIndex, clickedIndex];
      for (let i = a; i <= b; i++) state.selected.add(ids[i]);
      updateBulkBar();
      render();
    } else {
      state.selected.add(id);
      updateBulkBar();
      render();
    }
  }
}

function makeCard(goal) {
  const card = document.createElement("div");
  card.className = "card";
  card.draggable = true;
  card.dataset.id = goal.id;
  card.dataset.status = goal.status;
  card.dataset.priority = goal.priority;
  card.dataset.rank = (goal.rank !== undefined && goal.rank !== null) ? String(goal.rank) : "";
  if (state.selected.has(String(goal.id))) card.classList.add("selected");

  const top = document.createElement("div");
  top.className = "row";

  const text = document.createElement("div");
  text.className = "text";
  text.textContent = goal.text || "(empty)";

  const badge = document.createElement("div");
  badge.className = `badge ${goal.priority || "medium"}`;
  badge.textContent = (goal.priority || "medium").toUpperCase();
  badge.title = "Click to cycle priority";
  badge.addEventListener("click", (e) => {
    e.stopPropagation();
    const next = cyclePriority(goal.priority);
    setGoalPriority(goal.id, next);
  });

  top.appendChild(text);
  top.appendChild(badge);

  const meta = document.createElement("div");
  meta.className = "meta";

  const left = document.createElement("div");
  left.className = "left";

  const createdChip = document.createElement("span");
  createdChip.className = "chip";
  createdChip.textContent = `Created: ${fmtDate(goal.created)}`;
  left.appendChild(createdChip);

  const due = dueChip(goal);
  if (due) {
    const dc = document.createElement("span");
    dc.className = `chip ${due.cls || ""}`.trim();
    dc.textContent = due.text;
    left.appendChild(dc);
  }

  const tchips = tagsChips(goal);
  for (const tc of tchips) {
    const c = document.createElement("span");
    c.className = `chip ${tc.cls}`;
    c.textContent = tc.text;
    left.appendChild(c);
  }

  const attr = pickAttribution(goal);
  if (attr) {
    const autoChip = document.createElement("span");
    autoChip.className = "chip";
    autoChip.textContent = `Source: ${attr}`;
    left.appendChild(autoChip);
  }

  const actions = document.createElement("div");
  actions.className = "actions";

  if (goal.status === "open") {
    const startBtn = document.createElement("button");
    startBtn.className = "linkbtn";
    startBtn.textContent = "Start";
    startBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await moveGoal(goal.id, "in_progress", "open", { keepPositionTop: true });
    });
    actions.appendChild(startBtn);

    const runBtn = document.createElement("button");
    runBtn.className = "linkbtn";
    runBtn.textContent = "Run Now";
    runBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await runGoal(goal.id);
    });
    actions.appendChild(runBtn);
  } else if (goal.status === "in_progress") {
    const doneBtn = document.createElement("button");
    doneBtn.className = "linkbtn";
    doneBtn.textContent = "Done";
    doneBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await moveGoal(goal.id, "done", "in_progress", { keepPositionTop: true });
    });
    actions.appendChild(doneBtn);
  } else if (goal.status === "done") {
    const reopenBtn = document.createElement("button");
    reopenBtn.className = "linkbtn";
    reopenBtn.textContent = "Reopen";
    reopenBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await moveGoal(goal.id, "open", "done", { keepPositionTop: true });
    });
    actions.appendChild(reopenBtn);
  }

  const delBtn = document.createElement("button");
  delBtn.className = "linkbtn danger";
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    await deleteGoal(goal);
  });
  actions.appendChild(delBtn);

  meta.appendChild(left);
  meta.appendChild(actions);

  card.appendChild(top);
  card.appendChild(meta);

  // Click behavior: selection/drawer
  card.addEventListener("click", (e) => cardClickSelect(e, goal.id));

  card.addEventListener("dragstart", (e) => {
    state.dragging.id = goal.id;
    state.dragging.from = goal.status;
    card.classList.add("dragging");
    const payload = JSON.stringify({ id: goal.id, from: goal.status });
    e.dataTransfer.setData("text/plain", payload);
    e.dataTransfer.effectAllowed = "move";
  });

  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    state.dragging.id = null;
    state.dragging.from = null;
    removePlaceholder();
  });

  return card;
}

function render() {
  const { open, in_progress, done } = state.data;
  els.counts.open.textContent = String(open.length);
  els.counts.in_progress.textContent = String(in_progress.length);
  els.counts.done.textContent = String(done.length);

  for (const status of ["open", "in_progress", "done"]) {
    const zone = els.zones[status];
    zone.innerHTML = "";

    const list = (state.data[status] || []).filter(matchesFilter);
    if (!list.length) {
      zone.appendChild(makeHint("Nothing here. Quick add above, or drag cards between columns."));
      continue;
    }

    list.forEach((g, i) => {
      if (g.rank === undefined || g.rank === null) g.rank = i;
    });

    for (const g of list) zone.appendChild(makeCard(g));
  }
}

function savePrefs() {
  try {
    localStorage.setItem(LS.filter, state.filter);
    localStorage.setItem(LS.search, state.search);
  } catch {}
}

function loadPrefs() {
  try {
    const f = localStorage.getItem(LS.filter);
    const s = localStorage.getItem(LS.search);
    if (f) state.filter = f;
    if (s) state.search = s;
  } catch {}
}

function saveCache() {
  try {
    localStorage.setItem(LS.cache, JSON.stringify({ data: state.data, saved_at: Date.now() }));
  } catch {}
}
function loadCache() {
  try {
    const raw = localStorage.getItem(LS.cache);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.data) return false;
    state.data = parsed.data;
    render();
    setStatus("Loaded from cache");
    return true;
  } catch {
    return false;
  }
}

function saveStatsCache(stats) {
  try {
    localStorage.setItem(LS.statsCache, JSON.stringify({ stats, saved_at: Date.now() }));
  } catch {}
}
function loadStatsCache() {
  try {
    const raw = localStorage.getItem(LS.statsCache);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.stats) return false;
    applyStats(parsed.stats);
    return true;
  } catch {
    return false;
  }
}

function applyStats(s) {
  els.stats.open.textContent = s.open ?? "";
  els.stats.ip.textContent = s.in_progress ?? "";
  els.stats.done.textContent = s.done ?? "";
  els.stats.doneToday.textContent = s.done_today ?? "";
  els.stats.lead.textContent = (s.avg_lead_hours === null || s.avg_lead_hours === undefined) ? "" : `${s.avg_lead_hours}h`;
}

async function fetchStats({ quiet = false, force = false } = {}) {
  try {
    const headers = {};
    if (state.statsEtag && !force) headers["If-None-Match"] = state.statsEtag;
    const r = await apiFetch(API.stats, { headers });
    if (r && r.__not_modified) return;
    const stats = (r && r.json) || {};
    const et = r && r.headers ? r.headers.get("ETag") : null;
    if (et) state.statsEtag = et;
    applyStats(stats);
    saveStatsCache(stats);
  } catch (err) {
    if (!quiet) toast("warn", "Stats unavailable", "Continuing without stats.");
  }
}

async function fetchGoals({ quiet = false, force = false } = {}) {
  if (state.inflight) return;

  try {
    if (!quiet) setStatus("Fetching goals");

    const headers = {};
    if (state.etag && !force) headers["If-None-Match"] = state.etag;

    state.inflight = new AbortController();
    const r = await apiFetch(API.goals, { headers, signal: state.inflight.signal });

    if (r && r.__not_modified) {
      if (!quiet) setStatus("No changes");
      return;
    }

    const data = (r && r.json) || {};
    const et = r && r.headers ? r.headers.get("ETag") : null;
    if (et) state.etag = et;

    state.data = {
      open: data.open || [],
      in_progress: data.in_progress || [],
      done: data.done || [],
    };
    render();
    saveCache();
    if (!quiet) setStatus("Up to date");
  } catch (err) {
    if (String(err && err.name) === "AbortError") return;
    setStatus(`Fetch failed: ${err.message}`);
    toast("bad", "Fetch failed", err.message || "Unknown error");
  } finally {
    state.inflight = null;
  }
}

async function fetchAll({ quiet = false, force = false } = {}) {
  await Promise.all([fetchGoals({ quiet, force }), fetchStats({ quiet: true, force })]);
}

function setActiveFilter(filter) {
  state.filter = filter;
  els.pills.forEach((b) => b.classList.toggle("active", (b.dataset.filter || "all") === filter));
  savePrefs();
  render();
  setStatus(`Filter: ${state.filter}`);
}

function wireFilter() {
  els.pills.forEach((btn) => {
    btn.addEventListener("click", () => setActiveFilter(btn.dataset.filter || "all"));
  });
}

function wireSearch() {
  els.search.value = state.search || "";
  let t = null;
  els.search.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.search = (els.search.value || "").trim();
      savePrefs();
      render();
      setStatus(state.search ? "Searching" : "Search cleared");
    }, 120);
  });
}

function toggleAdd() {
  els.addwrap.classList.toggle("show");
  if (els.addwrap.classList.contains("show")) {
    els.addtext.focus();
    setStatus("Add a goal");
  }
}

function wireAddInline() {
  els.btnAddGoal.addEventListener("click", toggleAdd);
  els.addsave.addEventListener("click", () => createFromInput(els.addtext.value, els.addpriority.value));

  els.addtext.addEventListener("keydown", (e) => {
    if (e.key === "Enter") createFromInput(els.addtext.value, els.addpriority.value);
    if (e.key === "Escape") els.addwrap.classList.remove("show");
  });
}

/* Quick-add parsing: consumer-friendly tokens
   - #tag -> tags
   - !high/!medium/!low -> priority
   - due:YYYY-MM-DD or @YYYY-MM-DD[ HH:MM]
   - today / tomorrow / in X days / next <weekday> / <weekday>
   Example: "Call broker #ops !high tomorrow 3pm"
*/
const WEEKDAYS = ["sunday","monday","tuesday","wednesday","thursday","friday","saturday"];
function parseQuickAdd(rawText, defaultPriority = "medium") {
  let text = String(rawText || "").trim();
  if (!text) return null;

  let priority = String(defaultPriority || "medium").toLowerCase();
  const tags = [];

  // tags: #tag
  text = text.replace(/(^|\s)#([a-zA-Z0-9_\-]+)/g, (m, p1, t) => {
    tags.push(t);
    return p1;
  });

  // priority: !high etc
  text = text.replace(/(^|\s)!(high|medium|low)\b/gi, (m, p1, p2) => {
    priority = p2.toLowerCase();
    return p1;
  });

  // explicit due: due:YYYY-MM-DD or @YYYY-MM-DD
  let due = null;
  const dueMatch = text.match(/(?:due:|@)(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?/i);
  if (dueMatch) {
    const date = dueMatch[1];
    const time = dueMatch[2] || "";
    due = `${date}${time ? " " + time : ""}`;
    text = text.replace(dueMatch[0], "").trim();
  } else {
    // relative keywords
    const lower = text.toLowerCase();

    function parseTimeInText(s) {
      const m = s.match(/\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/);
      if (!m) return null;
      let h = parseInt(m[1], 10);
      const min = m[2] ? parseInt(m[2], 10) : 0;
      const ap = m[3];
      if (ap === "pm" && h < 12) h += 12;
      if (ap === "am" && h === 12) h = 0;
      return { h, min, token: m[0] };
    }

    const timeTok = parseTimeInText(lower);
    const now = new Date();

    function setDueFromDate(baseDate) {
      const dt = new Date(baseDate);
      if (timeTok) {
        dt.setHours(timeTok.h, timeTok.min, 0, 0);
        text = text.replace(new RegExp(timeTok.token, "i"), "").trim();
      } else {
        dt.setHours(9, 0, 0, 0);
      }
      const yyyy = dt.getFullYear();
      const mm = String(dt.getMonth() + 1).padStart(2, "0");
      const dd = String(dt.getDate()).padStart(2, "0");
      const hh = String(dt.getHours()).padStart(2, "0");
      const mi = String(dt.getMinutes()).padStart(2, "0");
      due = `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
    }

    if (/\btomorrow\b/.test(lower)) {
      const dt = new Date(now);
      dt.setDate(dt.getDate() + 1);
      setDueFromDate(dt);
      text = text.replace(/\btomorrow\b/i, "").trim();
    } else if (/\btoday\b/.test(lower)) {
      setDueFromDate(now);
      text = text.replace(/\btoday\b/i, "").trim();
    } else {
      const inDays = lower.match(/\bin\s+(\d+)\s+days?\b/);
      if (inDays) {
        const n = parseInt(inDays[1], 10);
        const dt = new Date(now);
        dt.setDate(dt.getDate() + n);
        setDueFromDate(dt);
        text = text.replace(inDays[0], "").trim();
      } else {
        const nextWd = lower.match(/\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/);
        if (nextWd) {
          const target = WEEKDAYS.indexOf(nextWd[1]);
          const dt = new Date(now);
          const day = dt.getDay();
          let delta = (target - day + 7) % 7;
          if (delta === 0) delta = 7;
          delta += 7; // force next week
          dt.setDate(dt.getDate() + delta);
          setDueFromDate(dt);
          text = text.replace(nextWd[0], "").trim();
        } else {
          const wd = lower.match(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/);
          if (wd) {
            const target = WEEKDAYS.indexOf(wd[1]);
            const dt = new Date(now);
            const day = dt.getDay();
            let delta = (target - day + 7) % 7;
            if (delta === 0) delta = 7; // next occurrence
            dt.setDate(dt.getDate() + delta);
            setDueFromDate(dt);
            text = text.replace(wd[0], "").trim();
          }
        }
      }
    }
  }

  text = text.replace(/\s{2,}/g, " ").trim();
  if (!text) return null;

  return { text, priority, tags, due, notes: "" };
}

function toIsoFromLocalDue(dueStr) {
  const dt = parseLocalDateTime(dueStr);
  if (!dt) return null;
  // Send ISO string with timezone offset (Date.toISOString() is UTC; but fine)
  // We'll store UTC ISO; UI shows local.
  return dt.toISOString();
}

async function createFromInput(textRaw, priorityDefault) {
  const parsed = parseQuickAdd(textRaw, priorityDefault);
  if (!parsed) return;

  try {
    setBusy(true);
    setStatus("Creating goal");

    const body = { text: parsed.text, priority: parsed.priority };
    if (parsed.tags && parsed.tags.length) body.tags = parsed.tags;
    if (parsed.due) {
      const iso = toIsoFromLocalDue(parsed.due);
      if (iso) body.due_at = iso;
    }

    await apiFetch(API.create, { method: "POST", body: JSON.stringify(body) });

    // clear inputs
    if (els.addtext.value === textRaw) els.addtext.value = "";
    els.quickAdd.value = "";
    els.addwrap.classList.remove("show");

    await fetchAll({ quiet: true, force: true });
    setStatus("Goal created");
    toast("", "Created", "Goal added to Open.");
  } catch (err) {
    setStatus(`Create failed: ${err.message}`);
    toast("bad", "Create failed", err.message || "Unknown error");
  } finally {
    setBusy(false);
  }
}

function wireQuickAdd() {
  els.quickAdd.addEventListener("keydown", (e) => {
    if (e.key === "Enter") createFromInput(els.quickAdd.value, "medium");
  });
}

async function runGoal(goalId) {
  try {
    setBusy(true);
    setStatus("Queueing goal");
    const r = await apiFetch(API.run(goalId), { method: "POST" });
    const how = (r && r.json && r.json.how) ? r.json.how : "ok";
    toast("", "Queued", `Queued via ${how}`);
    setStatus("Queued");
  } catch (err) {
    toast("bad", "Run failed", err.message || "Unknown error");
    setStatus(`Run failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

async function deleteGoal(goal) {
  const ok = confirm("Delete this goal?");
  if (!ok) return;

  state.lastDeleted = {
    text: goal.text,
    priority: goal.priority,
    status: goal.status,
    tags: goal.tags || [],
    due_at: goal.due_at || null,
    notes: goal.notes || "",
    estimate_minutes: goal.estimate_minutes || null,
  };

  try {
    setBusy(true);
    setStatus("Deleting goal");
    await apiFetch(API.del(goal.id), { method: "DELETE" });
    await fetchAll({ quiet: true, force: true });
    setStatus("Deleted");

    toast("warn", "Deleted", "Goal removed.", {
      actionLabel: "Undo",
      ttlMs: 5500,
      onAction: async () => {
        const s = state.lastDeleted;
        if (!s) return;
        state.lastDeleted = null;
        try {
          setStatus("Restoring goal");
          const body = { text: s.text, priority: (s.priority || "medium") };
          if (s.tags && s.tags.length) body.tags = s.tags;
          if (s.due_at) body.due_at = s.due_at;
          if (s.notes) body.notes = s.notes;
          const r = await apiFetch(API.create, { method: "POST", body: JSON.stringify(body) });
          const created = r && r.json && r.json.goal ? r.json.goal : null;
          if (created) {
            const patch = {};
            if (s.status && s.status !== "open") patch.status = s.status;
            if (s.estimate_minutes !== null && s.estimate_minutes !== undefined) patch.estimate_minutes = s.estimate_minutes;
            if (Object.keys(patch).length) await patchGoal(created.id, patch);
          }
          await fetchAll({ quiet: true, force: true });
          toast("", "Restored", "Goal restored.");
          setStatus("Restored");
        } catch (err) {
          toast("bad", "Undo failed", err.message || "Unknown error");
        }
      }
    });
  } catch (err) {
    setStatus(`Delete failed: ${err.message}`);
    toast("bad", "Delete failed", err.message || "Unknown error");
  } finally {
    setBusy(false);
  }
}

/* Drag/drop + persistent reorder (rank) */
let placeholderEl = null;
function ensurePlaceholder() {
  if (!placeholderEl) {
    placeholderEl = document.createElement("div");
    placeholderEl.className = "placeholder";
  }
  return placeholderEl;
}
function removePlaceholder() {
  if (placeholderEl && placeholderEl.parentNode) placeholderEl.parentNode.removeChild(placeholderEl);
}

function getDragAfterElement(zone, y) {
  const draggableElements = [...zone.querySelectorAll(".card:not(.dragging)")];
  return draggableElements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) return { offset, element: child };
    return closest;
  }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
}

function getDropInsertIndex(zone) {
  const ph = zone.querySelector(".placeholder");
  if (ph) {
    const idx = Array.from(zone.children).indexOf(ph);
    return idx === -1 ? 0 : idx;
  }
  return zone.querySelectorAll(".card:not(.dragging)").length;
}

function computeRankForInsert(zone, insertIndex) {
  const cards = Array.from(zone.querySelectorAll(".card"));
  const clean = cards.filter((c) => !c.classList.contains("dragging"));
  const getRank = (el) => {
    const s = el.dataset.rank;
    const f = s ? parseFloat(s) : NaN;
    return isFinite(f) ? f : null;
  };
  const prevEl = clean[insertIndex - 1] || null;
  const nextEl = clean[insertIndex] || null;
  const prevRank = prevEl ? getRank(prevEl) : null;
  const nextRank = nextEl ? getRank(nextEl) : null;
  if (prevRank !== null && nextRank !== null) return (prevRank + nextRank) / 2.0;
  if (prevRank !== null) return prevRank + 1.0;
  if (nextRank !== null) return nextRank - 1.0;
  return 0.0;
}

function optimisticMove(goalId, fromStatus, toStatus, insertIndex = 0) {
  const from = state.data[fromStatus] || [];
  const to = state.data[toStatus] || [];
  const idx = from.findIndex((g) => String(g.id) === String(goalId));
  if (idx === -1) return null;
  const [g] = from.splice(idx, 1);
  g.status = toStatus;
  const clamped = Math.max(0, Math.min(insertIndex, to.length));
  to.splice(clamped, 0, g);
  state.data[fromStatus] = from;
  state.data[toStatus] = to;
  render();
  return g;
}

async function moveGoal(goalId, newStatus, fromStatus, opts = {}) {
  const { keepPositionTop = false } = opts;

  try {
    setBusy(true);
    setStatus("Updating status");
    const zone = els.zones[newStatus];
    const insertIndex = keepPositionTop ? 0 : getDropInsertIndex(zone);
    optimisticMove(goalId, fromStatus, newStatus, insertIndex);
    const rank = computeRankForInsert(zone, insertIndex);
    await patchGoal(goalId, { status: newStatus, rank });
    await fetchAll({ quiet: true, force: true });
    setStatus("Moved");
    toast("", "Moved", `Moved to ${newStatus.replace("_"," ")}`);
  } catch (err) {
    setStatus(`Move failed: ${err.message}`);
    toast("bad", "Move failed", err.message || "Unknown error");
    await fetchAll({ quiet: true, force: true });
  } finally {
    setBusy(false);
  }
}

async function reorderWithin(zone, goalId, fromStatus) {
  const targetStatus = zone.dataset.status;
  const insertIndex = getDropInsertIndex(zone);
  const rank = computeRankForInsert(zone, insertIndex);

  try {
    setBusy(true);
    setStatus("Reordering");
    optimisticMove(goalId, fromStatus, targetStatus, insertIndex);
    await patchGoal(goalId, { status: targetStatus, rank });
    await fetchAll({ quiet: true, force: true });
    setStatus("Reordered");
  } catch (err) {
    toast("bad", "Reorder failed", err.message || "Unknown error");
    await fetchAll({ quiet: true, force: true });
    setStatus(`Reorder failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function wireDnD() {
  for (const status of ["open", "in_progress", "done"]) {
    const zone = els.zones[status];

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
      e.dataTransfer.dropEffect = "move";

      const after = getDragAfterElement(zone, e.clientY);
      const ph = ensurePlaceholder();
      if (!after) zone.appendChild(ph);
      else zone.insertBefore(ph, after);
    });

    zone.addEventListener("dragleave", () => {
      zone.classList.remove("dragover");
    });

    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");

      try {
        const payload = e.dataTransfer.getData("text/plain");
        const parsed = JSON.parse(payload);
        if (!parsed || !parsed.id) return;

        const id = parsed.id;
        const from = parsed.from;
        const targetStatus = zone.dataset.status;
        removePlaceholder();

        if (!targetStatus) return;

        if (from === targetStatus) await reorderWithin(zone, id, from);
        else await moveGoal(id, targetStatus, from);
      } catch {
        removePlaceholder();
      }
    });
  }
}

/* Drawer */
function openDrawer(goalId) {
  const g = getGoalById(goalId);
  if (!g) return;

  state.drawer.id = String(goalId);
  els.drawer.title.textContent = `Goal ${g.id}`;
  els.drawer.text.value = g.text || "";
  els.drawer.status.value = (g.status || "open");
  els.drawer.priority.value = (g.priority || "medium");
  els.drawer.notes.value = g.notes || "";
  els.drawer.tags.value = Array.isArray(g.tags) ? g.tags.map(t => `#${String(t).replace(/^#/, "")}`).join(", ") : "";
  els.drawer.est.value = (g.estimate_minutes !== undefined && g.estimate_minutes !== null) ? String(g.estimate_minutes) : "";
  els.drawer.due.value = g.due_at ? (new Date(g.due_at).toLocaleString()) : "";

  els.drawer.root.classList.add("show");
  els.drawer.root.setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  state.drawer.id = null;
  els.drawer.root.classList.remove("show");
  els.drawer.root.setAttribute("aria-hidden", "true");
}

function parseTagsInput(v) {
  const raw = String(v || "").trim();
  if (!raw) return [];
  return raw.split(/[,\n]/).map(s => s.trim()).filter(Boolean).map(s => s.replace(/^#/, "")).slice(0, 16);
}

async function saveDrawer() {
  const id = state.drawer.id;
  if (!id) return;

  const text = String(els.drawer.text.value || "").trim();
  if (!text) {
    toast("warn", "Missing text", "Goal text cant be empty.");
    return;
  }

  const status = els.drawer.status.value;
  const priority = els.drawer.priority.value;
  const notes = String(els.drawer.notes.value || "");
  const tags = parseTagsInput(els.drawer.tags.value);

  const dueRaw = String(els.drawer.due.value || "").trim();
  const dueIso = dueRaw ? toIsoFromLocalDue(dueRaw) : null;

  const estRaw = String(els.drawer.est.value || "").trim();
  const est = estRaw ? parseInt(estRaw, 10) : null;

  const payload = { text, status, priority, notes, tags };
  if (dueRaw && dueIso) payload.due_at = dueIso;
  if (!dueRaw) payload.due_at = ""; // clear
  if (est !== null && !isNaN(est)) payload.estimate_minutes = est;

  try {
    setBusy(true);
    setStatus("Saving");
    await patchGoal(id, payload);
    await fetchAll({ quiet: true, force: true });
    toast("", "Saved", "Goal updated.");
    setStatus("Saved");
  } catch (err) {
    toast("bad", "Save failed", err.message || "Unknown error");
    setStatus(`Save failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

async function archiveDrawer() {
  const id = state.drawer.id;
  if (!id) return;
  try {
    setBusy(true);
    setStatus("Archiving");
    await patchGoal(id, { archived: true });
    closeDrawer();
    await fetchAll({ quiet: true, force: true });
    toast("", "Archived", "Goal archived (hidden).");
    setStatus("Archived");
  } catch (err) {
    toast("bad", "Archive failed", err.message || "Unknown error");
    setStatus(`Archive failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

async function deleteDrawer() {
  const id = state.drawer.id;
  if (!id) return;
  const g = getGoalById(id);
  if (!g) return;
  closeDrawer();
  await deleteGoal(g);
}

async function runDrawer() {
  const id = state.drawer.id;
  if (!id) return;
  await runGoal(id);
}

function wireDrawer() {
  els.drawer.close.addEventListener("click", closeDrawer);
  els.drawer.save.addEventListener("click", saveDrawer);
  els.drawer.archive.addEventListener("click", archiveDrawer);
  els.drawer.del.addEventListener("click", deleteDrawer);
  els.drawer.run.addEventListener("click", runDrawer);
}

/* Bulk actions */
async function bulkPatch(patchFn) {
  const ids = Array.from(state.selected);
  if (!ids.length) return;
  try {
    setBusy(true);
    setStatus("Applying bulk action");
    for (const id of ids) {
      await patchFn(id);
    }
    clearSelection();
    await fetchAll({ quiet: true, force: true });
    setStatus("Bulk action done");
  } catch (err) {
    toast("bad", "Bulk failed", err.message || "Unknown error");
    setStatus(`Bulk failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function wireBulk() {
  els.bulk.clear.addEventListener("click", clearSelection);
  els.bulk.moveOpen.addEventListener("click", () => bulkPatch(id => patchGoal(id, { status: "open" })));
  els.bulk.moveIP.addEventListener("click", () => bulkPatch(id => patchGoal(id, { status: "in_progress" })));
  els.bulk.moveDone.addEventListener("click", () => bulkPatch(id => patchGoal(id, { status: "done" })));
  els.bulk.priority.addEventListener("click", () => bulkPatch(async (id) => {
    const g = getGoalById(id);
    const next = cyclePriority(g ? g.priority : "medium");
    await patchGoal(id, { priority: next });
  }));
  els.bulk.run.addEventListener("click", async () => {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    setBusy(true);
    setStatus("Queueing selected goals");
    try {
      for (const id of ids) await runGoal(id);
      clearSelection();
      setStatus("Queued selected");
    } finally {
      setBusy(false);
    }
  });
  els.bulk.del.addEventListener("click", async () => {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    const ok = confirm(`Delete ${ids.length} goals?`);
    if (!ok) return;
    setBusy(true);
    setStatus("Deleting selected");
    try {
      for (const id of ids) {
        await apiFetch(API.del(id), { method: "DELETE" });
      }
      clearSelection();
      await fetchAll({ quiet: true, force: true });
      setStatus("Deleted selected");
      toast("warn", "Deleted", "Selected goals removed.");
    } catch (err) {
      toast("bad", "Delete failed", err.message || "Unknown error");
      setStatus(`Delete failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  });
}

/* Command palette */
const COMMANDS = [
  { id: "refresh", title: "Refresh", desc: "Fetch latest goals + stats", key: "R", run: () => fetchAll({ force: true }) },
  { id: "focus_high", title: "Focus: High Priority", desc: "Show only high priority goals", key: "", run: () => setActiveFilter("high") },
  { id: "focus_all", title: "Focus: All", desc: "Clear priority filter", key: "", run: () => setActiveFilter("all") },
  { id: "export_json", title: "Export JSON", desc: "Download all goals as JSON", key: "", run: () => exportJSON() },
  { id: "export_md", title: "Export Markdown", desc: "Download a clean markdown snapshot", key: "", run: () => exportMarkdown() },
  { id: "import_json", title: "Import JSON", desc: "Import goals from a JSON file", key: "", run: () => importJSON() },
  { id: "archive_done_30", title: "Archive: Done older than 30d", desc: "Hide stale done goals", key: "", run: () => archiveOldDone(30) },
  { id: "clear_search", title: "Clear Search", desc: "Reset search box", key: "", run: () => { els.search.value=""; state.search=""; savePrefs(); render(); } },
];

function openPalette() {
  els.pal.root.classList.add("show");
  els.pal.root.setAttribute("aria-hidden", "false");
  els.pal.input.value = "";
  renderPalette();
  setTimeout(() => els.pal.input.focus(), 0);
}
function closePalette() {
  els.pal.root.classList.remove("show");
  els.pal.root.setAttribute("aria-hidden", "true");
}

function renderPalette(filterText = "") {
  const q = String(filterText || "").trim().toLowerCase();
  els.pal.list.innerHTML = "";

  const items = COMMANDS.filter(c => {
    if (!q) return true;
    return (c.title + " " + c.desc).toLowerCase().includes(q);
  });

  for (const cmd of items) {
    const row = document.createElement("div");
    row.className = "palitem";
    const l = document.createElement("div");
    l.className = "l";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = cmd.title;
    const d = document.createElement("div");
    d.className = "d";
    d.textContent = cmd.desc;
    l.appendChild(t);
    l.appendChild(d);

    const k = document.createElement("div");
    k.className = "k";
    k.textContent = cmd.key ? cmd.key : "Enter";
    row.appendChild(l);
    row.appendChild(k);
    row.addEventListener("click", async () => {
      closePalette();
      try { await cmd.run(); } catch (err) { toast("bad", "Command failed", err.message || "Unknown error"); }
    });

    els.pal.list.appendChild(row);
  }

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "palitem";
    empty.textContent = "No commands match.";
    els.pal.list.appendChild(empty);
  }
}

function wirePalette() {
  els.btnPalette.addEventListener("click", openPalette);
  els.pal.backdrop.addEventListener("click", closePalette);
  els.pal.input.addEventListener("input", () => renderPalette(els.pal.input.value));
  els.pal.input.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { closePalette(); return; }
    if (e.key === "Enter") {
      // run first visible command
      const first = els.pal.list.querySelector(".palitem");
      if (first) first.click();
    }
  });
}

/* Export / Import */
function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

function exportJSON() {
  const all = allGoalsFlat();
  download(`thomas_goals_${new Date().toISOString().slice(0,10)}.json`, JSON.stringify(all, null, 2), "application/json");
  toast("", "Exported", "Downloaded JSON export.");
}

function exportMarkdown() {
  const lines = [];
  const now = new Date().toLocaleString();
  lines.push(`# Thomas Goals\n\nGenerated: ${now}\n`);
  for (const status of ["open","in_progress","done"]) {
    lines.push(`\n## ${status.replace("_"," ").toUpperCase()}\n`);
    const list = state.data[status] || [];
    for (const g of list) {
      if (g.archived) continue;
      const tags = (g.tags || []).map(t => `#${String(t).replace(/^#/, "")}`).join(" ");
      const due = g.due_at ? ` (due ${new Date(g.due_at).toLocaleString()})` : "";
      lines.push(`- **${(g.priority || "medium").toUpperCase()}** ${g.text}${due} ${tags}`.trim());
      if (g.notes) lines.push(`  - ${String(g.notes).replace(/\n/g, "\n  - ")}`);
    }
  }
  download(`thomas_goals_${new Date().toISOString().slice(0,10)}.md`, lines.join("\n"), "text/markdown");
  toast("", "Exported", "Downloaded Markdown snapshot.");
}

function importJSON() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json";
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const text = await file.text();
    let arr = null;
    try { arr = JSON.parse(text); } catch {}
    if (!Array.isArray(arr)) {
      toast("bad", "Import failed", "JSON must be an array of goal objects.");
      return;
    }
    setBusy(true);
    setStatus("Importing goals");
    try {
      for (const g of arr) {
        if (!g || !g.text) continue;
        const body = { text: String(g.text), priority: (g.priority || "medium") };
        if (g.tags) body.tags = Array.isArray(g.tags) ? g.tags : String(g.tags).split(",").map(s => s.trim()).filter(Boolean);
        if (g.due_at) body.due_at = String(g.due_at);
        if (g.notes) body.notes = String(g.notes);
        const r = await apiFetch(API.create, { method: "POST", body: JSON.stringify(body) });
        const created = r && r.json && r.json.goal ? r.json.goal : null;
        if (created && g.status && g.status !== "open") await patchGoal(created.id, { status: g.status });
      }
      await fetchAll({ quiet: true, force: true });
      toast("", "Imported", "Goals imported.");
      setStatus("Imported");
    } catch (err) {
      toast("bad", "Import failed", err.message || "Unknown error");
      setStatus(`Import failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  });
  input.click();
}

/* Archive helper */
async function archiveOldDone(days) {
  const cutoff = Date.now() - days * 24 * 3600 * 1000;
  const done = state.data.done || [];
  const targets = done.filter(g => {
    const doneAt = g.done_at ? new Date(g.done_at).getTime() : (g.created ? new Date(g.created).getTime() : 0);
    return doneAt && doneAt < cutoff && !g.archived;
  });
  if (!targets.length) {
    toast("", "Archive", `No done goals older than ${days}d.`);
    return;
  }
  const ok = confirm(`Archive ${targets.length} done goals older than ${days} days?`);
  if (!ok) return;

  await bulkPatch(async (id) => patchGoal(id, { archived: true }));
}

/* Refresh */
function wireRefresh() {
  els.btnRefresh.addEventListener("click", () => fetchAll({ force: true }));
}

function wireShortcuts() {
  document.addEventListener("keydown", (e) => {
    const paletteOpen = els.pal.root.classList.contains("show");
    if (paletteOpen) return;

    const drawerOpen = els.drawer.root.classList.contains("show");
    const tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";

    if (drawerOpen) {
      if (e.key === "Escape") closeDrawer();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "enter") saveDrawer();
      return;
    }

    if (e.key === "Escape") {
      els.addwrap.classList.remove("show");
      clearSelection();
      return;
    }

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
      return;
    }

    if (!typing) {
      if (e.key === "/") {
        e.preventDefault();
        els.search.focus();
        return;
      }
      if (e.key.toLowerCase() === "n") {
        e.preventDefault();
        toggleAdd();
        return;
      }
      if (e.key.toLowerCase() === "r") {
        e.preventDefault();
        fetchAll({ force: true });
        return;
      }
    }
  });
}

function wireQuickAddAndSearchFocus() {
  els.search.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { els.search.blur(); }
  });
}

function wireEverything() {
  wireDnD();
  wireFilter();
  wireSearch();
  wireAddInline();
  wireQuickAdd();
  wireRefresh();
  wireDrawer();
  wireBulk();
  wirePalette();
  wireShortcuts();
  wireQuickAddAndSearchFocus();

  // clicking empty space clears selection (but not when dragging)
  document.addEventListener("click", (e) => {
    if (e.target.closest(".card") || e.target.closest(".drawer") || e.target.closest(".palette") || e.target.closest(".bulkbar")) return;
    if (e.target.closest(".btn") || e.target.closest(".pillbar") || e.target.closest(".searchwrap") || e.target.closest(".quickadd")) return;
    if (state.selected.size) clearSelection();
  });
}

function startPolling() {
  setInterval(() => {
    fetchAll({ quiet: true });
  }, 30_000);
}

(function init() {
  loadPrefs();
  // instant UI from cache
  loadCache();
  loadStatsCache();

  wireEverything();

  setActiveFilter(state.filter || "all");
  els.search.value = state.search || "";
  setStatus("Loading");
  fetchAll({ force: true });
  startPolling();
})();
