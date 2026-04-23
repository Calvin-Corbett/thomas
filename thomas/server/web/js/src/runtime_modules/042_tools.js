// Extracted from part-022.js
// From tools

                <button type="button" class="module-item-btn" data-lab-action="export">Export</button>
            </div>
        </div>
        <div class="module-wb-main-grid module-wb-main-grid-lab3d">
            <section class="module-wb-stage-card">
                <div class="module-wb-stage-head"><span class="module-wb-stage-title">CAD Surface</span><span class="module-wb-stage-meta" data-lab-status></span></div>
                <canvas class="module-wb-canvas-lab3d" data-lab-canvas width="${escapeHtml(String(wb.canvasWidth))}" height="${escapeHtml(String(wb.canvasHeight))}"></canvas>
                <p class="module-wb-hint">Use Select to move. Other tools draw shapes.</p>
            </section>
            <aside class="module-wb-inspector-card" data-lab-inspector></aside>
        </div>
    `;
    container.appendChild(shell);

    const tools = [
        { id: 'select', icon: 'ph-cursor-click', label: 'Select' },
        { id: 'rect', icon: 'ph-rectangle', label: 'Rect' },
        { id: 'circle', icon: 'ph-circle', label: 'Circle' },
        { id: 'line', icon: 'ph-line-segment', label: 'Line' },