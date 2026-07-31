function renderMissionRuntimeHero(payload, jobsPayload = null) {
    const ui = ensureMissionRuntimeHero();
    if (!ui) return;
    const preferredSessionId = missionPreferredSessionId();
    const runtime = missionBuildRuntimeState(payload, jobsPayload, {
        sessionId: preferredSessionId,
        fallbackToAll: true,
    });
    const taskState = preferredSessionId
        && runtime.sessionScoped
        && runtime.sessionId === preferredSessionId
        && taskContinuityLatestState
        && typeof taskContinuityLatestState === 'object'
        ? taskContinuityLatestState
        : null;
    const taskStatus = taskContinuityStatusLabel(taskState?.status);
    const taskGoal = safeString(taskState?.active_goal).trim();
    const taskProgress = safeString(taskState?.last_progress).trim();
    const taskError = taskState ? safeString(taskContinuityLatestError).trim() : '';
    const missingInputs = Array.isArray(taskState?.missing_inputs)
        ? taskState.missing_inputs.map((item) => safeString(item).trim()).filter(Boolean)
        : [];
    const primary = runtime.primary;
    const hasRuntime = runtime.activeCount > 0;
    const hasCurrentTask = hasRuntime || Boolean(taskGoal || taskProgress || taskError || missingInputs.length || taskStatus === 'blocked');
    const summaryText = taskProgress
        || safeString(primary?.summary)
        || safeString(runtime.primaryJob ? missionJobSummary(runtime.primaryJob) : '')
        || 'Mission Control is where delegated work shows up first.';
    if (ui.title instanceof HTMLElement) {
        ui.title.textContent = hasCurrentTask
            ? (taskGoal || safeString(primary?.name) || 'Current delegated task')
            : 'No current task';
    }
    if (ui.summary instanceof HTMLElement) {
        ui.summary.textContent = hasCurrentTask
            ? summaryText
            : 'When Thomas delegates work, the live task will appear here instead of inside chat.';
    }
    if (ui.pill instanceof HTMLElement) {
        let pillClass = missionRuntimePillClass(runtime);
        let pillText = hasRuntime ? missionHeartbeatLabel(runtime.heartbeat) : 'Idle';
        if (!hasRuntime && taskStatus === 'blocked') {
            pillClass = 'warn';
            pillText = 'Blocked';
        } else if (!hasRuntime && hasCurrentTask) {
            pillClass = 'neutral';
            pillText = 'Queued';
        }
        ui.pill.className = `mission-meta-pill ${pillClass}`;
        ui.pill.textContent = pillText;
    }
    if (ui.status instanceof HTMLElement) {
        const statusBits = [];
        if (hasRuntime) {
            statusBits.push(missionRuntimeStatusText(runtime));
        } else if (taskStatus === 'blocked') {
            statusBits.push('Waiting on input');
        } else if (hasCurrentTask) {
            statusBits.push('Queued for delegation');
        } else {
            statusBits.push('Waiting for delegated work');
        }
        if (runtime.sessionScoped && runtime.sessionId) {
            statusBits.push(`session ${safeString(runtime.sessionId).slice(0, 16)}`);
        }
        if (missingInputs.length > 0) {
            statusBits.push(`needs ${missingInputs.slice(0, 2).join(', ')}`);
        } else if (taskError) {
            statusBits.push(taskError);
        }
        ui.status.textContent = statusBits.filter(Boolean).join(' | ');
    }
    const hasProgress = hasRuntime && typeof runtime.progressPct === 'number';
    if (ui.bar instanceof HTMLElement) {
        ui.bar.classList.toggle('is-indeterminate', hasRuntime && !hasProgress);
    }
    if (ui.fill instanceof HTMLElement) {
        ui.fill.style.width = hasProgress ? `${runtime.progressPct}%` : (hasRuntime ? '34%' : (hasCurrentTask ? '18%' : '0%'));
    }
    if (ui.elapsed instanceof HTMLElement) {
        ui.elapsed.textContent = hasRuntime
            ? `Elapsed ${runtime.runtimeLabel}`
            : (hasCurrentTask ? 'Elapsed waiting' : 'Elapsed --');
    }
    if (ui.heartbeat instanceof HTMLElement) {
        ui.heartbeat.textContent = hasRuntime
            ? `Heartbeat ${missionHeartbeatLabel(runtime.heartbeat)}`
            : (hasCurrentTask ? `Task ${taskStatus === 'in_progress' ? 'queued' : taskStatus.replace('_', ' ')}` : 'Heartbeat idle');
    }
    if (ui.agents instanceof HTMLElement) {
        ui.agents.textContent = `${runtime.activeCount} delegated agent${runtime.activeCount === 1 ? '' : 's'}`;
    }
    if (ui.list instanceof HTMLElement) {
        const rows = hasRuntime ? runtime.liveAgents.slice(0, 4) : [];
        if (!rows.length) {
            ui.list.innerHTML = '<div class="mission-runtime-empty">No delegated agents are running right now.</div>';
        } else {
            ui.list.innerHTML = rows.map((item) => {
                const title = safeString(item?.name) || 'worker';
                const detail = [
                    missionStatusLabel(item?.status),
                    safeString(item?.room).replace(/_/g, ' '),
                    `updated ${missionRelativeTime(item?.updated_at)}`,
                ].filter(Boolean).join(' | ');
                return `
                    <article class="mission-runtime-task">
                        <div class="mission-runtime-task-head">
                            <strong>${escapeHtml(title)}</strong>
                            <span class="mission-pill status-${escapeHtml(missionStatusValue(item?.status))}">${escapeHtml(missionStatusLabel(item?.status))}</span>
                        </div>
                        <span class="mission-runtime-task-meta">${escapeHtml(detail)}</span>
                    </article>
                `;
            }).join('');
        }
    }
}

