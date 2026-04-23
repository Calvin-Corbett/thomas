// Extracted from part-017b.js
// From activejobspayload

    });

    const activeJobsPayload = jobsPayload || missionState?.lastJobsPayload || { jobs: [] };
    missionRenderOpsStrip(payload, activeJobsPayload);
    missionRenderJobs(activeJobsPayload);
    missionRenderHeaderAndKpis(payload);
    missionRenderPriorityList(payload, roomLabelById);
    missionRenderApprovals(payload);
    missionRenderRooms(payload, roomLabelById);
    missionRenderTimeline(payload);
}

function missionStopPolling() {
    if (!missionState || !missionState.pollTimerId) return;
    window.clearInterval(missionState.pollTimerId);
    missionState.pollTimerId = 0;
}

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