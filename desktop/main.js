/* main.js — the Thomas desktop app: a real browser shell around the Thomas
 * web chrome.
 *
 * Architecture (runtime decision, 2026-08-25):
 *  - One frameless BaseWindow. The CHROME view (a WebContentsView with
 *    preload.js) fills it and loads the Python server's page at / — the same
 *    chat.html + browser_shell.js that works in a plain browser. Workspace
 *    tabs stay same-origin iframes inside that page.
 *  - WEB tabs are separate WebContentsViews (own renderer processes, the
 *    persist:thomas partition, our profile dir), layered over the chrome's
 *    content area. The chrome page reports the content rect and which tab is
 *    active; main owns the views.
 *  - The agent↔page channel is CDP over webContents.debugger, exposed to
 *    Thomas's Python brain through a token-gated loopback WebSocket. That one
 *    channel carries see / control (and later record) — no screenshot-seeing
 *    or injected-script control as parallel paths.
 *  - Security defaults are non-negotiable everywhere: contextIsolation:true,
 *    sandbox:true, nodeIntegration:false. Web tabs get no preload at all.
 *
 * Modes: `electron .` runs the app. The Phase-1 gauntlet lives in spike.js
 * (`electron spike.js --gates|--verify-persist|--bridge`) and must keep
 * passing on every Electron bump.
 */
"use strict";

const { app, BaseWindow, WebContentsView, session, ipcMain, Menu } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");

const REPO_ROOT = path.join(__dirname, "..");
const PARTITION = "persist:thomas";
app.setPath("userData", path.join(REPO_ROOT, "runtime", "browser_profile"));

// The taskbar showed the default Electron icon, because an unpackaged Electron
// app has no identity of its own: Windows groups and labels a window by its
// AppUserModelID, and falls back to electron.exe's own icon when the window
// carries none. Both have to be set, and the ID has to be set before any window
// exists or Windows keeps the identity it already assigned to the process.
const APP_ICON = path.join(REPO_ROOT, "assets", "thomas.ico");
if (process.platform === "win32") app.setAppUserModelId("com.thomas.desktop");

if (!app.requestSingleInstanceLock()) app.exit(0);
app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });

const argv = process.argv.slice(1);
function argValue(name, fallback) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
}
const SERVER_PORT = Number(argValue("--server-port", process.env.THOMAS_SERVER_PORT || "8899"));
const SERVER_URL = process.env.THOMAS_SERVER_URL || `http://127.0.0.1:${SERVER_PORT}/`;
const SERVER_ORIGIN = new URL(SERVER_URL).origin;

const HISTORY_PATH = () => path.join(app.getPath("userData"), "history.jsonl");
const SESSION_PATH = () => path.join(app.getPath("userData"), "session.json");
const BRIDGE_INFO_PATH = () => path.join(app.getPath("userData"), "bridge.json");

const WEB_PREFS = { contextIsolation: true, sandbox: true, nodeIntegration: false, partition: PARTITION };

let win = null;
let chromeView = null;
let spawnedServer = null;
const tabs = new Map();          // id -> { view, id }
let activeTabId = null;
let contentBounds = { x: 0, y: 220, width: 1280, height: 600 };
let nextTabId = 1;
let chromeReady = false;
let pendingRestore = null;

/* ── Small utilities ────────────────────────────────────────────────── */
function log(...args) { try { console.log("[thomas-desktop]", ...args); } catch (_) { } }
function sendChrome(channel, payload) {
  if (chromeView && !chromeView.webContents.isDestroyed()) chromeView.webContents.send(channel, payload);
}
function tabEvent(id, type, value) { sendChrome("bt:tab-event", { id, type, value }); }

