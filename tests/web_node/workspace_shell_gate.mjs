// Runs workspace_shell.js in a vm context with a stub document and reports the
// browser-chrome gate's decisions, so the Python test asserts behaviour.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const style = { length: 0, setProperty() {}, removeProperty() {} };
const doc = {
  readyState: 'loading',
  addEventListener() {},
  querySelectorAll: () => [],
  querySelector: () => null,
  getElementById: () => null,
  documentElement: { dataset: {}, style, classList: { add() {} } },
  body: null,
};
const win = { addEventListener() {}, matchMedia: () => ({ matches: false }) };
win.parent = win;
const sandbox = {
  window: win, document: doc, localStorage: { getItem: () => null, setItem() {} },
  location: { search: '', pathname: '/', origin: 'http://x', href: 'http://x/' },
  CustomEvent: class {}, URLSearchParams, Promise, setTimeout, queueMicrotask, console,
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], 'utf8'), sandbox, { filename: 'workspace_shell.js' });
const shell = sandbox.window.ThomasWorkspaceShell;
if (!shell || typeof shell.browserChromeDecision !== 'function') {
  process.stderr.write('ThomasWorkspaceShell.browserChromeDecision missing\n'); process.exit(1);
}
const base = { search: '', stored: '', desktop: false, embedded: false, attached: false, shell: true };
const ask = o => shell.browserChromeDecision(Object.assign({}, base, o));
const report = {
  default_on: ask({}),
  query_off: ask({ search: '?browser=0' }),
  stored_off: ask({ stored: 'off' }),
  query_on_beats_stored_off: ask({ search: '?browser=1', stored: 'off' }),
  desktop: ask({ desktop: true }),
  embedded: ask({ embedded: true }),
  attached: ask({ attached: true }),
  no_shell: ask({ shell: false }),
  other_query: ask({ search: '?theme=light' }),
};
process.stdout.write(JSON.stringify(report));
