//   MISSION CONTROL                                                        
//   Agent ops, job tracking, approvals, KPIs, timeline, room load          
// 

function missionEnsureState() {
    if (missionState) {
        return missionState;
    }
    if (!missionWorkspace) {
        return null;
    }
    missionState = {
        active: false,
        loading: false,
        actionInFlight: false,
        controlsBound: false,
        pollTimerId: 0,
        autoStartQueuedJobsPending: false,
        autoRefresh: true,
        lastPayload: null,
        lastJobsPayload: null,
        lastFetchedAt: 0,
        stream: {
            controller: null,
            connected: false,
            connecting: false,
            reconnectTimer: 0,
            retryMs: MISSION_STREAM_RETRY_MIN_MS,
            lastSeq: 0,
            lastMessageAt: 0,
        },
    };
    return missionState;
}

function missionToEpoch(value) {
    const raw = safeString(value);
    if (!raw) return 0;
    const epoch = Date.parse(raw);
    return Number.isFinite(epoch) ? epoch : 0;
}

function missionRelativeTime(value) {
    const epoch = missionToEpoch(value);
    if (!epoch) return '--';
    const delta = Date.now() - epoch;
    const abs = Math.abs(delta);
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;

    if (abs < 45000) return delta >= 0 ? 'just now' : 'soon';
    if (abs < hour) {
        const n = Math.max(1, Math.round(abs / minute));
        return delta >= 0 ? `${n}m ago` : `in ${n}m`;
    }
    if (abs < day) {
        const n = Math.max(1, Math.round(abs / hour));
        return delta >= 0 ? `${n}h ago` : `in ${n}h`;
    }
    const n = Math.max(1, Math.round(abs / day));
    return delta >= 0 ? `${n}d ago` : `in ${n}d`;
}

function missionStatusValue(statusRaw) {
    return safeString(statusRaw).toLowerCase().replace(/\s+/g, '_') || 'unknown';
}

function missionStatusLabel(statusRaw) {
    const normalized = missionStatusValue(statusRaw);
    if (normalized === 'awaiting_approval') return 'awaiting approval';
    if (normalized === 'awaiting_proof') return 'awaiting proof';
    if (normalized === 'in_progress') return 'in progress';
    return normalized.replace(/_/g, ' ');
}

function missionStatusRank(statusRaw) {
    const normalized = missionStatusValue(statusRaw);
    const rank = {
        failed: 0,
        dead: 0,
        cancelled: 1,
        blocked: 2,
        awaiting_approval: 3,
        awaiting_proof: 3,
        verified: 3,
        running: 4,
        active: 4,
        executing: 4,
        in_progress: 4,
        claimed: 5,
        requested: 5,
        classified: 5,
        queued: 5,
        pending: 5,
        succeeded: 8,
        completed: 8,
    };
    return Object.prototype.hasOwnProperty.call(rank, normalized) ? rank[normalized] : 6;
}

function missionRoomRank(roomRaw) {
    const room = safeString(roomRaw).toLowerCase();
    const rank = {
        review: 0,
        planning: 1,
        tools: 2,
        files: 3,
        inbox: 4,
        done: 5,
    };
    return Object.prototype.hasOwnProperty.call(rank, room) ? rank[room] : 6;
}

function missionSetConnectionState(kind = 'neutral', text = 'Standby') {
    if (!missionConnectionPill) return;
    missionConnectionPill.className = `mission-meta-pill ${safeString(kind) || 'neutral'}`;
    missionConnectionPill.textContent = safeString(text) || 'Standby';
}

function missionRenderEmpty(container, message) {
    if (!container) return;
    container.innerHTML = '';
    const empty = document.createElement('div');
    empty.className = 'mission-item-empty';
    empty.textContent = safeString(message) || 'No data available.';
    container.appendChild(empty);
}

function missionCreatePill(label, extraClass = '') {
    const pill = document.createElement('span');
    pill.className = `mission-pill ${safeString(extraClass)}`.trim();
    pill.textContent = safeString(label);
    return pill;
}

function missionFormatSeconds(secondsRaw) {
    const seconds = Number(secondsRaw || 0);
    if (!Number.isFinite(seconds) || seconds <= 0) return '--';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
    return `${Math.round(seconds / 86400)}d`;
}

function missionScheduleDescriptor(job) {
    const schedule = job?.schedule && typeof job.schedule === 'object' ? job.schedule : null;
    const nextRun = safeString(job?.next_run_at);
    if (!schedule) {
        return {
            recurring: false,
            cadence: nextRun ? 'one-time' : 'manual',
            next: nextRun ? missionRelativeTime(nextRun) : '--',
        };
    }

    const stype = safeString(schedule?.type).toLowerCase();
    if (stype === 'interval') {
        return {
            recurring: true,
            cadence: `every ${missionFormatSeconds(schedule?.every_seconds)}`,
            next: nextRun ? missionRelativeTime(nextRun) : '--',
        };
    }
    if (stype === 'daily') {
        const at = safeString(schedule?.at) || '--:--';
        const tz = safeString(schedule?.tz) || 'UTC';
        return {
            recurring: true,
            cadence: `daily ${at}`,
            next: nextRun ? missionRelativeTime(nextRun) : '--',
            detail: tz,
        };
    }
    if (stype === 'weekly') {
        const at = safeString(schedule?.at) || '--:--';
        const tz = safeString(schedule?.tz) || 'UTC';
        const dows = Array.isArray(schedule?.dow) ? schedule.dow : [];
        const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const dowLabel = dows
            .map((raw) => Number(raw))
            .filter((idx) => Number.isInteger(idx) && idx >= 0 && idx <= 6)
            .slice(0, 7)
            .map((idx) => labels[idx])
            .join(', ');
        return {
            recurring: true,
            cadence: `weekly ${at}`,
            next: nextRun ? missionRelativeTime(nextRun) : '--',
            detail: `${dowLabel || 'no days'} | ${tz}`,
        };
    }
    if (stype === 'once') {
        return {
            recurring: false,
            cadence: 'one-time',
            next: nextRun ? missionRelativeTime(nextRun) : '--',
        };
    }
    return {
        recurring: MISSION_RECURRING_SCHEDULE_TYPES.has(stype),
        cadence: stype || 'scheduled',
        next: nextRun ? missionRelativeTime(nextRun) : '--',
    };
}