/* ── History (ours, on our disk) ────────────────────────────────────── */
let lastHistoryKey = "";
function recordHistory(url, title) {
  if (!url || url === "about:blank") return;
  const key = url + " " + (title || "");
  if (key === lastHistoryKey) return;
  lastHistoryKey = key;
  try {
    fs.appendFileSync(HISTORY_PATH(), JSON.stringify({ at: new Date().toISOString(), url, title: title || "" }) + "\n");
  } catch (e) { log("history write failed", e); }
}
function readHistory(query, limit) {
  try {
    const lines = fs.readFileSync(HISTORY_PATH(), "utf8").trim().split("\n");
    const q = String(query || "").toLowerCase();
    const rows = [];
    for (let i = lines.length - 1; i >= 0 && rows.length < (limit || 100); i--) {
      let row;
      try { row = JSON.parse(lines[i]); } catch (_) { continue; }
      // A row without a url used to throw past this loop and out of the
      // function, so ONE corrupt line (a crash mid-append, a hand edit)
      // returned an empty history for every query -- indistinguishable from
      // having no history at all. Skip the bad line, keep the rest.
      const url = typeof row.url === "string" ? row.url : "";
      if (!url) continue;
      const title = typeof row.title === "string" ? row.title : "";
      if (!q || url.toLowerCase().includes(q) || title.toLowerCase().includes(q)) rows.push(row);
    }
    return rows;
  } catch (_) { return []; }
}

/* ── Session restore ────────────────────────────────────────────────── */
let sessionSaveTimer = 0;
function saveSessionSoon() {
  clearTimeout(sessionSaveTimer);
  sessionSaveTimer = setTimeout(() => {
    const urls = [...tabs.values()]
      .map(t => t.view.webContents.getURL())
      .filter(u => u && u !== "about:blank");
    try { fs.writeFileSync(SESSION_PATH(), JSON.stringify({ urls })); } catch (_) { }
  }, 800);
}
function loadSavedSession() {
  try {
    const data = JSON.parse(fs.readFileSync(SESSION_PATH(), "utf8"));
    return Array.isArray(data.urls) ? data.urls.filter(u => typeof u === "string") : [];
  } catch (_) { return []; }
}

/* ── CDP (the one agent↔page channel) ───────────────────────────────── */
async function cdpFor(view) {
  const dbg = view.webContents.debugger;
  if (!dbg.isAttached()) {
    dbg.attach("1.3");
    // Gate-6 lesson: press events route through the focus pipeline; an
    // unfocused window drops them. Focus emulation keeps input honest.
    await dbg.sendCommand("Emulation.setFocusEmulationEnabled", { enabled: true });
  }
  return (method, params) => dbg.sendCommand(method, params || {});
}
async function cdpEval(view, expression) {
  const send = await cdpFor(view);
  const out = await send("Runtime.evaluate", { expression, returnByValue: true });
  if (out.exceptionDetails) throw new Error("eval failed");
  return out.result.value;
}
/* The accessibility tree is the anchor a recorded task should hang on.
 *
 * A CSS selector breaks the next time a site changes its markup, and a
 * coordinate breaks on the next reflow. "The button named Pay bill" survives
 * both, because it is what the page means rather than how it is built. This
 * read is also the honest way for the agent to see a page: names and roles,
 * not a screenshot it has to guess at.
 */
const AX_INTERESTING = new Set([
  "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
  "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "switch", "slider",
  "listbox", "option", "heading", "spinbutton",
]);
async function cdpAxSnapshot(view, limit) {
  const send = await cdpFor(view);
  await send("Accessibility.enable");
  const { nodes } = await send("Accessibility.getFullAXTree", {});
  const out = [];
  for (const node of nodes) {
    if (node.ignored) continue;
    const role = node.role && node.role.value;
    const name = node.name && node.name.value;
    if (!role || !AX_INTERESTING.has(String(role))) continue;
    if (!name || !String(name).trim()) continue;
    out.push({
      role: String(role),
      name: String(name).trim().slice(0, 160),
      backendNodeId: node.backendDOMNodeId,
      disabled: Boolean(node.properties && node.properties.some(
        p => p.name === "disabled" && p.value && p.value.value === true)),
    });
    if (out.length >= (limit || 300)) break;
  }
  return out;
}
// Clicking by anchor instead of by selector: same action, addressing that
// survives a redesign. Falls back to nothing -- a miss is reported, never
// approximated, so a caller can ask the model for the equivalent element
// rather than clicking whatever happened to be nearby.
/* Where to click, asked of the element itself.
 *
 * DOM.getBoxModel returns layout coordinates that do not always match the
 * viewport the input dispatcher aims at -- on wikipedia.org's circular link
 * layout it produced x=-100, y=-437, so every click silently landed nowhere.
 * getBoundingClientRect is what the renderer itself would use, after
 * scrolling the element into view, so it cannot disagree with the viewport.
 */
