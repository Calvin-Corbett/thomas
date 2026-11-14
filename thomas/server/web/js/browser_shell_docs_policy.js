/* browser_shell_docs_policy.js — what a click on the left means, decided once.
 *
 * The rules (2026-08-25, changed 2026-11-10): each of Chat, Build and Work has one tab, a row opens in it,
 * and a conversation exists once. Chrome's own rule fills the gap: a row
 * clicked on a blank new-tab page navigates that page in place, and a
 * modifier click always opens a new tab. These decisions take plain values
 * and touch no DOM, so the node harness drives them without a browser and
 * every tab, home included, asks the same question the same way.
 */
"use strict";

(function () {
  const DOC_URL = "/?embed=1&browser=0";

  function docUrlFor(spec) {
    const mode = spec && (spec.mode === "code" || spec.mode === "work") ? spec.mode : "chat";
    const id = spec && spec.chatId ? String(spec.chatId) : "";
    return DOC_URL + "&tab_mode=" + mode
      + (mode === "chat" && id ? "&tab_chat=" + encodeURIComponent(id) : "")
      + (mode === "code" && id ? "&forge_code=" + encodeURIComponent(id) : "");
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
    // One tab per mode (2026-11-10). You said: "we're gonna get way too many tabs if ... every single conversation,
    // every single thread, it has its own tab ... chat, build, or work, they make their own tabs, like only one. But
    // you can right click on a conversation and make it a tab." So a row opens in the tab you are in. Only a turn
    // still running, or words typed and not sent, keep their place: those would be lost, so the row gets a tab.
    const surface = input && input.surface;
    if (surface && surface.mode === row.mode && !surface.busy && !String(surface.draft || "").trim()) return { action: "adopt" };
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
