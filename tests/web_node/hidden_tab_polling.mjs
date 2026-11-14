/* Drives the real doc_activity.js + todo_panel.js on a virtual clock and reports
 * how many times each phase actually hit the network.
 *
 * The tab shell gives every Chat/Build/Work tab its own chat.html document and
 * hides the inactive ones by putting `bt-doc-hidden` on <html>. The panels used
 * to guard on `document.hidden`, which is only true when the whole browser tab
 * is backgrounded, so hidden Thomas tabs kept polling at 1.5s forever.
 *
 * Phases reported:
 *   visible  - polls on the normal cadence (unchanged behaviour)
 *   hidden   - no network at all while the document is paused
 *   resumed  - polls immediately when shown again, not after the idle gap
 *
 * tests/test_hidden_tabs_stop_polling.py asserts on this JSON.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , docActivityPath, todoPanelPath] = process.argv;

// ---- virtual clock -------------------------------------------------------
let now = 0;
let seq = 0;
const timers = new Map();

function setTimeoutStub(fn, ms) {
  const id = ++seq;
  timers.set(id, { at: now + Math.max(0, Number(ms) || 0), fn });
  return id;
}
function clearTimeoutStub(id) {
  timers.delete(id);
}

async function advance(ms) {
  const until = now + ms;
  // Settle anything already in flight first: the panel schedules its next tick
  // from a promise callback, so the timer does not exist until microtasks run.
  for (let i = 0; i < 20; i++) await Promise.resolve();
  // Fire everything due, in time order, letting promises settle between each.
  for (;;) {
    let nextId = null;
    let nextAt = Infinity;
    for (const [id, t] of timers) {
      if (t.at < nextAt) { nextAt = t.at; nextId = id; }
    }
    if (nextId === null || nextAt > until) break;
    now = nextAt;
    const t = timers.get(nextId);
    timers.delete(nextId);
    try { t.fn(); } catch (err) { /* a panel error must not stop the clock */ }
    for (let i = 0; i < 20; i++) await Promise.resolve();
  }
  now = until;
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

// ---- stub DOM ------------------------------------------------------------
let fetches = [];
const observers = [];

const classes = new Set();
const classList = {
  add: (c) => { classes.add(c); fireObservers(); },
  remove: (c) => { classes.delete(c); fireObservers(); },
  contains: (c) => classes.has(c),
  toggle: (c, on) => { if (on) classList.add(c); else classList.remove(c); },
};

function fireObservers() {
  for (const cb of observers) {
    try { cb(); } catch (err) { /* ignore */ }
  }
}

function element() {
  return {
    id: "", hidden: false, innerHTML: "", textContent: "",
    style: {}, dataset: {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    appendChild: (c) => c, insertBefore: (c) => c, closest: () => null,
    parentElement: null, children: [],
  };
}

const documentStub = {
  hidden: false,
  readyState: "complete",
  documentElement: { classList },
  head: element(),
  body: element(),
  addEventListener() {},
  removeEventListener() {},
  // No composer in this harness: host() returns null and paint() is a no-op.
  // poll() still runs, which is exactly what we are counting.
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => element(),
};

const windowStub = {
  document: documentStub,
  setTimeout: setTimeoutStub,
  clearTimeout: clearTimeoutStub,
  ThomasChatSession: { current: () => "session-under-test" },
  fetch: (url) => {
    fetches.push(String(url).split("?")[0]);
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ todos: [] }) });
  },
  addEventListener() {},
};

class MutationObserverStub {
  constructor(cb) { this.cb = cb; }
  observe() { observers.push(this.cb); }
  disconnect() {}
}

const sandbox = {
  window: windowStub,
  document: documentStub,
  console,
  setTimeout: setTimeoutStub,
  clearTimeout: clearTimeoutStub,
  fetch: windowStub.fetch,
  MutationObserver: MutationObserverStub,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

vm.runInContext(readFileSync(docActivityPath, "utf-8"), sandbox, { filename: "doc_activity.js" });
vm.runInContext(readFileSync(todoPanelPath, "utf-8"), sandbox, { filename: "todo_panel.js" });

const report = { doc_activity_loaded: typeof sandbox.window.ThomasDocActivity === "object" };

// --- phase 1: visible. The tab the user is looking at must be unaffected. ---
fetches = [];
await advance(10_000);
report.visible_fetches_in_10s = fetches.length;

// --- phase 2: the shell hides this tab. ---
classList.add("bt-doc-hidden");
report.paused_after_class = sandbox.window.ThomasDocActivity.isPaused();
fetches = [];
await advance(60_000);
report.hidden_fetches_in_60s = fetches.length;

// --- phase 3: shown again. Must refresh at once, not after the idle gap. ---
fetches = [];
classList.remove("bt-doc-hidden");
await advance(100);
report.fetches_within_100ms_of_resume = fetches.length;

// --- phase 4: back to normal cadence. ---
fetches = [];
await advance(10_000);
report.resumed_fetches_in_10s = fetches.length;

console.log(JSON.stringify(report, null, 1));
