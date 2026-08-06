(function () {
  'use strict';

  const ACTIVE_STATES = new Set(['running', 'active', 'queued', 'pending', 'awaiting_approval', 'blocked']);
  const TERMINAL_STATES = new Set(['succeeded', 'completed', 'failed', 'dead', 'cancelled']);
  const JOBS_REFRESH_MS = 15000;
  const FALLBACK_REFRESH_MS = 8000;
  const STREAM_URL = '/api/mission/stream?interval=3';
  const state = {
    control: null,
    jobs: [],
    jobsUnavailable: false,
    filter: 'active',
    loading: false,
    actionPending: false,
    streamController: null,
    streamConnected: false,
    reconnectTimer: 0,
    reconnectMs: 1000,
    jobsTimer: 0,
    fallbackTimer: 0,
  };

  const byId = (id) => document.getElementById(id);
  const safe = (value) => String(value == null ? '' : value).trim();
  // Worker prose is plain text here - strip markdown markers so **bold**
  // never renders with its asterisks. Mirrors chat.html deMd.
  const plainText = (value) => safe(value)
    .replace(/\*\*/g, '')
    .replace(/__/g, '')
    .replace(/`/g, '')
    .replace(/(^|\s)#{1,6}\s+/gm, '$1');
  const escapeHtml = (value) => safe(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const normalizeStatus = (value) => safe(value).toLowerCase().replace(/\s+/g, '_') || 'unknown';
  const statusLabel = (value) => normalizeStatus(value).replace(/_/g, ' ');
  const array = (value) => Array.isArray(value) ? value : [];
  const epoch = (value) => {
    const parsed = Date.parse(safe(value));
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

  function relativeTime(value) {
    const time = epoch(value);
    if (!time) return 'just now';
    const delta = Date.now() - time;
    const abs = Math.abs(delta);
    if (abs < 45000) return delta >= 0 ? 'just now' : 'soon';
    if (abs < 3600000) return `${delta >= 0 ? '' : 'in '}${Math.max(1, Math.round(abs / 60000))}m${delta >= 0 ? ' ago' : ''}`;
    if (abs < 86400000) return `${delta >= 0 ? '' : 'in '}${Math.max(1, Math.round(abs / 3600000))}h${delta >= 0 ? ' ago' : ''}`;
    return `${delta >= 0 ? '' : 'in '}${Math.max(1, Math.round(abs / 86400000))}d${delta >= 0 ? ' ago' : ''}`;
  }

  function setConnection(kind, label) {
    const pill = byId('missionConnection');
    if (!pill) return;
    pill.className = `connection-pill is-${kind}`;
    const text = pill.querySelector('span');
    if (text) text.textContent = label;
  }

  function showToast(message, tone = '') {
    const host = byId('missionToasts');
    if (!host) return;
    const toast = document.createElement('div');
    toast.className = `toast${tone ? ` is-${tone}` : ''}`;
    toast.textContent = safe(message);
    host.appendChild(toast);
    window.setTimeout(() => toast.remove(), 3600);
  }

  async function request(url, options = {}) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const contentType = safe(response.headers.get('content-type')).toLowerCase();
    let payload = null;
    if (contentType.includes('application/json')) {
      payload = await response.json().catch(() => null);
    } else {
      payload = await response.text().catch(() => '');
    }
    if (!response.ok) {
      const detail = typeof payload === 'object' && payload ? safe(payload.error || payload.message) : safe(payload);
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  function empty(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
  }

  function statusPill(status) {
    const value = normalizeStatus(status);
    return `<span class="status-pill status-${escapeHtml(value)}">${escapeHtml(statusLabel(value))}</span>`;
  }

  function instanceAttrs(type, key, container) {
    return `data-ui-id="mission.${escapeHtml(type)}.${escapeHtml(key)}" data-ui-role="mission.${escapeHtml(type)}" data-ui-instance-key="${escapeHtml(key)}" data-ui-policy="move resize" data-ui-constraints="contain=parent;container=${escapeHtml(container)};collision=avoid;minWidth=220;minHeight=72;preserveHandlers=true;preserveA11y=true"`;
  }

  function protectedAttrs(type, key) {
    return `data-ui-id="mission.${escapeHtml(type)}.${escapeHtml(key)}" data-ui-role="mission.${escapeHtml(type)}" data-ui-instance-key="${escapeHtml(key)}" data-ui-policy="protected controls" data-ui-constraints="move=false;resize=false;critical=true;preserveHandlers=true;preserveA11y=true"`;
  }

  function jobSummary(job) {
    const payload = job && typeof job.payload === 'object' ? job.payload : {};
    return plainText(payload.goal || payload.prompt || payload.task || payload.message || 'No task summary provided.');
  }

  function scheduleLabel(job) {
    const schedule = job && typeof job.schedule === 'object' ? job.schedule : null;
    if (!schedule) return safe(job && job.next_run_at) ? `once · ${relativeTime(job.next_run_at)}` : 'manual';
    const type = safe(schedule.type).toLowerCase();
    if (type === 'interval') {
      const seconds = Number(schedule.every_seconds || 0);
      if (seconds >= 3600) return `every ${Math.round(seconds / 3600)}h`;
      if (seconds >= 60) return `every ${Math.round(seconds / 60)}m`;
      return `every ${Math.round(seconds)}s`;
    }
    if (type === 'daily') return `daily ${safe(schedule.at) || '--:--'}`;
    if (type === 'weekly') return `weekly ${safe(schedule.at) || '--:--'}`;
    if (type === 'once') return `once · ${relativeTime(job.next_run_at)}`;
    return type || 'scheduled';
  }

  function renderPulse() {
    const control = state.control || {};
    const agents = array(control.agents);
    const jobs = state.jobs;
    const live = agents.filter((row) => ['running', 'active'].includes(normalizeStatus(row.status)));
    const primary = live[0] || agents.find((row) => ACTIVE_STATES.has(normalizeStatus(row.status)));
    const scheduled = jobs.filter((job) => epoch(job.next_run_at) > 0).sort((a, b) => epoch(a.next_run_at) - epoch(b.next_run_at));
    const blockers = agents.filter((row) => ['blocked', 'failed', 'dead'].includes(normalizeStatus(row.status)));
    const blockedJobs = jobs.filter((row) => ['blocked', 'failed', 'dead'].includes(normalizeStatus(row.status)));
    const blockerCount = blockers.length + blockedJobs.length;

    byId('pulseNowTitle').textContent = safe(primary && primary.name) || 'No active execution';
    byId('pulseNowMeta').textContent = primary ? (safe(primary.summary) || `${statusLabel(primary.status)} · ${safe(primary.room) || 'workspace'}`) : 'Waiting for live work';
    byId('pulseNextTitle').textContent = safe(scheduled[0] && scheduled[0].name) || 'No scheduled run';
    byId('pulseNextMeta').textContent = scheduled[0] ? `${scheduleLabel(scheduled[0])} · ${relativeTime(scheduled[0].next_run_at)}` : 'Create a job when ready';
    byId('pulseBlockerTitle').textContent = plural(blockerCount, 'blocker');
    byId('pulseBlockerMeta').textContent = blockerCount ? 'Review failed or blocked work' : 'Nothing needs attention';
  }

  function renderMetrics() {
    const control = state.control || {};
    const agents = array(control.agents);
    const approvals = control.approvals && typeof control.approvals === 'object' ? control.approvals : {};
    const active = agents.filter((row) => ACTIVE_STATES.has(normalizeStatus(row.status))).length;
    const risk = agents.filter((row) => ['blocked', 'failed', 'dead'].includes(normalizeStatus(row.status))).length;
    const pending = Number(approvals.pending_total || 0);
    const engine = control.engine && typeof control.engine === 'object' ? control.engine : {};
    const engineLive = Boolean(engine.autonomy_running || engine.run_store_enabled);
    byId('metricActive').textContent = String(active);
    byId('metricActiveMeta').textContent = active ? plural(active, 'agent') + ' in motion' : 'No active agents';
    byId('metricApprovals').textContent = String(pending);
    byId('metricApprovalsMeta').textContent = pending ? 'Owner decision needed' : 'Nothing waiting';
    byId('metricRisk').textContent = String(risk);
    byId('metricRiskMeta').textContent = risk ? 'Review attention states' : 'No blocked work';
    byId('metricEngine').textContent = engineLive ? 'Live' : 'Idle';
    byId('metricEngineMeta').textContent = `Run store ${engine.run_store_enabled ? 'on' : 'off'} · Autonomy ${engine.autonomy_enabled ? 'on' : 'off'}`;
  }

  function renderAgents() {
    const host = byId('agentsList');
    const agents = array(state.control && state.control.agents);
    const active = agents.filter((row) => ACTIVE_STATES.has(normalizeStatus(row.status)));
    byId('agentsCount').textContent = `${active.length} active`;
    const rows = [...active, ...agents.filter((row) => !ACTIVE_STATES.has(normalizeStatus(row.status)))].slice(0, 20);
    if (!rows.length) {
      host.innerHTML = empty('No delegated agents are active. New work will appear here as soon as Thomas hands it off.');
      return;
    }
    host.innerHTML = rows.map((agent, index) => {
      const key = safe(agent.id || agent.execution_id || agent.run_id || `agent-${index}`);
      const source = safe(agent.source).replace(/_/g, ' ') || 'Thomas';
      return `<article class="work-card" ${instanceAttrs('agent-card', key, 'mission.live-work')}>
        <div class="card-top"><div class="card-title"><strong>${escapeHtml(agent.name || 'Worker')}</strong><small>${escapeHtml(source)} · ${escapeHtml(agent.room || 'workspace')}</small></div>${statusPill(agent.status)}</div>
        <p class="card-summary">${escapeHtml(agent.summary || 'Standing by for the next update.')}</p>
        <div class="card-meta"><span>Updated ${escapeHtml(relativeTime(agent.updated_at))}</span>${agent.session_id ? `<span>Session ${escapeHtml(safe(agent.session_id).slice(0, 14))}</span>` : ''}</div>
      </article>`;
    }).join('');
  }

  function renderJobs() {
    const host = byId('jobsList');
    let jobs = [...state.jobs];
    if (state.filter === 'active') jobs = jobs.filter((job) => ACTIVE_STATES.has(normalizeStatus(job.status)));
    if (state.filter === 'scheduled') jobs = jobs.filter((job) => job.schedule || safe(job.next_run_at));
    jobs.sort((a, b) => {
      const aLive = ACTIVE_STATES.has(normalizeStatus(a.status)) ? 0 : 1;
      const bLive = ACTIVE_STATES.has(normalizeStatus(b.status)) ? 0 : 1;
      return aLive - bLive || epoch(b.updated_at) - epoch(a.updated_at);
    });
    byId('jobsCount').textContent = state.jobsUnavailable ? 'Runtime unavailable' : plural(state.jobs.length, 'job');
    if (!jobs.length) {
      host.innerHTML = empty(state.jobsUnavailable ? 'The autonomy runtime is unavailable. Create a mission to start it.' : `No ${state.filter === 'all' ? '' : state.filter + ' '}jobs to show.`);
      return;
    }
    host.innerHTML = jobs.slice(0, 40).map((job, index) => {
      const key = safe(job.id || `job-${index}`);
      const status = normalizeStatus(job.status);
      const canCancel = ACTIVE_STATES.has(status);
      const canRequeue = TERMINAL_STATES.has(status) || status === 'blocked';
      return `<article class="job-card" ${instanceAttrs('job-card', key, 'mission.jobs')}>
        <div class="card-top"><div class="card-title"><strong>${escapeHtml(job.name || job.id || 'Mission job')}</strong><small>${escapeHtml(scheduleLabel(job))}${job.next_run_at ? ` · ${escapeHtml(relativeTime(job.next_run_at))}` : ''}</small></div>${statusPill(status)}</div>
        <p class="card-summary">${escapeHtml(jobSummary(job))}</p>
        <div class="card-meta"><span>${escapeHtml(job.kind || 'workflow task')}</span><span>Updated ${escapeHtml(relativeTime(job.updated_at || job.created_at))}</span>${job.requires_approval ? '<span>Approval required</span>' : ''}</div>
        <div class="card-actions" ${protectedAttrs('job-actions', key)}>
          <button class="action-button is-primary" type="button" data-job-action="run_now" data-job-id="${escapeHtml(key)}">Run now</button>
          ${canRequeue ? `<button class="action-button" type="button" data-job-action="requeue" data-job-id="${escapeHtml(key)}">Requeue</button>` : ''}
          ${canCancel ? `<button class="action-button is-danger" type="button" data-job-action="cancel" data-job-id="${escapeHtml(key)}">Cancel</button>` : ''}
        </div>
      </article>`;
    }).join('');
  }

  function approvalRows() {
    const approvals = state.control && state.control.approvals && typeof state.control.approvals === 'object' ? state.control.approvals : {};
    return [
      ...array(approvals.autonomy).map((row) => ({ ...row, source: 'autonomy' })),
      ...array(approvals.guardrails).map((row) => ({ ...row, source: 'guardrails' })),
    ];
  }

  function approvalKey(row, index = 0) {
    return safe(row.id || `${row.source}:${row.run_id || ''}:${row.tool_call_id || ''}:${index}`);
  }

  function renderApprovals() {
    const host = byId('approvalsList');
    const rows = approvalRows();
    byId('approvalsCount').textContent = `${rows.length} waiting`;
    if (!rows.length) {
      host.innerHTML = empty('No approvals are waiting. Thomas will surface owner decisions here.');
      return;
    }
    host.innerHTML = rows.slice(0, 30).map((row, index) => {
      const key = approvalKey(row, index);
      const title = row.source === 'guardrails' ? (safe(row.tool_name) || 'Guardrail request') : (safe(row.name || row.kind) || 'Autonomy request');
      const detail = plainText(row.reason || row.summary || row.args_preview || 'Review this request before work continues.');
      return `<article class="approval-card" ${instanceAttrs('approval-card', key, 'mission.approvals')}>
        <div class="card-top"><div class="card-title"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(row.source)} · requested ${escapeHtml(relativeTime(row.requested_at))}</small></div><span class="status-pill is-warning">waiting</span></div>
        <p class="card-summary">${escapeHtml(detail)}</p>
        <div class="card-actions" ${protectedAttrs('approval-actions', key)}>
          <button class="action-button is-primary" type="button" data-approval-key="${escapeHtml(key)}" data-approval-action="approve">Approve</button>
          ${row.source === 'guardrails' ? `<button class="action-button" type="button" data-approval-key="${escapeHtml(key)}" data-approval-action="approve_session">Approve for session</button>` : ''}
          <button class="action-button is-danger" type="button" data-approval-key="${escapeHtml(key)}" data-approval-action="deny">Deny</button>
        </div>
      </article>`;
    }).join('');
  }

  function renderActivity() {
    const host = byId('activityList');
    const events = array(state.control && state.control.events).slice(0, 18);
    byId('updatedAt').textContent = state.control && state.control.generated_at ? `Updated ${relativeTime(state.control.generated_at)}` : 'Not synced';
    if (!events.length) {
      host.innerHTML = empty('No recent signals yet. Runtime updates will appear here.');
      return;
    }
    host.innerHTML = events.map((event, index) => {
      const key = safe(event.id || `${event.source || 'event'}:${event.ts || index}`);
      return `<article class="signal-card" ${instanceAttrs('signal-card', key, 'mission.activity')}><strong>${escapeHtml(safe(event.type).replace(/_/g, ' ') || 'Update')} · ${escapeHtml(relativeTime(event.ts))}</strong><p>${escapeHtml(event.text || 'Mission state changed.')}</p></article>`;
    }).join('');
  }

  function renderAll() {
    renderPulse();
    renderMetrics();
    renderAgents();
    renderJobs();
    renderApprovals();
    renderActivity();
  }

  async function refreshJobs({ silent = true } = {}) {
    try {
      const payload = await request('/api/mission/jobs?limit=180');
      state.jobs = array(payload && payload.jobs);
      state.jobsUnavailable = Boolean(payload && payload.unavailable);
      renderPulse();
      renderJobs();
      if (!silent && !state.streamConnected) setConnection('polling', 'Polling');
    } catch (error) {
      if (!silent) showToast(error.message || 'Could not refresh jobs.', 'error');
    }
  }

  async function refreshAll({ silent = false, fresh = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    if (!silent) setConnection('connecting', 'Refreshing');
    try {
      const [control, jobs] = await Promise.all([
        request(`/api/mission/control${fresh ? '?fresh=1' : ''}`),
        request('/api/mission/jobs?limit=180'),
      ]);
      state.control = control && typeof control === 'object' ? control : {};
      state.jobs = array(jobs && jobs.jobs);
      state.jobsUnavailable = Boolean(jobs && jobs.unavailable);
      renderAll();
      setConnection(state.streamConnected ? 'live' : 'polling', state.streamConnected ? 'Live' : 'Polling');
    } catch (error) {
      setConnection('offline', 'Offline');
      if (!silent) showToast(error.message || 'Mission Control refresh failed.', 'error');
    } finally {
      state.loading = false;
    }
  }

  function stopFallbackPolling() {
    if (state.fallbackTimer) window.clearInterval(state.fallbackTimer);
    state.fallbackTimer = 0;
  }

  function startFallbackPolling() {
    if (state.fallbackTimer) return;
    state.fallbackTimer = window.setInterval(() => void refreshAll({ silent: true }), FALLBACK_REFRESH_MS);
  }

  function scheduleStreamReconnect() {
    if (state.reconnectTimer || document.hidden) return;
    const delay = state.reconnectMs;
    state.reconnectMs = Math.min(15000, Math.round(state.reconnectMs * 1.7));
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = 0;
      void startStream();
    }, delay);
  }

  function stopStream() {
    if (state.streamController) state.streamController.abort();
    state.streamController = null;
    state.streamConnected = false;
  }

  async function startStream() {
    if (state.streamController || document.hidden) return;
    const controller = new AbortController();
    state.streamController = controller;
    try {
      const response = await fetch(STREAM_URL, { cache: 'no-store', headers: { Accept: 'application/x-ndjson' }, signal: controller.signal });
      if (!response.ok || !response.body) throw new Error(`Live stream unavailable (${response.status})`);
      state.streamConnected = true;
      state.reconnectMs = 1000;
      stopFallbackPolling();
      setConnection('live', 'Live');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (!controller.signal.aborted) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        let lineEnd = buffer.indexOf('\n');
        while (lineEnd >= 0) {
          const line = buffer.slice(0, lineEnd).trim();
          buffer = buffer.slice(lineEnd + 1);
          if (line) {
            try {
              const message = JSON.parse(line);
              if (message.type === 'snapshot' && message.payload && typeof message.payload === 'object') {
                state.control = message.payload;
                renderPulse(); renderMetrics(); renderAgents(); renderApprovals(); renderActivity();
              }
            } catch (_) { /* ignore malformed stream lines and continue */ }
          }
          lineEnd = buffer.indexOf('\n');
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) console.warn('Mission stream unavailable; using bounded polling.', error);
    } finally {
      if (state.streamController === controller) state.streamController = null;
      state.streamConnected = false;
      if (!controller.signal.aborted) {
        setConnection('polling', 'Polling');
        startFallbackPolling();
        scheduleStreamReconnect();
      }
    }
  }

  async function runJobAction(jobId, action) {
    if (state.actionPending || !jobId || !['run_now', 'requeue', 'cancel'].includes(action)) return;
    state.actionPending = true;
    try {
      await request(`/api/mission/jobs/${encodeURIComponent(jobId)}/${action}`, { method: 'POST' });
      showToast(`Job ${action.replace(/_/g, ' ')} requested.`);
      await refreshJobs({ silent: false });
    } catch (error) {
      showToast(error.message || 'Job action failed.', 'error');
    } finally {
      state.actionPending = false;
    }
  }

  async function resolveApproval(key, action) {
    if (state.actionPending) return;
    const rows = approvalRows();
    const row = rows.find((item, index) => approvalKey(item, index) === key);
    if (!row) return;
    const approve = action === 'approve' || action === 'approve_session';
    state.actionPending = true;
    try {
      if (row.source === 'autonomy') {
        await request(`/api/mission/approvals/autonomy/${encodeURIComponent(safe(row.id))}/decision`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approve, actor: 'mission_control', reason: approve ? 'approved in mission control' : 'denied in mission control' }),
        });
      } else {
        await request('/api/mission/approvals/guardrails/resolve', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_id: safe(row.run_id), tool_call_id: safe(row.tool_call_id), approve, allow_session_tool: action === 'approve_session', tool_name: safe(row.tool_name), session_id: safe(row.session_id), actor: 'mission_control' }),
        });
      }
      showToast(approve ? 'Approval submitted.' : 'Request denied.');
      await refreshAll({ silent: true, fresh: true });
    } catch (error) {
      showToast(error.message || 'Approval action failed.', 'error');
    } finally {
      state.actionPending = false;
    }
  }

  function updateScheduleFields() {
    const mode = safe(byId('missionMode').value).toLowerCase() || 'now';
    document.querySelectorAll('[data-schedule-field]').forEach((field) => {
      const kind = field.dataset.scheduleField;
      field.hidden = !(
        kind === mode ||
        (kind === 'timed' && (mode === 'daily' || mode === 'weekly')) ||
        (kind === 'weekly' && mode === 'weekly')
      );
    });
    if (mode === 'once' && !byId('missionRunAt').value) {
      const runAt = new Date(Date.now() + 15 * 60000);
      runAt.setSeconds(0, 0);
      const local = new Date(runAt.getTime() - runAt.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      byId('missionRunAt').value = local;
    }
  }

  function buildMissionPayload() {
    const mode = safe(byId('missionMode').value).toLowerCase() || 'now';
    const goal = safe(byId('missionGoal').value);
    if (!goal) throw new Error('Task or goal is required.');
    const payload = {
      name: safe(byId('missionName').value) || 'Mission task', kind: 'workflow_task', goal, prompt: goal,
      workflow: safe(byId('missionWorkflow').value) || 'chain', requires_approval: Boolean(byId('missionRequiresApproval').checked),
    };
    const profile = safe(byId('missionProfile').value);
    if (profile) payload.profile = profile;
    if (mode === 'once') {
      const runAt = new Date(byId('missionRunAt').value);
      if (!Number.isFinite(runAt.getTime())) throw new Error('Choose a valid run time.');
      payload.run_at = runAt.toISOString();
    } else if (mode === 'interval') {
      const seconds = Number(byId('missionEvery').value || 0);
      if (!Number.isFinite(seconds) || seconds < 30) throw new Error('Interval must be at least 30 seconds.');
      payload.schedule = { type: 'interval', every_seconds: Math.round(seconds) };
    } else if (mode === 'daily' || mode === 'weekly') {
      const at = safe(byId('missionAt').value);
      if (!/^\d{2}:\d{2}$/.test(at)) throw new Error('Choose a valid schedule time.');
      payload.schedule = { type: mode, at, tz: safe(byId('missionTimezone').value) || 'UTC' };
      if (mode === 'weekly') {
        payload.schedule.dow = Array.from(byId('missionWeekdays').querySelectorAll('input:checked')).map((input) => Number(input.value));
        if (!payload.schedule.dow.length) throw new Error('Choose at least one weekday.');
      }
    }
    return payload;
  }

  function toggleCreatePanel(open) {
    const panel = byId('missionCreatePanel');
    const button = byId('missionNewButton');
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(Boolean(open)));
    if (open) window.setTimeout(() => byId('missionGoal').focus(), 0);
  }

  async function createMission(event) {
    event.preventDefault();
    if (state.actionPending) return;
    let payload;
    try { payload = buildMissionPayload(); } catch (error) {
      byId('missionCreateStatus').textContent = error.message;
      return;
    }
    state.actionPending = true;
    byId('missionCreateSubmit').disabled = true;
    byId('missionCreateStatus').textContent = 'Creating…';
    try {
      const created = await request('/api/mission/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      showToast(`${safe(created && created.job && created.job.name) || payload.name} created.`);
      byId('missionCreateForm').reset();
      byId('missionTimezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      updateScheduleFields();
      toggleCreatePanel(false);
      await refreshJobs({ silent: false });
    } catch (error) {
      byId('missionCreateStatus').textContent = error.message || 'Create failed.';
      showToast(error.message || 'Could not create mission.', 'error');
    } finally {
      state.actionPending = false;
      byId('missionCreateSubmit').disabled = false;
    }
  }

  function bindControls() {
    byId('missionRefreshButton').addEventListener('click', () => void refreshAll({ fresh: true }));
    byId('missionNewButton').addEventListener('click', () => toggleCreatePanel(true));
    byId('missionCreateClose').addEventListener('click', () => toggleCreatePanel(false));
    byId('missionMode').addEventListener('change', updateScheduleFields);
    byId('missionCreateForm').addEventListener('submit', createMission);
    byId('jobFilters').addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest('button[data-filter]');
      if (!button) return;
      state.filter = safe(button.dataset.filter) || 'active';
      byId('jobFilters').querySelectorAll('button').forEach((item) => item.classList.toggle('is-active', item === button));
      renderJobs();
    });
    byId('jobsList').addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest('button[data-job-action][data-job-id]');
      if (button) void runJobAction(safe(button.dataset.jobId), safe(button.dataset.jobAction));
    });
    byId('approvalsList').addEventListener('click', (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest('button[data-approval-key][data-approval-action]');
      if (button) void resolveApproval(safe(button.dataset.approvalKey), safe(button.dataset.approvalAction));
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopStream(); stopFallbackPolling();
      } else {
        void refreshAll({ silent: true }); void startStream();
      }
    });
  }

  async function boot() {
    bindControls();
    try { byId('missionTimezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (_) { byId('missionTimezone').value = 'UTC'; }
    updateScheduleFields();
    renderAll();
    await refreshAll({ silent: true });
    state.jobsTimer = window.setInterval(() => void refreshJobs(), JOBS_REFRESH_MS);
    void startStream();
  }

  void boot();
})();
