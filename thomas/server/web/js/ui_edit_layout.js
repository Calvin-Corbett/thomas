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
  function identity(node) {
    if (!(node instanceof Element)) return "";
    const id = String(node.dataset.uiId || "").trim();
    const key = String(node.dataset.uiInstanceKey || "").trim();
    return id && key ? `${id}::${key}` : id;
  }
  function currentMap() {
    const slot = ensureSlot(read(), currentPoint());
    return clone(editing ? slot.draft : slot.saved);
  }
  function replaceMap(next) {
    const book = read(); const slot = ensureSlot(book, currentPoint()); const map = clone(next || {});
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
  function remove(id) { const map = currentMap(); delete map[id]; replaceMap(map); }
  function resetBreakpoint() { replaceMap({}); }
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
  function applyNode(node, map) {
    rememberBase(node);
    const id = identity(node); const item = id && (map || currentMap())[id]; const base = bases.get(node);
    if (!item) {
      node.style.translate = base.translate; node.style.width = base.width; node.style.height = base.height; node.style.zIndex = base.zIndex; node.style.position = base.position;
      delete node.dataset.uiLayoutApplied; delete node.dataset.uiLocked; return;
    }
    node.style.translate = `${Number(item.x) || 0}px ${Number(item.y) || 0}px`;
    node.style.width = Number.isFinite(item.width) ? `${item.width}px` : base.width;
    node.style.height = Number.isFinite(item.height) ? `${item.height}px` : base.height;
    node.style.zIndex = Number.isFinite(item.z) ? String(item.z) : base.zIndex;
    node.style.position = Number.isFinite(item.z) && getComputedStyle(node).position === "static" ? "relative" : base.position;
    node.dataset.uiLayoutApplied = "true";
    if (item.locked) node.dataset.uiLocked = "true"; else delete node.dataset.uiLocked;
  }
  function applyAll(root) {
    const scope = root || document; const map = currentMap();
    if (scope instanceof Element && scope.matches("[data-ui-id]")) applyNode(scope, map);
    scope.querySelectorAll("[data-ui-id]").forEach((node) => applyNode(node, map));
  }
  function exportBook() { return clone(read()); }
  function validate(root) {
    const seen = new Set(); const duplicates = [];
    (root || document).querySelectorAll("[data-ui-id]").forEach((node) => {
      const id = identity(node); if (!id || seen.has(id)) duplicates.push(id || "(empty)"); seen.add(id);
    });
    return { valid: duplicates.length === 0, duplicates };
  }

  window.ThomasUiLayout = { BREAKPOINTS, applyAll, applyNode, beginDraft, breakpoint, cancelDraft, commitDraft, currentMap, currentPoint, exportBook, get, identity, isDirty, policy, redoPrevious, remove, replaceMap, resetBreakpoint, restorePrevious, savedAt, set, validate, workspace };
  const start = () => {
    applyAll(); let applyFrame = 0;
    const queueApply = () => { if (applyFrame) return; applyFrame = requestAnimationFrame(() => { applyFrame = 0; applyAll(); }); };
    const observer = new MutationObserver((records) => { if (records.some((record) => record.addedNodes.length > 0)) queueApply(); });
    observer.observe(document.documentElement, { childList: true, subtree: true }); window.addEventListener("resize", queueApply);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
}());
