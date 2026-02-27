// Extracted from part-014.js
// From pillar

            Math.max(2, wall * 0.22),
            'rgba(243, 249, 255, 0.28)',
        );
        officeCanvasBox(
            ctx,
            rect.x + wall,
            rect.y + rect.h - wall - 2,
            Math.max(3, rect.w - (wall * 2)),
            Math.max(2, wall * 0.14),
            'rgba(34, 47, 67, 0.2)',
        );

        const pillar = Math.max(3, Math.round(wall * 0.38));
        officeCanvasRoundedBox(ctx, rect.x + 1, rect.y + 1, pillar, pillar, 2, 'rgba(212, 225, 246, 0.62)');
        officeCanvasRoundedBox(ctx, rect.x + rect.w - pillar - 1, rect.y + 1, pillar, pillar, 2, 'rgba(212, 225, 246, 0.62)');
        officeCanvasRoundedBox(ctx, rect.x + 1, rect.y + rect.h - pillar - 1, pillar, pillar, 2, 'rgba(76, 96, 126, 0.38)');
        officeCanvasRoundedBox(ctx, rect.x + rect.w - pillar - 1, rect.y + rect.h - pillar - 1, pillar, pillar, 2, 'rgba(76, 96, 126, 0.38)');

        // Subtle interior lines for a Gather-style tile feel.
        ctx.strokeStyle = 'rgba(69, 87, 121, 0.3)';
        ctx.lineWidth = 1;
        for (let x = rect.x + wall + tile; x < rect.x + rect.w - wall; x += tile) {
            ctx.beginPath();
            ctx.moveTo(x + 0.5, rect.y + wall);
            ctx.lineTo(x + 0.5, rect.y + rect.h - wall);
            ctx.stroke();
        }
        for (let y = rect.y + wall + tile; y < rect.y + rect.h - wall; y += tile) {
            ctx.beginPath();
            ctx.moveTo(rect.x + wall, y + 0.5);
            ctx.lineTo(rect.x + rect.w - wall, y + 0.5);
            ctx.stroke();
        }

        const doorWidth = Math.max(24, Math.min(56, Math.min(rect.w, rect.h) * 0.24));
        const doorDistances = {
            top: Math.abs(rect.doorY - rect.y),
            bottom: Math.abs(rect.doorY - (rect.y + rect.h)),
            left: Math.abs(rect.doorX - rect.x),
            right: Math.abs(rect.doorX - (rect.x + rect.w)),
        };
        const edge = Object.entries(doorDistances).sort((a, b) => a[1] - b[1])[0]?.[0] || 'bottom';
        const doorAnchor = { x: rect.doorX, y: rect.doorY };
        if (edge === 'top') doorAnchor.y = rect.y;
        if (edge === 'bottom') doorAnchor.y = rect.y + rect.h;
        if (edge === 'left') doorAnchor.x = rect.x;
        if (edge === 'right') doorAnchor.x = rect.x + rect.w;
        const doorDepth = Math.max(7, wall * 1.06);
        const doorRadius = Math.max(3, Math.min(doorWidth, doorDepth) * 0.2);
        const doorTrim = 'rgba(83, 106, 142, 0.78)';
        const doorSill = 'rgba(119, 144, 180, 0.72)';

        if (edge === 'top') {
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth / 2), rect.y - doorDepth + 1, doorWidth, doorDepth + 2, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.42), rect.y - doorDepth + 2, doorWidth * 0.84, Math.max(3, wall * 0.22), Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.46), rect.y + wall - 4, doorWidth * 0.92, Math.max(2, wall * 0.16), Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else if (edge === 'bottom') {
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth / 2), rect.y + rect.h - 1, doorWidth, doorDepth + 1, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.42), rect.y + rect.h + 1, doorWidth * 0.84, Math.max(3, wall * 0.22), Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, doorAnchor.x - (doorWidth * 0.46), rect.y + rect.h - wall - 4, doorWidth * 0.92, Math.max(2, wall * 0.16), Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else if (edge === 'left') {
            officeCanvasRoundedBox(ctx, rect.x - doorDepth + 1, doorAnchor.y - (doorWidth / 2), doorDepth + 2, doorWidth, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, rect.x - doorDepth + 2, doorAnchor.y - (doorWidth * 0.42), Math.max(3, wall * 0.22), doorWidth * 0.84, Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, rect.x + wall - 4, doorAnchor.y - (doorWidth * 0.46), Math.max(2, wall * 0.16), doorWidth * 0.92, Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        } else {
            officeCanvasRoundedBox(ctx, rect.x + rect.w - 1, doorAnchor.y - (doorWidth / 2), doorDepth + 1, doorWidth, doorRadius, corridorFill, doorTrim, 1);
            officeCanvasRoundedBox(ctx, rect.x + rect.w + 1, doorAnchor.y - (doorWidth * 0.42), Math.max(3, wall * 0.22), doorWidth * 0.84, Math.max(2, doorRadius * 0.6), doorSill);
            officeCanvasRoundedBox(ctx, rect.x + rect.w - wall - 4, doorAnchor.y - (doorWidth * 0.46), Math.max(2, wall * 0.16), doorWidth * 0.92, Math.max(1.5, doorRadius * 0.52), 'rgba(54, 72, 102, 0.3)');
        }

        // Draw a connector from each doorway to its hall node so corridors visually align with rooms.
        const hallPx = hallNodePxById.get(safeString(room.hallId));
        if (hallPx) {
            const connectorHalf = Math.max(5, Math.min(12, doorWidth * 0.24));
            const connectorStroke = 'rgba(128, 149, 183, 0.7)';
            const connectorRadius = Math.max(3, connectorHalf * 0.9);
            const drawConnector = (x1, y1, x2, y2) => {
                const dx = x2 - x1;
                const dy = y2 - y1;
                if (Math.hypot(dx, dy) < 0.9) return;
                if (Math.abs(dx) >= Math.abs(dy)) {
                    const minX = Math.min(x1, x2);
                    officeCanvasRoundedBox(
                        ctx,
                        minX,
                        y1 - connectorHalf,
                        Math.max(1.2, Math.abs(dx)),
                        connectorHalf * 2,
                        connectorRadius,
                        corridorFill,
                        connectorStroke,
                        1,
                    );
                } else {
                    const minY = Math.min(y1, y2);
                    officeCanvasRoundedBox(
                        ctx,
                        x1 - connectorHalf,
                        minY,
                        connectorHalf * 2,
                        Math.max(1.2, Math.abs(dy)),
                        connectorRadius,
                        corridorFill,
                        connectorStroke,
                        1,
                    );
                }
            };

            if (edge === 'top' || edge === 'bottom') {
                drawConnector(doorAnchor.x, doorAnchor.y, doorAnchor.x, hallPx.y);
                drawConnector(doorAnchor.x, hallPx.y, hallPx.x, hallPx.y);
            } else {
                drawConnector(doorAnchor.x, doorAnchor.y, hallPx.x, doorAnchor.y);
                drawConnector(hallPx.x, doorAnchor.y, hallPx.x, hallPx.y);
            }

            officeCanvasCircle(
                ctx,
                doorAnchor.x,
                doorAnchor.y,
                Math.max(2.8, connectorHalf * 0.46),
                'rgba(234, 241, 249, 0.98)',
                'rgba(120, 142, 176, 0.72)',
                1,
            );
        }

        officeDrawRoomFurnitureCanvas(ctx, room, {
            x: rect.x + wall + 6,
            y: rect.y + wall + 6,
            w: Math.max(4, rect.w - ((wall + 6) * 2)),
            h: Math.max(4, rect.h - ((wall + 6) * 2)),
        }, palette);
    });

    ctx.restore();
}

