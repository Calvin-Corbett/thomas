const UI_EDITOR_PART_FILES = [
    './modules/063_module_studio_comfy_style_id_part01.js',
    './modules/063_module_studio_comfy_style_id_part02.js',
    './modules/063_module_studio_comfy_style_id_part03.js',
];

function rescueSafeString(valueRaw) {
    if (valueRaw === null || valueRaw === undefined) return '';
    if (typeof valueRaw === 'string') return valueRaw;
    if (typeof valueRaw === 'number' || typeof valueRaw === 'boolean') return String(valueRaw);
    return '';
}

function rescueEscapeHtml(valueRaw) {
    return rescueSafeString(valueRaw)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function ensureRescueHelpers(workbenchState) {
    if (typeof window.safeString !== 'function') {
        window.safeString = rescueSafeString;
    }
    if (typeof window.escapeHtml !== 'function') {
        window.escapeHtml = rescueEscapeHtml;
    }
    if (typeof window.moduleWorkbenchMakeId !== 'function') {
        window.moduleWorkbenchMakeId = function moduleWorkbenchMakeId(prefixRaw = 'ui') {
            const prefix = rescueSafeString(prefixRaw) || 'ui';
            return prefix + '-' + String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
        };
    }
    if (typeof window.moduleWorkbenchCopyJson !== 'function') {
        window.moduleWorkbenchCopyJson = function moduleWorkbenchCopyJson(payload) {
            const json = JSON.stringify(payload, null, 2);
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                void navigator.clipboard.writeText(json).catch(() => {});
            } else {
                console.log(json);
            }
        };
    }
    if (typeof window.notifyUser !== 'function') {
        window.notifyUser = function notifyUser(messageRaw) {
            const text = rescueSafeString(messageRaw);
            const container = document.getElementById('toastContainer');
            if (!(container instanceof HTMLElement)) {
                console.log('[Thomas rescue]', text);
                return;
            }
            const toast = document.createElement('div');
            toast.className = 'toast toast-info';
            toast.textContent = text;
            container.appendChild(toast);
            window.setTimeout(() => {
                toast.remove();
            }, 2200);
        };
    }
    if (typeof window.fetchJsonSafe !== 'function') {
        window.fetchJsonSafe = async function fetchJsonSafe(url, options = {}) {
            try {
                const response = await fetch(url, options);
                const text = await response.text();
                let data = null;
                try {
                    data = text ? JSON.parse(text) : null;
                } catch (_error) {
                    data = null;
                }
                return { ok: response.ok, status: response.status, text, data };
            } catch (error) {
                return { ok: false, status: 0, text: rescueSafeString(error && error.message), data: null };
            }
        };
    }
    if (typeof window.moduleWorkbenchPushLog !== 'function') {
        window.moduleWorkbenchPushLog = function moduleWorkbenchPushLog() {};
    }
    if (typeof window.moduleWorkbenchRefreshMode !== 'function') {
        window.moduleWorkbenchRefreshMode = function moduleWorkbenchRefreshMode() {};
    }
    if (typeof window.moduleRenderWorkbenchStudioOss !== 'function') {
        window.moduleRenderWorkbenchStudioOss = function moduleRenderWorkbenchStudioOss() {
            return false;
        };
    }
    if (typeof window.moduleWorkbenchTeardown !== 'function') {
        window.moduleWorkbenchTeardown = function moduleWorkbenchTeardown() {};
    }
    window.moduleEnsureRuntime = function moduleEnsureRuntime() {
        return {
            workbench: {
                app_builder: workbenchState,
            },
        };
    };
    if (!Array.isArray(window.availableModelProfiles)) {
        window.availableModelProfiles = [];
    }
    if (!(window.composerTextarea instanceof HTMLTextAreaElement)) {
        window.composerTextarea = document.getElementById('composerTextarea');
    }
    if (typeof window.handleSend !== 'function') {
        window.handleSend = function handleSend() {};
    }
}

