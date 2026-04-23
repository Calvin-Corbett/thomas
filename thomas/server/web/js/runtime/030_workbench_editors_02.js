function moduleRenderWorkbenchAppBuilderOss(container, wb) {
    if (!container || !wb) return false;
    if (wb.ossError) return false;
    if (!wb.ossReady || !window.GridStack) {
        moduleWorkbenchRenderEngineLoading(
            container,
            'App Builder Layout Engine',
            'GridStack drag/resize UI builder with component schema export.',
            'Loading GridStack...',
            'Fallback list editor will open if engine loading fails.',
        );
        if (!wb.ossLoading) {
            wb.ossLoading = true;
            void moduleWorkbenchLoadGridStack().then(() => {
                wb.ossReady = true;
                wb.ossLoading = false;
                wb.ossError = '';
                moduleWorkbenchRefreshMode('app_builder');
            }).catch((error) => {
                wb.ossLoading = false;
                wb.ossReady = false;
                wb.ossError = safeString(error?.message) || 'Failed to load GridStack.';
                notifyUser('GridStack failed to load, using fallback builder list.', { tone: 'warn', durationMs: 2300, debugKind: 'app-builder' });
                moduleWorkbenchRefreshMode('app_builder');
            });
        }
        return true;
    }

    if (!Array.isArray(wb.components)) wb.components = [];
    wb.device = safeString(wb.device) === 'mobile' ? 'mobile' : 'desktop';
    wb.selectedId = safeString(wb.selectedId);
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.selectedProjectId = safeString(wb.selectedProjectId);
    wb.previewHtml = safeString(wb.previewHtml);

    const defs = [
        { id: 'table', label: 'Table', w: 4, h: 3 },
        { id: 'form', label: 'Form', w: 4, h: 4 },
        { id: 'chart', label: 'Chart', w: 5, h: 4 },
        { id: 'button', label: 'Button', w: 3, h: 2 },
        { id: 'modal', label: 'Modal', w: 6, h: 5 },
        { id: 'tabs', label: 'Tabs', w: 5, h: 3 },
    ];

    moduleWorkbenchHeader(container, 'App Builder Layout Engine', 'Describe intent and let Thomas generate/edit app layouts while you validate structure and publish readiness.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-app-oss';
    shell.innerHTML = `
        <aside class="module-wb-side-card">
            <h4>Components</h4>
            <div class="module-wb-palette" data-app-palette></div>
            ${moduleWorkbenchRenderProjectControls('app_builder', 'App Projects')}
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-app-action="preview">Preview</button>
                <button type="button" class="module-item-btn" data-app-action="publish">Publish</button>
                <button type="button" class="module-item-btn" data-app-action="export">Export</button>
                <button type="button" class="module-item-btn" data-app-action="export_html">Export HTML</button>
                <button type="button" class="module-item-btn" data-app-action="open_preview">Open Preview</button>
                <button type="button" class="module-item-btn" data-app-action="export_appsmith">Appsmith JSON</button>
                <button type="button" class="module-item-btn" data-app-action="export_budibase">Budibase JSON</button>
                <button type="button" class="module-item-btn" data-app-action="reset">Reset</button>
            </div>
        </aside>
        <section class="module-wb-stage-card">
            <div class="module-wb-stage-head"><span class="module-wb-stage-title">Layout Canvas</span><span class="module-wb-stage-meta" data-app-status></span></div>
            <div class="module-wb-device-switch">
                <button type="button" class="module-item-btn" data-app-device="desktop">Desktop</button>
                <button type="button" class="module-item-btn" data-app-device="mobile">Mobile</button>
            </div>
            <div class="module-wb-gridstack-shell${wb.device === 'mobile' ? ' mobile-mode' : ''}">
                <div class="grid-stack module-wb-gridstack" data-app-grid></div>
            </div>
            <div class="module-wb-preview-frame-wrap">
                <div class="module-wb-stage-head"><span class="module-wb-stage-title">Runtime Preview</span><span class="module-wb-stage-meta">live</span></div>
                <iframe class="module-wb-preview-frame" data-app-preview sandbox="allow-scripts"></iframe>
            </div>
        </section>
        <aside class="module-wb-inspector-card" data-app-inspector></aside>
        ${moduleWorkbenchRenderOssStack('app_builder')}
    `;
    container.appendChild(shell);

    const palette = shell.querySelector('[data-app-palette]');
    const gridEl = shell.querySelector('[data-app-grid]');
    const previewFrame = shell.querySelector('[data-app-preview]');
    const status = shell.querySelector('[data-app-status]');
    const inspector = shell.querySelector('[data-app-inspector]');
    if (!(palette instanceof HTMLElement) || !(gridEl instanceof HTMLElement) || !(previewFrame instanceof HTMLIFrameElement) || !(status instanceof HTMLElement) || !(inspector instanceof HTMLElement)) {
        return false;
    }

    if (wb.ossGrid?.destroy) {
        try {
            wb.ossGrid.destroy(false);
        } catch (_error) {}
        wb.ossGrid = null;
    }

    const byId = (idRaw) => wb.components.find((row) => safeString(row?.id) === safeString(idRaw)) || null;
    const findWidgetById = (idRaw) => {
        const id = safeString(idRaw);
        return Array.from(gridEl.querySelectorAll('.grid-stack-item')).find((element) => safeString(element.getAttribute('gs-id')) === id) || null;
    };
    const safeWidget = (raw, index = 0) => ({
        id: safeString(raw?.id) || `ui-${wb.nextId + index}`,
        type: safeString(raw?.type) || 'table',
        label: safeString(raw?.label) || 'Widget',
        binding: safeString(raw?.binding),
        required: Boolean(raw?.required),
        x: moduleWorkbenchClamp(Number(raw?.x) || 0, 0, 120),
        y: moduleWorkbenchClamp(Number(raw?.y) || 0, 0, 200),
        w: moduleWorkbenchClamp(Number(raw?.w) || 4, 1, 12),
        h: moduleWorkbenchClamp(Number(raw?.h) || 3, 1, 12),
    });
    wb.components = wb.components.map((component, index) => safeWidget(component, index));
    if (!wb.components.length) {
        wb.components.push({
            id: `ui-${wb.nextId++}`,
            type: 'table',
            label: 'Primary Table',
            binding: 'data.table',
            required: false,
            x: 0,
            y: 0,
            w: 5,
            h: 3,
        });
    }

    const widgetMarkup = (component) => `
        <div class="module-wb-app-widget" data-app-widget-id="${escapeHtml(safeString(component.id))}">
            <strong>${escapeHtml(safeString(component.label))}</strong>
            <span>${escapeHtml(safeString(component.type))}</span>
            <small>${escapeHtml(safeString(component.binding) || 'unbound')}</small>
        </div>
    `;

    const grid = window.GridStack.init({
        float: true,
        cellHeight: 84,
        margin: 8,
        disableOneColumnMode: false,
    }, gridEl);
    wb.ossGrid = grid;

    const syncSelection = () => {
        Array.from(gridEl.querySelectorAll('.grid-stack-item')).forEach((item) => {
            const id = safeString(item.getAttribute('gs-id'));
            item.classList.toggle('selected', id === wb.selectedId);
        });
    };
    const refreshWidgetContent = (component) => {
        const item = findWidgetById(component.id);
        if (!item) return;
        const content = item.querySelector('.module-wb-app-widget');
        if (content) {
            content.innerHTML = `<strong>${escapeHtml(safeString(component.label))}</strong><span>${escapeHtml(safeString(component.type))}</span><small>${escapeHtml(safeString(component.binding) || 'unbound')}</small>`;
        }
    };
    const renderInspector = () => {
        const component = byId(wb.selectedId);
        if (!component) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a widget to edit its bindings and dimensions.</p><div class="module-wb-metrics"><div><span>Widgets</span><strong>${wb.components.length}</strong></div><div><span>Device</span><strong>${escapeHtml(wb.device)}</strong></div><div><span>Roles</span><strong>${wb.components.filter((row) => row.required).length}</strong></div></div>`;
            syncSelection();
            return;
        }
        inspector.innerHTML = `
            <h4>${escapeHtml(safeString(component.label))}</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field">Label<input type="text" data-app-prop="label" value="${escapeHtml(safeString(component.label))}" /></label>
                <label class="module-wb-field">Type<select data-app-prop="type">${defs.map((entry) => `<option value="${entry.id}"${component.type === entry.id ? ' selected' : ''}>${entry.label}</option>`).join('')}</select></label>
                <label class="module-wb-field">X<input type="number" data-app-prop="x" min="0" value="${component.x}" /></label>
                <label class="module-wb-field">Y<input type="number" data-app-prop="y" min="0" value="${component.y}" /></label>
                <label class="module-wb-field">W<input type="number" data-app-prop="w" min="1" max="12" value="${component.w}" /></label>
                <label class="module-wb-field">H<input type="number" data-app-prop="h" min="1" max="12" value="${component.h}" /></label>
                <label class="module-wb-field module-wb-field-wide">Binding<input type="text" data-app-prop="binding" value="${escapeHtml(safeString(component.binding))}" placeholder="crm.customers" /></label>
                <label class="module-wb-field module-wb-field-check"><input type="checkbox" data-app-prop="required" ${component.required ? 'checked' : ''} />Require role gate</label>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-app-action="duplicate">Duplicate</button>
                <button type="button" class="module-item-btn" data-app-action="delete">Delete</button>
            </div>
        `;
        syncSelection();
    };
    const renderStatus = () => {
        status.textContent = `${wb.components.length} widget(s) | ${wb.device.toUpperCase()} mode`;
        shell.querySelectorAll('[data-app-device]').forEach((button) => button.classList.toggle('active', safeString(button.dataset.appDevice) === wb.device));
    };
    const renderProjectSelect = () => {
        const select = shell.querySelector('select[data-wb-project-select="app_builder"]');
        if (!(select instanceof HTMLSelectElement)) return;
        const rows = moduleWorkbenchProjectList('app_builder');
        const current = safeString(wb.selectedProjectId);
        select.innerHTML = `<option value="">Select project</option>${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}`;
        select.value = rows.some((row) => safeString(row.id) === current) ? current : '';
    };
    const renderPreview = () => {
        wb.previewHtml = moduleWorkbenchAppRuntimeHtml(wb);
        previewFrame.srcdoc = wb.previewHtml;
    };
    const syncFromGridItems = (itemsRaw) => {
        const items = Array.isArray(itemsRaw) ? itemsRaw : [];
        items.forEach((item) => {
            const id = safeString(item?.id || item?.el?.getAttribute?.('gs-id'));
            const component = byId(id);
            if (!component) return;
            component.x = moduleWorkbenchClamp(Number(item.x) || component.x, 0, 120);
            component.y = moduleWorkbenchClamp(Number(item.y) || component.y, 0, 200);
            component.w = moduleWorkbenchClamp(Number(item.w) || component.w, 1, 12);
            component.h = moduleWorkbenchClamp(Number(item.h) || component.h, 1, 12);
        });
    };

    palette.innerHTML = defs.map((entry) => `<button type="button" class="module-wb-palette-btn" data-app-component="${entry.id}"><strong>${entry.label}</strong><span>${entry.w} x ${entry.h}</span></button>`).join('');

    wb.components.forEach((component) => {
        grid.addWidget({
            id: component.id,
            x: component.x,
            y: component.y,
            w: component.w,
            h: component.h,
            content: widgetMarkup(component),
        });
    });
    if (!wb.selectedId && wb.components[0]) wb.selectedId = safeString(wb.components[0].id);
    grid.column(wb.device === 'mobile' ? 4 : 12, 'moveScale');
    renderStatus();
    renderInspector();
    renderProjectSelect();
    renderPreview();

    grid.on('change', (_event, items) => {
        syncFromGridItems(items);
        renderStatus();
        renderInspector();
        renderPreview();
    });

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const projectActionEl = event.target instanceof Element
            ? event.target.closest('[data-wb-project-action][data-wb-project-mode="app_builder"]')
            : null;
        if (projectActionEl) {
            const action = safeString(projectActionEl.dataset.wbProjectAction).toLowerCase();
            const select = shell.querySelector('select[data-wb-project-select="app_builder"]');
            const input = shell.querySelector('input[data-wb-project-name="app_builder"]');
            const selectedId = safeString(select instanceof HTMLSelectElement ? select.value : wb.selectedProjectId);
            if (action === 'save') {
                const savedId = moduleWorkbenchProjectSave('app_builder', {
                    device: wb.device,
                    components: wb.components,
                }, safeString(input instanceof HTMLInputElement ? input.value : ''));
                wb.selectedProjectId = savedId;
                if (input instanceof HTMLInputElement) input.value = '';
                renderProjectSelect();
                notifyUser('App project saved.', { tone: 'success', durationMs: 1600, debugKind: 'app-builder' });
                return;
            }
            if (action === 'load') {
                if (!selectedId) return;
                const project = moduleWorkbenchProjectGet('app_builder', selectedId);
                if (!project?.payload) return;
                const payload = project.payload;
                const components = Array.isArray(payload.components) ? payload.components : [];
                grid.removeAll(false);
                wb.components = components.map((component, index) => safeWidget(component, index));
                wb.device = safeString(payload.device) === 'mobile' ? 'mobile' : 'desktop';
                wb.components.forEach((component) => {
                    grid.addWidget({
                        id: component.id,
                        x: component.x,
                        y: component.y,
                        w: component.w,
                        h: component.h,
                        content: widgetMarkup(component),
                    });
                });
                wb.selectedId = wb.components[0] ? safeString(wb.components[0].id) : '';
                wb.selectedProjectId = selectedId;
                grid.column(wb.device === 'mobile' ? 4 : 12, 'moveScale');
                shell.querySelector('.module-wb-gridstack-shell')?.classList.toggle('mobile-mode', wb.device === 'mobile');
                renderStatus();
                renderInspector();
                renderPreview();
                renderProjectSelect();
                notifyUser(`Loaded app project: ${safeString(project.name)}.`, { tone: 'success', durationMs: 1800, debugKind: 'app-builder' });
                return;
            }
            if (action === 'delete') {
                if (!selectedId) return;
                if (moduleWorkbenchProjectDelete('app_builder', selectedId)) {
                    wb.selectedProjectId = '';
                    renderProjectSelect();
                    notifyUser('Deleted app project.', { tone: 'warn', durationMs: 1700, debugKind: 'app-builder' });
                }
                return;
            }
        }
        const target = event.target instanceof Element ? event.target.closest('[data-app-component], [data-app-action], [data-app-device], .module-wb-app-widget') : null;
        if (!target) return;
        const componentType = safeString(target.dataset.appComponent);
        const action = safeString(target.dataset.appAction).toLowerCase();
        const device = safeString(target.dataset.appDevice);
        const widgetId = safeString(target.dataset.appWidgetId);
        if (widgetId) {
            wb.selectedId = widgetId;
            renderInspector();
            return;
        }
        if (componentType) {
            const def = defs.find((entry) => entry.id === componentType) || defs[0];
            const component = {
                id: `ui-${wb.nextId++}`,
                type: def.id,
                label: `${def.label} ${wb.nextId - 1}`,
                binding: '',
                required: false,
                x: 0,
                y: 0,
                w: def.w,
                h: def.h,
            };
            wb.components.push(component);
            grid.addWidget({
                id: component.id,
                x: component.x,
                y: component.y,
                w: component.w,
                h: component.h,
                content: widgetMarkup(component),
            });
            wb.selectedId = component.id;
            renderStatus();
            renderInspector();
            renderPreview();
            return;
        }
        if (device) {
            wb.device = device === 'mobile' ? 'mobile' : 'desktop';
            grid.column(wb.device === 'mobile' ? 4 : 12, 'moveScale');
            shell.querySelector('.module-wb-gridstack-shell')?.classList.toggle('mobile-mode', wb.device === 'mobile');
            renderStatus();
            renderPreview();
            return;
        }
        const component = byId(wb.selectedId);
        if (action === 'preview') {
            renderPreview();
            notifyUser('Runtime preview refreshed.', { tone: 'success', durationMs: 1300, debugKind: 'app-builder' });
            return;
        }
        if (action === 'publish') {
            notifyUser('App published to internal preview workspace.', { tone: 'success', durationMs: 1700, debugKind: 'app-builder' });
            return;
        }
        if (action === 'export') {
            moduleWorkbenchCopyJson({
                device: wb.device,
                components: wb.components,
            }, 'App Builder Schema');
            return;
        }
        if (action === 'export_html') {
            renderPreview();
            moduleWorkbenchDownloadText('thomas-app-preview.html', wb.previewHtml, 'text/html;charset=utf-8');
            notifyUser('Exported runtime HTML.', { tone: 'success', durationMs: 1600, debugKind: 'app-builder' });
            return;
        }
        if (action === 'open_preview') {
            renderPreview();
            const blob = new Blob([wb.previewHtml], { type: 'text/html;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank', 'noopener');
            window.setTimeout(() => URL.revokeObjectURL(url), 5000);
            return;
        }
        if (action === 'export_appsmith') {
            moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToAppsmith(wb), 'Appsmith Page JSON');
            return;
        }
        if (action === 'export_budibase') {
            moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToBudibase(wb), 'Budibase App JSON');
            return;
        }
        if (action === 'reset') {
            grid.removeAll(false);
            wb.components = [];
            wb.selectedId = '';
            renderStatus();
            renderInspector();
            renderPreview();
            return;
        }
        if (action === 'duplicate' && component) {
            const copy = {
                ...component,
                id: `ui-${wb.nextId++}`,
                label: `${component.label} Copy`,
                x: component.x + 1,
                y: component.y + 1,
            };
            wb.components.push(copy);
            grid.addWidget({
                id: copy.id,
                x: copy.x,
                y: copy.y,
                w: copy.w,
                h: copy.h,
                content: widgetMarkup(copy),
            });
            wb.selectedId = copy.id;
            renderStatus();
            renderInspector();
            renderPreview();
            return;
        }
        if (action === 'delete' && component) {
            const widget = findWidgetById(component.id);
            if (widget) grid.removeWidget(widget, false);
            wb.components = wb.components.filter((row) => safeString(row.id) !== safeString(component.id));
            wb.selectedId = wb.components[0] ? safeString(wb.components[0].id) : '';
            renderStatus();
            renderInspector();
            renderPreview();
        }
    });

    inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
        const component = byId(wb.selectedId);
        if (!component) return;
        const prop = safeString(target.dataset.appProp);
        if (!prop) return;
        if (prop === 'label' || prop === 'binding') component[prop] = safeString(target.value).slice(0, 120);
        if (prop === 'type') component.type = safeString(target.value);
        if (prop === 'required' && target instanceof HTMLInputElement) component.required = target.checked;
        if (prop === 'x' || prop === 'y' || prop === 'w' || prop === 'h') {
            const limits = prop === 'w' || prop === 'h'
                ? { min: 1, max: 12 }
                : { min: 0, max: 200 };
            component[prop] = moduleWorkbenchClamp(Number(target.value) || component[prop], limits.min, limits.max);
            const widget = findWidgetById(component.id);
            if (widget) {
                grid.update(widget, {
                    x: component.x,
                    y: component.y,
                    w: component.w,
                    h: component.h,
                });
            }
        }
        refreshWidgetContent(component);
        renderStatus();
        renderInspector();
        renderPreview();
    });

    const projectSelect = shell.querySelector('select[data-wb-project-select="app_builder"]');
    if (projectSelect instanceof HTMLSelectElement) {
        projectSelect.addEventListener('change', () => {
            wb.selectedProjectId = safeString(projectSelect.value);
        });
    }

    return true;
}

function moduleRenderWorkbenchAppBuilder(container, wb) {
    if (moduleRenderWorkbenchAppBuilderOss(container, wb)) return;
    if (!container || !wb) return;
    if (!Array.isArray(wb.components)) wb.components = [];
    wb.selectedId = safeString(wb.selectedId);
    wb.device = safeString(wb.device) === 'mobile' ? 'mobile' : 'desktop';
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.selectedProjectId = safeString(wb.selectedProjectId);
    wb.previewHtml = safeString(wb.previewHtml);

    moduleWorkbenchHeader(container, 'App Builder Canvas', 'Guide Thomas-generated app components, bindings, and release-ready schema exports.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-app';
    shell.innerHTML = `
        <aside class="module-wb-side-card"><h4>UI Blocks</h4><div class="module-wb-palette" data-app-palette></div>${moduleWorkbenchRenderProjectControls('app_builder', 'App Projects')}<div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-app-action="preview">Preview</button><button type="button" class="module-item-btn" data-app-action="publish">Publish</button><button type="button" class="module-item-btn" data-app-action="export">Export</button><button type="button" class="module-item-btn" data-app-action="export_html">Export HTML</button><button type="button" class="module-item-btn" data-app-action="open_preview">Open Preview</button><button type="button" class="module-item-btn" data-app-action="export_appsmith">Appsmith JSON</button><button type="button" class="module-item-btn" data-app-action="export_budibase">Budibase JSON</button><button type="button" class="module-item-btn" data-app-action="clear">Clear</button></div></aside>
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Layout</span><span class="module-wb-stage-meta" data-app-status></span></div><div class="module-wb-device-switch"><button type="button" class="module-item-btn" data-app-device="desktop">Desktop</button><button type="button" class="module-item-btn" data-app-device="mobile">Mobile</button></div><div class="module-wb-app-list" data-app-list></div><div class="module-wb-preview-frame-wrap"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Runtime Preview</span><span class="module-wb-stage-meta">live</span></div><iframe class="module-wb-preview-frame" data-app-preview sandbox="allow-scripts"></iframe></div></section>
        <aside class="module-wb-inspector-card" data-app-inspector></aside>
        ${moduleWorkbenchRenderOssStack('app_builder')}
    `;
    container.appendChild(shell);

    const defs = [
        { id: 'table', label: 'Table', w: 220, h: 120 },
        { id: 'form', label: 'Form', w: 220, h: 140 },
        { id: 'chart', label: 'Chart', w: 220, h: 130 },
        { id: 'button', label: 'Button', w: 140, h: 64 },
        { id: 'modal', label: 'Modal', w: 260, h: 170 },
        { id: 'tabs', label: 'Tabs', w: 240, h: 98 },
    ];
    const byId = (id) => wb.components.find((item) => safeString(item.id) === safeString(id)) || null;
    const palette = shell.querySelector('[data-app-palette]');
    const list = shell.querySelector('[data-app-list]');
    const previewFrame = shell.querySelector('[data-app-preview]');
    const status = shell.querySelector('[data-app-status]');
    const inspector = shell.querySelector('[data-app-inspector]');

    const renderPalette = () => { palette.innerHTML = defs.map((entry) => `<button type="button" class="module-wb-palette-btn" data-app-component="${entry.id}"><strong>${entry.label}</strong><span>${entry.w}x${entry.h}</span></button>`).join(''); };
    const renderList = () => { list.innerHTML = wb.components.length ? wb.components.map((item) => `<article class="module-wb-list-item${safeString(item.id) === safeString(wb.selectedId) ? ' selected' : ''}" data-app-item-id="${escapeHtml(safeString(item.id))}"><strong>${escapeHtml(safeString(item.label))}</strong><span>${escapeHtml(`${item.type} | ${item.w}x${item.h} | ${item.binding || 'no binding'}`)}</span></article>`).join('') : '<div class="module-wb-ghost">Add components from the palette.</div>'; };
    const renderInspector = () => {
        const item = byId(wb.selectedId);
        if (!item) { inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a component to configure it.</p><div class="module-wb-metrics"><div><span>Components</span><strong>${wb.components.length}</strong></div><div><span>Device</span><strong>${escapeHtml(wb.device)}</strong></div><div><span>Publish</span><strong>Draft</strong></div></div>`; return; }
        inspector.innerHTML = `<h4>${escapeHtml(safeString(item.label))}</h4><div class="module-wb-field-grid"><label class="module-wb-field">Label<input type="text" data-app-prop="label" value="${escapeHtml(safeString(item.label))}" /></label><label class="module-wb-field">Type<select data-app-prop="type">${defs.map((entry) => `<option value="${entry.id}"${item.type === entry.id ? ' selected' : ''}>${entry.label}</option>`).join('')}</select></label><label class="module-wb-field">Width<input type="number" data-app-prop="w" min="80" value="${Number(item.w) || 80}" /></label><label class="module-wb-field">Height<input type="number" data-app-prop="h" min="40" value="${Number(item.h) || 40}" /></label><label class="module-wb-field module-wb-field-wide">Binding<input type="text" data-app-prop="binding" value="${escapeHtml(safeString(item.binding))}" placeholder="customers.list" /></label><label class="module-wb-field module-wb-field-check"><input type="checkbox" data-app-prop="required" ${item.required ? 'checked' : ''} />Require role gate</label></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-app-item-action="duplicate">Duplicate</button><button type="button" class="module-item-btn" data-app-item-action="delete">Delete</button></div>`;
    };
    const renderProjectSelect = () => {
        const select = shell.querySelector('select[data-wb-project-select="app_builder"]');
        if (!(select instanceof HTMLSelectElement)) return;
        const rows = moduleWorkbenchProjectList('app_builder');
        const current = safeString(wb.selectedProjectId);
        select.innerHTML = `<option value="">Select project</option>${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}`;
        select.value = rows.some((row) => safeString(row.id) === current) ? current : '';
    };
    const renderPreview = () => {
        wb.previewHtml = moduleWorkbenchAppRuntimeHtml(wb);
        if (previewFrame instanceof HTMLIFrameElement) {
            previewFrame.srcdoc = wb.previewHtml;
        }
    };
    const renderStatus = () => { status.textContent = `${wb.components.length} components | ${wb.device.toUpperCase()} preview`; shell.querySelectorAll('[data-app-device]').forEach((button) => button.classList.toggle('active', safeString(button.dataset.appDevice) === wb.device)); list.classList.toggle('mobile-mode', wb.device === 'mobile'); };
    const renderAll = () => { renderList(); renderInspector(); renderStatus(); renderProjectSelect(); renderPreview(); };

    renderPalette();
    renderAll();

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const projectActionEl = event.target instanceof Element
            ? event.target.closest('[data-wb-project-action][data-wb-project-mode="app_builder"]')
            : null;
        if (projectActionEl) {
            const action = safeString(projectActionEl.dataset.wbProjectAction).toLowerCase();
            const select = shell.querySelector('select[data-wb-project-select="app_builder"]');
            const input = shell.querySelector('input[data-wb-project-name="app_builder"]');
            const selectedId = safeString(select instanceof HTMLSelectElement ? select.value : wb.selectedProjectId);
            if (action === 'save') {
                wb.selectedProjectId = moduleWorkbenchProjectSave('app_builder', { device: wb.device, components: wb.components }, safeString(input instanceof HTMLInputElement ? input.value : ''));
                if (input instanceof HTMLInputElement) input.value = '';
                renderAll();
                return;
            }
            if (action === 'load') {
                if (!selectedId) return;
                const project = moduleWorkbenchProjectGet('app_builder', selectedId);
                if (!project?.payload) return;
                wb.device = safeString(project.payload.device) === 'mobile' ? 'mobile' : 'desktop';
                wb.components = Array.isArray(project.payload.components) ? project.payload.components : [];
                wb.selectedId = wb.components[0] ? safeString(wb.components[0].id) : '';
                wb.selectedProjectId = selectedId;
                renderAll();
                return;
            }
            if (action === 'delete') {
                if (!selectedId) return;
                moduleWorkbenchProjectDelete('app_builder', selectedId);
                wb.selectedProjectId = '';
                renderAll();
                return;
            }
        }
        const target = event.target instanceof Element ? event.target.closest('[data-app-component], [data-app-action], [data-app-device], [data-app-item-id], [data-app-item-action]') : null;
        if (!target) return;
        const addType = safeString(target.dataset.appComponent);
        const action = safeString(target.dataset.appAction).toLowerCase();
        const device = safeString(target.dataset.appDevice);
        const itemId = safeString(target.dataset.appItemId);
        const itemAction = safeString(target.dataset.appItemAction).toLowerCase();
        if (addType) {
            const def = defs.find((entry) => entry.id === addType) || defs[0];
            const id = `ui-${wb.nextId++}`;
            wb.components.push({ id, type: def.id, label: def.label, w: def.w, h: def.h, binding: '', required: false });
            wb.selectedId = id;
            renderAll();
            return;
        }
        if (device) { wb.device = device === 'mobile' ? 'mobile' : 'desktop'; renderStatus(); return; }
        if (action) {
            if (action === 'preview') renderAll();
            if (action === 'publish') notifyUser('App builder draft published to internal preview.', { tone: 'success', durationMs: 1700, debugKind: 'app-builder' });
            if (action === 'export') moduleWorkbenchCopyJson({ device: wb.device, components: wb.components }, 'App Builder Schema');
            if (action === 'export_html') { renderPreview(); moduleWorkbenchDownloadText('thomas-app-preview.html', wb.previewHtml, 'text/html;charset=utf-8'); }
            if (action === 'open_preview') {
                renderPreview();
                const blob = new Blob([wb.previewHtml], { type: 'text/html;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                window.open(url, '_blank', 'noopener');
                window.setTimeout(() => URL.revokeObjectURL(url), 5000);
            }
            if (action === 'export_appsmith') moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToAppsmith(wb), 'Appsmith Page JSON');
            if (action === 'export_budibase') moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToBudibase(wb), 'Budibase App JSON');
            if (action === 'clear') { wb.components = []; wb.selectedId = ''; }
            renderAll();
            return;
        }
        if (itemId) wb.selectedId = itemId;
        if (itemAction === 'duplicate') { const item = byId(wb.selectedId); if (item) { const copy = { ...item, id: `ui-${wb.nextId++}`, label: `${item.label} Copy` }; wb.components.push(copy); wb.selectedId = copy.id; } }
        if (itemAction === 'delete') { wb.components = wb.components.filter((item) => safeString(item.id) !== safeString(wb.selectedId)); wb.selectedId = ''; }
        renderAll();
    });

    if (inspector) {
        inspector.addEventListener('input', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
            const item = byId(wb.selectedId);
            if (!item) return;
            const prop = safeString(target.dataset.appProp);
            if (!prop) return;
            if (prop === 'label' || prop === 'binding') item[prop] = safeString(target.value).slice(0, 120);
            if (prop === 'type') item.type = safeString(target.value);
            if (prop === 'w' || prop === 'h') item[prop] = moduleWorkbenchClamp(Number(target.value) || item[prop], prop === 'w' ? 80 : 40, prop === 'w' ? 900 : 700);
            if (prop === 'required' && target instanceof HTMLInputElement) item.required = target.checked;
            renderAll();
        });
    }
}

