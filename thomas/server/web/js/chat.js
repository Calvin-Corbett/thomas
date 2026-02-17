/* ============================================================
   Thomas Chat
   ============================================================
   Message rendering, markdown, streaming, hover actions,
   autoscroll, tool call display.
   ============================================================ */

import { getState, subscribe, getActiveChat, addMessage, updateChat, setState, startRun, addRunStep, updateRun, endRun, createChat } from './store.js';
import { saveChat } from './db.js';
import { streamChat, createSession, importSession } from './api.js';
import { setComposerText, focusComposer } from './composer.js';
import { el, icon, escapeHtml, formatDuration, truncate, formatNumber } from './utils.js';
import { createButton, createModal, showToast } from './components.js';
import { ingestSwarmEvent, isSwarmEvent, openSwarmInspector } from './swarm.js';

let _messagesEl = null;
let _messagesInnerEl = null;
let _userScrolledUp = false;
let _currentStreamEl = null;
let _currentStreamText = '';
let _selectionBarEl = null;
let _activeUtterance = null;
let _speakingMsgId = null;
let _ttsQueue = [];
let _ttsSeq = 0;
let _swarmOpened = false;

export function initChat() {
  _messagesEl = document.getElementById('chatMessages');
  _messagesInnerEl = document.getElementById('chatMessagesInner');
  _selectionBarEl = ensureSelectionBar();

  if (_messagesEl) {
    _messagesEl.addEventListener('scroll', () => {
      const atBottom = _messagesEl.scrollHeight - _messagesEl.scrollTop - _messagesEl.clientHeight < 60;
      _userScrolledUp = !atBottom;
    });
  }

  subscribe('activeChatId', renderMessages);
  subscribe('chats', () => {
    if (!getState().ui.streaming) renderMessages();
  });
  subscribe('ui', () => {
    renderSelectionBar();
    if (!getState().ui.streaming) renderMessages();
  });

  renderSelectionBar();
  renderMessages();
}

function scrollToBottom(force = false) {
  if (!_messagesEl) return;
  if (force || !_userScrolledUp) {
    _messagesEl.scrollTop = _messagesEl.scrollHeight;
  }
}

function ensureSelectionBar() {
  const header = document.getElementById('chatHeader');
  if (!header) return null;
  let bar = document.getElementById('selectionBar');
  if (bar) return bar;

  bar = el('div', { className: 'selection-bar', id: 'selectionBar' });
  header.insertAdjacentElement('afterend', bar);
  return bar;
}

function setSelectionMode(enabled) {
  if (!enabled) {
    setState('ui', { selectionMode: false, selectedMessageIds: [] });
    return;
  }
  setState('ui', { selectionMode: true, selectedMessageIds: [] });
}

function toggleSelectedMessage(messageId) {
  const cur = Array.isArray(getState().ui.selectedMessageIds) ? getState().ui.selectedMessageIds : [];
  const set = new Set(cur);
  if (set.has(messageId)) set.delete(messageId);
  else set.add(messageId);
  setState('ui', { selectedMessageIds: Array.from(set) });
}

function getSelectedMessages() {
  const chat = getActiveChat();
  if (!chat) return [];
  const ids = new Set(Array.isArray(getState().ui.selectedMessageIds) ? getState().ui.selectedMessageIds : []);
  const out = [];
  for (const m of chat.messages || []) {
    if (ids.has(m.id)) out.push(m);
  }
  return out;
}

function selectedToMarkdown(msgs) {
  const parts = [];
  for (const m of msgs) {
    const who = m.role === 'user' ? 'You' : 'Thomas';
    const content = typeof m.content === 'string' ? m.content : '';
    parts.push(`## ${who}\n\n${content}\n`);
  }
  return parts.join('\n');
}

function downloadText(filename, text, mime = 'text/plain') {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function renderSelectionBar() {
  if (!_selectionBarEl) return;
  const ui = getState().ui;
  if (!ui.selectionMode) {
    _selectionBarEl.style.display = 'none';
    return;
  }

  const selected = getSelectedMessages();
  _selectionBarEl.style.display = 'flex';
  _selectionBarEl.innerHTML = '';

  const left = el('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', minWidth: '0' } });
  left.appendChild(el('strong', { style: { fontSize: 'var(--text-sm)' } }, `${selected.length} selected`));
  left.appendChild(el('span', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, 'Click checkboxes to select.'));

  const right = el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' } });

  right.appendChild(createButton({
    label: 'Copy',
    variant: 'ghost',
    size: 'sm',
    disabled: selected.length === 0,
    onClick: async () => {
      const md = selectedToMarkdown(selected);
      try {
        await navigator.clipboard.writeText(md);
        showToast('Copied', 'success');
      } catch {
        showToast('Copy failed', 'error');
      }
    },
  }));

  right.appendChild(createButton({
    label: 'Export MD',
    variant: 'ghost',
    size: 'sm',
    disabled: selected.length === 0,
    onClick: () => {
      const md = selectedToMarkdown(selected);
      downloadText('thomas-selection.md', md, 'text/markdown');
    },
  }));

  right.appendChild(createButton({
    label: 'Export JSON',
    variant: 'ghost',
    size: 'sm',
    disabled: selected.length === 0,
    onClick: () => {
      const json = JSON.stringify(selected, null, 2);
      downloadText('thomas-selection.json', json, 'application/json');
    },
  }));

  right.appendChild(createButton({
    label: 'Cancel',
    variant: 'primary',
    size: 'sm',
    onClick: () => setSelectionMode(false),
  }));

  _selectionBarEl.appendChild(left);
  _selectionBarEl.appendChild(right);
}

