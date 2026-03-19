        const part = safeString(partRaw);
        if (!part || part === '.') return;
        if (part === '..') {
            resolved.pop();
            return;
        }
        resolved.push(part);
    });
    return resolved.join('/');
}

function moduleUiEditorClamp(valueRaw, minRaw, maxRaw) {
    const value = Number(valueRaw);
    const min = Number(minRaw);
    const max = Number(maxRaw);
    if (!Number.isFinite(value)) return Number.isFinite(min) ? min : 0;
    if (Number.isFinite(min) && value < min) return min;
    if (Number.isFinite(max) && value > max) return max;
    return value;
}

function moduleUiEditorInferPurpose(element) {
    const tag = safeString(element && element.tagName).toLowerCase();
    const role = safeString(element && element.getAttribute && element.getAttribute('role')).toLowerCase();
    if (tag === 'button' || role === 'button') return 'action';
    if (tag === 'a' || tag === 'nav') return 'navigation';
    if (tag === 'input' || tag === 'select' || tag === 'textarea' || role === 'textbox') return 'input';
    if (tag === 'form') return 'form';
    if (tag === 'main' || tag === 'section' || tag === 'article') return 'layout';
    if (tag === 'header' || tag === 'footer' || tag === 'aside') return 'structure';
    return 'content';
}

function moduleUiEditorBuildSelector(element) {
    if (!(element instanceof Element)) return '';
    const parts = [];
    let cursor = element;
    while (cursor instanceof Element && safeString(cursor.tagName).toLowerCase() !== 'body') {
        const tag = safeString(cursor.tagName).toLowerCase();
        if (!tag) break;
        const id = safeString(cursor.id);
        if (id) {
            parts.unshift(tag + '#' + moduleUiEditorCssEscape(id));
            break;
        }
        let part = tag;
        const parent = cursor.parentElement;
        if (parent instanceof Element) {
            const siblings = Array.from(parent.children).filter((node) => safeString(node.tagName).toLowerCase() === tag);
            if (siblings.length > 1) {
                const idx = siblings.indexOf(cursor) + 1;
                if (idx > 0) part = part + ':nth-of-type(' + idx + ')';
            }
        }
        parts.unshift(part);
        cursor = parent;
    }
    parts.unshift('body');
    return parts.join(' > ');
}

function moduleUiEditorReadUrlStore() {
    try {
        const raw = window.localStorage.getItem(MODULE_UI_EDITOR_STORE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
        return [];
    }
}

function moduleUiEditorWriteUrlStore(rowsRaw) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    try {
        window.localStorage.setItem(MODULE_UI_EDITOR_STORE_KEY, JSON.stringify(rows));
    } catch (_error) {}
}

function moduleUiEditorReadShellPluginMarketplaceUrl() {
    try {
        const raw = window.localStorage.getItem(MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_URL_KEY);
        return safeString(raw);
    } catch (_error) {
        return '';
    }
}

function moduleUiEditorWriteShellPluginMarketplaceUrl(urlRaw) {
    const value = moduleUiEditorNormalizeShellPluginBootstrapSource(urlRaw);
    const normalized = value.ok ? value.source : '';
    try {
        if (!normalized) {
            window.localStorage.removeItem(MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_URL_KEY);
            return;
        }
        window.localStorage.setItem(MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_URL_KEY, normalized);
    } catch (_error) {}
}

function moduleUiEditorReadShellPluginMarketplaceLastSync() {
    try {
        const raw = window.localStorage.getItem(MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_LASTSYNC_KEY);
        const value = Number(raw);
        if (!Number.isFinite(value) || value <= 0) return 0;
        return value;
    } catch (_error) {
        return 0;
    }
}

function moduleUiEditorWriteShellPluginMarketplaceLastSync(tsRaw) {
    const value = Number(tsRaw);
    const normalized = Number.isFinite(value) && value > 0 ? value : Date.now();
    try {
        window.localStorage.setItem(MODULE_UI_EDITOR_PLUGIN_MARKETPLACE_LASTSYNC_KEY, String(normalized));
    } catch (_error) {}
}

