from pathlib import Path

from tests.web_ui_source import read_app_js_source

REPO_ROOT = Path(__file__).resolve().parents[1]
VIRTUAL_OFFICE_HTML = REPO_ROOT / "thomas" / "server" / "web" / "virtual_office.html"
VIRTUAL_OFFICE_STATIC_HTML = REPO_ROOT / "thomas" / "server" / "web" / "static" / "virtual_office.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_virtual_office_mode_is_reinserted_by_runtime() -> None:
    js = read_app_js_source()
    assert "button.id = 'navOfficeBtn';" in js
    assert "setSidebarNavMode('office');" in js
    assert "Search office" in js
    assert "id: 'office'" in js


def test_virtual_office_draft_map_runtime_hooks_present() -> None:
    js = read_app_js_source()
    assert "const OFFICE_DRAFT_MAP_SIZE = 24000;" in js
    assert "const OFFICE_DRAFT_MAP_MIN_ZOOM = 0.015;" in js
    assert "const OFFICE_DRAFT_MINIMAP_SIZE = 220;" in js
    assert "const OFFICE_DRAFT_LAYOUT_STORAGE_KEY = 'thomas.office.draft.layout.v1';" in js
    assert "const OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY = 'thomas.office.draft.autosave.v1';" in js
    assert "const OFFICE_DRAFT_UNDO_LIMIT = 48;" in js
    assert "const OFFICE_DRAFT_ASSET_SCALE_OPTIONS = Object.freeze([0.8, 1, 1.2, 1.4]);" in js
    assert "const OFFICE_DRAFT_ROOM_FLOOR_PALETTES = Object.freeze({" in js
    assert "const OFFICE_DRAFT_ASSET_LIBRARY = Object.freeze({" in js
    assert "const OFFICE_DRAFT_ASSET_COLORWAYS = Object.freeze({" in js
    assert "function officeEnsureDraftMapState()" in js
    assert "function officeDraftRoomPalette(paletteId)" in js
    assert "function officeDraftSelectedSpace()" in js
    assert "function officeDraftFindAsset(assetId)" in js
    assert "function officeDraftSpaceAtWorldPoint(worldX, worldY)" in js
    assert "function officeDraftRotationOptions()" in js
    assert "function officeDraftNormalizeRotation(value)" in js
    assert "function officeDraftSnap(value, gridSize, enabled = true)" in js
    assert "function officeDraftLoadStoredLayout()" in js
    assert "function officeDraftLoadAutosavePreference()" in js
    assert "function officeDraftSetAutosavePreference(enabledRaw, stateRaw = officeEnsureDraftMapState())" in js
    assert "function officeDraftPersistLayout(stateRaw = officeEnsureDraftMapState(), options = {})" in js
    assert "function officeDraftManualSaveLayout(event)" in js
    assert "function officeDraftApplySnapshot(snapshotRaw, stateRaw = officeEnsureDraftMapState(), options = {})" in js
    assert "function officeDraftCommitLayoutChange(previousSnapshot, stateRaw = officeEnsureDraftMapState())" in js
    assert "function officeDraftUndoLastChange(event)" in js
    assert "function officeDraftPlaceAssetInSpace(space, assetType, worldX, worldY, options = {})" in js
    assert "function officeDraftCreateCouchElement(space, asset, state)" in js
    assert "function officeRenderDraftMapEditorPanel()" in js
    assert "function officeToggleDraftEditor(event)" in js
    assert "function officeDraftAddCatalogAsset(assetType)" in js
    assert "function officeDraftBeginCatalogPlacement(assetType, pointerId, clientX, clientY)" in js
    assert "function officePrepareDraftMapShell()" in js
    assert "function officeBindDraftMapControls()" in js
    assert "function officeHandleDraftMapClick(event)" in js
    assert "function officeHandleDraftMapWheel(event)" in js
    assert "function officeRenderDraftMapMinimap()" in js
    assert "function officeToggleDraftMinimapMinimized(event)" in js
    assert "function officeHandleDraftMinimapPointerDown(event)" in js
    assert "function officeHandleDraftMinimapResizePointerDown(event)" in js
    assert "translate3d(" in js
    assert "Math.exp(-clampedDelta * 0.00125)" in js
    assert "Lounge" in js
    assert "floorPalette: 'tan'" in js
    assert "rotation: 0" in js
    assert "assets: [" in js
    assert "robot.innerHTML = officePixelAgentMarkup();" in js
    assert "couch: {" in js


