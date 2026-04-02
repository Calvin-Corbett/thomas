function officeDrawRoomFurnitureSprites(ctx, room, rect) {
    const atlas = officeGetSpriteAtlas();
    if (!atlas?.regions?.sprite_desk) return false;
    const theme = safeString(room?.theme || room?.kind).toLowerCase();
    const roomMin = Math.min(rect.w, rect.h);
    const baseSize = officeClamp(roomMin * 0.44, 34, 152);
    const compactSize = officeClamp(roomMin * 0.31, 22, 88);
    const roomHash = officeStableHash(`${safeString(room?.id)}|${safeString(room?.label)}`);
    const rugRadius = Math.max(8, roomMin * 0.08);

    officeCanvasRoundedBox(
        ctx,
        rect.x + (rect.w * 0.08),
        rect.y + (rect.h * 0.58),
        rect.w * 0.84,
        rect.h * 0.3,
        rugRadius,
        'rgba(136, 158, 189, 0.16)',
        'rgba(73, 94, 125, 0.16)',
        1,
    );
    officeCanvasRoundedBox(
        ctx,
        rect.x + (rect.w * 0.12),
        rect.y + (rect.h * 0.62),
        rect.w * 0.76,
        rect.h * 0.22,
        Math.max(6, rugRadius * 0.8),
        'rgba(214, 227, 245, 0.16)',
    );

    const stamp = (spriteId, relX, relY, scale = 1, opacity = 0.96, options = {}) => {
        const width = Math.max(8, baseSize * scale);
        const height = Math.max(8, baseSize * scale);
        officeCanvasRoundedBox(
            ctx,
            (rect.x + (rect.w * relX)) - (width * 0.38),
            (rect.y + (rect.h * relY)) - (height * 0.16),
            width * 0.76,
            height * 0.32,
            Math.max(3, width * 0.14),
            'rgba(47, 64, 93, 0.24)',
        );
        officePaintSpriteStamp(
            ctx,
            atlas,
            spriteId,
            rect.x + (rect.w * relX),
            rect.y + (rect.h * relY),
            width,
            height,
            opacity,
            options,
        );
    };

    const stampCompact = (spriteId, relX, relY, scale = 1, opacity = 0.9, options = {}) => {
        const width = Math.max(6, compactSize * scale);
        const height = Math.max(6, compactSize * scale);
        officeCanvasRoundedBox(
            ctx,
            (rect.x + (rect.w * relX)) - (width * 0.34),
            (rect.y + (rect.h * relY)) - (height * 0.12),
            width * 0.68,
            height * 0.24,
            Math.max(2, width * 0.12),
            'rgba(47, 64, 93, 0.2)',
        );
        officePaintSpriteStamp(
            ctx,
            atlas,
            spriteId,
            rect.x + (rect.w * relX),
            rect.y + (rect.h * relY),
            width,
            height,
            opacity,
            options,
        );
    };

    const stampShadow = (relX, relY, scale = 1, alpha = 0.14) => {
        const shadowW = Math.max(10, (baseSize * scale) * 0.68);
        const shadowH = Math.max(4, (baseSize * scale) * 0.16);
        officeCanvasRoundedBox(
            ctx,
            rect.x + (rect.w * relX) - (shadowW / 2),
            rect.y + (rect.h * relY) + (shadowH * 0.45),
            shadowW,
            shadowH,
            Math.max(2, shadowH * 0.45),
            `rgba(40, 53, 77, ${officeClamp(alpha, 0.06, 0.28)})`,
        );
    };

    // Light floor anchors to make furniture feel grounded.
    const anchorCount = room.id === 'room-lobby' ? 4 : 2;
    for (let i = 0; i < anchorCount; i += 1) {
        const ratio = (i + 1) / (anchorCount + 1);
        officeCanvasRoundedBox(
            ctx,
            rect.x + (rect.w * ratio) - (compactSize * 0.25),
            rect.y + (rect.h * 0.72),
            compactSize * 0.5,
            Math.max(2, compactSize * 0.1),
            2,
            'rgba(66, 85, 113, 0.1)',
        );
    }
    // Wall accents to reduce flat-block feeling.
    officeCanvasBox(
        ctx,
        rect.x + (rect.w * 0.04),
        rect.y + (rect.h * 0.06),
        rect.w * 0.92,
        Math.max(2, compactSize * 0.09),
        'rgba(241, 248, 255, 0.22)',
    );
    officeCanvasBox(
        ctx,
        rect.x + (rect.w * 0.04),
        rect.y + (rect.h * 0.86),
        rect.w * 0.92,
        Math.max(2, compactSize * 0.08),
        'rgba(59, 78, 107, 0.16)',
    );
    if ((roomHash % 2) === 0) {
        stampCompact('sprite_window', 0.5, 0.16, 1.15, 0.86);
    } else {
        stampCompact('sprite_board', 0.5, 0.17, 1.1, 0.84);
    }

    const layoutByTheme = {
        engineering: [
            ['sprite_desk', 0.26, 0.3, 1.05],
            ['sprite_desk', 0.52, 0.3, 1.05],
            ['sprite_desk', 0.74, 0.3, 1.05],
            ['sprite_monitor', 0.26, 0.48, 0.86],
            ['sprite_monitor', 0.52, 0.48, 0.86],
            ['sprite_monitor', 0.74, 0.48, 0.86],
            ['sprite_chair', 0.32, 0.66, 0.82],
            ['sprite_chair', 0.58, 0.66, 0.82],
            ['sprite_board', 0.16, 0.72, 0.94],
        ],
        content: [
            ['sprite_desk', 0.3, 0.34, 1.02],
            ['sprite_desk', 0.62, 0.34, 1.02],
            ['sprite_camera', 0.42, 0.56, 0.86],
            ['sprite_lamp', 0.56, 0.56, 0.88],
            ['sprite_sofa', 0.52, 0.74, 1.06],
            ['sprite_plant', 0.2, 0.74, 0.84],
        ],
        research: [
            ['sprite_table', 0.48, 0.36, 1.04],
            ['sprite_board', 0.74, 0.36, 0.88],
            ['sprite_rack', 0.26, 0.34, 0.88],
            ['sprite_monitor', 0.48, 0.56, 0.86],
            ['sprite_plant', 0.78, 0.66, 0.8],
        ],
        ops: [
            ['sprite_server', 0.24, 0.3, 1.04],
            ['sprite_server', 0.46, 0.3, 1.04],
            ['sprite_server', 0.68, 0.3, 1.04],
            ['sprite_monitor', 0.52, 0.62, 0.86],
            ['sprite_kiosk', 0.84, 0.64, 0.9],
        ],
        planning: [
            ['sprite_roundtable', 0.44, 0.42, 1.04],
            ['sprite_chair', 0.3, 0.56, 0.84],
            ['sprite_chair', 0.58, 0.56, 0.84],
            ['sprite_board', 0.76, 0.34, 0.9],
            ['sprite_plant', 0.18, 0.68, 0.78],
        ],
        design: [
            ['sprite_roundtable', 0.44, 0.42, 1.04],
            ['sprite_chair', 0.3, 0.56, 0.84],
            ['sprite_chair', 0.58, 0.56, 0.84],
            ['sprite_board', 0.76, 0.34, 0.9],
            ['sprite_plant', 0.18, 0.68, 0.78],
        ],
        support: [
            ['sprite_desk', 0.28, 0.32, 1.02],
            ['sprite_desk', 0.54, 0.32, 1.02],
            ['sprite_monitor', 0.3, 0.52, 0.84],
            ['sprite_monitor', 0.56, 0.52, 0.84],
            ['sprite_kiosk', 0.78, 0.62, 0.88],
        ],
        pods: [
            ['sprite_desk', 0.34, 0.34, 0.92],
            ['sprite_desk', 0.66, 0.34, 0.92],
            ['sprite_roundtable', 0.5, 0.62, 0.9],
            ['sprite_monitor', 0.5, 0.46, 0.8],
        ],
        dynamic: [
            ['sprite_desk', 0.34, 0.34, 0.92],
            ['sprite_desk', 0.66, 0.34, 0.92],
            ['sprite_roundtable', 0.5, 0.62, 0.9],
            ['sprite_monitor', 0.5, 0.46, 0.8],
        ],
        break: [
            ['sprite_sofa', 0.34, 0.38, 1.02],
            ['sprite_table', 0.62, 0.42, 0.94],
            ['sprite_coffee', 0.56, 0.62, 0.84],
            ['sprite_plant', 0.18, 0.66, 0.78],
            ['sprite_vending', 0.82, 0.52, 0.88],
        ],
        coffee: [
            ['sprite_window', 0.5, 0.19, 1.12],
            ['sprite_roundtable', 0.24, 0.37, 0.88],
            ['sprite_roundtable', 0.5, 0.37, 0.88],
            ['sprite_roundtable', 0.76, 0.37, 0.88],
            ['sprite_sofa', 0.28, 0.7, 0.98],
            ['sprite_sofa', 0.72, 0.7, 0.98],
            ['sprite_coffee', 0.5, 0.66, 0.92],
            ['sprite_vending', 0.88, 0.56, 0.9],
            ['sprite_plant', 0.1, 0.63, 0.82],
        ],
        lobby: [
            ['sprite_sofa', 0.34, 0.42, 1.08],
            ['sprite_sofa', 0.68, 0.42, 1.08],
            ['sprite_bench', 0.5, 0.68, 1.04],
            ['sprite_kiosk', 0.18, 0.62, 0.9],
            ['sprite_planter', 0.82, 0.62, 0.9],
            ['sprite_window', 0.5, 0.24, 1.04],
            ['sprite_roundtable', 0.36, 0.74, 0.86],
            ['sprite_roundtable', 0.64, 0.74, 0.86],
            ['sprite_plant', 0.24, 0.28, 0.84],
            ['sprite_plant', 0.76, 0.28, 0.84],
            ['sprite_monitor', 0.5, 0.52, 0.86],
        ],
    };

    const entries = layoutByTheme[theme] || [
        ['sprite_desk', 0.34, 0.34, 1],
        ['sprite_table', 0.62, 0.42, 0.92],
        ['sprite_plant', 0.22, 0.68, 0.78],
    ];

    entries.forEach(([spriteId, x, y, scale]) => {
        stampShadow(x, y, scale, 0.2);
        stamp(spriteId, x, y, scale, 0.98);
    });

    if (theme === 'coffee') {
        stampShadow(0.24, 0.5, 0.68, 0.12);
        stampCompact('sprite_chair', 0.24, 0.5, 0.9, 0.9);
        stampShadow(0.5, 0.5, 0.68, 0.12);
        stampCompact('sprite_chair', 0.5, 0.5, 0.9, 0.9);
        stampShadow(0.76, 0.5, 0.68, 0.12);
        stampCompact('sprite_chair', 0.76, 0.5, 0.9, 0.9);
        stampCompact('sprite_coffee', 0.5, 0.5, 0.88, 0.94);
        stampCompact('sprite_plant', 0.14, 0.24, 0.8, 0.9);
        stampCompact('sprite_plant', 0.86, 0.24, 0.8, 0.9, { flipX: true });
        return true;
    }

    if (theme === 'engineering') {
        stampCompact('sprite_server', 0.16, 0.3, 0.88, 0.92);
        stampCompact('sprite_monitor', 0.84, 0.3, 0.84, 0.9);
    } else if (theme === 'content') {
        stampCompact('sprite_camera', 0.22, 0.26, 0.86, 0.9);
        stampCompact('sprite_lamp', 0.84, 0.24, 0.86, 0.9);
    } else if (theme === 'research') {
        stampCompact('sprite_board', 0.18, 0.25, 0.9, 0.9);
        stampCompact('sprite_rack', 0.84, 0.64, 0.84, 0.88);
    } else if (theme === 'ops') {
        stampCompact('sprite_server', 0.84, 0.28, 0.9, 0.94);
        stampCompact('sprite_kiosk', 0.18, 0.66, 0.84, 0.9);
    } else if (theme === 'planning' || theme === 'design') {
        stampCompact('sprite_roundtable', 0.5, 0.62, 0.9, 0.9);
        stampCompact('sprite_window', 0.82, 0.24, 0.84, 0.86);
    } else if (theme === 'support') {
        stampCompact('sprite_kiosk', 0.2, 0.62, 0.86, 0.9);
        stampCompact('sprite_board', 0.82, 0.24, 0.84, 0.88);
    } else if (theme === 'pods' || theme === 'dynamic') {
        stampCompact('sprite_planter', 0.18, 0.7, 0.82, 0.88);
        stampCompact('sprite_planter', 0.82, 0.7, 0.82, 0.88, { flipX: true });
    } else if (theme === 'lobby') {
        stampCompact('sprite_bench', 0.5, 0.82, 1.06, 0.9);
        stampCompact('sprite_planter', 0.12, 0.28, 0.84, 0.9);
        stampCompact('sprite_planter', 0.88, 0.28, 0.84, 0.9, { flipX: true });
    }

    // Secondary accents for visual variety.
    stampShadow(0.24, 0.58, 0.78, 0.12);
    stampCompact('sprite_chair', 0.24, 0.58, 0.95);
    stampShadow(0.76, 0.58, 0.78, 0.12);
    stampCompact('sprite_chair', 0.76, 0.58, 0.95, 0.88, { flipX: true });
    stampCompact('sprite_monitor', 0.5, 0.28, 0.82, 0.86);
    if ((roomHash % 3) === 0) {
        stampCompact('sprite_plant', 0.14, 0.22, 0.78, 0.84);
    } else if ((roomHash % 3) === 1) {
        stampCompact('sprite_lamp', 0.86, 0.24, 0.78, 0.84);
    } else {
        stampCompact('sprite_coffee', 0.15, 0.8, 0.76, 0.84);
    }
    return true;
}

