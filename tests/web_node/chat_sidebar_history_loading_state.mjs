// The sidebar must never assert "No chats yet." before the history fetch has
// actually answered, and the active conversation must survive a history
// refresh that does not know about it yet.
//
// Drives the real renderSidebarChatList() and fetchChatHistory() from
// js/runtime/039_module_rendering_dispatch_02.js in a vm context.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
if (!sourcePath) throw new Error('usage: node chat_sidebar_history_loading_state.mjs <039_module_rendering_dispatch_02.js>');
const source = fs.readFileSync(sourcePath, 'utf8');

function functionSource(name) {
  const patterns = [`\nfunction ${name}(`, `\nasync function ${name}(`];
  let start = -1;
  for (const p of patterns) {
    start = source.indexOf(p);
    if (start >= 0) break;
  }
  if (start < 0) throw new Error(`could not extract ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function [A-Za-z_$]/);
  const end = next < 0 ? source.length : start + 1 + next;
  return source.slice(start, end);
}

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.className = '';
    this.textContent = '';
    this.type = '';
    this._innerHTML = '';
    this.classList = { add() {}, remove() {}, contains() { return false; } };
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    if (this._innerHTML === '') this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  appendChild(el) {
    this.children.push(el);
    return el;
  }

  addEventListener() {}
}

const sidebarChatList = new FakeElement('div');
const log = { syncActiveCalls: 0 };

const context = {
  console,
  document: { createElement: (tag) => new FakeElement(tag) },
  safeString: (value) => (value === null || value === undefined ? '' : String(value)),
  escapeHtml: (value) => String(value),
  withAgentName: (value) => String(value).replace('{{agent}}', 'Thomas'),
  formatSidebarSessionTitle: (session) => String(session?.title || ''),
  formatSidebarSessionMeta: () => 'meta',
  loadSessionFromHistory: async () => {},
  rebuildChatHistorySelector: () => {},
  updateDebugDockSnapshot: () => {},
  syncActiveChatSidebarEntry: () => { log.syncActiveCalls += 1; },
  mapPersistedChatToSidebarSession: (row) => (row && row.id
    ? { id: String(row.id), title: String(row.title || row.id), updatedAt: Number(row.updatedAt || 0) }
    : null),
  mapLegacySidebarSession: () => null,
  fetchJsonSafe: async () => ({ ok: true, data: { chats: [] } }),
  sidebarChatList,
  sidebarSessions: [],
  sidebarSearchScope: 'chat',
  sidebarHistoryLoadState: 'pending',
  globalSearchInput: null,
  activeChatId: '',
  sessionId: '',
  chatHistory: [],
};
vm.createContext(context);
vm.runInContext(
  [
    functionSource('renderSidebarChatList'),
    functionSource('fetchChatHistory'),
  ].join('\n'),
  context,
);

const checks = {};

function emptyNoteText() {
  const note = sidebarChatList.children.find((child) => child.className === 'sidebar-chat-empty');
  return note ? String(note.textContent) : '';
}

// 1. Before the history fetch has answered, an empty list is UNKNOWN, not empty.
context.sidebarHistoryLoadState = 'pending';
context.sidebarSessions = [];
vm.runInContext('renderSidebarChatList()', context);
const pendingText = emptyNoteText();
checks.pendingNeverClaimsNoChats = !/no chats yet/i.test(pendingText);
checks.pendingSaysLoading = /loading/i.test(pendingText);

// 2. A failed fetch is named, not passed off as an empty history.
context.sidebarHistoryLoadState = 'error';
vm.runInContext('renderSidebarChatList()', context);
const errorText = emptyNoteText();
checks.errorNeverClaimsNoChats = !/no chats yet/i.test(errorText);
checks.errorIsNamed = /could not|failed|unavailable/i.test(errorText);

// 3. Only a CONFIRMED empty history may say "No chats yet."
context.sidebarHistoryLoadState = 'loaded';
vm.runInContext('renderSidebarChatList()', context);
checks.confirmedEmptySaysNoChats = /no chats yet/i.test(emptyNoteText());

// 4. fetchChatHistory marks the state loaded on success ...
context.sidebarHistoryLoadState = 'pending';
await vm.runInContext('fetchChatHistory()', context);
checks.fetchMarksLoaded = context.sidebarHistoryLoadState === 'loaded';

// 5. ... and re-seats the active conversation when the server list does not
//    contain it yet (the user just sent; the first reply has not completed).
context.sidebarHistoryLoadState = 'pending';
context.activeChatId = 'live-1';
context.chatHistory = [{ role: 'user', content: 'change tuesday to 9' }];
context.fetchJsonSafe = async () => ({
  ok: true,
  data: { chats: [{ id: 'old-chat', title: 'Older chat', updatedAt: 5 }] },
});
log.syncActiveCalls = 0;
await vm.runInContext('fetchChatHistory()', context);
checks.activeChatReseated = log.syncActiveCalls === 1;

// 6. An active chat the server DOES know is not double-inserted.
context.activeChatId = 'old-chat';
context.chatHistory = [{ role: 'user', content: 'hello' }];
log.syncActiveCalls = 0;
await vm.runInContext('fetchChatHistory()', context);
checks.knownActiveChatNotReseated = log.syncActiveCalls === 0;

// 7. A failed fetch that never loaded marks the error state.
context.sidebarHistoryLoadState = 'pending';
context.fetchJsonSafe = async () => { throw new Error('network down'); };
await vm.runInContext('fetchChatHistory()', context);
checks.fetchFailureMarksError = context.sidebarHistoryLoadState === 'error';

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`sidebar loading-state checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