const MODULE_STUDIO_ASSET_TYPES = Object.freeze([
    { id: 'all', label: 'All assets' },
    { id: 'media', label: 'Audio / Video' },
    { id: 'image', label: 'Images' },
    { id: 'pixel', label: 'Pixel art' },
    { id: 'note', label: 'Notes' },
]);

const MODULE_STUDIO_AUDIO_PRESETS = Object.freeze([
    {
        id: 'podcast_clean',
        label: 'Podcast Clean',
        description: 'Speech denoise + loudness target at -16 LUFS.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=80,lowpass=f=12000,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11" output_podcast.wav',
    },
    {
        id: 'voice_broadcast',
        label: 'Broadcast Voice',
        description: 'Tight dialog chain with compression and limiting.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=90,acompressor=threshold=-18dB:ratio=3:attack=20:release=250,alimiter=limit=0.96,loudnorm=I=-14:TP=-1.0:LRA=9" output_broadcast.wav',
    },
    {
        id: 'cinematic_stems',
        label: 'Cinematic Stems',
        description: 'Dialogue/music/sfx-friendly mastering baseline.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=55,lowpass=f=16000,dynaudnorm=f=150:g=9,loudnorm=I=-18:TP=-2.0:LRA=12" output_stem.wav',
    },
]);

