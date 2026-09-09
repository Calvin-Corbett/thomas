/* Shared parent-shell conversation drawer for resident workspace specialists. */
(function () {
  'use strict';

  const Transport = window.ThomasWorkspaceChatTransport;
  const View = window.ThomasWorkspaceChatDrawerView;
  if (!Transport || !View) return;
  const WORKSPACES = Transport.WORKSPACES;

  let host = { getContext: function () { return {}; } };
  let currentMode = '';
  let current = null;
  let drawer = null;
  let historyList = null;
  let searchInput = null;
  let thread = null;
  let title = null;
  let subtitle = null;
  let input = null;
  let sendButton = null;
  let status = null;
  let sessionId = null;
  let activeChat = '';
  let histories = [];
  let messages = [];
  let controller = null;

  function mount() {
    if (drawer) return drawer;
    const ui = View.create();
    if (!ui) return null;
    drawer = ui.drawer;
    historyList = ui.historyList;
    searchInput = ui.searchInput;
    thread = ui.thread;
    title = ui.title;
    subtitle = ui.subtitle;
    input = ui.input;
    sendButton = ui.sendButton;
    status = ui.status;
    ui.newButton.addEventListener('click', newConversation);
    ui.closeButton.addEventListener('click', closeDrawer);
    searchInput.addEventListener('input', renderHistories);
    ui.form.addEventListener('submit', submit);
    input.addEventListener('input', resizeInput);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        ui.form.requestSubmit();
      }
    });
    window.addEventListener('thomas:ui-edit-mode-change', function (event) {
      if (event.detail && event.detail.active) closeDrawer();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && isOpen() && !document.documentElement.classList.contains('thomas-ui-editing')) closeDrawer();
    });
    window.addEventListener('message', receiveWorkspaceRequest);
    renderThread();
    return drawer;
  }

  function primaryButton() { return document.getElementById('tc-canvas-btn'); }
  function primaryLabel() { return document.getElementById('tc-primary-action-label'); }
  function primaryIcon() { return document.getElementById('tc-primary-action-icon'); }

  function syncPrimaryAction() {
    const button = primaryButton();
    const label = primaryLabel();
    const icon = primaryIcon();
    if (!button || !label || !icon) return;
    if (current) {
      label.textContent = 'Chat';
      icon.className = 'ph ph-broadcast';
      button.title = 'Talk to Thomas in ' + current.label;
      button.dataset.workspaceChat = 'true';
      button.dataset.uiId = 'workspace-chat.action.toggle';
      button.dataset.uiLabel = 'Open resident Thomas in ' + current.label;
    } else {
      label.textContent = 'Canvas';
      icon.className = 'ph ph-chalkboard-simple';
      button.title = 'Open Thomas Canvas';
      delete button.dataset.workspaceChat;
      button.dataset.uiId = 'chat.action.canvas';
      button.dataset.uiLabel = 'Canvas button';
    }
    button.dataset.workspaceChatOpen = isOpen() ? 'true' : 'false';
    button.setAttribute('aria-expanded', isOpen() ? 'true' : 'false');
    button.setAttribute('aria-controls', 'tc-workspace-chat-drawer');
  }

  function setWorkspace(mode) {
    const nextMode = String(mode || '');
    const next = WORKSPACES[nextMode] || null;
    if (currentMode !== nextMode) {
      closeDrawer();
      currentMode = next ? nextMode : '';
      current = next;
      sessionId = null;
      activeChat = '';
      histories = [];
      messages = [];
      if (searchInput) searchInput.value = '';
      renderHistories();
      renderThread();
    } else current = next;
    if (title) title.textContent = current ? 'Thomas in ' + current.label : 'Thomas';
    if (subtitle) subtitle.textContent = current ? 'Direct ' + current.label + ' specialist' : 'Direct workspace specialist';
    syncPrimaryAction();
  }

  function isOpen() { return !!(drawer && drawer.classList.contains('is-open')); }

  function openDrawer(options) {
    mount();
    if (!drawer || !current) return false;
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    drawer.inert = false;
    syncPrimaryAction();
    loadHistories();
    const draft = options && String(options.draft || '').trim();
    if (draft) input.value = draft;
    resizeInput();
    requestAnimationFrame(function () { input.focus(); });
    return true;
  }

  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    drawer.inert = true;
    syncPrimaryAction();
    if (controller) controller.abort();
  }

  function toggle() { return isOpen() ? closeDrawer() : openDrawer(); }

  function newConversation() {
    if (controller) controller.abort();
    sessionId = null;
    activeChat = '';
    messages = [];
    status.textContent = '';
    renderHistories();
    renderThread();
    input.value = '';
    resizeInput();
    input.focus();
  }

  async function loadHistories() {
    if (!current) return;
    const expected = current.context;
    try {
      const nextHistories = await Transport.listHistories(expected);
      if (!current || current.context !== expected) return;
      if (nextHistories) histories = nextHistories;
      renderHistories();
    } catch (_error) {}
  }

  function renderHistories() {
    if (!historyList) return;
    View.renderHistories(historyList, searchInput, histories, activeChat, function (row) {
      if (controller) return;
      activeChat = row.id;
      sessionId = row.sessionId;
      messages = row.messages.slice();
      renderHistories();
      renderThread();
      input.focus();
    });
  }

  function renderThread() {
    if (!thread) return;
    View.renderThread(thread, messages, current);
  }

  function appendMessage(role, text) {
    const message = { role: role, text: String(text || '') };
    messages.push(message);
    renderThread();
    return message;
  }

  function resizeInput() {
    if (!input) return;
    View.resizeInput(input);
  }

  async function submit(event) {
    event.preventDefault();
    const prompt = String(input.value || '').trim();
    if (!prompt || controller || !current) return;
    const scoped = current;
    appendMessage('user', prompt);
    const reply = appendMessage('assistant', '');
    input.value = '';
    resizeInput();
    sendButton.disabled = true;
    status.textContent = 'Thomas is working directly in ' + scoped.label + '...';
    let answer = '';
    try {
      const context = host.getContext ? host.getContext() || {} : {};
      const dials = context.dials || {};
      const payload = {
        message: prompt,
        session_id: sessionId || undefined,
        surface_mode: 'workspace',
        context_id: scoped.context,
        profile: context.profile || undefined,
        model: context.profile || undefined,
        model_id: context.modelId || undefined,
        autonomy_level: dials.autonomy,
        file_access: dials.fileAccess,
        token_economy: dials.tokenEconomy,
        thomas_guardrails: dials.guardrails,
        reasoning_effort: dials.effort,
        memory: dials.memory !== false,
      };
      const turn = Transport.beginTurn(payload, {
        onSession: function (nextSessionId) { sessionId = nextSessionId; },
        onStatus: function (nextStatus) { status.textContent = nextStatus; },
        onAnswer: function (nextAnswer) { answer = nextAnswer; reply.text = answer; renderThread(); },
      });
      controller = turn.controller;
      answer = await turn.promise;
      if (!answer.trim()) reply.text = 'Thomas completed the workspace turn without a text response.';
    } catch (error) {
      if (error && error.name === 'AbortError') reply.text = reply.text || 'Stopped.';
      else reply.text = 'I could not complete that workspace action: ' + String(error && error.message || error);
    } finally {
      controller = null;
      sendButton.disabled = false;
      status.textContent = '';
      renderThread();
      await loadHistories();
      if (isOpen()) input.focus();
    }
  }

  function receiveWorkspaceRequest(event) {
    if (event.origin !== location.origin || !event.data || event.data.type !== 'thomas:workspace-chat:open') return;
    const requestedMode = String(event.data.mode || currentMode);
    if (requestedMode !== currentMode) return;
    openDrawer({ draft: String(event.data.draft || '') });
  }

  function connect(options) {
    host = Object.assign({}, host, options || {});
    mount();
    syncPrimaryAction();
  }

  window.ThomasWorkspaceChat = {
    connect: connect,
    setWorkspace: setWorkspace,
    open: openDrawer,
    close: closeDrawer,
    toggle: toggle,
    isOpen: isOpen,
    current: function () { return currentMode; },
  };
  mount();
}());
