// Extracted from part-022b.js
// From trigger

                    ['inc', 'Increment'],
                    ['append_tag', 'Append tag'],
                    ['delete', 'Delete'],
                ].map(([value, label]) => `<option value="${value}"${safeString(node.properties?.operation) === value ? ' selected' : ''}>${label}</option>`).join('')}</select></label>
                <label class="module-wb-field">Channel<input type="text" data-flow-prop="channel" value="${escapeHtml(safeString(node.properties?.channel) || 'inbox')}" /></label>
                <label class="module-wb-field module-wb-field-check"><input type="checkbox" data-flow-prop="autoApprove" ${node.properties?.autoApprove ? 'checked' : ''} />Auto-approve gate</label>
                <label class="module-wb-field module-wb-field-wide">Notes<textarea rows="5" data-flow-prop="notes">${escapeHtml(safeString(node.properties?.notes))}</textarea></label>
                <label class="module-wb-field module-wb-field-wide">Message Template<textarea rows="3" data-flow-prop="template">${escapeHtml(safeString(node.properties?.template) || 'Workflow alert: {{subject}}')}</textarea></label>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-flow-action="duplicate">Duplicate</button>
                <button type="button" class="module-item-btn" data-flow-action="delete">Delete</button>
            </div>
        `;
    };

    palette.innerHTML = blockDefs.map((block) => `<button type="button" class="module-wb-palette-btn" data-flow-node-type="${block.id}"><strong>${block.label}</strong><span>${block.kind}</span></button>`).join('');

    if (wb.graphData?.nodes?.length) {
        try {
            graph.configure(wb.graphData);
        } catch (_error) {
            wb.graphData = null;
        }
    }
    if (!graphNodes().length) {
        const trigger = createNode(blockDefs[0], [80, 140]);
        const action = createNode(blockDefs[4], [420, 140]);
        if (trigger) graph.add(trigger);
        if (action) graph.add(action);
        if (trigger && action) trigger.connect(0, action, 0);
    }
    remember();
    renderLogs();
    renderReport();
    renderProjectSelect();
    renderStatus();
    renderInspector();

    graph.onAfterChange = () => {
        remember();
        renderStatus();
        renderInspector();
        renderProjectSelect();
    };

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const projectActionEl = event.target instanceof Element
            ? event.target.closest('[data-wb-project-action][data-wb-project-mode="automations"]')
            : null;
        if (projectActionEl) {
            const action = safeString(projectActionEl.dataset.wbProjectAction).toLowerCase();
            const select = shell.querySelector('select[data-wb-project-select="automations"]');
            const input = shell.querySelector('input[data-wb-project-name="automations"]');
            const selectedId = safeString(select instanceof HTMLSelectElement ? select.value : wb.selectedProjectId);
            if (action === 'save') {
                remember();
                const savedId = moduleWorkbenchProjectSave('automations', {
                    graphData: wb.graphData || graph.serialize(),
                    runInput: wb.runInput,
                }, safeString(input instanceof HTMLInputElement ? input.value : ''));
                wb.selectedProjectId = savedId;
                if (input instanceof HTMLInputElement) input.value = '';
                moduleWorkbenchPushLog(wb.logs, 'Saved flow project.', 'ok', 80, 'flow-log');
                renderLogs();
                renderProjectSelect();
                return;
            }
            if (action === 'load') {
                if (!selectedId) return;
                const project = moduleWorkbenchProjectGet('automations', selectedId);
                if (!project?.payload) return;
                const payload = project.payload;
                graph.clear();
                wb.graphData = payload.graphData && typeof payload.graphData === 'object' ? payload.graphData : null;
                if (wb.graphData?.nodes?.length) {
                    try {
                        graph.configure(wb.graphData);
                    } catch (_error) {
                        wb.graphData = null;
                    }
                }
                wb.runInput = safeString(payload.runInput) || wb.runInput;
                if (runInputEl instanceof HTMLTextAreaElement) runInputEl.value = wb.runInput;
                wb.selectedProjectId = selectedId;
                remember();
                moduleWorkbenchPushLog(wb.logs, `Loaded project: ${safeString(project.name)}.`, 'ok', 80, 'flow-log');
                renderLogs();
                renderStatus();
                renderInspector();
                renderProjectSelect();
                return;
            }
            if (action === 'delete') {
                if (!selectedId) return;
                if (moduleWorkbenchProjectDelete('automations', selectedId)) {
                    wb.selectedProjectId = '';
                    moduleWorkbenchPushLog(wb.logs, 'Deleted flow project.', 'warn', 80, 'flow-log');
                    renderLogs();
                    renderProjectSelect();
                }
                return;
            }
        }
        const target = event.target instanceof Element ? event.target.closest('[data-flow-node-type], [data-flow-action]') : null;
        if (!target) return;
        const nodeType = safeString(target.dataset.flowNodeType);
        const action = safeString(target.dataset.flowAction).toLowerCase();
        if (nodeType) {