function stripForSpeech(text) {
  if (!text) return '';
  let t = String(text);
  // Drop code blocks entirely.
  t = t.replace(/```[\s\S]*?```/g, '');
  // Replace links with their text.
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  // Remove some markdown punctuation.
  t = t.replace(/[#>*_~`]/g, ' ');
  t = t.replace(/\s+/g, ' ').trim();
  return t;
}

function getSelectedVoice() {
  try {
    const uri = getState().settings.ttsVoice;
    if (!uri) return null;
    const voices = window.speechSynthesis?.getVoices?.() || [];
    return voices.find(v => (v.voiceURI || v.name) === uri) || null;
  } catch {
    return null;
  }
}

function emitTtsEvent(type, detail = {}) {
  try {
    window.dispatchEvent(new CustomEvent(type, { detail }));
  } catch {
    // ignore
  }
}

function splitTtsChunks(text, { maxTotalChars = 9000, maxChunkChars = 260, maxChunks = 60 } = {}) {
  let t = String(text || '').trim();
  if (!t) return [];

  // Keep speech bounded so we don't generate a huge queue.
  if (t.length > maxTotalChars) {
    t = t.slice(0, maxTotalChars).trimEnd() + '...';
  }

  // Sentence-ish split (no lookbehind to keep compatibility).
  const sentences = [];
  let cur = '';
  for (let i = 0; i < t.length; i++) {
    const ch = t[i];
    cur += ch;
    if ((ch === '.' || ch === '!' || ch === '?') && (i === t.length - 1 || t[i + 1] === ' ')) {
      const s = cur.trim();
      if (s) sentences.push(s);
      cur = '';
    }
  }
  const tail = cur.trim();
  if (tail) sentences.push(tail);

  function chunkByWords(s) {
    const words = String(s || '').split(/\s+/g).filter(Boolean);
    const out = [];
    let buf = '';
    for (const w of words) {
      const cand = buf ? (buf + ' ' + w) : w;
      if (cand.length > maxChunkChars && buf) {
        out.push(buf);
        buf = w;
      } else {
        buf = cand;
      }
    }
    if (buf) out.push(buf);
    return out;
  }

  const chunks = [];
  const src = sentences.length > 0 ? sentences : [t];
  for (const s of src) {
    if (!s) continue;
    if (s.length <= maxChunkChars) chunks.push(s);
    else chunks.push(...chunkByWords(s));
    if (chunks.length >= maxChunks) break;
  }

  return chunks.slice(0, maxChunks).filter(Boolean);
}

function stopSpeaking() {
  _ttsSeq += 1;
  _ttsQueue = [];
  try { window.speechSynthesis?.cancel?.(); } catch { /* ignore */ }
  _activeUtterance = null;
  _speakingMsgId = null;
}

function speakText(text, { messageId = null } = {}) {
  const canSpeak = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);
  if (!canSpeak) return false;

  const t = stripForSpeech(text);
  if (!t) return false;

  // Stop any current speech.
  stopSpeaking();

  _speakingMsgId = messageId;
  _ttsQueue = splitTtsChunks(t);
  if (_ttsQueue.length === 0) {
    _speakingMsgId = null;
    return false;
  }

  const seq = _ttsSeq;

  function speakNext() {
    if (seq !== _ttsSeq) return;

    if (_ttsQueue.length === 0) {
      const mid = _speakingMsgId;
      _activeUtterance = null;
      _speakingMsgId = null;
      emitTtsEvent('thomas:tts_end', { messageId: mid });
      return;
    }

    const chunk = _ttsQueue.shift();
    const u = new SpeechSynthesisUtterance(chunk);

    const rate = getState().settings.ttsRate;
    u.rate = Math.max(0.7, Math.min(1.3, typeof rate === 'number' ? rate : 1.0));
    const voice = getSelectedVoice();
    if (voice) u.voice = voice;

    _activeUtterance = u;

    u.onend = () => speakNext();
    u.onerror = () => {
      // Fail closed: stop the queue and signal completion.
      _ttsQueue = [];
      const mid = _speakingMsgId;
      _activeUtterance = null;
      _speakingMsgId = null;
      emitTtsEvent('thomas:tts_end', { messageId: mid, error: true });
    };

    try {
      emitTtsEvent('thomas:tts_start', { messageId: _speakingMsgId });
      window.speechSynthesis.speak(u);
    } catch {
      // If speak throws, end the queue.
      _ttsQueue = [];
      const mid = _speakingMsgId;
      _activeUtterance = null;
      _speakingMsgId = null;
      emitTtsEvent('thomas:tts_end', { messageId: mid, error: true });
    }
  }

  speakNext();
  return true;
}

function maybeAutoSpeak(msg) {
  const s = getState().settings;
  if (!s.ttsEnabled) return false;
  if (!msg || msg.role !== 'assistant') return false;
  const content = typeof msg.content === 'string' ? msg.content : '';
  return speakText(content, { messageId: msg.id });
}

function speakMessage(msg) {
  if (!msg || msg.role !== 'assistant') return;
  if (_speakingMsgId && _speakingMsgId === msg.id) {
    stopSpeaking();
    return;
  }
  const content = typeof msg.content === 'string' ? msg.content : '';
  speakText(content, { messageId: msg.id });
}

function quoteMessage(msg) {
  const content = typeof msg.content === 'string' ? msg.content : '';
  if (!content.trim()) return;

  const who = msg.role === 'user' ? 'You' : 'Thomas';
  const lines = content.split('\n').map(l => `> ${l}`);
  const quoted = `> ${who}:\n` + lines.join('\n');

  setComposerText(quoted, { append: true });
  focusComposer();
}

function toggleBookmark(msg) {
  const chat = getActiveChat();
  if (!chat) return;
  const m = chat.messages.find(x => x.id === msg.id);
  if (!m) return;
  m.bookmarked = !m.bookmarked;
  updateChat(chat.id, { messages: chat.messages });
  saveChat(chat);
  renderMessages();
  showToast(m.bookmarked ? 'Bookmarked' : 'Unbookmarked', 'success');
}

function openMessageInfo(msg) {
  const body = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '10px' } });

  const when = msg.createdAt ? new Date(msg.createdAt).toLocaleString() : '';
  body.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, `${msg.role}  ${when}`));

  if (msg.meta) {
    const meta = msg.meta || {};
    const profile = meta.profile || '';
    const modelId = meta.modelId || '(profile default)';
    const mode = meta.mode || '';
    const elapsed = meta.elapsedMs ? formatDuration(meta.elapsedMs) : '';
    const toolCalls = typeof meta.toolCalls === 'number' ? meta.toolCalls : null;

    const lines = [];
    if (profile) lines.push(`Profile: ${profile}`);
    if (modelId) lines.push(`Model: ${modelId}`);
    if (mode) lines.push(`Mode: ${mode}`);
    if (elapsed) lines.push(`Elapsed: ${elapsed}`);
    if (toolCalls !== null) lines.push(`Tools: ${toolCalls}`);
    body.appendChild(el('div', { className: 'mono', style: { whiteSpace: 'pre-wrap', fontSize: '12px' } }, lines.join('\n')));

    const usage = meta.usage;
    if (usage && (usage.total_tokens || 0) > 0) {
      body.appendChild(el('div', { className: 'mono', style: { whiteSpace: 'pre-wrap', fontSize: '12px' } },
        `Usage: ${formatNumber(usage.prompt_tokens || 0)} prompt + ${formatNumber(usage.completion_tokens || 0)} completion = ${formatNumber(usage.total_tokens || 0)} total`
      ));
    }
  }

  const text = typeof msg.content === 'string' ? msg.content : '';
  body.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '4px' } }, 'Content'));
  body.appendChild(el('pre', { className: 'mono', style: { whiteSpace: 'pre-wrap', maxHeight: '260px', overflow: 'auto' } }, text.slice(0, 20000)));

  const copyBtn = createButton({
    label: 'Copy JSON',
    variant: 'ghost',
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(JSON.stringify(msg, null, 2));
        showToast('Copied', 'success');
      } catch {
        showToast('Copy failed', 'error');
      }
    },
  });
  const closeBtn = createButton({ label: 'Close', variant: 'primary', onClick: () => modal.close() });

  const modal = createModal({ title: 'Message Info', body, footer: [copyBtn, closeBtn] });
  document.getElementById('modals')?.appendChild(modal.backdrop);
}