function officeDrawRoomFurnitureCanvas(ctx, room, rect, palette) {
    if (officeDrawRoomFurnitureSprites(ctx, room, rect)) {
        return;
    }
    const deskFill = palette.desk;
    const deskStroke = 'rgba(62, 78, 106, 0.7)';
    const monitorFill = 'rgba(96, 145, 202, 0.88)';
    const monitorStroke = 'rgba(36, 52, 77, 0.82)';
    const chairFill = 'rgba(127, 145, 178, 0.82)';
    const tableFill = 'rgba(169, 180, 205, 0.86)';
    const sofaFill = 'rgba(151, 166, 198, 0.86)';
    const plantPotFill = 'rgba(114, 129, 158, 0.84)';
    const plantLeafFill = 'rgba(84, 139, 106, 0.92)';
    const rackFill = 'rgba(102, 121, 156, 0.88)';
    const unit = Math.max(2, Math.min(rect.w, rect.h) * 0.045);
    const theme = safeString(room.theme || room.kind).toLowerCase();

    const drawRoundedRel = (x, y, w, h, fill, stroke = deskStroke, radiusScale = 0.2) => {
        const px = rect.x + (rect.w * x);
        const py = rect.y + (rect.h * y);
        const pw = rect.w * w;
        const ph = rect.h * h;
        const radius = Math.max(2, Math.min(pw, ph) * radiusScale);
        officeCanvasRoundedBox(ctx, px, py, pw, ph, radius, fill, stroke, 1);
        return { x: px, y: py, w: pw, h: ph };
    };

    const drawPlant = (x, y, scale = 1) => {
        const base = drawRoundedRel(
            x,
            y + (0.035 * scale),
            0.07 * scale,
            0.07 * scale,
            plantPotFill,
            'rgba(62, 78, 103, 0.72)',
            0.34,
        );
        officeCanvasCircle(
            ctx,
            base.x + (base.w / 2),
            base.y - (base.h * 0.18),
            Math.max(2.6, base.w * 0.48),
            plantLeafFill,
            'rgba(59, 96, 74, 0.72)',
            1,
        );
        officeCanvasCircle(
            ctx,
            base.x + (base.w * 0.16),
            base.y + (base.h * 0.14),
            Math.max(2, base.w * 0.33),
            'rgba(103, 163, 126, 0.9)',
        );
        officeCanvasCircle(
            ctx,
            base.x + (base.w * 0.84),
            base.y + (base.h * 0.14),
            Math.max(2, base.w * 0.33),
            'rgba(103, 163, 126, 0.9)',
        );
    };

    const drawDeskSetup = (x, y, w, h, { monitors = 1, chair = 'bottom', tone = deskFill } = {}) => {
        const desk = drawRoundedRel(x, y, w, h, tone, deskStroke, 0.18);
        const monitorWidth = Math.max(unit * 1.2, (desk.w * 0.2));
        const monitorHeight = Math.max(unit * 0.58, (desk.h * 0.38));
        const monitorGap = Math.max(unit * 0.38, (desk.w * 0.08));
        const stackWidth = (monitorWidth * monitors) + (monitorGap * Math.max(0, monitors - 1));
        const monitorStart = desk.x + ((desk.w - stackWidth) / 2);
        for (let i = 0; i < monitors; i += 1) {
            const mx = monitorStart + (i * (monitorWidth + monitorGap));
            const my = desk.y + (desk.h * 0.16);
            officeCanvasRoundedBox(ctx, mx, my, monitorWidth, monitorHeight, Math.max(2, monitorHeight * 0.26), monitorFill, monitorStroke, 1);
            officeCanvasRoundedBox(ctx, mx + (monitorWidth * 0.16), my + (monitorHeight * 0.16), monitorWidth * 0.68, monitorHeight * 0.5, Math.max(1.2, monitorHeight * 0.14), 'rgba(170, 209, 255, 0.68)');
            officeCanvasRoundedBox(ctx, mx + (monitorWidth * 0.42), my + monitorHeight, monitorWidth * 0.16, monitorHeight * 0.24, 1, 'rgba(63, 84, 114, 0.82)');
        }
        officeCanvasRoundedBox(
            ctx,
            desk.x + (desk.w * 0.12),
            desk.y + (desk.h * 0.72),
            desk.w * 0.76,
            Math.max(2, desk.h * 0.12),
            Math.max(1.5, unit * 0.2),
            'rgba(121, 138, 165, 0.78)',
            'rgba(64, 79, 104, 0.66)',
            1,
        );

        const chairW = Math.max(unit * 1.05, desk.w * 0.24);
        const chairH = Math.max(unit * 0.75, desk.h * 0.48);
        let chairX = desk.x + ((desk.w - chairW) / 2);
        let chairY = desk.y + desk.h + (unit * 0.18);
        if (chair === 'top') chairY = desk.y - chairH - (unit * 0.18);
        if (chair === 'left') {
            chairX = desk.x - chairW - (unit * 0.2);
            chairY = desk.y + ((desk.h - chairH) / 2);
        }
        if (chair === 'right') {
            chairX = desk.x + desk.w + (unit * 0.2);
            chairY = desk.y + ((desk.h - chairH) / 2);
        }
        officeCanvasRoundedBox(ctx, chairX, chairY, chairW, chairH, Math.max(2, chairH * 0.24), chairFill, 'rgba(56, 71, 96, 0.66)', 1);
        officeCanvasRoundedBox(
            ctx,
            chairX + (chairW * 0.24),
            chairY + (chairH * 0.76),
            chairW * 0.52,
            Math.max(1.8, chairH * 0.16),
            Math.max(1.2, chairH * 0.12),
            'rgba(86, 101, 133, 0.84)',
        );
    };

    const drawSofa = (x, y, w, h) => {
        const sofa = drawRoundedRel(x, y, w, h, sofaFill, 'rgba(67, 83, 111, 0.68)', 0.24);
        officeCanvasRoundedBox(
            ctx,
            sofa.x + (sofa.w * 0.08),
            sofa.y + (sofa.h * 0.16),
            sofa.w * 0.84,
            sofa.h * 0.36,
            Math.max(2, sofa.h * 0.22),
            'rgba(184, 198, 224, 0.7)',
            'rgba(87, 102, 128, 0.42)',
            1,
        );
    };

    const drawRoundTable = (centerX, centerY, radiusPct = 0.08) => {
        const radius = Math.max(unit * 0.7, Math.min(rect.w, rect.h) * radiusPct);
        const x = rect.x + (rect.w * centerX);
        const y = rect.y + (rect.h * centerY);
        officeCanvasCircle(ctx, x, y, radius, tableFill, 'rgba(70, 86, 111, 0.68)', 1);
        officeCanvasCircle(ctx, x, y + (radius * 0.14), radius * 0.34, 'rgba(133, 147, 176, 0.85)');
    };

    const drawRack = (x, y, w, h) => {
        const rack = drawRoundedRel(x, y, w, h, rackFill, 'rgba(52, 67, 95, 0.72)', 0.15);
        const slotCount = Math.max(3, Math.round(rack.h / Math.max(8, unit * 1.25)));
        for (let i = 1; i < slotCount; i += 1) {
            const lineY = rack.y + ((rack.h / slotCount) * i);
            officeCanvasLine(ctx, rack.x + (unit * 0.3), lineY, rack.x + rack.w - (unit * 0.3), lineY, 'rgba(150, 170, 205, 0.52)', 1);
        }
        officeCanvasRoundedBox(
            ctx,
            rack.x + (rack.w * 0.62),
            rack.y + (rack.h * 0.12),
            rack.w * 0.22,
            rack.h * 0.1,
            2,
            'rgba(115, 210, 157, 0.78)',
        );
    };

    const drawBoard = (x, y, w, h) => {
        const board = drawRoundedRel(x, y, w, h, 'rgba(224, 237, 255, 0.86)', 'rgba(120, 143, 177, 0.72)', 0.15);
        officeCanvasLine(
            ctx,
            board.x + (board.w * 0.12),
            board.y + (board.h * 0.26),
            board.x + (board.w * 0.76),
            board.y + (board.h * 0.26),
            'rgba(101, 130, 170, 0.56)',
            1,
        );
        officeCanvasLine(
            ctx,
            board.x + (board.w * 0.18),
            board.y + (board.h * 0.58),
            board.x + (board.w * 0.64),
            board.y + (board.h * 0.74),
            'rgba(101, 130, 170, 0.48)',
            1,
        );
    };

    if (theme === 'engineering') {
        drawDeskSetup(0.1, 0.18, 0.34, 0.16, { monitors: 2, chair: 'bottom' });
        drawDeskSetup(0.56, 0.18, 0.34, 0.16, { monitors: 2, chair: 'bottom' });
        drawDeskSetup(0.1, 0.58, 0.34, 0.16, { monitors: 1, chair: 'top' });
        drawDeskSetup(0.56, 0.58, 0.34, 0.16, { monitors: 1, chair: 'top' });
        drawBoard(0.38, 0.41, 0.24, 0.12);
        return;
    }
    if (theme === 'content') {
        drawDeskSetup(0.14, 0.2, 0.32, 0.15, { monitors: 1, chair: 'bottom' });
        drawDeskSetup(0.54, 0.2, 0.32, 0.15, { monitors: 2, chair: 'bottom' });
        drawSofa(0.2, 0.57, 0.52, 0.17);
        drawRoundTable(0.78, 0.64, 0.075);
        drawPlant(0.08, 0.56, 0.86);
        return;
    }
    if (theme === 'research') {
        drawDeskSetup(0.12, 0.2, 0.3, 0.15, { monitors: 1, chair: 'bottom' });
        drawDeskSetup(0.58, 0.2, 0.3, 0.15, { monitors: 1, chair: 'bottom' });
        drawRoundedRel(0.2, 0.55, 0.6, 0.18, tableFill, 'rgba(68, 82, 107, 0.7)', 0.14);
        drawBoard(0.36, 0.12, 0.28, 0.11);
        drawPlant(0.08, 0.58, 0.82);
        return;
    }
    if (theme === 'ops') {
        drawRack(0.1, 0.14, 0.2, 0.62);
        drawRack(0.4, 0.14, 0.2, 0.62);
        drawRack(0.7, 0.14, 0.2, 0.62);
        drawDeskSetup(0.3, 0.77, 0.4, 0.13, { monitors: 3, chair: 'top' });
        return;
    }
    if (theme === 'planning' || theme === 'design') {
        drawRoundedRel(0.16, 0.2, 0.68, 0.2, tableFill, 'rgba(69, 84, 110, 0.68)', 0.18);
        drawDeskSetup(0.12, 0.58, 0.22, 0.14, { monitors: 1, chair: 'top' });
        drawDeskSetup(0.39, 0.58, 0.22, 0.14, { monitors: 1, chair: 'top' });
        drawDeskSetup(0.66, 0.58, 0.22, 0.14, { monitors: 1, chair: 'top' });
        drawBoard(0.08, 0.14, 0.18, 0.12);
        drawPlant(0.84, 0.56, 0.82);
        return;
    }
    if (theme === 'support') {
        drawDeskSetup(0.08, 0.22, 0.24, 0.14, { monitors: 1, chair: 'bottom' });
        drawDeskSetup(0.38, 0.22, 0.24, 0.14, { monitors: 1, chair: 'bottom' });
        drawDeskSetup(0.68, 0.22, 0.24, 0.14, { monitors: 1, chair: 'bottom' });
        drawRoundedRel(0.22, 0.58, 0.56, 0.16, tableFill, 'rgba(69, 84, 109, 0.68)', 0.14);
        drawPlant(0.08, 0.56, 0.84);
        return;
    }
    if (theme === 'pods' || theme === 'dynamic') {
        drawDeskSetup(0.12, 0.22, 0.32, 0.17, { monitors: 1, chair: 'bottom' });
        drawDeskSetup(0.56, 0.22, 0.32, 0.17, { monitors: 1, chair: 'bottom' });
        drawRoundedRel(0.28, 0.6, 0.44, 0.12, 'rgba(179, 188, 210, 0.84)', 'rgba(67, 83, 111, 0.64)', 0.16);
        drawRoundTable(0.5, 0.81, 0.062);
        return;
    }
    if (theme === 'break' || theme === 'coffee') {
        drawRoundedRel(0.24, 0.24, 0.52, 0.18, tableFill, 'rgba(69, 84, 109, 0.68)', 0.18);
        drawRoundTable(0.3, 0.68, 0.082);
        drawRoundTable(0.7, 0.68, 0.082);
        drawSofa(0.35, 0.56, 0.3, 0.16);
        drawPlant(0.08, 0.56, 0.9);
        drawPlant(0.84, 0.56, 0.9);
        return;
    }
    if (theme === 'lobby') {
        drawRoundedRel(0.18, 0.2, 0.62, 0.15, deskFill, deskStroke, 0.18);
        drawSofa(0.16, 0.54, 0.27, 0.14);
        drawSofa(0.56, 0.54, 0.27, 0.14);
        drawRoundTable(0.5, 0.63, 0.07);
        drawPlant(0.1, 0.18, 0.9);
        drawPlant(0.82, 0.18, 0.9);
        return;
    }

    drawDeskSetup(0.14, 0.24, 0.3, 0.16, { monitors: 1, chair: 'bottom' });
    drawDeskSetup(0.56, 0.24, 0.3, 0.16, { monitors: 1, chair: 'bottom' });
    drawRoundedRel(0.34, 0.58, 0.32, 0.16, tableFill, 'rgba(64, 79, 104, 0.66)', 0.14);
}