async function fetchTaskContinuitySessionActivity(sessionToken) {
    const sid = safeString(sessionToken || taskContinuityLatestSessionId);
    if (!sid) return taskContinuityLatestActivity;

    try {
        const delegationResp = await fetchJsonSafe(`/api/v2/chat/session/${encodeURIComponent(sid)}/delegations`);
        if (delegationResp.ok && delegationResp.data && typeof delegationResp.data === 'object') {
            const delegationPayload = delegationResp.data;
            const delegations = Array.isArray(delegationPayload.delegations) ? delegationPayload.delegations : [];
            if (delegations.length > 0) {
                const activity = buildDelegationRuntimeState(delegations, { sessionId: sid });
                taskContinuityLatestActivity = activity;
                return activity;
            }
        }
    } catch (error) {
        console.warn('Task continuity delegation fetch failed', error);
    }

    const cachedActivity = taskContinuityLatestActivity && typeof taskContinuityLatestActivity === 'object'
        ? taskContinuityLatestActivity
        : null;
    const cachedActive = Boolean(
        cachedActivity
        && (
            Number(cachedActivity.activeCount || 0) > 0
            || (Array.isArray(cachedActivity.liveAgents) && cachedActivity.liveAgents.length > 0)
        )
    );
    const now = Date.now();
    if (
        cachedActivity
        && !cachedActive
        && taskContinuityActivityFallbackLastFetchAt
        && (now - taskContinuityActivityFallbackLastFetchAt) < TASK_CONTINUITY_IDLE_ACTIVITY_REFRESH_INTERVAL_MS
    ) {
        return cachedActivity;
    }
    taskContinuityActivityFallbackLastFetchAt = now;

    const [missionResp, jobsResp] = await Promise.all([
        fetchJsonSafe('/api/mission/control'),
        fetchJsonSafe(`/api/mission/jobs?session_id=${encodeURIComponent(sid)}&limit=36`),
    ]);
    const missionPayload = missionResp.ok && missionResp.data && typeof missionResp.data === 'object'
        ? missionResp.data
        : (taskContinuityMissionPayload || { agents: [], generated_at: '' });
    const jobsPayload = jobsResp.ok && jobsResp.data && typeof jobsResp.data === 'object'
        ? jobsResp.data
        : (taskContinuityMissionJobs || { jobs: [] });
    taskContinuityMissionPayload = missionPayload;
    taskContinuityMissionJobs = jobsPayload;
    const activity = missionBuildRuntimeState(missionPayload, jobsPayload, { sessionId: sid });
    taskContinuityLatestActivity = activity;
    return activity;
}

function appendTerminalDelegationActivityResults(activity) {
    if (!activity || !Array.isArray(activity.agents)) return;
    if (typeof appendDelegationResultMessage !== 'function') return;
    const scopedSessionId = safeString(activity.sessionId || activity.requestedSessionId || taskContinuityLatestSessionId);
    activity.agents.forEach((row) => {
        if (!row || typeof row !== 'object') return;
        const state = safeString(row?.state || row?.status).toLowerCase();
        // `blocked` is NOT an ending, and this path used to treat it as one.
        //
        // One decision -- "is this run over, and did it fail" -- is spelled out in
        // two places. The live SSE path, `_delegationIsTerminalState` in
        // 013_actions_interactions_02.js, correctly excludes `blocked`. This
        // fallback gated on `chatTaskIsTerminal` (003_easy_setup_onboarding_01.js),
        // which INCLUDES it, and then called it failed on the next line. So a task
        // merely waiting on an approval gate got a permanent "Task failed" card
        // written into the transcript, while the stream and the supervisor both
        // still considered it running.
        //
        // `task_bot_runtime.ALLOWED_TRANSITIONS` lets `blocked` go back to
        // queued/claimed/executing, and it is absent from `TERMINAL_STATES`, so
        // this is settled by the state machine rather than by taste.
        if (!chatTaskIsTerminal(state) || state === 'blocked') return;
        const executionId = safeString(row?.execution_id);
        if (!executionId) return;
        // KNOWN, NOT FIXED HERE: `cancelled` is still reported as a failure.
        // task_bot_runtime says at its own line that "'cancelled' is its own
        // ending. Stopping a run on purpose is not a failure", and the Mission
        // Control board was corrected to match. This card is binary --
        // delegation_failed or delegation_completed -- so saying it truthfully
        // needs a third result type and a renderer that draws it. Calling a run
        // you stopped "failed" is wrong; calling it "completed" is also wrong.
        // Left as-is rather than trading one false label for another.
        const failed = state === 'failed' || state === 'cancelled' || state === 'dead';
        const summary = safeString(row?.last_progress || row?.summary || row?.task || row?.current_task);
        appendDelegationResultMessage({
            ...row,
            type: failed ? 'delegation_failed' : 'delegation_completed',
            session_id: safeString(row?.session_id) || scopedSessionId,
        }, {
            status: failed ? 'failed' : 'completed',
            summary,
        });
    });
}

// RECOVERED (2026-03-18): Was in dead app_parts/part-002b.js, never made it to live runtime.
function taskContinuityStatusTone(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (['complete', 'done', 'completed', 'succeeded'].includes(status)) return 'complete';
    if (['blocked', 'error', 'failed', 'abandoned', 'cancelled', 'dead'].includes(status)) return 'blocked';
    if (!status || status === 'idle') return 'idle';
    return 'working';
}

function taskContinuityStatusLabel(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (['complete', 'done', 'completed', 'succeeded'].includes(status)) return 'complete';
    if (['blocked', 'error', 'failed', 'abandoned', 'cancelled', 'dead'].includes(status)) return 'blocked';
    if (!status || status === 'idle') return 'idle';
    return 'in_progress';
}