async function forkFromMessage(msg) {
  const chat = getActiveChat();
  if (!chat) return;

  const idx = chat.messages.findIndex(m => m.id === msg.id);
  if (idx < 0) return;

  const cut = chat.messages
    .slice(0, idx + 1)
    .map(m => JSON.parse(JSON.stringify(m)));
  const forkTitle = `Fork: ${truncate(chat.title || 'Chat', 40)}`;

  // Exit selection mode if active (forking should be clean).
  if (getState().ui.selectionMode) setSelectionMode(false);

  const forkChat = createChat(forkTitle);
  updateChat(forkChat.id, { messages: cut, sessionId: null });
  saveChat(getState().chats.get(forkChat.id));

  // Best-effort: create a new server session seeded from the UI conversation.
  try {
    const conversation = [];
    for (const m of cut) {
      if (m.role !== 'user' && m.role !== 'assistant') continue;
      if (typeof m.content !== 'string') continue;
      conversation.push({ role: m.role, content: m.content });
    }

    const profile = getState().activeProfile || getState().models.defaultProfile || 'local';
    const modelId = (msg.meta && msg.meta.modelId) ? msg.meta.modelId : (getState().activeModelId || null);
    const sess = await importSession(conversation, { profile, model_id: modelId });
    updateChat(forkChat.id, { sessionId: sess.session_id });
    saveChat(getState().chats.get(forkChat.id));
    showToast('Fork created', 'success');
  } catch (e) {
    showToast(`Fork created (new session will start fresh): ${e.message || String(e)}`, 'info');
  }

  renderMessages();
  scrollToBottom(true);
}

export function renderMessages() {
  if (!_messagesInnerEl) return;

  const chat = getActiveChat();
  if (!chat || chat.messages.length === 0) {
    _messagesInnerEl.innerHTML = '';
    _messagesInnerEl.appendChild(renderEmptyState());
    return;
  }

  _messagesInnerEl.innerHTML = '';
  for (const msg of chat.messages) {
    _messagesInnerEl.appendChild(renderMessage(msg));
  }
  scrollToBottom(true);
}

