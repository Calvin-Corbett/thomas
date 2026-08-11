/** Office map constants, rooms, corridors, and agent seeds. */

const OFFICE_VIEWPORT_MARGIN = 0;
const OFFICE_MINIMAP_PAD_RATIO = 0.06;
const OFFICE_COLLISION_PAIR_COOLDOWN_MIN = 1300;
const OFFICE_COLLISION_PAIR_COOLDOWN_MAX = 2100;
const OFFICE_COLLISION_PAIR_PURGE_MS = 2600;
const OFFICE_RUNAWAY_DURATION_MS = 5600;
const OFFICE_RUNAWAY_EXIT_MARGIN = 6.2;
const OFFICE_HAPTIC_COOLDOWN_MS = 120;
const OFFICE_RUNTIME_TIMER_FIELDS = [
    'workUntil',
    'breakUntil',
    'idleUntil',
    'nextAmbientAt',
    'nextWorkLineAt',
    'nextSocialAt',
    'nextBreakAt',
    'bumpUntil',
    'jumpUntil',
    'collisionCooldownUntil',
    'crowdReliefUntil',
    'yieldUntil',
    'stuckSince',
    'returnAfterRunAt',
];
const MISSION_POLL_INTERVAL_MS = 6500;
const MISSION_STREAM_RETRY_MIN_MS = 900;
const MISSION_STREAM_RETRY_MAX_MS = 12000;
const MISSION_STREAM_URL = '/api/mission/stream?interval=1.2';
const MISSION_PRIORITY_LIMIT = 16;
const MISSION_TIMELINE_LIMIT = 10;
const MISSION_JOBS_LIMIT = 180;
const MISSION_TIMELINE_RECENT_MS = 1000 * 60 * 60 * 36;
const MISSION_RECURRING_SCHEDULE_TYPES = new Set(['interval', 'daily', 'weekly']);
const CONTENT_HUB_STALE_MS = 45_000;
const OFFICE_STATIC_ROOMS = [
    { id: 'room-planning', label: 'Strategy Room', meta: 'Planning + roadmaps', x: 4, y: 7, w: 13, h: 11, kind: 'work', theme: 'planning', doorX: 17, doorY: 24, hallId: 'hall-north-west' },
    { id: 'room-engineering', label: 'Software Lab', meta: 'Code + automation', x: 20, y: 8, w: 30, h: 16, kind: 'work', theme: 'engineering', doorX: 35, doorY: 24, hallId: 'hall-north-mid' },
    { id: 'room-content', label: 'Content Studio', meta: 'Video + social', x: 53, y: 13, w: 17, h: 12, kind: 'work', theme: 'content', doorX: 61.5, doorY: 24, hallId: 'hall-north-mid' },
    { id: 'room-research', label: 'Research Bay', meta: 'Comparisons + docs', x: 72, y: 8, w: 22, h: 14, kind: 'work', theme: 'research', doorX: 82, doorY: 24, hallId: 'hall-north-east' },
    { id: 'room-support', label: 'Support Desk', meta: 'Tickets + feedback', x: 4, y: 37, w: 14, h: 12, kind: 'work', theme: 'support', doorX: 18, doorY: 48, hallId: 'hall-west' },
    { id: 'room-design', label: 'Design Loft', meta: 'UI + product polish', x: 24, y: 43, w: 20, h: 14, kind: 'work', theme: 'design', doorX: 34, doorY: 48, hallId: 'hall-center' },
    { id: 'room-ops', label: 'Ops Command', meta: 'Deploy + reliability', x: 48, y: 35, w: 26, h: 17, kind: 'work', theme: 'ops', doorX: 74, doorY: 48, hallId: 'hall-east' },
    { id: 'room-coffee', label: 'Cafeteria', meta: 'Gather + recharge', x: 6, y: 64, w: 36, h: 30, kind: 'break', theme: 'coffee', doorX: 24, doorY: 76, hallId: 'hall-south-west' },
    { id: 'room-break', label: 'Lounge', meta: 'Breaks + team chat', x: 45, y: 66, w: 24, h: 16, kind: 'break', theme: 'break', doorX: 57, doorY: 76, hallId: 'hall-south-mid' },
    { id: 'room-pods', label: 'Focus Pods', meta: 'Task swarms + deep work', x: 76, y: 54, w: 18, h: 12, kind: 'work', theme: 'pods', doorX: 76, doorY: 70, hallId: 'hall-south-east' },
    { id: 'room-lobby', label: 'Main Lobby', meta: 'Free roaming + dispatch', x: 56, y: 6, w: 16, h: 10, kind: 'lobby', theme: 'lobby', doorX: 64, doorY: 24, hallId: 'hall-north-mid' },
];
const OFFICE_MISSION_ROOM_TO_OFFICE_ROOM = Object.freeze({
    inbox: 'room-lobby',
    planning: 'room-planning',
    tools: 'room-engineering',
    files: 'room-engineering',
    review: 'room-support',
    done: 'room-lobby',
});
const OFFICE_HALL_NODES = [
    { id: 'hall-north-west', x: 20, y: 24 },
    { id: 'hall-north-mid', x: 48, y: 24 },
    { id: 'hall-north-east', x: 82, y: 24 },
    { id: 'hall-west', x: 20, y: 48 },
    { id: 'hall-center', x: 48, y: 48 },
    { id: 'hall-east', x: 82, y: 48 },
    { id: 'hall-south-west', x: 24, y: 76 },
    { id: 'hall-south-mid', x: 57, y: 76 },
    { id: 'hall-south-east', x: 82, y: 76 },
];
const OFFICE_HALL_EDGES = [
    ['hall-north-west', 'hall-north-mid'],
    ['hall-north-mid', 'hall-north-east'],
    ['hall-north-west', 'hall-west'],
    ['hall-west', 'hall-center'],
    ['hall-center', 'hall-east'],
    ['hall-north-east', 'hall-east'],
    ['hall-north-mid', 'hall-center'],
    ['hall-north-west', 'hall-center'],
    ['hall-north-east', 'hall-center'],
    ['hall-west', 'hall-south-west'],
    ['hall-center', 'hall-south-mid'],
    ['hall-east', 'hall-south-east'],
    ['hall-south-west', 'hall-south-mid'],
    ['hall-south-mid', 'hall-south-east'],
    ['hall-center', 'hall-south-west'],
    ['hall-center', 'hall-south-east'],
];
const OFFICE_CORRIDORS = [
    { x: 16.2, y: 20.2, w: 70.8, h: 7.8, orientation: 'h' },
    { x: 16.2, y: 44.0, w: 70.8, h: 8.4, orientation: 'h' },
    { x: 21.5, y: 72.0, w: 64.8, h: 8.8, orientation: 'h' },
    { x: 16.2, y: 20.2, w: 7.8, h: 60.8, orientation: 'v' },
    { x: 44.1, y: 20.2, w: 8.2, h: 60.8, orientation: 'v' },
    { x: 78.0, y: 20.2, w: 8.2, h: 60.8, orientation: 'v' },
];
const OFFICE_AMBIENT_DECOR = [
    { type: 'tree', x: 1.8, y: 10.4, w: 5.8, h: 8.8 },
    { type: 'tree', x: 1.8, y: 84.2, w: 5.8, h: 8.8 },
    { type: 'tree', x: 95.4, y: 10.4, w: 5.8, h: 8.8 },
    { type: 'tree', x: 95.4, y: 84.2, w: 5.8, h: 8.8 },
    { type: 'windowstrip', x: 24, y: 4.2, w: 18, h: 2.8 },
    { type: 'windowstrip', x: 46, y: 4.2, w: 18, h: 2.8 },
    { type: 'windowstrip', x: 68, y: 4.2, w: 18, h: 2.8 },
    { type: 'planterrow', x: 40, y: 24.6, w: 18, h: 3.4 },
    { type: 'planterrow', x: 22, y: 70.8, w: 12, h: 3.2 },
    { type: 'planterrow', x: 52, y: 70.8, w: 12, h: 3.2 },
    { type: 'planterrow', x: 78, y: 70.8, w: 10, h: 3.2 },
    { type: 'whiteboard', x: 8.4, y: 34, w: 7.2, h: 2.6 },
    { type: 'whiteboard', x: 62.8, y: 34, w: 7.2, h: 2.6 },
    { type: 'bookshelf', x: 8.6, y: 60.2, w: 8.4, h: 3.4 },
    { type: 'bookshelf', x: 88, y: 34, w: 7.2, h: 3.2 },
    { type: 'meetingtable', x: 30.4, y: 41.2, w: 11.2, h: 3.8 },
    { type: 'kiosk', x: 47.8, y: 66, w: 4, h: 4.6 },
    { type: 'watercooler', x: 18.2, y: 72.2, w: 3.3, h: 5 },
    { type: 'watercooler', x: 57.4, y: 72.2, w: 3.3, h: 5 },
    { type: 'vending', x: 12, y: 67.8, w: 3.8, h: 6 },
    { type: 'vending', x: 67.8, y: 67.8, w: 3.8, h: 6 },
    { type: 'sofa', x: 40.6, y: 72.4, w: 10.6, h: 3.2 },
    { type: 'bench', x: 79.8, y: 78.6, w: 8.8, h: 3.1 },
    { type: 'table', x: 26.4, y: 76, w: 4.8, h: 3.4 },
    { type: 'lamp', x: 64, y: 66.8, w: 2.4, h: 4.9 },
    { type: 'lamp', x: 70.2, y: 66.8, w: 2.4, h: 4.9 },
    { type: 'floor-art', x: 35.2, y: 49.4, w: 7.4, h: 3.4 },
    { type: 'floor-art', x: 49.2, y: 49.4, w: 7.4, h: 3.4 },
    { type: 'lounge-rug', x: 33, y: 61.8, w: 26, h: 17.5 },
];
const OFFICE_EXPLICIT_ROOM_IDS = Object.freeze({
    planning: 'room-planning',
    engineering: 'room-engineering',
    content: 'room-content',
    research: 'room-research',
    support: 'room-support',
    design: 'room-design',
    ops: 'room-ops',
    pods: 'room-pods',
});
const OFFICE_SPECIALIST_ROOM_IDS = Object.freeze({
    coding: 'room-engineering',
    research: 'room-research',
    tools: 'room-ops',
    writing: 'room-content',
    data: 'room-research',
    reasoning: 'room-planning',
});
const OFFICE_AGENT_SEEDS = [
    { name: 'Brandon', color: '#9ad8ff', costume: 'visor', tint: 'blue', specialty: 'Software builds', personality: 'Practical, fast, and precise with code tasks.' },
    { name: 'Trey', color: '#9becc9', costume: 'headset', tint: 'green', specialty: 'Research', personality: 'Patient, source-focused, and careful with claims.' },
    { name: 'Zach', color: '#ffd49f', costume: 'cap', tint: 'orange', specialty: 'Game builds', personality: 'Playful, iterative, and tuned for runnable prototypes.' },
    { name: 'Matt', color: '#ffc7eb', costume: 'bowtie', tint: 'pink', specialty: 'Design polish', personality: 'Visual, detail-oriented, and direct about UI tradeoffs.' },
    { name: 'Taylor', color: '#d7c8ff', costume: 'satchel', tint: 'purple', specialty: 'Planning', personality: 'Structured, strategic, and good at breaking work into steps.' },
    { name: 'John', color: '#ffeaa9', costume: 'badge', tint: 'yellow', specialty: 'Support review', personality: 'Calm, user-focused, and good at finding edge cases.' },
    { name: 'Nova', color: '#7df7ff', costume: 'toolbelt', tint: 'blue', specialty: 'Ops automation', personality: 'Steady, reliable, and comfortable with deploy paths.' },
    { name: 'Pixel', color: '#ff9bd2', costume: 'scarf', tint: 'pink', specialty: 'Content systems', personality: 'Concise, organized, and good at repeatable workflows.' },
    { name: 'Byte', color: '#c4ff72', costume: 'tablet', tint: 'green', specialty: 'Data tasks', personality: 'Analytical, skeptical, and careful with transformations.' },
    { name: 'Orbit', color: '#ffa66d', costume: 'wrench', tint: 'orange', specialty: 'Integration', personality: 'Connector-minded and good at tying systems together.' },
    { name: 'Echo', color: '#f6f09d', costume: 'visor', tint: 'yellow', specialty: 'Documentation', personality: 'Clear, complete, and good at preserving context.' },
    { name: 'Glitch', color: '#b497ff', costume: 'mug', tint: 'purple', specialty: 'Debugging', personality: 'Curious, persistent, and good at narrowing failures.' },
];
const OFFICE_AGENT_STYLE_COLOR_POOL = [
    '#9ad8ff',
    '#9becc9',
    '#ffd49f',
    '#ffc7eb',
    '#d7c8ff',
    '#ffeaa9',
    '#9fd9ff',
    '#b2ffc8',
    '#f4c4ff',
    '#ffd0a8',
    '#a7ffe3',
    '#b7d6ff',
    '#ffd8c2',
    '#e4ceff',
    '#c6f4ff',
];
const OFFICE_AGENT_COSTUME_POOL = ['none', 'cap', 'visor', 'headset', 'bowtie', 'toolbelt', 'satchel', 'scarf', 'badge', 'tablet', 'wrench', 'mug'];

// 