async function clickPointOf(send, handle) {
  const resolved = await send("DOM.resolveNode", handle);
  const objectId = resolved.object && resolved.object.objectId;
  if (!objectId) throw new Error("element could not be resolved");
  const out = await send("Runtime.callFunctionOn", {
    objectId,
    returnByValue: true,
    functionDeclaration: `function () {
      // An accessible name often belongs to a text node or a zero-size
      // wrapper, so climb to the nearest ancestor that actually occupies
      // space -- that is the thing a person would be pointing at.
      let el = this.nodeType === 3 ? this.parentElement : this;
      let guard = 0;
      while (el && guard++ < 8) {
        const box = el.getBoundingClientRect();
        if (box.width > 0 && box.height > 0) break;
        el = el.parentElement;
      }
      if (!el) return null;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rects = el.getClientRects();
      const r = rects && rects.length ? rects[0] : el.getBoundingClientRect();
      return {
        x: r.left + r.width / 2, y: r.top + r.height / 2,
        w: r.width, h: r.height, tag: el.tagName,
        vw: window.innerWidth, vh: window.innerHeight,
      };
    }`,
  });
  const point = out.result && out.result.value;
  if (!point || point.w <= 0 || point.h <= 0) throw new Error("element has no clickable area");
  // Say the numbers. A bare "outside the viewport" sent me guessing twice.
  if (point.x < 0 || point.y < 0 || point.x > point.vw || point.y > point.vh) {
    throw new Error(
      `element sits outside the viewport after scrolling: point ${Math.round(point.x)},${Math.round(point.y)}`
      + ` in a ${point.vw}x${point.vh} view (<${point.tag}>, ${Math.round(point.w)}x${Math.round(point.h)})`);
  }
  return { x: point.x, y: point.y };
}
async function dispatchClick(send, view, point) {
  view.webContents.focus();
  const at = { x: point.x, y: point.y, button: "left", clickCount: 1 };
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0 });
  await send("Input.dispatchMouseEvent", Object.assign({ type: "mousePressed", buttons: 1 }, at));
  await send("Input.dispatchMouseEvent", Object.assign({ type: "mouseReleased", buttons: 0 }, at));
  return point;
}

async function cdpClickAx(view, role, name) {
  const send = await cdpFor(view);
  const nodes = await cdpAxSnapshot(view, 1000);
  const wanted = String(name || "").trim().toLowerCase();
  const match = nodes.find(n =>
    (!role || n.role === role) && n.name.toLowerCase() === wanted)
    || nodes.find(n => (!role || n.role === role) && n.name.toLowerCase().includes(wanted));
  if (!match) throw new Error(`no ${role || "element"} named "${name}" on this page`);
  if (match.disabled) throw new Error(`"${match.name}" is disabled`);
  const point = await clickPointOf(send, { backendNodeId: match.backendNodeId });
  await dispatchClick(send, view, point);
  return { matched: { role: match.role, name: match.name }, at: point };
}

async function cdpClick(view, selector) {
  const send = await cdpFor(view);
  const doc = await send("DOM.getDocument", { depth: 1 });
  const node = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector });
  if (!node.nodeId) throw new Error("selector not found: " + selector);
  const point = await clickPointOf(send, { nodeId: node.nodeId });
  await dispatchClick(send, view, point);
  return point;
}

/* ── Web-content tabs ───────────────────────────────────────────────── */
function applyBoundsTo(view) {
  // Never hand a view a zero rect; fall back to the window's own content area
  // so a tab is always at least usable.
  if (contentBounds.width <= 0 || contentBounds.height <= 0) {
    const b = win ? win.getContentBounds() : { width: 1280, height: 800 };
    contentBounds = { x: 0, y: Math.min(220, b.height), width: b.width, height: Math.max(1, b.height - 220) };
  }
  view.setBounds({
    x: Math.round(contentBounds.x), y: Math.round(contentBounds.y),
    width: Math.max(0, Math.round(contentBounds.width)),
    height: Math.max(0, Math.round(contentBounds.height)),
  });
}
/* Keyboard conventions, caught before the page gets them.
 *
 * A focused web tab is its own renderer, so while you are looking at a
 * website the chrome page receives no key events at all -- Ctrl+T would do
 * nothing, which is exactly the "looks like tabs, is not tabs" failure. The
 * main process watches every view and forwards the ACTION to the chrome,
 * where the behaviour is implemented once.
 */
