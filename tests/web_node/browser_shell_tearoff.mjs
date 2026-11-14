// Runs browser_shell_tearoff.js in a vm context against a small fake title bar
// and reports what the module asked the desktop app to do for each gesture, so
// the Python test asserts behaviour. What a fake DOM delivers is evidence about
// the handler, not proof of real-pointer delivery; the app run covers that.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// --- a minimal DOM: nodes with a tag, classes and a parent --------------------
function node(tag, cls, parent) {
  const n = {
    tag, classes: new Set(cls ? cls.split(' ') : []), parent: parent || null, children: [],
    listeners: {}, rect: { left: 0, right: 0, top: 0, bottom: 40, width: 0, height: 40 },
    captured: null,
    classList: {
      add: c => n.classes.add(c), remove: c => n.classes.delete(c),
      toggle: (c, on) => { if (on) n.classes.add(c); else n.classes.delete(c); },
      contains: c => n.classes.has(c),
    },
    addEventListener(type, fn) { (n.listeners[type] = n.listeners[type] || []).push(fn); },
    contains(other) { for (let x = other; x; x = x.parent) if (x === n) return true; return false; },
    closest(sel) {
      const parts = sel.split(',').map(s => s.trim());
      for (let x = n; x; x = x.parent) {
        for (const p of parts) {
          if (p.startsWith('.') ? x.classes.has(p.slice(1)) : x.tag === p) return x;
        }
      }
      return null;
    },
    getBoundingClientRect() { return n.rect; },
    setPointerCapture(id) { n.captured = id; },
    releasePointerCapture() { n.captured = null; },
  };
  if (parent) parent.children.push(n);
  return n;
}
const sandbox = {
  window: {}, console, Math, Promise, setTimeout, clearTimeout,
  requestAnimationFrame: fn => setTimeout(fn, 0),
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], 'utf8'), sandbox, { filename: 'browser_shell_tearoff.js' });
const mod = sandbox.window.ThomasBrowserTearoff;
if (!mod) { process.stderr.write('window.ThomasBrowserTearoff missing\n'); process.exit(1); }

const sleep = () => new Promise(r => setTimeout(r, 5));
// Events bubble from the target up to the title bar, the way the browser's do.
function bubble(target, type, ev) {
  const e = Object.assign({ type, target, button: 0, pointerId: 1, screenX: 0, screenY: 0, clientX: 0, clientY: 0,
    stopped: false, prevented: false, stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; } }, ev);
  for (let x = target; x; x = x.parent) for (const fn of (x.listeners[type] || [])) fn(e);
  return e;
}

function build(options) {
  const doc = node('#document', '');
  sandbox.document = doc;
  const titlebar = node('div', 'bt-titlebar', doc);
  const strip = node('div', 'bt-tabstrip', titlebar);
  strip.rect = { left: 30, right: 800, top: 4, bottom: 40, width: 770, height: 36 };
  const cluster = node('span', 'bt-wincluster', titlebar);
  const closeBtn = node('button', 'bt-winbtn', cluster);
  const newBtn = node('button', 'bt-newtab', strip);
  const tabs = [];
  options.tabs.forEach((s, i) => {
    const el = node('button', 'bt-tab' + (s.pinned ? ' is-pinned' : ''), strip);
    el.rect = { left: 40 + i * 130, right: 160 + i * 130, width: 120, top: 8, bottom: 40, height: 32 };
    Object.defineProperty(el, 'nextElementSibling', { get() {
      const at = strip.children.indexOf(el); return strip.children[at + 1] || null; } });
    tabs.push(Object.assign({ id: i + 1, el }, s));
  });
  // the real strip keeps its tabs first and the + button last
  strip.children.splice(strip.children.indexOf(newBtn), 1);
  strip.children.push(newBtn);
  strip.insertBefore = (el, before) => {
    strip.children.splice(strip.children.indexOf(el), 1);
    strip.children.splice(strip.children.indexOf(before), 0, el);
  };
  strip.querySelectorAll = () => strip.children.filter(c => c.classes.has('bt-tab'));
  const calls = [];
  const desktop = options.plain ? null : {
    dragWindow: (...a) => { calls.push(['dragWindow', ...a]); return Promise.resolve(); },
    dragTab: (phase, spec, x, y) => { calls.push(['dragTab', phase, spec ? spec.kind : null, x, y]); return Promise.resolve(phase === 'detach' ? 7 : null); },
    windowControl: a => { calls.push(['windowControl', a]); },
    onAdopt: fn => { desktop.adopt = fn; },
    onStripHover: fn => { desktop.hover = fn; },
  };
  const order = [];
  mod.wire({
    desktop, titlebar, strip, newBtn,
    activate: id => calls.push(['activate', id]),
    getTabs: () => tabs.slice(),
    reorderTabs: els => { tabs.sort((a, b) => els.indexOf(a.el) - els.indexOf(b.el)); order.splice(0, order.length, ...tabs.map(t => t.id)); },
    specFor: tab => tab.spec || null,
    releaseTab: tab => { calls.push(['release', tab.id]); },
    adopt: spec => calls.push(['adopt', spec.kind, spec.title]),
  });
  return { titlebar, strip, cluster, closeBtn, newBtn, tabs, calls, desktop, order };
}

const report = {};
const trio = () => [{ pinned: true }, { spec: { kind: 'doc', title: 'B' } }, { spec: { kind: 'ws', title: 'C' } }];