function officeDrawAmbientDecor(ctx, width, height) {
    OFFICE_AMBIENT_DECOR.forEach((item) => {
        const x = (item.x / 100) * width;
        const y = (item.y / 100) * height;
        const w = (Number(item.w) || 2.8) / 100 * width;
        const h = (Number(item.h) || 2.8) / 100 * height;

        if (item.type === 'tree') {
            officeCanvasRoundedBox(ctx, x - (w * 0.12), y - (h * 0.2), w * 0.24, h * 0.68, 2, '#7b8da9', 'rgba(66, 81, 104, 0.68)', 1);
            officeCanvasCircle(ctx, x, y - (h * 0.28), Math.max(8, (w + h) * 0.18), '#5f9577', 'rgba(55, 94, 75, 0.74)', 1);
            officeCanvasCircle(ctx, x - (w * 0.18), y - (h * 0.38), Math.max(6, (w + h) * 0.11), 'rgba(90, 146, 117, 0.9)');
            officeCanvasCircle(ctx, x + (w * 0.18), y - (h * 0.36), Math.max(6, (w + h) * 0.11), 'rgba(90, 146, 117, 0.9)');
            return;
        }
        if (item.type === 'windowstrip') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#d6ebff', 'rgba(117, 149, 186, 0.66)', 2);
            const paneW = Math.max(4, w / 7);
            for (let paneX = x - (w / 2) + paneW; paneX < x + (w / 2) - 1; paneX += paneW) {
                officeCanvasBox(ctx, paneX - 0.5, y - (h / 2) + 1, 1, Math.max(2, h - 2), 'rgba(116, 142, 173, 0.78)');
            }
            return;
        }
        if (item.type === 'plant') {
            officeCanvasBox(ctx, x - 7, y + 6, 14, 8, '#7f8ea8', 'rgba(54, 69, 92, 0.65)');
            ctx.fillStyle = '#5d8f73';
            ctx.beginPath();
            ctx.arc(x, y, 10, 0, Math.PI * 2);
            ctx.fill();
            return;
        }
        if (item.type === 'sofa') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#95a7c5', 'rgba(61, 79, 108, 0.68)', 2);
            return;
        }
        if (item.type === 'kiosk') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#8ba3c6', 'rgba(59, 74, 102, 0.72)', 2);
            officeCanvasBox(ctx, x - ((w * 0.26) / 2), y - ((h * 0.22) / 2), w * 0.26, h * 0.22, '#d6ebff');
            return;
        }
        if (item.type === 'whiteboard') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#f3f8ff', 'rgba(124, 142, 176, 0.78)', 2);
            officeCanvasBox(ctx, x - ((w * 0.58) / 2), y - ((h * 0.44) / 2), w * 0.58, h * 0.44, 'rgba(198, 221, 255, 0.76)');
            return;
        }
        if (item.type === 'bookshelf') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#8fa2bf', 'rgba(65, 83, 110, 0.72)', 2);
            officeCanvasBox(ctx, x - (w / 2) + 3, y - (h * 0.16), Math.max(3, w - 6), 2, '#7184a4');
            officeCanvasBox(ctx, x - (w / 2) + 3, y + (h * 0.12), Math.max(3, w - 6), 2, '#7184a4');
            return;
        }
        if (item.type === 'meetingtable') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#a8b5ca', 'rgba(67, 84, 110, 0.66)', 2);
            officeCanvasBox(ctx, x - (w * 0.42), y - (h * 0.64), w * 0.12, h * 0.26, '#8f9db8');
            officeCanvasBox(ctx, x - (w * 0.08), y - (h * 0.64), w * 0.12, h * 0.26, '#8f9db8');
            officeCanvasBox(ctx, x + (w * 0.26), y - (h * 0.64), w * 0.12, h * 0.26, '#8f9db8');
            return;
        }
        if (item.type === 'watercooler') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#9eb3d3', 'rgba(70, 88, 116, 0.68)', 2);
            officeCanvasBox(ctx, x - ((w * 0.5) / 2), y - (h * 0.45), w * 0.5, h * 0.25, '#d8efff', 'rgba(92, 116, 142, 0.56)', 1);
            return;
        }
        if (item.type === 'planterrow') {
            officeCanvasRoundedBox(ctx, x - (w / 2), y - (h / 2), w, h, Math.max(3, h * 0.28), '#8ca0bd', 'rgba(66, 84, 110, 0.66)', 2);
            const potCount = Math.max(3, Math.round(w / 26));
            const slot = w / potCount;
            for (let i = 0; i < potCount; i += 1) {
                const cx = x - (w / 2) + (slot * (i + 0.5));
                officeCanvasCircle(ctx, cx, y - (h * 0.16), Math.max(3, h * 0.42), '#67a17f', 'rgba(59, 97, 77, 0.72)', 1);
            }
            return;
        }
        if (item.type === 'vending') {
            officeCanvasRoundedBox(ctx, x - (w / 2), y - (h / 2), w, h, 3, '#7a8fb3', 'rgba(58, 74, 102, 0.72)', 2);
            officeCanvasRoundedBox(ctx, x - ((w * 0.66) / 2), y - (h * 0.28), w * 0.66, h * 0.4, 2, '#b2d1f8', 'rgba(69, 92, 124, 0.68)', 1);
            officeCanvasRoundedBox(ctx, x - ((w * 0.52) / 2), y + (h * 0.2), w * 0.52, h * 0.14, 2, '#586c92');
            officeCanvasCircle(ctx, x + (w * 0.24), y + (h * 0.28), Math.max(2, w * 0.08), '#e8f1ff');
            return;
        }
        if (item.type === 'lounge-rug') {
            officeCanvasRoundedBox(ctx, x - (w / 2), y - (h / 2), w, h, Math.max(6, Math.min(w, h) * 0.2), 'rgba(180, 198, 224, 0.52)', 'rgba(111, 130, 165, 0.38)', 1);
            officeCanvasRoundedBox(ctx, x - (w * 0.36), y - (h * 0.28), w * 0.72, h * 0.56, Math.max(4, Math.min(w, h) * 0.14), 'rgba(203, 218, 238, 0.46)');
            return;
        }
        if (item.type === 'floor-art') {
            officeCanvasRoundedBox(ctx, x - (w / 2), y - (h / 2), w, h, Math.max(3, h * 0.3), 'rgba(228, 237, 251, 0.72)', 'rgba(126, 148, 182, 0.56)', 1);
            officeCanvasLine(ctx, x - (w * 0.3), y + (h * 0.18), x - (w * 0.05), y - (h * 0.14), 'rgba(95, 130, 184, 0.54)', 1);
            officeCanvasLine(ctx, x - (w * 0.02), y + (h * 0.14), x + (w * 0.26), y - (h * 0.12), 'rgba(84, 159, 132, 0.56)', 1);
            return;
        }
        if (item.type === 'bench') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h * 0.5, '#a5b5cb', 'rgba(66, 83, 109, 0.66)', 2);
            officeCanvasBox(ctx, x - (w * 0.36), y + (h * 0.1), w * 0.12, h * 0.42, '#7b8ca8');
            officeCanvasBox(ctx, x + (w * 0.24), y + (h * 0.1), w * 0.12, h * 0.42, '#7b8ca8');
            return;
        }
        if (item.type === 'lamp') {
            officeCanvasBox(ctx, x - (w * 0.1), y - (h / 2), w * 0.2, h * 0.75, '#7186a8');
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h * 0.24, '#dbe7ff', 'rgba(106, 125, 159, 0.64)', 1);
            return;
        }
        if (item.type === 'arcade') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#6e7da0', 'rgba(54, 69, 95, 0.76)', 2);
            officeCanvasBox(ctx, x - ((w * 0.62) / 2), y - (h * 0.16), w * 0.62, h * 0.35, '#96b3dd', 'rgba(55, 70, 99, 0.78)', 1);
            officeCanvasBox(ctx, x - ((w * 0.2) / 2), y + (h * 0.22), w * 0.2, h * 0.14, '#f2d47e', 'rgba(88, 76, 42, 0.7)', 1);
            return;
        }
        if (item.type === 'pingpong') {
            officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#7ca7c6', 'rgba(56, 80, 108, 0.72)', 2);
            officeCanvasBox(ctx, x - (w * 0.02), y - (h / 2), Math.max(1, w * 0.04), h, '#d8ecff');
            officeCanvasBox(ctx, x - (w * 0.12), y + (h * 0.44), w * 0.08, h * 0.2, '#6b7f9f');
            officeCanvasBox(ctx, x + (w * 0.04), y + (h * 0.44), w * 0.08, h * 0.2, '#6b7f9f');
            return;
        }
        officeCanvasBox(ctx, x - (w / 2), y - (h / 2), w, h, '#8ea0bc', 'rgba(60, 77, 106, 0.66)', 2);
    });
}

