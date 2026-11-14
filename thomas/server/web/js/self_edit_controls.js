/* "Improve Thomas" -- the one way to ask Thomas to change himself.
 *
 * There were two, doing the same job by different means:
 *
 *   1. This dialog asked for a LIST OF FILES and opened a `self_edit` Build conversation. One worker edited a
 *      snapshot of Thomas's source inside the scope it was handed, and the result landed by writing those files
 *      over the running copy (Review -> Apply -> Restart, with Undo). No git history, no commit, no team.
 *   2. A Thomas project (`thomas/server/thomas_project.py`): a green git clone of Thomas's own source, Build's
 *      FULL team in it -- task manager, builders, reviewers -- the repo's size rule checked before hand-in,
 *      repair rounds when it is refused, and the change reaching you as a submission on your Windows sign-in
 *      card, which lands it as a real commit.
 *
 * (2) is what "Thomas works on himself" means now, and it is what this button starts: POST /api/self/projects.
 * Asking a person to name the files first was (1)'s requirement, not a thing anyone knows up front -- a project
 * is given the request in your own words and works out the files itself.
 *
 * GET /api/self/projects has been listing every project's state since it was written and no page read it; this
 * panel does, so you can see what is already going before starting another.
 *
 * `html`/`bind` below still render the (1)-style review card for conversations that already carry `self_edit`.
 * Nothing can create a new one -- this was its only entry point. When no such conversation is left, that half
 * and the routes under /api/evolve/agent/self-edit/* should go.
 */
