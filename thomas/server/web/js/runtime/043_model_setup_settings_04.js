function moduleUiEditorReadShellPluginCatalog() {
    try {
        const raw = window.localStorage.getItem(MODULE_UI_EDITOR_PLUGIN_STORE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        const list = Array.isArray(parsed) ? parsed : [];
        const byId = new Map();
        moduleUiEditorDefaultShellPlugins().forEach((row) => {
            const normalized = moduleUiEditorNormalizeShellPlugin(row);
            if (normalized) byId.set(normalized.id, normalized);
        });
        list.forEach((row) => {
            const normalized = moduleUiEditorNormalizeShellPlugin(row);
            if (!normalized) return;
            byId.set(normalized.id, normalized);
        });
        return Array.from(byId.values());
    } catch (_error) {
        return moduleUiEditorDefaultShellPlugins();
    }
}

function moduleUiEditorWriteShellPluginCatalog(rowsRaw) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    try {
        const safeRows = rows.map(moduleUiEditorNormalizeShellPlugin).filter(Boolean);
        const byId = new Map();
        const defaults = moduleUiEditorDefaultShellPlugins();
        defaults.forEach((row) => {
            const normalized = moduleUiEditorNormalizeShellPlugin(row);
            if (!normalized) return;
            byId.set(normalized.id, normalized);
        });
        safeRows.forEach((row) => {
            if (!row) return;
            byId.set(row.id, row);
        });
        window.localStorage.setItem(MODULE_UI_EDITOR_PLUGIN_STORE_KEY, JSON.stringify(Array.from(byId.values())));
    } catch (_error) {}
}

function moduleUiEditorNormalizeShellPluginIds(rawIds, catalog) {
    const source = Array.isArray(rawIds) ? rawIds : [];
    const registry = new Set();
    const available = Array.isArray(catalog) ? catalog : [];
    const valid = new Set(available.map((row) => safeString(row && row.id).toLowerCase()));
    source.forEach((idRaw) => {
        const id = safeString(idRaw).toLowerCase();
        if (id && valid.has(id)) registry.add(id);
    });
    if (!registry.size && valid.size) {
        const pinned = available.filter((row) => row && row.removable === false);
        if (pinned.length) {
            pinned.forEach((row) => {
                registry.add(safeString(row.id).toLowerCase());
            });
            return Array.from(registry);
        }
        available.forEach((row) => {
            const rowId = safeString(row && row.id).toLowerCase();
            if (rowId) registry.add(rowId);
        });
    }
    return Array.from(registry);
}

function moduleUiEditorParseShellPluginCards(rawCards) {
    const parsed = safeString(rawCards)
        .split('\n')
        .map((row) => safeString(row).trim())
        .filter(Boolean)
        .slice(0, 6);
    const cards = parsed.map((line) => {
        const divider = line.indexOf('|');
        if (divider === -1) {
            return { title: line, text: '' };
        }
        const title = safeString(line.slice(0, divider)).trim();
        const text = safeString(line.slice(divider + 1)).trim();
        return {
            title: title || 'Module',
            text: text || 'Custom module shell panel.',
        };
    });
    if (cards.length) return cards;
    return [{ title: 'Module', text: 'Custom module shell panel.' }];
}

function moduleUiEditorNormalizeGitHubRawUrl(urlRaw) {
    const url = safeString(urlRaw);
    if (!url) return '';
    if (url.includes('raw.githubusercontent.com')) return url;
    if (/^https?:\/\/github\.com\//i.test(url) && /\/blob\//i.test(url)) {
        return url
            .replace('https://github.com/', 'https://raw.githubusercontent.com/')
            .replace('/blob/', '/');
    }
    return url;
}

async function moduleUiEditorFetchShellPluginFromUrl(urlRaw) {
    const sourceCheck = moduleUiEditorNormalizeShellPluginBootstrapSource(urlRaw);
    if (!sourceCheck.ok) {
        return { ok: false, reason: sourceCheck.reason };
    }
    const source = sourceCheck.source;
    try {
        const response = await fetch(source, {
            method: 'GET',
            mode: 'cors',
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            return { ok: false, reason: 'Could not fetch plugin from URL.' };
        }
        const payload = await response.json();
        const plugin = moduleUiEditorNormalizeShellPlugin(payload);
        if (!plugin) return { ok: false, reason: 'Invalid plugin payload.' };
        return { ok: true, plugin, source };
    } catch (_error) {
        return { ok: false, reason: 'Failed to parse plugin payload.' };
    }
}

function moduleUiEditorExtractShellPluginManifestEntries(payload) {
    if (!payload || typeof payload !== 'object') return [];
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload.plugins)) return payload.plugins;
    if (Array.isArray(payload.modules)) return payload.modules;
    if (Array.isArray(payload.features)) return payload.features;
    if (payload.id || payload.name || payload.pill || payload.cards) return [payload];
    return [];
}

