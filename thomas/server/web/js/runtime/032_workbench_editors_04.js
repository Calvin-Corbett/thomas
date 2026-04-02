function moduleRenderWorkbenchStudio(container, wb) {
    if (moduleRenderWorkbenchStudioOss(container, wb)) return;
    if (!container || !wb) return;
    if (!Array.isArray(wb.assets)) wb.assets = [];
    if (!Array.isArray(wb.timeline)) wb.timeline = [];
    if (!Array.isArray(wb.logs)) wb.logs = [];
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.playhead = Math.max(0, Number(wb.playhead) || 0);
    wb.selectedAssetId = safeString(wb.selectedAssetId);
    wb.selectedClipId = safeString(wb.selectedClipId);
    moduleStudioEnsureForgeState(wb);
    moduleStudioEnsureWorkbenchState(wb);

    moduleWorkbenchHeader(container, 'Comfy Studio', 'Queue Comfy Studio jobs for Thomas, monitor connected tool runs, and review production-ready outputs.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-studio';
    shell.innerHTML = `
        <aside class="module-wb-side-card module-wb-studio-library">
            <h4>Asset Library</h4>
            <div class="module-wb-studio-chip-row" data-studio-library-stats></div>
            <div class="module-wb-field-grid module-wb-studio-filter-grid">
                <label class="module-wb-field module-wb-field-wide">Search
                    <input type="text" data-studio-filter-query value="${escapeHtml(wb.assetQuery)}" placeholder="Search assets, mime, or type" />
                </label>
                <label class="module-wb-field">Type
                    <select data-studio-filter-type>
                        ${moduleStudioOptionMarkup(MODULE_STUDIO_ASSET_TYPES, wb.assetType)}
                    </select>
                </label>
            </div>
            <form class="module-wb-inline-form" data-studio-asset-form>
                <input type="text" data-studio-asset-name placeholder="Asset name" />
                <input type="number" data-studio-asset-duration min="1" max="900" value="6" />
                <button type="submit" class="module-item-btn">Add Note Asset</button>
            </form>
            <label class="module-wb-file-pick">
                <input type="file" data-studio-file-input accept="audio/*,video/*,image/*" multiple />
                <span>Import audio/video/image</span>
            </label>
            <div class="module-wb-asset-list" data-studio-assets></div>
            ${moduleStudioForgeMarkup(wb)}
        </aside>
        <section class="module-wb-stage-card module-wb-studio-stage">
            <div class="module-wb-stage-head"><span class="module-wb-stage-title">Pipeline Preview</span><span class="module-wb-stage-meta" data-studio-status></span></div>
            <div class="module-wb-image-stage" data-studio-image-stage></div>
            <input type="range" class="module-wb-range" data-studio-playhead min="0" max="1" step="0.1" value="0" />
            <div class="module-wb-timeline" data-studio-timeline></div>
            <section class="module-wb-studio-control-grid">
                <label class="module-wb-field">Audio Preset
                    <select data-studio-audio-preset>
                        ${moduleStudioOptionMarkup(MODULE_STUDIO_AUDIO_PRESETS, wb.audioPreset)}
                    </select>
                </label>
                <label class="module-wb-field">Render Preset
                    <select data-studio-render-preset>
                        ${moduleStudioOptionMarkup(MODULE_STUDIO_RENDER_PRESETS, wb.renderPreset)}
                    </select>
                </label>
                <label class="module-wb-field">Generation Tool
                    <select data-studio-generation-tool>
                        ${moduleStudioOptionMarkup(MODULE_STUDIO_GENERATION_TOOLS, wb.generationTool)}
                    </select>
                </label>
                <label class="module-wb-field module-wb-field-wide">Generation Prompt
                    <input type="text" data-studio-generation-prompt value="${escapeHtml(wb.generationPrompt)}" placeholder="isometric robot office, clean product art" />
                </label>
            </section>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-studio-action="play">${wb.playing ? 'Pause' : 'Play'}</button>
                <button type="button" class="module-item-btn" data-studio-action="stop">Stop</button>
                <button type="button" class="module-item-btn" data-studio-action="export">Export</button>
                <button type="button" class="module-item-btn" data-studio-action="export_otio">OTIO</button>
                <button type="button" class="module-item-btn" data-studio-action="ffmpeg">ffmpeg</button>
                <button type="button" class="module-item-btn" data-studio-action="copy_audio">Audio Chain</button>
                <button type="button" class="module-item-btn" data-studio-action="copy_render">Render Cmd</button>
                <button type="button" class="module-item-btn" data-studio-action="copy_gen">Gen Cmd</button>
                <button type="button" class="module-item-btn" data-studio-action="queue_preset">Queue Preset</button>
                <button type="button" class="module-item-btn" data-studio-action="clear_queue">Clear Queue</button>
            </div>
        </section>
        <aside class="module-wb-inspector-card module-wb-studio-inspector">
            <div data-studio-inspector></div>
            <h4>Render Queue</h4>
            <div class="module-wb-log-list" data-studio-batch></div>
            <h4>Run Log</h4>
            <div class="module-wb-log-list" data-studio-logs></div>
        </aside>
        ${moduleWorkbenchRenderOssStack('studio', 'Comfy Studio OSS Toolchain')}
    `;
    container.appendChild(shell);

    const assets = shell.querySelector('[data-studio-assets]');
    const timeline = shell.querySelector('[data-studio-timeline]');
    const status = shell.querySelector('[data-studio-status]');
    const inspector = shell.querySelector('[data-studio-inspector]');
    const logs = shell.querySelector('[data-studio-logs]');
    const batch = shell.querySelector('[data-studio-batch]');
    const slider = shell.querySelector('[data-studio-playhead]');
    const form = shell.querySelector('[data-studio-asset-form]');
    const fileInput = shell.querySelector('[data-studio-file-input]');
    const filterQueryInput = shell.querySelector('[data-studio-filter-query]');
    const filterTypeSelect = shell.querySelector('[data-studio-filter-type]');
    const audioPresetSelect = shell.querySelector('[data-studio-audio-preset]');
    const renderPresetSelect = shell.querySelector('[data-studio-render-preset]');
    const generationToolSelect = shell.querySelector('[data-studio-generation-tool]');
    const generationPromptInput = shell.querySelector('[data-studio-generation-prompt]');
    const libraryStats = shell.querySelector('[data-studio-library-stats]');
    const imageStage = shell.querySelector('[data-studio-image-stage]');
    if (!(assets instanceof HTMLElement)
        || !(timeline instanceof HTMLElement)
        || !(status instanceof HTMLElement)
        || !(inspector instanceof HTMLElement)
        || !(logs instanceof HTMLElement)
        || !(batch instanceof HTMLElement)
        || !(slider instanceof HTMLInputElement)
        || !(imageStage instanceof HTMLElement)
        || !(filterQueryInput instanceof HTMLInputElement)
        || !(filterTypeSelect instanceof HTMLSelectElement)
        || !(audioPresetSelect instanceof HTMLSelectElement)
        || !(renderPresetSelect instanceof HTMLSelectElement)
        || !(generationToolSelect instanceof HTMLSelectElement)
        || !(generationPromptInput instanceof HTMLInputElement)
        || !(libraryStats instanceof HTMLElement)) {
        return;
    }
    const assetById = (id) => wb.assets.find((item) => safeString(item.id) === safeString(id)) || null;
    const clipById = (id) => wb.timeline.find((clip) => safeString(clip.id) === safeString(id)) || null;
    const recompute = () => {
        let cursor = 0;
        wb.timeline.forEach((clip) => {
            clip.duration = moduleWorkbenchClamp(Number(clip.duration) || 1, 0.5, 900);
            clip.start = cursor;
            cursor += clip.duration;
        });
        return cursor;
    };
    const selectedAsset = () => assetById(wb.selectedAssetId);
    const pushStudioLog = (messageRaw, toneRaw = 'ok') => {
        moduleWorkbenchPushLog(wb.logs, messageRaw, toneRaw, 80, 'studio-log');
    };
    const forgeUi = moduleStudioBindForge(shell, wb, {
        onChanged: () => renderAll(),
        onLog: (messageRaw, toneRaw = 'ok') => pushStudioLog(messageRaw, toneRaw),
    });
    const renderAssets = () => {
        const visibleAssets = moduleStudioFilterAssets(wb);
        assets.innerHTML = visibleAssets.length
            ? visibleAssets.map((item) => {
                const itemId = escapeHtml(safeString(item.id));
                const selected = safeString(item.id) === safeString(wb.selectedAssetId) ? ' selected' : '';
                const meta = `${moduleStudioDuration(item.duration)} | ${moduleStudioAssetKindLabel(item)}${item.url ? ' | ready' : ''}`;
                const editBtn = moduleStudioAssetKind(item) === 'pixel'
                    ? `<button type="button" class="module-item-btn" data-studio-action="edit" data-studio-asset-id="${itemId}">Edit</button>`
                    : '';
                return `<article class="module-wb-asset-row${selected}" data-studio-asset-id="${itemId}"><div><strong>${escapeHtml(safeString(item.name))}</strong><span>${escapeHtml(meta)}</span></div><div class="module-wb-inline-actions"><button type="button" class="module-item-btn" data-studio-action="insert" data-studio-asset-id="${itemId}">Insert</button><button type="button" class="module-item-btn" data-studio-action="load" data-studio-asset-id="${itemId}">Load</button>${editBtn}</div></article>`;
            }).join('')
            : `<div class="module-wb-ghost">${wb.assets.length ? 'No assets match this filter.' : 'No assets yet.'}</div>`;
    };
    const renderLibraryStats = () => {
        const counts = moduleStudioAssetCounts(wb);
        libraryStats.innerHTML = `
            <span class="module-wb-studio-chip">Total <strong>${counts.total}</strong></span>
            <span class="module-wb-studio-chip">Media <strong>${counts.media}</strong></span>
            <span class="module-wb-studio-chip">Images <strong>${counts.image}</strong></span>
            <span class="module-wb-studio-chip">Pixel <strong>${counts.pixel}</strong></span>
        `;
    };
    const renderTimeline = () => {
        const total = Math.max(1, recompute());
        timeline.innerHTML = wb.timeline.length
            ? wb.timeline.map((clip) => `<button type="button" class="module-wb-clip${safeString(clip.id) === safeString(wb.selectedClipId) ? ' selected' : ''}" data-studio-clip-id="${escapeHtml(safeString(clip.id))}" style="flex-basis:${Math.max(9, (clip.duration / total) * 100)}%"><span>${escapeHtml(safeString(clip.name))}</span><strong>${moduleStudioDuration(clip.duration)}</strong></button>`).join('')
            : '<div class="module-wb-ghost">Insert assets to build timeline.</div>';
        slider.max = String(total);
        slider.value = String(Math.min(total, wb.playhead));
    };
    const renderInspector = () => {
        const clip = clipById(wb.selectedClipId);
        if (!clip) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a clip to trim and reorder.</p><div class="module-wb-metrics"><div><span>Assets</span><strong>${wb.assets.length}</strong></div><div><span>Clips</span><strong>${wb.timeline.length}</strong></div><div><span>Total</span><strong>${moduleStudioDuration(recompute())}</strong></div></div>`;
            return;
        }
        inspector.innerHTML = `<h4>${escapeHtml(safeString(clip.name))}</h4><div class="module-wb-field-grid"><label class="module-wb-field">Name<input type="text" data-studio-clip-prop="name" value="${escapeHtml(safeString(clip.name))}" /></label><label class="module-wb-field">Duration<input type="number" min="0.5" step="0.5" data-studio-clip-prop="duration" value="${clip.duration}" /></label></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-studio-action="left">Move Left</button><button type="button" class="module-item-btn" data-studio-action="right">Move Right</button><button type="button" class="module-item-btn" data-studio-action="remove">Remove</button></div>`;
    };
    const renderLogs = () => {
        logs.innerHTML = wb.logs.length
            ? wb.logs.slice(0, 12).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('')
            : '<div class="module-wb-ghost">No render operations logged yet.</div>';
    };
    const renderBatchQueue = () => {
        batch.innerHTML = wb.batchQueue.length
            ? wb.batchQueue.map((entry) => {
                const tone = safeString(entry.status) === 'done' ? 'ok' : (safeString(entry.status) === 'failed' ? 'error' : 'warn');
                return `<article class="module-wb-log-item ${moduleToneClass(tone) || 'warn'}"><span>${escapeHtml(safeString(entry.at))} | ${escapeHtml(safeString(entry.preset))}</span><p>${escapeHtml(safeString(entry.name))} - ${escapeHtml(safeString(entry.status || 'queued'))}</p></article>`;
            }).join('')
            : '<div class="module-wb-ghost">No queued exports yet.</div>';
    };
    const renderStatus = () => {
        const renderPreset = moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, wb.renderPreset);
        const audioPreset = moduleStudioCatalogFind(MODULE_STUDIO_AUDIO_PRESETS, wb.audioPreset);
        status.textContent = `${wb.playing ? 'Playing' : 'Idle'} | ${moduleStudioDuration(wb.playhead)} / ${moduleStudioDuration(recompute())} | ${safeString(renderPreset?.label)} | ${safeString(audioPreset?.label)}`;
        if (document.activeElement !== filterQueryInput) {
            filterQueryInput.value = wb.assetQuery;
        }
        filterTypeSelect.value = wb.assetType;
        audioPresetSelect.value = wb.audioPreset;
        renderPresetSelect.value = wb.renderPreset;
        generationToolSelect.value = wb.generationTool;
        if (document.activeElement !== generationPromptInput) {
            generationPromptInput.value = wb.generationPrompt;
        }
    };
    const renderMediaPreview = () => {
        const asset = selectedAsset();
        moduleStudioSyncForgeWithSelection(wb, asset);
        moduleStudioRenderAssetPreview(imageStage, asset);
    };
    const renderAll = () => {
        moduleStudioEnsureWorkbenchState(wb);
        renderLibraryStats();
        renderAssets();
        renderTimeline();
        renderInspector();
        renderStatus();
        renderMediaPreview();
        forgeUi.render();
        renderBatchQueue();
        renderLogs();
    };
    const setPlaying = (playing) => {
        wb.playing = Boolean(playing);
        if (!wb.playing && Number(wb.timer) > 0) {
            window.clearInterval(wb.timer);
            wb.timer = 0;
        }
        if (wb.playing) {
            if (Number(wb.timer) > 0) window.clearInterval(wb.timer);
            wb.timer = window.setInterval(() => {
                const total = recompute();
                wb.playhead = Math.min(total, wb.playhead + 0.25);
                if (wb.playhead >= total) setPlaying(false);
                renderStatus();
                slider.value = String(wb.playhead);
            }, 250);
        }
        renderStatus();
    };

    renderAll();
    if (form instanceof HTMLFormElement) {
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const nameInput = form.querySelector('[data-studio-asset-name]');
            const durationInput = form.querySelector('[data-studio-asset-duration]');
            const name = safeString(nameInput?.value) || `Asset ${wb.nextId}`;
            const duration = moduleWorkbenchClamp(Number(durationInput?.value) || 6, 1, 900);
            const id = `asset-${wb.nextId++}`;
            wb.assets.unshift({ id, name, duration, kind: 'note', url: '', mime: '' });
            wb.selectedAssetId = id;
            if (nameInput) nameInput.value = '';
            pushStudioLog(`Added note asset ${safeString(name)}.`, 'ok');
            renderAll();
        });
    }
    if (fileInput instanceof HTMLInputElement) {
        fileInput.addEventListener('change', () => {
            const files = Array.from(fileInput.files || []);
            if (!files.length) return;
            files.forEach((file) => {
                const mime = safeString(file.type).toLowerCase();
                const asset = {
                    id: `asset-${wb.nextId++}`,
                    name: safeString(file.name) || `Media ${wb.nextId}`,
                    duration: 6,
                    url: URL.createObjectURL(file),
                    mime,
                    kind: mime.startsWith('image/') ? 'image' : 'media',
                };
                wb.assets.unshift(asset);
                wb.selectedAssetId = asset.id;
                pushStudioLog(`Imported ${safeString(file.name)}.`, 'ok');
            });
            fileInput.value = '';
            renderAll();
        });
    }
    filterQueryInput.addEventListener('input', () => {
        wb.assetQuery = safeString(filterQueryInput.value).slice(0, 80);
        renderAll();
    });
    filterTypeSelect.addEventListener('change', () => {
        wb.assetType = safeString(filterTypeSelect.value).toLowerCase();
        renderAll();
    });
    audioPresetSelect.addEventListener('change', () => {
        wb.audioPreset = safeString(audioPresetSelect.value).toLowerCase();
        pushStudioLog(`Audio preset set to ${safeString(moduleStudioCatalogFind(MODULE_STUDIO_AUDIO_PRESETS, wb.audioPreset)?.label)}.`, 'ok');
        renderAll();
    });
    renderPresetSelect.addEventListener('change', () => {
        wb.renderPreset = safeString(renderPresetSelect.value).toLowerCase();
        pushStudioLog(`Render preset set to ${safeString(moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, wb.renderPreset)?.label)}.`, 'ok');
        renderAll();
    });
    generationToolSelect.addEventListener('change', () => {
        wb.generationTool = safeString(generationToolSelect.value).toLowerCase();
        renderAll();
    });
    generationPromptInput.addEventListener('input', () => {
        wb.generationPrompt = safeString(generationPromptInput.value).slice(0, 220);
    });
    slider.addEventListener('input', () => {
        wb.playhead = Math.max(0, Number(slider.value) || 0);
        renderStatus();
    });
    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-studio-action], [data-studio-asset-id], [data-studio-clip-id]') : null;
        if (!target) return;
        const action = safeString(target.dataset.studioAction).toLowerCase();
        const assetId = safeString(target.dataset.studioAssetId);
        const clipId = safeString(target.dataset.studioClipId);
        if (assetId && !action) {
            wb.selectedAssetId = assetId;
            renderAll();
            return;
        }
        if (clipId) {
            wb.selectedClipId = clipId;
            const clip = clipById(clipId);
            if (clip) wb.playhead = clip.start;
            renderAll();
            return;
        }
        if (action === 'copy_audio') {
            moduleWorkbenchCopyText(moduleStudioAudioPresetCommand(wb), 'Comfy Studio Audio Chain');
            pushStudioLog('Copied audio chain command.', 'ok');
            renderLogs();
            return;
        }
        if (action === 'copy_render') {
            moduleWorkbenchCopyText(moduleStudioRenderPresetCommand(wb), 'Comfy Studio Render Command');
            pushStudioLog('Copied render preset command.', 'ok');
            renderLogs();
            return;
        }
        if (action === 'copy_gen') {
            moduleWorkbenchCopyText(moduleStudioGenerationCommand(wb), 'Comfy Studio Generation Command');
            pushStudioLog('Copied generation bridge command.', 'ok');
            renderLogs();
            return;
        }
        if (action === 'queue_preset') {
            const queued = moduleStudioQueueRenderJob(wb, selectedAsset());
            if (queued) pushStudioLog(`Queued ${safeString(queued.name)} with ${safeString(queued.preset)}.`, 'ok');
            renderAll();
            return;
        }
        if (action === 'clear_queue') {
            wb.batchQueue = [];
            pushStudioLog('Cleared render queue.', 'warn');
            renderAll();
            return;
        }
        if (action === 'load') {
            wb.selectedAssetId = assetId;
            renderAll();
            return;
        }
        if (action === 'edit') {
            wb.selectedAssetId = assetId;
            moduleStudioLoadForgeFromPixelAsset(wb, selectedAsset());
            renderAll();
            return;
        }
        if (action === 'insert') {
            const asset = assetById(assetId);
            if (asset) {
                const clip = { id: `clip-${wb.nextId++}`, name: safeString(asset.name), duration: moduleWorkbenchClamp(Number(asset.duration) || 1, 0.5, 900), start: 0 };
                wb.timeline.push(clip);
                wb.selectedClipId = clip.id;
                pushStudioLog(`Inserted clip from ${safeString(asset.name)}.`, 'ok');
            }
        }
        if (action === 'play') setPlaying(!wb.playing);
        if (action === 'stop') {
            setPlaying(false);
            wb.playhead = 0;
        }
        if (action === 'export') {
            moduleWorkbenchCopyJson({
                assets: wb.assets.map((asset) => ({
                    ...asset,
                    url: safeString(asset.url).startsWith('data:') ? '[data-url]' : (asset.url ? '[object-url]' : ''),
                })),
                timeline: wb.timeline,
                duration: recompute(),
            }, 'Comfy Studio Render Queue JSON');
            const queued = wb.batchQueue.find((entry) => safeString(entry.status) === 'queued');
            if (queued) {
                queued.status = 'done';
                queued.eta = 'complete';
                queued.at = moduleWorkbenchTimeStamp();
            }
            pushStudioLog('Export payload copied and queue advanced.', 'ok');
        }
        if (action === 'export_otio') moduleWorkbenchCopyJson(moduleWorkbenchStudioTimelineToOtio(wb), 'Comfy Studio OTIO JSON');
        if (action === 'ffmpeg') moduleWorkbenchCopyText(moduleWorkbenchStudioFfmpegConcatCommand(wb), 'Comfy Studio ffmpeg Concat Command');
        if (action === 'remove') {
            wb.timeline = wb.timeline.filter((clip) => safeString(clip.id) !== safeString(wb.selectedClipId));
            wb.selectedClipId = '';
        }
        if (action === 'left' || action === 'right') {
            const index = wb.timeline.findIndex((clip) => safeString(clip.id) === safeString(wb.selectedClipId));
            if (index >= 0) {
                const next = action === 'left' ? index - 1 : index + 1;
                if (next >= 0 && next < wb.timeline.length) {
                    const tmp = wb.timeline[index];
                    wb.timeline[index] = wb.timeline[next];
                    wb.timeline[next] = tmp;
                }
            }
        }
        renderAll();
    });
    inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        const clip = clipById(wb.selectedClipId);
        if (!clip) return;
        const prop = safeString(target.dataset.studioClipProp);
        if (!prop) return;
        if (prop === 'name') clip.name = safeString(target.value).slice(0, 100);
        if (prop === 'duration') clip.duration = moduleWorkbenchClamp(Number(target.value) || clip.duration, 0.5, 900);
        renderAll();
    });
}

function moduleDevStudioScanIssues(codeRaw) {
    const code = safeString(codeRaw);
    const lines = code.split(/\r?\n/);
    const issues = [];
    if (!code.trim()) {
        issues.push({ tone: 'warn', text: 'Editor is empty.', line: 1 });
    }
    const openCount = (code.match(/{/g) || []).length;
    const closeCount = (code.match(/}/g) || []).length;
    if (openCount !== closeCount) {
        issues.push({ tone: 'error', text: `Brace mismatch: ${openCount} open vs ${closeCount} close.`, line: 1 });
    }
    lines.forEach((line, index) => {
        if (line.includes('TODO')) {
            issues.push({ tone: 'warn', text: 'TODO marker still present.', line: index + 1 });
        }
        if (/console\.log\(/.test(line)) {
            issues.push({ tone: 'warn', text: 'Debug console.log found.', line: index + 1 });
        }
    });
    if (!/\b(test|describe|it)\s*\(/.test(code)) {
        issues.push({ tone: 'warn', text: 'No tests detected in this file.', line: 1 });
    }
    if (!issues.length) {
        issues.push({ tone: 'ok', text: 'No obvious static issues.', line: 1 });
    }
    return issues.slice(0, 30);
}

function moduleWorkbenchDevDockerfileSnippet() {
    return [
        'FROM node:22-alpine',
        'WORKDIR /app',
        'COPY package*.json ./',
        'RUN npm ci --omit=dev',
        'COPY . .',
        'EXPOSE 3000',
        'CMD ["npm", "run", "start"]',
    ].join('\n');
}

function moduleRenderWorkbenchDevStudioOss(container, wb) {
    if (!container || !wb) return false;
    if (wb.ossError) return false;
    if (!wb.ossReady || !window.ace?.edit) {
        moduleWorkbenchRenderEngineLoading(
            container,
            'Dev Studio Code Engine',
            'Ace editor with inline diagnostics and build/test actions.',
            'Loading Ace...',
            'Fallback textarea editor opens automatically if Ace fails.',
        );
        if (!wb.ossLoading) {
            wb.ossLoading = true;
            void moduleWorkbenchLoadAce().then(() => {
                wb.ossReady = true;
                wb.ossLoading = false;
                wb.ossError = '';
                moduleWorkbenchRefreshMode('dev_studio');
            }).catch((error) => {
                wb.ossLoading = false;
                wb.ossReady = false;
                wb.ossError = safeString(error?.message) || 'Failed to load Ace.';
                notifyUser('Ace failed to load, using fallback code editor.', { tone: 'warn', durationMs: 2300, debugKind: 'dev-studio' });
                moduleWorkbenchRefreshMode('dev_studio');
            });
        }
        return true;
    }

    wb.code = safeString(wb.code);
    if (!Array.isArray(wb.logs)) wb.logs = [];
    if (!Array.isArray(wb.issues)) wb.issues = [];
    if (!wb.code.trim()) {
        wb.code = `export async function handler(ctx) {\n    const data = await ctx.fetch();\n    return { ok: true, size: Array.isArray(data) ? data.length : 0 };\n}\n`;
    }

    moduleWorkbenchHeader(container, 'Dev Studio Code Engine', 'Thomas executes coding/test pipelines while you review diffs, checks, and build snapshots.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-dev-oss';
    shell.innerHTML = `
        <section class="module-wb-stage-card">
            <div class="module-wb-stage-head"><span class="module-wb-stage-title">Code Editor</span><span class="module-wb-stage-meta" data-dev-status></span></div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-dev-action="analyze">Analyze</button>
                <button type="button" class="module-item-btn" data-dev-action="tests">Run Tests</button>
                <button type="button" class="module-item-btn" data-dev-action="build">Build</button>
                <button type="button" class="module-item-btn" data-dev-action="format">Format</button>
                <button type="button" class="module-item-btn" data-dev-action="snippet">Snippet</button>
                <button type="button" class="module-item-btn" data-dev-action="dockerfile">Dockerfile</button>
                <button type="button" class="module-item-btn" data-dev-action="export">Export</button>
            </div>
            <div class="module-wb-monaco" data-dev-monaco></div>
        </section>
        <aside class="module-wb-inspector-card">
            <h4>Issues</h4>
            <div class="module-wb-issues" data-dev-issues></div>
            <h4>Logs</h4>
            <div class="module-wb-log-list" data-dev-logs></div>
        </aside>
        ${moduleWorkbenchRenderOssStack('dev_studio')}
    `;
    container.appendChild(shell);

    const editorWrap = shell.querySelector('[data-dev-monaco]');
    const status = shell.querySelector('[data-dev-status]');
    const issuesEl = shell.querySelector('[data-dev-issues]');
    const logsEl = shell.querySelector('[data-dev-logs]');
    if (!(editorWrap instanceof HTMLElement) || !(status instanceof HTMLElement) || !(issuesEl instanceof HTMLElement) || !(logsEl instanceof HTMLElement)) {
        return false;
    }

    if (wb.aceEditor?.destroy) {
        try {
            wb.aceEditor.destroy();
        } catch (_error) {}
    }
    editorWrap.innerHTML = '';

    const ace = window.ace;
    const editor = ace.edit(editorWrap, {
        mode: 'ace/mode/javascript',
        theme: 'ace/theme/tomorrow_night_eighties',
        fontSize: 13,
        showPrintMargin: false,
        wrap: true,
    });
    editor.session.setUseWorker(false);
    editor.setOption('tabSize', 4);
    editor.setOption('useSoftTabs', true);
    editor.setValue(wb.code, -1);
    wb.aceEditor = editor;

    const getCode = () => safeString(editor.getValue());
    const setCode = (text) => editor.setValue(safeString(text), -1);
    const log = (message, tone = 'ok') => moduleWorkbenchPushLog(wb.logs, message, tone, 120, 'dev-log');
    const renderLogs = () => {
        logsEl.innerHTML = wb.logs.length
            ? wb.logs.slice(0, 16).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('')
            : '<div class="module-wb-ghost">No execution logs yet.</div>';
    };
    const renderIssues = () => {
        issuesEl.innerHTML = wb.issues.length
            ? wb.issues.map((issue) => `<article class="module-wb-issue ${moduleToneClass(issue.tone) || 'ok'}">${escapeHtml(safeString(issue.text))}</article>`).join('')
            : '<div class="module-wb-ghost">No checks run yet.</div>';
        const errors = wb.issues.filter((issue) => moduleToneClass(issue.tone) === 'error').length;
        status.textContent = `${errors ? `${errors} error` : 'No critical errors'} | ${getCode().length} chars`;
    };
    const applyAnnotations = () => {
        const annotations = wb.issues
            .filter((issue) => moduleToneClass(issue.tone) !== 'ok')
            .map((issue) => ({
                row: Math.max(0, (Number(issue.line) || 1) - 1),
                column: 0,
                text: safeString(issue.text),
                type: moduleToneClass(issue.tone) === 'error' ? 'error' : 'warning',
            }));
        editor.session.setAnnotations(annotations);
    };
    const analyze = () => {
        wb.code = getCode();
        wb.issues = moduleDevStudioScanIssues(wb.code);
        applyAnnotations();
        renderIssues();
    };

    analyze();
    renderLogs();

    editor.session.on('change', () => {
        wb.code = getCode();
        renderIssues();
    });

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-dev-action]') : null;
        if (!target) return;
        const action = safeString(target.dataset.devAction).toLowerCase();
        wb.code = getCode();
        if (action === 'analyze') {
            analyze();
            log('Static analysis completed.', wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error') ? 'warn' : 'ok');
        }
        if (action === 'tests') {
            const hasTests = /\b(test|describe|it)\s*\(/.test(wb.code);
            if (!hasTests) {
                setCode(`${wb.code.trimEnd()}\n\n// test('smoke', () => expect(true).toBe(true));\n`);
                wb.code = getCode();
            }
            analyze();
            log(hasTests ? 'Tests passed in simulation.' : 'No tests found. Added smoke test stub.', hasTests ? 'ok' : 'warn');
        }
        if (action === 'build') {
            analyze();
            const failed = wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error');
            log(failed ? 'Build failed.' : 'Build succeeded.', failed ? 'error' : 'ok');
        }
        if (action === 'format') {
            try {
                editor.execCommand('beautify');
                log('Format command executed.', 'ok');
            } catch (_error) {
                log('Format command unavailable in this runtime.', 'warn');
            }
        }
        if (action === 'snippet') {
            const snippet = `\nexport async function rollout(ctx) {\n    const records = await ctx.fetch();\n    return { ok: true, count: Array.isArray(records) ? records.length : 0 };\n}\n`;
            setCode(`${getCode().trimEnd()}\n${snippet}`);
            wb.code = getCode();
            analyze();
            log('Inserted rollout snippet.', 'ok');
        }
        if (action === 'dockerfile') {
            moduleWorkbenchCopyText(moduleWorkbenchDevDockerfileSnippet(), 'Dockerfile Snippet');
            log('Copied Dockerfile starter.', 'ok');
        }
        if (action === 'export') {
            moduleWorkbenchCopyJson({ code: wb.code, issues: wb.issues, logs: wb.logs.slice(0, 24) }, 'Dev Studio Snapshot');
        }
        renderIssues();
        renderLogs();
    });

    return true;
}

