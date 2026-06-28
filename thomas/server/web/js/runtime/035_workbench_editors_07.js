
function moduleRenderWorkbenchGameStudio(container, wb) {
    if (moduleRenderWorkbenchGameStudioOss(container, wb)) return;
    if (!container || !wb) return;
    wb.gridWidth = moduleWorkbenchClamp(Number(wb.gridWidth) || 20, 8, 64);
    wb.gridHeight = moduleWorkbenchClamp(Number(wb.gridHeight) || 12, 6, 40);
    wb.brush = moduleWorkbenchClamp(Number(wb.brush) || 1, 0, 4);
    if (!Array.isArray(wb.tiles) || wb.tiles.length !== wb.gridHeight || (Array.isArray(wb.tiles[0]) && wb.tiles[0].length !== wb.gridWidth)) wb.tiles = Array.from({ length: wb.gridHeight }, () => Array.from({ length: wb.gridWidth }, () => 0));
    if (!Array.isArray(wb.logs)) wb.logs = [];

    moduleWorkbenchHeader(container, 'Game Studio Level Grid', 'Define level intent and let Thomas validate playability, packaging, and handoff outputs.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-game';
    shell.innerHTML = `
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Grid</span><span class="module-wb-stage-meta" data-game-status></span></div><div class="module-wb-tool-group" data-game-brushes></div><div class="module-wb-toolbar-actions"><label class="module-wb-inline-field">W <input type="number" min="8" max="64" data-game-size="width" value="${wb.gridWidth}" /></label><label class="module-wb-inline-field">H <input type="number" min="6" max="40" data-game-size="height" value="${wb.gridHeight}" /></label><button type="button" class="module-item-btn" data-game-action="resize">Resize Grid</button></div><div class="module-wb-game-grid" data-game-grid></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-game-action="check">Path Check</button><button type="button" class="module-item-btn" data-game-action="clear">Clear</button><button type="button" class="module-item-btn" data-game-action="export">Export</button></div></section>
        <aside class="module-wb-inspector-card"><h4>Metrics</h4><div class="module-wb-metrics" data-game-metrics></div><h4>Logs</h4><div class="module-wb-log-list" data-game-logs></div></aside>
        ${moduleWorkbenchRenderOssStack('game_studio')}
    `;
    container.appendChild(shell);

    const brushes = [{ id: 0, label: 'Erase' }, { id: 1, label: 'Platform' }, { id: 2, label: 'Hazard' }, { id: 3, label: 'Spawn' }, { id: 4, label: 'Goal' }];
    const brushBar = shell.querySelector('[data-game-brushes]');
    const grid = shell.querySelector('[data-game-grid]');
    const status = shell.querySelector('[data-game-status]');
    const metrics = shell.querySelector('[data-game-metrics]');
    const logs = shell.querySelector('[data-game-logs]');
    const sizeWidthInput = shell.querySelector('input[data-game-size="width"]');
    const sizeHeightInput = shell.querySelector('input[data-game-size="height"]');
    const counts = () => { const c = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0 }; wb.tiles.forEach((row) => row.forEach((tile) => { c[String(moduleWorkbenchClamp(Number(tile) || 0, 0, 4))] += 1; })); return c; };
    const paint = (x, y) => { const value = moduleWorkbenchClamp(Number(wb.brush) || 0, 0, 4); if (value === 3 || value === 4) wb.tiles.forEach((row, rowIndex) => row.forEach((tile, colIndex) => { if (Number(tile) === value) wb.tiles[rowIndex][colIndex] = 0; })); wb.tiles[y][x] = value; };
    const playable = () => {
        let start = null;
        const goals = new Set();
        for (let y = 0; y < wb.gridHeight; y += 1) for (let x = 0; x < wb.gridWidth; x += 1) { const tile = Number(wb.tiles[y][x]) || 0; if (tile === 3) start = { x, y }; if (tile === 4) goals.add(`${x},${y}`); }
        if (!start || !goals.size) return false;
        const queue = [start];
        const seen = new Set([`${start.x},${start.y}`]);
        while (queue.length) { const current = queue.shift(); if (!current) continue; if (goals.has(`${current.x},${current.y}`)) return true; [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => { const nx = current.x + dx; const ny = current.y + dy; if (nx < 0 || ny < 0 || nx >= wb.gridWidth || ny >= wb.gridHeight) return; const tile = Number(wb.tiles[ny][nx]) || 0; if (tile === 0 || tile === 2) return; const key = `${nx},${ny}`; if (seen.has(key)) return; seen.add(key); queue.push({ x: nx, y: ny }); }); }
        return false;
    };
    const render = () => {
        brushBar.innerHTML = brushes.map((brush) => `<button type="button" class="module-wb-tool-btn${Number(wb.brush) === brush.id ? ' active' : ''}" data-game-brush="${brush.id}"><span>${brush.label}</span></button>`).join('');
        grid.style.gridTemplateColumns = `repeat(${wb.gridWidth}, minmax(0, 1fr))`;
        const cells = [];
        for (let y = 0; y < wb.gridHeight; y += 1) for (let x = 0; x < wb.gridWidth; x += 1) cells.push(`<button type="button" class="module-wb-game-cell tile-${moduleWorkbenchClamp(Number(wb.tiles[y][x]) || 0, 0, 4)}" data-game-x="${x}" data-game-y="${y}"></button>`);
        grid.innerHTML = cells.join('');
        const c = counts();
        metrics.innerHTML = `<div><span>Platforms</span><strong>${c[1]}</strong></div><div><span>Hazards</span><strong>${c[2]}</strong></div><div><span>Spawn</span><strong>${c[3]}</strong></div><div><span>Goal</span><strong>${c[4]}</strong></div>`;
        status.textContent = `${wb.gridWidth}x${wb.gridHeight} | ${playable() ? 'Playable path found' : 'No valid path'}`;
        if (sizeWidthInput instanceof HTMLInputElement) sizeWidthInput.value = String(wb.gridWidth);
        if (sizeHeightInput instanceof HTMLInputElement) sizeHeightInput.value = String(wb.gridHeight);
        logs.innerHTML = wb.logs.length ? wb.logs.slice(0, 14).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('') : '<div class="module-wb-ghost">No validation logs yet.</div>';
    };
    render();
    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-game-brush], [data-game-action], [data-game-x][data-game-y]') : null;
        if (!target) return;
        const brush = safeString(target.dataset.gameBrush);
        const action = safeString(target.dataset.gameAction).toLowerCase();
        if (brush) { wb.brush = moduleWorkbenchClamp(Number(brush) || 0, 0, 4); render(); return; }
        if (action === 'check') moduleWorkbenchPushLog(wb.logs, playable() ? 'Path check passed.' : 'Path check failed.', playable() ? 'ok' : 'warn', 60, 'game-log');
        if (action === 'clear') { wb.tiles = Array.from({ length: wb.gridHeight }, () => Array.from({ length: wb.gridWidth }, () => 0)); moduleWorkbenchPushLog(wb.logs, 'Cleared level grid.', 'warn', 60, 'game-log'); }
        if (action === 'resize') {
            moduleGameStudioResizeGrid(
                wb,
                Number(sizeWidthInput instanceof HTMLInputElement ? sizeWidthInput.value : wb.gridWidth),
                Number(sizeHeightInput instanceof HTMLInputElement ? sizeHeightInput.value : wb.gridHeight),
            );
            moduleWorkbenchPushLog(wb.logs, `Resized grid to ${wb.gridWidth}x${wb.gridHeight}.`, 'ok', 60, 'game-log');
        }
        if (action === 'export') moduleWorkbenchCopyJson({ width: wb.gridWidth, height: wb.gridHeight, tiles: wb.tiles }, 'Game Studio Level JSON');
        const x = Number(target.dataset.gameX);
        const y = Number(target.dataset.gameY);
        if (Number.isFinite(x) && Number.isFinite(y)) paint(x, y);
        render();
    });
}

