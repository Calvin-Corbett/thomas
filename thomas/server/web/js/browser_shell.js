/* browser_shell.js — Thomas as a browser.
 *
 * Loaded LAST by chat.html (after the inline shell script), this layers the
 * browser chrome onto the live shell: Chrome-style tabs on a titlebar with
 * window controls, the omnibox, a bookmarks bar, a contextual side panel,
 * and the Ask Thomas quick chat (real backend via ThomasWorkspaceChatTransport).
 *
 * Design rules it implements (owner direction, 2026-08-25):
 *  - Sidebar clicks FOCUS an existing tab, never duplicate; a conversation
 *    exists once. Fresh workspace instances come from the + page's tiles.
 *  - One Thomas mark (titlebar); the top bars stay thin.
 *  - No AI-mode toggle and no page-vision toggle: Thomas is the AI and he
 *    already knows which tab you're on (the quick chat shows what he sees).
 *  - Profile avatar drops down Settings / theme switcher / Redesign; the
 *    side-panel toggle sits far right of the bookmarks bar, the sidebar
 *    collapse far left.
 *
 * Integration contract with the existing shell (all additive):
 *  - Workspace tabs get their OWN iframe per tab (same routes the shell's
 *    openWorkspace uses), so two Mission Control tabs hold two live states.
 *  - Every other Chat, Build or Work tab is its OWN chat.html document in an
 *    iframe (browser_shell_docs.js); the top-level page is the pinned home
 *    tab and is never driven by the strip. A tab is a document.
 *  - The quick chat calls ThomasWorkspaceChatTransport.beginTurn() — the same
 *    POST /api/v2/chat NDJSON pipeline as the composer, surface_mode 'chat'.
 *
 * Escape hatch: ?browser=0 or localStorage thomas_browser_shell='off'.
 */
