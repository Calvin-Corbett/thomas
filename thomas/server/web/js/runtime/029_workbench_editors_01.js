function moduleAutomationCoerceValue(rawValue) {
    const text = safeString(rawValue).trim();
    if (!text) return '';
    if (text === 'true') return true;
    if (text === 'false') return false;
    if (text === 'null') return null;
    if (!Number.isNaN(Number(text)) && text !== '') return Number(text);
    if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
        try {
            return JSON.parse(text);
        } catch (_error) {}
    }
    return text;
}

function moduleAutomationCompare(actual, opRaw, expectedRaw) {
    const op = safeString(opRaw) || 'equals';
    const expected = moduleAutomationCoerceValue(expectedRaw);
    if (op === 'equals') return actual === expected;
    if (op === 'not_equals') return actual !== expected;
    if (op === 'contains') return safeString(actual).toLowerCase().includes(safeString(expected).toLowerCase());
    if (op === 'not_contains') return !safeString(actual).toLowerCase().includes(safeString(expected).toLowerCase());
    if (op === 'gt') return Number(actual) > Number(expected);
    if (op === 'lt') return Number(actual) < Number(expected);
    if (op === 'exists') return typeof actual !== 'undefined' && actual !== null && safeString(actual) !== '';
    return actual === expected;
}

function moduleAutomationApplyTemplate(templateRaw, dataRaw) {
    const template = safeString(templateRaw);
    const data = dataRaw && typeof dataRaw === 'object' ? dataRaw : {};
    if (!template) return '';
    return template.replace(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g, (_match, path) => {
        const value = moduleWorkbenchPathGet(data, safeString(path));
        if (value === null || typeof value === 'undefined') return '';
        if (typeof value === 'object') return JSON.stringify(value);
        return safeString(value);
    });
}

function moduleAutomationExecuteNode(nodeRaw, payloadRaw, outputsRaw) {
    const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
    const outputs = Array.isArray(outputsRaw) ? outputsRaw : [];
    const props = node.properties && typeof node.properties === 'object' ? node.properties : {};
    const blockType = safeString(props.blockType);
    const kind = safeString(props.kind);
    const payload = moduleWorkbenchDeepClone(payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {});
    const data = payload && typeof payload === 'object' ? payload : {};
    const result = {
        pass: true,
        pendingApproval: false,
        note: '',
        payload: data,
    };

    if (blockType === 'if_else') {
        const field = safeString(props.field) || 'priority';
        const op = safeString(props.op) || 'equals';
        const actual = moduleWorkbenchPathGet(data, field);
        result.pass = moduleAutomationCompare(actual, op, props.value);
        result.note = result.pass ? `Condition passed (${field} ${op}).` : `Condition failed (${field} ${op}).`;
        return result;
    }

    if (blockType === 'approval_gate') {
        const autoApprove = Boolean(props.autoApprove);
        if (!autoApprove) {
            result.pendingApproval = true;
            result.pass = false;
            result.note = 'Waiting for human approval.';
            return result;
        }
        result.note = 'Auto-approved.';
        return result;
    }

    if (blockType === 'run_script') {
        const operation = safeString(props.operation) || 'set';
        const field = safeString(props.field) || 'result.value';
        if (operation === 'set') {
            moduleWorkbenchPathSet(data, field, moduleAutomationCoerceValue(props.value));
            result.note = `Set ${field}.`;
        } else if (operation === 'inc') {
            const current = Number(moduleWorkbenchPathGet(data, field) || 0);
            const inc = Number(moduleAutomationCoerceValue(props.value) || 1);
            moduleWorkbenchPathSet(data, field, current + inc);
            result.note = `Incremented ${field} by ${inc}.`;
        } else if (operation === 'append_tag') {
            const current = moduleWorkbenchPathGet(data, field);
            const next = Array.isArray(current) ? [...current, safeString(props.value)] : [safeString(props.value)];
            moduleWorkbenchPathSet(data, field, next);
            result.note = `Appended tag on ${field}.`;
        } else if (operation === 'delete') {
            moduleWorkbenchPathDelete(data, field);
            result.note = `Deleted ${field}.`;
        } else {
            result.note = `No-op operation: ${operation}.`;
        }
        return result;
    }

    if (blockType === 'send_message') {
        const template = safeString(props.template) || 'Workflow message: {{subject}}';
        const text = moduleAutomationApplyTemplate(template, data);
        outputs.push({
            channel: safeString(props.channel) || 'inbox',
            text,
        });
        result.note = 'Message action generated.';
        return result;
    }

    if (kind === 'trigger') {
        result.note = 'Trigger emitted payload.';
        return result;
    }
    if (kind === 'logic') {
        result.note = 'Logic gate passed.';
        return result;
    }
    if (kind === 'action') {
        result.note = 'Action executed.';
        return result;
    }
    result.note = 'Node executed.';
    return result;
}

