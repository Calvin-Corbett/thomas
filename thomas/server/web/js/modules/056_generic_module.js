// Extracted from part-029.js
// Generic module content

    shell.innerHTML = `
        <section class="module-wb-stage-card"><div class="module-wb-stage-head"><span class="module-wb-stage-title">Grid</span><span class="module-wb-stage-meta" data-game-status></span></div><div class="module-wb-tool-group" data-game-brushes></div><div class="module-wb-toolbar-actions"><label class="module-wb-inline-field">W <input type="number" min="8" max="64" data-game-size="width" value="${wb.gridWidth}" /></label><label class="module-wb-inline-field">H <input type="number" min="6" max="40" data-game-size="height" value="${wb.gridHeight}" /></label><button type="button" class="module-item-btn" data-game-action="resize">Resize Grid</button></div><div class="module-wb-game-grid" data-game-grid></div><div class="module-wb-inspector-actions"><button type="button" class="module-item-btn" data-game-action="check">Path Check</button><button type="button" class="module-item-btn" data-game-action="clear">Clear</button><button type="button" class="module-item-btn" data-game-action="export">Export</button></div></section>
        <aside class="module-wb-inspector-card"><h4>Metrics</h4><div class="module-wb-metrics" data-game-metrics></div><h4>Logs</h4><div class="module-wb-log-list" data-game-logs></div></aside>
        ${moduleWorkbenchRenderOssStack('game_studio')}
    `;
    container.appendChild(shell);