async function moduleUiEditorFetchShellPluginManifestFromUrl(urlRaw) {
    const sourceCheck = moduleUiEditorNormalizeShellPluginBootstrapSource(urlRaw);
    if (!sourceCheck.ok) {
        return { ok: false, reason: sourceCheck.reason };
    }
    const source = sourceCheck.source;
    try {
        const response = await fetch(source, {
            method: 'GET',
            mode: 'cors',
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            return { ok: false, reason: 'Could not fetch marketplace manifest.' };
        }
        const payload = await response.json();
        const rawRows = moduleUiEditorExtractShellPluginManifestEntries(payload);
        const normalizedRows = Array.isArray(rawRows)
            ? rawRows.map((row) => moduleUiEditorNormalizeShellPlugin(row)).filter(Boolean)
            : [];
        if (!normalizedRows.length) {
            return { ok: false, reason: 'Manifest contains no valid modules.' };
        }
        return { ok: true, source, rows: normalizedRows };
    } catch (_error) {
        return { ok: false, reason: 'Failed to parse marketplace manifest.' };
    }
}

function moduleUiEditorMergeShellPluginCatalogFromManifest(sourceRaw, rowsRaw) {
    const sourceCheck = moduleUiEditorNormalizeShellPluginBootstrapSource(sourceRaw);
    const source = sourceCheck.ok ? sourceCheck.source : '';
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    const defaults = moduleUiEditorDefaultShellPlugins()
        .map((row) => moduleUiEditorNormalizeShellPlugin(row))
        .filter(Boolean);
    const defaultIds = new Set(defaults.map((row) => safeString(row && row.id)));
    const byId = new Map();
    let added = 0;
    let updated = 0;

    defaults.forEach((row) => {
        if (!row || !row.id) return;
        byId.set(row.id, row);
    });

    moduleUiEditorReadShellPluginCatalog().forEach((row) => {
        const normalized = moduleUiEditorNormalizeShellPlugin(row);
        if (!normalized || !normalized.id) return;
        if (defaultIds.has(normalized.id)) return;
        byId.set(normalized.id, normalized);
    });

    rows.forEach((row) => {
        if (!row || typeof row !== 'object') return;
        const normalized = moduleUiEditorNormalizeShellPlugin(row);
        if (!normalized || !normalized.id) return;
        if (defaultIds.has(normalized.id)) return;
        const id = normalized.id;
        if (!normalized.source) normalized.source = source || '';
        if (source && normalized.source !== source) normalized.source = source;
        if (byId.has(id)) {
            updated += 1;
        } else {
            added += 1;
        }
        byId.set(id, normalized);
    });

    const mergedRows = Array.from(byId.values());
    moduleUiEditorWriteShellPluginCatalog(mergedRows);
    return {
        ok: true,
        source,
        added,
        updated,
        count: mergedRows.length,
    };
}
function moduleUiEditorCssEscape(valueRaw) {
    const value = safeString(valueRaw);
    if (!value) return '';
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(value);
    }
    return value.replace(/[^a-zA-Z0-9_-]/g, '');
}

