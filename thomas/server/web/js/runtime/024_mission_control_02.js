function missionStartPolling() {
    const state = missionEnsureState();
    if (!state) return;
    missionStopPolling();
    if (!state.active || !state.autoRefresh) return;
    state.pollTimerId = window.setInterval(() => {
        if (!state.active || !state.autoRefresh) return;
        void missionRefresh({ force: true, silent: true });
    }, MISSION_POLL_INTERVAL_MS);
}

async function missionRunJobNowDirect(jobId) {
    const url = missionJobActionUrl(jobId, 'run_now');
    if (!url) return false;
    try {
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) {
            const details = await res.text();
            console.warn('Mission auto-run queued job failed', details || `HTTP ${res.status}`);
            return false;
        }
        return true;
    } catch (error) {
        console.warn('Mission auto-run queued job request failed', error);
        return false;
    }
}

async function missionAutoStartQueuedJobsFromPayload(jobsPayload) {
    const state = missionEnsureState();
    if (!state || !state.autoStartQueuedJobsPending) return;
    if (!state.active || state.actionInFlight) return;

    const jobs = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
    if (!jobs.length) {
        state.autoStartQueuedJobsPending = false;
        return;
    }

    const now = Date.now();
    const nowDueJobs = jobs
        .filter((job) => {
            const status = missionStatusValue(job?.status);
            if (status !== 'queued' && status !== 'pending') return false;

            const nextRunAt = missionToEpoch(job?.next_run_at);
            if (!nextRunAt) return true;
            return nextRunAt <= now + 30000;
        })
        .sort((a, b) => missionToEpoch(a?.next_run_at) - missionToEpoch(b?.next_run_at));

    state.autoStartQueuedJobsPending = false;
    if (!nowDueJobs.length) return;

    let started = 0;
    for (const job of nowDueJobs) {
        if (state.actionInFlight) break;
        const jobId = safeString(job?.id);
        if (!jobId) continue;
        const ok = await missionRunJobNowDirect(jobId);
        if (ok) started += 1;
    }

    if (started > 0) {
        notifyUser(`Auto-started ${started} queued task${started === 1 ? '' : 's'}.`, {
            tone: 'success',
            debugKind: 'success',
            durationMs: 1800,
        });
    }
}

async function missionRefresh({ force = false, silent = false } = {}) {
    const state = missionEnsureState();
    if (!state) return;
    if (!state.active && !force) return;
    if (state.loading) return;

    state.loading = true;
    if (!silent) {
        missionSetConnectionState('neutral', 'Refreshing');
    }

    try {
        const [res, jobsRes] = await Promise.all([
            fetch('/api/mission/control'),
            fetch(`/api/mission/jobs?limit=${MISSION_JOBS_LIMIT}`),
        ]);
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }
        const payload = await res.json();
        let jobsPayload = state.lastJobsPayload;
        if (jobsRes.ok) {
            jobsPayload = await jobsRes.json();
        } else if (jobsRes.status === 404) {
            jobsPayload = { ok: false, unavailable: true, jobs: [] };
        } else {
            const details = await jobsRes.text();
            console.warn('Mission jobs refresh failed', details || `HTTP ${jobsRes.status}`);
        }
        state.lastPayload = payload;
        state.lastJobsPayload = jobsPayload;
        state.lastFetchedAt = Date.now();
        missionRender(payload, jobsPayload);
        missionSetConnectionState('ok', 'Live');
        await missionAutoStartQueuedJobsFromPayload(jobsPayload);
    } catch (error) {
        console.error('Mission refresh failed', error);
        missionSetConnectionState('danger', 'Offline');
        if (!silent) {
            notifyUser('Mission Control refresh failed.', {
                tone: 'warning',
                debugKind: 'warning',
                durationMs: 2600,
            });
        }
    } finally {
        state.loading = false;
    }
}

function missionSetCreateMeta(text) {
    if (!missionCreateMeta) return;
    missionCreateMeta.textContent = safeString(text) || 'workflow task';
}

