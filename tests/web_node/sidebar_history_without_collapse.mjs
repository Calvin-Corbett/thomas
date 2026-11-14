// Drive js/sidebar_history.js in a bare VM with the Build redesign's sidebar:
// no #tc-history-collapse control at all, and a view an older build saved
// with `collapsed: true`. The list must still decorate, sort and show -- a
// stale flag with no control left to undo it would hide every task for good.
import fs from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
if (!modulePath) throw new Error('usage: node sidebar_history_without_collapse.mjs <sidebar_history.js>');

function fakeEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(), hidden: false, style: {}, dataset: {}, children: [], parent: null,
    textContent: '', className: '', _listeners: {},
    classList: {
      set: new Set(),
      toggle(name, on) { if (on) this.set.add(name); else this.set.delete(name); },
      contains(name) { return this.set.has(name); },
    },
    setAttribute(name, value) { this[`attr:${name}`] = String(value); },
    removeAttribute(name) { delete this[`attr:${name}`]; },
    addEventListener(type, fn) { this._listeners[type] = fn; },
    appendChild(child) {
      if (child.parent) child.parent.children = child.parent.children.filter(node => node !== child);
      child.parent = this; this.children.push(child); return child;
    },
    // The list is put in order with insertBefore since rows stopped being re-appended one by one; a null
    // reference means "at the end", as it does in a browser.
    insertBefore(child, reference) {
      if (child.parent) child.parent.children = child.parent.children.filter(node => node !== child);
      child.parent = this;
      const at = reference ? this.children.indexOf(reference) : -1;
      if (at < 0) this.children.push(child); else this.children.splice(at, 0, child);
      return child;
    },
    get firstChild() { return this.children[0] || null; },
    get nextSibling() { const list = this.parent ? this.parent.children : []; return list[list.indexOf(this) + 1] || null; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const found = [];
      const attr = String(selector).match(/^\[data-([a-z-]+)\]$/);
      const walk = node => {
        for (const child of node.children) {
          if (attr) {
            const key = attr[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase());
            if (key in child.dataset) found.push(child);
          }
          walk(child);
        }
      };
      walk(this);
      return found;
    },
    getBoundingClientRect: () => ({ top: 0, bottom: 40, left: 0, width: 200, height: 40 }),
  };
  return el;
}

function row(id, title, time) {
  const el = fakeEl('button');
  el.dataset.historyId = id;
  el.dataset.historyTitle = title;
  el.dataset.historyTime = String(time);
  el.dataset.historyMode = 'code';
  return el;
}

const chats = fakeEl('div');
chats.style.flex = '1 1 auto';
chats.style.minHeight = '60px';
// The Build sidebar's head: a label and the sort chip, and nothing else.
const elements = { 'tc-chats': chats, 'tc-history-sort-label': fakeEl('span'), 'tc-history-filter': fakeEl('button') };
const touched = [];
const storage = new Map([['thomas_history_view_v1', JSON.stringify({ sort: 'recent', collapsed: true })]]);
const documentListeners = {};
const ctx = {
  console,
  Date,
  JSON,
  setTimeout: () => 0,
  clearTimeout: () => {},
  fetch: () => Promise.reject(new Error('no network in this harness')),
  localStorage: {
    getItem: key => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
  },
  window: { addEventListener() {}, innerWidth: 1440, innerHeight: 900 },
  document: {
    readyState: 'complete',
    body: fakeEl('body'),
    getElementById(id) { touched.push(id); return elements[id] || null; },
    createElement: tag => fakeEl(tag),
    addEventListener(type, fn) { documentListeners[type] = fn; },
  },
};
ctx.window.document = ctx.document;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(modulePath, 'utf8'), ctx);

const history = ctx.window.ThomasSidebarHistory;
if (!history || typeof history.decorate !== 'function') throw new Error('sidebar_history.js did not publish ThomasSidebarHistory.decorate');

const now = Date.now();
chats.appendChild(row('older', 'Playable Minesweeper', now - 86400000 * 3));
chats.appendChild(row('newer', 'Habit tracker with streaks', now - 1000));
history.decorate(chats);

const rows = chats.children.filter(node => node.dataset.historyId);
const askedForTheCollapse = touched.some(id => id.startsWith('tc-history-collapse'));

// A page cached from before the redesign still carries the old button. The
// stale flag must not reach the list through it either.
elements['tc-history-collapse'] = fakeEl('button');
history.decorate(chats);
const staleMarkupKeepsTheList = chats.hidden === false && chats.style.flex === '1 1 auto';
delete elements['tc-history-collapse'];

const checks = {
  staleMarkupKeepsTheList,
  listShown: chats.hidden === false,
  listKeepsItsFlex: chats.style.flex === '1 1 auto' && chats.style.minHeight === '60px',
  rowsShown: rows.length === 2 && rows.every(node => node.hidden === false),
  newestFirst: rows.map(node => node.dataset.historyId).join(',') === 'newer,older',
  sortLabelSynced: elements['tc-history-sort-label'].textContent === 'Recent',
  neverAskedForTheCollapse: !askedForTheCollapse,
  filterStillBound: typeof elements['tc-history-filter']._listeners.click === 'function',
};
for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`sidebar history check failed: ${name} ${JSON.stringify({ hidden: chats.hidden, style: chats.style, touched })}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
