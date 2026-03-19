// Extracted from part-024b.js
// From painting

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