function missionUpdateScheduleFields() {
    const mode = safeString(missionJobModeSelect?.value).toLowerCase() || 'now';
    if (missionJobOnceAtRow) missionJobOnceAtRow.classList.toggle('hidden', mode !== 'once');
    if (missionJobEverySecondsRow) missionJobEverySecondsRow.classList.toggle('hidden', mode !== 'interval');
    const timeBased = mode === 'daily' || mode === 'weekly';
    if (missionJobAtRow) missionJobAtRow.classList.toggle('hidden', !timeBased);
    if (missionJobTimezoneRow) missionJobTimezoneRow.classList.toggle('hidden', !timeBased);
    if (missionJobWeekdayRow) missionJobWeekdayRow.classList.toggle('hidden', mode !== 'weekly');

    if (mode === 'now') missionSetCreateMeta('run immediately');
    if (mode === 'once') missionSetCreateMeta('one-time schedule');
    if (mode === 'interval') missionSetCreateMeta('recurring interval');
    if (mode === 'daily') missionSetCreateMeta('daily cron');
    if (mode === 'weekly') missionSetCreateMeta('weekly cron');

    if (mode === 'once' && missionJobOnceAtInput && !safeString(missionJobOnceAtInput.value)) {
        const dt = new Date(Date.now() + (15 * 60 * 1000));
        dt.setSeconds(0, 0);
        const yyyy = String(dt.getFullYear());
        const mm = String(dt.getMonth() + 1).padStart(2, '0');
        const dd = String(dt.getDate()).padStart(2, '0');
        const hh = String(dt.getHours()).padStart(2, '0');
        const min = String(dt.getMinutes()).padStart(2, '0');
        missionJobOnceAtInput.value = `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    }
}

function missionApplyTemplate(button) {
    if (!(button instanceof HTMLButtonElement)) return;
    const ds = button.dataset || {};
    const name = safeString(ds.name);
    const goal = safeString(ds.goal);
    const mode = safeString(ds.mode).toLowerCase();
    const workflow = safeString(ds.workflow);
    const at = safeString(ds.at);
    const everySeconds = safeString(ds.everySeconds);

    if (name && missionJobNameInput) missionJobNameInput.value = name;
    if (goal && missionJobPromptInput) missionJobPromptInput.value = goal;
    if (workflow && missionJobWorkflowInput) missionJobWorkflowInput.value = workflow;
    if (mode && missionJobModeSelect) missionJobModeSelect.value = mode;
    if (at && missionJobAtInput) missionJobAtInput.value = at;
    if (everySeconds && missionJobEverySecondsInput) missionJobEverySecondsInput.value = everySeconds;

    missionUpdateScheduleFields();
    if (mode === 'once' && missionJobOnceAtInput && !safeString(missionJobOnceAtInput.value)) {
        const dt = new Date(Date.now() + (20 * 60 * 1000));
        dt.setSeconds(0, 0);
        const yyyy = String(dt.getFullYear());
        const mm = String(dt.getMonth() + 1).padStart(2, '0');
        const dd = String(dt.getDate()).padStart(2, '0');
        const hh = String(dt.getHours()).padStart(2, '0');
        const min = String(dt.getMinutes()).padStart(2, '0');
        missionJobOnceAtInput.value = `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    }
    missionSetCreateMeta(`template: ${safeString(button.textContent).trim()}`);
}

function missionCollectWeekdays() {
    if (!missionJobWeekdays) return [];
    const out = [];
    missionJobWeekdays.querySelectorAll('input[type="checkbox"]').forEach((el) => {
        if (!(el instanceof HTMLInputElement)) return;
        if (!el.checked) return;
        const val = Number(el.value);
        if (!Number.isInteger(val) || val < 0 || val > 6) return;
        out.push(val);
    });
    return out;
}

function missionDatetimeLocalToIso(valueRaw) {
    const raw = safeString(valueRaw);
    if (!raw) return '';
    const dt = new Date(raw);
    const epoch = dt.getTime();
    if (!Number.isFinite(epoch)) return '';
    return dt.toISOString();
}