function ensureTaskContinuityToggleUi() {
    if (!taskContinuityPanel) return null;
    const head = taskContinuityPanel.querySelector('.task-continuity-head');
    if (!(head instanceof HTMLElement)) return null;

    let actions = head.querySelector('.task-continuity-actions');
    if (!(actions instanceof HTMLElement)) {
        actions = document.createElement('div');
        actions.className = 'task-continuity-actions';
        head.appendChild(actions);
    }

    let toggleBtn = document.getElementById('taskContinuityToggleBtn');
    if (!(toggleBtn instanceof HTMLButtonElement)) {
        toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.id = 'taskContinuityToggleBtn';
        toggleBtn.className = 'btn-icon task-continuity-toggle';
        toggleBtn.innerHTML = '<i class="ph ph-caret-up"></i>';
    }

    const refreshInActions = taskContinuityRefreshBtn instanceof HTMLElement
        && taskContinuityRefreshBtn.parentNode === actions;
    if (toggleBtn.parentNode !== actions) {
        if (refreshInActions) {
            actions.insertBefore(toggleBtn, taskContinuityRefreshBtn);
        } else {
            actions.appendChild(toggleBtn);
        }
    }
    if (taskContinuityRefreshBtn && taskContinuityRefreshBtn.parentNode !== actions) {
        actions.appendChild(taskContinuityRefreshBtn);
    }

    return toggleBtn;
}

function taskContinuityHasDisplayContent({ state = null, activity = null, error = '', taskDefinition = null, taskEvaluation = null } = {}) {
    const normalizedError = safeString(error).trim();
    const normalizedStatus = taskContinuityStatusLabel(state?.status);
    const activeGoal = safeString(state?.active_goal).trim();
    const progress = safeString(state?.last_progress).trim();
    const missingInputs = Array.isArray(state?.missing_inputs) ? state.missing_inputs.filter(Boolean) : [];
    const activeWorkers = Number(activity?.activeCount || 0) > 0;
    const recentBackground = Array.isArray(activity?.agents) && activity.agents.length > 0;
    const hasTaskDefinition = Boolean(taskDefinition && typeof taskDefinition === 'object');
    const hasTaskEvaluation = Boolean(taskEvaluation && typeof taskEvaluation === 'object');

    if (normalizedError) return true;
    if (missingInputs.length > 0) return true;
    if (activeWorkers) return true;
    if (recentBackground) return true;
    if (hasTaskDefinition || hasTaskEvaluation) return true;
    if (normalizedStatus === 'blocked') return true;
    if (normalizedStatus === 'in_progress') {
        return Boolean(activeGoal || progress);
    }
    return false;
}

function taskContinuityShouldForceExpand({ error = '' } = {}) {
    return Boolean(safeString(error).trim());
}

function setTaskContinuityCollapsed(nextCollapsed, { remember = false } = {}) {
    if (!taskContinuityPanel) return;
    const collapsed = Boolean(nextCollapsed);
    if (remember) {
        taskContinuityCollapseOverride = collapsed;
    }
    taskContinuityPanel.classList.toggle('is-collapsed', collapsed);

    const toggleBtn = ensureTaskContinuityToggleUi();
    if (!(toggleBtn instanceof HTMLButtonElement)) return;

    const expanded = !collapsed;
    const label = expanded ? 'Collapse task details' : 'Expand task details';
    toggleBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    toggleBtn.setAttribute('aria-label', label);
    toggleBtn.title = label;
    const icon = toggleBtn.querySelector('i');
    if (icon) {
        icon.className = expanded ? 'ph ph-caret-up' : 'ph ph-caret-down';
    }
}

function syncTaskContinuityPanelVisibility() {
    if (!taskContinuityPanel) return;
    const visibleInNav = taskContinuityShouldBeVisible();
    const hasDisplayContent = taskContinuityHasDisplayContent({
        state: taskContinuityLatestState,
        activity: taskContinuityLatestActivity,
        error: taskContinuityLatestError,
        taskDefinition: taskContinuityLatestTaskDefinition,
        taskEvaluation: taskContinuityLatestTaskEvaluation,
    });
    const show = visibleInNav && hasDisplayContent;
    taskContinuityPanel.classList.toggle('hidden', !show);
    if (!show) {
        setChatAgentPresence(null);
    }
}

function taskContinuityShouldBeVisible() {
    if (!taskContinuityPanel) return false;
    if (isSettingsScreenOpen()) return false;
    return sidebarNavMode === 'chat' || sidebarNavMode === 'search';
}

function stopTaskContinuityAutoRefresh() {
    if (taskContinuityAutoRefreshTimer) {
        window.clearInterval(taskContinuityAutoRefreshTimer);
        taskContinuityAutoRefreshTimer = 0;
    }
}

function startTaskContinuityAutoRefresh() {
    if (taskContinuityAutoRefreshTimer) return;
    taskContinuityAutoRefreshTimer = window.setInterval(() => {
        if (!taskContinuityShouldBeVisible()) return;
        void refreshTaskContinuity();
    }, TASK_CONTINUITY_REFRESH_INTERVAL_MS);
}