function officeRenderScene() {
    if (!officeScene) return;
    /* ── New Virtual Office (iframe-based replacement) ── */
    if (!document.getElementById('virtualOfficeFrame')) {
        officeScene.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;overflow:hidden;';
        const iframe = document.createElement('iframe');
        iframe.id = 'virtualOfficeFrame';
        iframe.src = '/static/virtual_office.html';
        iframe.style.cssText = 'border:none;width:100%;height:100%;display:block;background:#0a0e1a;';
        iframe.setAttribute('allowfullscreen', '');
        wrap.appendChild(iframe);
        officeScene.appendChild(wrap);
        /* Pass agent/room state into iframe when ready */
        iframe.addEventListener('load', () => {
            try {
                if (officeState && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({
                        type: 'thomas-office-state',
                        agents: officeState.agents || [],
                        rooms: officeState.rooms || [],
                    }, '*');
                }
            } catch(e) { /* cross-origin safety */ }
        });
    }
    /* Legacy layers for compatibility (hidden behind iframe) */
    if (officeState) {
        officeState.roomLayerEl = officeState.roomLayerEl || document.createElement('div');
        officeState.agentLayerEl = officeState.agentLayerEl || document.createElement('div');
        officeState.agentElements = officeState.agentElements || new Map();
    }
}

function officeSetEditorOpen(open) {
    if (!officeEditorModal) return;
    const isOpen = Boolean(open);
    officeEditorModal.classList.toggle('hidden', !isOpen);
    officeEditorModal.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
    if (officeWorkspace) {
        officeWorkspace.classList.toggle('editor-open', isOpen);
    }
    if (officeEditorToggleBtn) {
        officeEditorToggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (officeEditorDockBtn) {
        officeEditorDockBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (isOpen) {
        officeSyncCustomizerFields();
        officeBusEmit('editor.opened', { selectedAgentId: officeState?.selectedAgentId || '' });
        if (officeAgentSelect) {
            window.setTimeout(() => {
                officeAgentSelect.focus();
            }, 0);
        }
    } else {
        officeBusEmit('editor.closed', {});
    }
}

function officeSyncCustomizerFields() {
    if (!officeState) return;