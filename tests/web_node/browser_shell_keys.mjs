// Runs browser_shell_keys.js in a vm context with a fake window and reports
// what each key event maps to, so the Python test asserts behaviour.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const listeners = [];
const sandbox = {
  window: { addEventListener(type, fn) { listeners.push([type, fn]); } },
  navigator: { platform: 'Win32' },
  console,
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], 'utf8'), sandbox, { filename: 'browser_shell_keys.js' });
const mod = sandbox.window.ThomasBrowserKeys;
if (!mod) { process.stderr.write('window.ThomasBrowserKeys missing\n'); process.exit(1); }

const calls = [];
const keys = mod.wire({
  newTab: () => { calls.push('new-tab'); return true; },
  closeActiveTab: () => { calls.push('close-tab'); return true; },
  cycleTab: d => { calls.push('cycle:' + d); return true; },
  selectTabIndex: n => { calls.push('select:' + n); return true; },
  focusOmnibox: () => true,
  reloadActive: () => true,
  goBack: () => { calls.push('back'); return false; },
  goForward: () => true,
});
if (typeof keys.attachTo !== 'function' || typeof keys.bindings !== 'function') {
  process.stderr.write('attachTo or bindings missing\n'); process.exit(1);
}
function ev(o) {
  return Object.assign({ key: '', code: '', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false,
    prevented: false, getModifierState() { return false; },
    preventDefault() { this.prevented = true; }, stopPropagation() {} }, o);
}
const act = o => keys.actionFor(ev(o));
const altGraph = ev({ key: '3', code: 'Digit3', altKey: true });
altGraph.getModifierState = k => k === 'AltGraph';
const report = {
  ctrl_2: act({ key: '2', code: 'Digit2', ctrlKey: true }),
  ctrl_9: act({ key: '9', code: 'Digit9', ctrlKey: true }),
  alt_3: act({ key: '3', code: 'Digit3', altKey: true }),
  alt_3_altgraph: keys.actionFor(altGraph),
  ctrl_shift_bracket_right: act({ key: '}', code: 'BracketRight', ctrlKey: true, shiftKey: true }),
  ctrl_shift_bracket_left: act({ key: '{', code: 'BracketLeft', ctrlKey: true, shiftKey: true }),
  ctrl_shift_e: act({ key: 'E', code: 'KeyE', ctrlKey: true, shiftKey: true }),
  alt_pagedown: act({ key: 'PageDown', altKey: true }),
  alt_pageup: act({ key: 'PageUp', altKey: true }),
  ctrl_tab: act({ key: 'Tab', ctrlKey: true }),
  plain_3: act({ key: '3', code: 'Digit3' }),
  ctrl_shift_3: act({ key: '#', code: 'Digit3', ctrlKey: true, shiftKey: true }),
  ctrl_t: act({ key: 't', code: 'KeyT', ctrlKey: true }),
};
const keydown = listeners.find(l => l[0] === 'keydown');
const altLeft = ev({ key: 'ArrowLeft', altKey: true });
keydown[1](altLeft);
report.alt_left_prevented = altLeft.prevented;
const ctrl2 = ev({ key: '2', code: 'Digit2', ctrlKey: true });
keydown[1](ctrl2);
report.ctrl_2_prevented = ctrl2.prevented;
const fakeWin = { got: [], addEventListener(type, fn) { this.got.push([type, fn]); } };
keys.attachTo(fakeWin);
report.attached_keydown = fakeWin.got.some(l => l[0] === 'keydown' && typeof l[1] === 'function');
report.bindings = keys.bindings().map(b => [b.keys, b.everywhere]);
report.calls = calls;
process.stdout.write(JSON.stringify(report));
