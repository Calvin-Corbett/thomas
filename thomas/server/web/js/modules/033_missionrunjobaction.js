// Extracted from part-017.js
// From missionrunjobaction

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