    catalogLoadBtn.type = 'button';
    catalogLoadBtn.className = 'module-ui-editor-btn';
    catalogLoadBtn.textContent = 'Load Catalog';
    const catalogStatus = document.createElement('div');
    catalogStatus.className = 'module-ui-editor-store-status';
    catalogStatus.textContent = 'No marketplace loaded.';
    const catalogUrlCol = document.createElement('div');
    const catalogBtnCol = document.createElement('div');
    const catalogStatusCol = document.createElement('div');
    catalogUrlCol.className = 'col2';
    catalogStatusCol.className = 'col2';
    catalogUrlCol.appendChild(catalogUrlInput);
    catalogBtnCol.appendChild(catalogLoadBtn);
    catalogStatusCol.appendChild(catalogStatus);
    catalogUrlInput.value = moduleUiEditorReadShellPluginMarketplaceUrl();
    if (catalogUrlInput.value) {
        const lastSync = moduleUiEditorReadShellPluginMarketplaceLastSync();
        if (lastSync) {
            catalogStatus.textContent = 'Saved catalog URL. Last synced ' + String((new Date(lastSync)).toLocaleString()) + '. Auto-loading on open.';
        } else {
            catalogStatus.textContent = 'Saved catalog URL. Auto-loading on open.';
        }
    }
    catalogRow.appendChild(catalogUrlCol);
    catalogRow.appendChild(catalogBtnCol);
    catalogRow.appendChild(catalogStatusCol);

    storeForm.appendChild(createTitle);
    storeForm.appendChild(createGrid);
    storeForm.appendChild(importTitle);
    storeForm.appendChild(importRow);
    storeForm.appendChild(catalogTitle);
    storeForm.appendChild(catalogRow);

    moduleStore.appendChild(storeHead);
    moduleStore.appendChild(storeList);
    moduleStore.appendChild(storeForm);

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

    main.appendChild(canvas);
    main.appendChild(moduleStore);
    shell.appendChild(top);
    shell.appendChild(main);
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

    const syncShellModules = () => {
        const catalog = moduleUiEditorReadShellPluginCatalog();
        if (!wb.uiShell || typeof wb.uiShell !== 'object') wb.uiShell = {};
        wb.uiShell.enabledPluginIds = moduleUiEditorNormalizeShellPluginIds(
            Array.isArray(wb.uiShell.enabledPluginIds)
                ? wb.uiShell.enabledPluginIds
                : [],
            catalog,
        );
        return {
            catalog,
            enabled: new Set(wb.uiShell.enabledPluginIds || []),
        };
    };
    let shellModuleSearchText = '';

    const renderShellModules = () => {
        const state = syncShellModules();
        const catalog = state.catalog;
        const enabled = state.enabled;
        const query = safeString(shellModuleSearchText).toLowerCase();
        const visibleCatalog = Array.isArray(catalog)
            ? catalog.filter((module) => {
                if (!query) return true;
                const name = safeString(module && module.name).toLowerCase();
                const id = moduleUiEditorNormalizeShellPluginId(module && module.id).toLowerCase();
                const pill = safeString(module && module.pill).toLowerCase();
                return name.indexOf(query) !== -1 || id.indexOf(query) !== -1 || pill.indexOf(query) !== -1;
            })
            : [];
        storeCount.textContent = String(enabled.size) + ' enabled | ' + String(visibleCatalog.length) + '/' + String(catalog.length) + ' shown';
        storeList.innerHTML = '';
        if (!visibleCatalog.length) {
            const none = document.createElement('div');
            none.className = 'module-ui-editor-store-row';
            none.textContent = query ? 'No modules match your search.' : 'No modules found.';
            storeList.appendChild(none);
            return;
        }
        visibleCatalog.forEach((module) => {
            const id = moduleUiEditorNormalizeShellPluginId(module && module.id);
            const removable = !(module && module.removable === false);
            const row = document.createElement('label');
            row.className = 'module-ui-editor-store-row';

            const check = document.createElement('input');
            check.type = 'checkbox';
            check.checked = enabled.has(id);
            check.addEventListener('change', () => {
                const catalogRows = moduleUiEditorReadShellPluginCatalog();
                const next = Array.from(enabled);
                const active = check.checked
                    ? next.concat([id]).filter(Boolean)
                    : next.filter((candidate) => candidate !== id);
                wb.uiShell.enabledPluginIds = moduleUiEditorNormalizeShellPluginIds(active, catalogRows);
                renderShellModules();
            });

            const name = document.createElement('span');
            name.className = 'name';
            name.textContent = safeString(module && module.name) || id;
            const typeTag = document.createElement('span');
            typeTag.className = removable ? 'module-ui-editor-pill' : 'module-ui-editor-pill module-ui-editor-pill-core';
            typeTag.textContent = removable ? 'plugin' : 'core';
            name.appendChild(typeTag);
            const meta = document.createElement('span');
            meta.className = 'meta';
            const version = safeString(module && module.version);
            const source = safeString(module && module.source);
            const details = [];
            details.push('ID: ' + id);
            if (version) details.push('v' + version);
            if (source) details.push(source);
            meta.textContent = details.join(' • ');
            if (source) meta.title = source;

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'module-ui-editor-btn';
            removeBtn.textContent = 'Remove';
            removeBtn.hidden = !removable;
            if (removable) {
                removeBtn.addEventListener('click', () => {
                    const catalogRows = moduleUiEditorReadShellPluginCatalog();
                    const nextRows = catalogRows.filter((row) => moduleUiEditorNormalizeShellPluginId(row && row.id) !== id);
                    moduleUiEditorWriteShellPluginCatalog(nextRows);
                    wb.uiShell.enabledPluginIds = moduleUiEditorNormalizeShellPluginIds(
                        (Array.isArray(wb.uiShell.enabledPluginIds) ? wb.uiShell.enabledPluginIds : []).filter((entry) => moduleUiEditorNormalizeShellPluginId(entry) !== id),
                        moduleUiEditorReadShellPluginCatalog(),
                    );
                    renderShellModules();
                });
            }

            row.appendChild(check);
            row.appendChild(name);
            row.appendChild(meta);
            row.appendChild(removeBtn);
            storeList.appendChild(row);
        });
    };

    const addOrUpdateModuleFromData = (payload) => {
        const normalized = moduleUiEditorNormalizeShellPlugin(payload);
        if (!normalized) {
            notifyUser('Invalid module payload.', { tone: 'warn', durationMs: 1800, debugKind: 'app-builder' });
            return false;
        }
        const catalog = moduleUiEditorReadShellPluginCatalog();
        let id = normalized.id;
        while (catalog.some((item) => moduleUiEditorNormalizeShellPluginId(item && item.id) === id)) {
            id = moduleUiEditorNormalizeShellPluginId(id + '-' + String(Date.now()).slice(-4));
            normalized.id = id;
        }
        catalog.push(normalized);
        moduleUiEditorWriteShellPluginCatalog(catalog);
        wb.uiShell.enabledPluginIds = moduleUiEditorNormalizeShellPluginIds(
            (Array.isArray(wb.uiShell.enabledPluginIds) ? wb.uiShell.enabledPluginIds : []).concat([id]),
            moduleUiEditorReadShellPluginCatalog(),
        );
        renderShellModules();
        return true;
    };

    const installFromUrl = async () => {
        const url = safeString(importUrlInput.value);
        if (!url) {
            notifyUser('Paste a plugin JSON URL.', { tone: 'warn', durationMs: 1800, debugKind: 'app-builder' });
            return;
        }
        importBtn.disabled = true;
        importBtn.textContent = 'Loading...';
        try {
            const result = await moduleUiEditorFetchShellPluginFromUrl(url);
            if (!result.ok || !result.plugin) {
                notifyUser(result.reason || 'Could not import module.', { tone: 'warn', durationMs: 2200, debugKind: 'app-builder' });
                return;
            }
            if (addOrUpdateModuleFromData(result.plugin)) {
                importUrlInput.value = '';
                notifyUser('Module imported.', { tone: 'success', durationMs: 1700, debugKind: 'app-builder' });
            }
        } finally {
            importBtn.disabled = false;
            importBtn.textContent = 'Import from URL';
        }
    };

    const syncMarketplaceCatalog = async ({ auto = false } = {}) => {
        const url = safeString(catalogUrlInput.value);
        if (!url) {
            if (!auto) {
                notifyUser('Paste a marketplace manifest URL.', { tone: 'warn', durationMs: 1800, debugKind: 'app-builder' });
            }
            return;
        }
        catalogLoadBtn.disabled = true;
        catalogLoadBtn.textContent = 'Loading...';
        catalogStatus.textContent = auto ? 'Auto-loading marketplace...' : 'Loading marketplace...';
        try {
            const result = await moduleUiEditorFetchShellPluginManifestFromUrl(url);
            if (!result.ok || !Array.isArray(result.rows) || !result.rows.length) {
                const reason = safeString(result && result.reason) || 'Could not load marketplace.';
                catalogStatus.textContent = reason;
                if (!auto) {
                    notifyUser(reason, { tone: 'warn', durationMs: 2200, debugKind: 'app-builder' });
                }
                return;
            }
            const merged = moduleUiEditorMergeShellPluginCatalogFromManifest(result.source, result.rows);
            if (!merged.ok) {
                const reason = 'Could not sync marketplace modules.';
                catalogStatus.textContent = reason;
                if (!auto) {
                    notifyUser(reason, { tone: 'warn', durationMs: 2200, debugKind: 'app-builder' });
                }
                return;
            }
            moduleUiEditorWriteShellPluginMarketplaceUrl(result.source);
            catalogUrlInput.value = result.source;
            const nextTotal = Number(result.rows.length);
            const added = Number(merged.added) || 0;
            const updated = Number(merged.updated) || 0;
            const syncedAtTs = Date.now();
            const syncedAt = new Date(syncedAtTs).toLocaleString();
            moduleUiEditorWriteShellPluginMarketplaceLastSync(syncedAtTs);
            catalogStatus.textContent = 'Loaded ' + String(nextTotal) + ' modules (' + String(added) + ' new, ' + String(updated) + ' updated). Last synced ' + syncedAt;
            renderShellModules();
            if (!auto) {
                notifyUser('Marketplace synced: ' + String(added + updated) + ' plugin(s) applied.', { tone: 'success', durationMs: 1800, debugKind: 'app-builder' });
            }
        } finally {
            catalogLoadBtn.disabled = false;
            catalogLoadBtn.textContent = 'Load Catalog';
        }
    };

    createBtn.addEventListener('click', () => {
        const name = safeString(nameInput.value);
        if (!name) {
            notifyUser('Name is required to create a module.', { tone: 'warn', durationMs: 1700, debugKind: 'app-builder' });
            return;
        }
        const created = {
            id: moduleUiEditorNormalizeShellPluginId(name),
            name,
            pill: safeString(pillInput.value) || safeString(name).toLowerCase(),
            toolbarActions: safeString(actionsInput.value)
                .split(',')
                .map((action) => safeString(action).trim())
                .filter(Boolean),
            cards: moduleUiEditorParseShellPluginCards(cardsInput.value),
            removable: true,
        };
        if (addOrUpdateModuleFromData(created)) {
            nameInput.value = '';
            pillInput.value = '';
            actionsInput.value = '';
            cardsInput.value = '';
            notifyUser('Module added.', { tone: 'success', durationMs: 1500, debugKind: 'app-builder' });
        }
    });
    importBtn.addEventListener('click', () => {
        void installFromUrl();
    });
    catalogLoadBtn.addEventListener('click', () => {
        void syncMarketplaceCatalog();
    });
    storeSearch.addEventListener('input', () => {
        shellModuleSearchText = safeString(storeSearch.value);
        renderShellModules();
    });

    moduleStoreToggle.addEventListener('click', () => {
        if (!wb.uiShell || typeof wb.uiShell !== 'object') wb.uiShell = {};
        moduleStore.hidden = !moduleStore.hidden;
        wb.uiShell.storeOpen = !moduleStore.hidden;
        moduleStoreToggle.textContent = moduleStore.hidden ? 'Show Modules' : 'Hide Modules';
    });

    const updateEditUi = () => {
        editBtn.textContent = wb.uiEditMode ? 'Done' : 'Edit';
        editBtn.classList.toggle('edit-active', wb.uiEditMode);
        if (wb.uiEditMode) {
            hint.textContent = 'Edit mode active · click any visible element and drag to move.';
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
            project.url = '/';
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

    renderShellModules();
    renderProjectOptions();
    updateViewportUi();
    updateEditUi();
    if (!moduleStore.hidden && catalogUrlInput.value) {
        void syncMarketplaceCatalog({ auto: true });
    }
    loadProject(false);
};