function renderTaskContinuity(
    state,
    events,
    sessionToken,
    { error = '', activity = null, taskDefinition = null, taskEvaluation = null, taskDefinitionStatus = '' } = {},
) {
    if (!taskContinuityPanel) return;

    const hasState = Boolean(state && typeof state === 'object');
    const normalizedEvents = Array.isArray(events) ? events.slice(0, 6) : [];
    const runtimeActivity = activity && typeof activity === 'object' ? activity : taskContinuityLatestActivity;
    const runtimePrimary = runtimeActivity && typeof runtimeActivity === 'object' ? runtimeActivity.primary : null;
    const runtimeStatus = safeString(runtimePrimary?.state || runtimePrimary?.status);
    const status = taskContinuityStatusLabel(hasState ? state.status : (runtimeStatus || (error ? 'blocked' : 'in_progress')));
    const activeGoal = hasState ? safeString(state.active_goal) : '';
    const progress = hasState ? safeString(state.last_progress) : '';
    const backgroundSummary = safeString(runtimePrimary?.summary || runtimePrimary?.name || runtimePrimary?.bot_name);
    const backgroundProgress = safeString(runtimePrimary?.last_progress || runtimePrimary?.summary || runtimePrimary?.name || runtimePrimary?.bot_name);
    const missingInputs = hasState && Array.isArray(state.missing_inputs) ? state.missing_inputs.filter(Boolean) : [];
    const updatedAtRaw = hasState ? safeString(state.updated_at) : '';
    const sessionLabelRaw = safeString(sessionToken);
    const sessionLabel = sessionLabelRaw.length > 16 ? `${sessionLabelRaw.slice(0, 16)}` : (sessionLabelRaw || '--');

    if (hasState) {
        taskContinuityLatestState = state;
    }
    if (normalizedEvents.length) {
        taskContinuityLatestEvents = normalizedEvents;
    }
    if (sessionLabelRaw) {
        taskContinuityLatestSessionId = sessionLabelRaw;
    }
    if (runtimeActivity && typeof runtimeActivity === 'object') {
        taskContinuityLatestActivity = runtimeActivity;
    }
    taskContinuityLatestError = safeString(error);
    if (taskDefinition && typeof taskDefinition === 'object') {
        taskContinuityLatestTaskDefinition = taskDefinition;
    }
    if (taskEvaluation && typeof taskEvaluation === 'object') {
        taskContinuityLatestTaskEvaluation = taskEvaluation;
    }
    if (safeString(taskDefinitionStatus)) {
        taskContinuityLatestTaskDefinitionStatus = safeString(taskDefinitionStatus);
    }

    if (taskContinuityStatusPill) {
        taskContinuityStatusPill.textContent = status;
        taskContinuityStatusPill.classList.remove('is-complete', 'is-blocked');
        if (status === 'complete') taskContinuityStatusPill.classList.add('is-complete');
        if (status === 'blocked') taskContinuityStatusPill.classList.add('is-blocked');
    }

    if (taskContinuityGoal) {
        if (activeGoal) {
            taskContinuityGoal.textContent = activeGoal;
        } else if (backgroundSummary) {
            taskContinuityGoal.textContent = backgroundSummary;
        } else if (error) {
            taskContinuityGoal.textContent = 'Task continuity is temporarily unavailable.';
        } else {
            taskContinuityGoal.textContent = 'No active task tracked yet.';
        }
    }

    if (taskContinuityProgress) {
        if (progress) {
            taskContinuityProgress.textContent = progress;
        } else if (backgroundProgress) {
            taskContinuityProgress.textContent = backgroundProgress;
        } else if (error) {
            taskContinuityProgress.textContent = error;
        } else {
            taskContinuityProgress.textContent = 'Waiting for first update.';
        }
    }

    if (taskContinuityBlockersWrap && taskContinuityBlockersList) {
        taskContinuityBlockersWrap.classList.toggle('hidden', missingInputs.length === 0);
        taskContinuityBlockersList.innerHTML = missingInputs
            .map((item) => `<li>${escapeHtml(safeString(item))}</li>`)
            .join('');
    }

    if (taskContinuityEventsList) {
        if (normalizedEvents.length > 0) {
            taskContinuityEventsList.classList.remove('hidden');
            taskContinuityEventsList.innerHTML = normalizedEvents.map((entry) => {
                const source = safeString(entry?.source).replace(/^chat\./, '');
                const line = safeString(entry?.last_progress);
                const when = missionRelativeTime(entry?.created_at);
                const textLine = [source || 'event', line].filter(Boolean).join(' | ');
                const suffix = when && when !== '--' ? ` (${when})` : '';
                return `<li title="${escapeHtml(textLine)}">${escapeHtml(textLine)}${escapeHtml(suffix)}</li>`;
            }).join('');
        } else {
            taskContinuityEventsList.classList.add('hidden');
            taskContinuityEventsList.innerHTML = '';
        }
    }

    if (taskContinuityUpdatedAt) {
        taskContinuityUpdatedAt.textContent = updatedAtRaw ? `Updated ${missionRelativeTime(updatedAtRaw)}` : 'Not synced';
    }
    if (taskContinuitySession) {
        taskContinuitySession.textContent = `Session: ${sessionLabel}`;
    }

    renderTaskDefinitionUi(
        taskContinuityLatestTaskDefinition,
        taskContinuityLatestTaskEvaluation,
        taskContinuityLatestTaskDefinitionStatus,
    );

    const hasDisplayContent = taskContinuityHasDisplayContent({
        state,
        activity: runtimeActivity,
        error,
        taskDefinition: taskContinuityLatestTaskDefinition,
        taskEvaluation: taskContinuityLatestTaskEvaluation,
    });
    const forceExpand = taskContinuityShouldForceExpand({
        state,
        activity: runtimeActivity,
        error,
    });
    const autoCollapsed = hasDisplayContent && !forceExpand;
    if (!hasDisplayContent || forceExpand) {
        taskContinuityCollapseOverride = null;
    }
    setTaskContinuityCollapsed(forceExpand ? false : (taskContinuityCollapseOverride ?? autoCollapsed));
    renderTaskContinuitySessionActivity(runtimeActivity);
    setChatAgentPresence(runtimeActivity);
    syncTaskContinuityPanelVisibility();
    if (missionState?.active || sidebarNavMode === 'mission') {
        const missionPayload = missionState?.lastPayload && typeof missionState.lastPayload === 'object'
            ? missionState.lastPayload
            : null;
        const missionJobs = missionState?.lastJobsPayload && typeof missionState.lastJobsPayload === 'object'
            ? missionState.lastJobsPayload
            : null;
        if (missionPayload) {
            renderMissionRuntimeHero(missionPayload, missionJobs);
        }
    }
}


function chatHistoryHasMessageId(messageId) {
    const normalizedId = safeString(messageId);
    if (!normalizedId) return false;
    return chatHistory.some((msg) => safeString(msg?.id) === normalizedId);
}