function moduleAutomationRunGraphData(graphDataRaw, inputRaw) {
    const graphData = graphDataRaw && typeof graphDataRaw === 'object' ? graphDataRaw : {};
    const nodes = Array.isArray(graphData.nodes) ? graphData.nodes : [];
    const edges = moduleWorkbenchLiteGraphLinks(graphData);
    const nodeMap = new Map();
    const adjacency = new Map();
    const indegree = new Map();
    nodes.forEach((node) => {
        const id = Number(node?.id) || 0;
        if (!id) return;
        nodeMap.set(id, node);
        adjacency.set(id, []);
        indegree.set(id, 0);
    });
    edges.forEach((edge) => {
        const from = Number(edge.originId) || 0;
        const to = Number(edge.targetId) || 0;
        if (!nodeMap.has(from) || !nodeMap.has(to)) return;
        adjacency.get(from).push(to);
        indegree.set(to, Number(indegree.get(to) || 0) + 1);
    });

    const starts = nodes
        .map((node) => Number(node?.id) || 0)
        .filter((id) => id && (
            safeString(nodeMap.get(id)?.properties?.kind) === 'trigger'
            || Number(indegree.get(id) || 0) === 0
        ));
    const queue = starts.map((id) => ({ id, payload: moduleWorkbenchDeepClone(inputRaw && typeof inputRaw === 'object' ? inputRaw : {}) }));
    const outputs = [];
    const steps = [];
    const guard = new Map();
    let iterations = 0;

    while (queue.length && iterations < 500) {
        iterations += 1;
        const item = queue.shift();
        if (!item) continue;
        const id = Number(item.id) || 0;
        const node = nodeMap.get(id);
        if (!node) continue;
        const key = String(id);
        const seen = Number(guard.get(key) || 0) + 1;
        guard.set(key, seen);
        if (seen > 12) continue;

        const run = moduleAutomationExecuteNode(node, item.payload, outputs);
        steps.push({
            id,
            title: safeString(node.title) || `Node ${id}`,
            pass: Boolean(run.pass),
            pendingApproval: Boolean(run.pendingApproval),
            note: safeString(run.note),
            payload: moduleWorkbenchDeepClone(run.payload),
        });
        if (!run.pass) continue;
        const children = adjacency.get(id) || [];
        children.forEach((childId) => {
            queue.push({ id: childId, payload: moduleWorkbenchDeepClone(run.payload) });
        });
    }

    const lastPayload = steps.length ? moduleWorkbenchDeepClone(steps[steps.length - 1].payload) : moduleWorkbenchDeepClone(inputRaw && typeof inputRaw === 'object' ? inputRaw : {});
    return {
        steps,
        outputs,
        finalPayload: lastPayload,
        nodeCount: nodes.length,
        edgeCount: edges.length,
    };
}

