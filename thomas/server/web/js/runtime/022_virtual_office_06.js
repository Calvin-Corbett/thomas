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
    panel.style.display = 'block';

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
    const selectedColorways = selectedAsset
        ? Object.entries(OFFICE_DRAFT_ASSET_COLORWAYS[safeString(selectedAsset.type)] || {}).map(([id, colorway]) => `
            <button
                type="button"
                data-office-editor-asset-color="${escapeHtml(id)}"
                aria-pressed="${safeString(selectedAsset.colorVariant || 'caramel') === id ? 'true' : 'false'}"
                style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:12px;border:1px solid ${safeString(selectedAsset.colorVariant || 'caramel') === id ? 'rgba(129, 182, 255, 0.72)' : 'rgba(116, 141, 181, 0.22)'};background:${safeString(selectedAsset.colorVariant || 'caramel') === id ? 'rgba(49, 84, 141, 0.34)' : 'rgba(15, 23, 38, 0.84)'};color:rgba(238,242,249,0.92);">
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
                <div style="font-size:0.74rem;line-height:1.45;color:rgba(198,210,226,0.72);">A / D rotate selected asset</div>
            </section>
        `
        : `
            <section style="display:grid;gap:8px;padding:12px;border-radius:16px;border:1px solid rgba(116,141,181,0.16);background:rgba(11,18,30,0.82);">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Selected Asset</div>
                <div style="font-size:0.78rem;line-height:1.55;color:rgba(198,210,226,0.72);">Select a placed couch to edit its color, change its scale, and rotate it with A / D.</div>
            </section>
        `;

    panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
            <strong style="font-size:0.92rem;letter-spacing:0.04em;text-transform:uppercase;">Office Editor</strong>
            <span style="font-size:0.72rem;color:rgba(202,214,230,0.72);">${state.autosaveEnabled ? 'Autosave On' : 'Autosave Off'}</span>
        </div>
        <div style="display:grid;gap:12px;margin-top:14px;">
            <section style="display:grid;gap:8px;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Selected Space</div>
                <button type="button" data-office-editor-selected-space="1" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:14px;border:1px solid rgba(116,141,181,0.22);background:rgba(14,22,35,0.9);color:rgba(240,244,250,0.94);">
                    <span>${escapeHtml(selectedSpace?.name || 'No space')}</span>
                    <span style="font-size:0.72rem;color:rgba(190,203,220,0.62);">click room label</span>
                </button>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">${paletteButtons}</div>
            </section>
            <section style="display:grid;gap:8px;">
                <div style="font-size:0.74rem;letter-spacing:0.08em;text-transform:uppercase;color:rgba(192,206,224,0.68);">Catalog</div>
                <button type="button" data-office-editor-catalog-asset="couch" style="display:grid;gap:10px;padding:12px;border-radius:16px;border:1px solid rgba(116,141,181,0.22);background:rgba(14,22,35,0.92);text-align:left;color:rgba(240,244,250,0.94);cursor:grab;">
                    <span style="display:flex;align-items:flex-end;justify-content:center;height:76px;padding:8px 0;border-radius:12px;background:linear-gradient(180deg, rgba(19, 28, 44, 0.96), rgba(11, 17, 28, 0.96));">
                        <span style="position:relative;display:block;width:92px;height:48px;">
                            <span style="position:absolute;left:10px;top:4px;width:72px;height:22px;border-radius:10px 10px 7px 7px;background:linear-gradient(180deg, rgba(212, 160, 117, 0.98), rgba(162, 105, 69, 0.98));"></span>
                            <span style="position:absolute;left:4px;top:18px;width:84px;height:20px;border-radius:10px;background:linear-gradient(180deg, rgba(223, 176, 132, 1), rgba(175, 117, 78, 0.98));"></span>
                            <span style="position:absolute;left:0;top:14px;width:16px;height:24px;border-radius:7px;background:linear-gradient(180deg, rgba(190, 132, 92, 0.98), rgba(141, 87, 56, 0.98));"></span>
                            <span style="position:absolute;right:0;top:14px;width:16px;height:24px;border-radius:7px;background:linear-gradient(180deg, rgba(190, 132, 92, 0.98), rgba(141, 87, 56, 0.98));"></span>
                            <span style="position:absolute;left:12px;top:36px;width:68px;height:8px;border-radius:999px;background:rgba(3,8,16,0.34);filter:blur(4px);"></span>
                        </span>
                    </span>
                    <strong style="font-size:0.9rem;">Couch</strong>
                    <span style="font-size:0.76rem;color:rgba(198,210,226,0.72);">Click and drag into a room to place a three-seat couch.</span>
                </button>
            </section>
            <section style="display:grid;gap:8px;">
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
            <section style="display:grid;gap:8px;">
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
            ${selectedAssetSection}
        </div>
    `;
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
    officeRenderDraftMapScene();
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
        colorVariant: 'caramel',
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
            assetRef.asset.colorVariant = safeString(colorBtn.dataset.officeEditorAssetColor) || 'caramel';
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
        state.selectedAssetId = null;
        officeDraftPersistLayout(state);
        if (state.editorOpen) {
            officeRenderDraftMapScene();
        }
        event.preventDefault();
    }
}

function officePrepareDraftMapShell() {
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
        hint.textContent = 'Base grid draft · drag to pan · wheel to zoom · rooms come later';
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
        mapToolbar.style.zIndex = '3';
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
        editorPanel.style.width = '292px';
        editorPanel.style.padding = '14px';
        editorPanel.style.borderRadius = '18px';
        editorPanel.style.border = '1px solid rgba(112, 139, 184, 0.24)';
        editorPanel.style.background = 'rgba(8, 14, 24, 0.92)';
        editorPanel.style.backdropFilter = 'blur(14px)';
        editorPanel.style.boxShadow = '0 20px 48px rgba(0, 0, 0, 0.28)';
        editorPanel.style.zIndex = '3';
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
        officeMinimap.style.background = 'rgba(6, 10, 19, 0.86)';
        officeMinimap.style.backdropFilter = 'blur(12px)';
        officeMinimap.style.boxShadow = '0 14px 40px rgba(0, 0, 0, 0.28)';
        officeMinimap.style.overflow = 'hidden';
        officeMinimap.style.transform = `translate3d(${state.minimapOffsetX}px, ${state.minimapOffsetY}px, 0)`;
        officeMinimap.style.zIndex = '3';
        officeMinimap.style.userSelect = 'none';
        officeMinimap.style.cursor = state.minimapPointerId === null ? 'grab' : 'grabbing';
    }
    const minimapHead = officeMinimap?.querySelector('.office-minimap-head');
    if (minimapHead instanceof HTMLElement) {
        minimapHead.style.display = 'flex';
        minimapHead.style.alignItems = 'center';
        minimapHead.style.justifyContent = 'flex-end';
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
        officeMinimapCanvas.style.cursor = state.minimapPointerId === null ? 'grab' : 'grabbing';
        officeMinimapCanvas.setAttribute('aria-label', 'Virtual office minimap showing the current camera window.');
    }
    const resizeHandle = officeMinimap?.querySelector('[data-office-minimap-resize="1"]');
    if (resizeHandle instanceof HTMLElement) {
        resizeHandle.style.position = 'absolute';
        resizeHandle.style.right = '10px';
        resizeHandle.style.bottom = '10px';
        resizeHandle.style.display = 'block';
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

    const seedSize = 360 * scale;
    const seedX = (OFFICE_DRAFT_MAP_SIZE / 2 * scale) - (seedSize / 2);
    const seedY = (OFFICE_DRAFT_MAP_SIZE / 2 * scale) - (seedSize / 2);
    ctx.fillStyle = 'rgba(88, 166, 255, 0.2)';
    ctx.strokeStyle = 'rgba(170, 213, 255, 0.7)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(seedX, seedY, seedSize, seedSize, 10);
    ctx.fill();
    ctx.stroke();

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

function officeApplyDraftMapTransform() {
    const state = officeEnsureDraftMapState();
    const plane = officeDraftMapPlane();
    if (!(plane instanceof HTMLElement)) return;
    const clamped = officeClampDraftMapPan(state.panX, state.panY, state.zoom);
    state.panX = clamped.panX;
    state.panY = clamped.panY;
    const offsetX = -(state.panX * state.zoom);
    const offsetY = -(state.panY * state.zoom);
    plane.style.transform = `translate3d(${offsetX.toFixed(2)}px, ${offsetY.toFixed(2)}px, 0) scale(${state.zoom.toFixed(4)})`;
    const badge = officeWorkspace?.querySelector('[data-office-map-badge="1"]');
    if (badge instanceof HTMLElement) {
        badge.textContent = `${Math.round(state.zoom * 100)}% · ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} x ${OFFICE_DRAFT_MAP_SIZE.toLocaleString()} grid`;
    }
    officeRenderDraftMapMinimap();
}

function officeRenderDraftMapScene() {
    if (!officeScene || !officeScenePanzoom) return;
    const state = officeEnsureDraftMapState();
    officePrepareDraftMapShell();
    officeScenePanzoom.style.position = 'absolute';
    officeScenePanzoom.style.inset = '0';
    officeScenePanzoom.style.width = '100%';
    officeScenePanzoom.style.height = '100%';
    officeScenePanzoom.style.overflow = 'hidden';
    officeScenePanzoom.style.transformOrigin = 'top left';
    officeScenePanzoom.style.willChange = 'contents';
    officeScene.style.position = 'relative';
    officeScene.style.width = '100%';
    officeScene.style.height = '100%';
    officeScene.style.overflow = 'hidden';
    officeScene.style.background = 'linear-gradient(180deg, rgba(8, 15, 27, 0.96), rgba(5, 10, 18, 1))';
    officeScene.innerHTML = '';
    const plane = document.createElement('div');
    plane.dataset.officeMapPlane = '1';
    plane.style.position = 'absolute';
    plane.style.left = '0';
    plane.style.top = '0';
    plane.style.width = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.height = `${OFFICE_DRAFT_MAP_SIZE}px`;
    plane.style.transformOrigin = 'top left';
    plane.style.willChange = 'transform';
    plane.style.backgroundColor = '#0a1321';
    plane.style.backgroundImage = [
        `linear-gradient(rgba(96, 124, 178, 0.10) 1px, transparent 1px)`,
        `linear-gradient(90deg, rgba(96, 124, 178, 0.10) 1px, transparent 1px)`,
        `linear-gradient(rgba(170, 205, 255, 0.20) 1px, transparent 1px)`,
        `linear-gradient(90deg, rgba(170, 205, 255, 0.20) 1px, transparent 1px)`,
    ].join(',');
    plane.style.backgroundSize = [
        `${OFFICE_DRAFT_MAP_MINOR_GRID}px ${OFFICE_DRAFT_MAP_MINOR_GRID}px`,
        `${OFFICE_DRAFT_MAP_MINOR_GRID}px ${OFFICE_DRAFT_MAP_MINOR_GRID}px`,
        `${OFFICE_DRAFT_MAP_MAJOR_GRID}px ${OFFICE_DRAFT_MAP_MAJOR_GRID}px`,
        `${OFFICE_DRAFT_MAP_MAJOR_GRID}px ${OFFICE_DRAFT_MAP_MAJOR_GRID}px`,
    ].join(',');
    plane.style.boxShadow = 'inset 0 0 0 1px rgba(255, 255, 255, 0.04)';
    state.spaces.forEach((space) => {
        const palette = officeDraftRoomPalette(space?.floorPalette);
        const isSelectedSpace = safeString(space?.id) === safeString(state.selectedSpaceId);
        const room = document.createElement('section');
        room.dataset.officeDraftSpaceId = safeString(space?.id);
        room.style.position = 'absolute';
        room.style.left = `${Math.round(Number(space?.x) || 0)}px`;
        room.style.top = `${Math.round(Number(space?.y) || 0)}px`;
        room.style.width = `${Math.round(Number(space?.width) || 0)}px`;
        room.style.height = `${Math.round(Number(space?.height) || 0)}px`;
        room.style.border = isSelectedSpace ? '4px solid rgba(122, 181, 255, 0.82)' : '4px solid rgba(158, 196, 255, 0.62)';
        room.style.borderRadius = '46px';
        room.style.background = palette.shell;
        room.style.overflow = 'visible';
        room.style.boxShadow = isSelectedSpace
            ? 'inset 0 0 0 1px rgba(215, 232, 255, 0.08), 0 0 0 2px rgba(110, 169, 255, 0.14), 0 32px 110px rgba(0, 0, 0, 0.26)'
            : 'inset 0 0 0 1px rgba(215, 232, 255, 0.05), 0 32px 110px rgba(0, 0, 0, 0.26)';

        const roomInset = document.createElement('div');
        roomInset.style.position = 'absolute';
        roomInset.style.left = '24px';
        roomInset.style.top = '24px';
        roomInset.style.right = '24px';
        roomInset.style.bottom = '24px';
        roomInset.style.borderRadius = '32px';
        roomInset.style.border = `1px solid ${palette.floorBorder}`;
        roomInset.style.background = palette.floor;
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
        roomLabel.style.fontSize = '1.2rem';
        roomLabel.style.fontWeight = '700';
        roomLabel.style.letterSpacing = '0.12em';
        roomLabel.style.textTransform = 'uppercase';
        roomLabel.style.cursor = state.editorOpen ? 'pointer' : 'default';
        room.appendChild(roomLabel);

        const robot = document.createElement('div');
        robot.style.position = 'absolute';
        robot.style.left = `${Math.round(Number(space?.robotX) || 0)}px`;
        robot.style.top = `${Math.round(Number(space?.robotY) || 0)}px`;
        robot.style.transform = 'scale(1.7)';
        robot.style.transformOrigin = 'top left';
        robot.style.pointerEvents = 'none';
        robot.innerHTML = officePixelAgentMarkup();
        room.appendChild(robot);

        (Array.isArray(space?.assets) ? space.assets : []).forEach((asset) => {
            if (safeString(asset?.type) === 'couch') {
                room.appendChild(officeDraftCreateCouchElement(space, asset, state));
            }
        });
        if (safeString(state.catalogPreviewSpaceId) === safeString(space?.id) && safeString(state.catalogPendingType) === 'couch') {
            room.appendChild(officeDraftCreateCouchElement(space, {
                id: 'catalog-preview',
                type: 'couch',
                x: state.catalogPreviewX,
                y: state.catalogPreviewY,
                rotation: 0,
                colorVariant: 'caramel',
                scale: 1,
                preview: true,
            }, state));
        }

        plane.appendChild(room);
    });

    officeScene.appendChild(plane);
    if (officeSceneWrap instanceof HTMLElement && !officeSceneWrap.querySelector('[data-office-map-toolbar="1"]')) {
        const toolbar = document.createElement('div');
        toolbar.dataset.officeMapToolbar = '1';

        const minimapBtn = document.createElement('button');
        minimapBtn.type = 'button';
        minimapBtn.dataset.officeMapToolbarMinimap = '1';
        minimapBtn.textContent = 'Minimap';

        const editorBtn = document.createElement('button');
        editorBtn.type = 'button';
        editorBtn.dataset.officeMapToolbarEditor = '1';
        editorBtn.textContent = 'Office Editor';

        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.dataset.officeMapToolbarSave = '1';
        saveBtn.textContent = 'Save';

        const undoBtn = document.createElement('button');
        undoBtn.type = 'button';
        undoBtn.dataset.officeMapToolbarUndo = '1';
        undoBtn.textContent = 'Back';

        const badge = document.createElement('span');
        badge.dataset.officeMapBadge = '1';

        toolbar.appendChild(minimapBtn);
        toolbar.appendChild(editorBtn);
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
    officeRenderDraftMapEditorPanel();
    officePrepareDraftMapShell();
    officeApplyDraftMapTransform();
    officeRenderDraftMapMinimap();
}

function officeBindDraftMapControls() {
    if (!(officeSceneWrap instanceof HTMLElement) || officeSceneWrap.dataset.officeDraftMapBound === '1') return;
    officeSceneWrap.dataset.officeDraftMapBound = '1';
    officeSceneWrap.addEventListener('pointerdown', officeHandleDraftMapPointerDown);
    officeSceneWrap.addEventListener('pointermove', officeHandleDraftMapPointerMove);
    officeSceneWrap.addEventListener('pointerup', officeHandleDraftMapPointerUp);
    officeSceneWrap.addEventListener('pointercancel', officeHandleDraftMapPointerUp);
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

function officeHandleDraftMapPointerDown(event) {
    if (!(officeSceneWrap instanceof HTMLElement)) return;
    if (event.button !== 0) return;
    const state = officeEnsureDraftMapState();
    if (event.target instanceof Element) {
        if (officeMinimap instanceof HTMLElement && officeMinimap.contains(event.target)) return;
        if (event.target.closest('[data-office-map-toolbar="1"]')) return;
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
    state.pointerId = event.pointerId;
    state.dragStartX = event.clientX;
    state.dragStartY = event.clientY;
    state.dragPanX = state.panX;
    state.dragPanY = state.panY;
    officeSceneWrap.style.cursor = 'grabbing';
    officeSceneWrap.setPointerCapture(event.pointerId);
}

function officeHandleDraftMapPointerMove(event) {
    const state = officeEnsureDraftMapState();
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
    const deltaX = event.clientX - state.dragStartX;
    const deltaY = event.clientY - state.dragStartY;
    state.panX = state.dragPanX - (deltaX / state.zoom);
    state.panY = state.dragPanY - (deltaY / state.zoom);
    officeApplyDraftMapTransform();
}

function officeHandleDraftMapPointerUp(event) {
    const state = officeEnsureDraftMapState();
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
                colorVariant: 'caramel',
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
    if (officeSceneWrap instanceof HTMLElement && officeSceneWrap.hasPointerCapture(event.pointerId)) {
        officeSceneWrap.releasePointerCapture(event.pointerId);
    }
    state.pointerId = null;
    if (officeSceneWrap instanceof HTMLElement) {
        officeSceneWrap.style.cursor = 'grab';
    }
}

function officeHandleDraftMapWheel(event) {
    event.preventDefault();
    const state = officeEnsureDraftMapState();
    const viewport = officeDraftMapViewportRect();
    const rect = officeSceneWrap?.getBoundingClientRect();
    const pointerX = rect ? event.clientX - rect.left : viewport.width / 2;
    const pointerY = rect ? event.clientY - rect.top : viewport.height / 2;
    const anchorWorldX = state.panX + (pointerX / state.zoom);
    const anchorWorldY = state.panY + (pointerY / state.zoom);
    const clampedDelta = Math.max(-220, Math.min(220, Number(event.deltaY) || 0));
    const zoomFactor = Math.exp(-clampedDelta * 0.00125);
    state.zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Math.min(OFFICE_DRAFT_MAP_MAX_ZOOM, state.zoom * zoomFactor));
    state.panX = anchorWorldX - (pointerX / state.zoom);
    state.panY = anchorWorldY - (pointerY / state.zoom);
    officeApplyDraftMapTransform();
}

function officeHandleDraftMapKeydown(event) {
    const state = officeEnsureDraftMapState();
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

function officeHandleDraftMinimapPointerDown(event) {
    if (event.button !== 0) return;
    if (event.target instanceof Element) {
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
    if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapPointerMove(event) {
    const state = officeEnsureDraftMapState();
    if (state.minimapPointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    state.minimapOffsetX = state.minimapDragOffsetX + (event.clientX - state.minimapDragStartX);
    state.minimapOffsetY = state.minimapDragOffsetY + (event.clientY - state.minimapDragStartY);
    officePrepareDraftMapShell();
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
    officePrepareDraftMapShell();
}

function officeHandleDraftMinimapResizePointerDown(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const state = officeEnsureDraftMapState();
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
