// Extracted from part-024.js
// From item

            renderAll();
            return;
        }
        if (itemId) wb.selectedId = itemId;
        if (itemAction === 'duplicate') { const item = byId(wb.selectedId); if (item) { const copy = { ...item, id: `ui-${wb.nextId++}`, label: `${item.label} Copy` }; wb.components.push(copy); wb.selectedId = copy.id; } }
        if (itemAction === 'delete') { wb.components = wb.components.filter((item) => safeString(item.id) !== safeString(wb.selectedId)); wb.selectedId = ''; }
        renderAll();
    });

    if (inspector) {
        inspector.addEventListener('input', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
            const item = byId(wb.selectedId);
            if (!item) return;
            const prop = safeString(target.dataset.appProp);
            if (!prop) return;
            if (prop === 'label' || prop === 'binding') item[prop] = safeString(target.value).slice(0, 120);
            if (prop === 'type') item.type = safeString(target.value);
            if (prop === 'w' || prop === 'h') item[prop] = moduleWorkbenchClamp(Number(target.value) || item[prop], prop === 'w' ? 80 : 40, prop === 'w' ? 900 : 700);
            if (prop === 'required' && target instanceof HTMLInputElement) item.required = target.checked;
            renderAll();
        });
    }
}

const MODULE_STUDIO_ASSET_TYPES = Object.freeze([
    { id: 'all', label: 'All assets' },
    { id: 'media', label: 'Audio / Video' },
    { id: 'image', label: 'Images' },
    { id: 'pixel', label: 'Pixel art' },
    { id: 'note', label: 'Notes' },
]);

const MODULE_STUDIO_AUDIO_PRESETS = Object.freeze([
    {
        id: 'podcast_clean',
        label: 'Podcast Clean',
        description: 'Speech denoise + loudness target at -16 LUFS.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=80,lowpass=f=12000,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11" output_podcast.wav',
    },
    {
        id: 'voice_broadcast',
        label: 'Broadcast Voice',
        description: 'Tight dialog chain with compression and limiting.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=90,acompressor=threshold=-18dB:ratio=3:attack=20:release=250,alimiter=limit=0.96,loudnorm=I=-14:TP=-1.0:LRA=9" output_broadcast.wav',
    },
    {
        id: 'cinematic_stems',
        label: 'Cinematic Stems',
        description: 'Dialogue/music/sfx-friendly mastering baseline.',
        ffmpeg: 'ffmpeg -i input.wav -af "highpass=f=55,lowpass=f=16000,dynaudnorm=f=150:g=9,loudnorm=I=-18:TP=-2.0:LRA=12" output_stem.wav',
    },
]);

const MODULE_STUDIO_RENDER_PRESETS = Object.freeze([
    {
        id: 'master_1080p',
        label: 'Master 1080p',
        description: 'H.264 archive master with high-quality audio.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -c:v libx264 -preset slow -crf 18 -c:a aac -b:a 320k -movflags +faststart master_1080p.mp4',
    },
    {
        id: 'social_vertical',
        label: 'Social Vertical',
        description: '9:16 export tuned for short-form delivery.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" -c:v libx264 -preset medium -crf 21 -c:a aac -b:a 192k social_vertical.mp4',
    },
    {
        id: 'review_proxy',
        label: 'Review Proxy',
        description: 'Lightweight preview file for fast feedback loops.',
        ffmpeg: 'ffmpeg -f concat -safe 0 -i clips.txt -vf "scale=1280:-2" -c:v libx264 -preset veryfast -crf 28 -c:a aac -b:a 128k review_proxy.mp4',
    },
]);

const MODULE_STUDIO_GENERATION_TOOLS = Object.freeze([
    {
        id: 'comfyui',
        label: 'Comfy Studio',
        description: 'Node-based local image generation workflows.',
        command: 'cd ComfyUI && python main.py --listen 127.0.0.1 --port 8188',
    },
    {
        id: 'krita_ai',
        label: 'Krita + AI Plugin',
        description: 'Paint-over + local inpaint concept workflow.',
        command: 'winget install --id KDE.Krita -e',
    },
    {
        id: 'blender_gen',
        label: 'Blender Scripted Render',
        description: 'Scripted turntables and asset renders.',
        command: 'blender -b scene.blend -P render_pipeline.py -a',
    },
]);

function moduleStudioCatalogFind(catalogRaw, idRaw) {