function moduleRenderWorkbenchAutomationsOss(container, wb) {
    if (!container || !wb) return false;
    if (wb.ossError) return false;
    if (!wb.ossReady || !window.LiteGraph) {
        moduleWorkbenchRenderEngineLoading(
            container,
            'Automation Graph Engine',
            'LiteGraph drag/drop canvas with node links and run traces.',
            'Loading LiteGraph...',
            'If loading fails, fallback list mode will open automatically.',
        );
        if (!wb.ossLoading) {
            wb.ossLoading = true;
            void moduleWorkbenchLoadLiteGraph().then(() => {
                wb.ossReady = true;
                wb.ossLoading = false;
                wb.ossError = '';
                moduleWorkbenchRefreshMode('automations');
            }).catch((error) => {
                wb.ossLoading = false;
                wb.ossReady = false;
                wb.ossError = safeString(error?.message) || 'Failed to load LiteGraph.';
                notifyUser('LiteGraph failed to load, using fallback flow list.', { tone: 'warn', durationMs: 2300, debugKind: 'automations' });
                moduleWorkbenchRefreshMode('automations');
            });
        }
        return true;
    }

    const LiteGraph = window.LiteGraph;
    moduleWorkbenchEnsureLiteGraphNodeType(LiteGraph);
    if (!Array.isArray(wb.logs)) wb.logs = [];
    wb.runInput = safeString(wb.runInput) || '{\n  "subject": "Ops status",\n  "priority": "high"\n}';
    if (!wb.runReport || typeof wb.runReport !== 'object') wb.runReport = null;
    wb.selectedProjectId = safeString(wb.selectedProjectId);
    wb.selectedNodeId = safeString(wb.selectedNodeId);

    moduleWorkbenchHeader(container, 'Automation Graph Engine', 'Define orchestration logic for Thomas to execute, then monitor run behavior and approvals.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-flow-oss';
    shell.innerHTML = `
        <aside class="module-wb-side-card">
            <h4>Block Palette</h4>
            <div class="module-wb-palette" data-flow-palette></div>
            ${moduleWorkbenchRenderProjectControls('automations', 'Flow Projects')}
            <label class="module-wb-field module-wb-field-wide">Run Input JSON<textarea rows="6" data-flow-run-input>${escapeHtml(safeString(wb.runInput) || '{\n  "subject": "Ops status",\n  "priority": "high"\n}')}</textarea></label>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-flow-action="run">Test Run</button>
                <button type="button" class="module-item-btn" data-flow-action="run_dry">Dry Run</button>
                <button type="button" class="module-item-btn" data-flow-action="export">Export</button>
                <button type="button" class="module-item-btn" data-flow-action="export_n8n">n8n JSON</button>
                <button type="button" class="module-item-btn" data-flow-action="export_nodered">Node-RED JSON</button>
                <button type="button" class="module-item-btn" data-flow-action="reset">Reset</button>
            </div>
        </aside>
        <section class="module-wb-stage-card">
            <div class="module-wb-stage-head"><span class="module-wb-stage-title">Visual Graph</span><span class="module-wb-stage-meta" data-flow-status></span></div>
            <canvas class="module-wb-flow-canvas" data-flow-canvas></canvas>
            <div class="module-wb-log-list" data-flow-logs></div>
            <div class="module-wb-run-report" data-flow-report></div>
        </section>
        <aside class="module-wb-inspector-card" data-flow-inspector></aside>
        ${moduleWorkbenchRenderOssStack('automations')}
    `;
    container.appendChild(shell);

    const palette = shell.querySelector('[data-flow-palette]');
    const canvas = shell.querySelector('[data-flow-canvas]');
    const logs = shell.querySelector('[data-flow-logs]');
    const report = shell.querySelector('[data-flow-report]');
    const inspector = shell.querySelector('[data-flow-inspector]');
    const status = shell.querySelector('[data-flow-status]');
    const runInputEl = shell.querySelector('[data-flow-run-input]');
    if (!(palette instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) || !(logs instanceof HTMLElement) || !(report instanceof HTMLElement) || !(inspector instanceof HTMLElement) || !(status instanceof HTMLElement)) {
        return false;
    }

    if (wb.ossGraphCanvas?.setGraph) {
        try {
            wb.ossGraph?.stop?.();
            wb.ossGraphCanvas.setGraph(null, true);
        } catch (_error) {}
    }

    const graph = new LiteGraph.LGraph();
    const graphCanvas = new LiteGraph.LGraphCanvas(canvas, graph);
    graphCanvas.ds.scale = 0.92;
    graphCanvas.onNodeSelected = (node) => {
        wb.selectedNodeId = safeString(node?.id);
        renderInspector();
    };
    graphCanvas.onNodeDeselected = () => {
        wb.selectedNodeId = '';
        renderInspector();
    };
    graph.start();

    wb.ossGraph = graph;
    wb.ossGraphCanvas = graphCanvas;

    const blockDefs = [
        { id: 'schedule_trigger', kind: 'trigger', label: 'Schedule Trigger' },
        { id: 'email_trigger', kind: 'trigger', label: 'New Email Trigger' },
        { id: 'if_else', kind: 'logic', label: 'If / Else' },
        { id: 'approval_gate', kind: 'logic', label: 'Human Approval' },
        { id: 'send_message', kind: 'action', label: 'Send Message' },
        { id: 'run_script', kind: 'action', label: 'Run Script' },
    ];

    const createNode = (def, pos = [120, 120]) => {
        const node = LiteGraph.createNode('thomas/flow_block');
        if (!node) return null;
        node.title = def.label;
        node.properties.blockType = def.id;
        node.properties.kind = def.kind;
        node.properties.notes = node.properties.notes || '';
        node.properties.approval = Boolean(node.properties.approval);
        node.properties.field = safeString(node.properties.field) || 'priority';
        node.properties.op = safeString(node.properties.op) || 'equals';
        node.properties.value = safeString(node.properties.value) || 'high';
        node.properties.template = safeString(node.properties.template) || 'Workflow alert: {{subject}}';
        node.properties.operation = safeString(node.properties.operation) || 'set';
        node.properties.channel = safeString(node.properties.channel) || 'inbox';
        node.properties.autoApprove = Boolean(node.properties.autoApprove);
        node.pos = [...pos];
        return node;
    };
    const graphNodes = () => Array.isArray(graph?._nodes) ? graph._nodes : [];
    const selectedNode = () => graphNodes().find((node) => safeString(node?.id) === safeString(wb.selectedNodeId)) || null;
    const remember = () => {
        try {
            wb.graphData = graph.serialize();
        } catch (_error) {}
    };
    const parseRunInput = () => {
        const raw = safeString(runInputEl instanceof HTMLTextAreaElement ? runInputEl.value : wb.runInput);
        wb.runInput = raw;
        if (!raw.trim()) return {};
        try {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') return parsed;
            return { value: parsed };
        } catch (_error) {
            return { _raw: raw };
        }
    };
    const renderProjectSelect = () => {
        const select = shell.querySelector('select[data-wb-project-select="automations"]');
        if (!(select instanceof HTMLSelectElement)) return;
        const rows = moduleWorkbenchProjectList('automations');
        const current = safeString(wb.selectedProjectId);
        select.innerHTML = `<option value="">Select project</option>${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}`;
        select.value = rows.some((row) => safeString(row.id) === current) ? current : '';
    };
    const renderLogs = () => {
        logs.innerHTML = wb.logs.length
            ? wb.logs.slice(0, 14).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('')
            : '<div class="module-wb-ghost">No run logs yet.</div>';
    };
    const renderReport = () => {
        const run = wb.runReport && typeof wb.runReport === 'object' ? wb.runReport : null;
        if (!run) {
            report.innerHTML = '<div class="module-wb-ghost">Run report appears here after Test Run.</div>';
            return;
        }
        const pending = run.steps.filter((step) => Boolean(step.pendingApproval)).length;
        report.innerHTML = `
            <div class="module-wb-metrics">
                <div><span>Nodes</span><strong>${Number(run.nodeCount) || 0}</strong></div>
                <div><span>Edges</span><strong>${Number(run.edgeCount) || 0}</strong></div>
                <div><span>Pending</span><strong>${pending}</strong></div>
            </div>
            <div class="module-wb-log-list">
                ${run.steps.slice(0, 20).map((step) => `<article class="module-wb-log-item ${step.pendingApproval ? 'warn' : (step.pass ? 'ok' : 'error')}"><span>${escapeHtml(safeString(step.title))}</span><p>${escapeHtml(safeString(step.note))}</p></article>`).join('')}
            </div>
            <div class="module-wb-field module-wb-field-wide">
                <label>Final Payload</label>
                <textarea rows="7" readonly>${escapeHtml(JSON.stringify(run.finalPayload || {}, null, 2))}</textarea>
            </div>
            <div class="module-wb-field module-wb-field-wide">
                <label>Generated Outputs</label>
                <textarea rows="6" readonly>${escapeHtml(JSON.stringify(run.outputs || [], null, 2))}</textarea>
            </div>
        `;
    };
    const renderStatus = () => {
        const links = graph?.links ? Object.keys(graph.links).length : 0;
        status.textContent = `${graphNodes().length} nodes | ${links} links`;
    };
    const renderInspector = () => {
        const node = selectedNode();
        if (!node) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a node on the canvas to edit details.</p><div class="module-wb-metrics"><div><span>Nodes</span><strong>${graphNodes().length}</strong></div><div><span>Links</span><strong>${graph?.links ? Object.keys(graph.links).length : 0}</strong></div><div><span>Approvals</span><strong>${graphNodes().filter((entry) => Boolean(entry?.properties?.approval)).length}</strong></div></div>`;
            return;
        }
        inspector.innerHTML = `
            <h4>${escapeHtml(safeString(node.title) || 'Flow Block')}</h4>
            <div class="module-wb-field-grid">
                <label class="module-wb-field">Label<input type="text" data-flow-prop="title" value="${escapeHtml(safeString(node.title))}" /></label>
                <label class="module-wb-field">Kind<select data-flow-prop="kind">${['trigger', 'logic', 'action'].map((kind) => `<option value="${kind}"${safeString(node.properties?.kind) === kind ? ' selected' : ''}>${kind}</option>`).join('')}</select></label>
                <label class="module-wb-field module-wb-field-check"><input type="checkbox" data-flow-prop="approval" ${node.properties?.approval ? 'checked' : ''} />Require approval</label>
                <label class="module-wb-field">Field<input type="text" data-flow-prop="field" value="${escapeHtml(safeString(node.properties?.field) || 'priority')}" /></label>
                <label class="module-wb-field">Operator<select data-flow-prop="op">${[
                    ['equals', 'Equals'],
                    ['not_equals', 'Not equals'],
                    ['contains', 'Contains'],
                    ['not_contains', 'Not contains'],
                    ['gt', 'Greater than'],
                    ['lt', 'Less than'],
                    ['exists', 'Exists'],
                ].map(([value, label]) => `<option value="${value}"${safeString(node.properties?.op) === value ? ' selected' : ''}>${label}</option>`).join('')}</select></label>
                <label class="module-wb-field">Value<input type="text" data-flow-prop="value" value="${escapeHtml(safeString(node.properties?.value))}" /></label>
                <label class="module-wb-field">Operation<select data-flow-prop="operation">${[
                    ['set', 'Set'],
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
            const def = blockDefs.find((block) => block.id === nodeType) || blockDefs[0];
            const offset = graphNodes().length;
            const node = createNode(def, [80 + (offset * 30), 100 + (offset * 20)]);
            if (!node) return;
            graph.add(node);
            wb.selectedNodeId = safeString(node.id);
            moduleWorkbenchPushLog(wb.logs, `Added ${def.label}.`, 'ok', 80, 'flow-log');
            remember();
            renderLogs();
            renderStatus();
            renderInspector();
            return;
        }
        const node = selectedNode();
        if (action === 'run') {
            remember();
            const run = moduleAutomationRunGraphData(wb.graphData || graph.serialize(), parseRunInput());
            wb.runReport = run;
            moduleWorkbenchPushLog(wb.logs, `Run completed: ${run.steps.length} step(s), ${run.outputs.length} output(s).`, 'ok', 80, 'flow-log');
            renderLogs();
            renderReport();
            return;
        }
        if (action === 'run_dry') {
            remember();
            const run = moduleAutomationRunGraphData(wb.graphData || graph.serialize(), parseRunInput());
            wb.runReport = {
                ...run,
                outputs: [],
                steps: run.steps.map((step) => ({ ...step, note: `${safeString(step.note)} (dry run)` })),
            };
            moduleWorkbenchPushLog(wb.logs, `Dry run completed: ${run.steps.length} step(s).`, 'warn', 80, 'flow-log');
            renderLogs();
            renderReport();
            return;
        }
        if (action === 'export') {
            remember();
            moduleWorkbenchCopyJson(wb.graphData || graph.serialize(), 'Automation Flow JSON');
            return;
        }
        if (action === 'export_n8n') {
            remember();
            moduleWorkbenchCopyJson(moduleWorkbenchFlowToN8n(wb.graphData || graph.serialize()), 'n8n Workflow JSON');
            return;
        }
        if (action === 'export_nodered') {
            remember();
            moduleWorkbenchCopyJson(moduleWorkbenchFlowToNodeRed(wb.graphData || graph.serialize()), 'Node-RED Flow JSON');
            return;
        }
        if (action === 'reset') {
            graph.clear();
            wb.graphData = null;
            wb.selectedNodeId = '';
            wb.logs = [];
            wb.runReport = null;
            renderLogs();
            renderReport();
            renderStatus();
            renderInspector();
            return;
        }
        if (action === 'duplicate' && node) {
            const clone = createNode({
                id: safeString(node.properties?.blockType) || 'custom',
                kind: safeString(node.properties?.kind) || 'action',
                label: `${safeString(node.title) || 'Block'} Copy`,
            }, [Number(node.pos?.[0] || 80) + 42, Number(node.pos?.[1] || 80) + 32]);
            if (!clone) return;
            clone.properties.notes = safeString(node.properties?.notes);
            clone.properties.approval = Boolean(node.properties?.approval);
            clone.properties.field = safeString(node.properties?.field);
            clone.properties.op = safeString(node.properties?.op) || 'equals';
            clone.properties.value = safeString(node.properties?.value);
            clone.properties.template = safeString(node.properties?.template);
            clone.properties.operation = safeString(node.properties?.operation) || 'set';
            clone.properties.channel = safeString(node.properties?.channel) || 'inbox';
            clone.properties.autoApprove = Boolean(node.properties?.autoApprove);
            graph.add(clone);
            wb.selectedNodeId = safeString(clone.id);
            remember();
            renderStatus();
            renderInspector();
            return;
        }
        if (action === 'delete' && node) {
            graph.remove(node);
            wb.selectedNodeId = '';
            remember();
            renderStatus();
            renderInspector();
        }
    });

    inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement)) return;
        const node = selectedNode();
        if (!node) return;
        const prop = safeString(target.dataset.flowProp);
        if (!prop) return;
        if (prop === 'title') node.title = safeString(target.value).slice(0, 90);
        if (prop === 'kind') node.properties.kind = safeString(target.value);
        if (prop === 'notes') node.properties.notes = safeString(target.value).slice(0, 2200);
        if (prop === 'field') node.properties.field = safeString(target.value).slice(0, 140);
        if (prop === 'op') node.properties.op = safeString(target.value);
        if (prop === 'value') node.properties.value = safeString(target.value).slice(0, 400);
        if (prop === 'template') node.properties.template = safeString(target.value).slice(0, 1800);
        if (prop === 'operation') node.properties.operation = safeString(target.value);
        if (prop === 'channel') node.properties.channel = safeString(target.value).slice(0, 80);
        if (prop === 'approval' && target instanceof HTMLInputElement) node.properties.approval = target.checked;
        if (prop === 'autoApprove' && target instanceof HTMLInputElement) node.properties.autoApprove = target.checked;
        node.setDirtyCanvas(true, true);
        remember();
        renderStatus();
        renderReport();
    });

    if (runInputEl instanceof HTMLTextAreaElement) {
        runInputEl.addEventListener('input', () => {
            wb.runInput = safeString(runInputEl.value);
        });
    }
    const projectSelect = shell.querySelector('select[data-wb-project-select="automations"]');
    if (projectSelect instanceof HTMLSelectElement) {
        projectSelect.addEventListener('change', () => {
            wb.selectedProjectId = safeString(projectSelect.value);
        });
    }

    return true;
}

