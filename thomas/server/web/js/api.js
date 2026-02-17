/* ============================================================
   Thomas API Client
   ============================================================
   Fetch wrappers for all server endpoints. Handles NDJSON
   streaming, error handling, and abort signals.
   ============================================================ */

/**
 * JSON fetch helper with error handling.
 * @param {string} url
 * @param {RequestInit} [opts]
 * @returns {Promise<any>}
 */
async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json();
}

/**
 * Stream NDJSON from an endpoint, calling onEvent for each JSON object.
 * @param {string} url
 * @param {RequestInit} opts
 * @param {(event: object) => void} onEvent
 */
async function streamNdjson(url, opts, onEvent) {
  const res = await fetch(url, opts);

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });

    while (true) {
      const idx = buf.indexOf('\n');
      if (idx === -1) break;

      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);

      if (!line) continue;

      try {
        const ev = JSON.parse(line);
        onEvent(ev);
      } catch {
        // skip malformed lines
      }
    }
  }

  if (buf.trim()) {
    try {
      onEvent(JSON.parse(buf.trim()));
    } catch {
      // ignore
    }
  }
}

/**
 * Fetch all model profiles from the server.
 * @returns {Promise<{default: string, profiles: object[]}>}
 */
export async function fetchModels() {
  return apiFetch('/api/models');
}

/**
 * Discover available model IDs for a specific profile.
 * @param {string} profile
 * @returns {Promise<{profile: string, models: string[]}>}
 */
export async function fetchModelIds(profile) {
  return apiFetch(`/api/models/${encodeURIComponent(profile)}/ids`);
}

/**
 * Probe a profile for auth/offline/unsupported state (localhost-only endpoint).
 * @param {string} profile
 * @returns {Promise<{profile: string, ok: boolean, status: string, http_status: number|null, url: string, models: string[], error: string|null}>}
 */
export async function fetchModelHandshake(profile) {
  return apiFetch(`/api/models/${encodeURIComponent(profile)}/handshake`);
}

/**
 * Create a new server session.
 * @returns {Promise<{session_id: string}>}
 */
export async function createSession() {
  return apiFetch('/api/session/new', { method: 'POST' });
}

/**
 * Fork an existing server session (copies server-side conversation state).
 * Note: endpoint is restricted to localhost.
 * @param {string} sessionId
 * @returns {Promise<{session_id: string, forked_from: string}>}
 */
export async function forkSession(sessionId) {
  return apiFetch('/api/session/fork', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

/**
 * Create a new server session from a client-provided conversation.
 * Note: endpoint is restricted to localhost.
 * @param {{role: 'user'|'assistant', content: string}[]} conversation
 * @param {{profile?: string, model_id?: string|null}} [opts]
 * @returns {Promise<{session_id: string}>}
 */
export async function importSession(conversation, opts = {}) {
  return apiFetch('/api/session/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      profile: opts.profile || null,
      model_id: opts.model_id || null,
      conversation: Array.isArray(conversation) ? conversation : [],
    }),
  });
}

/**
 * Fetch available tools from the server.
 * @returns {Promise<{tools: object[]}>}
 */
export async function fetchTools() {
  return apiFetch('/api/tools');
}

/**
 * Fetch memory diagnostics from the server.
 * @param {{session_id?: string|null, trace_limit?: number}} [opts]
 */
export async function fetchMemory(opts = {}) {
  const q = new URLSearchParams();
  if (opts.session_id) q.set('session_id', String(opts.session_id));
  if (typeof opts.trace_limit === 'number') q.set('trace_limit', String(opts.trace_limit));
  const suffix = q.toString() ? `?${q.toString()}` : '';
  return apiFetch(`/api/memory${suffix}`);
}

/**
 * Set/update a memory pin.
 * @param {string} key
 * @param {string} text
 */
export async function setMemoryPin(key, text) {
  return apiFetch('/api/memory/pins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, text }),
  });
}

/**
 * Remove a memory pin by key.
 * @param {string} key
 */
export async function clearMemoryPin(key) {
  const res = await fetch(`/api/memory/pins/${encodeURIComponent(key)}`, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json().catch(() => ({}));
}

/**
 * Fetch memory contradictions from the server.
 * @param {{only_open?: boolean, limit?: number}} [opts]
 */
export async function fetchMemoryContradictions(opts = {}) {
  const q = new URLSearchParams();
  if (typeof opts.only_open === 'boolean') q.set('only_open', opts.only_open ? '1' : '0');
  if (typeof opts.limit === 'number') q.set('limit', String(opts.limit));
  const suffix = q.toString() ? `?${q.toString()}` : '';
  return apiFetch(`/api/memory/contradictions${suffix}`);
}

/**
 * Resolve/reopen a memory contradiction entry.
 * @param {number|string} id
 * @param {boolean} [resolved]
 */
export async function resolveMemoryContradiction(id, resolved = true) {
  return apiFetch(`/api/memory/contradictions/${encodeURIComponent(String(id))}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resolved: !!resolved }),
  });
}

/**
 * Fetch secret/key status for model profiles.
 * Note: secrets endpoints are restricted to localhost.
 * @returns {Promise<{storage: object, profiles: object[]}>}
 */
export async function fetchSecrets() {
  return apiFetch('/api/secrets');
}

/**
 * Set an API key for a profile (stored on the server machine).
 * @param {string} profile
 * @param {string} apiKey
 * @param {boolean} [persist]
 */
export async function setProfileApiKey(profile, apiKey, persist = true) {
  return apiFetch(`/api/secrets/${encodeURIComponent(profile)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey, persist }),
  });
}

/**
 * Clear an API key for a profile.
 * @param {string} profile
 */
export async function clearProfileApiKey(profile) {
  const res = await fetch(`/api/secrets/${encodeURIComponent(profile)}`, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  return res.json().catch(() => ({}));
}

/**
 * Stream a chat request, calling onEvent for each NDJSON event.
 *
 * Events: {type: 'text', text}, {type: 'tool_start', name},
 *         {type: 'tool_result', name, ok, ms}, {type: 'tool_args', id, delta},
 *         {type: 'iteration', iteration, token_estimate, context_window},
 *         {type: 'error', error}, {type: 'done', iterations, tool_calls}
 *
 * @param {object} payload - {session_id, profile, model_id, mode, text, docs, images}
 * @param {(event: object) => void} onEvent
 * @param {AbortSignal} [signal]
 * @returns {Promise<void>}
 */
export async function streamChat(payload, onEvent, signal) {
  return streamNdjson('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  }, onEvent);
}

/**
 * Pull a local model via the server (Ollama proxy).
 * Note: endpoint is restricted to localhost.
 * @param {string} modelId
 * @param {(event: object) => void} onEvent
 * @param {AbortSignal} [signal]
 */
export async function pullLocalModel(modelId, onEvent, signal) {
  return streamNdjson('/api/local/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
    signal,
  }, onEvent);
}

/**
 * Check server connectivity.
 * @returns {Promise<boolean>}
 */
export async function checkConnection() {
  try {
    await apiFetch('/api/models');
    return true;
  } catch {
    return false;
  }
}
