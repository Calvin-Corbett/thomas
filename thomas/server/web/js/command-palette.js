/* ============================================================
   Thomas Command Palette
   ============================================================
   Ctrl/Cmd+K fuzzy-search overlay for quick actions.
   ============================================================ */

import { getState, setState, createChat, getChatsArray, setActiveChat } from './store.js';
import { saveChat, saveSetting } from './db.js';
import { el, icon, modKey, escapeHtml, applyTheme, truncate } from './utils.js';
import { focusComposer, setComposerText } from './composer.js';
import { scrollToMessage } from './chat.js';
import { updateCodeTheme } from './chat.js';
import { createModal, createButton, showToast } from './components.js';
import { openSetupWizard } from './setup-wizard.js';

let _isOpen = false;
let _selectedIndex = 0;
let _filteredItems = [];
let _backdrop = null;

const ACTIONS = [
  { id: 'new-chat', label: 'New Chat', icon: 'plus', shortcut: `${modKey()}+N`, action: () => { const c = createChat(); saveChat(c); } },
  { id: 'toggle-sidebar', label: 'Toggle Sidebar', icon: 'menu', shortcut: `${modKey()}+B`, action: toggleSidebar },
  { id: 'toggle-inspector', label: 'Toggle Inspector', icon: 'inspector', shortcut: `${modKey()}+I`, action: toggleInspector },
  { id: 'toggle-theme', label: 'Toggle Dark Mode', icon: 'moon', shortcut: `${modKey()}+Shift+L`, action: toggleTheme },
  { id: 'layout-zen', label: 'Layout: Zen (Hide Sidebar + Inspector)', icon: 'inspector', action: setZenLayout },
  { id: 'layout-reset-widths', label: 'Layout: Reset Pane Widths', icon: 'menu', action: resetPaneWidths },
  { id: 'select-messages', label: 'Select Messages', icon: 'check', action: toggleSelectionMode },
  { id: 'bookmarks', label: 'Bookmarks', icon: 'bookmark', action: openBookmarks },
  { id: 'stop-speaking', label: 'Stop Speaking', icon: 'speaker', action: stopSpeaking },
  { id: 'open-settings', label: 'Settings', icon: 'settings', action: () => { closePalette(); import('./settings.js').then(mod => mod.openSettings('appearance')).catch(() => { setState('ui', { settingsOpen: true, settingsTab: 'appearance' }); }); } },
  { id: 'open-models-providers', label: 'Models & Providers', icon: 'models', action: () => { closePalette(); import('./settings.js').then(mod => mod.openSettings('models')).catch(() => { setState('ui', { settingsOpen: true, settingsTab: 'models' }); }); } },
  { id: 'setup-wizard', label: 'Setup Wizard (Connect Providers)', icon: 'models', action: () => { closePalette(); openSetupWizard(); } },
  { id: 'focus-composer', label: 'Focus Message Input', icon: 'edit', shortcut: '/', action: () => focusComposer() },
];

export function initCommandPalette() {
  // Keyboard shortcut listener is registered in app.js
}