const MODULE_STUDIO_RENDER_PRESETS = Object.freeze([
    {
        id: 'master_1080p',
        label: 'Master 1080p',
        description: 'H.264 archive master with high-quality audio.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -c:v libx264 -preset slow -crf 18 -c:a aac -b:a 320k -movflags +faststart master_1080p.mp4',
    },
    {
        id: 'social_vertical',
        label: 'Social Vertical',
        description: '9:16 export tuned for short-form delivery.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" -c:v libx264 -preset medium -crf 21 -c:a aac -b:a 192k social_vertical.mp4',
    },
    {
        id: 'review_proxy',
        label: 'Review Proxy',
        description: 'Lightweight preview file for fast feedback loops.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -vf "scale=1280:-2" -c:v libx264 -preset veryfast -crf 28 -c:a aac -b:a 128k review_proxy.mp4',
    },
]);

const MODULE_STUDIO_GENERATION_TOOLS = Object.freeze([
    {
        id: 'comfyui',
        label: 'Comfy Studio',
        description: 'Node-based local image generation workflows.',
        command: 'cd ComfyUI && python main.py --listen 127.0.0.1 --port 8188',
    },
    {
        id: 'krita_ai',
        label: 'Krita + AI Plugin',
        description: 'Paint-over + local inpaint concept workflow.',
        command: 'winget install --id KDE.Krita -e',
    },
    {
        id: 'blender_gen',
        label: 'Blender Scripted Render',
        description: 'Scripted turntables and asset renders.',
        command: 'blender -b scene.blend -P render_pipeline.py -a',
    },
]);