function renderEmptyState() {
  const c = el('div', { className: 'empty-state empty-state-rich', style: { height: '100%', minHeight: '320px' } });
  c.appendChild(el('div', { className: 'empty-state-icon' }, '\uD83D\uDCAC'));
  c.appendChild(el('div', { className: 'empty-state-title' }, 'What can I help with?'));
  c.appendChild(el('div', { className: 'empty-state-text' }, 'Ask Thomas to debug, explain code, run tasks, or set up tools.'));

  const actions = el('div', { className: 'empty-quick-grid' });

  function quickCard(title, subtitle, onClick) {
    const btn = el('button', { className: 'empty-quick-card', type: 'button' });
    btn.appendChild(el('div', { className: 'empty-quick-title' }, title));
    btn.appendChild(el('div', { className: 'empty-quick-subtitle' }, subtitle));
    btn.addEventListener('click', onClick);
    return btn;
  }

  actions.appendChild(quickCard(
    'Debug code',
    'Get a focused bug hunt with fixes and tests.',
    () => {
      setComposerText('Help me debug this issue step by step. Include root cause and the smallest safe fix.');
      focusComposer();
    },
  ));

  actions.appendChild(quickCard(
    'Explain a file',
    'Break down structure, risks, and improvements.',
    () => {
      setComposerText('Explain this file, then list concrete improvements and potential risks:\n\n[path/to/file]');
      focusComposer();
    },
  ));

  actions.appendChild(quickCard(
    'Set up providers',
    'Configure API keys and test model connectivity.',
    () => {
      import('./settings.js')
        .then(mod => mod.openSettings('providers'))
        .catch(() => setState('ui', { settingsOpen: true, settingsTab: 'providers' }));
    },
  ));

  actions.appendChild(quickCard(
    'Keyboard shortcuts',
    'Open command palette and jump faster.',
    () => {
      import('./command-palette.js').then(mod => mod.openPalette()).catch(() => {});
    },
  ));

  c.appendChild(actions);
  c.appendChild(el('div', { className: 'empty-shortcut-hint' }, 'Tip: Ctrl/Cmd+K opens the command palette.'));
  return c;
}

function renderMessage(msg) {
  const container = el('div', { className: 'message', dataset: { messageId: msg.id }, id: `msg-${msg.id}` });

  const selectionMode = !!getState().ui.selectionMode;
  const selected = new Set(Array.isArray(getState().ui.selectedMessageIds) ? getState().ui.selectedMessageIds : []);
  const isSelected = selectionMode && selected.has(msg.id);

  if (selectionMode) {
    container.classList.add('selectable');
    container.classList.toggle('selected', isSelected);

    const wrap = el('label', { className: 'message-select-wrap', title: 'Select message' });
    const cb = el('input', { className: 'message-select', type: 'checkbox' });
    cb.checked = isSelected;
    cb.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleSelectedMessage(msg.id);
    });
    wrap.appendChild(cb);
    container.appendChild(wrap);

    container.addEventListener('click', (e) => {
      if (!getState().ui.selectionMode) return;
      if (e.target.closest('button') || e.target.closest('a') || e.target.closest('input')) return;
      toggleSelectedMessage(msg.id);
    });
  }

  const avatar = el('div', { className: `message-avatar ${msg.role}` },
    msg.role === 'user' ? 'U' : 'T');
  container.appendChild(avatar);

  const body = el('div', { className: 'message-body' });
  body.appendChild(el('div', { className: 'message-role' }, msg.role === 'user' ? 'You' : 'Thomas'));

  const contentEl = el('div', { className: 'message-content' });
  if (typeof msg.content === 'string') {
    if (msg.role === 'assistant') {
      contentEl.innerHTML = renderMarkdown(msg.content);
      requestAnimationFrame(() => enhanceCodeBlocks(contentEl));
    } else {
      contentEl.textContent = msg.content;
    }
  } else {
    contentEl.textContent = '(multimodal content)';
  }
  body.appendChild(contentEl);

  if (msg.toolCalls && msg.toolCalls.length > 0) {
    const section = renderToolCallsSection(msg);
    if (section) body.appendChild(section);
  }

  container.appendChild(body);

  // Hover actions
  const actions = el('div', { className: 'message-actions' });
  const bmBtn = createButton({
    iconName: 'bookmark', variant: 'icon', tooltip: msg.bookmarked ? 'Unbookmark' : 'Bookmark',
    onClick: () => toggleBookmark(msg),
  });
  if (msg.bookmarked) bmBtn.classList.add('btn-icon-active');
  actions.appendChild(bmBtn);
  actions.appendChild(createButton({
    iconName: 'quote', variant: 'icon', tooltip: 'Quote',
    onClick: () => quoteMessage(msg),
  }));
  actions.appendChild(createButton({
    iconName: 'copy', variant: 'icon', tooltip: 'Copy',
    onClick: () => {
      const text = typeof msg.content === 'string' ? msg.content : '';
      navigator.clipboard.writeText(text).then(() => showToast('Copied', 'success'));
    },
  }));
  actions.appendChild(createButton({
    iconName: 'info', variant: 'icon', tooltip: 'Info',
    onClick: () => openMessageInfo(msg),
  }));
  actions.appendChild(createButton({
    iconName: 'fork', variant: 'icon', tooltip: 'Fork from here',
    onClick: () => forkFromMessage(msg),
  }));
  if (msg.role === 'user') {
    actions.appendChild(createButton({
      iconName: 'edit', variant: 'icon', tooltip: 'Edit',
      onClick: () => editUserMessage(msg),
    }));
  }
  if (msg.role === 'assistant') {
    actions.appendChild(createButton({
      iconName: 'retry', variant: 'icon', tooltip: 'Retry',
      onClick: () => retryFromMessage(msg),
    }));
    const canSpeak = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);
    actions.appendChild(createButton({
      iconName: 'speaker', variant: 'icon', tooltip: canSpeak ? 'Speak' : 'TTS unavailable',
      disabled: !canSpeak,
      onClick: () => speakMessage(msg),
    }));
  }
  container.appendChild(actions);

  return container;
}

function renderMarkdown(text) {
  if (!text) return '';
  try {
    if (window.marked) {
      window.marked.setOptions({ breaks: true, gfm: true });
      return window.marked.parse(text);
    }
  } catch (e) {
    console.warn('[chat] markdown error:', e);
  }
  return escapeHtml(text).replace(/\n/g, '<br>');
}