function appendAssistantChatHistoryMessage(content, messageId) {
    const normalizedId = safeString(messageId);
    const normalizedContent = safeString(content).trim();
    if (!normalizedId || !normalizedContent) return false;
    if (chatHistoryHasMessageId(normalizedId) || document.getElementById(normalizedId)) return false;
    renderMessage({ role: 'assistant', content: normalizedContent, id: normalizedId });
    chatHistory.push({
        id: normalizedId,
        role: 'assistant',
        content: normalizedContent,
        createdAt: Date.now(),
        status: 'complete',
        toolCalls: [],
    });
    return true;
}

function buildEvolveJobSummaryMessage(job) {
    const jobId = safeString(job?.id);
    const status = safeString(job?.status).toLowerCase();
    const result = job?.result && typeof job.result === 'object' ? job.result : {};
    const session = result?.session && typeof result.session === 'object' ? result.session : {};
    const sessionLabel = safeString(session.session_id || result.session_id || jobId) || 'evolve session';
    const sessionStatus = safeString(session.status || status || 'completed') || 'completed';
    const changedFiles = Array.isArray(session.changed_files)
        ? session.changed_files.map((item) => safeString(item)).filter(Boolean)
        : [];
    const changedCount = changedFiles.length;
    if (status === 'succeeded') {
        const headline = `Evolve session ${sessionLabel} finished ${sessionStatus}.`;
        const changedLine = changedCount > 0
            ? `Changed ${changedCount} ${changedCount === 1 ? 'file' : 'files'} on the green side.`
            : 'No filesystem changes were recorded.';
        const fileLine = changedFiles.length > 0
            ? `Files: ${changedFiles.slice(0, 6).join(', ')}${changedFiles.length > 6 ? ', ...' : ''}`
            : '';
        const promoteLine = session.promotable
            ? 'It is ready for review in Mission Control.'
            : 'It is not promotable yet; review the run details in Mission Control.';
        return [headline, changedLine, fileLine, promoteLine].filter(Boolean).join('\n\n');
    }
    const error = job?.error && typeof job.error === 'object' ? job.error : {};
    const errorText = safeString(error.message || error.detail || error.text);
    let failureLead = `Evolve session ${sessionLabel} completed with status ${status || 'unknown'}.`;
    if (status === 'cancelled') {
        failureLead = `Evolve session ${sessionLabel} was cancelled.`;
    } else if (status === 'failed' || status === 'dead') {
        failureLead = `Evolve session ${sessionLabel} failed.`;
    }
    return [failureLead, errorText, 'Mission Control has the run details.'].filter(Boolean).join('\n\n');
}

async function refreshEvolveChatReplies({ sessionOverride = '', force = false } = {}) {
    const sid = safeString(sessionOverride || sessionId || activeChatId || taskContinuityLatestSessionId);
    if (!sid) return;
    if (evolveChatRepliesInFlight && !force) return;
    const activity = taskContinuityLatestActivity && typeof taskContinuityLatestActivity === 'object'
        ? taskContinuityLatestActivity
        : null;
    const hasActiveActivity = Boolean(
        activity
        && (
            Number(activity.activeCount || 0) > 0
            || (Array.isArray(activity.liveAgents) && activity.liveAgents.length > 0)
        )
    );
    const now = Date.now();
    if (
        !force
        && !hasActiveActivity
        && evolveChatRepliesLastRefreshAt
        && (now - evolveChatRepliesLastRefreshAt) < EVOLVE_CHAT_REPLY_IDLE_REFRESH_INTERVAL_MS
    ) {
        return;
    }
    evolveChatRepliesLastRefreshAt = now;
    evolveChatRepliesInFlight = true;
    try {
        const res = await fetchJsonSafe(`/api/mission/jobs?kind=evolve_session&session_id=${encodeURIComponent(sid)}&limit=24`);
        if (!res.ok) return;
        const payload = res.data && typeof res.data === 'object' ? res.data : {};
        const jobs = Array.isArray(payload.jobs) ? payload.jobs.slice() : [];
        jobs.sort((a, b) => safeString(a?.created_at).localeCompare(safeString(b?.created_at)));
        let appended = false;
        jobs.forEach((job) => {
            const jobId = safeString(job?.id);
            const status = safeString(job?.status).toLowerCase();
            if (!jobId || !EVOLVE_TERMINAL_JOB_STATUSES.has(status)) return;
            const messageId = `mission-evolve-result-${jobId}`;
            const content = buildEvolveJobSummaryMessage(job);
            if (appendAssistantChatHistoryMessage(content, messageId)) {
                appended = true;
            }
        });
        if (appended) {
            syncActiveChatSidebarEntry();
            void persistActiveChat({ quiet: true });
        }
    } catch (error) {
        console.warn('Evolve chat reply refresh failed', error);
    } finally {
        evolveChatRepliesInFlight = false;
    }
}