function moduleRenderWorkbenchDevStudio(container, wb) {
    if (moduleRenderWorkbenchDevStudioOss(container, wb)) return;
    if (!container || !wb) return;
    wb.code = safeString(wb.code);
    if (!Array.isArray(wb.issues)) wb.issues = [];
    if (!Array.isArray(wb.logs)) wb.logs = [];

    moduleWorkbenchHeader(container, 'Dev Studio', 'Dispatch engineering tasks to Thomas, inspect issues/checks, and review implementation outputs.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-dev';
    shell.innerHTML = `
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Editor</span><span class="module-wb-stage-meta" data-dev-status></span></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-dev-action="analyze">Analyze</button><button type="button" class="module-item-btn" data-dev-action="tests">Run Tests</button><button type="button" class="module-item-btn" data-dev-action="build">Build</button><button type="button" class="module-item-btn" data-dev-action="snippet">Snippet</button><button type="button" class="module-item-btn" data-dev-action="dockerfile">Dockerfile</button><button type="button" class="module-item-btn" data-dev-action="export">Export</button></div><textarea class="module-wb-code-editor" data-dev-code placeholder="Write code here...">${escapeHtml(wb.code)}</textarea></section>
        <aside class="module-wb-inspector-card"><h4>Issues</h4><div class="module-wb-issues" data-dev-issues></div><h4>Logs</h4><div class="module-wb-log-list" data-dev-logs></div></aside>
        ${moduleWorkbenchRenderOssStack('dev_studio')}
    `;
    container.appendChild(shell);

    const status = shell.querySelector('[data-dev-status]');
    const codeEl = shell.querySelector('[data-dev-code]');
    const issuesEl = shell.querySelector('[data-dev-issues]');
    const logsEl = shell.querySelector('[data-dev-logs]');
    const analyze = () => {
        const code = safeString(wb.code);
        const issues = [];
        if (!code.trim()) issues.push({ tone: 'warn', text: 'Editor is empty.' });
        const opens = (code.match(/{/g) || []).length;
        const closes = (code.match(/}/g) || []).length;
        if (opens !== closes) issues.push({ tone: 'error', text: `Brace mismatch: ${opens} vs ${closes}.` });
        if (/TODO/.test(code)) issues.push({ tone: 'warn', text: 'TODO markers still present.' });
        if (/console\.log\(/.test(code)) issues.push({ tone: 'warn', text: 'Debug logs detected.' });
        if (!/\b(test|describe|it)\s*\(/.test(code)) issues.push({ tone: 'warn', text: 'No tests found.' });
        if (!issues.length) issues.push({ tone: 'ok', text: 'No obvious static issues.' });
        wb.issues = issues;
    };
    const log = (message, tone = 'ok') => moduleWorkbenchPushLog(wb.logs, message, tone, 120, 'dev-log');
    const render = () => {
        issuesEl.innerHTML = wb.issues.length ? wb.issues.map((issue) => `<article class="module-wb-issue ${moduleToneClass(issue.tone) || 'ok'}">${escapeHtml(safeString(issue.text))}</article>`).join('') : '<div class="module-wb-ghost">No checks run yet.</div>';
        logsEl.innerHTML = wb.logs.length ? wb.logs.slice(0, 16).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('') : '<div class="module-wb-ghost">No execution logs yet.</div>';
        const errors = wb.issues.filter((issue) => moduleToneClass(issue.tone) === 'error').length;
        status.textContent = `${errors ? `${errors} error` : 'No critical errors'} | ${safeString(wb.code).length} chars`;
    };
    render();
    if (codeEl) codeEl.addEventListener('input', () => { wb.code = safeString(codeEl.value); render(); });
    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-dev-action]') : null;
        if (!target) return;
        const action = safeString(target.dataset.devAction).toLowerCase();
        wb.code = safeString(codeEl?.value);
        if (action === 'analyze') { analyze(); log('Static analysis completed.', wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error') ? 'warn' : 'ok'); }
        if (action === 'tests') { const hasTests = /\b(test|describe|it)\s*\(/.test(wb.code); log(hasTests ? 'Tests passed in simulation.' : 'No tests found. Added smoke test stub.', hasTests ? 'ok' : 'warn'); if (!hasTests) { wb.code += `${wb.code.endsWith('\n') ? '' : '\n'}\n// test('smoke', () => expect(true).toBe(true));`; if (codeEl) codeEl.value = wb.code; } analyze(); }
        if (action === 'build') { analyze(); log(wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error') ? 'Build failed.' : 'Build succeeded.', wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error') ? 'error' : 'ok'); }
        if (action === 'snippet') { wb.code += `${wb.code.endsWith('\n') ? '' : '\n'}\nexport async function handler(ctx){\n    const data = await ctx.fetch();\n    return { ok: true, size: Array.isArray(data) ? data.length : 0 };\n}\n`; if (codeEl) codeEl.value = wb.code; analyze(); log('Inserted reusable handler snippet.', 'ok'); }
        if (action === 'dockerfile') { moduleWorkbenchCopyText(moduleWorkbenchDevDockerfileSnippet(), 'Dockerfile Snippet'); log('Copied Dockerfile starter.', 'ok'); }
        if (action === 'export') moduleWorkbenchCopyJson({ code: wb.code, issues: wb.issues, logs: wb.logs.slice(0, 20) }, 'Dev Studio Snapshot');
        render();
    });
}

function moduleGameStudioEnsureGrid(wb) {
    wb.gridWidth = moduleWorkbenchClamp(Number(wb.gridWidth) || 20, 8, 64);
    wb.gridHeight = moduleWorkbenchClamp(Number(wb.gridHeight) || 12, 6, 40);
    wb.brush = moduleWorkbenchClamp(Number(wb.brush) || 1, 0, 4);
    if (!Array.isArray(wb.tiles) || wb.tiles.length !== wb.gridHeight || !Array.isArray(wb.tiles[0]) || wb.tiles[0].length !== wb.gridWidth) {
        wb.tiles = Array.from({ length: wb.gridHeight }, () => Array.from({ length: wb.gridWidth }, () => 0));
    }
    if (!Array.isArray(wb.logs)) wb.logs = [];
}

function moduleGameStudioResizeGrid(wb, widthRaw, heightRaw) {
    const nextWidth = moduleWorkbenchClamp(Number(widthRaw) || wb.gridWidth || 20, 8, 64);
    const nextHeight = moduleWorkbenchClamp(Number(heightRaw) || wb.gridHeight || 12, 6, 40);
    const prev = Array.isArray(wb.tiles) ? wb.tiles : [];
    const next = Array.from({ length: nextHeight }, (_row, y) => (
        Array.from({ length: nextWidth }, (_col, x) => moduleWorkbenchClamp(Number(prev?.[y]?.[x]) || 0, 0, 4))
    ));
    wb.gridWidth = nextWidth;
    wb.gridHeight = nextHeight;
    wb.tiles = next;
}

function moduleGameStudioCounts(wb) {
    const counts = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0 };
    wb.tiles.forEach((row) => row.forEach((tile) => {
        const key = String(moduleWorkbenchClamp(Number(tile) || 0, 0, 4));
        counts[key] += 1;
    }));
    return counts;
}

function moduleGameStudioPlayable(wb) {
    let start = null;
    const goals = new Set();
    for (let y = 0; y < wb.gridHeight; y += 1) {
        for (let x = 0; x < wb.gridWidth; x += 1) {
            const tile = Number(wb.tiles[y][x]) || 0;
            if (tile === 3) start = { x, y };
            if (tile === 4) goals.add(`${x},${y}`);
        }
    }
    if (!start || !goals.size) return false;
    const queue = [start];
    const seen = new Set([`${start.x},${start.y}`]);
    while (queue.length) {
        const current = queue.shift();
        if (!current) continue;
        if (goals.has(`${current.x},${current.y}`)) return true;
        [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
            const nx = current.x + dx;
            const ny = current.y + dy;
            if (nx < 0 || ny < 0 || nx >= wb.gridWidth || ny >= wb.gridHeight) return;
            const tile = Number(wb.tiles[ny][nx]) || 0;
            if (tile === 0 || tile === 2) return;
            const key = `${nx},${ny}`;
            if (seen.has(key)) return;
            seen.add(key);
            queue.push({ x: nx, y: ny });
        });
    }
    return false;
}