(function () {
  'use strict';
  const records = new Map();
  const pending = new Map();
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const key = (cid, rid) => `${cid}:${rid}`;
  const PROJECTS = '/api/self/projects';
  let speedCache = null;
  let speedLoading = null;
  let speedUpdated = 0;
  const QUEUE = '/api/self/projects/queue';
  const PLANNER = `${QUEUE}/planner`;

  // The subset of Build's dials POST /api/self/projects accepts (self_project_routes.SETTINGS_KEYS); it refuses
  // any other key by name. Mirrors unified_code_lifecycle.requestSettings, except that the route calls the
  // guardrail dial `guardrails` where a Build run request calls it `thomas_guardrails`.
  function settings() {
    // `ctx`, not `context`: this file already has a `context(state)` for the legacy review card below.
    const ctx = window.ThomasUnifiedModes?.host?.()?.getContext?.() || {};
    const dials = ctx.dials || {};
    const modelId = String(ctx.modelId || '');
    return {
      engine: 'agent',
      model: modelId ? (modelId.startsWith('gpt-') ? modelId : 'claude:sonnet') : undefined,
      model_id: modelId,
      // Build's per-role model picks, read and shaped exactly as unified_code_lifecycle.requestSettings does.
      // Left out, a project started from this panel ran its builder and reviewer on the default model while
      // the same picks were honoured for a run started from Build -- the one dial of the ten that did not
      // reach the route that accepts it. `undefined` when nothing is picked, which JSON.stringify drops.
      build_roles: ctx.roleProfiles || ctx.roleModelIds ? Object.fromEntries(
        ['builder', 'reviewer'].map(role => {
          const saved = 'build_' + role;
          const profile = (ctx.roleProfiles || {})[saved];
          const id = (ctx.roleModelIds || {})[saved];
          return [role, profile || id ? { profile: profile || '', model_id: id || '' } : null];
        })
      ) : undefined,
      reasoning_effort: dials.effort || 'medium',
      autonomy_level: dials.autonomy || 3,
      file_access: dials.fileAccess || 'project',
      memory: dials.memory !== false,
      guardrails: dials.guardrails || 'guarded',
      token_economy: dials.tokenEconomy || 'balanced',
    };
  }

  function duration(seconds) {
    if (seconds == null) return 'not recorded';
    return seconds < 60 ? `${Math.round(seconds)}s` : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  }

  const SPEED_STEPS = [
    ['building', 'Build'], ['checks', 'Checks'], ['second_look', 'Second look'],
    ['repair_rounds', 'Repairs'], ['card_wait', 'Your approval'], ['unattributed', 'Other / unrecorded'],
  ];

  function speedHtml(score) {
    if (!score) return '<span>Loading speed…</span>';
    const today = score.today || {};
    const week = score.last_week || {};
    const change = score.faster_percent == null ? null : Number(score.faster_percent).toFixed(1);
    const trend = change == null ? 'Waiting for landed changes in both periods'
      : Number(change) > 0 ? `${change}% faster than last week`
      : Number(change) < 0 ? `${Math.abs(Number(change)).toFixed(1)}% slower than last week`
      : 'Same speed as last week';
    const steps = SPEED_STEPS.map(([key, label]) => `<span>${label}: <strong>${today.steps ? `${today.steps[key] ?? 0}%` : '—'}</strong> today / <strong>${week.steps ? `${week.steps[key] ?? 0}%` : '—'}</strong> last 7 days</span>`).join(' · ');
    return `<h2>Build speed · Request → landed change</h2><div class="tc-speed-periods"><div>Today <strong>${duration(today.median_seconds)}</strong>${today.landed || 0} landed</div><div>Last 7 days <strong>${duration(week.median_seconds)}</strong>${week.landed || 0} landed</div></div>
      <p>${trend} · Teams at once: <strong>${today.peak_teams ?? 0} today</strong> / ${week.peak_teams ?? 0} last 7 days</p>
      <div class="tc-speed-steps" aria-label="Share of landed project wall-clock time">${steps}</div>
      <div class="tc-speed-cost" aria-label="What one landed change cost" data-build-cost>${costHtml('Today', today.cost)}${costHtml('Last 7 days', week.cost)}${score.disk_free_gb == null ? '' : `<span>Free disk: <strong>${Number(score.disk_free_gb).toFixed(1)} GB</strong></span>`}</div>`;
  }

  // Per landed change: Thomas's run, check and second-look hours, prompt tokens and cache, the machine's load.
  function costHtml(label, cost) {
    if (!cost) return '';
    const hours = cost.hours_per_landing == null ? `${Number(cost.hours || 0).toFixed(1)} h, nothing landed` : `${Number(cost.hours_per_landing).toFixed(1)} h`;
    const tokens = cost.prompt_tokens_per_landing == null ? '—' : `${(cost.prompt_tokens_per_landing / 1e6).toFixed(1)}M`;
    const cached = cost.cached_share == null ? '—' : `${Math.round(cost.cached_share * 100)}%`;
    const load = cost.average_cpu == null ? '—' : `${Math.round(cost.average_cpu)}% CPU, ${cost.average_memory == null ? '—' : Math.round(cost.average_memory)}% memory`;
    return `<p>${label} per landed change: <strong>${hours}</strong> of Thomas's work · <strong>${tokens}</strong> prompt tokens · <strong>${cached}</strong> from cache · ${load}</p>`;
  }

  function loadSpeed(root) {
    const host = root.querySelector('[data-build-speed]');
    if (!host) return;
    if (speedCache) host.innerHTML = speedHtml(speedCache);
    if (speedLoading || (speedCache && Date.now() - speedUpdated < 30000)) return;
    speedLoading = fetch(PROJECTS).then(response => {
      if (!response.ok) throw new Error('Speed unavailable');
      return response.json();
    }).then(data => {
      speedCache = data.speed_scoreboard || null;
      speedUpdated = Date.now();
      const current = document.querySelector('[data-build-speed]');
      if (current) current.innerHTML = speedHtml(speedCache);
    }).catch(() => {
      const current = document.querySelector('[data-build-speed]');
      if (current) current.textContent = 'Speed unavailable right now.';
    }).finally(() => { speedLoading = null; });
  }

  function projectRow(row) {
    const files = (row.changed_files || []).slice(0, 6).map(esc).join(', ');
    const timing = row.timings_seconds || {};
    const stages = [['building', 'Building'], ['checks', 'Checks'], ['second_look', 'Second look'],
      ['repair_rounds', 'Repair rounds'], ['card_wait', 'Waiting for my card']];
    const line = stages.map(([key, label]) => `${label}: ${duration(timing[key])}`).join(' · ');
    const more = (row.changed_files || []).length - 6;
    return `<li style="margin:0 0 8px"><strong>${esc(row.title || row.conversation_id)}</strong> — ${esc(row.state)}
      <div style="color:var(--c-muted);font-size:12.5px">${esc(row.detail || '')}</div>
      <div style="color:var(--c-muted);font-size:12.5px">${esc(line)}</div>
      ${files ? `<div style="color:var(--c-muted);font-size:12.5px">${files}${more > 0 ? `, +${more} more` : ''}</div>` : ''}</li>`;
  }

  async function showQueue(dialog) {
    const host = dialog.querySelector('[data-self-queue]');
    if (!host) return;
    try {
      const [queueResponse, plannerResponse] = await Promise.all([fetch(QUEUE), fetch(PLANNER)]);
      const [queue, settings] = await Promise.all([queueResponse.json(), plannerResponse.json()]);
      if (!queueResponse.ok || !plannerResponse.ok || !queue.ok || !settings.ok) {
        throw new Error(queue.error || settings.error || 'The self-project queue could not be read.');
      }
      const enabled = settings.planner.enabled !== false;
      const entries = queue.queued || [];
      const capacity = queue.capacity || {};
      const count = Number(capacity.running || 0);
      const starting = Number(capacity.starting || 0);
      host.innerHTML = `<h3 style="margin:0 0 8px;font-size:14px">Planned improvements</h3>
        <p role="status" style="color:var(--c-muted);font-size:12px">${count} running${starting ? `, ${starting} starting` : ''}; ${entries.length} queued.${capacity.blocked_by ? ` More cannot start: ${esc(capacity.blocked_by)}` : ' More can start when queued.'}</p>
        <label style="display:flex;align-items:center;gap:8px"><input type="checkbox" data-planner-enabled ${enabled ? 'checked' : ''}>
        Plan and start automatic improvements</label>
        <p style="color:var(--c-muted);font-size:12px">Turning this off pauses automatic proposals and starts; manual projects still run.</p>
        ${entries.length ? `<ul style="padding-left:20px">${entries.map(row => `<li style="margin-bottom:8px">
          ${esc(row.subject || row.request || 'Untitled project')}
          <div style="font-size:12px;color:var(--c-muted)">Origin: ${esc(row.origin || 'manual')} · Source ID: ${esc(row.source_id || 'manual request')}</div>
          ${row.last_reason ? `<div role="alert" style="font-size:12px;color:var(--c-danger, #c44)">Start failed: ${esc(row.last_reason)}${row.given_up ? ' (retries exhausted)' : ' (will retry)'} · <time>${esc(new Date(Number(row.failed_at || row.last_tried_at || row.queued_at) * 1000).toLocaleString())}</time></div>` : ''}
        </li>`).join('')}</ul>` : '<p>No improvements are queued.</p>'}
        ${(queue.given_up || []).length ? `<h4 style="margin:12px 0 6px">Could not start</h4>
          <ul style="padding-left:20px">${queue.given_up.slice(0, 10).map(row => `<li style="margin-bottom:8px">
            ${esc(row.subject || row.request || 'Untitled project')}
            <div role="alert" style="font-size:12px;color:var(--c-danger, #c44)">${esc(row.reason || row.last_reason || 'No reason recorded')} · <time>${esc(new Date(Number(row.failed_at || row.last_tried_at || row.queued_at) * 1000).toLocaleString())}</time></div>
          </li>`).join('')}</ul>` : ''}
        <p data-planner-error role="alert" style="color:var(--c-danger, #c44)"></p>`;
      const toggle = host.querySelector('[data-planner-enabled]');
      toggle.onchange = async () => {
        toggle.disabled = true;
        try {
          const response = await fetch(PLANNER, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: toggle.checked }),
          });
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || 'Could not change the planner switch.');
          toggle.checked = result.planner.enabled;
          host.querySelector('[data-planner-error]').textContent = '';
        } catch (error) {
          toggle.checked = !toggle.checked;
          host.querySelector('[data-planner-error]').textContent = error.message;
        } finally {
          toggle.disabled = false;
        }
      };
    } catch (error) {
      host.textContent = error.message || 'The self-project queue could not be read.';
    }
  }

  async function showProjects(dialog) {
    const host = dialog.querySelector('[data-self-projects]');
    if (!host) return;
    try {
      const response = await fetch(PROJECTS);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'The list of Thomas projects could not be read.');
      speedCache = data.speed_scoreboard || null;
      speedUpdated = Date.now();
      const rows = (data.projects || []).slice(0, 8);
      const unreadable = [...(data.unreadable || []), ...(data.warnings || [])];
      const warning = unreadable.length
        ? `<p role="status">Some Thomas projects could not be read, so this list may be missing some:</p><ul>${unreadable.map(sentence => `<li>${esc(sentence)}</li>`).join('')}</ul>`
        : '';
      const skipped = data.skipped || [];
      const skippedNote = skipped.length
        ? `<p role="status" style="margin:0 0 6px">Skipped, because they could not be read in several tries:</p><ul>${skipped.map(item => `<li>${esc(item.id)}: ${esc(item.reason)}</li>`).join('')}</ul>`
        : '';
      const slowest = data.slowest_today ? `<p style="margin:0 0 6px">${esc(data.slowest_today)}</p>` : '';
      host.innerHTML = warning + skippedNote + slowest + (rows.length
        ? `<p style="margin:0 0 6px;font-weight:700">Thomas projects right now</p><ul style="margin:0;padding-left:18px">${rows.map(projectRow).join('')}</ul>`
        : unreadable.length ? '' : data.refreshing ? '<p role="status">Checking Thomas projects…</p>' : '<p style="margin:0;color:var(--c-muted)">No Thomas project is going right now.</p>');
      if (data.refreshing && dialog.open) setTimeout(() => { if (dialog.open) void showProjects(dialog); }, 1100);
    } catch (error) {
      host.innerHTML = `<p style="margin:0;color:var(--c-muted)">${esc(error.message)}</p>`;
    }
  }

  function open() {
    document.getElementById('tc-self-edit-dialog')?.remove();
    const dialog = document.createElement('dialog');
    dialog.id = 'tc-self-edit-dialog';
    dialog.setAttribute('aria-labelledby', 'tc-self-edit-title');
    dialog.style.cssText = 'position:fixed;inset:0;margin:auto;width:min(580px,92vw);max-height:85vh;overflow:auto;background:var(--c-bg,#10121b);color:var(--c-text);border:1px solid var(--c-border);border-radius:16px;padding:24px;box-shadow:0 24px 80px #0009;';
    dialog.innerHTML = `<form style="display:grid;gap:14px"><h2 id="tc-self-edit-title" style="margin:0">Improve Thomas</h2>
      <p style="margin:0">Build's full team works in a private copy of Thomas's own source. Nothing reaches your running Thomas until you approve it on your sign-in card.</p>
      <div data-self-projects style="font-size:13px"></div>
      <div data-self-queue style="font-size:13px">Loading planned improvements…</div>
      <label for="tc-self-edit-request">What should Thomas change about himself?</label>
      <textarea id="tc-self-edit-request" rows="6" required spellcheck="true" placeholder="Describe the change in your own words. The team finds the files itself." style="width:100%;padding:12px;background:var(--c-bg);color:var(--c-text);border:1px solid var(--c-border);border-radius:8px"></textarea>
      <p role="status" data-self-edit-error style="margin:0"></p>
      <div style="display:flex;justify-content:flex-end;gap:12px"><button type="button" data-cancel>Cancel</button><button type="submit">Start a Thomas project</button></div></form>`;
    dialog.querySelector('[data-cancel]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove());
    dialog.querySelector('form').onsubmit = async event => {
      event.preventDefault();
      const button = dialog.querySelector('[type="submit"]');
      const status = dialog.querySelector('[data-self-edit-error]');
      button.disabled = true;
      try {
        const request = dialog.querySelector('textarea').value.trim();
        if (!request) throw new Error('Say what Thomas should change about himself.');
        const response = await fetch(PROJECTS, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request, settings: settings() }) });
        const data = await response.json();
        // The route's refusals are sentences meant to be read ("Autonomy ... may not edit"). Show the one it sent.
        if (!response.ok || !data.ok) throw new Error(data.error || 'Thomas could not start a project on himself.');
        dialog.querySelector('textarea').value = '';
        status.textContent = `Started. Its team is working in ${data.execution_id}; the change reaches your sign-in card when it is ready.`;
        await showProjects(dialog);
      } catch (error) {
        status.textContent = error.message;
      } finally { button.disabled = false; }
    };
    document.body.append(dialog);
    dialog.querySelectorAll('button').forEach(button => {
      button.style.cssText = 'padding:9px 13px;font:inherit;color:inherit;border:1px solid var(--c-border);border-radius:8px;background:var(--c-surface);cursor:pointer';
    });
    dialog.showModal();
    void showProjects(dialog);
    void showQueue(dialog);
  }

  // "Improve Thomas" picks Thomas's own source as the project, the way any project card is picked. You asked for
  // exactly that: "if you press improve Thomas, the selected project is the Thomas repo." The running server's
  // build root is that checkout, the same folder the send route refuses Code runs on.
  async function selectThomas(choose) {
    const response = await fetch('/api/health');
    const root = response.ok ? (await response.json())?.build?.root : '';
    if (!root) throw new Error('Thomas could not find his own source folder to select it.');
    await choose(root, 'Thomas');
  }

  // A message sent in Build with Thomas's own source selected is how he gets changed: it starts a Thomas project
  // (a private copy, checks, a second look, your sign-in card) with the words as they were typed, and the chat
  // moves to that project's conversation so everything it does stays in front of you.
  async function startFromChat(message) {
    const request = String(message || '').trim();
    const response = await fetch(PROJECTS, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request, settings: settings() }) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Thomas could not start a project on himself.');
    await window.ThomasCodeMode?.openConversation(data.conversation_id, { withinTab: true });
    return data;
  }

  function context(state) {
    if (!state.conversation?.self_edit) return null;
    const turn = [...(state.conversation.turns || [])].reverse().find(t => t.report?.self_edit);
    const rid = state.running ? state.runId : turn?.run_id;
    return { cid: state.activeId, rid, initial: turn?.report?.self_edit };
  }

  function html(state) {
    const ctx = context(state);
    // The scoreboard times Thomas's own landed self-changes, so it rides only on an Edit Thomas task;
    // an ordinary Build opens on the conversation alone (Build redesign 3a).
    if (!ctx) return '';
    const scoreboard = '<section class="tc-speed-scoreboard" aria-label="Build speed scoreboard" data-build-speed>' + speedHtml(speedCache) + '</section>';
    const record = records.get(key(ctx.cid, ctx.rid)) || ctx.initial || {};
    const status = state.running ? 'running' : record.status || 'draft';
    const labels = { draft: 'Private self-edit task', running: 'Editing a private copy', ready: 'Ready for review', failed: 'Needs repair', applied: 'Applied — restart and test', undone: 'Original files restored', discarded: 'Candidate discarded', recovery_required: 'Recovery required' };
    const busy = pending.has(key(ctx.cid, ctx.rid));
    const pendingMessages = { apply: 'Applying changes: checking source files and saving originals for Undo. This can take several minutes.', undo: 'Restoring the exact original files. Please wait.', restart: 'Restarting Thomas and waiting for the server to answer.', review: 'Loading the verified changes for review.', refresh: 'Refreshing the saved result.', discard: 'Discarding the private candidate.' };
    const reason = busy ? pendingMessages[pending.get(key(ctx.cid, ctx.rid))] : state.running ? 'Working in a private copy. Your running version stays unchanged until review and apply.' : record.uiError || record.reason || 'Describe the improvements below. Thomas will check them before you apply.';
    return `<section data-self-edit-card aria-label="Thomas self-edit" style="padding:16px;margin:12px 0;border:1px solid var(--c-border);border-radius:12px;overflow-wrap:anywhere">
      <strong>${esc(labels[status] || status)}</strong><p role="status">${esc(reason)}</p>
      <div>${(record.changed_files || state.conversation.self_edit_scope || []).map(p => `<div>${esc(p)}</div>`).join('')}</div>
      ${ctx.rid && !state.running ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button data-self-action="review" ${busy ? 'disabled' : ''}>Review changes</button>
        ${status === 'ready' ? `<button data-self-action="apply" ${busy || !record.reviewed ? 'disabled' : ''}>Apply changes</button>` : ''}
        ${['applied', 'recovery_required'].includes(status) ? `<button data-self-action="undo" ${busy ? 'disabled' : ''}>Undo this run</button>` : ''}
        ${['applied', 'undone'].includes(status) ? `<button data-self-action="restart" ${busy ? 'disabled' : ''}>Restart Thomas</button>` : ''}
        ${['ready', 'failed'].includes(status) ? `<button data-self-action="discard" ${busy ? 'disabled' : ''}>Discard candidate</button>` : ''}
        <button data-self-action="refresh" ${busy ? 'disabled' : ''}>Refresh status</button></div>` : ''}
      ${record.diff !== undefined ? `<details open><summary>Candidate changes</summary><pre style="max-height:350px;overflow:auto;white-space:pre-wrap">${esc(record.diff || 'No textual changes')}</pre></details>` : ''}
      ${status === 'applied' ? '<p>Source applied. Runtime behavior still needs verification after restart.</p>' : ''}</section>${scoreboard}`;
  }

  function bind(root, state, render) {
    const ctx = context(state);
    if (!ctx?.rid) return;
    root.querySelectorAll('[data-self-action]').forEach(button => button.addEventListener('click', async () => {
      const id = key(ctx.cid, ctx.rid), action = button.dataset.selfAction;
      if (pending.has(id)) return;
      pending.set(id, action); render();
      try {
        if (action === 'restart') {
          const result = await window.ThomasShellRestart();
          if (!result?.ok) throw new Error(result?.error || 'Restart could not be confirmed.');
          // A self-edit may change browser scripts as well as server modules.
          window.location.reload();
          return;
        }
        const reading = ['review', 'refresh'].includes(action);
        const url = reading ? `/api/evolve/agent/self-edit/${encodeURIComponent(ctx.cid)}/status?run_id=${encodeURIComponent(ctx.rid)}${action === 'review' ? '&review=1' : ''}` : `/api/evolve/agent/self-edit/${action}`;
        const response = await fetch(url, reading ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation_id: ctx.cid, run_id: ctx.rid }) });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Self-edit action failed.');
        records.set(id, { ...result, reviewed: action === 'review' && result.status === 'ready' });
      } catch (error) {
        records.set(id, { ...(records.get(id) || ctx.initial), uiError: error.message });
      } finally { pending.delete(id); render(); }
    }));
  }
  window.ThomasSelfEdit = { open, html, bind, loadSpeed, settings, showProjects, selectThomas, startFromChat };
})();
