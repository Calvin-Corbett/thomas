const CANVAS_RUNTIME_FILES = [
    './runtime/canvas_workspace_contract.js',
    './runtime/canvas_workspace_runtime.js',
    './runtime/048_ui_studio_canvas.js',
];

function rescueString(value) {
    if (value === null || value === undefined) return '';
    return typeof value === 'string' ? value : String(value);
}

function ensureRescueHelpers(workbenchState) {
    if (typeof window.notifyUser !== 'function') {
        window.notifyUser = function notifyUser(message) {
            const text = rescueString(message);
            const container = document.getElementById('toastContainer');
            if (!(container instanceof HTMLElement)) {
                console.log('[Thomas rescue]', text);
                return;
            }
            const toast = document.createElement('div');
            toast.className = 'toast toast-info'; toast.textContent = text;
            container.appendChild(toast);
            window.setTimeout(() => toast.remove(), 2200);
        };
    }
    if (typeof window.fetchJsonSafe !== 'function') {
        window.fetchJsonSafe = async function fetchJsonSafe(url, options = {}) {
            try {
                const response = await fetch(url, options);
                const text = await response.text();
                let data = null;
                try { data = text ? JSON.parse(text) : null; } catch (_error) { data = null; }
                return { ok: response.ok, status: response.status, text, data };
            } catch (error) {
                return { ok: false, status: 0, text: rescueString(error && error.message), data: null };
            }
        };
    }
    if (typeof window.moduleWorkbenchTeardown !== 'function') {
        window.moduleWorkbenchTeardown = function moduleWorkbenchTeardown() {};
    }
    window.moduleEnsureRuntime = function moduleEnsureRuntime() {
        return { workbench: { app_builder: workbenchState } };
    };
}

function loadClassicScript(relativePath) {
    return new Promise((resolve, reject) => {
        const src = new URL(relativePath, import.meta.url).href;
        const existing = document.querySelector(`script[data-canvas-rescue-src="${src}"]`);
        if (existing && existing.dataset.loaded === 'true') {
            resolve();
            return;
        }
        const script = existing || document.createElement('script');
        script.src = src; script.async = false; script.dataset.canvasRescueSrc = src;
        script.addEventListener('load', () => { script.dataset.loaded = 'true'; resolve(); }, { once: true });
        script.addEventListener('error', () => reject(new Error('Unable to load Canvas rescue runtime: ' + relativePath)), { once: true });
        if (!existing) document.head.appendChild(script);
    });
}

async function loadCanvasRuntime() {
    if (window.ThomasCanvasWorkspaceContract && window.ThomasCanvasWorkspaceRuntime
        && window.UI_STUDIO && typeof window.moduleRenderWorkbenchAppBuilder === 'function') return;
    for (const file of CANVAS_RUNTIME_FILES) {
        await loadClassicScript(file);
    }
    if (!window.UI_STUDIO || typeof window.moduleRenderWorkbenchAppBuilder !== 'function') {
        throw new Error('Canvas rescue runtime did not register its authoritative renderer.');
    }
}

function setHidden(id, hidden) {
    const node = document.getElementById(id);
    if (node) node.classList.toggle('hidden', hidden);
}

function setNavActive(activeId) {
    document.querySelectorAll('.sidebar-nav .nav-item').forEach((button) => {
        if (button instanceof HTMLElement) button.classList.toggle('active', button.id === activeId);
    });
}

function prepareRescueWorkspace() {
    setHidden('welcomeScreen', true);
    setHidden('chatScrollArea', true);
    setHidden('chatGamePanel', true);
    setHidden('settingsModal', true);
    setHidden('moduleWorkspace', false);
    setHidden('moduleWorkbench', false);
    const title = document.getElementById('moduleWorkspaceTitle');
    const subtitle = document.getElementById('moduleWorkspaceSubtitle');
    const pill = document.getElementById('moduleWorkspaceModePill');
    const meta = document.getElementById('moduleWorkspaceMeta');
    if (title) title.textContent = 'Canvas';
    if (subtitle) subtitle.textContent = 'Design interfaces, inspect layers, and export real code.';
    if (pill) pill.textContent = 'Rescue';
    if (meta) meta.textContent = 'Main app runtime is offline. Canvas mounted through its current runtime.';
    ['moduleKpiGrid', 'moduleSubnavRow', 'moduleFlairRow', 'moduleFocusStrip', 'moduleSpecialGrid'].forEach((id) => setHidden(id, true));
    ['moduleQueuePanel', 'moduleHealthPanel', 'moduleActionsPanel', 'moduleActivityPanel', 'moduleTriagePanel'].forEach((id) => {
        const panel = document.getElementById(id);
        if (panel) panel.classList.add('hidden');
    });
    setNavActive('navUiEditorBtn');
}

export async function startCanvasRescueMode() {
    const navButton = document.getElementById('navUiEditorBtn');
    const workbench = document.getElementById('moduleWorkbench');
    if (!(workbench instanceof HTMLElement)) throw new Error('Canvas rescue mount point not found.');
    const state = window.__thomasCanvasRescueWorkbench && typeof window.__thomasCanvasRescueWorkbench === 'object'
        ? window.__thomasCanvasRescueWorkbench : { mounted: false };
    window.__thomasCanvasRescueWorkbench = state;
    ensureRescueHelpers(state);
    await loadCanvasRuntime();
    const mount = () => {
        prepareRescueWorkspace();
        window.moduleRenderWorkbenchAppBuilder(workbench, state);
    };
    if (navButton instanceof HTMLElement && navButton.dataset.canvasRescueBound !== 'true') {
        navButton.dataset.canvasRescueBound = 'true';
        navButton.addEventListener('click', (event) => { event.preventDefault(); mount(); });
    }
    mount();
    window.notifyUser('Canvas rescue mode is active.', { tone: 'info', durationMs: 1800, debugKind: 'app-builder' });
}

export const startUiEditorRescueMode = startCanvasRescueMode;