function moduleStudioCatalogFind(catalogRaw, idRaw) {
    const catalog = Array.isArray(catalogRaw) ? catalogRaw : [];
    if (!catalog.length) return null;
    const id = safeString(idRaw).toLowerCase();
    return catalog.find((item) => safeString(item?.id).toLowerCase() === id) || catalog[0] || null;
}

function moduleStudioOptionMarkup(rowsRaw, selectedIdRaw) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    const selectedId = safeString(selectedIdRaw).toLowerCase();
    return rows.map((row) => {
        const id = safeString(row?.id).toLowerCase();
        const label = safeString(row?.label) || id || 'option';
        const selected = id === selectedId ? ' selected' : '';
        return `<option value="${escapeHtml(id)}"${selected}>${escapeHtml(label)}</option>`;
    }).join('');
}

function moduleStudioEnsureWorkbenchState(wb) {
    if (!wb || typeof wb !== 'object') return;
    wb.assetQuery = safeString(wb.assetQuery).slice(0, 80);
    const assetType = safeString(wb.assetType).toLowerCase();
    wb.assetType = MODULE_STUDIO_ASSET_TYPES.some((row) => safeString(row.id) === assetType) ? assetType : 'all';
    const audioPreset = safeString(wb.audioPreset).toLowerCase();
    wb.audioPreset = moduleStudioCatalogFind(MODULE_STUDIO_AUDIO_PRESETS, audioPreset)?.id || MODULE_STUDIO_AUDIO_PRESETS[0].id;
    const renderPreset = safeString(wb.renderPreset).toLowerCase();
    wb.renderPreset = moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, renderPreset)?.id || MODULE_STUDIO_RENDER_PRESETS[0].id;
    const generationTool = safeString(wb.generationTool).toLowerCase();
    wb.generationTool = moduleStudioCatalogFind(MODULE_STUDIO_GENERATION_TOOLS, generationTool)?.id || MODULE_STUDIO_GENERATION_TOOLS[0].id;
    wb.generationPrompt = safeString(wb.generationPrompt).slice(0, 220);
    if (!Array.isArray(wb.batchQueue)) wb.batchQueue = [];
    wb.batchQueue = wb.batchQueue
        .filter((item) => item && typeof item === 'object')
        .slice(0, 24);
}