function moduleRenderWorkbenchAutomations(container, wb) {
    if (moduleRenderWorkbenchAutomationsOss(container, wb)) return;
    if (!container || !wb) return;
    if (!Array.isArray(wb.nodes)) wb.nodes = [];
    if (!Array.isArray(wb.edges)) wb.edges = [];
    if (!Array.isArray(wb.logs)) wb.logs = [];
    wb.selectedId = safeString(wb.selectedId);
    wb.connectingFrom = safeString(wb.connectingFrom);
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.runInput = safeString(wb.runInput) || '{\n  "subject": "Ops status",\n  "priority": "high"\n}';
    if (!wb.runReport || typeof wb.runReport !== 'object') wb.runReport = null;
    wb.selectedProjectId = safeString(wb.selectedProjectId);

    moduleWorkbenchHeader(container, 'Automation Flow Builder', 'Compose workflows Thomas runs end to end with live logs, approvals, and recovery visibility.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-flow';
    shell.innerHTML = `
        <aside class="module-wb-side-card"><h4>Blocks</h4><div class="module-wb-palette" data-flow-palette></div>${moduleWorkbenchRenderProjectControls('automations', 'Flow Projects')}<label class="module-wb-field module-wb-field-wide">Run Input JSON<textarea rows="6" data-flow-run-input>${escapeHtml(wb.runInput)}</textarea></label><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-flow-action="run">Test Run</button><button type="button" class="module-item-btn" data-flow-action="run_dry">Dry Run</button><button type="button" class="module-item-btn" data-flow-action="export">Export</button><button type="button" class="module-item-btn" data-flow-action="export_n8n">n8n JSON</button><button type="button" class="module-item-btn" data-flow-action="export_nodered">Node-RED JSON</button><button type="button" class="module-item-btn" data-flow-action="clear">Reset</button></div></aside>
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Nodes + Links</span><span class="module-wb-stage-meta" data-flow-status></span></div><div class="module-wb-flow-list" data-flow-list></div><div class="module-wb-log-list" data-flow-logs></div><div class="module-wb-run-report" data-flow-report></div></section>
        <aside class="module-wb-inspector-card" data-flow-inspector></aside>
        ${moduleWorkbenchRenderOssStack('automations')}
    `;
    container.appendChild(shell);

    const blockDefs = [
        { id: 'schedule', kind: 'trigger', label: 'Schedule Trigger' },
        { id: 'email', kind: 'trigger', label: 'New Email Trigger' },
        { id: 'if_else', kind: 'logic', label: 'If / Else Branch' },
        { id: 'approval', kind: 'logic', label: 'Human Approval' },
        { id: 'send_message', kind: 'action', label: 'Send Message' },
        { id: 'run_script', kind: 'action', label: 'Run Script' },
    ];
    const byId = (id) => wb.nodes.find((node) => safeString(node.id) === safeString(id)) || null;
    const palette = shell.querySelector('[data-flow-palette]');
    const list = shell.querySelector('[data-flow-list]');
    const logs = shell.querySelector('[data-flow-logs]');
    const report = shell.querySelector('[data-flow-report]');
    const inspector = shell.querySelector('[data-flow-inspector]');
    const status = shell.querySelector('[data-flow-status]');
    const runInputEl = shell.querySelector('[data-flow-run-input]');

    const renderPalette = () => { palette.innerHTML = blockDefs.map((block) => `<button type="button" class="module-wb-palette-btn" data-flow-node-type="${block.id}"><strong>${block.label}</strong><span>${block.kind}</span></button>`).join(''); };
    const renderList = () => {
        list.innerHTML = wb.nodes.length ? wb.nodes.map((node) => `<article class="module-wb-list-item${safeString(node.id) === safeString(wb.selectedId) ? ' selected' : ''}" data-flow-node-id="${escapeHtml(safeString(node.id))}"><strong>${escapeHtml(safeString(node.label))}</strong><span>${escapeHtml(`${safeString(node.kind)} | ${safeString(node.type)}`)}</span><div class="module-wb-inline-actions"><button type="button" class="module-item-btn" data-flow-node-action="from" data-flow-node-id="${escapeHtml(safeString(node.id))}">From</button><button type="button" class="module-item-btn" data-flow-node-action="to" data-flow-node-id="${escapeHtml(safeString(node.id))}">To</button></div></article>`).join('') : '<div class="module-wb-ghost">Add your first workflow block.</div>';
    };
    const renderLogs = () => { logs.innerHTML = wb.logs.length ? wb.logs.slice(0, 16).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('') : '<div class="module-wb-ghost">No flow logs yet.</div>'; };
    const renderInspector = () => {
        const node = byId(wb.selectedId);
        if (!node) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a node to edit it.</p><div class="module-wb-metrics"><div><span>Nodes</span><strong>${wb.nodes.length}</strong></div><div><span>Links</span><strong>${wb.edges.length}</strong></div><div><span>Connect</span><strong>${wb.connectingFrom ? escapeHtml(wb.connectingFrom) : 'idle'}</strong></div></div>`;
            return;
        }
        inspector.innerHTML = `<h4>${escapeHtml(safeString(node.label))}</h4><div class="module-wb-field-grid"><label class="module-wb-field">Label<input type="text" data-flow-prop="label" value="${escapeHtml(safeString(node.label))}" /></label><label class="module-wb-field">Type<select data-flow-prop="type">${blockDefs.map((block) => `<option value="${block.id}"${safeString(node.type) === block.id ? ' selected' : ''}>${block.label}</option>`).join('')}</select></label><label class="module-wb-field module-wb-field-check"><input type="checkbox" data-flow-prop="approval" ${node.approval ? 'checked' : ''} />Require approval</label><label class="module-wb-field module-wb-field-wide">Notes<textarea rows="4" data-flow-prop="notes">${escapeHtml(safeString(node.notes))}</textarea></label></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-flow-node-action="duplicate">Duplicate</button><button type="button" class="module-item-btn" data-flow-node-action="delete">Delete</button></div>`;
    };
    const renderStatus = () => { status.textContent = `${wb.nodes.length} nodes | ${wb.edges.length} links${wb.connectingFrom ? ` | from ${wb.connectingFrom}` : ''}`; };
    const renderAll = () => { renderList(); renderLogs(); renderReport(); renderInspector(); renderStatus(); renderProjectSelect(); };

    renderPalette();
    renderAll();

    const toGraphData = () => {
        const nodeId = (idRaw, fallback) => {
            const match = safeString(idRaw).match(/\d+/);
            return Number(match?.[0]) || fallback;
        };
        const nodes = wb.nodes.map((node, index) => ({
            id: nodeId(node.id, index + 1),
            title: safeString(node.label) || `Flow ${index + 1}`,
            pos: [120 + (index * 34), 120 + (index * 22)],
            properties: {
                kind: safeString(node.kind) || 'action',
                blockType: safeString(node.type) || 'custom',
                notes: safeString(node.notes),
                approval: Boolean(node.approval),
            },
        }));
        const links = {};
        wb.edges.forEach((edge, index) => {
            const from = nodeId(edge.from, index + 1);
            const to = nodeId(edge.to, index + 2);
            links[index + 1] = [index + 1, from, 0, to, 0, 'flow'];
        });
        return { nodes, links };
    };
    const parseRunInput = () => {
        const raw = safeString(runInputEl instanceof HTMLTextAreaElement ? runInputEl.value : wb.runInput);
        wb.runInput = raw;
        if (!raw.trim()) return {};
        try {
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : { value: parsed };
        } catch (_error) {
            return { _raw: raw };
        }
    };
    const renderReport = () => {
        const run = wb.runReport && typeof wb.runReport === 'object' ? wb.runReport : null;
        if (!report) return;
        if (!run) {
            report.innerHTML = '<div class="module-wb-ghost">Run report appears here after Test Run.</div>';
            return;
        }
        report.innerHTML = `
            <div class="module-wb-metrics"><div><span>Nodes</span><strong>${Number(run.nodeCount) || 0}</strong></div><div><span>Edges</span><strong>${Number(run.edgeCount) || 0}</strong></div><div><span>Outputs</span><strong>${Array.isArray(run.outputs) ? run.outputs.length : 0}</strong></div></div>
            <div class="module-wb-log-list">${(Array.isArray(run.steps) ? run.steps : []).slice(0, 20).map((step) => `<article class="module-wb-log-item ${step.pendingApproval ? 'warn' : (step.pass ? 'ok' : 'error')}"><span>${escapeHtml(safeString(step.title))}</span><p>${escapeHtml(safeString(step.note))}</p></article>`).join('')}</div>
        `;
    };
    const renderProjectSelect = () => {
        const select = shell.querySelector('select[data-wb-project-select="automations"]');
        if (!(select instanceof HTMLSelectElement)) return;
        const rows = moduleWorkbenchProjectList('automations');
        const current = safeString(wb.selectedProjectId);
        select.innerHTML = `<option value="">Select project</option>${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}`;
        select.value = rows.some((row) => safeString(row.id) === current) ? current : '';
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
                wb.selectedProjectId = moduleWorkbenchProjectSave('automations', {
                    nodes: wb.nodes,
                    edges: wb.edges,
                    runInput: wb.runInput,
                }, safeString(input instanceof HTMLInputElement ? input.value : ''));
                if (input instanceof HTMLInputElement) input.value = '';
                renderAll();
                return;
            }
            if (action === 'load') {
                if (!selectedId) return;
                const project = moduleWorkbenchProjectGet('automations', selectedId);
                if (!project?.payload) return;
                wb.nodes = Array.isArray(project.payload.nodes) ? project.payload.nodes : [];
                wb.edges = Array.isArray(project.payload.edges) ? project.payload.edges : [];
                wb.runInput = safeString(project.payload.runInput) || wb.runInput;
                if (runInputEl instanceof HTMLTextAreaElement) runInputEl.value = wb.runInput;
                wb.selectedProjectId = selectedId;
                renderAll();
                return;
            }
            if (action === 'delete') {
                if (!selectedId) return;
                moduleWorkbenchProjectDelete('automations', selectedId);
                wb.selectedProjectId = '';
                renderAll();
                return;
            }
        }
        const target = event.target instanceof Element ? event.target.closest('[data-flow-node-type], [data-flow-action], [data-flow-node-id], [data-flow-node-action]') : null;
        if (!target) return;
        const type = safeString(target.dataset.flowNodeType);
        const action = safeString(target.dataset.flowAction).toLowerCase();
        const nodeAction = safeString(target.dataset.flowNodeAction).toLowerCase();
        const nodeId = safeString(target.dataset.flowNodeId);

        if (type) {
            const def = blockDefs.find((item) => item.id === type) || blockDefs[0];
            const id = `flow-${wb.nextId++}`;
            wb.nodes.push({ id, type: def.id, kind: def.kind, label: def.label, approval: false, notes: '' });
            wb.selectedId = id;
            moduleWorkbenchPushLog(wb.logs, `Added ${def.label}.`, 'ok', 80, 'flow-log');
            renderAll();
            return;
        }
        if (action) {
            if (action === 'run') {
                const run = moduleAutomationRunGraphData(toGraphData(), parseRunInput());
                wb.runReport = run;
                moduleWorkbenchPushLog(wb.logs, `Run completed: ${run.steps.length} step(s), ${run.outputs.length} output(s).`, 'ok', 80, 'flow-log');
            } else if (action === 'run_dry') {
                const run = moduleAutomationRunGraphData(toGraphData(), parseRunInput());
                wb.runReport = {
                    ...run,
                    outputs: [],
                    steps: run.steps.map((step) => ({ ...step, note: `${safeString(step.note)} (dry run)` })),
                };
                moduleWorkbenchPushLog(wb.logs, `Dry run completed: ${run.steps.length} step(s).`, 'warn', 80, 'flow-log');
            } else if (action === 'clear') {
                wb.nodes = [];
                wb.edges = [];
                wb.logs = [];
                wb.selectedId = '';
                wb.connectingFrom = '';
                wb.runReport = null;
            } else if (action === 'export') {
                moduleWorkbenchCopyJson({ nodes: wb.nodes, edges: wb.edges }, 'Automation Flow JSON');
            } else if (action === 'export_n8n') {
                moduleWorkbenchCopyJson(moduleWorkbenchFlowToN8n(toGraphData()), 'n8n Workflow JSON');
            } else if (action === 'export_nodered') {
                moduleWorkbenchCopyJson(moduleWorkbenchFlowToNodeRed(toGraphData()), 'Node-RED Flow JSON');
            }
            renderAll();
            return;
        }
        if (nodeId) wb.selectedId = nodeId;
        if (nodeAction === 'from') wb.connectingFrom = nodeId;
        if (nodeAction === 'to' && wb.connectingFrom && nodeId && wb.connectingFrom !== nodeId) {
            const exists = wb.edges.some((edge) => safeString(edge.from) === wb.connectingFrom && safeString(edge.to) === nodeId);
            if (!exists) wb.edges.push({ id: moduleWorkbenchMakeId('edge'), from: wb.connectingFrom, to: nodeId });
            wb.connectingFrom = '';
        }
        if (nodeAction === 'duplicate') {
            const node = byId(wb.selectedId);
            if (node) {
                const copy = { ...node, id: `flow-${wb.nextId++}`, label: `${node.label} Copy` };
                wb.nodes.push(copy);
                wb.selectedId = copy.id;
            }
        }
        if (nodeAction === 'delete') {
            wb.nodes = wb.nodes.filter((node) => safeString(node.id) !== safeString(wb.selectedId));
            wb.edges = wb.edges.filter((edge) => safeString(edge.from) !== safeString(wb.selectedId) && safeString(edge.to) !== safeString(wb.selectedId));
            wb.selectedId = '';
            wb.connectingFrom = '';
        }
        renderAll();
    });

    if (inspector) {
        inspector.addEventListener('input', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
            const node = byId(wb.selectedId);
            if (!node) return;
            const prop = safeString(target.dataset.flowProp);
            if (!prop) return;
            if (prop === 'label' || prop === 'notes') node[prop] = safeString(target.value).slice(0, 2000);
            if (prop === 'type') {
                node.type = safeString(target.value);
                const def = blockDefs.find((item) => item.id === node.type);
                if (def) node.kind = def.kind;
            }
            if (prop === 'approval' && target instanceof HTMLInputElement) node.approval = target.checked;
            renderAll();
        });
    }
    if (runInputEl instanceof HTMLTextAreaElement) {
        runInputEl.addEventListener('input', () => {
            wb.runInput = safeString(runInputEl.value);
        });
    }
    const projectSelect = shell.querySelector('select[data-wb-project-select="automations"]');
    if (projectSelect instanceof HTMLSelectElement) {
        projectSelect.addEventListener('change', () => {
            wb.selectedProjectId = safeString(projectSelect.value);
        });
    }
}

