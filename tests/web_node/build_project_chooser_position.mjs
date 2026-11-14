// Exercise the shipped chooser's positioning with measured rail/trigger boxes.
// The state variants mimic Build's normal, activity, viewer and narrow layouts
// -- the drawer and viewer ones arrive through the rail's ResizeObserver, which
// is how they reach an already-open chooser in the app. Every variant also
// asserts the trigger is NOT the column centre, so none of this can pass with
// the fix taken back out. Driven by tests/test_build_project_chooser_position.py.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(process.argv[2], 'utf8');
const boxes = { rail: { left: 0, width: 0 }, wrap: { left: 0 } };
const menu = { style: {} };
const rail = { getBoundingClientRect: () => boxes.rail };
const wrap = { getBoundingClientRect: () => boxes.wrap };
const elements = {
  'tc-code-library-menu': menu,
  'tc-code-project-wrap': wrap,
  'tc-composer-rail': rail,
};
const listeners = {};
let railResize;
globalThis.ResizeObserver = class {
  constructor(callback) { railResize = callback; }
  observe(target) { assert.equal(target, rail); }
};
globalThis.window = {
  innerWidth: 1280,
  addEventListener(name, callback) { listeners[name] = callback; },
};
globalThis.document = { getElementById: id => elements[id] || null };
vm.runInThisContext(source, { filename: process.argv[2] });
const state = {};
const panels = window.ThomasChatComposerPanels.create({ state });
state.libraryMenuOpen = true;

function check(label, viewport, railLeft, railWidth, triggerLeft, expectedLeft, expectedWidth, notify = listeners.resize) {
  window.innerWidth = viewport;
  boxes.rail = { left: railLeft, width: railWidth };
  boxes.wrap = { left: triggerLeft };
  notify();
  const left = triggerLeft + parseFloat(menu.style.left);
  const width = parseFloat(menu.style.width);
  assert.equal(menu.style.boxSizing, 'border-box', `${label}: measured width includes borders`);
  assert.equal(left, expectedLeft, `${label}: chooser left`);
  assert.equal(width, expectedWidth, `${label}: chooser width`);
  assert.ok(left >= 16 && left + width <= viewport - 16, `${label}: chooser stays visible`);
  assert.equal(left + width / 2, railLeft + railWidth / 2, `${label}: chooser shares the rail centre`);
  // The markup's own anchor is `left:0` -- the trigger's left edge. If that
  // already sat on the column centre these assertions would pass with the fix
  // removed, so name the gap instead of assuming it.
  assert.notEqual(triggerLeft + width / 2, railLeft + railWidth / 2, `${label}: the trigger is not the column centre`);
  console.log(`${label}: chooser ${left}..${left + width}, rail ${railLeft}..${railLeft + railWidth}`);
}

check('Build project selected', 1440, 426, 768, 540, 430, 760);
check('Build activity open', 1440, 426, 580, 540, 426, 580, railResize);
check('Build viewer open', 1440, 300, 500, 414, 300, 500, railResize);
check('Build narrow', 390, 16, 358, 130, 16, 358);
// Widening back out after the narrow case above: the width is rewritten on
// every call, so a phone-sized chooser must not survive into a desktop layout.
check('Build reopened wide', 1440, 336, 768, 450, 340, 760);
assert.equal(typeof panels.positionLibraryMenu, 'function');

// The two clamps, each made to BIND.
//
// Every case above is satisfied by centring alone: take `Math.max(margin, ...)`
// and `Math.min(..., viewport - margin - width)` back out of
// positionLibraryMenu and all of them still pass. So the 16px edge margin the
// fix promises -- the part that keeps a phone-width chooser on the screen --
// was the one piece of the arithmetic nothing defended. These are the two
// layouts where centring on the column would put the panel off the window: a
// rail that begins left of the viewport, and a rail pushed right by Build's
// viewer while the window is small. There the requirement is not "centred on
// the column", it is "still on screen, resting against the margin", so this
// check asserts that instead -- and asserts the centred answer would have been
// different, so neither case can pass with the clamp removed.
function checkClamped(label, viewport, railLeft, railWidth, triggerLeft, expectedLeft, expectedWidth) {
  window.innerWidth = viewport;
  boxes.rail = { left: railLeft, width: railWidth };
  boxes.wrap = { left: triggerLeft };
  listeners.resize();
  const left = triggerLeft + parseFloat(menu.style.left);
  const width = parseFloat(menu.style.width);
  const centred = railLeft + (railWidth - width) / 2;
  assert.equal(width, expectedWidth, `${label}: chooser width`);
  assert.equal(left, expectedLeft, `${label}: chooser left`);
  assert.notEqual(centred, expectedLeft, `${label}: centring alone already answers this -- the clamp is not under test`);
  assert.ok(left >= 16, `${label}: keeps the left margin`);
  assert.ok(left + width <= viewport - 16, `${label}: keeps the right margin`);
  console.log(`${label}: chooser ${left}..${left + width} in a ${viewport}px window (centring wanted ${centred})`);
}

