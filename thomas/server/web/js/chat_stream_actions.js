/* Chat stream actions. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Send / stream (wired to the real Thomas backend: POST /api/v2/chat, NDJSON) ----------
    function send() {
      if (!deps.attachmentsReady()) return;
      if (window.ThomasChatModelSelection && !window.ThomasChatModelSelection.ensureCurrent(deps.inputEl)) return;
      const text = deps.state.input.trim(); if (!text) return;
      // A mid-reply send QUEUES, visibly, instead of silently vanishing (the old guard's drop); turnFlow auto-sends it when this reply finishes.
      // Chat's queue is for Chat: a reply still streaming here must not capture a message typed in Build or Work, which have queues of their own.
      const inChat = !window.ThomasUnifiedModes || window.ThomasUnifiedModes.mode() === 'chat';
      if (inChat && deps.state.streaming) { deps.turnFlow.enqueue(); return; }
      // A user re-sending (nearly) the same message means the first answer
      // didn't land — that's friction worth seeing in the report.
      const recentUser = deps.state.messages.filter(m => m.role === 'user').slice(-2);
      if (recentUser.some(m => { const a = String(m.text || '').toLowerCase().trim(), b = text.toLowerCase(); return a && (a === b || (a.length > 20 && (a.includes(b) || b.includes(a)))); })) {
        deps.reportFriction('same_message_retry', text);
      }
      const routed = window.ThomasUnifiedModes && window.ThomasUnifiedModes.send(text, {
        profile: deps.state.profile,
        modelId: deps.state.modelId,
        modelLabel: deps.state.modelLabel,
        ...(window.ThomasChatModelSelection && window.ThomasChatModelSelection.roleContext
          ? window.ThomasChatModelSelection.roleContext() : {}),
        dials: Object.assign({}, deps.state.dials),
        docs: deps.state.docs.slice(),
        images: deps.state.images.slice(),
      });
      // Refused by the mode: it has said why, and what you typed stays in the box.
      if (routed === 'refused') return;
      if (routed) {
        deps.state.input = ''; deps.inputEl.value = ''; deps.state.docs = []; deps.state.images = [];
        deps.renderAttachments(); deps.autosize(); deps.syncDynamic();
        return;
      }
      // What you attached rides on the message so the bubble can show it.
      const attached = window.ThomasAttachmentStrip ? window.ThomasAttachmentStrip.itemsFrom(deps.state.docs, deps.state.images) : [];
      deps.state.messages.push(attached.length ? { role: 'user', text, attachments: attached } : { role: 'user', text });
      deps.state.input = ''; deps.inputEl.value = '';
      deps.syncView(); deps.appendMessage(deps.state.messages[deps.state.messages.length - 1]);
      deps.autosize(); deps.syncDynamic(); deps.scrollEnd();
      // Only a visual worker may open the Canvas; sending records intent.
      deps._pendingCanvasIntent = !!deps.detectVisualIntent(text);
      streamReal(text);
    }

    function chunkText(evt) {
      if (typeof evt.text === 'string') return evt.text;
      if (typeof evt.delta === 'string') return evt.delta;
      if (typeof evt.content === 'string') return evt.content;
      return '';
    }

    function applyModelRuntimeReceipt(idx, runtime) {
      const active = runtime && runtime.active && typeof runtime.active === 'object' ? runtime.active : {};
      const observedId = String(active.model || '').trim();
      if (!observedId) return;
      const choice = deps.profilesData.flatMap(profile => Array.isArray(profile.models) ? profile.models : []).find(model => String(model && model.id || '') === observedId);
      const observedLabel = String(choice && (choice.display_name || choice.id) || observedId).split('/').pop();
      // Provenance without jargon: "· observed" meant "runtime-verified model"
      // but read as noise on every message. Plain label + tooltip; call out
      // only the exceptional case (a fallback model actually served this).
      const label = observedLabel + (runtime.failover_used === true ? ' · fallback used' : '');
      deps.state.messages[idx].model = label;
      const modelEl = deps.msgRefs[idx] && deps.msgRefs[idx].modelEl;
      if (modelEl) {
        modelEl.textContent = label;
        modelEl.title = runtime.failover_used === true
          ? 'Your usual model was unavailable — this reply came from the fallback shown'
          : 'Verified: this model produced this reply';
      }
    }
    async function streamReal(text, attachments) {
      if (window.ThomasChatModelSelection && !window.ThomasChatModelSelection.ensureCurrent(deps.inputEl)) {
        if (attachments && attachments.onFailed) attachments.onFailed('The selected model cannot send right now.');
        return;
      }
      const ownsConversation = deps.captureConversation(), controller = new AbortController();
      const isCurrent = () => ownsConversation() && deps.abortController === controller;
      const files = attachments || { docs: deps.state.docs.slice(), images: deps.state.images.slice() };
      if (!attachments) { deps.state.docs = []; deps.state.images = []; deps.renderAttachments(); }
      const base = { role: 'assistant', text: '', model: deps.state.modelLabel || '', streaming: true, activity: { thinking: '', steps: [], expanded: false, artifact: null, wantsCanvas: deps._pendingCanvasIntent } };
      deps._pendingCanvasIntent = false;
      deps.state.messages.push(base);
      let idx = deps.state.messages.indexOf(base);
      const syncIndex = () => { idx = deps.state.messages.indexOf(base); return idx; };
      deps.state.streaming = true; deps.setExternalBusy();
      if (deps.turnFlow && deps.turnFlow.refreshQueuedNotes) deps.turnFlow.refreshQueuedNotes();
      deps.appendMessage(base); deps.scrollEnd();
      deps.abortController = controller;
      let acc = '', sawText = false, reachedServer = false, networkFailed = false;
      const setText = (t) => { if (isCurrent() && syncIndex() !== -1) { base.text = t; deps.updateStreamingBubble(idx); deps.scrollEnd(); } };
      const painter = window.ThomasChatStreamConsumer.createTextPainter(setText);
      try {
        const payload = {
          message: text,
          session_id: deps.state.sessionId || undefined,
          surface_mode: 'chat',
          profile: deps.state.profile || undefined,
          model: deps.state.profile || undefined,
          model_id: deps.state.modelId || undefined,
          autonomy_level: deps.state.dials.autonomy,        // from the Tools panel
          file_access: deps.state.dials.fileAccess,
          thomas_guardrails: deps.state.dials.guardrails,
          reasoning_effort: deps.state.dials.effort,
          memory: !!deps.state.dials.memory,
          docs: files.docs, images: files.images,
        };
        payload.session_id = (await deps.ensureSession(controller.signal)) || undefined;
        if (!isCurrent()) return;
        if (controller.signal.aborted) throw new DOMException('Stopped', 'AbortError');
        const res = await fetch('/api/v2/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: controller.signal });
        if (!isCurrent()) return;
        if (!res.ok) throw new Error('HTTP ' + res.status);
        reachedServer = true;
        if (attachments && attachments.onAccepted) attachments.onAccepted();
        // Apply events only while this turn still owns the displayed conversation.
        await window.ThomasChatStreamConsumer.consume(res, (evt) => {
            if (!isCurrent() || syncIndex() === -1) return;
            const type = evt.type;
            if (type === 'text' || type === 'agent_text' || type === 'delta' || type === 'assistant_delta' || type === 'message_delta') {
              const c = chunkText(evt);
              if (c) { if (!sawText) { sawText = true; const a = deps.state.messages[idx].activity; if (a) { deps._settleActivityForReply(a); deps.renderActivity(idx); } } acc += c; painter.paint(acc); }
            } else if (type === 'thinking') {
              const c = String(evt.text || ''); if (c) { const a = deps.state.messages[idx].activity; a.thinking += c; if (!sawText) a.expanded = true; deps.renderActivity(idx); deps.scrollEnd(); }
            } else if (type === 'tool_start') {
              deps.addToolStep(idx, evt.name); deps.scrollEnd();
              // Thomas arming Redesign mode. The structured capability replaces
              // the natural-language UI control that was removed: the shell acts
              // on the tool NAME, never on anything he says in prose.
              if (evt.name === 'ui.redesign' && window.ThomasRedesign) window.ThomasRedesign.start();
            } else if (type === 'tool_result') {
              deps.finishToolStep(idx, evt.ok !== false);
            } else if (type === 'model_runtime') {
              applyModelRuntimeReceipt(idx, evt.runtime);
            } else if (type === 'delegation_started' || type === 'delegation_progress' || type === 'delegation_completed' || type === 'delegation_failed') {
              deps.handleHandoff(idx, evt); deps.scrollEnd();
            } else if (type === 'delegation') {
              // Internal specialist (e.g. "reasoning") — orchestration, NOT a real
              // worker handoff. Don't render a card; it's just Thomas thinking.
            } else if (type === 'task_phase' || type === 'task_definition' || type === 'task_evaluation') {
              deps.handleTaskContract(idx, evt); deps.scrollEnd();
            } else if (type === 'error') {
              acc += (acc ? '\n\n' : '') + '⚠ ' + (evt.error || 'error'); painter.paint(acc);
            } else if (type === 'done') {
              if (evt.session_id) deps.state.sessionId = evt.session_id;
              if (!sawText) { const d = chunkText(evt) || evt.final || evt.output_text; if (d) { acc += d; painter.paint(acc); } }
            }
        });
        if (!isCurrent() || syncIndex() === -1) return;
        painter.settle();
        if (!acc.trim()) { setText('— (no text returned)'); }
        await deps.maybePromptChatGPTConnection(acc);
      } catch (err) {
        networkFailed = err.name !== 'AbortError';
        if (attachments && attachments.onFailed && !reachedServer) attachments.onFailed('Network error; your message is still queued.');
        if (!isCurrent()) return;
        painter.settle(); // flush any queued frame first so the stop/error note lands after the streamed text, never under a stale repaint
        if (err && err.name === 'AbortError') acc += (acc ? '\n\n' : '') + '— [stopped]';
        else acc += (acc ? '\n\n' : '') + '⚠ ' + ((err && err.message) || 'request failed');
        setText(acc);
      } finally {
        painter.settle(); base.streaming = false;
        if (isCurrent() && syncIndex() !== -1) {
          deps.state.streaming = false; deps.abortController = null;
          deps.updateStreamingBubble(idx); deps.renderActivity(idx); deps.setExternalBusy(); deps.scrollEnd();
          const fa = deps.state.messages[idx].activity;
          deps.canvasDocumentDone(); // settle a live DOCUMENT (no-op for visual/worker canvases)
          if (fa && fa.steps.some(s => s.kind === 'handoff' && s.status === 'running')) deps.pollDelegations(idx);
          deps.refreshChats(); // Show the saved turn in Recent immediately.
          // Name the chat from its first prompt, and again from the whole chat after the fifth (the server decides).
          if (window.ThomasAutoTitle) window.ThomasAutoTitle.after(deps.state.sessionId, deps.state.messages.length, () => deps.refreshChats());
          if (!networkFailed) deps.turnFlow.drainQueued(); // never drain after a network failure
        }
      }
    }
    return { send, chunkText, applyModelRuntimeReceipt, streamReal };
  }
  window.ThomasChatStreamActions = { create };
})();