function missionJobStatusRank(statusRaw) {
    const status = missionStatusValue(statusRaw);
    const rank = {
        running: 0,
        active: 0,
        executing: 0,
        in_progress: 0,
        awaiting_approval: 1,
        awaiting_proof: 1,
        verified: 1,
        claimed: 2,
        requested: 2,
        classified: 2,
        queued: 2,
        blocked: 3,
        failed: 4,
        dead: 4,
        cancelled: 5,
        succeeded: 6,
        completed: 6,
    };
    return Object.prototype.hasOwnProperty.call(rank, status) ? rank[status] : 7;
}

function missionJobSummary(job) {
    const payload = job?.payload && typeof job.payload === 'object' ? job.payload : {};
    return (
        safeString(job?.summary)
        || safeString(job?.progress_summary)
        || safeString(job?.request_text)
        || safeString(payload?.goal)
        || safeString(payload?.prompt)
        || safeString(payload?.task)
        || safeString(payload?.message)
        || safeString(job?.task_id)
        || safeString(job?.name)
        || 'No task summary provided.'
    );
}

function missionJobActionUrl(jobId, action) {
    const safeId = encodeURIComponent(safeString(jobId));
    if (!safeId) return '';
    if (action === 'cancel') return `/api/mission/jobs/${safeId}/cancel`;
    if (action === 'run_now') return `/api/mission/jobs/${safeId}/run_now`;
    if (action === 'requeue') return `/api/mission/jobs/${safeId}/requeue`;
    return '';
}

async function missionRunJobAction(jobId, action) {
    const state = missionEnsureState();
    if (!state || state.actionInFlight) return;
    const url = missionJobActionUrl(jobId, action);
    if (!url) return;

    state.actionInFlight = true;
    if (missionSetConnectionState) missionSetConnectionState('neutral', 'Updating');
    try {
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }
        const actionLabel = safeString(action).replace(/_/g, ' ');
        notifyUser(`Job ${actionLabel} requested.`, {
            tone: 'success',
            debugKind: 'success',
            durationMs: 1800,
        });
        await missionRefresh({ force: true, silent: true });
    } catch (error) {
        console.error('Mission job action failed', error);
        notifyUser('Mission job action failed.', {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2400,
        });
        missionSetConnectionState('danger', 'Offline');
    } finally {
        state.actionInFlight = false;
    }
}

async function missionResolveApproval(payload) {
    const state = missionEnsureState();
    if (!state || state.actionInFlight) return;
    if (!payload || typeof payload !== 'object') return;

    const source = safeString(payload.source).toLowerCase();
    const action = safeString(payload.action).toLowerCase();
    const approve = action === 'approve' || action === 'approve_session';
    const allowSessionTool = action === 'approve_session';

    if (!source || !action) return;
    if (!['approve', 'approve_session', 'deny'].includes(action)) return;

    const actor = typeof getAgentName === 'function' ? getAgentName() : 'mission_control';
    let url = '';
    let body = {
        approve,
        actor: safeString(actor) || 'mission_control',
    };

    if (source === 'autonomy') {
        const approvalId = safeString(payload.approvalId);
        if (!approvalId) return;
        url = `/api/mission/approvals/autonomy/${encodeURIComponent(approvalId)}/decision`;
        body.reason = approve ? 'approved in mission control' : 'denied in mission control';
    } else if (source === 'guardrails') {
        const runId = safeString(payload.runId);
        const toolCallId = safeString(payload.toolCallId);
        if (!runId || !toolCallId) return;
        url = '/api/mission/approvals/guardrails/resolve';
        body = {
            run_id: runId,
            tool_call_id: toolCallId,
            allow_session_tool: allowSessionTool && approve,
            tool_name: safeString(payload.toolName),
            session_id: safeString(payload.sessionId),
            approve,
            actor: safeString(actor) || 'mission_control',
        };
    } else {
        return;
    }

    state.actionInFlight = true;
    if (missionSetConnectionState) missionSetConnectionState('neutral', 'Updating');
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const details = await res.text();
            throw new Error(details || `HTTP ${res.status}`);
        }
        const actionLabel = action === 'approve_session' ? 'session approval' : action.replace('_', ' ');
        notifyUser(`${actionLabel.charAt(0).toUpperCase() + actionLabel.slice(1)} submitted.`, {
            tone: 'success',
            debugKind: 'success',
            durationMs: 1700,
        });
        await missionRefresh({ force: true, silent: true });
    } catch (error) {
        console.error('Mission approval action failed', error);
        notifyUser('Mission approval action failed.', {
            tone: 'warning',
            debugKind: 'warning',
            durationMs: 2400,
        });
        missionSetConnectionState('danger', 'Offline');
    } finally {
        state.actionInFlight = false;
    }
}

