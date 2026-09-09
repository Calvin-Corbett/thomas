/** Natural-language office command rules. */

const OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES = Object.freeze([
    {
        id: 'coke',
        action: 'drink',
        propLabel: 'Coke',
        types: ['vending_machine', 'soda_crate', 'fridge'],
        interactions: ['vend', 'drink'],
        terms: ['coke', 'cola', 'soda', 'pop', 'vending', 'vending machine', 'coke machine', 'soda machine', 'drink machine'],
    },
    {
        id: 'coffee',
        action: 'drink',
        propLabel: 'coffee',
        types: ['coffee_bar', 'tea_station', 'water_cooler', 'fridge'],
        interactions: ['drink'],
        terms: ['coffee', 'tea', 'water', 'water cooler', 'drink station', 'coffee bar'],
    },
    {
        id: 'food',
        action: 'food',
        propLabel: 'snack',
        types: ['kitchen_island', 'fridge', 'microwave', 'snack_shelf', 'recipe_counter', 'snack_table'],
        interactions: ['food'],
        terms: ['food', 'snack', 'eat', 'recipe', 'cook', 'microwave', 'fridge', 'kitchen island', 'snack shelf', 'snack table'],
    },
    {
        id: 'seat',
        action: 'sit',
        propLabel: '',
        types: ['couch', 'loveseat', 'chair', 'meeting_chair', 'lounge_chair', 'bean_bag', 'bench', 'stool', 'ottoman'],
        interactions: ['sit'],
        terms: ['sit', 'seat', 'chair', 'couch', 'sofa', 'loveseat', 'lounge chair', 'bean bag', 'bench', 'stool'],
    },
    {
        id: 'work',
        action: 'work',
        propLabel: '</>',
        types: ['workstation', 'desk', 'standing_desk', 'code_terminal', 'dual_monitor', 'laptop', 'server_console', 'lab_bench'],
        interactions: ['work', 'monitor', 'tools'],
        terms: ['work', 'desk', 'computer', 'workstation', 'terminal', 'laptop', 'monitor', 'code', 'coding', 'build', 'debug', 'lab bench'],
    },
    {
        id: 'meeting',
        action: 'work',
        propLabel: 'meet',
        types: ['conference_table', 'round_table', 'whiteboard', 'kanban_board'],
        interactions: ['meet', 'present', 'plan'],
        terms: ['meeting', 'meet', 'sync', 'conference', 'conference table', 'round table', 'team table'],
    },
    {
        id: 'focus',
        action: 'work',
        propLabel: 'focus',
        types: ['focus_pod', 'standing_desk', 'desk', 'task_lamp'],
        interactions: ['focus', 'work'],
        terms: ['focus', 'focus pod', 'deep work', 'quiet pod', 'quiet room', 'concentrate', 'concentration'],
    },
    {
        id: 'print',
        action: 'print',
        propLabel: 'print',
        types: ['printer', 'copier', 'filing_cabinet', 'mail_sorter', 'mail_cart'],
        interactions: ['print', 'archive', 'sort'],
        terms: ['print', 'printer', 'copy', 'copier', 'file', 'filing cabinet', 'mail', 'mail sorter', 'mail cart'],
    },
    {
        id: 'support',
        action: 'work',
        propLabel: 'help',
        types: ['ticket_kiosk', 'dispatch_board', 'phone_booth', 'mail_sorter', 'printer', 'copier', 'desk'],
        interactions: ['dispatch', 'sort', 'print', 'work'],
        terms: ['support', 'ticket', 'ticket kiosk', 'help desk', 'customer', 'triage', 'dispatch board', 'phone booth', 'call'],
    },
    {
        id: 'charge',
        action: 'charge',
        propLabel: 'charge',
        types: ['charging_dock'],
        interactions: ['charge'],
        terms: ['charge', 'charging', 'charging dock', 'dock'],
    },
    {
        id: 'planning',
        action: 'work',
        propLabel: 'map',
        types: ['whiteboard', 'kanban_board', 'blueprint_table', 'sticky_note_wall', 'conference_table'],
        interactions: ['present', 'plan', 'meet'],
        terms: ['whiteboard', 'board', 'kanban', 'plan', 'planning', 'strategy', 'blueprint', 'conference table'],
    },
    {
        id: 'research',
        action: 'research',
        propLabel: 'doc',
        types: ['bookshelf', 'research_terminal', 'map_table', 'microscope', 'sample_tray', 'pinboard', 'data_wall'],
        interactions: ['research', 'archive'],
        terms: ['research', 'book', 'bookshelf', 'source', 'docs', 'document', 'microscope', 'map table', 'sample'],
    },
    {
        id: 'design',
        action: 'work',
        propLabel: 'ui',
        types: ['drafting_table', 'vr_headset', 'pinboard', 'whiteboard', 'side_table', 'monitor_stand'],
        interactions: ['design', 'present', 'decor'],
        terms: ['design', 'ui', 'ux', 'visual', 'drafting table', 'prototype', 'vr headset', 'mockup'],
    },
    {
        id: 'ops',
        action: 'monitor',
        propLabel: 'ops',
        types: ['server_rack', 'security_console', 'server_console', 'network_switch', 'router_node', 'firewall_box', 'power_panel', 'data_wall'],
        interactions: ['monitor', 'network'],
        terms: ['server', 'server rack', 'security console', 'console', 'network', 'router', 'firewall', 'power panel', 'ops', 'monitoring'],
    },
    {
        id: 'studio',
        action: 'record',
        propLabel: 'rec',
        types: ['camera_tripod', 'microphone', 'podcast_desk', 'sound_mixer', 'green_screen', 'light_panel', 'camera_case', 'prop_shelf'],
        interactions: ['record', 'content'],
        terms: ['camera', 'record', 'recording', 'microphone', 'mic', 'podcast', 'sound mixer', 'green screen', 'light panel', 'prop shelf'],
    },
    {
        id: 'game',
        action: 'play',
        propLabel: 'game',
        types: ['arcade_cabinet', 'game_console'],
        interactions: ['play'],
        terms: ['game', 'arcade', 'console', 'play'],
    },
]);

