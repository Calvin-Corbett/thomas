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
      // It used to report the wrong thing as well. `model_id` carries what you
      // picked, and that is what landed on the turn (evolve_agent_routes passed
      // `settings.model_id or settings.dispatch_model`), so a run was labelled
      // with a model that had no part in it. Observed: profile `local`, turn
      // labelled `qwen2.5-coder:7b`, transcript ending `claude exited 1` because
      // the Claude CLI was not logged in. For that request from_payload produced
      // dispatch_model `claude:qwen2.5-coder:7b` -- the Claude CLI asked to run
      // qwen.
      //
      // That half is fixed: `ForgeCodeSettings.recorded_model()` reports the
      // executor, and the capability report marks the model dial "substituted"
      // with a reason instead of "applied". Nothing about what RUNS changed.
      //
      // Still open, and still a product decision rather than an edit: whether to
      // keep offering models Code cannot run, and whether to say which engine
      // will handle the request BEFORE it is sent rather than after. See the
      // matching note in forge_code_settings.from_payload.
      //
      // What DID change (measured 2026-08-05): an EMPTY modelId no longer rides
      // that placeholder. The chip read GPT-5.6 Terra, client model state had
      // been lost (modelId ""), and this line's `: 'claude:sonnet'` arm turned
      // "I have no model" into a Claude pick — dispatched to an unauthenticated
      // Claude CLI while OpenAI had 4 ready keys, dead in 15s with the CLI's raw
      // login prompt as the user-facing error. Now an empty modelId sends NO
      // `model` key at all (JSON.stringify drops undefined), and the server
      // resolves the actually-configured default — the same resolution that
      // feeds the chip — or refuses BEFORE dispatch with a sentence naming the
      // real situation. Only the empty case changed; a NAMED non-gpt model
      // still takes the placeholder above.
      model: modelId ? (modelId.startsWith('gpt-') ? modelId : 'claude:sonnet') : undefined,
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
      // An open conversation names its own folder (the server verifies it
      // against the registry). A NEW task may only name a root somebody
      // PICKED -- state.projectRoot follows whatever conversation was last on
      // screen, and sending it here is how task B was built inside task A's
      // folder. The pick flag rides along so the server can tell a real choice
      // from a root restored out of an old session's localStorage.
      project_root: (state.activeId ? state.projectRoot : state.chosenProjectRoot) || undefined,
      project_choice: !state.activeId && state.chosenProjectRoot && state.chosenProjectPicked ? 'picked' : undefined,
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