function shortcutFor(input) {
  if (input.type !== "keyDown") return null;
  const ctrl = input.control || input.meta;
  const key = String(input.key || "");
  const lower = key.toLowerCase();
  if (ctrl && !input.alt) {
    if (lower === "t" && !input.shift) return { action: "new-tab" };
    if (lower === "w" && !input.shift) return { action: "close-tab" };
    if (lower === "l" && !input.shift) return { action: "focus-omnibox" };
    if (lower === "r" && !input.shift) return { action: "reload" };
    if (key === "Tab") return { action: input.shift ? "prev-tab" : "next-tab" };
    if (/^[1-9]$/.test(key) && !input.shift) return { action: "select-tab", arg: Number(key) };
  }
  if (input.alt && !ctrl) {
    if (key === "Left" || key === "ArrowLeft") return { action: "back" };
    if (key === "Right" || key === "ArrowRight") return { action: "forward" };
    if (lower === "d") return { action: "focus-omnibox" };
  }
  if (key === "F5" && !ctrl && !input.alt) return { action: "reload" };
  return null;
}
function watchShortcuts(wc) {
  wc.on("before-input-event", (event, input) => {
    const hit = shortcutFor(input);
    if (!hit) return;
    event.preventDefault();               // the website never sees it
    sendChrome("bt:shortcut", hit);
  });
}

function createTab() {
  const id = nextTabId++;
  const view = new WebContentsView({ webPreferences: Object.assign({}, WEB_PREFS) });
  const wc = view.webContents;
  watchShortcuts(wc);
  tabs.set(id, { id, view });
  view.setVisible(false);
  win.contentView.addChildView(view);
  applyBoundsTo(view);

  wc.on("page-title-updated", (_e, title) => { tabEvent(id, "title", title); recordHistory(wc.getURL(), title); });
  wc.on("page-favicon-updated", (_e, favicons) => {
    if (!Array.isArray(favicons) || !favicons[0]) return;
    const icon = String(favicons[0]);
    const entry = tabs.get(id);
    if (entry) entry.favicon = icon;      // so list_tabs can report it too
    tabEvent(id, "favicon", icon);
  });
  wc.on("did-navigate", (_e, url) => { tabEvent(id, "url", url); recordHistory(url, wc.getTitle()); saveSessionSoon(); });
  wc.on("did-navigate-in-page", (_e, url, isMain) => { if (isMain) { tabEvent(id, "url", url); saveSessionSoon(); } });
  wc.on("did-start-loading", () => tabEvent(id, "loading", true));
  wc.on("did-stop-loading", () => tabEvent(id, "loading", false));
  wc.on("render-process-gone", (_e, details) => tabEvent(id, "crashed", details.reason));
  // target=_blank and window.open become OUR tabs, never OS windows.
  wc.setWindowOpenHandler(({ url }) => { tabEvent(id, "new-window", url); return { action: "deny" }; });
  return id;
}
function activateTab(id) {
  activeTabId = id;
  for (const t of tabs.values()) t.view.setVisible(t.id === id);
  if (id != null && tabs.has(id)) {
    const view = tabs.get(id).view;
    win.contentView.addChildView(view);          // re-add puts it on top of the chrome
    applyBoundsTo(view);
  }
}
function closeTab(id) {
  const t = tabs.get(id);
  if (!t) return;
  try { win.contentView.removeChildView(t.view); } catch (_) { }
  t.view.webContents.close();
  tabs.delete(id);
  if (activeTabId === id) activeTabId = null;
  saveSessionSoon();
}

