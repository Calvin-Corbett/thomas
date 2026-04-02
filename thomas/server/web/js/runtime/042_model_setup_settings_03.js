async function moduleUiEditorProjectFromFiles(filesRaw) {
    const files = Array.isArray(filesRaw) ? filesRaw : [];
    if (!files.length) return { ok: false, reason: 'No files selected.' };

    const fileMap = new Map();
    let rootName = 'Imported Project';
    files.forEach((file) => {
        const relative = safeString(file && file.webkitRelativePath) || safeString(file && file.name);
        if (!relative) return;
        const parts = relative.replace(/\\/g, '/').split('/').filter(Boolean);
        if (parts.length > 1 && rootName === 'Imported Project') {
            rootName = safeString(parts[0]) || rootName;
        }
        const key = moduleUiEditorNormalizePath(parts.length > 1 ? parts.slice(1).join('/') : parts[0]);
        if (!key) return;
        fileMap.set(key, file);
    });

    const htmlKeys = Array.from(fileMap.keys()).filter((key) => /\.html?$/i.test(key));
    if (!htmlKeys.length) return { ok: false, reason: 'No HTML file found in selected folder.' };

    const preferred = htmlKeys.find((key) => key === 'index.html')
        || htmlKeys.find((key) => key.endsWith('/index.html'))
        || htmlKeys[0];
    const entryFile = fileMap.get(preferred);
    if (!entryFile) return { ok: false, reason: 'Could not read entry HTML file.' };

    const htmlText = await entryFile.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(htmlText, 'text/html');
    const baseDir = preferred.includes('/') ? preferred.slice(0, preferred.lastIndexOf('/')) : '';
    const blobMap = new Map();

    const ensureBlobUrl = (pathRaw) => {
        const normalized = moduleUiEditorNormalizePath(pathRaw);
        if (!normalized || !fileMap.has(normalized)) return '';
        if (blobMap.has(normalized)) return blobMap.get(normalized);
        const url = URL.createObjectURL(fileMap.get(normalized));
        blobMap.set(normalized, url);
        return url;
    };

    const rewriteAttr = (selector, attr) => {
        doc.querySelectorAll(selector).forEach((node) => {
            if (!(node instanceof Element)) return;
            const raw = safeString(node.getAttribute(attr));
            if (!raw) return;
            if (/^(https?:|data:|blob:|javascript:|mailto:|tel:|#)/i.test(raw)) return;
            const resolved = raw.startsWith('/')
                ? moduleUiEditorNormalizePath(raw.slice(1))
                : moduleUiEditorResolvePath(baseDir, raw);
            if (!resolved) return;
            const blobUrl = ensureBlobUrl(resolved);
            if (!blobUrl) return;
            node.setAttribute(attr, blobUrl);
        });
    };

    rewriteAttr('[src]', 'src');
    rewriteAttr('link[href]', 'href');
    rewriteAttr('a[href]', 'href');

    const serialized = '<!doctype html>\n' + (doc.documentElement ? doc.documentElement.outerHTML : htmlText);
    return {
        ok: true,
        project: {
            id: moduleWorkbenchMakeId('ui-project'),
            name: safeString(rootName) || 'Imported Project',
            type: 'srcdoc',
            srcdoc: serialized,
            overrides: {},
            blobUrls: Array.from(blobMap.values()),
            updatedAt: Date.now(),
        },
    };
}

const moduleWorkbenchTeardownOriginalForUiEditor = moduleWorkbenchTeardown;
moduleWorkbenchTeardown = function moduleWorkbenchTeardownWithUiEditor(mode) {
    if (safeString(mode) === 'app_builder') {
        const state = moduleEnsureRuntime();
        const wb = state && state.workbench && state.workbench.app_builder ? state.workbench.app_builder : null;
        if (wb) moduleUiEditorClearRuntime(wb);
    }
    return moduleWorkbenchTeardownOriginalForUiEditor(mode);
};

moduleRenderWorkbenchAppBuilder = function moduleRenderWorkbenchAppBuilderUiEditor(container, wb) {
    if (!container || !wb) return;
    moduleUiEditorEnsureStyles();
    moduleUiEditorEnsureState(wb);
    moduleUiEditorClearRuntime(wb);

    const shell = document.createElement('section');
    shell.className = 'module-ui-editor-shell';

    const top = document.createElement('header');
    top.className = 'module-ui-editor-top';
    const topLeft = document.createElement('div');
    topLeft.className = 'module-ui-editor-left';
    const title = document.createElement('strong');
    title.className = 'module-ui-editor-title';
    title.textContent = 'UI Editor';
    const sub = document.createElement('span');
    sub.className = 'module-ui-editor-sub';
    sub.textContent = 'Live canvas view with lock-and-edit mode for the current screen.';
    topLeft.appendChild(title);
    topLeft.appendChild(sub);
    const topRight = document.createElement('div');
    topRight.className = 'module-ui-editor-right';
    const viewportMeta = document.createElement('span');
    viewportMeta.className = 'module-ui-editor-viewport-meta';
    const viewportBtn = document.createElement('button');
    viewportBtn.type = 'button';
    viewportBtn.className = 'module-ui-editor-btn';
    const count = document.createElement('span');
    count.className = 'module-ui-editor-count';
    count.textContent = '0 elements';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'module-ui-editor-btn';
    saveBtn.textContent = 'Save Layout';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'module-ui-editor-btn';
    topRight.appendChild(viewportMeta);
    topRight.appendChild(viewportBtn);
    topRight.appendChild(count);
    topRight.appendChild(saveBtn);
    topRight.appendChild(editBtn);
    top.appendChild(topLeft);
    top.appendChild(topRight);

    const canvas = document.createElement('section');
    canvas.className = 'module-ui-editor-canvas';
    const viewport = document.createElement('div');
    viewport.className = 'module-ui-editor-viewport';
    const frame = document.createElement('iframe');
    frame.className = 'module-ui-editor-frame';
    frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-modals');
    frame.setAttribute('title', 'UI Editor Canvas');
    const hint = document.createElement('div');
    hint.className = 'module-ui-editor-hint';
    hint.textContent = 'View mode';
    viewport.appendChild(frame);
    viewport.appendChild(hint);
    canvas.appendChild(viewport);

    const bottom = document.createElement('footer');
    bottom.className = 'module-ui-editor-bottom';
    const bottomLeft = document.createElement('div');
    bottomLeft.className = 'module-ui-editor-left';
    const projectLabel = document.createElement('span');
    projectLabel.className = 'module-ui-editor-count';
    projectLabel.textContent = 'Project';
    const projectSelect = document.createElement('select');
    bottomLeft.appendChild(projectLabel);
    bottomLeft.appendChild(projectSelect);
    const bottomRight = document.createElement('div');
    bottomRight.className = 'module-ui-editor-right';
    const addFolderBtn = document.createElement('button');
    addFolderBtn.type = 'button';
    addFolderBtn.className = 'module-ui-editor-btn';
    addFolderBtn.textContent = 'Add Project Folder';
    const reloadBtn = document.createElement('button');
    reloadBtn.type = 'button';
    reloadBtn.className = 'module-ui-editor-btn';
    reloadBtn.textContent = 'Reload';
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'module-ui-editor-btn';
    removeBtn.textContent = 'Remove';
    const folderInput = document.createElement('input');
    folderInput.type = 'file';
    folderInput.className = 'hidden';
    folderInput.multiple = true;
    folderInput.setAttribute('webkitdirectory', '');
    folderInput.setAttribute('directory', '');
    bottomRight.appendChild(addFolderBtn);
    bottomRight.appendChild(reloadBtn);
    bottomRight.appendChild(removeBtn);
    bottomRight.appendChild(folderInput);
    bottom.appendChild(bottomLeft);
    bottom.appendChild(bottomRight);

    shell.appendChild(top);
    shell.appendChild(canvas);
    shell.appendChild(bottom);
    container.appendChild(shell);

    const currentProject = () => moduleUiEditorProjectById(wb, wb.uiSelectedProjectId);

    const captureViewportSize = () => {
        if (!wb.uiViewport || wb.uiViewport.fit) return;
        const rect = viewport.getBoundingClientRect();
        const width = moduleUiEditorClamp(
            Math.round(rect.width),
            MODULE_UI_EDITOR_VIEWPORT_MIN_WIDTH,
            MODULE_UI_EDITOR_VIEWPORT_MAX_WIDTH,
        );
        const height = moduleUiEditorClamp(
            Math.round(rect.height),
            MODULE_UI_EDITOR_VIEWPORT_MIN_HEIGHT,
            MODULE_UI_EDITOR_VIEWPORT_MAX_HEIGHT,
        );
        wb.uiViewport.width = width;
        wb.uiViewport.height = height;
    };

    const updateViewportUi = () => {
        const fit = wb.uiViewport.fit !== false;
        wb.uiViewport.fit = fit;
        if (fit) {
            viewport.classList.remove('is-free');
            viewport.style.width = '100%';
            viewport.style.height = '100%';
            viewportMeta.textContent = 'Viewport: fit canvas';
            viewportBtn.textContent = 'Free Resize';
        } else {
            wb.uiViewport.width = moduleUiEditorClamp(
                Number(wb.uiViewport.width) || 1366,
                MODULE_UI_EDITOR_VIEWPORT_MIN_WIDTH,
                MODULE_UI_EDITOR_VIEWPORT_MAX_WIDTH,
            );
            wb.uiViewport.height = moduleUiEditorClamp(
                Number(wb.uiViewport.height) || 860,
                MODULE_UI_EDITOR_VIEWPORT_MIN_HEIGHT,
                MODULE_UI_EDITOR_VIEWPORT_MAX_HEIGHT,
            );
            viewport.classList.add('is-free');
            viewport.style.width = String(wb.uiViewport.width) + 'px';
            viewport.style.height = String(wb.uiViewport.height) + 'px';
            viewportMeta.textContent = 'Viewport: ' + String(wb.uiViewport.width) + 'x' + String(wb.uiViewport.height);
            viewportBtn.textContent = 'Fit Canvas';
        }
    };
    const viewportObserver = typeof ResizeObserver === 'function'
        ? new ResizeObserver(() => {
            if (!wb.uiViewport || wb.uiViewport.fit) return;
            captureViewportSize();
            viewportMeta.textContent = 'Viewport: ' + String(wb.uiViewport.width) + 'x' + String(wb.uiViewport.height);
        })
        : null;
    if (viewportObserver) viewportObserver.observe(viewport);
    wb.uiRuntime.previewCleanup = () => {
        if (viewportObserver) viewportObserver.disconnect();
    };

    const renderProjectOptions = () => {
        projectSelect.innerHTML = '';
        wb.uiProjects.forEach((project) => {
            const option = document.createElement('option');
            option.value = safeString(project && project.id);
            const type = safeString(project && project.type);
            const typeLabel = safeString(project && project.id) === 'ui-project-thomas'
                ? 'live thomas'
                : (type === 'url' ? 'live' : 'imported');
            option.textContent = safeString(project && project.name) + ' (' + typeLabel + ')';
            projectSelect.appendChild(option);
        });
        if (wb.uiSelectedProjectId) projectSelect.value = wb.uiSelectedProjectId;
    };

    const updateEditUi = () => {
        editBtn.textContent = wb.uiEditMode ? 'Done' : 'Edit';
        editBtn.classList.toggle('edit-active', wb.uiEditMode);
        if (wb.uiEditMode) {
            hint.textContent = 'Edit mode active';
            return;
        }
        hint.textContent = wb.uiViewport && wb.uiViewport.fit === false ? 'View mode (resizable)' : 'View mode (fit)';
    };

    const frameSandboxValue = (project) => {
        const type = safeString(project && project.type).toLowerCase();
        const id = safeString(project && project.id);
        const rawUrl = safeString(project && project.url);
        const trustedProject = id === 'ui-project-thomas'
            || type === 'imported'
            || rawUrl === '/'
            || rawUrl.startsWith('/');
        if (trustedProject) {
            return '';
        }
        return 'allow-scripts allow-forms allow-popups allow-modals';
    };

    const applyFrameSandbox = (project) => {
        const sandbox = frameSandboxValue(project);
        if (sandbox) {
            frame.setAttribute('sandbox', sandbox);
            return;
        }
        frame.removeAttribute('sandbox');
    };

    const refreshExtraction = () => {
        const project = currentProject();
        let doc = null;
        try {
            doc = frame.contentDocument;
        } catch (_error) {
            doc = null;
        }
        if (!doc || !doc.body) {
            wb.uiRuntime.elements = [];
            count.textContent = '0 elements';
            if (project) wb.uiRuntime.lastScreenUrl = '';
            return;
        }
        wb.uiRuntime.elements = moduleUiEditorExtractElements(doc);
        count.textContent = String(wb.uiRuntime.elements.length) + ' elements';
        try {
            wb.uiRuntime.lastScreenUrl = safeString(frame.contentWindow && frame.contentWindow.location && frame.contentWindow.location.href);
        } catch (_error) {
            wb.uiRuntime.lastScreenUrl = '';
        }
    };

    const loadProject = (forceReload = false) => {
        const project = currentProject();
        moduleUiEditorClearEditRuntime(wb);
        applyFrameSandbox(project);
        if (!project) {
            frame.srcdoc = '<html><body style="font-family:system-ui;padding:24px;background:#0f1723;color:#eaf2ff;">No project selected.</body></html>';
            count.textContent = '0 elements';
            return;
        }
        if (safeString(project.id) === 'ui-project-thomas') {
            project.url = moduleUiEditorThomasPreviewUrl();
        }
        if (safeString(project.type) === 'url') {
            frame.removeAttribute('srcdoc');
            if (forceReload) {
                try {
                    if (frame.contentWindow) {
                        frame.contentWindow.location.reload();
                        return;
                    }
                } catch (_error) {}
                const base = safeString(project.url) || '/';
                frame.src = base + (base.includes('?') ? '&' : '?') + 'ui_editor_reload=' + String(Date.now());
                return;
            }
            frame.src = safeString(project.url) || '/';
            return;
        }
        frame.src = 'about:blank';
        frame.srcdoc = safeString(project.srcdoc);
    };

    const saveLayout = () => {
        const project = currentProject();
        if (!project) return;
        refreshExtraction();
        const payload = {
            project: {
                id: safeString(project.id),
                name: safeString(project.name),
                type: safeString(project.type),
                url: safeString(project.url),
            },
            screen_url: safeString(wb.uiRuntime.lastScreenUrl),
            edit_mode: Boolean(wb.uiEditMode),
            viewport: {
                fit_canvas: wb.uiViewport ? wb.uiViewport.fit !== false : true,
                width: wb.uiViewport ? Number(wb.uiViewport.width) || 0 : 0,
                height: wb.uiViewport ? Number(wb.uiViewport.height) || 0 : 0,
            },
            extracted_elements: Array.isArray(wb.uiRuntime.elements) ? wb.uiRuntime.elements : [],
            position_overrides: project && typeof project.overrides === 'object' ? project.overrides : {},
        };
        moduleWorkbenchCopyJson(payload, 'UI Editor Layout Data');
        notifyUser('Layout data copied.', { tone: 'success', durationMs: 1800, debugKind: 'app-builder' });
        moduleUiEditorPersistUrlProjects(wb);
    };

    frame.addEventListener('load', () => {
        const project = currentProject();
        if (!project) {
            count.textContent = '0 elements';
            return;
        }
        let doc = null;
        try {
            doc = frame.contentDocument;
        } catch (_error) {
            doc = null;
        }
        if (!doc || !doc.body) {
            hint.textContent = 'View only (cross-origin)';
            wb.uiRuntime.elements = [];
            count.textContent = '0 elements';
            if (wb.uiEditMode) {
                wb.uiEditMode = false;
                updateEditUi();
            }
            return;
        }
        moduleUiEditorApplyOverrides(doc, project);
        refreshExtraction();
        if (wb.uiEditMode) {
            const attached = moduleUiEditorAttachEditMode(frame, wb, project, () => {
                refreshExtraction();
                moduleUiEditorPersistUrlProjects(wb);
            });
            if (!attached) {
                wb.uiEditMode = false;
                updateEditUi();
                notifyUser('Edit mode requires same-origin content.', { tone: 'warn', durationMs: 2200, debugKind: 'app-builder' });
            }
        }
    });

    projectSelect.addEventListener('change', () => {
        wb.uiSelectedProjectId = safeString(projectSelect.value);
        wb.uiEditMode = false;
        updateEditUi();
        loadProject(false);
    });

    editBtn.addEventListener('click', () => {
        wb.uiEditMode = !wb.uiEditMode;
        updateEditUi();
        loadProject(true);
        moduleUiEditorPersistUrlProjects(wb);
    });

    viewportBtn.addEventListener('click', () => {
        wb.uiViewport.fit = wb.uiViewport.fit === false;
        if (wb.uiViewport.fit === false) {
            const rect = viewport.getBoundingClientRect();
            wb.uiViewport.width = moduleUiEditorClamp(
                Math.round(rect.width),
                MODULE_UI_EDITOR_VIEWPORT_MIN_WIDTH,
                MODULE_UI_EDITOR_VIEWPORT_MAX_WIDTH,
            );
            wb.uiViewport.height = moduleUiEditorClamp(
                Math.round(rect.height),
                MODULE_UI_EDITOR_VIEWPORT_MIN_HEIGHT,
                MODULE_UI_EDITOR_VIEWPORT_MAX_HEIGHT,
            );
        }
        updateViewportUi();
        updateEditUi();
    });

    viewport.addEventListener('mouseup', () => {
        if (!wb.uiViewport || wb.uiViewport.fit) return;
        window.requestAnimationFrame(() => {
            captureViewportSize();
            updateViewportUi();
            updateEditUi();
        });
    });

    saveBtn.addEventListener('click', () => {
        saveLayout();
    });

    reloadBtn.addEventListener('click', () => {
        wb.uiEditMode = false;
        updateEditUi();
        loadProject(true);
    });

    addFolderBtn.addEventListener('click', () => {
        folderInput.click();
    });

    folderInput.addEventListener('change', async () => {
        const files = Array.from(folderInput.files || []);
        folderInput.value = '';
        if (!files.length) return;
        try {
            const result = await moduleUiEditorProjectFromFiles(files);
            if (!result.ok || !result.project) {
                notifyUser(result.reason || 'Could not import selected folder.', { tone: 'warn', durationMs: 2500, debugKind: 'app-builder' });
                return;
            }
            wb.uiProjects.unshift(result.project);
            wb.uiSelectedProjectId = safeString(result.project.id);
            wb.uiEditMode = false;
            renderProjectOptions();
            updateEditUi();
            loadProject(false);
            notifyUser('Imported project: ' + safeString(result.project.name), { tone: 'success', durationMs: 2200, debugKind: 'app-builder' });
        } catch (error) {
            const reason = safeString(error && error.message) || 'Import failed.';
            notifyUser(reason, { tone: 'warn', durationMs: 2600, debugKind: 'app-builder' });
        }
    });

    removeBtn.addEventListener('click', () => {
        const project = currentProject();
        if (!project) return;
        if (safeString(project.id) === 'ui-project-thomas') {
            notifyUser('Thomas project is pinned.', { tone: 'info', durationMs: 1700, debugKind: 'app-builder' });
            return;
        }
        if (Array.isArray(project.blobUrls)) {
            project.blobUrls.forEach((url) => {
                try {
                    URL.revokeObjectURL(safeString(url));
                } catch (_error) {}
            });
        }
        wb.uiProjects = wb.uiProjects.filter((row) => safeString(row && row.id) !== safeString(project.id));
        wb.uiSelectedProjectId = safeString(wb.uiProjects[0] && wb.uiProjects[0].id);
        wb.uiEditMode = false;
        moduleUiEditorPersistUrlProjects(wb);
        renderProjectOptions();
        updateEditUi();
        loadProject(false);
        notifyUser('Project removed.', { tone: 'warn', durationMs: 1700, debugKind: 'app-builder' });
    });

    renderProjectOptions();
    updateViewportUi();
    updateEditUi();
    loadProject(false);
};

// ---- Thomas post-restore UI editor patch ----
// (block scope removed for split compliance — originally from part-033.js)


// [duplicate removed] const MODULE_STUDIO_COMFY_STYLE_ID = 'moduleStudioComfyStyles';
const MODULE_UI_EDITOR_PLUGIN_BOOTSTRAP_ALLOWLIST = [
    'raw.githubusercontent.com',
];

function moduleUiEditorNormalizeShellPluginBootstrapSource(urlRaw) {
    const source = moduleUiEditorNormalizeGitHubRawUrl(urlRaw);
    if (!source) return { ok: false, reason: 'Missing plugin URL.' };
    if (!/^(https?):\/\//i.test(source)) {
        return { ok: false, reason: 'Plugin URL must use http or https.' };
    }
    try {
        const parsed = new URL(source);
        const host = safeString(parsed.hostname).toLowerCase();
        if (!MODULE_UI_EDITOR_PLUGIN_BOOTSTRAP_ALLOWLIST.includes(host)) {
            return { ok: false, reason: 'Plugin URL host is not allowlisted.' };
        }
        return { ok: true, source };
    } catch (_error) {
        return { ok: false, reason: 'Invalid plugin URL.' };
    }
}

function moduleStudioEnsureComfyStyles() {
    if (document.getElementById(MODULE_STUDIO_COMFY_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = MODULE_STUDIO_COMFY_STYLE_ID;
    style.textContent = [
        '.module-wb-shell-studio-oss,.module-wb-shell-studio{grid-template-columns:minmax(0,1fr)!important;}',
        '.module-wb-shell-studio-oss>.module-wb-side-card.module-wb-studio-library,.module-wb-shell-studio>.module-wb-side-card.module-wb-studio-library,.module-wb-shell-studio-oss>.module-wb-inspector-card.module-wb-studio-inspector,.module-wb-shell-studio>.module-wb-inspector-card.module-wb-studio-inspector{display:none!important;}',
        '.module-wb-shell-studio-oss .module-wb-stage-head,.module-wb-shell-studio .module-wb-stage-head{display:none!important;}',
        '.module-wb-shell-studio-oss [data-studio-wave],.module-wb-shell-studio [data-studio-wave],.module-wb-shell-studio-oss [data-studio-image-stage],.module-wb-shell-studio [data-studio-image-stage],.module-wb-shell-studio-oss [data-studio-playhead],.module-wb-shell-studio [data-studio-playhead],.module-wb-shell-studio-oss [data-studio-timeline],.module-wb-shell-studio [data-studio-timeline],.module-wb-shell-studio-oss .module-wb-studio-control-grid,.module-wb-shell-studio .module-wb-studio-control-grid,.module-wb-shell-studio-oss .module-wb-inspector-actions,.module-wb-shell-studio .module-wb-inspector-actions{display:none!important;}',
        '.module-wb-shell-app-oss,.module-wb-shell-app{grid-template-columns:minmax(0,1fr)!important;}',
        '.module-wb-shell-app-oss>.module-wb-side-card,.module-wb-shell-app>.module-wb-side-card,.module-wb-shell-app-oss>.module-wb-inspector-card,.module-wb-shell-app>.module-wb-inspector-card{display:none!important;}',
        '.module-wb-shell-app-oss .module-wb-preview-frame-wrap,.module-wb-shell-app .module-wb-preview-frame-wrap,.module-wb-shell-app-oss .module-wb-stage-head,.module-wb-shell-app .module-wb-stage-head,.module-wb-shell-app-oss .module-wb-device-switch,.module-wb-shell-app .module-wb-device-switch{display:none!important;}',
        '.module-wb-shell-app-oss .module-wb-app-list,.module-wb-shell-app .module-wb-app-list{max-height:none!important;min-height:560px;border:1px solid rgba(160,193,238,.24);border-radius:9px;padding:8px;background:rgba(8,14,23,.68);}',
        '.module-wb-comfy-shell{margin-top:14px;padding:12px;border-radius:12px;border:1px solid var(--border-subtle,rgba(120,140,180,.35));background:linear-gradient(180deg,rgba(24,32,44,.86),rgba(16,22,32,.92));display:flex;flex-direction:column;gap:10px;}',
        '.module-wb-shell-studio-oss .module-wb-comfy-shell,.module-wb-shell-studio .module-wb-comfy-shell{margin-top:0;}',
        '.module-wb-comfy-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap;}',
        '.module-wb-comfy-title{display:flex;flex-direction:column;gap:2px;}',
        '.module-wb-comfy-title strong{font-size:13px;letter-spacing:.01em;}',
        '.module-wb-comfy-title span{font-size:11px;opacity:.78;}',
        '.module-wb-comfy-status{display:inline-flex;align-items:center;gap:6px;font-size:11px;padding:4px 8px;border-radius:999px;background:rgba(74,118,255,.15);border:1px solid rgba(122,169,255,.3);}',
        '.module-wb-comfy-status .dot{width:7px;height:7px;border-radius:999px;background:#9ab8ff;}',
        '.module-wb-comfy-status.warn .dot{background:#f7c46b;}',
        '.module-wb-comfy-status.ok .dot{background:#68d4a3;}',
        '.module-wb-comfy-status.error .dot{background:#ff8f8f;}',
        '.module-wb-comfy-row{display:grid;grid-template-columns:1fr auto auto auto auto;gap:8px;align-items:end;}',
        '.module-wb-comfy-row .module-wb-field{margin:0;}',
        '.module-wb-comfy-frame{border:1px solid var(--border-subtle,rgba(120,140,180,.35));border-radius:10px;overflow:hidden;background:#0e141d;min-height:340px;}',
        '.module-wb-comfy-frame iframe{display:block;width:100%;height:420px;border:0;background:#0e141d;}',
        '.module-wb-comfy-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}',
        '.module-wb-comfy-box{border:1px solid var(--border-subtle,rgba(120,140,180,.35));border-radius:10px;padding:10px;background:rgba(11,16,24,.65);display:flex;flex-direction:column;gap:8px;}',
        '.module-wb-comfy-box h5{margin:0;font-size:12px;}',
        '.module-wb-comfy-actions{display:flex;gap:8px;flex-wrap:wrap;}',
        '.module-wb-comfy-box textarea,.module-wb-comfy-box input{width:100%;min-height:34px;max-height:210px;border-radius:8px;border:1px solid var(--border-subtle,rgba(120,140,180,.35));background:rgba(7,11,18,.85);color:var(--text-primary,#ecf2ff);padding:8px;font:inherit;}',
        '.module-wb-comfy-outputs{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:8px;}',
        '.module-wb-comfy-output{border:1px solid var(--border-subtle,rgba(120,140,180,.35));border-radius:8px;overflow:hidden;background:rgba(7,11,18,.85);}',
        '.module-wb-comfy-output a{display:block;text-decoration:none;color:inherit;}',
        '.module-wb-comfy-output img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;background:#0b1018;}',
        '.module-wb-comfy-output span{display:block;padding:6px 7px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
        '@media (max-width: 920px){.module-wb-comfy-row{grid-template-columns:1fr 1fr;}.module-wb-comfy-grid{grid-template-columns:1fr;}.module-wb-comfy-frame iframe{height:360px;}}',
    ].join('');
    document.head.appendChild(style);
}

function moduleStudioEnsureComfyState(wb) {
    if (!wb || typeof wb !== 'object') return;
    if (!wb.comfy || typeof wb.comfy !== 'object') {
        wb.comfy = {};
    }
    const comfy = wb.comfy;
    comfy.serverUrl = safeString(comfy.serverUrl) || 'http://127.0.0.1:8188';
    comfy.embedUrl = safeString(comfy.embedUrl) || comfy.serverUrl;
    comfy.status = comfy.status && typeof comfy.status === 'object' ? comfy.status : {};
    comfy.booting = Boolean(comfy.booting);
    comfy.statusLoading = Boolean(comfy.statusLoading);
    comfy.workflowText = safeString(comfy.workflowText);
    comfy.instructionText = safeString(comfy.instructionText);
    comfy.lastPromptId = safeString(comfy.lastPromptId);
    comfy.promptLookupId = safeString(comfy.promptLookupId) || comfy.lastPromptId;
    comfy.lastHistoryStatus = safeString(comfy.lastHistoryStatus);
    comfy.lastOutputs = Array.isArray(comfy.lastOutputs) ? comfy.lastOutputs : [];
    comfy.error = safeString(comfy.error);
    comfy.autoBootAttempted = Boolean(comfy.autoBootAttempted);
}

function moduleStudioResolveComfyProfileHint() {
    const profiles = Array.isArray(availableModelProfiles) ? availableModelProfiles : [];
    if (!profiles.length) return '';
    const rows = profiles
        .map((profile) => ({
            name: safeString(profile && profile.name),
            key: safeString(profile && profile.name).toLowerCase(),
        }))
        .filter((row) => Boolean(row.name));
    if (!rows.length) return '';
    const exact = rows.find((row) => row.key === 'comfy' || row.key === 'comfyui');
    if (exact) return exact.name;
    const fuzzy = rows.find((row) => row.key.includes('comfy') || row.key.includes('studio'));
    if (fuzzy) return fuzzy.name;
    return '';
}

function moduleStudioBuildChatContext() {
    const runtime = typeof moduleEnsureRuntime === 'function' ? moduleEnsureRuntime() : null;
    if (!runtime || typeof runtime !== 'object') {
        return { enabled: false, preferredProfile: '', context: {} };
    }
    const mode = safeString(runtime.workbenchMode).toLowerCase();
    if (mode !== 'studio') {
        return { enabled: false, preferredProfile: '', context: {} };
    }
    const wb = runtime.workbench && runtime.workbench.studio && typeof runtime.workbench.studio === 'object'
        ? runtime.workbench.studio
        : null;
    if (!wb) {
        return { enabled: false, preferredProfile: '', context: {} };
    }
    if (typeof moduleStudioEnsureComfyState === 'function') {
        moduleStudioEnsureComfyState(wb);
    }
    const comfy = wb.comfy && typeof wb.comfy === 'object' ? wb.comfy : {};
    const status = comfy.status && typeof comfy.status === 'object' ? comfy.status : {};
    const running = Boolean(status.running);
    const hasPrompt = Boolean(safeString(comfy.lastPromptId || comfy.promptLookupId));
    const hasOutputs = Array.isArray(comfy.lastOutputs) && comfy.lastOutputs.length > 0;
    const enabled = running || hasPrompt || hasOutputs || Boolean(comfy.booting);
    if (!enabled) {
        return { enabled: false, preferredProfile: '', context: {} };
    }
    return {
        enabled: true,
        preferredProfile: moduleStudioResolveComfyProfileHint(),
        context: {
            workspace: 'asset_studio',
            mode: 'comfy_studio',
            tool: 'comfyui',
            server_url: safeString(comfy.serverUrl || status.server_url || ''),
            prompt_id: safeString(comfy.lastPromptId || comfy.promptLookupId || ''),
            outputs_count: Array.isArray(comfy.lastOutputs) ? comfy.lastOutputs.length : 0,
            running: Boolean(status.running),
            booting: Boolean(comfy.booting),
        },
    };
}

function moduleStudioComfyPushLog(wb, messageRaw, toneRaw = 'ok') {
    if (!wb) return;
    if (!Array.isArray(wb.logs)) wb.logs = [];
    moduleWorkbenchPushLog(wb.logs, messageRaw, toneRaw, 80, 'studio-log');
}

function moduleStudioComfyRefreshMode() {
    if (typeof moduleWorkbenchRefreshMode === 'function') {
        moduleWorkbenchRefreshMode('studio');
    }
}

async function moduleStudioComfyRefreshStatus(wb, options = {}) {
    moduleStudioEnsureComfyState(wb);
    if (wb.comfy.statusLoading) return wb.comfy.status || {};
    wb.comfy.statusLoading = true;
    const silent = Boolean(options && options.silent);
    try {
        const query = new URLSearchParams();
        query.set('server_url', wb.comfy.serverUrl);
        query.set('timeout_s', '2');
        const response = await fetchJsonSafe('/api/asset-studio/v1/comfy/status?' + query.toString(), {
            method: 'GET',
            timeoutMs: 7000,
        });
        if (!response.ok || !response.data || typeof response.data.status !== 'object') {
            const reason = safeString(response.text) || 'Could not read Comfy status.';
            wb.comfy.error = reason;
            if (!silent) notifyUser(reason, { tone: 'warn', durationMs: 2200, debugKind: 'studio' });
            return wb.comfy.status || {};
        }
        wb.comfy.status = response.data.status;
        wb.comfy.error = '';
        if (wb.comfy.status && wb.comfy.status.running) {
            wb.comfy.embedUrl = safeString(wb.comfy.status.server_url) || wb.comfy.serverUrl;
        }
        return wb.comfy.status || {};
    } catch (error) {
        wb.comfy.error = safeString(error && error.message) || 'Comfy status check failed.';
        if (!silent) notifyUser(wb.comfy.error, { tone: 'warn', durationMs: 2200, debugKind: 'studio' });
        return wb.comfy.status || {};
    } finally {
        wb.comfy.statusLoading = false;
        moduleStudioComfyRefreshMode();
    }
}

async function moduleStudioComfyBoot(wb, options = {}) {
    moduleStudioEnsureComfyState(wb);
    if (wb.comfy.booting) return;
    wb.comfy.booting = true;
    const silent = Boolean(options && options.silent);
    moduleStudioComfyRefreshMode();
    try {
        const response = await fetchJsonSafe('/api/asset-studio/v1/comfy/boot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                server_url: wb.comfy.serverUrl,
                wait_timeout_s: 24,
            }),
            timeoutMs: 30000,
        });
        const boot = response.data && typeof response.data.boot === 'object' ? response.data.boot : {};
        wb.comfy.status = boot;
        wb.comfy.error = safeString(boot.error);
        if (boot && boot.running) {
            wb.comfy.embedUrl = safeString(boot.server_url) || wb.comfy.serverUrl;
            moduleStudioComfyPushLog(wb, 'Comfy Studio online.', 'ok');
            if (!silent) notifyUser('Comfy Studio is ready.', { tone: 'success', durationMs: 1800, debugKind: 'studio' });
        } else if (!silent) {
            const reason = wb.comfy.error || 'Comfy boot did not reach ready state.';
            notifyUser(reason, { tone: 'warn', durationMs: 2600, debugKind: 'studio' });
        }
    } catch (error) {
        wb.comfy.error = safeString(error && error.message) || 'Comfy boot failed.';
        if (!silent) notifyUser(wb.comfy.error, { tone: 'warn', durationMs: 2600, debugKind: 'studio' });
    } finally {
        wb.comfy.booting = false;
        moduleStudioComfyRefreshMode();
    }
}

async function moduleStudioComfyShutdown(wb) {
    moduleStudioEnsureComfyState(wb);
    try {
        const response = await fetchJsonSafe('/api/asset-studio/v1/comfy/shutdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server_url: wb.comfy.serverUrl, wait_timeout_s: 10 }),
            timeoutMs: 12000,
        });
        const payload = response.data && typeof response.data.shutdown === 'object' ? response.data.shutdown : {};
        wb.comfy.status = payload;
        wb.comfy.error = '';
        moduleStudioComfyPushLog(wb, 'Comfy Studio shutdown requested.', 'warn');
        notifyUser('Comfy Studio shutdown signal sent.', { tone: 'info', durationMs: 1800, debugKind: 'studio' });
    } catch (error) {
        wb.comfy.error = safeString(error && error.message) || 'Shutdown request failed.';
        notifyUser(wb.comfy.error, { tone: 'warn', durationMs: 2200, debugKind: 'studio' });
    } finally {
        moduleStudioComfyRefreshMode();
    }
}

