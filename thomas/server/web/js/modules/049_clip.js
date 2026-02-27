// Extracted from part-025b.js
// From clip

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