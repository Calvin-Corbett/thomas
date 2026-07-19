(function () {
  'use strict';

  function create({
    state, esc, activeWorkflowFor, statusPill, safeArtifactHref,
    onboardingBrief, jsonRequest, appUrl,
  }) {
    function receiptSummary(value) {
      if (!value || typeof value !== 'object') return '';
      const selected = value.artifact || value.reference || value.output || value.summary || value.message || value.error;
      return String(selected || '').trim().slice(0, 180);
    }

    function onboardingWorkflowCandidates() {
      const candidates = new Map();
      state.messages.filter(row => row.role === 'assistant' || row.role === 'thomas').forEach(row => {
        const messageCandidates = [];
        String(row.text || row.content || '').split(/\r?\n/).forEach(line => {
          const match = line.match(/^\s*(?:(?:[-*]|\d+[.)])\s*)?Workflow:\s*([^|]{3,80})\|\s*Purpose:\s*([^|]{8,280})\|\s*Type:\s*(manual|scheduled|event)(?:\s*\|\s*Connectors:\s*(.*))?$/i);
          if (!match) return;
          const name = match[1].replace(/\*\*/g, '').trim();
          const key = name.toLowerCase();
          const connectorText = String(match[4] || '').toLowerCase();
          const connectorSuggestions = state.connectors
            .filter(connector => [connector.id, connector.name]
              .map(value => String(value || '').trim().toLowerCase())
              .filter(Boolean)
              .some(alias => connectorText.includes(alias)))
            .map(connector => connector.id);
          messageCandidates.push([key, { name, purpose: match[2].replace(/\*\*/g, '').trim(), type: match[3].toLowerCase(), connector_suggestions: connectorSuggestions }]);
        });
        if (messageCandidates.length >= 3) candidates.clear();
        messageCandidates.forEach(([key, candidate]) => candidates.set(key, candidate));
      });
      return [...candidates.values()];
    }

    function selectedOnboardingWorkflow(candidates) {
      const lastUserMessage = [...state.messages].reverse().find(row => row.role === 'user');
      const selectionText = String(lastUserMessage && lastUserMessage.text || '').toLowerCase();
      const userTurn = state.messages.filter(row => row.role === 'user').length;
      const drafts = onboardingWorkflowDrafts(candidates);
      if (/\b(?:none|neither|not\s+(?:one|any)|don['’]?t\s+want)\b/.test(selectionText)) {
        state.onboardingWorkflowId = '';
        return null;
      }
      const namedMatches = candidates.filter(workflow => selectionText.includes(String(workflow.name || '').toLowerCase()));
      if (namedMatches.length) {
        const explicitSwitch = namedMatches.length === 1 || /\b(?:switch|change|move|use|pick|choose|select)\b/.test(selectionText);
        if (explicitSwitch) {
          const selected = namedMatches.reduce((latest, workflow) => selectionText.lastIndexOf(String(workflow.name || '').toLowerCase()) > selectionText.lastIndexOf(String(latest.name || '').toLowerCase()) ? workflow : latest);
          const selectedId = drafts[candidates.indexOf(selected)].id;
          if (selectedId !== state.onboardingWorkflowId) state.onboardingSelectionUserTurn = userTurn;
          state.onboardingWorkflowId = selectedId;
          return selected;
        }
      }
      const ordinals = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'];
      const position = ordinals.findIndex((ordinal, index) => selectionText.includes(ordinal) || new RegExp(`\\b${index + 1}(?:st|nd|rd|th)?\\b`).test(selectionText));
      if (position >= 0 && position < candidates.length) {
        if (drafts[position].id !== state.onboardingWorkflowId) state.onboardingSelectionUserTurn = userTurn;
        state.onboardingWorkflowId = drafts[position].id;
        return candidates[position];
      }
      const persistedIndex = drafts.findIndex(draft => draft.id === state.onboardingWorkflowId);
      if (persistedIndex >= 0) return candidates[persistedIndex];
      state.onboardingWorkflowId = '';
      return null;
    }

    function onboardingWorkflowDrafts(candidates) {
      return candidates.map((candidate, index) => {
        const slug = candidate.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 52) || 'workflow';
        return { ...candidate, id: `flow-${index + 1}-${slug}` };
      });
    }

    function restoreOnboardingWorkflow(fields) {
      const candidates = onboardingWorkflowCandidates();
      const drafts = onboardingWorkflowDrafts(candidates);
      const savedWorkflowId = String(fields.selected_workflow_id || '');
      const savedWorkflowName = String(fields.selected_workflow || '').toLowerCase();
      const savedIndex = drafts.findIndex((draft, index) => draft.id === savedWorkflowId || String(candidates[index].name || '').toLowerCase() === savedWorkflowName);
      state.onboardingWorkflowId = savedIndex >= 0 ? drafts[savedIndex].id : '';
      state.onboardingSelectionUserTurn = Math.max(0, Number(fields.selected_workflow_user_turn || 0));
    }

    function onboardingConfigurationReady(candidates, selected = selectedOnboardingWorkflow(candidates)) {
      if (!selected || !state.onboardingSelectionUserTurn) return false;
      const userTurns = state.messages.filter(row => row.role === 'user').length;
      return userTurns > state.onboardingSelectionUserTurn;
    }

    function confirmedOnboardingGoal() {
      for (const row of [...state.messages].reverse()) {
        if (row.role !== 'assistant' && row.role !== 'thomas') continue;
        const match = String(row.text || row.content || '').match(/^Goal confirmed:\s*(.{12,500})$/im);
        if (match) return match[1].trim();
      }
      return '';
    }

    function visibleOnboardingText(value) {
      return String(value || '').replace(/^Goal confirmed:\s*.*(?:\r?\n|$)/gim, '').trim();
    }

    function onboardingInstruction(jobName, turn) {
      const candidates = onboardingWorkflowCandidates();
      if (!confirmedOnboardingGoal()) {
        return `Stay in goal discovery for the job "${jobName}". Decide whether the outcome, owner, success measure, and important boundaries are genuinely clear from answer ${turn}. If not, ask exactly one specific goal question and do not discuss tools, connectors, cadence, or execution. If the goal is now clear, add a separate line "Goal confirmed: <one concise confirmed goal>", map it into 3-6 workflows using exactly one line per flow as "Workflow: <name> | Purpose: <purpose> | Type: manual|scheduled|event | Connectors: <installed connector names or none>", and ask which single workflow to configure first.`;
      }
      if (candidates.length < 3) {
        return `The confirmed goal for "${jobName}" is established. Map it into 3-6 distinct workflows without configuring them yet. Use exactly one line per flow as "Workflow: <name> | Purpose: <purpose> | Type: manual|scheduled|event | Connectors: <installed connector names or none>", then ask which single workflow to configure first.`;
      }
      if (candidates.length > 6) {
        return `The workflow map for "${jobName}" has too many flows. Replace it with one complete map of 3-6 distinct workflows using the required Workflow line format, then ask which single workflow to configure first.`;
      }
      const selected = selectedOnboardingWorkflow(candidates);
      if (!selected) return `The workflow map is established. Ask the user to explicitly choose one named or numbered workflow. Do not silently choose for them and do not configure any workflow yet.`;
      return `Focus only on the selected workflow "${selected.name}". Ask exactly one specific question about its inputs, decision points, trigger, approval boundary, connector identity, or finished deliverable. Do not configure the other workflows yet.`;
    }

    function composerHtml(placeholder) {
      const busy = state.running;
      return `<form id="tc-work-composer" class="tc-work-composer"><textarea name="message" rows="1" aria-label="Message Thomas" placeholder="${esc(placeholder)}" ${busy ? 'disabled' : ''}></textarea><button type="submit" class="tc-work-composer-send" aria-label="${busy ? 'Working' : 'Send'}" ${busy ? 'disabled' : ''}><i class="ph ${busy ? 'ph-circle-notch' : 'ph-arrow-up'}"></i></button></form>`;
    }

    function messageRows() {
      if (!state.messages.length) {
        if (state.stage === 'onboarding') return `<div class="tc-work-welcome"><span class="tc-work-orb">T</span><div><strong>What job do you want Thomas to own?</strong><p>Describe the outcome in your own words. Thomas will ask one useful question at a time and build the job with you.</p></div></div>`;
        return `<div class="tc-work-welcome"><span class="tc-work-orb">T</span><div><strong>Continue this job with Thomas.</strong><p>The selected workflow, connector identities, learned decisions, and results stay private to this job while the conversation remains shared across its workflows.</p></div></div>`;
      }
      return state.messages.map(row => {
        const isThomas = row.role === 'assistant' || row.role === 'thomas';
        return `<article class="tc-work-message is-${isThomas ? 'thomas' : 'user'}">${isThomas ? '<span class="tc-work-message-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span>' : ''}<div class="tc-work-message-body"><div class="tc-work-message-role">${isThomas ? 'Thomas' : 'You'}</div><div>${esc(isThomas ? visibleOnboardingText(row.text || row.content || '') : row.text || row.content || '')}</div></div></article>`;
      }).join('');
    }

    function homeHtml() {
      const rows = state.apps.flatMap(app => Object.values(app.jobs || {})
        .filter(job => job.status !== 'archived' && (!state.activeApp || state.activeApp.id === app.id))
        .map(job => ({ app, job })));
      const cards = rows.map(({ app, job }) => {
        const workflow = activeWorkflowFor(job);
        const canRun = workflow && workflow.type === 'manual' && workflow.status === 'active' && workflow.automation_id;
        const action = job.status === 'paused' ? 'resume' : 'pause';
        return `<article class="tc-work-app-card"><button class="tc-work-card-open" data-work-card-open data-work-app-id="${esc(app.id)}" data-work-job-id="${esc(job.id)}"><span class="tc-work-app-icon"><i class="ph ph-briefcase"></i></span><strong>${esc(job.name)}</strong><p>${esc(job.goal)}</p><small>${esc(app.name)}${workflow ? ` · ${esc(workflow.name)}` : ' · map workflows'}</small></button><footer>${statusPill(job.status)}<div class="tc-work-card-controls"><button data-work-card-status="${action}" data-work-app-id="${esc(app.id)}" data-work-job-id="${esc(job.id)}" aria-label="${action} ${esc(job.name)}" ${state.actionBusy ? 'disabled' : ''}><i class="ph ph-${action === 'pause' ? 'pause' : 'play'}"></i></button><button data-work-card-run data-work-app-id="${esc(app.id)}" data-work-job-id="${esc(job.id)}" data-work-workflow-id="${esc(workflow ? workflow.id : '')}" ${canRun && !state.actionBusy ? '' : 'disabled'} title="${canRun ? 'Run this workflow once through Mission' : 'Finish and activate one manual workflow first'}"><i class="ph ph-lightning"></i> Run once</button></div></footer></article>`;
      }).join('');
      const title = state.activeApp ? state.activeApp.name : 'All Work';
      const subtitle = state.activeApp ? state.activeApp.goal : 'Durable jobs with their own workflows, connector identities, memory, skills, and Mission-backed runs.';
      const createAttribute = state.activeApp ? 'data-work-create-job' : 'data-work-create';
      return `<div class="tc-mode-panel tc-work-home"><div class="tc-mode-hero"><div>${state.activeApp ? '<button class="tc-work-back" data-work-all-apps><i class="ph ph-arrow-left"></i> All Work</button>' : '<div class="tc-mode-kicker">Work · jobs Thomas can keep improving</div>'}<h1 class="tc-mode-title">${esc(title)}</h1><p class="tc-mode-subtitle">${esc(subtitle)}</p></div><button class="tc-work-primary" ${createAttribute}><i class="ph ph-plus"></i> Create job</button></div><div class="tc-work-app-grid">${cards}<button class="tc-work-app-card is-create" ${createAttribute}><span class="tc-work-app-icon"><i class="ph ph-plus"></i></span><strong>Create a new job</strong><p>Define the goal first. Thomas will map the job into workflows, then help configure one flow at a time.</p></button></div></div>`;
    }

    function onboardingHtml() {
      const userTurns = state.messages.filter(row => row.role === 'user').length;
      const thomasTurns = state.messages.filter(row => row.role === 'assistant' || row.role === 'thomas').length;
      const candidates = onboardingWorkflowCandidates();
      const selected = selectedOnboardingWorkflow(candidates);
      const ready = state.activeApp && state.onboardingPhase === 'workflow_configuration' && candidates.length >= 3 && candidates.length <= 6 && selected && onboardingConfigurationReady(candidates, selected) && userTurns >= 4 && thomasTurns >= userTurns && !state.running;
      const phases = ['goal_discovery', 'workflow_mapping', 'workflow_configuration'];
      const phaseIndex = Math.max(0, phases.indexOf(state.onboardingPhase));
      return `<div class="tc-mode-panel tc-work-panel"><div class="tc-mode-hero tc-work-compact"><div><button class="tc-work-back" data-work-cancel-onboarding><i class="ph ph-arrow-left"></i> All Work</button><div class="tc-mode-kicker">Work onboarding · ${esc(state.activeApp ? state.activeApp.name : 'new job')}</div><h1 class="tc-mode-title">Define the job before the machinery.</h1><p class="tc-mode-subtitle">Thomas starts with the outcome, maps the job into separate workflows, then configures only the flow you choose.</p></div>${ready ? '<button class="tc-work-primary" data-work-finish>Create job & continue this flow</button>' : ''}</div><section class="tc-work-onboarding"><div class="tc-work-progress"><span class="${phaseIndex >= 0 ? 'is-done' : ''}">1 · Goal</span><span class="${phaseIndex >= 1 ? 'is-done' : ''}">2 · Workflow map</span><span class="${phaseIndex >= 2 ? 'is-done' : ''}">3 · Configure one</span></div><div class="tc-work-transcript" role="log" aria-live="polite" aria-relevant="additions text" aria-busy="${state.running ? 'true' : 'false'}">${messageRows()}${state.running ? '<div class="tc-work-thinking" role="status">Thomas is thinking about the next useful question…</div>' : ''}</div>${composerHtml(state.messages.length ? 'Reply to Thomas…' : 'Describe the job you want Thomas to own…')}${candidates.length ? `<div class="tc-work-onboarding-map" role="status"><strong>${selected ? `Selected: ${esc(selected.name)}` : 'Choose one workflow explicitly'}</strong><span>${candidates.map(row => esc(row.name)).join(' · ')}</span></div>` : ''}</section></div>`;
    }

    function connectorHtml() {
      const bound = new Set(state.bindings.map(row => row.account_id));
      const accounts = state.accounts.map(account => {
        const ready = account.has_credentials === true;
        const status = ready ? account.status : 'needs connection';
        const action = bound.has(account.id)
          ? '<span class="tc-work-bound">Bound</span>'
          : ready
            ? `<button data-work-bind="${esc(account.id)}">Bind read-only</button>`
            : `<form class="tc-work-inline-connect" data-work-connect="${esc(account.id)}"><input name="credential" type="password" autocomplete="off" aria-label="Connector credential for ${esc(account.label)}" required placeholder="Paste credential"><button>Connect</button></form>`;
        return `<div class="tc-work-list-row"><div><strong>${esc(account.label)}</strong><small>${esc(account.provider)} · ${esc(account.identity)} · ${esc(status)}</small></div>${action}</div>`;
      }).join('');
      const options = state.connectors.map(row => `<option value="${esc(row.id)}">${esc(row.name)}</option>`).join('');
      return `<section class="tc-work-card"><header><span><i class="ph ph-plugs-connected"></i> Connectors</span><small>${state.bindings.length} bound</small></header>${accounts || '<p class="tc-work-muted">Choose an installed Thomas connector. The identity stays visible, so several accounts from one provider remain distinct.</p>'}<form id="tc-work-account-form" class="tc-work-mini-form"><select name="provider" aria-label="Installed connector provider">${options}</select><input name="label" aria-label="Account label" required placeholder="Account label"><input name="identity" aria-label="Email or account identity" required placeholder="Email or identity"><input name="credential" type="password" autocomplete="off" aria-label="Connector credential" placeholder="Credential (optional)"><button>Add account</button></form></section>`;
    }

    function automationHtml() {
      const rows = state.automations.map(row => {
        const trigger = row.trigger || {}; const kind = trigger.type || 'manual'; const delegation = (row.delegation || {}).state || 'not_deployed';
        const deployLabel = { armed: 'Armed', deployed: 'Deployed', running: 'Running', queued: 'Queued', awaiting_approval: 'Awaiting approval' }[delegation] || 'Deploy';
        const detail = kind === 'interval' ? Math.max(1, Math.round(Number(trigger.every_seconds || 900) / 60)) : kind === 'event' ? trigger.event_name || '' : trigger.at || '';
        if (state.editingAutomationId === row.id) return `<form class="tc-work-mini-form tc-work-automation-edit" data-work-automation-edit="${esc(row.id)}"><input name="name" aria-label="Automation name" required value="${esc(row.name)}"><select name="trigger" aria-label="Automation trigger"><option value="manual" ${kind === 'manual' ? 'selected' : ''}>Manual</option><option value="interval" ${kind === 'interval' ? 'selected' : ''}>Every N minutes</option><option value="daily" ${kind === 'daily' ? 'selected' : ''}>Daily</option><option value="weekly" ${kind === 'weekly' ? 'selected' : ''}>Weekdays</option><option value="event" ${kind === 'event' ? 'selected' : ''}>On event</option></select><input name="detail" aria-label="Schedule or event detail" value="${esc(detail)}" placeholder="15, 08:30, or event name"><label class="tc-work-check"><input type="checkbox" name="requires_approval" ${(row.mission_template || {}).requires_approval ? 'checked' : ''}> Require approval</label><button>Save</button><button type="button" data-work-automation-edit-cancel>Cancel</button></form>`;
        const approval = (row.mission_template || {}).requires_approval ? ' · approval required' : ''; const lastRun = (row.delegation || {}).last_run || {}; const receipt = receiptSummary(lastRun.result) || receiptSummary(lastRun.error);
        return `<div class="tc-work-list-row"><div><strong>${esc(row.name)}</strong><small>${esc(kind)} · ${esc(delegation.replace(/_/g, ' '))}${approval}${receipt ? ` · ${esc(receipt)}` : ''}</small></div><div class="tc-work-row-actions"><button data-work-automation-edit-open="${esc(row.id)}">Edit</button><button data-work-automation-toggle="${esc(row.id)}">${row.enabled ? 'Disable' : 'Enable'}</button><button class="is-danger" data-work-automation-delete="${esc(row.id)}">Delete</button><button data-work-deploy="${esc(row.id)}" ${!row.enabled || ['deployed', 'armed', 'running', 'queued', 'awaiting_approval'].includes(delegation) ? 'disabled' : ''}>${deployLabel}</button></div></div>`;
      }).join('');
      return `<section class="tc-work-card"><header><span><i class="ph ph-clock-countdown"></i> Automations</span><small>runs through Mission</small></header>${rows || '<p class="tc-work-muted">Create a manual, scheduled, or event workflow. Deployment delegates to Thomas Mission instead of creating a second scheduler.</p>'}<form id="tc-work-automation-form" class="tc-work-mini-form"><input name="name" aria-label="Automation name" required placeholder="Automation name"><select name="trigger" aria-label="Automation trigger"><option value="manual">Manual</option><option value="interval">Every N minutes</option><option value="daily">Daily</option><option value="weekly">Weekdays</option><option value="event">On event</option></select><input name="detail" aria-label="Schedule or event detail" placeholder="15, 08:30, or event name"><label class="tc-work-check"><input type="checkbox" name="requires_approval"> Require approval before actions</label><button>Add automation</button></form></section>`;
    }

    function skillsHtml() {
      const rows = state.skills.map(row => { const promotion = (row.promotion || {}).state || 'job_private'; let action = `<button data-work-promote-request="${esc(row.id)}">Request global</button>`; if (promotion === 'requested') action = `<button data-work-promote-approve="${esc(row.id)}">Approve globally</button>`; if (promotion === 'approved') action = '<span class="tc-work-bound">Global</span>'; return `<div class="tc-work-list-row"><div><strong>${esc(row.name)}</strong><small>Private to this job · ${esc(row.status)}</small></div>${action}</div>`; }).join('');
      return `<section class="tc-work-card"><header><span><i class="ph ph-sparkle"></i> Job skills</span><small>private by default</small></header>${rows || '<p class="tc-work-muted">Thomas can remember a repeatable workflow here without loading it in unrelated chats or jobs.</p>'}<form id="tc-work-skill-form" class="tc-work-mini-form"><input name="name" aria-label="Skill name" required placeholder="Skill name"><input name="description" aria-label="Skill instructions" placeholder="What should Thomas remember?"><button>Add skill</button></form></section>`;
    }

    function widgetHtml(w) {
      const toneVar = t => ({ good: 'var(--c-accent)', warn: '#e6b455', bad: '#ff7a7a', neutral: 'var(--c-muted)' }[t] || 'var(--c-accent)');
      if (w.kind === 'bar_chart') {
        const bars = Array.isArray(w.bars) ? w.bars : [];
        const max = Math.max(1, ...bars.map(b => Number(b.value) || 0));
        const cols = bars.map(b => { const h = Math.round(((Number(b.value) || 0) / max) * 46); return `<div class="tc-work-widget-bar"><span class="tc-work-widget-bar-fill" style="height:${h}px"></span><small>${esc(b.label || '')}</small><em>${esc(String(b.value))}</em></div>`; }).join('');
        return `<div class="tc-work-widget"><strong>${esc(w.title || 'Chart')}</strong><div class="tc-work-widget-bars">${cols}</div></div>`;
      }
      if (w.kind === 'progress') {
        const pct = Math.max(0, Math.min(100, Number(w.pct) || 0));
        return `<div class="tc-work-widget"><strong>${esc(w.title || 'Progress')}</strong><div class="tc-work-widget-progress-row"><span>${esc(w.label || '')}</span><em>${pct}%</em></div><div class="tc-work-widget-meter"><span style="width:${pct}%;background:${toneVar(w.tone)}"></span></div></div>`;
      }
      if (w.kind === 'status_list') {
        const items = (Array.isArray(w.items) ? w.items : []).map(it => `<span class="tc-work-widget-pill" style="border-color:${toneVar(it.tone)};color:${toneVar(it.tone)}">${esc(it.label || '')}</span>`).join('');
        return `<div class="tc-work-widget"><strong>${esc(w.title || 'Status')}</strong><div class="tc-work-widget-pills">${items}</div></div>`;
      }
      return '';
    }

    function sheetHtml(sheet) {
      // Editable in place: contenteditable cells, Add row, Save. The save
      // handler serializes the table back into the dashboard's sheets array.
      const head = (sheet.columns || []).map(col => `<th>${esc(col)}</th>`).join('');
      const body = (sheet.rows || []).map(row => `<tr>${(sheet.columns || []).map((c, i) => `<td contenteditable="true" spellcheck="false">${esc(row[i] == null ? '' : row[i])}</td>`).join('')}</tr>`).join('');
      return `<div class="tc-work-sheet" data-work-sheet="${esc(sheet.id)}"><div class="tc-work-sheet-head"><strong><i class="ph ph-table"></i> ${esc(sheet.title || 'Sheet')}</strong><span><button data-work-sheet-addrow="${esc(sheet.id)}">+ Row</button><button class="tc-work-primary is-compact" data-work-sheet-save="${esc(sheet.id)}">Save</button></span></div><div class="tc-work-sheet-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div></div>`;
    }

    function dashboardHtml() {
      const dashboard = state.activeJob.dashboard || {};
      const headline = dashboard.headline ? `<p class="tc-work-dashboard-headline">${esc(dashboard.headline)}</p>` : '';
      const tabs = Array.isArray(dashboard.tabs) && dashboard.tabs.length ? dashboard.tabs : [];
      const activeTab = tabs.length ? (tabs.some(t => t.id === state.dashTab) ? state.dashTab : tabs[0].id) : '';
      const inTab = row => !tabs.length || (row.tab || tabs[0].id) === activeTab;
      const tabBar = tabs.length > 1 ? `<div class="tc-work-dash-tabs" role="tablist">${tabs.map(t => `<button role="tab" aria-selected="${t.id === activeTab}" class="tc-work-dash-tab ${t.id === activeTab ? 'is-active' : ''}" data-work-dash-tab="${esc(t.id)}">${esc(t.label)}</button>`).join('')}</div>` : '';
      const metricRows = (dashboard.metrics || []).filter(inTab).map(row => `<div class="tc-work-dashboard-section tc-work-dash-metric"><strong>${esc(row.value == null || row.value === '' ? '—' : row.value)}</strong><p>${esc(row.label || '')}${row.hint ? ` <small>· ${esc(row.hint)}</small>` : ''}</p></div>`).join('');
      const widgets = (dashboard.widgets || []).filter(inTab).map(widgetHtml).join('');
      const sheets = (dashboard.sheets || []).filter(inTab).map(sheetHtml).join('');
      const sections = (dashboard.sections || []).filter(inTab).map(row => `<div class="tc-work-dashboard-section"><strong>${esc(row.title || row.name || 'Section')}</strong><p>${esc(row.text || row.description || '')}</p></div>`).join('');
      // AI-designed action buttons: each is bound server-side to one of THIS
      // job's workflows and runs through Mission — never a free-form command.
      const actions = (dashboard.actions || []).map(row => `<button class="tc-work-dashboard-action" data-work-dashboard-run="${esc(row.id)}" title="${esc(row.description || '')}" ${state.actionBusy ? 'disabled' : ''}><i class="ph ph-lightning"></i> ${esc(row.label || 'Run')}</button>`).join('');
      const inboxes = (dashboard.inboxes || []).filter(inTab).map(row => `<div class="tc-work-dashboard-section tc-work-dashboard-inbox"><strong><i class="ph ph-tray"></i> ${esc(row.label || 'Inbox')}</strong><p>${esc(row.description || '')}${row.source ? ` <small>· ${esc(row.source)}</small>` : ''}</p></div>`).join('');
      const designLabel = (dashboard.metrics || []).length || (dashboard.actions || []).length ? 'Redesign with AI' : 'Design my dashboard';
      return `<section class="tc-work-card"><header><span><i class="ph ph-squares-four"></i> Dashboard</span><small>designed for this job</small></header>${headline}${actions ? `<div class="tc-work-dashboard-actions">${actions}</div>` : ''}${tabBar}${metricRows}${widgets}${sheets}${sections}${inboxes}<button class="tc-work-primary is-compact" data-work-dashboard-design ${state.actionBusy ? 'disabled' : ''}><i class="ph ph-sparkle"></i> ${designLabel}</button><form id="tc-work-dashboard-form" class="tc-work-mini-form"><input name="metric_label" aria-label="Metric label" placeholder="Metric label"><input name="metric_value" aria-label="Metric value" placeholder="Metric value"><input name="section_title" aria-label="Section title" placeholder="Section title"><textarea name="section_text" aria-label="Dashboard note" placeholder="Dashboard note"></textarea><button>Save dashboard item</button></form></section>`;
    }

    function activityHtml() {
      const rows = state.activity.slice().reverse().slice(0, 12).map(row => { const receipt = receiptSummary((row.details || {}).result) || receiptSummary((row.details || {}).error); return `<div class="tc-work-activity is-${esc(row.state)}"><span></span><div><strong>${esc(row.summary)}</strong><small>${esc(row.state)} · ${esc(row.created_at)}${receipt ? ` · ${esc(receipt)}` : ''}</small></div></div>`; }).join('');
      return `<section class="tc-work-card tc-work-activity-card"><header><span><i class="ph ph-activity"></i> Activity</span><small>runs and results</small></header>${rows || '<p class="tc-work-muted">Runs, schedules, failures, approvals, and outputs will appear here.</p>'}</section>`;
    }

    function workflowRailHtml() {
      const rows = state.workflows.map(workflow => {
        const selected = workflow.id === state.activeWorkflowId;
        return `<button class="tc-work-workflow-row ${selected ? 'is-selected' : ''}" data-work-workflow-select="${esc(workflow.id)}" aria-pressed="${selected ? 'true' : 'false'}" ${selected ? 'aria-current="step"' : ''}><span>${esc(workflow.name)}</span><small>${esc(workflow.type)} · ${esc(workflow.status)}</small></button>`;
      }).join('');
      const selected = state.workflows.find(workflow => workflow.id === state.activeWorkflowId);
      const activate = selected && selected.status === 'configuring'
        ? `<button class="tc-work-primary is-compact" data-work-workflow-activate="${esc(selected.id)}">Mark ready</button>`
        : '';
      const run = selected && selected.type === 'manual' && selected.status === 'active' && selected.automation_id
        ? `<button data-work-workflow-run="${esc(selected.id)}"><i class="ph ph-lightning"></i> Run once</button>`
        : '';
      const triggerOptions = selected && selected.type === 'scheduled'
        ? '<select name="trigger"><option value="daily">Daily</option><option value="weekly">Weekdays</option><option value="interval">Every N minutes</option></select><input name="detail" required placeholder="08:30 or 15">'
        : selected && selected.type === 'event'
          ? '<input type="hidden" name="trigger" value="event"><input name="detail" required placeholder="Event name">'
          : '<input type="hidden" name="trigger" value="manual">';
      const configure = selected && !selected.automation_id
        ? `<form class="tc-work-workflow-runner" data-work-workflow-automation="${esc(selected.id)}"><strong>Configure ${esc(selected.type)} trigger</strong>${triggerOptions}<label class="tc-work-check"><input type="checkbox" name="requires_approval"> Require approval</label><button>Create workflow runner</button></form>`
        : '';
      const selectedActions = selected
        ? `<div class="tc-work-workflow-focus"><small>Selected workflow</small><strong>${esc(selected.name)}</strong><p>${esc(selected.purpose)}</p><div>${activate}${run}</div>${configure}</div>`
        : '<p class="tc-work-muted">Map the job into workflows, then configure one flow at a time.</p>';
      return `<aside class="tc-work-workflows"><button class="tc-work-back tc-work-all-work" data-work-all-jobs><i class="ph ph-arrow-left"></i> All Work</button><div class="tc-work-rail-heading"><span>Workflows</span><small>${state.workflows.length}</small></div>${rows || '<p class="tc-work-muted">No workflows yet.</p>'}${selectedActions}<form id="tc-work-workflow-form" class="tc-work-workflow-form"><strong>Add workflow</strong><input name="name" aria-label="Workflow name" required placeholder="Workflow name"><textarea name="purpose" aria-label="Workflow purpose" required placeholder="What outcome does this flow own?"></textarea><select name="type" aria-label="Workflow type"><option value="manual">Manual</option><option value="scheduled">Scheduled</option><option value="event">Event</option></select><button>Add workflow</button></form></aside>`;
    }

    function jobHtml() {
      const job = state.activeJob;
      const metrics = (job.dashboard && job.dashboard.metrics || []).map(row => `<div><strong>${esc(row.value == null ? '—' : row.value)}</strong><span>${esc(row.label || row.name || 'Metric')}</span></div>`).join('');
      const artifacts = (job.dashboard && job.dashboard.artifacts || []).map(row => { const href = safeArtifactHref(row.reference); return href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(row.title)}</a>` : `<span title="Unsafe result link blocked">${esc(row.title)}</span>`; }).join('');
      const identity = state.editing ? `<form id="tc-work-job-edit" class="tc-work-job-edit"><input name="name" aria-label="Job name" value="${esc(job.name)}" required><textarea name="goal" aria-label="Job goal" required>${esc(job.goal)}</textarea><button>Save</button><button type="button" data-work-edit-cancel>Cancel</button></form>` : `<div><div class="tc-mode-kicker">${esc(state.activeApp.name)} · job workspace</div><h1 class="tc-mode-title">${esc(job.name)}</h1><p class="tc-mode-subtitle">${esc(job.goal)}</p></div>`;
      return `<div class="tc-mode-panel tc-work-panel"><div class="tc-mode-hero tc-work-compact">${identity}<div class="tc-work-job-actions">${statusPill(job.status)}<button data-work-edit>Edit</button><button data-work-status="${job.status === 'paused' ? 'resume' : 'pause'}"><i class="ph ph-${job.status === 'paused' ? 'play' : 'pause'}"></i> ${job.status === 'paused' ? 'Resume' : 'Pause'}</button><button class="is-danger" data-work-archive>Archive</button></div></div><div class="tc-work-job-layout">${workflowRailHtml()}<main class="tc-work-job-main"><div class="tc-work-metrics">${metrics || '<div><strong>Ready</strong><span>Job status</span></div><div><strong>' + state.bindings.length + '</strong><span>Connectors</span></div><div><strong>' + state.workflows.length + '</strong><span>Workflows</span></div>'}</div><section class="tc-work-conversation"><div class="tc-work-conversation-label"><span class="tc-work-message-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><div><strong>Thomas</strong><small>Working inside ${esc(job.name)}</small></div></div><div class="tc-work-transcript" role="log" aria-live="polite" aria-relevant="additions text" aria-busy="${state.running ? 'true' : 'false'}">${messageRows()}${state.running ? '<div class="tc-work-thinking" role="status">Thomas is working in this job…</div>' : ''}</div>${composerHtml('Message Thomas in this job…')}</section>${artifacts ? `<section class="tc-work-artifacts"><h3>Results</h3>${artifacts}</section>` : ''}</main><aside class="tc-work-operations">${dashboardHtml()}${connectorHtml()}${automationHtml()}${skillsHtml()}${activityHtml()}</aside></div></div>`;
    }

    async function provisionOnboardedJob(job) {
      const brief = onboardingBrief();
      if (!brief) return [];
      const base = appUrl(`/jobs/${encodeURIComponent(job.id)}`);
      const actions = [
        ['history', jsonRequest(`${base}/history`, 'PATCH', {
          message_count: state.messages.length,
          last_message_at: new Date().toISOString(),
        })],
        ['memory', jsonRequest(`${base}/memory`, 'PATCH', { summary: brief })],
        ['dashboard', jsonRequest(`${base}/dashboard`, 'PATCH', {
          sections: [{ title: 'Onboarding brief', text: brief.slice(0, 1200) }],
        })],
      ];
      const results = await Promise.allSettled(actions.map(row => row[1]));
      return results.flatMap((result, index) => result.status === 'rejected' ? [actions[index][0]] : []);
    }
    return {
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
    };
  }

  window.ThomasWorkSupport = { create };
})();
