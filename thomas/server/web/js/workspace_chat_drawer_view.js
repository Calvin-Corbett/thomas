/* DOM construction and rendering for the resident workspace Chat drawer. */
(function () {
  'use strict';

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function create() {
    const body = document.getElementById('tc-body-row');
    if (!body) return null;
    const drawer = el('aside', 'tc-workspace-chat-drawer');
    drawer.id = 'tc-workspace-chat-drawer';
    drawer.setAttribute('aria-label', 'Thomas workspace conversation');
    drawer.setAttribute('aria-hidden', 'true');
    drawer.setAttribute('data-ui-id', 'workspace-chat.drawer');
    drawer.setAttribute('data-ui-label', 'Workspace Thomas drawer');
    drawer.setAttribute('data-ui-policy', 'resize protected');
    drawer.setAttribute('data-ui-constraints', 'minWidth=480;maxWidth=920;contain=chat.body');
    drawer.inert = true;

    const history = el('section', 'tc-workspace-chat-history');
    history.setAttribute('data-ui-id', 'workspace-chat.history');
    history.setAttribute('data-ui-label', 'Workspace conversations');
    history.setAttribute('data-ui-policy', 'layout-style');
    history.setAttribute('data-ui-constraints', 'minWidth=170;maxWidth=280;preserve-runtime-content');
    const historyHead = el('header', 'tc-workspace-chat-history-head');
    const historyTitle = el('h2', '', 'Conversations');
    const newButton = el('button', 'tc-workspace-chat-new', '+');
    newButton.type = 'button';
    newButton.title = 'New workspace conversation';
    newButton.setAttribute('aria-label', 'New workspace conversation');
    newButton.setAttribute('data-ui-id', 'workspace-chat.action.new');
    newButton.setAttribute('data-ui-policy', 'control protected');
    historyHead.append(historyTitle, newButton);
    const searchInput = el('input', 'tc-workspace-chat-search');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search this workspace';
    searchInput.setAttribute('aria-label', 'Search workspace conversations');
    const historyList = el('div', 'tc-workspace-chat-list tc-scroll');
    historyList.setAttribute('role', 'list');
    history.append(historyHead, searchInput, historyList);

    const main = el('section', 'tc-workspace-chat-main');
    main.setAttribute('data-ui-id', 'workspace-chat.conversation');
    main.setAttribute('data-ui-label', 'Resident Thomas conversation');
    main.setAttribute('data-ui-policy', 'layout-style');
    main.setAttribute('data-ui-constraints', 'minWidth=320;preserve-runtime-content');
    const mainHead = el('header', 'tc-workspace-chat-main-head');
    const mark = el('span', 'tc-workspace-chat-mark');
    mark.setAttribute('aria-hidden', 'true');
    mark.append(el('i'), el('i'));
    const copy = el('div');
    const title = el('h2', '', 'Thomas');
    const subtitle = el('p', '', 'Direct workspace specialist');
    copy.append(title, subtitle);
    const closeButton = el('button', 'tc-workspace-chat-icon-button', '\u00d7');
    closeButton.type = 'button';
    closeButton.title = 'Close workspace conversation';
    closeButton.setAttribute('aria-label', 'Close workspace conversation');
    closeButton.setAttribute('data-ui-id', 'workspace-chat.action.close');
    closeButton.setAttribute('data-ui-policy', 'control protected');
    mainHead.append(mark, copy, closeButton);
    const thread = el('div', 'tc-workspace-chat-thread tc-scroll');
    thread.setAttribute('role', 'log');
    thread.setAttribute('aria-live', 'polite');
    thread.setAttribute('data-ui-id', 'workspace-chat.thread');
    thread.setAttribute('data-ui-label', 'Workspace conversation messages');
    thread.setAttribute('data-ui-policy', 'layout-style');
    thread.setAttribute('data-ui-constraints', 'preserve-runtime-content,preserve-scroll');
    const status = el('div', 'tc-workspace-chat-status');
    status.setAttribute('role', 'status');
    const form = el('form', 'tc-workspace-chat-composer');
    form.setAttribute('data-ui-id', 'workspace-chat.composer');
    form.setAttribute('data-ui-label', 'Message resident Thomas');
    form.setAttribute('data-ui-policy', 'layout-style protected');
    form.setAttribute('data-ui-constraints', 'minHeight=58;preserve-handler');
    const input = el('textarea', 'tc-workspace-chat-input');
    input.rows = 1;
    input.placeholder = 'Tell Thomas what to do here...';
    input.setAttribute('aria-label', 'Message Thomas in this workspace');
    const sendButton = el('button', 'tc-workspace-chat-send', '\u2191');
    sendButton.type = 'submit';
    sendButton.title = 'Send to workspace Thomas';
    sendButton.setAttribute('aria-label', 'Send to workspace Thomas');
    sendButton.setAttribute('data-ui-id', 'workspace-chat.action.send');
    sendButton.setAttribute('data-ui-policy', 'control protected');
    form.append(input, sendButton);
    main.append(mainHead, thread, status, form);
    drawer.append(history, main);
    body.appendChild(drawer);
    return { drawer, historyList, searchInput, thread, title, subtitle, input, sendButton, status, form, newButton, closeButton };
  }

  function renderHistories(list, search, histories, activeChat, onSelect) {
    const query = String(search && search.value || '').trim().toLowerCase();
    const visible = histories.filter(function (row) { return !query || (row.title + '\n' + row.preview).toLowerCase().includes(query); });
    list.innerHTML = '';
    if (!visible.length) {
      list.appendChild(el('div', 'tc-workspace-chat-empty', query ? 'No matching conversations.' : 'No conversations in this workspace yet.'));
      return;
    }
    visible.forEach(function (row) {
      const button = el('button', 'tc-workspace-chat-history-row');
      button.type = 'button';
      button.setAttribute('role', 'listitem');
      button.setAttribute('aria-current', row.id === activeChat ? 'true' : 'false');
      button.setAttribute('data-ui-id', 'workspace-chat.history.item.' + row.id.replace(/[^a-zA-Z0-9_-]/g, '-'));
      button.setAttribute('data-ui-instance-key', row.id);
      button.setAttribute('data-ui-policy', 'style-only');
      button.append(el('strong', '', row.title), el('small', '', row.preview || 'Workspace conversation'));
      button.addEventListener('click', function () { onSelect(row); });
      list.appendChild(button);
    });
  }

  function renderThread(thread, messages, current) {
    thread.innerHTML = '';
    if (!messages.length) {
      const welcome = el('div', 'tc-workspace-chat-welcome');
      welcome.append(el('strong', '', current ? 'Thomas is already here.' : 'Open a workspace to begin.'), el('span', '', current ? current.hint : 'Workspace conversations stay with their workspace.'));
      thread.appendChild(welcome);
      return;
    }
    messages.forEach(function (message) {
      const article = el('article', 'tc-workspace-chat-message is-' + message.role);
      article.append(el('small', '', message.role === 'user' ? 'You' : 'Thomas'), el('div', 'tc-workspace-chat-bubble', message.text));
      thread.appendChild(article);
    });
    thread.scrollTop = thread.scrollHeight;
  }

  function resizeInput(input) {
    input.style.height = 'auto';
    input.style.height = Math.min(150, Math.max(30, input.scrollHeight)) + 'px';
  }

  window.ThomasWorkspaceChatDrawerView = { create, renderHistories, renderThread, resizeInput };
}());
