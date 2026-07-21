(function () {
  "use strict";

  const THEMES = ["nebula", "dark", "light", "aurora", "sandstone"];
  const STORAGE_KEY = "thomas_chat_theme";

  function safeTheme(value) {
    const theme = String(value || "").toLowerCase();
    return THEMES.includes(theme) ? theme : "nebula";
  }

  function storedTheme() {
    try { return safeTheme(localStorage.getItem(STORAGE_KEY)); }
    catch (_) { return "nebula"; }
  }

  function applyTheme(theme, options) {
    const name = safeTheme(theme);
    const root = document.documentElement;
    root.dataset.thomasTheme = name;
    root.dataset.theme = name;
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

  function sendTheme(frame, theme, vars) {
    if (!frame || !frame.contentWindow) return false;
    frame.contentWindow.postMessage({ type: "thomas:theme", theme: safeTheme(theme), vars: vars || null }, location.origin);
    return true;
  }

  function init() {
    let queryTheme = "";
    try {
      const params = new URLSearchParams(location.search);
      queryTheme = params.get("theme") || "";
      if (params.get("embed") === "1") document.documentElement.classList.add("is-embedded");
    } catch (_) { /* malformed URLs fall back safely */ }
    applyTheme(queryTheme || storedTheme(), { persist: Boolean(queryTheme) });
    document.querySelectorAll("[data-thomas-theme-select]").forEach((control) => {
      control.addEventListener("change", () => applyTheme(control.value));
    });
    if (window.parent !== window) {
      window.parent.postMessage({ type: "thomas:workspace-ready", workspace: workspaceKey() }, location.origin);
    }
  }

  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || !event.data) return;
    if (event.data.type === "thomas:theme") applyTheme(event.data.theme, { vars: event.data.vars, persist: true });
    if (event.data.type === "thomas:ui-edit:set" && window.ThomasUiEditMode) {
      window.ThomasUiEditMode.setActive(Boolean(event.data.active));
    }
  });

  window.ThomasWorkspaceShell = { THEMES, applyTheme, safeTheme, sendTheme, storedTheme, workspaceKey };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
}());