function missionRenderJobs(jobsPayload) {
    if (!missionJobsList) return;
    const jobs = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
    const sessionFilter = safeString(jobsPayload?.filters?.session_id || missionPreferredSessionId());
    const sorted = [...jobs].sort((a, b) => {
        const byStatus = missionJobStatusRank(a?.status) - missionJobStatusRank(b?.status);
        if (byStatus !== 0) return byStatus;
        const aDue = missionToEpoch(a?.next_run_at) || missionToEpoch(a?.updated_at);
        const bDue = missionToEpoch(b?.next_run_at) || missionToEpoch(b?.updated_at);
        if (aDue !== bDue) return aDue - bDue;
        return safeString(a?.name).localeCompare(safeString(b?.name));
    });

    const recurringCount = sorted.filter((job) => missionScheduleDescriptor(job).recurring).length;
    const taskCount = Math.max(0, sorted.length - recurringCount);
    if (missionJobsTaskCount) missionJobsTaskCount.textContent = String(taskCount);
    if (missionJobsCronCount) missionJobsCronCount.textContent = String(recurringCount);
    if (missionJobsMeta) {
        if (jobsPayload?.unavailable) {
            const reason = safeString(jobsPayload?.reason) || 'autonomy store is not available';
            missionJobsMeta.textContent = `Jobs unavailable · ${reason}`;
        } else {
            const scopeLabel = sessionFilter ? 'current chat session' : 'all sessions';
            missionJobsMeta.textContent = `${sorted.length} total${sorted.length > 0 ? `, showing ${Math.min(sorted.length, 40)}` : ''} · ${scopeLabel}`;
        }
    }

    missionJobsList.innerHTML = '';
    if (jobsPayload?.unavailable) {
        const reason = safeString(jobsPayload?.reason) || 'autonomy store is not available';
        missionRenderEmpty(missionJobsList, `Jobs are unavailable right now: ${reason}.`);
        return;
    }
    if (!sorted.length) {
        missionRenderEmpty(
            missionJobsList,
            sessionFilter
                ? 'No jobs for this chat session yet. Ask Thomas to do a task and it should appear here.'
                : 'No jobs yet. Create a task or cron job from the form.',
        );
        return;
    }

    const frag = document.createDocumentFragment();
    sorted.slice(0, 40).forEach((job) => {
        const status = missionStatusValue(job?.status);
        const descriptor = missionScheduleDescriptor(job);
        const row = document.createElement('article');
        row.className = 'mission-item';

        const head = document.createElement('div');
        head.className = 'mission-item-head';

        const title = document.createElement('div');
        title.className = 'mission-item-title';
        title.textContent = safeString(job?.name) || safeString(job?.id) || 'Mission job';

        const tags = document.createElement('div');
        tags.className = 'mission-item-tags';
        tags.appendChild(missionCreatePill(missionStatusLabel(status), `status-${status}`));
        tags.appendChild(missionCreatePill(descriptor.recurring ? 'cron' : 'task'));
        const kind = safeString(job?.kind).replace(/_/g, ' ');
        if (kind) tags.appendChild(missionCreatePill(kind));

        head.appendChild(title);
        head.appendChild(tags);

        const summary = document.createElement('div');
        summary.className = 'mission-item-summary';
        summary.textContent = missionJobSummary(job);

        const meta = document.createElement('div');
        meta.className = 'mission-item-meta';
        const cadence = document.createElement('span');
        cadence.textContent = descriptor.cadence;
        const nextRun = document.createElement('span');
        nextRun.textContent = descriptor.next === '--' ? 'next --' : `next ${descriptor.next}`;
        meta.appendChild(cadence);
        meta.appendChild(nextRun);
        if (descriptor.detail) {
            const detail = document.createElement('span');
            detail.textContent = descriptor.detail;
            meta.appendChild(detail);
        }
        const marker = safeString(job?.id);
        if (marker) {
            const markerEl = document.createElement('span');
            markerEl.textContent = marker.slice(0, 18);
            meta.appendChild(markerEl);
        }

        const actions = document.createElement('div');
        actions.className = 'mission-item-actions';

        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'settings-mini-btn';
        runBtn.dataset.jobAction = 'run_now';
        runBtn.dataset.jobId = safeString(job?.id);
        runBtn.textContent = 'Run now';
        actions.appendChild(runBtn);

        const requeueBtn = document.createElement('button');
        requeueBtn.type = 'button';
        requeueBtn.className = 'settings-mini-btn';
        requeueBtn.dataset.jobAction = 'requeue';
        requeueBtn.dataset.jobId = safeString(job?.id);
        requeueBtn.textContent = 'Requeue';
        actions.appendChild(requeueBtn);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'settings-mini-btn';
        cancelBtn.dataset.jobAction = 'cancel';
        cancelBtn.dataset.jobId = safeString(job?.id);
        cancelBtn.textContent = 'Cancel';
        actions.appendChild(cancelBtn);

        row.appendChild(head);
        row.appendChild(summary);
        row.appendChild(meta);
        row.appendChild(actions);
        frag.appendChild(row);
    });

    missionJobsList.appendChild(frag);
}