function enhanceCodeBlocks(container) {
  const pres = container.querySelectorAll('pre');
  for (const pre of pres) {
    const code = pre.querySelector('code');
    if (!code) continue;

    const lang = Array.from(code.classList).find(c => c.startsWith('language-'))?.replace('language-', '') || '';

    const wrapper = el('div', { className: 'code-block' });
    const header = el('div', { className: 'code-block-header' });
    header.appendChild(el('span', { className: 'code-block-lang' }, lang || 'code'));

    const copyBtn = el('button', { className: 'code-block-copy' }, 'Copy');
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(code.textContent || '').then(() => {
        copyBtn.textContent = 'Copied!';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
      });
    });
    header.appendChild(copyBtn);
    wrapper.appendChild(header);

    if (window.hljs && lang) {
      try {
        const result = window.hljs.highlight(code.textContent || '', { language: lang, ignoreIllegals: true });
        code.innerHTML = result.value;
      } catch { /* no-op */ }
    }

    const newPre = pre.cloneNode(true);
    wrapper.appendChild(newPre);
    pre.replaceWith(wrapper);
  }
}

function getToolCallCounts(toolCalls) {
  const t = Array.isArray(toolCalls) ? toolCalls : [];
  let ok = 0, fail = 0, running = 0;
  for (const tc of t) {
    if (tc?.ok === true) ok += 1;
    else if (tc?.ok === false) fail += 1;
    else running += 1;
  }
  return { total: t.length, ok, fail, running };
}

function updateToolCallSummary(wrap, msg) {
  if (!wrap) return;
  const counts = getToolCallCounts(msg?.toolCalls);
  const summary = wrap.querySelector('.tool-call-summary');
  const statusEl = wrap.querySelector('.tool-call-summary-status');
  const countsEl = wrap.querySelector('.tool-call-summary-counts');
  const progress = wrap.querySelector('.tool-call-progress-fill');
  const toggleBtn = wrap.querySelector('.tool-call-toggle');

  if (summary) summary.classList.toggle('running', counts.running > 0);
  if (statusEl) {
    if (counts.total === 0) statusEl.textContent = 'idle';
    else if (counts.running > 0) statusEl.textContent = 'running';
    else if (counts.fail > 0) statusEl.textContent = 'done (errors)';
    else statusEl.textContent = 'done';
  }
  if (countsEl) {
    countsEl.textContent = counts.total > 0 ? `${counts.ok + counts.fail}/${counts.total}` : '0/0';
  }
  if (progress) {
    const pct = counts.total > 0 ? Math.round(((counts.ok + counts.fail) / counts.total) * 100) : 0;
    progress.style.width = `${pct}%`;
  }
  if (toggleBtn) {
    toggleBtn.textContent = wrap.classList.contains('expanded') ? 'Hide details' : 'Show details';
  }
}

function renderToolCallsSection(msg, { force = false } = {}) {
  const toolCalls = Array.isArray(msg?.toolCalls) ? msg.toolCalls : [];
  if (!force && toolCalls.length === 0) return null;

  const wrap = el('div', { className: 'tool-call-wrap' });
  if (getState().settings.showToolDetails) wrap.classList.add('expanded');

  const summary = el('div', { className: 'tool-call-summary' });
  summary.appendChild(el('span', { className: 'tool-call-summary-icon' }, '\u2699'));
  summary.appendChild(el('span', { className: 'tool-call-summary-title' }, 'Process'));
  summary.appendChild(el('span', { className: 'tool-call-summary-status' }, 'idle'));
  summary.appendChild(el('span', { className: 'tool-call-summary-counts' }, '0/0'));

  const progress = el('div', { className: 'tool-call-progress' });
  progress.appendChild(el('div', { className: 'tool-call-progress-fill' }));
  summary.appendChild(progress);

  const toggleBtn = el('button', { className: 'tool-call-toggle', type: 'button' }, 'Show details');
  toggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    wrap.classList.toggle('expanded');
    updateToolCallSummary(wrap, msg);
  });
  summary.appendChild(toggleBtn);

  summary.addEventListener('click', () => {
    wrap.classList.toggle('expanded');
    updateToolCallSummary(wrap, msg);
  });

  const list = el('div', { className: 'tool-call-list' });
  for (const tc of toolCalls) list.appendChild(renderToolCall(tc));

  wrap.appendChild(summary);
  wrap.appendChild(list);
  updateToolCallSummary(wrap, msg);
  return wrap;
}

function ensureToolCallSection(parent, msg) {
  if (!parent) return null;
  let wrap = parent.querySelector('.tool-call-wrap');
  if (!wrap) {
    wrap = renderToolCallsSection(msg, { force: true });
    if (wrap) parent.appendChild(wrap);
  }
  if (wrap) updateToolCallSummary(wrap, msg);
  return wrap;
}

