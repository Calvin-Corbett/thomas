function moduleBuildFlair(mode, signals, snapshot) {
    const jobs = Array.isArray(snapshot?.jobs) ? snapshot.jobs.length : 0;
    const events = Array.isArray(snapshot?.events) ? snapshot.events.length : 0;
    const approvals = moduleFocusValue(signals?.approvals_pending);
    const connectors = moduleFocusValue(signals?.integrations_connected);
    const base = [
        { label: 'Mode', value: safeString(moduleSeed(mode)?.pill) || 'Live', tone: 'ok' },
        { label: 'Approvals', value: approvals, tone: Number(signals?.approvals_pending || 0) > 0 ? 'warn' : 'ok' },
        { label: 'Connectors', value: connectors, tone: Number(signals?.integrations_connected || 0) > 0 ? 'ok' : 'warn' },
    ];

    if (mode === 'operations') {
        return [
            { label: 'Open Work', value: moduleFocusValue(signals?.task_jobs), tone: Number(signals?.task_jobs || 0) > 0 ? 'ok' : '' },
            { label: 'Exceptions', value: moduleFocusValue(signals?.flow_failures), tone: Number(signals?.flow_failures || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Events', value: moduleFocusValue(events), tone: '' },
        ];
    }
    if (mode === 'inbox') {
        return [
            { label: 'Unread', value: moduleFocusValue(signals?.inbox_unread), tone: '' },
            { label: 'Urgent', value: moduleFocusValue(signals?.inbox_urgent), tone: Number(signals?.inbox_urgent || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Needs Reply', value: moduleFocusValue(signals?.inbox_needs_reply), tone: Number(signals?.inbox_needs_reply || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'notifications') {
        return [
            { label: 'Critical', value: moduleFocusValue(signals?.notif_escalations), tone: Number(signals?.notif_escalations || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Bundled', value: moduleFocusValue(signals?.notif_bundled), tone: '' },
            { label: 'Rules', value: moduleFocusValue(signals?.notif_rules), tone: '' },
        ];
    }
    if (mode === 'automations' || mode === 'app_builder') {
        return [
            { label: 'Flows', value: moduleFocusValue(signals?.flow_active), tone: '' },
            { label: 'Failing', value: moduleFocusValue(signals?.flow_failures), tone: Number(signals?.flow_failures || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Jobs', value: moduleFocusValue(jobs), tone: '' },
        ];
    }
    if (mode === 'vibe_code') {
        return [
            { label: 'Traces', value: moduleFocusValue(signals?.trace_count), tone: Number(signals?.trace_count || 0) > 0 ? 'ok' : '' },
            { label: 'Cuts', value: moduleFocusValue(signals?.runtime_cut_edges), tone: Number(signals?.runtime_cut_edges || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Modules Off', value: moduleFocusValue(signals?.modules_disabled), tone: Number(signals?.modules_disabled || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'agents') {
        return [
            { label: 'Active', value: moduleFocusValue(signals?.agent_active), tone: Number(signals?.agent_active || 0) > 0 ? 'ok' : '' },
            { label: 'Delegated', value: moduleFocusValue(signals?.agent_delegated), tone: '' },
            { label: 'Escalations', value: moduleFocusValue(signals?.agent_escalations), tone: Number(signals?.agent_escalations || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'studio' || mode === 'game_studio' || mode === 'lab_3d') {
        return [
            { label: 'Queue', value: moduleFocusValue(signals?.render_queue ?? signals?.print_queue), tone: '' },
            { label: 'Output', value: moduleFocusValue(signals?.exports_today ?? signals?.game_playtests), tone: '' },
            { label: 'Failures', value: moduleFocusValue(signals?.flow_failures), tone: Number(signals?.flow_failures || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'dev_studio') {
        return [
            { label: 'Failing Tests', value: moduleFocusValue(signals?.dev_failures), tone: Number(signals?.dev_failures || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Open PR Signals', value: moduleFocusValue(signals?.dev_pr_open), tone: '' },
            { label: 'Deploys', value: moduleFocusValue(signals?.deploys_today), tone: '' },
        ];
    }
    if (mode === 'research_lab') {
        return [
            { label: 'Briefs', value: moduleFocusValue(signals?.research_briefs), tone: '' },
            { label: 'Citations', value: moduleFocusValue(signals?.research_citations), tone: '' },
            { label: 'Watchlist', value: moduleFocusValue(signals?.research_watchlist), tone: '' },
        ];
    }
    if (mode === 'people') {
        return [
            { label: 'Contacts', value: moduleFocusValue(signals?.people_contacts), tone: '' },
            { label: 'Follow-ups', value: moduleFocusValue(signals?.people_followups), tone: Number(signals?.people_followups || 0) > 0 ? 'warn' : 'ok' },
            { label: 'At Risk', value: moduleFocusValue(signals?.people_at_risk), tone: Number(signals?.people_at_risk || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'finance') {
        return [
            { label: 'Anomalies', value: moduleFocusValue(signals?.finance_anomalies), tone: Number(signals?.finance_anomalies || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Approvals', value: moduleFocusValue(signals?.finance_approvals), tone: Number(signals?.finance_approvals || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Subscriptions', value: moduleFocusValue(signals?.finance_subscriptions), tone: '' },
        ];
    }
    if (mode === 'integrations') {
        return [
            { label: 'Connected', value: moduleFocusValue(signals?.integrations_connected), tone: Number(signals?.integrations_connected || 0) > 0 ? 'ok' : '' },
            { label: 'Degraded', value: moduleFocusValue(signals?.integrations_degraded), tone: Number(signals?.integrations_degraded || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Reconnects', value: moduleFocusValue(signals?.integrations_reconnects), tone: '' },
        ];
    }
    if (mode === 'marketplace') {
        return [
            { label: 'Installed', value: moduleFocusValue(signals?.market_installed), tone: '' },
            { label: 'Updates', value: moduleFocusValue(signals?.market_updates), tone: Number(signals?.market_updates || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Events', value: moduleFocusValue(events), tone: '' },
        ];
    }
    if (mode === 'vault') {
        return [
            { label: 'Secrets', value: moduleFocusValue(signals?.vault_secrets), tone: '' },
            { label: 'Expiring', value: moduleFocusValue(signals?.vault_expiring), tone: Number(signals?.vault_expiring || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Approvals', value: approvals, tone: Number(signals?.approvals_pending || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'timeline') {
        return [
            { label: 'Events 24h', value: moduleFocusValue(signals?.timeline_events), tone: '' },
            { label: 'Automated', value: moduleFocusValue(signals?.timeline_automated), tone: '' },
            { label: 'Retries', value: moduleFocusValue(signals?.timeline_retries), tone: Number(signals?.timeline_retries || 0) > 0 ? 'warn' : 'ok' },
        ];
    }
    if (mode === 'infinite') {
        return [
            { label: 'Handoffs', value: moduleFocusValue(signals?.handoffs_pending), tone: '' },
            { label: 'Offline', value: moduleFocusValue(signals?.offline_captures), tone: Number(signals?.offline_captures || 0) > 0 ? 'warn' : 'ok' },
            { label: 'Routes', value: moduleFocusValue(signals?.push_routes), tone: '' },
        ];
    }

    return base;
}

function moduleRenderFlair(flairRaw) {
    if (!moduleFlairRow) return;
    const flair = Array.isArray(flairRaw) ? flairRaw.filter(Boolean) : [];
    moduleFlairRow.innerHTML = '';
    if (!flair.length) {
        moduleFlairRow.classList.add('hidden');
        return;
    }
    moduleFlairRow.classList.remove('hidden');
    const frag = document.createDocumentFragment();
    flair.forEach((itemRaw) => {
        const tone = moduleToneClass(itemRaw?.tone);
        const item = document.createElement('article');
        item.className = `module-flair-pill${tone ? ` ${tone}` : ''}`;
        item.innerHTML = `
            <span>${escapeHtml(safeString(itemRaw?.label) || 'Info')}</span>
            <strong>${escapeHtml(moduleFocusValue(itemRaw?.value))}</strong>
        `;
        frag.appendChild(item);
    });
    moduleFlairRow.appendChild(frag);
}

function moduleWorkbenchMakeId(prefix = 'wb') {
    return `${prefix}-${Date.now()}-${Math.round(Math.random() * 1_000_000)}`;
}

function moduleWorkbenchPointFromEvent(canvas, event) {
    if (!(canvas instanceof HTMLCanvasElement) || !event) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width > 0 ? (canvas.width / rect.width) : 1;
    const scaleY = rect.height > 0 ? (canvas.height / rect.height) : 1;
    return {
        x: (event.clientX - rect.left) * scaleX,
        y: (event.clientY - rect.top) * scaleY,
    };
}

function moduleWorkbenchCopyJson(payload, label = 'Workbench JSON') {
    const text = JSON.stringify(payload, null, 2);
    if (navigator?.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            notifyUser(`${label} copied to clipboard.`, { tone: 'success', durationMs: 1600, debugKind: 'workbench' });
        }).catch(() => {
            notifyUser(`${label} ready in console (clipboard blocked).`, { tone: 'info', durationMs: 2100, debugKind: 'workbench' });
            console.log(label, text);
        });
        return;
    }
    notifyUser(`${label} ready in console.`, { tone: 'info', durationMs: 2100, debugKind: 'workbench' });
    console.log(label, text);
}

function moduleWorkbenchCopyText(textRaw, label = 'Workbench Text') {
    const text = safeString(textRaw);
    if (!text) {
        notifyUser(`${label} is empty.`, { tone: 'warn', durationMs: 1800, debugKind: 'workbench' });
        return;
    }
    if (navigator?.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            notifyUser(`${label} copied to clipboard.`, { tone: 'success', durationMs: 1600, debugKind: 'workbench' });
        }).catch(() => {
            notifyUser(`${label} ready in console (clipboard blocked).`, { tone: 'info', durationMs: 2100, debugKind: 'workbench' });
            console.log(label, text);
        });
        return;
    }
    notifyUser(`${label} ready in console.`, { tone: 'info', durationMs: 2100, debugKind: 'workbench' });
    console.log(label, text);
}

function moduleWorkbenchDownloadText(filenameRaw, textRaw, mime = 'text/plain;charset=utf-8') {
    const filename = safeString(filenameRaw) || 'download.txt';
    const text = safeString(textRaw);
    const blob = new Blob([text], { type: safeString(mime) || 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    window.setTimeout(() => {
        anchor.remove();
        URL.revokeObjectURL(url);
    }, 80);
}

function moduleWorkbenchOssCatalog(modeRaw) {
    const mode = safeString(modeRaw);
    if (mode === 'lab_3d') {
        return [
            {
                title: 'JSCAD',
                license: 'MIT',
                docsUrl: 'https://github.com/jscad/OpenJSCAD.org',
                why: 'Parametric CAD in browser/CLI',
                command: 'npx @jscad/cli design.jscad -o output.stl',
            },
            {
                title: 'Maker.js',
                license: 'Apache-2.0',
                docsUrl: 'https://github.com/microsoft/maker.js',
                why: '2D CAD/CNC geometry generation',
                command: 'npm i makerjs',
            },
            {
                title: 'Blender CLI',
                license: 'GPL',
                docsUrl: 'https://docs.blender.org/manual/en/latest/advanced/command_line/render.html',
                why: 'Headless rendering and automation',
                command: 'blender -b scene.blend -f 1',
            },
        ];
    }
    if (mode === 'automations') {
        return [
            {
                title: 'n8n',
                license: 'Fair-code',
                docsUrl: 'https://github.com/n8n-io/n8n',
                why: 'Production workflow automation',
                command: 'docker run -it --rm --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n',
            },
            {
                title: 'Node-RED',
                license: 'Apache-2.0',
                docsUrl: 'https://github.com/node-red/node-red',
                why: 'Event-driven visual flows',
                command: 'docker run -it --rm -p 1880:1880 -v node_red_data:/data nodered/node-red:latest',
            },
            {
                title: 'LiteGraph.js',
                license: 'MIT',
                docsUrl: 'https://github.com/jagenjo/litegraph.js',
                why: 'Embeddable node graph runtime',
                command: 'npm i litegraph.js',
            },
        ];
    }
    if (mode === 'app_builder') {
        return [
            {
                title: 'Admin Panel Runtime',
                license: 'OSS-compatible',
                docsUrl: '',
                why: 'Internal tools and admin panels',
                command: 'Use the exported page DSL with your preferred internal app runtime.',
            },
            {
                title: 'Builder Runtime',
                license: 'Project-specific',
                docsUrl: '',
                why: 'Low-code app and automation handoff',
                command: 'Export builder DSL, then map it to your chosen builder runtime.',
            },
            {
                title: 'Workflow Runtime',
                license: 'Project-specific',
                docsUrl: '',
                why: 'Extensible workflow-backed app surfaces',
                command: 'Export HTML or builder DSL and connect it to your workflow runtime.',
            },
        ];
    }
    if (mode === 'studio') {
        return [
            {
                title: 'FFmpeg',
                license: 'LGPL/GPL',
                docsUrl: 'https://ffmpeg.org/legal.html',
                why: 'Core transcoding, mastering, audio cleanup, and delivery exports.',
                command: 'winget install --id Gyan.FFmpeg -e',
            },
            {
                title: 'OpenTimelineIO',
                license: 'Apache-2.0',
                docsUrl: 'https://github.com/PixarAnimationStudios/OpenTimelineIO',
                why: 'Portable editorial timeline interchange across tools.',
                command: 'pip install opentimelineio',
            },
            {
                title: 'WaveSurfer.js',
                license: 'BSD-3-Clause',
                docsUrl: 'https://github.com/katspaugh/wavesurfer.js',
                why: 'In-browser waveform visualization and seek controls.',
                command: 'npm i wavesurfer.js',
            },
            {
                title: 'Blender',
                license: 'GPL',
                docsUrl: 'https://docs.blender.org/manual/en/latest/getting_started/about/license.html',
                why: '3D scenes, motion graphics, and scripted rendering.',
                command: 'winget install --id BlenderFoundation.Blender -e',
            },
            {
                title: 'Krita',
                license: 'GPL',
                docsUrl: 'https://krita.org/en/about/license/',
                why: 'Digital painting and concept art with pro brush engines.',
                command: 'winget install --id KDE.Krita -e',
            },
            {
                title: 'Inkscape',
                license: 'GPL',
                docsUrl: 'https://inkscape.org/about/',
                why: 'Vector graphics for logos, icons, and UI assets.',
                command: 'winget install --id Inkscape.Inkscape -e',
            },
            {
                title: 'Kdenlive',
                license: 'GPL-3.0',
                docsUrl: 'https://apps.kde.org/kdenlive/',
                why: 'Full NLE timeline editing with effect stacks.',
                command: 'winget install --id KDE.Kdenlive -e',
            },
            {
                title: 'Shotcut',
                license: 'GPL-3.0',
                docsUrl: 'https://github.com/mltframework/shotcut',
                why: 'Fast cross-platform editor for quick cuts and exports.',
                command: 'winget install --id Meltytech.Shotcut -e',
            },
            {
                title: 'Comfy Studio',
                license: 'GPL-3.0',
                docsUrl: 'https://github.com/comfyanonymous/ComfyUI',
                why: 'Thomas-integrated wrapper for local ComfyUI node workflows.',
                command: 'git clone https://github.com/comfyanonymous/ComfyUI.git',
            },
            {
                title: 'LMMS',
                license: 'GPL-2.0',
                docsUrl: 'https://github.com/LMMS/lmms',
                why: 'Music and sound design for custom loops and stingers.',
                command: 'winget install --id LMMS.LMMS -e',
            },
        ];
    }
    if (mode === 'dev_studio') {
        return [
            {
                title: 'code-server',
                license: 'MIT',
                docsUrl: 'https://github.com/coder/code-server',
                why: 'VS Code in browser',
                command: 'curl -fsSL https://code-server.dev/install.sh | sh',
            },
            {
                title: 'Ace Editor',
                license: 'BSD-3-Clause',
                docsUrl: 'https://github.com/ajaxorg/ace',
                why: 'Embeddable code editor',
                command: 'npm i ace-builds',
            },
            {
                title: 'Monaco Editor',
                license: 'MIT',
                docsUrl: 'https://github.com/microsoft/monaco-editor',
                why: 'VS Code core editor engine',
                command: 'npm i monaco-editor',
            },
        ];
    }
    if (mode === 'game_studio') {
        return [
            {
                title: 'Pixel Streaming Infrastructure',
                license: 'MIT',
                docsUrl: 'https://github.com/EpicGamesExt/PixelStreamingInfrastructure',
                why: 'Open-source Unreal stream frontend/signalling stack for embedded and remote viewport workflows.',
                command: 'git clone --branch UE5.5 https://github.com/EpicGamesExt/PixelStreamingInfrastructure.git',
            },
            {
                title: 'Unreal Remote Control API',
                license: 'Unreal feature',
                docsUrl: 'https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-api-http-reference-for-unreal-engine',
                why: 'Call Blueprint-callable functions over HTTP for editor automation and AI tooling.',
                command: 'curl -X GET http://127.0.0.1:30010/remote/info',
            },
            {
                title: 'Godot CLI',
                license: 'MIT',
                docsUrl: 'https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html',
                why: 'Headless export and CI builds',
                command: 'godot --headless --path ./game --export-release "Windows Desktop" build/game.exe',
            },
            {
                title: 'Phaser',
                license: 'MIT',
                docsUrl: 'https://docs.phaser.io/api-documentation/api-documentation',
                why: 'Fast 2D web playtest runtime',
                command: 'npm i phaser',
            },
        ];
    }
    if (mode === 'research_lab') {
        return [
            {
                title: 'JupyterLab',
                license: 'BSD',
                docsUrl: 'https://github.com/jupyterlab/jupyterlab',
                why: 'Exploration notebooks and experiments',
                command: 'pip install jupyterlab',
            },
            {
                title: 'Zotero',
                license: 'AGPL-3.0',
                docsUrl: 'https://github.com/zotero/zotero',
                why: 'Citation and source management',
                command: 'winget install --id Zotero.Zotero -e',
            },
            {
                title: 'OpenAlex API',
                license: 'Open data',
                docsUrl: 'https://docs.openalex.org/',
                why: 'Research metadata and paper graph',
                command: 'curl "https://api.openalex.org/works?search=agentic+workflow"',
            },
        ];
    }
    return [];
}

function moduleWorkbenchRenderOssStack(modeRaw, titleRaw = 'Open-Source Power Stack') {
    const mode = safeString(modeRaw);
    const title = safeString(titleRaw) || 'Open-Source Power Stack';
    const rows = moduleWorkbenchOssCatalog(mode);
    if (!rows.length) return '';
    return `
        <section class="module-wb-oss-stack">
            <h4>${escapeHtml(title)}</h4>
            <div class="module-wb-oss-list">
                ${rows.map((row, index) => `
                    <article class="module-wb-oss-item">
                        <div class="module-wb-oss-head">
                            <strong>${escapeHtml(safeString(row.title) || 'Tool')}</strong>
                            <span>${escapeHtml(safeString(row.license) || 'OSS')}</span>
                        </div>
                        <p>${escapeHtml(safeString(row.why) || '')}</p>
                        <div class="module-wb-inline-actions">
                            <button type="button" class="module-item-btn" data-oss-mode="${escapeHtml(mode)}" data-oss-copy="${index}">Copy command</button>
                            <a class="module-item-btn" href="${escapeHtml(safeString(row.docsUrl) || '#')}" target="_blank" rel="noopener noreferrer">Docs</a>
                        </div>
                    </article>
                `).join('')}
            </div>
        </section>
    `;
}

function moduleWorkbenchHandleOssStackClick(targetRaw) {
    const target = targetRaw instanceof Element ? targetRaw.closest('[data-oss-mode][data-oss-copy]') : null;
    if (!target) return false;
    const mode = safeString(target.dataset.ossMode);
    const index = Number(target.dataset.ossCopy);
    if (!mode || !Number.isInteger(index)) return false;
    const rows = moduleWorkbenchOssCatalog(mode);
    const row = rows[index];
    if (!row?.command) return false;
    moduleWorkbenchCopyText(row.command, `${safeString(row.title) || 'Integration'} Command`);
    return true;
}

const MODULE_WORKBENCH_PROJECT_STORE_KEY = 'thomas.workbench.projects.v1';

function moduleWorkbenchProjectsRead() {
    try {
        const raw = window.localStorage.getItem(MODULE_WORKBENCH_PROJECT_STORE_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_error) {
        return {};
    }
}

function moduleWorkbenchProjectsWrite(storeRaw) {
    const store = storeRaw && typeof storeRaw === 'object' ? storeRaw : {};
    try {
        window.localStorage.setItem(MODULE_WORKBENCH_PROJECT_STORE_KEY, JSON.stringify(store));
    } catch (_error) {}
}

function moduleWorkbenchProjectList(modeRaw) {
    const mode = safeString(modeRaw);
    if (!mode) return [];
    const store = moduleWorkbenchProjectsRead();
    const rows = Array.isArray(store[mode]) ? store[mode] : [];
    return rows.filter((row) => row && typeof row === 'object').slice(0, 20);
}

function moduleWorkbenchProjectSave(modeRaw, payloadRaw, nameRaw = '') {
    const mode = safeString(modeRaw);
    const payload = payloadRaw && typeof payloadRaw === 'object' ? payloadRaw : {};
    if (!mode) return '';
    const store = moduleWorkbenchProjectsRead();
    const current = Array.isArray(store[mode]) ? store[mode] : [];
    const name = safeString(nameRaw) || `Project ${moduleWorkbenchTimeStamp()}`;
    const id = moduleWorkbenchMakeId(`${mode}-project`);
    const next = [{ id, name: name.slice(0, 72), updatedAt: Date.now(), payload }, ...current]
        .slice(0, 20);
    store[mode] = next;
    moduleWorkbenchProjectsWrite(store);
    return id;
}

function moduleWorkbenchProjectGet(modeRaw, idRaw) {
    const mode = safeString(modeRaw);
    const id = safeString(idRaw);
    if (!mode || !id) return null;
    return moduleWorkbenchProjectList(mode).find((row) => safeString(row.id) === id) || null;
}

function moduleWorkbenchProjectDelete(modeRaw, idRaw) {
    const mode = safeString(modeRaw);
    const id = safeString(idRaw);
    if (!mode || !id) return false;
    const store = moduleWorkbenchProjectsRead();
    const rows = Array.isArray(store[mode]) ? store[mode] : [];
    const next = rows.filter((row) => safeString(row?.id) !== id);
    store[mode] = next;
    moduleWorkbenchProjectsWrite(store);
    return next.length !== rows.length;
}

function moduleWorkbenchRenderProjectControls(modeRaw, titleRaw = 'Projects') {
    const mode = safeString(modeRaw);
    const title = safeString(titleRaw) || 'Projects';
    const rows = moduleWorkbenchProjectList(mode);
    return `
        <section class="module-wb-project-panel">
            <h4>${escapeHtml(title)}</h4>
            <div class="module-wb-inline-form module-wb-project-form">
                <input type="text" data-wb-project-name="${escapeHtml(mode)}" placeholder="Project name" />
                <div class="module-wb-inline-actions">
                    <button type="button" class="module-item-btn" data-wb-project-action="save" data-wb-project-mode="${escapeHtml(mode)}">Save</button>
                    <button type="button" class="module-item-btn" data-wb-project-action="load" data-wb-project-mode="${escapeHtml(mode)}">Load</button>
                    <button type="button" class="module-item-btn" data-wb-project-action="delete" data-wb-project-mode="${escapeHtml(mode)}">Delete</button>
                </div>
                <select data-wb-project-select="${escapeHtml(mode)}">
                    <option value="">Select project</option>
                    ${rows.map((row) => `<option value="${escapeHtml(safeString(row.id))}">${escapeHtml(`${safeString(row.name)} (${new Date(Number(row.updatedAt) || Date.now()).toLocaleString()})`)}</option>`).join('')}
                </select>
            </div>
        </section>
    `;
}

function moduleWorkbenchPathGet(objRaw, pathRaw) {
    const obj = objRaw && typeof objRaw === 'object' ? objRaw : {};
    const path = safeString(pathRaw);
    if (!path) return obj;
    const parts = path.split('.').map((item) => safeString(item)).filter(Boolean);
    let cursor = obj;
    for (const part of parts) {
        if (!cursor || typeof cursor !== 'object') return undefined;
        cursor = cursor[part];
    }
    return cursor;
}

function moduleWorkbenchPathSet(objRaw, pathRaw, value) {
    const obj = objRaw && typeof objRaw === 'object' ? objRaw : {};
    const path = safeString(pathRaw);
    if (!path) return obj;
    const parts = path.split('.').map((item) => safeString(item)).filter(Boolean);
    if (!parts.length) return obj;
    let cursor = obj;
    for (let index = 0; index < parts.length - 1; index += 1) {
        const key = parts[index];
        if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
        cursor = cursor[key];
    }
    cursor[parts[parts.length - 1]] = value;
    return obj;
}

function moduleWorkbenchPathDelete(objRaw, pathRaw) {
    const obj = objRaw && typeof objRaw === 'object' ? objRaw : {};
    const path = safeString(pathRaw);
    if (!path) return obj;
    const parts = path.split('.').map((item) => safeString(item)).filter(Boolean);
    if (!parts.length) return obj;
    let cursor = obj;
    for (let index = 0; index < parts.length - 1; index += 1) {
        const key = parts[index];
        if (!cursor[key] || typeof cursor[key] !== 'object') return obj;
        cursor = cursor[key];
    }
    delete cursor[parts[parts.length - 1]];
    return obj;
}

function moduleWorkbenchDeepClone(value) {
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (_error) {
        return value;
    }
}

function formatDebugPercent(valueRaw, digits = 1, fallback = '-') {
    const value = Number(valueRaw);
    if (!Number.isFinite(value)) return fallback;
    return `${(value * 100).toFixed(Math.max(0, Number(digits) || 0))}%`;
}

const MODULE_WORKBENCH_OSS = {
    scriptPromises: Object.create(null),
    styleLoaded: Object.create(null),
    threePromise: null,
    liteGraphPromise: null,
    gridStackPromise: null,
    waveSurferPromise: null,
    monacoPromise: null,
    acePromise: null,
    phaserPromise: null,
};

function moduleWorkbenchModeIsActive(modeRaw) {
    const mode = safeString(modeRaw);
    if (!mode) return false;
    return Boolean(moduleWorkbench && safeString(moduleWorkbench.dataset.mode) === mode);
}

function moduleWorkbenchRefreshMode(modeRaw) {
    const mode = MODULE_NAV_MODE_SET.has(modeRaw) ? modeRaw : safeString(modeRaw);
    if (!mode || !moduleWorkbenchModeIsActive(mode)) return;
    const state = moduleEnsureRuntime();
    if (state?.workbench?.[mode]) {
        state.workbench[mode].mounted = false;
    }
    moduleRender(mode, { touch: false });
}

function moduleWorkbenchLoadStyle(urlRaw) {
    const url = safeString(urlRaw);
    if (!url) return;
    if (MODULE_WORKBENCH_OSS.styleLoaded[url]) return;
    MODULE_WORKBENCH_OSS.styleLoaded[url] = true;
    if (!(document?.head instanceof HTMLHeadElement)) return;
    const existing = document.head.querySelector(`link[rel="stylesheet"][href="${url}"]`);
    if (existing) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    document.head.appendChild(link);
}

function moduleWorkbenchLoadScript(urlRaw, { globalName = '', globalCheck = null } = {}) {
    const url = safeString(urlRaw);
    if (!url) return Promise.reject(new Error('Missing script URL.'));
    if (typeof globalCheck === 'function' && globalCheck()) {
        return Promise.resolve(true);
    }
    if (globalName && window[globalName]) {
        return Promise.resolve(true);
    }
    if (MODULE_WORKBENCH_OSS.scriptPromises[url]) {
        return MODULE_WORKBENCH_OSS.scriptPromises[url];
    }
    MODULE_WORKBENCH_OSS.scriptPromises[url] = new Promise((resolve, reject) => {
        if (!(document?.head instanceof HTMLHeadElement)) {
            reject(new Error('Document head unavailable.'));
            return;
        }
        const script = document.createElement('script');
        script.src = url;
        script.async = true;
        script.onload = () => {
            if (typeof globalCheck === 'function' && !globalCheck()) {
                reject(new Error(`Loaded ${url} but expected symbol missing.`));
                return;
            }
            if (globalName && !window[globalName]) {
                reject(new Error(`Loaded ${url} but window.${globalName} is unavailable.`));
                return;
            }
            resolve(true);
        };
        script.onerror = () => reject(new Error(`Failed to load script: ${url}`));
        document.head.appendChild(script);
    }).catch((error) => {
        delete MODULE_WORKBENCH_OSS.scriptPromises[url];
        throw error;
    });
    return MODULE_WORKBENCH_OSS.scriptPromises[url];
}

async function moduleWorkbenchLoadThreeBundle() {
    if (MODULE_WORKBENCH_OSS.threePromise) return MODULE_WORKBENCH_OSS.threePromise;
    MODULE_WORKBENCH_OSS.threePromise = (async () => {
        const THREE = await import('https://cdn.jsdelivr.net/npm/three@0.183.1/+esm');
        const orbitModule = await import('https://cdn.jsdelivr.net/npm/three@0.183.1/examples/jsm/controls/OrbitControls.js/+esm');
        const transformModule = await import('https://cdn.jsdelivr.net/npm/three@0.183.1/examples/jsm/controls/TransformControls.js/+esm');
        const gltfModule = await import('https://cdn.jsdelivr.net/npm/three@0.183.1/examples/jsm/exporters/GLTFExporter.js/+esm');
        const stlModule = await import('https://cdn.jsdelivr.net/npm/three@0.183.1/examples/jsm/exporters/STLExporter.js/+esm');
        return {
            THREE,
            OrbitControls: orbitModule.OrbitControls,
            TransformControls: transformModule.TransformControls,
            GLTFExporter: gltfModule.GLTFExporter,
            STLExporter: stlModule.STLExporter,
        };
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.threePromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.threePromise;
}

async function moduleWorkbenchLoadLiteGraph() {
    if (window.LiteGraph) return window.LiteGraph;
    if (MODULE_WORKBENCH_OSS.liteGraphPromise) return MODULE_WORKBENCH_OSS.liteGraphPromise;
    MODULE_WORKBENCH_OSS.liteGraphPromise = (async () => {
        moduleWorkbenchLoadStyle('https://cdn.jsdelivr.net/npm/litegraph.js@0.7.18/css/litegraph.css');
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/litegraph.js@0.7.18/build/litegraph.min.js', { globalName: 'LiteGraph' });
        if (!window.LiteGraph) throw new Error('LiteGraph did not initialize.');
        return window.LiteGraph;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.liteGraphPromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.liteGraphPromise;
}

async function moduleWorkbenchLoadGridStack() {
    if (window.GridStack) return window.GridStack;
    if (MODULE_WORKBENCH_OSS.gridStackPromise) return MODULE_WORKBENCH_OSS.gridStackPromise;
    MODULE_WORKBENCH_OSS.gridStackPromise = (async () => {
        moduleWorkbenchLoadStyle('https://cdn.jsdelivr.net/npm/gridstack@12.4.2/dist/gridstack.min.css');
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/gridstack@12.4.2/dist/gridstack-all.js', { globalName: 'GridStack' });
        if (!window.GridStack) throw new Error('GridStack did not initialize.');
        return window.GridStack;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.gridStackPromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.gridStackPromise;
}

async function moduleWorkbenchLoadWaveSurfer() {
    if (window.WaveSurfer) return window.WaveSurfer;
    if (MODULE_WORKBENCH_OSS.waveSurferPromise) return MODULE_WORKBENCH_OSS.waveSurferPromise;
    MODULE_WORKBENCH_OSS.waveSurferPromise = (async () => {
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/wavesurfer.js@7.12.1/dist/wavesurfer.min.js', { globalName: 'WaveSurfer' });
        if (!window.WaveSurfer) throw new Error('WaveSurfer did not initialize.');
        return window.WaveSurfer;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.waveSurferPromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.waveSurferPromise;
}

async function moduleWorkbenchLoadMonaco() {
    if (window.monaco?.editor) return window.monaco;
    if (MODULE_WORKBENCH_OSS.monacoPromise) return MODULE_WORKBENCH_OSS.monacoPromise;
    MODULE_WORKBENCH_OSS.monacoPromise = (async () => {
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min/vs/loader.js', {
            globalCheck: () => typeof window.require === 'function',
        });
        await new Promise((resolve, reject) => {
            if (typeof window.require !== 'function') {
                reject(new Error('Monaco loader missing window.require.'));
                return;
            }
            window.require.config({
                paths: {
                    vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min/vs',
                },
            });
            window.require(['vs/editor/editor.main'], () => resolve(true), reject);
        });
        if (!window.monaco?.editor) throw new Error('Monaco editor failed to load.');
        return window.monaco;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.monacoPromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.monacoPromise;
}

async function moduleWorkbenchLoadAce() {
    if (window.ace?.edit) return window.ace;
    if (MODULE_WORKBENCH_OSS.acePromise) return MODULE_WORKBENCH_OSS.acePromise;
    MODULE_WORKBENCH_OSS.acePromise = (async () => {
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/ace-builds@1.36.2/src-min-noconflict/ace.js', { globalName: 'ace' });
        if (!window.ace?.edit) throw new Error('Ace editor failed to load.');
        return window.ace;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.acePromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.acePromise;
}

async function moduleWorkbenchLoadPhaser() {
    if (window.Phaser) return window.Phaser;
    if (MODULE_WORKBENCH_OSS.phaserPromise) return MODULE_WORKBENCH_OSS.phaserPromise;
    MODULE_WORKBENCH_OSS.phaserPromise = (async () => {
        await moduleWorkbenchLoadScript('https://cdn.jsdelivr.net/npm/phaser@3.90.0/dist/phaser.min.js', { globalName: 'Phaser' });
        if (!window.Phaser) throw new Error('Phaser failed to initialize.');
        return window.Phaser;
    })().catch((error) => {
        MODULE_WORKBENCH_OSS.phaserPromise = null;
        throw error;
    });
    return MODULE_WORKBENCH_OSS.phaserPromise;
}

function moduleWorkbenchRenderEngineLoading(container, title, subtitle, status, details = '') {
    moduleWorkbenchHeader(container, title, subtitle);
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-loading';
    shell.innerHTML = `
        <section class="module-wb-stage-card">
            <div class="module-wb-loader">
                <strong>${escapeHtml(status || 'Loading engine...')}</strong>
                <p>${escapeHtml(details || 'Preparing open-source runtime for this tab.')}</p>
            </div>
        </section>
    `;
    container.appendChild(shell);
}

function moduleWorkbenchState(mode) {
    const state = moduleEnsureRuntime();
    if (!state) return null;
    if (!state.workbench[mode]) {
        if (mode === 'lab_3d') {
            state.workbench[mode] = {
                mounted: false,
                tool: 'rect',
                shapes: [],
                objects: [],
                selectedId: '',
                nextId: 1,
                draft: null,
                drawing: false,
                dragStart: null,
                canvasWidth: 860,
                canvasHeight: 420,
                grid: 24,
                snap: true,
                units: 'mm',
                transformSpace: 'world',
                transformSnap: false,
                showGrid: true,
                wireframe: false,
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'automations') {
            state.workbench[mode] = {
                mounted: false,
                nextId: 1,
                selectedId: '',
                nodes: [],
                edges: [],
                connectingFrom: '',
                logs: [],
                graphData: null,
                runInput: '{\n  "subject": "Ops status",\n  "priority": "high"\n}',
                runReport: null,
                selectedProjectId: '',
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'app_builder') {
            state.workbench[mode] = {
                mounted: false,
                nextId: 1,
                selectedId: '',
                components: [],
                device: 'desktop',
                grid: 16,
                selectedProjectId: '',
                previewHtml: '',
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'studio') {
            state.workbench[mode] = {
                mounted: false,
                nextId: 1,
                assets: [],
                timeline: [],
                playhead: 0,
                timer: 0,
                playing: false,
                selectedAssetId: '',
                selectedClipId: '',
                forge: null,
                assetQuery: '',
                assetType: 'all',
                audioPreset: 'podcast_clean',
                renderPreset: 'master_1080p',
                generationTool: 'comfyui',
                generationPrompt: 'cute helper robot in a clean office',
                batchQueue: [],
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'dev_studio') {
            state.workbench[mode] = {
                mounted: false,
                code: '',
                issues: [],
                logs: [],
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'game_studio') {
            const width = 20;
            const height = 12;
            state.workbench[mode] = {
                mounted: false,
                gridWidth: width,
                gridHeight: height,
                brush: 1,
                dragging: false,
                tiles: Array.from({ length: height }, () => Array.from({ length: width }, () => 0)),
                logs: [],
                highScore: 0,
                selectedProjectId: '',
                viewMode: 'split',
                playTarget: 'auto',
                godotProjectPath: 'C:/games/MyGodotProject',
                unrealProjectPath: 'C:/games/MyUnrealProject/MyGame.uproject',
                unrealViewportUrl: 'http://127.0.0.1:8888',
                viewportConnected: false,
                viewportLoadState: 'idle',
                viewportBlockedHint: false,
                unrealRcUrl: 'http://127.0.0.1:30010',
                unrealRcEndpoint: '/remote/object/call',
                unrealRcPayload: '{\n  "objectPath": "/Game/Blueprints/BP_GameMode.BP_GameMode_C",\n  "functionName": "RunEditorTick",\n  "parameters": {}\n}',
                unrealRcResponse: '',
                sceneActors: [],
                selectedActorId: '',
                nextActorId: 1,
                assets: moduleGameStudioDefaultAssets(),
                selectedAssetId: 'asset-floor-grid',
                assetFilterType: 'all',
                assetSearch: '',
                bridge: {
                    status: 'idle',
                    lastPingMs: 0,
                    lastSeenAt: 0,
                    lastError: '',
                    routes: [],
                    pullCount: 0,
                    pushCount: 0,
                    actorSyncPath: '/Game/Blueprints/BP_LevelBridge.BP_LevelBridge_C',
                },
                bridgePollTimer: 0,
                selectedEngine: 'unreal',
                engineProjects: {},
                activeProjectByEngine: {},
                studioChat: [],
                chatDraft: '',
                projectDraftName: '',
                projectDraftPath: 'C:/games/MyUnrealProject/MyGame.uproject',
                ossReady: false,
                ossLoading: false,
                ossError: '',
            };
        } else if (mode === 'research_lab') {
            state.workbench[mode] = {
                mounted: false,
                lastQuery: '',
                queries: [],
                sources: [],
                notes: '',
                claims: [],
                synthesis: '',
                activeSourceId: '',
            };
        } else {
            state.workbench[mode] = { mounted: false };
        }
    }
    return state.workbench[mode];
}

function moduleWorkbenchTeardown(mode) {
    const state = moduleEnsureRuntime();
    if (!state) return;
    const wb = state.workbench?.[mode];
    if (!wb || typeof wb !== 'object') return;
    if (mode === 'studio' && Number(wb.timer) > 0) {
        window.clearInterval(wb.timer);
        wb.timer = 0;
        wb.playing = false;
    }
    if (mode === 'lab_3d' && wb.ossEngine?.dispose) {
        try {
            wb.ossEngine.dispose();
        } catch (_error) {}
        wb.ossEngine = null;
    }
    if (mode === 'automations') {
        try {
            wb.ossGraph?.stop?.();
        } catch (_error) {}
        try {
            wb.ossGraphCanvas?.setGraph?.(null, true);
        } catch (_error) {}
        wb.ossGraph = null;
        wb.ossGraphCanvas = null;
    }
    if (mode === 'app_builder' && wb.ossGrid?.destroy) {
        try {
            wb.ossGrid.destroy(false);
        } catch (_error) {}
        wb.ossGrid = null;
    }
    if (mode === 'studio') {
        if (wb.waveSurfer?.destroy) {
            try {
                wb.waveSurfer.destroy();
            } catch (_error) {}
        }
        wb.waveSurfer = null;
        wb.waveContainer = null;
        wb.lastWaveAssetId = '';
    }
    if (mode === 'dev_studio') {
        if (wb.monacoEditor?.dispose) {
            try {
                wb.monacoEditor.dispose();
            } catch (_error) {}
        }
        if (wb.monacoModel?.dispose) {
            try {
                wb.monacoModel.dispose();
            } catch (_error) {}
        }
        wb.monacoEditor = null;
        wb.monacoModel = null;
        if (wb.aceEditor?.destroy) {
            try {
                wb.aceEditor.destroy();
            } catch (_error) {}
        }
        if (wb.aceEditor?.container) {
            wb.aceEditor.container.innerHTML = '';
        }
        wb.aceEditor = null;
    }
    if (mode === 'game_studio' && wb.phaserGame?.destroy) {
        try {
            wb.phaserGame.destroy(true);
        } catch (_error) {}
        wb.phaserGame = null;
    }
    if (mode === 'game_studio' && Number(wb.viewportProbeTimer) > 0) {
        window.clearTimeout(Number(wb.viewportProbeTimer));
        wb.viewportProbeTimer = 0;
    }
    if (mode === 'game_studio' && Number(wb.bridgePollTimer) > 0) {
        window.clearInterval(Number(wb.bridgePollTimer));
        wb.bridgePollTimer = 0;
    }
}

function moduleWorkbenchHeader(container, title, subtitle) {
    const head = document.createElement('header');
    head.className = 'module-wb-header';
    head.innerHTML = `
        <h3>${escapeHtml(title || 'Workbench')}</h3>
        <p>${escapeHtml(subtitle || 'Interactive workspace')}</p>
    `;
    container.appendChild(head);
}

const MODULE_WORKBENCH_OPERATOR_COPY = Object.freeze({
    default: 'Thomas executes the work in the background. Use this tab to dispatch tasks, monitor progress, and review outputs.',
    studio: 'Thomas runs connected asset pipelines and tool jobs. Use this tab to queue work, watch status, and review artifacts.',
    dev_studio: 'Thomas runs engineering work and checks. Use this tab to assign coding tasks, monitor results, and review patches.',
    app_builder: 'Thomas builds app structure from your intent. Use this tab to steer requirements, inspect generated UI, and publish safely.',
    game_studio: 'Thomas runs game pipeline jobs across tools. Use this tab to dispatch builds/content generation and review playtest outputs.',
    lab_3d: 'Thomas runs 3D and fabrication pipelines. Use this tab to dispatch modeling/slicing jobs and verify print-ready outputs.',
    research_lab: 'Thomas runs deep research workflows. Use this tab to track source-backed progress and final brief outputs.',
    automations: 'Thomas executes automation flows. Use this tab to define routes, monitor run health, and handle approvals.',
    vibe_code: 'Thomas exposes a controllable system flowchart. Use this tab to inspect, disconnect, and reconnect runtime paths.',
});

function moduleWorkbenchOperatorNote(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    return MODULE_WORKBENCH_OPERATOR_COPY[mode] || MODULE_WORKBENCH_OPERATOR_COPY.default;
}

function moduleWorkbenchOperatorPreamble(container, modeRaw) {
    if (!(container instanceof HTMLElement)) return;
    const note = moduleWorkbenchOperatorNote(modeRaw);
    const panel = document.createElement('section');
    panel.className = 'module-wb-operator-note';
    panel.setAttribute('aria-label', 'Thomas operator mode');
    panel.innerHTML = `
        <strong>Operator Mode</strong>
        <p>${escapeHtml(note)}</p>
    `;
    container.appendChild(panel);
}
