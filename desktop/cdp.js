/* cdp.js — the agent<->page channel: Chrome DevTools Protocol over a view's
 * webContents.debugger. Split out of main.js, which owns windows and tabs;
 * everything here is a function of one view, with no window or tab state.
 */
"use strict";

/* ── CDP (the one agent↔page channel) ───────────────────────────────── */
async function cdpFor(view) {
  const dbg = view.webContents.debugger;
  if (!dbg.isAttached()) {
    dbg.attach("1.3");
    // Gate-6 lesson: press events route through the focus pipeline; an
    // unfocused window drops them. Focus emulation keeps input honest.
    await dbg.sendCommand("Emulation.setFocusEmulationEnabled", { enabled: true });
  }
  return (method, params) => dbg.sendCommand(method, params || {});
}
async function cdpEval(view, expression) {
  const send = await cdpFor(view);
  const out = await send("Runtime.evaluate", { expression, returnByValue: true });
  if (out.exceptionDetails) throw new Error("eval failed");
  return out.result.value;
}
/* The accessibility tree is the anchor a recorded task should hang on.
 *
 * A CSS selector breaks the next time a site changes its markup, and a
 * coordinate breaks on the next reflow. "The button named Pay bill" survives
 * both, because it is what the page means rather than how it is built. This
 * read is also the honest way for the agent to see a page: names and roles,
 * not a screenshot it has to guess at.
 */
const AX_INTERESTING = new Set([
  "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
  "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "switch", "slider",
  "listbox", "option", "heading", "spinbutton",
]);
async function cdpAxSnapshot(view, limit) {
  const send = await cdpFor(view);
  await send("Accessibility.enable");
  const { nodes } = await send("Accessibility.getFullAXTree", {});
  const out = [];
  for (const node of nodes) {
    if (node.ignored) continue;
    const role = node.role && node.role.value;
    const name = node.name && node.name.value;
    if (!role || !AX_INTERESTING.has(String(role))) continue;
    if (!name || !String(name).trim()) continue;
    out.push({
      role: String(role),
      name: String(name).trim().slice(0, 160),
      backendNodeId: node.backendDOMNodeId,
      disabled: Boolean(node.properties && node.properties.some(
        p => p.name === "disabled" && p.value && p.value.value === true)),
    });
    if (out.length >= (limit || 300)) break;
  }
  return out;
}
// Clicking by anchor instead of by selector: same action, addressing that
// survives a redesign. Falls back to nothing -- a miss is reported, never
// approximated, so a caller can ask the model for the equivalent element
// rather than clicking whatever happened to be nearby.
/* Where to click, asked of the element itself.
 *
 * DOM.getBoxModel returns layout coordinates that do not always match the
 * viewport the input dispatcher aims at -- on wikipedia.org's circular link
 * layout it produced x=-100, y=-437, so every click silently landed nowhere.
 * getBoundingClientRect is what the renderer itself would use, after
 * scrolling the element into view, so it cannot disagree with the viewport.
 */
async function clickPointOf(send, handle) {
  const resolved = await send("DOM.resolveNode", handle);
  const objectId = resolved.object && resolved.object.objectId;
  if (!objectId) throw new Error("element could not be resolved");
  const out = await send("Runtime.callFunctionOn", {
    objectId,
    returnByValue: true,
    functionDeclaration: `function () {
      // An accessible name often belongs to a text node or a zero-size
      // wrapper, so climb to the nearest ancestor that actually occupies
      // space -- that is the thing a person would be pointing at.
      let el = this.nodeType === 3 ? this.parentElement : this;
      let guard = 0;
      while (el && guard++ < 8) {
        const box = el.getBoundingClientRect();
        if (box.width > 0 && box.height > 0) break;
        el = el.parentElement;
      }
      if (!el) return null;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rects = el.getClientRects();
      const r = rects && rects.length ? rects[0] : el.getBoundingClientRect();
      return {
        x: r.left + r.width / 2, y: r.top + r.height / 2,
        w: r.width, h: r.height, tag: el.tagName,
        vw: window.innerWidth, vh: window.innerHeight,
      };
    }`,
  });
  const point = out.result && out.result.value;
  if (!point || point.w <= 0 || point.h <= 0) throw new Error("element has no clickable area");
  // Say the numbers. A bare "outside the viewport" sent me guessing twice.
  if (point.x < 0 || point.y < 0 || point.x > point.vw || point.y > point.vh) {
    throw new Error(
      `element sits outside the viewport after scrolling: point ${Math.round(point.x)},${Math.round(point.y)}`
      + ` in a ${point.vw}x${point.vh} view (<${point.tag}>, ${Math.round(point.w)}x${Math.round(point.h)})`);
  }
  return { x: point.x, y: point.y };
}
async function dispatchClick(send, view, point) {
  view.webContents.focus();
  const at = { x: point.x, y: point.y, button: "left", clickCount: 1 };
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0 });
  await send("Input.dispatchMouseEvent", Object.assign({ type: "mousePressed", buttons: 1 }, at));
  await send("Input.dispatchMouseEvent", Object.assign({ type: "mouseReleased", buttons: 0 }, at));
  return point;
}

