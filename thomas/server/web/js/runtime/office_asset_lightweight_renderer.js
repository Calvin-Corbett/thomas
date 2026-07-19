/** Lightweight office-asset rendering for overview performance. */

function officeDraftDecorateLightweightAssetElement(root, type, shape, color, descriptor) {
    if (!(root instanceof HTMLElement)) return;
    const body = color.body || color.back || color.swatch || 'rgba(92, 119, 158, 0.92)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(154, 194, 255, 0.86)';
    const line = color.line || color.seam || 'rgba(12, 20, 34, 0.42)';
    const part = (styles = {}, text = '') => officeDraftAppendAssetPart(root, {
        position: 'absolute',
        boxSizing: 'border-box',
        pointerEvents: 'none',
        ...styles,
    }, text);
    root.style.overflow = 'hidden';
    root.style.boxShadow = 'inset 0 2px 0 rgba(255,255,255,0.20), inset 0 -7px 12px rgba(0,0,0,0.18), 0 7px 12px rgba(2,8,18,0.18)';
    part({ left: '13%', top: '9%', width: '30%', height: '6%', borderRadius: '999px', background: 'rgba(255,255,255,0.18)' });
    part({ right: '11%', bottom: '10%', width: '24%', height: '6%', borderRadius: '999px', background: line, opacity: '0.24' });
    [25, 50, 75].forEach((left, index) => {
        part({
            left: `${left}%`,
            top: `${index === 1 ? 74 : 18}%`,
            width: '5%',
            height: '6%',
            borderRadius: '999px',
            background: index === 1 ? accent : line,
            opacity: index === 1 ? '0.42' : '0.2',
        });
    });

    if (type === 'vending_machine') {
        part({ left: '15%', top: '10%', width: '46%', height: '45%', borderRadius: '8px', background: 'linear-gradient(180deg, rgba(247,252,255,0.78), rgba(84,139,182,0.68))', border: '2px solid rgba(255,255,255,0.48)' });
        [20, 31, 42].forEach((top, index) => {
            part({ left: `${25 + (index * 2)}%`, top: `${top}%`, width: '22%', height: '5%', borderRadius: '999px', background: index === 1 ? accent : 'rgba(255,255,255,0.58)' });
        });
        part({ right: '13%', top: '16%', width: '17%', height: '40%', borderRadius: '7px', background: 'rgba(9,15,27,0.48)' });
        part({ right: '17%', top: '25%', width: '8%', height: '7%', borderRadius: '999px', background: accent });
        part({ left: '22%', bottom: '19%', width: '52%', height: '16%', borderRadius: '7px', background: accent, color: 'rgba(99,24,30,0.92)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: `${Math.max(8, Math.round(Number(descriptor.width || 0) * 0.1))}px`, fontWeight: '900', lineHeight: '1' }, 'Coke');
        part({ left: '34%', bottom: '8%', width: '26%', height: '7%', borderRadius: '999px', background: line });
        return;
    }

    if (type === 'workstation' || type === 'dual_monitor' || type === 'code_terminal' || type === 'laptop' || shape === 'screen') {
        const screens = type === 'dual_monitor' ? [['13%', '18%'], ['53%', '18%']] : [['22%', '16%']];
        screens.forEach(([left, top]) => {
            part({ left, top, width: type === 'dual_monitor' ? '34%' : '58%', height: type === 'laptop' ? '40%' : '48%', borderRadius: '8px', background: 'rgba(5,10,18,0.86)', border: `2px solid ${line}` });
            part({ left: `calc(${left} + 10%)`, top: `calc(${top} + 16%)`, width: type === 'dual_monitor' ? '16%' : '30%', height: '7%', borderRadius: '999px', background: accent, boxShadow: `0 0 10px ${accent}` });
            part({ left: `calc(${left} + 12%)`, top: `calc(${top} + 30%)`, width: type === 'dual_monitor' ? '13%' : '24%', height: '4%', borderRadius: '999px', background: surface, opacity: '0.72' });
        });
        part({ left: '18%', bottom: '13%', width: '64%', height: '14%', borderRadius: '8px', background: surface });
        part({ left: '39%', bottom: '27%', width: '22%', height: '8%', borderRadius: '5px', background: line });
        return;
    }

    if (shape === 'board' || shape === 'panel' || shape === 'divider') {
        part({ left: '9%', top: '11%', width: '82%', height: '70%', borderRadius: '9px', background: surface, border: `2px solid ${body}` });
        part({ left: '19%', top: '31%', width: '44%', height: '6%', borderRadius: '999px', background: accent });
        part({ left: '19%', top: '49%', width: '60%', height: '5%', borderRadius: '999px', background: line, opacity: '0.72' });
        part({ left: '19%', top: '65%', width: '36%', height: '5%', borderRadius: '999px', background: line, opacity: '0.55' });
        [32, 48, 64].forEach((left, index) => {
            part({ left: `${left}%`, top: '18%', width: '9%', height: '11%', borderRadius: '3px', background: index === 1 ? accent : 'rgba(255,238,150,0.86)', transform: `rotate(${index - 1}deg)` });
        });
        return;
    }

    if (type === 'chair' || type === 'meeting_chair' || type === 'lounge_chair' || type === 'stool'
        || type === 'couch' || type === 'loveseat' || type === 'bench' || type === 'ottoman' || type === 'bean_bag'
        || shape === 'soft_seat') {
        if (type === 'bean_bag') {
            part({ left: '12%', top: '18%', width: '76%', height: '66%', borderRadius: '46% 54% 42% 58%', background: surface, transform: 'rotate(-6deg)', boxShadow: 'inset -8px -8px rgba(0,0,0,0.12)' });
            part({ left: '33%', top: '33%', width: '30%', height: '11%', borderRadius: '999px', background: accent, opacity: '0.7' });
            return;
        }
        part({ left: '13%', top: type === 'stool' ? '25%' : '12%', width: '74%', height: type === 'stool' ? '34%' : '38%', borderRadius: '16px 16px 8px 8px', background: body });
        part({ left: '9%', top: type === 'stool' ? '42%' : '46%', width: '82%', height: type === 'stool' ? '30%' : '32%', borderRadius: '13px', background: surface, boxShadow: 'inset 0 -5px rgba(0,0,0,0.14)' });
        part({ left: '18%', top: type === 'stool' ? '49%' : '55%', width: '58%', height: '7%', borderRadius: '999px', background: accent, opacity: '0.5' });
        part({ left: '21%', bottom: '9%', width: '8%', height: '22%', borderRadius: '5px', background: line });
        part({ right: '21%', bottom: '9%', width: '8%', height: '22%', borderRadius: '5px', background: line });
        if (type === 'couch' || type === 'loveseat') {
            part({ left: '36%', top: '51%', width: '3px', height: '22%', borderRadius: '999px', background: line, opacity: '0.48' });
            part({ right: '36%', top: '51%', width: '3px', height: '22%', borderRadius: '999px', background: line, opacity: '0.48' });
            part({ left: '7%', top: '44%', width: '12%', height: '33%', borderRadius: '10px', background: body });
            part({ right: '7%', top: '44%', width: '12%', height: '33%', borderRadius: '10px', background: body });
        }
        return;
    }

    if (type === 'plant' || type === 'tall_plant' || type === 'planter_box') {
        part({ left: type === 'planter_box' ? '12%' : '34%', bottom: '9%', width: type === 'planter_box' ? '76%' : '32%', height: type === 'planter_box' ? '20%' : '25%', borderRadius: '9px', background: accent });
        [18, 36, 54, 70].forEach((left, index) => {
            if (type !== 'planter_box' && index > 2) return;
            part({ left: `${left}%`, top: `${18 + ((index % 2) * 12)}%`, width: type === 'planter_box' ? '16%' : '28%', height: type === 'tall_plant' ? '52%' : '42%', borderRadius: '70% 30% 70% 30%', background: index % 2 ? body : surface, transform: `rotate(${index % 2 ? 18 : -24}deg)` });
        });
        return;
    }

    if (shape === 'counter' || shape === 'bench' || shape === 'table' || type === 'desk' || type === 'round_table' || type === 'conference_table') {
        part({ left: '8%', top: type === 'round_table' ? '9%' : '22%', width: '84%', height: type === 'round_table' ? '78%' : '34%', borderRadius: type === 'round_table' ? '999px' : '14px', background: surface, boxShadow: 'inset 0 -6px rgba(0,0,0,0.13)' });
        part({ left: '19%', bottom: '15%', width: '10%', height: '25%', borderRadius: '5px', background: body });
        part({ right: '19%', bottom: '15%', width: '10%', height: '25%', borderRadius: '5px', background: body });
        part({ left: '32%', top: type === 'round_table' ? '36%' : '32%', width: '36%', height: '7%', borderRadius: '999px', background: accent });
        [20, 38, 56].forEach((left) => {
            part({ left: `${left}%`, top: type === 'round_table' ? '55%' : '43%', width: '14%', height: '4%', borderRadius: '999px', background: line, opacity: '0.22' });
        });
        return;
    }

    if (shape === 'cabinet' || shape === 'shelf' || type === 'bookshelf' || type === 'server_rack') {
        part({ left: '10%', top: '8%', width: '80%', height: '78%', borderRadius: '10px', background: body, border: `2px solid ${line}` });
        [24, 43, 62].forEach((top, index) => {
            part({ left: '19%', top: `${top}%`, width: '60%', height: '5%', borderRadius: '999px', background: index === 1 ? accent : surface, opacity: index === 1 ? '0.95' : '0.74' });
        });
        [28, 42, 56, 70].forEach((left, index) => {
            part({ left: `${left}%`, top: `${31 + ((index % 2) * 20)}%`, width: '5%', height: '14%', borderRadius: '2px', background: index % 2 ? accent : surface });
        });
        part({ right: '18%', top: '17%', width: '8%', height: '8%', borderRadius: '999px', background: accent, boxShadow: `0 0 8px ${accent}` });
        return;
    }

    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') {
        part({ left: '45%', top: '25%', width: '10%', height: '54%', borderRadius: '999px', background: body });
        part({ left: '22%', top: '10%', width: '56%', height: '28%', borderRadius: shape === 'sign' ? '8px' : '999px', background: surface, boxShadow: `0 0 12px ${accent}` });
        part({ left: '18%', bottom: '8%', width: '64%', height: '8%', borderRadius: '999px', background: line });
        return;
    }

    if (shape === 'appliance' || shape === 'machine' || shape === 'console' || shape === 'cart' || shape === 'dock' || shape === 'node' || shape === 'box') {
        part({ left: '11%', top: '20%', width: '78%', height: '52%', borderRadius: '12px', background: surface, border: `2px solid ${body}` });
        part({ left: '25%', top: '36%', width: '33%', height: '8%', borderRadius: '999px', background: accent, boxShadow: `0 0 8px ${accent}` });
        [48, 58, 68].forEach((top, index) => {
            part({ left: `${30 + (index * 13)}%`, top: `${top}%`, width: '8%', height: '5%', borderRadius: '999px', background: line, opacity: '0.42' });
        });
        part({ left: '20%', bottom: '12%', width: '13%', height: '13%', borderRadius: '999px', background: line });
        part({ right: '20%', bottom: '12%', width: '13%', height: '13%', borderRadius: '999px', background: line });
        return;
    }

    part({ left: '10%', top: '12%', width: '80%', height: '64%', borderRadius: '12px', background: surface, border: `2px solid ${body}` });
    part({ left: '24%', top: '34%', width: '42%', height: '7%', borderRadius: '999px', background: accent });
    part({ left: '24%', top: '53%', width: '56%', height: '5%', borderRadius: '999px', background: line, opacity: '0.55' });
}

function officeDraftUseLightweightAssetRender(state, asset) {
    if (!state || state.editorOpen || asset?.preview) return false;
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    return zoom <= 0.3;
}

function officeDraftCreateLightweightAssetElement(space, asset, state) {
    const type = safeString(asset?.type) || 'desk';
    const assetInfo = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const shape = safeString(assetInfo.shape);
    const descriptor = officeDraftAssetDimensions(type, asset?.scale);
    const color = officeDraftAssetColorway(type, asset?.colorVariant) || {};
    const rotation = officeDraftNormalizeRotation(asset?.rotation);
    const body = color.body || color.back || color.swatch || 'rgba(92, 119, 158, 0.92)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(154, 194, 255, 0.86)';
    const root = document.createElement('div');
    const isSelected = state.editorOpen && safeString(asset?.id) === safeString(state.selectedAssetId);
    const zoom = Math.max(OFFICE_DRAFT_MAP_MIN_ZOOM, Number(state?.zoom) || OFFICE_DRAFT_MAP_DEFAULT_ZOOM);
    const lightweightVisualScale = zoom <= 0.2 ? 2.7 : (zoom <= 0.26 ? 2.25 : 1.72);
    const visualWidth = Math.round(Number(descriptor.width || 0) * lightweightVisualScale);
    const visualHeight = Math.round(Number(descriptor.height || 0) * lightweightVisualScale);
    const visualLeft = Math.round((Number(asset?.x) || 0) - ((visualWidth - Number(descriptor.width || 0)) / 2));
    const visualTop = Math.round((Number(asset?.y) || 0) - ((visualHeight - Number(descriptor.height || 0)) / 2));
    const radius = (() => {
        if (shape === 'rug' || type === 'round_table') return '999px';
        if (shape === 'screen' || shape === 'board' || shape === 'panel' || shape === 'divider') return '10px';
        if (shape === 'tower' || shape === 'lamp' || shape === 'light' || type === 'plant') return '999px 999px 18px 18px';
        return '18px';
    })();
    root.dataset.officeDraftAssetId = safeString(asset?.id);
    root.dataset.officeDraftSpaceId = safeString(space?.id);
    root.dataset.officeDraftAssetType = type;
    root.dataset.officeDraftAssetLightweight = '1';
    root.dataset.officeDraftAssetLightweightScale = String(lightweightVisualScale);
    root.style.position = 'absolute';
    root.style.left = `${visualLeft}px`;
    root.style.top = `${visualTop}px`;
    root.style.width = `${visualWidth}px`;
    root.style.height = `${visualHeight}px`;
    root.style.pointerEvents = 'none';
    root.style.borderRadius = radius;
    root.style.background = `linear-gradient(180deg, ${surface}, ${body})`;
    root.style.border = `2px solid ${accent}`;
    root.style.opacity = '0.86';
    root.style.outline = isSelected ? '2px solid rgba(132, 187, 255, 0.75)' : 'none';
    root.style.transform = `rotate(${rotation}deg)`;
    root.style.transformOrigin = 'center center';
    root.style.contain = 'layout paint style';
    officeDraftDecorateLightweightAssetElement(root, type, shape, color, descriptor);
    return root;
}


