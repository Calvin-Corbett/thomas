/* main.js — the Thomas desktop app: a real browser shell around the Thomas
 * web chrome.
 *
 * Architecture (runtime decision, 2026-08-25):
 *  - One frameless BaseWindow PER WINDOW (a "shell"), as many as you open. The
 *    CHROME view (a WebContentsView with preload.js) fills each and loads the Python server's page at / — the same
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
 *  - Windows behave like a browser's: the title bar drags the window (the page
 *    streams the pointer, this process moves the window, so it works across
 *    monitors), a tab dragged off the strip becomes a window of its own, and
 *    dropping it on another window's strip joins that window. A web tab's view
 *    is re-parented, so the page keeps its state; a Chat, Build or Work tab is
 *    opened again in the new window.
 *  - Security defaults are non-negotiable everywhere: contextIsolation:true,
 *    sandbox:true, nodeIntegration:false. Web tabs get no preload at all.
 *
 * Modes: `electron .` runs the app. The Phase-1 gauntlet lives in spike.js
 * (`electron spike.js --gates|--verify-persist|--bridge`) and must keep
 * passing on every Electron bump.
 */
"use strict";

const { app, BaseWindow, WebContentsView, session, ipcMain, Menu, screen } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const geometry = require("./window_geometry");

const REPO_ROOT = path.join(__dirname, "..");
const PARTITION = "persist:thomas";
app.setPath("userData", process.env.THOMAS_DESKTOP_PROFILE_DIR || path.join(REPO_ROOT, "runtime", "browser_profile"));
const startup = require("./startup_clock")({ app, path, fs }); // timings + the waiting screen; the override lets a timing run use its own profile

// The taskbar showed the default Electron icon, because an unpackaged Electron
// app has no identity of its own: Windows groups and labels a window by its
// AppUserModelID, and falls back to electron.exe's own icon when the window
// carries none. Both have to be set, and the ID has to be set before any window
// exists or Windows keeps the identity it already assigned to the process.
const APP_ICON = path.join(REPO_ROOT, "assets", "thomas.ico");
if (process.platform === "win32") app.setAppUserModelId("com.thomas.desktop");

if (!app.requestSingleInstanceLock()) app.exit(0);
// A second launch is another window, the way a second click on a browser icon is.
let wantSecondWindow = false;
app.on("second-instance", () => { if (app.isReady() && serverUp) openWindow(); else wantSecondWindow = true; });

const argv = process.argv.slice(1);
function argValue(name, fallback) {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
}
const SERVER_PORT = Number(argValue("--server-port", process.env.THOMAS_SERVER_PORT || "8899"));
// Caged: the server is the cage account's, started only by its scheduled task.
// A server this app spawned would run as you, with your rights.
const CAGED = argv.includes("--caged") || process.env.THOMAS_CAGED === "1";
const CAGED_TASK = "ThomasCagedServer";
const SERVER_URL = process.env.THOMAS_SERVER_URL || `http://127.0.0.1:${SERVER_PORT}/`;
const SERVER_ORIGIN = new URL(SERVER_URL).origin;

const HISTORY_PATH = () => path.join(app.getPath("userData"), "history.jsonl");
const SESSION_PATH = () => path.join(app.getPath("userData"), "session.json");
const BRIDGE_INFO_PATH = () => path.join(app.getPath("userData"), "bridge.json");

const WEB_PREFS = { contextIsolation: true, sandbox: true, nodeIntegration: false, partition: PARTITION };

let spawnedServer = null;
// One shell per window: { id, win, chromeView, activeTabId, contentBounds,
// chromeReady, pendingRestore, pendingAdopt }. A tab id is unique across all of
// them, so the agent bridge and the IPC handlers can name a tab on its own.
const shells = new Map();
let nextShellId = 1;
let frontShell = null;           // the window last focused
const tabs = new Map();          // id -> { view, id, shell, favicon }
let nextTabId = 1;
let serverUp = false;
// The pointer position normally comes from the OS (screen.getCursorScreenPoint),
// which is the only source that cannot lag a window it is moving. A test run
// that drives the page with synthetic events, and so cannot move the real
// cursor, may name its own points through this switch.
const POINTER_FROM_PAGE = process.env.THOMAS_DESKTOP_POINTER_FROM_PAGE === "1";