function missionRenderOpsStrip(payload, jobsPayload) {
    const agents = Array.isArray(payload?.agents) ? payload.agents : [];
    const approvalsPending = Number(payload?.approvals?.pending_total || payload?.totals?.approvals_pending || 0);
    const runtime = missionBuildRuntimeState(payload, jobsPayload);
    const active = Array.isArray(runtime.liveAgents)
        ? runtime.liveAgents.filter((item) => {
            const status = missionStatusValue(item?.status);
            return status === 'running' || status === 'active' || status === 'queued' || status === 'pending';
        })
        : [];

    const nowItem = runtime.activeCount > 0 ? runtime.primary : null;
    if (missionOpsNowTitle) {
        missionOpsNowTitle.textContent = nowItem
            ? (safeString(nowItem?.name) || 'Active mission item')
            : 'No active execution';
    }
    if (missionOpsNowMeta) {
        const status = missionStatusValue(nowItem?.status);
        missionOpsNowMeta.textContent = nowItem
            ? `${missionStatusLabel(status)} | updated ${missionRelativeTime(nowItem?.updated_at)}`
            : 'Waiting for active jobs';
    }

    const jobs = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
    const nowEpoch = Date.now();
    const nextRows = jobs
        .map((job) => {
            const nextEpoch = missionToEpoch(job?.next_run_at);
            return { job, nextEpoch };
        })
        .filter((row) => row.nextEpoch > nowEpoch)
        .filter((row) => {
            const status = missionStatusValue(row?.job?.status);
            return !['cancelled', 'succeeded', 'dead'].includes(status);
        })
        .sort((a, b) => a.nextEpoch - b.nextEpoch);
    const next = nextRows[0] || null;
    if (missionOpsNextTitle) {
        missionOpsNextTitle.textContent = next
            ? (safeString(next.job?.name) || 'Scheduled mission job')
            : 'No scheduled runs';
    }
    if (missionOpsNextMeta) {
        if (next) {
            const descriptor = missionScheduleDescriptor(next.job);
            missionOpsNextMeta.textContent = `${descriptor.cadence} | ${missionRelativeTime(next.job?.next_run_at)}`;
        } else {
            missionOpsNextMeta.textContent = 'Create a cron job to automate work';
        }
    }

    let blockerCount = approvalsPending;
    agents.forEach((item) => {
        const status = missionStatusValue(item?.status);
        if (status === 'blocked' || status === 'awaiting_approval' || status === 'failed' || status === 'cancelled' || status === 'dead') {
            blockerCount += 1;
        }
    });

    if (missionOpsBlockersTitle) {
        missionOpsBlockersTitle.textContent = blockerCount ? `${blockerCount} blockers` : '0 blockers';
    }
    if (missionOpsBlockersMeta) {
        missionOpsBlockersMeta.textContent = blockerCount
            ? `${approvalsPending} approvals waiting`
            : 'No blocked or failed work';
    }
}

function missionRenderPriorityList(payload, roomLabelById) {
    if (!missionPriorityList) return;
    const agents = Array.isArray(payload?.agents) ? payload.agents : [];
    const activeStatuses = new Set([
        'running',
        'active',
        'queued',
        'pending',
        'awaiting_approval',
        'blocked',
        'failed',
        'cancelled',
        'dead',
    ]);
    const activeOnly = agents.filter((agent) => activeStatuses.has(missionStatusValue(agent?.status)));
    const pool = activeOnly.length ? activeOnly : agents;
    const sorted = [...pool].sort((a, b) => {
        const byStatus = missionStatusRank(a?.status) - missionStatusRank(b?.status);
        if (byStatus !== 0) return byStatus;
        const byRoom = missionRoomRank(a?.room) - missionRoomRank(b?.room);
        if (byRoom !== 0) return byRoom;
        const byUpdated = missionToEpoch(b?.updated_at) - missionToEpoch(a?.updated_at);
        if (byUpdated !== 0) return byUpdated;
        return safeString(a?.name).localeCompare(safeString(b?.name));
    });
    const top = sorted.slice(0, MISSION_PRIORITY_LIMIT);
    if (missionPriorityMeta) {
        missionPriorityMeta.textContent = `${top.length} shown${pool.length > top.length ? ` of ${pool.length}` : ''}`;
    }
    missionPriorityList.innerHTML = '';
    if (!top.length) {
        missionRenderEmpty(missionPriorityList, 'No mission jobs yet. Activity appears idle.');
        return;
    }

    const frag = document.createDocumentFragment();
    top.forEach((item) => {
        const status = missionStatusValue(item?.status);
        const row = document.createElement('article');
        row.className = 'mission-item';

        const head = document.createElement('div');
        head.className = 'mission-item-head';

        const title = document.createElement('div');
        title.className = 'mission-item-title';
        title.textContent = safeString(item?.name) || safeString(item?.id) || 'Unnamed mission item';

        const tags = document.createElement('div');
        tags.className = 'mission-item-tags';
        tags.appendChild(missionCreatePill(missionStatusLabel(status), `status-${status}`));
        const sourceLabel = safeString(item?.kind) || safeString(item?.source) || 'agent';
        if (sourceLabel) {
            tags.appendChild(missionCreatePill(sourceLabel.replace(/_/g, ' ')));
        }

        head.appendChild(title);
        head.appendChild(tags);

        const summary = document.createElement('div');
        summary.className = 'mission-item-summary';
        summary.textContent = safeString(item?.summary) || 'No summary reported.';

        const meta = document.createElement('div');
        meta.className = 'mission-item-meta';
        const roomId = safeString(item?.room);
        const roomLabel = roomLabelById.get(roomId) || roomId || 'unassigned';
        const marker = safeString(item?.job_id || item?.objective_id).slice(0, 18);
        const updated = missionRelativeTime(item?.updated_at);

        const roomEl = document.createElement('span');
        roomEl.textContent = roomLabel;
        const updatedEl = document.createElement('span');
        updatedEl.textContent = `updated ${updated}`;
        meta.appendChild(roomEl);
        meta.appendChild(updatedEl);
        if (safeString(item?.source) === 'chat_run') {
            const modelLabel = safeString(item?.model_id).split('/').pop();
            const profileLabel = safeString(item?.profile);
            if (profileLabel || modelLabel) {
                const runMeta = document.createElement('span');
                runMeta.textContent = [profileLabel, modelLabel].filter(Boolean).join(' | ');
                meta.appendChild(runMeta);
            }
        }
        if (marker) {
            const markerEl = document.createElement('span');
            markerEl.textContent = marker;
            meta.appendChild(markerEl);
        }

        row.appendChild(head);
        row.appendChild(summary);
        row.appendChild(meta);
        frag.appendChild(row);
    });

    missionPriorityList.appendChild(frag);
}

