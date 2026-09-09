/** Collision-aware default-layout polishing. */

function officeDraftDefaultAssetCanLayer(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    return OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES.has(type)
        || OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES.has(safeString(descriptor?.shape));
}

function officeDraftDefaultAssetVisualRect(asset) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const padding = officeDraftDefaultAssetCanLayer(asset) ? -24 : 14;
    const left = Math.round(Number(asset?.x) || 0);
    const top = Math.round(Number(asset?.y) || 0);
    return {
        left: left - padding,
        top: top - padding,
        right: left + Number(dimensions.width || 0) + padding,
        bottom: top + Number(dimensions.height || 0) + padding,
    };
}

function officeDraftDefaultAssetInteractionClearanceRects(asset, roomWidthRaw = 0, roomHeightRaw = 0) {
    if (!asset || officeDraftDefaultAssetCanLayer(asset)) return [];
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const interaction = safeString(descriptor?.interaction);
    const needsClearance = OFFICE_DRAFT_DEFAULT_INTERACTION_CLEARANCE_TYPES.has(type)
        || ['drink', 'food', 'play', 'print', 'charge', 'work'].includes(interaction);
    if (!needsClearance) return [];
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const roomWidth = Number(roomWidthRaw) || 0;
    const roomHeight = Number(roomHeightRaw) || 0;
    const left = Math.round(Number(asset?.x) || 0);
    const top = Math.round(Number(asset?.y) || 0);
    const right = left + Number(dimensions.width || 0);
    const bottom = top + Number(dimensions.height || 0);
    const reach = type === 'vending_machine' ? 270 : 190;
    const frontDepth = type === 'vending_machine' ? 250 : 180;
    const pad = type === 'vending_machine' ? 26 : 18;
    const clampRect = (rect) => ({
        left: Math.round(officeClamp(rect.left, -80, Math.max(roomWidth, rect.left))),
        top: Math.round(officeClamp(rect.top, -80, Math.max(roomHeight, rect.top))),
        right: Math.round(officeClamp(rect.right, 0, roomWidth + 80)),
        bottom: Math.round(officeClamp(rect.bottom, 0, roomHeight + 80)),
    });
    return [
        clampRect({
            left: left - pad,
            top: bottom + 8,
            right: right + reach,
            bottom: bottom + frontDepth,
        }),
        clampRect({
            left: right + 8,
            top: top + Math.round(Number(dimensions.height || 0) * 0.08),
            right: right + reach,
            bottom: bottom + Math.round(frontDepth * 0.72),
        }),
    ].filter((rect) => rect.left < rect.right && rect.top < rect.bottom);
}

function officeDraftDefaultRectsOverlap(a, b) {
    if (!a || !b) return false;
    return a.left < b.right
        && a.right > b.left
        && a.top < b.bottom
        && a.bottom > b.top;
}

function officeDraftDefaultDoorClearanceRects(space) {
    const width = Number(space?.width) || 0;
    const height = Number(space?.height) || 0;
    if (width <= 0 || height <= 0) return [];
    const depth = Math.max(150, Math.min(210, Math.round(Math.min(width, height) * 0.2)));
    const horizontalSpan = Math.max(240, Math.min(420, Math.round(width * 0.28)));
    const verticalSpan = Math.max(220, Math.min(380, Math.round(height * 0.3)));
    const centerX = Math.round(width * 0.5);
    const centerY = Math.round(height * 0.52);
    const horizontalLeft = Math.round(centerX - (horizontalSpan / 2));
    const horizontalRight = Math.round(centerX + (horizontalSpan / 2));
    const verticalTop = Math.round(centerY - (verticalSpan / 2));
    const verticalBottom = Math.round(centerY + (verticalSpan / 2));
    return [
        { left: horizontalLeft, top: height - depth, right: horizontalRight, bottom: height + 80 },
        { left: horizontalLeft, top: -80, right: horizontalRight, bottom: depth },
        { left: width - depth, top: verticalTop, right: width + 80, bottom: verticalBottom },
        { left: -80, top: verticalTop, right: depth, bottom: verticalBottom },
    ];
}

function officeDraftDefaultRobotClearanceRect(space) {
    const robotX = Math.round(Number(space?.robotX) || 0);
    const robotY = Math.round(Number(space?.robotY) || 0);
    if (!robotX || !robotY) return null;
    return {
        left: robotX - 104,
        top: robotY - 112,
        right: robotX + 124,
        bottom: robotY + 138,
    };
}

