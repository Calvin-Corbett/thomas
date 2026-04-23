// Extracted from part-025.js
// From audiopresetselect

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