/* ── Small utilities ────────────────────────────────────────────────── */
function log(...args) { try { console.log("[thomas-desktop]", ...args); } catch (_) { } }
function sendChrome(shell, channel, payload) {
  const view = shell && shell.chromeView;
  if (view && !view.webContents.isDestroyed()) view.webContents.send(channel, payload);
}
function tabEvent(shell, id, type, value) { sendChrome(shell, "bt:tab-event", { id, type, value }); }
// Every IPC call comes from a window's chrome page; its sender names the window.
function shellFor(event) {
  for (const shell of shells.values()) {
    if (!shell.chromeView.webContents.isDestroyed() && shell.chromeView.webContents === event.sender) return shell;
  }
  return null;
}
// The window an agent command or a shortcut means when it names none.
function currentShell() {
  if (frontShell && shells.has(frontShell.id)) return frontShell;
  return shells.values().next().value || null;
}

/* The chrome page cannot read a WebContentsView's history, so Back and Forward
 * there can only guess at whether they have anywhere to go -- and a navigation
 * button that is lit and does nothing reads as a broken browser. After every
 * navigation the view says which way it can actually move. */
function sendNav(id, wc) {
  if (wc.isDestroyed()) return;
  const entry = tabs.get(id);
  const nav = wc.navigationHistory;
  if (entry) tabEvent(entry.shell, id, "nav", { back: nav.canGoBack(), forward: nav.canGoForward() });
}

/* ── History (ours, on our disk) ────────────────────────────────────── */
const { recordHistory, readHistory } = require("./history").create({ historyPath: HISTORY_PATH, log });

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

/* ── CDP (the one agent↔page channel) lives in cdp.js ───────────────── */
const { cdpEval, cdpAxSnapshot, cdpClickAx, cdpClick } = require("./cdp");