/* ── IPC: the preload contract ──────────────────────────────────────── */
ipcMain.handle("bt:create-tab", () => createTab());
ipcMain.handle("bt:navigate", async (_e, { id, url }) => {
  const t = tabs.get(id); if (!t) throw new Error("no tab " + id);
  const u = new URL(url);                          // malformed URLs throw here
  if (!["http:", "https:"].includes(u.protocol)) throw new Error("unsupported scheme " + u.protocol);
  // RETURN the promise. Without it, invoke() resolved before the request had
  // even started, so a dead domain or a refused connection reported success
  // and the page's .catch -- written for exactly that -- was unreachable.
  // Only synchronous throws ever got there.
  return t.view.webContents.loadURL(u.toString());
});
ipcMain.handle("bt:activate-tab", (_e, { id }) => activateTab(id));
ipcMain.handle("bt:close-tab", (_e, { id }) => closeTab(id));
ipcMain.handle("bt:back", (_e, { id }) => { const t = tabs.get(id); if (t) t.view.webContents.navigationHistory.goBack(); });
ipcMain.handle("bt:forward", (_e, { id }) => { const t = tabs.get(id); if (t) t.view.webContents.navigationHistory.goForward(); });
ipcMain.handle("bt:reload", (_e, { id }) => { const t = tabs.get(id); if (t) t.view.webContents.reload(); });
ipcMain.handle("bt:set-bounds", (_e, rect) => {
  // A ResizeObserver fires once immediately, and if the chrome page has not
  // laid out yet that first rect is 0x0. Accepting it left the view sized to
  // nothing: pages rendered into a zero viewport, so every computed click
  // point fell outside it and nothing was ever clickable. Nothing legitimate
  // asks for a zero-size view, so ignore those and keep the last good size.
  if (!rect || rect.width <= 0 || rect.height <= 0) return;
  contentBounds = { x: rect.x || 0, y: rect.y || 0, width: rect.width, height: rect.height };
  if (activeTabId != null && tabs.has(activeTabId)) applyBoundsTo(tabs.get(activeTabId).view);
});
ipcMain.handle("bt:window-control", (_e, { action }) => {
  if (!win) return;
  if (action === "min") win.minimize();
  else if (action === "max") { if (win.isMaximized()) win.unmaximize(); else win.maximize(); }
  else if (action === "close") win.close();
});
ipcMain.handle("bt:get-history", (_e, { query, limit }) => readHistory(query, limit));
// A native view paints over the chrome page, so every HTML dropdown the
// shell already owns -- the model picker, Tools, the library, the theme list
// -- is invisible while a web tab is showing. The page tells us when one is
// open and the view steps aside for as long as it is.
ipcMain.handle("bt:suspend-view", (_e, { suspended }) => {
  if (activeTabId == null || !tabs.has(activeTabId)) return;
  tabs.get(activeTabId).view.setVisible(!suspended);
});
// Native menus, because a WebContentsView paints OVER the chrome page: an
// HTML dropdown is simply invisible whenever a web tab is active. The page
// sends a serialisable spec and gets back the chosen id (or null).
ipcMain.handle("bt:popup-menu", (_e, { items, x, y }) => new Promise(resolve => {
  let settled = false;
  const done = value => { if (!settled) { settled = true; resolve(value); } };
  const template = (Array.isArray(items) ? items : []).map(item => {
    if (item && item.type === "separator") return { type: "separator" };
    return {
      label: String(item && item.label || ""),
      type: item && item.checked !== undefined ? "checkbox" : "normal",
      checked: Boolean(item && item.checked),
      enabled: item ? item.enabled !== false : true,
      click: () => done(item && item.id),
    };
  });
  try {
    Menu.buildFromTemplate(template).popup({
      window: win,
      x: Math.round(x || 0),
      y: Math.round(y || 0),
      callback: () => done(null),        // dismissed without choosing
    });
  } catch (e) {
    // Verified working on Electron 43.4.1, but a dead button is a worse
    // failure than a plain dropdown: say so and let the page fall back.
    log("native menu unavailable:", e && e.message);
    done("__unsupported__");
  }
}));
ipcMain.handle("bt:get-state", () => ({
  versions: { electron: process.versions.electron, chromium: process.versions.chrome },
  serverUrl: SERVER_URL,
}));
ipcMain.handle("bt:chrome-ready", () => {
  chromeReady = true;
  if (pendingRestore && pendingRestore.length) {
    sendChrome("bt:restore", pendingRestore);
    pendingRestore = null;
  }
});

