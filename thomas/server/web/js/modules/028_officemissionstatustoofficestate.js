// Extracted from part-014b.js
// From officemissionstatustoofficestate

function officeMissionStatusToOfficeState(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'active' || status === 'running' || status === 'in_progress') return 'working';
    if (status === 'idle' || status === 'waiting') return 'idle';
    if (status === 'blocked' || status === 'paused') return 'yield';
    if (status === 'break') return 'break';
    return '';
}

function officeReconcileFromMissionPayload(payload, now = performance.now()) {
    if (!officeState || !payload || typeof payload !== 'object') return false;
    let changed = false;
