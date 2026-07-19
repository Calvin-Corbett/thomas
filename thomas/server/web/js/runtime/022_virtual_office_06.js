/** Large cohesive office functions retained together; supporting concerns load from semantic modules. */
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