function missionRenderApprovals(payload) {
    if (!missionApprovalsList) return;
    const approvals = payload?.approvals || {};
    const autonomy = Array.isArray(approvals?.autonomy) ? approvals.autonomy : [];
    const guardrails = Array.isArray(approvals?.guardrails) ? approvals.guardrails : [];
    const rows = [];

    autonomy.forEach((item) => {
        const action = item?.action && typeof item.action === 'object' ? item.action : {};
        rows.push({
            source: 'autonomy',
            status: missionStatusValue(item?.status) || 'awaiting_approval',
            requestedAt: item?.requested_at,
            title: safeString(action?.title || action?.tool_name || item?.id || 'Autonomy approval'),
            summary:
                safeString(action?.summary)
                || safeString(item?.decision_reason)
                || `${safeString(item?.risk_class) || 'normal'} risk approval request`,
            marker: safeString(item?.job_id || item?.id),
            approvalId: safeString(item?.id),
        });
    });

    guardrails.forEach((item) => {
        const toolName = safeString(item?.tool_name) || 'tool call';
        rows.push({
            source: 'guardrails',
            status: 'awaiting_approval',
            requestedAt: item?.requested_at,
            title: `Tool approval: ${toolName}`,
            summary: safeString(item?.reason) || 'Guardrails requested human review.',
            marker: safeString(item?.run_id || item?.tool_call_id),
            runId: safeString(item?.run_id),
            toolCallId: safeString(item?.tool_call_id),
            toolName,
            sessionId: safeString(item?.session_id),
        });
    });

    rows.sort((a, b) => missionToEpoch(b.requestedAt) - missionToEpoch(a.requestedAt));
    if (missionApprovalsMeta) {
        missionApprovalsMeta.textContent = `${rows.length} pending`;
    }

    missionApprovalsList.innerHTML = '';
    if (!rows.length) {
        missionRenderEmpty(missionApprovalsList, 'No approvals are waiting.');
        return;
    }

    const frag = document.createDocumentFragment();
    rows.slice(0, 12).forEach((item) => {
        const row = document.createElement('article');
        row.className = 'mission-item';

        const head = document.createElement('div');
        head.className = 'mission-item-head';
        const title = document.createElement('div');
        title.className = 'mission-item-title';
        title.textContent = item.title;

        const tags = document.createElement('div');
        tags.className = 'mission-item-tags';
        tags.appendChild(missionCreatePill('approval', 'status-awaiting_approval'));
        tags.appendChild(missionCreatePill(item.source));

        head.appendChild(title);
        head.appendChild(tags);

        const summary = document.createElement('div');
        summary.className = 'mission-item-summary';
        summary.textContent = item.summary;

        const meta = document.createElement('div');
        meta.className = 'mission-item-meta';
        const requested = document.createElement('span');
        requested.textContent = `requested ${missionRelativeTime(item.requestedAt)}`;
        meta.appendChild(requested);
        if (item.marker) {
            const marker = document.createElement('span');
            marker.textContent = item.marker.slice(0, 18);
            meta.appendChild(marker);
        }

        const actions = document.createElement('div');
        actions.className = 'mission-item-actions';
        if (item.source === 'autonomy' && item.approvalId) {
            const approveBtn = document.createElement('button');
            approveBtn.type = 'button';
            approveBtn.className = 'settings-mini-btn';
            approveBtn.textContent = 'Approve';
            approveBtn.dataset.approvalAction = 'approve';
            approveBtn.dataset.approvalSource = item.source;
            approveBtn.dataset.approvalId = item.approvalId;

            const denyBtn = document.createElement('button');
            denyBtn.type = 'button';
            denyBtn.className = 'settings-mini-btn danger';
            denyBtn.textContent = 'Deny';
            denyBtn.dataset.approvalAction = 'deny';
            denyBtn.dataset.approvalSource = item.source;
            denyBtn.dataset.approvalId = item.approvalId;

            actions.appendChild(approveBtn);
            actions.appendChild(denyBtn);
        } else if (item.source === 'guardrails' && item.runId && item.toolCallId) {
            const approveBtn = document.createElement('button');
            approveBtn.type = 'button';
            approveBtn.className = 'settings-mini-btn';
            approveBtn.textContent = 'Approve once';
            approveBtn.dataset.approvalAction = 'approve';
            approveBtn.dataset.approvalSource = item.source;
            approveBtn.dataset.runId = item.runId;
            approveBtn.dataset.toolCallId = item.toolCallId;
            approveBtn.dataset.toolName = item.toolName;
            approveBtn.dataset.sessionId = item.sessionId;

            const approveSessionBtn = document.createElement('button');
            approveSessionBtn.type = 'button';
            approveSessionBtn.className = 'settings-mini-btn';
            approveSessionBtn.textContent = 'Approve session';
            approveSessionBtn.dataset.approvalAction = 'approve_session';
            approveSessionBtn.dataset.approvalSource = item.source;
            approveSessionBtn.dataset.runId = item.runId;
            approveSessionBtn.dataset.toolCallId = item.toolCallId;
            approveSessionBtn.dataset.toolName = item.toolName;
            approveSessionBtn.dataset.sessionId = item.sessionId;

            const denyBtn = document.createElement('button');
            denyBtn.type = 'button';
            denyBtn.className = 'settings-mini-btn danger';
            denyBtn.textContent = 'Deny';
            denyBtn.dataset.approvalAction = 'deny';
            denyBtn.dataset.approvalSource = item.source;
            denyBtn.dataset.runId = item.runId;
            denyBtn.dataset.toolCallId = item.toolCallId;
            denyBtn.dataset.toolName = item.toolName;
            denyBtn.dataset.sessionId = item.sessionId;

            actions.appendChild(approveBtn);
            actions.appendChild(approveSessionBtn);
            actions.appendChild(denyBtn);
        }

        row.appendChild(head);
        row.appendChild(summary);
        row.appendChild(meta);
        if (actions.childElementCount) {
            row.appendChild(actions);
        }
        frag.appendChild(row);
    });
    missionApprovalsList.appendChild(frag);
}