// 1. Pressing empty bar space drags the window; a button or a tab does not.
{
  const t = build({ tabs: [{ pinned: true }] });
  bubble(t.strip, 'pointerdown', { screenX: 500, screenY: 20 });
  bubble(t.strip, 'pointermove', { screenX: 540, screenY: 50 });
  await sleep();
  bubble(t.strip, 'pointerup', { screenX: 540, screenY: 50 });
  report.window_drag = t.calls.filter(c => c[0] === 'dragWindow').map(c => c.slice(1).join(':'));
  report.window_captured = t.titlebar.captured === null;   // released again at the end
  const b = build({ tabs: [{ pinned: true }] });
  bubble(b.closeBtn, 'pointerdown', {});
  report.button_press_drags_window = b.calls.some(c => c[0] === 'dragWindow');
  const d = build({ tabs: [{ pinned: true }] });
  bubble(d.strip, 'dblclick', {});
  report.double_click = d.calls.filter(c => c[0] === 'windowControl').map(c => c[1]);
  const home = build({ tabs: [{ pinned: true }] });
  bubble(home.tabs[0].el, 'pointerdown', {});
  report.tab_press_drags_window = home.calls.some(c => c[0] === 'dragWindow');
}

// 2. A tab dragged along the strip reorders; the home tab keeps first place.
{
  const t = build({ tabs: trio() });
  bubble(t.tabs[1].el, 'pointerdown', { clientX: 200, clientY: 20 });
  bubble(t.strip, 'pointermove', { clientX: 400, clientY: 20 });
  bubble(t.strip, 'pointerup', { clientX: 400, clientY: 20 });
  report.order_after_drag_right = t.order.slice();
  report.reorder_activates = t.calls.filter(c => c[0] === 'activate').map(c => c[1]);
  const l = build({ tabs: trio() });
  bubble(l.tabs[2].el, 'pointerdown', { clientX: 330, clientY: 20 });
  bubble(l.strip, 'pointermove', { clientX: 5, clientY: 20 });
  bubble(l.strip, 'pointerup', { clientX: 5, clientY: 20 });
  report.order_after_drag_far_left = l.order.slice();
  report.reorder_never_tears = l.calls.some(c => c[0] === 'dragTab');
}

// 3. A click (almost no travel) is not a drag and its click is not swallowed.
{
  const t = build({ tabs: trio() });
  const b = t.tabs[1].el;
  bubble(b, 'pointerdown', { clientX: 200, clientY: 20 });
  bubble(t.strip, 'pointermove', { clientX: 202, clientY: 21 });
  bubble(t.strip, 'pointerup', { clientX: 202, clientY: 21 });
  const click = bubble(b, 'click', {});
  report.click_calls = t.calls.map(c => c.join(':'));
  report.click_released_capture = t.titlebar.captured === null;
}

// 4. Pulled off the strip: detach, follow, end; the tab is released here.
{
  const t = build({ tabs: [{ pinned: true }, { spec: { kind: 'web', title: 'W', viewId: 9 } }] });
  const w = t.tabs[1];
  bubble(w.el, 'pointerdown', { clientX: 200, clientY: 20, screenX: 200, screenY: 20 });
  bubble(t.strip, 'pointermove', { clientX: 205, clientY: 90, screenX: 205, screenY: 90 });
  await sleep(); await sleep();
  bubble(t.strip, 'pointermove', { clientX: 260, clientY: 300, screenX: 260, screenY: 300 });
  await sleep(); await sleep();
  bubble(t.strip, 'pointerup', { clientX: 300, clientY: 320, screenX: 300, screenY: 320 });
  report.tear_calls = t.calls.map(c => c.join(':'));
  report.tear_flags = { dragging_cleared: !w.el.classes.has('is-dragging'), capture_released: t.titlebar.captured === null };
}

// 5. A tab that cannot leave (no spec) stays on the strip however far it is pulled.
{
  const t = build({ tabs: [{ pinned: true }, { spec: null }] });
  bubble(t.tabs[1].el, 'pointerdown', { clientX: 200, clientY: 20 });
  bubble(t.strip, 'pointermove', { clientX: 205, clientY: 200, screenX: 205, screenY: 200 });
  await sleep();
  bubble(t.strip, 'pointerup', { clientX: 205, clientY: 200 });
  report.no_spec_calls = t.calls.map(c => c.join(':'));
}

// 6. In a plain browser reordering works and nothing tries to leave.
{
  const t = build({ plain: true, tabs: trio() });
  bubble(t.tabs[1].el, 'pointerdown', { clientX: 200, clientY: 20 });
  bubble(t.strip, 'pointermove', { clientX: 400, clientY: 300 });
  bubble(t.strip, 'pointerup', { clientX: 400, clientY: 300 });
  report.plain_order = t.order.slice();
}

// 7. Receiving: an adopted tab reaches the shell, and the hover marker toggles.
{
  const t = build({ tabs: [{ pinned: true }] });
  t.desktop.adopt({ kind: 'doc', title: 'Moved' });
  t.desktop.hover(true);
  report.adopted = t.calls.filter(c => c[0] === 'adopt').map(c => c.slice(1).join(':'));
  report.hover_on = t.strip.classes.has('is-drop-target');
  t.desktop.hover(false);
  report.hover_off = !t.strip.classes.has('is-drop-target');
}

// 8. The pure helpers.
report.slots = [mod.slotFor(10, [50, 150, 250]), mod.slotFor(100, [50, 150, 250]), mod.slotFor(999, [50, 150, 250])];
report.tear_out = [mod.shouldTearOut(20, 4, 40), mod.shouldTearOut(80, 4, 40), mod.shouldTearOut(-40, 4, 40)];

process.stdout.write(JSON.stringify(report));
