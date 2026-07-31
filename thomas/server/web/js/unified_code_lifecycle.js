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
      // KNOWN, MEASURED 2026-07-31, deliberately not changed here.
      //
      // Anything that does not start with `gpt-` is sent as `claude:sonnet`, so
      // Code dispatches to the CLAUDE CLI. That is not a quirk of this line --
      // forge_code_settings.from_payload has exactly two families:
      //
      //     gpt = id.startswith("gpt-") or model.startswith(("gpt-", "codex", ...))
      //     if gpt:  family "gpt"      -> in-process ChatGPT (openai_codex)
      //     else:    family "claude"   -> the claude CLI
      //
      // So Code can only really run GPT or Claude. Picking a local qwen, a
      // Gemini or a Mistral in the model menu silently runs Claude instead.
      //
      // It also reports the wrong thing. `model_id` still carries what you
      // picked and that is what lands on the turn
      // (evolve_agent_routes: `settings.model_id or settings.dispatch_model`),
      // so a run is labelled with a model that had no part in it. Observed:
      // profile `local`, turn labelled `qwen2.5-coder:7b`, transcript ending
      // `claude exited 1` because the Claude CLI was not logged in. For that
      // request from_payload produced dispatch_model `claude:qwen2.5-coder:7b`
      // -- the Claude CLI asked to run qwen.
      //
      // Not fixed here because the honest options are product decisions, not
      // edits: stop offering models Code cannot run, say which engine will
      // actually handle the request, or record the DISPATCHED model on the turn
      // so the label matches the executor. Each changes what the owner sees or
      // what runs. See the matching note in forge_code_settings.from_payload.
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
    // Attachments ride the run request: photos as data URLs, docs as extracted
    // text. The server stages them into the project workspace so the Code agent
    // can actually read them (parity with chat's Add-files).
    const docs = Array.isArray(context.docs) ? context.docs.filter(d => d && d.name) : [];
    const images = Array.isArray(context.images) ? context.images.filter(im => im && im.data_url) : [];
    const base = {
      message,
      conversation_id: state.activeId || undefined,
      project_root: state.projectRoot || undefined,
      ...requestSettings(context),
    };
    if (docs.length) base.docs = docs;
    if (images.length) base.images = images;
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