function missionRenderRooms(payload, roomLabelById) {
    if (!missionRoomsList) return;
    const rooms = Array.isArray(payload?.rooms) ? payload.rooms : [];
    const agents = Array.isArray(payload?.agents) ? payload.agents : [];
    const activeStatuses = new Set([
        'running',
        'active',
        'queued',
        'pending',
        'awaiting_approval',
        'blocked',
        'failed',
        'cancelled',
        'dead',
    ]);

    const counts = new Map();
    agents.forEach((item) => {
        const status = missionStatusValue(item?.status);
        if (!activeStatuses.has(status)) return;
        const roomId = safeString(item?.room);
        if (!roomId) return;
        counts.set(roomId, Number(counts.get(roomId) || 0) + 1);
    });

    const rows = rooms
        .map((room) => {
            const id = safeString(room?.id);
            return {
                roomId: id,
                label: roomLabelById.get(id) || safeString(room?.label) || id,
                count: Number(counts.get(id) || 0),
            };
        })
        .filter((entry) => entry.count > 0)
        .sort((a, b) => {
            if (b.count !== a.count) return b.count - a.count;
            return a.label.localeCompare(b.label);
        });

    missionRoomsList.innerHTML = '';
    if (!rows.length) {
        missionRenderEmpty(missionRoomsList, 'No active room load right now.');
        return;
    }

    const maxCount = rows.reduce((acc, row) => Math.max(acc, row.count), 1);
    const frag = document.createDocumentFragment();
    rows.forEach((room) => {
        const row = document.createElement('article');
        row.className = 'mission-room-row';

        const head = document.createElement('div');
        head.className = 'mission-room-head';
        const name = document.createElement('span');
        name.className = 'mission-room-name';
        name.textContent = room.label;
        const count = document.createElement('span');
        count.className = 'mission-room-count';
        count.textContent = `${room.count} active`;
        head.appendChild(name);
        head.appendChild(count);

        const bar = document.createElement('div');
        bar.className = 'mission-room-bar';
        const fill = document.createElement('span');
        const pct = Math.max(8, Math.round((room.count / maxCount) * 100));
        fill.style.width = `${pct}%`;
        bar.appendChild(fill);

        row.appendChild(head);
        row.appendChild(bar);
        frag.appendChild(row);
    });

    missionRoomsList.appendChild(frag);
}

function missionRenderTimeline(payload) {
    if (!missionTimelineList) return;
    const allEvents = Array.isArray(payload?.events) ? payload.events : [];
    const cutoff = Date.now() - MISSION_TIMELINE_RECENT_MS;
    const events = allEvents.filter((event) => {
        const ts = missionToEpoch(event?.ts);
        if (!ts) return true;
        return ts >= cutoff;
    });
    if (missionTimelineMeta) {
        const shown = Math.min(events.length, MISSION_TIMELINE_LIMIT);
        missionTimelineMeta.textContent = `${shown} latest${events.length > shown ? ` of ${events.length}` : ''}`;
    }
    missionTimelineList.innerHTML = '';
    if (!events.length) {
        missionRenderEmpty(missionTimelineList, 'No recent signals in the last 36 hours.');
        return;
    }

    const frag = document.createDocumentFragment();
    events.slice(0, MISSION_TIMELINE_LIMIT).forEach((event) => {
        const row = document.createElement('article');
        row.className = 'mission-item';

        const head = document.createElement('div');
        head.className = 'mission-item-head';
        const title = document.createElement('div');
        title.className = 'mission-item-title';
        title.textContent = safeString(event?.type || 'event').replace(/_/g, ' ');

        const tags = document.createElement('div');
        tags.className = 'mission-item-tags';
        const source = safeString(event?.source) || 'signal';
        tags.appendChild(missionCreatePill(source.replace(/_/g, ' ')));

        head.appendChild(title);
        head.appendChild(tags);

        const summary = document.createElement('div');
        summary.className = 'mission-item-summary';
        summary.textContent = safeString(event?.text) || 'No details provided.';

        const meta = document.createElement('div');
        meta.className = 'mission-item-meta';
        const when = document.createElement('span');
        when.textContent = missionRelativeTime(event?.ts);
        meta.appendChild(when);
        const marker = safeString(event?.agent_id || event?.run_id);
        if (marker) {
            const markerEl = document.createElement('span');
            markerEl.textContent = marker.slice(0, 18);
            meta.appendChild(markerEl);
        }

        row.appendChild(head);
        row.appendChild(summary);
        row.appendChild(meta);
        frag.appendChild(row);
    });

    missionTimelineList.appendChild(frag);
}

