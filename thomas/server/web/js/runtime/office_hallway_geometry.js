/** Office room geometry and connector selection. */

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