function officeDrawTilemap(canvas, rooms, corridors) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    const tile = 26;
    const corridorFill = '#f3f8ff';
    const corridorStroke = 'rgba(88, 116, 150, 0.82)';
    const corridorJointFill = 'rgba(251, 254, 255, 0.98)';
    const corridorShadow = 'rgba(18, 29, 46, 0.34)';
    const spriteAtlas = officeGetSpriteAtlas();
    const hallNodePxById = new Map();
    OFFICE_HALL_NODES.forEach((node) => {
        hallNodePxById.set(node.id, {
            x: (node.x / 100) * width,
            y: (node.y / 100) * height,
        });
    });

    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.clearRect(0, 0, width, height);

    officeCanvasBox(
        ctx,
        0,
        0,
        width,
        height,
        '#8eacc2',
    );
    officeCanvasBox(
        ctx,
        width * 0.02,
        height * 0.02,
        width * 0.96,
        height * 0.96,
        'rgba(214, 230, 240, 0.94)',
    );

    officeCanvasBox(
        ctx,
        width * 0.03,
        height * 0.045,
        width * 0.94,
        height * 0.012,
        'rgba(109, 137, 168, 0.5)',
    );
    officeCanvasBox(
        ctx,
        width * 0.03,
        height * 0.9,
        width * 0.94,
        height * 0.01,
        'rgba(72, 96, 125, 0.36)',
    );

    officeCanvasRoundedBox(
        ctx,
        width * 0.035,
        height * 0.058,
        width * 0.93,
        height * 0.84,
        Math.max(18, Math.min(width, height) * 0.024),
        'rgba(224, 236, 246, 0.62)',
    );

    for (let y = 0; y < height; y += tile) {
        for (let x = 0; x < width; x += tile) {
            const checker = ((Math.floor(x / tile) + Math.floor(y / tile)) % 2) === 0;
            officeCanvasBox(
                ctx,
                x,
                y,
                tile,
                tile,
                checker ? 'rgba(248, 252, 255, 0.14)' : 'rgba(137, 161, 188, 0.07)',
            );
        }
    }

    corridors.forEach((corridor, corridorIndex) => {
        const x = (corridor.x / 100) * width;
        const y = (corridor.y / 100) * height;
        const w = (corridor.w / 100) * width;
        const h = (corridor.h / 100) * height;
        const radius = Math.max(4, Math.min(12, Math.min(w, h) * 0.46));
        officeCanvasRoundedBox(ctx, x + 1.5, y + 2, Math.max(2, w - 1.5), Math.max(2, h - 1), radius, corridorShadow);
        officeCanvasRoundedBox(ctx, x, y, w, h, corridorFill, corridorStroke, 2);
        const corridorSpriteId = corridor.orientation === 'h'
            ? (corridorIndex % 2 === 0 ? 'corridor_main' : 'corridor_polished')
            : (corridorIndex % 2 === 0 ? 'corridor_alt' : 'corridor_soft');
        officePaintSpriteFill(
            ctx,
            spriteAtlas,
            corridorSpriteId,
            x + 1,
            y + 1,
            Math.max(2, w - 2),
            Math.max(2, h - 2),
            20,
            0.6,
        );
        const edgeGlow = 'rgba(255, 255, 255, 0.56)';
        const edgeShade = 'rgba(54, 76, 108, 0.32)';
        if (corridor.orientation === 'h') {
            officeCanvasBox(ctx, x + 2, y + 1.6, Math.max(2, w - 4), Math.max(1.5, h * 0.12), edgeGlow);
            officeCanvasBox(ctx, x + 2, y + h - Math.max(2.5, h * 0.14), Math.max(2, w - 4), Math.max(1.5, h * 0.12), edgeShade);
        } else {
            officeCanvasBox(ctx, x + 1.6, y + 2, Math.max(1.5, w * 0.12), Math.max(2, h - 4), edgeGlow);
            officeCanvasBox(ctx, x + w - Math.max(2.5, w * 0.14), y + 2, Math.max(1.5, w * 0.12), Math.max(2, h - 4), edgeShade);
        }

        // Corridor rhythm marks give the map a clearer Gather-like walkway feel.
        ctx.strokeStyle = 'rgba(106, 126, 158, 0.22)';
        ctx.lineWidth = 1;
        if (corridor.orientation === 'h') {
            for (let markerX = x + 10; markerX < x + w - 10; markerX += 24) {
                ctx.beginPath();
                ctx.moveTo(markerX + 0.5, y + 4);
                ctx.lineTo(markerX + 0.5, y + h - 4);
                ctx.stroke();
                officeCanvasCircle(ctx, markerX + 0.5, y + (h * 0.5), 1.3, 'rgba(150, 176, 212, 0.56)');
            }
        } else {
            for (let markerY = y + 10; markerY < y + h - 10; markerY += 24) {
                ctx.beginPath();
                ctx.moveTo(x + 4, markerY + 0.5);
                ctx.lineTo(x + w - 4, markerY + 0.5);
                ctx.stroke();
                officeCanvasCircle(ctx, x + (w * 0.5), markerY + 0.5, 1.3, 'rgba(150, 176, 212, 0.56)');
            }
        }

        ctx.strokeStyle = 'rgba(66, 88, 122, 0.28)';
        ctx.lineWidth = 1;
        if (corridor.orientation === 'h') {
            const seamY = y + (h / 2);
            ctx.beginPath();
            ctx.moveTo(x + 2, seamY + 0.5);
            ctx.lineTo(x + w - 2, seamY + 0.5);
            ctx.stroke();
        } else {
            const seamX = x + (w / 2);
            ctx.beginPath();
            ctx.moveTo(seamX + 0.5, y + 2);
            ctx.lineTo(seamX + 0.5, y + h - 2);
            ctx.stroke();
        }
    });

    OFFICE_HALL_NODES.forEach((node) => {
        const x = (node.x / 100) * width;
        const y = (node.y / 100) * height;
        const radius = 8.2;
        officeCanvasCircle(ctx, x, y, radius + 2.7, 'rgba(194, 216, 240, 0.4)');
        ctx.fillStyle = corridorJointFill;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = 'rgba(111, 136, 170, 0.64)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = 'rgba(137, 160, 194, 0.5)';
        ctx.beginPath();
        ctx.arc(x, y, 2.4, 0, Math.PI * 2);
        ctx.fill();
    });

    officeDrawAmbientDecor(ctx, width, height);

    rooms.forEach((room) => {
        const rect = officeRoomPixels(room, width, height);
        const palette = officeRoomThemePalette(room.theme || room.kind);
        const wall = Math.max(9, Math.round(Math.min(rect.w, rect.h) * 0.068));
        const cornerRadius = Math.max(8, Math.round(Math.min(rect.w, rect.h) * 0.084));
        const innerRadius = Math.max(6, cornerRadius - Math.max(2, Math.round(wall * 0.4)));

        officeCanvasRoundedBox(
            ctx,
            rect.x + 2,
            rect.y + 3,
            Math.max(4, rect.w - 1),
            Math.max(4, rect.h - 1),
            cornerRadius,
            'rgba(27, 37, 56, 0.16)',
        );

        officeCanvasRoundedBox(ctx, rect.x, rect.y, rect.w, rect.h, cornerRadius, palette.wall, 'rgba(40, 54, 82, 0.68)', 2);
        officeCanvasRoundedBox(
            ctx,
            rect.x + wall,
            rect.y + wall,
            Math.max(6, rect.w - (wall * 2)),
            Math.max(6, rect.h - (wall * 2)),
            innerRadius,
            palette.floor,
        );
        officePaintSpriteFill(
            ctx,
            spriteAtlas,
            officeRoomThemeFloorSprite(room.theme || room.kind),
            rect.x + wall + 1,
            rect.y + wall + 1,
            Math.max(4, rect.w - (wall * 2) - 2),
            Math.max(4, rect.h - (wall * 2) - 2),
            18,
            0.56,
        );
        officeCanvasRoundedBox(
            ctx,
            rect.x + (wall * 1.16),
            rect.y + (wall * 1.16),
            Math.max(4, rect.w - (wall * 2.32)),
            Math.max(4, rect.h - (wall * 2.32)),
            Math.max(4, innerRadius * 0.76),
            'rgba(243, 249, 255, 0.05)',
        );
        officeCanvasBox(
            ctx,
            rect.x + 1,
            rect.y + 1,
            Math.max(2, rect.w - 2),
            Math.max(2, wall * 0.22),
            'rgba(243, 249, 255, 0.28)',
        );
        officeCanvasBox(
            ctx,
            rect.x + wall,
            rect.y + rect.h - wall - 2,
            Math.max(3, rect.w - (wall * 2)),
            Math.max(2, wall * 0.14),
            'rgba(34, 47, 67, 0.2)',
        );

        const pillar = Math.max(3, Math.round(wall * 0.38));
        officeCanvasRoundedBox(ctx, rect.x + 1, rect.y + 1, pillar, pillar, 2, 'rgba(212, 225, 246, 0.62)');
        officeCanvasRoundedBox(ctx, rect.x + rect.w - pillar - 1, rect.y + 1, pillar, pillar, 2, 'rgba(212, 225, 246, 0.62)');
        officeCanvasRoundedBox(ctx, rect.x + 1, rect.y + rect.h - pillar - 1, pillar, pillar, 2, 'rgba(76, 96, 126, 0.38)');
        officeCanvasRoundedBox(ctx, rect.x + rect.w - pillar - 1, rect.y + rect.h - pillar - 1, pillar, pillar, 2, 'rgba(76, 96, 126, 0.38)');

        // Subtle interior lines for a Gather-style tile feel.
        ctx.strokeStyle = 'rgba(69, 87, 121, 0.3)';
        ctx.lineWidth = 1;
        for (let x = rect.x + wall + tile; x < rect.x + rect.w - wall; x += tile) {
            ctx.beginPath();
            ctx.moveTo(x + 0.5, rect.y + wall);
            ctx.lineTo(x + 0.5, rect.y + rect.h - wall);
            ctx.stroke();
        }
        for (let y = rect.y + wall + tile; y < rect.y + rect.h - wall; y += tile) {
            ctx.beginPath();
            ctx.moveTo(rect.x + wall, y + 0.5);
            ctx.lineTo(rect.x + rect.w - wall, y + 0.5);
            ctx.stroke();
        }

        const doorWidth = Math.max(24, Math.min(56, Math.min(rect.w, rect.h) * 0.24));
        const doorDistances = {
            top: Math.abs(rect.doorY - rect.y),
            bottom: Math.abs(rect.doorY - (rect.y + rect.h)),
            left: Math.abs(rect.doorX - rect.x),
            right: Math.abs(rect.doorX - (rect.x + rect.w)),
        };
        const edge = Object.entries(doorDistances).sort((a, b) => a[1] - b[1])[0]?.[0] || 'bottom';
        const doorAnchor = { x: rect.doorX, y: rect.doorY };
        if (edge === 'top') doorAnchor.y = rect.y;
        if (edge === 'bottom') doorAnchor.y = rect.y + rect.h;
        if (edge === 'left') doorAnchor.x = rect.x;
        if (edge === 'right') doorAnchor.x = rect.x + rect.w;
        const doorDepth = Math.max(7, wall * 1.06);
        const doorRadius = Math.max(3, Math.min(doorWidth, doorDepth) * 0.2);
        const doorTrim = 'rgba(83, 106, 142, 0.78)';
        const doorSill = 'rgba(119, 144, 180, 0.72)';

        if (edge === 'top') {
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth / 2), rect.y - doorDepth + 1, doorWidth, doorDepth + 2, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.42), rect.y - doorDepth + 2, doorWidth * 0.84, Math.max(3, wall * 0.22), Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.46), rect.y + wall - 4, doorWidth * 0.92, Math.max(2, wall * 0.16), Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else if (edge === 'bottom') {
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth / 2), rect.y + rect.h - 1, doorWidth, doorDepth + 1, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.42), rect.y + rect.h + 1, doorWidth * 0.84, Math.max(3, wall * 0.22), Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.46), rect.y + rect.h - wall - 4, doorWidth * 0.92, Math.max(2, wall * 0.16), Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else if (edge === 'left') {
            officeCanvasRoundedBox(ctx, rect.x - doorDepth + 1, doorAnchor.y - (doorWidth / 2), doorDepth + 2, doorWidth, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, rect.x - doorDepth + 2, doorAnchor.y - (doorWidth * 0.42), Math.max(3, wall * 0.22), doorWidth * 0.84, Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, rect.x + wall - 4, doorAnchor.y - (doorWidth * 0.46), Math.max(2, wall * 0.16), doorWidth * 0.92, Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else {
            officeCanvasRoundedBox(ctx, rect.x + rect.w - 1, doorAnchor.y - (doorWidth / 2), doorDepth + 1, doorWidth, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, rect.x + rect.w + 1, doorAnchor.y - (doorWidth * 0.42), Math.max(3, wall * 0.22), doorWidth * 0.84, Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, rect.x + rect.w - wall - 4, doorAnchor.y - (doorWidth * 0.46), Math.max(2, wall * 0.16), doorWidth * 0.92, Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        }

        // Draw a connector from each doorway to its hall node so corridors visually align with rooms.
        const hallPx = hallNodePxById.get(safeString(room.hallId));
        if (hallPx) {
            const connectorHalf = Math.max(5, Math.min(12, doorWidth * 0.24));
            const connectorStroke = 'rgba(128, 149, 183, 0.7)';
            const connectorRadius = Math.max(3, connectorHalf * 0.9);
            const drawConnector = (x1, y1, x2, y2) => {
                const dx = x2 - x1;
                const dy = y2 - y1;
                if (Math.hypot(dx, dy) < 0.9) return;
                if (Math.abs(dx) >= Math.abs(dy)) {
                    const minX = Math.min(x1, x2);
                    officeCanvasRoundedBox(
                        ctx,
                        minX,
                        y1 - connectorHalf,
                        Math.max(1.2, Math.abs(dx)),
                        connectorHalf * 2,
                        connectorRadius,
                        corridorFill,
                        connectorStroke,
                        1,
                    );
                } else {
                    const minY = Math.min(y1, y2);
                    officeCanvasRoundedBox(
                        ctx,
                        x1 - connectorHalf,
                        minY,
                        connectorHalf * 2,
                        Math.max(1.2, Math.abs(dy)),
                        connectorRadius,
                        corridorFill,
                        connectorStroke,
                        1,
                    );
                }
            };

            if (edge === 'top' || edge === 'bottom') {
                drawConnector(doorAnchor.x, doorAnchor.y, doorAnchor.x, hallPx.y);
                drawConnector(doorAnchor.x, hallPx.y, hallPx.x, hallPx.y);
            } else {
                drawConnector(doorAnchor.x, doorAnchor.y, hallPx.x, doorAnchor.y);
                drawConnector(hallPx.x, doorAnchor.y, hallPx.x, hallPx.y);
            }

            officeCanvasCircle(
                ctx,
                doorAnchor.x,
                doorAnchor.y,
                Math.max(2.8, connectorHalf * 0.46),
                'rgba(234, 241, 249, 0.98)',
                'rgba(120, 142, 176, 0.72)',
                1,
            );
        }

        officeDrawRoomFurnitureCanvas(ctx, room, {
            x: rect.x + wall + 6,
            y: rect.y + wall + 6,
            w: Math.max(4, rect.w - ((wall + 6) * 2)),
            h: Math.max(4, rect.h - ((wall + 6) * 2)),
        }, palette);
    });

    ctx.restore();
}