function moduleUiEditorPersistUrlProjects(wb) {
    if (!wb || !Array.isArray(wb.uiProjects)) return;
    const rows = wb.uiProjects
        .filter((project) => safeString(project && project.type) === 'url')
        .map((project) => ({
            id: safeString(project && project.id),
            name: safeString(project && project.name),
            type: 'url',
            url: safeString(project && project.url) || '/',
            overrides: project && typeof project.overrides === 'object' ? project.overrides : {},
            updatedAt: Number(project && project.updatedAt) || Date.now(),
        }))
        .filter((row) => Boolean(row.id) && Boolean(row.name));
    moduleUiEditorWriteUrlStore(rows.slice(0, 24));
}

function moduleUiEditorEnsureState(wb) {
    if (!wb || typeof wb !== 'object') return;
    if (!Array.isArray(wb.uiProjects)) wb.uiProjects = [];
    if (!wb.uiShell || typeof wb.uiShell !== 'object') wb.uiShell = {};
    wb.uiShell.storeOpen = wb.uiShell.storeOpen !== false;
    const shellCatalog = moduleUiEditorReadShellPluginCatalog();
    const savedShellIds = Array.isArray(wb.uiShell.enabledPluginIds)
        ? wb.uiShell.enabledPluginIds
        : [];
    wb.uiShell.enabledPluginIds = moduleUiEditorNormalizeShellPluginIds(savedShellIds, shellCatalog);
    if (!wb.uiProjects.length) {
        const defaults = [{
            id: 'ui-project-thomas',
            name: 'Thomas',
            type: 'url',
            url: '/',
            overrides: {},
            updatedAt: Date.now(),
        }];
        const stored = moduleUiEditorReadUrlStore();
        wb.uiProjects = defaults;
        stored.forEach((row) => {
            const id = safeString(row && row.id);
            const name = safeString(row && row.name);
            const type = safeString(row && row.type);
            const url = safeString(row && row.url);
            if (!id || !name || type !== 'url' || !url) return;
            if (wb.uiProjects.some((project) => safeString(project.id) === id)) return;
            wb.uiProjects.push({
                id,
                name,
                type: 'url',
                url,
                overrides: row && typeof row.overrides === 'object' ? row.overrides : {},
                updatedAt: Number(row && row.updatedAt) || Date.now(),
            });
        });
    }
    const pinnedIndex = wb.uiProjects.findIndex((project) => safeString(project && project.id) === 'ui-project-thomas');
    if (pinnedIndex === -1) {
        wb.uiProjects.unshift({
            id: 'ui-project-thomas',
            name: 'Thomas',
            type: 'url',
            url: '/',
            overrides: {},
            updatedAt: Date.now(),
        });
    } else {
        const pinned = wb.uiProjects[pinnedIndex];
        pinned.name = 'Thomas';
        pinned.type = 'url';
        pinned.url = '/';
        pinned.overrides = pinned && typeof pinned.overrides === 'object' ? pinned.overrides : {};
        if (Object.prototype.hasOwnProperty.call(pinned, 'srcdoc')) delete pinned.srcdoc;
        if (Object.prototype.hasOwnProperty.call(pinned, 'blobUrls')) delete pinned.blobUrls;
        if (pinnedIndex > 0) {
            wb.uiProjects.splice(pinnedIndex, 1);
            wb.uiProjects.unshift(pinned);
        }
    }
    wb.uiSelectedProjectId = safeString(wb.uiSelectedProjectId);
    if (!wb.uiSelectedProjectId || !wb.uiProjects.some((project) => safeString(project.id) === wb.uiSelectedProjectId)) {
        wb.uiSelectedProjectId = safeString(wb.uiProjects[0] && wb.uiProjects[0].id);
    }
    if (wb.__uiEditorStateInitialized !== true) {
        wb.__uiEditorStateInitialized = true;
        wb.uiEditMode = false;
    } else {
        wb.uiEditMode = Boolean(wb.uiEditMode);
    }
    wb.uiViewport = wb.uiViewport && typeof wb.uiViewport === 'object' ? wb.uiViewport : {};
    wb.uiViewport.fit = wb.uiViewport.fit !== false;
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
    wb.uiRuntime = wb.uiRuntime && typeof wb.uiRuntime === 'object' ? wb.uiRuntime : {};
    wb.uiRuntime.elements = Array.isArray(wb.uiRuntime.elements) ? wb.uiRuntime.elements : [];
    wb.uiRuntime.lastScreenUrl = safeString(wb.uiRuntime.lastScreenUrl);
    wb.uiRuntime.cleanup = typeof wb.uiRuntime.cleanup === 'function' ? wb.uiRuntime.cleanup : null;
    wb.uiRuntime.previewCleanup = typeof wb.uiRuntime.previewCleanup === 'function' ? wb.uiRuntime.previewCleanup : null;
}