function moduleGameStudioFindFirstTile(wb, valueRaw) {
    const value = Number(valueRaw) || 0;
    for (let y = 0; y < wb.gridHeight; y += 1) {
        for (let x = 0; x < wb.gridWidth; x += 1) {
            if ((Number(wb.tiles[y][x]) || 0) === value) return { x, y };
        }
    }
    return null;
}

function moduleGameStudioPlayTarget(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (mode === 'auto' || mode === 'phaser' || mode === 'unreal') return mode;
    return 'auto';
}

function moduleGameStudioViewMode(modeRaw) {
    const mode = safeString(modeRaw).toLowerCase();
    if (mode === 'edit' || mode === 'playtest' || mode === 'unreal' || mode === 'split') return mode;
    return 'split';
}

function moduleGameStudioActorTypeFromTile(tileRaw) {
    const tile = Number(tileRaw) || 0;
    if (tile === 1) return 'platform';
    if (tile === 2) return 'hazard';
    if (tile === 3) return 'spawn';
    if (tile === 4) return 'goal';
    return '';
}

function moduleGameStudioTileFromActorType(typeRaw) {
    const type = safeString(typeRaw).toLowerCase();
    if (type === 'platform') return 1;
    if (type === 'hazard') return 2;
    if (type === 'spawn') return 3;
    if (type === 'goal') return 4;
    return 0;
}