const OFFICE_DRAFT_AGENT_COMMAND_ROOM_ALIASES = Object.freeze({
    'room-planning': ['strategy room', 'planning room', 'planning hub', 'strategy', 'roadmap room', 'plan room'],
    'room-engineering': ['software lab', 'engineering', 'engineer room', 'code room', 'coding room', 'build room', 'debug room', 'lab'],
    'room-research': ['research bay', 'research room', 'library', 'docs room', 'source room'],
    'room-design': ['design loft', 'design room', 'ui room', 'ux room', 'product room', 'visual room'],
    'room-content': ['content studio', 'content room', 'studio', 'video room', 'media room'],
    'room-ops': ['ops command', 'ops room', 'operations room', 'deploy room', 'monitoring room', 'server room'],
    'room-support': ['support desk', 'support room', 'ticket room', 'customer room', 'help desk'],
    'room-coffee': ['cafeteria', 'cafe', 'coffee room', 'kitchen', 'break kitchen', 'vending room', 'coke room', 'snack room'],
    'room-break': ['lounge', 'break room', 'relax room', 'couch room', 'hangout room'],
    'room-pods': ['focus pods', 'focus room', 'pod room', 'deep work room', 'quiet room'],
    'room-lobby': ['lobby', 'main lobby', 'front desk', 'reception'],
});

function officeDraftNormalizeAgentCommandText(textRaw) {
    const text = safeString(textRaw)
        .toLowerCase()
        .replace(/['`]/g, '')
        .replace(/[^a-z0-9#]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    return text ? ` ${text} ` : '';
}

function officeDraftAgentCommandHasTerm(commandText, termRaw) {
    const term = officeDraftNormalizeAgentCommandText(termRaw).trim();
    if (!commandText || !term) return false;
    return commandText.includes(` ${term} `);
}

function officeDraftAgentCommandVerbPresent(commandText) {
    return /\b(go|walk|move|head|enter|visit|navigate|use|grab|get|fetch|take|bring|drink|sit|stand|work|focus|play|find|make|cook|eat|snack|print|copy|file|ship|sort|charge|monitor|check|record|film|shoot|read|research|inspect|look|open|join|meet|call|help|triage|dispatch|support)\b/.test(commandText);
}

function officeDraftAgentCommandRuleScore(rule, commandText) {
    let score = 0;
    (Array.isArray(rule?.terms) ? rule.terms : []).forEach((termRaw) => {
        const term = officeDraftNormalizeAgentCommandText(termRaw).trim();
        if (!term || !officeDraftAgentCommandHasTerm(commandText, term)) return;
        score += 100 + Math.min(60, term.length * 3);
    });
    return score;
}

function officeDraftAgentCommandRuleForText(commandText) {
    let best = null;
    OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES.forEach((rule, index) => {
        const score = officeDraftAgentCommandRuleScore(rule, commandText);
        if (score <= 0) return;
        if (!best || score > best.score || (score === best.score && index < best.index)) {
            best = { rule, score, index };
        }
    });
    return best?.rule || null;
}


