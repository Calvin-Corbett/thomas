// Extracted from part-010.js
// From renderdebugmodelspanel

}

function renderDebugModelsPanel() {
    const payload = debugLiveCache.models;
    if (!payload) {
        if (debugModelsDefault) debugModelsDefault.textContent = '-';
        if (debugModelsCount) debugModelsCount.textContent = '0';
        if (debugModelsHealthy) debugModelsHealthy.textContent = '0';
        debugRenderEmpty(debugModelHealthList, 'No model health data yet.');
        return;
    }

    const modelPayload = payload?.models || {};