async function moduleStudioComfyQueueWorkflow(wb) {
    moduleStudioEnsureComfyState(wb);
    const workflowJson = safeString(wb.comfy.workflowText);
    if (!workflowJson) {
        notifyUser('Paste a Comfy workflow JSON first.', { tone: 'warn', durationMs: 2200, debugKind: 'studio' });
        return;
    }
    try {
        const response = await fetchJsonSafe('/api/asset-studio/v1/comfy/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                server_url: wb.comfy.serverUrl,
                workflow_json: workflowJson,
                timeout_s: 40,
            }),
            timeoutMs: 45000,
        });
        if (!response.ok || !response.data || typeof response.data.result !== 'object') {
            const reason = safeString(response.text) || 'Queue request failed.';
            notifyUser(reason, { tone: 'warn', durationMs: 2300, debugKind: 'studio' });
            return;
        }
        const result = response.data.result;
        wb.comfy.lastPromptId = safeString(result.prompt_id);
        wb.comfy.promptLookupId = wb.comfy.lastPromptId;
        wb.comfy.error = '';
        moduleStudioComfyPushLog(wb, 'Queued Comfy workflow ' + (wb.comfy.lastPromptId || '(no prompt id returned)') + '.', 'ok');
        notifyUser('Workflow queued in Comfy Studio.', { tone: 'success', durationMs: 1700, debugKind: 'studio' });
    } catch (error) {
        wb.comfy.error = safeString(error && error.message) || 'Queue request failed.';
        notifyUser(wb.comfy.error, { tone: 'warn', durationMs: 2300, debugKind: 'studio' });
    } finally {
        moduleStudioComfyRefreshMode();
    }
}