checkClamped('Clamped at the left edge', 1000, -120, 900, 40, 16, 760);
checkClamped('Clamped at the right edge', 1000, 700, 400, 760, 584, 400);

// Opening the chooser is the path every person takes, and the cases above do
// not exercise it: they call positionLibraryMenu() and the rail's observer
// directly. Nothing here would notice if toggleLibraryMenu() stopped
// positioning the panel -- only the Chromium test would, and that one SKIPS
// where Chromium cannot launch. So drive the toggle, from an inline `left`
// cleared back to the markup's own anchor, and require the open panel to come
// back centred on the column.
globalThis.document.createElement = () => ({ style: {}, dataset: {}, setAttribute() {} });
globalThis.document.querySelectorAll = () => [];
menu.prepend = () => {};
elements['tc-code-project-btn'] = { setAttribute() {} };
state.libraryProjects = [];  // already loaded and empty: no fetch, no previews
panels.toggleLibraryMenu();
assert.equal(menu.style.display, 'none', 'Opening the chooser: the toggle closes an open panel first');
window.innerWidth = 1440;
boxes.rail = { left: 426, width: 768 };
boxes.wrap = { left: 540 };
menu.style.left = '';
menu.style.width = '';
panels.toggleLibraryMenu();
assert.equal(menu.style.display, 'flex', 'Opening the chooser: the panel is shown');
assert.equal(menu.style.boxSizing, 'border-box', 'Opening the chooser: measured width includes borders');
const openedLeft = 540 + parseFloat(menu.style.left);
const openedWidth = parseFloat(menu.style.width);
assert.equal(openedLeft, 430, 'Opening the chooser: chooser left');
assert.equal(openedWidth, 760, 'Opening the chooser: chooser width');
assert.equal(openedLeft + openedWidth / 2, 426 + 768 / 2, 'Opening the chooser: shares the rail centre');
assert.notEqual(540 + openedWidth / 2, 426 + 768 / 2, 'Opening the chooser: the trigger is not the column centre');
console.log(`Opening the chooser: chooser ${openedLeft}..${openedLeft + openedWidth}, rail 426..1194`);

// Two states that are not layouts but that this code is still reached in: a
// document with no composer rail (the panel is not ours to move there), and a
// rail with no box yet -- a resize notification on the way to a real width,
// while Build's surface is swapping. In both the requirement is that NOTHING
// is written: a zero-width column pushed through the arithmetic would collapse
// an open chooser, which reads as the panel closing itself rather than as the
// column not being ready.
const settled = { left: menu.style.left, width: menu.style.width };
assert.ok(parseFloat(settled.width) > 0, 'the cases above must leave real geometry to defend');

elements['tc-composer-rail'] = null;
assert.doesNotThrow(() => panels.positionLibraryMenu(), 'no rail: must be a no-op');
assert.deepEqual({ left: menu.style.left, width: menu.style.width }, settled, 'no rail: the panel is untouched');
elements['tc-composer-rail'] = rail;

boxes.rail = { left: 0, width: 0 };
boxes.wrap = { left: 0 };
panels.positionLibraryMenu();
assert.deepEqual({ left: menu.style.left, width: menu.style.width }, settled, 'unlaid rail: the panel keeps its last good geometry');
console.log(`Degenerate states: no rail and an unlaid rail both keep ${settled.width} at ${settled.left}`);
