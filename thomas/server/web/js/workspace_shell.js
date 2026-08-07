(function () {
  "use strict";

  const THEMES = ["nebula", "dark", "light", "aurora", "sandstone"];
  const STORAGE_KEY = "thomas_chat_theme";
  let applyingRemoteEdit = false;

  function safeTheme(value) {
    const theme = String(value || "").toLowerCase();
    return THEMES.includes(theme) ? theme : "nebula";
  }
  function storedTheme() {
    try { return safeTheme(localStorage.getItem(STORAGE_KEY)); }
    catch (_) { return "nebula"; }
  }
  const LIGHT_THEMES = ["light", "sandstone"];
  function applyTheme(theme, options) {
    const name = safeTheme(theme); const root = document.documentElement;
    root.dataset.thomasTheme = name; root.dataset.theme = name;
    // Pin the theme's explicit color-scheme on the root. An embedded document
    // whose scheme differs from its iframe element's gets an OPAQUE canvas from
    // Chromium (white on light-pref machines), so both sides of every frame
    // boundary must state the same scheme. Never 'normal' - that means "light
    // only" and mismatches every dark theme.
    root.style.colorScheme = LIGHT_THEMES.includes(name) ? "light" : "dark";
    /* Clear inline vars from any previous vars payload first: a later theme
       applied WITHOUT vars (storage events) must not lose to stale inline
       values from an earlier postMessage. */
    for (let i = root.style.length - 1; i >= 0; i--) {
      const key = root.style[i];
      if (key && key.indexOf("--c-") === 0) root.style.removeProperty(key);
    }
    if (options && options.vars) {
      Object.entries(options.vars).forEach(([key, value]) => {
        if (key.startsWith("--c-") && typeof value === "string") root.style.setProperty(key, value);
      });
    }
    document.querySelectorAll("[data-thomas-theme-select]").forEach((control) => { control.value = name; });
    if (!options || options.persist !== false) {
      try { localStorage.setItem(STORAGE_KEY, name); } catch (_) { /* storage is optional */ }
    }
    window.dispatchEvent(new CustomEvent("thomas:themechange", { detail: { theme: name } }));
    return name;
  }
  function workspaceKey() {
    const declared = document.body && document.body.dataset.uiWorkspace;
    if (declared) return declared;
    try {
      const nav = new URLSearchParams(location.search).get("nav");
      if (nav) return nav === "app_builder" ? "canvas" : nav;
    } catch (_) { /* path fallback stays deterministic */ }
    const path = location.pathname.replace(/^\/+|\/+$/g, "").replace(/[^a-z0-9_-]+/gi, "-");
    return path || "chat";
  }
  // Thomas's own frames share this origin. A Code result does NOT: a generated
  // page is previewed from its own isolated loopback origin, so posting to it
  // with our origin as the target is refused and logs a warning for every frame
  // on every relay -- and it should be refused. Thomas's theme and UI-edit
  // traffic is internal, and an app he generated is untrusted content that has
  // no business receiving it. A srcdoc or about:blank frame reports an empty
  // src and inherits this origin, so it still counts as ours.
  function isOurFrame(frame) {
    const src = frame && frame.getAttribute ? String(frame.getAttribute("src") || "") : "";
    if (!src || src.startsWith("about:")) return true;
    try {
      return new URL(src, location.href).origin === location.origin;
    } catch (_) {
      return false;
    }
  }
  function sendTheme(frame, theme, vars) {
    if (!frame || !frame.contentWindow || !isOurFrame(frame)) return false;
    frame.contentWindow.postMessage({ type: "thomas:theme", theme: safeTheme(theme), vars: vars || null }, location.origin);
    return true;
  }
  function relayFrames(message, skipWindow) {
    document.querySelectorAll("iframe").forEach((frame) => {
      if (frame.contentWindow && frame.contentWindow !== skipWindow && isOurFrame(frame)) {
        frame.contentWindow.postMessage(message, location.origin);
      }
    });
  }
  function hasVisibleWorkspaceFrame() {
    return Array.from(document.querySelectorAll("iframe")).some((frame) => frame.contentWindow && getComputedStyle(frame).display !== "none" && frame.getBoundingClientRect().width > 0);
  }
  // Plugin workspace modes (paper_trading, freedom_transit, ...) only become
  // routable after the async /api/marketplace/installed fetch registers them.
  // Firing setSidebarNavMode once at runtime-ready raced that fetch: the mode
  // fell back to 'chat', and in ?embed=1 every chat surface is CSS-hidden, so
  // the workspace rendered as a silent black panel. Poll until the mode is
  // mountable; past the deadline, say so instead of showing nothing.
  const WORKSPACE_NAV_POLL_MS = 250;
  const WORKSPACE_NAV_TIMEOUT_MS = 8000;
  const WORKSPACE_CORE_MODES = new Set(["chat", "search", "office", "mission", "content"]);
  let workspaceNavPending = null;

  function workspaceModeAvailable(mode) {
    if (WORKSPACE_CORE_MODES.has(mode)) return true;
    if (typeof window.normalizeNavMode === "function") {
      try { return window.normalizeNavMode(mode) === mode; } catch (_) { /* fall through to DOM check */ }
    }
    return Boolean(document.querySelector(`[data-nav-mode="${mode}"]`));
  }
  function workspaceModeLabel(mode) {
    return String(mode || "").replace(/[_-]+/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase()).trim() || "This workspace";
  }
  function workspaceNoticeEl() {
    let el = document.getElementById("workspaceShellNotice");
    if (el) return el;
    el = document.createElement("div");
    el.id = "workspaceShellNotice";
    el.className = "workspace-shell-notice";
    el.setAttribute("role", "status");
    el.innerHTML = '<div class="workspace-shell-notice-card">' +
      '<div class="workspace-shell-notice-glyph" aria-hidden="true"></div>' +
      '<h2 class="workspace-shell-notice-title"></h2>' +
      '<p class="workspace-shell-notice-body"></p>' +
      "</div>";
    (document.body || document.documentElement).appendChild(el);
    return el;
  }
  function showWorkspaceNotice(mode, phase) {
    const el = workspaceNoticeEl();
    const label = workspaceModeLabel(mode);
    const title = el.querySelector(".workspace-shell-notice-title");
    const body = el.querySelector(".workspace-shell-notice-body");
    if (phase === "unavailable") {
      if (title) title.textContent = label + " isn't available here yet";
      if (body) body.textContent = "This workspace didn't load — it may not be installed or enabled on this Thomas. Your chats are untouched; pick another workspace from the sidebar.";
    } else {
      if (title) title.textContent = "Opening " + label + "…";
      if (body) body.textContent = "Loading this workspace.";
    }
    el.dataset.phase = phase === "unavailable" ? "unavailable" : "loading";
    el.classList.add("is-visible");
  }
  function hideWorkspaceNotice() {
    const el = document.getElementById("workspaceShellNotice");
    if (el) el.classList.remove("is-visible");
  }
  function navigateWorkspace(mode) {
    const normalized = String(mode || "").replace(/[^a-z0-9_-]/gi, "");
    if (!normalized) return;
    const perform = () => {
      if (typeof window.setSidebarNavMode === "function") { window.setSidebarNavMode(normalized); return true; }
      const fallbackIds = { office: "navOfficeBtn", chat: "navChatBtn", content: "navContentBtn" };
      const button = document.querySelector(`[data-nav-mode="${normalized}"]`) || document.getElementById(fallbackIds[normalized] || "");
      if (button instanceof HTMLElement) { button.click(); return true; }
      return false;
    };
    const start = () => {
      if (workspaceNavPending && workspaceNavPending.timer) window.clearTimeout(workspaceNavPending.timer);
      const pending = { mode: normalized, deadline: Date.now() + WORKSPACE_NAV_TIMEOUT_MS, timer: 0 };
      workspaceNavPending = pending;
      const attempt = () => {
        if (workspaceNavPending !== pending) return;
        if (workspaceModeAvailable(normalized) && perform()) {
          workspaceNavPending = null;
          hideWorkspaceNotice();
          return;
        }
        if (Date.now() >= pending.deadline) {
          workspaceNavPending = null;
          showWorkspaceNotice(normalized, "unavailable");
          return;
        }
        showWorkspaceNotice(normalized, "loading");
        pending.timer = window.setTimeout(attempt, WORKSPACE_NAV_POLL_MS);
      };
      attempt();
    };
    Promise.resolve(window.__thomasRuntimeReady).then(start, start);
  }
  function setRemoteEdit(active, save) {
    if (!window.ThomasUiEditMode) return;
    applyingRemoteEdit = true;
    window.ThomasUiEditMode.setActive(Boolean(active), { save: save !== false });
    queueMicrotask(() => { applyingRemoteEdit = false; });
  }
  function init() {
    let queryTheme = "";
    try {
      const params = new URLSearchParams(location.search); queryTheme = params.get("theme") || "";
      if (params.get("embed") === "1") {
        document.documentElement.classList.add("is-embedded");
        document.body.style.setProperty("background", "transparent");
      }
    } catch (_) { /* malformed URLs fall back safely */ }
    applyTheme(queryTheme || storedTheme(), { persist: Boolean(queryTheme) });
    window.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY && event.newValue) applyTheme(event.newValue, { persist: false });
    });
    document.querySelectorAll("[data-thomas-theme-select]").forEach((control) => control.addEventListener("change", () => applyTheme(control.value)));
    if (window.parent !== window) window.parent.postMessage({ type: "thomas:workspace-ready", workspace: workspaceKey() }, location.origin);
  }

  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || !event.data) return;
    const message = event.data;
    if (message.type === "thomas:theme") applyTheme(message.theme, { vars: message.vars, persist: true });
    if (message.type === "thomas:workspace:navigate") navigateWorkspace(message.mode);
    if (message.type === "thomas:ui-edit:set") setRemoteEdit(message.active);
    if (message.type === "thomas:ui-edit:state") {
      if (window.parent === window) {
        if (!message.active && window.ThomasUiEditMode && window.ThomasUiEditMode.isActive()) setRemoteEdit(false, false);
        relayFrames({ type: "thomas:ui-edit:set", active: Boolean(message.active) }, event.source);
      } else setRemoteEdit(message.active);
    }
    if (message.type === "thomas:ui-ai-edit" && window.parent === window) {
      window.dispatchEvent(new CustomEvent("thomas:ui-ai-edit-request", { detail: message }));
      relayFrames(message, event.source);
    }
  });
  window.addEventListener("thomas:ui-edit-mode-change", (event) => {
    if (applyingRemoteEdit) return;
    const message = { type: "thomas:ui-edit:state", active: Boolean(event.detail && event.detail.active) };
    if (window.parent !== window) window.parent.postMessage(message, location.origin);
    else {
      relayFrames({ type: "thomas:ui-edit:set", active: message.active });
      if (message.active && hasVisibleWorkspaceFrame()) setTimeout(() => setRemoteEdit(false, false), 0);
    }
  });

  window.ThomasWorkspaceShell = { THEMES, applyTheme, navigateWorkspace, relayFrames, safeTheme, sendTheme, storedTheme, workspaceKey };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
}());
