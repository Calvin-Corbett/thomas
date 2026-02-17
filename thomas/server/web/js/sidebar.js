/* ============================================================
   Thomas Sidebar
   ============================================================
   Left panel: chat list, search, new/rename/delete, projects.
   ============================================================ */

import { getState, subscribe, createChat, setActiveChat, deleteChat, updateChat, getChatsArray } from './store.js';
import { saveChat, deleteChatDB } from './db.js';
import { el, icon, formatRelativeTime, truncate, debounce } from './utils.js';
import { createContextMenu } from './components.js';
import { openSwarmInspector } from './swarm.js';

let _chatListEl = null;
let _searchInput = null;
let _searchQuery = '';

export function initSidebar() {
  _chatListEl = document.getElementById('chatList');
  _searchInput = document.getElementById('chatSearchInput');

  // New chat buttons
  const newBtn = document.getElementById('newChatBtn');
  if (newBtn) {
    newBtn.replaceChildren(icon('plus'));
    newBtn.addEventListener('click', handleNewChat);
  }
  document.getElementById('newChatBtnFull')?.addEventListener('click', handleNewChat);

  // Search
  if (_searchInput) {
    _searchInput.addEventListener('input', debounce((e) => {
      _searchQuery = e.target.value.trim().toLowerCase();
      renderChatList();
    }, 200));
  }

  // Projects toggle
  const projectsToggle = document.getElementById('projectsToggle');
  const projectsContent = document.getElementById('projectsContent');
  if (projectsToggle && projectsContent) {
    projectsToggle.addEventListener('click', () => {
      const visible = projectsContent.style.display !== 'none';
      projectsContent.style.display = visible ? 'none' : 'block';
      const arrow = projectsToggle.querySelector('span');
      if (arrow) arrow.textContent = visible ? '\u25B8' : '\u25BE';
    });
  }

  // Agents toggle + actions
  const agentsToggle = document.getElementById('agentsToggle');
  const agentsContent = document.getElementById('agentsContent');
  if (agentsToggle && agentsContent) {
    agentsToggle.addEventListener('click', () => {
      const visible = agentsContent.style.display !== 'none';
      agentsContent.style.display = visible ? 'none' : 'block';
      const arrow = agentsToggle.querySelector('span');
      if (arrow) arrow.textContent = visible ? '\u25B8' : '\u25BE';
    });
  }
  document.getElementById('openSwarmBoardBtn')?.addEventListener('click', () => {
    openSwarmInspector();
    if (window.innerWidth <= 1024) {
      document.getElementById('app')?.classList.remove('sidebar-open');
    }
  });

  // Footer button icons
  const settingsIcon = document.getElementById('settingsBtn')?.querySelector('.icon');
  if (settingsIcon) settingsIcon.replaceWith(icon('settings'));
  const helpIcon = document.getElementById('helpBtn')?.querySelector('.icon');
  if (helpIcon) helpIcon.replaceWith(icon('help'));

  // Sidebar overlay close (mobile)
  document.getElementById('sidebarOverlay')?.addEventListener('click', () => {
    document.getElementById('app')?.classList.remove('sidebar-open');
  });

  // Subscribe to state changes
  subscribe('chats', renderChatList);
  subscribe('activeChatId', renderChatList);

  renderChatList();
}

function handleNewChat() {
  const chat = createChat();
  saveChat(chat);
  if (window.innerWidth <= 1024) {
    document.getElementById('app')?.classList.remove('sidebar-open');
  }
}

function renderChatList() {
  if (!_chatListEl) return;

  const state = getState();
  let chats = getChatsArray();

  if (_searchQuery) {
    chats = chats.filter(c =>
      c.title.toLowerCase().includes(_searchQuery) ||
      c.messages.some(m => typeof m.content === 'string' && m.content.toLowerCase().includes(_searchQuery))
    );
  }

  _chatListEl.innerHTML = '';

  if (chats.length === 0) {
    const empty = el('div', { style: { padding: '24px 16px', textAlign: 'center' } });
    empty.innerHTML = `<div style="color: var(--sidebar-muted); font-size: var(--text-sm);">
      ${_searchQuery ? 'No matching chats' : 'No chats yet'}
    </div>`;
    _chatListEl.appendChild(empty);
    return;
  }

  for (const chat of chats) {
    const isActive = chat.id === state.activeChatId;
    const lastMsg = chat.messages[chat.messages.length - 1];
    const preview = lastMsg ? truncate(typeof lastMsg.content === 'string' ? lastMsg.content : '(attachment)', 40) : '';

    const item = el('div', {
      className: `chat-item${isActive ? ' active' : ''}`,
      role: 'option',
      'aria-selected': isActive ? 'true' : 'false',
      dataset: { chatId: chat.id },
    });

    if (chat.pinned) {
      item.appendChild(el('span', { className: 'chat-item-pin' }, '\uD83D\uDCCC'));
    }

    const content = el('div', { className: 'chat-item-content' });
    content.appendChild(el('div', { className: 'chat-item-title' }, truncate(chat.title, 30)));
    if (preview) {
      content.appendChild(el('div', { className: 'chat-item-preview' }, preview));
    }
    item.appendChild(content);

    item.appendChild(el('span', { className: 'chat-item-time' }, formatRelativeTime(chat.updatedAt)));

    const menuBtn = el('button', {
      className: 'btn-icon chat-item-menu',
      type: 'button',
      'aria-label': 'Chat options',
    });
    menuBtn.appendChild(icon('dots'));
    menuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      showChatContextMenu(chat, e.clientX, e.clientY);
    });
    item.appendChild(menuBtn);

    item.addEventListener('click', () => {
      setActiveChat(chat.id);
      if (window.innerWidth <= 1024) {
        document.getElementById('app')?.classList.remove('sidebar-open');
      }
    });

    item.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      showChatContextMenu(chat, e.clientX, e.clientY);
    });

    _chatListEl.appendChild(item);
  }
}

function showChatContextMenu(chat, x, y) {
  createContextMenu({
    x, y,
    items: [
      { label: 'Rename', icon: 'edit', onClick: () => renameChat(chat) },
      { label: chat.pinned ? 'Unpin' : 'Pin', icon: 'pin', onClick: () => {
        updateChat(chat.id, { pinned: !chat.pinned });
        saveChat(getState().chats.get(chat.id));
      }},
      { label: 'Export', icon: 'download', onClick: () => exportChat(chat) },
      { separator: true },
      { label: 'Delete', icon: 'trash', danger: true, onClick: () => {
        if (confirm(`Delete "${truncate(chat.title, 30)}"?`)) {
          deleteChat(chat.id);
          deleteChatDB(chat.id);
        }
      }},
    ],
  });
}

function renameChat(chat) {
  const newTitle = prompt('Rename chat:', chat.title);
  if (newTitle && newTitle.trim()) {
    updateChat(chat.id, { title: newTitle.trim() });
    saveChat(getState().chats.get(chat.id));
  }
}

function exportChat(chat) {
  const data = JSON.stringify(chat, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `thomas-chat-${chat.id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
