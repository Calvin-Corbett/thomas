/** Quality overlays for draft-office assets. */

function officeDraftAddAssetQualityOverlay(root, asset, state) {
    if (!(root instanceof HTMLElement) || !asset) return root;
    if (root.dataset.officeAssetQualityDetail === '16px') return root;
    const type = safeString(asset?.type) || 'desk';
    const descriptor = officeDraftAssetDimensions(type, asset?.scale);
    const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(assetInfo.shape);
    if (type === 'rug' || shape === 'rug') {
        root.dataset.officeAssetQualityDetail = '16px';
        return root;
    }
    const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
    const lightweight = root.dataset.officeDraftAssetLightweight === '1';
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const richDetail = !lightweight && zoom > 0.34 && !asset?.preview;
    const body = color.body || color.back || color.swatch || 'rgba(77,101,136,0.94)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(169,211,255,0.92)';
    const line = color.line || color.seam || 'rgba(8,15,27,0.44)';
    const highlight = 'rgba(255,255,255,0.24)';
    const layer = document.createElement('div');
    layer.dataset.officeAssetQualityOverlay = '1';
    layer.style.position = 'absolute';
    layer.style.inset = '0';
    layer.style.pointerEvents = 'none';
    layer.style.zIndex = '40';
    layer.style.overflow = 'hidden';
    layer.style.borderRadius = 'inherit';
    layer.style.mixBlendMode = 'normal';
    const part = (styles = {}, text = '') => officeDraftAppendAssetPart(layer, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    }, text);
    const dot = (left, top, size = 4, colorRaw = accent) => part({
        left: `${left}%`,
        top: `${top}%`,
        width: `${size}px`,
        height: `${size}px`,
        borderRadius: '2px',
        background: colorRaw,
        boxShadow: `0 0 ${Math.max(4, size)}px ${colorRaw}`,
    });
    part({ left: '7%', top: '8%', width: '26%', height: '4%', borderRadius: '999px', background: highlight, opacity: richDetail ? '0.86' : '0.45' });
    part({ right: '8%', bottom: '9%', width: '24%', height: '4%', borderRadius: '999px', background: line, opacity: '0.22' });
    if (!richDetail) {
        root.appendChild(layer);
        root.dataset.officeAssetQualityDetail = '16px';
        return root;
    }

    const isSeat = ['chair', 'meeting_chair', 'lounge_chair', 'stool', 'couch', 'loveseat', 'bench', 'ottoman', 'bean_bag'].includes(type)
        || shape === 'soft_seat';
    const isScreen = shape === 'screen' || shape === 'console' || ['workstation', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall', 'wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand', 'security_console', 'server_console', 'sound_mixer'].includes(type);
    const isTable = shape === 'table' || shape === 'tilt_table' || shape === 'counter' || shape === 'bench' || ['desk', 'round_table', 'conference_table', 'podcast_desk', 'kitchen_island', 'recipe_counter'].includes(type);
    const isStorage = shape === 'cabinet' || shape === 'shelf' || ['bookshelf', 'server_rack', 'storage_locker', 'filing_cabinet', 'mail_sorter', 'mail_cart', 'package_station', 'printer', 'copier'].includes(type);
    const isBoard = shape === 'board' || shape === 'panel' || ['whiteboard', 'kanban_board', 'pinboard', 'sticky_note_wall', 'dispatch_board', 'green_screen', 'acoustic_panel', 'divider'].includes(type);
    const isPlant = ['plant', 'tall_plant', 'planter_box'].includes(type);
    const isUtility = shape === 'appliance' || shape === 'machine' || shape === 'dock' || shape === 'node' || shape === 'box' || ['vending_machine', 'coffee_bar', 'ticket_kiosk', 'charging_dock', 'network_switch', 'router_node', 'firewall_box', 'testing_rig', 'game_console', 'arcade_cabinet'].includes(type);

    if (type === 'vending_machine') {
        part({ left: '21%', top: '15%', width: '30%', height: '34%', borderRadius: '7px', background: 'linear-gradient(180deg, rgba(244,251,255,0.56), rgba(78,124,170,0.36))', border: '2px solid rgba(255,255,255,0.34)' });
        [21, 30, 39].forEach((top, row) => {
            [28, 39].forEach((left, col) => dot(left + (col * 0.8), top, 5, row === 1 ? accent : 'rgba(255,255,255,0.72)'));
        });
        part({ right: '20%', top: '22%', width: '10%', height: '28%', borderRadius: '6px', background: 'rgba(8,14,24,0.52)' });
        dot(73, 31, 6, accent);
        part({ left: '24%', bottom: '20%', width: '38%', height: '12%', borderRadius: '6px', background: accent, color: 'rgba(105,23,35,0.94)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `${Math.max(8, Math.round(Number(descriptor.width || 0) * 0.06))}px`, fontWeight: '900', letterSpacing: '0' }, 'Coke');
    } else if (type === 'data_wall') {
        [18, 41, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: '22%', width: '18%', height: '46%', borderRadius: '8px', background: 'rgba(4,10,20,0.72)', border: `1px solid ${line}` });
            [33, 45, 57].forEach((top, row) => {
                part({ left: `${left + 3}%`, top: `${top}%`, width: `${row === 1 ? 12 : 8}%`, height: '3%', borderRadius: '999px', background: row === index % 3 ? accent : surface, opacity: row === index % 3 ? '0.9' : '0.5' });
            });
        });
        [24, 47, 70].forEach((left, index) => dot(left, 72, index === 1 ? 6 : 4, index === 1 ? accent : highlight));
    } else if (type === 'map_table') {
        part({ left: '18%', top: '24%', width: '62%', height: '42%', borderRadius: '14px', background: 'rgba(214,236,255,0.16)', border: `1px solid ${highlight}` });
        [34, 45, 56].forEach((top, index) => {
            part({ left: `${24 + (index * 5)}%`, top: `${top}%`, width: `${36 - (index * 4)}%`, height: '3%', borderRadius: '999px', background: index === 1 ? accent : line, opacity: index === 1 ? '0.74' : '0.42' });
        });
        dot(31, 38, 6, accent);
        dot(62, 54, 5, 'rgba(255,226,128,0.92)');
        dot(52, 44, 4, highlight);
    } else if (type === 'microscope') {
        part({ left: '46%', top: '18%', width: '10%', height: '48%', borderRadius: '999px', background: body, transform: 'rotate(18deg)' });
        part({ left: '30%', top: '26%', width: '32%', height: '18%', borderRadius: '999px', background: surface, border: `1px solid ${highlight}` });
        part({ left: '38%', top: '48%', width: '30%', height: '9%', borderRadius: '999px', background: accent });
        part({ left: '23%', bottom: '18%', width: '56%', height: '10%', borderRadius: '999px', background: line, opacity: '0.55' });
        dot(67, 27, 5, accent);
    } else if (type === 'conference_table') {
        [24, 40, 56, 72].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + ((index % 2) * 18)}%`, width: '9%', height: '10%', borderRadius: '5px', background: index % 2 ? accent : highlight, opacity: '0.72' });
        });
        part({ left: '26%', top: '48%', width: '48%', height: '5%', borderRadius: '999px', background: line, opacity: '0.26' });
        part({ left: '39%', top: '27%', width: '22%', height: '8%', borderRadius: '999px', background: accent, opacity: '0.42' });
    } else if (type === 'arcade_cabinet') {
        part({ left: '28%', top: '17%', width: '43%', height: '25%', borderRadius: '7px', background: 'rgba(5,10,18,0.88)', border: `1px solid ${line}` });
        part({ left: '35%', top: '27%', width: '28%', height: '5%', borderRadius: '999px', background: accent, boxShadow: `0 0 10px ${accent}` });
        part({ left: '30%', top: '53%', width: '40%', height: '17%', borderRadius: '8px', background: surface });
        [39, 50, 61].forEach((left, index) => dot(left, 60, index === 1 ? 6 : 4, index === 1 ? accent : 'rgba(255,231,122,0.9)'));
    } else if (type === 'focus_pod') {
        part({ left: '19%', top: '12%', width: '62%', height: '64%', borderRadius: '22px 22px 18px 18px', background: 'rgba(215,235,255,0.18)', border: `2px solid ${highlight}` });
        part({ left: '31%', top: '31%', width: '38%', height: '12%', borderRadius: '999px', background: accent, opacity: '0.72' });
        part({ left: '28%', bottom: '19%', width: '44%', height: '11%', borderRadius: '999px', background: line, opacity: '0.32' });
    } else if (isScreen) {
        [27, 37, 47, 57].forEach((top, index) => {
            part({ left: `${24 + (index % 2) * 5}%`, top: `${top}%`, width: `${index === 1 ? 38 : 28}%`, height: '3.5%', borderRadius: '999px', background: index === 1 ? accent : surface, opacity: index === 1 ? '0.88' : '0.52' });
        });
        [68, 75, 82].forEach((left, index) => dot(left, 23 + (index * 9), 5, index === 1 ? accent : 'rgba(255,255,255,0.5)'));
        if (['workstation', 'dual_monitor', 'laptop', 'code_terminal', 'research_terminal'].includes(type)) {
            part({ left: '24%', bottom: '16%', width: '42%', height: '5%', borderRadius: '999px', background: line, opacity: '0.4' });
            [27, 34, 41, 48, 55].forEach((left) => dot(left, 78, 3, highlight));
        }
    } else if (isSeat) {
        [26, 50, 74].forEach((left, index) => {
            part({ left: `${left}%`, top: '50%', width: '2.8%', height: '22%', borderRadius: '999px', background: line, opacity: index === 1 ? '0.4' : '0.26' });
        });
        part({ left: '20%', top: '28%', width: '20%', height: '11%', borderRadius: '10px', background: accent, opacity: '0.42' });
        part({ right: '18%', top: '31%', width: '16%', height: '9%', borderRadius: '9px', background: highlight, opacity: '0.35' });
    } else if (isTable) {
        [20, 36, 52, 68].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + (index % 2) * 13}%`, width: '16%', height: '3%', borderRadius: '999px', background: index === 1 ? accent : line, opacity: index === 1 ? '0.34' : '0.2' });
        });
        part({ right: '18%', top: '23%', width: '13%', height: '12%', borderRadius: '7px', background: 'rgba(255,255,255,0.14)', border: `1px solid ${highlight}` });
        dot(74, 52, 4, accent);
    } else if (isStorage) {
        [23, 40, 57, 74].forEach((top, index) => {
            part({ left: '18%', top: `${top}%`, width: '60%', height: '3.4%', borderRadius: '999px', background: index % 2 ? accent : line, opacity: index % 2 ? '0.72' : '0.28' });
        });
        [30, 44, 58, 72].forEach((left, index) => {
            part({ left: `${left}%`, top: `${32 + (index % 2) * 20}%`, width: '4.8%', height: '13%', borderRadius: '2px', background: index % 2 ? surface : accent, opacity: '0.88' });
        });
        dot(82, 20, 5, accent);
    } else if (isBoard) {
        [24, 40, 56].forEach((left, index) => {
            part({ left: `${left}%`, top: '22%', width: '11%', height: '15%', borderRadius: '3px', background: index === 1 ? accent : 'rgba(255,236,151,0.9)', transform: `rotate(${index - 1}deg)` });
        });
        [35, 51, 67].forEach((top, index) => {
            part({ left: '24%', top: `${top}%`, width: `${index === 1 ? 50 : 34}%`, height: '3%', borderRadius: '999px', background: index === 0 ? accent : line, opacity: index === 0 ? '0.82' : '0.46' });
        });
    } else if (isPlant) {
        [22, 36, 50, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: `${20 + (index % 2) * 10}%`, width: '15%', height: '38%', borderRadius: '70% 30% 70% 30%', background: index % 2 ? surface : body, transform: `rotate(${index % 2 ? 20 : -24}deg)`, opacity: '0.92' });
        });
        part({ left: '20%', bottom: '13%', width: '60%', height: '13%', borderRadius: '8px', background: accent, boxShadow: 'inset 0 -4px rgba(0,0,0,0.13)' });
    } else if (isUtility) {
        part({ left: '18%', top: '25%', width: '54%', height: '28%', borderRadius: '9px', background: surface, border: `2px solid ${body}` });
        [28, 44, 60].forEach((left, index) => dot(left, 39, index === 1 ? 6 : 4, index === 1 ? accent : highlight));
        part({ left: '25%', top: '59%', width: '42%', height: '4%', borderRadius: '999px', background: line, opacity: '0.34' });
        part({ right: '17%', top: '34%', width: '9%', height: '9%', borderRadius: '999px', background: accent, boxShadow: `0 0 9px ${accent}` });
    } else {
        [26, 48, 70].forEach((left, index) => dot(left, 28 + (index * 16), 4, index === 1 ? accent : highlight));
        part({ left: '22%', top: '58%', width: '44%', height: '4%', borderRadius: '999px', background: line, opacity: '0.3' });
    }
    root.appendChild(layer);
    root.dataset.officeAssetQualityDetail = '16px';
    return root;
}