function moduleStudioFilterAssets(wb) {
    const rows = Array.isArray(wb?.assets) ? wb.assets : [];
    const query = safeString(wb?.assetQuery).toLowerCase().trim();
    const type = safeString(wb?.assetType).toLowerCase() || 'all';
    return rows.filter((asset) => {
        const kind = moduleStudioAssetKind(asset);
        if (type !== 'all' && kind !== type) return false;
        if (!query) return true;
        const haystack = `${safeString(asset?.name)} ${safeString(asset?.mime)} ${kind}`.toLowerCase();
        return haystack.includes(query);
    });
}

function moduleStudioAssetCounts(wb) {
    const assets = Array.isArray(wb?.assets) ? wb.assets : [];
    const counts = { total: assets.length, media: 0, image: 0, pixel: 0, note: 0 };
    assets.forEach((asset) => {
        const kind = moduleStudioAssetKind(asset);
        if (kind === 'media' || kind === 'image' || kind === 'pixel' || kind === 'note') {
            counts[kind] += 1;
        }
    });
    return counts;
}

function moduleStudioAudioPresetCommand(wb) {
    const preset = moduleStudioCatalogFind(MODULE_STUDIO_AUDIO_PRESETS, wb?.audioPreset);
    return safeString(preset?.ffmpeg) || MODULE_STUDIO_AUDIO_PRESETS[0].ffmpeg;
}