async function moduleStudioComfyRefreshOutputs(wb) {
    moduleStudioEnsureComfyState(wb);
    const promptId = safeString(wb.comfy.promptLookupId || wb.comfy.lastPromptId);
    if (!promptId) {
        notifyUser('Set a prompt id to load outputs.', { tone: 'warn', durationMs: 2000, debugKind: 'studio' });
        return;
    }
    try {
        const query = new URLSearchParams();
        query.set('server_url', wb.comfy.serverUrl);
        query.set('timeout_s', '24');
        const response = await fetchJsonSafe('/api/asset-studio/v1/comfy/outputs/' + encodeURIComponent(promptId) + '?' + query.toString(), {
            method: 'GET',
            timeoutMs: 30000,
        });
        if (!response.ok || !response.data || typeof response.data.outputs !== 'object') {
            const reason = safeString(response.text) || 'Could not fetch outputs.';
            notifyUser(reason, { tone: 'warn', durationMs: 2300, debugKind: 'studio' });
            return;
        }
        const outputs = response.data.outputs;
        wb.comfy.lastPromptId = safeString(outputs.prompt_id) || promptId;
        wb.comfy.promptLookupId = wb.comfy.lastPromptId;
        wb.comfy.lastHistoryStatus = safeString(outputs.status);
        wb.comfy.lastOutputs = Array.isArray(outputs.images) ? outputs.images : [];
        wb.comfy.error = '';
        moduleStudioComfyPushLog(wb, 'Loaded ' + String(wb.comfy.lastOutputs.length) + ' Comfy outputs.', 'ok');
        notifyUser('Comfy Studio outputs refreshed.', { tone: 'success', durationMs: 1600, debugKind: 'studio' });
    } catch (error) {
        wb.comfy.error = safeString(error && error.message) || 'Could not fetch outputs.';
        notifyUser(wb.comfy.error, { tone: 'warn', durationMs: 2300, debugKind: 'studio' });
    } finally {
        moduleStudioComfyRefreshMode();
    }
}

