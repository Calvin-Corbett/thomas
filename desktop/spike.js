/* Thomas desktop — Phase 1 spike gate runner.
 *
 * Runs the seven gates from the 2026-08-25 runtime decision and writes
 * machine-readable evidence to spike-results.json. Three modes:
 *   electron . --gates           gates 1,2,3,4,6 + plants the persistence cookie
 *   electron . --verify-persist  gate 5: fresh process proves the cookie survived
 *   electron . --bridge          gate 7: WS server up, Python drives a tab via CDP
 *
 * Security posture is the point, not a convenience: every WebContentsView is
 * created with contextIsolation:true, sandbox:true, nodeIntegration:false and
 * the persist:thomas partition. Nothing here weakens that.
 */
"use strict";

const { app, BaseWindow, WebContentsView, session } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");

const MODE = process.argv.includes("--verify-persist") ? "verify"
  : process.argv.includes("--bridge") ? "bridge" : "gates";
const BOOT_LOG = path.join(__dirname, "boot.log");
function bootMark(step) {
  try { fs.appendFileSync(BOOT_LOG, new Date().toISOString() + " " + step + "\n"); } catch (_) { }
}
bootMark("module-start mode=" + MODE + " pid=" + process.pid);
const RESULTS_PATH = path.join(__dirname, "spike-results.json");
const BRIDGE_INFO_PATH = path.join(__dirname, "bridge.json");
const PARTITION = "persist:thomas";
const COOKIE_STAMP = "spike-" + new Date().toISOString().replace(/[:.]/g, "-");

// Gate 5: our own profile directory, not a system browser's.
app.setPath("userData", path.join(__dirname, "..", "runtime", "browser_profile"));

// Gate 1: single-instance.
bootMark("before-lock");
const gotLock = app.requestSingleInstanceLock();
bootMark("after-lock got=" + gotLock);
if (!gotLock) { bootMark("second-instance exit"); app.exit(1); }

const results = fs.existsSync(RESULTS_PATH)
  ? JSON.parse(fs.readFileSync(RESULTS_PATH, "utf8")) : {};
function record(gate, data) {
  results[gate] = Object.assign({ at: new Date().toISOString() }, data);
  fs.writeFileSync(RESULTS_PATH, JSON.stringify(results, null, 2));
}
function fail(gate, err) {
  record(gate, { pass: false, error: String(err && err.stack || err) });
}

const WEB_PREFS = { contextIsolation: true, sandbox: true, nodeIntegration: false, partition: PARTITION };

function makeTab(win) {
  const view = new WebContentsView({ webPreferences: Object.assign({}, WEB_PREFS) });
  view.setBounds({ x: 0, y: 0, width: 1200, height: 780 });
  win.contentView.addChildView(view);
  return view;
}
function showTab(win, view, all) {
  all.forEach(v => { if (v !== view) win.contentView.removeChildView(v); });
  win.contentView.addChildView(view);
  view.setBounds({ x: 0, y: 0, width: 1200, height: 780 });
}
function loadAndWait(view, url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const wc = view.webContents;
    const timer = setTimeout(() => { cleanup(); reject(new Error("load timeout: " + url)); }, timeoutMs || 30000);
    function onDone() { cleanup(); setTimeout(resolve, 1200); }   // settle for late paints
    function onFail(_e, code, desc, failedUrl, isMainFrame) {
      if (!isMainFrame) return;                                   // subresource noise is not a verdict
      cleanup(); reject(new Error("did-fail-load " + code + " " + desc + " " + failedUrl));
    }
    function cleanup() {
      clearTimeout(timer);
      wc.removeListener("did-finish-load", onDone);
      wc.removeListener("did-fail-load", onFail);
    }
    wc.on("did-finish-load", onDone);
    wc.on("did-fail-load", onFail);
    wc.loadURL(url);
  });
}

