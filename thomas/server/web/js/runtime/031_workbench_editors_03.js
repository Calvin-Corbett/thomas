function moduleStudioForgeMarkup(wb) {
    const forge = moduleStudioEnsureForgeState(wb);
    if (!forge) return '';
    return `
        <section class="module-wb-forge-card" data-studio-forge>
            <h4>Pixel Forge</h4>
            <label class="module-wb-field module-wb-field-wide">Prompt
                <input type="text" data-studio-forge-prompt value="${escapeHtml(forge.prompt)}" placeholder="robot desk terminal, blue glow" />
            </label>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-studio-forge-action="generate">Generate Local</button>
                <button type="button" class="module-item-btn" data-studio-forge-action="clear">Clear</button>
                <button type="button" class="module-item-btn" data-studio-forge-action="mirror">Mirror</button>
            </div>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-studio-forge-tool="paint">Paint</button>
                <button type="button" class="module-item-btn" data-studio-forge-tool="erase">Erase</button>
            </div>
            <div class="module-wb-color-palette" data-studio-forge-palette></div>
            <canvas class="module-wb-pixel-canvas" data-studio-forge-canvas width="${forge.size * forge.scale}" height="${forge.size * forge.scale}" aria-label="Pixel editor canvas"></canvas>
            <label class="module-wb-field module-wb-field-wide">Asset Name
                <input type="text" data-studio-forge-name value="${escapeHtml(forge.draftName)}" placeholder="office-asset" />
            </label>
            <div class="module-wb-inspector-actions">
                <button type="button" class="module-item-btn" data-studio-forge-action="save">Save Pixel Asset</button>
                <button type="button" class="module-item-btn" data-studio-forge-action="export">Export PNG</button>
            </div>
            <p class="module-wb-mini-note" data-studio-forge-meta></p>
        </section>
    `;
}

function moduleStudioRenderAssetPreview(stageEl, assetRaw) {
    if (!(stageEl instanceof HTMLElement)) return;
    const asset = assetRaw && typeof assetRaw === 'object' ? assetRaw : null;
    const previewUrl = moduleStudioAssetPreviewUrl(asset);
    stageEl.replaceChildren();
    if (!asset || !previewUrl) {
        const ghost = document.createElement('div');
        ghost.className = 'module-wb-ghost';
        ghost.textContent = 'Select an image or pixel asset to preview.';
        stageEl.appendChild(ghost);
        return;
    }
    const img = document.createElement('img');
    img.src = previewUrl;
    img.alt = safeString(asset.name) || 'Asset preview';
    img.loading = 'lazy';
    stageEl.appendChild(img);
}