async function cdpClickAx(view, role, name) {
  const send = await cdpFor(view);
  const nodes = await cdpAxSnapshot(view, 1000);
  const wanted = String(name || "").trim().toLowerCase();
  const match = nodes.find(n =>
    (!role || n.role === role) && n.name.toLowerCase() === wanted)
    || nodes.find(n => (!role || n.role === role) && n.name.toLowerCase().includes(wanted));
  if (!match) throw new Error(`no ${role || "element"} named "${name}" on this page`);
  if (match.disabled) throw new Error(`"${match.name}" is disabled`);
  const point = await clickPointOf(send, { backendNodeId: match.backendNodeId });
  await dispatchClick(send, view, point);
  return { matched: { role: match.role, name: match.name }, at: point };
}

async function cdpClick(view, selector) {
  const send = await cdpFor(view);
  const doc = await send("DOM.getDocument", { depth: 1 });
  const node = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector });
  if (!node.nodeId) throw new Error("selector not found: " + selector);
  const point = await clickPointOf(send, { nodeId: node.nodeId });
  await dispatchClick(send, view, point);
  return point;
}

/* ── Input the agent needs to be a user without the owner's mouse ───────
 * Typing, keys, a screenshot to a file, and waiting for text. All go through
 * the same debugger channel as clicks, so they work on a window that is
 * behind others and never touch the real keyboard or pointer.
 */
const KEYS = {
  Enter: { code: "Enter", vk: 13, text: "\r" }, Tab: { code: "Tab", vk: 9 },
  Escape: { code: "Escape", vk: 27 }, Backspace: { code: "Backspace", vk: 8 },
  Delete: { code: "Delete", vk: 46 }, ArrowUp: { code: "ArrowUp", vk: 38 },
  ArrowDown: { code: "ArrowDown", vk: 40 }, ArrowLeft: { code: "ArrowLeft", vk: 37 },
  ArrowRight: { code: "ArrowRight", vk: 39 }, Home: { code: "Home", vk: 36 },
  End: { code: "End", vk: 35 }, PageDown: { code: "PageDown", vk: 34 },
  PageUp: { code: "PageUp", vk: 33 },
};
function modifierBits(mods) {
  const m = new Set((mods || []).map(x => String(x).toLowerCase()));
  return (m.has("alt") ? 1 : 0) | (m.has("ctrl") || m.has("control") ? 2 : 0)
    | (m.has("meta") || m.has("cmd") ? 4 : 0) | (m.has("shift") ? 8 : 0);
}
async function cdpType(view, text) {
  const send = await cdpFor(view);
  view.webContents.focus();
  await send("Input.insertText", { text: String(text) });
  return { typed: String(text).length };
}
async function cdpKey(view, key, mods) {
  const send = await cdpFor(view);
  view.webContents.focus();
  const known = KEYS[key];
  const single = !known && String(key).length === 1;
  if (!known && !single) throw new Error("unknown key " + key + "; use one character or " + Object.keys(KEYS).join(", "));
  const upper = single ? String(key).toUpperCase() : "";
  const base = {
    modifiers: modifierBits(mods), key: known ? key : String(key),
    code: known ? known.code : "Key" + upper,
    windowsVirtualKeyCode: known ? known.vk : upper.charCodeAt(0),
  };
  const text = known ? known.text : (modifierBits(mods) ? undefined : String(key));
  await send("Input.dispatchKeyEvent", Object.assign({ type: text ? "keyDown" : "rawKeyDown" }, base, text ? { text } : {}));
  await send("Input.dispatchKeyEvent", Object.assign({ type: "keyUp" }, base));
  return { key };
}
async function cdpScreenshot(view, file) {
  const send = await cdpFor(view);
  const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 60 });
  require("node:fs").writeFileSync(file, Buffer.from(shot.data, "base64"));
  return { file };
}
async function cdpWaitForText(view, text, timeoutMs) {
  const wanted = JSON.stringify(String(text));
  const until = Date.now() + Math.min(Number(timeoutMs) || 15000, 120000);
  for (;;) {
    if (await cdpEval(view, `!!document.body && document.body.innerText.includes(${wanted})`)) return { found: true };
    if (Date.now() > until) return { found: false };
    await new Promise(r => setTimeout(r, 250));
  }
}

module.exports = { cdpEval, cdpAxSnapshot, cdpClickAx, cdpClick, cdpType, cdpKey, cdpScreenshot, cdpWaitForText };
