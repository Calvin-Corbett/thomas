// Extracted from part-011.js
// From officechance

    }
    return hash >>> 0;
}

function officeChance(probability) {
    return Math.random() < probability;
}

function officeAgentTintFromColor(colorRaw) {
    if (!/^#[0-9a-f]{6}$/i.test(safeString(colorRaw))) return 'blue';
    const rgb = officeHexToRgb(colorRaw);
    const { r, g, b } = rgb;
    if (r > 210 && b > 190 && g < 185) return 'pink';
    if (r > 188 && g > 150 && b < 130) return 'orange';
    if (r > 180 && g > 180 && b > 210) return 'purple';
    if (r > 210 && g > 205 && b < 150) return 'yellow';
    if (g >= r && g >= b) return 'green';
    return 'blue';
}

function officeApplyDefaultAgentStyleDiversification(agents, prefsRaw) {
    if (!Array.isArray(agents) || !agents.length) return;
    if (prefsRaw && typeof prefsRaw === 'object' && Object.keys(prefsRaw).length > 0) {
        return;
    }