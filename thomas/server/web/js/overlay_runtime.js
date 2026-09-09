/* overlay_runtime.js - the user overlay, applied in this document.
 *
 * The server injects this tag into every page it serves (thomas/server/
 * overlay/render.py), together with a JSON view of the overlay and, when one
 * exists, its stylesheet. So every document - the home page, every tab
 * iframe the browser shell opens, settings, mission - gets the overlay at
 * parse without chat.html or settings.html changing. This script:
 *
 *   - renames the assistant on five surfaces (document title, the brand
 *     mark, the composer placeholder, the welcome copy, the assistant
 *     message header), whole-word or whole-node matches only, via
 *     textContent, so prose that mentions Thomas stays stock; the stock text
 *     of each surface is remembered, so a later rename (Otto to Ada) or a
 *     cleared identity puts every surface back deterministically, and a
 *     surface the page rewrites itself (a mode switch sets its own
 *     placeholder) is renamed again from its new stock text;
 *   - repaints the shell fonts chat.html sets inline and never rewrites;
 *   - adopts a newer overlay live: the style block, the theme payload (when
 *     chat_themes.js offers mergeOverlay), the shell's inline palette, the
 *     layout book's overlay layer;
 *   - records new overrides through POST /api/ui/overlay/records with the
 *     overlay id this document knows as a strict precondition, refreshing
 *     and retrying once when another document gave birth or wrote first;
 *   - tells every other open document over BroadcastChannel('thomas-overlay');
 *   - answers honestly when the server predates the route (404 -> unavailable).
 *
 * Overlay text only ever lands as text, never as markup.
 */