function moduleStudioSendComfyInstruction(wb) {
    moduleStudioEnsureComfyState(wb);
    const instruction = safeString(wb.comfy.instructionText);
    if (!instruction) {
        notifyUser('Write a Thomas instruction first.', { tone: 'warn', durationMs: 2000, debugKind: 'studio' });
        return;
    }
    if (!(composerTextarea instanceof HTMLTextAreaElement) || typeof handleSend !== 'function') {
        notifyUser('Chat composer is not ready yet.', { tone: 'warn', durationMs: 2200, debugKind: 'studio' });
        return;
    }
    const promptId = safeString(wb.comfy.lastPromptId);
    const contextBits = ['server_url=' + wb.comfy.serverUrl];
    if (promptId) contextBits.push('prompt_id=' + promptId);
    const composed = '[Comfy Studio Context: ' + contextBits.join(', ') + '] ' + instruction;
    composerTextarea.value = composed;
    composerTextarea.dispatchEvent(new Event('input'));
    void handleSend();
    moduleStudioComfyPushLog(wb, 'Sent instruction to Thomas from Comfy Studio panel.', 'ok');
    notifyUser('Instruction sent to Thomas.', { tone: 'success', durationMs: 1700, debugKind: 'studio' });
}

function moduleStudioComfyOutputsMarkup(outputsRaw) {
    const outputs = Array.isArray(outputsRaw) ? outputsRaw : [];
    if (!outputs.length) {
        return '<div class="module-wb-ghost">No Comfy outputs loaded yet.</div>';
    }
    return outputs.slice(0, 24).map((row) => {
        const url = escapeHtml(safeString(row && row.url));
        const name = escapeHtml(safeString(row && row.filename) || 'output');
        if (!url) {
            return '<article class="module-wb-comfy-output"><span>' + name + '</span></article>';
        }
        return '<article class="module-wb-comfy-output"><a href="' + url + '" target="_blank" rel="noopener noreferrer"><img src="' + url + '" alt="' + name + '" loading="lazy" /><span>' + name + '</span></a></article>';
    }).join('');
}