/* ── Web-content tabs ───────────────────────────────────────────────── */
function applyBoundsTo(shell, view) {
  // Never hand a view a zero rect; fall back to the window's own content area
  // so a tab is always at least usable.
  let contentBounds = shell.contentBounds;
  if (contentBounds.width <= 0 || contentBounds.height <= 0) {
    const b = shell.win ? shell.win.getContentBounds() : { width: 1280, height: 800 };
    contentBounds = shell.contentBounds = { x: 0, y: Math.min(220, b.height), width: b.width, height: Math.max(1, b.height - 220) };
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
    if (lower === "n" && !input.shift) return { action: "new-window" };
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
function watchShortcuts(wc, shellOf) {
  wc.on("before-input-event", (event, input) => {
    const hit = shortcutFor(input);
    if (!hit) return;
    event.preventDefault();               // the website never sees it
    if (hit.action === "new-window") { openWindow(); return; }
    sendChrome(shellOf(), "bt:shortcut", hit);
  });
}

function createTab(shell) {
  const id = nextTabId++;
  const view = new WebContentsView({ webPreferences: Object.assign({}, WEB_PREFS) });
  const wc = view.webContents;
  const entry = { id, view, shell };
  // A tab can move to another window, so every handler asks the entry which
  // window it is in now rather than remembering the one it was born in.
  const say = (type, value) => tabEvent(entry.shell, id, type, value);
  watchShortcuts(wc, () => entry.shell);
  tabs.set(id, entry);
  view.setVisible(false);
  shell.win.contentView.addChildView(view);
  applyBoundsTo(shell, view);

  wc.on("page-title-updated", (_e, title) => { say("title", title); recordHistory(wc.getURL(), title); });
  wc.on("page-favicon-updated", (_e, favicons) => {
    if (!Array.isArray(favicons) || !favicons[0]) return;
    const icon = String(favicons[0]);
    entry.favicon = icon;                 // so list_tabs can report it too
    say("favicon", icon);
  });
  wc.on("did-navigate", (_e, url) => { say("url", url); sendNav(id, wc); recordHistory(url, wc.getTitle()); saveSessionSoon(); });
  wc.on("did-navigate-in-page", (_e, url, isMain) => { if (isMain) { say("url", url); sendNav(id, wc); saveSessionSoon(); } });
  wc.on("did-start-loading", () => say("loading", true));
  wc.on("did-stop-loading", () => { say("loading", false); sendNav(id, wc); });
  wc.on("render-process-gone", (_e, details) => say("crashed", details.reason));
  // target=_blank and window.open become OUR tabs, never OS windows.
  wc.setWindowOpenHandler(({ url }) => { say("new-window", url); return { action: "deny" }; });
  return id;
}
function activateTab(shell, id) {
  shell.activeTabId = id;
  for (const t of tabs.values()) if (t.shell === shell) t.view.setVisible(t.id === id);
  if (id != null && tabs.has(id)) {
    const view = tabs.get(id).view;
    shell.win.contentView.addChildView(view);    // re-add puts it on top of the chrome
    applyBoundsTo(shell, view);
  }
}
function closeTab(id) {
  const t = tabs.get(id);
  if (!t) return;
  try { t.shell.win.contentView.removeChildView(t.view); } catch (_) { }
  t.view.webContents.close();
  tabs.delete(id);
  if (t.shell.activeTabId === id) t.shell.activeTabId = null;
  saveSessionSoon();
}
/* A web tab changes windows by changing parents: the same view, so the page,
 * its scroll and its history all arrive with it. The new window's chrome page
 * then shows it as a tab of its own (bt:adopt). */
function moveTab(id, toShell) {
  const t = tabs.get(id);
  if (!t || t.shell === toShell) return t || null;
  const from = t.shell;
  try { from.win.contentView.removeChildView(t.view); } catch (_) { }
  if (from.activeTabId === id) from.activeTabId = null;
  t.shell = toShell;
  t.view.setVisible(false);
  toShell.win.contentView.addChildView(t.view);
  applyBoundsTo(toShell, t.view);
  saveSessionSoon();
  return t;
}

/* ── IPC: the preload contract ──────────────────────────────────────── */
ipcMain.handle("bt:create-tab", e => createTab(shellFor(e)));
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
ipcMain.handle("bt:activate-tab", (e, { id }) => activateTab(shellFor(e), id));
ipcMain.handle("bt:close-tab", (_e, { id }) => closeTab(id));
// Answers whether the view actually moved. A tab opened from a Thomas Search
// result was created for that result and holds a single entry, so goBack() is
// a silent no-op there; the chrome needs the answer to return to the results
// itself rather than leave the button lit and inert.
ipcMain.handle("bt:back", (_e, { id }) => {
  const t = tabs.get(id);
  if (!t) return false;
  const nav = t.view.webContents.navigationHistory;
  if (!nav.canGoBack()) return false;
  nav.goBack();
  return true;
});
// The twin of bt:back, and answers the same way: whether the view moved.
ipcMain.handle("bt:forward", (_e, { id }) => {
  const t = tabs.get(id);
  if (!t) return false;
  const nav = t.view.webContents.navigationHistory;
  if (!nav.canGoForward()) return false;
  nav.goForward();
  return true;
});
ipcMain.handle("bt:reload", (_e, { id }) => { const t = tabs.get(id); if (t) t.view.webContents.reload(); });
ipcMain.handle("bt:set-bounds", (e, rect) => {
  const shell = shellFor(e);
  if (!shell) return;
  // A ResizeObserver fires once immediately, and if the chrome page has not
  // laid out yet that first rect is 0x0. Accepting it left the view sized to
  // nothing: pages rendered into a zero viewport, so every computed click
  // point fell outside it and nothing was ever clickable. Nothing legitimate
  // asks for a zero-size view, so ignore those and keep the last good size.
  if (!rect || rect.width <= 0 || rect.height <= 0) return;
  shell.contentBounds = { x: rect.x || 0, y: rect.y || 0, width: rect.width, height: rect.height };
  if (shell.activeTabId != null && tabs.has(shell.activeTabId)) applyBoundsTo(shell, tabs.get(shell.activeTabId).view);
});
ipcMain.handle("bt:window-control", (e, { action }) => {
  const shell = shellFor(e);
  if (!shell) return;
  const win = shell.win;
  if (action === "min") win.minimize();
  else if (action === "max") { if (win.isMaximized()) win.unmaximize(); else win.maximize(); }
  else if (action === "close") win.close();
  else if (action === "new") openWindow();
});
ipcMain.handle("bt:get-history", (_e, { query, limit }) => readHistory(query, limit));
// A native view paints over the chrome page, so every HTML dropdown the
// shell already owns -- the model picker, Tools, the library, the theme list
// -- is invisible while a web tab is showing. The page tells us when one is
// open and the view steps aside for as long as it is.
ipcMain.handle("bt:suspend-view", (e, { suspended }) => {
  const shell = shellFor(e);
  if (!shell || shell.activeTabId == null || !tabs.has(shell.activeTabId)) return;
  tabs.get(shell.activeTabId).view.setVisible(!suspended);
});
// Native menus, because a WebContentsView paints OVER the chrome page: an
// HTML dropdown is simply invisible whenever a web tab is active. The page
// sends a serialisable spec and gets back the chosen id (or null).
ipcMain.handle("bt:popup-menu", (e, { items, x, y }) => new Promise(resolve => {
  const shell = shellFor(e);
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
      window: shell && shell.win,
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
ipcMain.handle("bt:chrome-ready", e => {
  const shell = shellFor(e);
  if (!shell) return;
  shell.chromeReady = true;
  if (shell.pendingRestore && shell.pendingRestore.length) {
    sendChrome(shell, "bt:restore", shell.pendingRestore);
    shell.pendingRestore = null;
  }
  // A tab that was torn off or dropped here before the page was up.
  while (shell.pendingAdopt.length) sendChrome(shell, "bt:adopt", shell.pendingAdopt.shift());
});

/* ── Downloads: land in the user's Downloads dir, chrome gets progress ── */
function wireDownloads() {
  session.fromPartition(PARTITION).on("will-download", (_e, item, webContents) => {
    const file = path.join(app.getPath("downloads"), item.getFilename());
    item.setSavePath(file);
    // The window whose tab started the download hears about it.
    const owner = () => {
      const t = [...tabs.values()].find(x => x.view.webContents === webContents);
      return { shell: t ? t.shell : currentShell(), id: t ? t.id : null };
    };
    item.on("updated", () => tabEvent(owner().shell, owner().id, "download", {
      state: "progress", filename: item.getFilename(),
      received: item.getReceivedBytes(), total: item.getTotalBytes(),
    }));
    item.once("done", (_ev, state) => tabEvent(owner().shell, owner().id, "download", {
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
  const activeOf = () => { const sh = currentShell(); return sh ? sh.activeTabId : null; };
  const extra = require("./bridge_extra")({ shells, tabs, currentShell, app, path, fs, openWindow });
  const forTab = id => {
    const chrome = extra.chromeOf(id); if (chrome) return chrome;
    const t = id != null ? tabs.get(id) : tabs.get(activeOf());
    if (!t) throw new Error("no such tab (pass tabId or activate one)");
    return t.view;
  };
  /* A hidden view has a 0x0 viewport, so every computed click point falls
     outside it and the click silently does nothing. Acting on a background
     tab therefore means bringing it forward first -- which is also what a
     person would do, and it keeps the agent's work visible instead of
     happening to a tab nobody is looking at. */
  const forTabInteractive = id => {
    const chrome = extra.chromeOf(id); if (chrome) return chrome;
    const t = id != null ? tabs.get(id) : tabs.get(activeOf());
    if (!t) throw new Error("no such tab (pass tabId or activate one)");
    if (t.id !== t.shell.activeTabId) {
      activateTab(t.shell, t.id);
      tabEvent(t.shell, t.id, "agent-activated", true);
    }
    return t.view;
  };
  const commands = {
    ...extra.commands(forTab, forTabInteractive),
    list_tabs: async () => [...extra.chromeTabs(), ...[...tabs.values()].map(t => ({
      tabId: t.id, url: t.view.webContents.getURL(), title: t.view.webContents.getTitle(),
      favicon: t.favicon || null,
      windowId: t.shell.id,
      active: t.id === t.shell.activeTabId,
    }))],
    // Open a URL THROUGH the chrome page, so the tab strip stays truthful —
    // the agent's tabs and the user's tabs are the same tabs.
    list_windows: async () => [...shells.values()].map(sh => ({
      windowId: sh.id, bounds: sh.win.getBounds(), maximized: sh.win.isMaximized(),
      resizable: sh.win.isResizable(), movable: sh.win.isMovable(), displayId: screen.getDisplayMatching(sh.win.getBounds()).id,
      focused: sh.win.isFocused(), tabs: [...tabs.values()].filter(t => t.shell === sh).map(t => t.id),
    })),
    open_url: async p => { tabEvent(currentShell(), null, "new-window", new URL(p.url).toString()); return { requested: p.url }; },
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
      const entry = [...tabs.values()].find(x => x.view === view);
      const shell = entry ? entry.shell : currentShell();
      return {
        viewBounds: view.getBounds(),
        contentBounds: shell.contentBounds,
        visible: view.getVisible ? view.getVisible() : null,
        windowContent: shell.win.getContentBounds(),
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
// Four self-improvement engines (code-issue, self-upgrade, UI-workflow, local-agent)
// default to on and run background checks: a heartbeat script, configuration and release
// checks, image-provider searches, local Ollama and git status reads. scripts/run-ui.ps1
// turns all six engine flags off for a server it starts; a server this app starts gets the
// same defaults.
// A value you have set wins. An empty one is not a value: the engines read it as
// unset and fall back to on, which is what this is here to prevent.
const QUIET_ENGINE_VARS = [
  "THOMAS_CODE_ISSUE_ENGINE_ENABLED",
  "THOMAS_SELF_UPGRADE_ENGINE_ENABLED",
  "THOMAS_UI_WORKFLOW_ENGINE_ENABLED",
  "THOMAS_LOCAL_AGENT_ENGINE_ENABLED",
  "THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED",
  "THOMAS_WORKSPACE_SYNC_AUTO_PUSH",
];
function serverEnv() {
  const env = Object.assign({}, process.env);
  for (const name of QUIET_ENGINE_VARS) if (String(env[name] || "").trim() === "") env[name] = "0";
  return env;
}
async function serverHealthy() {
  try {
    const res = await fetch(SERVER_URL.replace(/\/$/, "") + "/api/health", { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch (_) { return false; }
}
async function ensureServer() {
  if (await serverHealthy()) { startup.info.serverMode = "attached"; return true; }
  startup.info.serverMode = CAGED ? "caged-task" : "spawned";
  if (process.env.THOMAS_NO_SPAWN_SERVER === "1") return false;
  if (CAGED) {
    // Its task runs it as the cage account; you may start it without elevation.
    // Never stopped on quit: it is not ours (spawnedServer stays null).
    log("caged server not running; starting its task", CAGED_TASK);
    spawn("schtasks", ["/Run", "/TN", CAGED_TASK], { stdio: "ignore", windowsHide: true });
  } else {
    const venvPy = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
    if (!fs.existsSync(venvPy)) return false;
    log("server not running; spawning on port", SERVER_PORT);
    spawnedServer = spawn(venvPy, ["-m", "thomas.server", "--host", "127.0.0.1", "--port", String(SERVER_PORT)], {
      cwd: REPO_ROOT, env: serverEnv(), stdio: "ignore",
    });
  }
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

/* ── Windows ────────────────────────────────────────────────────────── */
function workAreaOf(bounds) { return screen.getDisplayMatching(bounds).workArea; }

function createShell(opts) {
  const o = opts || {};
  const shell = {
    id: nextShellId++, win: null, chromeView: null, activeTabId: null,
    contentBounds: { x: 0, y: 220, width: 1280, height: 600 },
    chromeReady: false, pendingRestore: o.restore || null, pendingAdopt: o.adopt ? o.adopt.slice() : [],
    size: null,
  };
  const b = o.bounds || {};
  shell.win = new BaseWindow({
    width: b.width || 1440, height: b.height || 900,
    x: Number.isFinite(b.x) ? b.x : undefined, y: Number.isFinite(b.y) ? b.y : undefined,
    frame: false, title: "Thomas", minWidth: 900, minHeight: 600, icon: APP_ICON,
  });
  // The size this window was asked to be. On a display scaled to a fraction
  // (150%, 175%) Windows rounds every size it is handed, so feeding a window
  // the size it reports back makes it a pixel larger with each move; moves
  // therefore always ask for this size, which only a resize by hand changes.
  shell.size = { width: b.width || 1440, height: b.height || 900 };
  shell.win.on("resized", () => { if (!shell.win.isMaximized() && !shell.win.isFullScreen()) shell.size = shell.win.getSize ? { width: shell.win.getSize()[0], height: shell.win.getSize()[1] } : shell.size; });
  shells.set(shell.id, shell);
  frontShell = shell;

  shell.chromeView = new WebContentsView({
    webPreferences: Object.assign({ preload: path.join(__dirname, "preload.js") }, WEB_PREFS),
  });
  shell.win.contentView.addChildView(shell.chromeView);
  // The chrome page has its own keydown listener, but catching combos here
  // too means they work identically whichever surface holds focus.
  watchShortcuts(shell.chromeView.webContents, () => shell);
  const fitChrome = () => {
    const c = shell.win.getContentBounds();
    shell.chromeView.setBounds({ x: 0, y: 0, width: c.width, height: c.height });
  };
  fitChrome();
  shell.win.on("resize", fitChrome);
  shell.win.on("focus", () => { frontShell = shell; });

  // The chrome view must never wander off to the internet — web content
  // belongs to tab views. Anything non-server becomes a tab.
  shell.chromeView.webContents.on("will-navigate", (e, url) => {
    if (new URL(url).origin !== SERVER_ORIGIN) { e.preventDefault(); tabEvent(shell, null, "new-window", url); }
  });
  shell.chromeView.webContents.setWindowOpenHandler(({ url }) => {
    tabEvent(shell, null, "new-window", url); return { action: "deny" };
  });

  shell.win.on("closed", () => {
    shells.delete(shell.id);
    for (const t of [...tabs.values()]) {
      if (t.shell !== shell) continue;
      try { t.view.webContents.close(); } catch (_) { }
      tabs.delete(t.id);
    }
    if (frontShell === shell) frontShell = null;
    if (tabDrag && tabDrag.shell === shell) tabDrag = null;
    if (windowDrag && windowDrag.shell === shell) windowDrag = null;
    // Closing a window closes its tabs; the last window closing is the app
    // quitting, which must keep the tabs the session saved.
    if (shells.size) saveSessionSoon();
  });
  return shell;
}

async function loadShellPage(shell) {
  const up = serverUp || await serverHealthy();
  if (shell.chromeView.webContents.isDestroyed()) return;
  if (up) {
    startup.loadShell(shell.chromeView.webContents, SERVER_URL, SERVER_ORIGIN);
  } else {
    shell.chromeView.webContents.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(
      "<body style='background:#070912;color:#eef0fb;font-family:sans-serif;display:grid;place-items:center;height:100vh;margin:0'>"
      + "<div style='text-align:center'><h2>Thomas server isn’t reachable</h2>"
      + "<p>Expected " + SERVER_URL + " — "
      + (CAGED ? "the caged server did not start from its task (" + CAGED_TASK + ")." : "start it (run-ui.cmd) and relaunch.")
      + "</p></div></body>"));
  }
}

/* A new window, a little down and to the right of the one in front. */
function openWindow(opts) {
  const o = opts || {};
  const front = currentShell();
  let bounds = o.bounds;
  if (!bounds && front) {
    const from = Object.assign({}, front.win.getBounds(), front.size);
    bounds = geometry.cascadeBounds(from, workAreaOf(from));
  }
  const shell = createShell({ bounds, adopt: o.adopt });
  loadShellPage(shell).catch(e => log("window page failed", e));
  return shell;
}

/* ── Moving a window by its title bar ───────────────────────────────── */
// The page streams "start", "move" and "end"; this process reads where the
// pointer is and moves the window to match.
let windowDrag = null;
function pointerOf(msg) {
  if (POINTER_FROM_PAGE && msg && Number.isFinite(msg.x) && Number.isFinite(msg.y)) return { x: msg.x, y: msg.y };
  return screen.getCursorScreenPoint();
}
ipcMain.handle("bt:window-drag", (e, msg) => {
  const shell = shellFor(e);
  if (!shell || !msg) return;
  const win = shell.win;
  const point = pointerOf(msg);
  if (msg.phase === "start") {
    let bounds = Object.assign({}, win.getBounds(), shell.size);
    if (win.isMaximized()) {
      bounds = geometry.restoreUnderPointer(Object.assign({}, win.getNormalBounds(), shell.size), win.getBounds(), point);
      win.unmaximize();
      win.setBounds(bounds);
    }
    windowDrag = { shell, startBounds: bounds, startPoint: point, moved: false };
  } else if (msg.phase === "move" && windowDrag && windowDrag.shell === shell) {
    const next = geometry.dragBounds(windowDrag.startBounds, windowDrag.startPoint, point);
    if (next.x !== windowDrag.startBounds.x || next.y !== windowDrag.startBounds.y) windowDrag.moved = true;
    win.setBounds(next);
  } else if (msg.phase === "end" && windowDrag && windowDrag.shell === shell) {
    const moved = windowDrag.moved;
    windowDrag = null;
    if (!moved) return;
    const area = screen.getDisplayNearestPoint(point).workArea;
    const zone = geometry.snapZone(point, area);
    if (zone === "maximize") win.maximize();
    else if (zone) win.setBounds(geometry.snapBounds(zone, area));
  }
});

/* ── Tearing a tab off, and putting it back ─────────────────────────── */
// The page that holds the tab tells us when it has left its strip ("detach");
// a window opens under the pointer carrying the tab and follows it ("move")
// until it is let go ("end") -- over another window's strip it joins that
// window, anywhere else it stays where it is.
let tabDrag = null;
function windowsFrontFirst() {
  return [...shells.values()].reverse().sort((a, b) => (b.win.isFocused() ? 1 : 0) - (a.win.isFocused() ? 1 : 0))
    .map(s => ({ id: s.id, bounds: s.win.getBounds() }));
}
function describeForAdopt(spec) {
  const out = Object.assign({}, spec);
  if (out.kind === "web" && out.viewId != null && tabs.has(out.viewId)) {
    const t = tabs.get(out.viewId);
    const wc = t.view.webContents;
    out.url = wc.getURL() || out.url;
    out.title = wc.getTitle() || out.title;
    out.favicon = t.favicon || null;
  }
  return out;
}
ipcMain.handle("bt:tab-drag", (e, msg) => {
  const shell = shellFor(e);
  if (!shell || !msg) return null;
  const point = pointerOf(msg);
  if (msg.phase === "detach") {
    if (tabDrag) return null;
    const spec = describeForAdopt(msg.spec || {});
    const bounds = geometry.tearOffBounds(point, shell.size, workAreaOf({ x: point.x, y: point.y, width: 1, height: 1 }));
    const dragged = createShell({ bounds });
    if (spec.kind === "web" && spec.viewId != null) moveTab(spec.viewId, dragged);
    dragged.pendingAdopt.push(Object.assign({}, spec, { tornOff: true }));
    try { dragged.win.setOpacity(0.88); } catch (_) { }
    loadShellPage(dragged).catch(err => log("torn-off window page failed", err));
    tabDrag = { shell: dragged, spec, grab: { x: point.x - bounds.x, y: point.y - bounds.y }, hover: null };
    return dragged.id;
  }
  if (!tabDrag) return null;
  if (msg.phase === "move") {
    const d = tabDrag;
    d.shell.win.setBounds({
      x: Math.round(point.x - d.grab.x), y: Math.round(point.y - d.grab.y),
      width: d.shell.size.width, height: d.shell.size.height,
    });
    const over = geometry.stripUnder(point, windowsFrontFirst(), d.shell.id);
    if (over !== d.hover) {
      if (d.hover != null && shells.has(d.hover)) sendChrome(shells.get(d.hover), "bt:strip-hover", false);
      if (over != null) sendChrome(shells.get(over), "bt:strip-hover", true);
      d.hover = over;
    }
    return over;
  }
  if (msg.phase === "end") {
    const d = tabDrag;
    tabDrag = null;
    try { d.shell.win.setOpacity(1); } catch (_) { }
    if (d.hover != null && shells.has(d.hover)) sendChrome(shells.get(d.hover), "bt:strip-hover", false);
    const over = geometry.stripUnder(point, windowsFrontFirst(), d.shell.id);
    if (over == null || !shells.has(over)) {
      // Let go anywhere else: keep the window's title bar reachable on its display.
      const cur = Object.assign({}, d.shell.win.getBounds(), d.shell.size);
      d.shell.win.setBounds(geometry.keepReachable(cur, workAreaOf({ x: point.x, y: point.y, width: 1, height: 1 })));
      return null;
    }
    const target = shells.get(over);
    if (d.spec.kind === "web" && d.spec.viewId != null) moveTab(d.spec.viewId, target);
    sendChrome(target, "bt:adopt", describeForAdopt(d.spec));
    target.win.focus();
    d.shell.win.close();
    return over;
  }
  return null;
});

/* ── Boot ───────────────────────────────────────────────────────────── */
app.whenReady().then(async () => {
  startup.mark("app-ready"); wireDownloads();
  startBridge();
  wireUpdater();
  const first = createShell({ restore: loadSavedSession() });
  serverUp = await startup.whileStarting(first, () => serverUp, ensureServer);
  await loadShellPage(first);
  if (wantSecondWindow) { wantSecondWindow = false; openWindow(); }
});

app.on("before-quit", () => {
  // We only stop a server WE spawned; an attached one belongs to the user.
  if (spawnedServer && !spawnedServer.killed) { try { spawnedServer.kill(); } catch (_) { } }
});
app.on("window-all-closed", () => app.quit());
