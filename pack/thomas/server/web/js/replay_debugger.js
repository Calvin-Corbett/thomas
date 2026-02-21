// thomas/server/web/js/replay_debugger.js
(function () {
  const $ = (id) => document.getElementById(id);

  function qs(name) {
    const url = new URL(window.location.href);
    return url.searchParams.get(name);
  }

  const state = {
    runId: qs("run_id") || "",
    total: 0,
    events: [],
    filtered: [],
    types: new Set(),
    enabledTypes: new Set(),
    search: "",
    index: 0,
    playing: false,
    timer: null,
    speed: 1,
    pageStart: 0,
    pageSize: 500,
  };

  function fmtJson(obj) {
    return JSON.stringify(obj, null, 2);
  }

  async function apiJson(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${txt}`);
    }
    return await res.json();
  }

  async function loadPage(start) {
    if (!state.runId) throw new Error("Missing run_id query param");
    state.pageStart = start;
    const data = await apiJson(`/api/runs/${encodeURIComponent(state.runId)}/events?start=${start}&limit=${state.pageSize}`);
    state.total = data.total || 0;
    state.events = data.events || [];
    state.types = new Set(state.events.map((e) => e.event_type).filter(Boolean));
    if (state.enabledTypes.size === 0) {
      state.enabledTypes = new Set(state.types);
    } else {
      for (const t of state.types) state.enabledTypes.add(t);
    }
    $("total").textContent = String(state.total);
    $("scrubber").max = String(Math.max(0, state.total - 1));
    renderFilters();
    applyFilters();
  }

  function renderFilters() {
    const wrap = $("filters");
    wrap.innerHTML = "";
    const types = Array.from(state.types).sort();
    for (const t of types) {
      const chip = document.createElement("label");
      chip.className = "filterChip";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.enabledTypes.has(t);
      cb.addEventListener("change", () => {
        if (cb.checked) state.enabledTypes.add(t);
        else state.enabledTypes.delete(t);
        applyFilters();
      });
      const span = document.createElement("span");
      span.textContent = t;
      chip.appendChild(cb);
      chip.appendChild(span);
      wrap.appendChild(chip);
    }
  }

  function applyFilters() {
    const s = (state.search || "").toLowerCase();
    state.filtered = state.events.filter((e) => {
      if (e.event_type && !state.enabledTypes.has(e.event_type)) return false;
      if (!s) return true;
      const blob = (e.event_type || "") + " " + JSON.stringify(e.payload || {});
      return blob.toLowerCase().includes(s);
    });
    renderEventList();
    updateIndexUI(state.index);
  }

  function renderEventList() {
    const list = $("eventList");
    list.innerHTML = "";
    for (const e of state.filtered) {
      const row = document.createElement("div");
      row.className = "eventRow";
      row.dataset.index = String(e.index);
      const left = document.createElement("div");
      left.className = "eventMeta";
      const t = document.createElement("div");
      t.className = "eventType";
      t.textContent = e.event_type || "(no type)";
      const s = document.createElement("div");
      s.className = "eventSmall";
      s.textContent = `idx ${e.index} · seq ${e.seq}${e.t_ms != null ? " · t_ms " + e.t_ms : ""}`;
      left.appendChild(t);
      left.appendChild(s);

      const right = document.createElement("div");
      right.className = "eventSmall";
      right.textContent = "";

      row.appendChild(left);
      row.appendChild(right);
      row.addEventListener("click", () => {
        setIndex(e.index).catch(console.error);
      });
      list.appendChild(row);
    }
    highlightActiveRow();
  }

  function highlightActiveRow() {
    const rows = $("eventList").querySelectorAll(".eventRow");
    rows.forEach((r) => {
      const idx = Number(r.dataset.index || "0");
      r.classList.toggle("active", idx === state.index);
    });
  }

  function findEventInPage(index) {
    return state.events.find((e) => e.index === index) || null;
  }

  async function ensureIndexLoaded(index) {
    if (index < 0) index = 0;
    if (index >= state.total && state.total > 0) index = state.total - 1;
    const pageStart = Math.floor(index / state.pageSize) * state.pageSize;
    if (pageStart !== state.pageStart || state.events.length === 0) {
      await loadPage(pageStart);
    }
  }

  async function setIndex(index) {
    await ensureIndexLoaded(index);
    state.index = index;
    $("scrubber").value = String(index);
    updateIndexUI(index);
  }

  function updateIndexUI(index) {
    $("idx").textContent = String(index);
    const ev = findEventInPage(index);
    if (ev) {
      $("etype").textContent = ev.event_type || "-";
      $("tms").textContent = ev.t_ms != null ? String(ev.t_ms) : "-";
      $("detail").textContent = fmtJson(ev);
    } else {
      $("etype").textContent = "-";
      $("tms").textContent = "-";
      $("detail").textContent = "(event not in this page)";
    }
    highlightActiveRow();
  }

  function stopPlaying() {
    state.playing = false;
    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    $("play").disabled = false;
    $("pause").disabled = true;
  }

  async function tick() {
    if (!state.playing) return;
    const next = state.index + 1;
    if (next >= state.total) {
      stopPlaying();
      return;
    }
    await setIndex(next);

    const cur = findEventInPage(state.index);
    const prev = findEventInPage(state.index - 1);
    let delay = 120;
    if (state.speed === 0) delay = 0;
    else if (cur && prev && cur.t_ms != null && prev.t_ms != null) {
      delay = Math.max(0, (cur.t_ms - prev.t_ms) / state.speed);
    } else {
      delay = delay / (state.speed || 1);
    }

    state.timer = setTimeout(() => { tick().catch(console.error); }, delay);
  }

  async function play() {
    state.speed = Number($("speed").value || "1");
    state.playing = true;
    $("play").disabled = true;
    $("pause").disabled = false;
    await tick();
  }

  async function step(delta) {
    const res = await apiJson(`/api/runs/${encodeURIComponent(state.runId)}/replay/step`, {
      method: "POST",
      body: JSON.stringify({ index: state.index, delta }),
    });
    if (res && res.ok && res.event) {
      await setIndex(res.event.index);
    }
  }

  function exportJson() {
    const url = `/api/runs/${encodeURIComponent(state.runId)}/export.json`;
    window.open(url, "_blank");
  }

  async function init() {
    $("subtitle").textContent = `run ${state.runId || "(missing)"}`;
    await loadPage(0);
    await setIndex(0);

    $("scrubber").addEventListener("input", async (ev) => {
      const i = Number(ev.target.value || "0");
      await setIndex(i);
    });

    $("search").addEventListener("input", (ev) => {
      state.search = ev.target.value || "";
      applyFilters();
    });

    $("play").addEventListener("click", () => { play().catch(console.error); });
    $("pause").addEventListener("click", () => { stopPlaying(); });
    $("stepBack").addEventListener("click", () => { step(-1).catch(console.error); });
    $("stepFwd").addEventListener("click", () => { step(1).catch(console.error); });
    $("exportJson").addEventListener("click", () => { exportJson(); });
    $("speed").addEventListener("change", () => { state.speed = Number($("speed").value || "1"); });
  }

  init().catch((e) => {
    console.error(e);
    $("detail").textContent = String(e && e.stack ? e.stack : e);
  });
})();
