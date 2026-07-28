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
  function applyTheme(theme, options) {
    const name = safeTheme(theme); const root = document.documentElement;
    root.dataset.thomasTheme = name; root.dataset.theme = name;
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
  function navigateWorkspace(mode) {
    const normalized = String(mode || "").replace(/[^a-z0-9_-]/gi, "");
    if (!normalized) return;
    const perform = () => {
      if (typeof window.setSidebarNavMode === "function") { window.setSidebarNavMode(normalized); return; }
      const fallbackIds = { office: "navOfficeBtn", chat: "navChatBtn", content: "navContentBtn" };
      const button = document.querySelector(`[data-nav-mode="${normalized}"]`) || document.getElementById(fallbackIds[normalized] || "");
      if (button instanceof HTMLElement) button.click();
    };
    Promise.resolve(window.__thomasRuntimeReady).then(perform, perform);
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