function moduleGameStudioActorTileBacked(typeRaw) {
    return moduleGameStudioTileFromActorType(typeRaw) > 0;
}

function moduleGameStudioActorName(typeRaw, indexRaw = 1) {
    const type = safeString(typeRaw).toLowerCase();
    const index = Math.max(1, Number(indexRaw) || 1);
    if (type === 'spawn') return 'Player Spawn';
    if (type === 'goal') return 'Goal Marker';
    if (type === 'hazard') return `Hazard ${index}`;
    if (type === 'platform') return `Platform ${index}`;
    if (type === 'npc') return `NPC ${index}`;
    if (type === 'pickup') return `Pickup ${index}`;
    if (type === 'light') return `Light ${index}`;
    if (type === 'camera') return `Camera ${index}`;
    if (type === 'trigger') return `Trigger ${index}`;
    return `Actor ${index}`;
}

function moduleGameStudioActorId(wb) {
    wb.nextActorId = Math.max(1, Number(wb.nextActorId) || 1);
    const id = `actor-${wb.nextActorId}`;
    wb.nextActorId += 1;
    return id;
}

function moduleGameStudioActorById(wb, actorIdRaw) {
    const actorId = safeString(actorIdRaw);
    if (!Array.isArray(wb?.sceneActors) || !actorId) return null;
    return wb.sceneActors.find((actor) => safeString(actor?.id) === actorId) || null;
}