async function loadUiEditorMonolith() {
    if (typeof window.moduleRenderWorkbenchAppBuilder === 'function') return;
    const chunks = await Promise.all(
        UI_EDITOR_PART_FILES.map(async (part) => {
            const response = await fetch(new URL(part, import.meta.url).href);
            if (!response.ok) {
                throw new Error('Unable to load UI editor rescue module: ' + part);
            }
            return response.text();
        }),
    );
    const preamble = [
        'var safeString = window.safeString;',
        'var escapeHtml = window.escapeHtml;',
        'var moduleWorkbenchMakeId = window.moduleWorkbenchMakeId;',
        'var moduleWorkbenchCopyJson = window.moduleWorkbenchCopyJson;',
        'var notifyUser = window.notifyUser;',
        'var fetchJsonSafe = window.fetchJsonSafe;',
        'var moduleWorkbenchPushLog = window.moduleWorkbenchPushLog;',
        'var moduleWorkbenchRefreshMode = window.moduleWorkbenchRefreshMode;',
        'var moduleRenderWorkbenchStudioOss = window.moduleRenderWorkbenchStudioOss;',
        'var moduleWorkbenchTeardown = window.moduleWorkbenchTeardown;',
        'var moduleEnsureRuntime = window.moduleEnsureRuntime;',
        'var availableModelProfiles = window.availableModelProfiles;',
        'var composerTextarea = window.composerTextarea;',
        'var handleSend = window.handleSend;',
    ].join('\n');
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.textContent = preamble + '\n' + chunks.join('\n');
    document.head.appendChild(script);
    script.remove();
    if (typeof window.moduleRenderWorkbenchAppBuilder !== 'function') {
        throw new Error('UI editor rescue module did not register moduleRenderWorkbenchAppBuilder.');
    }
}

function setHidden(id, hidden) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', hidden);
}

function setNavActive(activeId) {
    document.querySelectorAll('.sidebar-nav .nav-item').forEach((button) => {
        if (!(button instanceof HTMLElement)) return;
        button.classList.toggle('active', button.id === activeId);
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
    if (title) title.textContent = 'UI Editor';
    if (subtitle) subtitle.textContent = 'Rescue mode keeps the editor available while the main browser runtime is offline.';
    if (pill) pill.textContent = 'Rescue';
    if (meta) meta.textContent = 'Main app runtime failed to boot. UI editor mounted directly.';

    ['moduleKpiGrid', 'moduleSubnavRow', 'moduleFlairRow', 'moduleFocusStrip', 'moduleSpecialGrid'].forEach((id) => {
        setHidden(id, true);
    });
    ['moduleQueuePanel', 'moduleHealthPanel', 'moduleActionsPanel', 'moduleActivityPanel', 'moduleTriagePanel'].forEach((id) => {
        const panel = document.getElementById(id);
        if (panel) panel.classList.add('hidden');
    });
    setNavActive('navUiEditorBtn');
}

export async function startUiEditorRescueMode() {
    const navBtn = document.getElementById('navUiEditorBtn');
    const workbench = document.getElementById('moduleWorkbench');
    if (!(workbench instanceof HTMLElement)) {
        throw new Error('UI editor rescue mount point not found.');
    }

    const workbenchState = window.__thomasUiEditorRescueWorkbench && typeof window.__thomasUiEditorRescueWorkbench === 'object'
        ? window.__thomasUiEditorRescueWorkbench
        : { mounted: false };
    window.__thomasUiEditorRescueWorkbench = workbenchState;

    ensureRescueHelpers(workbenchState);
    await loadUiEditorMonolith();

    const mount = () => {
        prepareRescueWorkspace();
        workbench.innerHTML = '';
        window.moduleRenderWorkbenchAppBuilder(workbench, workbenchState);
    };

    if (navBtn instanceof HTMLElement) {
        navBtn.addEventListener('click', (event) => {
            event.preventDefault();
            mount();
        });
    }

    mount();
    window.notifyUser('UI Editor rescue mode is active.', { tone: 'info', durationMs: 1800, debugKind: 'app-builder' });
}