function missionBuildCreateJobPayload() {
    const mode = safeString(missionJobModeSelect?.value).toLowerCase() || 'now';
    const name = safeString(missionJobNameInput?.value) || 'Mission Task';
    const goal = safeString(missionJobPromptInput?.value);
    if (!goal) {
        throw new Error('Task / Goal is required.');
    }

    const workflow = safeString(missionJobWorkflowInput?.value) || 'chain';
    const profile = safeString(missionJobProfileInput?.value);
    const modelId = safeString(missionJobModelInput?.value);
    const requiresApproval = Boolean(missionJobApprovalToggle?.checked);

    const payload = {
        name,
        kind: 'workflow_task',
        goal,
        prompt: goal,
        workflow,
        requires_approval: requiresApproval,
    };
    if (profile) payload.profile = profile;
    if (modelId) payload.model_id = modelId;

    if (mode === 'once') {
        const runAtIso = missionDatetimeLocalToIso(missionJobOnceAtInput?.value);
        if (!runAtIso) {
            throw new Error('Run at date/time is required for one-time jobs.');
        }
        payload.run_at = runAtIso;
        return payload;
    }

    if (mode === 'interval') {
        const everySeconds = Number(missionJobEverySecondsInput?.value || 0);
        if (!Number.isFinite(everySeconds) || everySeconds <= 0) {
            throw new Error('Every seconds must be a positive number.');
        }
        payload.schedule = {
            type: 'interval',
            every_seconds: Math.round(everySeconds),
        };
        return payload;
    }

    if (mode === 'daily') {
        const at = safeString(missionJobAtInput?.value);
        if (!/^\d{2}:\d{2}$/.test(at)) {
            throw new Error('Daily time must be HH:MM.');
        }
        const tz = safeString(missionJobTimezoneInput?.value) || 'UTC';
        payload.schedule = {
            type: 'daily',
            at,
            tz,
        };
        return payload;
    }

    if (mode === 'weekly') {
        const at = safeString(missionJobAtInput?.value);
        if (!/^\d{2}:\d{2}$/.test(at)) {
            throw new Error('Weekly time must be HH:MM.');
        }
        const dow = missionCollectWeekdays();
        if (!dow.length) {
            throw new Error('Select at least one weekday for weekly cron.');
        }
        const tz = safeString(missionJobTimezoneInput?.value) || 'UTC';
        payload.schedule = {
            type: 'weekly',
            at,
            tz,
            dow,
        };
        return payload;
    }

    return payload;
}