function moduleGameStudioActorKey(actorTypeRaw, xRaw, yRaw) {
    const actorType = safeString(actorTypeRaw).toLowerCase();
    const x = Number(xRaw);
    const y = Number(yRaw);
    if (!actorType || !Number.isFinite(x) || !Number.isFinite(y)) return '';
    return `${actorType}:${Math.round(x)}:${Math.round(y)}`;
}

function moduleGameStudioNormalizeActor(actorRaw, fallbackId) {
    const actor = actorRaw && typeof actorRaw === 'object' ? actorRaw : {};
    const className = safeString(actor.className || actor.type || 'actor').toLowerCase() || 'actor';
    const id = safeString(actor.id) || safeString(fallbackId) || `actor-${Date.now()}`;
    return {
        id,
        name: safeString(actor.name) || moduleGameStudioActorName(className, 1),
        className,
        assetId: safeString(actor.assetId),
        x: Number(actor.x) || 0,
        y: Number(actor.y) || 0,
        z: Number(actor.z) || 0,
        rx: Number(actor.rx) || 0,
        ry: Number(actor.ry) || 0,
        rz: Number(actor.rz) || 0,
        sx: Number(actor.sx) || 1,
        sy: Number(actor.sy) || 1,
        sz: Number(actor.sz) || 1,
        tileBacked: moduleGameStudioActorTileBacked(className),
    };
}

