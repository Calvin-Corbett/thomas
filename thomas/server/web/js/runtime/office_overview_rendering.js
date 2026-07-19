/** Overview asset rendering and grid background. */

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


