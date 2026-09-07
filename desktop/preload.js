/* preload.js — the ONLY bridge between the Thomas chrome page and the main
 * process. Attached solely to the chrome WebContentsView (the page served by
 * the Python server at /); web-content tabs never get a preload.
 *
 * contextIsolation stays true and the page gets exactly this API, nothing
 * else — no Node, no Electron internals. browser_shell.js feature-detects
 * window.thomasDesktop and falls back to iframe tabs in a plain browser.
 */
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

/* The desktop app brings its own chrome.
 *
 * The tab strip, omnibox, bookmarks bar and side panel are served from
 * /static like every other Thomas asset, but they are NOT linked from
 * chat.html: that file is 2998 lines, over the monolith guard's HTML hard
 * limit and unbaselined, and the baseline is an owner-only enforcement file.
 * Rather than fight that or risk decomposing the shell unattended, the app
 * that actually needs the chrome attaches it to the page it hosts.
 *
 * Ordering matters: chat.html's inline shell script runs during parse and
 * boots the sidebar, themes and composer. browser_shell.js reads all of
 * that, so injection waits for DOMContentLoaded -- by then the shell exists.
 * The panel module must precede the shell that consumes it.
 *
 * When chat.html is eventually split (it should be), these move into the
 * page and this block goes away.
 */
function attachBrowserChrome() {
  if (document.getElementById("bt-titlebar")) return;   // the page attached its own
  const stamped = document.querySelector('link[href*="/static/css/tokens.css"]');
  const version = stamped ? (stamped.getAttribute("href").split("?")[1] || "") : "";
  const q = version ? "?" + version : "";

  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "/static/css/browser_shell.css" + q;
  document.head.appendChild(css);

  // Sequential, not parallel: the shell's IIFE runs on load and needs both
  // window.ThomasBrowserPanel and window.ThomasBrowserDesktop to exist.
  const chain = [
    "/static/js/browser_shell_panel.js",
    "/static/js/browser_shell_desktop.js",
    "/static/js/browser_shell_keys.js",
    "/static/js/browser_shell_search.js",
    "/static/js/browser_shell_web.js",
    "/static/js/browser_shell_docs_policy.js",
    "/static/js/browser_shell_docs.js",
    "/static/js/browser_shell.js",
  ];
  (function loadNext(i) {
    if (i >= chain.length) return;
    const el = document.createElement("script");
    el.src = chain[i] + q;
    el.addEventListener("load", () => loadNext(i + 1));
    el.addEventListener("error", () => {
      console.error("[thomas-desktop] browser chrome failed to load:", chain[i]);
    });
    document.body.appendChild(el);
  })(0);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", attachBrowserChrome, { once: true });
} else {
  attachBrowserChrome();
}

const tabEventHandlers = new Set();
ipcRenderer.on("bt:tab-event", (_e, evt) => {
  tabEventHandlers.forEach(fn => { try { fn(evt); } catch (_) { } });
});
const restoreHandlers = new Set();
ipcRenderer.on("bt:restore", (_e, urls) => {
  restoreHandlers.forEach(fn => { try { fn(urls); } catch (_) { } });
});
const shortcutHandlers = new Set();
ipcRenderer.on("bt:shortcut", (_e, msg) => {
  shortcutHandlers.forEach(fn => { try { fn(msg); } catch (_) { } });
});

contextBridge.exposeInMainWorld("thomasDesktop", {
  // tabs (web content only — workspace iframes stay in the page)
  createTab: () => ipcRenderer.invoke("bt:create-tab"),
  navigate: (id, url) => ipcRenderer.invoke("bt:navigate", { id, url }),
  activateTab: id => ipcRenderer.invoke("bt:activate-tab", { id }),
  closeTab: id => ipcRenderer.invoke("bt:close-tab", { id }),
  back: id => ipcRenderer.invoke("bt:back", { id }),
  forward: id => ipcRenderer.invoke("bt:forward", { id }),
  reload: id => ipcRenderer.invoke("bt:reload", { id }),
  setContentBounds: rect => ipcRenderer.invoke("bt:set-bounds", rect),
  onTabEvent: fn => { tabEventHandlers.add(fn); },

  // window chrome (frameless window; our titlebar is the real one)
  windowControl: action => ipcRenderer.invoke("bt:window-control", { action }),
  // Native menus: an HTML dropdown is invisible under a live web view.
  popupMenu: (items, x, y) => ipcRenderer.invoke("bt:popup-menu", { items, x, y }),
  // ...and for the dropdowns the shell already owns, the view steps aside.
  suspendView: suspended => ipcRenderer.invoke("bt:suspend-view", { suspended }),

  // history + session restore
  getHistory: (query, limit) => ipcRenderer.invoke("bt:get-history", { query, limit }),
  onRestore: fn => { restoreHandlers.add(fn); },
  // Keyboard conventions caught in main, because a focused web tab never
  // lets the chrome page see them.
  onShortcut: fn => { shortcutHandlers.add(fn); },
  ready: () => ipcRenderer.invoke("bt:chrome-ready"),

  getState: () => ipcRenderer.invoke("bt:get-state"),
});