function moduleStudioRenderPresetCommand(wb) {
    const preset = moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, wb?.renderPreset);
    return safeString(preset?.ffmpeg) || MODULE_STUDIO_RENDER_PRESETS[0].ffmpeg;
}

function moduleStudioGenerationCommand(wb) {
    const tool = moduleStudioCatalogFind(MODULE_STUDIO_GENERATION_TOOLS, wb?.generationTool);
    const prompt = safeString(wb?.generationPrompt) || 'clean robot office concept, isometric, pixel style';
    if (safeString(tool?.id) === 'comfyui') {
        return [
            '# 1) Start Comfy Studio (ComfyUI backend)',
            safeString(tool?.command),
            '# 2) Use this prompt in your workflow',
            prompt,
        ].join('\n');
    }
    if (safeString(tool?.id) === 'blender_gen') {
        return [
            '# Edit render_pipeline.py to read PROMPT env',
            `set PROMPT=${prompt.replace(/\n/g, ' ')}`,
            safeString(tool?.command),
        ].join('\n');
    }
    return safeString(tool?.command) || 'winget install --id KDE.Krita -e';
}

function moduleStudioQueueRenderJob(wb, assetRaw = null) {
    if (!wb || typeof wb !== 'object') return null;
    moduleStudioEnsureWorkbenchState(wb);
    const preset = moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, wb.renderPreset);
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : null;
    const target = safeString(asset?.name) || (wb.timeline?.length ? `Timeline (${wb.timeline.length} clips)` : 'Timeline');
    const row = {
        id: `render-${Date.now()}-${Math.round(Math.random() * 10000)}`,
        name: target,
        preset: safeString(preset?.label) || 'Master 1080p',
        status: 'queued',
        eta: 'pending',
        at: moduleWorkbenchTimeStamp(),
    };
    wb.batchQueue.unshift(row);
    wb.batchQueue = wb.batchQueue.slice(0, 24);
    return row;
}

