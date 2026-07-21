/** Shared server state bridge for the live Virtual Office viewport. */

let officeServerState = null;
let officeServerStateHydrated = false;
let officeServerStateApplying = false;
let officeServerStateRequest = null;

async function officeHydrateServerState(options = {}) {
    if (officeServerStateRequest && options.force !== true) return officeServerStateRequest;
    officeServerStateRequest = (async () => {
        try {
            const response = await fetch('/api/office/state', { cache: 'no-store' });
            if (!response.ok) return null;
            const payload = await response.json();
            const state = payload?.state && typeof payload.state === 'object' ? payload.state : null;
            if (!state) return null;
            officeServerState = state;
            officeServerStateHydrated = true;
            if (officeState && typeof officeSetFollowMode === 'function') {
                officeServerStateApplying = true;
                const agentId = safeString(state.follow_agent_id);
                officeSetFollowMode(Boolean(agentId), agentId);
                officeServerStateApplying = false;
                officePersistCameraState(performance.now() + 1000);
                officeRenderScene();
            }
            return state;
        } catch {
            return null;
        } finally {
            officeServerStateRequest = null;
        }
    })();
    return officeServerStateRequest;
}

async function officePersistServerFollowAgent(agentIdRaw) {
    if (!officeServerStateHydrated || officeServerStateApplying) return null;
    const followAgentId = safeString(agentIdRaw);
    try {
        const response = await fetch('/api/office/state', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ follow_agent_id: followAgentId }),
        });
        if (!response.ok) return null;
        const payload = await response.json();
        officeServerState = payload?.state || officeServerState;
        return officeServerState;
    } catch {
        return null;
    }
}

window.addEventListener('thomas:office-state:refresh', () => {
    void officeHydrateServerState({ force: true });
});
window.addEventListener('message', (event) => {
    if (event.origin !== location.origin || !event.data) return;
    if (event.data.type !== 'thomas:office-state:refresh') return;
    void officeHydrateServerState({ force: true });
});

void officeHydrateServerState();