function moduleRenderWorkbenchResearch(container, wb) {
    if (!container || !wb) return;
    if (!Array.isArray(wb.queries)) wb.queries = [];
    if (!Array.isArray(wb.sources)) wb.sources = [];
    if (!Array.isArray(wb.claims)) wb.claims = [];
    wb.notes = safeString(wb.notes);
    wb.synthesis = safeString(wb.synthesis);

    moduleWorkbenchHeader(container, 'Research Lab', 'Thomas executes source-backed research runs while you review citations, claims, and synthesized conclusions.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-research';
    shell.innerHTML = `
        <aside class="module-wb-side-card"><h4>Queries</h4><form class="module-wb-inline-form" data-research-query-form><input type="text" data-research-query placeholder="Research question" /><button type="submit" class="module-item-btn">Add</button></form><div class="module-wb-research-list" data-research-queries></div><h4>Sources</h4><form class="module-wb-inline-form" data-research-source-form><input type="text" data-research-source-title placeholder="Title" /><input type="text" data-research-source-url placeholder="URL" /><button type="submit" class="module-item-btn">Save</button></form><div class="module-wb-research-list" data-research-sources></div></aside>
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Notes + Claims</span><span class="module-wb-stage-meta" data-research-status></span></div><label class="module-wb-field module-wb-field-wide">Notes<textarea rows="8" data-research-notes>${escapeHtml(wb.notes)}</textarea></label><form class="module-wb-inline-form" data-research-claim-form><input type="text" data-research-claim-text placeholder="Claim" /><select data-research-claim-source></select><input type="number" min="0" max="100" value="70" data-research-claim-confidence /><button type="submit" class="module-item-btn">Add Claim</button></form><div class="module-wb-claims-table" data-research-claims></div></section>
        <aside class="module-wb-inspector-card"><h4>Synthesis</h4><textarea rows="12" data-research-synthesis>${escapeHtml(wb.synthesis)}</textarea><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-research-action="synthesize">Generate</button><button type="button" class="module-item-btn" data-research-action="export">Export</button><button type="button" class="module-item-btn" data-research-action="clear">Clear</button></div></aside>
        ${moduleWorkbenchRenderOssStack('research_lab')}
    `;
    container.appendChild(shell);

    const queries = shell.querySelector('[data-research-queries]');
    const sources = shell.querySelector('[data-research-sources]');
    const claims = shell.querySelector('[data-research-claims]');
    const status = shell.querySelector('[data-research-status]');
    const notes = shell.querySelector('[data-research-notes]');
    const synthesis = shell.querySelector('[data-research-synthesis]');
    const claimSource = shell.querySelector('[data-research-claim-source]');
    const sourceById = (id) => wb.sources.find((source) => safeString(source.id) === safeString(id)) || null;
    const render = () => {
        queries.innerHTML = wb.queries.length ? wb.queries.slice(0, 12).map((query) => `<article class="module-wb-list-item"><strong>${escapeHtml(safeString(query.text))}</strong><span>${escapeHtml(safeString(query.time))}</span></article>`).join('') : '<div class="module-wb-ghost">No saved queries yet.</div>';
        sources.innerHTML = wb.sources.length ? wb.sources.map((source) => `<article class="module-wb-list-item"><strong>${escapeHtml(safeString(source.title))}</strong><span>${escapeHtml(safeString(source.url))}</span></article>`).join('') : '<div class="module-wb-ghost">No sources yet.</div>';
        claimSource.innerHTML = `<option value="">Source</option>${wb.sources.map((source) => `<option value="${escapeHtml(safeString(source.id))}">${escapeHtml(safeString(source.title))}</option>`).join('')}`;
        claims.innerHTML = wb.claims.length ? wb.claims.map((claim) => `<article class="module-wb-list-item"><strong>${escapeHtml(safeString(claim.text))}</strong><span>${escapeHtml(`${sourceById(claim.sourceId)?.title || 'No source'} | ${claim.confidence}%`)}</span></article>`).join('') : '<div class="module-wb-ghost">No claims yet.</div>';
        status.textContent = `${wb.sources.length} sources | ${wb.claims.length} claims`;
    };
    const synthesize = () => { const top = wb.claims.slice(0, 4).map((claim, index) => `${index + 1}. ${claim.text} (${claim.confidence}% | ${sourceById(claim.sourceId)?.title || 'No source'})`); wb.synthesis = [`Research Focus: ${wb.queries[0]?.text || 'No query'}`, `Sources: ${wb.sources.length}`, `Claims: ${wb.claims.length}`, '', 'Top Claims:', top.length ? top.join('\n') : '- none', '', 'Notes:', wb.notes || '- none'].join('\n'); if (synthesis) synthesis.value = wb.synthesis; };
    render();
    const queryForm = shell.querySelector('[data-research-query-form]');
    const sourceForm = shell.querySelector('[data-research-source-form]');
    const claimForm = shell.querySelector('[data-research-claim-form]');
    if (queryForm instanceof HTMLFormElement) queryForm.addEventListener('submit', (event) => { event.preventDefault(); const input = queryForm.querySelector('[data-research-query]'); const text = safeString(input?.value); if (!text) return; wb.queries.unshift({ id: moduleWorkbenchMakeId('query'), text, time: moduleWorkbenchTimeStamp() }); if (input) input.value = ''; render(); });
    if (sourceForm instanceof HTMLFormElement) sourceForm.addEventListener('submit', (event) => { event.preventDefault(); const titleInput = sourceForm.querySelector('[data-research-source-title]'); const urlInput = sourceForm.querySelector('[data-research-source-url]'); const title = safeString(titleInput?.value) || 'Untitled Source'; const url = safeString(urlInput?.value); if (!title && !url) return; wb.sources.unshift({ id: moduleWorkbenchMakeId('source'), title, url }); if (titleInput) titleInput.value = ''; if (urlInput) urlInput.value = ''; render(); });
    if (claimForm instanceof HTMLFormElement) claimForm.addEventListener('submit', (event) => { event.preventDefault(); const textInput = claimForm.querySelector('[data-research-claim-text]'); const sourceInput = claimForm.querySelector('[data-research-claim-source]'); const confidenceInput = claimForm.querySelector('[data-research-claim-confidence]'); const text = safeString(textInput?.value); if (!text) return; wb.claims.unshift({ id: moduleWorkbenchMakeId('claim'), text, sourceId: safeString(sourceInput?.value), confidence: moduleWorkbenchClamp(Number(confidenceInput?.value) || 70, 0, 100) }); if (textInput) textInput.value = ''; render(); });
    if (notes) notes.addEventListener('input', () => { wb.notes = safeString(notes.value); });
    if (synthesis) synthesis.addEventListener('input', () => { wb.synthesis = safeString(synthesis.value); });
    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-research-action]') : null;
        if (!target) return;
        const action = safeString(target.dataset.researchAction).toLowerCase();
        if (action === 'synthesize') synthesize();
        if (action === 'export') moduleWorkbenchCopyJson({ queries: wb.queries, sources: wb.sources, claims: wb.claims, notes: wb.notes, synthesis: wb.synthesis }, 'Research Brief JSON');
        if (action === 'clear') { wb.queries = []; wb.sources = []; wb.claims = []; wb.notes = ''; wb.synthesis = ''; if (notes) notes.value = ''; if (synthesis) synthesis.value = ''; render(); }
    });
}