function moduleUiEditorEnsureStyles() {
    if (document.getElementById(MODULE_UI_EDITOR_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = MODULE_UI_EDITOR_STYLE_ID;
    style.textContent = [
        '.module-ui-editor-shell{display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:10px;min-height:780px;}',
        '.module-ui-editor-main{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,390px);gap:10px;align-items:start;}',
        '.module-ui-editor-top,.module-ui-editor-bottom{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid rgba(151,190,255,.24);border-radius:12px;background:rgba(8,14,23,.76);backdrop-filter:blur(2px);}',
        '.module-ui-editor-left,.module-ui-editor-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;}',
        '.module-ui-editor-title{font-size:12px;letter-spacing:.04em;text-transform:uppercase;font-weight:700;color:#edf6ff;}',
        '.module-ui-editor-sub{font-size:11px;color:var(--text-secondary,#a7bdd8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:500px;}',
        '.module-ui-editor-canvas{position:relative;border:1px solid rgba(160,193,238,.24);border-radius:12px;overflow:auto;background:linear-gradient(150deg,rgba(8,14,23,.94),rgba(8,16,28,.9));min-height:580px;padding:10px;display:grid;place-items:center;}',
        '.module-ui-editor-viewport{position:relative;border:1px solid rgba(160,193,238,.3);border-radius:10px;overflow:hidden;background:#fff;box-shadow:0 12px 28px rgba(2,7,12,.48);width:100%;height:100%;min-width:420px;min-height:280px;max-width:100%;max-height:100%;}',
        '.module-ui-editor-viewport.is-free{resize:both;}',
        '.module-ui-editor-frame{display:block;width:100%;height:100%;min-height:0;border:0;background:#fff;}',
        '.module-ui-editor-hint{position:absolute;top:10px;right:10px;z-index:3;pointer-events:none;padding:4px 10px;border-radius:999px;border:1px solid rgba(160,193,238,.28);background:rgba(8,14,23,.84);font-size:11px;color:#d7e9ff;box-shadow:0 0 0 1px rgba(0,0,0,.2) inset;}',
        '.module-ui-editor-viewport-meta{font-size:11px;color:var(--text-secondary,#a7bdd8);}',
        '.module-ui-editor-store{min-width:0;display:grid;gap:10px;grid-template-rows:auto auto 1fr;min-height:100%;}',
        '.module-ui-editor-store-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid rgba(160,193,238,.24);border-radius:12px;background:linear-gradient(180deg,rgba(13,22,37,.85),rgba(10,16,28,.88));}',
        '.module-ui-editor-store-title{font-size:12px;font-weight:700;color:#f0f6ff;letter-spacing:.03em;text-transform:uppercase;white-space:nowrap;}',
        '.module-ui-editor-store-search{max-width:200px;}',
        '.module-ui-editor-store-grid{display:grid;grid-template-columns:1fr;gap:8px;min-width:0;min-height:0;max-height:300px;padding-right:2px;overflow:auto;scrollbar-width:thin;}',
        '.module-ui-editor-store-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;gap:8px;align-items:center;padding:8px 10px;border:1px solid rgba(151,190,255,.22);background:linear-gradient(180deg,rgba(10,16,27,.82),rgba(7,12,20,.84));border-radius:10px;font-size:11px;}',
        '.module-ui-editor-store-row .name{display:flex;align-items:center;gap:7px;font-weight:700;color:#d6ecff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}',
        '.module-ui-editor-pill{display:inline-flex;align-items:center;justify-content:center;height:18px;padding:0 8px;border-radius:999px;background:rgba(110,226,176,.16);color:#bbf6df;border:1px solid rgba(110,226,176,.38);font-size:10px;letter-spacing:.02em;text-transform:uppercase;white-space:nowrap;}',
        '.module-ui-editor-pill-core{background:rgba(151,190,255,.14);border-color:rgba(151,190,255,.36);color:#cae0ff;}',
        '.module-ui-editor-store-row .meta{font-size:10px;color:#9bb0cc;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
        '.module-ui-editor-store-status{font-size:10px;color:#9bb0cc;line-height:1.4;display:flex;align-items:center;min-height:28px;grid-column:1 / -1;}',
        '.module-ui-editor-section-card{display:grid;grid-template-columns:1fr;gap:8px;padding:10px 12px;border:1px solid rgba(160,193,238,.22);border-radius:12px;background:linear-gradient(180deg,rgba(8,14,23,.92),rgba(8,14,23,.7));}',
        '.module-ui-editor-section-title{font-size:10px;font-weight:700;letter-spacing:.04em;color:#d5eaff;text-transform:uppercase;opacity:.96;margin-bottom:4px;}',
        '.module-ui-editor-store-section{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;align-items:end;}',
        '.module-ui-editor-store-section .col2{grid-column:span 2;}',
        '.module-ui-editor-store-section .module-ui-editor-input{border:1px solid rgba(151,190,255,.26);border-radius:8px;background:rgba(6,13,23,.9);color:#e8f2ff;padding:7px 8px;font-size:11px;min-width:120px;max-width:100%;width:100%;box-sizing:border-box;}',
        '.module-ui-editor-store-section textarea{min-height:84px;resize:vertical;}',
        '.module-ui-editor-input::placeholder{color:#95a9c4;}',
        '.module-ui-editor-bottom select{min-width:220px;max-width:360px;}',
        '.module-ui-editor-bottom select,.module-ui-editor-bottom input,.module-ui-editor-btn,.module-ui-editor-store-search{border:1px solid rgba(160,193,238,.24);border-radius:8px;background:rgba(9,15,26,.92);color:var(--text-primary,#ecf2ff);padding:7px 9px;font-size:12px;}',
        '.module-ui-editor-btn{border:1px solid rgba(160,193,238,.28);border-radius:8px;background:rgba(255,255,255,.04);color:var(--text-primary,#eff4ff);padding:7px 10px;font-size:12px;cursor:pointer;transition:.2s ease;background:rgba(255,255,255,.03);}',
        '.module-ui-editor-btn:hover{border-color:rgba(160,193,238,.52);background:rgba(255,255,255,.08);transform:translateY(-1px);}',
        '.module-ui-editor-btn.edit-active{border-color:rgba(110,226,176,.62);background:rgba(110,226,176,.18);}',
        '.module-ui-editor-count{font-size:11px;color:var(--text-secondary,#a7bdd8);}',
        '@media (max-width:1140px){.module-ui-editor-main{grid-template-columns:1fr;}.module-ui-editor-store-grid{max-height:240px;}.module-ui-editor-store-search{max-width:none;width:100%;}}',
        '@media (max-width:900px){.module-ui-editor-top,.module-ui-editor-bottom{flex-direction:column;align-items:flex-start;}.module-ui-editor-sub{max-width:100%;}.module-ui-editor-bottom select{max-width:100%;min-width:0;width:100%;}.module-ui-editor-canvas{min-height:460px;padding:6px;}.module-ui-editor-viewport{min-width:300px;min-height:220px;}.module-ui-editor-store-section{grid-template-columns:1fr;}.module-ui-editor-store-section .col2{grid-column:auto;}}',
    ].join('');
    document.head.appendChild(style);
}

function moduleUiEditorClearRuntime(wb) {
    if (!wb || !wb.uiRuntime || typeof wb.uiRuntime !== 'object') return;
    if (typeof wb.uiRuntime.cleanup === 'function') {
        try {
            wb.uiRuntime.cleanup();
        } catch (_error) {}
    }
    if (typeof wb.uiRuntime.previewCleanup === 'function') {
        try {
            wb.uiRuntime.previewCleanup();
        } catch (_error) {}
    }
    wb.uiRuntime.cleanup = null;
    wb.uiRuntime.previewCleanup = null;
}

function moduleUiEditorClearEditRuntime(wb) {
    if (!wb || !wb.uiRuntime || typeof wb.uiRuntime !== 'object') return;
    if (typeof wb.uiRuntime.cleanup === 'function') {
        try {
            wb.uiRuntime.cleanup();
        } catch (_error) {}
    }
    wb.uiRuntime.cleanup = null;
}

function moduleUiEditorProjectById(wb, idRaw) {
    const id = safeString(idRaw);
    if (!wb || !Array.isArray(wb.uiProjects) || !id) return null;
    return wb.uiProjects.find((project) => safeString(project && project.id) === id) || null;
}

function moduleUiEditorApplyOverrides(doc, project) {
    if (!doc || !project || typeof project !== 'object') return;
    const overrides = project.overrides && typeof project.overrides === 'object' ? project.overrides : {};
    Object.keys(overrides).forEach((selectorRaw) => {
        const selector = safeString(selectorRaw);
        if (!selector) return;
        let node = null;
        try {
            node = doc.querySelector(selector);
        } catch (_error) {
            node = null;
        }
        if (!(node instanceof Element)) return;
        const patch = overrides[selector] && typeof overrides[selector] === 'object' ? overrides[selector] : {};
        if (safeString(patch.position)) node.style.position = safeString(patch.position);
        if (safeString(patch.left)) node.style.left = safeString(patch.left);
        if (safeString(patch.top)) node.style.top = safeString(patch.top);
        if (safeString(patch.width)) node.style.width = safeString(patch.width);
        if (safeString(patch.height)) node.style.height = safeString(patch.height);
        if (safeString(patch.zIndex)) node.style.zIndex = safeString(patch.zIndex);
        if (safeString(patch.margin)) node.style.margin = safeString(patch.margin);
    });
}

function moduleUiEditorExtractElements(doc) {
    if (!doc || !doc.body) return [];
    const rows = [];
    const nodes = doc.body.querySelectorAll('*');
    const view = doc.defaultView || window;
    for (const node of nodes) {
        if (!(node instanceof Element)) continue;
        const style = view.getComputedStyle(node);
        const tag = safeString(node.tagName).toLowerCase();
        if (!tag || tag === 'html' || tag === 'body' || tag === 'head' || tag === 'script'
            || tag === 'style' || tag === 'meta' || tag === 'link' || tag === 'title'
            || tag === 'svg' || tag === 'path' || tag === 'g' || tag === 'noscript'
            || tag === 'template') {
            continue;
        }
        if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
        const rect = node.getBoundingClientRect();
        if (!Number.isFinite(rect.width) || !Number.isFinite(rect.height)) continue;
        if (rect.width < 8 || rect.height < 8) continue;
        if (rect.width > (window.innerWidth * 1.8) && rect.height > (window.innerHeight * 1.8)) continue;
        node.setAttribute('data-ui-editor-target', '1');
        rows.push({
            selector: moduleUiEditorBuildSelector(node),
            tag: safeString(node.tagName).toLowerCase(),
            purpose: moduleUiEditorInferPurpose(node),
            label: safeString(node.textContent).replace(/\\s+/g, ' ').trim().slice(0, 80),
            x: Math.round(rect.left),
            y: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
        });
        if (rows.length >= 1200) break;
    }
    return rows;
}

function moduleUiEditorSaveElementOverride(project, element) {
    if (!project || typeof project !== 'object' || !(element instanceof Element)) return;
    const selector = moduleUiEditorBuildSelector(element);
    if (!selector) return;
    if (!project.overrides || typeof project.overrides !== 'object') {
        project.overrides = {};
    }
    project.overrides[selector] = {
        position: safeString(element.style.position) || 'absolute',
        left: safeString(element.style.left),
        top: safeString(element.style.top),
        width: safeString(element.style.width),
        height: safeString(element.style.height),
        zIndex: safeString(element.style.zIndex) || '10',
        margin: safeString(element.style.margin) || '0',
    };
    project.updatedAt = Date.now();
}

function moduleUiEditorAttachEditMode(frame, wb, project, onMutation) {
    if (!(frame instanceof HTMLIFrameElement) || !wb || !project) return false;
    let doc = null;
    try {
        doc = frame.contentDocument;
    } catch (_error) {
        return false;
    }
    if (!doc || !doc.body) return false;
    moduleUiEditorClearRuntime(wb);

    const inlineStyle = doc.createElement('style');
    inlineStyle.id = MODULE_UI_EDITOR_INLINE_STYLE_ID;
    inlineStyle.textContent = [
        'body.ui-editor-editing [data-ui-editor-target="1"]{outline:1px dashed rgba(75,151,255,.55);outline-offset:1px;cursor:move !important;}',
        'body.ui-editor-editing [data-ui-editor-selected="1"]{outline:2px solid rgba(110,226,176,.95) !important;box-shadow:0 0 0 1px rgba(8,14,23,.8),0 0 0 3px rgba(110,226,176,.32);}',
    ].join('');
    doc.head.appendChild(inlineStyle);
    doc.body.classList.add('ui-editor-editing');

    let selected = null;
    let drag = null;
    const view = doc.defaultView || window;

    const markSelected = (element) => {
        if (selected instanceof Element) selected.removeAttribute('data-ui-editor-selected');
        selected = element instanceof Element ? element : null;
        if (selected instanceof Element) selected.setAttribute('data-ui-editor-selected', '1');
    };

    const pickTarget = (eventTarget) => {
        if (!(eventTarget instanceof Element)) return null;
        const target = eventTarget.closest('[data-ui-editor-target="1"]');
        if (!(target instanceof Element)) return null;
        const tag = safeString(target.tagName).toLowerCase();
        if (tag === 'body' || tag === 'html') return null;
        return target;
    };

    const onClick = (event) => {
        if (!wb.uiEditMode) return;
        const target = pickTarget(event && event.target);
        if (!(target instanceof Element)) return;
        event.preventDefault();
        event.stopPropagation();
        markSelected(target);
    };

    const onMouseDown = (event) => {
        if (!wb.uiEditMode || Number(event.button) !== 0) return;
        const target = pickTarget(event && event.target);
        if (!(target instanceof Element)) return;
        event.preventDefault();
        event.stopPropagation();
        markSelected(target);
        const rect = target.getBoundingClientRect();
        const computed = view.getComputedStyle(target);
        if (safeString(computed.position) === 'static') {
            target.style.position = 'absolute';
            target.style.left = Math.round(rect.left + view.scrollX) + 'px';
            target.style.top = Math.round(rect.top + view.scrollY) + 'px';
            target.style.width = Math.round(rect.width) + 'px';
            target.style.height = Math.round(rect.height) + 'px';
            target.style.margin = '0';
            target.style.zIndex = '10';
        }
        drag = {
            element: target,
            startX: Number(event.clientX) || 0,
            startY: Number(event.clientY) || 0,
            left: parseFloat(target.style.left) || 0,
            top: parseFloat(target.style.top) || 0,
        };
    };

    const onMouseMove = (event) => {
        if (!wb.uiEditMode || !drag || !(drag.element instanceof Element)) return;
        event.preventDefault();
        const left = drag.left + ((Number(event.clientX) || 0) - drag.startX);
        const top = drag.top + ((Number(event.clientY) || 0) - drag.startY);
        drag.element.style.left = Math.round(left) + 'px';
        drag.element.style.top = Math.round(top) + 'px';
    };

    const onMouseUp = (event) => {
        if (!wb.uiEditMode || !drag || !(drag.element instanceof Element)) return;
        event.preventDefault();
        moduleUiEditorSaveElementOverride(project, drag.element);
        drag = null;
        if (typeof onMutation === 'function') onMutation();
    };

    const onSubmit = (event) => {
        if (!wb.uiEditMode) return;
        event.preventDefault();
        event.stopPropagation();
    };

    doc.addEventListener('click', onClick, true);
    doc.addEventListener('mousedown', onMouseDown, true);
    doc.addEventListener('mousemove', onMouseMove, true);
    doc.addEventListener('mouseup', onMouseUp, true);
    doc.addEventListener('submit', onSubmit, true);

    wb.uiRuntime.cleanup = () => {
        doc.removeEventListener('click', onClick, true);
        doc.removeEventListener('mousedown', onMouseDown, true);
        doc.removeEventListener('mousemove', onMouseMove, true);
        doc.removeEventListener('mouseup', onMouseUp, true);
        doc.removeEventListener('submit', onSubmit, true);
        if (selected instanceof Element) selected.removeAttribute('data-ui-editor-selected');
        doc.body.classList.remove('ui-editor-editing');
        doc.querySelectorAll('[data-ui-editor-target]').forEach((node) => {
            if (node instanceof Element) node.removeAttribute('data-ui-editor-target');
        });
        inlineStyle.remove();
    };
    return true;
}

async function moduleUiEditorProjectFromFiles(filesRaw) {
    const files = Array.isArray(filesRaw) ? filesRaw : [];
    if (!files.length) return { ok: false, reason: 'No files selected.' };

    const fileMap = new Map();
    let rootName = 'Imported Project';
    files.forEach((file) => {
        const relative = safeString(file && file.webkitRelativePath) || safeString(file && file.name);
        if (!relative) return;
        const parts = relative.replace(/\\\\/g, '/').split('/').filter(Boolean);
        if (parts.length > 1 && rootName === 'Imported Project') {
            rootName = safeString(parts[0]) || rootName;
        }
        const key = moduleUiEditorNormalizePath(parts.length > 1 ? parts.slice(1).join('/') : parts[0]);
        if (!key) return;
        fileMap.set(key, file);
    });

    const htmlKeys = Array.from(fileMap.keys()).filter((key) => /\\.html?$/i.test(key));
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

    const serialized = '<!doctype html>\\n' + (doc.documentElement ? doc.documentElement.outerHTML : htmlText);
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
    sub.textContent = 'Inspect the live Thomas UI, adjust the selected element, then export a layout snapshot.';
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
    const moduleStoreToggle = document.createElement('button');
    moduleStoreToggle.type = 'button';
    moduleStoreToggle.className = 'module-ui-editor-btn';
    moduleStoreToggle.hidden = true;
    moduleStoreToggle.textContent = 'Hide Modules';
    topRight.appendChild(viewportMeta);
    topRight.appendChild(viewportBtn);
    topRight.appendChild(count);
    topRight.appendChild(saveBtn);
    topRight.appendChild(editBtn);
    topRight.appendChild(moduleStoreToggle);
    top.appendChild(topLeft);
    top.appendChild(topRight);

    const main = document.createElement('section');
    main.className = 'module-ui-editor-main';

    const canvas = document.createElement('section');
    canvas.className = 'module-ui-editor-canvas';
    const viewport = document.createElement('div');
    viewport.className = 'module-ui-editor-viewport';
    const frame = document.createElement('iframe');
    frame.className = 'module-ui-editor-frame';
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-modals');
    frame.setAttribute('title', 'UI Editor Canvas');
    const hint = document.createElement('div');
    hint.className = 'module-ui-editor-hint';
    hint.textContent = 'View mode';
    viewport.appendChild(frame);
    viewport.appendChild(hint);
    canvas.appendChild(viewport);

    const moduleStore = document.createElement('section');
    moduleStore.className = 'module-ui-editor-store';
    moduleStore.hidden = true;

    const storeHead = document.createElement('div');
    storeHead.className = 'module-ui-editor-store-head';
    const storeTitle = document.createElement('div');
    storeTitle.className = 'module-ui-editor-store-title';
    storeTitle.textContent = 'Shell Module Store';
    const storeCount = document.createElement('span');
    storeCount.className = 'module-ui-editor-count';
    const storeSearch = document.createElement('input');
    storeSearch.type = 'text';
    storeSearch.className = 'module-ui-editor-store-search module-ui-editor-input';
    storeSearch.placeholder = 'Search modules';
    moduleStoreToggle.textContent = moduleStore.hidden ? 'Show Modules' : 'Hide Modules';
    const storeHeaderRight = document.createElement('div');
    storeHeaderRight.className = 'module-ui-editor-left';
    storeHeaderRight.appendChild(storeCount);
    storeHeaderRight.appendChild(storeSearch);
    storeHead.appendChild(storeTitle);
    storeHead.appendChild(storeHeaderRight);

    const storeList = document.createElement('div');
    storeList.className = 'module-ui-editor-store-grid';

    const storeForm = document.createElement('div');
    storeForm.className = 'module-ui-editor-section-card';

    const createTitle = document.createElement('div');
    createTitle.className = 'module-ui-editor-section-title';
    createTitle.textContent = 'Create Module';

    const createGrid = document.createElement('div');
    createGrid.className = 'module-ui-editor-store-section';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'module-ui-editor-input';
    nameInput.placeholder = 'Module name';
    const pillInput = document.createElement('input');
    pillInput.type = 'text';
    pillInput.className = 'module-ui-editor-input';
    pillInput.placeholder = 'Pill label';
    const actionsInput = document.createElement('input');
    actionsInput.type = 'text';
    actionsInput.className = 'module-ui-editor-input';
    actionsInput.placeholder = 'Toolbar actions (comma separated)';
    const cardsInput = document.createElement('textarea');
    cardsInput.className = 'module-ui-editor-input';
    cardsInput.placeholder = 'Cards (Title|Text, one per line)';
    const createBtn = document.createElement('button');
    createBtn.type = 'button';
    createBtn.className = 'module-ui-editor-btn';
    createBtn.textContent = 'Create Module';

    const importTitle = document.createElement('div');
    importTitle.className = 'module-ui-editor-section-title';
    importTitle.textContent = 'Import Plugin JSON';
    const importRow = document.createElement('div');
    importRow.className = 'module-ui-editor-store-section';
    const importUrlInput = document.createElement('input');
    importUrlInput.type = 'text';
    importUrlInput.className = 'module-ui-editor-input';
    importUrlInput.placeholder = 'Paste raw GitHub plugin JSON URL';
    const importBtn = document.createElement('button');
    importBtn.type = 'button';
    importBtn.className = 'module-ui-editor-btn';
    importBtn.textContent = 'Import from URL';
    const nameCol = document.createElement('div');
    const pillCol = document.createElement('div');
    const actionsCol = document.createElement('div');
    const cardsCol = document.createElement('div');
    cardsCol.className = 'col2';
    const importCol = document.createElement('div');
    importCol.className = 'col2';
    nameCol.appendChild(nameInput);
    pillCol.appendChild(pillInput);
    actionsCol.appendChild(actionsInput);
    cardsCol.appendChild(cardsInput);
    createGrid.appendChild(nameCol);
    createGrid.appendChild(pillCol);
    createGrid.appendChild(actionsCol);
    createGrid.appendChild(cardsCol);
    createGrid.appendChild(createBtn);

    importCol.appendChild(importUrlInput);
    importCol.appendChild(importBtn);
    importRow.appendChild(importCol);

    const catalogTitle = document.createElement('div');
    catalogTitle.className = 'module-ui-editor-section-title';
    catalogTitle.textContent = 'Marketplace Sync';
    const catalogRow = document.createElement('div');
    catalogRow.className = 'module-ui-editor-store-section';
    const catalogUrlInput = document.createElement('input');
    catalogUrlInput.type = 'text';
    catalogUrlInput.className = 'module-ui-editor-input';
    catalogUrlInput.placeholder = 'Marketplace JSON URL (GitHub raw or public HTTPS)';
    const catalogLoadBtn = document.createElement('button');