def test_virtual_office_workspace_keeps_only_the_base_map_shell() -> None:
    js = read_app_js_source()
    assert "officeWorkspace.remove();" not in js
    assert "officeEditorToggleBtn.style.display = 'none';" in js
    assert "officeWorkspace?.querySelector('.office-bottom-dock')" in js
    assert "mapToolbar.style.right = '14px';" in js
    assert "toolbarStatus.style.display = 'none';" in js
    assert "officeMinimap.style.height = `${state.minimapSize}px`;" in js
    assert "officeMinimap.style.cursor = state.minimapPointerId === null ? 'grab' : 'grabbing';" in js
    assert "officeFollowToggleBtn.textContent = state.minimapMinimized ? 'Show' : 'Hide';" in js
    assert "Virtual office minimap showing the current camera window." in js
    assert "minimapBtn.textContent = 'Minimap';" in js
    assert "editorBtn.textContent = 'Office Editor';" in js
    assert "saveBtn.textContent = 'Save';" in js
    assert "editorToolbarBtn.textContent = 'Office Editor';" in js
    assert "undoBtn.textContent = 'Back';" in js
    assert "saveToolbarBtn.textContent = 'Save';" in js
    assert "undoToolbarBtn.textContent = 'Back';" in js
    assert "panel.dataset.officeEditorPanel = '1';" in js
    assert "officeSceneWrap.addEventListener('click', officeHandleDraftMapClick);" in js
    assert "officeSceneWrap.setPointerCapture(event.pointerId);" in js
    assert "data-office-editor-catalog-asset=\"couch\"" in js
    assert "Click and drag into a room to place a three-seat couch." in js
    assert "data-office-editor-rotation-step" in js
    assert "data-office-editor-grid-toggle=\"1\"" in js
    assert "${state.autosaveEnabled ? 'Autosave On' : 'Autosave Off'}" in js
    assert "data-office-editor-autosave-toggle=\"1\"" in js
    assert "data-office-editor-save=\"1\"" in js
    assert "Save Layout" in js
    assert "data-office-editor-asset-color" in js
    assert "data-office-editor-asset-scale" in js
    assert "Select a placed couch to edit its color, change its scale, and rotate it with A / D." in js
    assert "A / D rotate selected asset" in js
    assert "space.floorPalette = safeString(floorBtn.dataset.officeEditorFloorPalette) || 'tan';" in js
    assert "officeDraftBeginCatalogPlacement(catalogBtn.dataset.officeEditorCatalogAsset, event.pointerId, event.clientX, event.clientY);" in js
    assert "state.gridEnabled = !state.gridEnabled;" in js
    assert "state.rotationStep = Number(rotationBtn.dataset.officeEditorRotationStep) || 15;" in js
    assert "state.catalogPendingType = safeString(assetType);" in js
    assert "room.appendChild(officeDraftCreateCouchElement(space, {" in js
    assert "id: 'catalog-preview'" in js
    assert "officeSceneWrap.style.cursor = 'copy';" in js
    assert "officeSceneWrap.style.cursor = 'not-allowed';" in js
    assert "const assetId = `${pendingType}-${state.nextAssetId++}`;" in js
    assert "state.catalogPendingType = '';" in js
    assert "officeDraftPersistLayout(state);" in js
    assert "officeDraftPersistLayout(state, { force: true });" in js
    assert "officeDraftCommitLayoutChange(previousSnapshot, state);" in js
    assert "officeDraftSetAutosavePreference(state.autosaveEnabled === false, state);" in js
    assert "officeDraftManualSaveLayout(event);" in js
    assert "officeDraftUndoLastChange(event);" in js
    assert "if ((event.ctrlKey || event.metaKey) && safeString(event.key).toLowerCase() === 'z')" in js
    assert "colorVariant: 'caramel'" in js
    assert "scale: 1" in js
    assert "officeMinimap.addEventListener('pointerdown', officeHandleDraftMinimapPointerDown);" in js
    assert "resizeHandle.setAttribute('aria-label', 'Resize minimap');" in js
    assert "resizeHandle.style.borderRight = '3px solid rgba(152, 193, 255, 0.92)';" in js
    assert "roomLabel.style.top = '-32px';" in js
    assert "room.style.border = isSelectedSpace ? '4px solid rgba(122, 181, 255, 0.82)' : '4px solid rgba(158, 196, 255, 0.62)';" in js


def test_virtual_office_entry_points_are_placeholder_shells() -> None:
    for html_path in (VIRTUAL_OFFICE_HTML, VIRTUAL_OFFICE_STATIC_HTML):
        text = _read(html_path)
        assert "Virtual office reset pending rebuild" in text
        assert "Gather-style redesign" in text
        assert "virtual_office.script01.js" not in text
        assert "virtual_office.style01.css" not in text