function moduleUiEditorNormalizePath(pathRaw) {
    return safeString(pathRaw)
        .replace(/\\/g, '/')
        .replace(/^\.\//, '')
        .replace(/^\/+/, '')
        .replace(/\/+/g, '/')
        .toLowerCase();
}

function moduleUiEditorResolvePath(baseDirRaw, relativeRaw) {
    const baseDir = moduleUiEditorNormalizePath(baseDirRaw);
    const relative = safeString(relativeRaw).replace(/\\/g, '/');
    if (!relative) return '';
    if (/^[a-z]+:/i.test(relative) || relative.startsWith('//')) return '';
    if (relative.startsWith('#') || relative.startsWith('mailto:') || relative.startsWith('tel:')) return '';
    const clean = relative.split('#')[0].split('?')[0];
    const parts = clean.startsWith('/')
        ? moduleUiEditorNormalizePath(clean).split('/')
        : (baseDir ? baseDir.split('/') : []).concat(moduleUiEditorNormalizePath(clean).split('/'));
    const resolved = [];
    parts.forEach((partRaw) => {


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

function moduleUiEditorIsElement(valueRaw) {
    return Boolean(valueRaw && typeof valueRaw === 'object' && Number(valueRaw.nodeType) === 1);
}

function moduleUiEditorIsIframeElement(valueRaw) {
    return moduleUiEditorIsElement(valueRaw) && safeString(valueRaw.tagName).toLowerCase() === 'iframe';
}

function moduleUiEditorBuildSelector(element) {
    if (!moduleUiEditorIsElement(element)) return '';
    const parts = [];
    let cursor = element;
    while (moduleUiEditorIsElement(cursor) && safeString(cursor.tagName).toLowerCase() !== 'body') {
        const tag = safeString(cursor.tagName).toLowerCase();
        if (!tag) break;
        const id = safeString(cursor.id);
        if (id) {
            parts.unshift(tag + '#' + moduleUiEditorCssEscape(id));
            break;
        }
        let part = tag;
        const parent = cursor.parentElement;
        if (moduleUiEditorIsElement(parent)) {
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

function moduleUiEditorElementTargetId(element) {
    if (!moduleUiEditorIsElement(element)) return '';
    return safeString(element.getAttribute('data-thomas-id'));
}

function moduleUiEditorBuildTargetKey(targetIdRaw, selectorRaw) {
    const targetId = safeString(targetIdRaw);
    if (targetId) return targetId;
    const selector = safeString(selectorRaw);
    if (!selector) return '';
    return 'selector:' + selector;
}

function moduleUiEditorElementRefFromElement(element) {
    if (!moduleUiEditorIsElement(element)) return { key: '', targetId: '', selector: '' };
    const selector = moduleUiEditorBuildSelector(element);
    const targetId = moduleUiEditorElementTargetId(element);
    return {
        key: moduleUiEditorBuildTargetKey(targetId, selector),
        targetId,
        selector,
    };
}

function moduleUiEditorNormalizeStoredProject(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const id = safeString(raw.id);
    const name = safeString(raw.name);
    const type = safeString(raw.type);
    if (!id || !name || (type !== 'url' && type !== 'srcdoc')) return null;
    const project = {
        id,
        name,
        type,
        updatedAt: Number(raw.updatedAt) || Date.now(),
        overrides: raw.overrides && typeof raw.overrides === 'object' ? raw.overrides : {},
        overridesById: raw.overridesById && typeof raw.overridesById === 'object' ? raw.overridesById : {},
        notesById: raw.notesById && typeof raw.notesById === 'object' ? raw.notesById : {},
    };
    if (type === 'url') {
        project.url = safeString(raw.url) || '/';
    } else {
        project.srcdoc = safeString(raw.srcdoc);
    }
    return project;
}

function moduleUiEditorReadUrlStore() {
    try {
        const raw = window.localStorage.getItem(MODULE_UI_EDITOR_STORE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed
            .map(moduleUiEditorNormalizeStoredProject)
            .filter(Boolean);
    } catch (_error) {
        return [];
    }
}

function moduleUiEditorWriteUrlStore(rowsRaw) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    try {
        const safeRows = rows
            .map(moduleUiEditorNormalizeStoredProject)
            .filter(Boolean)
            .slice(0, 24);
        window.localStorage.setItem(MODULE_UI_EDITOR_STORE_KEY, JSON.stringify(safeRows));
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

function moduleUiEditorThomasPreviewUrl() {
    try {
        const url = new URL(window.location.href);
        url.searchParams.set('ui_editor_preview', '1');
        url.searchParams.set('nav', 'chat');
        return url.pathname + url.search + url.hash;
    } catch (_error) {
        return '/?ui_editor_preview=1&nav=chat';
    }
}

function moduleUiEditorPersistUrlProjects(wb) {
    if (!wb || !Array.isArray(wb.uiProjects)) return;
    const rows = wb.uiProjects
        .filter((project) => {
            const type = safeString(project && project.type);
            return type === 'url' || type === 'srcdoc';
        })
        .map((project) => ({
            id: safeString(project && project.id),
            name: safeString(project && project.name),
            type: safeString(project && project.type),
            url: safeString(project && project.url) || '/',
            srcdoc: safeString(project && project.srcdoc),
            overrides: project && typeof project.overrides === 'object' ? project.overrides : {},
            overridesById: project && typeof project.overridesById === 'object' ? project.overridesById : {},
            notesById: project && typeof project.notesById === 'object' ? project.notesById : {},
            updatedAt: Number(project && project.updatedAt) || Date.now(),
        }))
        .filter((row) => Boolean(row.id) && Boolean(row.name));
    moduleUiEditorWriteUrlStore(rows.slice(0, 24));
}

function moduleUiEditorEnsureState(wb) {
    if (!wb || typeof wb !== 'object') return;
    if (!Array.isArray(wb.uiProjects)) wb.uiProjects = [];
    if (!wb.uiShell || typeof wb.uiShell !== 'object') wb.uiShell = {};
    wb.uiShell.storeOpen = wb.uiShell.storeOpen === true;
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
            url: moduleUiEditorThomasPreviewUrl(),
            overrides: {},
            updatedAt: Date.now(),
        }];
        const stored = moduleUiEditorReadUrlStore();
        wb.uiProjects = defaults;
        stored.forEach((row) => {
            const project = moduleUiEditorNormalizeStoredProject(row);
            if (!project) return;
            const id = safeString(project.id);
            if (wb.uiProjects.some((project) => safeString(project.id) === id)) return;
            wb.uiProjects.push(project);
        });
    }
    const pinnedIndex = wb.uiProjects.findIndex((project) => safeString(project && project.id) === 'ui-project-thomas');
    if (pinnedIndex === -1) {
        wb.uiProjects.unshift({
            id: 'ui-project-thomas',
            name: 'Thomas',
            type: 'url',
            url: moduleUiEditorThomasPreviewUrl(),
            overrides: {},
            updatedAt: Date.now(),
        });
    } else {
        const pinned = wb.uiProjects[pinnedIndex];
        pinned.name = 'Thomas';
        pinned.type = 'url';
        pinned.url = moduleUiEditorThomasPreviewUrl();
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
    wb.uiRuntime.selectedKey = safeString(wb.uiRuntime.selectedKey);
    wb.uiRuntime.savedAt = Number(wb.uiRuntime.savedAt) || 0;
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
        '.module-ui-editor-store-shell{display:grid;gap:10px;min-height:0;}',
        '.module-ui-editor-step-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}',
        '.module-ui-editor-step{padding:9px 10px;border:1px solid rgba(151,190,255,.18);border-radius:10px;background:rgba(9,15,26,.72);display:grid;gap:4px;}',
        '.module-ui-editor-step strong{font-size:11px;color:#eff5ff;}',
        '.module-ui-editor-step span{font-size:10px;color:#9bb0cc;line-height:1.4;}',
        '.module-ui-editor-selection-meta{display:grid;gap:6px;font-size:11px;color:#cfe4ff;}',
        '.module-ui-editor-selection-meta code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;color:#f0f6ff;word-break:break-word;}',
        '.module-ui-editor-field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}',
        '.module-ui-editor-field{display:grid;gap:4px;font-size:11px;color:#9bb0cc;}',
        '.module-ui-editor-field input,.module-ui-editor-field textarea{border:1px solid rgba(151,190,255,.26);border-radius:8px;background:rgba(6,13,23,.9);color:#e8f2ff;padding:7px 8px;font-size:11px;min-width:0;width:100%;box-sizing:border-box;}',
        '.module-ui-editor-field textarea{min-height:82px;resize:vertical;}',
        '.module-ui-editor-selection-actions{display:flex;gap:8px;flex-wrap:wrap;}',
        '.module-ui-editor-element-list{display:grid;gap:6px;max-height:240px;overflow:auto;padding-right:2px;}',
        '.module-ui-editor-element-btn{border:1px solid rgba(151,190,255,.2);border-radius:10px;background:rgba(255,255,255,.03);color:#d7e9ff;padding:8px 10px;text-align:left;display:grid;gap:4px;cursor:pointer;}',
        '.module-ui-editor-element-btn:hover{border-color:rgba(151,190,255,.46);background:rgba(255,255,255,.06);}',
        '.module-ui-editor-element-btn.is-active{border-color:rgba(110,226,176,.58);background:rgba(110,226,176,.14);}',
        '.module-ui-editor-element-btn strong{font-size:11px;color:#f3f8ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
        '.module-ui-editor-element-btn span{font-size:10px;color:#9bb0cc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
        '.module-ui-editor-selection-empty{font-size:11px;color:#97adc9;padding:8px 0;}',
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
        '@media (max-width:900px){.module-ui-editor-top,.module-ui-editor-bottom{flex-direction:column;align-items:flex-start;}.module-ui-editor-sub{max-width:100%;}.module-ui-editor-bottom select{max-width:100%;min-width:0;width:100%;}.module-ui-editor-canvas{min-height:460px;padding:6px;}.module-ui-editor-viewport{min-width:300px;min-height:220px;}.module-ui-editor-store-section,.module-ui-editor-step-grid,.module-ui-editor-field-grid{grid-template-columns:1fr;}.module-ui-editor-store-section .col2{grid-column:auto;}}',
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

function moduleUiEditorFindElementForRef(doc, refRaw, keyRaw) {
    if (!doc || !doc.body) return null;
    const ref = refRaw && typeof refRaw === 'object' ? refRaw : {};
    const targetId = safeString(ref.targetId);
    const selector = safeString(ref.selector);
    const key = safeString(keyRaw) || moduleUiEditorBuildTargetKey(targetId, selector);
    if (key) {
        const byKey = doc.querySelector('[data-ui-editor-target-key="' + moduleUiEditorCssEscape(key) + '"]');
        if (moduleUiEditorIsElement(byKey)) return byKey;
    }
    if (targetId) {
        const byId = doc.querySelector('[data-thomas-id="' + moduleUiEditorCssEscape(targetId) + '"]');
        if (moduleUiEditorIsElement(byId)) return byId;
    }
    if (selector) {
        try {
            const bySelector = doc.querySelector(selector);
            if (moduleUiEditorIsElement(bySelector)) return bySelector;
        } catch (_error) {}
    }
    if (key.startsWith('selector:')) {
        try {
            const byKeySelector = doc.querySelector(key.slice('selector:'.length));
            if (moduleUiEditorIsElement(byKeySelector)) return byKeySelector;
        } catch (_error) {}
    }
    return null;
}

function moduleUiEditorStylePatchFromElement(element) {
    if (!moduleUiEditorIsElement(element)) return {};
    return {
        position: safeString(element.style.position) || 'absolute',
        left: safeString(element.style.left),
        top: safeString(element.style.top),
        width: safeString(element.style.width),
        height: safeString(element.style.height),
        zIndex: safeString(element.style.zIndex) || '10',
        margin: safeString(element.style.margin) || '0',
    };
}

function moduleUiEditorApplyStylePatch(node, patchRaw) {
    if (!moduleUiEditorIsElement(node) || !patchRaw || typeof patchRaw !== 'object') return;
    const patch = patchRaw.styleOverrides && typeof patchRaw.styleOverrides === 'object'
        ? patchRaw.styleOverrides
        : patchRaw;
    if (safeString(patch.position)) node.style.position = safeString(patch.position);
    if (safeString(patch.left)) node.style.left = safeString(patch.left);
    if (safeString(patch.top)) node.style.top = safeString(patch.top);
    if (safeString(patch.width)) node.style.width = safeString(patch.width);
    if (safeString(patch.height)) node.style.height = safeString(patch.height);
    if (safeString(patch.zIndex)) node.style.zIndex = safeString(patch.zIndex);
    if (safeString(patch.margin)) node.style.margin = safeString(patch.margin);
}

function moduleUiEditorReadProjectNotes(project, keyRaw) {
    const key = safeString(keyRaw);
    if (!project || typeof project !== 'object' || !key) return [];
    if (!project.notesById || typeof project.notesById !== 'object') return [];
    const rows = project.notesById[key];
    return Array.isArray(rows) ? rows : [];
}

function moduleUiEditorWriteProjectNote(project, refRaw, textRaw) {
    if (!project || typeof project !== 'object') return;
    const ref = refRaw && typeof refRaw === 'object' ? refRaw : {};
    const key = safeString(ref.key) || moduleUiEditorBuildTargetKey(ref.targetId, ref.selector);
    if (!key) return;
    if (!project.notesById || typeof project.notesById !== 'object') {
        project.notesById = {};
    }
    const text = safeString(textRaw).trim();
    if (!text) {
        delete project.notesById[key];
        project.updatedAt = Date.now();
        return;
    }
    project.notesById[key] = [{
        id: moduleWorkbenchMakeId('ui-note'),
        text,
        status: 'open',
        targetId: safeString(ref.targetId),
        selector: safeString(ref.selector),
        updatedAt: Date.now(),
    }];
    project.updatedAt = Date.now();
}

function moduleUiEditorApplyOverrides(doc, project) {
    if (!doc || !project || typeof project !== 'object') return;
    const byId = project.overridesById && typeof project.overridesById === 'object'
        ? project.overridesById
        : {};
    Object.keys(byId).forEach((keyRaw) => {
        const key = safeString(keyRaw);
        if (!key) return;
        const patch = byId[key] && typeof byId[key] === 'object' ? byId[key] : {};
        const node = moduleUiEditorFindElementForRef(doc, patch, key);
        if (!moduleUiEditorIsElement(node)) return;
        moduleUiEditorApplyStylePatch(node, patch);
    });
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
        if (!moduleUiEditorIsElement(node)) return;
        moduleUiEditorApplyStylePatch(node, overrides[selector]);
    });
}

function moduleUiEditorExtractElements(doc) {
    if (!doc || !doc.body) return [];
    const rows = [];
    const nodes = doc.body.querySelectorAll('*');
    const view = doc.defaultView || window;
    for (const node of nodes) {
        if (!moduleUiEditorIsElement(node)) continue;
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
        const ref = moduleUiEditorElementRefFromElement(node);
        node.setAttribute('data-ui-editor-target', '1');
        if (safeString(ref.key)) node.setAttribute('data-ui-editor-target-key', safeString(ref.key));
        rows.push({
            key: safeString(ref.key),
            targetId: safeString(ref.targetId),
            selector: safeString(ref.selector),
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
    if (!project || typeof project !== 'object' || !moduleUiEditorIsElement(element)) return;
    const ref = moduleUiEditorElementRefFromElement(element);
    if (!safeString(ref.key)) return;
    if (!project.overrides || typeof project.overrides !== 'object') {
        project.overrides = {};
    }
    if (!project.overridesById || typeof project.overridesById !== 'object') {
        project.overridesById = {};
    }
    const styleOverrides = moduleUiEditorStylePatchFromElement(element);
    project.overridesById[ref.key] = {
        key: ref.key,
        targetId: ref.targetId,
        selector: ref.selector,
        styleOverrides,
    };
    if (safeString(ref.selector)) {
        project.overrides[ref.selector] = styleOverrides;
    }
    project.updatedAt = Date.now();
}

function moduleUiEditorDeleteElementOverride(project, keyRaw) {
    if (!project || typeof project !== 'object') return;
    const key = safeString(keyRaw);
    if (!key) return;
    const patch = project.overridesById && typeof project.overridesById === 'object'
        ? project.overridesById[key]
        : null;
    if (patch && safeString(patch.selector) && project.overrides && typeof project.overrides === 'object') {
        delete project.overrides[patch.selector];
    }
    if (project.overridesById && typeof project.overridesById === 'object') {
        delete project.overridesById[key];
    }
    project.updatedAt = Date.now();
}

function moduleUiEditorAttachEditMode(frame, wb, project, onMutation, onSelection) {
    if (!moduleUiEditorIsIframeElement(frame) || !wb || !project) return false;
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

    const ensureEditablePosition = (target) => {
        if (!moduleUiEditorIsElement(target)) return;
        const rect = target.getBoundingClientRect();
        const computed = view.getComputedStyle(target);
        if (safeString(computed.position) !== 'static') return;
        target.style.position = 'absolute';
        target.style.left = Math.round(rect.left + view.scrollX) + 'px';
        target.style.top = Math.round(rect.top + view.scrollY) + 'px';
        target.style.width = Math.round(rect.width) + 'px';
        target.style.height = Math.round(rect.height) + 'px';
        target.style.margin = '0';
        target.style.zIndex = '10';
    };

    const markSelected = (element) => {
        if (moduleUiEditorIsElement(selected)) selected.removeAttribute('data-ui-editor-selected');
        selected = moduleUiEditorIsElement(element) ? element : null;
        if (moduleUiEditorIsElement(selected)) selected.setAttribute('data-ui-editor-selected', '1');
        if (typeof onSelection === 'function') onSelection(selected);
    };

    const pickTarget = (eventTarget) => {
        if (!moduleUiEditorIsElement(eventTarget)) return null;
        const target = eventTarget.closest('[data-ui-editor-target="1"]');
        if (!moduleUiEditorIsElement(target)) return null;
        const tag = safeString(target.tagName).toLowerCase();
        if (tag === 'body' || tag === 'html') return null;
        return target;
    };

    const onClick = (event) => {
        if (!wb.uiEditMode) return;
        const target = pickTarget(event && event.target);
        if (!moduleUiEditorIsElement(target)) return;
        event.preventDefault();
        event.stopPropagation();
        markSelected(target);
    };

    const onMouseDown = (event) => {
        if (!wb.uiEditMode || Number(event.button) !== 0) return;
        const target = pickTarget(event && event.target);
        if (!moduleUiEditorIsElement(target)) return;
        event.preventDefault();
        event.stopPropagation();
        markSelected(target);
        ensureEditablePosition(target);
        drag = {
            element: target,
            startX: Number(event.clientX) || 0,
            startY: Number(event.clientY) || 0,
            left: parseFloat(target.style.left) || 0,
            top: parseFloat(target.style.top) || 0,
        };
    };

    const onMouseMove = (event) => {
        if (!wb.uiEditMode || !drag || !moduleUiEditorIsElement(drag.element)) return;
        event.preventDefault();
        const left = drag.left + ((Number(event.clientX) || 0) - drag.startX);
        const top = drag.top + ((Number(event.clientY) || 0) - drag.startY);
        drag.element.style.left = Math.round(left) + 'px';
        drag.element.style.top = Math.round(top) + 'px';
    };

    const onMouseUp = (event) => {
        if (!wb.uiEditMode || !drag || !moduleUiEditorIsElement(drag.element)) return;
        event.preventDefault();
        moduleUiEditorSaveElementOverride(project, drag.element);
        drag = null;
        if (typeof onMutation === 'function') onMutation();
    };

    const onKeyDown = (event) => {
        if (!wb.uiEditMode || !moduleUiEditorIsElement(selected)) return;
        const key = safeString(event && event.key);
        if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Escape'].includes(key)) return;
        if (key === 'Escape') {
            event.preventDefault();
            markSelected(null);
            return;
        }
        ensureEditablePosition(selected);
        const step = event.shiftKey ? 10 : 1;
        const currentLeft = parseFloat(selected.style.left) || 0;
        const currentTop = parseFloat(selected.style.top) || 0;
        if (key === 'ArrowUp') selected.style.top = String(Math.round(currentTop - step)) + 'px';
        if (key === 'ArrowDown') selected.style.top = String(Math.round(currentTop + step)) + 'px';
        if (key === 'ArrowLeft') selected.style.left = String(Math.round(currentLeft - step)) + 'px';
        if (key === 'ArrowRight') selected.style.left = String(Math.round(currentLeft + step)) + 'px';
        event.preventDefault();
        moduleUiEditorSaveElementOverride(project, selected);
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
    doc.addEventListener('keydown', onKeyDown, true);
    doc.addEventListener('submit', onSubmit, true);

    wb.uiRuntime.cleanup = () => {
        doc.removeEventListener('click', onClick, true);
        doc.removeEventListener('mousedown', onMouseDown, true);
        doc.removeEventListener('mousemove', onMouseMove, true);
        doc.removeEventListener('mouseup', onMouseUp, true);
        doc.removeEventListener('keydown', onKeyDown, true);
        doc.removeEventListener('submit', onSubmit, true);
        if (moduleUiEditorIsElement(selected)) selected.removeAttribute('data-ui-editor-selected');
        doc.body.classList.remove('ui-editor-editing');
        doc.querySelectorAll('[data-ui-editor-target]').forEach((node) => {
            if (moduleUiEditorIsElement(node)) node.removeAttribute('data-ui-editor-target');
        });
        inlineStyle.remove();
    };
    return true;
}

function moduleUiEditorReadFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        if (!(file instanceof Blob)) {
            reject(new Error('Unsupported file payload.'));
            return;
        }
        const reader = new FileReader();
        reader.onload = () => resolve(safeString(reader.result));
        reader.onerror = () => reject(new Error('Could not read asset file.'));
        reader.readAsDataURL(file);
    });
}

