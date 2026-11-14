/* Chat session restore. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Top-level actions ----------
    function newChat() {
      if (window.ThomasUnifiedModes && window.ThomasUnifiedModes.newConversation()) return;
      deps.chatSelectionToken += 1;
      deps.showChat();
      if (deps.abortController) { try { deps.abortController.abort(); } catch (e) {} deps.abortController = null; }
      if (deps.timer) { clearInterval(deps.timer); deps.timer = null; }
      deps.state.messages = []; deps.state.activeChat = null; deps.state.streaming = false; deps.state.input = ''; deps.state.artifactOpen = false; deps.state.sessionId = null; deps.state.docs = []; deps.state.images = []; deps.renderAttachments();
      // Deliberate new chat: forget the restore target.
      try { localStorage.removeItem('thomas_last_chat'); localStorage.removeItem('thomas_last_session'); } catch (e) {}
      deps.inputEl.value = ''; deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
      deps.resetCanvasForConversation(); deps.renderChats(); deps.syncView(); deps.autosize(); deps.syncDynamic();
      // ask the backend for a fresh session (harmless 404 on the static preview)
      void deps.ensureSession();
    }

    async function restoreVerifiedChatArtifacts(chatId, sessionId, selectionToken) {
      const sid = String(sessionId || '');
      if (!sid) return;
      try {
        const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations');
        if (!r.ok) return;
        const d = await r.json();
        if (selectionToken !== deps.chatSelectionToken || deps.state.activeChat !== chatId || String(deps.state.sessionId || '') !== sid) return;
        const sessionRows = (Array.isArray(d.delegations) ? d.delegations : [])
          .filter(row => String(row.session_id || '') === sid && deps._completionVerified(row))
          .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')));
        const reviewedCanvasRows = sessionRows.filter(row => deps._canvasReviewed(row, true));
        const reviewedCanvas = reviewedCanvasRows.length ? reviewedCanvasRows[reviewedCanvasRows.length - 1] : null;
        // The in-memory Canvas stream is lost when Thomas restarts, but its reviewed
        // execution record and verified HTML artifact remain durable. Preserve that
        // artifact as the explicit-open fallback; selection itself still stays closed.
        const durableCanvasRows = sessionRows.map(row => {
          const profile = row && row.runtime_profile && typeof row.runtime_profile === 'object' ? row.runtime_profile : {};
          const wasCanvas = row && (row.is_canvas === true || profile.canvas === true || String(profile.canvas || '').toLowerCase() === 'true');
          const webArtifact = (Array.isArray(row && row.artifacts) ? row.artifacts : []).find(artifact => {
            const kind = String((artifact && artifact.kind) || '').toLowerCase();
            const name = String((artifact && (artifact.name || artifact.path)) || '');
            return !!(artifact && artifact.url && (kind === 'web' || /\.html?(?:$|[?#])/i.test(name)));
          });
          return wasCanvas && webArtifact ? { row, artifact: webArtifact } : null;
        }).filter(Boolean);
        const durableCanvasEntry = durableCanvasRows.length ? durableCanvasRows[durableCanvasRows.length - 1] : null;
        const durableCanvas = durableCanvasEntry && durableCanvasEntry.row;
        const durableCanvasArtifact = durableCanvasEntry && durableCanvasEntry.artifact;
        deps.state.restoredCanvas = reviewedCanvas ? {
          chatId,
          sessionId: sid,
          executionId: String(reviewedCanvas.execution_id || ''),
          mode: String(reviewedCanvas.canvas_mode || 'live'),
          html: String(reviewedCanvas.canvas_html || ''),
          shell: String(reviewedCanvas.canvas_shell || ''),
          elements: Array.isArray(reviewedCanvas.canvas_elements) ? reviewedCanvas.canvas_elements.slice() : [],
        } : durableCanvas ? {
          chatId,
          sessionId: sid,
          executionId: String(durableCanvas.execution_id || ''),
          mode: 'render',
          url: String(durableCanvasArtifact.url || ''),
          name: String(durableCanvasArtifact.name || durableCanvasArtifact.path || 'Canvas'),
          kind: String(durableCanvasArtifact.kind || 'web'),
        } : null;
        const media = window.ThomasChatMediaBridge.restoreReplies(deps.state.messages, sessionRows);
        if (media.restored) {
          deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
          deps.state.messages.forEach((message, index) => deps.threadEl.appendChild(deps.buildMessageNode(message, index)));
          if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
        }
        const rows = media.rows.filter(row => Array.isArray(row.artifacts) && row.artifacts.length);
        if (!rows.length) return;
        let idx = deps.state.messages.length - 1;
        while (idx >= 0 && deps.state.messages[idx].role !== 'assistant') idx -= 1;
        if (idx < 0) return;
        const activity = { thinking: '', steps: [], expanded: false, artifacts: [], artifact: null, artifactOpen: false, wantsCanvas: false, expectedHandoffCount: rows.length };
        rows.forEach(row => {
          const verifiedNames = row.artifacts.map(art => String((art && (art.name || art.path)) || '')).filter(Boolean);
          const verifiedLabel = verifiedNames.length === 1 ? ('Verified ' + verifiedNames[0]) : (verifiedNames.length > 1 ? (verifiedNames.length + ' verified deliverables') : 'Verified result');
          activity.steps.push({
            kind: 'handoff',
            id: String(row.execution_id || ''),
            worker: String(row.bot_name || row.specialist_id || 'worker'),
            label: verifiedLabel || 'Verified result',
            status: 'completed',
          });
          deps._mergeArtifacts(activity, row);
        });
        if (!activity.artifacts.length || selectionToken !== deps.chatSelectionToken || deps.state.activeChat !== chatId) return;
        deps.state.messages[idx].activity = activity;
        deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
        deps.state.messages.forEach((message, messageIndex) => deps.threadEl.appendChild(deps.buildMessageNode(message, messageIndex)));
        if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
        deps.syncDynamic(); deps.scrollEnd();
      } catch (e) {}
    }

    // Restore the task activity card when you return to a chat. Running rows come
    // back LIVE (controls + polling — the worker never stopped, only the visual was
    // lost); finished/failed/stopped rows come back as a settled card. Before this,
    // only running rows were restored, so a failed task's revisit showed the stale
    // "On it" sentence with the card that explained it gone. Row classification lives
    // in ThomasChatTurnFlow with the server-aligned terminal states ('verified'/'abandoned' included, which the old inline list missed).
    async function restoreDelegationCards(chatId, sessionId, selectionToken) {
      const sid = String(sessionId || '');
      if (!sid) return;
      let rows;
      try {
        const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations');
        if (!r.ok) return;
        const d = await r.json();
        rows = Array.isArray(d.delegations) ? d.delegations : [];
      } catch (e) { return; }
      if (selectionToken !== deps.chatSelectionToken || deps.state.activeChat !== chatId || String(deps.state.sessionId || '') !== sid) return;
      const plan = window.ThomasChatTurnFlow.planDelegationRestore(window.ThomasChatMediaBridge.unannouncedRows(deps.state.messages, rows), sid, deps.state.messages);
      if (!plan.steps.length) return;
      let idx = plan.anchorIdx;
      if (idx < 0) { deps.state.messages.push({ role: 'assistant', text: '', model: deps.state.modelLabel || '' }); idx = deps.state.messages.length - 1; }
      const a = deps.state.messages[idx].activity || { thinking: '', steps: [], expanded: false, artifacts: [], artifact: null, artifactOpen: false, wantsCanvas: false, expectedHandoffCount: 0 };
      window.ThomasChatTurnFlow.mergeRestoredSteps(a, plan);
      deps.state.messages[idx].activity = a;
      deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
      deps.state.messages.forEach((message, messageIndex) => deps.threadEl.appendChild(deps.buildMessageNode(message, messageIndex)));
      if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
      deps.syncDynamic(); deps.scrollEnd();
      if (plan.anyRunning) deps.pollDelegations(idx);
    }

    let renderedThreadSignature = null;

    function threadRenderSignature(messages) {
      try { return JSON.stringify(messages); } catch (error) { return null; }
    }

    async function hydrateSelectedChat(chat, selectionToken) {
      return window.ThomasChatTurnFlow.hydrateSelectedChat({
        state: deps.state, fetch, signature: threadRenderSignature, mapMessages: (...args) => deps.mapRealMessages(...args),
        ownsSelection: (row, token, sid) => token === deps.chatSelectionToken && deps.state.activeChat === row.id && String(deps.state.sessionId || '') === sid,
        paint: () => {
          const signature = threadRenderSignature(deps.state.messages);
          // A queued bubble can outlive the transcript object that hydration replaces.
          if (signature === null || signature !== renderedThreadSignature ||
              (deps.turnFlow && deps.turnFlow.queuedCount && deps.turnFlow.queuedCount())) {
            deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
            deps.state.messages.forEach((message, index) => deps.threadEl.appendChild(deps.buildMessageNode(message, index)));
            renderedThreadSignature = signature;
          }
          if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
          renderedThreadSignature = threadRenderSignature(deps.state.messages);
          deps.syncView(); deps.syncDynamic(); deps.scrollEnd();
        },
      }, chat, selectionToken);
    }

    function selectChat(id) {
      const selectionToken = ++deps.chatSelectionToken;
      deps.showChat();
      if (deps.abortController) { try { deps.abortController.abort(); } catch (e) {} deps.abortController = null; }
      if (deps.timer) { clearInterval(deps.timer); deps.timer = null; }
      const c = deps.chatList.find(x => x.id === id);
      // Keep the selected session across reloads.
      try { localStorage.setItem('thomas_last_chat', id); if (c && c.sessionId) localStorage.setItem('thomas_last_session', c.sessionId); } catch (e) {}
      deps.state.activeChat = id; deps.state.streaming = false; deps.state.input = ''; deps.state.artifactOpen = false;
      deps.state.sessionId = c && c.sessionId || null; deps.state.docs = []; deps.state.images = []; deps.renderAttachments();
      deps.inputEl.value = ''; deps.threadEl.innerHTML = ''; deps.msgRefs.length = 0;
      deps.state.messages = c ? c.msgs.map(m => Object.assign({}, m)) : [];
      deps.resetCanvasForConversation(); deps.renderChats(); deps.syncView();
      deps.state.messages.forEach((m, i) => deps.threadEl.appendChild(deps.buildMessageNode(m, i)));
      renderedThreadSignature = threadRenderSignature(deps.state.messages);
      if (deps.turnFlow && deps.turnFlow.restoreQueued) deps.turnFlow.restoreQueued();
      deps.autosize(); deps.syncDynamic(); deps.scrollEnd();
      if (!c || !c.sessionId) return Promise.resolve(false);
      return hydrateSelectedChat(c, selectionToken).finally(() => {
        if (selectionToken !== deps.chatSelectionToken || deps.state.activeChat !== id) return;
        restoreVerifiedChatArtifacts(id, c.sessionId, selectionToken).then(() => restoreDelegationCards(id, c.sessionId, selectionToken));
      });
    }

    function fillAndSend(text) { deps.state.input = text; deps.inputEl.value = text; deps.autosize(); deps.send(); }

    function toggleSidebar() {
      if (window.matchMedia('(max-width: 760px)').matches) {
        deps.shell.classList.toggle('is-mobile-sidebar-open');
        return;
      }
      const cur = deps.shell.style.getPropertyValue('--sidebar-margin');
      deps.shell.style.setProperty('--sidebar-margin', cur === '-280px' ? '0px' : '-280px');
    }
    return { newChat, restoreVerifiedChatArtifacts, restoreDelegationCards, threadRenderSignature, hydrateSelectedChat, selectChat, fillAndSend, toggleSidebar };
  }
  window.ThomasChatSessionRestore = { create };
})();
