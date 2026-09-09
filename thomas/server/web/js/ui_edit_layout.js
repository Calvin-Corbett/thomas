(function () {
  "use strict";

  const KEY = "thomas_ui_layout_v2";
  const LEGACY_KEY = "thomas_ui_layout_v1";
  const BREAKPOINTS = ["desktop", "tablet", "mobile"];
  const bases = new WeakMap();
  const authoredSizes = new WeakMap();
  let editing = false;

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(left, right) { return JSON.stringify(left || {}) === JSON.stringify(right || {}); }
  function breakpoint(width) { return width < 760 ? "mobile" : width < 1080 ? "tablet" : "desktop"; }
  function workspace() {
    if (window.ThomasWorkspaceShell) return window.ThomasWorkspaceShell.workspaceKey();
    return (document.body && document.body.dataset.uiWorkspace) || location.pathname || "chat";
  }
  function emptyBook() { return { version: 2, workspaces: {} }; }
  function emptySlot() { return { saved: {}, draft: {}, history: [], future: [], dirty: false, updatedAt: "" }; }
  function normalizeSlot(value) {
    const slot = value && typeof value === "object" ? value : {};
    return {
      saved: clone(slot.saved || {}), draft: clone(slot.draft || slot.saved || {}),
      history: Array.isArray(slot.history) ? clone(slot.history).slice(-20) : [],
      future: Array.isArray(slot.future) ? clone(slot.future).slice(-20) : [],
      // Carried through deliberately: this list is rebuilt from a fixed set of
      // fields, and leaving `versions` out silently discarded the per-element
      // undo stack on the very next ensureSlot call.
      versions: slot.versions && typeof slot.versions === "object" ? clone(slot.versions) : {},
      dirty: Boolean(slot.dirty), updatedAt: String(slot.updatedAt || "")
    };
  }
  function migrateLegacy() {
    try {
      const legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || "null");
      if (!legacy || legacy.version !== 1 || !legacy.workspaces) return emptyBook();
      const book = emptyBook();
      Object.entries(legacy.workspaces).forEach(([space, points]) => {
        book.workspaces[space] = {};
        BREAKPOINTS.forEach((point) => {
          const map = clone(points && points[point] || {});
          book.workspaces[space][point] = Object.assign(emptySlot(), { saved: map, draft: clone(map) });
        });
      });
      return book;
    } catch (_) { return emptyBook(); }
  }
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || "null");
      return value && value.version === 2 && value.workspaces ? value : migrateLegacy();
    } catch (_) { return migrateLegacy(); }
  }
  function write(book) {
    try { localStorage.setItem(KEY, JSON.stringify(book)); }
    catch (_) { /* editing stays available without persistence */ }
    window.dispatchEvent(new CustomEvent("thomas:ui-layout-change"));
  }
  function ensureSlot(book, point) {
    const key = workspace();
    if (!book.workspaces[key]) book.workspaces[key] = {};
    book.workspaces[key][point] = normalizeSlot(book.workspaces[key][point]);
    return book.workspaces[key][point];
  }
  function currentPoint() { return breakpoint(window.innerWidth); }
  // The user overlay's element layer (thomas/server/overlay): entries the
  // overlay records for this workspace and breakpoint sit UNDER the local
  // book, so a local edit still wins per key. A minted entry whose anchor no
  // longer resolves, or resolves to a different kind of element than the one
  // it was recorded on, is an ORPHAN: left out of the active map and listed
  // by orphans(), never applied to a replacement node silently. An exact id
  // with no element in this document is listed too, so the UI can say so.
  let overlayView = null;
  const orphanKeys = new Set();
  function readOverlayView() { return overlayView || window.ThomasOverlayView || null; }
  function overlayEntries() {
    const view = readOverlayView();
    const spaces = view && view.elements ? view.elements[workspace()] : null;
    const map = spaces ? spaces[currentPoint()] : null;
    return map && typeof map === "object" ? map : {};
  }
  function overlayAnchor(key) {
    const view = readOverlayView();
    return (view && view.anchors && view.anchors[`${workspace()}:${currentPoint()}:${key}`]) || null;
  }
  function hasExact(key) {
    return Array.from(document.querySelectorAll("[data-ui-id]")).some((node) => identity(node) === key);
  }
  function overlayMap() {
    const out = {}; orphanKeys.clear();
    Object.entries(overlayEntries()).forEach(([key, entry]) => {
      if (!entry || typeof entry !== "object") return;
      const anchor = overlayAnchor(key);
      if (anchor && anchor.fragile) {
        const node = resolveSynthetic(key);
        const component = String(anchor.component || "").toLowerCase();
        // The same expression the Redesign descriptor records, so a component name is never compared to a tag name.
        const actual = node ? String(node.dataset.uiComponent || node.tagName).toLowerCase() : "";
        if (!node || (component && actual !== component)) { orphanKeys.add(key); return; }
      } else if (!hasExact(key)) orphanKeys.add(key);
      out[key] = clone(entry);
    });
    return out;
  }
  function overlaidKeys() { return Object.keys(overlayMap()); }
  function orphans() { overlayMap(); return Array.from(orphanKeys); }
  function refreshOverlay(view) { overlayView = view || null; }
  // Removing or reverting a key the overlay carries must retract it THERE, or
  // the local deletion is quietly re-covered on the next apply while the UI
  // reports a rollback. Returns the write's promise (null when nothing was
  // overlaid); the reply's adopt() takes the entry out of every document.
  function clearOverlaid(ids, why) {
    const entries = overlayEntries();
    const keys = ids.filter((id) => Object.prototype.hasOwnProperty.call(entries, id));
    if (!keys.length) return null;
    const overlay = window.ThomasOverlay;
    if (!overlay || typeof overlay.record !== "function") return Promise.resolve({ ok: false, unavailable: true, keys });
    const records = keys.map((id) => ({ op: "clear", kind: "element", address: `element:${workspace()}:${currentPoint()}:${id}` }));
    return overlay.record({ actor: "layout", instruction: why || "clear", targets: keys }, records)
      .then((reply) => Object.assign({ keys }, reply || { ok: false }));
  }
  function identity(node) {
    if (!(node instanceof Element)) return "";
    const id = String(node.dataset.uiId || "").trim();
    const key = String(node.dataset.uiInstanceKey || "").trim();
    return id && key ? `${id}::${key}` : id;
  }
  function currentMap() {
    const slot = ensureSlot(read(), currentPoint());
    return Object.assign(overlayMap(), clone(editing ? slot.draft : slot.saved));
  }
  function replaceMap(next) {
    const book = read(); const slot = ensureSlot(book, currentPoint()); const map = clone(next || {});
    // An entry identical to the overlay's is the overlay's: it is not copied into the local book.
    const overlay = overlayMap();
    Object.keys(overlay).forEach((id) => { if (equal(map[id], overlay[id])) delete map[id]; });
    if (editing) { slot.draft = map; slot.dirty = !equal(slot.draft, slot.saved); }
    else { slot.saved = map; slot.draft = clone(map); slot.dirty = false; }
    write(book); applyAll();
  }
  function get(id) { return currentMap()[id] || null; }
  function set(id, patch) {
    const map = currentMap();
    map[id] = Object.assign({ x: 0, y: 0 }, map[id] || {}, patch || {});
    replaceMap(map); return map[id];
  }
  function remove(id) { const map = currentMap(); delete map[id]; replaceMap(map); return clearOverlaid([id], "remove"); }
  // Drop only this browser's copy of an entry the overlay now carries (after a
  // save); the overlay entry stays and keeps applying through the layer.
  function forgetLocal(id) {
    const book = read(); const slot = ensureSlot(book, currentPoint());
    delete slot.saved[id]; delete slot.draft[id]; slot.dirty = !equal(slot.draft, slot.saved);
    write(book); applyAll();
  }
  function resetBreakpoint() { const keys = overlaidKeys(); replaceMap({}); return clearOverlaid(keys, "reset"); }
  function beginDraft() {
    const book = read(); const slot = ensureSlot(book, currentPoint());
    editing = true; slot.draft = clone(slot.saved); slot.dirty = false; write(book); applyAll(); return clone(slot.saved);
  }
  function commitDraft() {
    const book = read(); const slot = ensureSlot(book, currentPoint());
    if (!equal(slot.saved, slot.draft)) {
      slot.history.push({ map: clone(slot.saved), savedAt: slot.updatedAt }); slot.history = slot.history.slice(-20);
      slot.future = []; slot.saved = clone(slot.draft); slot.updatedAt = new Date().toISOString();
    }
    slot.dirty = false; editing = false; write(book); applyAll(); return clone(slot.saved);
  }
  function cancelDraft() {
    const book = read(); const slot = ensureSlot(book, currentPoint());
    slot.draft = clone(slot.saved); slot.dirty = false; editing = false; write(book); applyAll(); return clone(slot.saved);
  }
  function restorePrevious() {
    const book = read(); const slot = ensureSlot(book, currentPoint()); const previous = slot.history.pop();
    if (!previous) return false;
    slot.future.push({ map: clone(slot.saved), savedAt: slot.updatedAt }); slot.future = slot.future.slice(-20);
    slot.saved = clone(previous.map || {}); slot.draft = clone(slot.saved); slot.updatedAt = String(previous.savedAt || "");
    slot.dirty = false; write(book); applyAll(); return true;
  }
  function redoPrevious() {
    const book = read(); const slot = ensureSlot(book, currentPoint()); const next = slot.future.pop();
    if (!next) return false;
    slot.history.push({ map: clone(slot.saved), savedAt: slot.updatedAt }); slot.history = slot.history.slice(-20);
    slot.saved = clone(next.map || {}); slot.draft = clone(slot.saved); slot.updatedAt = String(next.savedAt || "");
    slot.dirty = false; write(book); applyAll(); return true;
  }
  function isDirty() { return Boolean(ensureSlot(read(), currentPoint()).dirty); }
  function savedAt() { return ensureSlot(read(), currentPoint()).updatedAt; }

  function tokens(node) {
    return `${node.dataset.uiPolicy || ""} ${node.dataset.uiConstraints || ""}`
      .toLowerCase().split(/[\s,;]+/).filter(Boolean);
  }
  function numberConstraint(node, name, fallback) {
    const raw = node.dataset.uiConstraints || "";
    const match = raw.match(new RegExp(`${name}\\s*=\\s*(\\d+(?:\\.\\d+)?)`, "i"));
    const direct = node.dataset[name.charAt(0).toLowerCase() + name.slice(1)];
    const value = Number(direct || (match && match[1]));
    return Number.isFinite(value) && value > 0 ? value : fallback;
  }
  function policy(node) {
    const parts = tokens(node);
    const authored = authoredSizes.get(node) || node.getBoundingClientRect();
    const safeMinWidth = Math.min(authored.width || 160, Math.max(120, (authored.width || 160) * 0.4));
    const safeMinHeight = Math.min(authored.height || 72, Math.max(48, (authored.height || 72) * 0.3));
    const protectedNode = parts.includes("protected") || parts.includes("no-edit");
    const explicitMove = parts.includes("move") || parts.includes("layout") || parts.includes("layout-style") || parts.includes("style-only") || parts.includes("content-style") || parts.includes("control");
    const explicitResize = parts.includes("resize") || parts.includes("layout") || parts.includes("layout-style");
    return {
      protected: protectedNode,
      move: !protectedNode && explicitMove && !parts.includes("move=false") && !parts.includes("no-move"),
      resize: !protectedNode && explicitResize && !parts.includes("resize=false") && !parts.includes("resize-deny"),
      minWidth: numberConstraint(node, "minWidth", safeMinWidth), minHeight: numberConstraint(node, "minHeight", safeMinHeight),
      maxWidth: numberConstraint(node, "maxWidth", window.innerWidth), maxHeight: numberConstraint(node, "maxHeight", window.innerHeight),
      containment: parts.includes("contain=parent") || parts.includes("contain-parent") ? "parent" : "viewport",
      collision: parts.includes("collision=avoid") || parts.includes("collision-avoid") ? "avoid" : "allow"
    };
  }
  function rememberBase(node) {
    if (!bases.has(node)) {
      bases.set(node, { translate: node.style.translate, width: node.style.width, height: node.style.height, zIndex: node.style.zIndex, position: node.style.position });
      const rect = node.getBoundingClientRect(); authoredSizes.set(node, { width: rect.width, height: rect.height });
    }
  }
  // Visual properties a Redesign instruction is allowed to set. Geometry
  // stays in x/y/width/height; this covers "make it blue", "bigger text",
  // "less padding". Anything outside the list is dropped rather than
  // guessed at, so a bad model answer can't smuggle in arbitrary CSS.
  const STYLE_PROPS = new Set([
    "color", "background", "backgroundColor", "borderColor", "borderRadius", "borderWidth", "borderStyle",
    "fontSize", "fontWeight", "fontStyle", "letterSpacing", "lineHeight", "textAlign", "textTransform",
    "padding", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "margin", "marginTop", "marginRight", "marginBottom", "marginLeft",
    "gap", "opacity", "boxShadow", "outline", "flexDirection", "justifyContent", "alignItems",
    "gridTemplateColumns", "order", "textDecoration"
  ]);
  function safeStyleValue(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text || text.length > 160) return "";
    // No url()/expression()/@import, and no escaping the declaration.
    if (/url\s*\(|expression\s*\(|@import|[;{}<>]/i.test(text)) return "";
    return text;
  }
  function cleanStyle(value) {
    const out = {};
    Object.entries(value && typeof value === "object" ? value : {}).forEach(([key, raw]) => {
      const prop = String(key).replace(/-([a-z])/g, (_, char) => char.toUpperCase());
      if (!STYLE_PROPS.has(prop)) return;
      const safe = safeStyleValue(raw);
      if (safe) out[prop] = safe;
    });
    return out;
  }
  // Undoing a style must RESTORE what the author wrote, not blank it out.
  // chat.html styles most of its shell inline, so clearing font-size on the
  // welcome heading deleted its authored clamp() and shrank it permanently.
  // Remember each property's prior inline value the first time we touch it.
  //
  // Redesign styles are written with !important. An explicit "make this
  // square" from the user has to beat the stylesheet, and parts of the shell
  // (the .hv-* pills) carry !important rules that otherwise silently win over
  // an inline style — the change would land in the style attribute and never
  // show up on screen.
  const styleBases = new WeakMap();
  function kebab(prop) { return String(prop).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`); }
  function rememberStyle(node, prop) {
    let base = styleBases.get(node);
    if (!base) { base = {}; styleBases.set(node, base); }
    const name = kebab(prop);
    if (!Object.prototype.hasOwnProperty.call(base, prop)) {
      base[prop] = { value: node.style.getPropertyValue(name) || "", priority: node.style.getPropertyPriority(name) || "" };
    }
    return base;
  }
  function writeStyle(node, prop, value) {
    rememberStyle(node, prop);
    node.style.setProperty(kebab(prop), value, "important");
  }
  function restoreStyle(node, prop) {
    const base = styleBases.get(node); const name = kebab(prop);
    const saved = base && Object.prototype.hasOwnProperty.call(base, prop) ? base[prop] : null;
    node.style.removeProperty(name);
    if (saved && saved.value) node.style.setProperty(name, saved.value, saved.priority);
  }
  // Icons are a class swap, not a style: chat_shell.css maps `.ph-<name>` to a
  // literal glyph. The original name is parked on the node so a reset puts the
  // authored icon back rather than leaving whatever was tried last.
  function currentIcon(node) {
    const match = String(node.className || "").match(/\bph-[a-z0-9-]+\b/);
    return match ? match[0] : "";
  }
  function applyIcon(node, item) {
    const wanted = String(item.icon || "").trim();
    if (!/^ph-[a-z0-9-]+$/.test(wanted)) { clearIcon(node); return; }
    const present = currentIcon(node);
    if (!node.dataset.uiIconBase) node.dataset.uiIconBase = present || "(none)";
    if (present === wanted) return;
    if (present) node.classList.remove(present);
    node.classList.add(wanted);
  }
  function clearIcon(node) {
    const base = String(node.dataset.uiIconBase || "");
    if (!base) return;
    const present = currentIcon(node);
    if (present) node.classList.remove(present);
    if (base !== "(none)") node.classList.add(base);
    delete node.dataset.uiIconBase;
  }
  // What the element says. The text nodes are the target, never the children:
  // a button keeps its icon and gets new words. The stock words are kept on the
  // node so a removed record restores them exactly.
  const TEXT_SEP = " |~| ";  // joins the stock text runs; no label carries it
  function textRuns(node) { return Array.from(node.childNodes).filter((child) => child.nodeType === 3); }
  function applyText(node, item) {
    const wanted = String(item.text || "").trim();
    if (!wanted) { clearText(node); return; }
    const runs = textRuns(node);
    if (!("uiTextBase" in node.dataset)) node.dataset.uiTextBase = runs.map((run) => run.nodeValue).join(TEXT_SEP);
    const spoken = runs.filter((run) => String(run.nodeValue || "").trim());
    if (spoken.length === 0) { node.appendChild(document.createTextNode(wanted)); return; }
    runs.forEach((run) => { run.nodeValue = ""; });
    spoken[spoken.length - 1].nodeValue = wanted;
  }
  function clearText(node) {
    if (!("uiTextBase" in node.dataset)) return;
    const stored = String(node.dataset.uiTextBase);
    const base = stored === "" ? [] : stored.split(TEXT_SEP);
    // Every stock run gets its words back, whitespace included; a run this
    // overlay added (the element had no words) is removed again.
    textRuns(node).forEach((run, i) => { if (i < base.length) run.nodeValue = base[i]; else node.removeChild(run); });
    delete node.dataset.uiTextBase;
  }
  function clearStyle(node) {
    String(node.dataset.uiStyled || "").split(",").filter(Boolean).forEach((prop) => restoreStyle(node, prop));
    delete node.dataset.uiStyled;
    if (node.dataset.uiHidden) { restoreStyle(node, "display"); delete node.dataset.uiHidden; }
    clearIcon(node);
    clearText(node);
  }
  function applyStyle(node, item) {
    const style = cleanStyle(item.style);
    const keys = Object.keys(style);
    const previous = String(node.dataset.uiStyled || "").split(",").filter(Boolean);
    previous.filter((prop) => !style[prop]).forEach((prop) => restoreStyle(node, prop));
    keys.forEach((prop) => writeStyle(node, prop, style[prop]));
    if (keys.length) node.dataset.uiStyled = keys.join(","); else delete node.dataset.uiStyled;
    if (item.hidden === true) { writeStyle(node, "display", "none"); node.dataset.uiHidden = "true"; }
    else if (node.dataset.uiHidden) { restoreStyle(node, "display"); delete node.dataset.uiHidden; }
    if (item.icon) applyIcon(node, item); else clearIcon(node);
    if (item.text) applyText(node, item); else clearText(node);
  }
  function applyNode(node, map) {
    rememberBase(node);
    const id = identity(node); const item = id && (map || currentMap())[id]; const base = bases.get(node);
    if (!item) {
      node.style.translate = base.translate; node.style.width = base.width; node.style.height = base.height; node.style.zIndex = base.zIndex; node.style.position = base.position;
      clearStyle(node);
      delete node.dataset.uiLayoutApplied; delete node.dataset.uiLocked; return;
    }
    applyStyle(node, item);
    node.style.translate = `${Number(item.x) || 0}px ${Number(item.y) || 0}px`;
    node.style.width = Number.isFinite(item.width) ? `${item.width}px` : base.width;
    node.style.height = Number.isFinite(item.height) ? `${item.height}px` : base.height;
    node.style.zIndex = Number.isFinite(item.z) ? String(item.z) : base.zIndex;
    node.style.position = Number.isFinite(item.z) && getComputedStyle(node).position === "static" ? "relative" : base.position;
    node.dataset.uiLayoutApplied = "true";
    if (item.locked) node.dataset.uiLocked = "true"; else delete node.dataset.uiLocked;
  }
  // A minted address is "<region id>~~<path inside that region>", produced by
  // the Redesign selector for an element that has no data-ui-id of its own.
  // It lets any element on screen carry a saved style without borrowing its
  // container's identity — and it survives re-renders, which Work does
  // constantly, because the path is resolved fresh on every apply.
  const SYNTH = "~~";
  function resolveSynthetic(key, scope) {
    const cut = key.indexOf(SYNTH);
    if (cut < 0) return null;
    const ownerId = key.slice(0, cut), path = key.slice(cut + SYNTH.length);
    if (!ownerId || !path) return null;
    const owner = Array.from((scope || document).querySelectorAll("[data-ui-id]")).find((node) => identity(node) === ownerId);
    if (!owner) return null;
    try { return owner.querySelector(path); } catch (_) { return null; }
  }
  function applySyntheticNode(node, item, key) {
    rememberBase(node);
    applyStyle(node, item);
    if (Number.isFinite(item.width)) node.style.width = `${item.width}px`;
    if (Number.isFinite(item.height)) node.style.height = `${item.height}px`;
    node.dataset.uiSynth = key;
  }
  function applyAll(root) {
    const scope = root || document; const map = currentMap();
    if (scope instanceof Element && scope.matches("[data-ui-id]")) applyNode(scope, map);
    scope.querySelectorAll("[data-ui-id]").forEach((node) => applyNode(node, map));
    // Drop styling from elements whose minted entry has since been removed,
    // otherwise a reset would leave the last look burned in.
    const container = scope instanceof Element ? scope : document;
    container.querySelectorAll("[data-ui-synth]").forEach((node) => {
      if (map[node.dataset.uiSynth]) return;
      clearStyle(node); node.style.width = ""; node.style.height = ""; delete node.dataset.uiSynth;
    });
    Object.keys(map).forEach((key) => {
      if (key.indexOf(SYNTH) < 0) return;
      const node = resolveSynthetic(key, container);
      if (node) applySyntheticNode(node, map[key], key);
    });
  }
  // Per-element version stack. The slot-level history/future pair is for the
  // editor's undo of a whole draft; this is what lets ONE element be rolled
  // back later, long after other things have been changed around it.
  const MAX_VERSIONS = 12;
  function versionsFor(slot, id) {
    if (!slot.versions || typeof slot.versions !== "object") slot.versions = {};
    if (!Array.isArray(slot.versions[id])) slot.versions[id] = [];
    return slot.versions[id];
  }
  function pushVersion(id) {
    if (!id) return;
    const book = read(); const slot = ensureSlot(book, currentPoint());
    const stack = versionsFor(slot, id);
    const previous = clone((editing ? slot.draft : slot.saved)[id] || null);
    stack.push(previous);
    if (stack.length > MAX_VERSIONS) stack.shift();
    write(book);
  }
  function versionCount(id) {
    const slot = ensureSlot(read(), currentPoint());
    return versionsFor(slot, id).length;
  }
  // Roll ONE element back one step. Returns true when something moved, so the
  // caller can report honestly instead of claiming a revert that did nothing.
  function revert(id) {
    if (!id) return false;
    const book = read(); const slot = ensureSlot(book, currentPoint());
    const stack = versionsFor(slot, id);
    // An entry the overlay carries is reverted THERE (a clear record); the
    // local stack alone cannot move it, and saying it did would be a lie.
    if (Object.prototype.hasOwnProperty.call(overlayEntries(), id)) { stack.length = 0; write(book); clearOverlaid([id], "revert"); return true; }
    if (!stack.length) return false;
    const previous = stack.pop();
    const target = editing ? slot.draft : slot.saved;
    const before = JSON.stringify(target[id] || null);
    if (previous == null) delete target[id]; else target[id] = clone(previous);
    if (!editing) slot.draft = clone(slot.saved);
    slot.updatedAt = new Date().toISOString();
    write(book);
    applyAll();
    return before !== JSON.stringify(previous);
  }
  function exportBook() { return clone(read()); }
  function validate(root) {
    const seen = new Set(); const duplicates = [];
    (root || document).querySelectorAll("[data-ui-id]").forEach((node) => {
      const id = identity(node); if (!id || seen.has(id)) duplicates.push(id || "(empty)"); seen.add(id);
    });
    return { valid: duplicates.length === 0, duplicates };
  }

  window.ThomasUiLayout = { BREAKPOINTS, applyAll, applyNode, clearOverlaid, forgetLocal, orphans, overlaidKeys, refreshOverlay, beginDraft, breakpoint, cancelDraft, cleanStyle, commitDraft, currentMap, currentPoint, exportBook, get, identity, isDirty, policy, pushVersion, redoPrevious, remove, replaceMap, resetBreakpoint, restorePrevious, revert, savedAt, set, validate, versionCount, workspace };
  const start = () => {
    applyAll(); let applyFrame = 0;
    const queueApply = () => { if (applyFrame) return; applyFrame = requestAnimationFrame(() => { applyFrame = 0; applyAll(); }); };
    const observer = new MutationObserver((records) => { if (records.some((record) => record.addedNodes.length > 0)) queueApply(); });
    observer.observe(document.documentElement, { childList: true, subtree: true }); window.addEventListener("resize", queueApply);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
}());
