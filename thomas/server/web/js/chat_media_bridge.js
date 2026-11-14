/* Keep media jobs attached to their initiating Chat reply and conversation. */
(function () {
  'use strict';
  let sync = () => {};

  function mapMetadata(mapped, message) {
    const metadata = message && typeof message.metadata === 'object' && message.metadata || {};
    if (metadata.media_artifact) mapped.mediaArtifact = metadata.media_artifact;
    if (metadata.announce) mapped.announceId = String(metadata.announce);
    if (Array.isArray(metadata.artifacts)) mapped.artifacts = metadata.artifacts.filter(art => art && (art.url || art.name));
    return mapped;
  }

  function unannouncedRows(messages, rows) {
    const announced = new Set(messages.filter(message => message.announceId).map(message => String(message.announceId)));
    return rows.filter(row => !announced.has(String(row.execution_id || '')));
  }

  function restoreReplies(messages, rows) {
    const announced = new Map(messages.filter(message => message.announceId).map(message => [String(message.announceId), message]));
    let restored = false;
    rows.forEach(row => {
      const message = announced.get(String(row.execution_id || ''));
      if (!message || !Array.isArray(row.artifacts) || !row.artifacts.length) return;
      message.artifacts = row.artifacts.filter(art => art && (art.url || art.name));
      restored = true;
    });
    return { restored, rows: unannouncedRows(messages, rows) };
  }

  function bind(deps) {
    const { state, inputEl, captureConversation, ensureSession, isChatBusy, attachmentsReady,
      appendMessage, updateStreamingBubble, buildMessageNode, threadEl, renderActivity,
      autosize, syncDynamic, syncView, scrollEnd, refreshChats } = deps;
    const active = () => state.surfaceMode === 'chat';
    let ownsContext = captureConversation(), surface = state.surfaceMode;
    function repaint(message) {
      const index = state.messages.indexOf(message);
      if (index < 0 || !active()) return;
      const previous = threadEl.children[index];
      if (previous) threadEl.replaceChild(buildMessageNode(message, index), previous);
      scrollEnd();
    }
    function add(role, text, streaming = false) {
      const message = { role, text: String(text || ''), streaming, ...(role === 'assistant' ? { model: 'Media' } : {}) };
      state.messages.push(message); syncView(); appendMessage(message); scrollEnd();
      return message;
    }
    window.ThomasMediaGeneration.init({
      captureConversation() { const owns = captureConversation(); return () => owns() && active(); },
      canCreate() {
        if (!active()) return false;
        if (isChatBusy()) {
          inputEl.setCustomValidity('Wait for the current reply before creating media.'); inputEl.reportValidity();
          return false;
        }
        return attachmentsReady();
      },
      isStopAction: () => isChatBusy() && !inputEl.value.trim(),
      prompt: () => inputEl.value.trim(),
      consumePrompt(prompt) {
        if (inputEl.value.trim() !== prompt) return;
        inputEl.value = ''; state.input = ''; autosize(); syncDynamic();
      },
      ensureSession,
      sessionId: () => state.sessionId || '',
      conversationToken: () => state.messages,
      addUser: text => add('user', text),
      addAssistant: (text, streaming) => add('assistant', text, streaming),
      progress(message, text) {
        message.text = String(text || ''); message.streaming = true;
        const index = state.messages.indexOf(message);
        if (index >= 0 && active()) updateStreamingBubble(index);
      },
      started(message, jobId, medium) {
        message.activity = { thinking: '', steps: [{ kind: 'handoff', id: jobId, worker: 'Create ' + medium,
          label: 'Generating ' + medium, status: 'running' }], expanded: false, artifacts: [], artifact: null };
        const index = state.messages.indexOf(message);
        if (index >= 0 && active()) { renderActivity(index); syncDynamic(); }
      },
      finish(message, text, artifact, announcementId, status = 'failed') {
        message.text = String(text || ''); message.streaming = false;
        if (artifact) message.artifacts = [artifact];
        if (announcementId) message.announceId = String(announcementId);
        if (message.activity) {
          message.activity.steps.forEach(step => { step.status = status; step.label = message.text; });
          message.activity.cancelled = status === 'cancelled';
          message.activity.artifactMovedToAnnouncement = !!artifact;
        }
        repaint(message);
        if (state.messages.includes(message) && active()) syncDynamic();
        void refreshChats();
      },
    });
    sync = () => {
      if (ownsContext() && surface === state.surfaceMode) return;
      ownsContext = captureConversation(); surface = state.surfaceMode;
      window.ThomasMediaGeneration.resetContext();
      window.ThomasCreateMenu?.close();
    };
  }

  window.ThomasChatMediaBridge = { bind, mapMetadata, restoreReplies, unannouncedRows, syncContext: () => sync() };
})();
