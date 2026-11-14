/* window_geometry.js — the arithmetic behind moving, snapping and tearing off
 * Thomas windows. Pure functions on plain numbers, so main.js (which needs
 * Electron) stays thin and the rules can be tested in Node on their own.
 *
 * All points are screen points in the same units Electron reports window
 * bounds in; a rect is { x, y, width, height }.
 */
"use strict";

// How far below a window's top edge its tab strip reaches. A tab dropped
// anywhere in this band joins that window, the way a browser's tab row does.
const STRIP_BAND = 44;
// Pointer travel below this is a click, not the start of a drag.
const DRAG_THRESHOLD = 5;
// How far the pointer may leave the strip row before a dragged tab tears out.
const TEAR_DISTANCE = 28;
// How close to a work-area edge a released window snaps.
const SNAP_EDGE = 12;

/* The window moves by exactly as far as the pointer has. */
function dragBounds(startBounds, startPoint, point) {
  return {
    x: Math.round(startBounds.x + (point.x - startPoint.x)),
    y: Math.round(startBounds.y + (point.y - startPoint.y)),
    width: startBounds.width,
    height: startBounds.height,
  };
}

/* Pulling a maximized window by its title bar restores it, with the pointer
 * kept over the same fraction of the bar so it does not leap away. */
function restoreUnderPointer(normalBounds, maximizedBounds, point) {
  const fraction = maximizedBounds.width > 0
    ? Math.min(1, Math.max(0, (point.x - maximizedBounds.x) / maximizedBounds.width)) : 0.5;
  return {
    x: Math.round(point.x - normalBounds.width * fraction),
    y: Math.round(point.y - Math.min(16, normalBounds.height)),
    width: normalBounds.width,
    height: normalBounds.height,
  };
}

/* What releasing a dragged window at `point` does, given the work area of the
 * display it is on: the top edge maximizes, the side edges tile a half. */
function snapZone(point, workArea) {
  if (point.y <= workArea.y + SNAP_EDGE) return "maximize";
  if (point.x <= workArea.x + SNAP_EDGE) return "left";
  if (point.x >= workArea.x + workArea.width - SNAP_EDGE) return "right";
  return null;
}
function snapBounds(zone, workArea) {
  const half = Math.floor(workArea.width / 2);
  if (zone === "left") return { x: workArea.x, y: workArea.y, width: half, height: workArea.height };
  if (zone === "right") {
    return { x: workArea.x + half, y: workArea.y, width: workArea.width - half, height: workArea.height };
  }
  return null;
}

/* Which window's tab strip is under `point`, if any. `windows` is a list of
 * { id, bounds }, front-most first, and `exceptId` is the window being dragged
 * (a window is never dropped onto itself). */
function stripUnder(point, windows, exceptId) {
  for (const w of windows) {
    if (w.id === exceptId) continue;
    const b = w.bounds;
    if (point.x >= b.x && point.x <= b.x + b.width && point.y >= b.y && point.y <= b.y + STRIP_BAND) return w.id;
  }
  return null;
}

/* A torn-off window opens so the pointer sits over its first tab. It is not
 * kept on the display while it is being dragged (a window follows the pointer
 * wherever it goes, including partly off a screen); keepReachable puts it back
 * where its tab strip can be grabbed when it is let go. */
function tearOffBounds(point, size, workArea) {
  return {
    x: Math.round(point.x - 90), y: Math.round(point.y - 18),
    width: Math.min(size.width, workArea.width), height: Math.min(size.height, workArea.height),
  };
}
const REACH = 120;      // how much of a window's top edge must stay on screen
/* Nudges a window so its title bar is on the display and can be grabbed. */
function keepReachable(bounds, workArea) {
  const x = Math.min(Math.max(bounds.x, workArea.x - bounds.width + REACH), workArea.x + workArea.width - REACH);
  const y = Math.min(Math.max(bounds.y, workArea.y), workArea.y + workArea.height - 60);
  return { x: Math.round(x), y: Math.round(y), width: bounds.width, height: bounds.height };
}

/* A new window opens a little down and to the right of the one in front, so
 * the two never sit exactly on top of each other. */
function cascadeBounds(from, workArea) {
  const width = Math.min(from.width, workArea.width);
  const height = Math.min(from.height, workArea.height);
  let x = from.x + 32;
  let y = from.y + 32;
  if (x + width > workArea.x + workArea.width) x = workArea.x;
  if (y + height > workArea.y + workArea.height) y = workArea.y;
  return { x, y, width, height };
}

/* Where a tab dragged along its own strip lands: the index of the slot whose
 * midpoint the pointer has crossed. `mids` are the other tabs' midpoints, in
 * order, with the dragged tab left out. */
function slotFor(pointerX, mids) {
  let slot = 0;
  for (const m of mids) if (pointerX > m) slot += 1;
  return slot;
}

/* Whether a pointer at y has left a strip whose row spans [top, bottom] far
 * enough that the tab should tear out into a window of its own. */
function shouldTearOut(y, top, bottom) {
  return y < top - TEAR_DISTANCE || y > bottom + TEAR_DISTANCE;
}

module.exports = {
  STRIP_BAND, DRAG_THRESHOLD, TEAR_DISTANCE, SNAP_EDGE,
  dragBounds, restoreUnderPointer, snapZone, snapBounds, stripUnder,
  tearOffBounds, keepReachable, cascadeBounds, slotFor, shouldTearOut,
};