function officeEnsureNativeSceneLayers() {
    if (!officeScene || !officeState) return null;
    officeScene.classList.add('office-scene-native');

    let worldEl = officeScene.querySelector('.office-world');
    if (!worldEl) {
        officeScene.innerHTML = '';
        worldEl = document.createElement('div');
        worldEl.className = 'office-world';
        worldEl.innerHTML = `
            <canvas class="office-tilemap-canvas" aria-hidden="true"></canvas>
            <div class="office-room-layer" aria-hidden="true"></div>
            <div class="office-agent-layer" aria-label="Active office agents"></div>
            <aside class="office-roster-panel" aria-label="Office roster"></aside>
        `;
        officeScene.appendChild(worldEl);
    }

    const tilemapCanvas = worldEl.querySelector('.office-tilemap-canvas');
    const roomLayer = worldEl.querySelector('.office-room-layer');
    const agentLayer = worldEl.querySelector('.office-agent-layer');
    const rosterPanel = worldEl.querySelector('.office-roster-panel');
    if (!tilemapCanvas || !roomLayer || !agentLayer || !rosterPanel) {
        return null;
    }

    officeState.tilemapCanvas = tilemapCanvas;
    officeState.roomLayerEl = roomLayer;
    officeState.agentLayerEl = agentLayer;
    officeState.rosterPanelEl = rosterPanel;
    officeState.agentElements = officeState.agentElements || new Map();
    return { worldEl, tilemapCanvas, roomLayer, agentLayer, rosterPanel };
}

