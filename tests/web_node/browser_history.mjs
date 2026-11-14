import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const errors = [];
const context = { window: {}, console: { error: (...args) => errors.push(args) } };
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
const tabs = [], pages = [], active = [];
const pending = [];
const scope = {
  window: context.window, tabs, activeId: '',
  desktop: { getHistory: () => new Promise((resolve, reject) => pending.push({ resolve, reject })) },
  bodyRow: { appendChild: page => pages.push(page) },
  h: () => {
    let content = '';
    return { get innerHTML() { return content; }, set innerHTML(value) { content = value; },
      get textContent() { return content; }, set textContent(value) { content = value; }, querySelectorAll: () => [] };
  },
  esc: value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]),
  makeTab: spec => { const tab = {id:tabs.length+1,...spec}; tabs.push(tab); return tab; },
  activate: id => active.push(id), setStatus: (tab, status) => { tab.status = status; },
  SVG: {}, icons() {}, wsByMode: {}, bookmarks: [], byId() {}, setTitle() {}, toast() {},
  viewTabs: new Map(), reportBounds() {}, openWorkspaceTab() {}, omni: {}, websearch: {}, keys: {},
};
// Execute the actual shell's context wiring in its own lexical scope. The web
// module above has no global tabs variable, just as in the loaded product.
const shell = fs.readFileSync(process.argv[3], 'utf8');
const caller = shell.match(/const web = window\.ThomasBrowserWeb\.wire\(\{[\s\S]*?\n  \}\);/);
assert.ok(caller, 'The live shell must wire the web module');
const api = vm.runInNewContext(caller[0] + '\nweb;', scope);
const tick = () => new Promise(resolve => setImmediate(resolve));
api.openHistoryTab();
assert.match(pages[0].textContent, /Loading history/);
assert.equal(tabs[0].status, 'working');
pending[0].resolve([{title:'A visited page',url:'https://example.com'}]);
await tick();
assert.equal(tabs.length,1);
assert.equal(pages.length,1);
assert.match(pages[0].innerHTML,/A visited page/);
assert.equal(tabs[0].status, 'done');
api.openHistoryTab();
pending[1].resolve([{title:'A refreshed page',url:'https://example.com/new'}]);
await tick();
assert.equal(tabs.length,1,'Reopening History must reuse its live tab');
assert.equal(pending.length,2,'Reopening History refreshes its records');
assert.deepEqual(active,[1,1]);
assert.match(pages[0].innerHTML,/A refreshed page/);

api.openHistoryTab();
pending[2].reject(new Error('history store unavailable'));
await tick();
assert.equal(tabs[0].status, 'error');
assert.match(pages[0].textContent, /could not be loaded/);
assert.equal(errors.length, 1);
api.openHistoryTab();
pending[3].resolve([]);
await tick();
assert.equal(tabs[0].status, 'done');
assert.match(pages[0].innerHTML, /Pages you visit will appear here/);
assert.doesNotMatch(pages[0].innerHTML, /runtime\/|history\.jsonl/);

api.openHistoryTab();
api.openHistoryTab();
pending[5].resolve([{ title: 'Newest <script> page', url: 'https://example.com/latest' }]);
await tick();
const newest = pages[0].innerHTML;
assert.match(newest, /Newest &lt;script&gt; page/);
pending[4].reject(new Error('stale request failed'));
await tick();
assert.equal(pages[0].innerHTML, newest, 'Older refresh cannot replace newer results');
assert.equal(errors.length, 1, 'Obsolete request failure cannot change the current page');
api.openHistoryTab();
tabs.pop();
pending[6].resolve([{ title: 'Late closed-tab result', url: 'https://example.com/old' }]);
await tick();
assert.match(pages[0].textContent, /Loading history/, 'Closing the tab retires its pending refresh');
console.log('History creation, loading, failure, retry, tab reuse, and stale-result ownership passed');