async function missionCreateJobFromForm(event) {
    if (event) event.preventDefault();
    const state = missionEnsureState();
    if (!state || state.actionInFlight) return;
    const unavailableReason = missionCreateUnavailableReason(state.lastPayload, state.lastJobsPayload);
    if (unavailableReason) {
        missionSetCreateMeta(`creation unavailable: ${unavailableReason}`);
        notifyUser(`Mission runtime unavailable: ${unavailableReason}.`, {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2600,
        });
        return;
    }

    let payload;
    try {
        payload = missionBuildCreateJobPayload();
    } catch (error) {
        notifyUser(String(error?.message || 'Invalid mission job input.'), {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2600,
        });
        return;
    }

    state.actionInFlight = true;
    if (missionJobSubmitBtn) missionJobSubmitBtn.disabled = true;
    missionSetCreateMeta('submitting...');
    try {
        const res = await fetch('/api/mission/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }
        const created = await res.json();
        const jobName = safeString(created?.job?.name) || safeString(payload?.name) || 'Mission job';
        notifyUser(`${jobName} created.`, {
            tone: 'success',
            debugKind: 'success',
            durationMs: 1900,
        });
        missionSetCreateMeta(`created ${jobName}`);
        await missionRefresh({ force: true, silent: true });
    } catch (error) {
        console.error('Mission create job failed', error);
        missionSetCreateMeta('create failed');
        notifyUser('Failed to create mission job.', {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2600,
        });
    } finally {
        state.actionInFlight = false;
        if (missionJobSubmitBtn) missionJobSubmitBtn.disabled = false;
    }
}

function missionEnterMode() {
    const state = missionEnsureState();
    if (!state) return;
    state.active = true;
    state.autoStartQueuedJobsPending = true;
    state.autoRefresh = true;
    missionStartPolling();
    void missionStartStream();

    const isStale = (Date.now() - Number(state.lastFetchedAt || 0)) > MISSION_POLL_INTERVAL_MS;
    if (!state.lastPayload || isStale) {
        void missionRefresh({ force: true });
    } else {
        missionRender(state.lastPayload, state.lastJobsPayload);
        missionSetConnectionState('ok', 'Live');
        void missionAutoStartQueuedJobsFromPayload(state.lastJobsPayload);
    }
}

function missionLeaveMode() {
    if (!missionState) return;
    missionState.active = false;
    missionStopPolling();
    missionStopStream();
}

function initMissionWorkspace() {
    const state = missionEnsureState();
    if (!state) return;
    if (!state.controlsBound) {
        state.controlsBound = true;
        if (missionJobsList) {
            missionJobsList.addEventListener('click', (event) => {
                if (!(event.target instanceof Element)) return;
                const button = event.target.closest('button[data-job-action][data-job-id]');
                if (!(button instanceof HTMLButtonElement)) return;
                const action = safeString(button.dataset.jobAction);
                const jobId = safeString(button.dataset.jobId);
                if (!action || !jobId) return;
                void missionRunJobAction(jobId, action);
            });
        }
        if (missionApprovalsList) {
            missionApprovalsList.addEventListener('click', (event) => {
                if (!(event.target instanceof Element)) return;
                const button = event.target.closest('button[data-approval-action]');
                if (!(button instanceof HTMLButtonElement)) return;
                const source = safeString(button.dataset.approvalSource);
                const action = safeString(button.dataset.approvalAction);
                if (!source || !action) return;
                const payload = {
                    source,
                    action,
                    approvalId: safeString(button.dataset.approvalId),
                    runId: safeString(button.dataset.runId),
                    toolCallId: safeString(button.dataset.toolCallId),
                    toolName: safeString(button.dataset.toolName),
                    sessionId: safeString(button.dataset.sessionId),
                };
                void missionResolveApproval(payload);
            });
        }
        if (missionJobModeSelect) {
            missionJobModeSelect.addEventListener('change', () => {
                missionUpdateScheduleFields();
            });
        }
        if (missionJobForm) {
            missionJobForm.addEventListener('submit', (event) => {
                void missionCreateJobFromForm(event);
            });
        }
        if (missionJobTemplates) {
            missionJobTemplates.addEventListener('click', (event) => {
                if (!(event.target instanceof Element)) return;
                const button = event.target.closest('.mission-template-btn');
                if (!(button instanceof HTMLButtonElement)) return;
                missionApplyTemplate(button);
            });
        }
    }

    if (missionJobTimezoneInput && !safeString(missionJobTimezoneInput.value)) {
        try {
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
            if (tz) missionJobTimezoneInput.value = tz;
        } catch (_error) {
            missionJobTimezoneInput.value = 'UTC';
        }
    }
    missionUpdateScheduleFields();
    missionSetConnectionState('ok', 'Live');
    if (missionJobsTaskCount) missionJobsTaskCount.textContent = '0';
    if (missionJobsCronCount) missionJobsCronCount.textContent = '0';
    if (missionJobsMeta && !state.lastJobsPayload) missionJobsMeta.textContent = 'No jobs loaded';
    if (!state.lastPayload) {
        missionRenderEmpty(missionJobsList, 'No jobs yet. Create a task or cron job from the form.');
        missionRenderEmpty(missionPriorityList, 'No mission jobs yet. Activity appears idle.');
        missionRenderEmpty(missionApprovalsList, 'No approvals are waiting.');
        missionRenderEmpty(missionRoomsList, 'No active room load right now.');
        missionRenderEmpty(missionTimelineList, 'No recent signals in the last 36 hours.');
    }
}

// 
//   CONTENT HUB                                                            
//   Social platforms, workflows, scheduling, content track list            
// 

function contentEnsureState() {
    if (!contentWorkspace) return null;
    if (!contentState) {
        contentState = {
            controlsBound: false,
            loading: false,
            lastFetchedAt: 0,
            error: '',
            payload: null,
        };
    }
    return contentState;
}

function contentToCount(value, fallback = 0) {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.max(0, Math.round(num));
}

function contentEmptyPayload() {
    return {
        generatedAt: '',
        summary: {
            connected_platforms: 0,
            known_platforms: 0,
            total_jobs: 0,
            active_jobs: 0,
            queued_posts: 0,
            workflows: 0,
            scheduled_posts: 0,
            approvals_pending: 0,
            sessions_active: 0,
            sessions_recent_total: 0,
            cron_jobs: 0,
            skills_installed: 0,
            api_keys_configured: 0,
            logs_last_24h: 0,
        },
        platforms: [],
        workflows: [],
        scheduler: [],
        tools: [],
        control_surface: {
            chat_first: { enabled: true, detail: '' },
            cards: [],
            health_status: 'attention',
            health_checks: [],
        },
        navigation: [],
        organization_axes: [],
        checklist: [],
    };
}

function contentNormalizePayload(payloadRaw) {
    const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {};
    const summaryRaw = payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
    const controlRaw = payload.control_surface && typeof payload.control_surface === 'object'
        ? payload.control_surface
        : {};
    return {
        generatedAt: safeString(payload.generated_at),
        summary: {
            connected_platforms: contentToCount(summaryRaw.connected_platforms),
            known_platforms: contentToCount(summaryRaw.known_platforms),
            total_jobs: contentToCount(summaryRaw.total_jobs),
            active_jobs: contentToCount(summaryRaw.active_jobs),
            queued_posts: contentToCount(summaryRaw.queued_posts),
            workflows: contentToCount(summaryRaw.workflows),
            scheduled_posts: contentToCount(summaryRaw.scheduled_posts),
            approvals_pending: contentToCount(summaryRaw.approvals_pending),
            sessions_active: contentToCount(summaryRaw.sessions_active),
            sessions_recent_total: contentToCount(summaryRaw.sessions_recent_total),
            cron_jobs: contentToCount(summaryRaw.cron_jobs),
            skills_installed: contentToCount(summaryRaw.skills_installed),
            api_keys_configured: contentToCount(summaryRaw.api_keys_configured),
            logs_last_24h: contentToCount(summaryRaw.logs_last_24h),
        },
        platforms: Array.isArray(payload.platforms) ? payload.platforms : [],
        workflows: Array.isArray(payload.workflows) ? payload.workflows : [],
        scheduler: Array.isArray(payload.scheduler) ? payload.scheduler : [],
        tools: Array.isArray(payload.tools) ? payload.tools : [],
        control_surface: {
            chat_first: controlRaw.chat_first && typeof controlRaw.chat_first === 'object'
                ? controlRaw.chat_first
                : { enabled: true, detail: '' },
            cards: Array.isArray(controlRaw.cards) ? controlRaw.cards : [],
            health_status: safeString(controlRaw.health_status) || 'attention',
            health_checks: Array.isArray(controlRaw.health_checks) ? controlRaw.health_checks : [],
        },
        navigation: Array.isArray(payload.navigation) ? payload.navigation : [],
        organization_axes: Array.isArray(payload.organization_axes) ? payload.organization_axes : [],
        checklist: Array.isArray(payload.checklist) ? payload.checklist : [],
    };
}

function contentFormatNumber(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return '0';
    return num.toLocaleString();
}

function contentParseDate(valueRaw) {
    const raw = safeString(valueRaw);
    if (!raw) return null;
    const dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return null;
    return dt;
}

function contentFormatScheduleDay(valueRaw) {
    const dt = contentParseDate(valueRaw);
    if (!dt) return '--';
    return dt.toLocaleDateString(undefined, { weekday: 'long' });
}

function contentFormatScheduleTime(valueRaw) {
    const dt = contentParseDate(valueRaw);
    if (!dt) return '--';
    return dt.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function contentPlatformConnected(platform) {
    if (typeof platform?.connected === 'boolean') return platform.connected;
    return Number(platform?.total_jobs || 0) > 0;
}

function contentStatusClass(statusRaw) {
    const slug = safeString(statusRaw)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug ? ` status-${slug}` : '';
}

function contentRenderPlatforms(platforms = []) {
    if (!contentPlatformGrid) return;
    contentPlatformGrid.innerHTML = '';
    if (!platforms.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No platforms connected yet.';
        contentPlatformGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    platforms.forEach((platform) => {
        const connected = contentPlatformConnected(platform);
        const row = document.createElement('article');
        row.className = 'content-platform-card';
        row.innerHTML = `
            <div class="content-platform-head">
                <h4>${escapeHtml(platform?.name || 'Platform')}</h4>
                <span class="content-pill ${connected ? 'connected' : 'offline'}">${connected ? 'Connected' : 'Not Connected'}</span>
            </div>
            <div class="content-platform-metrics">
                <span>Total Jobs <strong>${contentFormatNumber(platform?.total_jobs)}</strong></span>
                <span>Queued <strong>${contentFormatNumber(platform?.queued)}</strong></span>
                <span>Running <strong>${contentFormatNumber(platform?.running)}</strong></span>
                <span>Needs Approval <strong>${contentFormatNumber(platform?.awaiting_approval)}</strong></span>
                <span>Published <strong>${contentFormatNumber(platform?.published)}</strong></span>
                <span>Failed <strong>${contentFormatNumber(platform?.failed)}</strong></span>
            </div>
        `;
        frag.appendChild(row);
    });
    contentPlatformGrid.appendChild(frag);
}

function contentRenderWorkflows(workflows = []) {
    if (!contentWorkflowGrid) return;
    contentWorkflowGrid.innerHTML = '';
    if (!workflows.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No workflows configured yet.';
        contentWorkflowGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    workflows.forEach((workflow) => {
        const activeJobs = contentToCount(workflow?.active_jobs);
        const totalJobs = contentToCount(workflow?.total_jobs);
        const row = document.createElement('article');
        row.className = 'content-workflow-card';
        row.innerHTML = `
            <h4>${escapeHtml(workflow?.name || 'Workflow')}</h4>
            <p><span>Trigger:</span> ${escapeHtml(safeString(workflow?.trigger))}</p>
            <p><span>Automation:</span> ${escapeHtml(safeString(workflow?.automation))}</p>
            <p><span>Approval:</span> ${escapeHtml(safeString(workflow?.approval))}</p>
            <p><span>Load:</span> ${contentFormatNumber(activeJobs)} active / ${contentFormatNumber(totalJobs)} total</p>
        `;
        frag.appendChild(row);
    });
    contentWorkflowGrid.appendChild(frag);
}

function contentRenderScheduler(schedule = []) {
    if (!contentSchedulerRows) return;
    contentSchedulerRows.innerHTML = '';
    if (!schedule.length) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="5">No scheduled content yet.</td>';
        contentSchedulerRows.appendChild(row);
        return;
    }

    const frag = document.createDocumentFragment();
    schedule.forEach((item) => {
        const runAt = safeString(item?.run_at);
        const day = safeString(item?.day) || contentFormatScheduleDay(runAt);
        const time = safeString(item?.time) || contentFormatScheduleTime(runAt);
        const platform = safeString(item?.platform || item?.channel) || 'All Channels';
        const type = safeString(item?.type || item?.workflow) || 'Scheduled content';
        const status = safeString(item?.status) || 'Queued';
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(day)}</td>
            <td>${escapeHtml(time)}</td>
            <td>${escapeHtml(platform)}</td>
            <td>${escapeHtml(type)}</td>
            <td><span class="content-status-pill${contentStatusClass(status)}">${escapeHtml(status)}</span></td>
        `;
        frag.appendChild(row);
    });
    contentSchedulerRows.appendChild(frag);
}

function contentRenderTools(tools = []) {
    if (!contentToolsGrid) return;
    contentToolsGrid.innerHTML = '';
    if (!tools.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'No manager tools configured yet.';
        contentToolsGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    tools.forEach((tool) => {
        const status = safeString(tool?.status);
        const row = document.createElement('article');
        row.className = 'content-tool-card';
        row.innerHTML = `
            <h4>${escapeHtml(tool?.title || 'Capability')}</h4>
            ${status ? `<p class="content-tool-status">Status: ${escapeHtml(status)}</p>` : ''}
            <p>${escapeHtml(safeString(tool?.detail))}</p>
        `;
        frag.appendChild(row);
    });
    contentToolsGrid.appendChild(frag);
}

function contentToneClass(statusRaw, prefix = 'tone-') {
    const slug = safeString(statusRaw)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return slug ? `${prefix}${slug}` : `${prefix}neutral`;
}

function contentRenderControl(control = null) {
    if (!contentControlGrid) return;
    contentControlGrid.innerHTML = '';
    const cards = Array.isArray(control?.cards) ? control.cards : [];
    if (!cards.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'Control surface data will appear after the first sync.';
        contentControlGrid.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    cards.forEach((card) => {
        const row = document.createElement('article');
        row.className = `content-control-card ${contentToneClass(card?.status, 'tone-')}`.trim();
        row.innerHTML = `
            <span class="content-control-label">${escapeHtml(safeString(card?.label) || 'Control')}</span>
            <strong class="content-control-value">${escapeHtml(safeString(card?.value) || '--')}</strong>
            <span class="content-control-status">${escapeHtml(safeString(card?.status) || 'idle')}</span>
            <p>${escapeHtml(safeString(card?.detail))}</p>
        `;
        frag.appendChild(row);
    });

    const checks = Array.isArray(control?.health_checks) ? control.health_checks : [];
    if (checks.length) {
        const checksCard = document.createElement('article');
        checksCard.className = 'content-control-card content-control-health';
        const lines = checks
            .slice(0, 8)
            .map((check) => {
                const name = escapeHtml(safeString(check?.name) || 'check');
                const status = escapeHtml(safeString(check?.status) || 'unknown');
                const detail = escapeHtml(safeString(check?.detail));
                return `<li><span>${name}</span><strong>${status}</strong><em>${detail}</em></li>`;
            })
            .join('');
        checksCard.innerHTML = `
            <span class="content-control-label">Health Checks</span>
            <ul class="content-health-list">${lines}</ul>
        `;
        frag.appendChild(checksCard);
    }
    contentControlGrid.appendChild(frag);
}

function contentRenderTrackList(container, rows = [], emptyText = 'No entries yet.') {
    if (!container) return;
    container.innerHTML = '';
    if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = emptyText;
        container.appendChild(empty);
        return;
    }
    const frag = document.createDocumentFragment();
    rows.forEach((row) => {
        const item = document.createElement('article');
        item.className = 'content-track-card';
        item.innerHTML = `
            <h4>${escapeHtml(safeString(row?.label) || 'Item')}</h4>
            <p>${escapeHtml(safeString(row?.description))}</p>
        `;
        frag.appendChild(item);
    });
    container.appendChild(frag);
}

function contentRenderChecklist(groups = []) {
    if (!contentChecklistGrid) return;
    contentChecklistGrid.innerHTML = '';
    if (!groups.length) {
        const empty = document.createElement('div');
        empty.className = 'content-item-empty';
        empty.textContent = 'Checklist categories are loading.';
        contentChecklistGrid.appendChild(empty);
        return;
    }
    const frag = document.createDocumentFragment();
    groups.forEach((group) => {
        const status = safeString(group?.status) || 'planned';
        const items = Array.isArray(group?.items) ? group.items : [];
        const itemLines = items
            .slice(0, 8)
            .map((line) => `<li>${escapeHtml(safeString(line))}</li>`)
            .join('');
        const card = document.createElement('article');
        card.className = 'content-checklist-card';
        card.innerHTML = `
            <div class="content-checklist-head">
                <h4>${escapeHtml(safeString(group?.title) || 'Checklist Group')}</h4>
                <span class="content-plan-pill ${contentToneClass(status, 'status-')}">${escapeHtml(status)}</span>
            </div>
            <p>${escapeHtml(safeString(group?.summary))}</p>
            <ul>${itemLines}</ul>
        `;
        frag.appendChild(card);
    });
    contentChecklistGrid.appendChild(frag);
}

async function contentRefresh({ silent = false } = {}) {
    const state = contentEnsureState();
    if (!state || state.loading) return false;
    state.loading = true;
    if (!silent && contentPlatformMeta) {
        contentPlatformMeta.textContent = 'Loading live mission data...';
    }
    contentRender();
    try {
        const res = await fetchJsonSafe('/api/mission/content-hub');
        if (!res.ok || !res.data || typeof res.data !== 'object') {
            const reason = safeString(res?.data?.error) || safeString(res?.text) || `HTTP ${res.status}`;
            throw new Error(reason || 'request failed');
        }
        state.payload = contentNormalizePayload(res.data);
        state.error = '';
        state.lastFetchedAt = Date.now();
        return true;
    } catch (error) {
        state.error = safeString(error?.message) || 'Unable to load live content data.';
        if (!state.payload) state.payload = contentEmptyPayload();
        return false;
    } finally {
        state.loading = false;
        contentRender();
    }
}

async function spendRefresh({ force = false } = {}) {
    if (!force && spendState.lastFetchedAt && (Date.now() - spendState.lastFetchedAt < 30000)) return;
    try {
        const res = await fetchJsonSafe('/api/spend/today');
        if (res.ok && res.data && typeof res.data === 'object') {
            spendState.payload = res.data;
            spendState.lastFetchedAt = Date.now();
        }
    } catch (_) { /* silent */ }
}

async function goalsRefresh({ force = false } = {}) {
    if (!force && goalsState.lastFetchedAt && (Date.now() - goalsState.lastFetchedAt < 30000)) return;
    try {
        const res = await fetchJsonSafe('/api/goals/stats');
        if (res.ok && res.data && typeof res.data === 'object') {
            goalsState.payload = res.data;
            goalsState.lastFetchedAt = Date.now();
        }
    } catch (_) { /* silent */ }
}

function contentRender() {
    const state = contentEnsureState();
    if (!state) return;
    const payload = state.payload || contentEmptyPayload();
    const summary = payload.summary || {};
    const platforms = Array.isArray(payload.platforms) ? payload.platforms : [];
    const workflows = Array.isArray(payload.workflows) ? payload.workflows : [];
    const schedule = Array.isArray(payload.scheduler) ? payload.scheduler : [];
    const tools = Array.isArray(payload.tools) ? payload.tools : [];
    const control = payload.control_surface && typeof payload.control_surface === 'object'
        ? payload.control_surface
        : {};
    const navItems = Array.isArray(payload.navigation) ? payload.navigation : [];
    const axes = Array.isArray(payload.organization_axes) ? payload.organization_axes : [];
    const checklist = Array.isArray(payload.checklist) ? payload.checklist : [];
    const connectedFromRows = platforms.filter((platform) => contentPlatformConnected(platform)).length;
    const connected = contentToCount(summary.connected_platforms, connectedFromRows);
    const knownPlatforms = contentToCount(summary.known_platforms, platforms.length);
    const activeJobs = contentToCount(summary.active_jobs);
    const queuedPosts = contentToCount(summary.queued_posts);
    const workflowCount = contentToCount(summary.workflows, workflows.length);
    const scheduledPosts = contentToCount(summary.scheduled_posts, schedule.length);
    const approvalsPending = contentToCount(summary.approvals_pending);
    const sessionsActive = contentToCount(summary.sessions_active);
    const cronJobs = contentToCount(summary.cron_jobs);
    const skillsInstalled = contentToCount(summary.skills_installed);
    const apiKeysConfigured = contentToCount(summary.api_keys_configured);
    const logs24h = contentToCount(summary.logs_last_24h);
    const generatedLabel = payload.generatedAt ? missionRelativeTime(payload.generatedAt) : '--';

    if (contentConnectedCount) contentConnectedCount.textContent = contentFormatNumber(connected);
    if (contentConnectedMeta) contentConnectedMeta.textContent = `${connected} of ${knownPlatforms} channels active`;
    if (contentAudienceCount) contentAudienceCount.textContent = contentFormatNumber(activeJobs);
    if (contentAudienceMeta) contentAudienceMeta.textContent = 'jobs currently queued, running, or awaiting approval';
    if (contentQueuedCount) contentQueuedCount.textContent = contentFormatNumber(queuedPosts);
    if (contentQueuedMeta) contentQueuedMeta.textContent = `${scheduledPosts} scheduled publish jobs`;
    if (contentWorkflowCount) contentWorkflowCount.textContent = contentFormatNumber(workflowCount);
    if (contentWorkflowMetaSummary) {
        contentWorkflowMetaSummary.textContent = approvalsPending > 0
            ? `${approvalsPending} approvals pending`
            : `updated ${generatedLabel}`;
    }

    if (contentPlatformMeta) {
        contentPlatformMeta.textContent = state.loading
            ? 'Loading live mission data...'
            : `${connected} connected platform streams`;
    }
    if (contentWorkflowMeta) contentWorkflowMeta.textContent = `${workflowCount} workflow groups from real jobs`;
    if (contentSchedulerMeta) contentSchedulerMeta.textContent = `${schedule.length} scheduler rows`;
    if (contentToolsMeta) {
        const errorLine = state.error ? `Sync issue: ${state.error}` : '';
        contentToolsMeta.textContent = errorLine || `${tools.length} management capabilities`;
    }
    if (contentControlMeta) {
        const health = safeString(control?.health_status) || 'attention';
        const base = `Sessions ${sessionsActive} | Cron ${cronJobs} | Skills ${skillsInstalled} | Keys ${apiKeysConfigured} | Logs24h ${logs24h}`;
        contentControlMeta.textContent = state.loading
            ? 'Loading run-state telemetry...'
            : `${base} | Health ${health}`;
    }
    if (contentNavMeta) contentNavMeta.textContent = `${navItems.length} core workspace sections`;
    if (contentAxisMeta) contentAxisMeta.textContent = `${axes.length} organization lens${axes.length === 1 ? '' : 'es'} mapped`;
    if (contentChecklistMeta) {
        const partial = checklist.filter((item) => safeString(item?.status) === 'partial').length;
        const live = checklist.filter((item) => safeString(item?.status) === 'live').length;
        contentChecklistMeta.textContent = `${checklist.length} categories tracked | ${partial} partial | ${live} live`;
    }

    contentRenderPlatforms(platforms);
    contentRenderWorkflows(workflows);
    contentRenderScheduler(schedule);
    contentRenderTools(tools);
    contentRenderControl(control);
    contentRenderTrackList(contentNavList, navItems, 'Navigation map unavailable.');
    contentRenderTrackList(contentAxisList, axes, 'Organization axes unavailable.');
    contentRenderChecklist(checklist);
}

function contentEnterMode() {
    const state = contentEnsureState();
    if (!state) return;
    contentRender();
    if (!state.lastFetchedAt || (Date.now() - state.lastFetchedAt) > CONTENT_HUB_STALE_MS) {
        void contentRefresh({ silent: true });
    }
}

function contentLeaveMode() {}

// 
