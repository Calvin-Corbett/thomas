(function () {
  'use strict';

  function requestId(prefix) {
    const random = globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function'
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}-${random}`;
  }

  function requestSettings(context) {
    const dials = context.dials || {};
    const modelId = String(context.modelId || '');
    return {
      engine: 'agent',
      model: modelId.startsWith('gpt-') ? modelId : 'claude:sonnet',
      model_id: modelId,
      reasoning_effort: dials.effort || 'medium',
      autonomy_level: dials.autonomy || 3,
      file_access: dials.fileAccess || 'project',
      memory: dials.memory !== false,
      thomas_guardrails: dials.guardrails || 'guarded',
      token_economy: dials.tokenEconomy || 'balanced',
    };
  }

  function runRequest(state, message, context) {
    const base = {
      message,
      conversation_id: state.activeId || undefined,
      project_root: state.projectRoot || undefined,
      ...requestSettings(context),
    };
    const retry = state.retryRequest;
    if (retry && retry.message === base.message && retry.conversation_id === base.conversation_id && retry.project_root === base.project_root) return { ...retry };
    return { ...base, request_id: requestId('run') };
  }

  function contextToken(state) {
    return { epoch: state.contextEpoch, id: state.activeId };
  }

  function contextMatches(state, token) {
    return Boolean(token && token.epoch === state.contextEpoch && token.id === state.activeId);
  }

  function registerRunProof(state, conversationId, runId) {
    state.runProof = { conversationId, runId };
  }

  function runIsDurable(conversation, proof) {
    const turns = conversation && Array.isArray(conversation.turns) ? conversation.turns : [];
    return Boolean(proof && conversation && conversation.id === proof.conversationId && turns.some(turn => turn.role === 'agent' && turn.run_id === proof.runId));
  }

  function adoptRunIdentity(state, runId) {
    const next = String(runId || '');
    if (state.runId !== next) state.eventCursor = 0;
    state.runId = next;
  }

  function acceptEvent(state, payload) {
    if (payload.run_id && state.runId && payload.run_id !== state.runId) return false;
    const sequence = Number(payload.event_seq || 0);
    if (sequence && sequence <= state.eventCursor) return false;
    if (sequence) state.eventCursor = sequence;
    return true;
  }

  function streamUrl(state) {
    const params = new URLSearchParams();
    if (state.runId) params.set('run_id', state.runId);
    if (state.eventCursor) params.set('cursor', String(state.eventCursor));
    const query = params.toString();
    return `/api/evolve/agent/stream${query ? `?${query}` : ''}`;
  }

  function changeRequest(action, file, conversationId, approvalId, requestIdValue) {
    const body = { file, conversation_id: conversationId, request_id: requestIdValue || requestId(action) };
    if (approvalId) body.approval_id = approvalId;
    return body;
  }

  window.ThomasCodeLifecycle = {
    acceptEvent,
    adoptRunIdentity,
    changeRequest,
    contextMatches,
    contextToken,
    registerRunProof,
    requestSettings,
    runIsDurable,
    runRequest,
    streamUrl,
  };
})();
