// Runs ui_edit_layout.js in a vm context against a small fake DOM and reports
// what a layout record with "text" did to an element, and what removing the
// record restored — so the Python test asserts behaviour, not source strings.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [, , layoutPath] = process.argv;

class Node_ {
  constructor(nodeType, nodeValue) { this.nodeType = nodeType; this.nodeValue = nodeValue; }
}
function fakeStyle() {
  const props = new Map();
  return {
    translate: '', width: '', height: '', zIndex: '', position: '',
    getPropertyValue: (n) => (props.get(n) || {}).value || '',
    getPropertyPriority: (n) => (props.get(n) || {}).priority || '',
    setProperty: (n, v, p) => { props.set(n, { value: v, priority: p || '' }); },
    removeProperty: (n) => { props.delete(n); },
  };
}
class Element {
  constructor(uiId, children) {
    this.dataset = uiId ? { uiId } : {};
    this.style = fakeStyle();
    this.childNodes = children;
    this.classList = { add() {}, remove() {}, contains: () => false };
  }
  appendChild(child) { this.childNodes.push(child); return child; }
  removeChild(child) { this.childNodes = this.childNodes.filter((c) => c !== child); return child; }
  getBoundingClientRect() { return { width: 100, height: 30 }; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  matches() { return false; }
  text() { return this.childNodes.filter((c) => c.nodeType === 3).map((c) => c.nodeValue).join(''); }
}
const text = (s) => new Node_(3, s);
const icon = () => new Element('', []);

const doc = {
  readyState: 'loading', addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
  documentElement: new Element('', []), body: null,
  createTextNode: (s) => text(s),
};
const win = { addEventListener() {}, dispatchEvent() {}, innerWidth: 1400, innerHeight: 900 };
const sandbox = {
  window: win, document: doc, Element, CustomEvent: class {}, MutationObserver: class { observe() {} },
  requestAnimationFrame: () => 1, getComputedStyle: () => ({ position: 'static' }),
  localStorage: { getItem: () => null, setItem() {} }, location: { pathname: '/chat' }, console,
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(layoutPath, 'utf8'), sandbox, { filename: 'ui_edit_layout.js' });
const L = win.ThomasUiLayout;

// A button like Build's "New build": an icon element, then the words, with the
// whitespace runs a formatted template leaves around them.
const button = new Element('build.newchat', [text('\n  '), icon(), text('\n  New build\n')]);
L.applyNode(button, { 'build.newchat': { x: 0, y: 0, text: 'Start a build' } });
const changed = button.text();
L.applyNode(button, {});
const restored = button.text();
const restoredCount = button.childNodes.length;

// An element that shows nothing yet still gets words.
const bare = new Element('chat.badge', [icon()]);
L.applyNode(bare, { 'chat.badge': { x: 0, y: 0, text: 'New' } });
const bareChanged = bare.text();
L.applyNode(bare, {});
const bareRestored = bare.text();
const bareCount = bare.childNodes.length;

process.stdout.write(JSON.stringify({ changed, restored, restoredCount, bareChanged, bareRestored, bareCount }));
