
"use strict";

(function () {
  const DOC_URL = "/?embed=1&browser=0";

  function docUrlFor(spec) {
    const mode = spec && (spec.mode === "code" || spec.mode === "work") ? spec.mode : "chat";
    const id = spec && spec.chatId ? String(spec.chatId) : "";
    return DOC_URL + (mode === "code" && id ? "&forge_code=" + encodeURIComponent(id) : "");
  }

  // A surface with nothing on it and nothing running: navigating it in place
  // loses nothing, exactly like Chrome's new-tab page.
  function blankIdle(surface) {
    if (!surface) return false;
    if (surface.chatId || surface.busy) return false;
    if (String(surface.draft || "").trim()) return false;
    return !surface.hasContent;
  }

  function holder(tabs, mode, id) {
    if (!id) return null;
    return (tabs || []).find(t => t && t.mode === mode && t.chatId === id) || null;
  }

  function decideRowClick(input) {
    const row = (input && input.row) || {};
    const tabs = (input && input.tabs) || [];
    const mods = (input && input.modifiers) || {};
    const held = holder(tabs, row.mode, row.id);
    if (held) return { action: "focus", tab: held };
    if (mods.ctrl || mods.meta || mods.middle) return { action: "open" };
    const surface = input && input.surface;
    if (surface && surface.mode === row.mode && blankIdle(surface)) return { action: "adopt" };
    return { action: "open" };
  }

  function decideModeClick(input) {
    const mode = input && input.mode;
    const home = input && input.home;
    if (home && home.mode === mode) return { action: "focus", tab: home };
    const docs = ((input && input.tabs) || []).filter(t => t && t.kind === "doc" && t.mode === mode);
    if (!docs.length) return { action: "open", mode };
    docs.sort((a, b) => (b.activatedAt || 0) - (a.activatedAt || 0));
    return { action: "focus", tab: docs[0] };
  }

  function decideNewChat(input) {
    const s = (input && input.surface) || {};
    if (s.busy || String(s.draft || "").trim()) return { action: "open", mode: s.mode || "chat" };
    return { action: "adopt" };
  }

  window.ThomasBrowserDocsPolicy = { decideRowClick, decideModeClick, decideNewChat, blankIdle, docUrlFor };
}());
