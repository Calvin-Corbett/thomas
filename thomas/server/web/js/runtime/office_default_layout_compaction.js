/** Default-room compaction rules and asset overrides. */

const OFFICE_DRAFT_DEFAULT_LAYOUT_OFFSET_SCALE = 0.74;
const OFFICE_DRAFT_DEFAULT_ROOM_SCALE_BY_ID = Object.freeze({
    'planning-hub': { scaleX: 0.66, scaleY: 0.64, minWidth: 900, minHeight: 680, offsetScale: 0.68 },
    'software-lab': { scaleX: 0.64, scaleY: 0.62, minWidth: 1180, minHeight: 780, offsetScale: 0.7 },
    'research-bay': { scaleX: 0.61, scaleY: 0.6, minWidth: 860, minHeight: 650, offsetScale: 0.66 },
    'design-loft': { scaleX: 0.6, scaleY: 0.61, minWidth: 800, minHeight: 660, offsetScale: 0.66 },
    'content-studio': { scaleX: 0.62, scaleY: 0.6, minWidth: 860, minHeight: 680, offsetScale: 0.68 },
    'ops-command': { scaleX: 0.62, scaleY: 0.6, minWidth: 900, minHeight: 700, offsetScale: 0.68 },
    'support-desk': { scaleX: 0.6, scaleY: 0.6, minWidth: 900, minHeight: 680, offsetScale: 0.64 },
    cafeteria: { scaleX: 0.62, scaleY: 0.58, minWidth: 1040, minHeight: 760, offsetScale: 0.7 },
    lounge: { scaleX: 0.6, scaleY: 0.58, minWidth: 960, minHeight: 690, offsetScale: 0.68 },
    'focus-pods': { scaleX: 0.58, scaleY: 0.58, minWidth: 820, minHeight: 660, offsetScale: 0.66 },
    lobby: { scaleX: 0.58, scaleY: 0.58, minWidth: 840, minHeight: 560, offsetScale: 0.76 },
});

function officeDraftCompactDefaultAsset(asset, scaleX, scaleY, roomWidth, roomHeight) {
    const dimensions = officeDraftAssetDimensions(asset?.type, asset?.scale);
    const margin = 48;
    const maxX = Math.max(margin, Number(roomWidth) - Number(dimensions.width || 0) - margin);
    const maxY = Math.max(margin, Number(roomHeight) - Number(dimensions.height || 0) - margin);
    return {
        ...asset,
        x: Math.round(Math.min(maxX, Math.max(margin, (Number(asset?.x) || 0) * scaleX))),
        y: Math.round(Math.min(maxY, Math.max(margin, (Number(asset?.y) || 0) * scaleY))),
    };
}

function officeDraftCompactDefaultSpace(space, options = {}) {
    const scaleX = Math.max(0.56, Math.min(1, Number(options.scaleX || options.scale) || 1));
    const scaleY = Math.max(0.56, Math.min(1, Number(options.scaleY || options.scale) || scaleX));
    const minWidth = Math.max(720, Math.min(1500, Number(options.minWidth) || 880));
    const minHeight = Math.max(520, Math.min(1100, Number(options.minHeight) || 660));
    const width = Math.max(minWidth, Math.round((Number(space?.width) || 0) * scaleX));
    const height = Math.max(minHeight, Math.round((Number(space?.height) || 0) * scaleY));
    const robotInset = 72;
    const assets = Array.isArray(space?.assets)
        ? space.assets.map((asset) => officeDraftCompactDefaultAsset(asset, scaleX, scaleY, width, height))
        : [];
    return {
        ...space,
        width,
        height,
        robotX: Math.round(Math.min(width - robotInset, Math.max(robotInset, (Number(space?.robotX) || 0) * scaleX))),
        robotY: Math.round(Math.min(height - robotInset, Math.max(robotInset, (Number(space?.robotY) || 0) * scaleY))),
        assets,
    };
}

function officeDraftCompactDefaultLayoutSpaces(spacesRaw) {
    const spaces = Array.isArray(spacesRaw) ? spacesRaw : [];
    const center = OFFICE_DRAFT_MAP_SIZE / 2;
    return spaces.map((space) => {
        const scale = OFFICE_DRAFT_DEFAULT_ROOM_SCALE_BY_ID[safeString(space?.id)] || {};
        const compact = officeDraftCompactDefaultSpace(space, scale);
        const offsetScale = Math.max(0.62, Math.min(1, Number(scale.offsetScale) || OFFICE_DRAFT_DEFAULT_LAYOUT_OFFSET_SCALE));
        const previousCenterX = (Number(space?.x) || 0) + ((Number(space?.width) || 0) / 2);
        const previousCenterY = (Number(space?.y) || 0) + ((Number(space?.height) || 0) / 2);
        const nextCenterX = center + ((previousCenterX - center) * offsetScale);
        const nextCenterY = center + ((previousCenterY - center) * offsetScale);
        return {
            ...compact,
            x: Math.round(nextCenterX - (compact.width / 2)),
            y: Math.round(nextCenterY - (compact.height / 2)),
        };
    });
}

