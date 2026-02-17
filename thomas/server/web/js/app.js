/* ============================================================
   Thomas Web UI Bootstrap
   ============================================================
   Initializes state (models, chats, settings) and wires the
   top-level UI interactions (header toggles, shortcuts).
   ============================================================ */

import { getState, setState, createChat, getActiveChat, updateChat, subscribe } from './store.js';
import { fetchModels } from './api.js';
import { loadChats, loadSettings, saveChat, saveSetting } from './db.js';
import { applyTheme, icon, isMac } from './utils.js';
import { initSidebar } from './sidebar.js';
import { initChat, updateCodeTheme } from './chat.js';
import { initComposer } from './composer.js';
import { initInspector } from './inspector.js';
import { initModelsUnified } from './models-unified.js';
import { initSettings } from './settings.js';
import { initLayout } from './layout.js';
import { openPalette, closePalette, isPaletteOpen } from './command-palette.js';
import { createModal, showToast } from './components.js';
import { initSetupWizard } from './setup-wizard.js';

function resolvedIsDark(theme) {
  if (theme === 'dark') return true;
  if (theme === 'light') return false;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function setInspectorOpen(open) {
  const app = document.getElementById('app');
  if (app) app.classList.toggle('inspector-open', !!open);
  setState('settings', { showInspector: !!open });
  saveSetting('showInspector', !!open);
}

function toggleSidebar() {
  const app = document.getElementById('app');
  if (!app) return;
  if (window.innerWidth <= 1024) {
    app.classList.toggle('sidebar-open');
  } else {
    const next = !app.classList.contains('sidebar-collapsed');
    app.classList.toggle('sidebar-collapsed', next);
    setState('settings', { sidebarCollapsed: next });
    saveSetting('sidebarCollapsed', next);
  }
}

function wireHeader() {
  const sidebarToggle = document.getElementById('sidebarToggle');
  if (sidebarToggle) {
    sidebarToggle.replaceChildren(icon('menu'));
    sidebarToggle.addEventListener('click', toggleSidebar);
  }

  const inspectorToggle = document.getElementById('inspectorToggle');
  if (inspectorToggle) {
    inspectorToggle.replaceChildren(icon('inspector'));
    inspectorToggle.addEventListener('click', () => {
      const app = document.getElementById('app');
      const open = !(app && app.classList.contains('inspector-open'));
      setInspectorOpen(open);
    });
  }

  // Mode segmented control
  const modeToggle = document.getElementById('modeToggle');
  if (modeToggle) {
    const syncModeButtons = () => {
      const active = String(getState().mode || 'auto').toLowerCase();
      modeToggle.querySelectorAll('.segmented-btn').forEach((b) => {
        b.classList.toggle('active', String(b.dataset.mode || '').toLowerCase() === active);
      });
    };

    modeToggle.querySelectorAll('.segmented-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = String(btn.dataset.mode || '').toLowerCase();
        if (!mode) return;
        setState('mode', mode);
        syncModeButtons();
      });
    });

    syncModeButtons();
  }

  // Help/About modal
  document.getElementById('helpBtn')?.addEventListener('click', () => {
    const body = document.createElement('div');
    body.style.display = 'flex';
    body.style.flexDirection = 'column';
    body.style.gap = '12px';
    body.innerHTML = `
      <div style="font-size: var(--text-sm); color: var(--text-secondary);">
        Thomas is a local-first AI assistant and orchestrator. This UI supports docs, images, and browser speech-to-text.
      </div>
      <div style="font-size: var(--text-xs); color: var(--text-muted); line-height: 1.6;">
        Shortcuts:<br/>
        ${isMac() ? 'Cmd' : 'Ctrl'}+K: Command palette<br/>
        ${isMac() ? 'Cmd' : 'Ctrl'}+B: Toggle sidebar<br/>
        ${isMac() ? 'Cmd' : 'Ctrl'}+I: Toggle inspector
      </div>
    `;

    const modal = createModal({ title: 'Help & About', body });
    document.getElementById('modals')?.appendChild(modal.backdrop);
  });
}

function wireGlobalShortcuts() {
  document.addEventListener('keydown', (e) => {
    const key = (e.key || '').toLowerCase();
    const meta = e.metaKey;
    const ctrl = e.ctrlKey;

    if ((meta || ctrl) && key === 'k') {
      e.preventDefault();
      if (isPaletteOpen()) closePalette();
      else openPalette();
      return;
    }

    if ((meta || ctrl) && key === 'b') {
      e.preventDefault();
      toggleSidebar();
      return;
    }

    if ((meta || ctrl) && key === 'i') {
      e.preventDefault();
      const app = document.getElementById('app');
      const open = !(app && app.classList.contains('inspector-open'));
      setInspectorOpen(open);
      return;
    }
  });
}