function renderToolCall(tc) {
  const container = el('div', { className: 'tool-call', dataset: { toolId: tc.id || '' } });
  const header = el('div', { className: 'tool-call-header' });
  header.appendChild(el('span', { className: 'tool-call-icon' }, '\u26A1'));
  header.appendChild(el('span', { className: 'tool-call-name' }, tc.name || 'tool'));

  const sc = tc.ok === true ? 'ok' : tc.ok === false ? 'fail' : 'running';
  const st = tc.ok === true ? `\u2713 ${formatDuration(tc.ms || 0)}` : tc.ok === false ? '\u2717 failed' : '\u23F3 running';
  header.appendChild(el('span', { className: `tool-call-status ${sc}` }, st));
  container.appendChild(header);

  const argsText = typeof tc.argsText === 'string' ? tc.argsText : '';
  const resultText = typeof tc.result === 'string' ? tc.result : tc.result ? JSON.stringify(tc.result) : '';

  const body = el('div', { className: 'tool-call-body' });
  const actions = el('div', { style: { display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-2)', flexWrap: 'wrap' } });

  actions.appendChild(createButton({
    label: 'Copy args',
    variant: 'ghost',
    size: 'sm',
    disabled: !argsText,
    onClick: () => {
      navigator.clipboard.writeText(argsText || '').then(() => showToast('Args copied', 'success'));
    },
  }));

  actions.appendChild(createButton({
    label: 'Copy result',
    variant: 'ghost',
    size: 'sm',
    disabled: !resultText,
    onClick: () => {
      navigator.clipboard.writeText(resultText || '').then(() => showToast('Result copied', 'success'));
    },
  }));

  // Best-effort: open diff/patch results in a modal
  const looksLikeDiff = /(^diff --git\\s)|(^\\*\\*\\* Begin Patch)/m.test(resultText);
  if (looksLikeDiff) {
    actions.appendChild(createButton({
      label: 'View diff',
      variant: 'ghost',
      size: 'sm',
      onClick: () => {
        const pre = el('pre', { style: { whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '12px', lineHeight: '1.5' } }, resultText.slice(0, 20000));
        const modal = createModal({ title: `${tc.name || 'tool'} output`, body: pre });
        document.getElementById('modals')?.appendChild(modal.backdrop);
      },
    }));
  }

  body.appendChild(actions);

  if (argsText) {
    body.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' } }, 'Args'));
    body.appendChild(el('pre', { className: 'mono', style: { whiteSpace: 'pre-wrap' } }, argsText.slice(0, 8000)));
  }

  if (resultText) {
    body.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--text-muted)', marginTop: argsText ? '10px' : '0', marginBottom: '4px' } }, 'Result'));
    body.appendChild(el('pre', { className: 'mono', style: { whiteSpace: 'pre-wrap' } }, resultText.slice(0, 20000)));
  }

  if (argsText || resultText) {
    container.appendChild(body);
    header.addEventListener('click', () => container.classList.toggle('expanded'));
  }

  return container;
}

/* ---- Streaming ---- */

export async function sendMessage(text, docs = [], images = []) {
  const state = getState();
  const chat = getActiveChat();
  if (!chat) return;
  _swarmOpened = false;

  if (!chat.sessionId) {
    try {
      const session = await createSession();
      updateChat(chat.id, { sessionId: session.session_id });
    } catch (e) {
      showToast('Failed to create session: ' + e.message, 'error');
      return;
    }
  }

  // New user input should interrupt any ongoing speech.
  stopSpeaking();

  addMessage(chat.id, { role: 'user', content: text });
  saveChat(getState().chats.get(chat.id));
  renderMessages();
  scrollToBottom(true);

  const abortController = new AbortController();
  setState('ui', { streaming: true, abortController });

  const asstMsgId = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  _currentStreamText = '';
  _currentStreamEl = null;

  const runProfile = state.activeProfile || state.models.defaultProfile || 'local';
  const runModelId = state.activeModelId || null;
  const runMode = state.mode;

  addMessage(chat.id, {
    id: asstMsgId,
    role: 'assistant',
    content: '',
    status: 'streaming',
    toolCalls: [],
    meta: {
      profile: runProfile,
      modelId: runModelId,
      mode: runMode,
      startedAt: Date.now(),
      usage: null,
      elapsedMs: 0,
    },
  });
  const run = startRun();
  updateRun({
    profile: runProfile,
    modelId: runModelId,
    mode: runMode,
  });

  const updatedChat = getState().chats.get(chat.id);
  const payload = {
    session_id: updatedChat.sessionId,
    profile: runProfile,
    model_id: runModelId,
    mode: runMode,
    text,
    docs: docs.map(d => ({ name: d.name, text: d.text })),
    images: images.map(img => ({ name: img.name, data_url: img.dataUrl })),
  };

  renderMessages();
  const lastMsgEl = _messagesInnerEl?.querySelector('.message:last-child .message-content');
  if (lastMsgEl) {
    _currentStreamEl = lastMsgEl;
    lastMsgEl.classList.add('streaming-cursor');
  }

  setStatus('thinking', true);

  try {
    const onEvent = (event) => {
      const currentChat = getState().chats.get(chat.id);
      if (!currentChat) return;
      const asstMsg = currentChat.messages.find(m => m.id === asstMsgId);

      if (isSwarmEvent(event)) {
        ingestSwarmEvent(event);
        if (!_swarmOpened) {
          openSwarmInspector();
          _swarmOpened = true;
        }
      }

      if (event.type === 'swarm_start') {
        updateRun({ status: 'swarm' });
        setStatus('swarm', true);
        return;
      } else if (event.type === 'task_update' || event.type === 'agent_text' || event.type === 'agent_tool_start' || event.type === 'agent_tool_result') {
        // Swarm detail events are handled by the Swarm Board.
        return;
      } else if (event.type === 'swarm_done') {
        const ok = !!event.ok;
        const finalText = (typeof event.final === 'string' && event.final.trim())
          ? event.final
          : (ok ? '(swarm complete)' : '(swarm failed)');

        if (asstMsg) {
          asstMsg.content = finalText;
          asstMsg.status = ok ? 'complete' : 'error';
          if (_currentStreamEl) {
            _currentStreamEl.innerHTML = renderMarkdown(finalText);
          }
          asstMsg.meta = {
            ...(asstMsg.meta || {}),
            usage: null,
            tokenReport: null,
            elapsedMs: 0,
            toolCalls: Array.isArray(asstMsg.toolCalls) ? asstMsg.toolCalls.length : 0,
          };
          if (ok) maybeAutoSpeak(asstMsg);
        }

        emitTtsEvent('thomas:assistant_done', {
          messageId: asstMsg ? asstMsg.id : asstMsgId,
          spoke: false,
          error: !ok,
        });
        endRun(ok ? 'done' : 'error');
        updateRun({ status: ok ? 'done' : 'error', error: event.error || null });
        setStatus(ok ? 'swarm done' : 'swarm error', ok);
        if (!ok) showToast(`Swarm error: ${event.error || 'unknown error'}`, 'error');
        return;
      }

      if (event.type === 'text') {
        _currentStreamText += event.text || '';
        if (asstMsg) asstMsg.content = _currentStreamText;
        if (_currentStreamEl) {
          _currentStreamEl.innerHTML = renderMarkdown(_currentStreamText);
          _currentStreamEl.classList.add('streaming-cursor');
          requestAnimationFrame(() => enhanceCodeBlocks(_currentStreamEl));
        }
        scrollToBottom();

      } else if (event.type === 'tool_start') {
        const tc = { id: event.id || '', name: event.name, ok: null, ms: 0, argsText: '', result: '' };
        if (asstMsg) asstMsg.toolCalls.push(tc);
        addRunStep({ type: 'tool_start', id: tc.id, name: event.name });
        updateRun({ status: 'running tools' });
        setStatus('running ' + event.name, true);
        if (_currentStreamEl?.parentElement) {
          const host = ensureToolCallSection(_currentStreamEl.parentElement, asstMsg);
          const list = host?.querySelector('.tool-call-list');
          if (list) list.appendChild(renderToolCall(tc));
          if (host) updateToolCallSummary(host, asstMsg);
        }

      } else if (event.type === 'tool_args') {
        const id = event.id || '';
        const delta = event.delta || '';
        if (asstMsg && delta) {
          const found = id
            ? asstMsg.toolCalls.find(x => x.id === id)
            : (asstMsg.toolCalls.length > 0 ? asstMsg.toolCalls[asstMsg.toolCalls.length - 1] : null);
          if (found) {
            found.argsText = (found.argsText || '') + delta;
          }
        }
        addRunStep({ type: 'tool_args', id, deltaLen: (delta || '').length });
        // Update DOM if present
        if (_currentStreamEl?.parentElement && id) {
          const elTc = _currentStreamEl.parentElement.querySelector(`.tool-call[data-tool-id="${CSS.escape(id)}"] .tool-call-body pre`);
          if (elTc) elTc.textContent = (asstMsg?.toolCalls.find(x => x.id === id)?.argsText || '').slice(0, 8000);
        }

      } else if (event.type === 'tool_result') {
        const id = event.id || '';
        if (asstMsg?.toolCalls?.length > 0) {
          const tc = id
            ? asstMsg.toolCalls.find(x => x.id === id)
            : asstMsg.toolCalls[asstMsg.toolCalls.length - 1];
          if (tc) {
            tc.ok = event.ok;
            tc.ms = event.ms;
            tc.result = event.result || '';
          }
        }
        addRunStep({ type: 'tool_result', id, name: event.name, ok: event.ok, ms: event.ms });
        // Update tool call status + result in DOM
        const parent = _currentStreamEl?.parentElement;
        if (parent) {
          const target = id
            ? parent.querySelector(`.tool-call[data-tool-id="${CSS.escape(id)}"]`)
            : (parent.querySelectorAll('.tool-call')?.[parent.querySelectorAll('.tool-call').length - 1] || null);
          if (target) {
            const statusEl = target.querySelector('.tool-call-status');
            if (statusEl) {
              statusEl.className = `tool-call-status ${event.ok ? 'ok' : 'fail'}`;
              statusEl.textContent = event.ok ? `\u2713 ${formatDuration(event.ms || 0)}` : '\u2717 failed';
            }
            // Best-effort: fill result area if expanded
            // (Re-rendering the whole tool call is simpler/safer than partial DOM surgery.)
            if (asstMsg) {
              const tc = id ? asstMsg.toolCalls.find(x => x.id === id) : asstMsg.toolCalls[asstMsg.toolCalls.length - 1];
              if (tc) {
                const expanded = target.classList.contains('expanded');
                const fresh = renderToolCall(tc);
                if (expanded) fresh.classList.add('expanded');
                target.replaceWith(fresh);
              }
            }
          }
          const host = parent.querySelector('.tool-call-wrap');
          if (host) updateToolCallSummary(host, asstMsg);
        }

      } else if (event.type === 'iteration') {
        updateRun({ tokenEstimate: event.token_estimate, contextWindow: event.context_window });
        addRunStep({ type: 'iteration', iteration: event.iteration });

      } else if (event.type === 'guardrails') {
        const evtName = String(event.event || '');
        const payloadObj = event.payload && typeof event.payload === 'object' ? event.payload : {};
        addRunStep({ type: 'guardrails', event: evtName, tool: payloadObj.tool_name || '' });
        try {
          if (window.guardrailsHandleEvent) window.guardrailsHandleEvent(evtName, payloadObj);
        } catch {
          // ignore UI plugin errors
        }

      } else if (event.type === 'error') {
        if (asstMsg) asstMsg.status = 'error';
        emitTtsEvent('thomas:assistant_done', {
          messageId: asstMsg ? asstMsg.id : asstMsgId,
          spoke: false,
          error: true,
        });
        endRun('error');
        updateRun({ error: event.error });
        setStatus('error', false);
        showToast('Error: ' + event.error, 'error');

      } else if (event.type === 'done') {
        let didSpeak = false;
        if (asstMsg) {
          asstMsg.status = 'complete';
          asstMsg.meta = {
            ...(asstMsg.meta || {}),
            usage: event.usage || null,
            tokenReport: event.token_report || null,
            elapsedMs: event.elapsed_ms || 0,
            toolCalls: Array.isArray(asstMsg.toolCalls) ? asstMsg.toolCalls.length : 0,
          };
          didSpeak = maybeAutoSpeak(asstMsg);
        }
        emitTtsEvent('thomas:assistant_done', {
          messageId: asstMsg ? asstMsg.id : asstMsgId,
          spoke: !!didSpeak,
          error: false,
        });
        endRun('done');
        updateRun({
          status: 'done',
          usage: event.usage || null,
          tokenReport: event.token_report || null,
          elapsedMs: event.elapsed_ms || 0,
        });
        setStatus(`done (${event.tool_calls || 0} tools)`, true);
      }
    };

    function isInvalidSessionError(err) {
      const msg = (err && err.message) ? String(err.message) : String(err || '');
      return /missing\/invalid session_id/i.test(msg) || /invalid session_id/i.test(msg);
    }

    async function recoverServerSessionId() {
      const currentChat = getState().chats.get(chat.id);
      if (!currentChat) throw new Error('Chat missing');

      // Do not include the last user message (we will send it again via payload.text),
      // and do not include the in-flight assistant placeholder message.
      const msgs = Array.isArray(currentChat.messages) ? currentChat.messages : [];
      const lastUser = [...msgs].reverse().find(m => m && m.role === 'user' && typeof m.content === 'string') || null;
      const lastUserId = lastUser?.id || null;

      const conversation = [];
      for (const m of msgs) {
        if (!m) continue;
        if (m.id === asstMsgId) continue;
        if (lastUserId && m.id === lastUserId) continue;
        if (m.role !== 'user' && m.role !== 'assistant') continue;
        if (typeof m.content !== 'string') continue;
        if (!m.content.trim()) continue;
        conversation.push({ role: m.role, content: m.content });
        if (conversation.length >= 250) break;
      }

      // Best effort: preserve server-side conversation state by importing the UI history.
      try {
        const sess = await importSession(conversation, { profile: runProfile, model_id: runModelId });
        updateChat(chat.id, { sessionId: sess.session_id });
        return sess.session_id;
      } catch (e) {
        const sess = await createSession();
        updateChat(chat.id, { sessionId: sess.session_id });
        return sess.session_id;
      }
    }

    // One automatic retry if the server restarted and forgot our session id.
    let lastErr = null;
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        await streamChat(payload, onEvent, abortController.signal);
        lastErr = null;
        break;
      } catch (e) {
        if (e?.name === 'AbortError') {
          lastErr = e;
          break;
        }

        if (attempt === 1 && isInvalidSessionError(e)) {
          try {
            setStatus('reconnecting...', false);
            showToast('Session expired. Restoring...', 'info');

            const sid = await recoverServerSessionId();
            payload.session_id = sid;

            // Reset the assistant placeholder in case we partially rendered anything.
            const currentChat = getState().chats.get(chat.id);
            const asstMsg = currentChat?.messages?.find(m => m.id === asstMsgId);
            if (asstMsg) {
              asstMsg.content = '';
              asstMsg.toolCalls = [];
              asstMsg.status = 'streaming';
            }

            continue; // retry stream
          } catch (recoverErr) {
            lastErr = recoverErr;
            break;
          }
        }

        lastErr = e;
        break;
      }
    }

    if (lastErr) throw lastErr;

  } catch (e) {
    if (e.name === 'AbortError') {
      setStatus('stopped', true);
    } else {
      setStatus('error', false);
      showToast('Stream error: ' + e.message, 'error');
    }
    endRun('error');
  } finally {
    setState('ui', { streaming: false, abortController: null });
    if (_currentStreamEl) {
      _currentStreamEl.classList.remove('streaming-cursor');
      _currentStreamEl = null;
    }
    const finalChat = getState().chats.get(chat.id);
    if (finalChat) saveChat(finalChat);
    renderMessages();
  }
}

