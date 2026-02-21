// thomas/server/web/static/search_overlay.js
(function () {
  const HL_START = "\u0001";
  const HL_END = "\u0002";

  const state = {
    open: false,
    lastQuery: "",
    debounceSearch: null,
    debounceSuggest: null,
    abort: null,

    selected: -1,
    results: [],
    bookmarks: new Set(),
    bookmarkLabels: new Map(),

    sort: "relevance",
    channel: "",
    since: "",
    before: "",
    hasTools: null, // null|true
    scopes: new Set(["all"]), // all/user/assistant/tools

    sugOpen: false,
    suggestions: [],
    sugSelected: -1,

    offset: 0,
    limit: 40,

    previewCache: new Map(), // turn_id -> context[]
    previewAbort: null,

    saved: [], // list of saved searches
    savedOpen: false,
  };

  function $(sel, root = document) { return root.querySelector(sel); }
  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else e.setAttribute(k, v);
    }
    for (const c of children) e.appendChild(c);
    return e;
  }

  function findHeaderMount() {
    const candidates = [
      "#header-actions",".header-actions",".topbar-actions",".toolbar-actions",
      "header .actions","header",".topbar",".toolbar"
    ];
    for (const sel of candidates) {
      const n = $(sel);
      if (n) return n;
    }
    return document.body;
  }

  function ensureButton() {
    if ($("#thomas-search-btn")) return;
    const mount = findHeaderMount();
    const btn = el("button", { id:"thomas-search-btn", title:"Search (Ctrl+K)", "aria-label":"Search" });
    btn.textContent = "";
    btn.addEventListener("click", toggle);
    mount.appendChild(btn);
  }

  function ensureOverlay() {
    if ($("#thomas-search-overlay")) return;

    const overlay = el("div", { id:"thomas-search-overlay", "data-open":"false" }, [
      el("div", { class:"ts-backdrop" }),
      el("div", { class:"ts-panel" }, [
        el("div", { class:"ts-top" }, [
          el("div", { class:"ts-inputwrap" }, [
            el("input", { class:"ts-input", type:"text", placeholder:"Search conversations", autocomplete:"off", spellcheck:"false", id:"thomas-search-input" }),
            el("div", { class:"ts-suggest", id:"thomas-search-suggest", "data-open":"false" }),
            el("div", { class:"ts-help", id:"thomas-search-help", text:'Pro tip: Ctrl+K opens this anywhere. Use quotes for phrases. Toggle scopes for precision.' }),
          ]),
          el("div", { class:"ts-kbd", text:"Ctrl+K" }),
          el("div", { class:"ts-kbd", text:"Esc" }),
        ]),
        el("div", { class:"ts-filters" }, [
          el("select", { class:"ts-select", id:"thomas-search-channel" }, [ el("option", { value:"", text:"All channels" }) ]),
          el("input", { class:"ts-date", id:"thomas-search-since", type:"date", title:"Since" }),
          el("input", { class:"ts-date", id:"thomas-search-before", type:"date", title:"Before" }),

          el("span", { class:"ts-chip", id:"ts-scope-all", "data-on":"true", title:"Search everywhere" }, [ el("span",{text:"All"}) ]),
          el("span", { class:"ts-chip", id:"ts-scope-user", "data-on":"false", title:"Search user messages" }, [ el("span",{text:"User"}) ]),
          el("span", { class:"ts-chip", id:"ts-scope-assistant", "data-on":"false", title:"Search assistant messages" }, [ el("span",{text:"Assistant"}) ]),
          el("span", { class:"ts-chip", id:"ts-scope-tools", "data-on":"false", title:"Search tool calls" }, [ el("span",{text:"Tools"}) ]),

          el("span", { class:"ts-chip", id:"ts-tools-only", "data-on":"false", title:"Only turns with tools" }, [ el("span",{text:"Has tools"}) ]),

          el("button", { class:"ts-btn", id:"thomas-search-sort", text:"Sort: relevance" }),
          el("button", { class:"ts-btn", id:"thomas-search-reindex", text:"Reindex" }),

          el("button", { class:"ts-btn", id:"thomas-search-savedbtn", text:"Saved" }),
          el("button", { class:"ts-btn", id:"thomas-search-savebtn", text:"Save this" }),
        ]),
        el("div", { class:"ts-body" }, [
          el("div", { class:"ts-results", id:"thomas-search-results" }),
          el("div", { class:"ts-preview", id:"thomas-search-preview" }, [
            el("h3", { text:"Preview" }),
            el("div", { class:"ts-pmeta", id:"thomas-search-pmeta", text:"Select a result to see context." }),
          ]),
        ]),
        el("div", { class:"ts-footer" }, [
          el("div", { class:"ts-pager" }, [
            el("button", { class:"ts-pagerbtn", id:"thomas-search-prev", text:"Prev" }),
            el("button", { class:"ts-pagerbtn", id:"thomas-search-next", text:"Next" }),
            el("span", { class:"ts-pageinfo", id:"thomas-search-pageinfo", text:"Page 1" }),
          ]),
          el("div", { class:"ts-pageinfo", id:"thomas-search-status", text:"" }),
        ]),
      ]),
    ]);

    overlay.addEventListener("click", (e) => {
      if (e.target.classList.contains("ts-backdrop")) close();
    });

    document.body.appendChild(overlay);

    const input = $("#thomas-search-input");
    input.addEventListener("input", () => { state.offset = 0; scheduleSearch(input.value); });
    input.addEventListener("keydown", onInputKeydown);

    $("#thomas-search-since").addEventListener("change", () => { state.since = $("#thomas-search-since").value || ""; state.offset = 0; scheduleSearch(input.value); });
    $("#thomas-search-before").addEventListener("change", () => { state.before = $("#thomas-search-before").value || ""; state.offset = 0; scheduleSearch(input.value); });
    $("#thomas-search-channel").addEventListener("change", () => { state.channel = $("#thomas-search-channel").value || ""; state.offset = 0; scheduleSearch(input.value); });

    $("#thomas-search-sort").addEventListener("click", () => {
      state.sort = state.sort === "relevance" ? "newest" : "relevance";
      $("#thomas-search-sort").textContent = state.sort === "relevance" ? "Sort: relevance" : "Sort: newest";
      state.offset = 0;
      scheduleSearch(input.value);
    });

    $("#thomas-search-reindex").addEventListener("click", async () => {
      const b = $("#thomas-search-reindex");
      b.textContent = "Reindexing";
      b.disabled = true;
      try { await fetch("/api/search/reindex", { method:"POST" }); } catch (_) {}
      b.textContent = "Reindex";
      b.disabled = false;
      state.offset = 0;
      await refreshBookmarks();
      scheduleSearch($("#thomas-search-input").value);
      await refreshSaved();
      await loadStatus();
    });

    $("#thomas-search-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); scheduleSearch($("#thomas-search-input").value); });
    $("#thomas-search-next").addEventListener("click", () => { state.offset = state.offset + state.limit; scheduleSearch($("#thomas-search-input").value); });

    // Scope chips
    wireScopeChip("all", "#ts-scope-all");
    wireScopeChip("user", "#ts-scope-user");
    wireScopeChip("assistant", "#ts-scope-assistant");
    wireScopeChip("tools", "#ts-scope-tools");

    $("#ts-tools-only").addEventListener("click", () => {
      const on = state.hasTools === true ? false : true;
      state.hasTools = on ? true : null;
      $("#ts-tools-only").setAttribute("data-on", on ? "true" : "false");
      state.offset = 0;
      scheduleSearch($("#thomas-search-input").value);
    });

    $("#thomas-search-savedbtn").addEventListener("click", () => openSavedMenu());
    $("#thomas-search-savebtn").addEventListener("click", () => saveCurrentSearch());

    loadChannels();
    loadStatus();
    refreshBookmarks();
    refreshSaved();
  }

  function wireScopeChip(scope, sel) {
    const chip = $(sel);
    chip.addEventListener("click", () => {
      if (scope === "all") {
        state.scopes = new Set(["all"]);
        setScopeChipStates();
      } else {
        // toggle individual scope
        if (state.scopes.has("all")) state.scopes.delete("all");
        if (state.scopes.has(scope)) state.scopes.delete(scope);
        else state.scopes.add(scope);
        if (state.scopes.size === 0) state.scopes.add("all");
        setScopeChipStates();
      }
      state.offset = 0;
      scheduleSearch($("#thomas-search-input").value);
    });
  }

  function setScopeChipStates() {
    const onAll = state.scopes.has("all");
    $("#ts-scope-all").setAttribute("data-on", onAll ? "true" : "false");
    $("#ts-scope-user").setAttribute("data-on", (!onAll && state.scopes.has("user")) ? "true" : "false");
    $("#ts-scope-assistant").setAttribute("data-on", (!onAll && state.scopes.has("assistant")) ? "true" : "false");
    $("#ts-scope-tools").setAttribute("data-on", (!onAll && state.scopes.has("tools")) ? "true" : "false");
  }

  async function loadStatus() {
    const n = $("#thomas-search-status");
    if (!n) return;
    try {
      const res = await fetch("/api/search/status");
      if (!res.ok) return;
      const s = await res.json();
      n.textContent = `Indexed ${s.indexed_rows}   ${s.bookmarks}   ${s.saved_searches}`;
    } catch (_) {}
  }

  async function loadChannels() {
    const sel = $("#thomas-search-channel");
    if (!sel) return;
    const existing = new Set(Array.from(sel.options).map((o) => o.value));
    try {
      const res = await fetch("/api/search/channels");
      if (!res.ok) return;
      const chans = await res.json();
      if (!Array.isArray(chans)) return;
      chans.forEach((c) => {
        const v = String(c || "").trim();
        if (!v || existing.has(v)) return;
        sel.appendChild(el("option", { value: v, text: v }));
        existing.add(v);
      });
    } catch (_) {}
  }

  async function refreshBookmarks() {
    state.bookmarks = new Set();
    state.bookmarkLabels = new Map();
    try {
      const res = await fetch("/api/search/bookmarks");
      if (!res.ok) return;
      const bms = await res.json();
      if (!Array.isArray(bms)) return;
      bms.forEach((b) => {
        state.bookmarks.add(String(b.turn_id));
        state.bookmarkLabels.set(String(b.turn_id), String(b.label || ""));
      });
    } catch (_) {}
  }

  async function refreshSaved() {
    state.saved = [];
    try {
      const res = await fetch("/api/search/saved");
      if (!res.ok) return;
      const ss = await res.json();
      if (!Array.isArray(ss)) return;
      state.saved = ss;
    } catch (_) {}
  }

  function open() {
    ensureOverlay();
    state.open = true;
    $("#thomas-search-overlay").setAttribute("data-open","true");
    const input = $("#thomas-search-input");
    input.focus();
    input.select();
    setScopeChipStates();
  }
  function close() {
    state.open = false;
    const overlay = $("#thomas-search-overlay");
    if (overlay) overlay.setAttribute("data-open","false");
    state.selected = -1;
    closeSuggest();
    closeSavedMenu();
  }
  function toggle() { state.open ? close() : open(); }

  function scheduleSearch(q) {
    clearTimeout(state.debounceSearch);
    state.debounceSearch = setTimeout(() => runSearch(q), 140);
    clearTimeout(state.debounceSuggest);
    state.debounceSuggest = setTimeout(() => runSuggest(q), 90);
  }

  function renderMarkedText(container, marked) {
    container.textContent = "";
    const s = String(marked || "");
    if (!s) return;
    let i = 0;
    while (i < s.length) {
      const a = s.indexOf(HL_START, i);
      if (a === -1) { container.appendChild(document.createTextNode(s.slice(i))); break; }
      if (a > i) container.appendChild(document.createTextNode(s.slice(i, a)));
      const b = s.indexOf(HL_END, a + 1);
      if (b === -1) { container.appendChild(document.createTextNode(s.slice(a))); break; }
      const mark = document.createElement("mark");
      mark.textContent = s.slice(a + 1, b);
      container.appendChild(mark);
      i = b + 1;
    }
  }

  async function runSuggest(q) {
    const s = (q || "").trim();
    if (s.length < 2) { closeSuggest(); return; }
    try {
      const res = await fetch(`/api/search/suggest?q=${encodeURIComponent(s)}`);
      if (!res.ok) return closeSuggest();
      const data = await res.json();
      if (!Array.isArray(data) || !data.length) return closeSuggest();
      state.suggestions = data.slice(0, 8);
      state.sugSelected = -1;
      openSuggest();
      renderSuggest();
    } catch (_) { closeSuggest(); }
  }

  function openSuggest() {
    const box = $("#thomas-search-suggest"); if (!box) return;
    state.sugOpen = true; box.setAttribute("data-open","true");
  }
  function closeSuggest() {
    const box = $("#thomas-search-suggest"); if (!box) return;
    state.sugOpen = false; box.setAttribute("data-open","false"); box.innerHTML = "";
  }
  function renderSuggest() {
    const box = $("#thomas-search-suggest");
    const input = $("#thomas-search-input");
    if (!box || !input) return;
    box.innerHTML = "";
    state.suggestions.forEach((sug, idx) => {
      const row = el("div", { class:"ts-sugrow" });
      if (idx === state.sugSelected) row.style.background = "rgba(255,255,255,0.06)";
      row.textContent = String(sug);
      row.addEventListener("click", () => {
        input.value = String(sug);
        closeSuggest();
        state.offset = 0;
        scheduleSearch(input.value);
        input.focus();
      });
      box.appendChild(row);
    });
  }

  async function runSearch(q) {
    const query = (q || "").trim();
    state.lastQuery = query;
    state.selected = -1;

    const resultsEl = $("#thomas-search-results");
    const previewEl = $("#thomas-search-preview");
    const pmetaEl = $("#thomas-search-pmeta");
    const pageInfo = $("#thomas-search-pageinfo");

    if (state.abort) state.abort.abort();
    state.abort = new AbortController();

    if (!query) {
      state.results = [];
      if (pageInfo) pageInfo.textContent = "Page 1";
      if (pmetaEl) pmetaEl.textContent = "Select a result to see context.";
      if (previewEl) previewEl.innerHTML = `<h3>Preview</h3><div class="ts-pmeta" id="thomas-search-pmeta">Select a result to see context.</div>`;
      renderResults();
      return;
    }

    if (resultsEl) resultsEl.innerHTML = `<div style="padding:14px;opacity:0.75;">Searching</div>`;

    try {
      const params = new URLSearchParams();
      params.set("q", query);
      params.set("limit", String(state.limit));
      params.set("offset", String(state.offset));
      if (state.channel) params.set("channel", state.channel);
      if (state.since) params.set("since", state.since);
      if (state.before) params.set("before", state.before);
      if (state.hasTools === true) params.set("has_tools", "true");
      params.set("sort", state.sort);
      params.set("scope", Array.from(state.scopes).join(","));

      const res = await fetch(`/api/search?${params.toString()}`, { signal: state.abort.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (state.lastQuery !== query) return;

      state.results = Array.isArray(data) ? data : [];
      renderResults();

      const page = Math.floor(state.offset / state.limit) + 1;
      if (pageInfo) pageInfo.textContent = `Page ${page}`;

      // auto-select first result for preview
      if (state.results.length) {
        state.selected = 0;
        renderResults();
        await updatePreview(state.results[0]);
      }
    } catch (e) {
      if (e.name === "AbortError") return;
      if (resultsEl) resultsEl.innerHTML = `<div style="padding:14px;opacity:0.75;">Search failed.</div>`;
    }
  }

  function renderResults() {
    const root = $("#thomas-search-results");
    if (!root) return;

    if (!state.results.length) {
      root.innerHTML = `<div style="padding:14px;opacity:0.75;">No results.</div>`;
      return;
    }

    root.innerHTML = "";
    state.results.forEach((r, idx) => {
      const row = el("div", { class:"ts-row", "data-idx": String(idx) });
      if (idx === state.selected) {
        row.style.outline = "2px solid rgba(255,255,255,0.12)";
        row.style.outlineOffset = "-2px";
      }

      const left = el("div", {}, []);
      const meta = el("div", { class:"ts-meta" }, [
        el("span", { class:"ts-tag", text: (r.channel || "unknown").toString() }),
        el("span", { text: (r.ts || "").toString() }),
        el("span", { text: `score ${(r.score ?? 0).toFixed(3)}` }),
      ]);

      const userLine = el("div", { class:"ts-user" });
      renderMarkedText(userLine, r.user_snippet || r.user_msg || "");

      const snip = el("div", { class:"ts-snip" });
      renderMarkedText(snip, r.assistant_snippet || r.assistant_snippet_plain || "");

      left.appendChild(meta);
      left.appendChild(userLine);
      left.appendChild(snip);

      const star = el("button", { class:"ts-star", title:"Bookmark (B)" });
      const on = state.bookmarks.has(String(r.turn_id));
      star.setAttribute("data-on", on ? "true" : "false");
      star.textContent = on ? "" : "";
      star.addEventListener("click", async (e) => {
        e.stopPropagation();
        await toggleBookmark(r);
        star.setAttribute("data-on", state.bookmarks.has(String(r.turn_id)) ? "true" : "false");
        star.textContent = state.bookmarks.has(String(r.turn_id)) ? "" : "";
        await loadStatus();
      });

      row.appendChild(left);
      row.appendChild(star);

      row.addEventListener("mouseenter", async () => {
        state.selected = idx;
        renderResults();
        await updatePreview(r);
      });
      row.addEventListener("click", async () => {
        state.selected = idx;
        renderResults();
        await jumpTo(r);
      });

      root.appendChild(row);
    });
  }

  async function updatePreview(result) {
    const preview = $("#thomas-search-preview");
    if (!preview) return;

    const tid = String(result.turn_id || "");
    if (!tid) return;

    if (state.previewAbort) state.previewAbort.abort();
    state.previewAbort = new AbortController();

    if (state.previewCache.has(tid)) {
      renderPreview(result, state.previewCache.get(tid));
      return;
    }

    preview.innerHTML = `<h3>Preview</h3><div class="ts-pmeta">Loading context</div>`;

    try {
      const res = await fetch(`/api/search/context?turn_id=${encodeURIComponent(tid)}&window=2`, { signal: state.previewAbort.signal });
      if (!res.ok) throw new Error("bad");
      const ctx = await res.json();
      state.previewCache.set(tid, ctx);
      renderPreview(result, ctx);
    } catch (e) {
      if (e.name === "AbortError") return;
      preview.innerHTML = `<h3>Preview</h3><div class="ts-pmeta">Could not load context.</div>`;
    }
  }

  function renderPreview(hit, ctx) {
    const preview = $("#thomas-search-preview");
    if (!preview) return;

    preview.innerHTML = "";
    preview.appendChild(el("h3", { text:"Preview" }));

    const meta = el("div", { class:"ts-pmeta" });
    meta.textContent = `${hit.ts || ""}  ${hit.channel || ""}  id ${hit.turn_id || ""}`;
    preview.appendChild(meta);

    if (!Array.isArray(ctx) || !ctx.length) {
      preview.appendChild(el("div", { class:"ts-pmeta", text:"No context available." }));
      return;
    }

    ctx.forEach((t) => {
      const turn = el("div", { class:"ts-turn" });
      const m = el("div", { class:"ts-pmeta" });
      m.textContent = `${t.ts}  ${t.channel}  pos ${t.turn_pos}`;
      const u = el("div", { class:"ts-u" }); u.textContent = t.user_msg || "";
      const a = el("div", { class:"ts-a" }); a.textContent = t.assistant_msg || "";
      turn.appendChild(m); turn.appendChild(u); turn.appendChild(a);
      if (t.tool_calls && String(t.tool_calls).trim() && String(t.tool_calls).trim() !== "[]") {
        const tools = el("div", { class:"ts-tools" }); tools.textContent = t.tool_calls;
        turn.appendChild(tools);
      }
      preview.appendChild(turn);
    });

    const actionRow = el("div", { style:"display:flex;gap:10px;margin-top:10px;align-items:center;" });
    const openBtn = el("button", { class:"ts-btn", text:"Open this hit" });
    openBtn.addEventListener("click", () => jumpTo(hit));
    const copyBtn = el("button", { class:"ts-btn", text:"Copy link" });
    copyBtn.addEventListener("click", () => copyLink(hit));
    actionRow.appendChild(openBtn);
    actionRow.appendChild(copyBtn);
    preview.appendChild(actionRow);
  }

  async function toggleBookmark(hit) {
    const tid = String(hit.turn_id || "");
    if (!tid) return;
    const on = state.bookmarks.has(tid);
    try {
      if (on) {
        await fetch(`/api/search/bookmarks/${encodeURIComponent(tid)}`, { method:"DELETE" });
        state.bookmarks.delete(tid);
      } else {
        await fetch(`/api/search/bookmarks`, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ turn_id: tid, label: "" }) });
        state.bookmarks.add(tid);
      }
    } catch (_) {}
  }

  function cssEscape(s) { return (s || "").replace(/["\\]/g, "\\$&"); }

  function findTurnNode(result) {
    const tid = (result.turn_id || "").toString();
    const ts = (result.ts || "").toString();
    const selectors = [
      `[data-turn-id="${cssEscape(tid)}"]`,
      `#turnid-${cssEscape(tid)}`,
      `[data-turn-ts="${cssEscape(ts)}"]`,
      `[data-ts="${cssEscape(ts)}"]`,
      `#turn-${cssEscape(ts)}`,
    ];
    for (const sel of selectors) {
      const node = document.querySelector(sel);
      if (node) return node;
    }
    return null;
  }

  async function jumpTo(result) {
    const node = findTurnNode(result);
    if (node) {
      close();
      node.scrollIntoView({ behavior:"smooth", block:"center" });
      node.classList.add("thomas-search-hit");
      setTimeout(() => node.classList.remove("thomas-search-hit"), 1200);
      return;
    }

    // Fetch context and emit event for app integration
    const tid = (result.turn_id || "").toString();
    try {
      const res = await fetch(`/api/search/context?turn_id=${encodeURIComponent(tid)}&window=2`);
      if (res.ok) {
        const ctx = await res.json();
        window.dispatchEvent(new CustomEvent("thomas:search:jump", { detail: { hit: result, context: ctx } }));
        // if app didn't handle it, show a fallback overlay (same as v3 style but smaller)
        showFallbackContext(result, ctx);
        close();
        return;
      }
    } catch (_) {}

    // Last fallback: URL param
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("jump_turn_id", tid);
      u.searchParams.set("jump_ts", (result.ts || "").toString());
      window.location.href = u.toString();
    } catch (_) {}

    close();
  }

  function showFallbackContext(hit, ctx) {
    if (window.__thomasSearchHandled) { window.__thomasSearchHandled = false; return; }
    if (!Array.isArray(ctx) || !ctx.length) return;

    const overlay = document.createElement("div");
    overlay.style.position = "fixed";
    overlay.style.inset = "0";
    overlay.style.zIndex = "10000";
    overlay.style.background = "rgba(0,0,0,0.55)";
    overlay.addEventListener("click", () => overlay.remove());

    const card = document.createElement("div");
    card.style.width = "min(96vw, 900px)";
    card.style.margin = "10vh auto 0 auto";
    card.style.background = "rgba(18,18,20,0.98)";
    card.style.border = "1px solid rgba(255,255,255,0.10)";
    card.style.borderRadius = "14px";
    card.style.padding = "14px";
    card.style.boxShadow = "0 20px 60px rgba(0,0,0,0.50)";
    card.addEventListener("click", (e) => e.stopPropagation());

    const title = document.createElement("div");
    title.style.display = "flex";
    title.style.justifyContent = "space-between";
    title.style.alignItems = "center";
    title.style.marginBottom = "10px";
    title.innerHTML = `<div style="color:white;opacity:.92;font-size:14px;">Context around hit</div>`;

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close";
    closeBtn.className = "ts-btn";
    closeBtn.addEventListener("click", () => overlay.remove());
    title.appendChild(closeBtn);

    const body = document.createElement("div");
    body.style.maxHeight = "60vh";
    body.style.overflow = "auto";
    body.style.borderTop = "1px solid rgba(255,255,255,0.08)";
    body.style.paddingTop = "10px";

    ctx.forEach((t) => {
      const row = document.createElement("div");
      row.style.padding = "10px 0";
      row.style.borderBottom = "1px solid rgba(255,255,255,0.06)";

      const meta = document.createElement("div");
      meta.style.color = "rgba(255,255,255,0.70)";
      meta.style.fontSize = "12px";
      meta.textContent = `${t.ts}  ${t.channel}  pos ${t.turn_pos}`;

      const u = document.createElement("div");
      u.style.color = "rgba(255,255,255,0.92)";
      u.style.marginTop = "6px";
      u.style.whiteSpace = "pre-wrap";
      u.textContent = t.user_msg || "";

      const a = document.createElement("div");
      a.style.color = "rgba(255,255,255,0.78)";
      a.style.marginTop = "6px";
      a.style.whiteSpace = "pre-wrap";
      a.textContent = t.assistant_msg || "";

      row.appendChild(meta);
      row.appendChild(u);
      row.appendChild(a);
      body.appendChild(row);
    });

    card.appendChild(title);
    card.appendChild(body);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
  }

  async function copyLink(hit) {
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("jump_turn_id", String(hit.turn_id || ""));
      u.searchParams.set("jump_ts", String(hit.ts || ""));
      await navigator.clipboard.writeText(u.toString());
    } catch (_) {}
  }

  function onInputKeydown(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }

    // Saved menu dismiss
    if (e.key === "Escape" && state.savedOpen) { e.preventDefault(); closeSavedMenu(); return; }

    if (state.sugOpen) {
      if (e.key === "ArrowDown") { e.preventDefault(); state.sugSelected = Math.min(state.suggestions.length - 1, state.sugSelected + 1); renderSuggest(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); state.sugSelected = Math.max(-1, state.sugSelected - 1); renderSuggest(); return; }
      if (e.key === "Enter" && state.sugSelected >= 0) {
        e.preventDefault();
        const input = $("#thomas-search-input");
        input.value = String(state.suggestions[state.sugSelected]);
        closeSuggest();
        state.offset = 0;
        scheduleSearch(input.value);
        return;
      }
    }

    if (e.key === "ArrowDown") { e.preventDefault(); moveSelection(1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); moveSelection(-1); return; }

    if (e.key === "Enter") {
      if (state.selected >= 0 && state.selected < state.results.length) {
        e.preventDefault();
        jumpTo(state.results[state.selected]);
      }
    }

    // Bookmark shortcut
    if (e.key.toLowerCase() === "b") {
      if (state.selected >= 0 && state.selected < state.results.length) {
        e.preventDefault();
        toggleBookmark(state.results[state.selected]).then(loadStatus).then(() => renderResults());
      }
    }

    // Save shortcut
    if (e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveCurrentSearch();
    }
  }

  function moveSelection(delta) {
    if (!state.results.length) return;
    const next = Math.max(0, Math.min(state.results.length - 1, state.selected + delta));
    state.selected = next;
    renderResults();
    const rows = document.querySelectorAll("#thomas-search-results .ts-row");
    if (rows[next]) rows[next].scrollIntoView({ block:"nearest" });
    updatePreview(state.results[next]);
  }

  // Saved searches UI (lightweight, no fancy portal libs)
  function openSavedMenu() {
    closeSavedMenu();
    state.savedOpen = true;

    const btn = $("#thomas-search-savedbtn");
    const rect = btn.getBoundingClientRect();

    const menu = document.createElement("div");
    menu.id = "thomas-search-savedmenu";
    menu.style.position = "fixed";
    menu.style.left = `${Math.min(rect.left, window.innerWidth - 360)}px`;
    menu.style.top = `${rect.bottom + 8}px`;
    menu.style.width = "340px";
    menu.style.background = "rgba(18,18,20,0.98)";
    menu.style.border = "1px solid rgba(255,255,255,0.10)";
    menu.style.borderRadius = "14px";
    menu.style.boxShadow = "0 22px 70px rgba(0,0,0,0.55)";
    menu.style.overflow = "hidden";
    menu.style.zIndex = "10001";

    const head = document.createElement("div");
    head.style.padding = "10px 12px";
    head.style.color = "rgba(255,255,255,0.86)";
    head.style.fontSize = "13px";
    head.style.borderBottom = "1px solid rgba(255,255,255,0.08)";
    head.textContent = "Saved searches";
    menu.appendChild(head);

    if (!state.saved.length) {
      const empty = document.createElement("div");
      empty.style.padding = "10px 12px";
      empty.style.color = "rgba(255,255,255,0.70)";
      empty.style.fontSize = "13px";
      empty.textContent = "No saved searches yet.";
      menu.appendChild(empty);
    } else {
      state.saved.slice(0, 20).forEach((s) => {
        const row = document.createElement("div");
        row.style.padding = "10px 12px";
        row.style.cursor = "pointer";
        row.style.display = "flex";
        row.style.justifyContent = "space-between";
        row.style.gap = "10px";
        row.style.alignItems = "center";
        row.style.borderBottom = "1px solid rgba(255,255,255,0.06)";

        const left = document.createElement("div");
        left.style.minWidth = "0";

        const nm = document.createElement("div");
        nm.style.color = "rgba(255,255,255,0.90)";
        nm.style.fontSize = "13px";
        nm.style.whiteSpace = "nowrap";
        nm.style.overflow = "hidden";
        nm.style.textOverflow = "ellipsis";
        nm.textContent = s.name || "Saved search";

        const q = document.createElement("div");
        q.style.color = "rgba(255,255,255,0.70)";
        q.style.fontSize = "12px";
        q.style.whiteSpace = "nowrap";
        q.style.overflow = "hidden";
        q.style.textOverflow = "ellipsis";
        q.textContent = s.query || "";

        left.appendChild(nm);
        left.appendChild(q);

        const del = document.createElement("button");
        del.textContent = "";
        del.className = "ts-btn";
        del.style.padding = "6px 10px";
        del.addEventListener("click", async (e) => {
          e.stopPropagation();
          try { await fetch(`/api/search/saved/${encodeURIComponent(String(s.id))}`, { method:"DELETE" }); } catch (_) {}
          await refreshSaved();
          await loadStatus();
          closeSavedMenu();
          openSavedMenu();
        });

        row.appendChild(left);
        row.appendChild(del);

        row.addEventListener("click", async () => {
          const input = $("#thomas-search-input");
          input.value = String(s.query || "");
          closeSavedMenu();
          state.offset = 0;
          // apply saved filters if present
          try {
            const f = JSON.parse(s.filters_json || "{}");
            state.channel = f.channel || "";
            $("#thomas-search-channel").value = state.channel;
            state.since = f.since || "";
            $("#thomas-search-since").value = state.since;
            state.before = f.before || "";
            $("#thomas-search-before").value = state.before;
            state.sort = f.sort || "relevance";
            $("#thomas-search-sort").textContent = state.sort === "relevance" ? "Sort: relevance" : "Sort: newest";

            const scopes = new Set((f.scopes || ["all"]).map((x) => String(x).toLowerCase()));
            state.scopes = scopes.size ? scopes : new Set(["all"]);
            setScopeChipStates();

            state.hasTools = f.hasTools ? true : null;
            $("#ts-tools-only").setAttribute("data-on", state.hasTools ? "true" : "false");
          } catch (_) {}
          await runSearch(input.value);
          // touch use_count via query param to /api/search
          // simplest: a quick re-run with saved_id
          try {
            const params = new URLSearchParams();
            params.set("q", input.value.trim());
            params.set("limit", String(state.limit));
            params.set("offset", String(state.offset));
            params.set("saved_id", String(s.id));
            if (state.channel) params.set("channel", state.channel);
            if (state.since) params.set("since", state.since);
            if (state.before) params.set("before", state.before);
            if (state.hasTools) params.set("has_tools","true");
            params.set("sort", state.sort);
            params.set("scope", Array.from(state.scopes).join(","));
            await fetch(`/api/search?${params.toString()}`);
          } catch (_) {}
          await refreshSaved();
          await loadStatus();
        });

        menu.appendChild(row);
      });
    }

    document.body.appendChild(menu);

    setTimeout(() => {
      window.addEventListener("click", onOutsideSavedClick, { once: true });
    }, 0);
  }

  function onOutsideSavedClick(e) {
    const menu = $("#thomas-search-savedmenu");
    if (!menu) return;
    if (menu.contains(e.target) || $("#thomas-search-savedbtn").contains(e.target)) {
      window.addEventListener("click", onOutsideSavedClick, { once: true });
      return;
    }
    closeSavedMenu();
  }

  function closeSavedMenu() {
    state.savedOpen = false;
    const menu = $("#thomas-search-savedmenu");
    if (menu) menu.remove();
  }

  async function saveCurrentSearch() {
    const q = ($("#thomas-search-input").value || "").trim();
    if (!q) return;

    const name = prompt("Name this saved search:", q.length > 32 ? q.slice(0, 32) + "" : q);
    if (name === null) return;

    const filters = {
      channel: state.channel || "",
      since: state.since || "",
      before: state.before || "",
      sort: state.sort || "relevance",
      hasTools: state.hasTools === true,
      scopes: Array.from(state.scopes),
    };

    try {
      await fetch("/api/search/saved", {
        method: "POST",
        headers: { "Content-Type":"application/json" },
        body: JSON.stringify({ name: name || "Saved search", query: q, filters }),
      });
    } catch (_) {}

    await refreshSaved();
    await loadStatus();
  }

  // Global shortcut Ctrl+K (Cmd+K on Mac)
  window.addEventListener("keydown", (e) => {
    const isMac = navigator.platform.toLowerCase().includes("mac");
    const mod = isMac ? e.metaKey : e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); toggle(); return; }
    if (e.key === "Escape" && state.open) { e.preventDefault(); close(); }
  });

  document.addEventListener("DOMContentLoaded", () => { ensureButton(); ensureOverlay(); });
})();