function moduleStudioBindForge(shell, wb, { onChanged = null, onLog = null } = {}) {
    const root = shell?.querySelector('[data-studio-forge]');
    if (!(root instanceof HTMLElement)) {
        return { render: () => {} };
    }
    const promptInput = root.querySelector('[data-studio-forge-prompt]');
    const nameInput = root.querySelector('[data-studio-forge-name]');
    const paletteEl = root.querySelector('[data-studio-forge-palette]');
    const canvas = root.querySelector('[data-studio-forge-canvas]');
    const metaEl = root.querySelector('[data-studio-forge-meta]');
    const ctx = canvas instanceof HTMLCanvasElement ? canvas.getContext('2d') : null;
    if (!(paletteEl instanceof HTMLElement) || !(canvas instanceof HTMLCanvasElement) || !ctx) {
        return { render: () => {} };
    }
    const callChanged = () => {
        if (typeof onChanged === 'function') onChanged();
    };
    const pushLog = (messageRaw, toneRaw = 'ok') => {
        if (typeof onLog === 'function') onLog(messageRaw, toneRaw);
    };
    const activeForge = () => moduleStudioEnsureForgeState(wb);
    const paintCell = (xRaw, yRaw) => {
        const forge = activeForge();
        if (!forge) return false;
        const size = forge.size;
        const x = moduleWorkbenchClamp(Math.floor(Number(xRaw) || 0), 0, size - 1);
        const y = moduleWorkbenchClamp(Math.floor(Number(yRaw) || 0), 0, size - 1);
        const index = (y * size) + x;
        const next = forge.tool === 'erase' ? '' : forge.selectedColor;
        if (safeString(forge.draftPixels[index]) === safeString(next)) return false;
        forge.draftPixels[index] = next;
        forge.syncedSelectionId = safeString(wb.selectedAssetId);
        return true;
    };
    const eventToCell = (event) => {
        const forge = activeForge();
        if (!forge) return null;
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        const px = ((event.clientX - rect.left) / rect.width) * forge.size;
        const py = ((event.clientY - rect.top) / rect.height) * forge.size;
        return {
            x: moduleWorkbenchClamp(Math.floor(px), 0, forge.size - 1),
            y: moduleWorkbenchClamp(Math.floor(py), 0, forge.size - 1),
        };
    };
    const mirrorDraft = () => {
        const forge = activeForge();
        if (!forge) return;
        const next = moduleStudioPixelBlank(forge.size);
        for (let y = 0; y < forge.size; y += 1) {
            for (let x = 0; x < forge.size; x += 1) {
                const source = (y * forge.size) + x;
                const target = (y * forge.size) + ((forge.size - 1) - x);
                next[target] = safeString(forge.draftPixels[source]).toLowerCase();
            }
        }
        forge.draftPixels = next;
        forge.syncedSelectionId = safeString(wb.selectedAssetId);
    };
    const renderCanvas = () => {
        const forge = activeForge();
        if (!forge) return;
        const size = forge.size;
        const scale = forge.scale;
        const targetSize = size * scale;
        if (canvas.width !== targetSize || canvas.height !== targetSize) {
            canvas.width = targetSize;
            canvas.height = targetSize;
        }
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (let y = 0; y < size; y += 1) {
            for (let x = 0; x < size; x += 1) {
                const checker = (x + y) % 2 === 0 ? 'rgba(255,255,255,0.035)' : 'rgba(11,18,28,0.42)';
                ctx.fillStyle = checker;
                ctx.fillRect(x * scale, y * scale, scale, scale);
                const color = safeString(forge.draftPixels[(y * size) + x]).toLowerCase();
                if (!/^#[0-9a-f]{6}$/.test(color)) continue;
                ctx.fillStyle = color;
                ctx.fillRect(x * scale, y * scale, scale, scale);
            }
        }
        ctx.strokeStyle = 'rgba(160, 193, 238, 0.16)';
        ctx.lineWidth = 1;
        for (let x = 0; x <= size; x += 1) {
            const lineX = Math.round((x * scale) + 0.5);
            ctx.beginPath();
            ctx.moveTo(lineX, 0);
            ctx.lineTo(lineX, canvas.height);
            ctx.stroke();
        }
        for (let y = 0; y <= size; y += 1) {
            const lineY = Math.round((y * scale) + 0.5);
            ctx.beginPath();
            ctx.moveTo(0, lineY);
            ctx.lineTo(canvas.width, lineY);
            ctx.stroke();
        }
    };
    const renderPalette = () => {
        const forge = activeForge();
        if (!forge) return;
        paletteEl.innerHTML = forge.palette.map((color) => `
            <button
                type="button"
                class="module-wb-color-chip${safeString(color) === safeString(forge.selectedColor) ? ' active' : ''}"
                data-studio-forge-color="${escapeHtml(safeString(color))}"
                style="--chip:${escapeHtml(safeString(color))};"
                aria-label="Pick ${escapeHtml(safeString(color))}">
            </button>
        `).join('');
        root.querySelectorAll('[data-studio-forge-tool]').forEach((btn) => {
            const tool = safeString(btn.getAttribute('data-studio-forge-tool')).toLowerCase();
            btn.classList.toggle('active', tool === safeString(forge.tool));
        });
    };
    const render = () => {
        const forge = activeForge();
        if (!forge) return;
        if (promptInput instanceof HTMLInputElement && document.activeElement !== promptInput) {
            promptInput.value = forge.prompt;
        }
        if (nameInput instanceof HTMLInputElement && document.activeElement !== nameInput) {
            nameInput.value = forge.draftName;
        }
        if (metaEl instanceof HTMLElement) {
            const source = safeString(forge.editingAssetId) ? `editing ${safeString(forge.editingAssetId)}` : 'new draft';
            metaEl.textContent = `${forge.size}x${forge.size} | ${forge.tool} | ${source}`;
        }
        renderPalette();
        renderCanvas();
    };

    let painting = false;
    canvas.addEventListener('pointerdown', (event) => {
        event.preventDefault();
        const point = eventToCell(event);
        if (!point) return;
        if (paintCell(point.x, point.y)) {
            painting = true;
            render();
        }
    });
    canvas.addEventListener('pointermove', (event) => {
        if (!painting) return;
        const point = eventToCell(event);
        if (!point) return;
        if (paintCell(point.x, point.y)) {
            render();
        }
    });
    const stopPaint = () => {
        painting = false;
    };
    canvas.addEventListener('pointerup', stopPaint);
    canvas.addEventListener('pointerleave', stopPaint);
    canvas.addEventListener('pointercancel', stopPaint);

    if (promptInput instanceof HTMLInputElement) {
        promptInput.addEventListener('input', () => {
            const forge = activeForge();
            if (!forge) return;
            forge.prompt = safeString(promptInput.value).slice(0, 180);
        });
    }
    if (nameInput instanceof HTMLInputElement) {
        nameInput.addEventListener('input', () => {
            const forge = activeForge();
            if (!forge) return;
            forge.draftName = safeString(nameInput.value).slice(0, 96);
        });
    }

    root.addEventListener('click', (event) => {
        const colorTarget = event.target instanceof Element ? event.target.closest('[data-studio-forge-color]') : null;
        if (colorTarget) {
            const forge = activeForge();
            if (!forge) return;
            forge.selectedColor = safeString(colorTarget.getAttribute('data-studio-forge-color')).toLowerCase();
            forge.tool = 'paint';
            render();
            return;
        }
        const toolTarget = event.target instanceof Element ? event.target.closest('[data-studio-forge-tool]') : null;
        if (toolTarget) {
            const forge = activeForge();
            if (!forge) return;
            const tool = safeString(toolTarget.getAttribute('data-studio-forge-tool')).toLowerCase();
            forge.tool = tool === 'erase' ? 'erase' : 'paint';
            render();
            return;
        }
        const actionTarget = event.target instanceof Element ? event.target.closest('[data-studio-forge-action]') : null;
        if (!actionTarget) return;
        const forge = activeForge();
        if (!forge) return;
        const action = safeString(actionTarget.getAttribute('data-studio-forge-action')).toLowerCase();
        if (action === 'generate') {
            forge.draftPixels = moduleStudioGeneratePixelPrompt(forge.prompt || forge.draftName, forge.size, forge.palette);
            forge.editingAssetId = '';
            forge.syncedSelectionId = safeString(wb.selectedAssetId);
            pushLog('Generated local pixel draft.', 'ok');
            render();
            return;
        }
        if (action === 'clear') {
            forge.draftPixels = moduleStudioPixelBlank(forge.size);
            forge.editingAssetId = '';
            forge.syncedSelectionId = safeString(wb.selectedAssetId);
            render();
            return;
        }
        if (action === 'mirror') {
            mirrorDraft();
            pushLog('Mirrored pixel draft.', 'ok');
            render();
            return;
        }
        if (action === 'save') {
            const asset = moduleStudioSaveForgeAsset(wb, safeString(forge.editingAssetId));
            if (!asset) {
                pushLog('Nothing to save yet. Add pixels first.', 'warn');
                return;
            }
            pushLog(`Saved ${safeString(asset.name)}.`, 'ok');
            callChanged();
            render();
            return;
        }
        if (action === 'export') {
            const filename = `${(safeString(forge.draftName).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'pixel-asset')}.png`;
            const dataUrl = moduleStudioPixelsToDataUrl(forge.draftPixels, forge.size, 10);
            moduleStudioDownloadDataUrl(filename, dataUrl);
            pushLog(`Exported ${filename}.`, 'ok');
            return;
        }
    });

    render();
    return { render };
}

function moduleRenderWorkbenchStudioOss(container, wb) {
    if (!container || !wb) return false;
    if (wb.ossError) return false;
    if (!wb.ossReady || !window.WaveSurfer) {
        moduleWorkbenchRenderEngineLoading(
            container,
            'Comfy Studio Engine',
            'WaveSurfer timeline with media asset queue and clip sequencing.',
            'Loading Comfy Studio audio engine...',
            'Fallback timeline editor will run if loading fails.',
        );
        if (!wb.ossLoading) {
            wb.ossLoading = true;
            void moduleWorkbenchLoadWaveSurfer().then(() => {
                wb.ossReady = true;
                wb.ossLoading = false;
                wb.ossError = '';
                moduleWorkbenchRefreshMode('studio');
            }).catch((error) => {
                wb.ossLoading = false;
                wb.ossReady = false;
                wb.ossError = safeString(error?.message) || 'Failed to load WaveSurfer.';
                notifyUser('Comfy Studio audio engine failed to load, using fallback timeline.', { tone: 'warn', durationMs: 2300, debugKind: 'studio' });
                moduleWorkbenchRefreshMode('studio');
            });
        }
        return true;
    }

    if (!Array.isArray(wb.assets)) wb.assets = [];
    if (!Array.isArray(wb.timeline)) wb.timeline = [];
    if (!Array.isArray(wb.logs)) wb.logs = [];
    wb.nextId = Math.max(1, Number(wb.nextId) || 1);
    wb.selectedAssetId = safeString(wb.selectedAssetId);
    wb.selectedClipId = safeString(wb.selectedClipId);
    wb.playhead = Math.max(0, Number(wb.playhead) || 0);
    moduleStudioEnsureForgeState(wb);
    moduleStudioEnsureWorkbenchState(wb);

    moduleWorkbenchHeader(container, 'Comfy Studio Engine', 'Thomas-managed Comfy pipelines with connected tools, queue orchestration, and delivery outputs.');
    const shell = document.createElement('section');
    shell.className = 'module-wb-shell module-wb-shell-studio-oss';
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
            <div class="module-wb-wave-stage" data-studio-wave></div>
            <div class="module-wb-image-stage hidden" data-studio-image-stage></div>
            <input type="range" class="module-wb-range" data-studio-playhead min="0" max="1" step="0.05" value="0" />
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
    const waveEl = shell.querySelector('[data-studio-wave]');
    const imageStage = shell.querySelector('[data-studio-image-stage]');
    if (!(assets instanceof HTMLElement)
        || !(timeline instanceof HTMLElement)
        || !(status instanceof HTMLElement)
        || !(inspector instanceof HTMLElement)
        || !(logs instanceof HTMLElement)
        || !(batch instanceof HTMLElement)
        || !(slider instanceof HTMLInputElement)
        || !(waveEl instanceof HTMLElement)
        || !(imageStage instanceof HTMLElement)
        || !(filterQueryInput instanceof HTMLInputElement)
        || !(filterTypeSelect instanceof HTMLSelectElement)
        || !(audioPresetSelect instanceof HTMLSelectElement)
        || !(renderPresetSelect instanceof HTMLSelectElement)
        || !(generationToolSelect instanceof HTMLSelectElement)
        || !(generationPromptInput instanceof HTMLInputElement)
        || !(libraryStats instanceof HTMLElement)) {
        return false;
    }

    if (wb.waveSurfer?.destroy) {
        try {
            wb.waveSurfer.destroy();
        } catch (_error) {}
        wb.waveSurfer = null;
    }
    const wave = window.WaveSurfer.create({
        container: waveEl,
        waveColor: '#7ab8ff',
        progressColor: '#2f79d9',
        cursorColor: '#f6fbff',
        height: 98,
        normalize: true,
        dragToSeek: true,
    });
    wb.waveSurfer = wave;

    const assetById = (idRaw) => wb.assets.find((item) => safeString(item?.id) === safeString(idRaw)) || null;
    const clipById = (idRaw) => wb.timeline.find((item) => safeString(item?.id) === safeString(idRaw)) || null;
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
    const selectedClip = () => clipById(wb.selectedClipId);
    const pushStudioLog = (messageRaw, toneRaw = 'ok') => {
        moduleWorkbenchPushLog(wb.logs, messageRaw, toneRaw, 80, 'studio-log');
    };
    const forgeUi = moduleStudioBindForge(shell, wb, {
        onChanged: () => renderAll(),
        onLog: (messageRaw, toneRaw = 'ok') => pushStudioLog(messageRaw, toneRaw),
    });
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
    const renderLibraryStats = () => {
        const counts = moduleStudioAssetCounts(wb);
        libraryStats.innerHTML = `
            <span class="module-wb-studio-chip">Total <strong>${counts.total}</strong></span>
            <span class="module-wb-studio-chip">Media <strong>${counts.media}</strong></span>
            <span class="module-wb-studio-chip">Images <strong>${counts.image}</strong></span>
            <span class="module-wb-studio-chip">Pixel <strong>${counts.pixel}</strong></span>
        `;
    };
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
    const renderTimeline = () => {
        const total = Math.max(1, recompute());
        timeline.innerHTML = wb.timeline.length
            ? wb.timeline.map((clip) => `<button type="button" class="module-wb-clip${safeString(clip.id) === safeString(wb.selectedClipId) ? ' selected' : ''}" data-studio-clip-id="${escapeHtml(safeString(clip.id))}" style="flex-basis:${Math.max(8, (clip.duration / total) * 100)}%"><span>${escapeHtml(safeString(clip.name))}</span><strong>${moduleStudioDuration(clip.duration)}</strong></button>`).join('')
            : '<div class="module-wb-ghost">Insert assets to build a timeline.</div>';
        slider.max = String(total);
        slider.value = String(Math.min(total, wb.playhead));
    };
    const renderInspector = () => {
        const clip = selectedClip();
        if (!clip) {
            inspector.innerHTML = `<h4>Inspector</h4><p class="module-wb-mini-note">Select a clip to trim, reorder, and remove.</p><div class="module-wb-metrics"><div><span>Assets</span><strong>${wb.assets.length}</strong></div><div><span>Clips</span><strong>${wb.timeline.length}</strong></div><div><span>Total</span><strong>${moduleStudioDuration(recompute())}</strong></div></div>`;
            return;
        }
        inspector.innerHTML = `<h4>${escapeHtml(safeString(clip.name))}</h4><div class="module-wb-field-grid"><label class="module-wb-field">Name<input type="text" data-studio-prop="name" value="${escapeHtml(safeString(clip.name))}" /></label><label class="module-wb-field">Duration<input type="number" min="0.5" step="0.5" data-studio-prop="duration" value="${clip.duration}" /></label></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-studio-action="left">Move Left</button><button type="button" class="module-item-btn" data-studio-action="right">Move Right</button><button type="button" class="module-item-btn" data-studio-action="remove">Remove</button></div>`;
    };
    const renderStatus = () => {
        const renderPreset = moduleStudioCatalogFind(MODULE_STUDIO_RENDER_PRESETS, wb.renderPreset);
        const audioPreset = moduleStudioCatalogFind(MODULE_STUDIO_AUDIO_PRESETS, wb.audioPreset);
        status.textContent = `${wb.playing ? 'Playing' : 'Idle'} | ${moduleStudioDuration(wb.playhead)} / ${moduleStudioDuration(recompute())} | ${safeString(renderPreset?.label)} | ${safeString(audioPreset?.label)}`;
        const playBtn = shell.querySelector('[data-studio-action="play"]');
        if (playBtn) {
            playBtn.textContent = wb.playing ? 'Pause' : 'Play';
        }
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
    const ensureWaveLoaded = (asset) => {
        if (!asset || !moduleStudioCanWaveLoad(asset)) {
            wb.lastWaveAssetId = '';
            return;
        }
        if (safeString(wb.lastWaveAssetId) === safeString(asset.id)) return;
        wb.lastWaveAssetId = safeString(asset.id);
        try {
            wave.load(safeString(asset.url));
            pushStudioLog(`Loaded media: ${safeString(asset.name)}`, 'ok');
            renderLogs();
        } catch (_error) {
            pushStudioLog(`Failed to load ${safeString(asset.name)}.`, 'warn');
            renderLogs();
        }
    };
    const renderMediaPreview = () => {
        const asset = selectedAsset();
        moduleStudioSyncForgeWithSelection(wb, asset);
        const kind = moduleStudioAssetKind(asset);
        const useWave = moduleStudioCanWaveLoad(asset);
        const showImage = !useWave && (kind === 'image' || kind === 'pixel');
        waveEl.classList.toggle('hidden', showImage);
        imageStage.classList.toggle('hidden', !showImage);
        if (useWave) {
            ensureWaveLoaded(asset);
            return;
        }
        if (showImage) {
            try {
                if (wave.isPlaying()) wave.pause();
            } catch (_error) {}
            moduleStudioRenderAssetPreview(imageStage, asset);
        }
    };

    wave.on('ready', () => {
        const asset = selectedAsset();
        if (!asset || !moduleStudioCanWaveLoad(asset)) return;
        const duration = moduleWorkbenchClamp(Number(wave.getDuration()) || Number(asset.duration) || 1, 0.5, 900);
        asset.duration = Number(duration.toFixed(2));
        renderAll();
    });
    wave.on('timeupdate', (timeRaw) => {
        wb.playhead = Math.max(0, Number(timeRaw) || 0);
        renderStatus();
        slider.value = String(Math.min(Number(slider.max) || wb.playhead, wb.playhead));
    });
    wave.on('finish', () => {
        wb.playing = false;
        renderStatus();
    });

    if (form instanceof HTMLFormElement) {
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const nameInput = form.querySelector('[data-studio-asset-name]');
            const durationInput = form.querySelector('[data-studio-asset-duration]');
            const name = safeString(nameInput?.value) || `Asset ${wb.nextId}`;
            const duration = moduleWorkbenchClamp(Number(durationInput?.value) || 6, 1, 900);
            const asset = {
                id: `asset-${wb.nextId++}`,
                name,
                duration,
                url: '',
                mime: '',
                kind: 'note',
            };
            wb.assets.unshift(asset);
            wb.selectedAssetId = asset.id;
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
        const asset = selectedAsset();
        if (asset && moduleStudioCanWaveLoad(asset) && Number(asset.duration) > 0) {
            wave.seekTo(moduleWorkbenchClamp(wb.playhead / Number(asset.duration), 0, 1));
        }
        renderStatus();
    });
    inspector.addEventListener('input', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) return;
        const clip = selectedClip();
        if (!clip) return;
        const prop = safeString(target.dataset.studioProp);
        if (prop === 'name') clip.name = safeString(target.value).slice(0, 100);
        if (prop === 'duration') clip.duration = moduleWorkbenchClamp(Number(target.value) || clip.duration, 0.5, 900);
        renderAll();
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
            const clip = selectedClip();
            if (clip) wb.playhead = Number(clip.start) || 0;
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
            const asset = selectedAsset();
            if (asset && moduleStudioCanWaveLoad(asset)) ensureWaveLoaded(asset);
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
            if (!asset) return;
            const clip = {
                id: `clip-${wb.nextId++}`,
                name: safeString(asset.name),
                duration: moduleWorkbenchClamp(Number(asset.duration) || 1, 0.5, 900),
                start: 0,
            };
            wb.timeline.push(clip);
            wb.selectedClipId = clip.id;
            pushStudioLog(`Inserted clip from ${safeString(asset.name)}.`, 'ok');
            renderAll();
            return;
        }
        if (action === 'play') {
            const asset = selectedAsset();
            if (asset && moduleStudioCanWaveLoad(asset)) {
                wave.playPause();
                wb.playing = wave.isPlaying();
                renderStatus();
                return;
            }
            wb.playing = !wb.playing;
            if (wb.playing) pushStudioLog('Playback simulation started (no media loaded).', 'warn');
            renderLogs();
            renderStatus();
            return;
        }
        if (action === 'stop') {
            wb.playing = false;
            wb.playhead = 0;
            try {
                wave.stop();
            } catch (_error) {}
            renderAll();
            return;
        }
        if (action === 'left' || action === 'right') {
            const index = wb.timeline.findIndex((item) => safeString(item.id) === safeString(wb.selectedClipId));
            if (index >= 0) {
                const next = action === 'left' ? index - 1 : index + 1;
                if (next >= 0 && next < wb.timeline.length) {
                    const copy = wb.timeline[index];
                    wb.timeline[index] = wb.timeline[next];
                    wb.timeline[next] = copy;
                }
            }
            renderAll();
            return;
        }
        if (action === 'remove') {
            wb.timeline = wb.timeline.filter((clip) => safeString(clip.id) !== safeString(wb.selectedClipId));
            wb.selectedClipId = '';
            renderAll();
            return;
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
            renderAll();
            return;
        }
        if (action === 'export_otio') {
            moduleWorkbenchCopyJson(moduleWorkbenchStudioTimelineToOtio(wb), 'Comfy Studio OTIO JSON');
            return;
        }
        if (action === 'ffmpeg') {
            moduleWorkbenchCopyText(moduleWorkbenchStudioFfmpegConcatCommand(wb), 'Comfy Studio ffmpeg Concat Command');
        }
    });

    renderAll();
    return true;
}