function moduleGameStudioSyncSceneActorsFromTiles(wb) {
    if (!wb || !Array.isArray(wb.tiles)) return;
    if (!Array.isArray(wb.sceneActors)) wb.sceneActors = [];
    wb.nextActorId = Math.max(1, Number(wb.nextActorId) || 1);

    const previousSelected = safeString(wb.selectedActorId);
    const existingTileActors = new Map();
    const customActors = [];

    wb.sceneActors.forEach((actorRaw) => {
        const actor = moduleGameStudioNormalizeActor(actorRaw);
        if (!moduleGameStudioActorTileBacked(actor.className)) {
            customActors.push({
                ...actor,
                tileBacked: false,
            });
            return;
        }
        const key = moduleGameStudioActorKey(actor.className, actor.x, actor.y);
        if (!key || existingTileActors.has(key)) return;
        existingTileActors.set(key, actor);
    });

    const counters = Object.create(null);
    const tileActors = [];
    for (let y = 0; y < wb.gridHeight; y += 1) {
        for (let x = 0; x < wb.gridWidth; x += 1) {
            const className = moduleGameStudioActorTypeFromTile(wb.tiles?.[y]?.[x]);
            if (!className) continue;
            const key = moduleGameStudioActorKey(className, x, y);
            counters[className] = (Number(counters[className]) || 0) + 1;
            const existing = existingTileActors.get(key);
            const normalized = moduleGameStudioNormalizeActor(existing || {
                id: moduleGameStudioActorId(wb),
                name: moduleGameStudioActorName(className, counters[className]),
                className,
                x,
                y,
                z: 0,
                rx: 0,
                ry: 0,
                rz: 0,
                sx: 1,
                sy: 1,
                sz: 1,
            });
            normalized.className = className;
            normalized.x = x;
            normalized.y = y;
            normalized.z = 0;
            normalized.tileBacked = true;
            tileActors.push(normalized);
        }
    }

    wb.sceneActors = [...tileActors, ...customActors];
    const selectedStillExists = wb.sceneActors.some((actor) => safeString(actor.id) === previousSelected);
    wb.selectedActorId = selectedStillExists ? previousSelected : safeString(wb.sceneActors[0]?.id);
}