async function refreshTaskContinuity({ sessionOverride = '', force = false } = {}) {
    if (taskContinuityInFlight && !force) return;

    const sid = safeString(sessionOverride || sessionId || activeChatId || taskContinuityLatestSessionId);
    const currentUrl = sid
        ? `/api/task-ledger/current?session_id=${encodeURIComponent(sid)}`
        : '/api/task-ledger/current';
    const historyUrl = sid
        ? `/api/task-ledger/history?session_id=${encodeURIComponent(sid)}&limit=6`
        : '/api/task-ledger/history?limit=6';
    let evolveReplySessionId = sid;

    taskContinuityInFlight = true;
    if (taskContinuityRefreshBtn) taskContinuityRefreshBtn.disabled = true;
    try {
        const [currentResp, historyResp, activity] = await Promise.all([
            fetchJsonSafe(currentUrl),
            fetchJsonSafe(historyUrl),
            fetchTaskContinuitySessionActivity(sid),
        ]);
        const currentPayload = currentResp.ok && currentResp.data && typeof currentResp.data === 'object' ? currentResp.data : {};
        const historyPayload = historyResp.ok && historyResp.data && typeof historyResp.data === 'object' ? historyResp.data : {};
        const state = currentPayload.state && typeof currentPayload.state === 'object' ? currentPayload.state : null;
        const events = Array.isArray(historyPayload.events) ? historyPayload.events : [];
        const taskDefinition = currentPayload.task_definition && typeof currentPayload.task_definition === 'object'
            ? currentPayload.task_definition
            : null;
        const taskEvaluation = currentPayload.task_evaluation && typeof currentPayload.task_evaluation === 'object'
            ? currentPayload.task_evaluation
            : null;
        const taskDefinitionStatus = safeString(currentPayload.task_definition_status) || taskContinuityLatestTaskDefinitionStatus;
        const resolvedSid = safeString(currentPayload.session_id || historyPayload.session_id || sid);
        evolveReplySessionId = resolvedSid || sid;
        const hasDelegationActivity = Boolean(Array.isArray(activity?.agents) && activity.agents.length > 0);
        if (!currentResp.ok && !hasDelegationActivity) {
            throw new Error(currentResp.text || `Task continuity HTTP ${currentResp.status}`);
        }
        if (!historyResp.ok && !hasDelegationActivity) {
            throw new Error(historyResp.text || `Task history HTTP ${historyResp.status}`);
        }
        renderTaskContinuity(state, events, resolvedSid, {
            activity,
            taskDefinition,
            taskEvaluation,
            taskDefinitionStatus,
        });
        appendTerminalDelegationActivityResults(activity);
    } catch (error) {
        const fallbackState = taskContinuityLatestState;
        const fallbackEvents = taskContinuityLatestEvents;
        const fallbackSid = safeString(taskContinuityLatestSessionId || sid);
        evolveReplySessionId = fallbackSid || sid;
        renderTaskContinuity(fallbackState, fallbackEvents, fallbackSid, {
            error: safeString(error?.message) || 'Sync failed.',
            activity: taskContinuityLatestActivity,
            taskDefinition: taskContinuityLatestTaskDefinition,
            taskEvaluation: taskContinuityLatestTaskEvaluation,
            taskDefinitionStatus: taskContinuityLatestTaskDefinitionStatus,
        });
    } finally {
        taskContinuityInFlight = false;
        if (taskContinuityRefreshBtn) taskContinuityRefreshBtn.disabled = false;
        syncTaskContinuityPanelVisibility();
    }
    void refreshEvolveChatReplies({ sessionOverride: evolveReplySessionId, force });
}


function updateTaskContinuityVisibility({ refresh = false } = {}) {
    if (!taskContinuityPanel) return;
    const visible = taskContinuityShouldBeVisible();
    if (!visible) {
        taskContinuityPanel.classList.add('hidden');
        stopTaskContinuityAutoRefresh();
        setChatAgentPresence(null);
        return;
    }
    startTaskContinuityAutoRefresh();
    syncTaskContinuityPanelVisibility();
    if (refresh) {
        void refreshTaskContinuity({ force: true });
    }
}

async function emitOnboardingTelemetry(eventName, payload = {}) {
    const normalized = safeString(eventName);
    if (!normalized) return;
    const basePayload = payload && typeof payload === 'object' ? { ...payload } : {};
    const telemetryTiming = ensureOnboardingTelemetryClock();
    if (!safeString(basePayload.onboarding_session_id)) {
        basePayload.onboarding_session_id = telemetryTiming.onboarding_session_id;
    }
    if (!Number.isFinite(Number(basePayload.elapsed_ms))) {
        basePayload.elapsed_ms = telemetryTiming.elapsed_ms;
    }
    try {
        await fetch('/api/onboarding/telemetry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event: normalized,
                payload: basePayload,
            }),
        });
    } catch {
        // Best-effort telemetry only.
    }
}

function getOnboardingFromPrefs() {
    return currentPreferences?.onboarding || {};
}

function isOnboardingComplete() {
    return Boolean(getOnboardingFromPrefs()?.setup_completed);
}

function mapRecommendedPath(bootstrap) {
    const recommended = safeString(bootstrap?.quick_start?.recommended_path).toLowerCase();
    if (recommended === 'codex') return 'codex';
    if (recommended === 'local') return 'local';
    if (recommended === 'cloud') return 'manual';
    return '';
}

function easySetupStepName(step) {
    if (step <= 1) return 'choose_path';
    if (step === 2) return 'connect';
    if (step === 3) return 'downloads';
    if (step === 4) return 'preferences';
    if (step === 5) return 'brain_ready';
    return 'choose_path';
}

function stepFromOnboardingName(nameRaw) {
    const name = safeString(nameRaw).toLowerCase();
    if (name === 'connect') return 2;
    if (name === 'downloads') return 3;
    if (name === 'preferences') return 4;
    if (name === 'brain_ready') return 5;
    if (name === 'interview' || name === 'completed') return 5;
    return 1;
}

function setEasySetupStatus(targetEl, text, tone = '') {
    if (!targetEl) return;
    targetEl.textContent = safeString(text);
    targetEl.classList.remove('ok', 'error');
    if (tone === 'ok') targetEl.classList.add('ok');
    if (tone === 'error') targetEl.classList.add('error');
    if (tone === 'error') {
        notifyUser(targetEl.textContent, {
            tone: 'error',
            durationMs: 3400,
        });
    }
}

function hideAssistantSuggestions({ force = false } = {}) {
    if (!assistantSuggestionRail || !assistantSuggestionBubbles) return;
    if (!force && !suggestionDismissible) return;
    _stopSuggestionAutoScroll();
    suggestionRailVersion += 1;
    suggestionContext = '';
    suggestionDismissible = true;
    assistantSuggestionBubbles.innerHTML = '';
    assistantSuggestionBubbles.removeAttribute('data-mode');
    assistantSuggestionBubbles.removeAttribute('data-ready');
    assistantSuggestionRail.classList.add('hidden');
    assistantSuggestionRail.removeAttribute('data-context');
    if (assistantSuggestionTitle) assistantSuggestionTitle.textContent = 'Suggestions';
    if (assistantSuggestionDismissBtn) assistantSuggestionDismissBtn.classList.add('hidden');
}