function officeRoomAgents(room) {
    if (!officeState || !room) return [];
    return officeState.agents.filter((agent) => officeCurrentRoomForAgent(agent)?.id === room.id);
}

function officeRenderRoomOverlays() {
    if (!officeState?.roomLayerEl) return;
    const roomLayer = officeState.roomLayerEl;
    roomLayer.innerHTML = '';

    officeState.rooms.forEach((room) => {
        const roomEl = document.createElement('article');
        roomEl.className = `office-room overlay theme-${safeString(room.theme || room.kind).toLowerCase() || 'default'}`;
        roomEl.dataset.roomId = room.id;
        roomEl.style.left = `${room.x}%`;
        roomEl.style.top = `${room.y}%`;
        roomEl.style.width = `${room.w}%`;
        roomEl.style.height = `${room.h}%`;

        const assignedAgents = officeRoomAgents(room);
        const rosterMarkup = assignedAgents.slice(0, 3).map((agent) => (
            `<span class="office-room-roster-chip">${escapeHtml(agent.name)}</span>`
        )).join('');
        const deskSummary = assignedAgents.length
            ? `${assignedAgents.length} active in zone`
            : safeString(room.meta || 'Reserved desk zone');

        roomEl.innerHTML = `
            <header class="office-room-title">${escapeHtml(room.label)}</header>
            <div class="office-room-meta">${escapeHtml(deskSummary)}</div>
            <div class="office-room-roster">${rosterMarkup || '<span class="office-room-roster-empty">Reserved desks ready</span>'}</div>
        `;
        roomLayer.appendChild(roomEl);
    });
}

