// Extracted from part-013.js
// From regions

        '.obddbo.',
        '.oo..oo.',
        '........',
    ], spritePalette);
    stampSprite(3, 4, [
        '........',
        '.oooooo.',
        '.obppbo.',
        '.ocddco.',
        '.ocddco.',
        '.obppbo.',
        '.oooooo.',
        '........',
    ], spritePalette);
    stampSprite(4, 4, [
        '........',
        '...oo...',
        '..obbo..',
        '.obddbo.',
        '.obddbo.',
        '..obbo..',
        '...oo...',
        '........',
    ], spritePalette);
    stampSprite(5, 4, [
        '........',
        '.oooooo.',
        '.offffo.',
        '.ofggfo.',
        '.ofggfo.',
        '.offffo.',
        '.oooooo.',
        '........',
    ], spritePalette);

    const regions = {
        floor_neutral: { x: 0, y: 0, w: tile, h: tile },
        floor_blue: { x: tile, y: 0, w: tile, h: tile },
        floor_violet: { x: tile * 2, y: 0, w: tile, h: tile },
        floor_green: { x: tile * 3, y: 0, w: tile, h: tile },
        floor_warm: { x: tile * 4, y: 0, w: tile, h: tile },
        floor_lobby: { x: tile * 5, y: 0, w: tile, h: tile },
        corridor_main: { x: 0, y: tile, w: tile, h: tile },
        corridor_alt: { x: tile, y: tile, w: tile, h: tile },
        corridor_polished: { x: tile * 6, y: tile, w: tile, h: tile },
        corridor_soft: { x: tile * 7, y: tile, w: tile, h: tile },
        sprite_desk: { x: 0, y: tile * 3, w: tile, h: tile },
        sprite_monitor: { x: tile, y: tile * 3, w: tile, h: tile },
        sprite_chair: { x: tile * 2, y: tile * 3, w: tile, h: tile },
        sprite_table: { x: tile * 3, y: tile * 3, w: tile, h: tile },
        sprite_sofa: { x: tile * 4, y: tile * 3, w: tile, h: tile },
        sprite_plant: { x: tile * 5, y: tile * 3, w: tile, h: tile },
        sprite_rack: { x: tile * 6, y: tile * 3, w: tile, h: tile },
        sprite_board: { x: tile * 7, y: tile * 3, w: tile, h: tile },
        sprite_coffee: { x: tile * 8, y: tile * 3, w: tile, h: tile },
        sprite_kiosk: { x: tile * 9, y: tile * 3, w: tile, h: tile },
        sprite_camera: { x: tile * 10, y: tile * 3, w: tile, h: tile },
        sprite_lamp: { x: tile * 11, y: tile * 3, w: tile, h: tile },
        sprite_window: { x: 0, y: tile * 4, w: tile, h: tile },
        sprite_vending: { x: tile, y: tile * 4, w: tile, h: tile },
        sprite_bench: { x: tile * 2, y: tile * 4, w: tile, h: tile },
        sprite_server: { x: tile * 3, y: tile * 4, w: tile, h: tile },
        sprite_roundtable: { x: tile * 4, y: tile * 4, w: tile, h: tile },
        sprite_planter: { x: tile * 5, y: tile * 4, w: tile, h: tile },
    };

    return { canvas, tile, regions };
}

function officeGetSpriteAtlas() {
    if (officeSpriteAtlasCache) return officeSpriteAtlasCache;
    officeSpriteAtlasCache = officeBuildSpriteAtlas();
    return officeSpriteAtlasCache;
}

function officeRoomThemeFloorSprite(themeRaw) {
    const theme = safeString(themeRaw).toLowerCase();
    if (theme === 'engineering' || theme === 'ops') return 'floor_blue';
    if (theme === 'content' || theme === 'pods' || theme === 'dynamic') return 'floor_violet';
    if (theme === 'research') return 'floor_green';
    if (theme === 'break' || theme === 'coffee') return 'floor_warm';
    if (theme === 'lobby') return 'floor_lobby';
    return 'floor_neutral';
}

function officePaintSpriteFill(ctx, atlas, spriteId, x, y, w, h, tileSize = 20, opacity = 0.34) {
    if (!atlas || !ctx) return;