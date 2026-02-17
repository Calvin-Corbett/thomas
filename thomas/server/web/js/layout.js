/* ============================================================
   Thomas Layout (Resizable Panes + Presets)
   ============================================================
   - Draggable resize handles for sidebar and inspector (desktop).
   - Persists widths in settings (IndexedDB).
   - Applies saved collapsed state for the sidebar.
   ============================================================ */

import { getState, setState } from './store.js';
import { saveSetting } from './db.js';

const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 520;
const INSPECTOR_MIN = 300;
const INSPECTOR_MAX = 720;

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function setPxVar(name, px) {
  document.documentElement.style.setProperty(name, `${Math.round(px)}px`);
}

export function applyPaneWidths() {
  const s = getState().settings;
  if (typeof s.sidebarWidth === 'number') setPxVar('--sidebar-width', s.sidebarWidth);
  if (typeof s.inspectorWidth === 'number') setPxVar('--inspector-width', s.inspectorWidth);
}

function ensureHandle(container, kind) {
  const id = kind === 'sidebar' ? 'sidebarResizeHandle' : 'inspectorResizeHandle';
  let h = document.getElementById(id);
  if (h) return h;

  h = document.createElement('div');
  h.id = id;
  h.className = `resize-handle resize-handle-${kind}`;
  container.appendChild(h);
  return h;
}

function persistWidths(kind, px) {
  if (kind === 'sidebar') {
    setState('settings', { sidebarWidth: px });
    saveSetting('sidebarWidth', px);
    setPxVar('--sidebar-width', px);
  } else {
    setState('settings', { inspectorWidth: px });
    saveSetting('inspectorWidth', px);
    setPxVar('--inspector-width', px);
  }
}

function startDrag(e, kind) {
  if (e.button !== 0) return;
  e.preventDefault();

  const app = document.getElementById('app');
  if (app && kind === 'sidebar' && app.classList.contains('sidebar-collapsed')) return;
  if (app && kind === 'inspector' && !app.classList.contains('inspector-open')) return;
  if (window.innerWidth <= 1024) return; // handles are desktop-only

  document.body.classList.add('resizing');
  document.body.style.cursor = 'col-resize';

  function onMove(ev) {
    if (kind === 'sidebar') {
      const next = clamp(ev.clientX, SIDEBAR_MIN, SIDEBAR_MAX);
      setPxVar('--sidebar-width', next);
    } else {
      const next = clamp(window.innerWidth - ev.clientX, INSPECTOR_MIN, INSPECTOR_MAX);
      setPxVar('--inspector-width', next);
    }
  }

  function onUp(ev) {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.body.classList.remove('resizing');
    document.body.style.cursor = '';

    if (kind === 'sidebar') {
      const next = clamp(ev.clientX, SIDEBAR_MIN, SIDEBAR_MAX);
      persistWidths('sidebar', next);
    } else {
      const next = clamp(window.innerWidth - ev.clientX, INSPECTOR_MIN, INSPECTOR_MAX);
      persistWidths('inspector', next);
    }
  }

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

export function initLayout() {
  applyPaneWidths();

  const app = document.getElementById('app');
  if (app) {
    app.classList.toggle('sidebar-collapsed', !!getState().settings.sidebarCollapsed);
  }

  const sidebar = document.getElementById('sidebar');
  const inspector = document.getElementById('inspector');

  if (sidebar) {
    const h = ensureHandle(sidebar, 'sidebar');
    h.addEventListener('mousedown', (e) => startDrag(e, 'sidebar'));
  }
  if (inspector) {
    const h = ensureHandle(inspector, 'inspector');
    h.addEventListener('mousedown', (e) => startDrag(e, 'inspector'));
  }
}