function wireChatTitle() {
  const titleEl = document.getElementById('chatTitle');
  if (!titleEl) return;

  function syncTitle() {
    const chat = getActiveChat();
    if (!chat) return;
    if (document.activeElement === titleEl) return;
    titleEl.textContent = chat.title || 'New Chat';
  }

  subscribe('activeChatId', syncTitle);
  subscribe('chats', syncTitle);
  syncTitle();

  titleEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      titleEl.blur();
    }
  });

  titleEl.addEventListener('blur', () => {
    const chat = getActiveChat();
    if (!chat) return;
    const next = (titleEl.textContent || '').trim();
    if (!next) {
      titleEl.textContent = chat.title || 'New Chat';
      return;
    }
    if (next === chat.title) return;
    updateChat(chat.id, { title: next });
    const updated = getState().chats.get(chat.id);
    if (updated) saveChat(updated);
  });
}

async function loadInitialState() {
  // Settings
  const loadedSettings = await loadSettings();
  if (loadedSettings && typeof loadedSettings === 'object') {
    setState('settings', loadedSettings);
  }
  applyTheme(getState().settings.theme);
  updateCodeTheme(resolvedIsDark(getState().settings.theme));

  // React to system theme changes if using system theme
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', () => {
      const theme = getState().settings.theme;
      if (theme !== 'system') return;
      applyTheme(theme);
      updateCodeTheme(resolvedIsDark(theme));
    });
  } catch { /* ignore */ }

  // Chats
  const loadedChats = await loadChats();
  if (Array.isArray(loadedChats) && loadedChats.length > 0) {
    const map = new Map();
    for (const c of loadedChats) {
      if (c && c.id) {
        c.messages = Array.isArray(c.messages) ? c.messages : [];
        map.set(c.id, c);
      }
    }
    if (map.size > 0) {
      setState('chats', map);
      // Pick most recently updated
      const sorted = Array.from(map.values()).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
      setState('activeChatId', sorted[0].id);
    }
  }

  if (!getState().activeChatId) {
    const chat = createChat();
    saveChat(chat);
  }

  // Apply inspector setting
  if (getState().settings.showInspector) {
    document.getElementById('app')?.classList.add('inspector-open');
  }
  // Apply sidebar collapsed setting (desktop only)
  if (getState().settings.sidebarCollapsed && window.innerWidth > 1024) {
    document.getElementById('app')?.classList.add('sidebar-collapsed');
  }
}

async function loadModels() {
  try {
    const data = await fetchModels();
    setState('models', { profiles: data.profiles || [], defaultProfile: data.default || null });

    if (!getState().activeProfile) {
      const preferred = getState().settings.preferredProfile;
      const names = new Set((data.profiles || []).map(p => p.name));
      if (preferred && names.has(preferred)) {
        setState('activeProfile', preferred);
      } else {
        const defaultProfile = data.default || data.profiles?.[0]?.name || 'local';
        setState('activeProfile', defaultProfile);
      }
    }
  } catch (e) {
    showToast(`Failed to load models: ${e.message || String(e)}`, 'error');
  }
}

async function main() {
  wireHeader();
  wireGlobalShortcuts();

  await loadInitialState();
  initLayout();
  await loadModels();

  // Persist last-used profile so restarts feel seamless.
  subscribe('activeProfile', () => {
    const p = getState().activeProfile;
    if (p) saveSetting('preferredProfile', p);
  });

  // Module init order matters a bit (state should be ready first)
  initSidebar();
  initChat();
  initComposer();
  initInspector();
  initSettings();
  wireChatTitle();
  await initModelsUnified();

  // Setup wizard (first-run or on-demand)
  initSetupWizard();

  // First-run nudge (only if setup wizard didn't show)
  const chat = getActiveChat();
  if (chat && (!Array.isArray(chat.messages) || chat.messages.length === 0)) {
    setTimeout(() => {
      if (!getState().settings.setupCompleted) return; // wizard is showing instead
      showToast('Tip: Ctrl/Cmd+K opens the command palette.', 'info');
    }, 1500);
  }

  // Boot watchdog flag (see index.html)
  try { window.__THOMAS_UI_BOOTED = true; } catch { /* ignore */ }
}

main().catch((e) => {
  console.error('[app] bootstrap failed:', e);
  showToast(`Startup error: ${e.message || String(e)}`, 'error');
});