function moduleStudioComfyPanelMarkup(wb) {
    const comfy = wb && wb.comfy && typeof wb.comfy === 'object' ? wb.comfy : {};
    const status = comfy.status && typeof comfy.status === 'object' ? comfy.status : {};
    const running = Boolean(status.running);
    const booting = Boolean(comfy.booting);
    const tone = booting ? 'warn' : (running ? 'ok' : 'error');
    const label = booting ? 'Booting' : (running ? 'Running' : 'Offline');
    const errorText = escapeHtml(safeString(comfy.error));
    const workflowText = escapeHtml(safeString(comfy.workflowText));
    const instructionText = escapeHtml(safeString(comfy.instructionText));
    const promptLookupId = escapeHtml(safeString(comfy.promptLookupId || comfy.lastPromptId));
    const historyStatus = escapeHtml(safeString(comfy.lastHistoryStatus) || 'unknown');
    const serverUrl = escapeHtml(safeString(comfy.serverUrl));
    const iframeUrl = escapeHtml(safeString(comfy.embedUrl || comfy.serverUrl));
    const outputs = moduleStudioComfyOutputsMarkup(comfy.lastOutputs);
    const frameClass = running ? 'module-wb-comfy-frame' : 'module-wb-comfy-frame hidden';
    const offlineClass = running ? 'module-wb-ghost hidden' : 'module-wb-ghost';
    return ''
        + '<section class="module-wb-comfy-shell" data-studio-comfy-shell>'
        +   '<div class="module-wb-comfy-head">'
        +     '<div class="module-wb-comfy-title"><strong>Comfy Studio</strong><span>Thomas wrapper powered by ComfyUI (open source).</span></div>'
        +     '<div class="module-wb-comfy-status ' + tone + '"><span class="dot"></span><span>' + escapeHtml(label) + '</span></div>'
        +   '</div>'
        +   '<div class="module-wb-comfy-row">'
        +     '<label class="module-wb-field module-wb-field-wide">Comfy Server URL<input type="text" data-comfy-server-url value="' + serverUrl + '" placeholder="http://127.0.0.1:8188" /></label>'
        +     '<button type="button" class="module-item-btn" data-comfy-action="boot">Boot</button>'
        +     '<button type="button" class="module-item-btn" data-comfy-action="status">Refresh</button>'
        +     '<button type="button" class="module-item-btn" data-comfy-action="shutdown">Stop</button>'
        +     '<button type="button" class="module-item-btn" data-comfy-action="open">Open Tab</button>'
        +   '</div>'
        +   (errorText ? '<div class="module-wb-ghost">' + errorText + '</div>' : '')
        +   '<div class="' + frameClass + '"><iframe data-comfy-iframe src="' + iframeUrl + '" title="Comfy Studio Embedded"></iframe></div>'
        +   '<div class="' + offlineClass + '">Comfy is offline. Click <strong>Boot</strong> to start the managed session.</div>'
        +   '<div class="module-wb-comfy-grid">'
        +     '<article class="module-wb-comfy-box">'
        +       '<h5>Talk to Thomas in Comfy Context</h5>'
        +       '<textarea data-comfy-instruction rows="4" placeholder="Example: load workflow, set prompt to cinematic robot office, queue render.">' + instructionText + '</textarea>'
        +       '<div class="module-wb-comfy-actions"><button type="button" class="module-item-btn" data-comfy-action="send_instruction">Send to Thomas</button></div>'
        +     '</article>'
        +     '<article class="module-wb-comfy-box">'
        +       '<h5>Queue Workflow + Outputs</h5>'
        +       '<textarea data-comfy-workflow rows="6" placeholder="Paste Comfy workflow JSON here.">' + workflowText + '</textarea>'
        +       '<input type="text" data-comfy-prompt-id value="' + promptLookupId + '" placeholder="Prompt id for output lookup" />'
        +       '<div class="module-wb-comfy-actions">'
        +         '<button type="button" class="module-item-btn" data-comfy-action="queue_workflow">Queue Render</button>'
        +         '<button type="button" class="module-item-btn" data-comfy-action="refresh_outputs">Get Outputs</button>'
        +       '</div>'
        +     '</article>'
        +   '</div>'
        +   '<div class="module-wb-comfy-box"><h5>Outputs (status: ' + historyStatus + ')</h5><div class="module-wb-comfy-outputs">' + outputs + '</div></div>'
        + '</section>';
}

