(function () {
  "use strict";

  const L = window.ThomasUiLayout;
  if (!L) return;
  const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  const state = { active: false, selected: null, drag: null, history: [], future: [], snap: true, chord: false, returnFocus: null };
  let ui;

  function element(tag, attrs, html) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
    if (html !== undefined) node.innerHTML = html;
    return node;
  }
  function makeUi() {
    const entry = element("button", { class: "thomas-ui-edit-entry", type: "button", "aria-label": "Edit this Thomas workspace", "aria-keyshortcuts": "Control+Shift+E Shift+Tab" }, "Edit UI");
    const editor = element("div", { class: "thomas-ui-editor", hidden: "", "data-editor-ui": "", role: "region", "aria-label": "Thomas UI Edit Mode" });
    editor.innerHTML = `<div class="thomas-ui-edit-grid"></div><div class="thomas-ui-edit-toolbar" role="toolbar" aria-label="UI layout tools"><button class="thomas-ui-edit-grip" type="button" data-action="move-toolbar" aria-label="Move toolbar">Move</button><b class="thomas-ui-edit-badge">EDIT</b><span class="thomas-ui-edit-name">Select a region</span><span class="thomas-ui-edit-breakpoint"></span><button type="button" data-action="undo" aria-label="Undo draft change">Undo</button><button type="button" data-action="redo" aria-label="Redo draft change">Redo</button><button type="button" data-action="snap" aria-label="Toggle snapping" aria-pressed="true">Snap</button><button type="button" data-action="lock" aria-label="Lock selected region">Lock</button><button type="button" data-action="front" aria-label="Bring selected region to front">Front</button><button type="button" data-action="back" aria-label="Send selected region backward">Back</button><button type="button" data-action="reset" aria-label="Reset selected region">Reset item</button><button type="button" data-action="reset-view" aria-label="Reset this breakpoint draft">Reset view</button><button type="button" data-action="versions" aria-label="Restore previous saved layout">Previous</button><button type="button" data-action="export" aria-label="Export all layouts">Export</button><button type="button" data-action="cancel" aria-label="Discard draft layout">Cancel</button><button type="button" data-action="done" aria-label="Save layout and exit UI Edit Mode">Done &amp; Save</button></div><aside class="thomas-ui-edit-inspector" aria-label="Selected UI region details"><label>Region<select data-inspector="regions" aria-label="Choose any UI region"></select></label><dl><div><dt>Identity</dt><dd data-inspector="identity">None selected</dd></div><div><dt>Component</dt><dd data-inspector="component">-</dd></div><div><dt>Size</dt><dd data-inspector="size">-</dd></div><div><dt>Stack</dt><dd data-inspector="stack">-</dd></div></dl><label>AI edit this region<textarea data-inspector="prompt" rows="3" placeholder="Tell Thomas how this region should look or behave..."></textarea></label><button type="button" data-action="ai-edit">Send to Thomas</button><small>Done &amp; Save makes this draft permanent. Cancel or Escape restores the last saved layout.</small></aside><div class="thomas-ui-edit-selection" hidden><span></span>${HANDLES.map((edge) => `<button type="button" class="thomas-ui-resize-handle thomas-ui-resize-${edge}" data-edge="${edge}" aria-label="Resize ${edge}"></button>`).join("")}</div><i class="thomas-ui-guide thomas-ui-guide-x"></i><i class="thomas-ui-guide thomas-ui-guide-y"></i><div class="thomas-ui-edit-toast" role="status" aria-live="polite"></div>`;
    document.body.append(entry, editor);
    const toolbar = editor.querySelector(".thomas-ui-edit-toolbar");
    try {
      const saved = JSON.parse(localStorage.getItem("thomas_ui_toolbar_v1") || "null");
      if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) { toolbar.style.left = `${saved.x}px`; toolbar.style.top = `${saved.y}px`; toolbar.style.translate = "0"; }
    } catch (_) { /* the default position is safe */ }
    return {
      entry, editor, toolbar, inspector: editor.querySelector(".thomas-ui-edit-inspector"),
      regions: editor.querySelector('[data-inspector="regions"]'), identity: editor.querySelector('[data-inspector="identity"]'),
      component: editor.querySelector('[data-inspector="component"]'), size: editor.querySelector('[data-inspector="size"]'),
      stack: editor.querySelector('[data-inspector="stack"]'), prompt: editor.querySelector('[data-inspector="prompt"]'),
      selection: editor.querySelector(".thomas-ui-edit-selection"), name: editor.querySelector(".thomas-ui-edit-name"),
      point: editor.querySelector(".thomas-ui-edit-breakpoint"), toast: editor.querySelector(".thomas-ui-edit-toast"),
      guideX: editor.querySelector(".thomas-ui-guide-x"), guideY: editor.querySelector(".thomas-ui-guide-y")
    };
  }
  function typing(target) { return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target && target.isContentEditable; }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function flash(message) { ui.toast.textContent = message; clearTimeout(flash.timer); flash.timer = setTimeout(() => { ui.toast.textContent = ""; }, 1800); }
  function policy() { return state.selected ? L.policy(state.selected) : null; }
  function selectedId() { return state.selected ? L.identity(state.selected) : ""; }
  function item() { return state.selected ? Object.assign({ x: 0, y: 0 }, L.get(selectedId()) || {}) : null; }
  function record() { state.history.push(L.currentMap()); state.history = state.history.slice(-40); state.future = []; sync(); }
  function label(node) { return node.dataset.uiLabel || node.getAttribute("aria-label") || node.dataset.uiId; }
  function setGuides(x, y) { ui.guideX.classList.toggle("is-visible", x); ui.guideY.classList.toggle("is-visible", y); }
  function registeredRegions() {
    return Array.from(document.querySelectorAll("[data-ui-id]")).filter((node) => !node.closest("[data-editor-ui]") && L.identity(node));
  }
  function syncRegionPicker() {
    const regions = registeredRegions(); const chosen = selectedId(); ui.regions.innerHTML = "";
    const blank = document.createElement("option"); blank.value = ""; blank.textContent = `${regions.length} regions`; ui.regions.appendChild(blank);
    regions.sort((a, b) => label(a).localeCompare(label(b))).forEach((node) => {
      const option = document.createElement("option"); option.value = L.identity(node); option.textContent = label(node); option.selected = option.value === chosen; ui.regions.appendChild(option);
    });
  }
  function refreshInspector() {
    syncRegionPicker();
    if (!state.selected || !state.selected.isConnected) {
      ui.identity.textContent = "None selected"; ui.component.textContent = "-"; ui.size.textContent = "-"; ui.stack.textContent = "-"; return;
    }
    const rect = state.selected.getBoundingClientRect(); const selectedItem = item();
    ui.identity.textContent = selectedId(); ui.component.textContent = state.selected.dataset.uiComponent || state.selected.tagName.toLowerCase();
    ui.size.textContent = `${Math.round(rect.width)} x ${Math.round(rect.height)}`; ui.stack.textContent = String(Number(selectedItem.z) || 0);
  }
  function refreshSelection() {
    if (!state.active || !state.selected || !state.selected.isConnected) { ui.selection.hidden = true; return; }
    const rect = state.selected.getBoundingClientRect();
    if (!rect.width || !rect.height) { ui.selection.hidden = true; return; }
    ui.selection.hidden = false; ui.selection.style.left = `${rect.left}px`; ui.selection.style.top = `${rect.top}px`;
    ui.selection.style.width = `${rect.width}px`; ui.selection.style.height = `${rect.height}px`;
    ui.selection.querySelector("span").textContent = label(state.selected);
    const canResize = policy().resize && !item().locked;
    ui.selection.querySelectorAll("[data-edge]").forEach((handle) => { handle.hidden = !canResize; }); refreshInspector();
  }
  function sync() {
    syncRegionPicker();
    ui.point.textContent = `${L.currentPoint()}${L.isDirty() ? " - draft" : " - saved"}`; ui.name.textContent = state.selected ? label(state.selected) : "Select a region";
    const selectedItem = item();
    ui.toolbar.querySelector('[data-action="undo"]').disabled = !state.history.length;
    ui.toolbar.querySelector('[data-action="redo"]').disabled = !state.future.length;
    ["lock", "front", "back", "reset"].forEach((action) => { ui.toolbar.querySelector(`[data-action="${action}"]`).disabled = !state.selected; });
    ui.toolbar.querySelector('[data-action="lock"]').setAttribute("aria-pressed", String(Boolean(selectedItem && selectedItem.locked)));
    ui.toolbar.querySelector('[data-action="lock"]').textContent = selectedItem && selectedItem.locked ? "Unlock" : "Lock";
    ui.toolbar.querySelector('[data-action="snap"]').setAttribute("aria-pressed", String(state.snap)); requestAnimationFrame(refreshSelection);
  }
  function setActive(active, options) {
    const next = Boolean(active); const save = !options || options.save !== false;
    if (next === state.active) return;
    if (next && document.activeElement instanceof HTMLElement) state.returnFocus = document.activeElement;
    if (next) L.beginDraft(); else if (save) L.commitDraft(); else L.cancelDraft();
    state.active = next; state.drag = null; state.selected = null; state.history = []; state.future = []; setGuides(false, false);
    document.documentElement.classList.toggle("thomas-ui-editing", state.active); ui.editor.hidden = !state.active; ui.entry.hidden = state.active;
    sync();
    if (state.active) { ui.toolbar.querySelector('[data-action="done"]').focus(); flash(`Editing ${L.currentPoint()} draft`); }
    else if (state.returnFocus && state.returnFocus.isConnected) state.returnFocus.focus({ preventScroll: true });
    window.dispatchEvent(new CustomEvent("thomas:ui-edit-mode-change", { detail: { active: state.active, saved: !state.active && save } }));
  }
  function select(node) { state.selected = node; sync(); if (L.policy(node).protected) flash(`${label(node)} is protected`); }
  function boundary(node) {
    const p = L.policy(node); if (p.containment === "parent" && node.parentElement) return node.parentElement.getBoundingClientRect();
    return { left: 0, top: 0, right: innerWidth, bottom: innerHeight, width: innerWidth, height: innerHeight };
  }
  function snapped(value) { return state.snap ? Math.round(value / 8) * 8 : Math.round(value); }
  function preview(node, next) {
    node.style.translate = `${next.x || 0}px ${next.y || 0}px`; if (Number.isFinite(next.width)) node.style.width = `${next.width}px`;
    if (Number.isFinite(next.height)) node.style.height = `${next.height}px`; if (Number.isFinite(next.z)) node.style.zIndex = String(next.z);
    state.drag.pending = next; refreshSelection();
  }
  function collides(node, next, natural) {
    if (L.policy(node).collision !== "avoid") return false;
    const trial = { left: natural.left + next.x, top: natural.top + next.y, right: natural.left + next.x + (next.width || natural.width), bottom: natural.top + next.y + (next.height || natural.height) };
    return registeredRegions().some((other) => { if (other === node || node.contains(other) || other.contains(node) || L.policy(other).protected) return false; const r = other.getBoundingClientRect(); return trial.left < r.right && trial.right > r.left && trial.top < r.bottom && trial.bottom > r.top; });
  }
  function beginDrag(event, node, type, edge) {
    const p = L.policy(node); const current = Object.assign({ x: 0, y: 0 }, L.get(L.identity(node)) || {});
    if (current.locked || p.protected || (type === "move" && !p.move) || (type === "resize" && !p.resize)) { flash(current.locked ? "Unlock this region to change it" : "This region is protected"); return; }
    record(); const rect = node.getBoundingClientRect();
    state.drag = { node, type, edge, startX: event.clientX, startY: event.clientY, item: current, rect, natural: { left: rect.left - current.x, top: rect.top - current.y, width: rect.width, height: rect.height }, pending: current };
  }
  function moveDrag(event) {
    const d = state.drag; if (!d) return; const dx = event.clientX - d.startX, dy = event.clientY - d.startY, p = L.policy(d.node), box = boundary(d.node);
    if (d.type === "move") {
      let x = d.item.x + dx, y = d.item.y + dy; const centerX = d.natural.left + x + d.rect.width / 2, centerY = d.natural.top + y + d.rect.height / 2;
      const guideX = Math.abs(centerX - (box.left + box.right) / 2) <= 8, guideY = Math.abs(centerY - (box.top + box.bottom) / 2) <= 8;
      if (guideX && state.snap) x += (box.left + box.right) / 2 - centerX; if (guideY && state.snap) y += (box.top + box.bottom) / 2 - centerY;
      x = Math.max(box.left - d.natural.left, Math.min(box.right - d.natural.left - d.rect.width, snapped(x)));
      y = Math.max(box.top - d.natural.top, Math.min(box.bottom - d.natural.top - d.rect.height, snapped(y)));
      const next = Object.assign({}, d.item, { x, y }); setGuides(guideX, guideY); if (!collides(d.node, next, d.natural)) preview(d.node, next);
    } else {
      const west = d.edge.includes("w"), north = d.edge.includes("n"), east = d.edge.includes("e"), south = d.edge.includes("s");
      const baseW = d.item.width || d.rect.width, baseH = d.item.height || d.rect.height;
      const width = snapped(Math.max(p.minWidth, Math.min(p.maxWidth, box.width, baseW + (east ? dx : west ? -dx : 0))));
      const height = snapped(Math.max(p.minHeight, Math.min(p.maxHeight, box.height, baseH + (south ? dy : north ? -dy : 0))));
      const next = Object.assign({}, d.item, { x: snapped(d.item.x + (west ? baseW - width : 0)), y: snapped(d.item.y + (north ? baseH - height : 0)), width, height });
      next.x = Math.max(box.left - d.natural.left, Math.min(box.right - d.natural.left - width, next.x)); next.y = Math.max(box.top - d.natural.top, Math.min(box.bottom - d.natural.top - height, next.y));
      if (!collides(d.node, next, d.natural)) preview(d.node, next);
    }
  }
  function endDrag() { if (!state.drag) return; L.set(L.identity(state.drag.node), state.drag.pending); state.drag = null; setGuides(false, false); sync(); }
  function changeSelected(patch) {
    if (!state.selected) return; const current = item(), p = policy(), rect = state.selected.getBoundingClientRect(), box = boundary(state.selected);
    const next = Object.assign({}, current, patch), naturalLeft = rect.left - current.x, naturalTop = rect.top - current.y;
    next.width = Number.isFinite(next.width) ? Math.max(p.minWidth, Math.min(p.maxWidth, box.width, next.width)) : next.width;
    next.height = Number.isFinite(next.height) ? Math.max(p.minHeight, Math.min(p.maxHeight, box.height, next.height)) : next.height;
    const width = next.width || rect.width, height = next.height || rect.height;
    next.x = Math.max(box.left - naturalLeft, Math.min(box.right - naturalLeft - width, next.x)); next.y = Math.max(box.top - naturalTop, Math.min(box.bottom - naturalTop - height, next.y));
    const changesGeometry = ["x", "y", "width", "height"].some((key) => Object.prototype.hasOwnProperty.call(patch, key));
    if (changesGeometry && collides(state.selected, next, { left: naturalLeft, top: naturalTop, width: rect.width, height: rect.height })) { flash("That change would overlap another region"); return; }
    record(); L.set(selectedId(), next); sync();
  }
  function stack(direction) {
    const zs = Object.values(L.currentMap()).map((value) => Number(value.z) || 0); const target = direction === "front" ? Math.max(0, ...zs) + 1 : Math.min(0, ...zs) - 1;
    changeSelected({ z: target }); flash(direction === "front" ? "Brought region to front" : "Sent region backward");
  }
  function undo() { const previous = state.history.pop(); if (!previous) return; state.future.push(L.currentMap()); L.replaceMap(previous); flash("Undid draft change"); sync(); }
  function redo() { const next = state.future.pop(); if (!next) return; state.history.push(L.currentMap()); L.replaceMap(next); flash("Redid draft change"); sync(); }
  function resetSelected() { if (!state.selected) return; record(); L.remove(selectedId()); flash(`${label(state.selected)} restored`); sync(); }
  function resetView() { record(); L.resetBreakpoint(); state.selected = null; flash(`${L.currentPoint()} draft restored`); sync(); }
  function exportLayout() {
    const blob = new Blob([JSON.stringify({ source: "Thomas UI Edit Mode", layouts: L.exportBook() }, null, 2)], { type: "application/json" });
    const link = document.createElement("a"), url = URL.createObjectURL(blob); link.href = url; link.download = "thomas-ui-layout.json"; link.click(); URL.revokeObjectURL(url); flash("Saved layouts exported");
  }
  function requestAiEdit() {
    if (!state.selected) { flash("Select a region first"); return; }
    const prompt = String(ui.prompt.value || "").trim(); if (!prompt) { ui.prompt.focus(); flash("Describe the change for Thomas"); return; }
    const detail = { type: "thomas:ui-ai-edit", workspace: L.workspace(), identity: selectedId(), label: label(state.selected), component: state.selected.dataset.uiComponent || "region", prompt };
    window.dispatchEvent(new CustomEvent("thomas:ui-ai-edit-request", { detail }));
    if (window.parent !== window) window.parent.postMessage(detail, location.origin); else document.querySelectorAll("iframe").forEach((frame) => { if (frame.contentWindow) frame.contentWindow.postMessage(detail, location.origin); });
    ui.prompt.value = ""; flash("Sent this region to Thomas");
  }
  function action(name) {
    if (name === "done") setActive(false, { save: true }); else if (name === "cancel") setActive(false, { save: false });
    else if (name === "undo") undo(); else if (name === "redo") redo(); else if (name === "snap") { state.snap = !state.snap; sync(); }
    else if (name === "lock") changeSelected({ locked: !item().locked }); else if (name === "front" || name === "back") stack(name);
    else if (name === "reset") resetSelected(); else if (name === "reset-view") resetView();
    else if (name === "versions") { if (L.restorePrevious()) { L.beginDraft(); flash("Previous saved layout restored"); sync(); } else flash("No earlier saved layout"); }
    else if (name === "export") exportLayout(); else if (name === "ai-edit") requestAiEdit();
  }
  function moveToolbar(event) {
    const rect = ui.toolbar.getBoundingClientRect(), start = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
    const move = (next) => { ui.toolbar.style.left = `${Math.max(8, Math.min(innerWidth - rect.width - 8, start.left + next.clientX - start.x))}px`; ui.toolbar.style.top = `${Math.max(8, Math.min(innerHeight - rect.height - 8, start.top + next.clientY - start.y))}px`; ui.toolbar.style.translate = "0"; };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); try { localStorage.setItem("thomas_ui_toolbar_v1", JSON.stringify({ x: parseFloat(ui.toolbar.style.left), y: parseFloat(ui.toolbar.style.top) })); } catch (_) {} };
    addEventListener("pointermove", move); addEventListener("pointerup", up, { once: true });
  }
  function onPointerDown(event) {
    if (!state.active || event.target.closest("[data-editor-ui]")) return; const node = event.target.closest("[data-ui-id]"); if (!node) return;
    event.preventDefault(); event.stopImmediatePropagation(); select(node); beginDrag(event, node, "move");
  }
  function onKeyDown(event) {
    if (event.key.toLowerCase() === "e" && event.ctrlKey && event.shiftKey) { event.preventDefault(); state.chord = false; setActive(!state.active, { save: true }); return; }
    if (event.key === "Tab" && event.shiftKey && !typing(event.target)) { event.preventDefault(); state.chord = false; setActive(!state.active, { save: true }); return; }
    if ((event.key === "Shift" && event.ctrlKey) || (event.key === "Control" && event.shiftKey)) { state.chord = true; return; }
    if (!["Shift", "Control"].includes(event.key)) state.chord = false; if (!state.active) return;
    if (event.key === "Escape") { event.preventDefault(); setActive(false, { save: false }); return; }
    if (event.ctrlKey && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
    if (event.ctrlKey && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
    if (!state.selected || typing(event.target) || !event.key.startsWith("Arrow")) return;
    event.preventDefault(); const current = item(), step = event.shiftKey ? 8 : 1, p = policy();
    if (current.locked) { flash("Unlock this region to change it"); return; }
    if (event.altKey && p.resize) changeSelected({ width: Math.max(p.minWidth, (current.width || state.selected.getBoundingClientRect().width) + (event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0)), height: Math.max(p.minHeight, (current.height || state.selected.getBoundingClientRect().height) + (event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0)) });
    else if (p.move) changeSelected({ x: current.x + (event.key === "ArrowRight" ? step : event.key === "ArrowLeft" ? -step : 0), y: current.y + (event.key === "ArrowDown" ? step : event.key === "ArrowUp" ? -step : 0) });
  }
  function start() {
    ui = makeUi(); ui.entry.addEventListener("click", () => setActive(true));
    ui.editor.addEventListener("click", (event) => { const button = event.target.closest("[data-action]"); if (button && button.dataset.action !== "move-toolbar") action(button.dataset.action); });
    ui.regions.addEventListener("change", () => { const node = registeredRegions().find((candidate) => L.identity(candidate) === ui.regions.value); if (node) { select(node); node.scrollIntoView({ block: "nearest", inline: "nearest" }); } });
    ui.toolbar.querySelector('[data-action="move-toolbar"]').addEventListener("pointerdown", moveToolbar);
    ui.selection.addEventListener("pointerdown", (event) => { const handle = event.target.closest("[data-edge]"); if (handle && state.selected) { event.preventDefault(); event.stopPropagation(); beginDrag(event, state.selected, "resize", handle.dataset.edge); } });
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("click", (event) => { if (state.active && event.target.closest("[data-ui-id]") && !event.target.closest("[data-editor-ui]")) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);
    addEventListener("pointermove", moveDrag); addEventListener("pointerup", endDrag); addEventListener("pointercancel", endDrag);
    addEventListener("keydown", onKeyDown); addEventListener("keyup", (event) => { if (["Shift", "Control"].includes(event.key) && state.chord) { state.chord = false; setActive(!state.active, { save: true }); } });
    addEventListener("scroll", refreshSelection, true); addEventListener("resize", () => { L.applyAll(); sync(); }); sync();
  }
  window.ThomasUiEditMode = { setActive, toggle: () => setActive(!state.active, { save: true }), isActive: () => state.active, selectedId };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
}());
