/** Surface and pixel detail rendering for office assets. */

function officeDraftAppendAssetPart(parent, styles = {}, text = '') {
    const part = document.createElement('div');
    part.style.boxSizing = 'border-box';
    Object.entries(styles).forEach(([key, value]) => {
        part.style[key] = value;
    });
    if (text) {
        part.textContent = text;
    }
    parent.appendChild(part);
    return part;
}

function officeDraftAddAssetSurfaceDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {}) {
    if (!(root instanceof HTMLElement) || typeof scaled !== 'function') return;
    const baseWidth = Math.max(48, Number(baseWidthRaw) || 0);
    const baseHeight = Math.max(48, Number(baseHeightRaw) || 0);
    const accent = color.accent || color.arm || 'rgba(214, 236, 255, 0.62)';
    const line = color.line || color.seam || 'rgba(9, 18, 31, 0.34)';
    officeDraftAppendAssetPart(root, {
        position: 'absolute',
        left: scaled(baseWidth * 0.12),
        top: scaled(baseHeight * 0.08),
        width: scaled(Math.max(26, baseWidth * 0.26)),
        height: scaled(Math.max(4, baseHeight * 0.045)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.18)',
        pointerEvents: 'none',
    });
    officeDraftAppendAssetPart(root, {
        position: 'absolute',
        right: scaled(baseWidth * 0.1),
        bottom: scaled(baseHeight * 0.09),
        width: scaled(Math.max(24, baseWidth * 0.2)),
        height: scaled(Math.max(4, baseHeight * 0.04)),
        borderRadius: '999px',
        background: line,
        opacity: '0.24',
        pointerEvents: 'none',
    });
    [0.24, 0.5, 0.76].forEach((leftRatio, index) => {
        officeDraftAppendAssetPart(root, {
            position: 'absolute',
            left: scaled(baseWidth * leftRatio),
            top: scaled(baseHeight * (0.16 + (index % 2) * 0.58)),
            width: scaled(Math.max(5, baseWidth * 0.025)),
            height: scaled(Math.max(5, baseWidth * 0.025)),
            borderRadius: '999px',
            background: index === 1 ? accent : line,
            opacity: index === 1 ? '0.46' : '0.24',
            pointerEvents: 'none',
        });
    });
}

function officeDraftAddAssetPixelDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {}, typeRaw = '', shapeRaw = '') {
    if (!(root instanceof HTMLElement) || typeof scaled !== 'function') return;
    const baseWidth = Math.max(48, Number(baseWidthRaw) || 0);
    const baseHeight = Math.max(48, Number(baseHeightRaw) || 0);
    const type = safeString(typeRaw);
    const shape = safeString(shapeRaw);
    const accent = color.accent || color.arm || 'rgba(214, 236, 255, 0.72)';
    const line = color.line || color.seam || 'rgba(7, 13, 24, 0.36)';
    const surface = color.surface || color.seat || color.body || 'rgba(120, 147, 184, 0.92)';
    const body = color.body || color.back || surface;
    const part = (styles = {}) => officeDraftAppendAssetPart(root, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    });
    part({
        left: scaled(baseWidth * 0.06),
        top: scaled(baseHeight * 0.12),
        width: scaled(Math.max(4, baseWidth * 0.018)),
        height: scaled(Math.max(18, baseHeight * 0.56)),
        borderRadius: '999px',
        background: line,
        opacity: '0.18',
    });
    part({
        right: scaled(baseWidth * 0.06),
        top: scaled(baseHeight * 0.16),
        width: scaled(Math.max(4, baseWidth * 0.018)),
        height: scaled(Math.max(18, baseHeight * 0.42)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.16)',
        opacity: '0.82',
    });
    part({
        left: scaled(baseWidth * 0.18),
        top: scaled(baseHeight * 0.08),
        width: scaled(Math.max(32, baseWidth * 0.34)),
        height: scaled(Math.max(4, baseHeight * 0.035)),
        borderRadius: '999px',
        background: 'rgba(255,255,255,0.22)',
        opacity: '0.72',
    });

    const isScreenLike = shape === 'screen' || shape === 'board' || ['workstation', 'dual_monitor', 'code_terminal', 'research_terminal', 'data_wall', 'wall_monitor', 'monitor_stand', 'laptop', 'tablet_stand'].includes(type);
    const isSeating = ['chair', 'meeting_chair', 'lounge_chair', 'stool', 'couch', 'loveseat', 'bench', 'ottoman', 'bean_bag'].includes(type) || shape === 'soft_seat';
    const isSurface = ['desk', 'round_table', 'conference_table', 'coffee_table', 'kitchen_island'].includes(type) || shape === 'table' || shape === 'tilt_table' || shape === 'counter';
    const isStorage = ['bookshelf', 'server_rack', 'storage_locker', 'filing_cabinet', 'printer', 'copier', 'mail_sorter', 'mail_cart', 'package_station'].includes(type) || shape === 'cabinet' || shape === 'shelf';
    const isUtility = ['vending_machine', 'coffee_bar', 'ticket_kiosk', 'power_panel', 'charging_dock', 'network_switch', 'router_node', 'firewall_box', 'sound_mixer', 'testing_rig', 'game_console'].includes(type) || shape === 'appliance' || shape === 'machine' || shape === 'console';

    if (isScreenLike) {
        [0.28, 0.42, 0.56].forEach((topRatio, index) => {
            part({
                left: scaled(baseWidth * 0.24),
                top: scaled(baseHeight * topRatio),
                width: scaled(baseWidth * (index === 1 ? 0.36 : 0.26)),
                height: scaled(Math.max(4, baseHeight * 0.025)),
                borderRadius: '999px',
                background: index === 1 ? accent : surface,
                opacity: index === 1 ? '0.9' : '0.58',
                boxShadow: index === 1 ? `0 0 ${scaled(8)} ${accent}` : 'none',
            });
        });
        return;
    }

    if (isSeating) {
        [0.28, 0.5, 0.72].forEach((leftRatio, index) => {
            part({
                left: scaled(baseWidth * leftRatio),
                top: scaled(baseHeight * 0.5),
                width: scaled(Math.max(5, baseWidth * 0.026)),
                height: scaled(Math.max(18, baseHeight * 0.18)),
                borderRadius: '999px',
                background: line,
                opacity: index === 1 ? '0.32' : '0.22',
            });
        });
        part({
            left: scaled(baseWidth * 0.22),
            top: scaled(baseHeight * 0.28),
            width: scaled(baseWidth * 0.18),
            height: scaled(baseHeight * 0.12),
            borderRadius: scaled(10),
            background: accent,
            opacity: '0.48',
        });
        return;
    }

    if (isSurface) {
        [0.22, 0.42, 0.62].forEach((topRatio, index) => {
            part({
                left: scaled(baseWidth * (0.2 + index * 0.08)),
                top: scaled(baseHeight * topRatio),
                width: scaled(baseWidth * 0.32),
                height: scaled(Math.max(4, baseHeight * 0.025)),
                borderRadius: '999px',
                background: index === 1 ? accent : line,
                opacity: index === 1 ? '0.38' : '0.22',
            });
        });
        part({
            right: scaled(baseWidth * 0.18),
            top: scaled(baseHeight * 0.24),
            width: scaled(baseWidth * 0.12),
            height: scaled(baseHeight * 0.12),
            borderRadius: scaled(6),
            background: body,
            opacity: '0.62',
        });
        return;
    }

    if (isStorage || isUtility) {
        [0.24, 0.48, 0.72].forEach((topRatio, index) => {
            part({
                right: scaled(baseWidth * 0.18),
                top: scaled(baseHeight * topRatio),
                width: scaled(Math.max(8, baseWidth * 0.06)),
                height: scaled(Math.max(5, baseHeight * 0.035)),
                borderRadius: '999px',
                background: index === 1 ? accent : line,
                opacity: index === 1 ? '0.88' : '0.34',
                boxShadow: index === 1 ? `0 0 ${scaled(7)} ${accent}` : 'none',
            });
        });
        part({
            left: scaled(baseWidth * 0.18),
            bottom: scaled(baseHeight * 0.16),
            width: scaled(baseWidth * 0.24),
            height: scaled(Math.max(5, baseHeight * 0.035)),
            borderRadius: '999px',
            background: line,
            opacity: '0.38',
        });
    }
}