function moduleStudioBindComfyPanel(container, wb) {
    if (!(container instanceof HTMLElement)) return;
    moduleStudioEnsureComfyState(wb);
    moduleStudioEnsureComfyStyles();
    const stage = container.querySelector('.module-wb-studio-stage');
    if (!(stage instanceof HTMLElement)) return;
    let mount = stage.querySelector('[data-studio-comfy-shell-host]');
    if (!(mount instanceof HTMLElement)) {
        mount = document.createElement('div');
        mount.setAttribute('data-studio-comfy-shell-host', '1');
        stage.appendChild(mount);
    }
    mount.innerHTML = moduleStudioComfyPanelMarkup(wb);

    const serverInput = mount.querySelector('[data-comfy-server-url]');
    const workflowInput = mount.querySelector('[data-comfy-workflow]');
    const instructionInput = mount.querySelector('[data-comfy-instruction]');
    const promptIdInput = mount.querySelector('[data-comfy-prompt-id]');
    const iframe = mount.querySelector('[data-comfy-iframe]');
    if (serverInput instanceof HTMLInputElement) {
        serverInput.addEventListener('input', () => {
            wb.comfy.serverUrl = safeString(serverInput.value) || 'http://127.0.0.1:8188';
            wb.comfy.embedUrl = wb.comfy.serverUrl;
        });
    }
    if (workflowInput instanceof HTMLTextAreaElement) {
        workflowInput.addEventListener('input', () => {
            wb.comfy.workflowText = safeString(workflowInput.value);
        });
    }
    if (instructionInput instanceof HTMLTextAreaElement) {
        instructionInput.addEventListener('input', () => {
            wb.comfy.instructionText = safeString(instructionInput.value);
        });
    }
    if (promptIdInput instanceof HTMLInputElement) {
        promptIdInput.addEventListener('input', () => {
            wb.comfy.promptLookupId = safeString(promptIdInput.value);
        });
    }
    if (iframe instanceof HTMLIFrameElement) {
        const target = safeString(wb.comfy.embedUrl || wb.comfy.serverUrl);
        if (target && iframe.src !== target) {
            iframe.src = target;
        }
    }

    mount.addEventListener('click', (event) => {
        const target = event.target instanceof Element ? event.target.closest('[data-comfy-action]') : null;
        if (!(target instanceof HTMLElement)) return;
        const action = safeString(target.getAttribute('data-comfy-action')).toLowerCase();
        if (action === 'boot') {
            void moduleStudioComfyBoot(wb);
            return;
        }
        if (action === 'status') {
            void moduleStudioComfyRefreshStatus(wb);
            return;
        }
        if (action === 'shutdown') {
            void moduleStudioComfyShutdown(wb);
            return;
        }
        if (action === 'open') {
            const url = safeString(wb.comfy.serverUrl) || 'http://127.0.0.1:8188';
            window.open(url, '_blank', 'noopener,noreferrer');
            return;
        }
        if (action === 'send_instruction') {
            moduleStudioSendComfyInstruction(wb);
            return;
        }
        if (action === 'queue_workflow') {
            void moduleStudioComfyQueueWorkflow(wb);
            return;
        }
        if (action === 'refresh_outputs') {
            void moduleStudioComfyRefreshOutputs(wb);
            return;
        }
    });

    if (!wb.comfy.autoBootAttempted) {
        wb.comfy.autoBootAttempted = true;
        void moduleStudioComfyRefreshStatus(wb, { silent: true }).then((status) => {
            if (!status || !status.running) {
                void moduleStudioComfyBoot(wb, { silent: true });
            }
        });
    }
}