// CSS marquee handles the scrolling animation via .assistant-suggestion-track
// These are kept as no-ops for any callers that reference them
function _startSuggestionAutoScroll() {}
function _stopSuggestionAutoScroll() {}

function setElementA11y(element, { title = '', label = '' } = {}) {
    if (!(element instanceof HTMLElement)) return;
    if (title) element.title = title;
    if (label) element.setAttribute('aria-label', label);
}

function syncSendButtonA11y() {
    const label = isGenerating ? 'Stop response' : 'Send message';
    setElementA11y(sendBtn, { title: label, label });
}

function configureComposerSurface() {
    setElementA11y(attachBtn, { title: 'Add or create', label: 'Add or create' });
    setElementA11y(micBtn, { title: 'Use microphone', label: 'Use microphone' });
    setElementA11y(sidebarToggleBtn, { title: 'Toggle sidebar', label: 'Toggle sidebar' });
    setElementA11y(modelSetupBtn, { title: 'Configure model', label: 'Configure model' });
    syncSendButtonA11y();

    if (composerActionPopover instanceof HTMLElement) {
        composerActionPopover.setAttribute('aria-label', 'Add or create actions');
    }
    if (!(composerActionList instanceof HTMLElement)) return;

    const priorityOrder = ['add_files', 'research', 'evolve', 'create_image', 'create_video', 'create_song', 'games'];
    const hiddenActions = new Set();
    const buttonByAction = new Map();
    Array.from(composerActionList.querySelectorAll('[data-action]')).forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) return;
        buttonByAction.set(safeString(button.dataset.action).toLowerCase(), button);
    });

    priorityOrder.forEach((action) => {
        const button = buttonByAction.get(action);
        if (button) composerActionList.appendChild(button);
    });

    buttonByAction.forEach((button, action) => {
        const isVisiblePrimary = priorityOrder.includes(action);
        button.classList.toggle('hidden', hiddenActions.has(action));
        button.classList.toggle('is-secondary', !hiddenActions.has(action) && !isVisiblePrimary);
        if (action === 'add_files') {
            button.textContent = 'Add files';
            button.title = 'Attach files to this chat';
        } else if (action === 'research') {
            button.textContent = 'Research';
            button.title = 'Run a research-oriented prompt';
        } else if (action === 'evolve') {
            button.textContent = 'Evolve';
            button.title = 'Launch a green-side self-improvement session';
        } else if (action === 'create_image') {
            button.textContent = 'Create image';
            button.title = 'Start an image generation request';
        } else if (action === 'create_video') {
            button.textContent = 'Create video';
            button.title = 'Start a video generation request';
        } else if (action === 'create_song') {
            button.textContent = 'Create song';
            button.title = 'Start a music generation request';
        } else if (action === 'games') {
            button.textContent = 'Games';
            button.title = 'Open built-in chat games';
        }
    });
}

function isCompactWebLayout() {
    try {
        if (typeof window?.matchMedia === 'function') {
            return window.matchMedia(UI_COMPACT_LAYOUT_MEDIA_QUERY).matches;
        }
    } catch {
        // Fall back to viewport width.
    }
    return window.innerWidth <= 760;
}

function applyResponsiveSidebarState() {
    if (!(sidebar instanceof HTMLElement)) return;
    const viewportMode = isCompactWebLayout() ? 'compact' : 'wide';
    const previousMode = lastSidebarResponsiveViewport;
    lastSidebarResponsiveViewport = viewportMode;
    if (viewportMode === 'compact') {
        if (previousMode !== 'compact') {
            sidebar.classList.add('collapsed');
        }
        return;
    }
    if (previousMode === 'compact' || previousMode === '') {
        sidebar.classList.toggle('collapsed', loadStoredSidebarCollapsed());
    }
}