function officeRenderRosterPanel() {
    if (!officeState?.rosterPanelEl) return;
    const panel = officeState.rosterPanelEl;
    const selectedId = safeString(officeState.selectedAgentId);
    panel.innerHTML = '';

    const head = document.createElement('div');
    head.className = 'office-roster-head';
    head.innerHTML = `
        <strong>Active Roster</strong>
        <span>${officeState.agents.length} agents</span>
    `;
    panel.appendChild(head);

    const list = document.createElement('div');
    list.className = 'office-roster-list';

    officeState.agents.forEach((agent) => {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'office-roster-card';
        if (agent.id === selectedId) card.classList.add('is-selected');
        const room = officeCurrentRoomForAgent(agent);
        const palette = officeAgentPalette(agent);
        card.style.setProperty('--agent-primary', palette.primary);
        card.style.setProperty('--agent-secondary', palette.secondary);
        card.style.setProperty('--agent-glow', palette.glow);
        card.innerHTML = `
            <span class="office-roster-avatar">
                <span class="office-pixel-agent${agent.facing < 0 ? ' facing-left' : ''}">
                    <span class="office-agent-head">
                        <span class="office-agent-eye office-agent-eye-left"></span>
                        <span class="office-agent-eye office-agent-eye-right"></span>
                    </span>
                    <span class="office-agent-body"></span>
                    <span class="office-agent-leg office-agent-leg-left"></span>
                    <span class="office-agent-leg office-agent-leg-right"></span>
                </span>
            </span>
            <span class="office-roster-copy">
                <strong>${escapeHtml(agent.name)}</strong>
                <span>${escapeHtml(room?.label || 'Roaming')}</span>
            </span>
            <span class="office-roster-state">${escapeHtml(safeString(agent.state || 'idle'))}</span>
        `;
        card.addEventListener('click', () => officeHandleAgentTap(agent.id));
        list.appendChild(card);
    });

    panel.appendChild(list);
}

function officeRenderScene() {
    if (!officeScene) return;
    if (!officeState) return;

    const mounted = officeEnsureNativeSceneLayers();
    if (!mounted) return;

    const { tilemapCanvas } = mounted;
    tilemapCanvas.width = Math.max(1, Math.round(officeState.mapWidth || OFFICE_MAP_WIDTH));
    tilemapCanvas.height = Math.max(1, Math.round(officeState.mapHeight || OFFICE_MAP_HEIGHT));
    officeDrawTilemap(tilemapCanvas, officeState.rooms, officeState.corridors || []);
    officeRenderRoomOverlays();
    officeRenderRosterPanel();
    officeUpdateRoomMeta();
}