// [duplicate removed] const moduleRenderWorkbenchStudioOssOriginal = moduleRenderWorkbenchStudioOss;
moduleRenderWorkbenchStudioOss = function moduleRenderWorkbenchStudioOssWithComfy(container, wb) {
    const rendered = moduleRenderWorkbenchStudioOssOriginal(container, wb);
    if (rendered) {
        try {
            moduleStudioBindComfyPanel(container, wb);
        } catch (error) {
            console.warn('Comfy Studio panel binding failed', error);
        }
    }
    return rendered;
};

// [duplicate removed] const MODULE_UI_EDITOR_STYLE_ID = 'moduleUiEditorStyles';
// [duplicate removed] const MODULE_UI_EDITOR_INLINE_STYLE_ID = 'moduleUiEditorInlineStyles';
// [duplicate removed] const MODULE_UI_EDITOR_STORE_KEY = 'thomas.uiEditor.urlProjects.v1';
const MODULE_UI_EDITOR_PLUGIN_STORE_KEY = 'thomas.uiEditor.shellModules.v1';
const MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_URL_KEY = 'thomas.uiEditor.shellModules.marketplaceUrl.v1';
const MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_LASTSYNC_KEY = 'thomas.uiEditor.shellModules.marketplaceLastSync.v1';
// [duplicate removed] const MODULE_UI_EDITOR_VIEWPORT_MIN_WIDTH = 420;
// [duplicate removed] const MODULE_UI_EDITOR_VIEWPORT_MIN_HEIGHT = 280;
// [duplicate removed] const MODULE_UI_EDITOR_VIEWPORT_MAX_WIDTH = 2400;
// [duplicate removed] const MODULE_UI_EDITOR_VIEWPORT_MAX_HEIGHT = 1600;