function moduleGameStudioRebuildTilesFromActors(wb) {
    if (!wb) return;
    const nextTiles = Array.from({ length: wb.gridHeight }, () => Array.from({ length: wb.gridWidth }, () => 0));
    const uniqueTileOwner = new Map();
    const actors = Array.isArray(wb.sceneActors) ? wb.sceneActors : [];

    actors.forEach((actorRaw) => {
        const actor = moduleGameStudioNormalizeActor(actorRaw);
        const tileType = moduleGameStudioTileFromActorType(actor.className);
        if (!tileType) return;
        const x = moduleWorkbenchClamp(Math.round(Number(actor.x) || 0), 0, wb.gridWidth - 1);
        const y = moduleWorkbenchClamp(Math.round(Number(actor.y) || 0), 0, wb.gridHeight - 1);
        if (tileType === 3 || tileType === 4) {
            uniqueTileOwner.set(tileType, { x, y });
            return;
        }
        nextTiles[y][x] = tileType;
    });

    if (uniqueTileOwner.has(3)) {
        const position = uniqueTileOwner.get(3);
        if (position) nextTiles[position.y][position.x] = 3;
    }
    if (uniqueTileOwner.has(4)) {
        const position = uniqueTileOwner.get(4);
        if (position) nextTiles[position.y][position.x] = 4;
    }

    wb.tiles = nextTiles;
}

const MODULE_GAME_ASSET_TYPES = [
    { id: 'all', label: 'All' },
    { id: 'mesh', label: 'Mesh' },
    { id: 'material', label: 'Material' },
    { id: 'blueprint', label: 'Blueprint' },
    { id: 'audio', label: 'Audio' },
    { id: 'vfx', label: 'VFX' },
    { id: 'ui', label: 'UI' },
];

function moduleGameStudioDefaultAssets() {
    return [
        { id: 'asset-floor-grid', name: 'SM_FloorGrid', type: 'mesh', source: '/Game/Environment/Meshes', tags: ['level', 'base'] },
        { id: 'asset-platform-a', name: 'SM_PlatformA', type: 'mesh', source: '/Game/Environment/Meshes', tags: ['platform'] },
        { id: 'asset-hazard-01', name: 'BP_HazardLaser', type: 'blueprint', source: '/Game/Gameplay/Blueprints', tags: ['hazard'] },
        { id: 'asset-goal-beacon', name: 'BP_GoalBeacon', type: 'blueprint', source: '/Game/Gameplay/Blueprints', tags: ['goal'] },
        { id: 'asset-robot-npc', name: 'BP_RobotGuard', type: 'blueprint', source: '/Game/Characters/Blueprints', tags: ['npc'] },
        { id: 'asset-hud-main', name: 'WBP_MainHUD', type: 'ui', source: '/Game/UI/Widgets', tags: ['ui'] },
    ];
}

function moduleGameStudioNormalizeAsset(assetRaw, fallbackId) {
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : {};
    const id = safeString(asset.id) || safeString(fallbackId) || `asset-${Date.now()}`;
    const typeRaw = safeString(asset.type).toLowerCase();
    const type = MODULE_GAME_ASSET_TYPES.some((row) => safeString(row.id) === typeRaw)
        ? typeRaw
        : 'mesh';
    return {
        id,
        name: safeString(asset.name) || `Asset ${id}`,
        type,
        source: safeString(asset.source) || '/Game',
        tags: Array.isArray(asset.tags)
            ? asset.tags.map((tag) => safeString(tag)).filter(Boolean).slice(0, 12)
            : [],
    };
}