/* Minimal CDP helper over webContents.debugger — the one agent↔page channel. */
function cdp(view) {
  const dbg = view.webContents.debugger;
  if (!dbg.isAttached()) dbg.attach("1.3");
  return {
    send: (method, params) => dbg.sendCommand(method, params || {}),
    detach: () => { try { dbg.detach(); } catch (_) { } },
  };
}
async function cdpEval(view, expression) {
  const c = cdp(view);
  const out = await c.send("Runtime.evaluate", { expression, returnByValue: true });
  if (out.exceptionDetails) throw new Error("eval failed: " + JSON.stringify(out.exceptionDetails.exception));
  return out.result.value;
}
async function cdpClick(view, selector) {
  const c = cdp(view);
  const doc = await c.send("DOM.getDocument", { depth: 1 });
  const node = await c.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector });
  if (!node.nodeId) throw new Error("selector not found: " + selector);
  const box = await c.send("DOM.getBoxModel", { nodeId: node.nodeId });
  const q = box.model.content;                                    // [x1,y1, x2,y2, x3,y3, x4,y4]
  const x = (q[0] + q[4]) / 2, y = (q[1] + q[5]) / 2;
  // Press events route through the focus pipeline; an unfocused/background
  // window silently drops them (mousemove goes through, mousedown doesn't).
  // Focus emulation is the headless-grade fix Puppeteer relies on.
  await c.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  view.webContents.focus();
  await new Promise(r => setTimeout(r, 120));
  await c.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", buttons: 0 });
  await c.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await c.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
  return { x, y };
}