function moduleUiEditorEscapeHtml(valueRaw) {
    const value = safeString(valueRaw);
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function moduleUiEditorNormalizeShellPluginId(valueRaw) {
    const slug = safeString(valueRaw)
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/(^-+|-+$)/g, '');
    if (slug) return slug;
    const fallback = typeof moduleWorkbenchMakeId === 'function'
        ? moduleWorkbenchMakeId('module')
        : String(Date.now());
    return 'module-' + String(fallback).replace(/[^a-z0-9]/gi, '');
}

function moduleUiEditorDefaultShellPlugins() {
    return [
        {
            id: 'chat',
            name: 'Chat',
            pill: 'chat mode',
            toolbarActions: ['New Chat'],
            cards: [
                { title: 'Conversation Stream', text: 'Editable conversation view and composer region.' },
                { title: 'Task Continuity', text: 'Goals, blockers, and progress ribbon.' },
                { title: 'Suggestions', text: 'Action chips and quick prompts.' },
            ],
            removable: false,
        },
        {
            id: 'office',
            name: 'Virtual Office',
            pill: 'office mode',
            toolbarActions: ['Pan', 'Zoom'],
            cards: [
                { title: 'Foundation Grid', text: 'Massive expandable map canvas for future neighborhoods and rooms.' },
                { title: 'Seed Zone', text: 'Central starting area for the first build pass.' },
                { title: 'Expansion Margin', text: 'Plenty of empty terrain so the office can scale hard.' },
            ],
            removable: false,
        },
        {
            id: 'mission',
            name: 'Mission Control',
            pill: 'mission mode',
            toolbarActions: ['Run Plan', 'Approve'],
            cards: [
                { title: 'Mission Board', text: 'Objectives and ownership lanes.' },
                { title: 'Approvals', text: 'Pending policy checks.' },
                { title: 'Health', text: 'Critical service status.' },
            ],
            removable: false,
        },
        {
            id: 'content',
            name: 'Content Hub',
            pill: 'content hub',
            toolbarActions: ['Create Post', 'Schedule'],
            cards: [
                { title: 'Pipelines', text: 'Draft, review, publish lanes.' },
                { title: 'Assets', text: 'Media and campaign resources.' },
                { title: 'Calendar', text: 'Queued and live drops.' },
            ],
            removable: false,
        },
        {
            id: 'editor',
            name: 'UI Editor',
            pill: 'ui editor',
            toolbarActions: ['Edit', 'Save Layout'],
            cards: [
                { title: 'Canvas', text: 'Select and move interface assets.' },
                { title: 'Inspector', text: 'Position and sizing metadata.' },
                { title: 'Export', text: 'JSON payload for wiring functionality.' },
            ],
            removable: false,
        },
    ];
}

function moduleUiEditorNormalizeShellPlugin(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const cards = Array.isArray(raw.cards) ? raw.cards : [];
    const toolbarActions = Array.isArray(raw.toolbarActions) ? raw.toolbarActions : [];
    const cleanCards = cards
        .map((card) => ({
            title: safeString(card && card.title),
            text: safeString(card && card.text),
        }))
        .filter((row) => Boolean(row.title) || Boolean(row.text))
        .slice(0, 5);
    if (!cleanCards.length) {
        cleanCards.push({
            title: safeString(raw && raw.name) || 'Module',
            text: 'Custom module shell panel.',
        });
    }
    const cleanToolbar = toolbarActions
        .map((action) => safeString(action))
        .filter(Boolean)
        .slice(0, 6);
    const id = moduleUiEditorNormalizeShellPluginId(safeString(raw.id) || safeString(raw.name));
    return {
        id,
        name: safeString(raw.name) || id,
        pill: safeString(raw.pill) || (safeString(raw.name) || id).toLowerCase(),
        toolbarActions: cleanToolbar.length ? cleanToolbar : ['Open'],
        cards: cleanCards,
        removable: safeString(raw.removable) === 'false' ? false : (raw.removable !== false),
        source: safeString(raw.source) || safeString(raw.url) || '',
        version: safeString(raw.version),
        description: safeString(raw.description),
    };
}