(function () {
  "use strict";

  if (window.parent !== window) return;                       // never inside embeds
  try {
    const params = new URLSearchParams(location.search);
    if (params.get("browser") === "0") return;
    if (localStorage.getItem("thomas_browser_shell") === "off") return;
  } catch (_) { /* storage/URL failures never block the shell */ }

  // Desktop runtime (Electron): preload.js exposes window.thomasDesktop and
  // web tabs become real WebContentsViews. Absent it, web tabs fall back to
  // iframes (useful in a plain browser; most sites refuse framing there).
  const desktop = window.thomasDesktop || null;

  const shell = document.getElementById("tc-shell");
  const mainEl = document.querySelector("main");
  const bodyRow = document.getElementById("tc-body-row");
  const primaryCol = document.getElementById("tc-primary-column");
  const asideEl = shell && shell.querySelector("aside.tc-sidebar");
  if (!shell || !mainEl || !bodyRow || !primaryCol || !asideEl) return;

  function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }
  function icons() { return window.ThomasIcons || { glyph: () => "", face: () => "" }; }

  const SVG = {
    back: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 6l-6 6 6 6"/></svg>',
    fwd: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10 6l6 6-6 6"/></svg>',
    reload: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 3v4h-4"/></svg>',
    search: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M15 15l5 5M11 17a6 6 0 1 0 0-12 6 6 0 0 0 0 12z"/></svg>',
    plus: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    x: '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    spark: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M12 2l2.5 6.5L21 11l-6.5 2.5L12 20l-2.5-6.5L3 11l6.5-2.5z"/></svg>',
    eye: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/></svg>',
    globe: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>',
    panel: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg>',
    up: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    ext: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M10 5H5v14h14v-5"/></svg>',
    gear: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="3.1"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/></svg>',
    min: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 12h14"/></svg>',
    max: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="5" width="14" height="14" rx="1.5"/></svg>',
  };

  /* ── Workspace catalog: labels the sidebar renders → modes → routes ──
     Mirrors the inline shell's WORKSPACE_ROUTES; plugins are merged from the
     same marketplace endpoint it uses. */
  const MODERN_ROUTES = {
    mission: "/mission?embed=1",
    my_stuff: "/my-stuff?embed=1",
    settings: "/settings?embed=1",
    agent_ops: "/agent-ops?embed=1",
    system_map: "/system-map?embed=1",
  };
  const CLASSIC_ROUTE = "/classic?embed=1";
  const BUILTIN_WS = {
    "Mission Control": { mode: "mission", icon: "mission" },
    "System Map": { mode: "system_map", icon: "trading" },
    "Agent Ops": { mode: "agent_ops", icon: "search" },
    "Virtual Office": { mode: "office", icon: "office" },
    "Canvas": { mode: "app_builder", icon: "canvas" },
    "Library": { mode: "my_stuff", icon: "library" },
    "Channels": { mode: "channels", icon: "channels" },
    "Token Economy": { mode: "token_economy", icon: "tokens" },
    "Marketplace": { mode: "marketplace", icon: "market" },
  };
  const wsByMode = {};                    // mode -> {label, icon, route}
  Object.entries(BUILTIN_WS).forEach(([label, w]) => {
    wsByMode[w.mode] = { label, icon: w.icon, route: MODERN_ROUTES[w.mode] || CLASSIC_ROUTE };
  });
  wsByMode.settings = { label: "Settings", icon: "settings", route: MODERN_ROUTES.settings };
  const wsByLabel = {};                   // sidebar label -> mode
  Object.entries(BUILTIN_WS).forEach(([label, w]) => { wsByLabel[label] = w.mode; });

  async function loadPluginRoutes() {
    try {
      const res = await fetch("/api/marketplace/installed", { cache: "no-store" });
      if (!res.ok) return;
      const body = await res.json();
      (Array.isArray(body && body.plugins) ? body.plugins : [])
        .filter(p => p && p.enabled && p.surface_url && p.mode_id
          && String(p.left_nav_behavior || "workspace") === "workspace")
        .forEach(p => {
          const mode = String(p.mode_id);
          const label = String(p.surface_title || p.display_name || mode);
          wsByMode[mode] = { label, icon: "market", route: String(p.surface_url) };
          wsByLabel[label] = mode;
        });
      annotateWorkspaceButtons();
    } catch (_) { /* the built-ins are enough */ }
  }

  /* ── Chrome DOM: titlebar / nav row / bookmarks bar above the old shell ── */
  shell.style.flexDirection = "column";
  const rowWrap = h('<div class="bt-row"></div>');
  shell.appendChild(rowWrap);
  rowWrap.appendChild(asideEl);
  rowWrap.appendChild(mainEl);

  const titlebar = h('<div id="bt-titlebar">'
    + '<span class="bt-appmark" title="Thomas"><span></span><span></span></span>'
    + '<div id="bt-tabstrip" role="tablist" aria-label="Open tabs"></div>'
    + '<button id="bt-askthomas" type="button" title="Quick question — opens a side chat, no full tab needed">' + SVG.spark + " Ask Thomas</button>"
    + '<span class="bt-wincluster">'
    + '<button class="bt-winbtn" id="bt-min" type="button" title="Minimize">' + SVG.min + "</button>"
    + '<button class="bt-winbtn" id="bt-max" type="button" title="Maximize">' + SVG.max + "</button>"
    + '<button class="bt-winbtn close" id="bt-close" type="button" title="Close">' + SVG.x + "</button>"
    + "</span></div>");
  shell.insertBefore(titlebar, rowWrap);
  const strip = titlebar.querySelector("#bt-tabstrip");
  const newBtn = h('<button class="bt-newtab" type="button" title="New Thomas tab" aria-label="New Thomas tab">' + SVG.plus + "</button>");
  strip.appendChild(newBtn);

  const navrow = h('<div id="bt-navrow">'
    + '<button id="bt-back" class="bt-navbtn" type="button" title="Back" aria-label="Back">' + SVG.back + "</button>"
    + '<button id="bt-fwd" class="bt-navbtn" type="button" title="Forward" aria-label="Forward">' + SVG.fwd + "</button>"
    + '<button id="bt-reload" class="bt-navbtn" type="button" title="Reload this page" aria-label="Reload this page" data-ui-id="browser.action.reload" data-ui-label="Reload this page" data-ui-policy="protected source-edit" data-redesign-source="thomas/server/web/js/browser_shell.js">' + SVG.reload + "</button>"
    + '<div class="bt-omnibox">' + SVG.search
    + '<input id="bt-omni" placeholder="Search or type a URL — opens inside Thomas" autocomplete="off" spellcheck="false" aria-label="Search or address bar">'
    + '<button class="bt-star" id="bt-star" type="button" title="Bookmark this page">'
    + '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l2.7 5.8 6.3.7-4.7 4.3 1.3 6.2-5.6-3.2-5.6 3.2 1.3-6.2L3 9.5l6.3-.7z"/></svg></button>'
    + "</div></div>");
  shell.insertBefore(navrow, rowWrap);
  const omni = navrow.querySelector("#bt-omni");

  // Loaded tab documents mirror model changes immediately and read the persisted
  // preference when they boot.
  const modelWrap = document.querySelector("[data-model-switch]");
  if (modelWrap) navrow.appendChild(modelWrap);
  function syncModelToDocuments(profile, modelId) {
    document.querySelectorAll("iframe.bt-doc").forEach(frame => {
      try {
        const child = frame.contentWindow;
        const selection = child && child.ThomasModelSelection;
        if (selection) selection.select(profile, modelId);
      } catch (_) { /* a tab still loading will read the persisted preference */ }
    });
  }
  window.addEventListener("thomas:model-selected", event => {
    const detail = event.detail || {};
    syncModelToDocuments(detail.profile, detail.modelId);
  });
  const profWrap = h('<div style="position: relative; flex: 0 0 auto;">'
    + '<button id="bt-profile" class="bt-avatar" type="button" title="Profile — settings, themes, redesign" aria-haspopup="menu" aria-expanded="false">C</button>'
    + '<div id="bt-profmenu" role="menu"></div></div>');
  navrow.appendChild(profWrap);
  const profBtn = profWrap.querySelector("#bt-profile");
  const profMenu = profWrap.querySelector("#bt-profmenu");
  profMenu.innerHTML = '<div class="bt-pm-head"><span class="bt-avatar" style="width:34px;height:34px;font-size:14px;">C</span>'
    + "<span><b>This Thomas</b><em>Local profile — cloud sign-in is a future thing</em></span></div>"
    + '<button class="bt-pm-item" id="bt-pm-settings" type="button">' + SVG.gear + " Settings</button>"
    + '<button class="bt-pm-item" id="bt-pm-classic" type="button" title="Turn the tab shell off; ?browser=1 turns it back on">' + SVG.panel + " Classic layout</button>"
    + (desktop ? '<button class="bt-pm-item" id="bt-pm-history" type="button">' + SVG.reload + " History</button>" : "")
    + '<div class="bt-pm-label">Appearance & tools</div>'
    + '<div class="bt-pm-hosted" id="bt-pm-hosted"></div>';
  const hosted = profMenu.querySelector("#bt-pm-hosted");
  // Rehome only the real theme switcher; chat actions stay in the chat header.
  const themeWrap = document.querySelector("[data-theme-switch]");
  if (themeWrap) hosted.appendChild(themeWrap);

  function closeProfMenu() { profMenu.classList.remove("open"); profBtn.setAttribute("aria-expanded", "false"); }

  profBtn.addEventListener("click", e => {
    e.stopPropagation();
    function showHtmlMenu() {
      const open = !profMenu.classList.contains("open");
      profMenu.classList.toggle("open", open);
      profBtn.setAttribute("aria-expanded", String(open));
    }
    if (desktopWiring && desktopWiring.nativeMenus) {
      closeProfMenu();
      // A native menu is the only kind visible over a live web view; if the
      // runtime cannot show one, fall back rather than leave a dead button.
      desktopWiring.openProfileMenu().then(shown => { if (!shown) showHtmlMenu(); });
      return;
    }
    showHtmlMenu();
  });
  document.addEventListener("click", e => { if (!profWrap.contains(e.target)) closeProfMenu(); });
  profMenu.querySelector("#bt-pm-settings").addEventListener("click", () => { closeProfMenu(); openWorkspaceTab("settings"); });
  // The visible way out of the tab shell, remembered until ?browser=1.
  profMenu.querySelector("#bt-pm-classic").addEventListener("click", () => {
    try { localStorage.setItem("thomas_browser_shell", "off"); } catch (_) { /* navigation below still applies */ }
    window.location.assign(window.location.href);
  });
  const historyItem = profMenu.querySelector("#bt-pm-history");
  if (historyItem) historyItem.addEventListener("click", () => { closeProfMenu(); openHistoryTab(); });

  // Bookmarks bar: collapse | favorites | side panel.
  const bookbar = h('<div id="bt-bookmarks"></div>');
  shell.insertBefore(bookbar, rowWrap);
  const sidebarToggle = document.getElementById("tc-sidebar-toggle");
  if (sidebarToggle) bookbar.appendChild(sidebarToggle);
  // The toggle folds home through its own handler; every tab document follows.
  if (sidebarToggle) sidebarToggle.addEventListener("click", () => docs.onSidebarToggle(), true);
  const DEFAULT_BOOKMARKS = [
    { label: "Gmail", url: "https://mail.google.com", c: "#ea4335", t: "M" },
    { label: "Truckstop", url: "https://truckstop.com", c: "#e01e37", t: "T" },
    { label: "Motive", url: "https://gomotive.com", c: "#3b4252", t: "M" },
    { label: "Wells Fargo", url: "https://www.wellsfargo.com", c: "#d71e28", t: "WF" },
    { label: "PrePass", url: "https://prepass.com", c: "#7c3aed", t: "P" },
  ];
  function loadBookmarks() {
    try {
      const raw = JSON.parse(localStorage.getItem("thomas_browser_bookmarks") || "null");
      if (Array.isArray(raw) && raw.length) return raw;
    } catch (_) { /* fall through to defaults */ }
    return DEFAULT_BOOKMARKS.slice();
  }
  const bookmarks = loadBookmarks();
  function saveBookmarks() {
    try { localStorage.setItem("thomas_browser_bookmarks", JSON.stringify(bookmarks)); } catch (_) { }
  }
  const bmHost = h('<span style="display:flex; align-items:center; gap:2px; min-width:0;"></span>');
  bookbar.appendChild(bmHost);
  function renderBookmarks() {
    bmHost.innerHTML = "";
    bookmarks.forEach(bm => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "bt-bm"; b.title = bm.url;
      b.innerHTML = '<span class="bt-bm-ic" style="background:' + esc(bm.c || "#556") + ';">' + esc(bm.t || bm.label.slice(0, 1).toUpperCase()) + "</span><span>" + esc(bm.label) + "</span>";
      b.addEventListener("click", () => openUrl(bm.url));
      bmHost.appendChild(b);
    });
  }
  renderBookmarks();
  const panelBtn = h('<button id="bt-panelbtn" type="button" title="Side panel — what’s relevant to this page">' + SVG.panel + "</button>");
  bookbar.appendChild(panelBtn);

  /* ── Toast (transient notices) ──────────────────────────────────────── */
  let toastEl = null, toastTimer = 0;
  function toast(text) {
    if (!toastEl) {
      toastEl = h('<div role="status" style="position:fixed; left:50%; bottom:22px; transform:translateX(-50%); z-index:120; padding:9px 16px; border-radius:999px; background:var(--c-menu-bg, var(--c-surface)); border:1px solid var(--c-border-2); color:var(--c-text); font-family:var(--font-sans); font-size:12.5px; box-shadow:var(--c-shadow); max-width:70vw;"></div>');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    toastEl.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.style.display = "none"; }, 3600);
  }

  /* ── Tab machinery ──────────────────────────────────────────────────── */
  const tabs = []; let activeId = null; let uid = 0;
  const viewTabs = new Map();            // desktop viewId -> tab

  function tabIcon(tab) {
    if (tab.face) return icons().face(tab.face, 14) || SVG.globe;
    if (tab.icon) return icons().glyph(tab.icon, 14) || SVG.globe;
    return SVG.globe;
  }
  function makeTab(spec) {
    const id = ++uid;
    const tab = Object.assign({ id, status: "idle" }, spec);
    tab.el = h('<button class="bt-tab" type="button" role="tab" title="' + esc(tab.title) + '">'
      + '<span class="bt-tab-ic">' + tabIcon(tab) + "</span>"
      + '<span class="bt-tab-title">' + esc(tab.title) + "</span>"
      + '<span class="bt-light" title="idle"></span>'
      + '<span class="bt-tab-x" title="Close tab">' + SVG.x + "</span></button>");
    tab.el.addEventListener("click", e => { if (e.target.closest(".bt-tab-x")) closeTab(id); else activate(id); });
    strip.insertBefore(tab.el, newBtn);
    tabs.push(tab);
    return tab;
  }
  function byId(id) { return tabs.find(t => t.id === id); }
  function setTitle(tab, title) {
    tab.title = title;
    tab.el.querySelector(".bt-tab-title").textContent = title;
    tab.el.title = title;
  }
  function setFavicon(tab, url) {
    // A site's own mark, where its generic globe was. If the image fails to
    // load we keep the globe rather than leaving an empty square.
    const slot = tab.el.querySelector(".bt-tab-ic");
    if (!slot) return;
    const img = new Image();
    img.width = 14; img.height = 14; img.alt = "";
    img.addEventListener("load", () => { slot.innerHTML = ""; slot.appendChild(img); });
    img.src = url;
  }
  function setStatus(tab, status) {
    tab.status = status;
    const light = tab.el.querySelector(".bt-light");
    light.className = "bt-light " + (status === "idle" ? "" : status);
    light.title = { idle: "idle", working: "Thomas is working…", done: "finished", error: "needs attention" }[status] || "idle";
  }

  function reportBounds() {
    // The active web view is a native surface layered over this page; main
    // needs the content rect (and the side panel steals width when open).
    if (!desktop) return;
    const t = byId(activeId);
    if (!t || t.kind !== "web" || !t.desktop) return;
    const r = bodyRow.getBoundingClientRect();
    // Before first layout this rect is 0x0; reporting that sizes the native
    // view to nothing and every click lands outside it.
    if (r.width <= 0 || r.height <= 0) return;
    const width = Math.max(1, r.width - panel.width());
    desktop.setContentBounds({ x: r.left, y: r.top, width, height: r.height });
  }
  function hideAllSurfaces() {
    if (desktop) desktop.activateTab(null);
    document.querySelectorAll(".tc-workspace-frame").forEach(f => { f.style.display = "none"; });
    tabs.forEach(t => {
      if (t.frame) t.frame.classList.remove("is-active");
      if (t.page) t.page.classList.remove("is-active");
      if (t.fallback) t.fallback.classList.remove("is-active");
    });
    primaryCol.style.visibility = "hidden";
    primaryCol.inert = true;
    docs.hideAll();
  }
  function showPrimary() {
    primaryCol.style.visibility = "";
    primaryCol.inert = false;
    asideEl.inert = false;
    if (window.ThomasWorkspaceChat) window.ThomasWorkspaceChat.setWorkspace(null);
  }

  function activate(id) {
    const tab = byId(id); if (!tab) return;
    activeId = id;
    tabs.forEach(t => t.el.classList.toggle("is-active", t.id === id));
    hideAllSurfaces();
    tab.activatedAt = Date.now();
    if (tab.kind === "chat-home") {
      showPrimary();
    } else if (tab.kind === "doc") {
      docs.show(tab);
    } else if (tab.kind === "ws") {
      asideEl.inert = false;
      tab.frame.style.display = "";
      tab.frame.classList.add("is-active");
      if (window.ThomasWorkspaceChat) window.ThomasWorkspaceChat.setWorkspace(tab.mode);
    } else if (tab.kind === "web") {
      asideEl.inert = false;
      if (tab.desktop) {
        if (tab.viewId != null) desktop.activateTab(tab.viewId);
        reportBounds();
      } else {
        tab.frame.classList.add("is-active");
        if (tab.fallback) tab.fallback.classList.add("is-active");
      }
    } else if (tab.page) {                        // ntp, history — our own pages
      asideEl.inert = false;
      tab.page.classList.add("is-active");
      const inp = tab.page.querySelector("input");
      if (inp) setTimeout(() => inp.focus(), 60);
    }
    // The browser bar is the one model control for every Thomas document.
    if (modelWrap) modelWrap.style.display = "";
    omni.value = tab.url || "";
    syncNav();
    panel.sync();
  }
  function closeTab(id) {
    const i = tabs.findIndex(t => t.id === id);
    if (i < 0) return;
    const tab = tabs[i];
    if (tab.pinned) return;                       // home stays in this version
    if (tab.kind === "doc") docs.remove(tab);
    tab.el.remove();
    if (tab.viewId != null && desktop) { desktop.closeTab(tab.viewId); viewTabs.delete(tab.viewId); }
    // Adopted originals (tc-ws-frame) survive tab close; our own frames don't.
    if (tab.frame && tab.frame.classList.contains("bt-frame") && !tab.adopted) tab.frame.remove();
    else if (tab.frame) { tab.frame.style.display = "none"; tab.frame.classList.remove("is-active"); }
    if (tab.page) tab.page.remove();
    if (tab.fallback) tab.fallback.remove();
    tabs.splice(i, 1);
    if (activeId === id) {
      if (tabs.length) activate(tabs[Math.min(i, tabs.length - 1)].id);
      else openNtp();
    }
  }

  /* ── Live tabs: chat home + modes + conversations ───────────────────── */
  const homeTab = makeTab({ kind: "chat-home", title: "Chat", face: "chat", url: "thomas://chat",
    mode: shell.dataset.surfaceMode || "chat", chatId: "", pinned: true });
  homeTab.el.classList.add("is-pinned");

  // Mode buttons, conversation rows and New chat are intercepted by the
  // document-tab module (docs.installOn, below): a tab is a document.

  /* ── Workspace tabs: one live iframe per tab ────────────────────────── */
  function annotateWorkspaceButtons() {
    const wrap = document.getElementById("tc-workspaces");
    if (!wrap) return;
    wrap.querySelectorAll("button:not([data-bt-mode])").forEach(btn => {
      const label = (btn.textContent || "").trim();
      const mode = wsByLabel[label];
      if (mode) {
        btn.dataset.btMode = mode;
        btn.title = "Opens as a tab; clicking again focuses it. Fresh instances live on the + page.";
      }
    });
  }
  annotateWorkspaceButtons();
  const wsWrap = document.getElementById("tc-workspaces");
  if (wsWrap) new MutationObserver(annotateWorkspaceButtons).observe(wsWrap, { childList: true });

  document.addEventListener("click", e => {
    const btn = e.target.closest("#tc-workspaces button[data-bt-mode]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();                 // capture phase: the old single-frame path never runs
    openWorkspaceTab(btn.dataset.btMode);
  }, true);

  function currentThemeVars() {
    const name = (window.ThomasWorkspaceShell && window.ThomasWorkspaceShell.storedTheme()) || "nebula";
    const themes = window.ThomasChatThemes && window.ThomasChatThemes.THEMES;
    return { name, vars: themes && themes[name] ? themes[name].vars : null };
  }
  function syncFrame(frame, mode, route) {
    const theme = currentThemeVars();
    if (window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.sendTheme(frame, theme.name, theme.vars);
    if (route === CLASSIC_ROUTE && frame.contentWindow) {
      frame.contentWindow.postMessage({ type: "thomas:workspace:navigate", mode }, location.origin);
    }
  }
  function openWorkspaceTab(mode, fresh) {
    const meta = wsByMode[mode];
    if (!meta) return null;
    if (!fresh) {
      const existing = tabs.find(t => t.kind === "ws" && t.mode === mode);
      if (existing) { activate(existing.id); return existing; }
    }
    const n = tabs.filter(t => t.kind === "ws" && t.mode === mode).length + 1;
    const tab = makeTab({
      kind: "ws", mode, icon: meta.icon,
      title: meta.label + (n > 1 ? " · " + n : ""),
      url: "thomas://" + mode.replace(/_/g, "-") + (n > 1 ? "/" + n : ""),
    });
    const frame = document.createElement("iframe");
    frame.className = "tc-workspace-frame bt-frame";
    frame.title = meta.label;
    frame.dataset.workspaceMode = mode;
    frame.addEventListener("load", () => { syncFrame(frame, mode, meta.route); setStatus(tab, "idle"); });
    setStatus(tab, "working");
    frame.src = meta.route;
    bodyRow.appendChild(frame);
    tab.frame = frame;
    activate(tab.id);
    return tab;
  }

  // Theme changes reach every tab frame.
  window.addEventListener("thomas:themechange", () => {
    tabs.filter(t => t.kind === "ws" && t.frame).forEach(t => {
      const meta = wsByMode[t.mode];
      if (meta) syncFrame(t.frame, t.mode, meta.route);
    });
  });

  // If anything still opens the ORIGINAL single workspace frame (deep links,
  // internal flows), adopt it into a tab instead of letting surfaces fight.
  function watchOriginalFrame(frameId) {
    const frame = document.getElementById(frameId);
    if (!frame) return;
    new MutationObserver(() => {
      if (frame.style.display === "none") return;
      const mode = frame.dataset.workspaceMode;
      if (!mode || !wsByMode[mode]) return;
      let tab = tabs.find(t => t.kind === "ws" && t.mode === mode);
      if (!tab) {
        tab = makeTab({
          kind: "ws", mode, icon: wsByMode[mode].icon,
          title: wsByMode[mode].label, url: "thomas://" + mode.replace(/_/g, "-"),
          adopted: true,
        });
        tab.frame = frame;
        frame.classList.add("bt-frame");
      }
      if (activeId !== tab.id) activate(tab.id);
    }).observe(frame, { attributes: true, attributeFilter: ["style"] });
  }
  watchOriginalFrame("tc-ws-frame");

  /* ── Web tabs, the + page and History live in their own module ─────── */
  const web = window.ThomasBrowserWeb.wire({
    desktop, bodyRow, h, esc, SVG, icons, wsByMode, bookmarks, makeTab, byId, activate,
    setTitle, setStatus, toast, viewTabs, reportBounds, openWorkspaceTab, omni,
    getActiveId: () => activeId,
    websearch: () => websearch,
    keys: () => keys,
  });
  const { openNtp, openUrl, hostOf, openWebTab, openHistoryTab } = web;

  /* ── Toolbar wiring ─────────────────────────────────────────────────── */
  const backBtn = navrow.querySelector("#bt-back"), fwdBtn = navrow.querySelector("#bt-fwd");
  function syncNav() {
    const t = byId(activeId), web = t && t.kind === "web";
    backBtn.disabled = !web;
    fwdBtn.disabled = !web;
  }
  backBtn.addEventListener("click", () => {
    const t = byId(activeId);
    if (!t || t.kind !== "web") return;
    if (t.desktop) desktop.back(t.viewId);
    else if (t.frame) { try { t.frame.contentWindow.history.back(); } catch (_) { } }
  });
  fwdBtn.addEventListener("click", () => {
    const t = byId(activeId);
    if (!t || t.kind !== "web") return;
    if (t.desktop) desktop.forward(t.viewId);
    else if (t.frame) { try { t.frame.contentWindow.history.forward(); } catch (_) { } }
  });
  const reloadBtn = navrow.querySelector("#bt-reload");
  let reloadAnimationTimer = 0;
  function reloadActiveTab() {
    clearTimeout(reloadAnimationTimer);
    reloadBtn.classList.add("is-reloading");
    reloadBtn.setAttribute("aria-busy", "true");
    const finish = pending => Promise.resolve(pending).finally(() => {
      reloadAnimationTimer = setTimeout(() => {
        reloadBtn.classList.remove("is-reloading");
        reloadBtn.removeAttribute("aria-busy");
      }, 320);
    });

    const t = byId(activeId);
    if (!t) return finish();
    if (t === homeTab) {
      const reload = window.ThomasChatSurface && window.ThomasChatSurface.reload;
      if (typeof reload !== "function") {
        toast("Chat is still starting — try reload again."); return finish();
      }
      setStatus(t, "working");
      const pending = window.ThomasChatSurface.reload === reload
        ? Promise.resolve(reload())
        : Promise.resolve(window.ThomasChatSurface.reload());
      return finish(pending.then(
        result => { setStatus(t, "done"); return result; },
        error => { setStatus(t, "error"); toast("Chat could not be reloaded."); throw error; },
      ));
    }
    if (t.kind === "doc") { docs.reload(t); return finish(); }
    if (t.desktop && t.viewId != null) { setStatus(t, "working"); desktop.reload(t.viewId); }
    else if (t.frame) { setStatus(t, "working"); try { t.frame.src = t.frame.src; } catch (_) { } }
    return finish();
  }
  reloadBtn.addEventListener("click", reloadActiveTab);
  window.addEventListener("thomas:reload-current-tab", reloadActiveTab);
  omni.addEventListener("keydown", e => {
    if (e.key !== "Enter" || !omni.value.trim()) return;
    const raw = omni.value.trim();
    if (raw.startsWith("thomas://")) return;         // our own addresses aren't navigable
    openUrl(websearch.toUrl(raw));
  });
  navrow.querySelector("#bt-star").addEventListener("click", () => {
    const t = byId(activeId);
    if (!t || t.kind !== "web") { toast("Open a website first — bookmarks hold web pages."); return; }
    if (bookmarks.some(b => b.url === t.url)) { toast("Already bookmarked."); return; }
    const host = hostOf(t.url).replace(/^www\./, "");
    bookmarks.push({ label: host, url: t.url, c: "#5b6dd6", t: host.slice(0, 1).toUpperCase() });
    saveBookmarks(); renderBookmarks();
    toast("Bookmarked " + host);
  });
  newBtn.addEventListener("click", () => openNtp());

  // Window controls: REAL in the desktop app (frameless window, our
  // titlebar); honest fallbacks when the page runs in a plain browser.
  titlebar.querySelector("#bt-max").addEventListener("click", () => {
    if (desktop) { desktop.windowControl("max"); return; }
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => toast("Fullscreen was blocked by the browser."));
  });
  titlebar.querySelector("#bt-min").addEventListener("click", () => {
    if (desktop) { desktop.windowControl("min"); return; }
    toast("Minimize needs the desktop app — launch Thomas from its shortcut.");
  });
  titlebar.querySelector("#bt-close").addEventListener("click", () => {
    if (desktop) { desktop.windowControl("close"); return; }
    window.close();
    setTimeout(() => toast("The browser refused to close this window — use the window's own close button."), 150);
  });

  /* ── Side panel + quick chat (its own module) ───────────────────────── */
  const panel = window.ThomasBrowserPanel.create({
    desktop, bodyRow: rowWrap, esc, h, SVG, byId, setStatus, navrow, activate,
    getActiveId: () => activeId,
    homeTabId: () => homeTab.id,
    openWorkspaceTab,
    onBoundsChange: () => reportBounds(),
  });
  panel.attach(panelBtn);
  titlebar.querySelector("#bt-askthomas").addEventListener("click", panel.openQuickChat);

  /* ── Desktop-only wiring lives in its own module ────────────────────── */
  const desktopWiring = window.ThomasBrowserDesktop.wire({
    desktop, bodyRow, profBtn, omni, viewTabs, toast, setTitle, setStatus, setFavicon,
    openWebTab, openWorkspaceTab, openHistoryTab, activate, reportBounds,
    getActiveId: () => activeId,
    homeTabId: () => homeTab.id,
  });

  /* ── Keyboard: the conventions your hands already know ──────────────── */
  const keys = window.ThomasBrowserKeys.wire({
    // Each callback says whether it did anything: a no-op leaves the
    // browser's own default alone instead of swallowing the key.
    newTab: () => { openNtp(); return true; },
    closeActiveTab: () => {
      const t = byId(activeId);
      if (!t || t.pinned) return false;                  // the home tab stays
      closeTab(activeId); return true;
    },
    cycleTab: delta => {
      if (tabs.length < 2) return false;
      const i = tabs.findIndex(t => t.id === activeId);
      // Wrap in both directions, the way a tab strip is expected to.
      activate(tabs[(i + delta + tabs.length) % tabs.length].id);
      return true;
    },
    selectTabIndex: n => {
      // Chrome's rule: 1-8 pick that tab, 9 always means the last one.
      const tab = n === 9 ? tabs[tabs.length - 1] : tabs[n - 1];
      if (!tab) return false;
      activate(tab.id); return true;
    },
    focusOmnibox: () => { omni.focus(); omni.select(); return true; },
    reloadActive: () => { navrow.querySelector("#bt-reload").click(); return true; },
    goBack: () => { if (backBtn.disabled) return false; backBtn.click(); return true; },
    goForward: () => { if (fwdBtn.disabled) return false; fwdBtn.click(); return true; },
  });
  // In the app, a focused web tab swallows every key before this page sees
  // it, so the main process forwards the action instead.
  if (desktop && desktop.onShortcut) desktop.onShortcut(msg => keys.handle(msg.action, msg.arg));

  /* ── Document tabs: every extra Chat, Build or Work tab is its own page ── */
  const docs = window.ThomasBrowserDocs.wire({
    rowWrap, asideEl, makeTab, byId, activate, setTitle, setStatus, wsByLabel, openWorkspaceTab,
    getActiveId: () => activeId, getTabs: () => tabs.slice(), homeTab, keys,
    closeMenus: closeProfMenu,
    faceFor: mode => ({ chat: "chat", code: "build", work: "work" }[mode] || "chat"),
  });
  docs.installOn(homeTab, document);

  /* ── Search is a page we serve, not a site we hand you to ──────────── */
  const websearch = window.ThomasBrowserSearch.wire({
    h, body: bodyRow, activate, setTitle, setStatus, icon: SVG.search,
    openUrl: url => openUrl(url), desktop, viewTabs,
  });

  /* ── Boot ───────────────────────────────────────────────────────────── */
  loadPluginRoutes();
  activate(homeTab.id);
})();