/* ── Downloads: land in the user's Downloads dir, chrome gets progress ── */
function wireDownloads() {
  session.fromPartition(PARTITION).on("will-download", (_e, item) => {
    const file = path.join(app.getPath("downloads"), item.getFilename());
    item.setSavePath(file);
    item.on("updated", () => tabEvent(activeTabId, "download", {
      state: "progress", filename: item.getFilename(),
      received: item.getReceivedBytes(), total: item.getTotalBytes(),
    }));
    item.once("done", (_ev, state) => tabEvent(activeTabId, "download", {
      state, filename: item.getFilename(), path: file,
    }));
  });
}

/* ── Agent bridge: Thomas's Python brain drives tabs over CDP ───────── */
function startBridge() {
  let WebSocketServer;
  try { ({ WebSocketServer } = require("ws")); } catch (e) { log("ws missing; bridge disabled", e); return; }
  const token = crypto.randomBytes(16).toString("hex");
  const wss = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  wss.once("listening", () => {
    const port = wss.address().port;
    try { fs.writeFileSync(BRIDGE_INFO_PATH(), JSON.stringify({ port, token })); } catch (_) { }
    log("agent bridge on ws://127.0.0.1:" + port);
  });
  const forTab = id => {
    const t = id != null ? tabs.get(id) : tabs.get(activeTabId);
    if (!t) throw new Error("no such tab (pass tabId or activate one)");
    return t.view;
  };
  /* A hidden view has a 0x0 viewport, so every computed click point falls
     outside it and the click silently does nothing. Acting on a background
     tab therefore means bringing it forward first -- which is also what a
     person would do, and it keeps the agent's work visible instead of
     happening to a tab nobody is looking at. */
  const forTabInteractive = id => {
    const t = id != null ? tabs.get(id) : tabs.get(activeTabId);
    if (!t) throw new Error("no such tab (pass tabId or activate one)");
    if (t.id !== activeTabId) {
      activateTab(t.id);
      tabEvent(t.id, "agent-activated", true);
    }
    return t.view;
  };
  const commands = {
    list_tabs: async () => [...tabs.values()].map(t => ({
      tabId: t.id, url: t.view.webContents.getURL(), title: t.view.webContents.getTitle(),
      favicon: t.favicon || null,
      active: t.id === activeTabId,
    })),
    // Open a URL THROUGH the chrome page, so the tab strip stays truthful —
    // the agent's tabs and the user's tabs are the same tabs.
    open_url: async p => { tabEvent(null, "new-window", new URL(p.url).toString()); return { requested: p.url }; },
    navigate: async p => {
      const view = forTab(p.tabId);
      await view.webContents.loadURL(new URL(p.url).toString());
      return { url: view.webContents.getURL() };
    },
    read_dom: async p => JSON.parse(await cdpEval(forTab(p.tabId),
      "JSON.stringify({ url: location.href, title: document.title, text: document.body ? document.body.innerText.slice(0, 20000) : '', htmlChars: document.documentElement.outerHTML.length })")),
    click: async p => {
      const view = forTabInteractive(p.tabId);
      const point = await cdpClick(view, p.selector);
      return { clickedAt: point, url: view.webContents.getURL() };
    },
    // What the page offers, by name and role -- the anchors a recorded task
    // should be written against.
    snapshot: async p => {
      const view = forTab(p.tabId);
      const nodes = await cdpAxSnapshot(view, p.limit);
      return { url: view.webContents.getURL(), count: nodes.length, nodes };
    },
    // Same click, addressed the way a person would describe it.
    click_named: async p => {
      const view = forTabInteractive(p.tabId);
      const result = await cdpClickAx(view, p.role, p.name);
      return { ...result, url: view.webContents.getURL() };
    },
    url: async p => ({ url: forTab(p.tabId).webContents.getURL() }),
    // Geometry, from both sides. When a click lands nowhere the first
    // question is always "how big does the page think it is", and guessing
    // that cost an hour once.
    metrics: async p => {
      const view = forTab(p.tabId);
      const page = await cdpEval(view,
        "JSON.stringify({ innerWidth: window.innerWidth, innerHeight: window.innerHeight, dpr: window.devicePixelRatio })");
      return {
        viewBounds: view.getBounds(),
        contentBounds,
        visible: view.getVisible ? view.getVisible() : null,
        windowContent: win ? win.getContentBounds() : null,
        page: JSON.parse(page),
      };
    },
  };
  wss.on("connection", (sock, req) => {
    const u = new URL(req.url, "ws://x");
    if (u.searchParams.get("token") !== token) { sock.close(4001, "bad token"); return; }
    sock.on("message", async raw => {
      let msg;
      try {
        msg = JSON.parse(raw);
      } catch (_) {
        // Answer anyway. Dropping the frame left a caller awaiting a reply
        // that could never come, which is a hang rather than an error.
        sock.send(JSON.stringify({ id: null, ok: false, error: "malformed JSON frame" }));
        return;
      }
      try {
        const fn = commands[msg.cmd];
        if (!fn) throw new Error("unknown cmd " + msg.cmd);
        sock.send(JSON.stringify({ id: msg.id, ok: true, result: await fn(msg.params || {}) }));
      } catch (e) {
        sock.send(JSON.stringify({ id: msg.id, ok: false, error: String(e && e.message || e) }));
      }
    });
  });
}

