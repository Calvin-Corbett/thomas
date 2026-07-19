(function () {
  'use strict';

  const state = {
    apps: [], accounts: [], connectors: [], activeApp: null, jobs: [], activeJob: null,
    messages: [], bindings: [], skills: [], automations: [], activity: [], workflows: [], activeWorkflowId: '',
    stage: 'home', onboardingPhase: 'goal_discovery', onboardingWorkflowId: '', onboardingSelectionUserTurn: 0, running: false, actionBusy: false, formDirty: false, editing: false, editingAutomationId: '', creatingJobInApp: false, sessionId: '', error: '', dashTab: '',
  };
  let reconcileTimer = null;
  let activeStreamController = null;
  let adapterActive = false;
  let selectionGeneration = 0;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const modes = () => window.ThomasUnifiedModes;
  const host = () => modes().host() || {};
  const surface = () => document.getElementById('tc-mode-surface');
  const appUrl = suffix => `/api/work/apps/${encodeURIComponent(state.activeApp.id)}${suffix || ''}`;
  const jobUrl = suffix => `${appUrl(`/jobs/${encodeURIComponent(state.activeJob.id)}`)}${suffix || ''}`;

  async function request(url, options) {
    const response = await fetch(url, options);
    let data;
    try { data = await response.json(); }
    catch (error) { throw new Error(`Work returned an unreadable response (${response.status})`); }
    if (!response.ok || data.ok === false) throw new Error(data.error || `Work request failed (${response.status})`);
    return data;
  }

  function jsonRequest(url, method, payload) {
    return request(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async function safely(action) {
    if (state.actionBusy) return;
    state.actionBusy = true;
    state.error = '';
    try {
      await action();
      state.formDirty = false;
    } catch (error) {
      state.error = error && error.message ? error.message : 'Work could not complete that action.';
    } finally { state.actionBusy = false; render(); }
  }

  function contextSettings() {
    const context = host().getContext ? host().getContext() : {};
    const dials = context.dials || {};
    return {
      profile: context.profile || undefined,
      model: context.profile || undefined,
      model_id: context.modelId || undefined,
      autonomy_level: dials.autonomy,
      file_access: dials.fileAccess,
      token_economy: dials.tokenEconomy,
      thomas_guardrails: dials.guardrails,
      reasoning_effort: dials.effort,
      memory: dials.memory !== false,
    };
  }
  function deriveName(text) {
    const cleaned = String(text || '').replace(/\s+/g, ' ').trim();
    if (!cleaned) return 'New job';
    return cleaned.split(/[.!?]/)[0].split(' ').slice(0, 7).join(' ').slice(0, 72) || 'New job';
  }
  function onboardingBrief() {
    return state.messages
      .filter(row => row.role === 'user')
      .map(row => String(row.text || row.content || '').trim())
      .filter(Boolean)
      .join('\n\n')
      .slice(0, 8000);
  }

  function activeJobDraft(app = state.activeApp) {
    const fields = app && app.onboarding && typeof app.onboarding.fields === 'object' ? app.onboarding.fields : {};
    return fields.job_draft && typeof fields.job_draft === 'object' ? fields.job_draft : {};
  }

  async function persistJobDraft(patch) {
    const data = await jsonRequest(appUrl('/onboarding'), 'PATCH', {
      fields: {
        job_draft: {
          ...activeJobDraft(),
          ...patch,
          updated_at: new Date().toISOString(),
        },
      },
    });
    state.activeApp.onboarding = data.onboarding;
  }

  function workflowRows(job) {
    const memory = job && job.memory && typeof job.memory === 'object' ? job.memory : {};
    return Array.isArray(memory.workflows) ? memory.workflows : [];
  }

  function activeWorkflowFor(job) {
    const memory = job && job.memory && typeof job.memory === 'object' ? job.memory : {};
    const activeId = String((memory.metadata || {}).active_workflow_id || '');
    return workflowRows(job).find(row => String(row.id || '') === activeId) || null;
  }

  function statusPill(status) {
    const value = String(status || 'active');
    return `<span class="tc-work-status is-${esc(value)}">${esc(value.replace(/_/g, ' '))}</span>`;
  }

  function safeArtifactHref(value) {
    const reference = String(value || '').trim();
    if (!reference || /[\u0000-\u001f\u007f\\]/.test(reference) || reference.startsWith('//')) return '';
    try {
      const decodedPath = decodeURIComponent(reference.split(/[?#]/, 1)[0]);
      if (decodedPath.includes('\\') || decodedPath.split('/').includes('..')) return '';
      const resolved = new URL(reference, window.location.href);
      return ['http:', 'https:'].includes(resolved.protocol) && !resolved.username && !resolved.password
        ? reference
        : '';
    } catch (error) { return ''; }
  }

  function visibleWorkMessage(message) {
    const text = String((message || {}).content || (message || {}).text || '');
    if (String((message || {}).role || '') === 'user' && text.startsWith('[Private Thomas Work onboarding context.')) {
      const boundary = text.indexOf('\n\n');
      return boundary >= 0 ? text.slice(boundary + 2) : '';
    }
    return text;
  }

  const {
    onboardingWorkflowCandidates,
    selectedOnboardingWorkflow,
    onboardingConfigurationReady,
    onboardingWorkflowDrafts,
    restoreOnboardingWorkflow,
    confirmedOnboardingGoal,
    visibleOnboardingText,
    onboardingInstruction,
    messageRows,
    homeHtml,
    onboardingHtml,
    connectorHtml,
    automationHtml,
    skillsHtml,
    dashboardHtml,
    activityHtml,
    workflowRailHtml,
    jobHtml,
    provisionOnboardedJob,
  } = window.ThomasWorkSupport.create({
    state, esc, activeWorkflowFor, statusPill, safeArtifactHref,
    onboardingBrief, jsonRequest, appUrl,
  });

  function showAllWork() {
    if (activeStreamController) activeStreamController.abort();
    selectionGeneration += 1;
    clearTimeout(reconcileTimer);
    reconcileTimer = null;
    state.activeApp = null;
    state.activeJob = null;
    state.jobs = [];
    state.messages = [];
    state.workflows = [];
    state.activeWorkflowId = '';
    state.sessionId = '';
    state.creatingJobInApp = false;
    state.onboardingPhase = 'goal_discovery';
    state.onboardingWorkflowId = '';
    state.onboardingSelectionUserTurn = 0;
    state.stage = 'home';
    state.error = '';
    render();
    host().renderHistory && host().renderHistory();
  }

  function render() {
    if (!adapterActive) return;
    const root = surface(); if (!root) return;
    root.innerHTML = state.stage === 'onboarding' ? onboardingHtml() : state.stage === 'job' && state.activeJob ? jobHtml() : homeHtml();
    if (state.error) root.insertAdjacentHTML('afterbegin', `<div class="tc-work-error" role="alert">${esc(state.error)}</div>`);
    root.querySelectorAll('[data-work-create]').forEach(button => button.addEventListener('click', newConversation));
    root.querySelector('[data-work-create-job]')?.addEventListener('click', newJobInApp);
    root.querySelectorAll('[data-work-app]').forEach(button => button.addEventListener('click', () => { void safely(() => openApp(button.dataset.workApp)); }));
    root.querySelector('[data-work-all-apps]')?.addEventListener('click', showAllWork);
    root.querySelector('[data-work-all-jobs]')?.addEventListener('click', showAllWork);
    root.querySelector('[data-work-cancel-onboarding]')?.addEventListener('click', showAllWork);
    root.querySelectorAll('[data-work-open-job]').forEach(button => button.addEventListener('click', () => { void safely(() => openJob(state.activeApp.id, button.dataset.workOpenJob)); }));
    root.querySelectorAll('[data-work-card-open]').forEach(button => button.addEventListener('click', () => { void safely(() => openJob(button.dataset.workAppId, button.dataset.workJobId)); }));
    root.querySelectorAll('[data-work-card-status]').forEach(button => button.addEventListener('click', () => { void safely(() => setCardJobStatus(button.dataset.workAppId, button.dataset.workJobId, button.dataset.workCardStatus)); }));
    root.querySelectorAll('[data-work-card-run]').forEach(button => button.addEventListener('click', () => { void safely(() => runCardWorkflow(button.dataset.workAppId, button.dataset.workJobId, button.dataset.workWorkflowId)); }));
    root.querySelector('[data-work-finish]')?.addEventListener('click', () => { void safely(finishOnboarding); });
    root.querySelector('[data-work-status]')?.addEventListener('click', event => { void safely(() => setJobStatus(event.currentTarget.dataset.workStatus)); });
    root.querySelector('[data-work-edit]')?.addEventListener('click', () => { state.editing = true; render(); });
    root.querySelector('[data-work-edit-cancel]')?.addEventListener('click', () => { state.editing = false; state.formDirty = false; render(); });
    root.querySelector('[data-work-archive]')?.addEventListener('click', () => { void safely(archiveJob); });
    root.querySelector('#tc-work-job-edit')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => editJob(new FormData(event.currentTarget))); });
    root.querySelectorAll('[data-work-bind]').forEach(button => button.addEventListener('click', () => { void safely(() => bindAccount(button.dataset.workBind)); }));
    root.querySelectorAll('[data-work-connect]').forEach(form => form.addEventListener('submit', event => { event.preventDefault(); void safely(() => connectAccount(event.currentTarget.dataset.workConnect, new FormData(event.currentTarget))); }));
    root.querySelectorAll('[data-work-deploy]').forEach(button => button.addEventListener('click', () => { void safely(() => deployAutomation(button.dataset.workDeploy)); }));
    root.querySelectorAll('[data-work-automation-edit-open]').forEach(button => button.addEventListener('click', () => { state.editingAutomationId = button.dataset.workAutomationEditOpen; render(); }));
    root.querySelector('[data-work-automation-edit-cancel]')?.addEventListener('click', () => { state.editingAutomationId = ''; state.formDirty = false; render(); });
    root.querySelector('[data-work-automation-edit]')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => updateAutomation(event.currentTarget.dataset.workAutomationEdit, new FormData(event.currentTarget))); });
    root.querySelectorAll('[data-work-automation-toggle]').forEach(button => button.addEventListener('click', () => { void safely(() => toggleAutomation(button.dataset.workAutomationToggle)); }));
    root.querySelectorAll('[data-work-automation-delete]').forEach(button => button.addEventListener('click', () => { void safely(() => deleteAutomation(button.dataset.workAutomationDelete)); }));
    root.querySelectorAll('[data-work-promote-request]').forEach(button => button.addEventListener('click', () => { void safely(() => requestPromotion(button.dataset.workPromoteRequest)); }));
    root.querySelectorAll('[data-work-promote-approve]').forEach(button => button.addEventListener('click', () => { void safely(() => approvePromotion(button.dataset.workPromoteApprove)); }));
    root.querySelectorAll('[data-work-workflow-select]').forEach(button => button.addEventListener('click', () => { void safely(() => selectWorkflow(button.dataset.workWorkflowSelect)); }));
    root.querySelectorAll('[data-work-workflow-activate]').forEach(button => button.addEventListener('click', () => { void safely(() => activateWorkflow(button.dataset.workWorkflowActivate)); }));
    root.querySelectorAll('[data-work-workflow-run]').forEach(button => button.addEventListener('click', () => { void safely(() => runWorkflowOnce(button.dataset.workWorkflowRun)); }));
    root.querySelector('[data-work-workflow-automation]')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => configureWorkflowAutomation(event.currentTarget.dataset.workWorkflowAutomation, new FormData(event.currentTarget))); });
    root.querySelector('#tc-work-workflow-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => createWorkflow(new FormData(event.currentTarget))); });
    root.querySelector('#tc-work-account-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => createAccount(new FormData(event.currentTarget))); });
    root.querySelector('#tc-work-automation-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => createAutomation(new FormData(event.currentTarget))); });
    root.querySelector('#tc-work-skill-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => createSkill(new FormData(event.currentTarget))); });
    root.querySelector('#tc-work-dashboard-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => updateDashboard(new FormData(event.currentTarget))); });
    root.querySelector('[data-work-dashboard-design]')?.addEventListener('click', () => { void safely(designDashboard); });
    root.querySelectorAll('[data-work-dashboard-run]').forEach(button => button.addEventListener('click', () => { void safely(() => runDashboardAction(button.dataset.workDashboardRun)); }));
    root.querySelectorAll('[data-work-dash-tab]').forEach(button => button.addEventListener('click', () => { state.dashTab = button.dataset.workDashTab; render(); }));
    root.querySelectorAll('[data-work-sheet-addrow]').forEach(button => button.addEventListener('click', () => {
      const holder = root.querySelector(`[data-work-sheet="${button.dataset.workSheetAddrow}"] tbody`);
      const cols = root.querySelectorAll(`[data-work-sheet="${button.dataset.workSheetAddrow}"] thead th`).length;
      if (holder && cols) { const tr = document.createElement('tr'); tr.innerHTML = Array.from({ length: cols }, () => '<td contenteditable="true" spellcheck="false"></td>').join(''); holder.appendChild(tr); }
    }));
    root.querySelectorAll('[data-work-sheet-save]').forEach(button => button.addEventListener('click', () => { void safely(() => saveSheet(button.dataset.workSheetSave)); }));
    const composer = root.querySelector('#tc-work-composer');
    if (composer) {
      const field = composer.querySelector('textarea');
      const submitComposer = () => {
        const value = field ? field.value : '';
        if (!String(value || '').trim() || state.running) return;
        if (field) field.value = '';
        void send(value);
      };
      composer.addEventListener('submit', event => { event.preventDefault(); submitComposer(); });
      if (field) {
        // Enter sends, Shift+Enter is a newline; grow with content like main chat.
        field.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submitComposer(); } });
        field.addEventListener('input', () => { field.style.height = 'auto'; field.style.height = Math.min(field.scrollHeight, 160) + 'px'; });
        if (!state.running && document.activeElement !== field) { try { field.focus({ preventScroll: true }); } catch (e) { field.focus(); } }
      }
    }
    root.querySelectorAll('form input, form textarea, form select').forEach(element => {
      element.addEventListener('input', () => { state.formDirty = true; });
      element.addEventListener('change', () => { state.formDirty = true; });
    });
    requestAnimationFrame(() => { const transcript = root.querySelector('.tc-work-transcript'); if (transcript) transcript.scrollTop = transcript.scrollHeight; });
  }

  async function refresh() {
    try {
      const [apps, accounts, connectors] = await Promise.all([request('/api/work/apps'), request('/api/work/accounts'), request('/api/work/connectors')]);
      state.apps = Array.isArray(apps.apps) ? apps.apps : [];
      state.accounts = Array.isArray(accounts.accounts) ? accounts.accounts : [];
      state.connectors = Array.isArray(connectors.connectors) ? connectors.connectors : [];
      state.error = '';
      if (state.activeApp) state.activeApp = state.apps.find(row => row.id === state.activeApp.id) || state.activeApp;
      host().renderHistory && host().renderHistory(); render();
    } catch (error) { state.error = error.message; render(); }
  }

  function renderHistory(root, query) {
    const term = String(query || '').trim().toLowerCase(); root.innerHTML = '';
    const apps = state.apps.filter(app => !term || `${app.name} ${app.goal}`.toLowerCase().includes(term) || Object.values(app.jobs || {}).some(job => `${job.name} ${job.goal}`.toLowerCase().includes(term)));
    if (!apps.length) { root.innerHTML = `<div class="tc-mode-empty">${term ? 'No matching jobs.' : 'No jobs yet.'}</div>`; return; }
    apps.forEach(app => {
      const heading = document.createElement('button'); heading.className = 'tc-work-history-app'; heading.innerHTML = `<span>${esc(app.name)}</span><small>${esc(app.status)}</small>`; heading.addEventListener('click', () => { void safely(() => openApp(app.id)); }); root.appendChild(heading);
      Object.values(app.jobs || {}).filter(job => job.status !== 'archived' && (!term || `${job.name} ${job.goal}`.toLowerCase().includes(term))).forEach(job => {
        const button = document.createElement('button'); button.className = 'hv-soft tc-mode-history-row tc-work-history-job'; if (state.activeJob && job.id === state.activeJob.id) button.classList.add('is-active');
        button.innerHTML = `<span>${esc(job.name)}</span><small>${esc(job.status)} · ${Number((job.history || {}).message_count || 0)} messages</small>`; button.addEventListener('click', () => { void safely(() => openJob(app.id, job.id)); }); root.appendChild(button);
      });
    });
  }

  async function openApp(id) {
    if (activeStreamController) activeStreamController.abort();
    clearTimeout(reconcileTimer); reconcileTimer = null;
    const generation = ++selectionGeneration;
    const data = await request(`/api/work/apps/${encodeURIComponent(id)}`);
    const jobsData = await request(`/api/work/apps/${encodeURIComponent(id)}/jobs`);
    const draft = activeJobDraft(data.app);
    const draftSessionId = String(draft.session_id || '');
    const draftChats = draftSessionId
      ? await request(`/api/chats?mode=work&context_id=${encodeURIComponent(`${id}:onboarding:${draftSessionId}`)}`)
      : null;
    if (!adapterActive || generation !== selectionGeneration) return;
    state.activeApp = data.app; state.jobs = jobsData.jobs || [];
    state.activeJob = null; state.messages = []; state.workflows = []; state.activeWorkflowId = ''; state.onboardingWorkflowId = ''; state.onboardingSelectionUserTurn = 0; state.creatingJobInApp = false;
    if (draftSessionId) {
      const row = (draftChats.chats || []).find(chat => String(chat.session_id || chat.sessionId || '') === draftSessionId);
      state.stage = 'onboarding';
      state.creatingJobInApp = true;
      state.sessionId = draftSessionId;
      state.onboardingPhase = String(draft.phase || 'goal_discovery');
      state.messages = row ? (row.messages || []).map(message => ({ role: message.role, text: visibleWorkMessage(message) })) : [];
      restoreOnboardingWorkflow(draft);
    } else if (state.activeApp.onboarding && state.activeApp.onboarding.state !== 'ready') {
      state.stage = 'onboarding'; state.messages = (state.activeApp.onboarding.messages || []).map(row => ({ role: row.role === 'thomas' ? 'assistant' : row.role, text: row.text }));
      const onboardingFields = state.activeApp.onboarding.fields || {};
      state.sessionId = String(onboardingFields.session_id || '');
      state.onboardingPhase = String(state.activeApp.onboarding.phase || 'goal_discovery');
      restoreOnboardingWorkflow(onboardingFields);
    } else state.stage = 'home';
    render(); host().renderHistory && host().renderHistory();
  }

  async function openJob(appId, jobId) {
    if (activeStreamController) activeStreamController.abort();
    clearTimeout(reconcileTimer); reconcileTimer = null;
    const generation = ++selectionGeneration;
    const app = !state.activeApp || state.activeApp.id !== appId
      ? (await request(`/api/work/apps/${encodeURIComponent(appId)}`)).app
      : state.activeApp;
    const base = `/api/work/apps/${encodeURIComponent(appId)}/jobs/${encodeURIComponent(jobId)}`;
    const job = (await request(base)).job;
    const [automations, chats, bindings, skills, activity, workflows] = await Promise.all([
      request(`${base}/automations`), request(`/api/chats?mode=work&context_id=${encodeURIComponent(`${appId}:${jobId}`)}`), request(`${base}/bindings`), request(`${base}/skills`), request(`${base}/activity`), request(`${base}/workflows`),
    ]);
    if (!adapterActive || generation !== selectionGeneration) return;
    state.activeApp = app; state.activeJob = job;
    state.sessionId = String((job.history || {}).session_id || ''); state.stage = 'job'; state.messages = []; state.formDirty = false; state.editing = false; state.editingAutomationId = '';
    const row = (chats.chats || []).find(chat => String(chat.session_id || chat.sessionId || '') === state.sessionId);
    state.messages = row ? (row.messages || []).map(message => ({ role: message.role, text: visibleWorkMessage(message) })) : [];
    state.bindings = bindings.bindings || []; state.skills = skills.skills || []; state.automations = automations.automations || []; state.activity = activity.activity || [];
    state.workflows = workflows.workflows || []; state.activeWorkflowId = String(workflows.active_workflow_id || '');
    render(); host().renderHistory && host().renderHistory();
    scheduleJobReconcile(generation, appId, jobId);
  }

  function scheduleJobReconcile(generation, appId, jobId) {
    clearTimeout(reconcileTimer);
    reconcileTimer = setTimeout(() => {
      const sameJob = adapterActive && generation === selectionGeneration && state.stage === 'job' && state.activeJob && state.activeJob.id === jobId;
      if (!sameJob) return;
      const draftIsActive = state.running || state.actionBusy || state.formDirty || state.editing || state.editingAutomationId || surface()?.querySelector('form:focus-within');
      if (draftIsActive) {
        scheduleJobReconcile(generation, appId, jobId);
        return;
      }
      void safely(() => openJob(appId, jobId));
    }, 15000);
  }

  function newConversation() {
    if (activeStreamController) activeStreamController.abort();
    selectionGeneration += 1; clearTimeout(reconcileTimer); reconcileTimer = null; state.activeApp = null; state.activeJob = null; state.messages = []; state.workflows = []; state.activeWorkflowId = ''; state.onboardingWorkflowId = ''; state.onboardingSelectionUserTurn = 0; state.sessionId = ''; state.creatingJobInApp = false; state.onboardingPhase = 'goal_discovery'; state.stage = 'onboarding'; state.error = ''; render();
  }

  function newJobInApp() {
    if (activeStreamController) activeStreamController.abort();
    selectionGeneration += 1; clearTimeout(reconcileTimer); reconcileTimer = null; state.activeJob = null; state.messages = []; state.workflows = []; state.activeWorkflowId = ''; state.onboardingWorkflowId = ''; state.onboardingSelectionUserTurn = 0; state.sessionId = ''; state.creatingJobInApp = true; state.onboardingPhase = 'goal_discovery'; state.stage = 'onboarding'; state.error = ''; render();
  }

  async function ensureOnboardingApp(firstMessage, generation) {
    if (state.activeApp && state.creatingJobInApp) {
      if (!state.sessionId) {
        const session = await request('/api/session/new', { method: 'POST' });
        if (generation !== selectionGeneration) return false;
        state.sessionId = String(session.session_id || (session.data || {}).session_id || '');
        await persistJobDraft({
          session_id: state.sessionId,
          phase: state.onboardingPhase,
          selected_workflow: '',
          selected_workflow_id: '',
        });
      }
      return true;
    }
    if (state.activeApp) return true;
    const created = await request('/api/work/apps', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: deriveName(firstMessage), goal: '' }) });
    if (generation !== selectionGeneration) return false;
    state.activeApp = created.app;
    const appBase = `/api/work/apps/${encodeURIComponent(created.app.id)}`;
    await request(appBase, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal: firstMessage }) });
    if (generation !== selectionGeneration) return false;
    const session = await request('/api/session/new', { method: 'POST' });
    if (generation !== selectionGeneration) return false;
    state.sessionId = String(session.session_id || (session.data || {}).session_id || '');
    await request(`${appBase}/onboarding`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: { session_id: state.sessionId } }) });
    return generation === selectionGeneration;
  }

  async function appendOnboarding(role, text) {
    if (state.creatingJobInApp) return;
    await request(appUrl('/onboarding/messages'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: role === 'assistant' ? 'thomas' : role, text }) });
  }

  async function advanceOnboardingPhase() {
    const candidates = onboardingWorkflowCandidates();
    const selected = selectedOnboardingWorkflow(candidates);
    const confirmedGoal = confirmedOnboardingGoal();
    const nextPhase = state.onboardingPhase === 'workflow_configuration'
      ? 'workflow_configuration'
      : selected && state.onboardingPhase === 'workflow_mapping'
        ? 'workflow_configuration'
        : candidates.length >= 3 ? 'workflow_mapping' : 'goal_discovery';
    const phaseFields = {
      session_id: state.sessionId,
      confirmed_goal: confirmedGoal,
      workflow_count: candidates.length,
      selected_workflow: selected ? selected.name : '',
      selected_workflow_id: selected ? state.onboardingWorkflowId : '',
      selected_workflow_user_turn: selected ? state.onboardingSelectionUserTurn : 0,
      selected_workflow_configured: onboardingConfigurationReady(candidates, selected),
    };
    if (state.creatingJobInApp) await persistJobDraft({ phase: nextPhase, ...phaseFields });
    else {
      const update = { fields: phaseFields };
      if (nextPhase !== state.onboardingPhase) update.phase = nextPhase;
      await jsonRequest(appUrl('/onboarding'), 'PATCH', update);
    }
    state.onboardingPhase = nextPhase;
  }

  async function readChatStream(message, options) {
    const response = await fetch('/api/v2/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: options.signal, body: JSON.stringify({ message, display_prompt: options.displayPrompt || undefined, session_id: state.sessionId || undefined, surface_mode: 'work', context_id: options.contextId, ...contextSettings() }) });
    if (!response.ok || !response.body) {
      const problemText = await response.text();
      let problem = {};
      if (problemText) {
        try { problem = JSON.parse(problemText); }
        catch (error) { throw new Error(`Thomas returned an unreadable error response (${response.status})`); }
      }
      throw new Error(problem.error || `Thomas could not answer (${response.status})`);
    }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let answer = '';
    while (true) {
      const part = await reader.read();
      buffer += decoder.decode(part.value || new Uint8Array(), { stream: !part.done });
      const lines = buffer.split('\n'); buffer = part.done ? '' : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let event;
        try { event = JSON.parse(line); }
        catch (error) { throw new Error('Thomas returned a malformed stream event.'); }
        const type = event.type;
        if (['text', 'agent_text', 'delta', 'assistant_delta', 'message_delta'].includes(type)) {
          answer += String(event.text || event.delta || event.content || '');
          if (options.onDelta) options.onDelta(answer);
        }
        else if (type === 'done') { state.sessionId = String(event.session_id || state.sessionId); if (!answer) answer = String(event.final || event.output_text || event.text || ''); }
        else if (type === 'error') throw new Error(event.error || 'Thomas reported an error');
      }
      if (part.done) break;
    }
    return answer.trim() || 'I need one more detail before I can finish setting up this job.';
  }

  async function send(message) {
    const text = String(message || '').trim(); if (!text || state.running) return;
    const generation = selectionGeneration;
    const controller = new AbortController();
    activeStreamController = controller;
    state.running = true; host().setBusy && host().setBusy(true); state.error = '';
    try {
      if (state.stage === 'onboarding') {
        if (!await ensureOnboardingApp(text, generation)) return;
        state.messages.push({ role: 'user', text }); await appendOnboarding('user', text); render();
        const turn = state.messages.filter(row => row.role === 'user').length;
        const jobName = state.creatingJobInApp ? deriveName((state.messages.find(row => row.role === 'user') || {}).text) : state.activeApp.name;
        const instruction = `[Private Thomas Work onboarding context. ${onboardingInstruction(jobName, turn)} This is follow-up ${turn}. Do not repeat answered questions and do not claim setup is complete.]\n\n${text}`;
        const contextId = state.creatingJobInApp ? `${state.activeApp.id}:onboarding:${state.sessionId}` : state.activeApp.id;
        const pending = { role: 'assistant', text: '' }; state.messages.push(pending); render();
        const answer = await readChatStream(instruction, { contextId, displayPrompt: text, signal: controller.signal, onDelta: value => { if (generation === selectionGeneration) { pending.text = value; if (adapterActive) render(); } } });
        if (generation !== selectionGeneration) return;
        pending.text = answer; await appendOnboarding('assistant', answer);
        await advanceOnboardingPhase();
      } else if (state.stage === 'job' && state.activeJob) {
        state.messages.push({ role: 'user', text }); render();
        const pending = { role: 'assistant', text: '' }; state.messages.push(pending); render();
        const answer = await readChatStream(text, { contextId: `${state.activeApp.id}:${state.activeJob.id}`, signal: controller.signal, onDelta: value => { if (generation === selectionGeneration) { pending.text = value; if (adapterActive) render(); } } });
        if (generation !== selectionGeneration) return;
        pending.text = answer;
        await request(jobUrl('/history'), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_count: state.messages.length, last_message_at: new Date().toISOString() }) });
      } else { newConversation(); return send(text); }
      await refresh();
    } catch (error) {
      if (generation !== selectionGeneration) return;
      const last = state.messages[state.messages.length - 1];
      if (last && (last.role === 'assistant' || last.role === 'thomas') && !String(last.text || '').trim()) state.messages.pop();
      if (controller.signal.aborted) {
        state.messages.push({ role: 'assistant', text: 'Stopped.' });
        return;
      }
      state.error = error.message; state.messages.push({ role: 'assistant', text: `I couldn't safely complete that Work turn: ${error.message}` });
    }
    finally {
      if (activeStreamController === controller) activeStreamController = null;
      state.running = false;
      host().setBusy && host().setBusy(false);
      if (adapterActive && generation === selectionGeneration) {
        render();
        host().renderHistory && host().renderHistory();
      }
    }
  }

  async function finishOnboarding() {
    if (!state.activeApp) return;
    const candidates = onboardingWorkflowCandidates();
    if (state.onboardingPhase !== 'workflow_configuration' || candidates.length < 3 || candidates.length > 6) throw new Error('Thomas needs a complete map of three to six workflows before creating this job.');
    const requestedSelection = selectedOnboardingWorkflow(candidates);
    if (!requestedSelection) throw new Error('Choose one named or numbered workflow before creating this job.');
    if (!onboardingConfigurationReady(candidates, requestedSelection)) throw new Error('Answer at least one configuration question about the selected workflow before creating this job.');
    const confirmedGoal = confirmedOnboardingGoal();
    if (!confirmedGoal) throw new Error('Thomas needs to confirm the job goal before creating workflows.');
    if (!state.sessionId) throw new Error('The onboarding session is missing; continue the conversation once before retrying.');
    const firstUserMessage = (state.messages.find(row => row.role === 'user') || {}).text || '';
    const goal = confirmedGoal;
    const settings = contextSettings(); const jobSettings = { model_id: settings.model_id, profile: settings.profile, reasoning_effort: settings.reasoning_effort, autonomy: settings.autonomy_level, file_access: settings.file_access, memory: settings.memory, guardrails: settings.thomas_guardrails, token_economy: settings.token_economy };
    Object.keys(jobSettings).forEach(key => jobSettings[key] == null && delete jobSettings[key]);
    const data = await jsonRequest(appUrl('/jobs'), 'POST', { name: state.creatingJobInApp ? deriveName(firstUserMessage) : state.activeApp.name, goal, description: 'Created conversationally with Thomas Work.', history_session_id: state.sessionId, idempotency_key: state.sessionId, settings: jobSettings });
    const base = appUrl(`/jobs/${encodeURIComponent(data.job.id)}`);
    const [existingWorkflowData, existingAutomationData] = await Promise.all([request(`${base}/workflows`), request(`${base}/automations`)]);
    const existingWorkflows = existingWorkflowData.workflows || [];
    const existingAutomations = existingAutomationData.automations || [];
    const drafts = onboardingWorkflowDrafts(candidates);
    const createdWorkflows = [];
    for (const draft of drafts) {
      let workflow = existingWorkflows.find(row => row.id === draft.id);
      if (!workflow) workflow = (await jsonRequest(`${base}/workflows`, 'POST', draft)).workflow;
      if (workflow.type === 'manual') {
        const automationId = `${workflow.id}-run`.slice(0, 80).replace(/-+$/g, '');
        let automation = existingAutomations.find(row => row.id === automationId);
        if (!automation) automation = (await jsonRequest(`${base}/automations`, 'POST', { id: automationId, name: `${workflow.name} run once`, enabled: true, trigger: { type: 'manual' }, mission_template: { goal: workflow.purpose, requires_approval: false } })).automation;
        if (workflow.automation_id !== automation.id) workflow = (await jsonRequest(`${base}/workflows/${encodeURIComponent(workflow.id)}`, 'PATCH', { automation_id: automation.id })).workflow;
      }
      createdWorkflows.push(workflow);
    }
    const selectedDraft = drafts[candidates.indexOf(requestedSelection)];
    const selected = createdWorkflows.find(workflow => workflow.id === selectedDraft.id);
    if (selected && existingWorkflowData.active_workflow_id !== selected.id) await request(`${base}/workflows/${encodeURIComponent(selected.id)}/select`, { method: 'POST' });
    const setupFailures = await provisionOnboardedJob(data.job);
    if (setupFailures.length) throw new Error(`Job setup is saved and can resume, but ${setupFailures.join(', ')} still needs attention.`);
    if (!state.creatingJobInApp) await jsonRequest(appUrl(), 'PATCH', { goal });
    if (state.creatingJobInApp) {
      const cleared = await jsonRequest(appUrl('/onboarding'), 'PATCH', { fields: { job_draft: {} } });
      state.activeApp.onboarding = cleared.onboarding;
    } else {
      await jsonRequest(appUrl('/onboarding'), 'PATCH', { phase: 'ready', state: 'ready', next_prompt: '' });
    }
    state.creatingJobInApp = false;
    await refresh(); await openJob(state.activeApp.id, data.job.id);
  }

  async function setJobStatus(action) { const data = await request(jobUrl(`/${action}`), { method: 'POST' }); state.activeJob = data.job; await refresh(); render(); }
  async function setCardJobStatus(appId, jobId, action) {
    await request(`/api/work/apps/${encodeURIComponent(appId)}/jobs/${encodeURIComponent(jobId)}/${encodeURIComponent(action)}`, { method: 'POST' });
    await refresh();
  }
  async function runCardWorkflow(appId, jobId, workflowId) {
    if (!workflowId) throw new Error('Choose and activate a manual workflow before running this job.');
    const data = await request(`/api/work/apps/${encodeURIComponent(appId)}/jobs/${encodeURIComponent(jobId)}/workflows/${encodeURIComponent(workflowId)}/run-once`, { method: 'POST' });
    const missionId = String((data.mission || {}).job_id || '');
    host().announce && host().announce(missionId ? `Mission ${missionId} started.` : 'Workflow started through Mission.');
    await refresh();
  }
  async function createWorkflow(form) {
    const fields = Object.fromEntries(form.entries());
    const base = jobUrl('/workflows');
    const created = await jsonRequest(base, 'POST', fields);
    let workflow = created.workflow;
    if (workflow.type === 'manual') {
      const automation = await jsonRequest(jobUrl('/automations'), 'POST', {
        name: `${workflow.name} run once`,
        enabled: true,
        trigger: { type: 'manual' },
        mission_template: { goal: workflow.purpose, requires_approval: false },
      });
      workflow = (await jsonRequest(`${base}/${encodeURIComponent(workflow.id)}`, 'PATCH', { automation_id: automation.automation.id })).workflow;
    }
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function configureWorkflowAutomation(workflowId, form) {
    const workflow = state.workflows.find(row => row.id === workflowId);
    if (!workflow) throw new Error('The selected workflow is no longer available.');
    const fields = Object.fromEntries(form.entries());
    const kind = String(fields.trigger || 'manual');
    const detail = String(fields.detail || '').trim();
    let trigger = { type: kind };
    if (kind === 'interval') trigger.every_seconds = Math.max(60, (parseInt(detail, 10) || 15) * 60);
    if (kind === 'daily') trigger = { type: kind, at: detail || '08:30', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' };
    if (kind === 'weekly') trigger = { type: kind, at: detail || '08:30', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', dow: [0, 1, 2, 3, 4] };
    if (kind === 'event') trigger.event_name = (detail || 'work_event').toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
    const automationId = `${workflow.id}-runner`.slice(0, 80).replace(/-+$/g, '');
    const automation = await jsonRequest(jobUrl('/automations'), 'POST', {
      id: automationId,
      name: `${workflow.name} runner`,
      enabled: true,
      trigger,
      mission_template: { goal: workflow.purpose, requires_approval: fields.requires_approval === 'on' },
    });
    await jsonRequest(jobUrl(`/workflows/${encodeURIComponent(workflow.id)}`), 'PATCH', { automation_id: automation.automation.id });
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function selectWorkflow(workflowId) {
    await request(jobUrl(`/workflows/${encodeURIComponent(workflowId)}/select`), { method: 'POST' });
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function activateWorkflow(workflowId) {
    await jsonRequest(jobUrl(`/workflows/${encodeURIComponent(workflowId)}`), 'PATCH', { status: 'active' });
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function runWorkflowOnce(workflowId) {
    const data = await request(jobUrl(`/workflows/${encodeURIComponent(workflowId)}/run-once`), { method: 'POST' });
    const missionId = String((data.mission || {}).job_id || '');
    host().announce && host().announce(missionId ? `Mission ${missionId} started.` : 'Workflow started through Mission.');
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function editJob(form) { const fields = Object.fromEntries(form.entries()); const data = await request(jobUrl(), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: fields.name, goal: fields.goal }) }); state.activeJob = data.job; state.editing = false; await refresh(); render(); }
  async function archiveJob() { await request(jobUrl('/archive'), { method: 'POST' }); const appId = state.activeApp.id; state.activeJob = null; state.stage = 'home'; await refresh(); await openApp(appId); }
  async function createAccount(form) { const fields = Object.fromEntries(form.entries()); const credential = String(fields.credential || ''); delete fields.credential; const created = await request('/api/work/accounts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields) }); if (credential) await request(`/api/work/accounts/${encodeURIComponent(created.account.id)}/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential }) }); await refresh(); }
  async function connectAccount(accountId, form) { const credential = String(form.get('credential') || ''); await request(`/api/work/accounts/${encodeURIComponent(accountId)}/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential }) }); await refresh(); }
  async function bindAccount(accountId) { const account = state.accounts.find(row => row.id === accountId); const connector = account && state.connectors.find(row => row.id === account.provider); if (!account || !connector) throw new Error('This connector is unavailable and was not bound.'); if (!account.has_credentials) throw new Error('Connect this account before binding it to a job.'); await request(jobUrl('/bindings'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_id: accountId, scopes: ['read'] }) }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function createSkill(form) { await request(jobUrl('/skills'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form.entries())) }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function requestPromotion(id) { await request(jobUrl(`/skills/${encodeURIComponent(id)}/promotion/request`), { method: 'POST' }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function approvePromotion(id) { await request(jobUrl(`/skills/${encodeURIComponent(id)}/promotion/approve`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approved_by: 'local_owner' }) }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function updateDashboard(form) { const fields = Object.fromEntries(form.entries()); const dashboard = state.activeJob.dashboard || {}; const metrics = [...(dashboard.metrics || [])]; const sections = [...(dashboard.sections || [])]; if (String(fields.metric_label || '').trim()) metrics.push({ label: fields.metric_label, value: fields.metric_value }); if (String(fields.section_title || '').trim()) sections.push({ title: fields.section_title, text: fields.section_text }); if (!String(fields.metric_label || '').trim() && !String(fields.section_title || '').trim()) return; await request(jobUrl('/dashboard'), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ metrics, sections }) }); await openJob(state.activeApp.id, state.activeJob.id); }
  // The AI designs this job's dashboard server-side from its real context;
  // buttons it creates only ever bind to the job's own workflows.
  async function designDashboard() { await request(jobUrl('/dashboard/design'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }); await openJob(state.activeApp.id, state.activeJob.id); }
  // Serialize the edited table (textContent per cell — no markup) back into
  // the dashboard's sheets array and persist the whole set.
  async function saveSheet(sheetId) {
    const holder = document.querySelector(`[data-work-sheet="${sheetId}"]`);
    if (!holder || !state.activeJob) return;
    const rows = [...holder.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => (td.textContent || '').trim().slice(0, 200)));
    const sheets = [...((state.activeJob.dashboard || {}).sheets || [])].map(s => s.id === sheetId ? { ...s, rows: rows.filter(r => r.some(c => c)) } : s);
    await request(jobUrl('/dashboard'), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sheets }) });
    await openJob(state.activeApp.id, state.activeJob.id);
  }
  async function runDashboardAction(actionId) { await request(jobUrl(`/dashboard/actions/${encodeURIComponent(actionId)}/run`), { method: 'POST' }); await openJob(state.activeApp.id, state.activeJob.id); }
  function automationPayload(form, enabled) {
    const fields = Object.fromEntries(form.entries());
    const kind = fields.trigger || 'manual';
    const detail = String(fields.detail || '').trim();
    let trigger = { type: kind };
    if (kind === 'interval') trigger.every_seconds = Math.max(60, (parseInt(detail || '15', 10) || 15) * 60);
    if (kind === 'daily') trigger = { type: kind, at: detail || '08:30', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' };
    if (kind === 'weekly') trigger = { type: kind, at: detail || '08:30', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', dow: [0, 1, 2, 3, 4] };
    if (kind === 'event') trigger.event_name = (detail || 'work_event').toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
    return {
      name: fields.name,
      enabled,
      trigger,
      mission_template: { goal: state.activeJob.goal, requires_approval: fields.requires_approval === 'on' },
    };
  }
  async function createAutomation(form) { await request(jobUrl('/automations'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(automationPayload(form, true)) }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function updateAutomation(id, form) { const current = state.automations.find(row => row.id === id); await request(jobUrl(`/automations/${encodeURIComponent(id)}`), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(automationPayload(form, current ? current.enabled : true)) }); state.editingAutomationId = ''; await openJob(state.activeApp.id, state.activeJob.id); }
  async function toggleAutomation(id) { const current = state.automations.find(row => row.id === id); if (!current) return; await request(jobUrl(`/automations/${encodeURIComponent(id)}`), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !current.enabled }) }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function deleteAutomation(id) { const current = state.automations.find(row => row.id === id); if (!current || !window.confirm(`Delete automation “${current.name}”? Its activity history will remain.`)) return; await request(jobUrl(`/automations/${encodeURIComponent(id)}`), { method: 'DELETE' }); await openJob(state.activeApp.id, state.activeJob.id); }
  async function deployAutomation(id) { await request(jobUrl(`/automations/${encodeURIComponent(id)}/deploy`), { method: 'POST' }); await openJob(state.activeApp.id, state.activeJob.id); }

  function stop() {
    if (!activeStreamController) return false;
    activeStreamController.abort();
    return true;
  }

  async function leave() {
    adapterActive = false;
    clearTimeout(reconcileTimer);
    reconcileTimer = null;
  }

  async function enter() {
    adapterActive = true;
    clearTimeout(reconcileTimer);
    reconcileTimer = null;
    render();
    await refresh();
    if (state.stage === 'job' && state.activeApp && state.activeJob) {
      scheduleJobReconcile(selectionGeneration, state.activeApp.id, state.activeJob.id);
    }
  }

  modes().registerAdapter('work', { enter, leave, refresh, renderHistory, newConversation, send, stop, isBusy: () => state.running });
})();
