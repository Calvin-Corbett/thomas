function vibeCodeTopStatus(trace) {
    if (!trace || !(trace.nodes instanceof Map) || !trace.nodes.size) return 'pending';
    let top = 'pending';
    for (const node of trace.nodes.values()) {
        top = vibeCodeMergeStatus(top, node?.status);
    }
    return top;
}

function vibeCodeNodeEdgeKey(fromRaw, toRaw) {
    return `${safeString(fromRaw)}->${safeString(toRaw)}`;
}

function vibeCodeSortNodeIds(trace) {
    const orderMap = new Map();
    trace.order.forEach((id, index) => {
        orderMap.set(id, index);
    });
    return [...trace.nodes.keys()].sort((left, right) => {
        const leftOrder = orderMap.has(left) ? Number(orderMap.get(left)) : Number.MAX_SAFE_INTEGER;
        const rightOrder = orderMap.has(right) ? Number(orderMap.get(right)) : Number.MAX_SAFE_INTEGER;
        if (leftOrder !== rightOrder) return leftOrder - rightOrder;
        return left.localeCompare(right);
    });
}

function vibeCodeCreateTrace(traceId) {
    const trace = {
        id: safeString(traceId),
        nodes: new Map(),
        order: [],
        edges: [...VIBE_CODE_FALLBACK_EDGES],
        events: [],
        meta: {},
    };
    for (const node of VIBE_CODE_FALLBACK_NODES) {
        const nodeId = safeString(node.id);
        if (!nodeId) continue;
        trace.nodes.set(nodeId, {
            id: nodeId,
            label: safeString(node.label) || nodeId,
            kind: safeString(node.kind) || 'step',
            summary: safeString(node.summary),
            detail: safeString(node.summary),
            status: 'pending',
        });
        trace.order.push(nodeId);
    }
    return trace;
}

function vibeCodeActiveTrace() {
    return vibeCodeState.traces.get(vibeCodeState.activeTraceId) || null;
}

function vibeCodeRegisterNode(nodeRaw, statusRaw = '') {
    const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
    const nodeId = safeString(node.id);
    if (!nodeId) return;
    const now = Date.now();
    const existing = vibeCodeState.discoveredNodes.get(nodeId);
    const next = {
        id: nodeId,
        label: safeString(node.label) || safeString(existing?.label) || nodeId,
        kind: safeString(node.kind) || safeString(existing?.kind) || 'step',
        detail: safeString(node.detail) || safeString(node.summary) || safeString(existing?.detail),
        status: vibeCodeNormalizeStatus(statusRaw || node.status || existing?.status || 'pending'),
        firstSeenMs: Number(existing?.firstSeenMs) || now,
        lastSeenMs: now,
        seenCount: (Number(existing?.seenCount) || 0) + 1,
    };
    vibeCodeState.discoveredNodes.set(nodeId, next);
}

function vibeCodeProjectStageForNode(nodeIdRaw, kindRaw = '') {
    const nodeId = safeString(nodeIdRaw).toLowerCase();
    const kind = safeString(kindRaw).toLowerCase();
    if (nodeId === 'user.input' || kind === 'user' || kind === 'input') return 'project.frontend';
    if (nodeId === 'api.chat.request' || kind === 'server') return 'project.api';
    if (nodeId === 'session.resolve' || /session|memory/.test(kind)) return 'project.session';
    if (nodeId === 'route.select' || /route|router/.test(kind)) return 'project.router';
    if (nodeId === 'llm.generate' || /model|reason/.test(kind)) return 'project.model';
    if (nodeId === 'tool.exec' || nodeId.startsWith('tool.') || /tool|integration/.test(kind)) return 'project.tools';
    if (nodeId === 'response.stream' || nodeId === 'response.done' || /stream|result|response/.test(kind)) return 'project.output';
    if (/mission|job|approval/.test(kind)) return 'project.mission';
    if (/content|publish|workflow/.test(kind)) return 'project.content';
    if (/module|workspace|ui/.test(kind)) return 'project.modules';
    return '';
}

function vibeCodeEnsureModuleControlState() {
    if (!(vibeCodeState.controls?.moduleEnabled instanceof Set)) {
        vibeCodeState.controls.moduleEnabled = new Set();
    }
    if (!vibeCodeState.controls.moduleEnabled.size) {
        VIBE_CODE_PROJECT_NODES.forEach((node) => {
            const id = safeString(node?.id);
            if (id) vibeCodeState.controls.moduleEnabled.add(id);
        });
    }
    return vibeCodeState.controls.moduleEnabled;
}

function vibeCodeModuleEnabled(stageIdRaw = '') {
    const stageId = safeString(stageIdRaw);
    if (!stageId) return true;
    const enabled = vibeCodeEnsureModuleControlState();
    return enabled.has(stageId);
}