export function openPalette() {
  if (_isOpen) return;
  _isOpen = true;
  _selectedIndex = 0;

  // Build palette
  _backdrop = el('div', { className: 'palette-backdrop' });
  const palette = el('div', { className: 'palette' });

  const input = el('input', {
    className: 'palette-input',
    type: 'text',
    placeholder: 'Type a command or search chats...',
  });

  const results = el('div', { className: 'palette-results' });

  palette.appendChild(input);
  palette.appendChild(results);
  _backdrop.appendChild(palette);

  // Close on backdrop click
  _backdrop.addEventListener('click', (e) => {
    if (e.target === _backdrop) closePalette();
  });

  document.body.appendChild(_backdrop);

  function getItems(query = '') {
    const q = query.toLowerCase().trim();
    const items = [];

    // Actions
    for (const action of ACTIONS) {
      if (!q || action.label.toLowerCase().includes(q)) {
        items.push({ type: 'action', ...action });
      }
    }

    // Chats (search)
    if (q) {
      const chats = getChatsArray();
      for (const chat of chats.slice(0, 5)) {
        if (chat.title.toLowerCase().includes(q)) {
          items.push({
            type: 'chat',
            id: `chat-${chat.id}`,
            label: chat.title,
            icon: 'edit',
            action: () => setActiveChat(chat.id),
          });
        }
      }

      // Message search (best-effort, bounded)
      let found = 0;
      for (const chat of chats) {
        if (found >= 8) break;
        for (const msg of (chat.messages || [])) {
          if (found >= 8) break;
          if (typeof msg.content !== 'string') continue;
          const hay = msg.content.toLowerCase();
          const idx = hay.indexOf(q);
          if (idx === -1) continue;

          const start = Math.max(0, idx - 40);
          const end = Math.min(msg.content.length, idx + q.length + 60);
          const snippetRaw = msg.content.slice(start, end).replace(/\\s+/g, ' ').trim();
          items.push({
            type: 'message',
            id: `msg-${chat.id}-${msg.id}`,
            label: chat.title,
            subtitle: (msg.role === 'user' ? 'You: ' : 'Thomas: ') + snippetRaw,
            icon: 'search',
            action: () => {
              setActiveChat(chat.id);
              // Wait for DOM to render the messages.
              setTimeout(() => scrollToMessage(msg.id), 60);
            },
          });
          found++;
        }
      }

      // Prompt library (best-effort)
      const prompts = Array.isArray(getState().settings.promptLibrary) ? getState().settings.promptLibrary : [];
      let pFound = 0;
      for (const p of prompts) {
        if (pFound >= 6) break;
        const title = String(p.title || '');
        const text = String(p.text || '');
        const hay = `${title} ${text}`.toLowerCase();
        if (!hay.includes(q)) continue;
        const snippet = text.replace(/\s+/g, ' ').trim().slice(0, 80);
        items.push({
          type: 'prompt',
          id: `prompt-${p.id}`,
          label: `Prompt: ${title || 'Untitled'}`,
          subtitle: snippet,
          icon: 'command',
          action: () => {
            setComposerText(text);
            focusComposer();
          },
        });
        pFound++;
      }
    }

    return items;
  }

  function render(query = '') {
    _filteredItems = getItems(query);
    _selectedIndex = Math.min(_selectedIndex, Math.max(0, _filteredItems.length - 1));
    results.innerHTML = '';

    if (_filteredItems.length === 0) {
      results.appendChild(el('div', { style: {
        padding: 'var(--space-4) var(--space-5)',
        color: 'var(--text-muted)',
        fontSize: 'var(--text-sm)',
      }}, 'No results'));
      return;
    }

    for (let i = 0; i < _filteredItems.length; i++) {
      const item = _filteredItems[i];
      const row = el('div', {
        className: `palette-item ${i === _selectedIndex ? 'selected' : ''}`,
      });

      if (item.icon) {
        row.appendChild(el('span', { className: 'palette-item-icon', innerHTML: getIconHtml(item.icon) }));
      }

      const textWrap = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', flex: '1', minWidth: '0' } });
      textWrap.appendChild(el('span', { className: 'palette-item-label' }, item.label));
      if (item.subtitle) {
        textWrap.appendChild(el('span', { style: { fontSize: '11px', color: 'var(--text-muted)' }, innerHTML: escapeHtml(item.subtitle) }));
      }
      row.appendChild(textWrap);

      if (item.shortcut) {
        row.appendChild(el('span', { className: 'palette-item-shortcut' }, item.shortcut));
      }

      if (item.type === 'chat') {
        row.appendChild(el('span', { className: 'chip', style: { fontSize: '10px' } }, 'chat'));
      } else if (item.type === 'message') {
        row.appendChild(el('span', { className: 'chip', style: { fontSize: '10px' } }, 'msg'));
      }

      row.addEventListener('click', () => {
        closePalette();
        item.action?.();
      });

      row.addEventListener('mouseenter', () => {
        _selectedIndex = i;
        render(input.value);
      });

      results.appendChild(row);
    }
  }

  input.addEventListener('input', () => {
    _selectedIndex = 0;
    render(input.value);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closePalette();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      _selectedIndex = Math.min(_selectedIndex + 1, _filteredItems.length - 1);
      render(input.value);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _selectedIndex = Math.max(_selectedIndex - 1, 0);
      render(input.value);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const item = _filteredItems[_selectedIndex];
      if (item) {
        closePalette();
        item.action?.();
      }
    }
  });

  render();
  requestAnimationFrame(() => input.focus());
}

