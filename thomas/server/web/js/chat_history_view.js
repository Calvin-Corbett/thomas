/* Chat history view. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Sidebar lists ----------
    function fmtChatDate(ms) {
      const n = Number(ms); if (!n) return '';
      const d = new Date(n), now = new Date();
      if (isNaN(d.getTime())) return '';
      if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      const y = new Date(now); y.setDate(now.getDate() - 1);
      if (d.toDateString() === y.toDateString()) return 'Yesterday';
      const opts = d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' };
      return d.toLocaleDateString([], opts);
    }

    function renderChats() {
      const query = String(deps.state.search || '').trim().toLowerCase();
      const wrap = document.getElementById('tc-chats');
      // The top-bar name rides the same refresh as the list: a chat that gets
      // renamed, or one whose server-side title lands after the first reply,
      // updates in both places from one call.
      deps.syncChatTitle();
      // Code and Work render their own rows; decorate them the same way so the
      // hover card, right-click menu and sorting are not Chat-only features.
      if (window.ThomasUnifiedModes && window.ThomasUnifiedModes.renderHistory(wrap, query)) {
        if (window.ThomasSidebarHistory) window.ThomasSidebarHistory.decorate(wrap);
        return;
      }
      const chats = query
        ? deps.chatList.filter(c => (String(c.title || '') + '\n' + String(c.preview || '')).toLowerCase().includes(query))
        : deps.chatList;
      wrap.innerHTML = '';
      if (!chats.length) {
        wrap.innerHTML = `<div data-chat-empty style="padding:12px 10px;color:var(--c-muted);font-size:12px;line-height:1.5;">${query ? 'No matching chats.' : 'No chats yet.'}</div>`;
        return;
      }
      const history = window.ThomasSidebarHistory;
      chats.forEach(c => {
        const sel = c.id === deps.state.activeChat;
        const b = document.createElement('button');
        b.className = 'hv-soft';
        b.style.cssText = `width: 100%; text-align: left; display: flex; flex-direction: column; gap: 2px; padding: 9px 11px; margin-bottom: 2px; border-radius: 10px; border: 1px solid transparent; background: ${sel ? 'var(--c-surface-2)' : 'transparent'}; color: var(--c-text); font-family: inherit; cursor: pointer; transition: all .14s;`;
        // Identity the shared decorator needs for sorting, pinning, renaming,
        // the hover card and the right-click menu.
        b.dataset.historyId = c.id;
        b.dataset.historyTitle = c.title;
        b.dataset.historyTime = String(c.updatedAt || 0);
        b.dataset.historyMode = 'chat';
        // A run belongs to the chat it was started in, so only THAT row gets
        // the dot — the mode tab alone could not say which chat was busy.
        const running = sel && deps.state.streaming;
        b.innerHTML = history
          ? history.rowHtml({ title: c.title, preview: c.preview, time: c.updatedAt, running })
          : `<span class="tc-history-line"><span class="tc-history-name" data-history-name>${deps.esc(c.title)}</span></span><span class="tc-history-preview">${deps.esc(c.preview)}</span>`;
        b.addEventListener('click', () => deps.selectChat(c.id));
        wrap.appendChild(b);
      });
      if (history) history.decorate(wrap);
    }


    // ---------- Welcome action cards ----------
    // No welcome tiles. Your direction, 2026-09-06: "Remove the welcome tiles on
    // a new chat entirely, including Draw it on the canvas; a new chat is just
    // the greeting and the composer." Kept as a function so the boot that calls
    // it is unchanged; it clears the row and hides it.
    function renderCards() {
      const wrap = document.getElementById('tc-cards');
      if (!wrap) return;
      wrap.innerHTML = '';
      wrap.hidden = true;
      wrap.style.display = 'none';
    }


    // ---------- Boot: pull live model + chats + session from the backend ----------
    // Historical replies show their recorded model, never the current picker.
    // A missing recorded model remains blank.
    function mapRealMessages(list, rowModel) {
      const answered = String(rowModel || '').trim();
      return (Array.isArray(list) ? list : []).map(m => window.ThomasChatMediaBridge.mapMetadata({
        role: (m.role === 'assistant' ? 'assistant' : 'user'),
        text: String(m.content != null ? m.content : (m.text || '')),
        model: (m.role === 'assistant' ? answered : ''),
      }, m));
    }

    // Pull the real recent-chat list (legacy store + live v2 sessions) into the sidebar.
    // Called on boot AND after each turn so a brand-new chat shows up in Recent without
    // a reload, with its real title + date. (chat history fix, 2026-06-28)
    // The list is kept in this browser as it was last seen, so the sidebar fills at once on the next open and the
    // fresh list replaces it a moment later. The newest rows keep their messages (opening one needs them); older
    // rows keep only what the list shows.
    const CACHE_KEY = 'thomas_recent_chats_v1';
    const CACHE_FULL = 25;
    function toList(rows) {
      return rows.map(row => {
        const msgs = mapRealMessages(row.messages, row.model);
        // The second line says what Thomas answered. It used to repeat the first thing you typed, which is also
        // where an unnamed chat gets its title, so a row read "pong" over "pong". A chat with no reply yet has none.
        const lastReply = msgs.filter(m => m.role === 'assistant' && String(m.text || '').trim()).pop();
        return { id: String(row.id || row.session_id || ''), title: String(row.title || 'Untitled chat'), preview: String(row.preview || (lastReply ? lastReply.text : '')).replace(/\s+/g, ' ').trim().slice(0, 60), msgs, sessionId: row.sessionId || row.session_id || null, surfaceMode: String(row.surfaceMode || 'chat'), contextId: String(row.contextId || ''), updatedAt: Number(row.updatedAt || row.createdAt || 0) };
      }).filter(c => c.id);
    }
    function remember(rows) {
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(rows.map((row, i) => (i < CACHE_FULL ? row : { ...row, messages: [] })))); } catch (e) { /* too big or blocked: just not remembered */ }
    }
    function paintRemembered() {
      if (deps.chatList && deps.chatList.length) return;
      try {
        const rows = JSON.parse(localStorage.getItem(CACHE_KEY) || '[]');
        if (!Array.isArray(rows) || !rows.length) return;
        const active = deps.state.activeChat;
        deps.chatList = toList(rows);
        deps.state.activeChat = active;
        renderChats();
      } catch (e) { /* an unreadable copy is ignored */ }
    }
    async function refreshChats() {
      paintRemembered();
      try {
        const r = await fetch('/api/chats?mode=chat');
        if (!r.ok) return;
        const d = await r.json();
        const rows = d.chats || (d.data && d.data.chats) || [];
        if (!Array.isArray(rows)) return;
        const active = deps.state.activeChat;
        deps.chatList = toList(rows);
        deps.state.activeChat = active;
        renderChats();
        remember(rows);
      } catch (e) {}
    }
    return { fmtChatDate, renderChats, renderCards, mapRealMessages, refreshChats };
  }
  window.ThomasChatHistoryView = { create };
})();