function vibeCodeApplyModulePreset(presetRaw = 'all') {
    const preset = safeString(presetRaw).toLowerCase();
    const enabled = vibeCodeEnsureModuleControlState();
    enabled.clear();
    VIBE_CODE_PROJECT_NODES.forEach((node) => {
        const stageId = safeString(node?.id);
        if (!stageId) return;
        if (preset === 'core') {
            if (VIBE_CODE_CORE_PROJECT_MODULES.has(stageId)) {
                enabled.add(stageId);
            }
            return;
        }
        enabled.add(stageId);
    });
}

function vibeCodeBuildFlowLayout(nodesRaw, { columns = 4, nodeWidth = 210, nodeHeight = 96, gapX = 28, gapY = 32, padding = 16 } = {}) {
    const nodes = Array.isArray(nodesRaw) ? nodesRaw : [];
    const positions = new Map();
    const maxColumns = Math.max(1, Number(columns) || 1);
    nodes.forEach((node, index) => {
        const col = index % maxColumns;
        const row = Math.floor(index / maxColumns);
        const x = padding + (col * (nodeWidth + gapX));
        const y = padding + (row * (nodeHeight + gapY));
        positions.set(safeString(node?.id), { x, y, w: nodeWidth, h: nodeHeight });
    });
    const rows = Math.max(1, Math.ceil(nodes.length / maxColumns));
    const visibleColumns = Math.max(1, Math.min(maxColumns, nodes.length));
    const width = Math.max(340, padding * 2 + visibleColumns * nodeWidth + Math.max(0, visibleColumns - 1) * gapX);
    const height = Math.max(160, padding * 2 + rows * nodeHeight + Math.max(0, rows - 1) * gapY);
    return { positions, width, height };
}

