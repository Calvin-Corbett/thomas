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
    const assetMap = new Map();

    const ensureAssetUrl = async (pathRaw) => {
        const normalized = moduleUiEditorNormalizePath(pathRaw);
        if (!normalized || !fileMap.has(normalized)) return '';
        if (assetMap.has(normalized)) return assetMap.get(normalized);
        const url = await moduleUiEditorReadFileAsDataUrl(fileMap.get(normalized));
        assetMap.set(normalized, url);
        return url;
    };

    const rewriteAttr = async (selector, attr) => {
        const nodes = Array.from(doc.querySelectorAll(selector));
        for (const node of nodes) {
            if (!moduleUiEditorIsElement(node)) continue;
            const raw = safeString(node.getAttribute(attr));
            if (!raw) continue;
            if (/^(https?:|data:|blob:|javascript:|mailto:|tel:|#)/i.test(raw)) continue;
            const resolved = raw.startsWith('/')
                ? moduleUiEditorNormalizePath(raw.slice(1))
                : moduleUiEditorResolvePath(baseDir, raw);
            if (!resolved) continue;
            const assetUrl = await ensureAssetUrl(resolved);
            if (!assetUrl) continue;
            node.setAttribute(attr, assetUrl);
        }
    };

    await rewriteAttr('[src]', 'src');
    await rewriteAttr('link[href]', 'href');
    await rewriteAttr('a[href]', 'href');

    const serialized = '<!doctype html>\\n' + (doc.documentElement ? doc.documentElement.outerHTML : htmlText);
    return {
        ok: true,
        project: {
            id: moduleWorkbenchMakeId('ui-project'),
            name: safeString(rootName) || 'Imported Project',
            type: 'srcdoc',
            srcdoc: serialized,
            overrides: {},
            overridesById: {},
            notesById: {},
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
    const draftStatus = document.createElement('span');
    draftStatus.className = 'module-ui-editor-count';
    draftStatus.textContent = 'Drafts stay on this device.';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'module-ui-editor-btn';
    saveBtn.textContent = 'Export Snapshot';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'module-ui-editor-btn';
    const moduleStoreToggle = document.createElement('button');
    moduleStoreToggle.type = 'button';
    moduleStoreToggle.className = 'module-ui-editor-btn';
    moduleStoreToggle.hidden = true;
    moduleStoreToggle.textContent = 'Shell Modules';
    topRight.appendChild(viewportMeta);
    topRight.appendChild(viewportBtn);
    topRight.appendChild(count);
    topRight.appendChild(draftStatus);
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
    frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-modals');
    frame.setAttribute('title', 'UI Editor Canvas');
    const hint = document.createElement('div');
    hint.className = 'module-ui-editor-hint';
    hint.textContent = 'View mode';
    viewport.appendChild(frame);
    viewport.appendChild(hint);
    canvas.appendChild(viewport);

    const moduleStore = document.createElement('section');
    moduleStore.className = 'module-ui-editor-store';

    const workflowCard = document.createElement('section');
    workflowCard.className = 'module-ui-editor-section-card';
    const workflowTitle = document.createElement('div');
    workflowTitle.className = 'module-ui-editor-section-title';
    workflowTitle.textContent = 'Workflow';
    const workflowSteps = document.createElement('div');
    workflowSteps.className = 'module-ui-editor-step-grid';
    workflowSteps.innerHTML = [
        '<article class="module-ui-editor-step"><strong>1. Pick a project</strong><span>Start with live Thomas, or switch to another live URL or imported folder.</span></article>',
        '<article class="module-ui-editor-step"><strong>2. Inspect layers</strong><span>Use the visible layer list to focus the right element.</span></article>',
        '<article class="module-ui-editor-step"><strong>3. Edit safely</strong><span>Drag in canvas or tune numeric fields for precise changes.</span></article>',
        '<article class="module-ui-editor-step"><strong>4. Export</strong><span>Download a JSON snapshot of the current layout and notes.</span></article>',
    ].join('');
    const workflowStatus = document.createElement('div');
    workflowStatus.className = 'module-ui-editor-store-status';
    workflowStatus.textContent = 'Choose a project to start inspecting the current screen.';
    workflowCard.appendChild(workflowTitle);
    workflowCard.appendChild(workflowSteps);
    workflowCard.appendChild(workflowStatus);

    const selectionCard = document.createElement('section');
    selectionCard.className = 'module-ui-editor-section-card';
    const selectionTitle = document.createElement('div');
    selectionTitle.className = 'module-ui-editor-section-title';
    selectionTitle.textContent = 'Selected Element';
    const selectionStatus = document.createElement('div');
    selectionStatus.className = 'module-ui-editor-store-status';
    selectionStatus.textContent = 'Pick a visible layer to inspect it.';
    const selectionMeta = document.createElement('div');
    selectionMeta.className = 'module-ui-editor-selection-meta';
    const selectionFields = document.createElement('div');
    selectionFields.className = 'module-ui-editor-field-grid';
    const selectionActions = document.createElement('div');
    selectionActions.className = 'module-ui-editor-selection-actions';
    const elementListTitle = document.createElement('div');
    elementListTitle.className = 'module-ui-editor-section-title';
    elementListTitle.textContent = 'Visible Layers';
    const elementList = document.createElement('div');
    elementList.className = 'module-ui-editor-element-list';

    const createNumberField = (labelText) => {
        const wrap = document.createElement('label');
        wrap.className = 'module-ui-editor-field';
        const label = document.createElement('span');
        label.textContent = labelText;
        const input = document.createElement('input');
        input.type = 'number';
        wrap.appendChild(label);
        wrap.appendChild(input);
        return { wrap, input };
    };

    const fieldX = createNumberField('X');
    const fieldY = createNumberField('Y');
    const fieldW = createNumberField('Width');
    const fieldH = createNumberField('Height');
    const fieldZ = createNumberField('Layer');
    fieldZ.input.step = '1';
    const noteField = document.createElement('label');
    noteField.className = 'module-ui-editor-field';
    const noteLabel = document.createElement('span');
    noteLabel.textContent = 'Notes';
    const noteInput = document.createElement('textarea');
    noteInput.placeholder = 'Record why this element changed.';
    noteField.appendChild(noteLabel);
    noteField.appendChild(noteInput);
    const applySelectionBtn = document.createElement('button');
    applySelectionBtn.type = 'button';
    applySelectionBtn.className = 'module-ui-editor-btn';
    applySelectionBtn.textContent = 'Apply Fields';
    const resetSelectionBtn = document.createElement('button');
    resetSelectionBtn.type = 'button';
    resetSelectionBtn.className = 'module-ui-editor-btn';
    resetSelectionBtn.textContent = 'Reset Override';
    selectionFields.appendChild(fieldX.wrap);
    selectionFields.appendChild(fieldY.wrap);
    selectionFields.appendChild(fieldW.wrap);
    selectionFields.appendChild(fieldH.wrap);
    selectionFields.appendChild(fieldZ.wrap);
    selectionFields.appendChild(noteField);
    selectionActions.appendChild(applySelectionBtn);
    selectionActions.appendChild(resetSelectionBtn);
    selectionCard.appendChild(selectionTitle);
    selectionCard.appendChild(selectionStatus);
    selectionCard.appendChild(selectionMeta);
    selectionCard.appendChild(selectionFields);
    selectionCard.appendChild(selectionActions);
    selectionCard.appendChild(elementListTitle);
    selectionCard.appendChild(elementList);

    const moduleCatalog = document.createElement('section');
    moduleCatalog.className = 'module-ui-editor-store-shell';
    moduleCatalog.hidden = Boolean(wb.uiShell && wb.uiShell.storeOpen !== true);

    const storeHead = document.createElement('div');
    storeHead.className = 'module-ui-editor-store-head';
    const storeTitle = document.createElement('div');
    storeTitle.className = 'module-ui-editor-store-title';
    storeTitle.textContent = 'Shell Modules';
    const storeCount = document.createElement('span');
    storeCount.className = 'module-ui-editor-count';
    const storeSearch = document.createElement('input');
    storeSearch.type = 'text';
    storeSearch.className = 'module-ui-editor-store-search module-ui-editor-input';
    storeSearch.placeholder = 'Search modules';
    moduleStoreToggle.textContent = moduleCatalog.hidden ? 'Show Shell Modules' : 'Hide Shell Modules';
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

    moduleCatalog.appendChild(storeHead);
    moduleCatalog.appendChild(storeList);
    moduleCatalog.appendChild(storeForm);
    moduleStore.appendChild(workflowCard);
    moduleStore.appendChild(selectionCard);

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
    const currentDoc = () => {
        try {
            return frame.contentDocument;
        } catch (_error) {
            return null;
        }
    };
    const setDraftStatus = (messageRaw) => {
        const message = safeString(messageRaw).trim();
        draftStatus.textContent = message || 'Drafts stay on this device.';
    };
    const persistProjects = (messageRaw) => {
        moduleUiEditorPersistUrlProjects(wb);
        wb.uiRuntime.savedAt = Date.now();
        if (safeString(messageRaw)) {
            setDraftStatus(messageRaw);
            return;
        }
        setDraftStatus('Draft saved ' + new Date(wb.uiRuntime.savedAt).toLocaleTimeString());
    };
    const currentSelectionMeta = () => {
        const key = safeString(wb.uiRuntime && wb.uiRuntime.selectedKey);
        if (!key) return null;
        const rows = Array.isArray(wb.uiRuntime && wb.uiRuntime.elements) ? wb.uiRuntime.elements : [];
        return rows.find((row) => safeString(row && row.key) === key) || null;
    };
    const currentSelectionElement = () => {
        const doc = currentDoc();
        const project = currentProject();
        const key = safeString(wb.uiRuntime && wb.uiRuntime.selectedKey);
        if (!doc || !project || !key) return null;
        const patch = project.overridesById && typeof project.overridesById === 'object'
            ? project.overridesById[key]
            : null;
        return moduleUiEditorFindElementForRef(doc, patch || currentSelectionMeta(), key);
    };
    const updateWorkflowUi = () => {
        const project = currentProject();
        const selection = currentSelectionMeta();
        if (!project) {
            workflowStatus.textContent = 'Choose a project to start inspecting the current screen.';
            return;
        }
        const type = safeString(project.type);
        const projectLabel = safeString(project.id) === 'ui-project-thomas'
            ? 'Live Thomas UI'
            : (type === 'url' ? 'Live URL target' : 'Imported folder');
        const selectionLabel = selection
            ? ' Selected: ' + (safeString(selection.targetId) || safeString(selection.label) || safeString(selection.tag))
            : ' No element selected yet.';
        const editHint = type === 'url'
            ? ' Cross-origin pages remain view-only.'
            : ' Same-origin targets support drag and keyboard nudging.';
        workflowStatus.textContent = projectLabel + '.' + selectionLabel + editHint;
    };
    const renderElementList = () => {
        const rows = Array.isArray(wb.uiRuntime && wb.uiRuntime.elements) ? wb.uiRuntime.elements.slice(0, 120) : [];
        const activeKey = safeString(wb.uiRuntime && wb.uiRuntime.selectedKey);
        elementList.innerHTML = '';
        if (!rows.length) {
            const empty = document.createElement('div');
            empty.className = 'module-ui-editor-selection-empty';
            empty.textContent = 'No visible layers detected for this screen.';
            elementList.appendChild(empty);
            return;
        }
        rows.forEach((row) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'module-ui-editor-element-btn' + (safeString(row && row.key) === activeKey ? ' is-active' : '');
            const title = document.createElement('strong');
            title.textContent = safeString(row && row.label) || safeString(row && row.targetId) || safeString(row && row.tag) || 'Untitled layer';
            const meta = document.createElement('span');
            const bits = [
                safeString(row && row.targetId) || safeString(row && row.selector),
                safeString(row && row.purpose),
                String(Math.round(Number(row && row.width) || 0)) + 'x' + String(Math.round(Number(row && row.height) || 0)),
            ].filter(Boolean);
            meta.textContent = bits.join(' | ');
            button.appendChild(title);
            button.appendChild(meta);
            button.addEventListener('click', () => {
                wb.uiRuntime.selectedKey = safeString(row && row.key);
                renderElementList();
                renderSelectionUi();
                updateWorkflowUi();
                const target = currentSelectionElement();
                if (target && typeof target.scrollIntoView === 'function') {
                    try {
                        target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                    } catch (_error) {}
                }
            });
            elementList.appendChild(button);
        });
    };
    const renderSelectionUi = () => {
        const project = currentProject();
        const meta = currentSelectionMeta();
        const element = currentSelectionElement();
        const notes = project && meta ? moduleUiEditorReadProjectNotes(project, meta.key) : [];
        const computed = element ? (element.ownerDocument.defaultView || window).getComputedStyle(element) : null;
        const rect = element ? element.getBoundingClientRect() : null;
        const disabled = !project || !meta || !moduleUiEditorIsElement(element);
        [fieldX.input, fieldY.input, fieldW.input, fieldH.input, fieldZ.input, noteInput, applySelectionBtn, resetSelectionBtn]
            .forEach((control) => { control.disabled = disabled; });
        if (disabled) {
            selectionStatus.textContent = project && meta
                ? 'Selected layer could not be rebound to the live DOM. Reload the project and try again.'
                : (project
                    ? 'Pick a visible layer, then use edit mode or the fields below.'
                    : 'Choose a project to inspect individual layers.');
            selectionMeta.innerHTML = '<div class="module-ui-editor-selection-empty">Nothing selected yet.</div>';
            fieldX.input.value = '';
            fieldY.input.value = '';
            fieldW.input.value = '';
            fieldH.input.value = '';
            fieldZ.input.value = '';
            noteInput.value = '';
            return;
        }
        const boundsX = Math.round(rect ? rect.left : Number(meta.x) || 0);
        const boundsY = Math.round(rect ? rect.top : Number(meta.y) || 0);
        const boundsW = Math.round(rect ? rect.width : Number(meta.width) || 0);
        const boundsH = Math.round(rect ? rect.height : Number(meta.height) || 0);
        const posLeft = parseFloat(element.style.left);
        const posTop = parseFloat(element.style.top);
        const width = parseFloat(element.style.width);
        const height = parseFloat(element.style.height);
        const safeNumberInputValue = (value, fallback) => {
            const numeric = Number.isFinite(value) ? value : fallback;
            return Number.isFinite(numeric) ? String(Math.round(numeric)) : '';
        };
        fieldX.input.value = safeNumberInputValue(posLeft, boundsX);
        fieldY.input.value = safeNumberInputValue(posTop, boundsY);
        fieldW.input.value = safeNumberInputValue(width, boundsW);
        fieldH.input.value = safeNumberInputValue(height, boundsH);
        fieldZ.input.value = safeString(element.style.zIndex) || (computed ? safeString(computed.zIndex) : '') || '10';
        noteInput.value = safeString(notes[0] && notes[0].text);
        selectionStatus.textContent = 'Selected ' + (safeString(meta.targetId) || safeString(meta.tag) || 'element') + '. Use fields for exact edits.';
        selectionMeta.innerHTML = [
            '<div><strong>Key:</strong> <code>' + moduleUiEditorEscapeHtml(safeString(meta.key)) + '</code></div>',
            safeString(meta.targetId)
                ? '<div><strong>Stable ID:</strong> <code>' + moduleUiEditorEscapeHtml(safeString(meta.targetId)) + '</code></div>'
                : '',
            '<div><strong>Selector:</strong> <code>' + moduleUiEditorEscapeHtml(safeString(meta.selector)) + '</code></div>',
            '<div><strong>Purpose:</strong> ' + moduleUiEditorEscapeHtml(safeString(meta.purpose) || 'content') + ' | <strong>Bounds:</strong> ' + String(boundsW) + 'x' + String(boundsH) + ' at ' + String(boundsX) + ',' + String(boundsY) + '</div>',
        ].filter(Boolean).join('');
    };
    const applySelectionFields = () => {
        const project = currentProject();
        const meta = currentSelectionMeta();
        const element = currentSelectionElement();
        if (!project || !meta || !moduleUiEditorIsElement(element)) {
            notifyUser('Select a visible layer first.', { tone: 'warn', durationMs: 1700, debugKind: 'app-builder' });
            return;
        }
        const view = element.ownerDocument.defaultView || window;
        const computed = view.getComputedStyle(element);
        if (safeString(computed.position) === 'static') {
            const rect = element.getBoundingClientRect();
            element.style.position = 'absolute';
            element.style.left = Math.round(rect.left + view.scrollX) + 'px';
            element.style.top = Math.round(rect.top + view.scrollY) + 'px';
            element.style.width = Math.round(rect.width) + 'px';
            element.style.height = Math.round(rect.height) + 'px';
            element.style.margin = '0';
        }
        const maybeNumber = (input) => {
            const value = Number(input && input.value);
            return Number.isFinite(value) ? value : null;
        };
        const nextX = maybeNumber(fieldX.input);
        const nextY = maybeNumber(fieldY.input);
        const nextW = maybeNumber(fieldW.input);
        const nextH = maybeNumber(fieldH.input);
        const nextZ = safeString(fieldZ.input && fieldZ.input.value).trim();
        if (nextX !== null) element.style.left = String(Math.round(nextX)) + 'px';
        if (nextY !== null) element.style.top = String(Math.round(nextY)) + 'px';
        if (nextW !== null) element.style.width = String(Math.max(8, Math.round(nextW))) + 'px';
        if (nextH !== null) element.style.height = String(Math.max(8, Math.round(nextH))) + 'px';
        if (nextZ) element.style.zIndex = nextZ;
        element.style.margin = '0';
        moduleUiEditorSaveElementOverride(project, element);
        moduleUiEditorWriteProjectNote(project, meta, noteInput.value);
        refreshExtraction();
        persistProjects();
        updateWorkflowUi();
        notifyUser('Element override saved.', { tone: 'success', durationMs: 1500, debugKind: 'app-builder' });
    };
    const resetSelectionOverride = () => {
        const project = currentProject();
        const meta = currentSelectionMeta();
        if (!project || !meta) {
            notifyUser('Select a layer first.', { tone: 'warn', durationMs: 1600, debugKind: 'app-builder' });
            return;
        }
        moduleUiEditorDeleteElementOverride(project, meta.key);
        moduleUiEditorWriteProjectNote(project, meta, noteInput.value);
        persistProjects();
        loadProject(false);
        notifyUser('Override removed for selected element.', { tone: 'info', durationMs: 1700, debugKind: 'app-builder' });
    };

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
        updateWorkflowUi();
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
            meta.textContent = details.join('  ');
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
        moduleCatalog.hidden = !moduleCatalog.hidden;
        wb.uiShell.storeOpen = !moduleCatalog.hidden;
        persistProjects();
        moduleStoreToggle.textContent = moduleCatalog.hidden ? 'Show Shell Modules' : 'Hide Shell Modules';
    });

    const updateEditUi = () => {
        editBtn.textContent = wb.uiEditMode ? 'Done' : 'Edit';
        editBtn.classList.toggle('edit-active', wb.uiEditMode);
        if (wb.uiEditMode) {
            hint.textContent = 'Edit mode active - click any visible element, drag it, or use arrow keys to nudge.';
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
            renderElementList();
            renderSelectionUi();
            updateWorkflowUi();
            return;
        }
        wb.uiRuntime.elements = moduleUiEditorExtractElements(doc);
        count.textContent = String(wb.uiRuntime.elements.length) + ' elements';
        try {
            wb.uiRuntime.lastScreenUrl = safeString(frame.contentWindow && frame.contentWindow.location && frame.contentWindow.location.href);
        } catch (_error) {
            wb.uiRuntime.lastScreenUrl = '';
        }
        if (safeString(wb.uiRuntime.selectedKey) && !wb.uiRuntime.elements.some((row) => safeString(row && row.key) === safeString(wb.uiRuntime.selectedKey))) {
            wb.uiRuntime.selectedKey = '';
        }
        renderElementList();
        renderSelectionUi();
        updateWorkflowUi();
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
            selected_key: safeString(wb.uiRuntime.selectedKey),
            position_overrides: project && typeof project.overrides === 'object' ? project.overrides : {},
            overrides_by_target: project && typeof project.overridesById === 'object' ? project.overridesById : {},
            notes_by_target: project && typeof project.notesById === 'object' ? project.notesById : {},
        };
        const json = JSON.stringify(payload, null, 2);
        const fileName = (safeString(project.name) || 'ui-editor-layout')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '') || 'ui-editor-layout';
        try {
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = fileName + '.layout.json';
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (_error) {}
        moduleWorkbenchCopyJson(payload, 'UI Editor Layout Data');
        persistProjects('Exported snapshot ' + new Date().toLocaleTimeString());
        notifyUser('Layout snapshot downloaded and copied.', { tone: 'success', durationMs: 1800, debugKind: 'app-builder' });
    };

    frame.addEventListener('load', () => {
        const project = currentProject();
        if (!project) {
            count.textContent = '0 elements';
            renderElementList();
            renderSelectionUi();
            updateWorkflowUi();
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
            renderElementList();
            renderSelectionUi();
            updateWorkflowUi();
            return;
        }
        moduleUiEditorApplyOverrides(doc, project);
        refreshExtraction();
        if (wb.uiEditMode) {
            const attached = moduleUiEditorAttachEditMode(frame, wb, project, () => {
                refreshExtraction();
                persistProjects();
            }, (target) => {
                const ref = moduleUiEditorElementRefFromElement(target);
                wb.uiRuntime.selectedKey = safeString(ref.key);
                renderElementList();
                renderSelectionUi();
                updateWorkflowUi();
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
        wb.uiRuntime.selectedKey = '';
        updateEditUi();
        loadProject(false);
        persistProjects();
    });

    editBtn.addEventListener('click', () => {
        wb.uiEditMode = !wb.uiEditMode;
        updateEditUi();
        loadProject(true);
        persistProjects();
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
    applySelectionBtn.addEventListener('click', () => {
        applySelectionFields();
    });
    resetSelectionBtn.addEventListener('click', () => {
        resetSelectionOverride();
    });
    noteInput.addEventListener('change', () => {
        const project = currentProject();
        const meta = currentSelectionMeta();
        if (!project || !meta) return;
        moduleUiEditorWriteProjectNote(project, meta, noteInput.value);
        persistProjects();
        renderSelectionUi();
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
            wb.uiRuntime.selectedKey = '';
            renderProjectOptions();
            updateEditUi();
            loadProject(false);
            persistProjects();
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
        wb.uiProjects = wb.uiProjects.filter((row) => safeString(row && row.id) !== safeString(project.id));
        wb.uiSelectedProjectId = safeString(wb.uiProjects[0] && wb.uiProjects[0].id);
        wb.uiEditMode = false;
        wb.uiRuntime.selectedKey = '';
        persistProjects();
        renderProjectOptions();
        updateEditUi();
        loadProject(false);
        notifyUser('Project removed.', { tone: 'warn', durationMs: 1700, debugKind: 'app-builder' });
    });

    renderShellModules();
    renderProjectOptions();
    updateViewportUi();
    updateEditUi();
    renderElementList();
    renderSelectionUi();
    updateWorkflowUi();
    if (moduleCatalog.isConnected && catalogUrlInput.value) {
        void syncMarketplaceCatalog({ auto: true });
    }
    loadProject(false);
};

// ═══════════════════════════════════════════════════════════════════════════
// RECOVERED FEATURES (2026-03-18)
// These functions were in dead app_parts/ files and never made it to the
// live runtime. Recovered and integrated by audit.
// ═══════════════════════════════════════════════════════════════════════════

const BUILDER_MODE_STORAGE_KEY = 'thomas.builder_mode.enabled';

