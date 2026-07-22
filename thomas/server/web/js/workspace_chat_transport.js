/* Namespaced history and streaming transport for resident workspace specialists. */
(function () {
  'use strict';

  const WORKSPACES = Object.freeze({
    mission: { context: 'workspace:mission', label: 'Mission Control', hint: 'Operate missions, approvals, schedules, and live work here.' },
    office: { context: 'workspace:office', label: 'Virtual Office', hint: 'Arrange and operate the live office with its resident Thomas.' },
    app_builder: { context: 'workspace:app_builder', label: 'Canvas', hint: 'Create, revise, model, and export directly on this canvas.' },
    my_stuff: { context: 'workspace:my_stuff', label: 'Library', hint: 'Find, organize, open, and manage the things Thomas has made.' },
    channels: { context: 'workspace:channels', label: 'Channels', hint: 'Configure and operate Thomas communication channels directly.' },
    token_economy: { context: 'workspace:token_economy', label: 'Token Economy', hint: 'Inspect and change allowed runtime economy controls here.' },
    marketplace: { context: 'workspace:marketplace', label: 'Marketplace', hint: 'Discover and manage proof-eligible Thomas capabilities.' },
    settings: { context: 'workspace:settings', label: 'Settings', hint: 'Inspect and update Thomas preferences directly.' },
    paper_trading: { context: 'workspace:paper_trading', label: 'Paper Trading', hint: 'Research and operate the simulated portfolio directly.' },
  });

  function mapMessages(rows) {
    return (Array.isArray(rows) ? rows : []).map(function (row) {
      return { role: row && row.role === 'assistant' ? 'assistant' : 'user', text: String(row && (row.content !== undefined ? row.content : row.text) || '') };
    }).filter(function (row) { return row.text; });
  }

  function normalizeHistories(payload) {
    return (Array.isArray(payload && payload.chats) ? payload.chats : []).map(function (row) {
      const rowMessages = mapMessages(row.messages);
      const first = rowMessages.find(function (message) { return message.role === 'user'; });
      return {
        id: String(row.id || row.sessionId || row.session_id || ''),
        sessionId: String(row.sessionId || row.session_id || row.id || ''),
        title: String(row.title || (first && first.text) || 'Workspace conversation'),
        preview: String(row.preview || (first && first.text) || '').slice(0, 90),
        messages: rowMessages,
        updatedAt: Number(row.updatedAt || row.createdAt || 0),
      };
    }).filter(function (row) { return row.id; });
  }

  async function listHistories(context) {
    const response = await fetch('/api/chats?mode=workspace&context_id=' + encodeURIComponent(context), { cache: 'no-store' });
    if (!response.ok) return null;
    return normalizeHistories(await response.json());
  }

  function eventText(event) {
    if (typeof event.text === 'string') return event.text;
    if (typeof event.delta === 'string') return event.delta;
    if (typeof event.content === 'string') return event.content;
    return '';
  }

  function beginTurn(payload, observer) {
    const controller = new AbortController();
    return { controller: controller, promise: streamTurn(payload, observer || {}, controller.signal) };
  }

  async function streamTurn(payload, observer, signal) {
    const response = await fetch('/api/v2/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: signal,
    });
    if (!response.ok || !response.body) {
      let detail = '';
      try { detail = String((await response.json()).error || ''); } catch (_error) {}
      throw new Error(detail || 'Workspace Thomas returned HTTP ' + response.status);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let answer = '';
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(function (line) {
        let item;
        try { item = JSON.parse(line); } catch (_error) { return; }
        if (item.session_id && observer.onSession) observer.onSession(String(item.session_id));
        if (['text', 'agent_text', 'delta', 'assistant_delta', 'message_delta'].includes(item.type)) answer += eventText(item);
        if (item.type === 'done' && !answer) answer = eventText(item) || String(item.final || item.output_text || '');
        if (item.type === 'tool_start' && observer.onStatus) observer.onStatus('Using ' + String(item.name || 'the workspace tools') + '...');
        if (item.type === 'tool_result' && observer.onStatus) observer.onStatus(item.ok === false ? 'A workspace action was safely refused.' : 'Verifying the workspace change...');
        if (item.type === 'tool_result' && item.ok !== false && payload.context_id === 'workspace:office') {
          window.dispatchEvent(new CustomEvent('thomas:office-state:refresh'));
          const refresh = { type: 'thomas:office-state:refresh' };
          document.querySelectorAll('iframe').forEach(function (frame) {
            if (frame.contentWindow) frame.contentWindow.postMessage(refresh, location.origin);
          });
          if (window.parent !== window) window.parent.postMessage(refresh, location.origin);
        }
        if (item.type === 'error') answer += (answer ? '\n\n' : '') + String(item.error || 'Workspace action failed.');
        if (observer.onAnswer) observer.onAnswer(answer);
      });
    }
    return answer;
  }

  window.ThomasWorkspaceChatTransport = {
    WORKSPACES: WORKSPACES,
    beginTurn: beginTurn,
    listHistories: listHistories,
  };
}());