async function runGates(win) {
  record("versions", {
    electron: process.versions.electron,
    chromium: process.versions.chrome,
    node: process.versions.node,
    platform: process.platform + "-" + process.arch,
  });
  record("gate1_single_instance", { pass: gotLock === true });

  const tabA = makeTab(win);
  const tabB = makeTab(win);
  const all = [tabA, tabB];

  // Gate 2: strict prefs, straight from the live webContents.
  const lastPrefs = tabA.webContents.getLastWebPreferences
    ? tabA.webContents.getLastWebPreferences() : WEB_PREFS;
  record("gate2_security_defaults", {
    pass: lastPrefs.contextIsolation === true && lastPrefs.sandbox === true && lastPrefs.nodeIntegration === false,
    contextIsolation: lastPrefs.contextIsolation,
    sandbox: lastPrefs.sandbox,
    nodeIntegration: lastPrefs.nodeIntegration,
    partition: WEB_PREFS.partition,
  });

  // Gate 3: two WebContentsViews, separate renderer processes, live state
  // that survives switching.
  try {
    showTab(win, tabA, all);
    await loadAndWait(tabA, "https://example.com");
    showTab(win, tabB, all);
    await loadAndWait(tabB, "https://example.org");
    const pidA = tabA.webContents.getOSProcessId();
    const pidB = tabB.webContents.getOSProcessId();
    showTab(win, tabA, all);
    await cdpEval(tabA, "window.__thomasSpike = 'marker-" + COOKIE_STAMP + "'; document.title = 'THOMAS-SPIKE-A'; 'set'");
    showTab(win, tabB, all);                                      // A detached from the window…
    await new Promise(r => setTimeout(r, 800));
    showTab(win, tabA, all);                                      // …and back
    const marker = await cdpEval(tabA, "window.__thomasSpike");
    record("gate3_webcontentsviews", {
      pass: pidA > 0 && pidB > 0 && pidA !== pidB && marker === "marker-" + COOKIE_STAMP,
      rendererPidA: pidA, rendererPidB: pidB,
      distinctRendererProcesses: pidA !== pidB,
      liveStateAfterSwitch: marker,
      api: "WebContentsView (BrowserView not used)",
    });
  } catch (e) { fail("gate3_webcontentsviews", e); }

  // Gate 4: Wells Fargo, top-level, full render.
  try {
    showTab(win, tabB, all);
    await loadAndWait(tabB, "https://www.wellsfargo.com", 45000);
    await new Promise(r => setTimeout(r, 3000));
    const title = tabB.webContents.getTitle();
    const bodyChars = await cdpEval(tabB, "document.body ? document.body.innerText.length : 0");
    // The render verdict comes from the DOM; the screenshot is corroborating
    // evidence and may need a retry while the compositor settles.
    let shot = null, shotErr = null;
    for (let attempt = 0; attempt < 3 && !shot; attempt++) {
      try {
        await new Promise(r => setTimeout(r, 1500));
        const img = await tabB.webContents.capturePage();
        if (!img.isEmpty()) {
          shot = path.join(__dirname, "wellsfargo.png");
          fs.writeFileSync(shot, img.toPNG());
        }
      } catch (e) { shotErr = String(e); }
    }
    record("gate4_wellsfargo", {
      pass: bodyChars > 500,
      url: tabB.webContents.getURL(),
      title,
      bodyTextChars: bodyChars,
      screenshot: shot,
      screenshotError: shot ? null : shotErr,
      note: "top-level WebContentsView load; X-Frame-Options does not apply to top-level navigations",
    });
  } catch (e) { fail("gate4_wellsfargo", e); }

  // Gate 5 part A: plant a page-set persistent cookie (the same mechanism a
  // login session cookie uses), then report where the profile lives on disk.
  try {
    showTab(win, tabA, all);
    await loadAndWait(tabA, "https://example.com");
    await cdpEval(tabA, "document.cookie = 'thomas_spike=" + COOKIE_STAMP + "; max-age=604800; path=/'; document.cookie");
    await session.fromPartition(PARTITION).cookies.flushStore();
    const found = await session.fromPartition(PARTITION).cookies.get({ name: "thomas_spike" });
    record("gate5a_cookie_planted", {
      pass: found.length === 1 && found[0].value === COOKIE_STAMP,
      cookie: found[0] || null,
      userData: app.getPath("userData"),
      partitionDir: path.join(app.getPath("userData"), "Partitions", "thomas"),
    });
  } catch (e) { fail("gate5a_cookie_planted", e); }

  // Gate 6: CDP — read the live DOM, click a real element, observe the effect.
  try {
    showTab(win, tabA, all);
    await loadAndWait(tabA, "https://example.com");
    const domRead = await cdpEval(tabA,
      "JSON.stringify({ title: document.title, h1: document.querySelector('h1').textContent, links: [...document.querySelectorAll('a')].map(a => a.href), htmlChars: document.documentElement.outerHTML.length })");
    const preUrl = tabA.webContents.getURL();
    // Diagnostic listeners: what does the renderer actually receive?
    await cdpEval(tabA, "window.__ev = []; ['mousemove','mousedown','mouseup','click'].forEach(t => document.addEventListener(t, e => window.__ev.push(t + '@' + e.clientX + ',' + e.clientY + ' on ' + e.target.tagName), true)); 'armed'");
    const navDone = new Promise(resolve => tabA.webContents.once("did-navigate", (_e, url) => resolve(url)));
    const point = await cdpClick(tabA, "a");
    await new Promise(r => setTimeout(r, 1500));
    const seen = await cdpEval(tabA, "JSON.stringify({ events: window.__ev, atPoint: (document.elementFromPoint(" + point.x + "," + point.y + ") || {}).tagName || null })").catch(() => "\"gone (navigated?)\"");
    const postUrl = await Promise.race([navDone, new Promise(r => setTimeout(() => r("NO-NAVIGATION"), 15000))]);
    record("gate6_cdp_read_and_click", {
      pass: postUrl !== "NO-NAVIGATION" && postUrl !== preUrl,
      domRead: JSON.parse(domRead),
      clickedAt: point,
      rendererSaw: typeof seen === "string" ? JSON.parse(seen) : seen,
      preUrl, postUrl,
      channel: "webContents.debugger (CDP 1.3): DOM.getDocument, DOM.querySelector, DOM.getBoxModel, Runtime.evaluate, Input.dispatchMouseEvent",
    });
  } catch (e) { fail("gate6_cdp_read_and_click", e); }
}