function officeDraftDefaultAssetNudgeCandidates(asset, roomWidth, roomHeight) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const margin = 40;
    const maxX = Math.max(margin, Number(roomWidth) - Number(dimensions.width || 0) - margin);
    const maxY = Math.max(margin, Number(roomHeight) - Number(dimensions.height || 0) - margin);
    const originX = Math.round(Number(asset?.x) || 0);
    const originY = Math.round(Number(asset?.y) || 0);
    const clampCandidate = (dx, dy) => ({
        x: Math.round(officeClamp(originX + dx, margin, maxX)),
        y: Math.round(officeClamp(originY + dy, margin, maxY)),
    });
    const candidates = [clampCandidate(0, 0)];
    const stepX = Math.max(76, Math.round(Number(dimensions.width || 0) * 0.58));
    const stepY = Math.max(64, Math.round(Number(dimensions.height || 0) * 0.62));
    for (let ring = 1; ring <= 6; ring += 1) {
        [
            [ring, 0],
            [-ring, 0],
            [0, ring],
            [0, -ring],
            [ring, ring],
            [-ring, ring],
            [ring, -ring],
            [-ring, -ring],
            [ring, Math.ceil(ring / 2)],
            [-ring, Math.ceil(ring / 2)],
            [Math.ceil(ring / 2), ring],
            [Math.ceil(ring / 2), -ring],
        ].forEach(([xMul, yMul]) => {
            candidates.push(clampCandidate(xMul * stepX, yMul * stepY));
        });
    }
    const scanStepX = Math.max(86, Math.round(Number(dimensions.width || 0) * 0.68));
    const scanStepY = Math.max(72, Math.round(Number(dimensions.height || 0) * 0.72));
    for (let y = margin; y <= maxY; y += scanStepY) {
        for (let x = margin; x <= maxX; x += scanStepX) {
            candidates.push({
                x: Math.round(officeClamp(x, margin, maxX)),
                y: Math.round(officeClamp(y, margin, maxY)),
            });
        }
    }
    candidates.push({ x: Math.round(maxX), y: Math.round(maxY) });
    const seen = new Set();
    return candidates.filter((candidate) => {
        const key = `${candidate.x},${candidate.y}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function officeDraftPolishDefaultAsset(asset, roomWidth, roomHeight, placedRects, reservedRects = []) {
    const next = {
        ...asset,
        rotation: OFFICE_DRAFT_DEFAULT_UPRIGHT_ASSET_TYPES.has(safeString(asset?.type))
            ? 0
            : officeDraftNormalizeRotation(asset?.rotation),
    };
    if (officeDraftDefaultAssetCanLayer(next)) return next;
    let best = { ...next };
    let bestScore = Number.POSITIVE_INFINITY;
    const reserved = (Array.isArray(reservedRects) ? reservedRects : []).filter(Boolean);
    const candidates = officeDraftDefaultAssetNudgeCandidates(next, roomWidth, roomHeight);
    const scoreCandidates = ({ allowPlacedOverlap = false, allowReservedOverlap = false } = {}) => {
        candidates.forEach((candidate) => {
            const candidateAsset = { ...next, x: candidate.x, y: candidate.y };
            const rect = officeDraftDefaultAssetVisualRect(candidateAsset);
            const placedOverlapCount = placedRects.filter((placed) => officeDraftDefaultRectsOverlap(rect, placed)).length;
            if (!allowPlacedOverlap && placedOverlapCount) return;
            const reservedOverlapCount = reserved.filter((reservedRect) => officeDraftDefaultRectsOverlap(rect, reservedRect)).length;
            if (!allowReservedOverlap && reservedOverlapCount) return;
            const distance = Math.hypot(candidate.x - (Number(next.x) || 0), candidate.y - (Number(next.y) || 0));
            const score = distance + (candidate.y * 0.02) + (reservedOverlapCount * 400) + (placedOverlapCount * 10000);
            if (score < bestScore) {
                best = candidateAsset;
                bestScore = score;
            }
        });
    };
    scoreCandidates({ allowPlacedOverlap: false, allowReservedOverlap: false });
    if (!Number.isFinite(bestScore)) scoreCandidates({ allowPlacedOverlap: false, allowReservedOverlap: true });
    if (!Number.isFinite(bestScore)) scoreCandidates({ allowPlacedOverlap: true, allowReservedOverlap: true });
    return best;
}

function officeDraftPolishDefaultLayoutSpaces(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    return spaces.map((space) => {
        const placedRects = [];
        const reservedRects = [
            ...officeDraftDefaultDoorClearanceRects(space),
            officeDraftDefaultRobotClearanceRect(space),
        ].filter(Boolean);
        const assets = (Array.isArray(space?.assets) ? space.assets : []).map((asset) => {
            const override = OFFICE_DRAFT_DEFAULT_LAYOUT_ASSET_OVERRIDES[safeString(space?.id)]?.[safeString(asset?.id)] || null;
            const authoredAsset = override ? { ...asset, ...override } : asset;
            const polished = officeDraftPolishDefaultAsset(
                authoredAsset,
                Number(space?.width) || 0,
                Number(space?.height) || 0,
                placedRects,
                reservedRects,
            );
            if (!officeDraftDefaultAssetCanLayer(polished)) {
                placedRects.push(officeDraftDefaultAssetVisualRect(polished));
                reservedRects.push(...officeDraftDefaultAssetInteractionClearanceRects(
                    polished,
                    Number(space?.width) || 0,
                    Number(space?.height) || 0,
                ));
            }
            return polished;
        });
        return {
            ...space,
            assets,
        };
    });
}