function moduleGameStudioEnsureAssets(wb) {
    if (!wb) return;
    const defaults = moduleGameStudioDefaultAssets();
    const incoming = Array.isArray(wb.assets) && wb.assets.length ? wb.assets : defaults;
    const seen = new Set();
    wb.assets = incoming.map((asset, index) => moduleGameStudioNormalizeAsset(asset, `asset-${index + 1}`))
        .filter((asset) => {
            if (seen.has(asset.id)) return false;
            seen.add(asset.id);
            return true;
        })
        .slice(0, 180);
    wb.selectedAssetId = safeString(wb.selectedAssetId);
    if (!wb.assets.some((asset) => safeString(asset.id) === wb.selectedAssetId)) {
        wb.selectedAssetId = safeString(wb.assets[0]?.id);
    }
    wb.assetFilterType = MODULE_GAME_ASSET_TYPES.some((row) => safeString(row.id) === safeString(wb.assetFilterType).toLowerCase())
        ? safeString(wb.assetFilterType).toLowerCase()
        : 'all';
    wb.assetSearch = safeString(wb.assetSearch);
}

function moduleGameStudioFilteredAssets(wb) {
    const rows = Array.isArray(wb?.assets) ? wb.assets : [];
    const type = safeString(wb?.assetFilterType).toLowerCase() || 'all';
    const query = safeString(wb?.assetSearch).trim().toLowerCase();
    return rows.filter((asset) => {
        const assetType = safeString(asset?.type).toLowerCase();
        if (type !== 'all' && assetType !== type) return false;
        if (!query) return true;
        const haystack = `${safeString(asset?.name)} ${safeString(asset?.source)} ${(Array.isArray(asset?.tags) ? asset.tags.join(' ') : '')}`.toLowerCase();
        return haystack.includes(query);
    });
}

function moduleGameStudioAssetById(wb, assetIdRaw) {
    const assetId = safeString(assetIdRaw);
    const rows = Array.isArray(wb?.assets) ? wb.assets : [];
    return rows.find((asset) => safeString(asset?.id) === assetId) || null;
}

function moduleGameStudioBridgeState(wb) {
    if (!wb) return {};
    if (!wb.bridge || typeof wb.bridge !== 'object') {
        wb.bridge = {};
    }
    const bridge = wb.bridge;
    bridge.status = safeString(bridge.status).toLowerCase() || 'idle';
    bridge.lastPingMs = Number(bridge.lastPingMs) || 0;
    bridge.lastSeenAt = Number(bridge.lastSeenAt) || 0;
    bridge.lastError = safeString(bridge.lastError);
    bridge.routes = Array.isArray(bridge.routes) ? bridge.routes.slice(0, 120) : [];
    bridge.pullCount = Number(bridge.pullCount) || 0;
    bridge.pushCount = Number(bridge.pushCount) || 0;
    bridge.actorSyncPath = safeString(bridge.actorSyncPath) || '/Game/Blueprints/BP_LevelBridge.BP_LevelBridge_C';
    return bridge;
}

async function moduleGameStudioBridgeFetch(wb, endpointRaw, { method = 'GET', body = null, timeoutMs = 4800 } = {}) {
    const url = moduleGameStudioRemoteUrl(wb.unrealRcUrl, endpointRaw);
    if (!url) throw new Error('Set Unreal RC URL first.');
    const started = Date.now();
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let timerId = 0;
    if (controller && Number(timeoutMs) > 0) {
        timerId = window.setTimeout(() => controller.abort(), Number(timeoutMs));
    }
    try {
        const response = await fetch(url, {
            method,
            headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body: body ? JSON.stringify(body) : undefined,
            signal: controller ? controller.signal : undefined,
        });
        const text = await response.text();
        let payload = text;
        try {
            payload = text ? JSON.parse(text) : null;
        } catch (_error) {}
        return {
            ok: response.ok,
            status: response.status,
            statusText: safeString(response.statusText),
            elapsedMs: Date.now() - started,
            url,
            body: payload,
        };
    } finally {
        if (timerId > 0) window.clearTimeout(timerId);
    }
}

async function moduleGameStudioBridgePing(wb, { silent = false } = {}) {
    const bridge = moduleGameStudioBridgeState(wb);
    try {
        const response = await moduleGameStudioBridgeFetch(wb, '/remote/info', { method: 'GET', timeoutMs: 4200 });
        bridge.status = response.ok ? 'online' : 'degraded';
        bridge.lastPingMs = Number(response.elapsedMs) || 0;
        bridge.lastSeenAt = Date.now();
        bridge.lastError = response.ok ? '' : `HTTP ${response.status}`;
        const routeSource = response?.body && typeof response.body === 'object'
            ? (Array.isArray(response.body.routes)
                ? response.body.routes
                : Array.isArray(response.body.pathes)
                    ? response.body.pathes
                    : [])
            : [];
        bridge.routes = routeSource
            .map((row) => safeString(typeof row === 'string' ? row : row?.path || row?.route || row?.name))
            .filter(Boolean)
            .slice(0, 120);
        if (!silent) {
            moduleWorkbenchPushLog(
                wb.logs,
                response.ok
                    ? `Bridge ping ok (${response.elapsedMs} ms).`
                    : `Bridge ping degraded (${response.status}).`,
                response.ok ? 'ok' : 'warn',
                80,
                'game-log',
            );
        }
        return response;
    } catch (error) {
        bridge.status = 'offline';
        bridge.lastPingMs = 0;
        bridge.lastError = safeString(error?.message) || 'Ping failed.';
        if (!silent) {
            moduleWorkbenchPushLog(wb.logs, bridge.lastError, 'error', 80, 'game-log');
        }
        return {
            ok: false,
            status: 0,
            statusText: 'error',
            elapsedMs: 0,
            url: moduleGameStudioRemoteUrl(wb.unrealRcUrl, '/remote/info'),
            body: { error: bridge.lastError },
        };
    }
}

async function moduleGameStudioBridgePushSelectedActor(wb) {
    const actor = moduleGameStudioActorById(wb, wb.selectedActorId);
    if (!actor) throw new Error('Select an actor to push.');
    const bridge = moduleGameStudioBridgeState(wb);
    const payload = {
        objectPath: bridge.actorSyncPath,
        functionName: 'ApplyActorPatch',
        parameters: {
            id: safeString(actor.id),
            name: safeString(actor.name),
            className: safeString(actor.className),
            assetId: safeString(actor.assetId),
            transform: {
                x: Number(actor.x) || 0,
                y: Number(actor.y) || 0,
                z: Number(actor.z) || 0,
                rx: Number(actor.rx) || 0,
                ry: Number(actor.ry) || 0,
                rz: Number(actor.rz) || 0,
                sx: Number(actor.sx) || 1,
                sy: Number(actor.sy) || 1,
                sz: Number(actor.sz) || 1,
            },
        },
    };
    const result = await moduleGameStudioRemoteSend(wb, payload);
    if (result.ok) bridge.pushCount = (Number(bridge.pushCount) || 0) + 1;
    return result;
}