/* ── Server attach/spawn ────────────────────────────────────────────── */
async function serverHealthy() {
  try {
    const res = await fetch(SERVER_URL.replace(/\/$/, "") + "/api/health", { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch (_) { return false; }
}
async function ensureServer() {
  if (await serverHealthy()) return true;
  if (process.env.THOMAS_NO_SPAWN_SERVER === "1") return false;
  const venvPy = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
  if (!fs.existsSync(venvPy)) return false;
  log("server not running; spawning on port", SERVER_PORT);
  spawnedServer = spawn(venvPy, ["-m", "thomas.server", "--host", "127.0.0.1", "--port", String(SERVER_PORT)], {
    cwd: REPO_ROOT, stdio: "ignore",
  });
  for (let i = 0; i < 120; i++) {
    if (await serverHealthy()) return true;
    await new Promise(r => setTimeout(r, 500));
  }
  return false;
}

/* ── Self-update (real once packaged + a feed exists) ───────────────── */
function wireUpdater() {
  if (!app.isPackaged) { log("updater: skipped (unpackaged dev run)"); return; }
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.checkForUpdatesAndNotify().catch(e => log("updater check failed", e));
  } catch (e) { log("updater unavailable", e); }
}

/* ── Boot ───────────────────────────────────────────────────────────── */
app.whenReady().then(async () => {
  win = new BaseWindow({ width: 1440, height: 900, frame: false, title: "Thomas", minWidth: 900, minHeight: 600, icon: APP_ICON });

  chromeView = new WebContentsView({
    webPreferences: Object.assign({ preload: path.join(__dirname, "preload.js") }, WEB_PREFS),
  });
  win.contentView.addChildView(chromeView);
  // The chrome page has its own keydown listener, but catching combos here
  // too means they work identically whichever surface holds focus.
  watchShortcuts(chromeView.webContents);
  const fitChrome = () => {
    const b = win.getContentBounds();
    chromeView.setBounds({ x: 0, y: 0, width: b.width, height: b.height });
  };
  fitChrome();
  win.on("resize", fitChrome);

  // The chrome view must never wander off to the internet — web content
  // belongs to tab views. Anything non-server becomes a tab.
  chromeView.webContents.on("will-navigate", (e, url) => {
    if (new URL(url).origin !== SERVER_ORIGIN) { e.preventDefault(); tabEvent(null, "new-window", url); }
  });
  chromeView.webContents.setWindowOpenHandler(({ url }) => {
    tabEvent(null, "new-window", url); return { action: "deny" };
  });

  wireDownloads();
  startBridge();
  wireUpdater();
  pendingRestore = loadSavedSession();

  const ok = await ensureServer();
  if (ok) {
    chromeView.webContents.loadURL(SERVER_URL);
  } else {
    chromeView.webContents.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(
      "<body style='background:#070912;color:#eef0fb;font-family:sans-serif;display:grid;place-items:center;height:100vh;margin:0'>"
      + "<div style='text-align:center'><h2>Thomas server isn’t reachable</h2>"
      + "<p>Expected " + SERVER_URL + " — start it (run-ui.cmd) and relaunch.</p></div></body>"));
  }
});

app.on("before-quit", () => {
  // We only stop a server WE spawned; an attached one belongs to the user.
  if (spawnedServer && !spawnedServer.killed) { try { spawnedServer.kill(); } catch (_) { } }
});
app.on("window-all-closed", () => app.quit());
