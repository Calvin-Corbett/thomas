// Extracted from part-019.js
// From moduleensurehiddenbucket

            triageFilters: {},
            subnavFocus: {},
            workbenchMode: '',
            workbench: {},
            hidden: {},
            activity: {},
            refreshedAt: {},
            marketplace: {
                apps: [],
                modules: [],
                loading: false,
                error: '',
                search: '',
                lastRefreshedAt: 0,
                refreshPromise: null,
            },
        };
    }
    return moduleState;
}

function moduleEnsureHiddenBucket(mode, section) {
    const state = moduleEnsureRuntime();
    if (!state) return null;
    if (!state.hidden[mode]) {
        state.hidden[mode] = {
            queue: new Set(),
            health: new Set(),
            triage: new Set(),
        };
    }
    if (!state.hidden[mode][section]) {
        state.hidden[mode][section] = new Set();
    }