function setStatus(text, ok) {
  const statusText = document.getElementById('statusText');
  const statusChip = document.getElementById('statusChip');
  if (statusText) statusText.textContent = text;
  if (statusChip) {
    statusChip.classList.toggle('connected', ok);
    statusChip.classList.toggle('disconnected', !ok);
  }
}

export function stopStreaming() {
  const state = getState();
  if (state.ui.abortController) state.ui.abortController.abort();
}

export function stopSpeakingTts() {
  stopSpeaking();
}

export function scrollToMessage(messageId) {
  if (!_messagesEl || !_messagesInnerEl || !messageId) return;
  const target = _messagesInnerEl.querySelector(`.message[data-message-id="${CSS.escape(messageId)}"]`);
  if (!target) return;
  target.classList.add('highlight');
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  setTimeout(() => target.classList.remove('highlight'), 1600);
}

function editUserMessage(msg) {
  const chat = getActiveChat();
  if (!chat) return;
  const newText = prompt('Edit message:', typeof msg.content === 'string' ? msg.content : '');
  if (newText === null) return;
  const idx = chat.messages.findIndex(m => m.id === msg.id);
  if (idx >= 0) {
    chat.messages.splice(idx);
    updateChat(chat.id, { messages: chat.messages });
    saveChat(chat);
    renderMessages();
    if (newText.trim()) sendMessage(newText.trim());
  }
}

function retryFromMessage(msg) {
  const chat = getActiveChat();
  if (!chat) return;
  const idx = chat.messages.findIndex(m => m.id === msg.id);
  if (idx > 0) {
    const prevUser = chat.messages[idx - 1];
    chat.messages.splice(idx);
    updateChat(chat.id, { messages: chat.messages });
    saveChat(chat);
    renderMessages();
    if (prevUser && typeof prevUser.content === 'string') sendMessage(prevUser.content);
  }
}

export function updateCodeTheme(dark) {
  const light = document.getElementById('hljs-light');
  const darkSheet = document.getElementById('hljs-dark');
  if (light) light.disabled = dark;
  if (darkSheet) darkSheet.disabled = !dark;
}