const OFFICE_DRAFT_DEFAULT_UPRIGHT_ASSET_TYPES = new Set([
    'bean_bag',
    'bench',
    'chair',
    'couch',
    'lounge_chair',
    'loveseat',
    'meeting_chair',
    'ottoman',
    'stool',
]);

const OFFICE_DRAFT_DEFAULT_LAYERED_ASSET_TYPES = new Set([
    'keyboard_tray',
    'laptop',
    'microphone',
    'carpet',
    'rug',
]);

const OFFICE_DRAFT_DEFAULT_INTERACTION_CLEARANCE_TYPES = new Set([
    'arcade_cabinet',
    'charging_dock',
    'coffee_bar',
    'focus_pod',
    'fridge',
    'printer',
    'ticket_kiosk',
    'vending_machine',
    'water_cooler',
]);

const OFFICE_DRAFT_DEFAULT_LAYOUT_ASSET_OVERRIDES = Object.freeze({
    'planning-hub': Object.freeze({
        'whiteboard-1': { x: 70, y: 82 },
        'round_table-2': { x: 365, y: 315 },
        'chair-3': { x: 300, y: 220 },
        'chair-4': { x: 570, y: 455 },
        'kanban_board-45': { x: 660, y: 88 },
        'blueprint_table-46': { x: 105, y: 455 },
        'sticky_note_wall-120': { x: 690, y: 295 },
        'meeting_chair-220': { x: 435, y: 225 },
        'meeting_chair-221': { x: 460, y: 500 },
        'data_wall-270': { x: 330, y: 92 },
        'tablet_stand-271': { x: 765, y: 510 },
        'bench-272': { x: 620, y: 535 },
        'room_sign-273': { x: 55, y: 545 },
    }),
    'software-lab': Object.freeze({
        'workstation-5': { x: 155, y: 135 },
        'workstation-6': { x: 445, y: 135 },
        'desk-7': { x: 780, y: 170 },
        'server_rack-8': { x: 1010, y: 130 },
        'chair-9': { x: 245, y: 370 },
        'chair-10': { x: 535, y: 370 },
        'lab_bench-49': { x: 715, y: 520 },
        'tool_cart-50': { x: 1010, y: 535 },
        'dual_monitor-122': { x: 590, y: 365 },
        'testing_rig-123': { x: 905, y: 640 },
        'code_terminal-224': { x: 610, y: 570 },
        'storage_locker-226': { x: 1080, y: 390 },
        'rug-258': { x: 380, y: 300 },
        'standing_desk-259': { x: 350, y: 560 },
        'data_wall-260': { x: 845, y: 250 },
        'power_panel-261': { x: 1085, y: 210 },
        'task_lamp-262': { x: 825, y: 565 },
        'divider-263': { x: 930, y: 505 },
    }),
    'research-bay': Object.freeze({
        'bookshelf-11': { x: 80, y: 100 },
        'whiteboard-13': { x: 565, y: 90 },
        'desk-12': { x: 350, y: 365 },
        'research_terminal-125': { x: 410, y: 215 },
        'map_table-126': { x: 170, y: 360 },
        'microscope-228': { x: 640, y: 345 },
        'sample_tray-127': { x: 735, y: 490 },
        'data_wall-230': { x: 300, y: 535 },
        'plant-14': { x: 720, y: 500 },
        'rug-264': { x: 255, y: 285 },
        'tablet_stand-265': { x: 520, y: 510 },
        'archive_box-266': { x: 115, y: 520 },
        'bench-267': { x: 565, y: 565 },
        'task_lamp-268': { x: 230, y: 495 },
        'room_sign-269': { x: 55, y: 535 },
    }),
    'design-loft': Object.freeze({
        'whiteboard-15': { x: 80, y: 80 },
        'pinboard-128': { x: 470, y: 85 },
        'drafting_table-58': { x: 145, y: 385 },
        'round_table-16': { x: 450, y: 405 },
        'chair-17': { x: 375, y: 550 },
        'loveseat-231': { x: 575, y: 360 },
        'side_table-130': { x: 690, y: 535 },
        'monitor_stand-232': { x: 315, y: 245 },
        'tall_plant-233': { x: 710, y: 180 },
        'plant-18': { x: 720, y: 520 },
    }),
    'content-studio': Object.freeze({
        'wall_monitor-65': { x: 105, y: 80 },
        'desk-19': { x: 130, y: 205 },
        'workstation-20': { x: 465, y: 205 },
        'podcast_desk-234': { x: 285, y: 385 },
        'microphone-131': { x: 310, y: 480 },
        'sound_mixer-132': { x: 560, y: 420 },
        'green_screen-133': { x: 650, y: 85 },
        'light_panel-63': { x: 735, y: 255 },
        'camera_tripod-62': { x: 145, y: 465 },
        'couch-21': { x: 435, y: 560 },
        'plant-22': { x: 35, y: 520 },
        'prop_shelf-236': { x: 725, y: 520 },
    }),
    'ops-command': Object.freeze({
        'server_rack-23': { x: 75, y: 115 },
        'server_rack-24': { x: 230, y: 115 },
        'wall_monitor-69': { x: 455, y: 75 },
        'workstation-25': { x: 535, y: 225 },
        'security_console-66': { x: 325, y: 430 },
        'network_switch-134': { x: 140, y: 410 },
        'data_wall-136': { x: 520, y: 390 },
        'server_console-237': { x: 650, y: 520 },
        'firewall_box-238': { x: 260, y: 555 },
        'storage_locker-239': { x: 70, y: 500 },
        'package_station-68': { x: 675, y: 610 },
    }),
    'support-desk': Object.freeze({
        'dispatch_board-139': { x: 215, y: 80 },
        'whiteboard-29': { x: 585, y: 90 },
        'ticket_kiosk-137': { x: 765, y: 128 },
        'phone_booth-138': { x: 50, y: 220 },
        'desk-27': { x: 250, y: 260 },
        'laptop-243': { x: 315, y: 296 },
        'chair-28': { x: 335, y: 430 },
        'printer-71': { x: 575, y: 310 },
        'copier-240': { x: 650, y: 450 },
        'bookshelf-30': { x: 715, y: 445 },
        'mail_sorter-70': { x: 80, y: 500 },
        'mail_cart-242': { x: 245, y: 565 },
        'shredder-241': { x: 455, y: 570 },
        'filing_cabinet-72': { x: 520, y: 520 },
        'floor_sign-73': { x: 740, y: 315 },
    }),
    cafeteria: Object.freeze({
        'vending_machine-31': { x: 70, y: 155 },
        'coffee_bar-32': { x: 325, y: 150 },
        'microwave-76': { x: 470, y: 285 },
        'fridge-75': { x: 850, y: 165 },
        'water_cooler-77': { x: 920, y: 405 },
        'kitchen_island-74': { x: 220, y: 385 },
        'recipe_counter-79': { x: 105, y: 560 },
        'round_table-33': { x: 565, y: 420 },
        'chair-34': { x: 500, y: 565 },
        'chair-35': { x: 745, y: 390 },
        'stool-244': { x: 360, y: 530 },
        'stool-245': { x: 445, y: 500 },
        'stool-246': { x: 300, y: 330 },
        'snack_shelf-78': { x: 760, y: 555 },
        'snack_table-142': { x: 695, y: 310 },
        'soda_crate-140': { x: 115, y: 365 },
        'tea_station-141': { x: 610, y: 270 },
        'trash_bin-247': { x: 935, y: 590 },
    }),
    lounge: Object.freeze({
        'coffee_bar-36': { x: 110, y: 125 },
        'trophy_shelf-82': { x: 375, y: 125 },
        'arcade_cabinet-81': { x: 675, y: 190 },
        'game_console-144': { x: 715, y: 330 },
        'loveseat-248': { x: 585, y: 165 },
        'couch-1': { x: 260, y: 385 },
        'couch-2': { x: 630, y: 410 },
        'ottoman-143': { x: 490, y: 355 },
        'side_table-249': { x: 555, y: 310 },
        'lounge_chair-145': { x: 125, y: 420 },
        'bean_bag-80': { x: 760, y: 385 },
        'floor_lamp-83': { x: 840, y: 485 },
        'plant-37': { x: 785, y: 510 },
        'planter_box-251': { x: 140, y: 555 },
        'round_table-274': { x: 455, y: 405 },
        'tablet_stand-275': { x: 715, y: 505 },
        'bench-276': { x: 300, y: 540 },
    }),
    'focus-pods': Object.freeze({
        'focus_pod-38': { x: 115, y: 150 },
        'focus_pod-39': { x: 350, y: 150 },
        'focus_pod-40': { x: 585, y: 150 },
        'phone_booth-146': { x: 670, y: 390 },
        'divider-87': { x: 400, y: 425 },
        'task_lamp-147': { x: 295, y: 470 },
        'charging_dock-88': { x: 560, y: 500 },
        'storage_locker-252': { x: 40, y: 430 },
        'planter_box-253': { x: 250, y: 550 },
    }),
    lobby: Object.freeze({
        'floor_sign-90': { x: 670, y: 210 },
        'coat_rack-149': { x: 780, y: 250 },
        'bench-150': { x: 660, y: 110 },
        'loveseat-255': { x: 300, y: 230 },
        'planter_box-256': { x: 710, y: 390 },
    }),
});


