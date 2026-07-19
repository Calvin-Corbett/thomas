/** Command-to-room and command-to-asset targeting. */

function officeDraftAssetMatchesAgentCommandRule(asset, rule) {
    if (!asset || !rule) return false;
    const type = safeString(asset?.type);
    const interaction = safeString(OFFICE_DRAFT_ASSET_LIBRARY[type]?.interaction);
    return (Array.isArray(rule.types) && rule.types.includes(type))
        || (Array.isArray(rule.interactions) && rule.interactions.includes(interaction));
}

function officeDraftInferCommandActionFromInteraction(interactionRaw) {
    const interaction = safeString(interactionRaw);
    return {
        archive: 'print',
        charge: 'charge',
        content: 'record',
        decor: 'move',
        design: 'work',
        dispatch: 'work',
        drink: 'drink',
        focus: 'work',
        food: 'food',
        meet: 'work',
        monitor: 'monitor',
        network: 'monitor',
        plan: 'work',
        play: 'play',
        present: 'work',
        print: 'print',
        record: 'record',
        research: 'research',
        sit: 'sit',
        sort: 'print',
        tools: 'work',
        vend: 'drink',
        work: 'work',
    }[interaction] || 'move';
}

function officeDraftCommandContainsAnyTerm(commandText, termsRaw = []) {
    return (Array.isArray(termsRaw) ? termsRaw : []).some((term) => officeDraftAgentCommandHasTerm(commandText, term));
}

function officeDraftCommandAssetTerms(asset) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const terms = [
        safeString(descriptor?.label),
        type.replace(/_/g, ' '),
        safeString(descriptor?.category),
        safeString(descriptor?.interaction),
    ];
    const aliases = {
        arcade_cabinet: ['arcade machine'],
        coffee_bar: ['coffee counter'],
        conference_table: ['meeting table'],
        copier: ['copy machine'],
        camera_tripod: ['camera', 'video camera'],
        data_wall: ['dashboard wall', 'metrics wall'],
        dispatch_board: ['ticket board', 'support board'],
        focus_pod: ['pod', 'quiet pod', 'deep work pod', 'focus booth'],
        game_console: ['game system'],
        green_screen: ['backdrop', 'recording backdrop'],
        kitchen_island: ['kitchen counter'],
        lab_bench: ['test bench'],
        loveseat: ['small couch', 'sofa'],
        map_table: ['research table'],
        microphone: ['mic', 'recording mic'],
        microwave: ['microwave oven'],
        monitor_stand: ['monitor'],
        network_switch: ['network box', 'switch'],
        package_station: ['package counter', 'shipping station'],
        phone_booth: ['phone room', 'call booth'],
        podcast_desk: ['recording desk'],
        reception_counter: ['front desk', 'reception desk'],
        recipe_counter: ['recipe station'],
        research_terminal: ['research computer'],
        security_console: ['security desk'],
        snack_shelf: ['snacks', 'snack rack'],
        soda_crate: ['coke crate', 'soda box'],
        standing_desk: ['standing table'],
        sticky_note_wall: ['sticky notes', 'notes wall'],
        tablet_stand: ['tablet'],
        testing_rig: ['test rig', 'qa rig'],
        ticket_kiosk: ['ticket terminal', 'ticket station'],
        vending_machine: ['coke machine', 'soda machine', 'drink machine'],
        wall_monitor: ['screen', 'display'],
        water_cooler: ['water station'],
        whiteboard: ['board'],
        workstation: ['computer', 'monitor', 'coding station'],
    };
    (aliases[type] || []).forEach((term) => terms.push(term));
    return [...new Set(terms.map((term) => safeString(term)).filter(Boolean))];
}

function officeDraftAssetMatchesCommandText(asset, commandText) {
    return officeDraftCommandAssetTerms(asset).some((term) => officeDraftAgentCommandHasTerm(commandText, term));
}

function officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch = false) {
    const type = safeString(asset?.type);
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
    const typeIndex = Array.isArray(rule?.types) ? rule.types.indexOf(type) : -1;
    let score = 800 - (Math.max(0, Number(spaceIndex) || 0) * 24);
    if (typeIndex >= 0) score += Math.max(0, 220 - (typeIndex * 26));
    if (officeDraftAgentCommandHasTerm(commandText, safeString(descriptor?.label))) score += 190;
    if (officeDraftAgentCommandHasTerm(commandText, type.replace(/_/g, ' '))) score += 150;
    if (officeDraftAgentCommandHasTerm(commandText, safeString(space?.name))) score += 60;
    if (officeDraftCommandContainsAnyTerm(commandText, officeDraftCommandRoomAliases(space))) score += 120;
    if (officeDraftCommandContainsAnyTerm(commandText, officeDraftCommandAssetTerms(asset))) score += 90;
    if (labelMatch) score += 360;
    return score;
}

function officeDraftUniqueCommandSpaces(spacesRaw) {
    const spaces = [];
    const seen = new Set();
    (Array.isArray(spacesRaw) ? spacesRaw : []).forEach((space) => {
        const spaceId = safeString(space?.id);
        if (!spaceId || seen.has(spaceId)) return;
        seen.add(spaceId);
        spaces.push(space);
    });
    return spaces;
}

function officeDraftCommandRoomAliases(space) {
    const roomId = officeDraftNormalizeRoomId(space?.roomId, space?.id);
    const room = officeRoomById(roomId);
    const terms = [
        safeString(space?.name),
        safeString(space?.id).replace(/-/g, ' '),
        roomId.replace(/^room-/, '').replace(/-/g, ' '),
        safeString(room?.label),
        safeString(room?.theme),
    ];
    (OFFICE_DRAFT_AGENT_COMMAND_ROOM_ALIASES[roomId] || []).forEach((term) => terms.push(term));
    return terms.filter(Boolean);
}

function officeDraftFindCommandTargetRoom(commandText, agent) {
    const state = officeEnsureDraftMapState();
    const spaces = Array.isArray(state?.spaces) ? state.spaces : [];
    if (!spaces.length) return null;
    if (officeDraftAgentCommandHasTerm(commandText, 'this room')
        || officeDraftAgentCommandHasTerm(commandText, 'current room')
        || officeDraftAgentCommandHasTerm(commandText, 'here')) {
        const selected = officeDraftSpaceForAgent(agent) || officeDraftFindSpace(state.selectedSpaceId);
        if (selected) return { space: selected, label: safeString(selected.name || 'this room'), score: 1000 };
    }
    let best = null;
    spaces.forEach((space) => {
        let score = 0;
        officeDraftCommandRoomAliases(space).forEach((term) => {
            if (!officeDraftAgentCommandHasTerm(commandText, term)) return;
            score = Math.max(score, 120 + Math.min(80, term.length * 2));
        });
        if (score <= 0) return;
        if (!best || score > best.score) {
            best = { space, label: safeString(space?.name || officeRoomById(officeDraftNormalizeRoomId(space?.roomId, space?.id))?.label), score };
        }
    });
    return best;
}

function officeDraftFindCommandTargetAsset(commandText, agent, roomMatch = null) {
    const rule = officeDraftAgentCommandRuleForText(commandText);
    const state = officeEnsureDraftMapState();
    const selectedSpace = officeDraftFindSpace(state.selectedSpaceId);
    const currentSpace = officeDraftSpaceForAgent(agent);
    const spaces = officeDraftUniqueCommandSpaces([
        roomMatch?.space,
        selectedSpace,
        currentSpace,
        ...(Array.isArray(state?.spaces) ? state.spaces : []),
    ]);
    let best = null;
    spaces.forEach((space, spaceIndex) => {
        (Array.isArray(space?.assets) ? space.assets : []).forEach((asset) => {
            const explicitMatch = rule && officeDraftAssetMatchesAgentCommandRule(asset, rule);
            const labelMatch = officeDraftAssetMatchesCommandText(asset, commandText);
            if (!explicitMatch && !labelMatch) return;
            const type = safeString(asset?.type);
            const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[type] || {};
            const interaction = safeString(descriptor?.interaction);
            const action = safeString(rule?.action) || officeDraftInferCommandActionFromInteraction(interaction);
            const score = officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch);
            if (!best || score > best.score) {
                best = {
                    asset,
                    space,
                    rule,
                    action: safeString(action || 'move'),
                    propLabel: safeString(rule?.propLabel),
                    score,
                };
            }
        });
    });
    return best;
}