(function () {
  "use strict";
  const CHANNEL = "thomas-overlay";
  const STOCK_NAME = "Thomas";
  const WORD = /\bThomas\b/g;

  function readView() {
    if (window.ThomasOverlayView) return window.ThomasOverlayView;
    const el = document.getElementById("thomas-overlay-view");
    let view = { present: false, rev: 0, identity: {}, tokens: {}, themes: {}, elements: {}, notes: [] };
    try { if (el) view = JSON.parse(el.textContent || "{}"); } catch (_) { view.notes = ["overlay view unreadable"]; }
    window.ThomasOverlayView = view;
    return view;
  }
  const state = { view: readView(), name: "", swapping: false };
  const stock = {};            // surface -> the text it had before any rename
  const written = {};          // surface -> the last value the runtime itself wrote
  const metaStock = {};        // theme -> the welcome copy before any rename

  /* ---------- identity ---------- */
  function swapWord(text, name) { return name ? String(text || "").replace(WORD, () => name) : String(text || ""); }
  function identityOf() { return (state.view && state.view.identity) || {}; }
  function guarded(fn) {
    if (state.swapping) return;
    state.swapping = true;
    try { fn(); } finally { state.swapping = false; }
  }
  function textOf(id) { const node = document.getElementById(id); return node ? String(node.textContent || "") : ""; }
  function setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; }
  // The four text surfaces. Each remembers the STOCK text it had before any
  // rename and the last value the runtime wrote; a value that is neither is
  // the page rewriting the surface itself (a mode switch sets its own
  // placeholder, a conversation sets the title), so it becomes the new stock
  // text and the rename is applied on top of it again. Observers read the
  // identity in effect at the time they fire, never one captured earlier.
  const SURFACES = {
    "title": { read: () => document.title, write: (v) => { document.title = v; },
      node: () => document.querySelector("title"), options: { childList: true, characterData: true, subtree: true } },
    "placeholder": { read: () => { const i = document.getElementById("tc-input"); return i ? String(i.placeholder || "") : ""; },
      write: (v) => { const i = document.getElementById("tc-input"); if (i) i.placeholder = v; },
      node: () => document.getElementById("tc-input"), options: { attributes: true, attributeFilter: ["placeholder"] } },
    "welcome.title": { read: () => textOf("tc-welcome-title"), write: (v) => setText("tc-welcome-title", v),
      node: () => document.getElementById("tc-welcome-title"), options: { childList: true, characterData: true, subtree: true } },
    "welcome.sub": { read: () => textOf("tc-welcome-sub"), write: (v) => setText("tc-welcome-sub", v),
      node: () => document.getElementById("tc-welcome-sub"), options: { childList: true, characterData: true, subtree: true } },
  };
  function applySurface(key) {
    const s = SURFACES[key];
    if (!s.node()) return;
    const current = s.read();
    if (!(key in stock)) stock[key] = current;
    else if (current !== written[key] && current !== swapWord(stock[key], state.name)) stock[key] = current;
    const explicit = identityOf()[key];
    const next = explicit ? String(explicit) : swapWord(stock[key], state.name);
    if (current !== next) { written[key] = next; s.write(next); }
  }
  function watchSurface(key) {
    const node = SURFACES[key].node();
    if (!node || node.__thomasOverlayWatched) return;
    node.__thomasOverlayWatched = true;
    new MutationObserver(() => guarded(() => applySurface(key))).observe(node, SURFACES[key].options);
  }
  // The brand mark: the sidebar's own leaf that reads exactly the name. No
  // markdown lands in the sidebar, so a whole-node match is safe there.
  function renameLeaves(root, from, to) {
    if (!root || from === to) return;
    root.querySelectorAll("span, b, strong").forEach((node) => {
      if (node.childElementCount === 0 && (node.textContent || "").trim() === from) node.textContent = to;
    });
  }
  // The assistant message header only: the name span whose row is followed by
  // the message's activity block. Prose inside a message (a bold "Thomas", a
  // heading) is never touched, whatever it says.
  function renameHeaders(root, from, to) {
    if (!root || from === to) return;
    root.querySelectorAll("span").forEach((node) => {
      if (node.childElementCount !== 0 || (node.textContent || "").trim() !== from) return;
      const row = node.parentElement;
      const after = row && row.nextElementSibling;
      if (after && after.classList && after.classList.contains("tc-activity")) node.textContent = to;
    });
  }
  function applyIdentity(view) {
    const id = (view && view.identity) || {};
    const previous = state.name || STOCK_NAME;
    state.name = String(id.name || "").trim();
    const next = state.name || STOCK_NAME;
    Object.keys(SURFACES).forEach((key) => { applySurface(key); watchSurface(key); });
    renameLeaves(document.querySelector('[data-ui-id="chat.sidebar"]'), previous, next);
    // chat.html's applyTheme rewrites the welcome copy from THEME_META on every
    // theme change, so the copy in the payload is renamed (or restored) too.
    const meta = window.ThomasChatThemes && window.ThomasChatThemes.THEME_META;
    if (meta) Object.keys(meta).forEach((key) => {
      const welcome = meta[key] && meta[key].welcome;
      if (!Array.isArray(welcome)) return;
      if (!metaStock[key]) metaStock[key] = welcome.slice();
      meta[key].welcome = metaStock[key].map((line) => swapWord(line, state.name));
    });
    const thread = document.getElementById("tc-thread");
    renameHeaders(thread, previous, next);
    renameHeaders(thread, STOCK_NAME, next);
    if (thread && !thread.__thomasOverlayWatched) {
      thread.__thomasOverlayWatched = true;
      new MutationObserver((records) => guarded(() => records.forEach((record) => record.addedNodes.forEach((node) => {
        if (node.nodeType === 1) renameHeaders(node, STOCK_NAME, state.name || STOCK_NAME);
      })))).observe(thread, { childList: true, subtree: true });
    }
  }

  /* ---------- shell repaint ---------- */
  function shellTokens(view) {
    const shell = document.getElementById("tc-shell");
    const theme = (shell && shell.dataset.theme) || "nebula";
    const tokens = (view && view.tokens) || {};
    return Object.assign({}, tokens["*"] || {}, tokens[theme] || {});
  }
  // The shell's inline font vars are chat.html's own; the runtime remembers
  // the value it found before its first write and puts it back when the
  // token is cleared, so a clear is as visible as a set.
  const shellOriginal = {};
  function repaintShellFonts(view) {
    const shell = document.getElementById("tc-shell");
    if (!shell || !view) return;
    const tokens = view.present ? shellTokens(view) : {};
    ["--font-sans", "--font-serif", "--font-mono"].forEach((key) => {
      if (tokens[key]) {
        if (!(key in shellOriginal)) shellOriginal[key] = shell.style.getPropertyValue(key);
        shell.style.setProperty(key, tokens[key]);
      } else if (key in shellOriginal) {
        if (shellOriginal[key]) shell.style.setProperty(key, shellOriginal[key]); else shell.style.removeProperty(key);
        delete shellOriginal[key];
      }
    });
  }
  // When the theme this document shows was cleared from the overlay, fall
  // back the way a fresh tab would: the overlay's default theme, else nebula.
  function fallbackTheme(themes) {
    const wanted = String((state.view && state.view.default_theme) || "");
    return themes.THEMES[wanted] ? wanted : "nebula";
  }
  function repaintShellTheme(preferDefault) {
    const shell = document.getElementById("tc-shell");
    const themes = window.ThomasChatThemes;
    if (!shell || !themes || !themes.THEMES) return;
    let name = shell.dataset.theme || "nebula";
    if (preferDefault) {
      let stored = "";
      try { stored = localStorage.getItem("thomas_chat_theme") || ""; } catch (_) { /* storage is optional */ }
      if (!stored) name = fallbackTheme(themes);
    }
    let theme = themes.THEMES[name];
    if (!theme || !theme.vars) {
      name = fallbackTheme(themes);
      theme = themes.THEMES[name];
      try { localStorage.setItem("thomas_chat_theme", name); } catch (_) { /* storage is optional */ }
    }
    if (shell.dataset.theme !== name) {
      shell.dataset.theme = name;
      const label = document.getElementById("tc-theme-name");
      if (label) label.textContent = theme.name;
    }
    Object.entries(theme.vars).forEach(([key, value]) => shell.style.setProperty(key, value));
    const meta = (themes.THEME_META || {})[name] || {};
    [["--font-head", meta.fontHead], ["--font-label", meta.fontLabel], ["--r-card", meta.rCard],
     ["--r-composer", meta.rComposer], ["--c-menu-bg", meta.menuBg]].forEach(([key, value]) => {
      if (value) shell.style.setProperty(key, value);
    });
    if (window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.applyTheme(name, { vars: theme.vars, persist: false });
  }

  /* ---------- adopt a (newer) overlay ---------- */
  function setStyle(css) {
    let style = document.getElementById("thomas-overlay-css");
    if (!css && !style) return;
    if (!style) {
      style = document.createElement("style");
      style.id = "thomas-overlay-css";
      const view = document.getElementById("thomas-overlay-view");
      if (view && view.parentNode) view.parentNode.insertBefore(style, view); else document.head.appendChild(style);
    }
    style.textContent = String(css || "");
  }
  function adopt(view, css) {
    if (!view) return;
    // Overlay-theme welcome text is mutable user state, not immutable stock.
    // Drop both removed and incoming names so clear/re-add or an update cannot
    // resurrect the first version cached before an identity rename.
    Object.keys((state.view && state.view.themes) || {}).forEach((name) => { delete metaStock[name]; });
    Object.keys(view.themes || {}).forEach((name) => { delete metaStock[name]; });
    state.view = view;
    window.ThomasOverlayView = view;
    if (css != null) setStyle(css);
    const themes = window.ThomasChatThemes;
    if (themes && typeof themes.mergeOverlay === "function") themes.mergeOverlay(view);
    repaintShellTheme();
    repaintShellFonts(view);
    guarded(() => applyIdentity(view));
    const layout = window.ThomasUiLayout;
    if (layout && typeof layout.refreshOverlay === "function") { layout.refreshOverlay(view); layout.applyAll(); }
    window.dispatchEvent(new CustomEvent("thomas:overlay:adopted", { detail: { rev: view.rev || 0 } }));
  }
  async function refresh() {
    let res;
    try { res = await fetch("/api/ui/overlay", { cache: "no-store" }); } catch (_) { return null; }
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    if (data && data.ok && data.view) adopt(data.view, data.css);
    return data;
  }

  /* ---------- record new overrides ---------- */
  async function post(action, records) {
    const body = { overlay_id: (state.view && state.view.overlay_id) || null, action: action || {}, records: records || [] };
    let res;
    try {
      res = await fetch("/api/ui/overlay/records", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (_) { return { ok: false, unavailable: true, error: "the overlay request did not reach the server" }; }
    if (res.status === 404) return { ok: false, unavailable: true, error: "this server predates the overlay endpoint" };
    return res.json().catch(() => ({ ok: false, error: "unreadable reply (" + res.status + ")" }));
  }
  async function record(action, records) {
    let data = await post(action, records);
    if (data && data.code === "overlay_mismatch") {
      // Another document gave birth or wrote first: take its view, then try once more.
      await refresh();
      data = await post(action, records);
    }
    if (data && data.ok && data.view) {
      adopt(data.view, data.css);
      broadcast({ type: "changed", rev: data.rev });
    }
    return data;
  }

  /* ---------- fan-out to every open document ---------- */
  let channel = null;
  try { channel = new BroadcastChannel(CHANNEL); } catch (_) { channel = null; }
  function broadcast(message) { if (channel) { try { channel.postMessage(message); } catch (_) { /* no fan-out */ } } }
  if (channel) channel.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.type !== "changed") return;
    const mine = (state.view && state.view.rev) || 0;
    if (typeof message.rev === "number" && message.rev <= mine) return;
    refresh();
  });

  function boot() {
    const view = state.view;
    repaintShellTheme(true);
    guarded(() => applyIdentity(view));
    repaintShellFonts(view);
    if (view && Array.isArray(view.notes) && view.notes.length) {
      try { console.warn("[thomas] overlay:", view.notes.join(" | ")); } catch (_) { /* console is optional */ }
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true }); else boot();

  window.ThomasOverlay = {
    get view() { return state.view; },
    adopt, applyIdentity, record, refresh,
    notes() { return (state.view && state.view.notes) || []; },
  };
}());