function moduleSpecialListFromRows(rowsRaw, { fallback = 'No live items yet.', max = 3 } = {}) {
    const rows = Array.isArray(rowsRaw) ? rowsRaw : [];
    const items = rows
        .slice(0, Math.max(1, max))
        .map((row) => {
            const title = safeString(row?.title);
            const meta = safeString(row?.meta);
            if (title && meta) return `${title} - ${meta}`;
            return title || meta || '';
        })
        .filter(Boolean);
    return items.length ? items : [fallback];
}

function moduleBuildSpecialCards(mode, snapshot, signals, definition) {
    const queueRows = Array.isArray(definition?.queueRows) ? definition.queueRows : [];
    const healthRows = Array.isArray(definition?.healthRows) ? definition.healthRows : [];
    const activityRows = Array.isArray(definition?.activityRows) ? definition.activityRows : [];
    const triageRows = Array.isArray(definition?.triage?.rows) ? definition.triage.rows : [];

    if (mode === 'dashboard') {
        return [
            {
                title: 'Today Pulse',
                meta: 'Immediate priorities',
                tone: 'ok',
                items: [
                    `Task jobs: ${moduleFocusValue(signals?.task_jobs)}`,
                    `Cron jobs: ${moduleFocusValue(signals?.cron_jobs)}`,
                    `Approvals pending: ${moduleFocusValue(signals?.approvals_pending)}`,
                ],
            },
            {
                title: 'Robot Feed Highlights',
                meta: 'Most relevant updates',
                tone: 'warn',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No new robot events.' }),
            },
        ];
    }
    if (mode === 'operations') {
        return [
            {
                title: 'Exceptions',
                meta: 'Failures and blockers to clear',
                tone: Number(signals?.flow_failures || 0) > 0 ? 'warn' : 'ok',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No open operational exceptions.' }),
            },
            {
                title: 'Customer + Order Context',
                meta: 'Use before responses',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No active customer/order queue.' }),
            },
            {
                title: 'Ops System Health',
                meta: 'Connectors and checks',
                items: moduleSpecialListFromRows(healthRows, { fallback: 'No ops health data loaded.' }),
            },
        ];
    }
    if (mode === 'inbox') {
        return [
            {
                title: 'Triage Buckets',
                meta: 'Urgent / needs reply / FYI',
                tone: Number(signals?.inbox_urgent || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Urgent: ${moduleFocusValue(signals?.inbox_urgent)}`,
                    `Needs reply: ${moduleFocusValue(signals?.inbox_needs_reply)}`,
                    `Unread: ${moduleFocusValue(signals?.inbox_unread)}`,
                ],
            },
            {
                title: 'Thread Commitments',
                meta: 'Quoted action promises',
                items: moduleSpecialListFromRows(triageRows, { fallback: 'No commitments extracted yet.' }),
            },
        ];
    }
    if (mode === 'notifications') {
        return [
            {
                title: 'Interrupt Policy',
                meta: 'Critical routing and escalation',
                tone: Number(signals?.notif_escalations || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Critical escalations: ${moduleFocusValue(signals?.notif_escalations)}`,
                    `Bundled notifications: ${moduleFocusValue(signals?.notif_bundled)}`,
                    `Rules active: ${moduleFocusValue(signals?.notif_rules)}`,
                ],
            },
            {
                title: 'Recent Notification Causes',
                meta: 'Why these fired',
                items: moduleSpecialListFromRows(triageRows, { fallback: 'No recent notification triggers.' }),
            },
        ];
    }
    if (mode === 'automations') {
        return [
            {
                title: 'Run Logs',
                meta: 'Recent flow outcomes',
                tone: Number(signals?.flow_failures || 0) > 0 ? 'warn' : 'ok',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No recent automation runs.' }),
            },
            {
                title: 'Flow Builder Readiness',
                meta: 'What needs attention before publish',
                items: [
                    `Active flows: ${moduleFocusValue(signals?.flow_active)}`,
                    `Failing runs: ${moduleFocusValue(signals?.flow_failures)}`,
                    `Approvals waiting: ${moduleFocusValue(signals?.flow_approvals)}`,
                ],
            },
        ];
    }
    if (mode === 'agents') {
        return [
            {
                title: 'Crew Assignments',
                meta: 'Delegated work right now',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No active agent assignments.' }),
            },
            {
                title: 'Guardrail Pressure',
                meta: 'Approvals and blocked actions',
                tone: Number(signals?.agent_approval_only || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Active agents: ${moduleFocusValue(signals?.agent_active)}`,
                    `Needs approval: ${moduleFocusValue(signals?.agent_approval_only)}`,
                    `Escalations: ${moduleFocusValue(signals?.agent_escalations)}`,
                ],
            },
        ];
    }
    if (mode === 'studio' || mode === 'game_studio' || mode === 'lab_3d') {
        return [
            {
                title: 'Production Pipeline',
                meta: 'Queue and output',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No active production queue.' }),
            },
            {
                title: 'Recent Output',
                meta: 'Renders, playtests, fabrication runs',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No recent production outputs.' }),
            },
        ];
    }
    if (mode === 'dev_studio') {
        return [
            {
                title: 'Build + Test Health',
                meta: 'Release confidence view',
                tone: Number(signals?.dev_failures || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Failing tests: ${moduleFocusValue(signals?.dev_failures)}`,
                    `Deploys today: ${moduleFocusValue(signals?.deploys_today)}`,
                    `Open PR signals: ${moduleFocusValue(signals?.dev_pr_open)}`,
                ],
            },
            {
                title: 'Engineering Queue',
                meta: 'PRs, tests, deploys',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No engineering queue items.' }),
            },
        ];
    }
    if (mode === 'app_builder') {
        return [
            {
                title: 'App Runtime Readiness',
                meta: 'Publish confidence',
                items: [
                    `Published apps: ${moduleFocusValue(signals?.apps_published)}`,
                    `Draft apps: ${moduleFocusValue(signals?.apps_draft)}`,
                    `Connectors: ${moduleFocusValue(signals?.connectors_total)}`,
                ],
            },
            {
                title: 'Data + Permissions',
                meta: 'Connector health and scope',
                items: moduleSpecialListFromRows(healthRows, { fallback: 'No connector telemetry yet.' }),
            },
        ];
    }
    if (mode === 'research_lab') {
        return [
            {
                title: 'Research Queue',
                meta: 'Open investigations',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No active research queue.' }),
            },
            {
                title: 'Citations + Claims',
                meta: 'Source-backed output confidence',
                items: [
                    `Briefs: ${moduleFocusValue(signals?.research_briefs)}`,
                    `Citations: ${moduleFocusValue(signals?.research_citations)}`,
                    `Competitor watch: ${moduleFocusValue(signals?.research_competitors)}`,
                ],
            },
        ];
    }
    if (mode === 'people') {
        return [
            {
                title: 'Relationship Health',
                meta: 'Follow-up risk board',
                tone: Number(signals?.people_at_risk || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Follow-ups due: ${moduleFocusValue(signals?.people_followups)}`,
                    `At risk: ${moduleFocusValue(signals?.people_at_risk)}`,
                    `Commitments open: ${moduleFocusValue(signals?.people_commitments)}`,
                ],
            },
            {
                title: 'Recent Interactions',
                meta: 'Conversation-linked actions',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No recent people activity.' }),
            },
        ];
    }
    if (mode === 'finance') {
        return [
            {
                title: 'Money Signals',
                meta: 'Anomalies and approvals',
                tone: Number(signals?.finance_anomalies || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Anomalies: ${moduleFocusValue(signals?.finance_anomalies)}`,
                    `Approvals: ${moduleFocusValue(signals?.finance_approvals)}`,
                    `Subscriptions: ${moduleFocusValue(signals?.finance_subscriptions)}`,
                ],
            },
            {
                title: 'Transaction Queue',
                meta: 'Receipts and reconciliation',
                items: moduleSpecialListFromRows(queueRows, { fallback: 'No finance queue data.' }),
            },
        ];
    }
    if (mode === 'integrations') {
        return [
            {
                title: 'Connector Health',
                meta: 'Reconnect and auth pressure',
                tone: Number(signals?.integrations_degraded || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Connected: ${moduleFocusValue(signals?.integrations_connected)}`,
                    `Degraded: ${moduleFocusValue(signals?.integrations_degraded)}`,
                    `Reconnects: ${moduleFocusValue(signals?.integrations_reconnects)}`,
                ],
            },
            {
                title: 'Permission + Scope Review',
                meta: 'High-impact integration states',
                items: moduleSpecialListFromRows(healthRows, { fallback: 'No integration scope warnings.' }),
            },
        ];
    }
    if (mode === 'marketplace') return [];
    if (mode === 'vault') {
        return [
            {
                title: 'Secrets + Retention',
                meta: 'Security baseline',
                tone: Number(signals?.vault_expiring || 0) > 0 ? 'warn' : 'ok',
                items: [
                    `Secrets: ${moduleFocusValue(signals?.vault_secrets)}`,
                    `Expiring: ${moduleFocusValue(signals?.vault_expiring)}`,
                    `Sources: ${moduleFocusValue(signals?.vault_sources)}`,
                ],
            },
            {
                title: 'Policy Events',
                meta: 'Approvals and risk alerts',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No recent vault policy events.' }),
            },
        ];
    }
    if (mode === 'timeline') {
        return [
            {
                title: 'Audit Summary',
                meta: 'What Thomas did',
                items: [
                    `Events 24h: ${moduleFocusValue(signals?.timeline_events)}`,
                    `Automated actions: ${moduleFocusValue(signals?.timeline_automated)}`,
                    `Retries: ${moduleFocusValue(signals?.timeline_retries)}`,
                ],
            },
            {
                title: 'Event Chain Highlights',
                meta: 'Failures, approvals, rollbacks',
                items: moduleSpecialListFromRows(triageRows, { fallback: 'No timeline highlights for active filter.' }),
            },
        ];
    }
    if (mode === 'infinite') {
        return [
            {
                title: 'Device Capture Flow',
                meta: 'Mobile and companion routing',
                items: [
                    `Handoffs: ${moduleFocusValue(signals?.handoffs_pending)}`,
                    `Offline captures: ${moduleFocusValue(signals?.offline_captures)}`,
                    `Push routes: ${moduleFocusValue(signals?.push_routes)}`,
                ],
            },
            {
                title: 'Recent Device Activity',
                meta: 'Approvals and sync events',
                items: moduleSpecialListFromRows(activityRows, { fallback: 'No recent companion activity.' }),
            },
        ];
    }
    return [];
}

function moduleRenderSpecialCards(cardsRaw) {
    if (!moduleSpecialGrid) return;
    const cards = Array.isArray(cardsRaw) ? cardsRaw.filter(Boolean) : [];
    moduleSpecialGrid.innerHTML = '';
    if (!cards.length) {
        moduleSpecialGrid.classList.add('hidden');
        return;
    }
    moduleSpecialGrid.classList.remove('hidden');
    const frag = document.createDocumentFragment();
    cards.forEach((cardRaw) => {
        const tone = moduleToneClass(cardRaw?.tone);
        const card = document.createElement('article');
        card.className = `module-special-card${tone ? ` ${tone}` : ''}`;
        const items = Array.isArray(cardRaw?.items) ? cardRaw.items.filter(Boolean) : [];
        const listHtml = items.map((item) => `<li>${escapeHtml(safeString(item))}</li>`).join('');
        card.innerHTML = `
            <header>
                <h4>${escapeHtml(safeString(cardRaw?.title) || 'Module')}</h4>
                <p>${escapeHtml(safeString(cardRaw?.meta) || '')}</p>
            </header>
            <ul>${listHtml || '<li>No live items yet.</li>'}</ul>
        `;
        frag.appendChild(card);
    });
    moduleSpecialGrid.appendChild(frag);
}

function moduleRenderMarketplaceCatalogV2(container) {
    return moduleRenderMarketplaceSurface(container);
}

function moduleRenderMarketplaceCatalog(container) {
    return moduleRenderMarketplaceSurface(container);
}

function moduleRenderMarketplaceCatalogV3(container) {
    return moduleRenderMarketplaceSurface(container);
}

const MODULE_SPECIAL_SURFACE_CONFIGS = Object.freeze({
    my_stuff: Object.freeze({
        title: 'Project Board',
        src: '/static/static/my_stuff.html?v=20260624-forge-builds-1',
        surfaceMode: 'immersive',
    }),
});

const MODULE_STATIC_WORKSPACE_ITEMS = Object.freeze([
    { workspace_id: 'mission', mode_id: 'mission', label: 'Mission Control', icon: 'ph-crosshair-simple', default_nav_section: 'apps', default_nav_order: 120 },
    { workspace_id: 'app_builder', mode_id: 'app_builder', label: 'UI Editor', icon: 'ph-app-window', default_nav_section: 'apps', default_nav_order: 160 },
    { workspace_id: 'my_stuff', mode_id: 'my_stuff', label: 'My Stuff', icon: 'ph-grid-four', default_nav_section: 'apps', default_nav_order: 220 },
    { workspace_id: 'channels', mode_id: 'channels', label: 'Channels', icon: 'ph-broadcast', default_nav_section: 'apps', default_nav_order: 280 },
    { workspace_id: 'token_economy', mode_id: 'token_economy', label: 'Token Economy', icon: 'ph-coins', default_nav_section: 'apps', default_nav_order: 300 },
    { workspace_id: 'marketplace', mode_id: 'marketplace', label: 'Marketplace', icon: 'ph-storefront', default_nav_section: 'apps', default_nav_order: 320 },
]);

function moduleInstalledPluginRows() {
    const state = moduleEnsureRuntime();
    const rows = state?.marketplace?.plugins;
    return Array.isArray(rows) ? rows : [];
}

function moduleInstalledPluginForMode(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (!mode) return null;
    return moduleInstalledPluginRows().find((plugin) => safeString(plugin?.mode_id).toLowerCase() === mode) || null;
}

function moduleDynamicSpecialSurfaceConfig(modeRaw) {
    const plugin = moduleInstalledPluginForMode(modeRaw);
    if (!plugin || !plugin?.enabled) return null;
    const src = safeString(plugin?.surface_url);
    if (!src) return null;
    return {
        title: safeString(plugin?.surface_title) || safeString(plugin?.display_name) || 'Thomas Upgrade',
        src,
        surfaceMode: safeString(plugin?.surface_mode) || 'immersive',
    };
}

function loadStoredWorkspaceNavOrder() {
    try {
        if (!window?.localStorage || isUiEditorPreviewShell()) return [];
        const raw = window.localStorage.getItem(UI_WORKSPACE_NAV_ORDER_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed.map((value) => safeString(value).toLowerCase()).filter(Boolean) : [];
    } catch {
        return [];
    }
}

function saveStoredWorkspaceNavOrder(orderRaw) {
    const order = Array.isArray(orderRaw) ? orderRaw.map((value) => safeString(value).toLowerCase()).filter(Boolean) : [];
    try {
        if (!window?.localStorage || isUiEditorPreviewShell()) return;
        window.localStorage.setItem(UI_WORKSPACE_NAV_ORDER_STORAGE_KEY, JSON.stringify(order));
    } catch {
        // Ignore storage failures.
    }
}

function moduleInstalledWorkspaceRows() {
    return moduleInstalledPluginRows().filter((plugin) => (
        plugin?.enabled
        && safeString(plugin?.left_nav_behavior).toLowerCase() === 'workspace'
        && safeString(plugin?.mode_id)
        && safeString(plugin?.display_name)
    ));
}

function moduleWorkspaceNavEntries() {
    const staticByMode = new Map([
        ['mission', navMissionBtn],
        ['app_builder', navUiEditorBtn],
        ['my_stuff', navMyStuffBtn],
        ['channels', navChannelsBtn],
        ['token_economy', navTokenEconomyBtn],
        ['marketplace', navMarketplaceBtn],
    ]);
    const entries = [];
    MODULE_STATIC_WORKSPACE_ITEMS.forEach((item) => {
        const node = staticByMode.get(item.mode_id);
        if (!(node instanceof HTMLButtonElement)) return;
        entries.push({
            workspace_id: item.workspace_id,
            mode_id: item.mode_id,
            display_name: item.label,
            subtitle: item.label,
            icon: item.icon,
            marketplace_type: 'app',
            left_nav_behavior: 'workspace',
            default_nav_section: item.default_nav_section,
            default_nav_order: item.default_nav_order,
            node,
            dynamic: false,
        });
    });
    moduleInstalledWorkspaceRows().forEach((plugin) => {
        const workspaceId = safeString(plugin?.workspace_id || plugin?.mode_id).toLowerCase();
        if (!workspaceId) return;
        entries.push({
            workspace_id: workspaceId,
            mode_id: safeString(plugin?.mode_id).toLowerCase(),
            display_name: safeString(plugin?.display_name) || workspaceId,
            subtitle: safeString(plugin?.subtitle) || safeString(plugin?.description),
            icon: safeString(plugin?.icon) || 'ph-puzzle-piece',
            marketplace_type: safeString(plugin?.marketplace_type) || 'plugin',
            left_nav_behavior: safeString(plugin?.left_nav_behavior) || 'workspace',
            default_nav_section: safeString(plugin?.default_nav_section) || 'installed',
            default_nav_order: Number(plugin?.default_nav_order) || 900,
            plugin,
            dynamic: true,
        });
    });
    return entries;
}

function moduleWorkspaceNavFallbackOrder(entriesRaw) {
    const entries = Array.isArray(entriesRaw) ? entriesRaw.slice() : [];
    const sectionWeight = (sectionRaw) => ['apps', 'command_centers'].includes(safeString(sectionRaw).toLowerCase()) ? 0 : 1;
    return entries.sort((left, right) => {
        const sectionDiff = sectionWeight(left?.default_nav_section) - sectionWeight(right?.default_nav_section);
        if (sectionDiff) return sectionDiff;
        const orderDiff = (Number(left?.default_nav_order) || 900) - (Number(right?.default_nav_order) || 900);
        if (orderDiff) return orderDiff;
        return safeString(left?.display_name).localeCompare(safeString(right?.display_name));
    });
}

function moduleWorkspaceNavOrder(entriesRaw) {
    const entries = Array.isArray(entriesRaw) ? entriesRaw : [];
    const validIds = new Set(entries.map((entry) => safeString(entry?.workspace_id).toLowerCase()).filter(Boolean));
    const stored = loadStoredWorkspaceNavOrder().filter((id) => validIds.has(id));
    const appended = moduleWorkspaceNavFallbackOrder(entries)
        .map((entry) => safeString(entry?.workspace_id).toLowerCase())
        .filter((id) => id && !stored.includes(id));
    return stored.concat(appended);
}

function modulePersistWorkspaceNavOrderFromDom() {
    if (!(workspaceNavItems instanceof HTMLElement)) return;
    const order = Array.from(workspaceNavItems.querySelectorAll('[data-workspace-id]'))
        .map((node) => safeString(node.getAttribute('data-workspace-id')).toLowerCase())
        .filter(Boolean);
    saveStoredWorkspaceNavOrder(order);
}

function moduleBindWorkspaceNavDnD() {
    if (!(workspaceNavItems instanceof HTMLElement) || workspaceNavItems.dataset.workspaceDnDBound === '1') return;
    workspaceNavItems.dataset.workspaceDnDBound = '1';
    let draggingId = '';
    workspaceNavItems.addEventListener('dragstart', (event) => {
        const button = event.target instanceof Element ? event.target.closest('[data-workspace-id]') : null;
        if (!(button instanceof HTMLButtonElement)) return;
        draggingId = safeString(button.dataset.workspaceId).toLowerCase();
        button.classList.add('is-dragging');
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', draggingId);
        }
    });
    workspaceNavItems.addEventListener('dragend', () => {
        draggingId = '';
        workspaceNavItems.querySelectorAll('.is-dragging').forEach((node) => node.classList.remove('is-dragging'));
        modulePersistWorkspaceNavOrderFromDom();
    });
    workspaceNavItems.addEventListener('dragover', (event) => {
        if (!draggingId) return;
        const target = event.target instanceof Element ? event.target.closest('[data-workspace-id]') : null;
        const dragged = Array.from(workspaceNavItems.querySelectorAll('[data-workspace-id]')).find((node) => safeString(node.getAttribute('data-workspace-id')).toLowerCase() === draggingId);
        if (!(target instanceof HTMLElement) || !(dragged instanceof HTMLElement) || target === dragged) return;
        event.preventDefault();
        const rect = target.getBoundingClientRect();
        const after = event.clientY > rect.top + (rect.height / 2);
        workspaceNavItems.insertBefore(dragged, after ? target.nextSibling : target);
    });
    workspaceNavItems.addEventListener('drop', (event) => {
        if (!draggingId) return;
        event.preventDefault();
        modulePersistWorkspaceNavOrderFromDom();
    });
}

function moduleRenderInstalledPluginNav() {
    if (!(workspaceNavItems instanceof HTMLElement)) return;
    moduleBindWorkspaceNavDnD();
    Array.from(workspaceNavItems.querySelectorAll('[data-workspace-dynamic="1"]')).forEach((node) => node.remove());
    const entries = moduleWorkspaceNavEntries();
    const byId = new Map(entries.map((entry) => [safeString(entry.workspace_id).toLowerCase(), entry]));
    const order = moduleWorkspaceNavOrder(entries);
    order.forEach((workspaceId) => {
        const entry = byId.get(workspaceId);
        if (!entry) return;
        let button = entry.node;
        if (!(button instanceof HTMLButtonElement)) {
            button = document.createElement('button');
            button.className = 'nav-item';
            button.dataset.workspaceDynamic = '1';
        }
        button.type = 'button';
        const icon = safeString(entry.icon) || 'ph-puzzle-piece';
        const iconClass = icon.startsWith('ph-') ? icon : `ph-${icon}`;
        button.dataset.navMode = safeString(entry.mode_id).toLowerCase();
        button.dataset.workspaceId = safeString(entry.workspace_id).toLowerCase();
        button.draggable = true;
        button.title = safeString(entry.subtitle) || safeString(entry.display_name);
        button.classList.toggle('active', normalizeNavMode(entry.mode_id) === sidebarNavMode);
        button.innerHTML = `<i class="ph ${escapeHtml(iconClass)}"></i> ${escapeHtml(safeString(entry.display_name))}`;
        workspaceNavItems.appendChild(button);
    });
    saveStoredWorkspaceNavOrder(order);
    if (pluginNavItems) pluginNavItems.innerHTML = '';
}

function moduleGetSpecialSurfaceConfig(mode) {
    const key = safeString(mode);
    if (!key) return null;
    if (key === 'marketplace') return null;
    const dynamic = moduleDynamicSpecialSurfaceConfig(key);
    if (dynamic) return dynamic;
    return MODULE_SPECIAL_SURFACE_CONFIGS[key] || null;
}

function moduleModeUsesSpecialSurface(mode) {
    return Boolean(moduleGetSpecialSurfaceConfig(mode));
}

function moduleGetSpecialSurfaceMode(mode) {
    return moduleGetSpecialSurfaceConfig(mode)?.surfaceMode || '';
}

function moduleFitEmbeddedSurface(frame, { minHeight = 680, viewportPadding = 20, lockInternalScroll = false, preferContentHeight = true } = {}) {
    if (!(frame instanceof HTMLIFrameElement)) return;
    const minHeightPx = Number.isFinite(minHeight) ? minHeight : 680;
    const viewportPaddingPx = Number.isFinite(viewportPadding) ? viewportPadding : 20;
    const scheduleHeightSync = () => {
        const sync = () => {
            const bounds = frame.getBoundingClientRect();
            let nextHeight = Math.max(minHeightPx, (window.innerHeight || minHeightPx) - Math.max(bounds.top, 0) - viewportPaddingPx);
            try {
                const doc = frame.contentDocument;
                const root = doc?.documentElement;
                const body = doc?.body;
                if (lockInternalScroll && root && body) {
                    root.style.overflowY = 'hidden';
                    body.style.overflowY = 'hidden';
                }
                const contentHeight = Math.max(root?.scrollHeight || 0, body?.scrollHeight || 0, root?.offsetHeight || 0, body?.offsetHeight || 0);
                if (preferContentHeight && contentHeight > 0) {
                    nextHeight = Math.max(nextHeight, contentHeight);
                }
            } catch (_error) {}
            frame.style.height = `${Math.ceil(nextHeight)}px`;
        };
        if (typeof window.requestAnimationFrame === 'function') {
            window.requestAnimationFrame(sync);
            return;
        }
        window.setTimeout(sync, 0);
    };

    if (typeof frame.__moduleEmbeddedCleanup === 'function') {
        try {
            frame.__moduleEmbeddedCleanup();
        } catch (_error) {}
    }

    let resizeObserver = null;
    const onWindowResize = () => scheduleHeightSync();
    const cleanup = () => {
        window.removeEventListener('resize', onWindowResize);
        if (resizeObserver) {
            resizeObserver.disconnect();
            resizeObserver = null;
        }
    };
    frame.__moduleEmbeddedCleanup = cleanup;
    window.addEventListener('resize', onWindowResize);

    const attachObserver = () => {
        try {
            if (typeof ResizeObserver !== 'function') return;
            const doc = frame.contentDocument;
            const root = doc?.documentElement;
            const body = doc?.body;
            resizeObserver = new ResizeObserver(() => scheduleHeightSync());
            if (root) resizeObserver.observe(root);
            if (body && body !== root) resizeObserver.observe(body);
        } catch (_error) {
            resizeObserver = null;
        }
    };

    frame.addEventListener('load', () => {
        attachObserver();
        scheduleHeightSync();
        window.setTimeout(scheduleHeightSync, 120);
        window.setTimeout(scheduleHeightSync, 420);
    }, { once: true });

    if (frame.contentDocument?.readyState === 'complete') {
        attachObserver();
        scheduleHeightSync();
    } else {
        scheduleHeightSync();
    }
}

function moduleRenderEmbeddedSurface(container, { title, src, surfaceMode = 'standard' }) {
    if (!container) return null;
    const existing = container.querySelector(`iframe[data-module-embedded-surface="${src}"]`);
    if (existing instanceof HTMLIFrameElement) {
        if (surfaceMode === 'immersive') {
            moduleFitEmbeddedSurface(existing, { minHeight: 680, viewportPadding: 14, lockInternalScroll: false, preferContentHeight: true });
        }
        return existing;
    }

    const staleEmbedded = container.querySelector('[data-module-embedded-surface]');
    if (staleEmbedded instanceof HTMLIFrameElement && typeof staleEmbedded.__moduleEmbeddedCleanup === 'function') {
        try {
            staleEmbedded.__moduleEmbeddedCleanup();
        } catch (_error) {}
    }
    container.innerHTML = '';

    const shell = document.createElement('section');
    shell.className = 'module-marketplace-shell';
    shell.dataset.moduleSurfaceMode = surfaceMode;

    const frameWrap = document.createElement('section');
    frameWrap.className = 'module-marketplace-stream';
    frameWrap.dataset.moduleSurfaceMode = surfaceMode;

    const frame = document.createElement('iframe');
    frame.setAttribute('title', title);
    const trustedEmbeddedSurface = safeString(src).startsWith('/');
    if (!trustedEmbeddedSurface) {
        frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups allow-modals');
    }
    frame.dataset.moduleEmbeddedSurface = src;
    frame.dataset.moduleEmbeddedMode = surfaceMode;
    frame.loading = 'eager';
    frame.scrolling = 'auto';
    frame.src = src;
    frame.style.width = '100%';
    frame.style.border = '0';
    frame.style.background = 'transparent';

    if (surfaceMode === 'immersive') {
        frame.style.height = '680px';
        frame.style.minHeight = '680px';
        frame.style.borderRadius = '18px';
        moduleFitEmbeddedSurface(frame, { minHeight: 680, viewportPadding: 14, lockInternalScroll: false, preferContentHeight: true });
    } else {
        frame.style.height = '680px';
        frame.style.minHeight = '680px';
        frame.style.borderRadius = '18px';
    }

    frameWrap.appendChild(frame);
    shell.appendChild(frameWrap);
    container.appendChild(shell);
    return frame;
}

function moduleMarketplaceToneKey(toneRaw = '') {
    const tone = safeString(toneRaw).toLowerCase();
    if (!tone) return '';
    return tone.startsWith('tone-') ? tone.slice(5) : tone;
}