function moduleStudioDuration(totalRaw) {
    const total = Number(totalRaw) || 0;
    const mins = Math.floor(total / 60);
    const secs = Math.floor(total % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function moduleWorkbenchStudioTimelineToOtio(wb) {
    const timeline = Array.isArray(wb?.timeline) ? wb.timeline : [];
    return {
        OTIO_SCHEMA: 'Timeline.1',
        name: 'Thomas Timeline Export',
        tracks: {
            OTIO_SCHEMA: 'Stack.1',
            children: [
                {
                    OTIO_SCHEMA: 'Track.1',
                    kind: 'Video',
                    children: timeline.map((clip, index) => ({
                        OTIO_SCHEMA: 'Clip.2',
                        name: safeString(clip.name) || `Clip ${index + 1}`,
                        source_range: {
                            OTIO_SCHEMA: 'TimeRange.1',
                            start_time: {
                                OTIO_SCHEMA: 'RationalTime.1',
                                value: Number(clip.start) || 0,
                                rate: 1,
                            },
                            duration: {
                                OTIO_SCHEMA: 'RationalTime.1',
                                value: Number(clip.duration) || 1,
                                rate: 1,
                            },
                        },
                        metadata: {},
                    })),
                },
            ],
        },
    };
}

function moduleWorkbenchStudioFfmpegConcatCommand(wb) {
    const assets = Array.isArray(wb?.assets) ? wb.assets : [];
    const media = assets.filter((asset) => Boolean(safeString(asset.url))).slice(0, 8);
    if (!media.length) {
        return 'ffmpeg -f concat -safe 0 -i clips.txt -c copy output.mp4';
    }
    const lines = media.map((asset) => `file '${safeString(asset.name).replace(/'/g, "\\'")}'`);
    return [
        '# 1) Save this as clips.txt',
        ...lines,
        '# 2) Run concat',
        'ffmpeg -f concat -safe 0 -i clips.txt -c:v libx264 -c:a aac -shortest output.mp4',
    ].join('\n');
}

const MODULE_STUDIO_FORGE_SIZE = 16;
const MODULE_STUDIO_FORGE_SCALE = 14;
const MODULE_STUDIO_FORGE_PALETTE = [
    '#0f1a2b',
    '#1e3351',
    '#2f4e73',
    '#5f8cc0',
    '#89b8f0',
    '#91e1d6',
    '#f2c27f',
    '#f08d7f',
    '#f5f8ff',
];

function moduleStudioAssetKind(assetRaw) {
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : {};
    const explicit = safeString(asset.kind).toLowerCase();
    if (explicit === 'pixel' || explicit === 'image' || explicit === 'media') return explicit;
    if (Array.isArray(asset.pixelData) && asset.pixelData.length) return 'pixel';
    const mime = safeString(asset.mime).toLowerCase();
    if (mime.startsWith('image/')) return 'image';
    if (mime.startsWith('audio/') || mime.startsWith('video/')) return 'media';
    return safeString(asset.url) ? 'media' : 'note';
}

function moduleStudioAssetKindLabel(assetRaw) {
    const kind = moduleStudioAssetKind(assetRaw);
    if (kind === 'pixel') return 'pixel';
    if (kind === 'image') return 'image';
    if (kind === 'media') return 'media';
    return 'note';
}

function moduleStudioCanWaveLoad(assetRaw) {
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : {};
    if (!safeString(asset.url)) return false;
    if (moduleStudioAssetKind(asset) !== 'media') return false;
    const mime = safeString(asset.mime).toLowerCase();
    if (!mime) return true;
    return mime.startsWith('audio/') || mime.startsWith('video/');
}

function moduleStudioPixelBlank(sizeRaw = MODULE_STUDIO_FORGE_SIZE) {
    const size = moduleWorkbenchClamp(Number(sizeRaw) || MODULE_STUDIO_FORGE_SIZE, 8, 32);
    return Array.from({ length: size * size }, () => '');
}

function moduleStudioPixelNormalize(pixelsRaw, sizeRaw = MODULE_STUDIO_FORGE_SIZE) {
    const size = moduleWorkbenchClamp(Number(sizeRaw) || MODULE_STUDIO_FORGE_SIZE, 8, 32);
    const pixels = Array.isArray(pixelsRaw) ? pixelsRaw : [];
    const total = size * size;
    const next = Array.from({ length: total }, (_entry, index) => {
        const value = safeString(pixels[index]).toLowerCase();
        return /^#[0-9a-f]{6}$/.test(value) ? value : '';
    });
    return next;
}

function moduleStudioSeededRandom(seedRaw) {
    let state = (Number(seedRaw) >>> 0) || 1;
    return () => {
        state = (Math.imul(1664525, state) + 1013904223) >>> 0;
        return state / 4294967296;
    };
}

function moduleStudioPixelSet(pixels, size, xRaw, yRaw, colorRaw) {
    const x = moduleWorkbenchClamp(Math.floor(Number(xRaw) || 0), 0, size - 1);
    const y = moduleWorkbenchClamp(Math.floor(Number(yRaw) || 0), 0, size - 1);
    const index = (y * size) + x;
    if (index < 0 || index >= pixels.length) return;
    const color = safeString(colorRaw).toLowerCase();
    pixels[index] = /^#[0-9a-f]{6}$/.test(color) ? color : '';
}

function moduleStudioGeneratePixelPrompt(promptRaw, sizeRaw = MODULE_STUDIO_FORGE_SIZE, paletteRaw = MODULE_STUDIO_FORGE_PALETTE) {
    const size = moduleWorkbenchClamp(Number(sizeRaw) || MODULE_STUDIO_FORGE_SIZE, 8, 32);
    const palette = Array.isArray(paletteRaw) && paletteRaw.length ? paletteRaw : MODULE_STUDIO_FORGE_PALETTE;
    const prompt = safeString(promptRaw).toLowerCase();
    const pixels = moduleStudioPixelBlank(size);
    const seed = officeStableHash(`${prompt}|${size}`) || Date.now();
    const rand = moduleStudioSeededRandom(seed);
    const center = Math.floor(size / 2);
    const dark = safeString(palette[1] || palette[0] || '#1e3351');
    const body = safeString(palette[3] || palette[2] || '#5f8cc0');
    const accent = safeString(palette[6] || palette[5] || '#f2c27f');
    const highlight = safeString(palette[8] || palette[4] || '#f5f8ff');
    const alt = safeString(palette[5] || palette[4] || '#91e1d6');

    const paintMirror = (xRaw, yRaw, color) => {
        const x = moduleWorkbenchClamp(Math.floor(Number(xRaw) || 0), 0, size - 1);
        const y = moduleWorkbenchClamp(Math.floor(Number(yRaw) || 0), 0, size - 1);
        moduleStudioPixelSet(pixels, size, x, y, color);
        moduleStudioPixelSet(pixels, size, (size - 1) - x, y, color);
    };
    const fillMirrorRect = (x0Raw, y0Raw, widthRaw, heightRaw, color) => {
        const x0 = moduleWorkbenchClamp(Math.floor(Number(x0Raw) || 0), 0, size - 1);
        const y0 = moduleWorkbenchClamp(Math.floor(Number(y0Raw) || 0), 0, size - 1);
        const width = Math.max(1, Math.floor(Number(widthRaw) || 1));
        const height = Math.max(1, Math.floor(Number(heightRaw) || 1));
        for (let y = y0; y < y0 + height && y < size; y += 1) {
            for (let x = x0; x < x0 + width && x <= center; x += 1) {
                paintMirror(x, y, color);
            }
        }
    };

    const bodyHalf = Math.max(2, Math.floor(size * (0.16 + (rand() * 0.12))));
    const bodyHeight = Math.max(4, Math.floor(size * (0.34 + (rand() * 0.2))));
    const bodyTop = moduleWorkbenchClamp(Math.floor(size * 0.36), 1, size - 3);
    fillMirrorRect(center - bodyHalf, bodyTop, bodyHalf + 1, bodyHeight, body);

    const headHalf = Math.max(2, bodyHalf - 1);
    const headHeight = Math.max(2, Math.floor(size * (0.16 + (rand() * 0.08))));
    const headTop = moduleWorkbenchClamp(bodyTop - headHeight - 1, 0, size - 3);
    fillMirrorRect(center - headHalf, headTop, headHalf + 1, headHeight, dark);

    const eyeY = moduleWorkbenchClamp(headTop + Math.floor(headHeight / 2), 0, size - 1);
    paintMirror(center - 1, eyeY, highlight);
    paintMirror(center - 2, eyeY, alt);
    paintMirror(center - 1, eyeY + 1, highlight);

    const legY = moduleWorkbenchClamp(bodyTop + bodyHeight, 1, size - 1);
    paintMirror(center - 1, legY, dark);
    paintMirror(center - 2, legY, dark);

    if (/(desk|table|bench|counter|workspace)/.test(prompt)) {
        const top = moduleWorkbenchClamp(Math.floor(size * 0.68), 0, size - 1);
        for (let x = 1; x < size - 1; x += 1) {
            moduleStudioPixelSet(pixels, size, x, top, accent);
            if (x % 3 === 0) moduleStudioPixelSet(pixels, size, x, top + 1, dark);
        }
    }
    if (/(server|rack|datacenter|compute|gpu)/.test(prompt)) {
        const rackTop = moduleWorkbenchClamp(Math.floor(size * 0.24), 0, size - 1);
        const rackBottom = moduleWorkbenchClamp(Math.floor(size * 0.82), 0, size - 1);
        for (let y = rackTop; y <= rackBottom; y += 1) {
            paintMirror(center - 4, y, dark);
            if (y % 3 === 0) paintMirror(center - 3, y, accent);
        }
    }
    if (/(plant|green|nature|tree|garden)/.test(prompt)) {
        const leafY = moduleWorkbenchClamp(Math.floor(size * 0.18), 0, size - 1);
        const leaf = safeString(palette[5] || palette[4] || '#91e1d6');
        paintMirror(center - 2, leafY, leaf);
        paintMirror(center - 3, leafY + 1, leaf);
        paintMirror(center - 1, leafY + 1, leaf);
    }
    if (/(warning|danger|hazard|fire)/.test(prompt)) {
        const hot = safeString(palette[7] || '#f08d7f');
        for (let y = Math.floor(size * 0.58); y < size; y += 1) {
            if (y % 2 === 0) {
                paintMirror(center - 2, y, hot);
                paintMirror(center - 4, y, hot);
            }
        }
    }
    if (/(goal|star|trophy|win)/.test(prompt)) {
        const trophy = safeString(palette[6] || '#f2c27f');
        const y = moduleWorkbenchClamp(Math.floor(size * 0.25), 0, size - 1);
        paintMirror(center - 1, y, trophy);
        paintMirror(center - 2, y + 1, trophy);
        paintMirror(center - 1, y + 2, trophy);
    }
    const sparkleCount = Math.max(4, Math.floor(size * 0.6));
    for (let i = 0; i < sparkleCount; i += 1) {
        const x = Math.floor(rand() * (center + 1));
        const y = Math.floor(rand() * size);
        const color = rand() > 0.6 ? accent : highlight;
        paintMirror(x, y, color);
    }
    return pixels;
}

function moduleStudioEnsureForgeState(wb) {
    if (!wb || typeof wb !== 'object') return null;
    if (!wb.forge || typeof wb.forge !== 'object') wb.forge = {};
    const forge = wb.forge;
    forge.size = MODULE_STUDIO_FORGE_SIZE;
    forge.scale = MODULE_STUDIO_FORGE_SCALE;
    if (!Array.isArray(forge.palette) || !forge.palette.length) {
        forge.palette = [...MODULE_STUDIO_FORGE_PALETTE];
    } else {
        forge.palette = forge.palette
            .map((color) => safeString(color).toLowerCase())
            .filter((color) => /^#[0-9a-f]{6}$/.test(color))
            .slice(0, 18);
        if (!forge.palette.length) forge.palette = [...MODULE_STUDIO_FORGE_PALETTE];
    }
    forge.selectedColor = safeString(forge.selectedColor).toLowerCase();
    if (!forge.palette.includes(forge.selectedColor)) {
        forge.selectedColor = safeString(forge.palette[3] || forge.palette[0] || '#5f8cc0');
    }
    const tool = safeString(forge.tool).toLowerCase();
    forge.tool = tool === 'erase' ? 'erase' : 'paint';
    forge.prompt = safeString(forge.prompt).slice(0, 180);
    forge.draftName = safeString(forge.draftName).slice(0, 96) || `Pixel ${Math.max(1, Number(wb.nextId) || 1)}`;
    forge.draftPixels = moduleStudioPixelNormalize(forge.draftPixels, forge.size);
    if (!forge.draftPixels.some(Boolean)) {
        forge.draftPixels = moduleStudioGeneratePixelPrompt(forge.prompt || 'robot helper', forge.size, forge.palette);
    }
    forge.editingAssetId = safeString(forge.editingAssetId);
    forge.syncedSelectionId = safeString(forge.syncedSelectionId);
    return forge;
}

function moduleStudioPixelsToDataUrl(pixelsRaw, sizeRaw = MODULE_STUDIO_FORGE_SIZE, scaleRaw = 1) {
    const size = moduleWorkbenchClamp(Number(sizeRaw) || MODULE_STUDIO_FORGE_SIZE, 8, 64);
    const scale = moduleWorkbenchClamp(Number(scaleRaw) || 1, 1, 64);
    const pixels = moduleStudioPixelNormalize(pixelsRaw, size);
    const canvas = document.createElement('canvas');
    canvas.width = size * scale;
    canvas.height = size * scale;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
            const color = safeString(pixels[(y * size) + x]).toLowerCase();
            if (!/^#[0-9a-f]{6}$/.test(color)) continue;
            ctx.fillStyle = color;
            ctx.fillRect(x * scale, y * scale, scale, scale);
        }
    }
    return canvas.toDataURL('image/png');
}

function moduleStudioAssetPreviewUrl(assetRaw) {
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : null;
    if (!asset) return '';
    if (moduleStudioAssetKind(asset) === 'pixel') {
        const size = moduleWorkbenchClamp(Number(asset.pixelSize) || MODULE_STUDIO_FORGE_SIZE, 8, 64);
        const pixels = moduleStudioPixelNormalize(asset.pixelData, size);
        const signature = `${size}:${pixels.join('|')}`;
        if (safeString(asset.pixelPreviewSignature) !== signature) {
            asset.pixelPreviewSignature = signature;
            asset.pixelPreviewUrl = moduleStudioPixelsToDataUrl(pixels, size, 1);
        }
        return safeString(asset.pixelPreviewUrl);
    }
    return safeString(asset.url);
}

function moduleStudioLoadForgeFromPixelAsset(wb, assetRaw) {
    const forge = moduleStudioEnsureForgeState(wb);
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : null;
    if (!forge || !asset || moduleStudioAssetKind(asset) !== 'pixel') return false;
    forge.draftName = safeString(asset.name).slice(0, 96) || forge.draftName;
    forge.prompt = safeString(asset.prompt).slice(0, 180);
    forge.draftPixels = moduleStudioPixelNormalize(asset.pixelData, forge.size);
    forge.editingAssetId = safeString(asset.id);
    return true;
}

function moduleStudioSyncForgeWithSelection(wb, assetRaw) {
    const forge = moduleStudioEnsureForgeState(wb);
    if (!forge) return;
    const selectedId = safeString(assetRaw?.id);
    if (selectedId === safeString(forge.syncedSelectionId)) return;
    forge.syncedSelectionId = selectedId;
    moduleStudioLoadForgeFromPixelAsset(wb, assetRaw);
}

function moduleStudioSaveForgeAsset(wb, preferredIdRaw = '') {
    if (!wb || typeof wb !== 'object') return null;
    if (!Array.isArray(wb.assets)) wb.assets = [];
    const forge = moduleStudioEnsureForgeState(wb);
    if (!forge) return null;
    const preferredId = safeString(preferredIdRaw);
    const targetId = preferredId || safeString(forge.editingAssetId);
    let target = wb.assets.find((item) => safeString(item?.id) === targetId) || null;
    if (target && moduleStudioAssetKind(target) !== 'pixel') target = null;
    const pixelData = moduleStudioPixelNormalize(forge.draftPixels, forge.size);
    if (!pixelData.some(Boolean)) return null;
    if (!target) {
        target = {
            id: `asset-${Math.max(1, Number(wb.nextId) || 1)}`,
            duration: 6,
        };
        wb.nextId = Math.max(1, Number(wb.nextId) || 1) + 1;
        wb.assets.unshift(target);
    }
    target.name = safeString(forge.draftName).slice(0, 96) || `Pixel ${safeString(target.id)}`;
    target.duration = moduleWorkbenchClamp(Number(target.duration) || 6, 0.5, 900);
    target.kind = 'pixel';
    target.mime = 'image/png';
    target.pixelSize = forge.size;
    target.pixelData = pixelData;
    target.prompt = safeString(forge.prompt).slice(0, 180);
    target.pixelPreviewSignature = '';
    target.pixelPreviewUrl = '';
    target.url = moduleStudioAssetPreviewUrl(target);
    wb.selectedAssetId = safeString(target.id);
    forge.editingAssetId = safeString(target.id);
    forge.syncedSelectionId = safeString(target.id);
    return target;
}

function moduleStudioDownloadDataUrl(filenameRaw, dataUrlRaw) {
    const filename = safeString(filenameRaw) || 'asset.png';
    const dataUrl = safeString(dataUrlRaw);
    if (!dataUrl.startsWith('data:image/')) return;
    const anchor = document.createElement('a');
    anchor.href = dataUrl;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    window.setTimeout(() => {
        anchor.remove();
    }, 80);
}