function missionRenderHeaderAndKpis(payload) {
    const totals = payload?.totals && typeof payload.totals === 'object' ? payload.totals : {};
    const engine = payload?.engine && typeof payload.engine === 'object' ? payload.engine : {};
    const agents = Array.isArray(payload?.agents) ? payload.agents : [];
    const approvalsPending = Number(totals.approvals_pending || payload?.approvals?.pending_total || 0);

    const statusCounts = {
        running: 0,
        queued: 0,
        blocked: 0,
        failed: 0,
    };
    agents.forEach((item) => {
        const status = missionStatusValue(item?.status);
        if (status === 'running' || status === 'active') statusCounts.running += 1;
        if (status === 'queued' || status === 'pending') statusCounts.queued += 1;
        if (status === 'blocked' || status === 'awaiting_approval') statusCounts.blocked += 1;
        if (status === 'failed' || status === 'cancelled' || status === 'dead') statusCounts.failed += 1;
    });

    if (missionKpiActiveAgents) missionKpiActiveAgents.textContent = String(Number(totals.active_agents || 0));
    if (missionKpiActiveMeta) {
        missionKpiActiveMeta.textContent = `${statusCounts.running} running | ${statusCounts.queued} queued`;
    }
    if (missionKpiApprovals) missionKpiApprovals.textContent = String(approvalsPending);
    if (missionKpiApprovalsMeta) {
        missionKpiApprovalsMeta.textContent = approvalsPending ? 'Review queue needs attention' : 'No approvals waiting';
    }
    const riskCount = statusCounts.blocked + statusCounts.failed;
    if (missionKpiRisks) missionKpiRisks.textContent = String(riskCount);
    if (missionKpiRisksMeta) {
        missionKpiRisksMeta.textContent = `${statusCounts.blocked} blocked | ${statusCounts.failed} failed`;
    }

    const runStoreEnabled = Boolean(engine.run_store_enabled);
    const autonomyEnabled = Boolean(engine.autonomy_enabled);
    const autonomyRunning = Boolean(engine.autonomy_running);
    if (missionKpiEngine) {
        missionKpiEngine.textContent = autonomyRunning
            ? 'Online'
            : (autonomyEnabled || runStoreEnabled ? 'Standby' : 'Limited');
    }
    if (missionKpiEngineMeta) {
        missionKpiEngineMeta.textContent = `Run store ${runStoreEnabled ? 'on' : 'off'} | Autonomy ${autonomyEnabled ? 'on' : 'off'}`;
    }

    if (missionUpdatedAt) {
        const stamp = missionToEpoch(payload?.generated_at);
        missionUpdatedAt.textContent = stamp
            ? `${new Date(stamp).toLocaleTimeString([], { hour12: false })} (${missionRelativeTime(payload?.generated_at)})`
            : missionRelativeTime(payload?.generated_at);
    }
}

function missionCreateUnavailableReason(payload, jobsPayload = null) {
    if (jobsPayload?.unavailable) {
        return safeString(jobsPayload?.reason) || 'autonomy store is not available';
    }
    const engine = payload?.engine && typeof payload.engine === 'object' ? payload.engine : {};
    if (!Boolean(engine.run_store_enabled)) {
        return 'run store is off';
    }
    if (!Boolean(engine.autonomy_enabled)) {
        return 'autonomy is off';
    }
    return '';
}

function missionSyncCreateAvailability(payload, jobsPayload = null) {
    const reason = missionCreateUnavailableReason(payload, jobsPayload);
    const disabled = Boolean(reason);
    if (missionJobForm) {
        missionJobForm.dataset.missionUnavailable = disabled ? '1' : '0';
        missionJobForm.querySelectorAll('input, select, textarea, button').forEach((node) => {
            if (
                node instanceof HTMLInputElement
                || node instanceof HTMLSelectElement
                || node instanceof HTMLTextAreaElement
                || node instanceof HTMLButtonElement
            ) {
                node.disabled = disabled;
            }
        });
    }
    if (missionJobSubmitBtn) {
        missionJobSubmitBtn.title = disabled ? `Mission runtime unavailable: ${reason}` : 'Create mission job';
    }
    if (disabled) {
        missionSetCreateMeta(`creation unavailable: ${reason}`);
        return;
    }
    missionUpdateScheduleFields();
}