export function closePalette() {
  _isOpen = false;
  _backdrop?.remove();
  _backdrop = null;
}

export function isPaletteOpen() {
  return _isOpen;
}

function getIconHtml(name) {
  const tmpSpan = icon(name);
  return tmpSpan.innerHTML;
}

// Re-usable toggle functions
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

function toggleInspector() {
  const app = document.getElementById('app');
  if (!app) return;
  const next = !app.classList.contains('inspector-open');
  app.classList.toggle('inspector-open', next);
  setState('settings', { showInspector: next });
  saveSetting('showInspector', next);
}

function resolvedIsDark(theme) {
  if (theme === 'dark') return true;
  if (theme === 'light') return false;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function toggleTheme() {
  const state = getState();
  const current = state.settings.theme;
  const next = current === 'dark' ? 'light' : 'dark';
  setState('settings', { theme: next });
  saveSetting('theme', next);
  applyTheme(next);
  updateCodeTheme(resolvedIsDark(next));
}

function setZenLayout() {
  const app = document.getElementById('app');
  if (!app) return;
  // Desktop: collapse sidebar + close inspector
  if (window.innerWidth > 1024) {
    app.classList.add('sidebar-collapsed');
    setState('settings', { sidebarCollapsed: true });
    saveSetting('sidebarCollapsed', true);
  } else {
    app.classList.remove('sidebar-open');
  }
  app.classList.remove('inspector-open');
  setState('settings', { showInspector: false });
  saveSetting('showInspector', false);
}

function resetPaneWidths() {
  setState('settings', { sidebarWidth: 280, inspectorWidth: 380 });
  saveSetting('sidebarWidth', 280);
  saveSetting('inspectorWidth', 380);
  document.documentElement.style.setProperty('--sidebar-width', '280px');
  document.documentElement.style.setProperty('--inspector-width', '380px');
  showToast('Pane widths reset', 'success');
}

function toggleSelectionMode() {
  const ui = getState().ui;
  const next = !ui.selectionMode;
  setState('ui', { selectionMode: next, selectedMessageIds: [] });
}

function stopSpeaking() {
  try { window.speechSynthesis?.cancel?.(); } catch { /* ignore */ }
}

function openBookmarks() {
  const chats = getChatsArray();
  const bookmarks = [];
  for (const c of chats) {
    for (const m of (c.messages || [])) {
      if (!m.bookmarked) continue;
      const text = typeof m.content === 'string' ? m.content : '';
      bookmarks.push({
        chatId: c.id,
        chatTitle: c.title || 'Chat',
        msgId: m.id,
        role: m.role,
        snippet: truncate(text.replace(/\\s+/g, ' ').trim(), 110),
      });
    }
  }

  const body = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } });
  if (bookmarks.length === 0) {
    body.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: 'var(--text-sm)' } }, 'No bookmarks yet.'));
  } else {
    for (const b of bookmarks) {
      const row = el('button', { className: 'card card-clickable', type: 'button', style: { textAlign: 'left', padding: 'var(--space-3)' } });
      row.appendChild(el('div', { style: { fontWeight: 'var(--font-semibold)', fontSize: 'var(--text-sm)' } }, b.chatTitle));
      row.appendChild(el('div', { style: { color: 'var(--text-muted)', fontSize: '11px', marginTop: '4px' } }, `${b.role === 'user' ? 'You' : 'Thomas'}: ${b.snippet}`));
      row.addEventListener('click', () => {
        modal.close();
        setActiveChat(b.chatId);
        setTimeout(() => scrollToMessage(b.msgId), 60);
      });
      body.appendChild(row);
    }
  }

  const modal = createModal({
    title: 'Bookmarks',
    body,
    footer: [
      createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() }),
    ],
  });
  document.getElementById('modals')?.appendChild(modal.backdrop);
}

export { toggleSidebar, toggleInspector, toggleTheme };