function vibeCodeRenderFlowCanvas(container, { nodes = [], edges = [], emptyText = 'No flow data yet.', enableEdgeControls = false, onEdgeToggle = null } = {}) {
    if (!(container instanceof HTMLElement)) return;
    container.innerHTML = '';
    if (!Array.isArray(nodes) || !nodes.length) {
        const empty = document.createElement('div');
        empty.className = 'vibe-code-empty';
        empty.textContent = emptyText;
        container.appendChild(empty);
        return;
    }

    const layout = vibeCodeBuildFlowLayout(nodes, {
        columns: Math.min(4, Math.max(2, Math.ceil(Math.sqrt(nodes.length)))),
    });
    const stage = document.createElement('div');
    stage.className = 'vibe-flow-stage';
    stage.style.width = `${layout.width}px`;
    stage.style.height = `${layout.height}px`;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'vibe-flow-links');
    svg.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = `
        <defs>
            <marker id="vibeFlowArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(150, 181, 255, 0.75)"></path>
            </marker>
        </defs>
    `;
    const nodeById = new Map();
    nodes.forEach((nodeRaw) => {
        const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
        const nodeId = safeString(node.id);
        if (!nodeId) return;
        nodeById.set(nodeId, node);
    });
    const validEdges = Array.isArray(edges) ? edges : [];
    validEdges.forEach((edgeRaw) => {
        const edge = edgeRaw && typeof edgeRaw === 'object' ? edgeRaw : {};
        const from = safeString(edge.from);
        const to = safeString(edge.to);
        if (!from || !to) return;
        const fromPos = layout.positions.get(from);
        const toPos = layout.positions.get(to);
        if (!fromPos || !toPos) return;
        const fromNode = nodeById.get(from);
        const toNode = nodeById.get(to);
        const edgeKey = vibeCodeNodeEdgeKey(from, to);
        const manuallyDisconnected = vibeCodeState.controls.disconnectedEdges.has(edgeKey);
        const moduleDisconnected = Boolean(fromNode && fromNode.moduleEnabled === false) || Boolean(toNode && toNode.moduleEnabled === false);
        const disconnected = manuallyDisconnected || moduleDisconnected;
        const x1 = fromPos.x + fromPos.w;
        const y1 = fromPos.y + (fromPos.h / 2);
        const x2 = toPos.x;
        const y2 = toPos.y + (toPos.h / 2);
        const bend = Math.max(26, Math.abs(x2 - x1) * 0.33);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const edgeClassNames = ['vibe-flow-edge'];
        if (disconnected) edgeClassNames.push('is-disconnected');
        if (moduleDisconnected) edgeClassNames.push('is-locked');
        path.setAttribute('class', edgeClassNames.join(' '));
        path.setAttribute('d', `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
        path.setAttribute('marker-end', 'url(#vibeFlowArrow)');
        if (enableEdgeControls) {
            path.dataset.edgeFrom = from;
            path.dataset.edgeTo = to;
            path.dataset.edgeKey = edgeKey;
            if (!moduleDisconnected) {
                const onToggle = () => {
                    const currentlyDisconnected = vibeCodeState.controls.disconnectedEdges.has(edgeKey);
                    if (currentlyDisconnected) {
                        vibeCodeState.controls.disconnectedEdges.delete(edgeKey);
                    } else {
                        vibeCodeState.controls.disconnectedEdges.add(edgeKey);
                    }
                    if (typeof onEdgeToggle === 'function') {
                        onEdgeToggle({
                            from,
                            to,
                            edgeKey,
                            disconnected: !currentlyDisconnected,
                        });
                    }
                };
                path.setAttribute('role', 'button');
                path.setAttribute('tabindex', '0');
                path.setAttribute('aria-label', disconnected
                    ? `Reconnect edge ${from} to ${to}`
                    : `Disconnect edge ${from} to ${to}`);
                path.addEventListener('click', (event) => {
                    event.preventDefault();
                    onToggle();
                });
                path.addEventListener('keydown', (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    onToggle();
                });
            }
        }
        svg.appendChild(path);
    });
    stage.appendChild(svg);

    nodes.forEach((nodeRaw) => {
        const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
        const nodeId = safeString(node.id);
        const pos = layout.positions.get(nodeId);
        if (!pos) return;
        const status = vibeCodeNormalizeStatus(node.status);
        const moduleEnabled = node.moduleEnabled !== false;
        const card = document.createElement('article');
        card.className = `vibe-flow-node is-${status}${moduleEnabled ? '' : ' is-module-off'}`;
        card.style.left = `${pos.x}px`;
        card.style.top = `${pos.y}px`;
        card.style.width = `${pos.w}px`;
        card.style.height = `${pos.h}px`;
        card.innerHTML = `
            <div class="vibe-flow-node-head">
                <strong>${escapeHtml(safeString(node.label) || nodeId)}</strong>
                <span>${escapeHtml(moduleEnabled ? status : 'module off')}</span>
            </div>
            <div class="vibe-flow-node-kind">${escapeHtml(safeString(node.kind) || 'step')}</div>
            <p>${escapeHtml(moduleEnabled
                ? (safeString(node.detail) || safeString(node.summary) || 'Waiting')
                : 'Module disabled. Paths in and out are disconnected.')}</p>
        `;
        stage.appendChild(card);
    });
    container.appendChild(stage);
}

function vibeCodeBuildProjectGraph(trace) {
    const statusById = new Map();
    VIBE_CODE_PROJECT_NODES.forEach((node) => {
        statusById.set(node.id, 'pending');
    });
    if (missionState?.lastPayload && typeof missionState.lastPayload === 'object') {
        statusById.set('project.mission', 'success');
    }
    if (contentState?.payload && typeof contentState.payload === 'object') {
        statusById.set('project.content', 'success');
    }
    if (sidebarNavMode === 'office' || sidebarNavMode === 'mission' || sidebarNavMode === 'content' || MODULE_NAV_MODE_SET.has(sidebarNavMode)) {
        statusById.set('project.modules', 'active');
    }
    if (trace && trace.nodes instanceof Map) {
        for (const node of trace.nodes.values()) {
            const stageId = vibeCodeProjectStageForNode(node?.id, node?.kind);
            if (!stageId) continue;
            statusById.set(stageId, vibeCodeMergeStatus(statusById.get(stageId), node?.status));
        }
    }
    return {
        nodes: VIBE_CODE_PROJECT_NODES.map((node) => {
            const stageId = safeString(node.id);
            const moduleEnabled = vibeCodeModuleEnabled(stageId);
            return {
                ...node,
                kind: 'system',
                detail: node.summary,
                status: statusById.get(stageId) || 'pending',
                moduleEnabled,
                stageId,
            };
        }),
        edges: [...VIBE_CODE_PROJECT_EDGES],
    };
}

function vibeCodeBuildRuntimeGraph(trace) {
    const fallbackNodes = VIBE_CODE_FALLBACK_NODES.map((node) => {
        const id = safeString(node.id);
        const stageId = vibeCodeProjectStageForNode(id, node?.kind);
        return {
            id,
            label: safeString(node.label) || safeString(node.id),
            kind: safeString(node.kind) || 'step',
            detail: safeString(node.summary),
            summary: safeString(node.summary),
            status: 'pending',
            stageId,
            moduleEnabled: vibeCodeModuleEnabled(stageId),
        };
    });
    if (!trace || !(trace.nodes instanceof Map)) {
        return { nodes: fallbackNodes, edges: [...VIBE_CODE_FALLBACK_EDGES] };
    }
    const ids = vibeCodeSortNodeIds(trace);
    const nodes = ids.map((nodeId) => {
        const node = trace.nodes.get(nodeId);
        const stageId = vibeCodeProjectStageForNode(nodeId, node?.kind);
        return {
            id: nodeId,
            label: safeString(node?.label) || nodeId,
            kind: safeString(node?.kind) || 'step',
            detail: safeString(node?.detail) || safeString(node?.summary) || 'Waiting',
            summary: safeString(node?.summary),
            status: vibeCodeNormalizeStatus(node?.status),
            stageId,
            moduleEnabled: vibeCodeModuleEnabled(stageId),
        };
    });
    const nodeIdSet = new Set(ids);
    let edges = Array.isArray(trace.edges)
        ? trace.edges
            .map((edgeRaw) => ({
                from: safeString(edgeRaw?.from || edgeRaw?.source || edgeRaw?.src || edgeRaw?.from_id),
                to: safeString(edgeRaw?.to || edgeRaw?.target || edgeRaw?.dst || edgeRaw?.to_id),
            }))
            .filter((edge) => edge.from && edge.to && nodeIdSet.has(edge.from) && nodeIdSet.has(edge.to))
        : [];
    if (!edges.length) {
        edges = [];
        for (let index = 0; index < ids.length - 1; index += 1) {
            edges.push({ from: ids[index], to: ids[index + 1] });
        }
    }
    return { nodes, edges };
}

function vibeCodeCollectVisibleEdgeKeys(trace = vibeCodeActiveTrace()) {
    const keys = new Set();
    const graphs = [];
    if (vibeCodeState.controls.projectEnabled) {
        graphs.push(vibeCodeBuildProjectGraph(trace));
    }
    if (vibeCodeState.controls.runtimeEnabled) {
        graphs.push(vibeCodeBuildRuntimeGraph(trace));
    }
    graphs.forEach((graph) => {
        const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
        const edges = Array.isArray(graph?.edges) ? graph.edges : [];
        const nodeById = new Map();
        nodes.forEach((nodeRaw) => {
            const node = nodeRaw && typeof nodeRaw === 'object' ? nodeRaw : {};
            const id = safeString(node.id);
            if (!id) return;
            nodeById.set(id, node);
        });
        edges.forEach((edgeRaw) => {
            const from = safeString(edgeRaw?.from);
            const to = safeString(edgeRaw?.to);
            if (!from || !to) return;
            const fromNode = nodeById.get(from);
            const toNode = nodeById.get(to);
            if (fromNode && fromNode.moduleEnabled === false) return;
            if (toNode && toNode.moduleEnabled === false) return;
            keys.add(vibeCodeNodeEdgeKey(from, to));
        });
    });
    return [...keys];
}

function vibeCodeSetVisibleEdgesDisconnected(disconnected = true) {
    const keys = vibeCodeCollectVisibleEdgeKeys(vibeCodeActiveTrace());
    keys.forEach((key) => {
        if (disconnected) {
            vibeCodeState.controls.disconnectedEdges.add(key);
        } else {
            vibeCodeState.controls.disconnectedEdges.delete(key);
        }
    });
    return keys.length;
}

function vibeCodeRenderModuleControls() {
    if (!(vibeCodeState.moduleGridEl instanceof HTMLElement)) return;
    const enabled = vibeCodeEnsureModuleControlState();
    vibeCodeState.moduleGridEl.innerHTML = '';
    VIBE_CODE_PROJECT_NODES.forEach((node) => {
        const stageId = safeString(node?.id);
        if (!stageId) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `vibe-module-chip${enabled.has(stageId) ? '' : ' is-off'}`;
        button.dataset.vibeModuleId = stageId;
        button.setAttribute('aria-pressed', enabled.has(stageId) ? 'true' : 'false');
        button.textContent = safeString(node?.label) || stageId;
        button.addEventListener('click', () => {
            if (enabled.has(stageId)) {
                enabled.delete(stageId);
            } else {
                enabled.add(stageId);
            }
            vibeCodeRender();
            if (sidebarNavMode === 'vibe_code') {
                moduleRender('vibe_code', { touch: false });
            }
        });
        vibeCodeState.moduleGridEl.appendChild(button);
    });
    if (vibeCodeState.edgeCountEl instanceof HTMLElement) {
        vibeCodeState.edgeCountEl.textContent = `${vibeCodeState.controls.disconnectedEdges.size} edge${vibeCodeState.controls.disconnectedEdges.size === 1 ? '' : 's'} cut`;
    }
}

function vibeCodeRenderDiscovered() {
    if (!(vibeCodeState.discoveryEl instanceof HTMLElement)) return;
    const rows = [...vibeCodeState.discoveredNodes.values()]
        .sort((left, right) => (Number(right?.lastSeenMs) || 0) - (Number(left?.lastSeenMs) || 0))
        .slice(0, 16);
    vibeCodeState.discoveryEl.innerHTML = '';
    if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'vibe-code-empty';
        empty.textContent = 'Nodes auto-appear here as the project executes new paths.';
        vibeCodeState.discoveryEl.appendChild(empty);
        return;
    }
    const list = document.createElement('ul');
    list.className = 'vibe-code-discovery-list';
    rows.forEach((row) => {
        const status = vibeCodeNormalizeStatus(row?.status);
        const item = document.createElement('li');
        item.className = `vibe-code-discovery-item is-${status}`;
        item.innerHTML = `
            <strong>${escapeHtml(safeString(row?.label) || safeString(row?.id) || 'node')}</strong>
            <span>${escapeHtml(safeString(row?.kind) || 'step')}  seen ${escapeHtml(String(Number(row?.seenCount) || 1))}x</span>
        `;
        list.appendChild(item);
    });
    vibeCodeState.discoveryEl.appendChild(list);
}

function vibeCodeBuildQueueRows(limit = 12) {
    const trace = vibeCodeActiveTrace();
    if (!trace) {
        return [
            {
                id: 'vibe-waiting',
                title: 'Waiting for first trace',
                meta: 'Send a message in chat to execute and visualize runtime flow.',
                badge: 'pending',
                tone: 'warn',
                actions: [],
            },
        ];
    }
    return vibeCodeSortNodeIds(trace)
        .map((nodeId) => trace.nodes.get(nodeId))
        .filter(Boolean)
        .slice(0, Math.max(1, Number(limit) || 12))
        .map((node) => ({
            id: safeString(node.id),
            title: safeString(node.label) || safeString(node.id) || 'Node',
            meta: safeString(node.detail) || safeString(node.summary) || 'Waiting',
            badge: vibeCodeNormalizeStatus(node.status),
            tone: vibeCodeToneFromStatus(node.status),
            actions: [],
        }));
}

function vibeCodeBuildHealthRows(limit = 10) {
    const trace = vibeCodeActiveTrace();
    return vibeCodeBuildProjectGraph(trace).nodes
        .slice(0, Math.max(1, Number(limit) || 10))
        .map((node) => ({
            id: safeString(node.id),
            title: safeString(node.label) || safeString(node.id) || 'System',
            meta: safeString(node.summary) || '',
            badge: vibeCodeNormalizeStatus(node.status),
            tone: vibeCodeToneFromStatus(node.status),
            actions: [],
        }));
}

function vibeCodeBuildActivityRows(limit = 14) {
    const trace = vibeCodeActiveTrace();
    if (!trace || !Array.isArray(trace.events)) return [];
    return trace.events
        .slice(0, Math.max(1, Number(limit) || 14))
        .map((entry, index) => ({
            id: `vibe-event-${index}-${safeString(trace.id)}`,
            title: safeString(entry?.text) || 'Runtime event',
            meta: new Date(Number(entry?.tsMs) || Date.now()).toLocaleTimeString(),
            badge: vibeCodeNormalizeStatus(entry?.status),
            tone: vibeCodeToneFromStatus(entry?.status),
            actions: [],
        }));
}

function vibeCodeCollectStats() {
    const trace = vibeCodeActiveTrace();
    const discovered = vibeCodeState.discoveredNodes.size;
    const moduleEnabled = vibeCodeEnsureModuleControlState().size;
    const modulesDisabled = Math.max(0, VIBE_CODE_PROJECT_NODES.length - moduleEnabled);
    const cutEdges = vibeCodeState.controls.disconnectedEdges.size;
    if (!trace || !(trace.nodes instanceof Map)) {
        return {
            trace_count: vibeCodeState.traces.size,
            runtime_steps: 0,
            runtime_active: 0,
            runtime_errors: 0,
            runtime_discovered: discovered,
            runtime_cut_edges: cutEdges,
            modules_disabled: modulesDisabled,
        };
    }
    let activeCount = 0;
    let errorCount = 0;
    trace.nodes.forEach((node) => {
        const status = vibeCodeNormalizeStatus(node?.status);
        if (status === 'active') activeCount += 1;
        if (status === 'error') errorCount += 1;
    });
    return {
        trace_count: vibeCodeState.traces.size,
        runtime_steps: trace.nodes.size,
        runtime_active: activeCount,
        runtime_errors: errorCount,
        runtime_discovered: discovered,
        runtime_cut_edges: cutEdges,
        modules_disabled: modulesDisabled,
    };
}

function vibeCodeEnsurePanel(mountTarget = null) {
    vibeCodeEnsureModuleControlState();
    const mount = mountTarget instanceof HTMLElement
        ? mountTarget
        : ((sidebarNavMode === 'vibe_code' && moduleWorkbench instanceof HTMLElement) ? moduleWorkbench : null);
    if (!mount) return null;

    if (vibeCodeState.panel instanceof HTMLElement && document.body.contains(vibeCodeState.panel)) {
        if (vibeCodeState.panel.parentElement !== mount) {
            mount.appendChild(vibeCodeState.panel);
        }
        return vibeCodeState.panel;
    }

    const panel = document.createElement('section');
    panel.id = 'vibeCodePanel';
    panel.className = 'vibe-code-panel vibe-code-panel-module';
    panel.innerHTML = `
        <header class="vibe-code-head">
            <div class="vibe-code-heading">
                <strong>Vibe Code</strong>
                <span class="vibe-code-sub">Project flowchart + live runtime trace</span>
            </div>
            <div class="vibe-code-head-actions">
                <span class="vibe-code-status-pill" data-vibe-status>idle</span>
                <button class="vibe-code-toggle" type="button" data-vibe-toggle aria-expanded="true">Collapse</button>
            </div>
        </header>
        <p class="vibe-code-meta" data-vibe-meta>Waiting for trace graph...</p>
        <div class="vibe-code-controls" data-vibe-controls>
            <div class="vibe-code-controls-row">
                <label><input type="checkbox" data-vibe-project-toggle checked> Project flow</label>
                <label><input type="checkbox" data-vibe-runtime-toggle checked> Runtime flow</label>
                <button type="button" class="vibe-code-btn" data-vibe-disconnect-visible>Disconnect Visible</button>
                <button type="button" class="vibe-code-btn" data-vibe-reconnect-visible>Reconnect Visible</button>
                <span class="vibe-code-edge-count" data-vibe-edge-count>0 edges cut</span>
            </div>
            <div class="vibe-code-controls-row vibe-code-controls-row-modules">
                <span class="vibe-code-control-label">Modules</span>
                <button type="button" class="vibe-code-btn" data-vibe-modules-all>All</button>
                <button type="button" class="vibe-code-btn" data-vibe-modules-core>Core Path</button>
            </div>
            <div class="vibe-code-module-grid" data-vibe-module-grid></div>
            <p class="vibe-code-control-note">Click edges to disconnect/reconnect. Disable modules to cut entire paths.</p>
        </div>
        <div class="vibe-code-body" data-vibe-body>
            <section class="vibe-code-block" data-vibe-project-block>
                <h4>Project Systems</h4>
                <div class="vibe-flow-canvas" data-vibe-project-flow></div>
            </section>
            <section class="vibe-code-block" data-vibe-runtime-block>
                <h4>Live Request Flow (Comfy-style)</h4>
                <div class="vibe-flow-canvas" data-vibe-runtime-flow></div>
            </section>
            <section class="vibe-code-block">
                <h4>Runtime Events</h4>
                <ol class="vibe-code-log" data-vibe-log></ol>
            </section>
            <section class="vibe-code-block">
                <h4>Discovered Nodes</h4>
                <div class="vibe-code-discovery" data-vibe-discovery></div>
            </section>
        </div>
    `;
    mount.appendChild(panel);

    vibeCodeState.panel = panel;
    vibeCodeState.graphEl = panel.querySelector('[data-vibe-runtime-flow]');
    vibeCodeState.projectFlowEl = panel.querySelector('[data-vibe-project-flow]');
    vibeCodeState.runtimeFlowEl = panel.querySelector('[data-vibe-runtime-flow]');
    vibeCodeState.logEl = panel.querySelector('[data-vibe-log]');
    vibeCodeState.discoveryEl = panel.querySelector('[data-vibe-discovery]');
    vibeCodeState.metaEl = panel.querySelector('[data-vibe-meta]');
    vibeCodeState.statusPillEl = panel.querySelector('[data-vibe-status]');
    vibeCodeState.bodyEl = panel.querySelector('[data-vibe-body]');
    vibeCodeState.toggleBtn = panel.querySelector('[data-vibe-toggle]');
    vibeCodeState.controlsEl = panel.querySelector('[data-vibe-controls]');
    vibeCodeState.moduleGridEl = panel.querySelector('[data-vibe-module-grid]');
    vibeCodeState.edgeCountEl = panel.querySelector('[data-vibe-edge-count]');
    vibeCodeState.collapsed = false;

    if (vibeCodeState.toggleBtn instanceof HTMLButtonElement) {
        vibeCodeState.toggleBtn.addEventListener('click', () => {
            vibeCodeState.collapsed = !vibeCodeState.collapsed;
            panel.classList.toggle('collapsed', vibeCodeState.collapsed);
            vibeCodeState.toggleBtn.textContent = vibeCodeState.collapsed ? 'Expand' : 'Collapse';
            vibeCodeState.toggleBtn.setAttribute('aria-expanded', vibeCodeState.collapsed ? 'false' : 'true');
        });
    }

    const projectToggle = panel.querySelector('[data-vibe-project-toggle]');
    const runtimeToggle = panel.querySelector('[data-vibe-runtime-toggle]');
    if (projectToggle instanceof HTMLInputElement) {
        projectToggle.checked = Boolean(vibeCodeState.controls.projectEnabled);
        projectToggle.addEventListener('change', () => {
            vibeCodeState.controls.projectEnabled = Boolean(projectToggle.checked);
            panel.classList.toggle('project-disabled', !vibeCodeState.controls.projectEnabled);
            vibeCodeRender();
        });
    }
    if (runtimeToggle instanceof HTMLInputElement) {
        runtimeToggle.checked = Boolean(vibeCodeState.controls.runtimeEnabled);
        runtimeToggle.addEventListener('change', () => {
            vibeCodeState.controls.runtimeEnabled = Boolean(runtimeToggle.checked);
            panel.classList.toggle('runtime-disabled', !vibeCodeState.controls.runtimeEnabled);
            vibeCodeRender();
        });
    }
    panel.classList.toggle('project-disabled', !vibeCodeState.controls.projectEnabled);
    panel.classList.toggle('runtime-disabled', !vibeCodeState.controls.runtimeEnabled);
    const disconnectVisibleBtn = panel.querySelector('[data-vibe-disconnect-visible]');
    const reconnectVisibleBtn = panel.querySelector('[data-vibe-reconnect-visible]');
    const modulesAllBtn = panel.querySelector('[data-vibe-modules-all]');
    const modulesCoreBtn = panel.querySelector('[data-vibe-modules-core]');
    if (disconnectVisibleBtn instanceof HTMLButtonElement) {
        disconnectVisibleBtn.addEventListener('click', () => {
            vibeCodeSetVisibleEdgesDisconnected(true);
            vibeCodeRender();
        });
    }
    if (reconnectVisibleBtn instanceof HTMLButtonElement) {
        reconnectVisibleBtn.addEventListener('click', () => {
            vibeCodeSetVisibleEdgesDisconnected(false);
            vibeCodeRender();
        });
    }
    if (modulesAllBtn instanceof HTMLButtonElement) {
        modulesAllBtn.addEventListener('click', () => {
            vibeCodeApplyModulePreset('all');
            vibeCodeRender();
        });
    }
    if (modulesCoreBtn instanceof HTMLButtonElement) {
        modulesCoreBtn.addEventListener('click', () => {
            vibeCodeApplyModulePreset('core');
            vibeCodeRender();
        });
    }
    vibeCodeRenderModuleControls();
    return panel;
}

function vibeCodeRender() {
    const panel = vibeCodeEnsurePanel(sidebarNavMode === 'vibe_code' ? moduleWorkbench : null);
    if (!(panel instanceof HTMLElement)) return;
    const trace = vibeCodeActiveTrace();
    const topStatus = trace ? vibeCodeTopStatus(trace) : 'pending';

    if (vibeCodeState.metaEl instanceof HTMLElement) {
        if (!trace) {
            vibeCodeState.metaEl.textContent = 'Waiting for trace graph. Send a chat message to animate the pipeline.';
        } else {
            const meta = trace.meta || {};
            const profileText = safeString(meta.profile) || '-';
            const modeText = safeString(meta.mode) || '-';
            const sessionText = safeString(meta.session_id || '').slice(0, 12) || '-';
            const traceText = safeString(trace.id).slice(0, 12) || '-';
            vibeCodeState.metaEl.textContent = `Session ${sessionText} | Trace ${traceText} | profile=${profileText} | mode=${modeText}`;
        }
    }
    if (vibeCodeState.statusPillEl instanceof HTMLElement) {
        vibeCodeState.statusPillEl.textContent = trace ? topStatus : 'idle';
        vibeCodeState.statusPillEl.className = trace
            ? `vibe-code-status-pill is-${topStatus}`
            : 'vibe-code-status-pill';
    }

    const projectBlock = panel.querySelector('[data-vibe-project-block]');
    const runtimeBlock = panel.querySelector('[data-vibe-runtime-block]');
    if (projectBlock instanceof HTMLElement) {
        projectBlock.classList.toggle('hidden', !vibeCodeState.controls.projectEnabled);
    }
    if (runtimeBlock instanceof HTMLElement) {
        runtimeBlock.classList.toggle('hidden', !vibeCodeState.controls.runtimeEnabled);
    }

    const edgeToggleHandler = () => {
        vibeCodeRender();
    };

    if (vibeCodeState.controls.projectEnabled) {
        const projectGraph = vibeCodeBuildProjectGraph(trace);
        vibeCodeRenderFlowCanvas(vibeCodeState.projectFlowEl, {
            nodes: projectGraph.nodes,
            edges: projectGraph.edges,
            emptyText: 'Project systems flow unavailable.',
            enableEdgeControls: true,
            onEdgeToggle: edgeToggleHandler,
        });
    }
    if (vibeCodeState.controls.runtimeEnabled) {
        const runtimeGraph = vibeCodeBuildRuntimeGraph(trace);
        vibeCodeRenderFlowCanvas(vibeCodeState.runtimeFlowEl, {
            nodes: runtimeGraph.nodes,
            edges: runtimeGraph.edges,
            emptyText: 'Waiting for runtime graph.',
            enableEdgeControls: true,
            onEdgeToggle: edgeToggleHandler,
        });
    }

    if (vibeCodeState.logEl instanceof HTMLElement) {
        vibeCodeState.logEl.innerHTML = '';
        const events = trace && Array.isArray(trace.events) ? trace.events.slice(0, 24) : [];
        if (!events.length) {
            const row = document.createElement('li');
            row.className = 'vibe-log-item';
            row.innerHTML = '<span class="vibe-log-time">--:--:--</span><span class="vibe-log-text">Waiting for runtime events.</span>';
            vibeCodeState.logEl.appendChild(row);
        } else {
            const logFragment = document.createDocumentFragment();
            for (const entry of events) {
                const row = document.createElement('li');
                row.className = `vibe-log-item is-${vibeCodeNormalizeStatus(entry?.status)}`;
                row.innerHTML = `
                    <span class="vibe-log-time">${escapeHtml(new Date(Number(entry?.tsMs) || Date.now()).toLocaleTimeString())}</span>
                    <span class="vibe-log-text">${escapeHtml(safeString(entry?.text) || 'event')}</span>
                `;
                logFragment.appendChild(row);
            }
            vibeCodeState.logEl.appendChild(logFragment);
        }
    }
    vibeCodeRenderModuleControls();
    vibeCodeRenderDiscovered();
}

function vibeCodePrepareForRequest(payload) {
    if (sidebarNavMode !== 'vibe_code') return;
    const panel = vibeCodeEnsurePanel(moduleWorkbench);
    if (!(panel instanceof HTMLElement)) return;
    const sessionText = safeString(payload?.session_id || sessionId).slice(0, 12) || '-';
    if (vibeCodeState.metaEl instanceof HTMLElement) {
        vibeCodeState.metaEl.textContent = `Session ${sessionText} | waiting for trace graph...`;
    }
    if (vibeCodeState.statusPillEl instanceof HTMLElement) {
        vibeCodeState.statusPillEl.textContent = 'pending';
        vibeCodeState.statusPillEl.className = 'vibe-code-status-pill is-pending';
    }
}

function vibeCodeHandleGraphEvent(evt) {
    const traceId = safeString(evt?.trace_id || evt?.run_id);
    if (!traceId) return;
    const trace = vibeCodeCreateTrace(traceId);
    const graph = evt?.graph;
    if (graph && Array.isArray(graph.nodes)) {
        trace.nodes.clear();
        trace.order = [];
        for (const node of graph.nodes) {
            if (!node || typeof node !== 'object') continue;
            const nodeId = safeString(node.id);
            if (!nodeId) continue;
            const nextNode = {
                id: nodeId,
                label: safeString(node.label) || nodeId,
                kind: safeString(node.kind) || 'step',
                summary: safeString(node.summary),
                detail: safeString(node.summary),
                status: 'pending',
            };
            trace.nodes.set(nodeId, nextNode);
            trace.order.push(nodeId);
            vibeCodeRegisterNode(nextNode);
        }
    }
    if (graph && Array.isArray(graph.edges)) {
        trace.edges = graph.edges
            .map((edgeRaw) => ({
                from: safeString(edgeRaw?.from || edgeRaw?.source || edgeRaw?.src || edgeRaw?.from_id),
                to: safeString(edgeRaw?.to || edgeRaw?.target || edgeRaw?.dst || edgeRaw?.to_id),
            }))
            .filter((edge) => edge.from && edge.to);
    }
    trace.meta = (evt && typeof evt.meta === 'object' && evt.meta) ? { ...evt.meta } : {};
    trace.events.unshift({
        tsMs: Date.now(),
        status: 'pending',
        text: 'Trace graph received.',
    });
    vibeCodeState.traces.set(traceId, trace);
    vibeCodeState.activeTraceId = traceId;
    vibeCodeRender();
    if (sidebarNavMode === 'vibe_code') {
        moduleRender('vibe_code', { touch: false });
    }
}

function vibeCodeHandleTraceEvent(evt) {
    const traceId = safeString(evt?.trace_id || evt?.run_id);
    if (!traceId) return;
    if (!vibeCodeState.traces.has(traceId)) {
        vibeCodeState.traces.set(traceId, vibeCodeCreateTrace(traceId));
    }
    const trace = vibeCodeState.traces.get(traceId);
    if (!trace) return;
    const nodeId = safeString(evt?.node_id);
    if (!nodeId) return;
    let node = trace.nodes.get(nodeId);
    if (!node) {
        node = {
            id: nodeId,
            label: safeString(evt?.label) || nodeId,
            kind: safeString(evt?.kind) || 'step',
            summary: '',
            detail: '',
            status: 'pending',
        };
        trace.nodes.set(nodeId, node);
        trace.order.push(nodeId);
        const prevNodeId = trace.order.length > 1 ? trace.order[trace.order.length - 2] : '';
        if (prevNodeId && prevNodeId !== nodeId) {
            trace.edges.push({ from: prevNodeId, to: nodeId });
        }
    }
    const status = vibeCodeNormalizeStatus(evt?.status);
    const labelText = safeString(evt?.label);
    if (labelText) node.label = labelText;
    const detailText = safeString(evt?.detail);
    if (detailText) node.detail = detailText;
    const kindText = safeString(evt?.kind);
    if (kindText) node.kind = kindText;
    node.status = status;
    vibeCodeRegisterNode(node, status);
    trace.events.unshift({
        tsMs: Number(evt?.ts_ms) || Date.now(),
        status,
        text: `${safeString(node.label) || nodeId}: ${detailText || status}`,
    });
    trace.events = trace.events.slice(0, 40);
    vibeCodeState.activeTraceId = traceId;
    vibeCodeRender();
    if (sidebarNavMode === 'vibe_code') {
        moduleRender('vibe_code', { touch: false });
    }
}

/**
 * Stream an assistant response from the /api/chat endpoint.
 *
 * Extracted from handleSend() so that edit-message, regenerate, and retry
 * flows can reuse the same streaming + rendering logic without duplication.
 *
 * @param {Object} payload - The chat API payload (message, session_id, profile, etc.)
 * @param {Object} opts
 * @param {string} [opts.userContext] - User context string for follow-up suggestions
 * @param {string} [opts.existingBubbleId] - Reuse an existing assistant bubble instead of creating one
 */