function missionRender(payload, jobsPayload = null) {
    const rooms = Array.isArray(payload?.rooms) ? payload.rooms : [];
    const roomLabelById = new Map();
    rooms.forEach((room) => {
        const id = safeString(room?.id);
        if (!id) return;
        roomLabelById.set(id, safeString(room?.label) || id);
    });

    const activeJobsPayload = jobsPayload || missionState?.lastJobsPayload || { jobs: [] };
    renderMissionRuntimeHero(payload, activeJobsPayload);
    missionRenderOpsStrip(payload, activeJobsPayload);
    missionRenderJobs(activeJobsPayload);
    missionRenderHeaderAndKpis(payload);
    missionSyncCreateAvailability(payload, activeJobsPayload);
    missionRenderPriorityList(payload, roomLabelById);
    missionRenderApprovals(payload);
    missionRenderRooms(payload, roomLabelById);
    missionRenderTimeline(payload);
}

function missionHandleStreamLine(lineRaw) {
    const state = missionEnsureState();
    if (!state) return;
    const line = safeString(lineRaw);
    if (!line) return;
    let parsed = null;
    try {
        parsed = JSON.parse(line);
    } catch {
        return;
    }
    if (!parsed || typeof parsed !== 'object') return;
    if (safeString(parsed.type).toLowerCase() !== 'snapshot' || !parsed.payload || typeof parsed.payload !== 'object') {
        return;
    }
    state.lastPayload = parsed.payload;
    state.lastFetchedAt = Date.now();
    if (state.active) {
        missionRender(parsed.payload, state.lastJobsPayload);
        missionSetConnectionState('ok', 'Live');
    }
    if (taskContinuityLatestSessionId) {
        taskContinuityMissionPayload = parsed.payload;
        taskContinuityLatestActivity = missionBuildRuntimeState(parsed.payload, taskContinuityMissionJobs, {
            sessionId: taskContinuityLatestSessionId,
        });
        if (taskContinuityShouldBeVisible()) {
            renderTaskContinuity(taskContinuityLatestState, taskContinuityLatestEvents, taskContinuityLatestSessionId, {
                activity: taskContinuityLatestActivity,
            });
        }
    }
}

function missionScheduleStreamReconnect(delayMs = 0) {
    const state = missionEnsureState();
    if (!state?.stream || !state.active) return;
    const stream = state.stream;
    if (stream.reconnectTimer) return;
    const retryMs = delayMs > 0
        ? delayMs
        : Math.min(MISSION_STREAM_RETRY_MAX_MS, Math.max(MISSION_STREAM_RETRY_MIN_MS, Number(stream.retryMs) || MISSION_STREAM_RETRY_MIN_MS));
    stream.retryMs = Math.min(MISSION_STREAM_RETRY_MAX_MS, Math.round(retryMs * 1.75));
    stream.reconnectTimer = window.setTimeout(() => {
        const latest = missionEnsureState();
        if (!latest?.stream) return;
        latest.stream.reconnectTimer = 0;
        void missionStartStream();
    }, retryMs);
}

function missionStopStream() {
    const state = missionEnsureState();
    if (!state?.stream) return;
    const stream = state.stream;
    if (stream.reconnectTimer) {
        window.clearTimeout(stream.reconnectTimer);
        stream.reconnectTimer = 0;
    }
    if (stream.controller) {
        try {
            stream.controller.abort();
        } catch {
            // Ignore abort failures.
        }
    }
    stream.connected = false;
    stream.connecting = false;
    stream.controller = null;
}

async function missionStartStream() {
    const state = missionEnsureState();
    if (!state?.stream || !state.active) return;
    const stream = state.stream;
    if (stream.connecting || stream.connected) return;
    if (typeof fetch !== 'function' || typeof TextDecoder === 'undefined') return;

    stream.connecting = true;
    missionSetConnectionState('neutral', 'Linking');
    const controller = new AbortController();
    stream.controller = controller;

    try {
        const response = await fetch(MISSION_STREAM_URL, {
            method: 'GET',
            headers: {
                Accept: 'application/x-ndjson',
            },
            signal: controller.signal,
            cache: 'no-store',
        });
        if (!response.ok || !response.body) {
            throw new Error(`mission_stream_http_${response.status}`);
        }

        stream.connected = true;
        stream.connecting = false;
        stream.retryMs = MISSION_STREAM_RETRY_MIN_MS;
        stream.lastMessageAt = Date.now();
        missionSetConnectionState('ok', 'Live');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (missionState && missionState.active && !controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            stream.lastMessageAt = Date.now();
            buffer += decoder.decode(value, { stream: true });
            let newlineIndex = buffer.indexOf('\n');
            while (newlineIndex >= 0) {
                const line = buffer.slice(0, newlineIndex).trim();
                buffer = buffer.slice(newlineIndex + 1);
                if (line) {
                    missionHandleStreamLine(line);
                }
                newlineIndex = buffer.indexOf('\n');
            }
        }
    } catch (error) {
        if (!controller.signal.aborted) {
            console.warn('Mission stream failed', error);
            missionSetConnectionState('warn', 'Polling');
        }
    } finally {
        const latest = missionEnsureState();
        if (!latest?.stream) return;
        stream.connected = false;
        stream.connecting = false;
        stream.controller = null;
        if (latest.active) {
            missionScheduleStreamReconnect();
        }
    }
}

function missionStopPolling() {
    if (!missionState || !missionState.pollTimerId) return;
    window.clearInterval(missionState.pollTimerId);
    missionState.pollTimerId = 0;
}
