function officeDraftCatalogIconMarkup(assetType, color = {}) {
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)] || {};
    const shape = safeString(descriptor.shape);
    const body = color.body || color.back || color.swatch || 'linear-gradient(180deg, #7aa7d9, #435b86)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(225, 241, 255, 0.92)';
    const line = color.line || color.seam || 'rgba(12, 20, 34, 0.45)';
    const shadow = '<span style="position:absolute;left:16px;right:16px;bottom:5px;height:5px;border-radius:999px;background:rgba(2,7,14,0.26);"></span>';
    if (assetType === 'couch') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:8px;width:72px;height:24px;border-radius:13px 13px 8px 8px;background:${body};"></span><span style="position:absolute;left:10px;top:26px;width:92px;height:24px;border-radius:14px;background:${surface};"></span><span style="position:absolute;left:0;top:22px;width:22px;height:28px;border-radius:10px;background:${accent};"></span><span style="position:absolute;right:0;top:22px;width:22px;height:28px;border-radius:10px;background:${accent};"></span></span>`;
    }
    if (assetType === 'desk') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:12px;top:20px;width:88px;height:22px;border-radius:9px;background:${surface};"></span><span style="position:absolute;left:24px;top:40px;width:12px;height:18px;border-radius:4px;background:${body};"></span><span style="position:absolute;right:24px;top:40px;width:12px;height:18px;border-radius:4px;background:${body};"></span><span style="position:absolute;left:62px;top:28px;width:24px;height:4px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (assetType === 'chair') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:42px;top:8px;width:30px;height:30px;border-radius:12px 12px 6px 6px;background:${body};"></span><span style="position:absolute;left:34px;top:34px;width:46px;height:18px;border-radius:10px;background:${surface};"></span><span style="position:absolute;left:40px;top:50px;width:5px;height:12px;background:${line};"></span><span style="position:absolute;right:40px;top:50px;width:5px;height:12px;background:${line};"></span></span>`;
    }
    if (assetType === 'workstation') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:42px;width:72px;height:14px;border-radius:7px;background:${surface};"></span><span style="position:absolute;left:32px;top:10px;width:48px;height:34px;border-radius:7px;background:rgba(7,12,22,0.82);border:5px solid ${body};"></span><span style="position:absolute;left:43px;top:23px;width:26px;height:6px;border-radius:999px;background:${accent};box-shadow:0 0 10px ${accent};"></span></span>`;
    }
    if (assetType === 'whiteboard') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:16px;top:10px;width:80px;height:38px;border-radius:8px;background:${surface};border:5px solid ${body};"></span><span style="position:absolute;left:32px;top:27px;width:28px;height:3px;border-radius:999px;background:${accent};"></span><span style="position:absolute;left:32px;top:36px;width:48px;height:3px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (assetType === 'vending_machine') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:40px;top:4px;width:34px;height:56px;border-radius:9px;background:${body};"></span><span style="position:absolute;left:48px;top:14px;width:14px;height:24px;border-radius:4px;background:rgba(231,246,255,0.68);"></span><span style="position:absolute;left:47px;top:42px;width:20px;height:10px;border-radius:5px;background:${accent};"></span><span style="position:absolute;right:39px;top:16px;width:7px;height:24px;border-radius:3px;background:${line};"></span></span>`;
    }
    if (assetType === 'coffee_bar') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:14px;top:32px;width:84px;height:22px;border-radius:10px;background:${body};"></span><span style="position:absolute;left:22px;top:22px;width:68px;height:16px;border-radius:8px;background:${surface};"></span><span style="position:absolute;left:34px;top:8px;width:12px;height:16px;border-radius:4px 4px 8px 8px;background:${accent};"></span><span style="position:absolute;left:54px;top:6px;width:20px;height:20px;border-radius:6px;background:${line};"></span></span>`;
    }
    if (assetType === 'round_table') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:35px;top:9px;width:42px;height:42px;border-radius:999px;background:${surface};box-shadow:inset 0 -8px rgba(0,0,0,0.14);"></span><span style="position:absolute;left:50px;top:24px;width:12px;height:12px;border-radius:999px;background:${body};"></span></span>`;
    }
    if (assetType === 'plant') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:46px;bottom:9px;width:20px;height:18px;border-radius:6px 6px 10px 10px;background:${accent};"></span><span style="position:absolute;left:38px;top:18px;width:22px;height:34px;border-radius:70% 30% 70% 30%;background:${surface};transform:rotate(-25deg);"></span><span style="position:absolute;left:54px;top:8px;width:24px;height:42px;border-radius:45% 65% 45% 65%;background:${body};transform:rotate(15deg);"></span></span>`;
    }
    if (assetType === 'bookshelf') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:24px;top:9px;width:64px;height:48px;border-radius:8px;background:${body};"></span><span style="position:absolute;left:32px;top:24px;width:48px;height:3px;background:${line};"></span><span style="position:absolute;left:32px;top:40px;width:48px;height:3px;background:${line};"></span><span style="position:absolute;left:36px;top:28px;width:5px;height:10px;background:${accent};"></span><span style="position:absolute;left:48px;top:28px;width:5px;height:10px;background:${surface};"></span><span style="position:absolute;left:60px;top:44px;width:5px;height:10px;background:${accent};"></span></span>`;
    }
    if (assetType === 'server_rack') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:40px;top:5px;width:34px;height:54px;border-radius:8px;background:${body};border:4px solid rgba(5,10,18,0.5);"></span><span style="position:absolute;left:49px;top:18px;width:16px;height:5px;border-radius:3px;background:${surface};"></span><span style="position:absolute;left:49px;top:30px;width:16px;height:5px;border-radius:3px;background:${surface};"></span><span style="position:absolute;right:45px;top:19px;width:4px;height:4px;border-radius:999px;background:${accent};box-shadow:0 0 8px ${accent};"></span></span>`;
    }
    if (assetType === 'focus_pod') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:34px;top:6px;width:44px;height:54px;border-radius:24px 24px 12px 12px;background:${body};"></span><span style="position:absolute;left:43px;top:19px;width:26px;height:30px;border-radius:16px 16px 8px 8px;background:${surface};"></span><span style="position:absolute;left:49px;top:30px;width:14px;height:4px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'counter' || shape === 'bench') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:10px;top:25px;width:92px;height:24px;border-radius:10px;background:${surface};"></span><span style="position:absolute;left:18px;top:44px;width:12px;height:14px;border-radius:4px;background:${body};"></span><span style="position:absolute;right:18px;top:44px;width:12px;height:14px;border-radius:4px;background:${body};"></span><span style="position:absolute;left:28px;top:32px;width:56px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'table' || shape === 'tilt_table') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:14px;top:20px;width:84px;height:28px;border-radius:${shape === 'tilt_table' ? '8px 18px 8px 18px' : '16px'};background:${surface};transform:${shape === 'tilt_table' ? 'skewX(-10deg)' : 'none'};"></span><span style="position:absolute;left:36px;top:44px;width:7px;height:14px;background:${body};"></span><span style="position:absolute;right:36px;top:44px;width:7px;height:14px;background:${body};"></span></span>`;
    }
    if (shape === 'screen' || shape === 'board') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:10px;width:72px;height:40px;border-radius:8px;background:${shape === 'screen' ? 'rgba(5,10,18,0.86)' : surface};border:5px solid ${body};"></span><span style="position:absolute;left:35px;top:24px;width:42px;height:5px;border-radius:999px;background:${accent};box-shadow:${shape === 'screen' ? `0 0 10px ${accent}` : 'none'};"></span><span style="position:absolute;left:35px;top:36px;width:30px;height:4px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (shape === 'cabinet' || shape === 'shelf') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:34px;top:8px;width:44px;height:50px;border-radius:8px;background:${body};"></span><span style="position:absolute;left:40px;top:23px;width:32px;height:3px;background:${line};"></span><span style="position:absolute;left:40px;top:38px;width:32px;height:3px;background:${line};"></span><span style="position:absolute;left:44px;top:27px;width:6px;height:9px;background:${accent};"></span><span style="position:absolute;left:58px;top:42px;width:6px;height:9px;background:${surface};"></span></span>`;
    }
    if (shape === 'appliance' || shape === 'machine' || shape === 'console') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:26px;top:20px;width:60px;height:32px;border-radius:9px;background:${body};"></span><span style="position:absolute;left:36px;top:28px;width:28px;height:10px;border-radius:4px;background:${surface};"></span><span style="position:absolute;right:32px;top:30px;width:7px;height:7px;border-radius:999px;background:${accent};box-shadow:0 0 8px ${accent};"></span></span>`;
    }
    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:50px;top:18px;width:10px;height:36px;border-radius:6px;background:${body};"></span><span style="position:absolute;left:38px;top:${shape === 'lamp' || shape === 'light' ? '7px' : '12px'};width:34px;height:${shape === 'sign' ? '22px' : '20px'};border-radius:${shape === 'sign' ? '5px' : '12px'};background:${surface};box-shadow:0 0 10px ${accent};"></span><span style="position:absolute;left:32px;top:53px;width:48px;height:5px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (shape === 'cart' || shape === 'dock' || shape === 'node' || shape === 'box') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:28px;top:25px;width:56px;height:24px;border-radius:8px;background:${surface};border:4px solid ${body};"></span><span style="position:absolute;left:38px;top:48px;width:8px;height:8px;border-radius:999px;background:${line};"></span><span style="position:absolute;right:38px;top:48px;width:8px;height:8px;border-radius:999px;background:${line};"></span><span style="position:absolute;left:46px;top:33px;width:20px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'panel' || shape === 'divider' || shape === 'rug' || shape === 'soft_seat') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:${shape === 'rug' ? '16px' : '34px'};top:${shape === 'rug' ? '21px' : '12px'};width:${shape === 'rug' ? '80px' : '44px'};height:${shape === 'rug' ? '32px' : '42px'};border-radius:${shape === 'soft_seat' ? '999px 999px 18px 18px' : '12px'};background:${surface};border:4px solid ${body};"></span><span style="position:absolute;left:44px;top:31px;width:24px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:30px;top:14px;width:52px;height:36px;border-radius:12px;background:${surface};border:5px solid ${body};"></span></span>`;
}

function officeRenderDraftMapEditorPanel() {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeEnsureDraftMapState();
    const selectedSpace = officeDraftSelectedSpace();
    let panel = officeSceneWrap.querySelector('[data-office-editor-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeEditorPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    if (!state.editorOpen) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    panel.style.display = 'flex';

    const paletteButtons = Object.entries(OFFICE_DRAFT_ROOM_FLOOR_PALETTES).map(([id, palette]) => `
        <button
            type="button"
            data-office-editor-floor-palette="${escapeHtml(id)}"
            aria-pressed="${selectedSpace?.floorPalette === id ? 'true' : 'false'}"
            style="display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border-radius:12px;border:1px solid ${selectedSpace?.floorPalette === id ? 'rgba(129, 182, 255, 0.72)' : 'rgba(116, 141, 181, 0.22)'};background:${selectedSpace?.floorPalette === id ? 'rgba(49, 84, 141, 0.34)' : 'rgba(15, 23, 38, 0.84)'};color:rgba(238,242,249,0.92);">
            <span style="display:inline-block;width:14px;height:14px;border-radius:999px;background:${palette.floor};border:1px solid ${palette.floorBorder};"></span>
            <span>${escapeHtml(palette.label)}</span>
        </button>
    `).join('');
    const selectedAssetRef = state.selectedAssetId ? officeDraftFindAsset(state.selectedAssetId) : null;
    const selectedAsset = selectedAssetRef?.asset || null;
    const rotationStepButtons = officeDraftRotationOptions().map((value) => `
        <button
            type="button"
            data-office-editor-rotation-step="${value}"
            aria-pressed="${state.rotationStep === value ? 'true' : 'false'}"
            style="padding:7px 10px;border-radius:12px;border:1px solid ${state.rotationStep === value ? 'rgba(129, 182, 255, 0.72)' : 'rgba(116, 141, 181, 0.22)'};background:${state.rotationStep === value ? 'rgba(49, 84, 141, 0.34)' : 'rgba(15, 23, 38, 0.84)'};color:rgba(238,242,249,0.92);">
            ${value} deg
        </button>
    `).join('');
    const selectedAssetDescriptor = selectedAsset ? OFFICE_DRAFT_ASSET_LIBRARY[safeString(selectedAsset.type)] : null;
    const selectedAssetColorways = selectedAsset
        ? (OFFICE_DRAFT_ASSET_COLORWAYS[safeString(selectedAsset.type)]
            || OFFICE_DRAFT_ASSET_COLORWAYS[safeString(selectedAssetDescriptor?.colorGroup)]
            || {})
        : {};
    const selectedColorways = selectedAsset
        ? Object.entries(selectedAssetColorways).map(([id, colorway]) => `
            <button
                type="button"
                data-office-editor-asset-color="${escapeHtml(id)}"
                aria-pressed="${safeString(selectedAsset.colorVariant || officeDraftAssetDefaultColorVariant(selectedAsset.type)) === id ? 'true' : 'false'}"
                style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:12px;border:1px solid ${safeString(selectedAsset.colorVariant || officeDraftAssetDefaultColorVariant(selectedAsset.type)) === id ? 'rgba(129, 182, 255, 0.72)' : 'rgba(116, 141, 181, 0.22)'};background:${safeString(selectedAsset.colorVariant || officeDraftAssetDefaultColorVariant(selectedAsset.type)) === id ? 'rgba(49, 84, 141, 0.34)' : 'rgba(15, 23, 38, 0.84)'};color:rgba(238,242,249,0.92);">
                <span style="display:inline-block;width:14px;height:14px;border-radius:999px;background:${colorway.swatch};border:1px solid rgba(255,255,255,0.18);"></span>
                <span>${escapeHtml(colorway.label)}</span>
            </button>
        `).join('')
        : '';
    const selectedScaleButtons = selectedAsset
        ? OFFICE_DRAFT_ASSET_SCALE_OPTIONS.map((value) => `
            <button
                type="button"
                data-office-editor-asset-scale="${value}"
                aria-pressed="${officeDraftClampAssetScale(selectedAsset.scale) === value ? 'true' : 'false'}"
                style="padding:7px 10px;border-radius:12px;border:1px solid ${officeDraftClampAssetScale(selectedAsset.scale) === value ? 'rgba(129, 182, 255, 0.72)' : 'rgba(116, 141, 181, 0.22)'};background:${officeDraftClampAssetScale(selectedAsset.scale) === value ? 'rgba(49, 84, 141, 0.34)' : 'rgba(15, 23, 38, 0.84)'};color:rgba(238,242,249,0.92);">
                ${Math.round(value * 100)}%
            </button>
        `).join('')
        : '';
    const selectedAssetSection = selectedAsset
        ? `
            <section style="display:grid;gap:10px;padding:12px;border-radius:16px;border:1px solid rgba(116,141,181,0.22);background:rgba(14,22,35,0.9);">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                    <div>
                        <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Selected Asset</div>
                        <strong style="display:block;margin-top:4px;font-size:0.98rem;color:rgba(242,246,252,0.96);">${escapeHtml(OFFICE_DRAFT_ASSET_LIBRARY[safeString(selectedAsset.type)]?.label || safeString(selectedAsset.type))}</strong>
                    </div>
                    <div style="font-size:0.72rem;line-height:1.45;text-align:right;color:rgba(198,210,226,0.74);">
                        ${escapeHtml(selectedAssetRef?.space?.name || 'Space')}
                        <br />${officeDraftNormalizeRotation(selectedAsset.rotation)} deg
                    </div>
                </div>
                <div style="font-size:0.75rem;line-height:1.5;color:rgba(198,210,226,0.74);">Use Back if you need to undo the last placement or styling change. Autosave is optional now.</div>
                <div style="display:grid;gap:8px;">
                    <div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.62);">Color</div>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;">${selectedColorways}</div>
                </div>
                <div style="display:grid;gap:8px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                        <span style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.62);">Scale</span>
                        <strong style="font-size:0.76rem;color:rgba(235,241,250,0.92);">${Math.round(officeDraftClampAssetScale(selectedAsset.scale) * 100)}%</strong>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;">${selectedScaleButtons}</div>
                </div>
                <div style="display:grid;gap:8px;">
                    <div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.62);">Layer</div>
                    <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;">
                        <button type="button" data-office-editor-asset-layer="back" style="padding:7px 6px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.78);color:rgba(238,242,249,0.9);font-size:0.68rem;">Back</button>
                        <button type="button" data-office-editor-asset-layer="down" style="padding:7px 6px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.78);color:rgba(238,242,249,0.9);font-size:0.68rem;">Down</button>
                        <button type="button" data-office-editor-asset-layer="up" style="padding:7px 6px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.78);color:rgba(238,242,249,0.9);font-size:0.68rem;">Up</button>
                        <button type="button" data-office-editor-asset-layer="front" style="padding:7px 6px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.78);color:rgba(238,242,249,0.9);font-size:0.68rem;">Front</button>
                    </div>
                </div>
                <button type="button" data-office-editor-asset-deselect="1" style="display:flex;align-items:center;justify-content:center;padding:9px 12px;border-radius:12px;border:1px solid rgba(116,141,181,0.22);background:rgba(16,30,50,0.92);color:rgba(240,244,250,0.94);font-weight:800;">Done Editing Item</button>
                <div style="font-size:0.74rem;line-height:1.45;color:rgba(198,210,226,0.72);">A / D rotate selected asset. Use layer buttons to put chairs behind tables or bring decor forward.</div>
            </section>
        `
        : `
            <section style="display:grid;gap:8px;padding:12px;border-radius:16px;border:1px solid rgba(116,141,181,0.16);background:rgba(11,18,30,0.82);">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Selected Asset</div>
                <div style="font-size:0.78rem;line-height:1.55;color:rgba(198,210,226,0.72);">Select a placed asset to edit its color, change its scale, and rotate it with A / D.</div>
            </section>
        `;
    const catalogSearch = safeString(state.catalogSearch).toLowerCase();
    const catalogCategory = safeString(state.catalogCategory || 'all').toLowerCase() || 'all';
    const catalogEntries = Object.entries(OFFICE_DRAFT_ASSET_LIBRARY);
    const catalogCategories = ['all', ...new Set(catalogEntries.map(([, descriptor]) => safeString(descriptor.category || 'Asset').toLowerCase()))];
    const catalogCategoryButtons = catalogCategories.map((category) => {
        const selected = category === catalogCategory;
        const label = category === 'all' ? 'All' : officeTaskTitle(category);
        return `
            <button type="button" data-office-editor-catalog-category="${escapeHtml(category)}" aria-pressed="${selected ? 'true' : 'false'}" style="padding:6px 9px;border-radius:999px;border:1px solid ${selected ? 'rgba(141,190,255,0.72)' : 'rgba(116,141,181,0.24)'};background:${selected ? 'rgba(49,84,141,0.42)' : 'rgba(9,15,26,0.76)'};color:rgba(235,242,252,0.9);font-size:0.68rem;font-weight:700;text-transform:capitalize;">${escapeHtml(label)}</button>
        `;
    }).join('');
    const visibleCatalogEntries = catalogEntries.filter(([assetType, descriptor]) => {
        const category = safeString(descriptor.category || 'Asset').toLowerCase();
        const haystack = `${assetType} ${descriptor.label || ''} ${descriptor.category || ''} ${descriptor.description || ''}`.toLowerCase();
        return (catalogCategory === 'all' || category === catalogCategory) && (!catalogSearch || haystack.includes(catalogSearch));
    });
    const catalogButtons = visibleCatalogEntries.map(([assetType, descriptor]) => {
        const color = officeDraftAssetColorway(assetType, officeDraftAssetDefaultColorVariant(assetType)) || {};
        const description = assetType === 'couch'
            ? 'Click and drag into a room to place a three-seat couch.'
            : `Click and drag into a room to place ${descriptor.label}.`;
        return `
            <button type="button" data-office-editor-catalog-asset="${escapeHtml(assetType)}" style="display:grid;grid-template-rows:auto 1fr;gap:7px;min-width:0;padding:8px;border-radius:12px;border:1px solid rgba(116,141,181,0.22);background:rgba(14,22,35,0.92);text-align:left;color:rgba(240,244,250,0.94);cursor:grab;">
                <span data-office-catalog-icon="1" style="display:flex;align-items:center;justify-content:center;height:70px;padding:6px 0;border-radius:10px;background:linear-gradient(180deg, rgba(19, 28, 44, 0.96), rgba(11, 17, 28, 0.96));overflow:hidden;">
                    ${officeDraftCatalogIconMarkup(assetType, color)}
                </span>
                <span style="display:grid;gap:4px;min-width:0;">
                    <span style="display:flex;align-items:center;justify-content:space-between;gap:6px;min-width:0;">
                        <strong style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.78rem;">${escapeHtml(descriptor.label)}</strong>
                        <span style="display:inline-block;width:12px;height:12px;flex:0 0 auto;border-radius:999px;background:${color.swatch || color.surface || color.body || '#7aa7d9'};border:1px solid rgba(255,255,255,0.2);"></span>
                    </span>
                    <span style="font-size:0.64rem;color:rgba(186,202,222,0.66);">${escapeHtml(descriptor.category || 'Asset')}</span>
                    <span style="font-size:0.66rem;line-height:1.28;color:rgba(198,210,226,0.72);">${escapeHtml(description)}</span>
                </span>
            </button>
        `;
    }).join('') || '<div style="padding:12px;border-radius:12px;background:rgba(9,15,26,0.72);color:rgba(198,210,226,0.72);font-size:0.76rem;">No catalog matches.</div>';
    const catalogSection = selectedAsset ? '' : `
            <section style="display:flex;flex:0 0 auto;min-height:0;flex-direction:column;gap:8px;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Catalog</div>
                <input data-office-editor-catalog-search="1" value="${escapeHtml(state.catalogSearch || '')}" placeholder="Search assets" style="width:100%;padding:9px 10px;border-radius:12px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);font-size:0.78rem;" />
                <div style="display:flex;gap:6px;overflow-x:auto;overflow-y:hidden;padding-bottom:2px;overscroll-behavior-x:contain;">${catalogCategoryButtons}</div>
                <div data-office-editor-catalog-scroll="1" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-content:start;gap:8px;height:min(46vh,520px);min-height:240px;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:6px;">${catalogButtons}</div>
            </section>
    `;

    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex:0 0 auto;">
            <strong style="font-size:0.92rem;letter-spacing:0.04em;text-transform:uppercase;">Office Editor</strong>
            <span style="font-size:0.72rem;color:rgba(202,214,230,0.72);">${state.autosaveEnabled ? 'Autosave On' : 'Autosave Off'}</span>
        </div>
        <div style="display:flex;flex:1 1 auto;min-height:0;flex-direction:column;gap:12px;margin-top:14px;overflow-y:auto;overflow-x:hidden;padding-right:2px;">
            <section style="display:grid;gap:8px;flex:0 0 auto;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Selected Space</div>
                <button type="button" data-office-editor-selected-space="1" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(14,22,35,0.9);color:rgba(240,244,250,0.94);">
                    <span>${escapeHtml(selectedSpace?.name || 'No space')}</span>
                    <span style="font-size:0.72rem;color:rgba(190,203,220,0.62);">click room label</span>
                </button>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">${paletteButtons}</div>
            </section>
            ${selectedAssetSection}
            ${catalogSection}
            <section style="display:grid;gap:8px;flex:0 0 auto;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Build Controls</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">${rotationStepButtons}</div>
                <button type="button" data-office-editor-grid-toggle="1" aria-pressed="${state.gridEnabled ? 'true' : 'false'}" style="display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:${state.gridEnabled ? 'rgba(49, 84, 141, 0.34)' : 'rgba(14,22,35,0.9)'};color:rgba(240,244,250,0.94);">
                    <span>Grid Snap</span>
                    <strong style="font-size:0.78rem;">${state.gridEnabled ? 'On' : 'Off'}</strong>
                </button>
                <div style="font-size:0.74rem;line-height:1.45;color:rgba(198,210,226,0.72);">
                    Selected asset: ${escapeHtml(selectedAsset ? `${safeString(selectedAsset.type)} · ${officeDraftNormalizeRotation(selectedAsset.rotation)} deg` : 'none')}
                    <br />A / D rotate selected asset
                </div>
            </section>
            <section style="display:grid;gap:8px;flex:0 0 auto;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Save Controls</div>
                <button type="button" data-office-editor-autosave-toggle="1" aria-pressed="${state.autosaveEnabled ? 'true' : 'false'}" style="display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:${state.autosaveEnabled ? 'rgba(49, 84, 141, 0.34)' : 'rgba(14,22,35,0.9)'};color:rgba(240,244,250,0.94);">
                    <span>Autosave</span>
                    <strong style="font-size:0.78rem;">${state.autosaveEnabled ? 'On' : 'Off'}</strong>
                </button>
                <button type="button" data-office-editor-save="1" style="display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(16,30,50,0.92);color:rgba(240,244,250,0.94);">
                    <span>Save Layout</span>
                    <strong style="font-size:0.78rem;">Manual</strong>
                </button>
            </section>
        </div>
    `;
    const searchInput = panel.querySelector('[data-office-editor-catalog-search="1"]');
    const catalogScroll = panel.querySelector('[data-office-editor-catalog-scroll="1"]');
    if (catalogScroll instanceof HTMLElement) {
        catalogScroll.scrollTop = Number(state.catalogScrollTop) || 0;
        catalogScroll.addEventListener('wheel', (event) => {
            const deltaUnit = event.deltaMode === 1 ? 14 : (event.deltaMode === 2 ? 120 : 1);
            const nextTop = Math.max(0, Math.min(
                catalogScroll.scrollHeight - catalogScroll.clientHeight,
                Number(catalogScroll.scrollTop) + ((Number(event.deltaY) || 0) * deltaUnit),
            ));
            if (Math.round(nextTop) === Math.round(Number(catalogScroll.scrollTop) || 0)) return;
            event.preventDefault();
            event.stopPropagation();
            catalogScroll.scrollTop = nextTop;
            state.catalogScrollTop = Math.max(0, Math.round(nextTop));
        }, { passive: false });
        catalogScroll.addEventListener('scroll', () => {
            state.catalogScrollTop = Math.max(0, Math.round(Number(catalogScroll.scrollTop) || 0));
        }, { passive: true });
    }
    if (searchInput instanceof HTMLInputElement) {
        searchInput.addEventListener('input', () => {
            const nextValue = safeString(searchInput.value).slice(0, 60);
            const draftState = officeEnsureDraftMapState();
            if (draftState.catalogSearch === nextValue) return;
            draftState.catalogSearch = nextValue;
            draftState.catalogScrollTop = 0;
            officeRenderDraftMapEditorPanel();
            officePrepareDraftMapShell();
            const nextInput = panel.querySelector('[data-office-editor-catalog-search="1"]');
            if (nextInput instanceof HTMLInputElement) {
                nextInput.focus();
                nextInput.setSelectionRange(nextInput.value.length, nextInput.value.length);
            }
        });
    }
}

function officeToggleDraftEditor(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.editorOpen = !state.editorOpen;
    state.selectedAssetId = null;
    officeDraftPersistLayout(state);
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-click' });
}

function officeDraftAddCatalogAsset(assetType) {
    const state = officeEnsureDraftMapState();
    const descriptor = officeDraftAssetDimensions(assetType, 1);
    const space = officeDraftSelectedSpace();
    if (!descriptor || !space) return;
    const previousSnapshot = officeDraftLayoutSnapshot(state);
    const assetId = `${safeString(assetType)}-${state.nextAssetId++}`;
    const offset = Math.max(0, (Array.isArray(space.assets) ? space.assets.length : 0) * 42);
    const asset = {
        id: assetId,
        type: safeString(assetType),
        x: Math.max(24, Math.min(space.width - descriptor.width - 24, Math.round((space.width - descriptor.width) / 2) + offset)),
        y: Math.max(24, Math.min(space.height - descriptor.height - 24, Math.round((space.height - descriptor.height) / 2) + 100)),
        rotation: 0,
        colorVariant: officeDraftAssetDefaultColorVariant(assetType),
        scale: 1,
    };
    space.assets = Array.isArray(space.assets) ? [...space.assets, asset] : [asset];
    state.selectedAssetId = assetId;
    officeDraftCommitLayoutChange(previousSnapshot, state);
    officeRenderDraftMapScene();
}

function officeDraftBeginCatalogPlacement(assetType, pointerId, clientX, clientY) {
    const state = officeEnsureDraftMapState();
    state.catalogPointerId = pointerId;
    state.catalogPendingType = safeString(assetType);
    state.catalogPreviewSpaceId = '';
    state.catalogPreviewX = 0;
    state.catalogPreviewY = 0;
    state.selectedAssetId = null;
    const worldPoint = officeDraftMapClientToWorld(clientX, clientY);
    const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
    const previewPlacement = previewSpace && worldPoint
        ? officeDraftPlaceAssetInSpace(previewSpace, state.catalogPendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
        : null;
    if (previewSpace && previewPlacement) {
        state.catalogPreviewSpaceId = safeString(previewSpace.id);
        state.catalogPreviewX = previewPlacement.x;
        state.catalogPreviewY = previewPlacement.y;
        state.selectedSpaceId = safeString(previewSpace.id);
    }
    officeRenderDraftMapScene();
}

function officeDraftMoveSelectedAssetLayer(actionRaw) {
    const state = officeEnsureDraftMapState();
    const assetRef = state.selectedAssetId ? officeDraftFindAsset(state.selectedAssetId) : null;
    const assets = Array.isArray(assetRef?.space?.assets) ? assetRef.space.assets : null;
    if (!assetRef?.asset || !assets) return false;
    const currentIndex = assets.findIndex((asset) => safeString(asset?.id) === safeString(assetRef.asset.id));
    if (currentIndex < 0) return false;
    const action = safeString(actionRaw);
    let nextIndex = currentIndex;
    if (action === 'back') nextIndex = 0;
    else if (action === 'front') nextIndex = assets.length - 1;
    else if (action === 'down') nextIndex = Math.max(0, currentIndex - 1);
    else if (action === 'up') nextIndex = Math.min(assets.length - 1, currentIndex + 1);
    if (nextIndex === currentIndex) return false;
    const previousSnapshot = officeDraftLayoutSnapshot(state);
    const [asset] = assets.splice(currentIndex, 1);
    assets.splice(nextIndex, 0, asset);
    officeDraftCommitLayoutChange(previousSnapshot, state);
    return true;
}

function officeDraftNearestAgentIdAtClient(clientXRaw, clientYRaw, maxDistanceRaw = 82, preferredAgentIdRaw = '') {
    const clientX = Number(clientXRaw);
    const clientY = Number(clientYRaw);
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return '';
    const maxDistance = Math.max(24, Number(maxDistanceRaw) || 82);
    const preferredAgentId = safeString(preferredAgentIdRaw);
    let best = null;
    document.querySelectorAll('[data-office-draft-agent-id]').forEach((node) => {
        if (!(node instanceof HTMLElement)) return;
        const agentId = safeString(node.dataset.officeDraftAgentId);
        const rect = node.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return;
        const centerX = rect.left + (rect.width / 2);
        const centerY = rect.top + (rect.height / 2);
        const dx = clientX - centerX;
        const dy = clientY - centerY;
        const distance = Math.hypot(dx, dy);
        const hitRadius = Math.max(maxDistance, (Math.max(rect.width, rect.height) / 2) + 24);
        const insideExpandedRect = clientX >= rect.left - 34
            && clientX <= rect.right + 34
            && clientY >= rect.top - 34
            && clientY <= rect.bottom + 34;
        if (distance > hitRadius && !insideExpandedRect) return;
        const score = distance - (agentId && agentId === preferredAgentId ? maxDistance + 1000 : 0);
        if (!best || score < best.score) {
            best = { agentId, distance, score };
        }
    });
    return safeString(best?.agentId);
}

function officeHandleDraftMapClick(event) {
    if (!(event.target instanceof Element)) return;
    const floorBtn = event.target.closest('[data-office-editor-floor-palette]');
    if (floorBtn instanceof HTMLElement) {
        const space = officeDraftSelectedSpace();
        if (space) {
            const state = officeEnsureDraftMapState();
            const previousSnapshot = officeDraftLayoutSnapshot(state);
            space.floorPalette = safeString(floorBtn.dataset.officeEditorFloorPalette) || 'tan';
            officeDraftCommitLayoutChange(previousSnapshot, state);
            officeRenderDraftMapScene();
        }
        event.preventDefault();
        return;
    }
    const catalogBtn = event.target.closest('[data-office-editor-catalog-asset]');
    if (catalogBtn instanceof HTMLElement) {
        event.preventDefault();
        return;
    }
    const catalogCategoryBtn = event.target.closest('[data-office-editor-catalog-category]');
    if (catalogCategoryBtn instanceof HTMLElement) {
        const state = officeEnsureDraftMapState();
        state.catalogCategory = safeString(catalogCategoryBtn.dataset.officeEditorCatalogCategory) || 'all';
        state.catalogScrollTop = 0;
        officeRenderDraftMapEditorPanel();
        officePrepareDraftMapShell();
        event.preventDefault();
        return;
    }
    const rotationBtn = event.target.closest('[data-office-editor-rotation-step]');
    if (rotationBtn instanceof HTMLElement) {
        const state = officeEnsureDraftMapState();
        state.rotationStep = Number(rotationBtn.dataset.officeEditorRotationStep) || 15;
        officeDraftPersistLayout(state);
        officeRenderDraftMapScene();
        event.preventDefault();
        return;
    }
    if (event.target.closest('[data-office-editor-autosave-toggle="1"]')) {
        const state = officeEnsureDraftMapState();
        officeDraftSetAutosavePreference(state.autosaveEnabled === false, state);
        officeRenderDraftMapScene();
        event.preventDefault();
        return;
    }
    if (event.target.closest('[data-office-editor-save="1"]')) {
        officeDraftManualSaveLayout(event);
        return;
    }
    const colorBtn = event.target.closest('[data-office-editor-asset-color]');
    if (colorBtn instanceof HTMLElement) {
        const state = officeEnsureDraftMapState();
        const assetRef = state.selectedAssetId ? officeDraftFindAsset(state.selectedAssetId) : null;
        if (assetRef?.asset) {
            const previousSnapshot = officeDraftLayoutSnapshot(state);
            assetRef.asset.colorVariant = safeString(colorBtn.dataset.officeEditorAssetColor) || officeDraftAssetDefaultColorVariant(assetRef.asset.type);
            officeDraftCommitLayoutChange(previousSnapshot, state);
            officeRenderDraftMapScene();
        }
        event.preventDefault();
        return;
    }
    const scaleBtn = event.target.closest('[data-office-editor-asset-scale]');
    if (scaleBtn instanceof HTMLElement) {
        const state = officeEnsureDraftMapState();
        const assetRef = state.selectedAssetId ? officeDraftFindAsset(state.selectedAssetId) : null;
        if (assetRef?.asset) {
            const previousSnapshot = officeDraftLayoutSnapshot(state);
            const dimensions = officeDraftAssetDimensions(assetRef.asset.type, Number(scaleBtn.dataset.officeEditorAssetScale) || 1);
            assetRef.asset.scale = dimensions.scale;
            assetRef.asset.x = Math.max(24, Math.min(Number(assetRef.space?.width) - dimensions.width - 24, Number(assetRef.asset.x) || 0));
            assetRef.asset.y = Math.max(24, Math.min(Number(assetRef.space?.height) - dimensions.height - 24, Number(assetRef.asset.y) || 0));
            officeDraftCommitLayoutChange(previousSnapshot, state);
            officeRenderDraftMapScene();
        }
        event.preventDefault();
        return;
    }
    const layerBtn = event.target.closest('[data-office-editor-asset-layer]');
    if (layerBtn instanceof HTMLElement) {
        if (officeDraftMoveSelectedAssetLayer(layerBtn.dataset.officeEditorAssetLayer)) {
            officeRenderDraftMapScene();
        }
        event.preventDefault();
        return;
    }
    if (event.target.closest('[data-office-editor-asset-deselect="1"]')) {
        const state = officeEnsureDraftMapState();
        state.selectedAssetId = null;
        officeDraftPersistLayout(state);
        officeRenderDraftMapScene();
        event.preventDefault();
        return;
    }
    if (event.target.closest('[data-office-editor-grid-toggle="1"]')) {
        const state = officeEnsureDraftMapState();
        state.gridEnabled = !state.gridEnabled;
        officeDraftPersistLayout(state);
        officeRenderDraftMapScene();
        event.preventDefault();
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-minimap="1"]')) {
        officeToggleDraftMinimapMinimized(event);
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-editor="1"]')) {
        officeToggleDraftEditor(event);
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-roster="1"]')) {
        officeToggleDraftAgentRoster(event);
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-chat="1"]')) {
        officeToggleDraftAgentChat(event);
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-save="1"]')) {
        officeDraftManualSaveLayout(event);
        return;
    }
    if (event.target.closest('[data-office-map-toolbar-undo="1"]')) {
        officeDraftUndoLastChange(event);
        return;
    }
    const labelBtn = event.target.closest('[data-office-draft-space-label]');
    if (labelBtn instanceof HTMLElement) {
        const state = officeEnsureDraftMapState();
        state.selectedSpaceId = safeString(labelBtn.dataset.officeDraftSpaceLabel) || state.selectedSpaceId;
        state.userSelectedSpace = true;
        state.selectedAssetId = null;
        officeDraftPersistLayout(state);
        if (state.editorOpen) {
            officeRenderDraftMapScene();
        }
        event.preventDefault();
        return;
    }
    const state = officeEnsureDraftMapState();
    if (!state.editorOpen
        && !event.target.closest('[data-office-editor-panel="1"]')
        && !event.target.closest('[data-office-agent-roster-panel="1"]')
        && !event.target.closest('[data-office-agent-chat-panel="1"]')
        && !event.target.closest('[data-office-map-toolbar="1"]')) {
        const nearbyAgentId = officeDraftNearestAgentIdAtClient(event.clientX, event.clientY);
        if (nearbyAgentId) {
            officeDraftHandleAgentClick(event, nearbyAgentId);
            event.preventDefault();
            return;
        }
    }
    if (state.editorOpen
        && state.selectedAssetId
        && !event.target.closest('[data-office-draft-asset-id]')
        && !event.target.closest('[data-office-editor-panel="1"]')
        && !event.target.closest('[data-office-agent-chat-panel="1"]')
        && !event.target.closest('[data-office-map-toolbar="1"]')) {
        state.selectedAssetId = null;
        officeDraftPersistLayout(state);
        officeRenderDraftMapScene();
    }
}

function officeDraftSpaceForRoomId(roomIdRaw) {
    const state = officeEnsureDraftMapState();
    const roomId = officeDraftNormalizeRoomId(roomIdRaw);
    return state.spaces.find((space) => officeDraftNormalizeRoomId(space?.roomId, space?.id) === roomId)
        || state.spaces.find((space) => safeString(space?.id) === 'lobby')
        || state.spaces[0]
        || null;
}

function officeDraftHomeRoomIdForAgent(agent) {
    const text = `${safeString(agent?.specialty)} ${safeString(agent?.personality)} ${safeString(agent?.name)}`.toLowerCase();
    if (/\b(code|software|debug|build|game|engineer|integration)\b/.test(text)) return 'room-engineering';
    if (/\b(research|docs|documentation|source)\b/.test(text)) return 'room-research';
    if (/\b(design|ui|visual|polish)\b/.test(text)) return 'room-design';
    if (/\b(content|video|social|copy)\b/.test(text)) return 'room-content';
    if (/\b(ops|deploy|reliability|monitor|automation)\b/.test(text)) return 'room-ops';
    if (/\b(support|ticket|customer|review)\b/.test(text)) return 'room-support';
    if (/\b(data|analysis|transform)\b/.test(text)) return 'room-research';
    if (/\b(plan|planning|strategy|roadmap)\b/.test(text)) return 'room-planning';
    return 'room-lobby';
}

function officeDraftAgentPinnedTargetActive(agent, now = performance.now()) {
    if (!agent || !safeString(agent.draftPinnedRoomId)) return false;
    const taskId = safeString(agent.taskId);
    if (safeString(agent.draftPinnedTaskId) !== taskId) return false;
    if (officeDraftAgentCommandActive(agent, now)) return true;
    if (taskId) return true;
    return (Number(agent.draftManualPinUntil) || 0) > (Number(now) || performance.now());
}

function officeDraftAgentEligibleForWander(agent, now = performance.now()) {
    if (!agent || safeString(agent.taskId)) return false;
    if (officeDraftAgentCommandActive(agent, now)) return false;
    if ((Number(agent.draftPausedUntil) || 0) > now) return false;
    if ((Number(agent.draftDropUntil) || 0) > now) return false;
    if ((Number(agent.draftManualPinUntil) || 0) > now) return false;
    if (agent?.draftMotion?.dragging) return false;
    const intent = safeString(agent.intent);
    const state = safeString(agent.state);
    if (intent === 'task' || state === 'working') return false;
    if (state === 'break' && (Number(agent.breakUntil) || 0) > now) return false;
    return true;
}

function officeDraftAgentWanderTargetActive(agent, now = performance.now()) {
    if (!officeDraftAgentEligibleForWander(agent, now)) return false;
    if (!safeString(agent?.draftWanderRoomId)) return false;
    const localX = Number(agent.draftWanderLocalX);
    const localY = Number(agent.draftWanderLocalY);
    return Number.isFinite(localX) && Number.isFinite(localY);
}

function officeDraftAgentWanderTargetWorld(space, agent, now = performance.now()) {
    if (!space || !officeDraftAgentWanderTargetActive(agent, now)) return null;
    if (safeString(agent.draftWanderSpaceId) !== safeString(space.id)
        && officeDraftNormalizeRoomId(agent.draftWanderRoomId) !== officeDraftNormalizeRoomId(space.roomId, space.id)) {
        return null;
    }
    const rect = officeDraftSpaceRect(space);
    const localX = Number(agent.draftWanderLocalX);
    const localY = Number(agent.draftWanderLocalY);
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(rect.left + localX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(rect.top + localY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftWanderCandidateAssets(space) {
    const preferredTypes = new Set([
        'vending_machine', 'coffee_bar', 'couch', 'bean_bag', 'round_table', 'arcade_cabinet',
        'bookshelf', 'whiteboard', 'workstation', 'standing_desk', 'desk', 'conference_table',
        'kanban_board', 'map_table', 'microscope', 'data_wall', 'server_rack', 'focus_pod',
        'bench', 'reception_counter', 'ticket_kiosk', 'tablet_stand',
    ]);
    return (Array.isArray(space?.assets) ? space.assets : []).filter((asset) => {
        const type = safeString(asset?.type);
        const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
        return preferredTypes.has(type) || Boolean(interaction);
    });
}

function officeDraftChooseWanderSpace(agent, now = performance.now()) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces.filter(Boolean) : [];
    if (!spaces.length) return null;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    const currentSpace = motion && Number.isFinite(Number(motion.x)) && Number.isFinite(Number(motion.y))
        ? officeDraftSpaceAtWorldPoint(Number(motion.x), Number(motion.y))
        : null;
    const homeRoomId = officeDraftHomeRoomIdForAgent(agent);
    const lastRoomId = officeDraftNormalizeRoomId(agent?.draftWanderLastRoomId);
    const sequence = Number(agent?.draftWanderSequence) || 0;
    const seed = officeStableHash(`${safeString(agent?.id)}|wander-space|${sequence}|${Math.floor((Number(now) || performance.now()) / 7000)}`);
    const commonRooms = new Set(['room-lobby', 'room-coffee', 'room-break', 'room-pods', 'room-planning']);
    let best = null;
    spaces.forEach((space, index) => {
        const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
        const assetCount = officeDraftWanderCandidateAssets(space).length;
        const center = officeDraftSpaceCenter(space);
        const from = currentSpace ? officeDraftSpaceCenter(currentSpace) : center;
        const distance = Math.hypot(center.x - from.x, center.y - from.y);
        let score = ((seed + (index * 193)) % 1000) + (distance * 0.05);
        if (roomId === homeRoomId) score -= 170;
        if (commonRooms.has(roomId)) score -= 125;
        if (assetCount) score -= Math.min(160, 34 + (assetCount * 14));
        if (currentSpace && safeString(currentSpace.id) === safeString(space.id)) score += 130;
        if (lastRoomId && roomId === lastRoomId && spaces.length > 2) score += 220;
        if (!best || score < best.score) best = { space, score };
    });
    return best?.space || spaces[0] || null;
}

function officeDraftChooseWanderFreePoint(space, agent, seed = 0) {
    if (!space) return null;
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const network = officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const door = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    const candidates = [center, door];
    for (let index = 0; index < 12; index += 1) {
        const hash = officeStableHash(`${safeString(agent?.id)}|wander-point|${safeString(space?.id)}|${seed}|${index}`);
        const xRatio = 0.18 + (((hash % 997) / 997) * 0.64);
        const yRatio = 0.2 + ((((Math.floor(hash / 997)) % 991) / 991) * 0.6);
        candidates.push({
            x: Math.round(bounds.left + ((bounds.right - bounds.left) * xRatio)),
            y: Math.round(bounds.top + ((bounds.bottom - bounds.top) * yRatio)),
        });
    }
    let best = null;
    candidates.forEach((candidateRaw, index) => {
        const candidate = officeDraftClampWorldPointToWalkable(candidateRaw, space, obstacles);
        if (!officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const centerDistance = Math.hypot(candidate.x - center.x, candidate.y - center.y);
        const doorDistance = Math.hypot(candidate.x - door.x, candidate.y - door.y);
        const score = (index * 18) + (centerDistance * 0.12) + (doorDistance * 0.04) - (Math.min(260, clearance) * 1.6);
        if (!best || score < best.score) best = { point: candidate, score };
    });
    return best?.point || center;
}

function officeDraftSetAgentWanderTarget(agent, space, targetWorld, options = {}, now = performance.now()) {
    if (!agent || !space || !targetWorld) return null;
    const roomId = officeDraftNormalizeRoomId(space.roomId, space.id);
    const sequence = (Number(agent.draftWanderSequence) || 0) + 1;
    agent.draftWanderSequence = sequence;
    agent.draftWanderRoomId = roomId;
    agent.draftWanderSpaceId = safeString(space.id);
    agent.draftWanderLocalX = Math.round(Number(targetWorld.x) - (Number(space.x) || 0));
    agent.draftWanderLocalY = Math.round(Number(targetWorld.y) - (Number(space.y) || 0));
    agent.draftWanderAssetId = safeString(options.assetId);
    agent.draftWanderAssetType = safeString(options.assetType);
    agent.draftWanderAction = safeString(options.action || 'wander') || 'wander';
    agent.draftWanderLastRoomId = roomId;
    agent.draftWanderArrivedAt = 0;
    agent.draftWanderNextAt = 0;
    agent.draftWanderDwellMs = OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS
        + (officeStableHash(`${safeString(agent.id)}|wander-dwell|${sequence}`) % Math.max(1, OFFICE_DRAFT_AGENT_WANDER_DWELL_MAX_MS - OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS));
    agent.intent = 'wander';
    if (!new Set(['idle', 'break']).has(safeString(agent.state))) agent.state = 'idle';
    delete agent.draftTargetPointCache;
    delete agent.draftFallbackTargetCache;
    const motion = agent.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (motion && Number(motion.navVersion) === OFFICE_DRAFT_AGENT_NAV_VERSION) {
        motion.targetX = Math.round(Number(targetWorld.x) || 0);
        motion.targetY = Math.round(Number(targetWorld.y) || 0);
        motion.targetSignature = '';
        motion.needsReplan = true;
        motion.routeRetryAfter = 0;
        motion.lastProgressAt = Number(now) || performance.now();
    }
    const stats = officeDraftAgentNavStats(agent);
    if (stats) stats.wanderTargets = (Number(stats.wanderTargets) || 0) + 1;
    return { space, targetWorld, action: agent.draftWanderAction };
}

function officeDraftEnsureAgentWanderTarget(agent, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!officeDraftAgentEligibleForWander(agent, currentNow)) return null;
    const activeSpace = officeDraftAgentWanderTargetActive(agent, currentNow)
        ? officeDraftSpaceForRoomId(agent.draftWanderRoomId)
        : null;
    const activeTarget = activeSpace ? officeDraftAgentWanderTargetWorld(activeSpace, agent, currentNow) : null;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (activeSpace && activeTarget) {
        const routeActive = Array.isArray(motion?.route) && motion.route.length > 0 && Number(motion.routeIndex) < motion.route.length;
        const distance = motion && Number.isFinite(Number(motion.x)) && Number.isFinite(Number(motion.y))
            ? Math.hypot((Number(motion.x) || 0) - activeTarget.x, (Number(motion.y) || 0) - activeTarget.y)
            : 9999;
        if (routeActive || distance > Math.max(OFFICE_DRAFT_AGENT_ROUTE_EPSILON * 2.5, 26)) {
            return { space: activeSpace, targetWorld: activeTarget, action: safeString(agent.draftWanderAction || 'wander') };
        }
        if (!Number(agent.draftWanderArrivedAt)) {
            agent.draftWanderArrivedAt = currentNow;
            agent.draftWanderNextAt = currentNow + Math.max(OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS, Number(agent.draftWanderDwellMs) || 0);
        }
        if ((Number(agent.draftWanderNextAt) || 0) > currentNow) {
            return { space: activeSpace, targetWorld: activeTarget, action: safeString(agent.draftWanderAction || 'wander') };
        }
    }
    const space = officeDraftChooseWanderSpace(agent, currentNow);
    if (!space) return null;
    const seed = officeStableHash(`${safeString(agent.id)}|wander|${Number(agent.draftWanderSequence) || 0}|${Math.floor(currentNow / 1000)}`);
    const assets = officeDraftWanderCandidateAssets(space);
    const targetAsset = assets.length ? assets[seed % assets.length] : null;
    const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset?.type)]?.interaction);
    const targetWorld = targetAsset
        ? officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed, { routeAware: false })
        : officeDraftChooseWanderFreePoint(space, agent, seed);
    const action = officeDraftInferCommandActionFromInteraction(interaction)
        || (targetAsset ? 'inspect' : 'wander');
    return officeDraftSetAgentWanderTarget(agent, space, targetWorld, {
        assetId: safeString(targetAsset?.id),
        assetType: safeString(targetAsset?.type),
        action,
    }, currentNow);
}

function officeDraftRoomIdForAgent(agent) {
    if (!agent) return 'room-lobby';
    const now = performance.now();
    if (officeDraftAgentPinnedTargetActive(agent, now)) {
        return officeDraftNormalizeRoomId(agent.draftPinnedRoomId);
    }
    const taskId = safeString(agent.taskId);
    const task = officeState?.tasks?.find((entry) => (
        safeString(entry?.id) === taskId
        && safeString(entry?.assignedAgentId) === safeString(agent?.id)
        && safeString(entry?.status) !== 'done'
    ));
    if (task?.roomId) return officeDraftNormalizeRoomId(task.roomId);
    const homeRoomId = officeDraftHomeRoomIdForAgent(agent);
    const wanderTarget = !taskId ? officeDraftEnsureAgentWanderTarget(agent, now) : null;
    if (wanderTarget?.space) return officeDraftNormalizeRoomId(wanderTarget.space.roomId, wanderTarget.space.id);
    const remoteRoomId = officeDraftNormalizeRoomId(agent.remoteRoomId);
    if (!taskId) return homeRoomId;
    if (!task && remoteRoomId === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;
    if (agent.remoteRoomId && safeString(agent.intent) === 'task') return officeDraftNormalizeRoomId(agent.remoteRoomId);
    const currentRoom = officeCurrentRoomForAgent(agent);
    if (!task && officeDraftNormalizeRoomId(currentRoom?.id) === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;
    if (currentRoom?.id) return officeDraftNormalizeRoomId(currentRoom.id);
    if (agent.remoteRoomId) return officeDraftNormalizeRoomId(agent.remoteRoomId);
    return 'room-lobby';
}

function officeDraftSpaceForAgent(agent) {
    return officeDraftSpaceForRoomId(officeDraftRoomIdForAgent(agent));
}

function officeDraftAgentsForSpace(space) {
    if (!officeState || !Array.isArray(officeState.agents)) return [];
    const spaceId = safeString(space?.id);
    return officeState.agents.filter((agent) => safeString(officeDraftSpaceForAgent(agent)?.id) === spaceId);
}

function officeDraftAgentAssignmentMap(state = officeEnsureDraftMapState()) {
    const assignments = new Map();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    spaces.forEach((space) => {
        const spaceId = safeString(space?.id);
        if (spaceId) assignments.set(spaceId, []);
    });
    const fallbackSpace = spaces.find((space) => safeString(space?.id) === 'lobby') || spaces[0] || null;
    (officeState?.agents || []).forEach((agent) => {
        const targetSpace = officeDraftSpaceForAgent(agent) || fallbackSpace;
        const spaceId = safeString(targetSpace?.id);
        if (!spaceId) return;
        if (!assignments.has(spaceId)) assignments.set(spaceId, []);
        assignments.get(spaceId).push(agent);
    });
    return assignments;
}

function officeDraftAgentCommandActive(agent, now = performance.now()) {
    return Boolean(agent && (Number(agent.draftCommandUntil) || 0) > (Number(now) || performance.now()));
}

function officeDraftAgentCommandAsset(space, agent, now = performance.now()) {
    if (!officeDraftAgentCommandActive(agent, now)) return null;
    const commandAssetId = safeString(agent?.draftCommandAssetId);
    if (!commandAssetId || !Array.isArray(space?.assets)) return null;
    return space.assets.find((asset) => safeString(asset?.id) === commandAssetId) || null;
}

function officeDraftPrimaryInteractionAsset(space, agent, index = 0, total = 1) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const assets = Array.isArray(space?.assets) ? space.assets : [];
    const state = safeString(agent?.state);
    const intent = safeString(agent?.intent);
    const directedActivity = state === 'working' || state === 'break' || intent === 'task' || intent === 'break';
    const choose = (candidates) => {
        const usable = (Array.isArray(candidates) ? candidates : []).filter(Boolean);
        if (!usable.length) return null;
        const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|asset`);
        const spreadOffset = Math.max(0, Number(index) || 0) * (Math.max(1, Math.floor(usable.length / Math.max(1, Number(total) || 1))) || 3);
        return usable[(seed + spreadOffset) % usable.length];
    };
    const commandAsset = officeDraftAgentCommandAsset(space, agent);
    if (commandAsset) return commandAsset;
    if (!directedActivity && !new Set(['room-coffee', 'room-break', 'room-pods']).has(roomId)) return null;
    if ((roomId === 'room-coffee' || roomId === 'room-break' || state === 'break') && assets.some((asset) => safeString(asset?.type) === 'vending_machine')) {
        return choose(assets.filter((asset) => safeString(asset?.type) === 'vending_machine' || safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(asset?.type)]?.interaction) === 'drink'));
    }
    if (roomId === 'room-break' && assets.some((asset) => safeString(asset?.type) === 'couch')) {
        return choose(assets.filter((asset) => new Set(['couch', 'bean_bag', 'round_table', 'arcade_cabinet']).has(safeString(asset?.type))));
    }
    if (roomId === 'room-pods' && assets.some((asset) => safeString(asset?.type) === 'focus_pod')) {
        return choose(assets.filter((asset) => safeString(asset?.type) === 'focus_pod'));
    }
    const primaryTypesByRoom = {
        'room-engineering': ['workstation', 'desk', 'standing_desk', 'lab_bench', 'code_terminal', 'dual_monitor'],
        'room-planning': ['whiteboard', 'conference_table', 'kanban_board', 'blueprint_table'],
        'room-research': ['bookshelf', 'research_terminal', 'map_table', 'microscope'],
        'room-design': ['drafting_table', 'whiteboard', 'monitor_stand', 'pinboard'],
        'room-content': ['podcast_desk', 'microphone', 'workstation', 'desk', 'green_screen'],
        'room-ops': ['server_rack', 'security_console', 'server_console', 'network_switch', 'data_wall'],
        'room-support': ['desk', 'ticket_kiosk', 'dispatch_board', 'printer'],
        'room-lobby': ['reception_counter', 'package_station', 'bench', 'charging_dock'],
    };
    const primaryTypes = primaryTypesByRoom[roomId] || [];
    const primaryAsset = primaryTypes.length
        ? choose(assets.filter((asset) => primaryTypes.includes(safeString(asset?.type))))
        : null;
    if (primaryAsset) return primaryAsset;
    const workTypes = new Set([
        'workstation', 'desk', 'whiteboard', 'server_rack', 'bookshelf', 'round_table',
        'conference_table', 'kanban_board', 'blueprint_table', 'lab_bench', 'wall_monitor',
        'security_console', 'standing_desk', 'drafting_table', 'mail_sorter', 'printer',
        'reception_counter', 'package_station', 'router_node',
    ]);
    return choose(assets.filter((asset) => {
        const type = safeString(asset?.type);
        const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
        return workTypes.has(type) || new Set(['work', 'monitor', 'present', 'plan', 'design', 'sort', 'dispatch']).has(interaction);
    })) || choose(assets);
}

function officeDraftAgentPinnedTargetWorld(space, agent) {
    if (!space || !agent) return null;
    if (!officeDraftAgentPinnedTargetActive(agent)) return null;
    if (safeString(agent.draftPinnedRoomId) !== officeDraftNormalizeRoomId(space?.roomId, space?.id)) return null;
    const rect = officeDraftSpaceRect(space);
    const localX = Number(agent.draftPinnedLocalX);
    const localY = Number(agent.draftPinnedLocalY);
    if (!Number.isFinite(localX) || !Number.isFinite(localY)) return null;
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(rect.left + localX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(rect.top + localY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftAgentNavStats(agent) {
    if (!agent) return null;
    if (!agent.draftNavStats || typeof agent.draftNavStats !== 'object') {
        agent.draftNavStats = {
            version: OFFICE_DRAFT_AGENT_NAV_VERSION,
            routeResets: 0,
            obstacleDetours: 0,
            stuckReplans: 0,
            hardClamps: 0,
            maxJump: 0,
            lastJump: 0,
        };
    }
    agent.draftNavStats.version = OFFICE_DRAFT_AGENT_NAV_VERSION;
    return agent.draftNavStats;
}

function officeDraftWalkableBounds(space) {
    const rect = officeDraftSpaceRect(space);
    const margin = OFFICE_DRAFT_AGENT_ROOM_MARGIN;
    return {
        left: Math.round(rect.left + margin),
        top: Math.round(rect.top + margin),
        right: Math.round(rect.right - margin),
        bottom: Math.round(rect.bottom - margin),
    };
}

function officeDraftPointInsideRect(point, rect, padding = 0) {
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= (Number(rect?.left) - padding)
        && x <= (Number(rect?.right) + padding)
        && y >= (Number(rect?.top) - padding)
        && y <= (Number(rect?.bottom) + padding);
}

function officeDraftLineSegmentIntersectsRect(a, b, rect, padding = 0) {
    if (!rect) return false;
    if (officeDraftPointInsideRect(a, rect, padding) || officeDraftPointInsideRect(b, rect, padding)) return true;
    const left = Number(rect.left) - padding;
    const right = Number(rect.right) + padding;
    const top = Number(rect.top) - padding;
    const bottom = Number(rect.bottom) + padding;
    const x1 = Number(a?.x) || 0;
    const y1 = Number(a?.y) || 0;
    const x2 = Number(b?.x) || 0;
    const y2 = Number(b?.y) || 0;
    const dx = x2 - x1;
    const dy = y2 - y1;
    let t0 = 0;
    let t1 = 1;
    const clip = (p, q) => {
        if (Math.abs(p) < 0.000001) return q >= 0;
        const r = q / p;
        if (p < 0) {
            if (r > t1) return false;
            if (r > t0) t0 = r;
            return true;
        }
        if (r < t0) return false;
        if (r < t1) t1 = r;
        return true;
    };
    return clip(-dx, x1 - left)
        && clip(dx, right - x1)
        && clip(-dy, y1 - top)
        && clip(dy, bottom - y1)
        && t0 <= t1;
}

function officeDraftPointObstacleClearance(point, obstaclesRaw = []) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : [];
    if (!obstacles.length) return 9999;
    let best = Number.POSITIVE_INFINITY;
    obstacles.forEach((rect) => {
        const x = Number(point?.x) || 0;
        const y = Number(point?.y) || 0;
        if (officeDraftPointInsideRect(point, rect)) {
            best = 0;
            return;
        }
        const dx = x < rect.left ? rect.left - x : (x > rect.right ? x - rect.right : 0);
        const dy = y < rect.top ? rect.top - y : (y > rect.bottom ? y - rect.bottom : 0);
        best = Math.min(best, Math.hypot(dx, dy));
    });
    return Number.isFinite(best) ? best : 9999;
}

const OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES = new Set([
    'acoustic_panel',
    'data_wall',
    'dispatch_board',
    'green_screen',
    'kanban_board',
    'pinboard',
    'room_sign',
    'sticky_note_wall',
    'wall_clock',
    'wall_monitor',
    'whiteboard',
]);

function officeDraftAssetBlocksNavigation(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(descriptor.shape);
    if (!type) return false;
    if (OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES.has(type)) return false;
    if (new Set(['rug', 'carpet']).has(type)) return false;
    if (new Set(['rug']).has(shape)) return false;
    return true;
}

function officeDraftAssetObstacleRect(space, asset, marginRaw = OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN) {
    if (!space || !asset || !officeDraftAssetBlocksNavigation(asset)) return null;
    const dims = officeDraftAssetDimensions(asset.type, asset.scale);
    const margin = Math.max(0, Number(marginRaw) || 0);
    const left = (Number(space.x) || 0) + (Number(asset.x) || 0);
    const top = (Number(space.y) || 0) + (Number(asset.y) || 0);
    return {
        assetId: safeString(asset.id),
        type: safeString(asset.type),
        left: Math.round(left - margin),
        top: Math.round(top - margin),
        right: Math.round(left + dims.width + margin),
        bottom: Math.round(top + dims.height + margin),
    };
}

function officeDraftObstacleRects(space) {
    if (!space || !Array.isArray(space.assets)) return [];
    return space.assets
        .map((asset) => officeDraftAssetObstacleRect(space, asset))
        .filter(Boolean);
}

function officeDraftPointInWalkableBounds(point, space) {
    const bounds = officeDraftWalkableBounds(space);
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom;
}

function officeDraftPointWalkableInSpace(point, space, obstaclesRaw = null) {
    if (!officeDraftPointInWalkableBounds(point, space)) return false;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    return !obstacles.some((rect) => officeDraftPointInsideRect(point, rect));
}

function officeDraftClampWorldPointToWalkable(pointRaw, space, obstaclesRaw = null) {
    if (!space) return {
        x: Math.round(Number(pointRaw?.x) || 0),
        y: Math.round(Number(pointRaw?.y) || 0),
    };
    const bounds = officeDraftWalkableBounds(space);
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const raw = {
        x: Math.round(officeClamp(Number(pointRaw?.x) || ((bounds.left + bounds.right) / 2), bounds.left, bounds.right)),
        y: Math.round(officeClamp(Number(pointRaw?.y) || ((bounds.top + bounds.bottom) / 2), bounds.top, bounds.bottom)),
    };
    if (officeDraftPointWalkableInSpace(raw, space, obstacles)) return raw;
    const candidates = [raw, officeDraftSpaceCenter(space)];
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        candidates.push(
            { x: rect.left - gap, y: rect.top - gap },
            { x: rect.right + gap, y: rect.top - gap },
            { x: rect.left - gap, y: rect.bottom + gap },
            { x: rect.right + gap, y: rect.bottom + gap },
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
        );
    });
    for (let radius = 52; radius <= 420; radius += 52) {
        for (let step = 0; step < 16; step += 1) {
            const angle = (Math.PI * 2 * step) / 16;
            candidates.push({
                x: raw.x + (Math.cos(angle) * radius),
                y: raw.y + (Math.sin(angle) * radius),
            });
        }
    }
    let best = null;
    candidates.forEach((candidate) => {
        const clamped = {
            x: Math.round(officeClamp(Number(candidate?.x) || raw.x, bounds.left, bounds.right)),
            y: Math.round(officeClamp(Number(candidate?.y) || raw.y, bounds.top, bounds.bottom)),
        };
        if (!officeDraftPointWalkableInSpace(clamped, space, obstacles)) return;
        const distance = Math.hypot(clamped.x - raw.x, clamped.y - raw.y);
        if (!best || distance < best.distance) {
            best = { ...clamped, distance };
        }
    });
    return best ? { x: best.x, y: best.y } : raw;
}

function officeDraftSpaceSpawnWorldPoint(space, agent, index = 0, total = 1) {
    const rect = officeDraftSpaceRect(space);
    const totalAgents = Math.max(1, Number(total) || 1);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|spawn`);
    const baseX = Number(space?.robotX) || (rect.width / 2);
    const baseY = Number(space?.robotY) || (rect.height / 2);
    return officeDraftClampWorldPointToWalkable({
        x: rect.left + baseX + ((index - ((totalAgents - 1) / 2)) * 84),
        y: rect.top + baseY + (((seed % 5) - 2) * 34),
    }, space);
}

function officeDraftCheapAgentTargetWorldPoint(space, agent, index = 0, total = 1) {
    const bounds = officeDraftWalkableBounds(space);
    const left = Math.min(bounds.left, bounds.right);
    const right = Math.max(bounds.left, bounds.right);
    const top = Math.min(bounds.top, bounds.bottom);
    const bottom = Math.max(bounds.top, bounds.bottom);
    const totalAgents = Math.max(1, Number(total) || 1);
    const slotIndex = Math.max(0, Math.min(totalAgents - 1, Number(index) || 0));
    const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(totalAgents))));
    const rows = Math.max(1, Math.ceil(totalAgents / columns));
    const column = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|cheap-target`);
    const jitterX = ((seed % 5) - 2) * 14;
    const jitterY = ((Math.floor(seed / 5) % 5) - 2) * 12;
    return {
        x: Math.round(officeClamp(left + (((right - left) / (columns + 1)) * (column + 1)) + jitterX, left, right)),
        y: Math.round(officeClamp(top + (((bottom - top) / (rows + 1)) * (row + 1)) + jitterY, top, bottom)),
    };
}

function officeDraftInitialMotionSpaceForAgent(agent, targetSpace) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    const byId = (spaceId) => spaces.find((space) => safeString(space?.id) === safeString(spaceId)) || null;
    const lastSpace = byId(agent?.draftLastSpaceId);
    if (lastSpace) return lastSpace;
    const currentRoom = typeof officeCurrentRoomForAgent === 'function' ? officeCurrentRoomForAgent(agent) : null;
    const currentSpace = currentRoom?.id ? officeDraftSpaceForRoomId(currentRoom.id) : null;
    if (currentSpace && safeString(currentSpace.id) !== safeString(targetSpace?.id)) return currentSpace;
    const homeSpace = officeDraftSpaceForRoomId(officeDraftHomeRoomIdForAgent(agent));
    if (homeSpace && safeString(homeSpace.id) !== safeString(targetSpace?.id)) return homeSpace;
    const lobby = byId('lobby');
    if (lobby && safeString(lobby.id) !== safeString(targetSpace?.id)) return lobby;
    return targetSpace || lobby || spaces[0] || null;
}

function officeDraftInitialMotionWorldPoint(agent, targetSpace, targetWorld, index = 0, total = 1) {
    const sourceSpace = officeDraftInitialMotionSpaceForAgent(agent, targetSpace);
    if (!sourceSpace) return targetWorld;
    if (officeDraftAgentWanderTargetActive(agent)) {
        return officeDraftSpaceSpawnWorldPoint(sourceSpace, agent, index, total);
    }
    if (!safeString(agent?.taskId)
        && !officeDraftAgentCommandActive(agent)
        && safeString(agent?.intent) !== 'task') {
        return targetWorld;
    }
    return officeDraftSpaceSpawnWorldPoint(sourceSpace, agent, index, total);
}

function officeDraftEnsureAgentMotion(agent, space, index = 0, total = 1, targetAsset = null, now = performance.now()) {
    const pinned = officeDraftAgentPinnedTargetWorld(space, agent);
    const targetWorld = pinned || officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset);
    if (!agent.draftMotion || typeof agent.draftMotion !== 'object' || Number(agent.draftMotion.navVersion) !== OFFICE_DRAFT_AGENT_NAV_VERSION) {
        const startWorld = officeDraftInitialMotionWorldPoint(agent, space, targetWorld, index, total);
        agent.draftMotion = {
            navVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
            x: startWorld.x,
            y: startWorld.y,
            targetX: targetWorld.x,
            targetY: targetWorld.y,
            targetSignature: `spawn:${safeString(space?.id)}`,
            route: [],
            routeIndex: 0,
            lastAt: Number(now) || performance.now(),
            lastProgressAt: Number(now) || performance.now(),
            routeStartedAt: 0,
            arrivedAt: Number(now) || performance.now(),
            dragging: false,
            needsReplan: false,
            lastStepDistance: 0,
        };
    }
    if (!Number.isFinite(Number(agent.draftMotion.x)) || !Number.isFinite(Number(agent.draftMotion.y))) {
        const startWorld = officeDraftInitialMotionWorldPoint(agent, space, targetWorld, index, total);
        agent.draftMotion.x = startWorld.x;
        agent.draftMotion.y = startWorld.y;
    }
    if (!Number.isFinite(Number(agent.draftMotion.lastAt))) {
        agent.draftMotion.lastAt = Number(now) || performance.now();
    }
    agent.draftMotion.navVersion = OFFICE_DRAFT_AGENT_NAV_VERSION;
    officeDraftAgentNavStats(agent);
    return agent.draftMotion;
}

function officeDraftAgentMotionSpeed(agent) {
    const base = Math.max(OFFICE_DRAFT_AGENT_SPEED_MIN, Math.min(
        OFFICE_DRAFT_AGENT_SPEED_MAX,
        (Number(agent?.speed) || 3.2) * OFFICE_DRAFT_AGENT_SPEED_SCALE,
    ));
    if (officeDraftAgentCommandActive(agent)) return base * 1.16;
    if (safeString(agent?.intent) === 'task') return base * 1.04;
    if (safeString(agent?.state) === 'break') return base * 0.78;
    return base;
}

function officeDraftAgentTargetSignature(space, agent, targetWorld, targetAsset = null) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const pinnedKey = officeDraftAgentPinnedTargetActive(agent) && safeString(agent?.draftPinnedRoomId) === roomId
        ? `${Math.round(Number(agent?.draftPinnedLocalX) || 0)},${Math.round(Number(agent?.draftPinnedLocalY) || 0)}`
        : '';
    const wanderKey = !pinnedKey && officeDraftAgentWanderTargetActive(agent) && officeDraftNormalizeRoomId(agent?.draftWanderRoomId) === roomId
        ? `${Math.round(Number(agent?.draftWanderLocalX) || 0)},${Math.round(Number(agent?.draftWanderLocalY) || 0)}:${Number(agent?.draftWanderSequence) || 0}:${safeString(agent?.draftWanderAssetId)}`
        : '';
    return [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        roomId,
        pinnedKey,
        wanderKey,
        (pinnedKey || wanderKey) ? '' : safeString(targetAsset?.id),
        Math.round(Number(targetWorld?.x) || 0),
        Math.round(Number(targetWorld?.y) || 0),
    ].join('|');
}

function officeDraftStepInsideDoorCorridor(space, fromPoint, toPoint) {
    if (!space) return false;
    const network = officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const door = officeDraftSpaceDoorPoint(space, network);
    const interior = officeDraftSpaceDoorInteriorPoint(space, network);
    const corridor = {
        x1: interior.x,
        y1: interior.y,
        x2: door.outsideX,
        y2: door.outsideY,
    };
    return officeDraftPointOnSegment(fromPoint, corridor, 28)
        && officeDraftPointOnSegment(toPoint, corridor, 28);
}

function officeDraftStepOnHallway(fromPoint, toPoint, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments : [];
    if (!segments.length) return false;
    const tolerance = Math.max(34, (OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH / 2) - 12);
    return officeDraftNearestHallwayPoint(fromPoint, network).distance <= tolerance
        && officeDraftNearestHallwayPoint(toPoint, network).distance <= tolerance;
}

function officeDraftCurrentPointWalkable(current, space) {
    if (!space) return false;
    if (officeDraftStepOnHallway(current, current)) return true;
    return officeDraftPointWalkableInSpace(current, space);
}

function officeDraftRememberBlockedTarget(motion, signatureRaw, nowRaw = performance.now()) {
    if (!motion || typeof motion !== 'object') return;
    const signature = safeString(signatureRaw);
    if (!signature) return;
    const currentNow = Number(nowRaw) || performance.now();
    const until = currentNow + OFFICE_DRAFT_AGENT_BLOCKED_TARGET_MS;
    const records = motion.blockedTargetRecords && typeof motion.blockedTargetRecords === 'object'
        ? motion.blockedTargetRecords
        : {};
    Object.keys(records).forEach((key) => {
        if ((Number(records[key]) || 0) <= currentNow) delete records[key];
    });
    records[signature] = until;
    motion.blockedTargetRecords = records;
    motion.blockedTargetSignature = signature;
    motion.blockedTargetUntil = until;
}

function officeDraftTargetBlocked(motion, signatureRaw, nowRaw = performance.now()) {
    if (!motion || typeof motion !== 'object') return false;
    const signature = safeString(signatureRaw);
    if (!signature) return false;
    const currentNow = Number(nowRaw) || performance.now();
    const records = motion.blockedTargetRecords && typeof motion.blockedTargetRecords === 'object'
        ? motion.blockedTargetRecords
        : {};
    if ((Number(records[signature]) || 0) > currentNow) return true;
    return safeString(motion.blockedTargetSignature) === signature
        && (Number(motion.blockedTargetUntil) || 0) > currentNow;
}

function officeDraftHoldAgentRouteAfterBlock(motion, nowRaw = performance.now(), retryMs = OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS) {
    if (!motion || typeof motion !== 'object') return;
    const currentNow = Number(nowRaw) || performance.now();
    motion.route = [];
    motion.routeIndex = 0;
    motion.needsReplan = false;
    motion.routeRetryAfter = Math.max(Number(motion.routeRetryAfter) || 0, currentNow + Math.max(480, Number(retryMs) || 0));
    officeDraftRememberBlockedTarget(motion, motion.targetSignature, currentNow);
    motion.lastProgressAt = currentNow;
}

function officeDraftConstrainAgentStep(agent, motion, nextPoint, now = performance.now()) {
    const next = {
        x: Math.round(Number(nextPoint?.x) || Number(motion?.x) || 0),
        y: Math.round(Number(nextPoint?.y) || Number(motion?.y) || 0),
    };
    const current = {
        x: Math.round(Number(motion?.x) || next.x),
        y: Math.round(Number(motion?.y) || next.y),
    };
    const space = officeDraftSpaceAtWorldPoint(next.x, next.y)
        || officeDraftSpaceAtWorldPoint(current.x, current.y);
    if (!space) return next;
    if (officeDraftStepOnHallway(current, next)) return next;
    if (officeDraftPointWalkableInSpace(next, space)) return next;
    if (officeDraftStepInsideDoorCorridor(space, current, next)) return next;
    const eased = [0.75, 0.5, 0.33, 0.2].find((factor) => {
        const candidate = {
            x: Math.round(current.x + ((next.x - current.x) * factor)),
            y: Math.round(current.y + ((next.y - current.y) * factor)),
        };
        return (officeDraftStepOnHallway(current, candidate)
            || officeDraftStepInsideDoorCorridor(space, current, candidate)
            || (
                officeDraftPointWalkableInSpace(candidate, space)
                && officeDraftSegmentClearInSpace(current, candidate, space)
            ));
    });
    if (Number.isFinite(eased)) {
        return {
            x: Math.round(current.x + ((next.x - current.x) * eased)),
            y: Math.round(current.y + ((next.y - current.y) * eased)),
        };
    }
    const stats = officeDraftAgentNavStats(agent);
    if (stats) stats.hardClamps += 1;
    officeDraftHoldAgentRouteAfterBlock(motion, now);
    if (officeDraftCurrentPointWalkable(current, space)) return current;
    return officeDraftClampWorldPointToWalkable(current, space);
}

function officeDraftRecordAgentStep(agent, motion, fromPoint, toPoint) {
    const distance = Math.round(Math.hypot((Number(toPoint?.x) || 0) - (Number(fromPoint?.x) || 0), (Number(toPoint?.y) || 0) - (Number(fromPoint?.y) || 0)));
    motion.lastStepDistance = distance;
    const stats = officeDraftAgentNavStats(agent);
    if (stats) {
        stats.lastJump = distance;
        stats.maxJump = Math.max(Number(stats.maxJump) || 0, distance);
    }
}

function officeDraftMotionPaintFresh(now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    const lastPaintAt = Number(officeState?.lastDraftMotionPaintAt) || currentNow;
    const maxPaintGap = typeof OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS === 'number'
        ? OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS
        : 260;
    return currentNow - lastPaintAt <= maxPaintGap;
}

function officeDraftAdvanceAgentCheapMotion(agent, motion, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!motion || typeof motion !== 'object' || !officeDraftMotionPaintFresh(currentNow)) {
        if (motion && typeof motion === 'object') motion.lastAt = currentNow;
        return;
    }
    const lastAt = Number(motion.lastAt) || currentNow;
    const deltaSeconds = Math.max(0, Math.min(0.14, (currentNow - lastAt) / 1000));
    motion.lastAt = currentNow;
    if (motion.dragging || (Number(agent?.draftPausedUntil) || 0) > currentNow) return;
    const targetX = Number(motion.targetX);
    const targetY = Number(motion.targetY);
    if (!Number.isFinite(targetX) || !Number.isFinite(targetY)) return;
    const dx = targetX - (Number(motion.x) || targetX);
    const dy = targetY - (Number(motion.y) || targetY);
    const distance = Math.hypot(dx, dy);
    if (distance <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        motion.x = Math.round(targetX);
        motion.y = Math.round(targetY);
        motion.arrivedAt = currentNow;
        motion.needsReplan = false;
        motion.route = [];
        motion.routeIndex = 0;
        return;
    }
    const step = Math.min(distance, officeDraftAgentMotionSpeed(agent) * deltaSeconds);
    if (step <= 0) return;
    const fromPoint = { x: Number(motion.x) || targetX, y: Number(motion.y) || targetY };
    const nextRaw = {
        x: fromPoint.x + ((dx / distance) * step),
        y: fromPoint.y + ((dy / distance) * step),
    };
    const nextPoint = {
        x: Math.round(Number(nextRaw.x) || fromPoint.x),
        y: Math.round(Number(nextRaw.y) || fromPoint.y),
    };
    const stepSpace = officeDraftSpaceAtWorldPoint(nextPoint.x, nextPoint.y)
        || officeDraftSpaceAtWorldPoint(fromPoint.x, fromPoint.y);
    const canStep = officeDraftStepOnHallway(fromPoint, nextPoint)
        || (stepSpace && (
            officeDraftStepInsideDoorCorridor(stepSpace, fromPoint, nextPoint)
            || (
                officeDraftPointWalkableInSpace(nextPoint, stepSpace)
                && officeDraftSegmentClearInSpace(fromPoint, nextPoint, stepSpace)
            )
        ));
    if (!canStep) {
        motion.needsReplan = true;
        return;
    }
    motion.x = nextPoint.x;
    motion.y = nextPoint.y;
    officeDraftRecordAgentStep(agent, motion, fromPoint, nextPoint);
    if (Math.hypot(motion.x - fromPoint.x, motion.y - fromPoint.y) > 1) {
        motion.lastProgressAt = currentNow;
    }
    if (Math.abs(dx) > 1) {
        agent.facing = dx >= 0 ? 1 : -1;
    }
}

function officeDraftAdvanceAgentMotion(agent, motion, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!officeDraftMotionPaintFresh(currentNow)) {
        motion.lastAt = currentNow;
        return;
    }
    const lastAt = Number(motion.lastAt) || currentNow;
    const deltaSeconds = Math.max(0, Math.min(0.18, (currentNow - lastAt) / 1000));
    motion.lastAt = currentNow;
    if (motion.dragging || (Number(agent?.draftPausedUntil) || 0) > currentNow) {
        return;
    }
    const route = Array.isArray(motion.route) ? motion.route : [];
    if (!route.length || Number(motion.routeIndex) >= route.length) {
        return;
    }
    let remaining = officeDraftAgentMotionSpeed(agent) * deltaSeconds;
    while (remaining > 0 && Number(motion.routeIndex) < route.length) {
        const waypoint = route[Number(motion.routeIndex)];
        const dx = (Number(waypoint?.x) || motion.x) - motion.x;
        const dy = (Number(waypoint?.y) || motion.y) - motion.y;
        const distance = Math.hypot(dx, dy);
        if (distance <= OFFICE_DRAFT_AGENT_WAYPOINT_EPSILON) {
            motion.x = Math.round(Number(waypoint?.x) || motion.x);
            motion.y = Math.round(Number(waypoint?.y) || motion.y);
            motion.routeIndex = Number(motion.routeIndex) + 1;
            continue;
        }
        const step = Math.min(distance, remaining);
        const fromPoint = { x: motion.x, y: motion.y };
        const nextPoint = officeDraftConstrainAgentStep(agent, motion, {
            x: motion.x + ((dx / distance) * step),
            y: motion.y + ((dy / distance) * step),
        }, currentNow);
        motion.x = nextPoint.x;
        motion.y = nextPoint.y;
        officeDraftRecordAgentStep(agent, motion, fromPoint, nextPoint);
        if (Math.hypot(motion.x - fromPoint.x, motion.y - fromPoint.y) > 1) {
            motion.lastProgressAt = currentNow;
        } else if ((currentNow - (Number(motion.lastProgressAt) || currentNow)) > OFFICE_DRAFT_AGENT_STUCK_REPLAN_MS) {
            officeDraftHoldAgentRouteAfterBlock(motion, currentNow, OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS);
            const stats = officeDraftAgentNavStats(agent);
            if (stats) stats.stuckReplans += 1;
            break;
        }
        if (Math.abs(dx) > 1) {
            agent.facing = dx >= 0 ? 1 : -1;
        }
        remaining -= step;
        break;
    }
    if (Number(motion.routeIndex) >= route.length) {
        motion.route = [];
        motion.routeIndex = 0;
        motion.arrivedAt = currentNow;
        agent.draftLastSpaceId = safeString(officeDraftSpaceAtWorldPoint(motion.x, motion.y)?.id);
    }
}

function officeDraftConsumeRoutePlanBudget(stateRaw = null) {
    const state = stateRaw || officeDraftMapState;
    if (!state || !Number.isFinite(Number(state.agentRoutePlansRemaining))) return true;
    if (Number(state.agentRoutePlansRemaining) > 0) {
        state.agentRoutePlansRemaining = Number(state.agentRoutePlansRemaining) - 1;
        return true;
    }
    state.agentRoutePlanDeferred = true;
    return false;
}

function officeDraftAgentHasPendingRoutePlan(agent, nowRaw = performance.now()) {
    if (!agent || typeof agent !== 'object') return false;
    const now = Number(nowRaw) || performance.now();
    if ((Number(agent.draftPausedUntil) || 0) > now) return false;
    const motion = agent.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (!motion || Number(motion.navVersion) !== OFFICE_DRAFT_AGENT_NAV_VERSION) return true;
    if (motion.dragging === true) return false;
    if ((Number(motion.routeRetryAfter) || 0) > now) return false;
    if (motion.needsReplan === true) return true;
    const signature = safeString(motion.targetSignature);
    if (!signature || signature.startsWith('spawn:') || signature.startsWith('deferred:')) return true;
    const routeActive = Array.isArray(motion.route) && motion.route.length > 0;
    if (routeActive) return false;
    const distanceToTarget = Math.hypot(
        (Number(motion.x) || 0) - (Number(motion.targetX) || Number(motion.x) || 0),
        (Number(motion.y) || 0) - (Number(motion.targetY) || Number(motion.y) || 0),
    );
    return distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON && (Number(motion.routeRetryAfter) || 0) <= now;
}

function officeDraftRoutePlanQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if ((Number(state.routePlanQuietUntil) || 0) > currentNow) return true;
    return officeDraftAgentRenderQuietActive(state, currentNow);
}

function officeDraftScheduleDeferredRoutePlan(stateRaw = null, now = performance.now()) {
    const state = stateRaw || officeDraftMapState;
    if (!state || state.agentRoutePlanTimer) return;
    const currentNow = Number(now) || performance.now();
    const previousCost = Math.max(0, Number(officeState?.lastDraftAgentRenderDurationMs) || 0);
    const adaptiveDelay = previousCost > OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS
        ? Math.min(2200, Math.max(900, Math.round(previousCost * 8)))
        : 900;
    const lastRoutePlanAt = Number(state.lastRoutePlanRenderAt) || 0;
    const sinceLastRoutePlan = currentNow - lastRoutePlanAt;
    const throttleDelay = Math.max(0, OFFICE_DRAFT_AGENT_ROUTE_PLAN_MIN_INTERVAL_MS - sinceLastRoutePlan);
    state.agentRoutePlanTimer = window.setTimeout(() => {
        state.agentRoutePlanTimer = 0;
        const timerNow = performance.now();
        if (officeDraftRoutePlanQuietActive(state, timerNow)) {
            officeDraftScheduleDeferredRoutePlan(state, timerNow);
            return;
        }
        officeRenderDraftAgentLayerOnly(timerNow, { force: true, source: 'route-plan' });
    }, Math.max(adaptiveDelay, throttleDelay, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS - (currentNow % OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS)));
}

function officeDraftAgentWorldPlacement(space, agent, index, total, now = performance.now(), targetAsset = null) {
    if (!space || !agent) return null;
    const currentNow = Number(now) || performance.now();
    const state = officeEnsureDraftMapState();
    const skipRoutePlanning = state?.agentLayerSkipRoutePlanning === true;
    const cachedMotion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (skipRoutePlanning && cachedMotion && Number(cachedMotion.navVersion) === OFFICE_DRAFT_AGENT_NAV_VERSION
        && Number.isFinite(Number(cachedMotion.x)) && Number.isFinite(Number(cachedMotion.y))) {
        const cachedRouteActive = Array.isArray(cachedMotion.route)
            && cachedMotion.route.length > 0
            && Number(cachedMotion.routeIndex) < cachedMotion.route.length;
        if (cachedRouteActive) {
            officeDraftAdvanceAgentMotion(agent, cachedMotion, currentNow);
        } else {
            officeDraftAdvanceAgentCheapMotion(agent, cachedMotion, currentNow);
        }
        const distanceToTarget = Math.hypot(
            (Number(cachedMotion.x) || 0) - (Number(cachedMotion.targetX) || Number(cachedMotion.x) || 0),
            (Number(cachedMotion.y) || 0) - (Number(cachedMotion.targetY) || Number(cachedMotion.y) || 0),
        );
        const routeStillActive = Array.isArray(cachedMotion.route)
            && cachedMotion.route.length > 0
            && Number(cachedMotion.routeIndex) < cachedMotion.route.length;
        if (!routeStillActive && (cachedMotion.needsReplan === true || distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON)) {
            state.agentRoutePlanDeferred = true;
        }
        return {
            x: Math.round(Number(cachedMotion.x) || 0),
            y: Math.round(Number(cachedMotion.y) || 0),
            routeActive: routeStillActive
                || cachedMotion.needsReplan === true
                || distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON,
        };
    }
    if (skipRoutePlanning) {
        const deferredTarget = officeDraftCheapAgentTargetWorldPoint(space, agent, index, total);
        const cachedPoint = cachedMotion
            && Number.isFinite(Number(cachedMotion.x))
            && Number.isFinite(Number(cachedMotion.y))
            ? { x: Math.round(Number(cachedMotion.x) || 0), y: Math.round(Number(cachedMotion.y) || 0) }
            : null;
        const startWorld = cachedPoint || officeDraftInitialMotionWorldPoint(agent, space, deferredTarget, index, total);
        agent.draftMotion = {
            navVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
            x: startWorld.x,
            y: startWorld.y,
            targetX: deferredTarget.x,
            targetY: deferredTarget.y,
            targetSignature: `deferred:${safeString(space?.id)}:${deferredTarget.x},${deferredTarget.y}`,
            route: [],
            routeIndex: 0,
            lastAt: currentNow,
            lastProgressAt: currentNow,
            routeStartedAt: 0,
            arrivedAt: currentNow,
            dragging: false,
            needsReplan: true,
            lastStepDistance: 0,
        };
        state.agentRoutePlanDeferred = true;
        officeDraftAgentNavStats(agent);
        return {
            x: startWorld.x,
            y: startWorld.y,
            routeActive: Math.hypot(startWorld.x - deferredTarget.x, startWorld.y - deferredTarget.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON,
        };
    }
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const pinned = officeDraftAgentPinnedTargetWorld(space, agent);
    let targetWorld = officeDraftClampWorldPointToWalkable(pinned || officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset), space);
    let targetSignature = officeDraftAgentTargetSignature(space, agent, targetWorld, targetAsset);
    const motion = officeDraftEnsureAgentMotion(agent, space, index, total, targetAsset, currentNow);
    if (!pinned && officeDraftTargetBlocked(motion, targetSignature, currentNow)) {
        targetAsset = null;
        targetWorld = officeDraftFallbackAgentTargetWorldPoint(space, agent, index, total);
        targetSignature = `${officeDraftAgentTargetSignature(space, agent, targetWorld, null)}|fallback`;
    }
    if (motion.dragging) {
        return { x: Math.round(motion.x), y: Math.round(motion.y), routeActive: false };
    }
    if ((Number(motion.routeRetryAfter) || 0) > 0
        && (Number(motion.routeRetryAfter) || 0) <= currentNow
        && (!Array.isArray(motion.route) || motion.route.length === 0)
        && Math.hypot((Number(motion.x) || targetWorld.x) - targetWorld.x, (Number(motion.y) || targetWorld.y) - targetWorld.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        motion.needsReplan = true;
        motion.routeRetryAfter = 0;
    }
    if ((Number(agent.draftPausedUntil) || 0) <= currentNow && (motion.needsReplan || safeString(motion.targetSignature) !== targetSignature)) {
        if (!officeDraftConsumeRoutePlanBudget(state)) {
            motion.needsReplan = true;
            motion.lastAt = currentNow;
            return {
                x: Math.round(Number(motion.x) || targetWorld.x),
                y: Math.round(Number(motion.y) || targetWorld.y),
                routeActive: Array.isArray(motion.route) && motion.route.length > 0,
            };
        }
        const startWorld = { x: Number(motion.x) || targetWorld.x, y: Number(motion.y) || targetWorld.y };
        let route = officeDraftRouteBetweenWorldPoints(startWorld, space, targetWorld, network);
        let routeBlocked = officeDraftRouteHasBlockedSegment(route, state.spaces, network);
        let routeReachedTarget = officeDraftRouteReached(route, targetWorld);
        if ((!routeReachedTarget || routeBlocked) && !pinned) {
            const blockedTargetSignature = targetSignature;
            const fallbackTarget = officeDraftFallbackAgentTargetWorldPoint(space, agent, index, total);
            const fallbackRoute = officeDraftRouteBetweenWorldPoints(startWorld, space, fallbackTarget, network);
            const fallbackBlocked = officeDraftRouteHasBlockedSegment(fallbackRoute, state.spaces, network);
            if (!fallbackBlocked && officeDraftRouteReached(fallbackRoute, fallbackTarget)) {
                officeDraftRememberBlockedTarget(motion, blockedTargetSignature, currentNow);
                targetAsset = null;
                targetWorld = fallbackTarget;
                targetSignature = `${officeDraftAgentTargetSignature(space, agent, targetWorld, null)}|fallback`;
                route = fallbackRoute;
                routeBlocked = false;
                routeReachedTarget = true;
            }
        }
        if (routeBlocked) {
            route = [startWorld];
        }
        motion.route = route;
        motion.routeIndex = route.length > 1 ? 1 : 0;
        motion.targetX = targetWorld.x;
        motion.targetY = targetWorld.y;
        motion.targetSignature = targetSignature;
        motion.routeStartedAt = currentNow;
        motion.lastAt = currentNow;
        motion.lastProgressAt = currentNow;
        motion.needsReplan = false;
        const stats = officeDraftAgentNavStats(agent);
        if (stats) {
            stats.routeResets += 1;
            if (route.length > 2) stats.obstacleDetours += 1;
        }
        if (route.length <= 1 && Math.hypot(startWorld.x - targetWorld.x, startWorld.y - targetWorld.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
            motion.x = targetWorld.x;
            motion.y = targetWorld.y;
        } else if (route.length <= 1) {
            officeDraftHoldAgentRouteAfterBlock(motion, currentNow, 2400);
        }
    }
    officeDraftAdvanceAgentMotion(agent, motion, currentNow);
    return {
        x: Math.round(Number(motion.x) || targetWorld.x),
        y: Math.round(Number(motion.y) || targetWorld.y),
        routeActive: Array.isArray(motion.route) && motion.route.length > 0,
    };
}

function officeDraftAgentWalkPlacement(space, agent, index, total, now = performance.now(), targetAsset = null) {
    const world = officeDraftAgentWorldPlacement(space, agent, index, total, now, targetAsset);
    if (!world) return null;
    return {
        x: Math.round(world.x - (Number(space?.x) || 0)),
        y: Math.round(world.y - (Number(space?.y) || 0)),
        worldX: world.x,
        worldY: world.y,
        routeActive: world.routeActive,
    };
}

function officeDraftAgentPlacement(space, agent, index, total, now = performance.now()) {
    const targetAsset = officeDraftPrimaryInteractionAsset(space, agent, index, total);
    const placement = officeDraftAgentWalkPlacement(space, agent, index, total, now, targetAsset);
    if (placement) return placement;
    const target = officeDraftAgentTargetWorldPoint(space, agent, index, total, targetAsset);
    return {
        x: Math.round(target.x - (Number(space?.x) || 0)),
        y: Math.round(target.y - (Number(space?.y) || 0)),
        worldX: target.x,
        worldY: target.y,
        routeActive: false,
    };
}

function officeDraftAgentActivity(agent, space) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const now = performance.now();
    const state = safeString(agent?.state);
    if (agent?.draftMotion?.dragging) return 'dragging';
    if ((Number(agent?.draftDropUntil) || 0) > now) return 'dropped';
    if ((Number(agent?.draftPausedUntil) || 0) > now) {
        return agent?.speech ? 'talking' : 'paused';
    }
    if (Array.isArray(agent?.draftMotion?.route) && agent.draftMotion.route.length) return 'walking';
    officeDraftMaybeCompleteAgentCommand(agent, now);
    if (officeDraftAgentCommandActive(agent, now)) {
        const commandIntent = safeString(agent?.draftInteractionIntent);
        if (commandIntent === 'drink') return 'drink';
        if (commandIntent === 'food') return 'drink';
        if (commandIntent === 'sit') return 'sit';
        if (['work', 'play', 'research', 'print', 'charge', 'monitor', 'record'].includes(commandIntent)) return 'working';
    }
    if (state === 'working') return 'working';
    if (roomId === 'room-coffee') return 'drink';
    if (roomId === 'room-break') return 'sit';
    if (state === 'idle' && safeString(agent?.intent) === 'task') return 'thinking';
    return 'idle';
}

function officeDraftAgentActivityLabel(agent, activity, total = 1) {
    if (activity === 'working') return 'working';
    if (activity === 'walking') return 'en route';
    if (activity === 'drink') return `${safeString(agent?.draftCommandPropLabel || 'Coke')} break`;
    if (activity === 'sit') return 'syncing';
    if (activity === 'paused') return 'paused';
    if (activity === 'talking') return 'talking';
    if (activity === 'dragging') return 'moving';
    if (activity === 'dropped') return 'placed';
    if (activity === 'thinking') return 'thinking';
    if (Number(total) > 1) return 'with team';
    return safeString(agent?.specialty || 'idle');
}

function officeDraftAgentAnimation(agent, activity, now = performance.now()) {
    if (activity === 'walking') return 'walking';
    if (activity === 'working') return safeString(agent?.intent) === 'task' ? 'working' : 'thinking';
    if (activity === 'drink') return 'drinking';
    if (activity === 'sit') return 'sitting';
    if (activity === 'talking') return 'talking';
    if (activity === 'paused') return 'paused';
    if (activity === 'dragging') return 'dragging';
    if (activity === 'dropped') return 'dropped';
    if (activity === 'thinking') return 'thinking';
    if (((Math.floor(((Number(now) || 0) / 2200) + (officeStableHash(agent?.id) % 7)) % 11) === 0)) return 'celebrating';
    return 'idle';
}

function officeDraftAgentSocialLine(agent, space, index, total, activity, now = performance.now()) {
    if (Number(total) < 2) return '';
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|social`);
    const cadence = activity === 'working' ? 2400 : 3000;
    const slot = Math.floor(((Number(now) || performance.now()) / cadence) + (seed % 5)) % 6;
    if (slot > 1) return '';
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const linesByRoom = {
        'room-engineering': ['Pushing a fix.', 'Running checks.', 'Need a review?'],
        'room-research': ['Found a source.', 'Cross-checking that.', 'I have notes.'],
        'room-content': ['Draft is moving.', 'Tightening copy.', 'Queueing assets.'],
        'room-ops': ['Watching deploys.', 'Logs look steady.', 'Checking alerts.'],
        'room-support': ['I can take that.', 'Reply drafted.', 'Ticket triaged.'],
        'room-coffee': ['Coke break.', 'Back in a sec.', 'Refueled.'],
        'room-break': ['Quick sync?', 'Resetting focus.', 'Ready after this.'],
        'room-pods': ['Deep work.', 'Holding context.', 'On the thread.'],
        'room-planning': ['Plan is clearer.', 'Next step?', 'I mapped it.'],
        'room-lobby': ['Available.', 'Who needs help?', 'Dispatch ready.'],
    };
    const lines = linesByRoom[roomId] || ['On it.', 'Syncing up.', 'I can help.'];
    return lines[(index + seed) % lines.length];
}

function officeDraftAgentPropLabel(agent) {
    const commandIntent = officeDraftAgentCommandActive(agent) ? safeString(agent?.draftInteractionIntent) : '';
    const commandProp = safeString(agent?.draftCommandPropLabel);
    if (commandIntent && commandProp) return commandProp;
    if (commandIntent === 'drink') return safeString(agent?.draftCommandPropLabel || 'Coke') || 'Coke';
    if (commandIntent === 'play') return 'game';
    const text = `${safeString(agent?.specialty)} ${safeString(agent?.personality)} ${safeString(agent?.name)}`.toLowerCase();
    if (/\b(code|software|debug|build|game|engineer)\b/.test(text)) return '</>';
    if (/\b(research|docs|document|source)\b/.test(text)) return 'doc';
    if (/\b(design|ui|visual|polish)\b/.test(text)) return 'ui';
    if (/\b(ops|deploy|reliability|monitor)\b/.test(text)) return 'ops';
    if (/\b(support|ticket|customer|review)\b/.test(text)) return 'msg';
    if (/\b(data|analysis|transform)\b/.test(text)) return 'db';
    if (/\b(plan|strategy|roadmap)\b/.test(text)) return 'map';
    if (/\b(content|video|social)\b/.test(text)) return 'cam';
    return 'ai';
}

function officeDraftAgentUiVisibility(state, agent, activity, selected, now = performance.now(), total = 1) {
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const hovered = safeString(state?.hoveredAgentId) === safeString(agent?.id);
    const clickedAt = Number(agent?.draftClickedAt) || 0;
    const dropUntil = Number(agent?.draftDropUntil) || 0;
    const clicked = clickedAt > 0 && clickedAt + 6600 > (Number(now) || performance.now());
    const dropped = dropUntil > 0 && dropUntil > (Number(now) || performance.now());
    const focused = Boolean(selected || hovered || clicked || dropped || agent?.draftMotion?.dragging);
    const densityAllowsNames = Math.max(1, Number(total) || 1) <= 3;
    const activeAgentId = safeString(state?.expandedRosterAgentId || officeState?.selectedAgentId);
    const speechText = typeof officeVisibleSpeech === 'function' ? officeVisibleSpeech(agent, now) : safeString(agent?.speech);
    const speechContext = activity === 'talking' || activity === 'paused' || activity === 'dropped';
    return {
        focused,
        showName: focused || (!activeAgentId && densityAllowsNames && zoom >= OFFICE_DRAFT_AGENT_NAME_ZOOM),
        showStatus: false,
        showProp: false,
        showBubble: Boolean(safeString(speechText) && speechContext),
    };
}

function officeEnsureDraftPerformanceStyles() {
    if (document.getElementById('office-draft-performance-styles')) return;
    const style = document.createElement('style');
    style.id = 'office-draft-performance-styles';
    style.textContent = `
        body.office-active #te-space-root {
            display: none !important;
        }
        body.office-active .app-layout,
        body.office-active .main-content {
            background: #050a12 !important;
        }
        #officeWorkspace [data-office-map-plane="1"],
        #officeWorkspace [data-office-map-plane="1"] * {
            animation: none !important;
            backdrop-filter: none !important;
            box-shadow: none !important;
            filter: none !important;
            text-shadow: none !important;
            transition: none !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-draft-agent-id] {
            contain: layout style;
            overflow: visible !important;
            transition: transform 64ms linear, border-color 120ms ease !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-agent-overview="1"] {
            width: 62px !important;
            min-height: 62px !important;
            border-radius: 999px !important;
            background: var(--agent-primary) !important;
            outline: none;
            pointer-events: auto !important;
            transition: transform 140ms linear, outline-color 120ms ease !important;
        }
        #officeWorkspace [data-office-map-plane="1"] [data-office-agent-overview="1"] > span {
            display: none !important;
        }
    `;
    document.head.appendChild(style);
}

function officeEnsureDraftAgentMotionStyles() {
    if (document.getElementById('office-draft-agent-motion-styles')) return;
    const style = document.createElement('style');
    style.id = 'office-draft-agent-motion-styles';
    style.textContent = `
        @keyframes officeDraftAgentIdleBreath { 0%,100% { transform: translateY(0) scale(1.28); } 50% { transform: translateY(-3px) scale(1.29); } }
        @keyframes officeDraftAgentWalkBob { 0%,100% { transform: translateY(0) scale(1.28); } 50% { transform: translateY(-4px) scale(1.28); } }
        @keyframes officeDraftAgentLegWalkLeft { 0%,100% { transform: translateY(0) rotate(-8deg); } 50% { transform: translateY(1px) rotate(9deg); } }
        @keyframes officeDraftAgentLegWalkRight { 0%,100% { transform: translateY(1px) rotate(9deg); } 50% { transform: translateY(0) rotate(-8deg); } }
        @keyframes officeDraftAgentWorkTap { 0%,100% { transform: translateY(0) scale(1.28); filter: saturate(1); } 35% { transform: translateY(1px) scale(1.27); filter: saturate(1.25); } 70% { transform: translateY(-2px) scale(1.29); } }
        @keyframes officeDraftAgentDrinkSip { 0%,100% { transform: rotate(0deg) scale(1.28); } 42% { transform: rotate(-5deg) translateY(-4px) scale(1.28); } 60% { transform: rotate(3deg) scale(1.28); } }
        @keyframes officeDraftAgentSitSettle { 0%,100% { transform: translateY(9px) scale(1.14,0.92); } 50% { transform: translateY(6px) scale(1.16,0.9); } }
        @keyframes officeDraftAgentPauseLook { 0%,100% { transform: scale(1.28) rotate(0deg); } 45% { transform: scale(1.28) rotate(-3deg); } 70% { transform: scale(1.28) rotate(3deg); } }
        @keyframes officeDraftAgentTalkBounce { 0%,100% { transform: translateY(0) scale(1.28); } 30% { transform: translateY(-5px) scale(1.31); } 62% { transform: translateY(-2px) scale(1.29); } }
        @keyframes officeDraftAgentDragHover { 0%,100% { transform: translateY(-12px) scale(1.32) rotate(-2deg); } 50% { transform: translateY(-18px) scale(1.34) rotate(2deg); } }
        @keyframes officeDraftAgentDropPop { 0% { transform: translateY(-16px) scale(1.36); } 55% { transform: translateY(2px) scale(1.24); } 100% { transform: translateY(0) scale(1.28); } }
        @keyframes officeDraftAgentThinkGlow { 0%,100% { filter: drop-shadow(0 0 0 rgba(140,190,255,0)); transform: scale(1.28); } 50% { filter: drop-shadow(0 0 12px var(--agent-glow)); transform: scale(1.3); } }
        @keyframes officeDraftAgentCelebrate { 0%,100% { transform: translateY(0) scale(1.28) rotate(0deg); } 25% { transform: translateY(-9px) scale(1.31) rotate(-5deg); } 55% { transform: translateY(-4px) scale(1.3) rotate(5deg); } }
        @keyframes officeDraftAgentBubblePop { 0% { opacity:0; transform:translateX(0) translateY(6px) scale(.92); } 100% { opacity:1; transform:translateX(0) translateY(0) scale(1); } }
        [data-office-draft-agent-id] [data-office-draft-agent-robot] { animation: officeDraftAgentIdleBreath 2.8s ease-in-out infinite; }
        [data-office-agent-animation="walking"] [data-office-draft-agent-robot] { animation: officeDraftAgentWalkBob 0.92s ease-in-out infinite; }
        [data-office-agent-animation="walking"] .office-agent-leg-left { animation: officeDraftAgentLegWalkLeft 0.72s ease-in-out infinite; transform-origin:center top; }
        [data-office-agent-animation="walking"] .office-agent-leg-right { animation: officeDraftAgentLegWalkRight 0.72s ease-in-out infinite; transform-origin:center top; }
        [data-office-agent-animation="working"] [data-office-draft-agent-robot] { animation: officeDraftAgentWorkTap 0.82s ease-in-out infinite; }
        [data-office-agent-animation="drinking"] [data-office-draft-agent-robot] { animation: officeDraftAgentDrinkSip 1.35s ease-in-out infinite; }
        [data-office-agent-animation="sitting"] [data-office-draft-agent-robot] { animation: officeDraftAgentSitSettle 2.4s ease-in-out infinite; }
        [data-office-agent-animation="paused"] [data-office-draft-agent-robot] { animation: officeDraftAgentPauseLook 2.1s ease-in-out infinite; }
        [data-office-agent-animation="talking"] [data-office-draft-agent-robot] { animation: officeDraftAgentTalkBounce 0.72s ease-in-out infinite; }
        [data-office-agent-animation="dragging"] [data-office-draft-agent-robot] { animation: officeDraftAgentDragHover 0.75s ease-in-out infinite; }
        [data-office-agent-animation="dropped"] [data-office-draft-agent-robot] { animation: officeDraftAgentDropPop 0.52s cubic-bezier(.2,.9,.2,1.1) both; }
        [data-office-agent-animation="thinking"] [data-office-draft-agent-robot] { animation: officeDraftAgentThinkGlow 1.65s ease-in-out infinite; }
        [data-office-agent-animation="celebrating"] [data-office-draft-agent-robot] { animation: officeDraftAgentCelebrate 1s ease-in-out infinite; }
        [data-office-agent-animation="talking"] [data-office-draft-agent-bubble],
        [data-office-agent-animation="dropped"] [data-office-draft-agent-bubble] { animation: officeDraftAgentBubblePop 180ms ease-out both; }
    `;
    document.head.appendChild(style);
}

function officeDraftAgentClickLine(agent, space) {
    const room = safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label || 'the office');
    const lines = [
        `Paused in ${room}. What do you need?`,
        `I stopped here. I can take a task or move rooms.`,
        `I am listening from ${room}.`,
        `Ready. Send me a task or drag me somewhere else.`,
    ];
    return lines[officeStableHash(`${safeString(agent?.id)}|click`) % lines.length];
}

function officeDraftBuildAgentConversationPrompt(agent, space) {
    const agentName = safeString(agent?.name) || 'Agent';
    const roomName = safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label || 'the office');
    const specialty = safeString(agent?.specialty) || 'Generalist';
    const personality = safeString(agent?.personality) || 'Helpful, direct, and persistent.';
    const activeTask = officeState?.tasks?.find((entry) => (
        safeString(entry?.assignedAgentId) === safeString(agent?.id)
        && safeString(entry?.status) !== 'done'
    ));
    const memoryLine = safeString(activeTask?.title || agent?.lastOfficeActionMemory || agent?.lastMissionSummary || agent?.lastTaskSummary || 'No recent task yet.');
    const commandLine = officeDraftAgentCommandActive(agent)
        ? safeString(agent?.lastOfficeCommandSummary || 'Following the user office command.')
        : 'No direct office command active.';
    return [
        `You are speaking as the persistent Thomas office agent named ${agentName}.`,
        `Stay in character as this robot, not as generic Thomas.`,
        `Specialty: ${specialty}.`,
        `Personality: ${personality}.`,
        `Current office room: ${roomName}.`,
        `Recent task memory: ${memoryLine}.`,
        `Current office action: ${commandLine}.`,
        'This is the office conversation layer, separate from task routing. Reply as this agent in first person and keep the answer concise.',
    ].join('\n');
}

function officeDraftPrimeAgentConversation(agent, space, now = performance.now()) {
    if (!agent) return;
    const promptPrefix = officeDraftBuildAgentConversationPrompt(agent, space);
    agent.lastOfficeConversationPrompt = promptPrefix;
    agent.lastOfficeConversationAt = now;
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.chat_prompt', {
            agentId: safeString(agent.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
            prompt: promptPrefix,
        }, now);
    }
}

const OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES = Object.freeze([
    {
        id: 'coke',
        action: 'drink',
        propLabel: 'Coke',
        types: ['vending_machine', 'soda_crate', 'fridge'],
        interactions: ['vend', 'drink'],
        terms: ['coke', 'cola', 'soda', 'pop', 'vending', 'vending machine', 'coke machine', 'soda machine', 'drink machine'],
    },
    {
        id: 'coffee',
        action: 'drink',
        propLabel: 'coffee',
        types: ['coffee_bar', 'tea_station', 'water_cooler', 'fridge'],
        interactions: ['drink'],
        terms: ['coffee', 'tea', 'water', 'water cooler', 'drink station', 'coffee bar'],
    },
    {
        id: 'food',
        action: 'food',
        propLabel: 'snack',
        types: ['kitchen_island', 'fridge', 'microwave', 'snack_shelf', 'recipe_counter', 'snack_table'],
        interactions: ['food'],
        terms: ['food', 'snack', 'eat', 'recipe', 'cook', 'microwave', 'fridge', 'kitchen island', 'snack shelf', 'snack table'],
    },
    {
        id: 'seat',
        action: 'sit',
        propLabel: '',
        types: ['couch', 'loveseat', 'chair', 'meeting_chair', 'lounge_chair', 'bean_bag', 'bench', 'stool', 'ottoman'],
        interactions: ['sit'],
        terms: ['sit', 'seat', 'chair', 'couch', 'sofa', 'loveseat', 'lounge chair', 'bean bag', 'bench', 'stool'],
    },
    {
        id: 'work',
        action: 'work',
        propLabel: '</>',
        types: ['workstation', 'desk', 'standing_desk', 'code_terminal', 'dual_monitor', 'laptop', 'server_console', 'lab_bench'],
        interactions: ['work', 'monitor', 'tools'],
        terms: ['work', 'desk', 'computer', 'workstation', 'terminal', 'laptop', 'monitor', 'code', 'coding', 'build', 'debug', 'lab bench'],
    },
    {
        id: 'meeting',
        action: 'work',
        propLabel: 'meet',
        types: ['conference_table', 'round_table', 'whiteboard', 'kanban_board'],
        interactions: ['meet', 'present', 'plan'],
        terms: ['meeting', 'meet', 'sync', 'conference', 'conference table', 'round table', 'team table'],
    },
    {
        id: 'focus',
        action: 'work',
        propLabel: 'focus',
        types: ['focus_pod', 'standing_desk', 'desk', 'task_lamp'],
        interactions: ['focus', 'work'],
        terms: ['focus', 'focus pod', 'deep work', 'quiet pod', 'quiet room', 'concentrate', 'concentration'],
    },
    {
        id: 'print',
        action: 'print',
        propLabel: 'print',
        types: ['printer', 'copier', 'filing_cabinet', 'mail_sorter', 'mail_cart'],
        interactions: ['print', 'archive', 'sort'],
        terms: ['print', 'printer', 'copy', 'copier', 'file', 'filing cabinet', 'mail', 'mail sorter', 'mail cart'],
    },
    {
        id: 'support',
        action: 'work',
        propLabel: 'help',
        types: ['ticket_kiosk', 'dispatch_board', 'phone_booth', 'mail_sorter', 'printer', 'copier', 'desk'],
        interactions: ['dispatch', 'sort', 'print', 'work'],
        terms: ['support', 'ticket', 'ticket kiosk', 'help desk', 'customer', 'triage', 'dispatch board', 'phone booth', 'call'],
    },
    {
        id: 'charge',
        action: 'charge',
        propLabel: 'charge',
        types: ['charging_dock'],
        interactions: ['charge'],
        terms: ['charge', 'charging', 'charging dock', 'dock'],
    },
    {
        id: 'planning',
        action: 'work',
        propLabel: 'map',
        types: ['whiteboard', 'kanban_board', 'blueprint_table', 'sticky_note_wall', 'conference_table'],
        interactions: ['present', 'plan', 'meet'],
        terms: ['whiteboard', 'board', 'kanban', 'plan', 'planning', 'strategy', 'blueprint', 'conference table'],
    },
    {
        id: 'research',
        action: 'research',
        propLabel: 'doc',
        types: ['bookshelf', 'research_terminal', 'map_table', 'microscope', 'sample_tray', 'pinboard', 'data_wall'],
        interactions: ['research', 'archive'],
        terms: ['research', 'book', 'bookshelf', 'source', 'docs', 'document', 'microscope', 'map table', 'sample'],
    },
    {
        id: 'design',
        action: 'work',
        propLabel: 'ui',
        types: ['drafting_table', 'vr_headset', 'pinboard', 'whiteboard', 'side_table', 'monitor_stand'],
        interactions: ['design', 'present', 'decor'],
        terms: ['design', 'ui', 'ux', 'visual', 'drafting table', 'prototype', 'vr headset', 'mockup'],
    },
    {
        id: 'ops',
        action: 'monitor',
        propLabel: 'ops',
        types: ['server_rack', 'security_console', 'server_console', 'network_switch', 'router_node', 'firewall_box', 'power_panel', 'data_wall'],
        interactions: ['monitor', 'network'],
        terms: ['server', 'server rack', 'security console', 'console', 'network', 'router', 'firewall', 'power panel', 'ops', 'monitoring'],
    },
    {
        id: 'studio',
        action: 'record',
        propLabel: 'rec',
        types: ['camera_tripod', 'microphone', 'podcast_desk', 'sound_mixer', 'green_screen', 'light_panel', 'camera_case', 'prop_shelf'],
        interactions: ['record', 'content'],
        terms: ['camera', 'record', 'recording', 'microphone', 'mic', 'podcast', 'sound mixer', 'green screen', 'light panel', 'prop shelf'],
    },
    {
        id: 'game',
        action: 'play',
        propLabel: 'game',
        types: ['arcade_cabinet', 'game_console'],
        interactions: ['play'],
        terms: ['game', 'arcade', 'console', 'play'],
    },
]);

const OFFICE_DRAFT_AGENT_COMMAND_ROOM_ALIASES = Object.freeze({
    'room-planning': ['strategy room', 'planning room', 'planning hub', 'strategy', 'roadmap room', 'plan room'],
    'room-engineering': ['software lab', 'engineering', 'engineer room', 'code room', 'coding room', 'build room', 'debug room', 'lab'],
    'room-research': ['research bay', 'research room', 'library', 'docs room', 'source room'],
    'room-design': ['design loft', 'design room', 'ui room', 'ux room', 'product room', 'visual room'],
    'room-content': ['content studio', 'content room', 'studio', 'video room', 'media room'],
    'room-ops': ['ops command', 'ops room', 'operations room', 'deploy room', 'monitoring room', 'server room'],
    'room-support': ['support desk', 'support room', 'ticket room', 'customer room', 'help desk'],
    'room-coffee': ['cafeteria', 'cafe', 'coffee room', 'kitchen', 'break kitchen', 'vending room', 'coke room', 'snack room'],
    'room-break': ['lounge', 'break room', 'relax room', 'couch room', 'hangout room'],
    'room-pods': ['focus pods', 'focus room', 'pod room', 'deep work room', 'quiet room'],
    'room-lobby': ['lobby', 'main lobby', 'front desk', 'reception'],
});

function officeDraftNormalizeAgentCommandText(textRaw) {
    const text = safeString(textRaw)
        .toLowerCase()
        .replace(/['`]/g, '')
        .replace(/[^a-z0-9#]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    return text ? ` ${text} ` : '';
}

function officeDraftAgentCommandHasTerm(commandText, termRaw) {
    const term = officeDraftNormalizeAgentCommandText(termRaw).trim();
    if (!commandText || !term) return false;
    return commandText.includes(` ${term} `);
}

function officeDraftAgentCommandVerbPresent(commandText) {
    return /\b(go|walk|move|head|enter|visit|navigate|use|grab|get|fetch|take|bring|drink|sit|stand|work|focus|play|find|make|cook|eat|snack|print|copy|file|ship|sort|charge|monitor|check|record|film|shoot|read|research|inspect|look|open|join|meet|call|help|triage|dispatch|support)\b/.test(commandText);
}

function officeDraftAgentCommandRuleScore(rule, commandText) {
    let score = 0;
    (Array.isArray(rule?.terms) ? rule.terms : []).forEach((termRaw) => {
        const term = officeDraftNormalizeAgentCommandText(termRaw).trim();
        if (!term || !officeDraftAgentCommandHasTerm(commandText, term)) return;
        score += 100 + Math.min(60, term.length * 3);
    });
    return score;
}

function officeDraftAgentCommandRuleForText(commandText) {
    let best = null;
    OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES.forEach((rule, index) => {
        const score = officeDraftAgentCommandRuleScore(rule, commandText);
        if (score <= 0) return;
        if (!best || score > best.score || (score === best.score && index < best.index)) {
            best = { rule, score, index };
        }
    });
    return best?.rule || null;
}

function officeDraftAssetMatchesAgentCommandRule(asset, rule) {
    if (!asset || !rule) return false;
    const type = safeString(asset?.type);
    const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
    return (Array.isArray(rule.types) && rule.types.includes(type))
        || (Array.isArray(rule.interactions) && rule.interactions.includes(interaction));
}

function officeDraftInferCommandActionFromInteraction(interactionRaw) {
    const interaction = safeString(interactionRaw);
    return {
        archive: 'print',
        charge: 'charge',
        content: 'record',
        decor: 'move',
        design: 'work',
        dispatch: 'work',
        drink: 'drink',
        focus: 'work',
        food: 'food',
        meet: 'work',
        monitor: 'monitor',
        network: 'monitor',
        plan: 'work',
        play: 'play',
        present: 'work',
        print: 'print',
        record: 'record',
        research: 'research',
        sit: 'sit',
        sort: 'print',
        tools: 'work',
        vend: 'drink',
        work: 'work',
    }[interaction] || 'move';
}

function officeDraftCommandContainsAnyTerm(commandText, termsRaw = []) {
    return (Array.isArray(termsRaw) ? termsRaw : []).some((term) => officeDraftAgentCommandHasTerm(commandText, term));
}

function officeDraftCommandAssetTerms(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const terms = [
        safeString(descriptor?.label),
        type.replace(/_/g, ' '),
        safeString(descriptor?.category),
        safeString(descriptor?.interaction),
    ];
    const aliases = {
        arcade_cabinet: ['arcade machine'],
        coffee_bar: ['coffee counter'],
        conference_table: ['meeting table'],
        copier: ['copy machine'],
        camera_tripod: ['camera', 'video camera'],
        data_wall: ['dashboard wall', 'metrics wall'],
        dispatch_board: ['ticket board', 'support board'],
        focus_pod: ['pod', 'quiet pod', 'deep work pod', 'focus booth'],
        game_console: ['game system'],
        green_screen: ['backdrop', 'recording backdrop'],
        kitchen_island: ['kitchen counter'],
        lab_bench: ['test bench'],
        loveseat: ['small couch', 'sofa'],
        map_table: ['research table'],
        microphone: ['mic', 'recording mic'],
        microwave: ['microwave oven'],
        monitor_stand: ['monitor'],
        network_switch: ['network box', 'switch'],
        package_station: ['package counter', 'shipping station'],
        phone_booth: ['phone room', 'call booth'],
        podcast_desk: ['recording desk'],
        reception_counter: ['front desk', 'reception desk'],
        recipe_counter: ['recipe station'],
        research_terminal: ['research computer'],
        security_console: ['security desk'],
        snack_shelf: ['snacks', 'snack rack'],
        soda_crate: ['coke crate', 'soda box'],
        standing_desk: ['standing table'],
        sticky_note_wall: ['sticky notes', 'notes wall'],
        tablet_stand: ['tablet'],
        testing_rig: ['test rig', 'qa rig'],
        ticket_kiosk: ['ticket terminal', 'ticket station'],
        vending_machine: ['coke machine', 'soda machine', 'drink machine'],
        wall_monitor: ['screen', 'display'],
        water_cooler: ['water station'],
        whiteboard: ['board'],
        workstation: ['computer', 'monitor', 'coding station'],
    };
    (aliases[type] || []).forEach((term) => terms.push(term));
    return [...new Set(terms.map((term) => safeString(term)).filter(Boolean))];
}

function officeDraftAssetMatchesCommandText(asset, commandText) {
    return officeDraftCommandAssetTerms(asset).some((term) => officeDraftAgentCommandHasTerm(commandText, term));
}

function officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch = false) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const typeIndex = Array.isArray(rule?.types) ? rule.types.indexOf(type) : -1;
    let score = 800 - (Math.max(0, Number(spaceIndex) || 0) * 24);
    if (typeIndex >= 0) score += Math.max(0, 220 - (typeIndex * 26));
    if (officeDraftAgentCommandHasTerm(commandText, safeString(descriptor?.label))) score += 190;
    if (officeDraftAgentCommandHasTerm(commandText, type.replace(/_/g, ' '))) score += 150;
    if (officeDraftAgentCommandHasTerm(commandText, safeString(space?.name))) score += 60;
    if (officeDraftCommandContainsAnyTerm(commandText, officeDraftCommandRoomAliases(space))) score += 120;
    if (officeDraftCommandContainsAnyTerm(commandText, officeDraftCommandAssetTerms(asset))) score += 90;
    if (labelMatch) score += 360;
    return score;
}

function officeDraftUniqueCommandSpaces(spacesRaw) {
    const spaces = [];
    const seen = new Set();
    (Array.isArray(spacesRaw) ? spacesRaw : []).forEach((space) => {
        const spaceId = safeString(space?.id);
        if (!spaceId || seen.has(spaceId)) return;
        seen.add(spaceId);
        spaces.push(space);
    });
    return spaces;
}

function officeDraftCommandRoomAliases(space) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const room = officeRoomById(roomId);
    const terms = [
        safeString(space?.name),
        safeString(space?.id).replace(/-/g, ' '),
        roomId.replace(/^room-/, '').replace(/-/g, ' '),
        safeString(room?.label),
        safeString(room?.theme),
    ];
    (OFFICE_DRAFT_AGENT_COMMAND_ROOM_ALIASES[roomId] || []).forEach((term) => terms.push(term));
    return terms.filter(Boolean);
}

function officeDraftFindCommandTargetRoom(commandText, agent) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    if (!spaces.length) return null;
    if (officeDraftAgentCommandHasTerm(commandText, 'this room')
        || officeDraftAgentCommandHasTerm(commandText, 'current room')
        || officeDraftAgentCommandHasTerm(commandText, 'here')) {
        const selected = officeDraftSpaceForAgent(agent) || officeDraftFindSpace(state.selectedSpaceId);
        if (selected) return { space: selected, label: safeString(selected.name || 'this room'), score: 1000 };
    }
    let best = null;
    spaces.forEach((space) => {
        let score = 0;
        officeDraftCommandRoomAliases(space).forEach((term) => {
            if (!officeDraftAgentCommandHasTerm(commandText, term)) return;
            score = Math.max(score, 120 + Math.min(80, term.length * 2));
        });
        if (score <= 0) return;
        if (!best || score > best.score) {
            best = { space, label: safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label), score };
        }
    });
    return best;
}

function officeDraftFindCommandTargetAsset(commandText, agent, roomMatch = null) {
    const rule = officeDraftAgentCommandRuleForText(commandText);
    const state = officeEnsureDraftMapState();
    const selectedSpace = officeDraftFindSpace(state.selectedSpaceId);
    const currentSpace = officeDraftSpaceForAgent(agent);
    const spaces = officeDraftUniqueCommandSpaces([
        roomMatch?.space,
        selectedSpace,
        currentSpace,
        ...(Array.isArray(state?.spaces) ? state.spaces : []),
    ]);
    let best = null;
    spaces.forEach((space, spaceIndex) => {
        (Array.isArray(space?.assets) ? space.assets : []).forEach((asset) => {
            const explicitMatch = rule && officeDraftAssetMatchesAgentCommandRule(asset, rule);
            const labelMatch = officeDraftAssetMatchesCommandText(asset, commandText);
            if (!explicitMatch && !labelMatch) return;
            const type = safeString(asset?.type);
            const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
            const interaction = safeString(descriptor?.interaction);
            const action = safeString(rule?.action) || officeDraftInferCommandActionFromInteraction(interaction);
            const score = officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch);
            if (!best || score > best.score) {
                best = {
                    asset,
                    space,
                    rule,
                    action: safeString(action || 'move'),
                    propLabel: safeString(rule?.propLabel),
                    score,
                };
            }
        });
    });
    return best;
}

function officeDraftSetAgentCommandTarget(agent, space, targetWorld, options = {}) {
    if (!agent || !space || !targetWorld) return null;
    const now = performance.now();
    const roomId = officeDraftNormalizeRoomId(space.roomId, space.id);
    const action = safeString(options.action || 'move') || 'move';
    agent.remoteRoomId = roomId;
    agent.draftPinnedRoomId = roomId;
    agent.draftPinnedTaskId = safeString(agent.taskId);
    agent.draftPinnedLocalX = Math.round(Number(targetWorld.x) - (Number(space.x) || 0));
    agent.draftPinnedLocalY = Math.round(Number(targetWorld.y) - (Number(space.y) || 0));
    agent.draftCommandAssetId = safeString(options.assetId);
    agent.draftCommandAssetType = safeString(options.assetType);
    agent.draftCommandPropLabel = safeString(options.propLabel);
    agent.draftInteractionIntent = action;
    agent.draftCommandUntil = now + 70000;
    agent.draftCommandCompletedAt = 0;
    agent.draftCommandCompletionKey = '';
    agent.draftManualPinUntil = 0;
    agent.draftWanderRoomId = '';
    agent.draftWanderSpaceId = '';
    agent.draftWanderNextAt = 0;
    agent.draftWanderArrivedAt = 0;
    agent.lastOfficeCommandSummary = safeString(options.summary || `Going to ${safeString(space.name) || 'that room'}.`).slice(0, 180);
    agent.draftPausedUntil = 0;
    agent.draftDropUntil = 0;
    agent.state = 'walking';
    agent.intent = ['drink', 'food', 'sit', 'play'].includes(action)
        ? 'break'
        : (['work', 'research', 'print', 'charge', 'monitor', 'record'].includes(action) ? 'task' : 'wander');
    delete agent.draftTargetPointCache;
    delete agent.draftFallbackTargetCache;
    const motion = officeDraftEnsureAgentMotion(agent, space, 0, 1, null, now);
    if (motion) {
        motion.route = [];
        motion.routeIndex = 0;
        motion.targetSignature = '';
        motion.targetX = Math.round(Number(targetWorld.x) || 0);
        motion.targetY = Math.round(Number(targetWorld.y) || 0);
        motion.needsReplan = true;
        motion.dragging = false;
        motion.routeRetryAfter = 0;
        motion.lastProgressAt = now;
        motion.lastAt = now;
    }
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.office_command', {
            agentId: safeString(agent.id),
            roomId,
            spaceId: safeString(space.id),
            assetId: safeString(options.assetId),
            assetType: safeString(options.assetType),
            action,
            summary: agent.lastOfficeCommandSummary,
        }, now);
    }
    return {
        roomId,
        spaceId: safeString(space.id),
        assetId: safeString(options.assetId),
        assetType: safeString(options.assetType),
        action,
        summary: agent.lastOfficeCommandSummary,
    };
}

function officeDraftAgentCommandCompletionKey(agent) {
    if (!agent) return '';
    return [
        safeString(agent.id),
        safeString(agent.draftCommandAssetId),
        safeString(agent.draftCommandAssetType),
        safeString(agent.draftPinnedRoomId),
        Math.round(Number(agent.draftPinnedLocalX) || 0),
        Math.round(Number(agent.draftPinnedLocalY) || 0),
        safeString(agent.draftInteractionIntent),
    ].join('|');
}

function officeDraftAgentCommandRouteActive(agent) {
    const route = Array.isArray(agent?.draftMotion?.route) ? agent.draftMotion.route : [];
    return route.length > 0 && Number(agent?.draftMotion?.routeIndex) < route.length;
}

function officeDraftAgentCommandArrived(agent) {
    if (!officeDraftAgentCommandActive(agent)) return false;
    const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
    if (!motion) return false;
    const targetX = Number(motion.targetX);
    const targetY = Number(motion.targetY);
    const x = Number(motion.x);
    const y = Number(motion.y);
    if (!Number.isFinite(targetX) || !Number.isFinite(targetY) || !Number.isFinite(x) || !Number.isFinite(y)) return false;
    const arrived = Math.hypot(x - targetX, y - targetY) <= Math.max(OFFICE_DRAFT_AGENT_ROUTE_EPSILON * 2, 18);
    if (arrived) return true;
    if (officeDraftAgentCommandRouteActive(agent)) return false;
    return false;
}

function officeDraftPushAgentOfficeMemory(agent, entryRaw = {}) {
    if (!agent) return;
    const now = Number(entryRaw.at) || Date.now();
    const entry = {
        at: now,
        action: safeString(entryRaw.action || agent.draftInteractionIntent || 'move'),
        roomId: safeString(entryRaw.roomId || agent.draftPinnedRoomId),
        assetId: safeString(entryRaw.assetId || agent.draftCommandAssetId),
        assetType: safeString(entryRaw.assetType || agent.draftCommandAssetType),
        summary: safeString(entryRaw.summary || agent.lastOfficeCommandSummary || 'Completed an office action.').slice(0, 180),
    };
    const history = Array.isArray(agent.officeActionHistory) ? agent.officeActionHistory : [];
    const last = history[history.length - 1] || null;
    if (last && safeString(last.summary) === entry.summary && safeString(last.assetId) === entry.assetId) {
        last.at = now;
        agent.officeActionHistory = history.slice(-8);
    } else {
        agent.officeActionHistory = [...history.slice(-7), entry];
    }
    agent.lastOfficeActionMemory = entry.summary;
}

function officeDraftAgentCommandVerb(agent, actionRaw) {
    const action = safeString(actionRaw || agent?.draftInteractionIntent || 'move');
    const prop = safeString(agent?.draftCommandPropLabel);
    const grabbed = (labelRaw, fallbackRaw) => {
        const label = safeString(labelRaw || fallbackRaw);
        if (!label) return 'grabbed something';
        if (/^(coffee|tea|water)$/i.test(label)) return `grabbed ${label}`;
        if (/^(a|an|the)\s+/i.test(label)) return `grabbed ${label}`;
        return `grabbed a ${label}`;
    };
    if (action === 'drink') return `${grabbed(prop, 'drink')} at`;
    if (action === 'food') return `${grabbed(prop, 'snack')} at`;
    if (action === 'sit') return 'sat down near';
    if (action === 'play') return 'started playing at';
    if (action === 'research') return 'started researching at';
    if (action === 'print') return 'used';
    if (action === 'charge') return 'plugged into';
    if (action === 'monitor') return 'checked';
    if (action === 'record') return 'started recording at';
    if (action === 'work') return 'started working at';
    return 'arrived at';
}

function officeDraftMaybeCompleteAgentCommand(agent, now = performance.now()) {
    if (!agent || !officeDraftAgentCommandArrived(agent)) return false;
    const completionKey = officeDraftAgentCommandCompletionKey(agent);
    if (!completionKey || safeString(agent.draftCommandCompletionKey) === completionKey) return true;
    const action = safeString(agent.draftInteractionIntent || 'move') || 'move';
    const space = officeDraftSpaceForAgent(agent);
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id || agent.draftPinnedRoomId);
    const assetLabel = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(agent.draftCommandAssetType)]?.label || agent.draftCommandAssetType).replace(/_/g, ' ');
    const roomLabel = safeString(space?.name || officeRoomById(roomId)?.label || 'the office');
    const verb = officeDraftAgentCommandVerb(agent, action);
    const summary = assetLabel
        ? `${safeString(agent.name) || 'Agent'} ${verb} the ${assetLabel} in ${roomLabel}.`
        : `${safeString(agent.name) || 'Agent'} arrived in ${roomLabel}.`;
    agent.draftCommandCompletedAt = Number(now) || performance.now();
    agent.draftCommandCompletionKey = completionKey;
    agent.lastOfficeCommandSummary = summary;
    agent.draftCommandUntil = Math.max(Number(agent.draftCommandUntil) || 0, (Number(now) || performance.now()) + 28000);
    if (action === 'drink' || action === 'food' || action === 'sit' || action === 'play') {
        agent.state = 'break';
        agent.intent = 'break';
        agent.breakUntil = (Number(now) || performance.now()) + 24000;
    } else if (['work', 'research', 'print', 'charge', 'monitor', 'record'].includes(action)) {
        agent.state = 'working';
        agent.intent = 'task';
        agent.workUntil = (Number(now) || performance.now()) + 26000;
    } else {
        agent.state = 'idle';
        agent.intent = 'wander';
    }
    officeDraftPushAgentOfficeMemory(agent, {
        at: Date.now(),
        action,
        roomId,
        assetId: safeString(agent.draftCommandAssetId),
        assetType: safeString(agent.draftCommandAssetType),
        summary,
    });
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.office_command_complete', {
            agentId: safeString(agent.id),
            roomId,
            assetId: safeString(agent.draftCommandAssetId),
            assetType: safeString(agent.draftCommandAssetType),
            action,
            summary,
        }, Number(now) || performance.now());
    }
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(Number(now) || performance.now(), { force: true });
    }
    return true;
}

function officeDraftApplyAgentChatCommand(agent, textRaw) {
    if (!agent) return null;
    const commandText = officeDraftNormalizeAgentCommandText(textRaw);
    if (!commandText || !officeDraftAgentCommandVerbPresent(commandText)) return null;
    const roomMatch = officeDraftFindCommandTargetRoom(commandText, agent);
    const assetMatch = officeDraftFindCommandTargetAsset(commandText, agent, roomMatch);
    let targetSpace = assetMatch?.space || roomMatch?.space || null;
    let targetAsset = assetMatch?.asset || null;
    let action = safeString(assetMatch?.action || 'move') || 'move';
    let propLabel = safeString(assetMatch?.propLabel);
    if (!targetSpace) return null;
    if (!targetAsset && roomMatch?.space) {
        targetAsset = officeDraftPrimaryInteractionAsset(targetSpace, agent);
        if (targetAsset) {
            const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset.type)]?.interaction);
            const inferredAction = officeDraftInferCommandActionFromInteraction(interaction);
            if (inferredAction) action = inferredAction;
        }
    }
    const seed = officeStableHash(`${safeString(agent.id)}|${commandText}|${safeString(targetAsset?.id)}`);
    const targetWorld = targetAsset
        ? officeDraftChooseAssetApproachPoint(targetSpace, agent, targetAsset, seed, { routeAware: true })
        : officeDraftFallbackAgentTargetWorldPoint(targetSpace, agent, 0, 1);
    if (!targetWorld) return null;
    const assetLabel = safeString(OFFICE_DRAFT_ASSET_LIBRARY[safeString(targetAsset?.type)]?.label);
    const roomLabel = safeString(targetSpace.name || officeRoomById(officeDraftNormalizeRoomId(targetSpace.roomId, targetSpace.id))?.label || 'that room');
    const summary = targetAsset
        ? `${safeString(agent.name) || 'Agent'} is going to the ${assetLabel || 'target'} in ${roomLabel}.`
        : `${safeString(agent.name) || 'Agent'} is going to ${roomLabel}.`;
    const result = officeDraftSetAgentCommandTarget(agent, targetSpace, targetWorld, {
        action,
        propLabel: propLabel || (action === 'drink' ? 'Coke' : ''),
        assetId: safeString(targetAsset?.id),
        assetType: safeString(targetAsset?.type),
        summary,
    });
    agent.lastOfficeChatCommand = result;
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(performance.now(), { force: true });
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-chat-command' });
    return result;
}

function officeDraftPauseAgentForUser(agent, space, now = performance.now()) {
    if (!agent) return;
    const motion = officeDraftEnsureAgentMotion(agent, space, 0, 1, null, now);
    motion.route = [];
    motion.routeIndex = 0;
    motion.dragging = false;
    motion.needsReplan = false;
    agent.draftPausedUntil = now + 6500;
    agent.draftClickedAt = now;
    agent.draftInteractionIntent = 'talk';
    if (typeof officeBusEmit === 'function') {
        officeBusEmit('agent.draft_click', {
            agentId: safeString(agent.id),
            roomId: officeDraftNormalizeRoomId(space?.roomId, space?.id),
        }, now);
    }
    officeDraftPrimeAgentConversation(agent, space, now);
}

function officeDraftHandleAgentClick(event, agentId) {
    const state = officeEnsureDraftMapState();
    if ((Number(state.suppressAgentClickUntil) || 0) > performance.now()) return;
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    officeState.selectedAgentId = agent.id;
    state.expandedRosterAgentId = agent.id;
    officeDraftPauseAgentForUser(agent, space, performance.now());
    officeDraftOpenAgentChat(agent.id, { prime: false });
    officeSyncCustomizerFields();
    officePersistAgentPrefs();
    if (typeof officePersistRuntimeState === 'function') {
        officePersistRuntimeState(performance.now(), { force: true });
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-click' });
}

function officeDraftAgentMotionForDrag(agent, space, now = performance.now()) {
    const targetAsset = officeDraftPrimaryInteractionAsset(space, agent);
    return officeDraftEnsureAgentMotion(agent, space, 0, 1, targetAsset, now);
}

function officeDraftRenderSingleAgentElement(agent, stateRaw = null, now = performance.now(), renderSource = 'single-agent') {
    if (!agent || !officeState) return;
    const state = stateRaw || officeEnsureDraftMapState();
    const layer = officeScene?.querySelector('[data-office-draft-agent-layer="global"]');
    if (!(layer instanceof HTMLElement)) return;
    const assignments = officeDraftAgentAssignmentMap(state);
    const fallbackSpace = (Array.isArray(state?.spaces) ? state.spaces : []).find((space) => safeString(space?.id) === 'lobby')
        || (Array.isArray(state?.spaces) ? state.spaces[0] : null)
        || null;
    const space = officeDraftSpaceForAgent(agent) || fallbackSpace;
    if (!space) return;
    const group = assignments.get(safeString(space.id)) || [agent];
    const index = Math.max(0, group.findIndex((entry) => safeString(entry?.id) === safeString(agent?.id)));
    const elementMap = officeDraftLayerElementMap(layer);
    let el = elementMap.get(safeString(agent.id));
    if (!(el instanceof HTMLElement) || !layer.contains(el)) {
        el = officeDraftCreateAgentElement(space, agent, index, group.length || 1, state, { skipInitialUpdate: true });
        el.dataset.officeDraftAgentGlobal = '1';
        elementMap.set(safeString(agent.id), el);
        layer.appendChild(el);
    }
    el.dataset.officeDraftSpaceId = safeString(space.id);
    officeDraftUpdateAgentElement(el, space, agent, index, group.length || 1, state, now);
    state.agentLayerRenderSources = state.agentLayerRenderSources && typeof state.agentLayerRenderSources === 'object'
        ? state.agentLayerRenderSources
        : {};
    const source = safeString(renderSource) || 'single-agent';
    state.agentLayerRenderSources[source] = (Number(state.agentLayerRenderSources[source]) || 0) + 1;
}

function officeDraftHandleAgentPointerDown(event, agentId) {
    if (!(officeSceneWrap instanceof HTMLElement) || !officeState) return;
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== null) return true;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const motion = officeDraftAgentMotionForDrag(agent, space, performance.now());
    const world = officeDraftMapClientToWorld(event.clientX, event.clientY);
    if (!world) return;
    event.preventDefault();
    event.stopPropagation();
    state.agentPointerId = event.pointerId;
    state.agentDragAgentId = agent.id;
    state.agentDragStartClientX = event.clientX;
    state.agentDragStartClientY = event.clientY;
    state.agentDragOffsetX = world.x - (Number(motion.x) || world.x);
    state.agentDragOffsetY = world.y - (Number(motion.y) || world.y);
    state.agentDragActive = false;
    state.lastInputMode = 'agent';
    state.agentLayerQuietUntil = 0;
    officeState.selectedAgentId = agent.id;
    state.expandedRosterAgentId = agent.id;
    if (officeSceneWrap instanceof HTMLElement && typeof officeSceneWrap.setPointerCapture === 'function') {
        officeSceneWrap.setPointerCapture(event.pointerId);
    } else if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    return true;
}

function officeDraftClampAgentDropPointToSpace(worldPoint, space) {
    const rect = officeDraftSpaceRect(space);
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(Number(worldPoint?.x) || rect.centerX, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(Number(worldPoint?.y) || rect.centerY, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftClampAgentDragPoint(worldPoint, fallbackSpace = null) {
    const bounded = {
        x: Math.round(officeClamp(Number(worldPoint?.x) || 0, 80, OFFICE_DRAFT_MAP_SIZE - 140)),
        y: Math.round(officeClamp(Number(worldPoint?.y) || 0, 92, OFFICE_DRAFT_MAP_SIZE - 170)),
    };
    const space = officeDraftSpaceAtWorldPoint(bounded.x, bounded.y) || fallbackSpace;
    if (space) return officeDraftClampAgentDropPointToSpace(bounded, space);
    const snapped = officeDraftNearestHallwayPoint(bounded, officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces));
    return { x: Math.round(snapped.x), y: Math.round(snapped.y) };
}

function officeDraftHandleAgentPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== event.pointerId || !safeString(state.agentDragAgentId)) return false;
    const agent = officeGetAgentById(state.agentDragAgentId);
    if (!agent) return true;
    const world = officeDraftMapClientToWorld(event.clientX, event.clientY);
    if (!world) return true;
    const moved = Math.hypot(event.clientX - state.agentDragStartClientX, event.clientY - state.agentDragStartClientY);
    if (moved > 7) {
        state.agentDragActive = true;
    }
    if (!state.agentDragActive) return true;
    event.preventDefault();
    event.stopPropagation();
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const motion = officeDraftAgentMotionForDrag(agent, space, performance.now());
    const dragPoint = officeDraftClampAgentDragPoint({
        x: world.x - (Number(state.agentDragOffsetX) || 0),
        y: world.y - (Number(state.agentDragOffsetY) || 0),
    }, space);
    motion.dragging = true;
    motion.route = [];
    motion.routeIndex = 0;
    motion.targetSignature = '';
    motion.targetX = dragPoint.x;
    motion.targetY = dragPoint.y;
    motion.x = dragPoint.x;
    motion.y = dragPoint.y;
    motion.needsReplan = false;
    agent.draftPausedUntil = 0;
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grabbing';
    }
    officeDraftRenderSingleAgentElement(agent, state, performance.now(), 'agent-drag');
    return true;
}

function officeDraftHandleAgentPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.agentPointerId !== event.pointerId || !safeString(state.agentDragAgentId)) return false;
    const agent = officeGetAgentById(state.agentDragAgentId);
    const wasDragging = Boolean(state.agentDragActive);
    if (officeSceneWrap instanceof HTMLElement && typeof officeSceneWrap.hasPointerCapture === 'function' && officeSceneWrap.hasPointerCapture(event.pointerId)) {
        officeSceneWrap.releasePointerCapture(event.pointerId);
    } else if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (agent) {
        const now = performance.now();
        const currentSpace = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
        const motion = officeDraftAgentMotionForDrag(agent, currentSpace, now);
        motion.dragging = false;
        if (wasDragging) {
            const world = officeDraftMapClientToWorld(event.clientX, event.clientY) || { x: motion.x, y: motion.y };
            const dropSpace = officeDraftSpaceAtWorldPoint(world.x, world.y);
            if (dropSpace) {
                const dropPoint = officeDraftClampAgentDropPointToSpace(world, dropSpace);
                const roomId = officeDraftNormalizeRoomId(dropSpace.roomId, dropSpace.id);
                agent.remoteRoomId = roomId;
                agent.draftPinnedRoomId = roomId;
                agent.draftPinnedTaskId = safeString(agent.taskId);
                agent.draftPinnedLocalX = Math.round(dropPoint.x - (Number(dropSpace.x) || 0));
                agent.draftPinnedLocalY = Math.round(dropPoint.y - (Number(dropSpace.y) || 0));
                agent.draftManualPinUntil = now + OFFICE_DRAFT_AGENT_MANUAL_PIN_MS;
                agent.draftWanderRoomId = '';
                agent.draftWanderSpaceId = '';
                agent.draftWanderNextAt = 0;
                agent.draftWanderArrivedAt = 0;
                agent.draftDropUntil = now + 1250;
                agent.draftPausedUntil = now + 900;
                motion.x = dropPoint.x;
                motion.y = dropPoint.y;
                motion.route = [];
                motion.routeIndex = 0;
                motion.targetSignature = officeDraftAgentTargetSignature(dropSpace, agent, dropPoint, null);
                motion.targetX = dropPoint.x;
                motion.targetY = dropPoint.y;
                motion.needsReplan = false;
                agent.draftLastSpaceId = safeString(dropSpace.id);
                if (typeof officeSpeak === 'function') {
                    officeSpeak(agent, `Placed in ${safeString(dropSpace.name) || 'this room'}.`, { priority: true, durationMs: 1800 });
                }
                if (typeof officeBusEmit === 'function') {
                    officeBusEmit('agent.draft_drop', {
                        agentId: safeString(agent.id),
                        roomId,
                        spaceId: safeString(dropSpace.id),
                    }, now);
                }
            } else {
                const snapped = officeDraftNearestHallwayPoint(world, officeDraftAutoHallwayNetwork(state.spaces));
                motion.x = snapped.x;
                motion.y = snapped.y;
                motion.route = [];
                motion.routeIndex = 0;
                motion.targetSignature = `hall:${snapped.x},${snapped.y}`;
                motion.targetX = snapped.x;
                motion.targetY = snapped.y;
                motion.needsReplan = false;
                agent.draftManualPinUntil = now + OFFICE_DRAFT_AGENT_MANUAL_PIN_MS;
                agent.draftWanderRoomId = '';
                agent.draftWanderSpaceId = '';
                agent.draftWanderNextAt = 0;
                agent.draftWanderArrivedAt = 0;
                agent.draftPausedUntil = now + 900;
            }
            state.suppressAgentClickUntil = now + 360;
            if (typeof officePersistRuntimeState === 'function') {
                officePersistRuntimeState(now, { force: true });
            }
        }
    }
    state.agentPointerId = null;
    state.agentDragAgentId = '';
    state.agentDragActive = false;
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grab';
    }
    if (wasDragging) {
        event.preventDefault();
        event.stopPropagation();
        officeDraftRenderSingleAgentElement(agent, state, performance.now(), 'agent-drop');
        officeRenderDraftMapMinimapThrottled(true);
        window.setTimeout(() => {
            officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-drop-settle' });
        }, Math.max(120, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS * 2));
    } else if (agent) {
        event.preventDefault();
        event.stopPropagation();
        officeDraftHandleAgentClick(event, safeString(agent.id));
        state.suppressAgentClickUntil = performance.now() + 320;
    }
    return true;
}

function officeDraftCreateAgentElement(space, agent, index, total, state, options = {}) {
    officeEnsureDraftAgentMotionStyles();
    const palette = officeAgentPalette(agent);
    const el = document.createElement('button');
    el.type = 'button';
    el.dataset.officeDraftAgentId = safeString(agent?.id);
    el.setAttribute('aria-label', `${safeString(agent?.name) || 'Agent'} office agent`);
    el.style.position = 'absolute';
    el.style.left = '0';
    el.style.top = '0';
    el.style.width = `${OFFICE_DRAFT_AGENT_HITBOX_W}px`;
    el.style.minHeight = `${OFFICE_DRAFT_AGENT_HITBOX_H}px`;
    el.style.borderRadius = '16px';
    el.style.border = '0';
    el.style.outline = 'none';
    el.style.appearance = 'none';
    el.style.webkitAppearance = 'none';
    el.style.background = 'transparent';
    el.style.color = 'rgba(242,246,252,0.94)';
    el.style.cursor = 'pointer';
    el.style.padding = '0';
    el.style.pointerEvents = 'auto';
    el.style.touchAction = 'none';
    el.style.overflow = 'visible';
    el.style.transition = 'transform 64ms linear, border-color 160ms ease';
    el.style.willChange = 'transform';
    el.style.setProperty('--agent-primary', palette.primary);
    el.style.setProperty('--agent-secondary', palette.secondary);
    el.style.setProperty('--agent-glow', palette.glow);
    el.innerHTML = `
        <span data-office-draft-agent-name="1" style="position:absolute;z-index:3;left:50%;top:2px;display:none;box-sizing:border-box;max-width:112px;transform:translateX(-50%);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0;border:0;background:transparent;font-size:0.56rem;font-weight:900;line-height:1;color:rgba(246,249,255,0.96);text-shadow:0 2px 6px rgba(0,0,0,0.66);pointer-events:none;"></span>
        <span data-office-draft-agent-bubble="1" style="position:absolute;z-index:4;left:136px;right:auto;top:42px;display:none;box-sizing:border-box;min-width:94px;width:max-content;max-width:172px;transform:none;padding:7px 9px;border-radius:9px;background:rgba(6,12,22,0.94);border:1px solid rgba(154,188,235,0.34);box-shadow:0 8px 18px rgba(0,0,0,0.18);font-size:0.58rem;line-height:1.22;color:rgba(238,244,252,0.94);text-align:left;white-space:normal;overflow-wrap:break-word;pointer-events:none;"></span>
        <span data-office-draft-agent-robot="1" style="position:relative;z-index:2;display:flex;align-items:flex-start;justify-content:center;width:96px;height:106px;margin:20px auto 0;transform-origin:center bottom;">
            ${officePixelAgentMarkup('', `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`)}
        </span>
        <span data-office-draft-agent-prop="1" style="position:absolute;right:10px;top:58px;display:none;align-items:center;justify-content:center;min-width:24px;height:16px;padding:0 4px;border-radius:7px;background:rgba(7,12,22,0.78);border:1px solid rgba(238,246,255,0.2);box-shadow:0 5px 10px rgba(0,0,0,0.18);font-size:0.48rem;font-weight:900;line-height:1;color:rgba(242,248,255,0.9);letter-spacing:0;text-transform:uppercase;"></span>
        <span data-office-draft-agent-status="1" style="display:none;margin:3px auto 0;width:max-content;max-width:100px;padding:2px 6px;border-radius:999px;background:rgba(5,10,18,0.58);border:1px solid rgba(160,190,232,0.18);font-size:0.54rem;color:rgba(212,225,244,0.78);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
        <span data-office-draft-agent-can="1" style="position:absolute;left:92px;top:70px;display:none;align-items:center;justify-content:center;box-sizing:border-box;width:38px;height:25px;padding:0 5px;border-radius:8px;background:linear-gradient(180deg, #ff5b58, #981f2d);border:2px solid rgba(255,239,214,0.92);color:rgba(255,244,230,0.98);font-size:0.48rem;font-weight:900;line-height:1;letter-spacing:0;text-transform:uppercase;box-shadow:0 7px 12px rgba(0,0,0,0.26), inset 0 2px 0 rgba(255,255,255,0.22);transform:rotate(-7deg);">Coke</span>
    `;
    if (options?.skipInitialUpdate !== true) {
        officeDraftUpdateAgentElement(el, space, agent, index, total, state, performance.now());
    }
    el.addEventListener('pointerenter', () => {
        const currentState = officeEnsureDraftMapState();
        currentState.hoveredAgentId = safeString(agent?.id);
        window.clearTimeout(currentState.agentHoverRenderTimer);
        currentState.agentHoverRenderTimer = window.setTimeout(() => {
            if (!officeDraftAgentRenderQuietActive(currentState, performance.now())) {
                officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'hover-enter' });
            }
        }, 140);
    });
    el.addEventListener('pointerleave', () => {
        const currentState = officeEnsureDraftMapState();
        if (safeString(currentState.hoveredAgentId) === safeString(agent?.id)) {
            currentState.hoveredAgentId = '';
            window.clearTimeout(currentState.agentHoverRenderTimer);
            currentState.agentHoverRenderTimer = 0;
        }
    });
    el.addEventListener('pointerdown', (event) => {
        officeDraftHandleAgentPointerDown(event, safeString(agent?.id));
    });
    el.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        officeDraftHandleAgentClick(event, safeString(agent?.id));
    });
    return el;
}

function officeDraftSetDatasetValue(el, key, value) {
    if (!(el instanceof HTMLElement) || !key) return;
    const next = safeString(value);
    if (el.dataset[key] !== next) el.dataset[key] = next;
}

function officeDraftSetStyleValue(el, prop, value) {
    if (!(el instanceof HTMLElement) || !prop) return;
    const next = safeString(value);
    if (el.style[prop] !== next) el.style[prop] = next;
}

function officeDraftSetCssVariable(el, name, value) {
    if (!(el instanceof HTMLElement) || !name) return;
    const next = safeString(value);
    if (el.style.getPropertyValue(name) !== next) el.style.setProperty(name, next);
}

function officeDraftUpdateAgentElement(el, space, agent, index, total, state, now = performance.now()) {
    if (!(el instanceof HTMLElement) || !agent) return;
    const placement = officeDraftAgentPlacement(space, agent, index, total, now);
    const palette = officeAgentPalette(agent);
    const selected = safeString(state.expandedRosterAgentId || officeState?.selectedAgentId) === safeString(agent?.id);
    const globalLayer = el.dataset.officeDraftAgentGlobal === '1';
    const offsetX = globalLayer ? (Number(space?.x) || 0) : 0;
    const offsetY = globalLayer ? (Number(space?.y) || 0) : 0;
    const overviewAgent = officeDraftOverviewMode(state)
        && !selected
        && safeString(state?.hoveredAgentId) !== safeString(agent?.id)
        && !agent?.draftMotion?.dragging;
    officeDraftSetDatasetValue(el, 'officeAgentOverview', overviewAgent ? '1' : '0');
    officeDraftSetCssVariable(el, '--agent-primary', palette.primary);
    officeDraftSetCssVariable(el, '--agent-secondary', palette.secondary);
    officeDraftSetCssVariable(el, '--agent-glow', palette.glow);
    if (overviewAgent) {
        officeDraftSetDatasetValue(el, 'officeAgentActivity', placement.routeActive ? 'walking' : safeString(agent?.state || 'idle'));
        officeDraftSetDatasetValue(el, 'officeAgentAnimation', placement.routeActive ? 'walking' : 'idle');
        officeDraftSetDatasetValue(el, 'officeAgentRouteActive', placement.routeActive ? '1' : '0');
        officeDraftSetDatasetValue(el, 'officeAgentWorldX', String(Math.round(Number(placement.worldX) || (offsetX + placement.x))));
        officeDraftSetDatasetValue(el, 'officeAgentWorldY', String(Math.round(Number(placement.worldY) || (offsetY + placement.y))));
        officeDraftSetStyleValue(el, 'transform', `translate3d(${Math.round(offsetX + placement.x - 24)}px, ${Math.round(offsetY + placement.y - 24)}px, 0)`);
        officeDraftSetStyleValue(el, 'border', placement.routeActive ? '2px solid rgba(234, 243, 255, 0.78)' : '1px solid rgba(7, 13, 24, 0.64)');
        officeDraftSetStyleValue(el, 'boxShadow', 'none');
        return;
    }

    const activity = officeDraftAgentActivity(agent, space);
    const animation = officeDraftAgentAnimation(agent, activity, now);
    const sitScale = activity === 'sit' ? ' scale(1,0.88)' : '';
    officeDraftSetDatasetValue(el, 'officeAgentActivity', activity);
    officeDraftSetDatasetValue(el, 'officeAgentAnimation', animation);
    officeDraftSetDatasetValue(el, 'officeAgentRouteActive', placement.routeActive ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentWorldX', String(Math.round(Number(placement.worldX) || (offsetX + placement.x))));
    officeDraftSetDatasetValue(el, 'officeAgentWorldY', String(Math.round(Number(placement.worldY) || (offsetY + placement.y))));
    officeDraftSetStyleValue(el, 'transform', `translate3d(${Math.round(offsetX + placement.x)}px, ${Math.round(offsetY + placement.y)}px, 0)${sitScale}`);
    const visibility = officeDraftAgentUiVisibility(state, agent, activity, selected, now, total);
    officeDraftSetDatasetValue(el, 'officeAgentLabelVisible', visibility.showName ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentStatusVisible', visibility.showStatus ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentPropVisible', visibility.showProp ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentBubbleVisible', visibility.showBubble ? '1' : '0');
    officeDraftSetStyleValue(el, 'border', '0');
    officeDraftSetStyleValue(el, 'outline', 'none');
    officeDraftSetStyleValue(el, 'boxShadow', 'none');
    officeDraftSetStyleValue(el, 'zIndex', selected ? '80' : (visibility.showBubble ? '70' : String(20 + Math.round((Number(placement.y) || 0) / 120))));

    const robotWrap = el.querySelector('[data-office-draft-agent-robot="1"]');
    if (robotWrap instanceof HTMLElement) {
        officeDraftSetStyleValue(robotWrap, 'transform', activity === 'sit' ? 'scale(1.24,0.94)' : 'scale(1.24)');
    }
    const nameEl = el.querySelector('[data-office-draft-agent-name="1"]');
    if (nameEl instanceof HTMLElement) {
        officeDraftSetStyleValue(nameEl, 'display', visibility.showName ? 'block' : 'none');
        if (visibility.showName && nameEl.textContent !== safeString(agent?.name)) {
            nameEl.textContent = safeString(agent?.name) || 'Agent';
        }
    }
    const statusEl = el.querySelector('[data-office-draft-agent-status="1"]');
    const statusText = officeDraftAgentActivityLabel(agent, activity, total);
    if (statusEl instanceof HTMLElement) {
        officeDraftSetStyleValue(statusEl, 'display', visibility.showStatus ? 'block' : 'none');
        if (visibility.showStatus && statusEl.textContent !== statusText) {
            statusEl.textContent = statusText;
        }
    }
    const pixelEl = el.querySelector('.office-pixel-agent');
    if (pixelEl instanceof HTMLElement) {
        officeDraftSetCssVariable(pixelEl, '--agent-primary', palette.primary);
        officeDraftSetCssVariable(pixelEl, '--agent-secondary', palette.secondary);
        officeDraftSetCssVariable(pixelEl, '--agent-glow', palette.glow);
        pixelEl.classList.toggle('facing-left', Number(agent?.facing) < 0);
        pixelEl.classList.toggle('looking-user', activity === 'working' || activity === 'drink' || activity === 'talking' || activity === 'paused');
        pixelEl.classList.remove('costume-cap', 'costume-visor', 'costume-headset', 'costume-bowtie', 'costume-toolbelt', 'costume-satchel', 'costume-scarf', 'costume-badge', 'costume-tablet', 'costume-wrench', 'costume-mug');
        // Costumes are intentionally NOT drawn on the office floor — the small
        // cap/visor/bowtie/headset overlays read as visual noise at scene scale.
        // (The roster panel still previews them for users who opt in per-agent.)
    }
    const propEl = el.querySelector('[data-office-draft-agent-prop="1"]');
    if (propEl instanceof HTMLElement) {
        officeDraftSetStyleValue(propEl, 'display', visibility.showProp ? 'flex' : 'none');
        if (visibility.showProp) {
            const propLabel = officeDraftAgentPropLabel(agent);
            if (propEl.textContent !== propLabel) propEl.textContent = propLabel;
            officeDraftSetStyleValue(propEl, 'borderColor', palette.primary);
            officeDraftSetStyleValue(propEl, 'boxShadow', `0 5px 10px rgba(0,0,0,0.18), 0 0 0 1px ${palette.glow}`);
        }
    }
    const canEl = el.querySelector('[data-office-draft-agent-can="1"]');
    if (canEl instanceof HTMLElement) {
        officeDraftSetStyleValue(canEl, 'display', activity === 'drink' ? 'inline-flex' : 'none');
        if (activity === 'drink') {
            const propLabel = safeString(agent?.draftCommandPropLabel || 'Coke') || 'Coke';
            if (canEl.textContent !== propLabel) canEl.textContent = propLabel;
        }
    }
    const bubbleEl = el.querySelector('[data-office-draft-agent-bubble="1"]');
    const speech = typeof officeVisibleSpeech === 'function' ? officeVisibleSpeech(agent, now) : '';
    const bubbleText = visibility.showBubble ? speech : '';
    if (bubbleEl instanceof HTMLElement) {
        const bubbleLeft = Number(placement.x) > (Number(space?.width) || 0) - 260;
        officeDraftSetStyleValue(bubbleEl, 'left', bubbleLeft ? 'auto' : '136px');
        officeDraftSetStyleValue(bubbleEl, 'right', bubbleLeft ? '136px' : 'auto');
        officeDraftSetStyleValue(bubbleEl, 'display', bubbleText ? 'block' : 'none');
        if (bubbleText && bubbleEl.textContent !== bubbleText) {
            bubbleEl.textContent = bubbleText;
        }
    }
}

function officeDraftLayerElementMap(layer) {
    if (!(layer instanceof HTMLElement)) return new Map();
    if (!(layer.__officeDraftAgentElements instanceof Map)) {
        layer.__officeDraftAgentElements = new Map();
        layer.querySelectorAll('[data-office-draft-agent-id]').forEach((node) => {
            const agentId = safeString(node?.dataset?.officeDraftAgentId);
            if (agentId && node instanceof HTMLElement) {
                layer.__officeDraftAgentElements.set(agentId, node);
            }
        });
    }
    return layer.__officeDraftAgentElements;
}

function officeDraftClampResolvedAgentItemToSpace(item) {
    if (!item?.node) return;
    const state = officeEnsureDraftMapState();
    const spaceId = safeString(item.node.dataset.officeDraftSpaceId);
    const space = (Array.isArray(state?.spaces) ? state.spaces : []).find((entry) => safeString(entry?.id) === spaceId);
    if (!space) return;
    const globalLayer = item.node.dataset.officeDraftAgentGlobal === '1';
    if (globalLayer && item.node.dataset.officeAgentRouteActive === '1') {
        const rect = officeDraftSpaceRect(space);
        const center = {
            x: Math.round((Number(item.x) || 0) + (OFFICE_DRAFT_AGENT_HITBOX_W / 2)),
            y: Math.round((Number(item.y) || 0) + (OFFICE_DRAFT_AGENT_HITBOX_H / 2)),
        };
        if (!officeDraftPointInsideRect(center, rect, 0)) return;
    }
    const baseX = globalLayer ? (Number(space.x) || 0) : 0;
    const baseY = globalLayer ? (Number(space.y) || 0) : 0;
    const minX = baseX + 32;
    const minY = baseY + 36;
    const maxX = baseX + Math.max(48, (Number(space.width) || 0) - OFFICE_DRAFT_AGENT_HITBOX_W - 28);
    const maxY = baseY + Math.max(64, (Number(space.height) || 0) - OFFICE_DRAFT_AGENT_HITBOX_H - 20);
    item.x = officeClamp(item.x, Math.min(minX, maxX), Math.max(minX, maxX));
    item.y = officeClamp(item.y, Math.min(minY, maxY), Math.max(minY, maxY));
}

function officeDraftSpreadDuplicateResolvedAgentItem(item, duplicateIndex = 1) {
    if (!item?.node) return;
    const state = officeEnsureDraftMapState();
    const spaceId = safeString(item.node.dataset.officeDraftSpaceId);
    const space = (Array.isArray(state?.spaces) ? state.spaces : []).find((entry) => safeString(entry?.id) === spaceId);
    if (!space) return;
    const globalLayer = item.node.dataset.officeDraftAgentGlobal === '1';
    const baseX = globalLayer ? (Number(space.x) || 0) : 0;
    const baseY = globalLayer ? (Number(space.y) || 0) : 0;
    const minX = baseX + 32;
    const minY = baseY + 36;
    const usableWidth = Math.max(OFFICE_DRAFT_AGENT_HITBOX_W, (Number(space.width) || 0) - OFFICE_DRAFT_AGENT_HITBOX_W - 60);
    const usableHeight = Math.max(OFFICE_DRAFT_AGENT_HITBOX_H, (Number(space.height) || 0) - OFFICE_DRAFT_AGENT_HITBOX_H - 56);
    const columns = Math.max(2, Math.min(5, Math.floor(usableWidth / 132)));
    const rows = Math.max(2, Math.min(5, Math.floor(usableHeight / 118)));
    const slot = Math.abs((Number(item.index) || 0) + (Number(duplicateIndex) || 1) * 7) % (columns * rows);
    item.x = minX + ((slot % columns) * 132);
    item.y = minY + (Math.floor(slot / columns) * 118);
    officeDraftClampResolvedAgentItemToSpace(item);
}

function officeDraftResolveAgentElementOverlaps(layer) {
    if (!(layer instanceof HTMLElement)) return;
    const items = Array.from(layer.querySelectorAll('[data-office-draft-agent-id]'))
        .map((node, index) => {
            if (!(node instanceof HTMLElement)) return null;
            const transform = safeString(node.style.transform);
            const match = transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px,\s*0(?:px)?\)(.*)$/);
            if (!match) return null;
            return {
                node,
                index,
                x: Number(match[1]) || 0,
                y: Number(match[2]) || 0,
                suffix: safeString(match[3]),
                adjusted: false,
            };
        })
        .filter(Boolean);
    if (items.length <= 1) return;
    const minX = 132;
    const minY = 118;
    for (let pass = 0; pass < 5; pass += 1) {
        for (let leftIndex = 0; leftIndex < items.length; leftIndex += 1) {
            for (let rightIndex = leftIndex + 1; rightIndex < items.length; rightIndex += 1) {
                const left = items[leftIndex];
                const right = items[rightIndex];
                const dx = right.x - left.x;
                const dy = right.y - left.y;
                if (Math.abs(dx) >= minX || Math.abs(dy) >= minY) continue;
                const pushX = dx === 0 ? (right.index % 2 === 0 ? 1 : -1) : Math.sign(dx);
                const pushY = dy === 0 ? (right.index % 3 === 0 ? 1 : -1) : Math.sign(dy);
                const adjustX = Math.min(70, ((minX - Math.abs(dx)) / 2) + 10);
                const adjustY = Math.min(62, ((minY - Math.abs(dy)) / 2) + 8);
                left.x -= pushX * adjustX;
                right.x += pushX * adjustX;
                left.y -= pushY * adjustY;
                right.y += pushY * adjustY;
                left.adjusted = true;
                right.adjusted = true;
                officeDraftClampResolvedAgentItemToSpace(left);
                officeDraftClampResolvedAgentItemToSpace(right);
            }
        }
    }
    const occupied = new Map();
    items.forEach((item) => {
        officeDraftClampResolvedAgentItemToSpace(item);
        let key = `${Math.round(item.x)}:${Math.round(item.y)}:${safeString(item.node.dataset.officeDraftSpaceId)}`;
        let duplicateIndex = Number(occupied.get(key)) || 0;
        while (duplicateIndex > 0 && duplicateIndex < 10) {
            officeDraftSpreadDuplicateResolvedAgentItem(item, duplicateIndex);
            item.adjusted = true;
            key = `${Math.round(item.x)}:${Math.round(item.y)}:${safeString(item.node.dataset.officeDraftSpaceId)}`;
            duplicateIndex = Number(occupied.get(key)) || 0;
        }
        occupied.set(key, (Number(occupied.get(key)) || 0) + 1);
        if (item.adjusted) {
            item.node.dataset.officeAgentOverlapResolved = '1';
            item.node.style.setProperty('transition', 'none', 'important');
        } else if (item.node.dataset.officeAgentOverlapResolved === '1') {
            delete item.node.dataset.officeAgentOverlapResolved;
            item.node.style.removeProperty('transition');
        }
        officeDraftSetStyleValue(item.node, 'transform', `translate3d(${Math.round(item.x)}px, ${Math.round(item.y)}px, 0)${item.suffix}`);
    });
}

function officePopulateDraftAgentLayer(layer, space, state, now = performance.now(), agentsOverride = null) {
    if (!(layer instanceof HTMLElement)) return;
    const agents = Array.isArray(agentsOverride) ? agentsOverride : officeDraftAgentsForSpace(space);
    const elementMap = officeDraftLayerElementMap(layer);
    const seen = new Set();
    agents.forEach((agent, index) => {
        const agentId = safeString(agent?.id);
        if (!agentId) return;
        seen.add(agentId);
        let el = elementMap.get(agentId);
        if (!(el instanceof HTMLElement) || !layer.contains(el)) {
            el = officeDraftCreateAgentElement(space, agent, index, agents.length, state, { skipInitialUpdate: true });
            elementMap.set(agentId, el);
            layer.appendChild(el);
        }
        el.dataset.officeDraftSpaceId = safeString(space.id);
        officeDraftUpdateAgentElement(el, space, agent, index, agents.length, state, now);
    });
    Array.from(elementMap.entries()).forEach(([agentId, node]) => {
        if (!seen.has(agentId)) {
            if (node instanceof HTMLElement) node.remove();
            elementMap.delete(agentId);
        }
    });
    officeDraftResolveAgentElementOverlaps(layer);
}

function officePopulateDraftGlobalAgentLayer(layer, state, now = performance.now(), assignmentsOverride = null, renderSource = 'direct') {
    if (!(layer instanceof HTMLElement) || !officeState) return;
    const currentNow = Number(now) || performance.now();
    if (state?.agentLayerForceRender !== true
        && state?.agentPointerId === null
        && state?.agentLayerQuietMotionRender !== true
        && officeDraftAgentRenderQuietActive(state, currentNow)) {
        return;
    }
    state.agentLayerRenderCount = (Number(state.agentLayerRenderCount) || 0) + 1;
    const sourceKey = safeString(renderSource) || 'direct';
    state.agentLayerRenderSources = state.agentLayerRenderSources && typeof state.agentLayerRenderSources === 'object'
        ? state.agentLayerRenderSources
        : {};
    state.agentLayerRenderSources[sourceKey] = (Number(state.agentLayerRenderSources[sourceKey]) || 0) + 1;
    const assignments = assignmentsOverride instanceof Map ? assignmentsOverride : officeDraftAgentAssignmentMap(state);
    const elementMap = officeDraftLayerElementMap(layer);
    const allAgents = Array.isArray(officeState.agents) ? officeState.agents.filter(Boolean) : [];
    const routePlanPendingAgents = sourceKey === 'route-plan'
        ? allAgents.filter((agent) => officeDraftAgentHasPendingRoutePlan(agent, currentNow))
        : [];
    const routePlanCursor = routePlanPendingAgents.length
        ? Math.max(0, Number(state.agentRoutePlanCursor) || 0) % routePlanPendingAgents.length
        : 0;
    const renderAgents = sourceKey === 'route-plan' && routePlanPendingAgents.length
        ? [routePlanPendingAgents[routePlanCursor]]
        : (sourceKey === 'route-plan' ? [] : allAgents);
    const routePlanHasMoreAgents = sourceKey === 'route-plan' && routePlanPendingAgents.length > 1;
    if (sourceKey === 'route-plan') {
        state.agentRoutePlanCursor = routePlanPendingAgents.length
            ? (routePlanCursor + 1) % routePlanPendingAgents.length
            : 0;
        state.lastRoutePlanRenderAt = currentNow;
    }
    const seen = new Set(allAgents.map((agent) => safeString(agent?.id)).filter(Boolean));
    const fallbackSpace = (Array.isArray(state?.spaces) ? state.spaces : []).find((space) => safeString(space?.id) === 'lobby')
        || (Array.isArray(state?.spaces) ? state.spaces[0] : null)
        || null;
    const groupIndexByAgentId = new Map();
    assignments.forEach((agents) => {
        (Array.isArray(agents) ? agents : []).forEach((agent, index) => {
            groupIndexByAgentId.set(safeString(agent?.id), index);
        });
    });
    const previousRouteBudget = state.agentRoutePlansRemaining;
    const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;
    const skipRoutePlanning = previousSkipRoutePlanning === true;
    const routePlanningSource = new Set(['route-plan', 'agent-chat-command']).has(sourceKey);
    if (!routePlanningSource || state.agentLayerQuietMotionRender === true) {
        state.agentLayerSkipRoutePlanning = true;
    }
    state.agentRoutePlansRemaining = (skipRoutePlanning || state.agentLayerQuietMotionRender === true || !routePlanningSource)
        ? 0
        : OFFICE_DRAFT_AGENT_ROUTE_PLANS_PER_RENDER;
    state.agentRoutePlanDeferred = false;
    const previousRoutePlanningSource = state.agentRoutePlanningSource;
    state.agentRoutePlanningSource = sourceKey;
    const chunkStartedAt = performance.now();
    const allowChunking = safeString(renderSource) !== 'scene' && renderAgents.length > 4;
    const chunkBudget = state.agentLayerForceRender === true
        ? OFFICE_DRAFT_AGENT_LAYER_FORCE_CHUNK_BUDGET_MS
        : OFFICE_DRAFT_AGENT_LAYER_CHUNK_BUDGET_MS;
    const priorityAgentIds = new Set([
        safeString(state.agentDragAgentId),
        safeString(state.hoveredAgentId),
        safeString(state.expandedRosterAgentId),
        safeString(officeState.selectedAgentId),
    ].filter(Boolean));
    const priorityAgents = allowChunking
        ? renderAgents.filter((agent) => priorityAgentIds.has(safeString(agent?.id)))
        : [];
    const normalAgents = allowChunking
        ? renderAgents.filter((agent) => !priorityAgentIds.has(safeString(agent?.id)))
        : renderAgents;
    const startCursor = allowChunking
        ? Math.max(0, Number(state.agentLayerRenderCursor) || 0) % Math.max(1, normalAgents.length)
        : 0;
    const orderedAgents = allowChunking
        ? priorityAgents.concat(normalAgents.slice(startCursor), normalAgents.slice(0, startCursor))
        : renderAgents;
    let processed = 0;
    let completedAllAgents = true;
    try {
        for (let step = 0; step < orderedAgents.length; step += 1) {
            const agent = orderedAgents[step];
            const agentId = safeString(agent?.id);
            if (!agentId) continue;
            const space = officeDraftSpaceForAgent(agent) || fallbackSpace;
            if (!space) continue;
            const group = assignments.get(safeString(space.id)) || [agent];
            const index = groupIndexByAgentId.has(agentId) ? groupIndexByAgentId.get(agentId) : Math.max(0, group.findIndex((entry) => safeString(entry?.id) === agentId));
            let el = elementMap.get(agentId);
            if (!(el instanceof HTMLElement) || !layer.contains(el)) {
                el = officeDraftCreateAgentElement(space, agent, Math.max(0, index), group.length || 1, state, { skipInitialUpdate: true });
                el.dataset.officeDraftAgentGlobal = '1';
                elementMap.set(agentId, el);
                layer.appendChild(el);
            }
            el.dataset.officeDraftSpaceId = safeString(space.id);
            officeDraftUpdateAgentElement(el, space, agent, Math.max(0, index), group.length || 1, state, currentNow);
            processed += 1;
            if (allowChunking
                && processed > 0
                && performance.now() - chunkStartedAt > chunkBudget
                && step < orderedAgents.length - 1) {
                completedAllAgents = false;
                break;
            }
        }
    } finally {
        const routeDeferred = state.agentRoutePlanDeferred === true;
        state.agentRoutePlansRemaining = previousRouteBudget;
        state.agentRoutePlanDeferred = routeDeferred || routePlanHasMoreAgents;
        state.agentRoutePlanningSource = previousRoutePlanningSource || '';
        state.agentLayerSkipRoutePlanning = previousSkipRoutePlanning === true;
    }
    if (state.agentRoutePlanDeferred) {
        officeDraftScheduleDeferredRoutePlan(state, currentNow);
    }
    if (allowChunking && !completedAllAgents) {
        const normalProcessed = Math.max(0, processed - priorityAgents.length);
        state.agentLayerRenderCursor = (startCursor + normalProcessed) % Math.max(1, normalAgents.length);
        if (!state.agentLayerChunkTimer) {
            state.agentLayerChunkTimer = window.setTimeout(() => {
                state.agentLayerChunkTimer = 0;
                officeRenderDraftAgentLayerOnly(performance.now(), { force: false, source: 'agent-layer-chunk' });
            }, Math.max(24, OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS));
        }
    } else {
        state.agentLayerRenderCursor = 0;
    }
    Array.from(elementMap.entries()).forEach(([agentId, node]) => {
        if (!seen.has(agentId)) {
            if (node instanceof HTMLElement) node.remove();
            elementMap.delete(agentId);
        }
    });
    if (!allowChunking || completedAllAgents) {
        officeDraftResolveAgentElementOverlaps(layer);
    }
}

function officeDraftMaybeFocusOccupiedRoom(state, assignments) {
    if (!state || state.userSelectedSpace === true) return false;
    if (state.agentFocusInitialized === true) return false;
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null) return false;
    const assignmentMap = assignments instanceof Map ? assignments : officeDraftAgentAssignmentMap(state);
    const totalAgents = Array.from(assignmentMap.values()).reduce((count, agents) => count + (Array.isArray(agents) ? agents.length : 0), 0);
    if (!totalAgents) return false;
    const selectedAgents = assignmentMap.get(safeString(state.selectedSpaceId)) || [];
    if (selectedAgents.length) {
        state.agentFocusInitialized = true;
        return false;
    }
    const focusSpace = typeof officeDraftInitialFocusSpace === 'function'
        ? officeDraftInitialFocusSpace(state)
        : null;
    if (!focusSpace || safeString(focusSpace.id) === safeString(state.selectedSpaceId)) {
        state.agentFocusInitialized = true;
        return false;
    }
    state.agentFocusInitialized = true;
    state.selectedSpaceId = safeString(focusSpace.id);
    officeCenterDraftMapViewport();
    officeRenderDraftMapScene();
    return true;
}

function officeDraftAgentRenderQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null || state.agentDragActive) return true;
    if ((Number(state.agentLayerQuietUntil) || 0) > currentNow) return true;
    if ((currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastPointerIntentAt) || 0)) < OFFICE_DRAFT_AGENT_POINTER_QUIET_MS) return true;
    return false;
}

function officeDraftSceneRenderQuietActive(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.pointerId !== null && state.lastInputMode === 'pan') return true;
    if ((currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS) return true;
    if ((currentNow - (Number(state.lastPointerIntentAt) || 0)) < OFFICE_DRAFT_AGENT_POINTER_QUIET_MS) return true;
    return false;
}

function officeDraftInputMotionRenderAllowed(state, now = performance.now()) {
    const currentNow = Number(now) || performance.now();
    if (!state) return false;
    if (state.assetPointerId !== null || state.catalogPointerId !== null || state.agentDragActive) return false;
    const hasActivePan = state.pointerId !== null && state.lastInputMode === 'pan';
    const recentlyPanned = (currentNow - (Number(state.lastPanAt) || 0)) < OFFICE_DRAFT_AGENT_PAN_QUIET_MS;
    const recentlyWheeled = (currentNow - (Number(state.lastWheelAt) || 0)) < OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS;
    if (!hasActivePan && !recentlyPanned && !recentlyWheeled) return false;
    return (currentNow - (Number(state.lastQuietAgentRenderAt) || 0)) >= OFFICE_DRAFT_AGENT_INPUT_RENDER_INTERVAL_MS;
}

function officeDraftCancelAgentHoverRender(stateRaw = null) {
    const state = stateRaw || officeEnsureDraftMapState();
    window.clearTimeout(state.agentHoverRenderTimer);
    state.agentHoverRenderTimer = 0;
    state.hoveredAgentId = '';
    if (state.agentRoutePlanTimer) {
        window.clearTimeout(state.agentRoutePlanTimer);
        state.agentRoutePlanTimer = 0;
    }
}

function officeDraftScheduleSceneRenderAfterInput(state, now = performance.now()) {
    if (!state) return;
    const currentNow = Number(now) || performance.now();
    const panDelay = Math.max(0, OFFICE_DRAFT_AGENT_PAN_QUIET_MS - (currentNow - (Number(state.lastPanAt) || 0)));
    const wheelDelay = Math.max(0, OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS - (currentNow - (Number(state.lastWheelAt) || 0)));
    const pointerDelay = Math.max(0, OFFICE_DRAFT_AGENT_POINTER_QUIET_MS - (currentNow - (Number(state.lastPointerIntentAt) || 0)));
    const delay = Math.max(90, panDelay, wheelDelay, pointerDelay) + 80;
    state.sceneRenderDeferred = true;
    window.clearTimeout(state.sceneRenderTimer);
    state.sceneRenderTimer = window.setTimeout(() => {
        const timerNow = performance.now();
        if (officeDraftSceneRenderQuietActive(state, timerNow)) {
            officeDraftScheduleSceneRenderAfterInput(state, timerNow);
            return;
        }
        state.sceneRenderDeferred = false;
        officeRenderDraftMapScene({ force: true });
    }, delay);
}

function officeDraftFlushSceneOrAgentLayerAfterInput(state, source) {
    const currentState = state || officeEnsureDraftMapState();
    if (currentState.sceneRenderDeferred) {
        window.clearTimeout(currentState.sceneRenderTimer);
        currentState.sceneRenderDeferred = false;
        officeRenderDraftMapScene({ force: true });
        return;
    }
    officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source });
}

function officeRenderDraftAgentLayerOnly(now = performance.now(), options = {}) {
    if (!officeState || !officeDraftMapPlane()) return;
    const state = officeEnsureDraftMapState();
    const force = options?.force === true;
    const missionDirty = state.missionAgentLayerDirty === true;
    const source = safeString(options?.source) || (missionDirty ? 'mission-stream-deferred' : (force ? 'force' : 'tick'));
    const quietActive = !force && officeDraftAgentRenderQuietActive(state, now);
    const quietMotionRender = quietActive && officeDraftInputMotionRenderAllowed(state, now);
    if (source === 'route-plan' && officeDraftRoutePlanQuietActive(state, now)) {
        officeDraftScheduleDeferredRoutePlan(state, now);
        return;
    }
    if (quietActive && !quietMotionRender) return;
    if (quietMotionRender) {
        state.lastQuietAgentRenderAt = Number(now) || performance.now();
    }
    const lastAt = Number(officeState.lastDraftAgentRenderAt) || 0;
    const previousRenderCost = Math.max(0, Number(officeState.lastDraftAgentRenderDurationMs) || 0);
    const dynamicRenderInterval = previousRenderCost > OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS
        ? Math.min(
            OFFICE_DRAFT_AGENT_RENDER_BACKOFF_MAX_MS,
            Math.max(OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS, Math.round(previousRenderCost * 1.7)),
        )
        : OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS;
    if (!force && (Number(now) || performance.now()) - lastAt < dynamicRenderInterval) return;
    officeState.lastDraftAgentRenderAt = Number(now) || performance.now();
    const assignments = officeDraftAgentAssignmentMap(state);
    if (officeDraftMaybeFocusOccupiedRoom(state, assignments)) return;
    const layer = officeScene?.querySelector('[data-office-draft-agent-layer="global"]');
    state.agentLayerForceRender = force;
    state.agentLayerQuietMotionRender = quietMotionRender;
    const renderStartedAt = performance.now();
    try {
        officePopulateDraftGlobalAgentLayer(layer, state, now, assignments, quietMotionRender ? 'quiet-motion' : source);
    } finally {
        officeState.lastDraftAgentRenderDurationMs = Math.max(0, performance.now() - renderStartedAt);
        state.agentLayerForceRender = false;
        state.agentLayerQuietMotionRender = false;
        state.missionAgentLayerDirty = false;
    }
    if (state.rosterOpen && ((Number(now) || performance.now()) - (Number(officeState.lastDraftRosterRenderAt) || 0)) > 1600) {
        officeState.lastDraftRosterRenderAt = Number(now) || performance.now();
        officeRenderDraftAgentRosterPanel();
    }
}

function officeToggleDraftAgentRoster(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.rosterOpen = !state.rosterOpen;
    officeRenderDraftMapScene();
}

function officeDraftUpdateRosterField(agentId, field, valueRaw) {
    if (!officeState) return;
    const agent = officeGetAgentById(agentId);
    if (!agent) return;
    const value = safeString(valueRaw);
    if (field === 'name') {
        agent.name = value.slice(0, 24) || agent.name;
    } else if (field === 'specialty') {
        agent.specialty = value.slice(0, 64) || 'Generalist';
    } else if (field === 'personality') {
        agent.personality = value.slice(0, 160) || 'Helpful, direct, and persistent.';
    } else if (field === 'chatProfile') {
        agent.chatProfile = value.slice(0, 80);
        agent.chatModelId = officeDraftDefaultChatModelId(value) || safeString(agent.chatModelId).slice(0, 120);
    } else if (field === 'chatModelId') {
        agent.chatModelId = value.slice(0, 120);
    } else if (field === 'color' && /^#[0-9a-f]{6}$/i.test(value)) {
        agent.color = value;
        agent.tint = officeAgentTintFromColor(value);
    } else if (field === 'costume' && new Set(OFFICE_AGENT_COSTUME_POOL).has(value)) {
        agent.costume = value;
    }
    officeState.selectedAgentId = agent.id;
    officePersistAgentPrefs();
    officeRenderAgentSelector(agent.id);
    officeRenderDraftMapScene();
}

function officeBindDraftRosterPanel(panel) {
    if (!(panel instanceof HTMLElement)) return;
    const backBtn = panel.querySelector('[data-office-roster-back="1"]');
    if (backBtn instanceof HTMLElement) {
        backBtn.addEventListener('click', (event) => {
            event.preventDefault();
            const state = officeEnsureDraftMapState();
            state.expandedRosterAgentId = '';
            officeRenderDraftMapScene();
        });
    }
    panel.querySelectorAll('[data-office-roster-expand]').forEach((node) => {
        node.addEventListener('click', (event) => {
            event.preventDefault();
            const agentId = safeString(node.dataset.officeRosterExpand);
            const state = officeEnsureDraftMapState();
            state.expandedRosterAgentId = agentId;
            if (officeState) officeState.selectedAgentId = agentId;
            officeRenderDraftMapScene();
        });
    });
    panel.querySelectorAll('[data-office-roster-field]').forEach((node) => {
        node.addEventListener('change', () => {
            officeDraftUpdateRosterField(
                safeString(node.dataset.officeRosterAgentId),
                safeString(node.dataset.officeRosterField),
                node.value,
            );
        });
    });
}

function officeDraftEnsureAgentChatState(stateRaw = officeEnsureDraftMapState()) {
    const state = stateRaw || officeEnsureDraftMapState();
    state.agentChatOpen = Boolean(state.agentChatOpen);
    state.agentChatAgentId = safeString(state.agentChatAgentId);
    if (!state.agentChatDraftById || typeof state.agentChatDraftById !== 'object' || Array.isArray(state.agentChatDraftById)) {
        state.agentChatDraftById = {};
    }
    return state;
}

function officeDraftAgentChatHistory(agent) {
    if (!agent) return [];
    if (!Array.isArray(agent.officeChatHistory)) {
        agent.officeChatHistory = [];
    }
    if (agent.officeChatHistory.length > 28) {
        agent.officeChatHistory.splice(0, agent.officeChatHistory.length - 28);
    }
    return agent.officeChatHistory;
}

function officeDraftAppendAgentChat(agent, roleRaw, textRaw, now = performance.now()) {
    const text = safeString(textRaw).replace(/\s+/g, ' ').trim();
    if (!agent || !text) return null;
    const entry = {
        role: safeString(roleRaw) || 'agent',
        text: text.slice(0, 600),
        at: Date.now(),
        timeLabel: new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
    };
    const history = officeDraftAgentChatHistory(agent);
    history.push(entry);
    if (history.length > 28) {
        history.splice(0, history.length - 28);
    }
    agent.lastOfficeChatAt = Number(now) || performance.now();
    return entry;
}

function officeDraftJoinAgentChatChunks(chunksRaw = []) {
    const chunks = (Array.isArray(chunksRaw) ? chunksRaw : [])
        .map((chunk) => safeString(chunk))
        .filter((chunk) => chunk);
    if (!chunks.length) return '';
    if (chunks.some((chunk) => /\s/.test(chunk))) return chunks.join('');
    if (chunks.every((chunk) => chunk.length <= 1)) return chunks.join('');
    return chunks.join(' ');
}

function officeDraftSeedAgentChat(agent, space, now = performance.now()) {
    if (!agent) return;
    officeDraftAgentChatHistory(agent);
    if (!agent.lastOfficeConversationPrompt) {
        officeDraftPrimeAgentConversation(agent, space, now);
    }
}

function officeDraftAgentChatSessionId(agent) {
    const rawId = safeString(agent?.id || agent?.name || 'agent');
    const slug = rawId.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 64) || 'agent';
    return `office-agent-chat-${slug}`;
}

function officeDraftDefaultChatProfile() {
    return safeString(modelSelector?.value)
        || safeString(setupProviderSelector?.value)
        || safeString(currentPreferences?.advanced?.model?.active_profile)
        || (Array.isArray(availableModelProfiles) ? safeString(availableModelProfiles.find((profile) => safeString(profile?.name))?.name) : '')
        || '';
}

function officeDraftDefaultChatModelId(profileRaw = '') {
    const profile = safeString(profileRaw || officeDraftDefaultChatProfile());
    if (!profile) return safeString(activeModelOverride);
    if (typeof resolveActiveModelIdForProfile === 'function') {
        const activeModelId = safeString(resolveActiveModelIdForProfile(profile));
        if (activeModelId) return activeModelId;
    }
    if (typeof defaultModelIdForProfile === 'function') {
        return safeString(defaultModelIdForProfile(profile));
    }
    const profileMeta = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.find((entry) => safeString(entry?.name) === profile)
        : null;
    return safeString(profileMeta?.model).split('/').pop();
}

function officeDraftAgentChatProfile(agent) {
    return safeString(agent?.chatProfile) || officeDraftDefaultChatProfile();
}

function officeDraftAgentChatModelId(agent, profileRaw = '') {
    const profile = safeString(profileRaw || officeDraftAgentChatProfile(agent));
    return safeString(agent?.chatModelId) || officeDraftDefaultChatModelId(profile);
}

function officeDraftAgentChatModelLabel(agent) {
    const profile = officeDraftAgentChatProfile(agent);
    const modelId = safeString(officeDraftAgentChatModelId(agent, profile)).split('/').pop();
    const providerLabel = profile && typeof formatProviderDisplay === 'function'
        ? (formatProviderDisplay(profile) || profile)
        : profile;
    if (providerLabel && modelId) return `${providerLabel} - ${modelId}`;
    return providerLabel || modelId || 'default model';
}

function officeDraftAgentChatProfileOptionsMarkup(selectedProfileRaw = '') {
    const selectedProfile = safeString(selectedProfileRaw || officeDraftDefaultChatProfile());
    const profiles = Array.isArray(availableModelProfiles)
        ? availableModelProfiles.filter((profile) => safeString(profile?.name))
        : [];
    if (!profiles.length) {
        const fallback = selectedProfile || 'default';
        return `<option value="${escapeHtml(fallback)}" selected>${escapeHtml(fallback)}</option>`;
    }
    let hasSelected = false;
    const options = profiles.map((profile) => {
        const name = safeString(profile?.name);
        const modelId = safeString(officeDraftDefaultChatModelId(name) || profile?.model).split('/').pop();
        const providerLabel = typeof formatProviderDisplay === 'function'
            ? (formatProviderDisplay(name) || name)
            : name;
        const isSelected = name === selectedProfile;
        hasSelected = hasSelected || isSelected;
        return `<option value="${escapeHtml(name)}"${isSelected ? ' selected' : ''}>${escapeHtml(providerLabel)}${modelId ? ` - ${escapeHtml(modelId)}` : ''}</option>`;
    });
    if (selectedProfile && !hasSelected) {
        options.unshift(`<option value="${escapeHtml(selectedProfile)}" selected>${escapeHtml(selectedProfile)}</option>`);
    }
    return options.join('');
}

function officeDraftBuildAgentChatRequestPayload(agent, userTextRaw) {
    const text = safeString(userTextRaw).trim();
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    const promptPrefix = officeDraftBuildAgentConversationPrompt(agent, space);
    const profile = officeDraftAgentChatProfile(agent);
    const modelId = officeDraftAgentChatModelId(agent, profile);
    const message = `${promptPrefix}\n\nUser message:\n${text}`;
    const payload = typeof buildChatRequestPayload === 'function'
        ? buildChatRequestPayload(message, {
            docs: [],
            images: [],
            systemPrompt: promptPrefix,
            resolvedProfile: profile,
            studioChatContext: { enabled: false },
        })
        : {
            message,
            docs: [],
            images: [],
            system_prompt: promptPrefix,
        };
    payload.message = message;
    payload.session_id = officeDraftAgentChatSessionId(agent);
    payload.profile = profile || payload.profile || undefined;
    payload.model = payload.profile || profile || undefined;
    payload.model_id = modelId || undefined;
    payload.mode = 'auto';
    payload.autonomy_level = 1;
    payload.file_access = 'read_only';
    payload.module = undefined;
    payload.asset_studio_mode = undefined;
    payload.asset_studio_context = undefined;
    payload.office_agent_chat = {
        agent_id: safeString(agent?.id),
        agent_name: safeString(agent?.name),
        specialty: safeString(agent?.specialty),
        chat_profile: profile,
        chat_model_id: modelId,
        session_id: payload.session_id,
    };
    return payload;
}

function officeDraftExtractAgentChatEventText(evt) {
    if (!evt || typeof evt !== 'object') return '';
    const evtType = safeString(evt.type);
    if (evtType === 'text') return safeString(evt.text);
    if (evtType === 'agent_text') return safeString(evt.text || evt.delta || evt.content);
    if (['assistant_delta', 'delta', 'message_delta'].includes(evtType)) {
        return safeString(evt.text || evt.delta || evt.content);
    }
    if (evtType === 'assistant' || evtType === 'message') {
        return safeString(evt.text || evt.content || evt.message);
    }
    const choiceDelta = evt?.choices?.[0]?.delta?.content || evt?.choices?.[0]?.message?.content;
    return safeString(choiceDelta);
}

function officeDraftExtractAgentChatDoneText(evt) {
    if (!evt || typeof evt !== 'object') return '';
    if (safeString(evt.type) !== 'done') return '';
    return safeString(evt.text || evt.final || evt.output_text || evt.message);
}

async function officeDraftRequestAgentChatReply(agent, userTextRaw) {
    const payload = officeDraftBuildAgentChatRequestPayload(agent, userTextRaw);
    const chatEndpoint = window.__THOMAS_CHAT_V2__ === false ? '/api/chat' : '/api/v2/chat';
    const response = await fetch(chatEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        let errorText = '';
        try {
            errorText = safeString(await response.text()).slice(0, 180);
        } catch (_) {
            errorText = '';
        }
        throw new Error(errorText || `Agent chat failed (${response.status})`);
    }

    const chunks = [];
    let doneText = '';
    const consumeLine = (lineRaw) => {
        let line = safeString(lineRaw).trim();
        if (!line) return;
        if (line.startsWith('data:')) line = line.slice(5).trim();
        if (!line || line === '[DONE]') return;
        try {
            const evt = JSON.parse(line);
            const text = officeDraftExtractAgentChatEventText(evt);
            if (text) chunks.push(text);
            const finalText = officeDraftExtractAgentChatDoneText(evt);
            if (finalText) doneText = finalText;
        } catch (_) {
            chunks.push(line);
        }
    };

    if (response.body && typeof response.body.getReader === 'function') {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split(/\r?\n/);
            buffer = lines.pop() || '';
            lines.forEach(consumeLine);
        }
        buffer += decoder.decode();
        if (buffer.trim()) consumeLine(buffer);
    } else {
        const text = await response.text();
        text.split(/\r?\n/).forEach(consumeLine);
    }

    const reply = safeString(officeDraftJoinAgentChatChunks(chunks) || doneText).trim();
    if (!reply) {
        throw new Error('The chat model returned no text.');
    }
    return { reply, payload };
}

function officeDraftSelectedAgentForChat() {
    if (!officeState) return null;
    const state = officeDraftEnsureAgentChatState();
    const selectedId = safeString(state.agentChatAgentId || officeState.selectedAgentId || state.expandedRosterAgentId);
    return (selectedId ? officeGetAgentById(selectedId) : null)
        || (Array.isArray(officeState.agents) ? officeState.agents[0] : null)
        || null;
}

function officeDraftOpenAgentChat(agentIdRaw, options = {}) {
    const state = officeDraftEnsureAgentChatState();
    const agent = (officeState && officeGetAgentById(agentIdRaw))
        || officeDraftSelectedAgentForChat();
    state.agentChatOpen = true;
    if (!agent) {
        state.agentChatAgentId = '';
        officeRenderDraftAgentChatPanel();
        officePrepareDraftMapShell();
        return null;
    }
    const space = officeDraftSpaceForAgent(agent) || officeDraftSpaceForRoomId('room-lobby');
    state.agentChatAgentId = safeString(agent.id);
    state.expandedRosterAgentId = safeString(agent.id);
    if (officeState) officeState.selectedAgentId = safeString(agent.id);
    if (options?.prime !== false) {
        officeDraftPrimeAgentConversation(agent, space, performance.now());
    }
    officeDraftSeedAgentChat(agent, space, performance.now());
    officeRenderDraftAgentChatPanel({ focusInput: Boolean(options?.focusInput) });
    officePrepareDraftMapShell();
    return agent;
}

function officeDraftCloseAgentChat(event) {
    if (event?.preventDefault) event.preventDefault();
    if (event?.stopPropagation) event.stopPropagation();
    const state = officeDraftEnsureAgentChatState();
    state.agentChatOpen = false;
    officeRenderDraftAgentChatPanel();
    officePrepareDraftMapShell();
}

function officeToggleDraftAgentChat(event) {
    if (event?.preventDefault) event.preventDefault();
    if (event?.stopPropagation) event.stopPropagation();
    const state = officeDraftEnsureAgentChatState();
    if (state.agentChatOpen) {
        officeDraftCloseAgentChat(event);
        return;
    }
    officeDraftOpenAgentChat(safeString(officeState?.selectedAgentId || state.expandedRosterAgentId), {
        focusInput: true,
        prime: true,
    });
}

async function officeDraftSendAgentChatMessage(agentIdRaw = '') {
    const state = officeDraftEnsureAgentChatState();
    const agent = officeGetAgentById(agentIdRaw || state.agentChatAgentId);
    if (!agent) return false;
    if (agent.officeChatPending) return false;
    const panel = officeSceneWrap?.querySelector('[data-office-agent-chat-panel="1"]');
    const input = panel?.querySelector('[data-office-agent-chat-input="1"]');
    const text = safeString(input instanceof HTMLTextAreaElement ? input.value : state.agentChatDraftById?.[agent.id]).trim();
    if (!text) return false;
    const now = performance.now();
    state.agentChatDraftById[agent.id] = '';
    officeDraftAppendAgentChat(agent, 'user', text, now);
    agent.lastOfficeChatSummary = text.slice(0, 160);
    const commandResult = officeDraftApplyAgentChatCommand(agent, text);
    agent.lastOfficeChatCommandHandled = Boolean(commandResult);
    agent.officeChatError = '';
    agent.officeChatPending = true;
    if (typeof officePushChatLine === 'function') {
        officePushChatLine(`You -> @${safeString(agent.name) || 'Agent'}: ${text}`, 'user');
    }
    officeRenderDraftAgentChatPanel({ focusInput: false });
    officeRenderDraftAgentLayerOnly(now, { force: true, source: 'agent-chat-pending' });
    try {
        const { reply, payload } = await officeDraftRequestAgentChatReply(agent, text);
        agent.lastOfficeChatPayload = payload;
        officeDraftAppendAgentChat(agent, 'agent', reply, performance.now());
        if (typeof officeSpeak === 'function') {
            officeSpeak(agent, reply, { priority: true, durationMs: Math.max(2600, Math.min(7200, reply.length * 42)) });
        }
        if (typeof officePushChatLine === 'function') {
            officePushChatLine(`@${safeString(agent.name) || 'Agent'}: ${reply}`);
        }
        if (typeof officeBusEmit === 'function') {
            officeBusEmit('agent.chat_message', {
                agentId: safeString(agent.id),
                agentName: safeString(agent.name),
                message: text.slice(0, 260),
                reply: reply.slice(0, 260),
                sessionId: safeString(payload?.session_id),
                profile: safeString(payload?.profile),
                modelId: safeString(payload?.model_id),
            }, performance.now());
        }
    } catch (error) {
        console.warn('office agent chat request failed', error);
        agent.officeChatError = safeString(error?.message || error || 'Agent chat failed.').slice(0, 220);
    } finally {
        agent.officeChatPending = false;
        officePersistAgentPrefs();
        officeRenderDraftAgentChatPanel({ focusInput: true });
        officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-chat' });
    }
    return true;
}

function officeBindDraftAgentChatPanel(panel) {
    if (!(panel instanceof HTMLElement)) return;
    if (panel.dataset.officeAgentChatPointerBound !== '1') {
        panel.dataset.officeAgentChatPointerBound = '1';
        panel.addEventListener('pointerdown', (event) => {
            event.stopPropagation();
        });
    }
    const state = officeDraftEnsureAgentChatState();
    const agentId = safeString(panel.dataset.officeAgentChatAgentId || state.agentChatAgentId);
    const closeBtn = panel.querySelector('[data-office-agent-chat-close="1"]');
    if (closeBtn instanceof HTMLButtonElement) {
        closeBtn.addEventListener('click', officeDraftCloseAgentChat);
    }
    const form = panel.querySelector('[data-office-agent-chat-form="1"]');
    if (form instanceof HTMLFormElement) {
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            event.stopPropagation();
            void officeDraftSendAgentChatMessage(agentId);
        });
    }
    const input = panel.querySelector('[data-office-agent-chat-input="1"]');
    if (input instanceof HTMLTextAreaElement) {
        input.addEventListener('input', () => {
            state.agentChatDraftById[agentId] = input.value;
        });
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void officeDraftSendAgentChatMessage(agentId);
            }
        });
    }
}

function officeRenderDraftAgentChatPanel(options = {}) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeDraftEnsureAgentChatState();
    let panel = officeSceneWrap.querySelector('[data-office-agent-chat-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeAgentChatPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    if (!state.agentChatOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agent = officeGetAgentById(state.agentChatAgentId) || officeDraftSelectedAgentForChat();
    if (!agent) {
        panel.dataset.officeAgentChatAgentId = '';
        panel.style.display = 'grid';
        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <strong style="font-size:0.9rem;letter-spacing:0.06em;text-transform:uppercase;">Agent Chat</strong>
                <button type="button" data-office-agent-chat-close="1" style="padding:7px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Close</button>
            </div>
            <div style="padding:14px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);color:rgba(204,218,238,0.76);font-size:0.78rem;line-height:1.45;">Click a robot to talk with that agent.</div>
        `;
        officeBindDraftAgentChatPanel(panel);
        return;
    }
    state.agentChatAgentId = safeString(agent.id);
    panel.dataset.officeAgentChatAgentId = safeString(agent.id);
    const palette = officeAgentPalette(agent);
    const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
        ? `costume-${safeString(agent.costume)}`
        : '';
    const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
    const room = officeRoomById(officeDraftRoomIdForAgent(agent));
    const activeTask = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === safeString(agent.id) && entry.status !== 'done');
    const chatModelLabel = officeDraftAgentChatModelLabel(agent);
    const pending = Boolean(agent.officeChatPending);
    const errorText = safeString(agent.officeChatError);
    const history = officeDraftAgentChatHistory(agent);
    const messageMarkup = history.length ? history.map((entry) => {
        const user = safeString(entry.role) === 'user';
        return `
            <div data-office-agent-chat-message="${user ? 'user' : 'agent'}" style="display:grid;justify-items:${user ? 'end' : 'start'};gap:3px;min-width:0;overflow:hidden;">
                <span style="display:block;box-sizing:border-box;max-width:96%;min-width:0;padding:9px 11px;border-radius:12px;background:${user ? 'rgba(75,121,204,0.36)' : 'rgba(12,19,31,0.92)'};border:1px solid ${user ? 'rgba(146,188,255,0.28)' : 'rgba(116,141,181,0.22)'};color:rgba(238,244,252,0.94);font-size:0.8rem;line-height:1.42;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;overflow:hidden;">${escapeHtml(entry.text)}</span>
                <span style="font-size:0.56rem;color:rgba(185,200,222,0.52);">${escapeHtml(entry.timeLabel || '')}</span>
            </div>
        `;
    }).join('') : `
        <div data-office-agent-chat-empty="1" style="padding:12px;border-radius:12px;border:1px dashed rgba(116,141,181,0.24);background:rgba(5,10,18,0.44);color:rgba(198,210,226,0.62);font-size:0.74rem;line-height:1.4;">Send a message to start this agent's local chat memory.</div>
    `;
    const pendingMarkup = pending ? `
        <div data-office-agent-chat-pending="1" style="justify-self:start;padding:7px 10px;border-radius:999px;background:rgba(72,111,172,0.24);border:1px solid rgba(129,182,255,0.25);color:rgba(218,232,252,0.82);font-size:0.68rem;font-weight:800;">Thinking...</div>
    ` : '';
    const errorMarkup = errorText ? `
        <div data-office-agent-chat-error="1" style="padding:8px 10px;border-radius:12px;border:1px solid rgba(248,112,112,0.28);background:rgba(88,25,31,0.42);color:rgba(255,214,214,0.9);font-size:0.72rem;line-height:1.35;">${escapeHtml(errorText)}</div>
    ` : '';
    panel.style.display = 'grid';
    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
            <strong style="font-size:0.9rem;letter-spacing:0.06em;text-transform:uppercase;">Agent Chat</strong>
            <button type="button" data-office-agent-chat-close="1" style="padding:7px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Close</button>
        </div>
        <section style="display:grid;grid-template-columns:68px minmax(0,1fr);gap:10px;align-items:center;padding:10px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);">
            <span style="display:flex;align-items:center;justify-content:center;width:68px;height:66px;border-radius:14px;background:rgba(5,10,18,0.58);overflow:hidden;">
                <span style="transform:scale(0.82);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
            </span>
            <span style="display:grid;gap:4px;min-width:0;">
                <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.94rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.72rem;color:rgba(196,211,231,0.74);">${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span>
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.66rem;color:rgba(169,210,255,0.72);">Chat model: ${escapeHtml(chatModelLabel)}</span>
                <span style="font-size:0.66rem;line-height:1.32;color:rgba(196,211,231,0.62);">${escapeHtml(activeTask?.title || agent.lastMissionSummary || agent.lastOfficeChatSummary || 'Available.')}</span>
            </span>
        </section>
        <div data-office-agent-chat-log="1" style="display:grid;align-content:start;gap:10px;min-height:220px;max-height:420px;overflow-y:auto;overflow-x:hidden;padding:2px 4px 6px 2px;overscroll-behavior:contain;min-width:0;">${messageMarkup}${pendingMarkup}</div>
        ${errorMarkup}
        <form data-office-agent-chat-form="1" style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end;">
            <textarea data-office-agent-chat-input="1" rows="3" placeholder="Message ${escapeHtml(agent.name || 'agent')}"${pending ? ' disabled' : ''} style="box-sizing:border-box;width:100%;min-width:0;min-height:72px;max-height:150px;resize:vertical;padding:10px 11px;border-radius:12px;border:1px solid rgba(116,141,181,0.26);background:rgba(5,10,18,0.82);color:rgba(242,246,252,0.94);font-size:0.8rem;line-height:1.4;overflow-x:hidden;overflow-y:auto;white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHtml(state.agentChatDraftById[agent.id] || '')}</textarea>
            <button type="submit" data-office-agent-chat-send="1"${pending ? ' disabled' : ''} style="height:42px;padding:0 13px;border-radius:12px;border:1px solid rgba(129,182,255,0.38);background:${pending ? 'rgba(48,60,82,0.74)' : 'rgba(48,88,154,0.74)'};color:rgba(246,250,255,0.96);font-weight:900;">${pending ? '...' : 'Send'}</button>
        </form>
    `;
    officeBindDraftAgentChatPanel(panel);
    const log = panel.querySelector('[data-office-agent-chat-log="1"]');
    if (log instanceof HTMLElement) {
        log.scrollTop = log.scrollHeight;
    }
    if (options?.focusInput) {
        window.setTimeout(() => {
            const input = panel.querySelector('[data-office-agent-chat-input="1"]');
            if (input instanceof HTMLTextAreaElement) {
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
            }
        }, 0);
    }
}

function officeRenderDraftAgentRosterPanel() {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    const state = officeEnsureDraftMapState();
    let panel = officeSceneWrap.querySelector('[data-office-agent-roster-panel="1"]');
    if (!(panel instanceof HTMLElement)) {
        panel = document.createElement('aside');
        panel.dataset.officeAgentRosterPanel = '1';
        officeSceneWrap.appendChild(panel);
    }
    if (!state.rosterOpen || !officeState) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
    }
    const agents = Array.isArray(officeState.agents) ? officeState.agents : [];
    const expandedId = safeString(state.expandedRosterAgentId);
    const expandedAgent = expandedId ? agents.find((agent) => safeString(agent?.id) === expandedId) : null;
    const agentCard = (agent) => {
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
            ? `costume-${safeString(agent.costume)}`
            : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        return `
            <button type="button" data-office-roster-expand="${escapeHtml(agent.id)}" style="display:grid;gap:7px;align-items:center;justify-items:center;min-width:0;padding:9px 7px;border-radius:12px;border:1px solid rgba(116,141,181,0.2);background:rgba(12,19,31,0.86);color:inherit;text-align:center;cursor:pointer;">
                <span style="display:flex;align-items:center;justify-content:center;width:62px;height:58px;border-radius:14px;background:rgba(5,10,18,0.58);overflow:hidden;">
                    <span style="transform:scale(0.78);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
                </span>
                <span style="display:block;width:100%;min-width:0;">
                    <strong style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.74rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                    <span style="display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:0.58rem;color:rgba(196,211,231,0.72);">${escapeHtml(room?.label || 'Office')}</span>
                </span>
            </button>
        `;
    };
    const rosterGrid = agents.map(agentCard).join('') || '<div style="grid-column:1/-1;padding:12px;border-radius:12px;background:rgba(9,15,26,0.72);color:rgba(198,210,226,0.72);font-size:0.76rem;">No agents yet.</div>';
    const detailMarkup = expandedAgent ? (() => {
        const agent = expandedAgent;
        const palette = officeAgentPalette(agent);
        const costumeClass = safeString(agent?.costume) && safeString(agent.costume) !== 'none'
            ? `costume-${safeString(agent.costume)}`
            : '';
        const paletteStyle = `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`;
        const task = officeState.tasks.find((entry) => safeString(entry.assignedAgentId) === safeString(agent.id) && entry.status !== 'done');
        const room = officeRoomById(officeDraftRoomIdForAgent(agent));
        const optionMarkup = (options) => options.map((costume) => `
            <option value="${escapeHtml(costume)}"${safeString(agent.costume || 'none') === costume ? ' selected' : ''}>${escapeHtml(costume === 'none' ? 'none' : officeTaskTitle(costume))}</option>
        `).join('');
        const hatOptions = optionMarkup(['none', 'cap', 'visor', 'headset']);
        const accessoryOptions = optionMarkup(['none', 'bowtie', 'scarf', 'badge', 'satchel']);
        const heldOptions = optionMarkup(['none', 'tablet', 'wrench', 'mug', 'toolbelt']);
        const chatProfile = officeDraftAgentChatProfile(agent);
        const chatModelId = officeDraftAgentChatModelId(agent, chatProfile);
        const chatProfileOptions = officeDraftAgentChatProfileOptionsMarkup(chatProfile);
        return `
            <div style="display:grid;gap:12px;">
                <button type="button" data-office-roster-back="1" style="justify-self:start;padding:6px 10px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(9,15,26,0.82);color:rgba(235,242,252,0.92);font-weight:800;">Back to Agents</button>
                <section style="display:grid;grid-template-columns:96px 1fr;gap:12px;align-items:center;padding:12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(12,19,31,0.86);">
                    <span style="display:flex;align-items:center;justify-content:center;width:96px;height:94px;border-radius:16px;background:rgba(5,10,18,0.58);overflow:hidden;">
                        <span style="transform:scale(1.08);transform-origin:center;">${officePixelAgentMarkup(costumeClass, paletteStyle)}</span>
                    </span>
                    <span style="display:grid;gap:4px;min-width:0;">
                        <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:1.04rem;color:rgba(242,246,252,0.96);">${escapeHtml(agent.name || 'Agent')}</strong>
                        <span style="font-size:0.76rem;color:rgba(196,211,231,0.74);">${escapeHtml(agent.specialty || 'Generalist')} - ${escapeHtml(room?.label || 'Office')}</span>
                        <span style="font-size:0.7rem;line-height:1.4;color:rgba(196,211,231,0.66);">${escapeHtml(task?.title || agent.lastMissionSummary || 'Available for the next task.')}</span>
                    </span>
                </section>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Name
                    <input data-office-roster-field="name" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(agent.name)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                </label>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Specialty
                    <input data-office-roster-field="specialty" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(agent.specialty || 'Generalist')}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                </label>
                <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Personality
                    <textarea data-office-roster-field="personality" data-office-roster-agent-id="${escapeHtml(agent.id)}" rows="4" style="width:100%;resize:vertical;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${escapeHtml(agent.personality || 'Helpful, direct, and persistent.')}</textarea>
                </label>
                <section style="display:grid;gap:8px;padding:10px;border-radius:12px;border:1px solid rgba(116,141,181,0.18);background:rgba(5,10,18,0.38);">
                    <strong style="font-size:0.72rem;color:rgba(218,232,252,0.86);">Chat Model</strong>
                    <label style="display:grid;gap:4px;font-size:0.68rem;color:rgba(198,210,226,0.72);">Profile
                        <select data-office-roster-field="chatProfile" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${chatProfileOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.68rem;color:rgba(198,210,226,0.72);">Model ID
                        <input data-office-roster-field="chatModelId" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(chatModelId)}" placeholder="${escapeHtml(officeDraftDefaultChatModelId(chatProfile) || 'default')}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);" />
                    </label>
                    <span style="font-size:0.62rem;line-height:1.35;color:rgba(182,199,224,0.58);">Used only for talking to this agent in the office. Task-specialist routing stays separate.</span>
                </section>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Body Color
                        <input type="color" data-office-roster-field="color" data-office-roster-agent-id="${escapeHtml(agent.id)}" value="${/^#[0-9a-f]{6}$/i.test(safeString(agent.color)) ? escapeHtml(agent.color) : '#9ad8ff'}" style="width:100%;height:36px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);" />
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Hat / Headset
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${hatOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Glasses / Badge
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${accessoryOptions}</select>
                    </label>
                    <label style="display:grid;gap:4px;font-size:0.7rem;color:rgba(198,210,226,0.72);">Held Item / Arms
                        <select data-office-roster-field="costume" data-office-roster-agent-id="${escapeHtml(agent.id)}" style="width:100%;padding:8px 9px;border-radius:10px;border:1px solid rgba(116,141,181,0.24);background:rgba(5,10,18,0.72);color:rgba(242,246,252,0.94);">${heldOptions}</select>
                    </label>
                </div>
            </div>
        `;
    })() : '';
    panel.style.display = 'block';
    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;">
            <strong style="font-size:0.92rem;letter-spacing:0.04em;text-transform:uppercase;">Agent Roster</strong>
            <span style="font-size:0.72rem;color:rgba(202,214,230,0.72);">${agents.length} agents</span>
        </div>
        ${expandedAgent ? detailMarkup : `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;">${rosterGrid}</div>`}
    `;
    officeBindDraftRosterPanel(panel);
}

function officeDraftSpaceCenter(space) {
    return {
        x: Math.round((Number(space?.x) || 0) + ((Number(space?.width) || 0) / 2)),
        y: Math.round((Number(space?.y) || 0) + ((Number(space?.height) || 0) / 2)),
    };
}

const OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH = 154;
const OFFICE_DRAFT_HALLWAY_OUTER_WIDTH = 182;
const OFFICE_DRAFT_HALLWAY_SCAN_STEP = 56;
const OFFICE_DRAFT_AGENT_NAV_VERSION = 13;
const OFFICE_DRAFT_AGENT_ROUTE_EPSILON = 8;
const OFFICE_DRAFT_AGENT_WAYPOINT_EPSILON = 14;
const OFFICE_DRAFT_AGENT_ROOM_MARGIN = 92;
const OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN = 54;
const OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP = 44;
const OFFICE_DRAFT_AGENT_LOCAL_SAMPLE_STEP = 34;
const OFFICE_DRAFT_AGENT_LOCAL_CANDIDATE_LIMIT = 76;
const OFFICE_DRAFT_AGENT_LOCAL_EDGE_LIMIT = 1400;
const OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT = 900;
const OFFICE_DRAFT_AGENT_HALLWAY_GRAPH_NODE_LIMIT = 700;
const OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT = 180;
const OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS = 18;
const OFFICE_DRAFT_AGENT_STUCK_REPLAN_MS = 900;
const OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS = 1600;
const OFFICE_DRAFT_AGENT_BLOCKED_TARGET_MS = 30000;
const OFFICE_DRAFT_AGENT_SPEED_MIN = 22;
const OFFICE_DRAFT_AGENT_SPEED_MAX = 58;
const OFFICE_DRAFT_AGENT_SPEED_SCALE = 18;
const OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS = 48;
const OFFICE_DRAFT_AGENT_INPUT_RENDER_INTERVAL_MS = 96;
const OFFICE_DRAFT_AGENT_RENDER_BACKOFF_MAX_MS = 180;
const OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS = 34;
const OFFICE_DRAFT_AGENT_LAYER_CHUNK_BUDGET_MS = 18;
const OFFICE_DRAFT_AGENT_LAYER_FORCE_CHUNK_BUDGET_MS = 28;
const OFFICE_DRAFT_AGENT_ROUTE_PLANS_PER_RENDER = 1;
const OFFICE_DRAFT_AGENT_PAN_QUIET_MS = 260;
const OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS = 320;
const OFFICE_DRAFT_AGENT_POINTER_QUIET_MS = 340;
const OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS = 900;
const OFFICE_DRAFT_AGENT_ROUTE_PLAN_MIN_INTERVAL_MS = 1600;
const OFFICE_DRAFT_AGENT_ROUTE_PLAN_BOOT_QUIET_MS = 2800;
const OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS = 4200;
const OFFICE_DRAFT_AGENT_WANDER_DWELL_MAX_MS = 14500;
const OFFICE_DRAFT_AGENT_MANUAL_PIN_MS = 12500;
const OFFICE_DRAFT_AGENT_NAME_ZOOM = 0.44;
const OFFICE_DRAFT_AGENT_STATUS_ZOOM = 0.88;
const OFFICE_DRAFT_AGENT_PROP_ZOOM = 0.78;
const OFFICE_DRAFT_AGENT_HITBOX_W = 148;
const OFFICE_DRAFT_AGENT_HITBOX_H = 178;
const OFFICE_DRAFT_AGENT_ANIMATIONS = Object.freeze([
    'idle',
    'walking',
    'working',
    'drinking',
    'sitting',
    'paused',
    'talking',
    'dragging',
    'dropped',
    'thinking',
    'celebrating',
]);

function officeDraftSpaceRect(space) {
    const x = Number(space?.x) || 0;
    const y = Number(space?.y) || 0;
    const width = Math.max(320, Number(space?.width) || 0);
    const height = Math.max(240, Number(space?.height) || 0);
    return {
        id: safeString(space?.id),
        x,
        y,
        width,
        height,
        left: x,
        top: y,
        right: x + width,
        bottom: y + height,
        centerX: x + (width / 2),
        centerY: y + (height / 2),
        space,
    };
}

function officeDraftClusterSpaceRows(spacesRaw) {
    const rects = (Array.isArray(spacesRaw) ? spacesRaw : [])
        .map(officeDraftSpaceRect)
        .filter((rect) => rect.id)
        .sort((a, b) => (a.centerY - b.centerY) || (a.centerX - b.centerX));
    if (!rects.length) return [];
    const averageHeight = rects.reduce((sum, rect) => sum + rect.height, 0) / rects.length;
    const rowThreshold = Math.max(760, Math.min(1120, averageHeight * 0.78));
    const rows = [];
    rects.forEach((rect) => {
        const row = rows[rows.length - 1];
        if (!row || Math.abs(rect.centerY - row.centerY) > rowThreshold) {
            rows.push({
                rects: [rect],
                top: rect.top,
                bottom: rect.bottom,
                left: rect.left,
                right: rect.right,
                centerY: rect.centerY,
            });
            return;
        }
        row.rects.push(rect);
        row.top = Math.min(row.top, rect.top);
        row.bottom = Math.max(row.bottom, rect.bottom);
        row.left = Math.min(row.left, rect.left);
        row.right = Math.max(row.right, rect.right);
        row.centerY = row.rects.reduce((sum, item) => sum + item.centerY, 0) / row.rects.length;
    });
    return rows.map((row, index) => ({
        ...row,
        id: `row-${index}`,
        rects: row.rects.sort((a, b) => a.centerX - b.centerX),
    }));
}

function officeDraftSegmentIntersectsRect(segment, rect, margin = 0) {
    const minX = Math.min(segment.x1, segment.x2);
    const maxX = Math.max(segment.x1, segment.x2);
    const minY = Math.min(segment.y1, segment.y2);
    const maxY = Math.max(segment.y1, segment.y2);
    return maxX >= (rect.left - margin)
        && minX <= (rect.right + margin)
        && maxY >= (rect.top - margin)
        && minY <= (rect.bottom + margin);
}

function officeDraftRoomClearanceForVertical(x, y1, y2, rects, margin = 0) {
    let nearest = Number.POSITIVE_INFINITY;
    let collisions = 0;
    const segment = { x1: x, y1, x2: x, y2 };
    rects.forEach((rect) => {
        if (!officeDraftSegmentIntersectsRect(segment, rect, margin)) return;
        collisions += 1;
        const edgeDistance = Math.min(Math.abs(x - rect.left), Math.abs(x - rect.right));
        nearest = Math.min(nearest, edgeDistance);
    });
    return {
        collisions,
        clearance: Number.isFinite(nearest) ? nearest : 9999,
    };
}

function officeDraftChooseVerticalConnectorX(laneA, laneB, rects) {
    const y1 = Math.min(laneA.y, laneB.y);
    const y2 = Math.max(laneA.y, laneB.y);
    const minX = Math.max(220, Math.min(laneA.minX, laneB.minX));
    const maxX = Math.min(OFFICE_DRAFT_MAP_SIZE - 220, Math.max(laneA.maxX, laneB.maxX));
    const attachedDoors = [...(laneA.doorXs || []), ...(laneB.doorXs || [])];
    const target = attachedDoors.length
        ? attachedDoors.reduce((sum, value) => sum + value, 0) / attachedDoors.length
        : ((minX + maxX) / 2);
    const scanMargin = (OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH / 2) + 12;
    let best = {
        x: Math.round(officeClamp(target, minX, maxX)),
        score: Number.POSITIVE_INFINITY,
    };
    for (let x = minX; x <= maxX; x += OFFICE_DRAFT_HALLWAY_SCAN_STEP) {
        const px = Math.round(x);
        const probe = officeDraftRoomClearanceForVertical(px, y1, y2, rects, scanMargin);
        const centerPenalty = Math.abs(px - target);
        const edgePenalty = Math.min(Math.abs(px - minX), Math.abs(maxX - px)) < 180 ? 260 : 0;
        const score = (probe.collisions * 100000) + centerPenalty + edgePenalty - Math.min(420, probe.clearance);
        if (score < best.score) {
            best = { x: px, score };
        }
    }
    [minX, maxX, target].forEach((candidate) => {
        const px = Math.round(officeClamp(candidate, minX, maxX));
        const probe = officeDraftRoomClearanceForVertical(px, y1, y2, rects, scanMargin);
        const score = (probe.collisions * 100000) + Math.abs(px - target) - Math.min(420, probe.clearance);
        if (score < best.score) {
            best = { x: px, score };
        }
    });
    return best.x;
}

function officeDraftChooseDoorXForRect(rect, edge) {
    const minX = Math.round(officeClamp(rect.left + 190, rect.left + 92, rect.right - 92));
    const maxX = Math.round(officeClamp(rect.right - 190, rect.left + 92, rect.right - 92));
    const fallbackX = Math.round(officeClamp(rect.centerX, minX, maxX));
    const space = rect?.space;
    if (!space) return fallbackX;
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const interiorY = Math.round(edge === 'top' ? bounds.top : bounds.bottom);
    const doorY = Math.round(edge === 'top' ? rect.top : rect.bottom);
    const probe = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const probeCandidates = [
        probe,
        { x: bounds.left, y: bounds.top },
        { x: bounds.right, y: bounds.top },
        { x: bounds.left, y: bounds.bottom },
        { x: bounds.right, y: bounds.bottom },
        { x: bounds.left + ((bounds.right - bounds.left) * 0.28), y: bounds.top + ((bounds.bottom - bounds.top) * 0.5) },
        { x: bounds.left + ((bounds.right - bounds.left) * 0.72), y: bounds.top + ((bounds.bottom - bounds.top) * 0.5) },
    ]
        .map((point) => officeDraftClampWorldPointToWalkable(point, space, obstacles))
        .filter((point, pointIndex, points) => (
            officeDraftPointWalkableInSpace(point, space, obstacles)
            && points.findIndex((entry) => officeDraftPointKey(entry, 8) === officeDraftPointKey(point, 8)) === pointIndex
        ));
    const candidates = [fallbackX, minX, maxX];
    for (let x = minX; x <= maxX; x += OFFICE_DRAFT_HALLWAY_SCAN_STEP) {
        candidates.push(Math.round(x));
    }
    obstacles.forEach((obstacle) => {
        candidates.push(
            Math.round(obstacle.left - OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP),
            Math.round(obstacle.right + OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP),
        );
    });
    let best = { x: fallbackX, score: Number.POSITIVE_INFINITY };
    const seen = new Set();
    candidates.forEach((candidateRaw) => {
        const x = Math.round(officeClamp(candidateRaw, minX, maxX));
        if (seen.has(x)) return;
        seen.add(x);
        const interior = { x, y: interiorY };
        const door = { x, y: doorY };
        const walkable = officeDraftPointWalkableInSpace(interior, space, obstacles);
        const corridorClear = !obstacles.some((obstacle) => officeDraftLineSegmentIntersectsRect(interior, door, obstacle));
        const interiorClear = walkable && officeDraftSegmentClearInSpace(probe, interior, space, obstacles);
        const reachableProbeCount = walkable
            ? probeCandidates.filter((entry) => officeDraftSegmentClearInSpace(entry, interior, space, obstacles)).length
            : 0;
        const blockedLaneCount = obstacles.filter((obstacle) => (
            x >= obstacle.left - 10
            && x <= obstacle.right + 10
            && (edge === 'top'
                ? obstacle.top > interiorY && obstacle.top < bounds.bottom
                : obstacle.bottom < interiorY && obstacle.bottom > bounds.top)
        )).length;
        const clearance = officeDraftPointObstacleClearance(interior, obstacles);
        const edgePenalty = Math.min(Math.abs(x - minX), Math.abs(maxX - x)) < 56 ? 180 : 0;
        const score = (walkable ? 0 : 100000)
            + (corridorClear ? 0 : 50000)
            + (interiorClear ? 0 : 1800)
            + (blockedLaneCount * 4200)
            + ((probeCandidates.length - reachableProbeCount) * 520)
            + (Math.max(0, 132 - clearance) * 42)
            + Math.abs(x - rect.centerX)
            + edgePenalty
            - Math.min(260, clearance);
        if (score < best.score) {
            best = { x, score };
        }
    });
    return best.x;
}

function officeDraftAddNetworkNode(nodes, point, kind = 'joint', id = '') {
    const x = Math.round(Number(point?.x) || 0);
    const y = Math.round(Number(point?.y) || 0);
    const key = `${x},${y}`;
    if (nodes.has(key)) return nodes.get(key);
    const node = { id: id || `node-${nodes.size + 1}`, x, y, kind };
    nodes.set(key, node);
    return node;
}

function officeDraftSegmentPath(segments) {
    return (Array.isArray(segments) ? segments : [])
        .filter((segment) => segment && Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1) > 2)
        .map((segment) => `M ${Math.round(segment.x1)} ${Math.round(segment.y1)} L ${Math.round(segment.x2)} ${Math.round(segment.y2)}`)
        .join(' ');
}

function officeDraftHallwayNetworkSignature(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw.filter(Boolean) : [];
    return spaces
        .map((space) => {
            const rect = officeDraftSpaceRect(space);
            const assetSignature = (Array.isArray(space?.assets) ? space.assets : [])
                .filter((asset) => officeDraftAssetBlocksNavigation(asset))
                .map((asset) => [
                    safeString(asset?.id),
                    safeString(asset?.type),
                    Math.round(Number(asset?.x) || 0),
                    Math.round(Number(asset?.y) || 0),
                    officeDraftClampAssetScale(asset?.scale),
                    officeDraftNormalizeRotation(asset?.rotation),
                ].join(','))
                .join(';');
            return [
                safeString(rect.id),
                Math.round(rect.left),
                Math.round(rect.top),
                Math.round(rect.right),
                Math.round(rect.bottom),
                assetSignature,
            ].join(':');
        })
        .join('|');
}

function officeDraftAutoHallwayNetwork(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw.filter(Boolean) : [];
    const cacheState = officeDraftMapState && spacesRaw === officeDraftMapState.spaces
        ? officeDraftMapState
        : null;
    const signature = cacheState ? officeDraftHallwayNetworkSignature(spaces) : '';
    if (
        cacheState
        && cacheState.hallwayNetworkCache
        && cacheState.hallwayNetworkCache.signature === signature
        && cacheState.hallwayNetworkCache.network
    ) {
        return cacheState.hallwayNetworkCache.network;
    }
    const rects = spaces.map(officeDraftSpaceRect).filter((rect) => rect.id);
    const rows = officeDraftClusterSpaceRows(spaces);
    const lanes = [];
    if (rows.length >= 2) {
        for (let index = 0; index < rows.length - 1; index += 1) {
            const current = rows[index];
            const next = rows[index + 1];
            const gap = next.top - current.bottom;
            const laneY = Math.round(gap > 140
                ? current.bottom + (gap / 2)
                : current.centerY + ((next.centerY - current.centerY) / 2));
            lanes.push({
                id: `hall-row-${index}`,
                y: Math.round(officeClamp(laneY, 260, OFFICE_DRAFT_MAP_SIZE - 260)),
                minX: Math.round(Math.max(220, Math.min(current.left, next.left) - 360)),
                maxX: Math.round(Math.min(OFFICE_DRAFT_MAP_SIZE - 220, Math.max(current.right, next.right) + 360)),
                doorXs: [],
            });
        }
    }
    if (!lanes.length && rects.length) {
        const bounds = rects.reduce((acc, rect) => ({
            left: Math.min(acc.left, rect.left),
            right: Math.max(acc.right, rect.right),
            top: Math.min(acc.top, rect.top),
            bottom: Math.max(acc.bottom, rect.bottom),
        }), {
            left: Number.POSITIVE_INFINITY,
            right: Number.NEGATIVE_INFINITY,
            top: Number.POSITIVE_INFINITY,
            bottom: Number.NEGATIVE_INFINITY,
        });
        lanes.push({
            id: 'hall-row-0',
            y: Math.round(officeClamp(bounds.bottom + 240, 260, OFFICE_DRAFT_MAP_SIZE - 260)),
            minX: Math.round(Math.max(220, bounds.left - 360)),
            maxX: Math.round(Math.min(OFFICE_DRAFT_MAP_SIZE - 220, bounds.right + 360)),
            doorXs: [],
        });
    }

    const laneForRect = (rect) => {
        if (!lanes.length) return null;
        const candidates = lanes
            .map((lane) => {
                const outside = lane.y <= rect.top - 64 || lane.y >= rect.bottom + 64;
                return {
                    lane,
                    outside,
                    distance: Math.min(Math.abs(lane.y - rect.top), Math.abs(lane.y - rect.bottom)),
                };
            })
            .sort((a, b) => {
                if (a.outside !== b.outside) return a.outside ? -1 : 1;
                return a.distance - b.distance;
            });
        return candidates[0]?.lane || lanes[0];
    };

    const doors = new Map();
    rects.forEach((rect) => {
        const lane = laneForRect(rect);
        if (!lane) return;
        const edge = lane.y < rect.centerY ? 'top' : 'bottom';
        const doorX = officeDraftChooseDoorXForRect(rect, edge);
        const doorY = Math.round(edge === 'top' ? rect.top : rect.bottom);
        const normalY = edge === 'top' ? -1 : 1;
        const outsideY = Math.round(lane.y);
        const door = {
            edge,
            localX: Math.round(doorX - rect.x),
            localY: Math.round(doorY - rect.y),
            worldX: doorX,
            worldY: doorY,
            outsideX: doorX,
            outsideY,
            normalX: 0,
            normalY,
            laneId: lane.id,
            spaceId: rect.id,
        };
        doors.set(rect.id, door);
        lane.minX = Math.min(lane.minX, doorX - 220);
        lane.maxX = Math.max(lane.maxX, doorX + 220);
        lane.doorXs.push(doorX);
    });

    const connectors = [];
    for (let index = 0; index < lanes.length - 1; index += 1) {
        const laneA = lanes[index];
        const laneB = lanes[index + 1];
        const x = officeDraftChooseVerticalConnectorX(laneA, laneB, rects);
        connectors.push({
            id: `hall-connector-${index}`,
            x,
            y1: Math.min(laneA.y, laneB.y),
            y2: Math.max(laneA.y, laneB.y),
        });
        laneA.minX = Math.min(laneA.minX, x - 180);
        laneA.maxX = Math.max(laneA.maxX, x + 180);
        laneB.minX = Math.min(laneB.minX, x - 180);
        laneB.maxX = Math.max(laneB.maxX, x + 180);
    }

    const segments = [];
    const nodes = new Map();
    lanes.forEach((lane) => {
        const x1 = Math.round(officeClamp(lane.minX, 180, OFFICE_DRAFT_MAP_SIZE - 180));
        const x2 = Math.round(officeClamp(lane.maxX, 180, OFFICE_DRAFT_MAP_SIZE - 180));
        const segment = { kind: 'trunk', orientation: 'h', x1, y1: lane.y, x2, y2: lane.y, laneId: lane.id };
        segments.push(segment);
        officeDraftAddNetworkNode(nodes, { x: x1, y: lane.y }, 'end');
        officeDraftAddNetworkNode(nodes, { x: x2, y: lane.y }, 'end');
    });
    connectors.forEach((connector) => {
        const segment = {
            kind: 'connector',
            orientation: 'v',
            x1: connector.x,
            y1: connector.y1,
            x2: connector.x,
            y2: connector.y2,
            connectorId: connector.id,
        };
        segments.push(segment);
        officeDraftAddNetworkNode(nodes, { x: connector.x, y: connector.y1 }, 'junction', `${connector.id}-a`);
        officeDraftAddNetworkNode(nodes, { x: connector.x, y: connector.y2 }, 'junction', `${connector.id}-b`);
    });
    doors.forEach((door) => {
        segments.push({
            kind: 'door',
            orientation: door.normalY ? 'v' : 'h',
            x1: door.worldX,
            y1: door.worldY,
            x2: door.outsideX,
            y2: door.outsideY,
            spaceId: door.spaceId,
        });
        officeDraftAddNetworkNode(nodes, { x: door.outsideX, y: door.outsideY }, 'door', `${door.spaceId}-hall`);
    });

    const network = {
        lanes,
        connectors,
        doors,
        segments,
        nodes: [...nodes.values()],
    };
    if (cacheState) {
        cacheState.hallwayNetworkCache = { signature, network };
    }
    return network;
}

function officeDraftPointKey(point, precision = 1) {
    const scale = Math.max(1, Number(precision) || 1);
    const x = Math.round((Number(point?.x) || 0) / scale) * scale;
    const y = Math.round((Number(point?.y) || 0) / scale) * scale;
    return `${Math.round(x)},${Math.round(y)}`;
}

function officeDraftRouteSolveDeadline(budgetMs = OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS) {
    return performance.now() + Math.max(4, Number(budgetMs) || OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS);
}

function officeDraftRouteDeadlineExceeded(deadlineRaw) {
    const deadline = Number(deadlineRaw) || 0;
    return deadline > 0 && performance.now() > deadline;
}

function officeDraftSegmentLength(segment) {
    if (!segment) return 0;
    return Math.hypot((Number(segment.x2) || 0) - (Number(segment.x1) || 0), (Number(segment.y2) || 0) - (Number(segment.y1) || 0));
}

function officeDraftPointOnSegment(point, segment, tolerance = 1) {
    if (!point || !segment) return false;
    const x = Number(point.x) || 0;
    const y = Number(point.y) || 0;
    const x1 = Number(segment.x1) || 0;
    const y1 = Number(segment.y1) || 0;
    const x2 = Number(segment.x2) || 0;
    const y2 = Number(segment.y2) || 0;
    const minX = Math.min(x1, x2) - tolerance;
    const maxX = Math.max(x1, x2) + tolerance;
    const minY = Math.min(y1, y2) - tolerance;
    const maxY = Math.max(y1, y2) + tolerance;
    if (x < minX || x > maxX || y < minY || y > maxY) return false;
    const dx = x2 - x1;
    const dy = y2 - y1;
    if (Math.abs(dx) < 0.001) return Math.abs(x - x1) <= tolerance;
    if (Math.abs(dy) < 0.001) return Math.abs(y - y1) <= tolerance;
    const cross = Math.abs(((x - x1) * dy) - ((y - y1) * dx));
    return cross <= tolerance * Math.max(1, Math.hypot(dx, dy));
}

function officeDraftProjectPointToSegment(point, segment) {
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    const x1 = Number(segment?.x1) || 0;
    const y1 = Number(segment?.y1) || 0;
    const x2 = Number(segment?.x2) || 0;
    const y2 = Number(segment?.y2) || 0;
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lengthSq = (dx * dx) + (dy * dy);
    if (lengthSq <= 0.001) return { x: Math.round(x1), y: Math.round(y1), distance: Math.hypot(x - x1, y - y1) };
    const t = officeClamp((((x - x1) * dx) + ((y - y1) * dy)) / lengthSq, 0, 1);
    const px = x1 + (dx * t);
    const py = y1 + (dy * t);
    return {
        x: Math.round(px),
        y: Math.round(py),
        distance: Math.hypot(x - px, y - py),
    };
}

function officeDraftSegmentIntersectionPoint(a, b) {
    if (!a || !b) return null;
    const aHorizontal = safeString(a.orientation) === 'h' || Math.abs((Number(a.y2) || 0) - (Number(a.y1) || 0)) < 0.001;
    const bHorizontal = safeString(b.orientation) === 'h' || Math.abs((Number(b.y2) || 0) - (Number(b.y1) || 0)) < 0.001;
    if (aHorizontal === bHorizontal) return null;
    const h = aHorizontal ? a : b;
    const v = aHorizontal ? b : a;
    const y = Number(h.y1) || 0;
    const x = Number(v.x1) || 0;
    const hMin = Math.min(Number(h.x1) || 0, Number(h.x2) || 0) - 1;
    const hMax = Math.max(Number(h.x1) || 0, Number(h.x2) || 0) + 1;
    const vMin = Math.min(Number(v.y1) || 0, Number(v.y2) || 0) - 1;
    const vMax = Math.max(Number(v.y1) || 0, Number(v.y2) || 0) + 1;
    if (x < hMin || x > hMax || y < vMin || y > vMax) return null;
    return { x: Math.round(x), y: Math.round(y) };
}

function officeDraftNearestHallwayPoint(point, networkRaw) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments.filter((segment) => officeDraftSegmentLength(segment) > 2) : [];
    let best = null;
    segments.forEach((segment) => {
        const projected = officeDraftProjectPointToSegment(point, segment);
        if (!best || projected.distance < best.distance) {
            best = { ...projected, segment };
        }
    });
    return best || { x: Number(point?.x) || 0, y: Number(point?.y) || 0, distance: 0, segment: null };
}

function officeDraftBuildHallwayRouteGraph(networkRaw, extraPointsRaw = []) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const segments = Array.isArray(network?.segments) ? network.segments.filter((segment) => officeDraftSegmentLength(segment) > 2) : [];
    const pointByKey = new Map();
    const addPoint = (point) => {
        if (!point) return null;
        const normalized = {
            x: Math.round(Number(point.x) || 0),
            y: Math.round(Number(point.y) || 0),
        };
        const key = officeDraftPointKey(normalized);
        if (!pointByKey.has(key)) pointByKey.set(key, normalized);
        return pointByKey.get(key);
    };
    segments.forEach((segment) => {
        addPoint({ x: segment.x1, y: segment.y1 });
        addPoint({ x: segment.x2, y: segment.y2 });
    });
    for (let i = 0; i < segments.length; i += 1) {
        for (let j = i + 1; j < segments.length; j += 1) {
            addPoint(officeDraftSegmentIntersectionPoint(segments[i], segments[j]));
        }
    }
    (Array.isArray(extraPointsRaw) ? extraPointsRaw : []).forEach(addPoint);
    if (pointByKey.size > OFFICE_DRAFT_AGENT_HALLWAY_GRAPH_NODE_LIMIT) {
        return new Map();
    }
    const graph = new Map();
    const ensureNode = (point) => {
        const normalized = addPoint(point);
        if (!normalized) return '';
        const key = officeDraftPointKey(normalized);
        if (!graph.has(key)) {
            graph.set(key, {
                id: key,
                x: normalized.x,
                y: normalized.y,
                links: new Map(),
            });
        }
        return key;
    };
    const connect = (a, b) => {
        const aId = ensureNode(a);
        const bId = ensureNode(b);
        if (!aId || !bId || aId === bId) return;
        const aNode = graph.get(aId);
        const bNode = graph.get(bId);
        const distance = Math.hypot(aNode.x - bNode.x, aNode.y - bNode.y);
        if (distance <= 0.001) return;
        aNode.links.set(bId, distance);
        bNode.links.set(aId, distance);
    };
    segments.forEach((segment) => {
        const points = [...pointByKey.values()]
            .filter((point) => officeDraftPointOnSegment(point, segment, 2))
            .sort((a, b) => {
                if (safeString(segment.orientation) === 'v' || Math.abs((Number(segment.x2) || 0) - (Number(segment.x1) || 0)) < 0.001) {
                    return a.y - b.y;
                }
                return a.x - b.x;
            });
        for (let index = 0; index < points.length - 1; index += 1) {
            connect(points[index], points[index + 1]);
        }
    });
    return graph;
}

function officeDraftFindHallwayRoute(networkRaw, fromRaw, toRaw, deadlineRaw = 0) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return [fromRaw, toRaw];
    const from = officeDraftNearestHallwayPoint(fromRaw, network);
    const to = officeDraftNearestHallwayPoint(toRaw, network);
    const graph = officeDraftBuildHallwayRouteGraph(network, [from, to]);
    const startId = officeDraftPointKey(from);
    const endId = officeDraftPointKey(to);
    if (!graph.has(startId) || !graph.has(endId)) return [from, to];
    if (startId === endId) return [from];

    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadlineRaw)) return [from, to];
        let currentId = '';
        let currentDistance = Number.POSITIVE_INFINITY;
        unsettled.forEach((nodeId) => {
            const distance = distances.has(nodeId) ? distances.get(nodeId) : Number.POSITIVE_INFINITY;
            if (distance < currentDistance) {
                currentDistance = distance;
                currentId = nodeId;
            }
        });
        if (!currentId || !Number.isFinite(currentDistance)) break;
        unsettled.delete(currentId);
        if (currentId === endId) break;
        const node = graph.get(currentId);
        node?.links?.forEach((weight, nextId) => {
            if (!unsettled.has(nextId)) return;
            const nextDistance = currentDistance + weight;
            if (nextDistance < (distances.get(nextId) ?? Number.POSITIVE_INFINITY)) {
                distances.set(nextId, nextDistance);
                parent.set(nextId, currentId);
            }
        });
    }
    if (!distances.has(endId)) return [from, to];
    const route = [];
    let cursor = endId;
    while (cursor) {
        const node = graph.get(cursor);
        if (node) route.push({ x: node.x, y: node.y });
        if (cursor === startId) break;
        cursor = parent.get(cursor);
    }
    route.reverse();
    return officeDraftDedupeRoute(route);
}

function officeDraftDedupeRoute(pointsRaw) {
    const points = [];
    (Array.isArray(pointsRaw) ? pointsRaw : []).forEach((point) => {
        if (!point) return;
        const next = {
            x: Math.round(Number(point.x) || 0),
            y: Math.round(Number(point.y) || 0),
        };
        const prev = points[points.length - 1];
        if (prev && Math.hypot(prev.x - next.x, prev.y - next.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) return;
        points.push(next);
    });
    return points;
}

function officeDraftRouteDistance(pointsRaw) {
    const points = Array.isArray(pointsRaw) ? pointsRaw : [];
    let distance = 0;
    for (let index = 0; index < points.length - 1; index += 1) {
        distance += Math.hypot(
            (Number(points[index + 1]?.x) || 0) - (Number(points[index]?.x) || 0),
            (Number(points[index + 1]?.y) || 0) - (Number(points[index]?.y) || 0),
        );
    }
    return distance;
}

function officeDraftRouteReached(routeRaw, targetRaw) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (!route.length) return false;
    const last = route[route.length - 1];
    return Math.hypot((Number(last?.x) || 0) - (Number(targetRaw?.x) || 0), (Number(last?.y) || 0) - (Number(targetRaw?.y) || 0)) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON;
}

function officeDraftRouteHasBlockedSegment(routeRaw, spacesRaw, networkRaw = null) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (route.length <= 1) return false;
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    return route.some((point, index) => index > 0 && (
        officeDraftRouteSegmentWallViolation(route[index - 1], point, spaces, network)
        || officeDraftRouteSegmentObstacleViolation(route[index - 1], point, spaces, network)
    ));
}

function officeDraftSegmentClearInSpace(a, b, space, obstaclesRaw = null) {
    if (!space) return true;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    if (!officeDraftPointWalkableInSpace(a, space, obstacles) || !officeDraftPointWalkableInSpace(b, space, obstacles)) return false;
    return !obstacles.some((rect) => officeDraftLineSegmentIntersectsRect(a, b, rect));
}

function officeDraftLocalNavCandidatePoints(space, start, target, obstaclesRaw = null) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const rawPoints = [
        start,
        target,
        officeDraftSpaceCenter(space),
        { x: start.x, y: target.y },
        { x: target.x, y: start.y },
        { x: bounds.left, y: bounds.top },
        { x: bounds.right, y: bounds.top },
        { x: bounds.left, y: bounds.bottom },
        { x: bounds.right, y: bounds.bottom },
    ];
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        rawPoints.push(
            { x: rect.left - gap, y: rect.top - gap },
            { x: rect.right + gap, y: rect.top - gap },
            { x: rect.left - gap, y: rect.bottom + gap },
            { x: rect.right + gap, y: rect.bottom + gap },
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
            { x: start.x, y: rect.top - gap },
            { x: start.x, y: rect.bottom + gap },
            { x: rect.left - gap, y: start.y },
            { x: rect.right + gap, y: start.y },
            { x: target.x, y: rect.top - gap },
            { x: target.x, y: rect.bottom + gap },
            { x: rect.left - gap, y: target.y },
            { x: rect.right + gap, y: target.y },
        );
    });
    const byKey = new Map();
    rawPoints.forEach((point) => {
        const clamped = {
            x: Math.round(officeClamp(Number(point?.x) || 0, bounds.left, bounds.right)),
            y: Math.round(officeClamp(Number(point?.y) || 0, bounds.top, bounds.bottom)),
        };
        if (!officeDraftPointWalkableInSpace(clamped, space, obstacles)) return;
        const key = officeDraftPointKey(clamped, 6);
        if (!byKey.has(key)) byKey.set(key, clamped);
    });
    const startKey = officeDraftPointKey(start, 6);
    const targetKey = officeDraftPointKey(target, 6);
    return [...byKey.values()]
        .sort((a, b) => {
            const aKey = officeDraftPointKey(a, 6);
            const bKey = officeDraftPointKey(b, 6);
            if (aKey === startKey || aKey === targetKey) return -1;
            if (bKey === startKey || bKey === targetKey) return 1;
            const aScore = Math.hypot(a.x - start.x, a.y - start.y) + Math.hypot(a.x - target.x, a.y - target.y);
            const bScore = Math.hypot(b.x - start.x, b.y - start.y) + Math.hypot(b.x - target.x, b.y - target.y);
            return aScore - bScore;
        })
        .slice(0, OFFICE_DRAFT_AGENT_LOCAL_CANDIDATE_LIMIT);
}

function officeDraftFindOrthogonalLocalRoute(space, start, target, obstaclesRaw = null) {
    if (!space) return null;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
    const xCandidates = [start.x, target.x, (bounds.left + bounds.right) / 2, bounds.left, bounds.right];
    const yCandidates = [start.y, target.y, (bounds.top + bounds.bottom) / 2, bounds.top, bounds.bottom];
    obstacles.forEach((rect) => {
        xCandidates.push(rect.left - gap, rect.right + gap, (rect.left + rect.right) / 2);
        yCandidates.push(rect.top - gap, rect.bottom + gap, (rect.top + rect.bottom) / 2);
    });
    const clampPoint = (point) => officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(Number(point?.x) || 0, bounds.left, bounds.right)),
        y: Math.round(officeClamp(Number(point?.y) || 0, bounds.top, bounds.bottom)),
    }, space, obstacles);
    const candidatePaths = [];
    const addPath = (pointsRaw) => {
        const points = officeDraftDedupeRoute((Array.isArray(pointsRaw) ? pointsRaw : []).map(clampPoint));
        if (points.length < 2) return;
        const clear = points.every((point, index) => index === 0 || officeDraftSegmentClearInSpace(points[index - 1], point, space, obstacles));
        if (clear) candidatePaths.push(points);
    };
    yCandidates.forEach((yRaw) => {
        const y = Math.round(officeClamp(Number(yRaw) || start.y, bounds.top, bounds.bottom));
        addPath([start, { x: start.x, y }, { x: target.x, y }, target]);
    });
    xCandidates.forEach((xRaw) => {
        const x = Math.round(officeClamp(Number(xRaw) || start.x, bounds.left, bounds.right));
        addPath([start, { x, y: start.y }, { x, y: target.y }, target]);
    });
    if (!candidatePaths.length) return null;
    return candidatePaths.sort((a, b) => officeDraftRouteDistance(a) - officeDraftRouteDistance(b))[0];
}

function officeDraftFindGridLocalRoute(space, start, target, obstaclesRaw = null, deadlineRaw = 0) {
    if (!space) return null;
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const stepSize = Math.max(44, OFFICE_DRAFT_AGENT_LOCAL_SAMPLE_STEP + 14);
    const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP;
    const xs = new Set([bounds.left, bounds.right, start.x, target.x]);
    const ys = new Set([bounds.top, bounds.bottom, start.y, target.y]);
    for (let x = bounds.left; x <= bounds.right; x += stepSize) xs.add(Math.round(x));
    for (let y = bounds.top; y <= bounds.bottom; y += stepSize) ys.add(Math.round(y));
    obstacles.forEach((rect) => {
        [rect.left - gap, rect.right + gap, (rect.left + rect.right) / 2].forEach((x) => {
            xs.add(Math.round(officeClamp(x, bounds.left, bounds.right)));
        });
        [rect.top - gap, rect.bottom + gap, (rect.top + rect.bottom) / 2].forEach((y) => {
            ys.add(Math.round(officeClamp(y, bounds.top, bounds.bottom)));
        });
    });
    let xValues = [...xs].sort((a, b) => a - b);
    let yValues = [...ys].sort((a, b) => a - b);
    if (xValues.length * yValues.length > OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT) {
        const compactXs = new Set([bounds.left, bounds.right, start.x, target.x]);
        const compactYs = new Set([bounds.top, bounds.bottom, start.y, target.y]);
        for (let x = bounds.left; x <= bounds.right; x += stepSize) compactXs.add(Math.round(x));
        for (let y = bounds.top; y <= bounds.bottom; y += stepSize) compactYs.add(Math.round(y));
        xValues = [...compactXs].sort((a, b) => a - b);
        yValues = [...compactYs].sort((a, b) => a - b);
    }
    if (xValues.length * yValues.length > OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT) {
        return null;
    }
    const graph = new Map();
    const keyFor = (xIndex, yIndex) => `${xIndex},${yIndex}`;
    const nodeIdAt = new Map();
    xValues.forEach((x, xIndex) => {
        if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
        yValues.forEach((y, yIndex) => {
            if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
            const point = { x: Math.round(x), y: Math.round(y) };
            if (!officeDraftPointWalkableInSpace(point, space, obstacles)) return;
            const id = officeDraftPointKey(point, 4);
            graph.set(id, { id, x: point.x, y: point.y, links: new Map(), xIndex, yIndex });
            nodeIdAt.set(keyFor(xIndex, yIndex), id);
        });
    });
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const connect = (a, b) => {
        if (!a || !b || a.id === b.id) return;
        if (!officeDraftSegmentClearInSpace(a, b, space, obstacles)) return;
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        a.links.set(b.id, distance);
        b.links.set(a.id, distance);
    };
    graph.forEach((node) => {
        if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return;
        for (let dx = -1; dx <= 1; dx += 1) {
            for (let dy = -1; dy <= 1; dy += 1) {
                if (dx === 0 && dy === 0) continue;
                const neighborId = nodeIdAt.get(keyFor(node.xIndex + dx, node.yIndex + dy));
                if (!neighborId) continue;
                connect(node, graph.get(neighborId));
            }
        }
    });
    if (officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
    const startId = officeDraftPointKey(start, 4);
    const targetId = officeDraftPointKey(target, 4);
    if (!graph.has(startId) || !graph.has(targetId)) return null;
    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadlineRaw)) return null;
        let currentId = '';
        let currentDistance = Number.POSITIVE_INFINITY;
        unsettled.forEach((nodeId) => {
            const distance = distances.has(nodeId) ? distances.get(nodeId) : Number.POSITIVE_INFINITY;
            if (distance < currentDistance) {
                currentDistance = distance;
                currentId = nodeId;
            }
        });
        if (!currentId || !Number.isFinite(currentDistance)) break;
        unsettled.delete(currentId);
        if (currentId === targetId) break;
        const node = graph.get(currentId);
        node?.links?.forEach((weight, nextId) => {
            if (!unsettled.has(nextId)) return;
            const nextDistance = currentDistance + weight;
            if (nextDistance < (distances.get(nextId) ?? Number.POSITIVE_INFINITY)) {
                distances.set(nextId, nextDistance);
                parent.set(nextId, currentId);
            }
        });
    }
    if (!distances.has(targetId)) return null;
    const route = [];
    let cursor = targetId;
    while (cursor) {
        const node = graph.get(cursor);
        if (node) route.push({ x: node.x, y: node.y });
        if (cursor === startId) break;
        cursor = parent.get(cursor);
    }
    route.reverse();
    return officeDraftDedupeRoute(route);
}

function officeDraftFindLocalRoute(space, startRaw, targetRaw, obstaclesRaw = null, deadlineRaw = 0) {
    if (!space) return officeDraftDedupeRoute([startRaw, targetRaw]);
    const deadline = Number(deadlineRaw) || officeDraftRouteSolveDeadline();
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const start = officeDraftClampWorldPointToWalkable(startRaw, space, obstacles);
    const target = officeDraftClampWorldPointToWalkable(targetRaw, space, obstacles);
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    if (Math.hypot(start.x - target.x, start.y - target.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        return [target];
    }
    if (officeDraftSegmentClearInSpace(start, target, space, obstacles)) {
        return officeDraftDedupeRoute([start, target]);
    }
    const orthogonalRoute = officeDraftFindOrthogonalLocalRoute(space, start, target, obstacles);
    if (orthogonalRoute && orthogonalRoute.length > 1) return orthogonalRoute;
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    const points = officeDraftLocalNavCandidatePoints(space, start, target, obstacles);
    const startId = officeDraftPointKey(start, 6);
    const targetId = officeDraftPointKey(target, 6);
    const graph = new Map();
    const ensureNode = (point) => {
        const key = officeDraftPointKey(point, 6);
        if (!graph.has(key)) graph.set(key, { id: key, x: point.x, y: point.y, links: new Map() });
        return graph.get(key);
    };
    points.forEach(ensureNode);
    const edgeCandidates = [];
    for (let i = 0; i < points.length; i += 1) {
        if (i % 8 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        for (let j = i + 1; j < points.length; j += 1) {
            const a = points[i];
            const b = points[j];
            const distance = Math.hypot(a.x - b.x, a.y - b.y);
            const aligned = Math.abs(a.x - b.x) <= 3 || Math.abs(a.y - b.y) <= 3;
            const endpointBonus = i < 2 || j < 2 ? 220 : 0;
            edgeCandidates.push({ a, b, distance, score: distance - (aligned ? 180 : 0) - endpointBonus });
        }
    }
    if (officeDraftRouteDeadlineExceeded(deadline)) return [start];
    edgeCandidates.sort((a, b) => a.score - b.score);
    let edgeIndex = 0;
    for (const edge of edgeCandidates.slice(0, OFFICE_DRAFT_AGENT_LOCAL_EDGE_LIMIT)) {
        edgeIndex += 1;
        if (edgeIndex % 32 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        if (!officeDraftSegmentClearInSpace(edge.a, edge.b, space, obstacles)) continue;
        const aNode = ensureNode(edge.a);
        const bNode = ensureNode(edge.b);
        const distance = Math.hypot(aNode.x - bNode.x, aNode.y - bNode.y);
        aNode.links.set(bNode.id, distance);
        bNode.links.set(aNode.id, distance);
    }
    if (!graph.has(startId) || !graph.has(targetId)) {
        return officeDraftFindGridLocalRoute(space, start, target, obstacles, deadline) || [start];
    }
    const distances = new Map([[startId, 0]]);
    const parent = new Map();
    const unsettled = new Set(graph.keys());
    let guard = 0;
    while (unsettled.size) {
        guard += 1;
        if (guard % 16 === 0 && officeDraftRouteDeadlineExceeded(deadline)) return [start];
        let currentId = '';
        let currentDistance = Number.POSITIVE_INFINITY;
        unsettled.forEach((nodeId) => {
            const distance = distances.has(nodeId) ? distances.get(nodeId) : Number.POSITIVE_INFINITY;
            if (distance < currentDistance) {
                currentDistance = distance;
                currentId = nodeId;
            }
        });
        if (!currentId || !Number.isFinite(currentDistance)) break;
        unsettled.delete(currentId);
        if (currentId === targetId) break;
        const node = graph.get(currentId);
        node?.links?.forEach((weight, nextId) => {
            if (!unsettled.has(nextId)) return;
            const nextDistance = currentDistance + weight;
            if (nextDistance < (distances.get(nextId) ?? Number.POSITIVE_INFINITY)) {
                distances.set(nextId, nextDistance);
                parent.set(nextId, currentId);
            }
        });
    }
    if (!distances.has(targetId)) {
        return officeDraftFindGridLocalRoute(space, start, target, obstacles, deadline) || [start];
    }
    const route = [];
    let cursor = targetId;
    while (cursor) {
        const node = graph.get(cursor);
        if (node) route.push({ x: node.x, y: node.y });
        if (cursor === startId) break;
        cursor = parent.get(cursor);
    }
    route.reverse();
    return officeDraftDedupeRoute(route);
}

function officeDraftAssetApproachCandidates(space, asset, seed = 0, obstaclesRaw = null) {
    if (!space || !asset) return [];
    const rect = officeDraftSpaceRect(space);
    const dims = officeDraftAssetDimensions(asset.type, asset.scale);
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const standOff = Math.max(98, OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN + OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP);
    const spread = Math.max(56, Math.min(96, Math.round(Math.max(dims.width, dims.height) * 0.28)));
    const assetLeft = rect.left + (Number(asset.x) || 0);
    const assetTop = rect.top + (Number(asset.y) || 0);
    const assetRight = assetLeft + dims.width;
    const assetBottom = assetTop + dims.height;
    const centerX = assetLeft + (dims.width / 2);
    const centerY = assetTop + (dims.height / 2);
    const sideSpecs = [
        { name: 'bottom', axis: 'x', x: centerX, y: assetBottom + standOff },
        { name: 'right', axis: 'y', x: assetRight + standOff, y: centerY },
        { name: 'left', axis: 'y', x: assetLeft - standOff, y: centerY },
        { name: 'top', axis: 'x', x: centerX, y: assetTop - standOff },
    ];
    const sideOffset = Math.abs(Math.round(Number(seed) || 0)) % sideSpecs.length;
    const orderedSides = sideSpecs.slice(sideOffset).concat(sideSpecs.slice(0, sideOffset));
    const spreadValues = [0, -spread, spread, -(spread * 1.7), spread * 1.7];
    const candidates = [];
    const seen = new Set();
    orderedSides.forEach((side, sideIndex) => {
        spreadValues.forEach((spreadValue, spreadIndex) => {
            const raw = {
                x: side.axis === 'x' ? side.x + spreadValue : side.x,
                y: side.axis === 'y' ? side.y + spreadValue : side.y,
            };
            const bounded = {
                x: Math.round(officeClamp(raw.x, rect.left + 92, rect.right - 136)),
                y: Math.round(officeClamp(raw.y, rect.top + 112, rect.bottom - 172)),
            };
            const point = officeDraftClampWorldPointToWalkable(bounded, space, obstacles);
            if (!officeDraftPointWalkableInSpace(point, space, obstacles)) return;
            const key = officeDraftPointKey(point, 8);
            if (seen.has(key)) return;
            seen.add(key);
            candidates.push({
                point,
                raw: bounded,
                side: side.name,
                sideIndex,
                spreadIndex,
            });
        });
    });
    return candidates;
}

function officeDraftAssetApproachAnchor(space, obstaclesRaw = null) {
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const state = officeEnsureDraftMapState();
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const doorInterior = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    if (officeDraftPointWalkableInSpace(doorInterior, space, obstacles)) return doorInterior;
    return officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
}

function officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed = 0, options = {}) {
    if (!space || !targetAsset) return null;
    const allowRouteSearch = options?.routeAware === true;
    const obstacles = officeDraftObstacleRects(space);
    const cacheKey = [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        Math.round(Number(space?.x) || 0),
        Math.round(Number(space?.y) || 0),
        Math.round(Number(space?.width) || 0),
        Math.round(Number(space?.height) || 0),
        safeString(targetAsset?.id),
        Math.round(Number(targetAsset?.x) || 0),
        Math.round(Number(targetAsset?.y) || 0),
        officeDraftClampAssetScale(targetAsset?.scale),
        officeDraftNormalizeRotation(targetAsset?.rotation),
    ].join('|');
    if (agent?.draftTargetPointCache?.key === cacheKey) {
        const cached = {
            x: Math.round(Number(agent.draftTargetPointCache.x) || 0),
            y: Math.round(Number(agent.draftTargetPointCache.y) || 0),
        };
        const cachedRouteAware = agent.draftTargetPointCache.routeAware === true;
        if (officeDraftPointWalkableInSpace(cached, space, obstacles)
            && (cachedRouteAware || !allowRouteSearch)) {
            return cached;
        }
    }
    const anchor = officeDraftAssetApproachAnchor(space, obstacles);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const targetDims = officeDraftAssetDimensions(targetAsset.type, targetAsset.scale);
    const targetRect = officeDraftSpaceRect(space);
    const targetCenter = {
        x: targetRect.left + (Number(targetAsset.x) || 0) + (targetDims.width / 2),
        y: targetRect.top + (Number(targetAsset.y) || 0) + (targetDims.height / 2),
    };
    let best = null;
    let routeSearches = 0;
    const deadline = allowRouteSearch ? officeDraftRouteSolveDeadline(OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS) : 0;
    officeDraftAssetApproachCandidates(space, targetAsset, seed, obstacles).forEach((candidate) => {
        const point = candidate.point;
        const anchorClear = officeDraftSegmentClearInSpace(anchor, point, space, obstacles);
        const shouldRouteSearch = allowRouteSearch
            && !anchorClear
            && routeSearches < 8
            && !officeDraftRouteDeadlineExceeded(deadline);
        let localRoute = anchorClear ? [anchor, point] : null;
        if (shouldRouteSearch) {
            routeSearches += 1;
            localRoute = officeDraftFindLocalRoute(space, anchor, point, obstacles, deadline);
        }
        const localRouteClear = Array.isArray(localRoute)
            && officeDraftRouteReached(localRoute, point)
            && officeDraftRouteClearInSpace(localRoute, space, obstacles);
        const centerClear = anchorClear || localRouteClear || officeDraftSegmentClearInSpace(center, point, space, obstacles);
        const clearance = officeDraftPointObstacleClearance(point, obstacles);
        const diversitySlot = Math.abs(Number(seed) || 0) % 13;
        const candidateSlot = ((candidate.sideIndex * 5) + candidate.spreadIndex) % 13;
        const assetDistance = Math.hypot(point.x - targetCenter.x, point.y - targetCenter.y);
        const routeDistance = localRouteClear ? officeDraftRouteDistance(localRoute) : Math.hypot(point.x - anchor.x, point.y - anchor.y);
        const score = (anchorClear ? 0 : (localRouteClear ? 280 : (centerClear ? 780 : 1900)))
            + (Math.max(0, 132 - clearance) * 7)
            + (routeDistance * 0.42)
            + (assetDistance * 0.62)
            + (Math.max(0, assetDistance - 230) * 8)
            + (candidate.sideIndex * 18)
            + (candidate.spreadIndex * 7)
            + (Math.abs(diversitySlot - candidateSlot) * 20)
            + (Math.hypot(point.x - candidate.raw.x, point.y - candidate.raw.y) * 3);
        if (!best || score < best.score) {
            best = { point, score, routeAware: localRouteClear || anchorClear };
        }
    });
    if (!best) return null;
    if (agent && typeof agent === 'object') {
        agent.draftTargetPointCache = {
            key: cacheKey,
            x: best.point.x,
            y: best.point.y,
            routeAware: allowRouteSearch && best.routeAware === true,
        };
    }
    return best.point;
}

function officeDraftSpreadAgentTargetPoint(space, pointRaw, index = 0, total = 1, seed = 0, obstaclesRaw = null) {
    if (!space || !pointRaw) return pointRaw || { x: 0, y: 0 };
    const totalAgents = Math.max(1, Number(total) || 1);
    if (totalAgents <= 1) return pointRaw;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const slotIndex = Math.max(0, Number(index) || 0);
    const base = officeDraftClampWorldPointToWalkable(pointRaw, space, obstacles);
    const angleBase = (((slotIndex * 137.508) + (Math.abs(Number(seed) || 0) % 89)) % 360) * (Math.PI / 180);
    const radiusBase = 74 + ((slotIndex % 4) * 22) + (Math.floor(slotIndex / 4) * 18);
    const offsets = [
        { angle: angleBase, radius: radiusBase },
        { angle: angleBase + Math.PI * 0.5, radius: radiusBase * 0.9 },
        { angle: angleBase - Math.PI * 0.5, radius: radiusBase * 0.9 },
        { angle: angleBase + Math.PI, radius: radiusBase * 0.72 },
        { angle: angleBase + Math.PI * 0.25, radius: radiusBase * 1.12 },
        { angle: angleBase - Math.PI * 0.25, radius: radiusBase * 1.12 },
    ];
    let best = null;
    offsets.forEach((offset, offsetIndex) => {
        const candidateRaw = {
            x: base.x + (Math.cos(offset.angle) * offset.radius),
            y: base.y + (Math.sin(offset.angle) * offset.radius),
        };
        const candidate = officeDraftClampWorldPointToWalkable({
            x: Math.round(officeClamp(candidateRaw.x, bounds.left, bounds.right)),
            y: Math.round(officeClamp(candidateRaw.y, bounds.top, bounds.bottom)),
        }, space, obstacles);
        if (!officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const score = Math.hypot(candidate.x - base.x, candidate.y - base.y)
            + (offsetIndex * 9)
            - (Math.min(220, clearance) * 1.45);
        if (!best || score < best.score) best = { point: candidate, score };
    });
    return best?.point || base;
}

function officeDraftAgentTargetWorldPoint(space, agent, index = 0, total = 1, targetAsset = null) {
    const rect = officeDraftSpaceRect(space);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|target`);
    const wanderTarget = officeDraftAgentWanderTargetWorld(space, agent);
    if (wanderTarget) return wanderTarget;
    if (targetAsset) {
        const commandAsset = officeDraftAgentCommandAsset(space, agent);
        const routeAware = commandAsset && safeString(commandAsset?.id) === safeString(targetAsset?.id);
        const approach = officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed, { routeAware });
        if (approach) return officeDraftSpreadAgentTargetPoint(space, approach, index, total, seed);
    }
    const totalAgents = Math.max(1, Number(total) || 1);
    const slotIndex = Math.max(0, Math.min(totalAgents - 1, Number(index) || 0));
    const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(totalAgents))));
    const rows = Math.max(1, Math.ceil(totalAgents / columns));
    const column = slotIndex % columns;
    const row = Math.floor(slotIndex / columns);
    const jitterX = ((seed % 5) - 2) * 18;
    const jitterY = ((Math.floor(seed / 5) % 5) - 2) * 14;
    const walkLeft = rect.left + 132;
    const walkRight = rect.right - 164;
    const walkTop = rect.top + 132;
    const walkBottom = rect.bottom - 190;
    let x = walkLeft + (((walkRight - walkLeft) / (columns + 1)) * (column + 1)) + jitterX;
    let y = walkTop + (((walkBottom - walkTop) / (rows + 1)) * (row + 1)) + jitterY;
    return officeDraftClampWorldPointToWalkable({
        x: Math.round(officeClamp(x, rect.left + 92, rect.right - 136)),
        y: Math.round(officeClamp(y, rect.top + 112, rect.bottom - 172)),
    }, space);
}

function officeDraftRouteClearInSpace(routeRaw, space, obstaclesRaw = null) {
    const route = Array.isArray(routeRaw) ? routeRaw : [];
    if (route.length <= 1) return true;
    const obstacles = Array.isArray(obstaclesRaw) ? obstaclesRaw : officeDraftObstacleRects(space);
    return route.every((point, index) => index === 0 || officeDraftSegmentClearInSpace(route[index - 1], point, space, obstacles));
}

function officeDraftFallbackAgentTargetWorldPoint(space, agent, index = 0, total = 1) {
    if (!space) return { x: 0, y: 0 };
    const cacheKey = [
        OFFICE_DRAFT_AGENT_NAV_VERSION,
        safeString(space?.id),
        Math.round(Number(space?.x) || 0),
        Math.round(Number(space?.y) || 0),
        Math.round(Number(space?.width) || 0),
        Math.round(Number(space?.height) || 0),
        safeString(agent?.id),
        (Array.isArray(space?.assets) ? space.assets : []).map((asset) => [
            safeString(asset?.id),
            safeString(asset?.type),
            Math.round(Number(asset?.x) || 0),
            Math.round(Number(asset?.y) || 0),
            officeDraftClampAssetScale(asset?.scale),
            officeDraftNormalizeRotation(asset?.rotation),
        ].join(':')).join(','),
    ].join('|');
    if (agent?.draftFallbackTargetCache?.key === cacheKey) {
        const cached = {
            x: Math.round(Number(agent.draftFallbackTargetCache.x) || 0),
            y: Math.round(Number(agent.draftFallbackTargetCache.y) || 0),
        };
        if (officeDraftPointWalkableInSpace(cached, space)) return cached;
    }
    const obstacles = officeDraftObstacleRects(space);
    const bounds = officeDraftWalkableBounds(space);
    const state = officeEnsureDraftMapState();
    const network = officeDraftAutoHallwayNetwork(state.spaces);
    const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|fallback`);
    const anchor = officeDraftClampWorldPointToWalkable(officeDraftSpaceDoorInteriorPoint(space, network), space, obstacles);
    const center = officeDraftClampWorldPointToWalkable(officeDraftSpaceCenter(space), space, obstacles);
    const spawn = officeDraftSpaceSpawnWorldPoint(space, agent, index, total);
    const candidates = [spawn, center, anchor];
    const xStops = [
        bounds.left + (bounds.right - bounds.left) * 0.28,
        bounds.left + (bounds.right - bounds.left) * 0.5,
        bounds.left + (bounds.right - bounds.left) * 0.72,
    ];
    const yStops = [
        bounds.top + (bounds.bottom - bounds.top) * 0.3,
        bounds.top + (bounds.bottom - bounds.top) * 0.52,
        bounds.top + (bounds.bottom - bounds.top) * 0.74,
    ];
    xStops.forEach((x) => {
        yStops.forEach((y) => candidates.push({ x, y }));
    });
    obstacles.forEach((rect) => {
        const gap = OFFICE_DRAFT_AGENT_OBSTACLE_CORNER_GAP + 22;
        const centerX = (rect.left + rect.right) / 2;
        const centerY = (rect.top + rect.bottom) / 2;
        candidates.push(
            { x: rect.left - gap, y: centerY },
            { x: rect.right + gap, y: centerY },
            { x: centerX, y: rect.top - gap },
            { x: centerX, y: rect.bottom + gap },
        );
    });
    let best = null;
    const seen = new Set();
    candidates.forEach((candidateRaw, candidateIndex) => {
        const candidate = officeDraftClampWorldPointToWalkable(candidateRaw, space, obstacles);
        const key = officeDraftPointKey(candidate, 8);
        if (seen.has(key) || !officeDraftPointWalkableInSpace(candidate, space, obstacles)) return;
        seen.add(key);
        if (Math.hypot(anchor.x - candidate.x, anchor.y - candidate.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON
            && !officeDraftSegmentClearInSpace(anchor, candidate, space, obstacles)) {
            return;
        }
        const clearance = officeDraftPointObstacleClearance(candidate, obstacles);
        const score = Math.hypot(anchor.x - candidate.x, anchor.y - candidate.y)
            + (Math.hypot(candidate.x - center.x, candidate.y - center.y) * 0.32)
            - (Math.min(220, clearance) * 1.8)
            + (((seed + candidateIndex) % 17) * 4);
        if (!best || score < best.score) {
            best = { point: candidate, score };
        }
    });
    const point = best?.point || anchor;
    const spreadPoint = officeDraftSpreadAgentTargetPoint(space, point, index, total, seed, obstacles);
    if (agent && typeof agent === 'object') {
        agent.draftFallbackTargetCache = {
            key: cacheKey,
            x: spreadPoint.x,
            y: spreadPoint.y,
        };
    }
    return spreadPoint;
}

function officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const startWorld = {
        x: Math.round(Number(startWorldRaw?.x) || 0),
        y: Math.round(Number(startWorldRaw?.y) || 0),
    };
    const targetWorld = {
        x: Math.round(Number(targetWorldRaw?.x) || 0),
        y: Math.round(Number(targetWorldRaw?.y) || 0),
    };
    const startSpace = officeDraftSpaceAtWorldPoint(startWorld.x, startWorld.y);
    const targetSpaceId = safeString(targetSpace?.id);
    if (startSpace && safeString(startSpace.id) === targetSpaceId) {
        const obstacles = officeDraftObstacleRects(startSpace);
        if (officeDraftSegmentClearInSpace(startWorld, targetWorld, startSpace, obstacles)) {
            return officeDraftDedupeRoute([startWorld, targetWorld]);
        }
        return officeDraftDedupeRoute(officeDraftFindOrthogonalLocalRoute(startSpace, startWorld, targetWorld, obstacles) || [startWorld, targetWorld]);
    }
    const route = [startWorld];
    let hallStart = officeDraftNearestHallwayPoint(startWorld, network);
    if (startSpace) {
        const startDoor = officeDraftSpaceDoorPoint(startSpace, network);
        const startInterior = officeDraftSpaceDoorInteriorPoint(startSpace, network);
        route.push(startInterior);
        route.push({ x: startDoor.worldX, y: startDoor.worldY });
        route.push({ x: startDoor.outsideX, y: startDoor.outsideY });
        hallStart = { x: startDoor.outsideX, y: startDoor.outsideY };
    } else if (hallStart.distance > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        route.push({ x: hallStart.x, y: hallStart.y });
    }
    const targetDoor = officeDraftSpaceDoorPoint(targetSpace, network);
    const hallEnd = { x: targetDoor.outsideX, y: targetDoor.outsideY };
    if (Math.hypot(hallStart.x - hallEnd.x, hallStart.y - hallEnd.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        if (Math.abs(hallStart.x - hallEnd.x) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON
            && Math.abs(hallStart.y - hallEnd.y) > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
            route.push({ x: Math.round(hallEnd.x), y: Math.round(hallStart.y) });
        }
        route.push(hallEnd);
    }
    const targetInterior = officeDraftSpaceDoorInteriorPoint(targetSpace, network);
    route.push({ x: targetDoor.worldX, y: targetDoor.worldY });
    route.push(targetInterior);
    if (officeDraftSegmentClearInSpace(targetInterior, targetWorld, targetSpace)) {
        route.push(targetWorld);
    } else {
        route.push(officeDraftClampWorldPointToWalkable(targetWorld, targetSpace));
    }
    return officeDraftDedupeRoute(route);
}

function officeDraftRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null) {
    if (safeString(officeEnsureDraftMapState()?.agentRoutePlanningSource) === 'route-plan') {
        return officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw);
    }
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeEnsureDraftMapState().spaces);
    const deadline = officeDraftRouteSolveDeadline(OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS * 1.8);
    const startWorld = {
        x: Math.round(Number(startWorldRaw?.x) || 0),
        y: Math.round(Number(startWorldRaw?.y) || 0),
    };
    const targetWorld = {
        x: Math.round(Number(targetWorldRaw?.x) || 0),
        y: Math.round(Number(targetWorldRaw?.y) || 0),
    };
    const startSpace = officeDraftSpaceAtWorldPoint(startWorld.x, startWorld.y);
    const targetSpaceId = safeString(targetSpace?.id);
    if (startSpace && safeString(startSpace.id) === targetSpaceId) {
        return officeDraftFindLocalRoute(startSpace, startWorld, targetWorld, null, deadline);
    }
    const route = [startWorld];
    let hallStart = officeDraftNearestHallwayPoint(startWorld, network);
    if (startSpace) {
        const startDoor = officeDraftSpaceDoorPoint(startSpace, network);
        const startInterior = officeDraftSpaceDoorInteriorPoint(startSpace, network);
        const localExit = officeDraftFindLocalRoute(startSpace, startWorld, startInterior, null, deadline);
        if (!officeDraftRouteReached(localExit, startInterior)) {
            return officeDraftDedupeRoute([startWorld]);
        }
        localExit.slice(1).forEach((point) => route.push(point));
        route.push({ x: startDoor.worldX, y: startDoor.worldY });
        route.push({ x: startDoor.outsideX, y: startDoor.outsideY });
        hallStart = { x: startDoor.outsideX, y: startDoor.outsideY };
    } else if (hallStart.distance > OFFICE_DRAFT_AGENT_ROUTE_EPSILON) {
        route.push({ x: hallStart.x, y: hallStart.y });
    }
    const targetDoor = officeDraftSpaceDoorPoint(targetSpace, network);
    const hallEnd = { x: targetDoor.outsideX, y: targetDoor.outsideY };
    const hallwayRoute = officeDraftFindHallwayRoute(network, hallStart, hallEnd, deadline);
    hallwayRoute.forEach((point, pointIndex) => {
        if (pointIndex === 0 && route.length && Math.hypot(route[route.length - 1].x - point.x, route[route.length - 1].y - point.y) <= OFFICE_DRAFT_AGENT_ROUTE_EPSILON) return;
        route.push(point);
    });
    route.push({ x: targetDoor.worldX, y: targetDoor.worldY });
    const targetInterior = officeDraftSpaceDoorInteriorPoint(targetSpace, network);
    route.push(targetInterior);
    if (officeDraftRouteDeadlineExceeded(deadline)) return officeDraftDedupeRoute(route);
    const localEntry = officeDraftFindLocalRoute(targetSpace, targetInterior, targetWorld, null, deadline);
    if (!officeDraftRouteReached(localEntry, targetWorld)) {
        return officeDraftDedupeRoute(route);
    }
    localEntry.slice(1).forEach((point) => route.push(point));
    return officeDraftDedupeRoute(route);
}

function officeDraftWorldPointInSpace(point, space) {
    const rect = officeDraftSpaceRect(space);
    const x = Number(point?.x) || 0;
    const y = Number(point?.y) || 0;
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function officeDraftRouteSegmentWallViolation(a, b, spacesRaw, networkRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    const segment = { x1: a?.x, y1: a?.y, x2: b?.x, y2: b?.y };
    const onHall = (point) => officeDraftNearestHallwayPoint(point, network).distance <= (OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH / 2) + 8;
    if (onHall(a) && onHall(b)) return null;
    const sharedSpace = spaces.find((space) => officeDraftWorldPointInSpace(a, space) && officeDraftWorldPointInSpace(b, space));
    if (sharedSpace) return null;
    const touchesDoor = spaces.some((space) => {
        const door = officeDraftSpaceDoorPoint(space, network);
        const doorSegment = { x1: door.worldX, y1: door.worldY, x2: door.outsideX, y2: door.outsideY };
        return officeDraftPointOnSegment(a, doorSegment, 4) && officeDraftPointOnSegment(b, doorSegment, 4);
    });
    if (touchesDoor) return null;
    const crossed = spaces.find((space) => officeDraftSegmentIntersectsRect(segment, officeDraftSpaceRect(space), 12));
    return crossed ? { spaceId: safeString(crossed.id), from: a, to: b } : null;
}

function officeDraftRouteSegmentObstacleViolation(a, b, spacesRaw, networkRaw = null) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const network = networkRaw || officeDraftAutoHallwayNetwork(spaces);
    if (officeDraftStepOnHallway(a, b, network)) return null;
    const sharedSpace = spaces.find((space) => officeDraftWorldPointInSpace(a, space) && officeDraftWorldPointInSpace(b, space));
    if (!sharedSpace) return null;
    const obstacles = officeDraftObstacleRects(sharedSpace);
    if (!obstacles.length) return null;
    const obstacle = obstacles.find((rect) => officeDraftLineSegmentIntersectsRect(a, b, rect));
    if (obstacle) {
        return {
            spaceId: safeString(sharedSpace.id),
            obstacleAssetId: safeString(obstacle.assetId),
            obstacleType: safeString(obstacle.type),
            from: a,
            to: b,
        };
    }
    return null;
}

function officeDraftSpaceDoorPoint(space, networkRaw = null) {
    const network = networkRaw || officeDraftAutoHallwayNetwork(officeDraftMapState?.spaces || []);
    const spaceId = safeString(space?.id);
    const networkDoor = network?.doors instanceof Map ? network.doors.get(spaceId) : null;
    if (networkDoor) return { ...networkDoor };
    const rect = officeDraftSpaceRect(space);
    const center = {
        x: rect.centerX,
        y: rect.centerY,
    };
    const mapCenter = OFFICE_DRAFT_MAP_SIZE / 2;
    const dx = center.x - mapCenter;
    const dy = center.y - mapCenter;
    let edge = 'bottom';
    if (Math.abs(dx) > Math.abs(dy)) {
        edge = dx < 0 ? 'right' : 'left';
    } else {
        edge = dy < 0 ? 'bottom' : 'top';
    }
    const local = {
        x: rect.width / 2,
        y: rect.height / 2,
    };
    if (edge === 'left') local.x = 0;
    if (edge === 'right') local.x = rect.width;
    if (edge === 'top') local.y = 0;
    if (edge === 'bottom') local.y = rect.height;
    const normal = {
        x: edge === 'left' ? -1 : (edge === 'right' ? 1 : 0),
        y: edge === 'top' ? -1 : (edge === 'bottom' ? 1 : 0),
    };
    return {
        edge,
        localX: Math.round(local.x),
        localY: Math.round(local.y),
        worldX: Math.round(rect.x + local.x),
        worldY: Math.round(rect.y + local.y),
        outsideX: Math.round(rect.x + local.x + (normal.x * 260)),
        outsideY: Math.round(rect.y + local.y + (normal.y * 260)),
        normalX: normal.x,
        normalY: normal.y,
    };
}

function officeDraftSpaceDoorInteriorPoint(space, networkRaw = null) {
    const door = officeDraftSpaceDoorPoint(space, networkRaw);
    return officeDraftClampWorldPointToWalkable({
        x: Number(door.worldX) - ((Number(door.normalX) || 0) * OFFICE_DRAFT_AGENT_ROOM_MARGIN),
        y: Number(door.worldY) - ((Number(door.normalY) || 0) * OFFICE_DRAFT_AGENT_ROOM_MARGIN),
    }, space);
}

function officeDraftCorridorPath(from, to) {
    const network = officeDraftAutoHallwayNetwork(officeDraftMapState?.spaces || [from, to]);
    const a = officeDraftSpaceDoorPoint(from, network);
    const b = officeDraftSpaceDoorPoint(to, network);
    const midX = Math.round((a.outsideX + b.outsideX) / 2);
    const midY = Math.round((a.outsideY + b.outsideY) / 2);
    const horizontalBias = Math.abs(a.outsideX - b.outsideX) >= Math.abs(a.outsideY - b.outsideY);
    const bendA = horizontalBias ? `${midX} ${a.outsideY}` : `${a.outsideX} ${midY}`;
    const bendB = horizontalBias ? `${midX} ${b.outsideY}` : `${b.outsideX} ${midY}`;
    return {
        d: `M ${a.worldX} ${a.worldY} L ${a.outsideX} ${a.outsideY} L ${bendA} L ${bendB} L ${b.outsideX} ${b.outsideY} L ${b.worldX} ${b.worldY}`,
        fromDoor: a,
        toDoor: b,
    };
}

function officeDraftConnectorPairs(spaces) {
    const byId = new Map((Array.isArray(spaces) ? spaces : []).map((space) => [safeString(space?.id), space]));
    const defaultPairs = [
        ['planning-hub', 'software-lab'],
        ['software-lab', 'research-bay'],
        ['design-loft', 'content-studio'],
        ['content-studio', 'ops-command'],
        ['ops-command', 'support-desk'],
        ['planning-hub', 'design-loft'],
        ['software-lab', 'content-studio'],
        ['research-bay', 'ops-command'],
        ['cafeteria', 'lounge'],
        ['lounge', 'focus-pods'],
        ['focus-pods', 'lobby'],
        ['content-studio', 'lounge'],
        ['support-desk', 'focus-pods'],
    ].filter(([a, b]) => byId.has(a) && byId.has(b));
    const pairs = [...defaultPairs];
    const connected = new Set(defaultPairs.flat());
    const lobby = byId.get('lobby') || spaces.find((space) => officeDraftNormalizeRoomId(space?.roomId, space?.id) === 'room-lobby');
    if (lobby) {
        spaces.forEach((space) => {
            const id = safeString(space?.id);
            if (!id || id === safeString(lobby.id) || connected.has(id)) return;
            pairs.push([id, safeString(lobby.id)]);
        });
    }
    return pairs;
}

function officeRenderDraftRoomConnectors(plane, state) {
    if (!(plane instanceof HTMLElement) || !state) return;
    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    if (!spaces.length) return;
    const network = officeDraftAutoHallwayNetwork(spaces);
    const hallwayPath = officeDraftSegmentPath(network.segments);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('data-office-draft-connectors', '1');
    svg.setAttribute('data-office-draft-hallways', '1');
    svg.setAttribute('width', String(OFFICE_DRAFT_MAP_SIZE));
    svg.setAttribute('height', String(OFFICE_DRAFT_MAP_SIZE));
    svg.style.position = 'absolute';
    svg.style.left = '0';
    svg.style.top = '0';
    svg.style.width = `${OFFICE_DRAFT_MAP_SIZE}px`;
    svg.style.height = `${OFFICE_DRAFT_MAP_SIZE}px`;
    svg.style.pointerEvents = 'none';
    svg.style.zIndex = '0';
    if (hallwayPath) {
        const shadow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        shadow.setAttribute('data-office-draft-hallway-path', 'shadow');
        shadow.setAttribute('d', hallwayPath);
        shadow.setAttribute('fill', 'none');
        shadow.setAttribute('stroke', 'rgba(21, 31, 45, 0.5)');
        shadow.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH + 26));
        shadow.setAttribute('stroke-linecap', 'round');
        shadow.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(shadow);
        const outer = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        outer.setAttribute('data-office-draft-hallway-path', 'outer');
        outer.setAttribute('d', hallwayPath);
        outer.setAttribute('fill', 'none');
        outer.setAttribute('stroke', 'rgba(111, 130, 153, 0.96)');
        outer.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH));
        outer.setAttribute('stroke-linecap', 'round');
        outer.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(outer);
        const curb = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        curb.setAttribute('data-office-draft-hallway-path', 'curb');
        curb.setAttribute('d', hallwayPath);
        curb.setAttribute('fill', 'none');
        curb.setAttribute('stroke', 'rgba(226, 236, 246, 0.34)');
        curb.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_OUTER_WIDTH - 16));
        curb.setAttribute('stroke-linecap', 'round');
        curb.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(curb);
        const floor = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        floor.setAttribute('data-office-draft-hallway-path', 'floor');
        floor.setAttribute('d', hallwayPath);
        floor.setAttribute('fill', 'none');
        floor.setAttribute('stroke', 'rgba(190, 203, 216, 0.98)');
        floor.setAttribute('stroke-width', String(OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH));
        floor.setAttribute('stroke-linecap', 'round');
        floor.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(floor);
        const lane = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        lane.setAttribute('data-office-draft-hallway-path', 'lane');
        lane.setAttribute('d', hallwayPath);
        lane.setAttribute('fill', 'none');
        lane.setAttribute('stroke', 'rgba(222, 232, 242, 0.22)');
        lane.setAttribute('stroke-width', String(Math.max(34, OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH - 48)));
        lane.setAttribute('stroke-linecap', 'round');
        lane.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(lane);
        const tile = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        tile.setAttribute('data-office-draft-hallway-path', 'tile');
        tile.setAttribute('d', hallwayPath);
        tile.setAttribute('fill', 'none');
        tile.setAttribute('stroke', 'rgba(255, 255, 255, 0.22)');
        tile.setAttribute('stroke-width', '34');
        tile.setAttribute('stroke-linecap', 'round');
        tile.setAttribute('stroke-linejoin', 'round');
        tile.setAttribute('stroke-dasharray', '18 52');
        svg.appendChild(tile);
        const centerLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        centerLine.setAttribute('data-office-draft-hallway-path', 'center');
        centerLine.setAttribute('d', hallwayPath);
        centerLine.setAttribute('fill', 'none');
        centerLine.setAttribute('stroke', 'rgba(248, 252, 255, 0.34)');
        centerLine.setAttribute('stroke-width', '8');
        centerLine.setAttribute('stroke-linecap', 'round');
        centerLine.setAttribute('stroke-linejoin', 'round');
        centerLine.setAttribute('stroke-dasharray', '64 54');
        svg.appendChild(centerLine);
    }
    network.nodes.forEach((node) => {
        if (safeString(node.kind) !== 'junction') return;
        const joint = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        joint.setAttribute('data-office-draft-hallway-node', safeString(node.kind));
        joint.setAttribute('cx', String(node.x));
        joint.setAttribute('cy', String(node.y));
        joint.setAttribute('r', '74');
        joint.setAttribute('fill', 'rgba(178, 190, 204, 0.98)');
        joint.setAttribute('stroke', 'rgba(80, 96, 116, 0.72)');
        joint.setAttribute('stroke-width', '10');
        svg.appendChild(joint);
    });
    network.doors.forEach((door) => {
        const pad = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        pad.setAttribute('data-office-draft-door-pad', safeString(door.spaceId));
        pad.setAttribute('x', String(door.worldX - 84));
        pad.setAttribute('y', String(door.worldY - 46));
        pad.setAttribute('width', '168');
        pad.setAttribute('height', '92');
        pad.setAttribute('rx', '28');
        pad.setAttribute('fill', 'rgba(238, 246, 255, 0.24)');
        pad.setAttribute('stroke', 'rgba(249, 252, 255, 0.42)');
        pad.setAttribute('stroke-width', '4');
        svg.appendChild(pad);
    });
    plane.appendChild(svg);
}

function officePrepareDraftMapShell() {
    officeEnsureDraftPerformanceStyles();
    const state = officeEnsureDraftMapState();
    const toolbar = officeWorkspace?.querySelector('.office-toolbar');
    const toolbarTitle = officeWorkspace?.querySelector('.office-toolbar-title');
    const toolbarLabel = toolbarTitle?.querySelector('span:last-child');
    if (toolbar instanceof HTMLElement) {
        toolbar.style.display = 'flex';
        toolbar.style.alignItems = 'center';
        toolbar.style.justifyContent = 'space-between';
        toolbar.style.gap = '16px';
        toolbar.style.padding = '18px 22px';
        toolbar.style.borderBottom = '1px solid rgba(104, 128, 164, 0.24)';
        toolbar.style.background = 'linear-gradient(180deg, rgba(11, 19, 34, 0.98), rgba(8, 14, 26, 0.88))';
    }
    if (toolbarLabel instanceof HTMLElement) {
        toolbarLabel.textContent = 'Virtual Office';
    }
    if (toolbarTitle instanceof HTMLElement && !toolbar.querySelector('[data-office-map-hint="1"]')) {
        const hint = document.createElement('span');
        hint.dataset.officeMapHint = '1';
        hint.textContent = 'Live agent office - drag to pan - wheel to zoom';
        hint.style.fontSize = '0.75rem';
        hint.style.letterSpacing = '0.08em';
        hint.style.textTransform = 'uppercase';
        hint.style.color = 'rgba(201, 214, 236, 0.64)';
        hint.style.marginLeft = '14px';
        toolbarTitle.appendChild(hint);
    }
    if (officeEditorToggleBtn instanceof HTMLElement) {
        officeEditorToggleBtn.style.display = 'none';
    }
    [
        officeWorkspace?.querySelector('.office-map-controls'),
        officeWorkspace?.querySelector('.office-debug-overlay'),
        officeWorkspace?.querySelector('.office-editor-modal'),
        officeWorkspace?.querySelector('.office-bottom-dock'),
    ].forEach((node) => {
        if (node instanceof HTMLElement) {
            node.style.display = 'none';
        }
    });
    const stage = officeWorkspace?.querySelector('.office-stage');
    if (officeWorkspace instanceof HTMLElement) {
        officeWorkspace.style.display = officeWorkspace.classList.contains('hidden') ? '' : 'flex';
        officeWorkspace.style.flexDirection = 'column';
        officeWorkspace.style.minHeight = 'calc(100vh - 140px)';
        officeWorkspace.style.background = 'linear-gradient(180deg, rgba(8, 14, 26, 0.96), rgba(6, 10, 19, 0.98))';
        officeWorkspace.style.overflow = 'hidden';
    }
    if (stage instanceof HTMLElement) {
        stage.style.display = 'flex';
        stage.style.flex = '1';
        stage.style.minHeight = '0';
        stage.style.padding = '22px';
    }
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.tabIndex = 0;
        officeSceneWrap.setAttribute('aria-label', 'Virtual office base map. Drag to pan and use the mouse wheel to zoom.');
        officeSceneWrap.style.position = 'relative';
        officeSceneWrap.style.flex = '1';
        officeSceneWrap.style.minHeight = 'calc(100vh - 120px)';
        officeSceneWrap.style.borderRadius = '26px';
        officeSceneWrap.style.overflow = 'hidden';
        officeSceneWrap.style.cursor = state.pointerId === null ? 'grab' : 'grabbing';
        officeSceneWrap.style.touchAction = 'none';
        officeSceneWrap.style.background = 'radial-gradient(circle at top, rgba(58, 86, 132, 0.28), rgba(8, 14, 26, 0.94) 52%, rgba(4, 7, 14, 1) 100%)';
        officeSceneWrap.style.boxShadow = 'inset 0 0 0 1px rgba(110, 134, 176, 0.16)';
    }
    if (toolbar instanceof HTMLElement) {
        toolbar.style.display = 'none';
        toolbar.style.padding = '0';
        toolbar.style.margin = '0';
        toolbar.style.minHeight = '0';
        toolbar.style.border = '0';
        toolbar.style.overflow = 'hidden';
    }
    if (officeWorkspace instanceof HTMLElement) {
        officeWorkspace.style.minHeight = 'calc(100vh - 76px)';
    }
    if (stage instanceof HTMLElement) {
        stage.style.padding = '8px';
    }
    const mapToolbar = officeSceneWrap?.querySelector('[data-office-map-toolbar="1"]');
    if (mapToolbar instanceof HTMLElement) {
        mapToolbar.style.position = 'absolute';
        mapToolbar.style.top = '14px';
        mapToolbar.style.left = '14px';
        mapToolbar.style.right = '14px';
        mapToolbar.style.display = 'flex';
        mapToolbar.style.alignItems = 'center';
        mapToolbar.style.justifyContent = 'flex-start';
        mapToolbar.style.gap = '8px';
        mapToolbar.style.padding = '8px 10px';
        mapToolbar.style.borderRadius = '16px';
        mapToolbar.style.background = 'rgba(6, 10, 19, 0.84)';
        mapToolbar.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        mapToolbar.style.backdropFilter = 'blur(10px)';
        mapToolbar.style.zIndex = '12';
    }
    const minimapToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-minimap="1"]');
    if (minimapToolbarBtn instanceof HTMLButtonElement) {
        minimapToolbarBtn.textContent = 'Minimap';
        minimapToolbarBtn.setAttribute('aria-pressed', state.minimapMinimized ? 'false' : 'true');
        minimapToolbarBtn.style.padding = '8px 14px';
        minimapToolbarBtn.style.borderRadius = '12px';
        minimapToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        minimapToolbarBtn.style.background = state.minimapMinimized ? 'rgba(17, 27, 44, 0.72)' : 'rgba(55, 103, 184, 0.34)';
        minimapToolbarBtn.style.color = 'rgba(234, 242, 255, 0.92)';
        minimapToolbarBtn.style.fontSize = '0.82rem';
        minimapToolbarBtn.style.fontWeight = '600';
    }
    const editorToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-editor="1"]');
    if (editorToolbarBtn instanceof HTMLButtonElement) {
        editorToolbarBtn.textContent = 'Office Editor';
        editorToolbarBtn.setAttribute('aria-pressed', state.editorOpen ? 'true' : 'false');
        editorToolbarBtn.style.padding = '8px 14px';
        editorToolbarBtn.style.borderRadius = '12px';
        editorToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        editorToolbarBtn.style.background = state.editorOpen ? 'rgba(81, 125, 205, 0.34)' : 'rgba(17, 27, 44, 0.72)';
        editorToolbarBtn.style.color = 'rgba(234, 242, 255, 0.92)';
        editorToolbarBtn.style.fontSize = '0.82rem';
        editorToolbarBtn.style.fontWeight = '600';
    }
    const rosterToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-roster="1"]');
    if (rosterToolbarBtn instanceof HTMLButtonElement) {
        rosterToolbarBtn.textContent = 'Agent Roster';
        rosterToolbarBtn.setAttribute('aria-pressed', state.rosterOpen ? 'true' : 'false');
        rosterToolbarBtn.style.padding = '8px 14px';
        rosterToolbarBtn.style.borderRadius = '12px';
        rosterToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        rosterToolbarBtn.style.background = state.rosterOpen ? 'rgba(81, 125, 205, 0.34)' : 'rgba(17, 27, 44, 0.72)';
        rosterToolbarBtn.style.color = 'rgba(234, 242, 255, 0.92)';
        rosterToolbarBtn.style.fontSize = '0.82rem';
        rosterToolbarBtn.style.fontWeight = '600';
    }
    const chatToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-chat="1"]');
    if (chatToolbarBtn instanceof HTMLButtonElement) {
        chatToolbarBtn.textContent = 'Chat';
        chatToolbarBtn.setAttribute('aria-pressed', state.agentChatOpen ? 'true' : 'false');
        chatToolbarBtn.style.padding = '8px 14px';
        chatToolbarBtn.style.borderRadius = '12px';
        chatToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        chatToolbarBtn.style.background = state.agentChatOpen ? 'rgba(81, 125, 205, 0.34)' : 'rgba(17, 27, 44, 0.72)';
        chatToolbarBtn.style.color = 'rgba(234, 242, 255, 0.92)';
        chatToolbarBtn.style.fontSize = '0.82rem';
        chatToolbarBtn.style.fontWeight = '600';
    }
    const saveToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-save="1"]');
    if (saveToolbarBtn instanceof HTMLButtonElement) {
        saveToolbarBtn.textContent = 'Save';
        saveToolbarBtn.style.padding = '8px 14px';
        saveToolbarBtn.style.borderRadius = '12px';
        saveToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        saveToolbarBtn.style.background = 'rgba(20, 38, 64, 0.86)';
        saveToolbarBtn.style.color = 'rgba(234, 242, 255, 0.92)';
        saveToolbarBtn.style.fontSize = '0.82rem';
        saveToolbarBtn.style.fontWeight = '600';
    }
    const undoToolbarBtn = officeSceneWrap?.querySelector('[data-office-map-toolbar-undo="1"]');
    if (undoToolbarBtn instanceof HTMLButtonElement) {
        const canUndo = Array.isArray(state.undoStack) && state.undoStack.length > 0;
        undoToolbarBtn.textContent = 'Back';
        undoToolbarBtn.disabled = !canUndo;
        undoToolbarBtn.style.padding = '8px 14px';
        undoToolbarBtn.style.borderRadius = '12px';
        undoToolbarBtn.style.border = '1px solid rgba(112, 139, 184, 0.28)';
        undoToolbarBtn.style.background = canUndo ? 'rgba(28, 44, 73, 0.78)' : 'rgba(17, 27, 44, 0.42)';
        undoToolbarBtn.style.color = canUndo ? 'rgba(234, 242, 255, 0.92)' : 'rgba(168, 184, 209, 0.56)';
        undoToolbarBtn.style.fontSize = '0.82rem';
        undoToolbarBtn.style.fontWeight = '600';
        undoToolbarBtn.style.cursor = canUndo ? 'pointer' : 'not-allowed';
        undoToolbarBtn.style.opacity = canUndo ? '1' : '0.72';
    }
    const toolbarStatus = officeSceneWrap?.querySelector('[data-office-map-badge="1"]');
    if (toolbarStatus instanceof HTMLElement) {
        toolbarStatus.style.display = 'none';
    }
    const editorPanel = officeSceneWrap?.querySelector('[data-office-editor-panel="1"]');
    if (editorPanel instanceof HTMLElement) {
        editorPanel.style.position = 'absolute';
        editorPanel.style.top = '62px';
        editorPanel.style.right = '14px';
        editorPanel.style.width = '520px';
        editorPanel.style.maxWidth = 'calc(100% - 28px)';
        editorPanel.style.height = 'calc(100% - 92px)';
        editorPanel.style.maxHeight = 'calc(100% - 92px)';
        editorPanel.style.flexDirection = 'column';
        editorPanel.style.minHeight = '0';
        editorPanel.style.overflow = 'hidden';
        editorPanel.style.padding = '14px';
        editorPanel.style.borderRadius = '18px';
        editorPanel.style.border = '1px solid rgba(112, 139, 184, 0.24)';
        editorPanel.style.background = 'rgba(8, 14, 24, 0.98)';
        editorPanel.style.backdropFilter = 'none';
        editorPanel.style.boxShadow = '0 14px 34px rgba(0, 0, 0, 0.24)';
        editorPanel.style.zIndex = '12';
    }
    const rosterPanel = officeSceneWrap?.querySelector('[data-office-agent-roster-panel="1"]');
    if (rosterPanel instanceof HTMLElement) {
        rosterPanel.style.position = 'absolute';
        rosterPanel.style.top = '62px';
        rosterPanel.style.left = '14px';
        rosterPanel.style.width = '430px';
        rosterPanel.style.maxWidth = 'calc(100% - 28px)';
        rosterPanel.style.maxHeight = 'calc(100% - 92px)';
        rosterPanel.style.overflow = 'auto';
        rosterPanel.style.padding = '14px';
        rosterPanel.style.borderRadius = '18px';
        rosterPanel.style.border = '1px solid rgba(112, 139, 184, 0.24)';
        rosterPanel.style.background = 'rgba(8, 14, 24, 0.98)';
        rosterPanel.style.backdropFilter = 'none';
        rosterPanel.style.boxShadow = '0 14px 34px rgba(0, 0, 0, 0.24)';
        rosterPanel.style.zIndex = '12';
    }
    const chatPanel = officeSceneWrap?.querySelector('[data-office-agent-chat-panel="1"]');
    if (chatPanel instanceof HTMLElement) {
        chatPanel.style.position = 'absolute';
        chatPanel.style.top = '62px';
        chatPanel.style.right = state.editorOpen ? '548px' : '14px';
        chatPanel.style.width = '520px';
        chatPanel.style.maxWidth = 'calc(100% - 28px)';
        chatPanel.style.maxHeight = 'calc(100% - 92px)';
        chatPanel.style.overflow = 'hidden';
        chatPanel.style.gridTemplateRows = 'auto auto minmax(0,1fr) auto';
        chatPanel.style.gap = '10px';
        chatPanel.style.padding = '12px';
        chatPanel.style.borderRadius = '18px';
        chatPanel.style.border = '1px solid rgba(112, 139, 184, 0.24)';
        chatPanel.style.background = 'rgba(8, 14, 24, 0.98)';
        chatPanel.style.backdropFilter = 'none';
        chatPanel.style.boxShadow = '0 14px 34px rgba(0, 0, 0, 0.24)';
        chatPanel.style.zIndex = '13';
    }
    if (officeMinimap instanceof HTMLElement) {
        officeMinimap.style.display = state.minimapMinimized ? 'none' : 'block';
        officeMinimap.style.position = 'absolute';
        officeMinimap.style.right = '34px';
        officeMinimap.style.bottom = '34px';
        officeMinimap.style.width = `${state.minimapSize}px`;
        officeMinimap.style.height = `${state.minimapSize}px`;
        officeMinimap.style.padding = '0';
        officeMinimap.style.border = '1px solid rgba(112, 139, 184, 0.3)';
        officeMinimap.style.borderRadius = '18px';
        officeMinimap.style.background = 'rgba(6, 10, 19, 0.94)';
        officeMinimap.style.backdropFilter = 'none';
        officeMinimap.style.boxShadow = '0 10px 28px rgba(0, 0, 0, 0.24)';
        officeMinimap.style.overflow = 'hidden';
        officeMinimap.style.transform = `translate3d(${state.minimapOffsetX}px, ${state.minimapOffsetY}px, 0)`;
        officeMinimap.style.zIndex = '12';
        officeMinimap.style.userSelect = 'none';
        officeMinimap.style.cursor = state.minimapLocked ? 'default' : (state.minimapPointerMode === 'panel' && state.minimapPointerId !== null ? 'grabbing' : 'default');
    }
    const minimapHead = officeMinimap?.querySelector('.office-minimap-head');
    if (minimapHead instanceof HTMLElement) {
        minimapHead.style.display = 'flex';
        minimapHead.style.alignItems = 'center';
        minimapHead.style.justifyContent = 'space-between';
        minimapHead.style.position = 'absolute';
        minimapHead.style.top = '8px';
        minimapHead.style.left = '8px';
        minimapHead.style.right = '8px';
        minimapHead.style.zIndex = '2';
        minimapHead.style.gap = '6px';
        minimapHead.style.padding = '0';
        minimapHead.style.cursor = 'default';
        minimapHead.style.background = 'transparent';
        minimapHead.style.borderBottom = '0';
        minimapHead.style.userSelect = 'none';
    }
    const minimapLockBtn = officeMinimap?.querySelector('[data-office-minimap-lock="1"]');
    if (minimapLockBtn instanceof HTMLElement) {
        minimapLockBtn.textContent = state.minimapLocked ? 'Lock' : 'Move';
        minimapLockBtn.setAttribute('aria-pressed', state.minimapLocked ? 'true' : 'false');
        minimapLockBtn.setAttribute('aria-label', state.minimapLocked ? 'Minimap locked' : 'Minimap can move');
        minimapLockBtn.style.display = 'inline-flex';
        minimapLockBtn.style.alignItems = 'center';
        minimapLockBtn.style.justifyContent = 'center';
        minimapLockBtn.style.minWidth = '42px';
        minimapLockBtn.style.padding = '4px 8px';
        minimapLockBtn.style.fontSize = '0.68rem';
        minimapLockBtn.style.fontWeight = '800';
        minimapLockBtn.style.borderRadius = '8px';
        minimapLockBtn.style.border = state.minimapLocked ? '1px solid rgba(142, 199, 255, 0.62)' : '1px solid rgba(112, 139, 184, 0.26)';
        minimapLockBtn.style.background = state.minimapLocked ? 'rgba(40, 83, 138, 0.88)' : 'rgba(11, 18, 32, 0.84)';
        minimapLockBtn.style.color = 'rgba(235, 243, 255, 0.94)';
        minimapLockBtn.style.cursor = 'pointer';
    }
    const minimapLabel = minimapHead?.querySelector('span');
    if (minimapLabel instanceof HTMLElement) {
        minimapLabel.textContent = '';
        minimapLabel.style.display = 'none';
    }
    if (officeFollowToggleBtn instanceof HTMLElement) {
        officeFollowToggleBtn.textContent = state.minimapMinimized ? 'Show' : 'Hide';
        officeFollowToggleBtn.style.display = 'inline-flex';
        officeFollowToggleBtn.style.alignItems = 'center';
        officeFollowToggleBtn.style.justifyContent = 'center';
        officeFollowToggleBtn.style.padding = '4px 8px';
        officeFollowToggleBtn.style.fontSize = '0.68rem';
        officeFollowToggleBtn.style.fontWeight = '600';
        officeFollowToggleBtn.style.borderRadius = '8px';
        officeFollowToggleBtn.style.border = '1px solid rgba(112, 139, 184, 0.26)';
        officeFollowToggleBtn.style.background = 'rgba(11, 18, 32, 0.84)';
        officeFollowToggleBtn.style.color = 'rgba(235, 243, 255, 0.92)';
    }
    if (officeMinimapCanvas instanceof HTMLCanvasElement) {
        officeMinimapCanvas.style.display = 'block';
        officeMinimapCanvas.style.width = `${state.minimapSize}px`;
        officeMinimapCanvas.style.height = `${state.minimapSize}px`;
        officeMinimapCanvas.style.cursor = state.minimapPointerMode === 'camera' && state.minimapPointerId !== null ? 'grabbing' : 'crosshair';
        officeMinimapCanvas.setAttribute('aria-label', 'Virtual office minimap showing the current camera window.');
    }
    const resizeHandle = officeMinimap?.querySelector('[data-office-minimap-resize="1"]');
    if (resizeHandle instanceof HTMLElement) {
        resizeHandle.style.position = 'absolute';
        resizeHandle.style.right = '10px';
        resizeHandle.style.bottom = '10px';
        resizeHandle.style.display = state.minimapLocked ? 'none' : 'block';
        resizeHandle.style.width = '14px';
        resizeHandle.style.height = '14px';
        resizeHandle.style.padding = '0';
        resizeHandle.style.borderRadius = '0';
        resizeHandle.style.cursor = 'nwse-resize';
        resizeHandle.style.background = 'transparent';
        resizeHandle.style.borderRight = '3px solid rgba(152, 193, 255, 0.92)';
        resizeHandle.style.borderBottom = '3px solid rgba(152, 193, 255, 0.92)';
        resizeHandle.style.boxShadow = 'none';
        resizeHandle.style.color = 'transparent';
        resizeHandle.style.fontSize = '0';
    }
    const liveRect = officeSceneWrap?.getBoundingClientRect();
    const hasLiveViewport = Boolean(liveRect && liveRect.width > 1 && liveRect.height > 1);
    if (!state.initialized || (hasLiveViewport && !state.hasLiveViewport)) {
        officeCenterDraftMapViewport();
        state.initialized = true;
        state.hasLiveViewport = hasLiveViewport;
    } else {
        const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
        state.panX = clamped.panX;
        state.panY = clamped.panY;
    }
}

function officeDraftMapPlane() {
    return officeScene?.querySelector('[data-office-map-plane="1"]') || null;
}

function officeDraftDebugSnapshot() {
    const state = typeof officeEnsureDraftMapState === 'function' ? officeEnsureDraftMapState() : null;
    const plane = officeDraftMapPlane();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    const network = state ? officeDraftAutoHallwayNetwork(spaces) : null;
    const agentNodes = Array.from(plane?.querySelectorAll('[data-office-draft-agent-id]') || []);
    const layerNodes = Array.from(plane?.querySelectorAll('[data-office-draft-agent-layer]') || []);
    const animationStates = [...new Set(agentNodes.map((node) => safeString(node?.dataset?.officeAgentAnimation)).filter(Boolean))].sort();
    const draftRoutes = (officeState?.agents || []).map((agent) => {
        const motion = agent?.draftMotion && typeof agent.draftMotion === 'object' ? agent.draftMotion : null;
        const route = motion && Array.isArray(motion.route)
            ? [
                { x: Math.round(Number(motion.x) || 0), y: Math.round(Number(motion.y) || 0) },
                ...motion.route.slice(Math.max(0, Number(motion.routeIndex) || 0)).map((point) => ({
                    x: Math.round(Number(point?.x) || 0),
                    y: Math.round(Number(point?.y) || 0),
                })),
            ]
            : [];
        return {
            agentId: safeString(agent?.id),
            points: route,
        };
    }).filter((entry) => entry.points.length > 1);
    const draftRouteWallViolations = [];
    const draftRouteObstacleViolations = [];
    let draftRouteSegmentsChecked = 0;
    for (const entry of draftRoutes) {
        for (let index = 0; index < entry.points.length - 1; index += 1) {
            if (draftRouteSegmentsChecked >= OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT) break;
            draftRouteSegmentsChecked += 1;
            const violation = officeDraftRouteSegmentWallViolation(entry.points[index], entry.points[index + 1], spaces, network);
            if (violation) {
                draftRouteWallViolations.push({
                    agentId: entry.agentId,
                    segmentIndex: index,
                    ...violation,
                });
            }
            const obstacleViolation = officeDraftRouteSegmentObstacleViolation(entry.points[index], entry.points[index + 1], spaces, network);
            if (obstacleViolation) {
                draftRouteObstacleViolations.push({
                    agentId: entry.agentId,
                    segmentIndex: index,
                    ...obstacleViolation,
                });
            }
        }
        if (draftRouteSegmentsChecked >= OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT) break;
    }
    const navStats = (officeState?.agents || []).map((agent) => officeDraftAgentNavStats(agent)).filter(Boolean);
    const isVisible = (el) => {
        if (!(el instanceof HTMLElement)) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity || 1) > 0.02
            && rect.width > 2
            && rect.height > 2
            && rect.right > 0
            && rect.bottom > 0
            && rect.left < window.innerWidth
            && rect.top < window.innerHeight;
    };
    return {
        schemaVersion: OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION,
        mapSize: OFFICE_DRAFT_MAP_SIZE,
        zoom: Math.round((Number(state?.zoom) || 0) * 1000) / 1000,
        panX: Math.round(Number(state?.panX) || 0),
        panY: Math.round(Number(state?.panY) || 0),
        lastInputMode: safeString(state?.lastInputMode),
        lastWheelDelta: Number(state?.lastWheelDelta) || 0,
        lastZoomDelta: Number(state?.lastZoomDelta) || 0,
        lastPanDeltaScreen: Number(state?.lastPanDeltaScreen) || 0,
        selectedSpaceId: safeString(state?.selectedSpaceId),
        focusSpaceId: state && typeof officeDraftInitialFocusSpace === 'function'
            ? safeString(officeDraftInitialFocusSpace(state)?.id)
            : '',
        spaces: spaces.length,
        roomAssets: spaces.reduce((count, space) => count + (Array.isArray(space?.assets) ? space.assets.length : 0), 0),
        catalogAssets: Object.keys(OFFICE_DRAFT_ASSET_LIBRARY || {}).length,
        floorPalettes: Object.keys(OFFICE_DRAFT_ROOM_FLOOR_PALETTES || {}).length,
        hallwaySegments: Number(network?.segments?.length) || 0,
        hallwayDoors: Number(network?.doors?.size) || 0,
        hallwayNodes: Number(network?.nodes?.length) || 0,
        hallwayPaths: plane?.querySelectorAll('[data-office-draft-hallway-path="floor"]').length || 0,
        hallwayPaintLayers: plane?.querySelectorAll('[data-office-draft-hallway-path]').length || 0,
        agentCount: officeState?.agents?.length || 0,
        agentNodes: agentNodes.length,
        visibleAgentNodes: agentNodes.filter(isVisible).length,
        draftAgentRoutes: draftRoutes.length,
        draftAgentRoutePoints: draftRoutes.reduce((count, route) => count + route.points.length, 0),
        draftAgentRouteSegmentsChecked: draftRouteSegmentsChecked,
        draftAgentWallViolations: draftRouteWallViolations.length,
        draftAgentObstacleViolations: draftRouteObstacleViolations.length,
        draftAgentNavVersion: OFFICE_DRAFT_AGENT_NAV_VERSION,
        draftAgentRouteResets: navStats.reduce((sum, stats) => sum + (Number(stats.routeResets) || 0), 0),
        draftAgentObstacleDetours: navStats.reduce((sum, stats) => sum + (Number(stats.obstacleDetours) || 0), 0),
        draftAgentStuckReplans: navStats.reduce((sum, stats) => sum + (Number(stats.stuckReplans) || 0), 0),
        draftAgentHardClamps: navStats.reduce((sum, stats) => sum + (Number(stats.hardClamps) || 0), 0),
        draftAgentWanderTargets: navStats.reduce((sum, stats) => sum + (Number(stats.wanderTargets) || 0), 0),
        draftAgentMaxJump: navStats.reduce((max, stats) => Math.max(max, Number(stats.maxJump) || 0), 0),
        draftAgentAnimationsAvailable: OFFICE_DRAFT_AGENT_ANIMATIONS.length,
        draftAgentAnimationStates: animationStates,
        draftAgentClickableNodes: agentNodes.filter((node) => node instanceof HTMLElement && window.getComputedStyle(node).pointerEvents !== 'none').length,
        draftAgentDragging: Boolean(state?.agentDragActive),
        draftAgentDragRenders: Number(state?.agentLayerRenderSources?.['agent-drag']) || 0,
        globalAgentLayers: layerNodes.filter((node) => safeString(node?.dataset?.officeDraftAgentLayer) === 'global').length,
        roomAgentLayers: layerNodes.filter((node) => safeString(node?.dataset?.officeDraftAgentLayer) !== 'global').length,
        minimapVisible: Boolean(officeMinimap instanceof HTMLElement && officeMinimap.style.display !== 'none'),
        minimapSize: state?.minimapSize || 0,
    };
}

function officeDraftDrawMiniHallwayNetwork(ctx, network, scale) {
    const segments = Array.isArray(network?.segments) ? network.segments : [];
    if (!segments.length) return;
    const drawSegments = (strokeStyle, lineWidth) => {
        ctx.beginPath();
        segments.forEach((segment) => {
            ctx.moveTo(segment.x1 * scale, segment.y1 * scale);
            ctx.lineTo(segment.x2 * scale, segment.y2 * scale);
        });
        ctx.strokeStyle = strokeStyle;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
    };
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    drawSegments('rgba(80, 96, 116, 0.92)', Math.max(3, OFFICE_DRAFT_HALLWAY_OUTER_WIDTH * scale));
    drawSegments('rgba(174, 187, 202, 0.98)', Math.max(2, OFFICE_DRAFT_HALLWAY_FLOOR_WIDTH * scale));
    drawSegments('rgba(236, 245, 255, 0.32)', Math.max(1, 10 * scale));
    (Array.isArray(network?.nodes) ? network.nodes : []).forEach((node) => {
        if (safeString(node?.kind) !== 'junction') return;
        ctx.fillStyle = 'rgba(165, 177, 192, 0.96)';
        ctx.strokeStyle = 'rgba(39, 53, 74, 0.78)';
        ctx.lineWidth = Math.max(1, 10 * scale);
        ctx.beginPath();
        ctx.arc(node.x * scale, node.y * scale, Math.max(1.6, 46 * scale), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
    });
    ctx.restore();
}

function officeRenderDraftMapMinimap() {
    if (!(officeMinimapCanvas instanceof HTMLCanvasElement)) return;
    const state = officeEnsureDraftMapState();
    if (state.minimapMinimized) return;
    const size = state.minimapSize;
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    const targetSize = Math.round(size * dpr);
    if (officeMinimapCanvas.width !== targetSize || officeMinimapCanvas.height !== targetSize) {
        officeMinimapCanvas.width = targetSize;
        officeMinimapCanvas.height = targetSize;
    }
    const ctx = officeMinimapCanvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, targetSize, targetSize);
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#09111d';
    ctx.fillRect(0, 0, size, size);

    const scale = size / OFFICE_DRAFT_MAP_SIZE;
    const minor = Math.max(4, Math.round(OFFICE_DRAFT_MAP_MINOR_GRID * scale));
    const major = Math.max(20, Math.round(OFFICE_DRAFT_MAP_MAJOR_GRID * scale));

    ctx.strokeStyle = 'rgba(92, 116, 158, 0.16)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= size; x += minor) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, size);
        ctx.stroke();
    }
    for (let y = 0; y <= size; y += minor) {
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(size, y + 0.5);
        ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(182, 217, 255, 0.28)';
    for (let x = 0; x <= size; x += major) {
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, size);
        ctx.stroke();
    }
    for (let y = 0; y <= size; y += major) {
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(size, y + 0.5);
        ctx.stroke();
    }

    const spaces = Array.isArray(state.spaces) ? state.spaces : [];
    const byId = new Map(spaces.map((space) => [safeString(space?.id), space]));
    const network = officeDraftAutoHallwayNetwork(spaces);
    officeDraftDrawMiniHallwayNetwork(ctx, network, scale);

    spaces.forEach((space) => {
        const palette = officeDraftRoomPalette(space?.floorPalette);
        const x = (Number(space?.x) || 0) * scale;
        const y = (Number(space?.y) || 0) * scale;
        const width = Math.max(4, (Number(space?.width) || 0) * scale);
        const height = Math.max(4, (Number(space?.height) || 0) * scale);
        ctx.fillStyle = safeString(space?.id) === safeString(state.selectedSpaceId)
            ? 'rgba(92, 158, 255, 0.42)'
            : 'rgba(221, 231, 244, 0.22)';
        ctx.strokeStyle = palette.floorBorder || 'rgba(236, 245, 255, 0.28)';
        ctx.lineWidth = safeString(space?.id) === safeString(state.selectedSpaceId) ? 2 : 1;
        ctx.beginPath();
        ctx.roundRect(x, y, width, height, 4);
        ctx.fill();
        ctx.stroke();
    });

    const assignments = officeDraftAgentAssignmentMap(state);
    assignments.forEach((agents, spaceId) => {
        const space = byId.get(spaceId);
        if (!space || !Array.isArray(agents)) return;
        agents.slice(0, 18).forEach((agent, index) => {
            const placement = officeDraftAgentPlacement(space, agent, index, agents.length, performance.now());
            const worldX = ((Number(space.x) || 0) + placement.x) * scale;
            const worldY = ((Number(space.y) || 0) + placement.y) * scale;
            ctx.fillStyle = /^#[0-9a-f]{6}$/i.test(safeString(agent?.color)) ? safeString(agent.color) : '#9ad8ff';
            ctx.strokeStyle = 'rgba(6, 10, 18, 0.82)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(worldX, worldY, Math.max(2, 4 * scale), 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        });
    });

    const viewport = officeDraftMapViewportWorldRect();
    const viewX = viewport.x * scale;
    const viewY = viewport.y * scale;
    const viewW = Math.max(6, viewport.width * scale);
    const viewH = Math.max(6, viewport.height * scale);
    ctx.fillStyle = 'rgba(236, 246, 255, 0.08)';
    ctx.strokeStyle = 'rgba(244, 250, 255, 0.92)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.rect(viewX, viewY, Math.min(size - viewX, viewW), Math.min(size - viewY, viewH));
    ctx.fill();
    ctx.stroke();
}

function officeDraftOverviewMode(state) {
    if (!state || state.editorOpen) return false;
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    return zoom <= 0.32;
}

function officeDraftDebugRenderMark(stageRaw) {
    try {
        if (!window.location.search.includes('proof=')) return;
        console.log(`[office-proof-page] render:${safeString(stageRaw)}`);
    } catch (_) {
        // Debug-only marker; ignore logging failures.
    }
}

function officeDraftViewportPadding(state) {
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    return Math.round(Math.max(280, 260 / zoom));
}

function officeDraftSpaceIntersectsViewport(space, viewportRaw, paddingRaw = 0) {
    if (!space || !viewportRaw) return true;
    const padding = Math.max(0, Number(paddingRaw) || 0);
    const left = Number(space.x) || 0;
    const top = Number(space.y) || 0;
    const right = left + (Number(space.width) || 0);
    const bottom = top + (Number(space.height) || 0);
    const viewLeft = (Number(viewportRaw.x) || 0) - padding;
    const viewTop = (Number(viewportRaw.y) || 0) - padding;
    const viewRight = viewLeft + (Number(viewportRaw.width) || 0) + (padding * 2);
    const viewBottom = viewTop + (Number(viewportRaw.height) || 0) + (padding * 2);
    return right >= viewLeft && left <= viewRight && bottom >= viewTop && top <= viewBottom;
}

function officeDraftOverviewColor(space, role = 'floor') {
    const paletteId = safeString(space?.floorPalette);
    const colors = {
        tan: { shell: 'rgba(142, 116, 88, 0.96)', floor: 'rgba(205, 176, 137, 0.94)', dot: 'rgba(232, 202, 158, 0.95)' },
        sand: { shell: 'rgba(154, 133, 95, 0.96)', floor: 'rgba(220, 197, 158, 0.94)', dot: 'rgba(246, 218, 169, 0.95)' },
        clay: { shell: 'rgba(132, 91, 67, 0.96)', floor: 'rgba(195, 148, 115, 0.94)', dot: 'rgba(234, 174, 135, 0.95)' },
        slate: { shell: 'rgba(75, 88, 110, 0.96)', floor: 'rgba(133, 149, 174, 0.94)', dot: 'rgba(166, 190, 224, 0.95)' },
        carpet: { shell: 'rgba(82, 68, 106, 0.96)', floor: 'rgba(134, 105, 157, 0.94)', dot: 'rgba(184, 140, 208, 0.95)' },
        terrazzo: { shell: 'rgba(102, 126, 122, 0.96)', floor: 'rgba(183, 204, 198, 0.94)', dot: 'rgba(219, 238, 231, 0.95)' },
    };
    return colors[paletteId]?.[role] || colors.tan[role];
}

function officeDraftOverviewAssetKind(typeRaw, shapeRaw = '') {
    const type = safeString(typeRaw);
    const shape = safeString(shapeRaw);
    if (['plant', 'tall_plant', 'planter_box'].includes(type)) return 'plant';
    if (['chair', 'meeting_chair', 'lounge_chair', 'stool', 'couch', 'loveseat', 'bench', 'ottoman', 'bean_bag'].includes(type) || shape === 'soft_seat') return 'seat';
    if (shape === 'screen' || shape === 'console' || ['workstation', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall', 'wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand', 'security_console', 'server_console', 'sound_mixer'].includes(type)) return 'screen';
    if (shape === 'board' || shape === 'panel' || ['whiteboard', 'kanban_board', 'pinboard', 'sticky_note_wall', 'dispatch_board', 'green_screen'].includes(type)) return 'board';
    if (shape === 'cabinet' || shape === 'shelf' || ['bookshelf', 'server_rack', 'storage_locker', 'filing_cabinet', 'mail_sorter', 'mail_cart', 'package_station', 'printer', 'copier'].includes(type)) return 'storage';
    if (shape === 'appliance' || shape === 'machine' || shape === 'dock' || shape === 'node' || ['vending_machine', 'coffee_bar', 'ticket_kiosk', 'charging_dock', 'network_switch', 'router_node', 'firewall_box', 'testing_rig', 'game_console', 'arcade_cabinet'].includes(type)) return 'machine';
    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') return 'tower';
    if (shape === 'table' || shape === 'tilt_table' || shape === 'counter' || shape === 'bench' || ['desk', 'round_table', 'conference_table', 'podcast_desk', 'kitchen_island', 'recipe_counter'].includes(type)) return 'table';
    return 'item';
}

function officeDraftOverviewAssetVisualSpec(typeRaw, shapeRaw, zoomRaw) {
    const kind = officeDraftOverviewAssetKind(typeRaw, shapeRaw);
    const zoom = Math.max(0.12, Math.min(0.32, Number(zoomRaw) || 0.26));
    const screenByKind = {
        board: [34, 20],
        item: [22, 15],
        machine: [26, 24],
        plant: [19, 24],
        screen: [30, 18],
        seat: [28, 20],
        storage: [24, 25],
        table: [34, 21],
        tower: [18, 28],
    }[kind] || [24, 18];
    return {
        kind,
        width: Math.round(screenByKind[0] / zoom),
        height: Math.round(screenByKind[1] / zoom),
        border: Math.max(3, Math.round(2.4 / zoom)),
    };
}

function officeDraftCreateOverviewAssetDetail(root, kind, color = {}) {
    if (!(root instanceof HTMLElement)) return;
    const accent = color.accent || color.arm || 'rgba(173, 219, 255, 0.92)';
    const surface = color.surface || color.seat || color.swatch || 'rgba(195, 214, 232, 0.86)';
    const line = color.line || color.seam || 'rgba(8, 15, 26, 0.46)';
    const part = (styles = {}) => officeDraftAppendAssetPart(root, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    });
    if (kind === 'screen') {
        part({ left: '17%', top: '22%', width: '44%', height: '12%', borderRadius: '999px', background: accent, boxShadow: `0 0 10px ${accent}` });
        part({ left: '20%', top: '46%', width: '57%', height: '8%', borderRadius: '999px', background: surface, opacity: '0.58' });
        part({ left: '34%', bottom: '10%', width: '31%', height: '10%', borderRadius: '999px', background: line, opacity: '0.58' });
        return;
    }
    if (kind === 'board') {
        [20, 39, 58].forEach((left, index) => part({ left: `${left}%`, top: '18%', width: '14%', height: '24%', borderRadius: '4px', background: index === 1 ? accent : 'rgba(255, 229, 139, 0.95)' }));
        part({ left: '18%', top: '58%', width: '56%', height: '8%', borderRadius: '999px', background: line, opacity: '0.38' });
        return;
    }
    if (kind === 'seat') {
        part({ left: '10%', top: '19%', width: '80%', height: '35%', borderRadius: '16px 16px 7px 7px', background: surface, opacity: '0.92' });
        part({ left: '7%', bottom: '18%', width: '86%', height: '34%', borderRadius: '14px', background: color.body || surface, boxShadow: 'inset 0 -8px rgba(0,0,0,0.13)' });
        [26, 50, 74].forEach((left) => part({ left: `${left}%`, bottom: '9%', width: '5%', height: '18%', borderRadius: '999px', background: line, opacity: '0.52' }));
        return;
    }
    if (kind === 'table') {
        part({ left: '8%', top: '22%', width: '84%', height: '35%', borderRadius: '14px', background: surface, boxShadow: 'inset 0 -8px rgba(0,0,0,0.12)' });
        part({ left: '24%', top: '36%', width: '47%', height: '8%', borderRadius: '999px', background: accent, opacity: '0.8' });
        part({ left: '19%', bottom: '14%', width: '8%', height: '23%', borderRadius: '5px', background: line, opacity: '0.45' });
        part({ right: '19%', bottom: '14%', width: '8%', height: '23%', borderRadius: '5px', background: line, opacity: '0.45' });
        return;
    }
    if (kind === 'storage') {
        [24, 43, 62].forEach((top, index) => part({ left: '18%', top: `${top}%`, width: '64%', height: '8%', borderRadius: '999px', background: index === 1 ? accent : surface, opacity: index === 1 ? '0.9' : '0.58' }));
        [30, 50, 70].forEach((left, index) => part({ left: `${left}%`, top: `${34 + (index % 2) * 20}%`, width: '7%', height: '15%', borderRadius: '2px', background: index === 1 ? accent : line, opacity: index === 1 ? '0.86' : '0.4' }));
        return;
    }
    if (kind === 'plant') {
        [22, 39, 56].forEach((left, index) => part({ left: `${left}%`, top: `${14 + (index % 2) * 11}%`, width: '25%', height: '49%', borderRadius: '70% 30% 70% 30%', background: index === 1 ? accent : surface, transform: `rotate(${index === 1 ? 20 : -22}deg)` }));
        part({ left: '22%', bottom: '8%', width: '56%', height: '18%', borderRadius: '9px', background: color.body || line, opacity: '0.72' });
        return;
    }
    if (kind === 'tower') {
        part({ left: '43%', top: '26%', width: '14%', height: '52%', borderRadius: '999px', background: line, opacity: '0.6' });
        part({ left: '20%', top: '12%', width: '60%', height: '29%', borderRadius: '999px', background: surface, boxShadow: `0 0 11px ${accent}` });
        part({ left: '18%', bottom: '8%', width: '64%', height: '9%', borderRadius: '999px', background: line, opacity: '0.52' });
        return;
    }
    if (kind === 'machine') {
        part({ left: '13%', top: '19%', width: '70%', height: '50%', borderRadius: '12px', background: surface, boxShadow: 'inset 0 -7px rgba(0,0,0,0.13)' });
        part({ left: '25%', top: '35%', width: '35%', height: '10%', borderRadius: '999px', background: accent, boxShadow: `0 0 8px ${accent}` });
        part({ right: '19%', top: '35%', width: '10%', height: '10%', borderRadius: '999px', background: line, opacity: '0.46' });
        part({ left: '22%', bottom: '12%', width: '58%', height: '8%', borderRadius: '999px', background: line, opacity: '0.42' });
        return;
    }
    part({ left: '15%', top: '20%', width: '70%', height: '48%', borderRadius: '12px', background: surface });
    part({ left: '24%', top: '39%', width: '42%', height: '10%', borderRadius: '999px', background: accent });
}

function officeDraftCreateOverviewAssetDots(space, assetsRaw = [], stateRaw = null) {
    const assets = Array.isArray(assetsRaw) ? assetsRaw.filter(Boolean).slice(0, 12) : [];
    const state = stateRaw || officeDraftMapState || {};
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const layer = document.createElement('div');
    layer.dataset.officeDraftOverviewAssets = '1';
    layer.style.position = 'absolute';
    layer.style.inset = '0';
    layer.style.pointerEvents = 'none';
    layer.style.contain = 'layout paint style';
    assets.forEach((asset, index) => {
        const type = safeString(asset?.type) || 'desk';
        const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
        const shape = safeString(assetInfo.shape);
        const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
        const spec = officeDraftOverviewAssetVisualSpec(type, shape, zoom);
        const dimensions = officeDraftAssetDimensions(type, asset?.scale);
        const left = Math.round((Number(asset?.x) || 0) + ((Number(dimensions.width) || 0) / 2) - (spec.width / 2));
        const top = Math.round((Number(asset?.y) || 0) + ((Number(dimensions.height) || 0) / 2) - (spec.height / 2));
        const item = document.createElement('span');
        item.dataset.officeDraftOverviewAsset = type;
        item.dataset.officeDraftOverviewAssetKind = spec.kind;
        item.style.position = 'absolute';
        item.style.left = `${left}px`;
        item.style.top = `${top}px`;
        item.style.width = `${spec.width}px`;
        item.style.height = `${spec.height}px`;
        item.style.borderRadius = spec.kind === 'plant' || type === 'round_table' || type === 'bean_bag' ? '999px' : `${Math.max(14, Math.round(5 / zoom))}px`;
        item.style.background = `linear-gradient(180deg, ${color.surface || color.seat || color.swatch || officeDraftOverviewColor(space, 'dot')}, ${color.body || color.back || color.swatch || officeDraftOverviewColor(space, 'shell')})`;
        item.style.border = `${spec.border}px solid ${color.accent || color.arm || 'rgba(210, 231, 255, 0.82)'}`;
        item.style.boxSizing = 'border-box';
        item.style.opacity = String(index < 8 ? 0.9 : 0.68);
        item.style.boxShadow = `0 ${Math.round(5 / zoom)}px ${Math.round(9 / zoom)}px rgba(3, 8, 16, 0.20), inset 0 ${Math.round(2 / zoom)}px 0 rgba(255,255,255,0.18)`;
        item.style.overflow = 'hidden';
        officeDraftCreateOverviewAssetDetail(item, spec.kind, color);
        layer.appendChild(item);
    });
    return layer;
}

function officeApplyDraftMapGridBackground(state, offsetX, offsetY) {
    if (!(officeScene instanceof HTMLElement)) return;
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const minorSize = Math.max(8, Math.round(OFFICE_DRAFT_MAP_MINOR_GRID * zoom));
    const majorSize = Math.max(32, Math.round(OFFICE_DRAFT_MAP_MAJOR_GRID * zoom));
    const minorX = Math.round(offsetX % minorSize);
    const minorY = Math.round(offsetY % minorSize);
    const majorX = Math.round(offsetX % majorSize);
    const majorY = Math.round(offsetY % majorSize);
    officeScene.style.backgroundColor = '#0a1321';
    if (zoom <= 0.32) {
        const overviewSize = Math.max(42, majorSize);
        const overviewX = Math.round(offsetX % overviewSize);
        const overviewY = Math.round(offsetY % overviewSize);
        officeScene.style.backgroundImage = [
            'linear-gradient(rgba(130, 168, 218, 0.14) 1px, transparent 1px)',
            'linear-gradient(90deg, rgba(130, 168, 218, 0.14) 1px, transparent 1px)',
        ].join(',');
        officeScene.style.backgroundSize = [
            `${overviewSize}px ${overviewSize}px`,
            `${overviewSize}px ${overviewSize}px`,
        ].join(',');
        officeScene.style.backgroundPosition = [
            `${overviewX}px ${overviewY}px`,
            `${overviewX}px ${overviewY}px`,
        ].join(',');
        return;
    }
    officeScene.style.backgroundImage = [
        'linear-gradient(rgba(96, 124, 178, 0.10) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(96, 124, 178, 0.10) 1px, transparent 1px)',
        'linear-gradient(rgba(170, 205, 255, 0.20) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(170, 205, 255, 0.20) 1px, transparent 1px)',
    ].join(',');
    officeScene.style.backgroundSize = [
        `${minorSize}px ${minorSize}px`,
        `${minorSize}px ${minorSize}px`,
        `${majorSize}px ${majorSize}px`,
        `${majorSize}px ${majorSize}px`,
    ].join(',');
    officeScene.style.backgroundPosition = [
        `${minorX}px ${minorY}px`,
        `${minorX}px ${minorY}px`,
        `${majorX}px ${majorY}px`,
        `${majorX}px ${majorY}px`,
    ].join(',');
}

function officeRenderDraftMapMinimapThrottled(force = false) {
    const state = officeEnsureDraftMapState();
    const now = performance.now();
    if (force) {
        if (state.minimapRenderTimer) {
            window.clearTimeout(state.minimapRenderTimer);
            state.minimapRenderTimer = 0;
        }
        state.lastMinimapRenderAt = now;
        officeRenderDraftMapMinimap();
        return;
    }
    if (state.minimapRenderTimer) return;
    state.minimapRenderTimer = window.setTimeout(() => {
        state.minimapRenderTimer = 0;
        state.lastMinimapRenderAt = performance.now();
        officeRenderDraftMapMinimap();
    }, 90);
}

function officeApplyDraftMapTransform(options = {}) {
    const state = officeEnsureDraftMapState();
    const plane = officeDraftMapPlane();
    if (!(plane instanceof HTMLElement)) return;
    const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    const offsetX = -(state.panX * state.zoom);
    const offsetY = -(state.panY * state.zoom);
    plane.style.transform = `translate3d(${offsetX.toFixed(2)}px, ${offsetY.toFixed(2)}px, 0) scale(${state.zoom.toFixed(4)})`;
    officeApplyDraftMapGridBackground(state, offsetX, offsetY);
    const badge = officeWorkspace?.querySelector('[data-office-map-badge="1"]');
    if (badge instanceof HTMLElement) {
        badge.textContent = `${Math.round(state.zoom * 100)}% · ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} x ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} grid`;
    }
    officeRenderDraftMapMinimapThrottled(options?.deferMinimap !== true);
}

function officeRenderDraftMapScene(options = {}) {
    if (!officeScene || !officeScenePanzoom) return;
    const state = officeEnsureDraftMapState();
    const renderNow = performance.now();
    officeDraftDebugRenderMark('start');
    if (options?.force !== true && officeDraftSceneRenderQuietActive(state, renderNow)) {
        officeDraftScheduleSceneRenderAfterInput(state, renderNow);
        return;
    }
    if (options?.force === true) {
        window.clearTimeout(state.sceneRenderTimer);
        state.sceneRenderDeferred = false;
    }
    officePrepareDraftMapShell();
    officeScenePanzoom.style.position = 'absolute';
    officeScenePanzoom.style.inset = '0';
    officeScenePanzoom.style.width = '100%';
    officeScenePanzoom.style.height = '100%';
    officeScenePanzoom.style.overflow = 'hidden';
    officeScenePanzoom.style.transformOrigin = 'top left';
    officeScenePanzoom.style.willChange = 'transform';
    officeScenePanzoom.style.setProperty('--office-zoom', '1');
    officeScenePanzoom.style.setProperty('--office-pan-x', '0px');
    officeScenePanzoom.style.setProperty('--office-pan-y', '0px');
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.setProperty('--office-pan-x', '0px');
        officeSceneWrap.style.setProperty('--office-pan-y', '0px');
    }
    officeScene.style.position = 'relative';
    officeScene.style.width = '100%';
    officeScene.style.height = '100%';
    officeScene.style.overflow = 'hidden';
    officeScene.style.backgroundColor = '#0a1321';
    officeScene.innerHTML = '';
    officeDraftDebugRenderMark('shell');
    const plane = document.createElement('div');
    plane.dataset.officeMapPlane = '1';
    plane.style.position = 'absolute';
    plane.style.left = '0';
    plane.style.top = '0';
    plane.style.width = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.height = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.transformOrigin = 'top left';
    plane.style.willChange = 'transform';
    plane.style.contain = 'layout paint style';
    plane.style.background = 'transparent';
    officeRenderDraftRoomConnectors(plane, state);
    officeDraftDebugRenderMark('connectors');
    const initialAgentAssignments = officeDraftAgentAssignmentMap(state);
    const overviewMode = officeDraftOverviewMode(state);
    const viewportWorldRect = officeDraftMapViewportWorldRect();
    const viewportPadding = officeDraftViewportPadding(state);
    state.spaces.forEach((space) => {
        const palette = officeDraftRoomPalette(space?.floorPalette);
        const isSelectedSpace = safeString(space?.id) === safeString(state.selectedSpaceId);
        const spaceNearViewport = officeDraftSpaceIntersectsViewport(space, viewportWorldRect, viewportPadding);
        const renderDetailedSpace = !overviewMode && spaceNearViewport;
        const room = document.createElement('section');
        room.dataset.officeDraftSpaceId = safeString(space?.id);
        room.dataset.officeDraftOverview = overviewMode ? '1' : '0';
        room.dataset.officeDraftDetail = renderDetailedSpace ? '1' : '0';
        room.style.position = 'absolute';
        room.style.zIndex = '1';
        room.style.left = `${Math.round(Number(space?.x) || 0)}px`;
        room.style.top = `${Math.round(Number(space?.y) || 0)}px`;
        room.style.width = `${Math.round(Number(space?.width) || 0)}px`;
        room.style.height = `${Math.round(Number(space?.height) || 0)}px`;
        room.style.border = isSelectedSpace ? '4px solid rgba(122, 181, 255, 0.82)' : '4px solid rgba(158, 196, 255, 0.62)';
        room.style.borderRadius = overviewMode ? '30px' : '46px';
        room.style.background = overviewMode ? officeDraftOverviewColor(space, 'shell') : palette.shell;
        room.style.overflow = 'visible';
        room.style.boxShadow = isSelectedSpace
            ? 'inset 0 0 0 1px rgba(215, 232, 255, 0.08), 0 0 0 2px rgba(110, 169, 255, 0.14), 0 18px 42px rgba(0, 0, 0, 0.22)'
            : 'inset 0 0 0 1px rgba(215, 232, 255, 0.05), 0 16px 38px rgba(0, 0, 0, 0.2)';

        const roomInset = document.createElement('div');
        roomInset.style.position = 'absolute';
        roomInset.style.left = '24px';
        roomInset.style.top = '24px';
        roomInset.style.right = '24px';
        roomInset.style.bottom = '24px';
        roomInset.style.borderRadius = overviewMode ? '22px' : '32px';
        roomInset.style.border = `1px solid ${palette.floorBorder}`;
        roomInset.style.background = overviewMode ? officeDraftOverviewColor(space, 'floor') : palette.floor;
        if (!overviewMode && safeString(palette.pattern)) {
            roomInset.style.backgroundImage = `${palette.pattern}, ${palette.floor}`;
            roomInset.style.backgroundSize = `${safeString(palette.patternSize) || '120px 120px'}, auto`;
        }
        room.appendChild(roomInset);

        const roomLabel = document.createElement('button');
        roomLabel.type = 'button';
        roomLabel.dataset.officeDraftSpaceLabel = safeString(space?.id);
        roomLabel.textContent = safeString(space?.name) || 'Space';
        roomLabel.style.position = 'absolute';
        roomLabel.style.left = '42px';
        roomLabel.style.top = '-32px';
        roomLabel.style.padding = '10px 18px';
        roomLabel.style.borderRadius = '18px 18px 10px 10px';
        roomLabel.style.border = isSelectedSpace ? '2px solid rgba(128, 185, 255, 0.72)' : '2px solid rgba(214, 228, 247, 0.28)';
        roomLabel.style.background = isSelectedSpace ? 'rgba(80, 128, 205, 0.9)' : 'rgba(43, 59, 88, 0.92)';
        roomLabel.style.color = 'rgba(245, 248, 255, 0.96)';
        roomLabel.style.fontSize = overviewMode ? '1rem' : '1.2rem';
        roomLabel.style.fontWeight = '700';
        roomLabel.style.letterSpacing = '0.12em';
        roomLabel.style.textTransform = 'uppercase';
        roomLabel.style.cursor = state.editorOpen ? 'pointer' : 'default';
        room.appendChild(roomLabel);

        const roomAssets = Array.isArray(space?.assets) ? space.assets : [];
        if (renderDetailedSpace) {
            roomAssets.forEach((asset) => {
                room.appendChild(officeDraftCreateAssetElement(space, asset, state));
            });
        } else {
            room.appendChild(officeDraftCreateOverviewAssetDots(space, roomAssets, state));
        }
        if (safeString(state.catalogPreviewSpaceId) === safeString(space?.id) && safeString(state.catalogPendingType)) {
            const pendingType = safeString(state.catalogPendingType);
            room.appendChild(officeDraftCreateAssetElement(space, {
                id: 'catalog-preview',
                type: pendingType,
                x: state.catalogPreviewX,
                y: state.catalogPreviewY,
                rotation: 0,
                colorVariant: officeDraftAssetDefaultColorVariant(pendingType),
                scale: 1,
                preview: true,
            }, state));
        }

        plane.appendChild(room);
    });
    officeDraftDebugRenderMark('rooms');

    const agentLayer = document.createElement('div');
    agentLayer.dataset.officeDraftAgentLayer = 'global';
    agentLayer.style.position = 'absolute';
    agentLayer.style.inset = '0';
    agentLayer.style.pointerEvents = state.editorOpen ? 'none' : 'auto';
    agentLayer.style.zIndex = '4';
    agentLayer.style.overflow = 'visible';
    state.agentLayerForceRender = true;
    const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;
    state.agentLayerSkipRoutePlanning = true;
    try {
        officeDraftDebugRenderMark('agents-before');
        officePopulateDraftGlobalAgentLayer(agentLayer, state, renderNow, initialAgentAssignments, 'scene');
        officeDraftDebugRenderMark('agents-after');
        if (officeState) officeState.lastDraftAgentRenderAt = renderNow;
    } finally {
        state.agentLayerForceRender = false;
        state.agentLayerSkipRoutePlanning = previousSkipRoutePlanning === true;
    }
    plane.appendChild(agentLayer);
    officeDraftDebugRenderMark('agent-layer');
    if (state.agentRoutePlanDeferred) {
        state.routePlanQuietUntil = Math.max(
            Number(state.routePlanQuietUntil) || 0,
            renderNow + OFFICE_DRAFT_AGENT_ROUTE_PLAN_BOOT_QUIET_MS,
        );
        officeDraftScheduleDeferredRoutePlan(state, renderNow);
    }

    officeScene.appendChild(plane);
    officeDraftDebugRenderMark('plane-appended');
    if (officeSceneWrap instanceof HTMLElement && !officeSceneWrap.querySelector('[data-office-map-toolbar="1"]')) {
        const toolbar = document.createElement('div');
        toolbar.dataset.officeMapToolbar = '1';

        const minimapBtn = document.createElement('button');
        minimapBtn.type = 'button';
        minimapBtn.dataset.officeMapToolbarMinimap = '1';
        minimapBtn.textContent = 'Minimap';
        minimapBtn.addEventListener('click', officeToggleDraftMinimapMinimized);

        const editorBtn = document.createElement('button');
        editorBtn.type = 'button';
        editorBtn.dataset.officeMapToolbarEditor = '1';
        editorBtn.textContent = 'Office Editor';
        editorBtn.addEventListener('click', officeToggleDraftEditor);

        const rosterBtn = document.createElement('button');
        rosterBtn.type = 'button';
        rosterBtn.dataset.officeMapToolbarRoster = '1';
        rosterBtn.textContent = 'Agent Roster';
        rosterBtn.addEventListener('click', officeToggleDraftAgentRoster);

        const chatBtn = document.createElement('button');
        chatBtn.type = 'button';
        chatBtn.dataset.officeMapToolbarChat = '1';
        chatBtn.textContent = 'Chat';
        chatBtn.addEventListener('click', officeToggleDraftAgentChat);

        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.dataset.officeMapToolbarSave = '1';
        saveBtn.textContent = 'Save';
        saveBtn.addEventListener('click', officeDraftManualSaveLayout);

        const undoBtn = document.createElement('button');
        undoBtn.type = 'button';
        undoBtn.dataset.officeMapToolbarUndo = '1';
        undoBtn.textContent = 'Back';
        undoBtn.addEventListener('click', officeDraftUndoLastChange);

        const badge = document.createElement('span');
        badge.dataset.officeMapBadge = '1';

        toolbar.appendChild(minimapBtn);
        toolbar.appendChild(editorBtn);
        toolbar.appendChild(rosterBtn);
        toolbar.appendChild(chatBtn);
        toolbar.appendChild(saveBtn);
        toolbar.appendChild(undoBtn);
        toolbar.appendChild(badge);
        officeSceneWrap.appendChild(toolbar);
    }
    if (officeMinimap instanceof HTMLElement && !officeMinimap.querySelector('[data-office-minimap-resize="1"]')) {
        const resizeHandle = document.createElement('div');
        resizeHandle.dataset.officeMinimapResize = '1';
        resizeHandle.setAttribute('aria-label', 'Resize minimap');
        officeMinimap.appendChild(resizeHandle);
    }
    const minimapHead = officeMinimap?.querySelector('.office-minimap-head');
    if (minimapHead instanceof HTMLElement && !minimapHead.querySelector('[data-office-minimap-lock="1"]')) {
        const lockButton = document.createElement('button');
        lockButton.type = 'button';
        lockButton.dataset.officeMinimapLock = '1';
        lockButton.textContent = 'Lock';
        lockButton.addEventListener('click', officeToggleDraftMinimapLocked);
        minimapHead.prepend(lockButton);
    }
    officeRenderDraftMapEditorPanel();
    officeRenderDraftAgentRosterPanel();
    officeRenderDraftAgentChatPanel();
    officePrepareDraftMapShell();
    officeApplyDraftMapTransform();
    const attachedAgentLayer = officeScene.querySelector('[data-office-draft-agent-layer="global"]');
    if (attachedAgentLayer instanceof HTMLElement) {
        officeDraftResolveAgentElementOverlaps(attachedAgentLayer);
    }
    officeRenderDraftMapMinimap();
    officeDraftDebugRenderMark('done');
}

function officeBindDraftMapControls() {
    if (!(officeSceneWrap instanceof HTMLElement) || officeSceneWrap.dataset.officeDraftMapBound === '1') return;
    officeSceneWrap.dataset.officeDraftMapBound = '1';
    officeSceneWrap.addEventListener('pointerdown', officeHandleDraftMapPointerDown);
    officeSceneWrap.addEventListener('pointermove', officeHandleDraftMapPointerMove);
    officeSceneWrap.addEventListener('pointerup', officeHandleDraftMapPointerUp);
    officeSceneWrap.addEventListener('pointercancel', officeHandleDraftMapPointerUp);
    officeSceneWrap.addEventListener('mousemove', officeHandleDraftMapMouseMove, { passive: true });
    officeSceneWrap.addEventListener('wheel', officeHandleDraftMapWheel, { passive: false });
    officeSceneWrap.addEventListener('keydown', officeHandleDraftMapKeydown);
    officeSceneWrap.addEventListener('click', officeHandleDraftMapClick);
    window.addEventListener('resize', officeHandleDraftMapResize);
    if (officeMinimap instanceof HTMLElement) {
        officeMinimap.addEventListener('pointerdown', officeHandleDraftMinimapPointerDown);
        officeMinimap.addEventListener('pointermove', officeHandleDraftMinimapPointerMove);
        officeMinimap.addEventListener('pointerup', officeHandleDraftMinimapPointerUp);
        officeMinimap.addEventListener('pointercancel', officeHandleDraftMinimapPointerUp);
    }
    const minimapResizeHandle = officeMinimap?.querySelector('[data-office-minimap-resize="1"]');
    if (minimapResizeHandle instanceof HTMLElement) {
        minimapResizeHandle.addEventListener('pointerdown', officeHandleDraftMinimapResizePointerDown);
        minimapResizeHandle.addEventListener('pointermove', officeHandleDraftMinimapResizePointerMove);
        minimapResizeHandle.addEventListener('pointerup', officeHandleDraftMinimapResizePointerUp);
        minimapResizeHandle.addEventListener('pointercancel', officeHandleDraftMinimapResizePointerUp);
    }
    if (officeFollowToggleBtn instanceof HTMLElement) {
        officeFollowToggleBtn.addEventListener('click', officeToggleDraftMinimapMinimized);
    }
}

function officeDraftMapWheelPassesThrough(event) {
    const target = event?.target;
    if (!(target instanceof Element)) return false;
    if (officeMinimap instanceof HTMLElement && officeMinimap.contains(target)) return true;
    if (target.closest('[data-office-map-toolbar="1"]')) return true;
    if (target.closest('[data-office-editor-panel="1"]')) return true;
    if (target.closest('[data-office-agent-roster-panel="1"]')) return true;
    if (target.closest('[data-office-agent-chat-panel="1"]')) return true;
    if (target.closest('input, select, textarea, [contenteditable="true"]')) return true;
    return false;
}

function officeHandleDraftMapMouseMove(event) {
    if (officeDraftMapWheelPassesThrough(event)) return;
    const state = officeEnsureDraftMapState();
    if (state.pointerId !== null || state.assetPointerId !== null || state.catalogPointerId !== null || state.agentPointerId !== null) return;
    const now = performance.now();
    if ((now - (Number(state.lastPointerIntentAt) || 0)) < 80) return;
    state.lastPointerIntentAt = now;
    state.agentLayerQuietUntil = Math.max(Number(state.agentLayerQuietUntil) || 0, now + OFFICE_DRAFT_AGENT_POINTER_QUIET_MS);
    state.routePlanQuietUntil = Math.max(Number(state.routePlanQuietUntil) || 0, now + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS);
    if (state.agentRoutePlanTimer) {
        window.clearTimeout(state.agentRoutePlanTimer);
        state.agentRoutePlanTimer = 0;
        officeDraftScheduleDeferredRoutePlan(state, now);
    }
}

function officeHandleDraftMapPointerDown(event) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (event.target instanceof Element) {
        if (officeMinimap instanceof HTMLElement && officeMinimap.contains(event.target)) return;
        if (event.target.closest('[data-office-map-toolbar="1"]')) return;
        const agentTarget = event.target.closest('[data-office-draft-agent-id]');
        if (agentTarget instanceof HTMLElement) {
            officeDraftHandleAgentPointerDown(event, agentTarget.dataset.officeDraftAgentId);
            return;
        }
        if (event.target.closest('[data-office-agent-roster-panel="1"]')) return;
        if (event.target.closest('[data-office-agent-chat-panel="1"]')) return;
        if (event.target.closest('[data-office-editor-panel="1"]')) {
            const catalogBtn = event.target.closest('[data-office-editor-catalog-asset]');
            if (catalogBtn instanceof HTMLElement && state.editorOpen) {
                officeDraftBeginCatalogPlacement(catalogBtn.dataset.officeEditorCatalogAsset, event.pointerId, event.clientX, event.clientY);
                officeSceneWrap.style.cursor = 'grabbing';
                officeSceneWrap.setPointerCapture(event.pointerId);
            }
            return;
        }
        if (state.editorOpen) {
            if (event.target.closest('[data-office-draft-space-label]')) return;
            const assetEl = event.target.closest('[data-office-draft-asset-id]');
            if (assetEl instanceof HTMLElement) {
                const assetRef = officeDraftFindAsset(assetEl.dataset.officeDraftAssetId);
                const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
                if (assetRef && worldPoint) {
                    state.assetPointerId = event.pointerId;
                    state.assetDragSpaceId = safeString(assetRef.space?.id);
                    state.assetDragId = safeString(assetRef.asset?.id);
                    state.assetDragSnapshot = officeDraftLayoutSnapshot(state);
                    state.selectedSpaceId = safeString(assetRef.space?.id);
                    state.selectedAssetId = safeString(assetRef.asset?.id);
                    state.assetDragOffsetX = worldPoint.x - (Number(assetRef.space?.x) + Number(assetRef.asset?.x));
                    state.assetDragOffsetY = worldPoint.y - (Number(assetRef.space?.y) + Number(assetRef.asset?.y));
                    officeSceneWrap.style.cursor = 'grabbing';
                    officeSceneWrap.setPointerCapture(event.pointerId);
                    officeRenderDraftMapScene();
                    return;
                }
            }
        }
    }
    if (state.editorOpen !== true) {
        const preferredAgentId = safeString(state.hoveredAgentId);
        const nearbyAgentId = officeDraftNearestAgentIdAtClient(
            event.clientX,
            event.clientY,
            preferredAgentId ? 124 : 56,
            preferredAgentId,
        );
        if (nearbyAgentId) {
            officeDraftHandleAgentPointerDown(event, nearbyAgentId);
            return;
        }
    }
    state.pointerId = event.pointerId;
    state.dragStartX = event.clientX;
    state.dragStartY = event.clientY;
    state.dragPanX = state.panX;
    state.dragPanY = state.panY;
    officeDraftCancelAgentHoverRender(state);
    state.lastPanAt = performance.now();
    state.lastInputMode = 'pan';
    if (state.sceneRenderDeferred) {
        officeDraftScheduleSceneRenderAfterInput(state, state.lastPanAt);
    }
    event.preventDefault();
    officeSceneWrap.style.cursor = 'grabbing';
    officeSceneWrap.setPointerCapture(event.pointerId);
}

function officeHandleDraftMapPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (officeDraftHandleAgentPointerMove(event)) return;
    if (state.pointerId !== event.pointerId
        && state.catalogPointerId !== event.pointerId
        && state.assetPointerId !== event.pointerId
        && Number(event.buttons) === 0) {
        officeDraftCancelAgentHoverRender(state);
    }
    if (state.catalogPointerId === event.pointerId && safeString(state.catalogPendingType)) {
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
        const previewPlacement = previewSpace && worldPoint
            ? officeDraftPlaceAssetInSpace(previewSpace, state.catalogPendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
            : null;
        if (previewSpace && previewPlacement) {
            state.catalogPreviewSpaceId = safeString(previewSpace.id);
            state.catalogPreviewX = previewPlacement.x;
            state.catalogPreviewY = previewPlacement.y;
            state.selectedSpaceId = safeString(previewSpace.id);
            if (officeSceneWrap instanceof HTMLElement) {
                officeSceneWrap.style.cursor = 'copy';
            }
        } else {
            state.catalogPreviewSpaceId = '';
            state.catalogPreviewX = 0;
            state.catalogPreviewY = 0;
            if (officeSceneWrap instanceof HTMLElement) {
                officeSceneWrap.style.cursor = 'not-allowed';
            }
        }
        officeRenderDraftMapScene();
        return;
    }
    if (state.assetPointerId === event.pointerId && state.assetDragId) {
        const assetRef = officeDraftFindAsset(state.assetDragId);
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        if (assetRef && worldPoint) {
            const descriptor = officeDraftAssetDimensions(assetRef.asset?.type, assetRef.asset?.scale);
            assetRef.asset.x = Math.max(24, Math.min(
                Number(assetRef.space?.width) - descriptor.width - 24,
                officeDraftSnap(
                    worldPoint.x - Number(assetRef.space?.x) - state.assetDragOffsetX,
                    OFFICE_DRAFT_MAP_MINOR_GRID,
                    state.gridEnabled,
                ),
            ));
            assetRef.asset.y = Math.max(24, Math.min(
                Number(assetRef.space?.height) - descriptor.height - 24,
                officeDraftSnap(
                    worldPoint.y - Number(assetRef.space?.y) - state.assetDragOffsetY,
                    OFFICE_DRAFT_MAP_MINOR_GRID,
                    state.gridEnabled,
                ),
            ));
            officeRenderDraftMapScene();
        }
        return;
    }
    if (state.pointerId !== event.pointerId) return;
    event.preventDefault();
    const deltaX = event.clientX - state.dragStartX;
    const deltaY = event.clientY - state.dragStartY;
    state.panX = state.dragPanX - (deltaX / state.zoom);
    state.panY = state.dragPanY - (deltaY / state.zoom);
    state.lastPanAt = performance.now();
    state.lastPanDeltaScreen = Math.round(Math.hypot(deltaX, deltaY));
    state.lastInputMode = 'pan';
    officeApplyDraftMapTransform({ deferMinimap: true });
}

function officeHandleDraftMapPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (officeDraftHandleAgentPointerUp(event)) return;
    if (state.catalogPointerId !== null && event.pointerId === state.catalogPointerId) {
        if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
            officeSceneWrap.releasePointerCapture(event.pointerId);
        }
        const pendingType = safeString(state.catalogPendingType);
        const previousSnapshot = officeDraftLayoutSnapshot(state);
        const worldPoint = officeDraftMapClientToWorld(event.clientX, event.clientY);
        const previewSpace = worldPoint ? officeDraftSpaceAtWorldPoint(worldPoint.x, worldPoint.y) : null;
        const previewPlacement = previewSpace && worldPoint
            ? officeDraftPlaceAssetInSpace(previewSpace, pendingType, worldPoint.x, worldPoint.y, { gridEnabled: state.gridEnabled })
            : null;
        if (pendingType && previewSpace && previewPlacement) {
            const assetId = `${pendingType}-${state.nextAssetId++}`;
            const asset = {
                id: assetId,
                type: pendingType,
                x: previewPlacement.x,
                y: previewPlacement.y,
                rotation: previewPlacement.rotation,
                colorVariant: officeDraftAssetDefaultColorVariant(pendingType),
                scale: previewPlacement.scale,
            };
            previewSpace.assets = Array.isArray(previewSpace.assets) ? [...previewSpace.assets, asset] : [asset];
            state.selectedSpaceId = safeString(previewSpace.id);
            state.selectedAssetId = assetId;
        }
        state.catalogPointerId = null;
        state.catalogPendingType = '';
        state.catalogPreviewSpaceId = '';
        state.catalogPreviewX = 0;
        state.catalogPreviewY = 0;
        if (officeSceneWrap instanceof HTMLElement) {
            officeSceneWrap.style.cursor = 'grab';
        }
        officeDraftCommitLayoutChange(previousSnapshot, state);
        officeRenderDraftMapScene();
        return;
    }
    if (state.assetPointerId !== null && event.pointerId === state.assetPointerId) {
        if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
            officeSceneWrap.releasePointerCapture(event.pointerId);
        }
        state.assetPointerId = null;
        state.assetDragSpaceId = '';
        state.assetDragId = '';
        officeDraftCommitLayoutChange(state.assetDragSnapshot, state);
        state.assetDragSnapshot = null;
        if (officeSceneWrap instanceof HTMLElement) {
            officeSceneWrap.style.cursor = 'grab';
        }
        officeRenderDraftMapScene();
        return;
    }
    if (state.pointerId !== null && event.pointerId !== state.pointerId) return;
    const panMoved = Number(state.lastPanDeltaScreen) || 0;
    if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
        officeSceneWrap.releasePointerCapture(event.pointerId);
    }
    state.pointerId = null;
    state.lastPanAt = performance.now();
    state.agentLayerQuietUntil = state.lastPanAt + OFFICE_DRAFT_AGENT_PAN_QUIET_MS + 80;
    state.routePlanQuietUntil = state.lastPanAt + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS;
    if (panMoved > 8) {
        state.suppressAgentClickUntil = performance.now() + 320;
    }
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grab';
    }
    officeRenderDraftMapMinimapThrottled(true);
    window.clearTimeout(state.panSettleTimer);
    state.panSettleTimer = window.setTimeout(() => {
        state.agentLayerQuietUntil = 0;
        officeDraftFlushSceneOrAgentLayerAfterInput(state, 'pan-settle');
    }, OFFICE_DRAFT_AGENT_PAN_QUIET_MS);
}

function officeHandleDraftMapWheel(event) {
    if (officeDraftMapWheelPassesThrough(event)) return;
    event.preventDefault();
    event.stopPropagation();
    const state = officeEnsureDraftMapState();
    officeDraftCancelAgentHoverRender(state);
    const viewport = officeDraftMapViewportRect();
    const rect = officeSceneWrap?.getBoundingClientRect();
    const pointerX = rect ? event.clientX - rect.left : viewport.width / 2;
    const pointerY = rect ? event.clientY - rect.top : viewport.height / 2;
    const anchorWorldX = state.panX + (pointerX / state.zoom);
    const anchorWorldY = state.panY + (pointerY / state.zoom);
    const deltaUnit = event.deltaMode === 1 ? 14 : (event.deltaMode === 2 ? 120 : 1);
    const clampedDelta = Math.max(-180, Math.min(180, (Number(event.deltaY) || 0) * deltaUnit));
    const previousZoom = state.zoom;
    const zoomFactor = Math.exp(-clampedDelta * 0.0009);
    state.zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, state.zoom * zoomFactor));
    state.panX = anchorWorldX - (pointerX / state.zoom);
    state.panY = anchorWorldY - (pointerY / state.zoom);
    state.lastWheelDelta = Math.round(clampedDelta);
    state.lastZoomDelta = Math.round((state.zoom - previousZoom) * 10000) / 10000;
    state.lastWheelAt = performance.now();
    state.lastInputMode = 'wheel';
    state.agentLayerQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS + 80;
    state.routePlanQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS;
    if (state.sceneRenderDeferred) {
        officeDraftScheduleSceneRenderAfterInput(state, state.lastWheelAt);
    }
    officeApplyDraftMapTransform({ deferMinimap: true });
    window.clearTimeout(state.wheelSettleTimer);
    state.wheelSettleTimer = window.setTimeout(() => {
        state.agentLayerQuietUntil = 0;
        officeDraftFlushSceneOrAgentLayerAfterInput(state, 'wheel-settle');
        officeRenderDraftMapMinimapThrottled(true);
    }, OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS);
}

function officeHandleDraftMapKeydown(event) {
    const state = officeEnsureDraftMapState();
    if (event.target instanceof Element && event.target.closest('input, select, textarea, [contenteditable="true"]')) return;
    if ((event.ctrlKey || event.metaKey) && safeString(event.key).toLowerCase() === 'z') {
        officeDraftUndoLastChange(event);
        return;
    }
    if (state.editorOpen && state.selectedAssetId) {
        const assetRef = officeDraftFindAsset(state.selectedAssetId);
        if (assetRef) {
            if (event.key === 'a' || event.key === 'A') {
                const previousSnapshot = officeDraftLayoutSnapshot(state);
                assetRef.asset.rotation = officeDraftNormalizeRotation((assetRef.asset.rotation || 0) - state.rotationStep);
                officeDraftCommitLayoutChange(previousSnapshot, state);
                event.preventDefault();
                officeRenderDraftMapScene();
                return;
            } else if (event.key === 'd' || event.key === 'D') {
                const previousSnapshot = officeDraftLayoutSnapshot(state);
                assetRef.asset.rotation = officeDraftNormalizeRotation((assetRef.asset.rotation || 0) + state.rotationStep);
                officeDraftCommitLayoutChange(previousSnapshot, state);
                event.preventDefault();
                officeRenderDraftMapScene();
                return;
            }
        }
    }
    const step = 160 / state.zoom;
    if (event.key === 'ArrowLeft') state.panX -= step;
    else if (event.key === 'ArrowRight') state.panX += step;
    else if (event.key === 'ArrowUp') state.panY -= step;
    else if (event.key === 'ArrowDown') state.panY += step;
    else return;
    event.preventDefault();
    officeApplyDraftMapTransform();
}

function officeHandleDraftMapResize() {
    const state = officeEnsureDraftMapState();
    const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    officeApplyDraftMapTransform();
}

function officeToggleDraftMinimapMinimized(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.minimapMinimized = !state.minimapMinimized;
    officePrepareDraftMapShell();
    officeRenderDraftMapMinimap();
}

function officeToggleDraftMinimapLocked(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const state = officeEnsureDraftMapState();
    state.minimapLocked = state.minimapLocked !== true;
    state.minimapPointerId = null;
    state.minimapResizePointerId = null;
    officePrepareDraftMapShell();
}

function officeDraftPanCameraToMinimapEvent(event) {
    if (!(officeMinimapCanvas instanceof HTMLCanvasElement)) return;
    const state = officeEnsureDraftMapState();
    const rect = officeMinimapCanvas.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return;
    const localX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
    const localY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const viewport = officeDraftMapViewportRect();
    const worldX = (localX / rect.width) * OFFICE_DRAFT_MAP_SIZE;
    const worldY = (localY / rect.height) * OFFICE_DRAFT_MAP_SIZE;
    state.panX = worldX - (viewport.width / (state.zoom * 2));
    state.panY = worldY - (viewport.height / (state.zoom * 2));
    state.lastInputMode = 'minimap';
    state.lastPanAt = performance.now();
    officeApplyDraftMapTransform({ deferMinimap: true });
    officeRenderDraftMapMinimapThrottled(true);
}

function officeHandleDraftMinimapPointerDown(event) {
    if (event.button !== 0) return;
    if (event.target instanceof Element) {
        if (event.target.closest('[data-office-minimap-lock="1"]')) return;
        if (event.target.closest('#officeFollowToggleBtn')) return;
        if (event.target.closest('[data-office-minimap-resize="1"]')) return;
    }
    event.preventDefault();
    event.stopPropagation();
    const state = officeEnsureDraftMapState();
    state.minimapPointerId = event.pointerId;
    state.minimapDragStartX = event.clientX;
    state.minimapDragStartY = event.clientY;
    state.minimapDragOffsetX = state.minimapOffsetX;
    state.minimapDragOffsetY = state.minimapOffsetY;
    state.minimapPointerMode = event.target instanceof Element
        && event.target.closest('.office-minimap-head')
        && state.minimapLocked !== true
        ? 'panel'
        : 'camera';
    if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (state.minimapPointerMode === 'camera') {
        officeDraftPanCameraToMinimapEvent(event);
    }
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapPointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (state.minimapPointerMode === 'panel' && state.minimapLocked !== true) {
        state.minimapOffsetX = state.minimapDragOffsetX + (event.clientX - state.minimapDragStartX);
        state.minimapOffsetY = state.minimapDragOffsetY + (event.clientY - state.minimapDragStartY);
        officePrepareDraftMapShell();
        return;
    }
    officeDraftPanCameraToMinimapEvent(event);
}

function officeHandleDraftMinimapPointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapPointerId !== null && event.pointerId !== state.minimapPointerId) return;
    if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.preventDefault();
    event.stopPropagation();
    state.minimapPointerId = null;
    state.minimapPointerMode = 'camera';
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapResizePointerDown(event) {
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (state.minimapLocked) return;
    event.preventDefault();
    event.stopPropagation();
    state.minimapResizePointerId = event.pointerId;
    state.minimapResizeStartX = event.clientX;
    state.minimapResizeStartY = event.clientY;
    state.minimapResizeStartSize = state.minimapSize;
    if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
}

function officeHandleDraftMinimapResizePointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapResizePointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const delta = Math.max(event.clientX - state.minimapResizeStartX, event.clientY - state.minimapResizeStartY);
    state.minimapSize = Math.max(150, Math.min(420, state.minimapResizeStartSize + delta));
    officePrepareDraftMapShell();
    officeRenderDraftMapMinimap();
}

function officeHandleDraftMinimapResizePointerUp(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapResizePointerId !== null && event.pointerId !== state.minimapResizePointerId) return;
    if (event.currentTarget instanceof HTMLElement && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.preventDefault();
    event.stopPropagation();
    state.minimapResizePointerId = null;
}

// 