async function runVerifyPersist(win) {
  // Fresh process, same partition: is the cookie still there, on OUR disk?
  try {
    const found = await session.fromPartition(PARTITION).cookies.get({ name: "thomas_spike" });
    const planted = results.gate5a_cookie_planted && results.gate5a_cookie_planted.cookie;
    const partitionDir = path.join(app.getPath("userData"), "Partitions", "thomas");
    const onDisk = fs.readdirSync(partitionDir, { recursive: true })
      .filter(f => String(f).includes("Cookies")).map(String);
    // And prove the cookie actually rides a real request from a tab.
    const tab = makeTab(win);
    await loadAndWait(tab, "https://example.com");
    const docCookie = await cdpEval(tab, "document.cookie");
    record("gate5b_persistence_after_relaunch", {
      pass: found.length === 1 && !!planted && found[0].value === planted.value && docCookie.includes("thomas_spike="),
      cookieAfterRelaunch: found[0] || null,
      documentCookieInPage: docCookie,
      profileUserData: app.getPath("userData"),
      cookieFilesOnDisk: onDisk,
      note: "page-set persistent cookie (the mechanism login sessions use); a human-credential login was not performed by the agent",
    });
  } catch (e) { fail("gate5b_persistence_after_relaunch", e); }
}

async function runBridge(win) {
  // Gate 7: Python (Thomas's brain) drives a tab end-to-end through the main
  // process. Transport: JSON-RPC-ish over a loopback WebSocket with a token.
  const { WebSocketServer } = require("ws");
  const token = crypto.randomBytes(16).toString("hex");
  const tab = makeTab(win);
  showTab(win, tab, [tab]);

  const wss = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await new Promise(r => wss.once("listening", r));
  const port = wss.address().port;
  fs.writeFileSync(BRIDGE_INFO_PATH, JSON.stringify({ port, token }));
  record("gate7_bridge_listening", { pass: true, transport: "ws://127.0.0.1:" + port, tokenRequired: true });

  const commands = {
    navigate: async p => { await loadAndWait(tab, p.url, 45000); return { url: tab.webContents.getURL() }; },
    read_dom: async () => JSON.parse(await cdpEval(tab,
      "JSON.stringify({ url: location.href, title: document.title, h1: (document.querySelector('h1')||{}).textContent || null, htmlChars: document.documentElement.outerHTML.length })")),
    click: async p => {
      const navDone = new Promise(resolve => tab.webContents.once("did-navigate", (_e, url) => resolve(url)));
      const point = await cdpClick(tab, p.selector);
      const nav = await Promise.race([navDone, new Promise(r => setTimeout(() => r(null), 12000))]);
      return { clickedAt: point, navigatedTo: nav, url: tab.webContents.getURL() };
    },
    url: async () => ({ url: tab.webContents.getURL() }),
    quit: async () => { setTimeout(() => app.quit(), 300); return { bye: true }; },
  };

  wss.on("connection", (sock, req) => {
    const u = new URL(req.url, "ws://x");
    if (u.searchParams.get("token") !== token) { sock.close(4001, "bad token"); return; }
    sock.on("message", async raw => {
      let msg;
      try { msg = JSON.parse(raw); } catch (_) { return; }
      try {
        const fn = commands[msg.cmd];
        if (!fn) throw new Error("unknown cmd " + msg.cmd);
        const result = await fn(msg.params || {});
        sock.send(JSON.stringify({ id: msg.id, ok: true, result }));
        record("gate7_last_command", { pass: true, cmd: msg.cmd, result });
      } catch (e) {
        sock.send(JSON.stringify({ id: msg.id, ok: false, error: String(e && e.message || e) }));
        record("gate7_last_command", { pass: false, cmd: msg.cmd, error: String(e) });
      }
    });
  });
}

app.whenReady().then(async () => {
  bootMark("ready");
  const win = new BaseWindow({ width: 1200, height: 820, title: "Thomas Browser Spike" });
  bootMark("window-created");
  try {
    if (MODE === "gates") await runGates(win);
    else if (MODE === "verify") await runVerifyPersist(win);
    else await runBridge(win);
  } catch (e) { fail("fatal_" + MODE, e); }
  if (MODE !== "bridge") { setTimeout(() => app.quit(), 500); }
});
// Hard stop so a hung site can never wedge the spike.
setTimeout(() => { try { fail("timeout_" + MODE, "hard 240s cap hit"); } finally { app.exit(2); } }, 240000);
app.on("window-all-closed", () => app.quit());