function setAssistantSuggestions({ title = 'Suggestions', options = [], context = 'general', dismissible = true } = {}) {
    if (!assistantSuggestionRail || !assistantSuggestionBubbles) return;
    if (isGenerating) return;

    const validOptions = (Array.isArray(options) ? options : []).filter((option) => {
        return Boolean(safeString(option?.label) || safeString(option?.value));
    });
    if (validOptions.length === 0) {
        hideAssistantSuggestions({ force: true });
        return;
    }

    suggestionRailVersion += 1;
    const renderVersion = suggestionRailVersion;
    suggestionContext = safeString(context) || 'general';
    suggestionDismissible = Boolean(dismissible);
    const heading = safeString(title) || 'Suggestions';

    assistantSuggestionRail.classList.remove('hidden');
    assistantSuggestionRail.dataset.context = suggestionContext;
    if (assistantSuggestionTitle) {
        assistantSuggestionTitle.textContent = heading;
    }
    if (assistantSuggestionDismissBtn) {
        assistantSuggestionDismissBtn.classList.toggle('hidden', !suggestionDismissible);
    }

    assistantSuggestionBubbles.innerHTML = '';
    assistantSuggestionBubbles.dataset.mode = 'marquee';
    assistantSuggestionBubbles.dataset.ready = 'false';

    const track = document.createElement('div');
    track.className = 'assistant-suggestion-track';

    function createChipButton(option) {
        const button = document.createElement('button');
        const isAction = safeString(option?.kind) === 'action';
        button.className = isAction
            ? 'onboarding-action-chip assistant-suggestion-chip'
            : 'onboarding-option-chip assistant-suggestion-chip';
        if (safeString(option?.tone) === 'primary') button.classList.add('primary');
        if (safeString(option?.tone) === 'danger') button.classList.add('danger');
        button.type = 'button';
        button.textContent = safeString(option?.label) || safeString(option?.value);

        button.addEventListener('click', async () => {
            if (!assistantSuggestionBubbles) return;
            const buttons = Array.from(assistantSuggestionBubbles.querySelectorAll('button'));
            buttons.forEach((b) => { b.disabled = true; });
            button.classList.add('selected');

            try {
                if (typeof option?.onChoose === 'function') {
                    await option.onChoose(option);
                } else {
                    const sendPrompt = safeString(option?.send_prompt || option?.sendPrompt);
                    const insertPrompt = safeString(option?.insert_prompt || option?.insertPrompt);
                    if (sendPrompt) {
                        composerTextarea.value = sendPrompt;
                        composerTextarea.dispatchEvent(new Event('input'));
                        await handleSend();
                    } else if (insertPrompt) {
                        composerTextarea.value = insertPrompt;
                        composerTextarea.dispatchEvent(new Event('input'));
                        composerTextarea.focus();
                    }
                }
            } catch (err) {
                console.error('Suggestion action failed', err);
            } finally {
                if (renderVersion !== suggestionRailVersion) return;
                if (Boolean(option?.keep_after_choose)) {
                    buttons.forEach((b) => { b.disabled = false; });
                    button.classList.remove('selected');
                } else {
                    hideAssistantSuggestions({ force: true });
                }
            }
        });
        return button;
    }

    const loopOptions = validOptions.slice(0, 12);
    const primaryGroup = document.createElement('div');
    primaryGroup.className = 'assistant-suggestion-group';
    loopOptions.forEach((option) => {
        primaryGroup.appendChild(createChipButton(option));
    });
    track.appendChild(primaryGroup);

    const duplicateGroup = document.createElement('div');
    duplicateGroup.className = 'assistant-suggestion-group is-duplicate';
    duplicateGroup.setAttribute('aria-hidden', 'true');
    loopOptions.forEach((option) => {
        duplicateGroup.appendChild(createChipButton(option));
    });
    track.appendChild(duplicateGroup);

    assistantSuggestionBubbles.appendChild(track);

    requestAnimationFrame(() => {
        if (renderVersion !== suggestionRailVersion || !primaryGroup.isConnected || !track.isConnected) return;
        const groupWidth = Math.max(1, Math.ceil(primaryGroup.getBoundingClientRect().width));
        const pixelsPerSecond = 16;
        const durationSeconds = Math.max(40, Math.min(88, groupWidth / pixelsPerSecond));
        track.style.setProperty('--assistant-group-width', `${groupWidth}px`);
        track.style.setProperty('--assistant-scroll-duration', `${durationSeconds}s`);
        assistantSuggestionBubbles.dataset.ready = 'true';
    });
}

function normalizeSuggestionOptions(options = []) {
    const unique = [];
    const seen = new Set();
    (Array.isArray(options) ? options : []).forEach((option) => {
        const label = safeString(option?.label || option?.value);
        if (!label) return;
        const key = label.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        unique.push(option);
    });
    return unique.slice(0, 9);
}

function buildUniversalFollowupSuggestionOptions() {
    return normalizeSuggestionOptions([
        {
            label: 'Keep this moving',
            kind: 'action',
            tone: 'primary',
            send_prompt: 'Continue this exact task. Give me the best next step and execute it directly where possible.',
        },
        {
            label: 'Summarize where we are',
            kind: 'option',
            send_prompt: 'Give a quick summary of where we are and what matters most next.',
        },
        {
            label: 'Next 3 actions',
            kind: 'option',
            send_prompt: 'Give the next 3 highest-impact actions from here.',
        },
        {
            label: 'Make it concrete',
            kind: 'option',
            send_prompt: 'Make this more concrete with specific examples and outputs.',
        },
        {
            label: 'Check assumptions',
            kind: 'option',
            send_prompt: 'List the assumptions behind this result and what to validate first.',
        },
        {
            label: 'Give me 3 alternatives',
            kind: 'option',
            send_prompt: 'Offer 3 viable alternatives with tradeoffs.',
        },
        {
            label: 'Ask what you need',
            kind: 'option',
            send_prompt: 'Ask only the minimum questions needed to improve the result.',
        },
    ]);
}

function buildStarterSuggestionOptions() {
    if (!isOnboardingComplete()) {
        return [
            {
                label: 'Run Easy Setup',
                kind: 'action',
                tone: 'primary',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'suggestion', force: false, restart: false });
                },
            },
            {
                label: withAgentName('Is {{agent}} safe?'),
                kind: 'option',
                send_prompt: withAgentName('Is {{agent}} safe to run? Explain approvals, downloads, and security controls in plain language.'),
            },
            {
                label: 'What does setup do?',
                kind: 'option',
                send_prompt: 'Explain Easy Setup in plain English and what each step unlocks.',
            },
            {
                label: 'Minimal setup',
                kind: 'action',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'suggestion', force: false, restart: true });
                    handleEasySetupPathSelect('manual');
                },
            },
        ];
    }

    return [
        {
            label: 'Plan something',
            kind: 'action',
            tone: 'primary',
            send_prompt: 'Help me plan something important with milestones, priorities, and a practical first step.',
        },
        {
            label: 'Draft a message',
            kind: 'option',
            send_prompt: 'Help me draft a clear, effective message/email. Ask 2-3 clarifying questions first.',
        },
        {
            label: 'Research a topic',
            kind: 'option',
            send_prompt: 'Research this topic and compare the best options with tradeoffs and a recommendation.',
        },
        {
            label: 'Brainstorm ideas',
            kind: 'option',
            send_prompt: 'Brainstorm a wide range of ideas, then shortlist the strongest 3 with reasoning.',
        },
        {
            label: 'Organize tasks',
            kind: 'option',
            send_prompt: 'Turn my current priorities into a focused, realistic task plan.',
        },
        {
            label: 'Help me decide',
            kind: 'option',
            send_prompt: 'Help me decide between options with a clear recommendation and tradeoffs.',
        },
    ];
}

