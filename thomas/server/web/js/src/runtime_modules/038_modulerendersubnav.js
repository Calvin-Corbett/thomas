// Extracted from part-020.js
// From modulerendersubnav

            <em>${escapeHtml(safeString(cardRaw?.meta) || '')}</em>
        `;
        frag.appendChild(card);
    });
    moduleFocusStrip.appendChild(frag);
}

function moduleRenderSubnav(modeRaw) {
    if (!moduleSubnavRow || !moduleSubnavList) return;
    const mode = MODULE_NAV_MODE_SET.has(modeRaw) ? modeRaw : 'dashboard';
    const state = moduleEnsureRuntime();