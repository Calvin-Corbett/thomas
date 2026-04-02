function officePanForWorldPoint(worldPxX, worldPxY, zoomRaw, metrics = null) {
    if (!officeState) {
        return { panX: 0, panY: 0 };
    }
    const view = metrics || officeViewportMetrics();
    if (!view) {
        return { panX: 0, panY: 0 };
    }
    const zoom = Number.isFinite(zoomRaw) ? zoomRaw : officeState.zoomLevel;
    const renderZoom = officeEffectiveZoom(zoom);
    const rawPanX = (view.wrapWidth / 2) - (worldPxX * renderZoom);
    const rawPanY = (view.wrapHeight / 2) - (worldPxY * renderZoom);
    return officeClampPan(rawPanX, rawPanY, zoom, view);
}

function officeCenterOnWorldPoint(worldPxX, worldPxY) {
    if (!officeState) return;
    const metrics = officeViewportMetrics();
    if (!metrics) return;
    const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    const pan = officePanForWorldPoint(worldPxX, worldPxY, baseZoom, metrics);
    officeState.targetPanX = pan.panX;
    officeState.targetPanY = pan.panY;
}

function officeUpdateFollowUi() {
    if (!officeFollowToggleBtn || !officeState) return;
    const isFollowing = Boolean(safeString(officeState.followAgentId));
    officeFollowToggleBtn.textContent = isFollowing ? 'Follow: On' : 'Follow: Off';
    officeFollowToggleBtn.classList.toggle('active', isFollowing);
}

function officeSetFollowMode(enabled, agentId = '') {
    if (!officeState) return;
    if (!enabled) {
        officeState.followAgentId = '';
        officeUpdateFollowUi();
        return;
    }
    const fallbackId = safeString(agentId) || safeString(officeState.selectedAgentId) || safeString(officeState.agents[0]?.id);
    if (!fallbackId) {
        officeState.followAgentId = '';
        officeUpdateFollowUi();
        return;
    }
    officeState.followAgentId = fallbackId;
    const target = officeGetAgentById(fallbackId);
    if (target) {
        officeCenterOnWorldPoint((target.x / 100) * officeState.mapWidth, (target.y / 100) * officeState.mapHeight);
    }
    officeUpdateFollowUi();
}

function officeTickFollowCamera() {
    if (!officeState) return;
    const followId = safeString(officeState.followAgentId);
    if (!followId) return;
    if (officeState.dragging?.active) return;
    const agent = officeGetAgentById(followId);
    if (!agent || agent.state === 'runaway') return;

    const metrics = officeViewportMetrics();
    if (!metrics) return;
    const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    const pan = officePanForWorldPoint(
        (agent.x / 100) * officeState.mapWidth,
        (agent.y / 100) * officeState.mapHeight,
        baseZoom,
        metrics,
    );
    const currentTargetX = Number.isFinite(officeState.targetPanX) ? officeState.targetPanX : officeState.panX;
    const currentTargetY = Number.isFinite(officeState.targetPanY) ? officeState.targetPanY : officeState.panY;
    officeState.targetPanX = currentTargetX + ((pan.panX - currentTargetX) * 0.22);
    officeState.targetPanY = currentTargetY + ((pan.panY - currentTargetY) * 0.22);
}

function officeRenderMinimap() {
    if (!officeState || !officeMinimapCanvas) return;
    const ctx = officeMinimapCanvas.getContext('2d');
    if (!ctx) return;

    const box = officeMinimapCanvas.getBoundingClientRect();
    const deviceScale = window.devicePixelRatio || 1;
    const targetW = Math.max(100, Math.round(box.width * deviceScale));
    const targetH = Math.max(72, Math.round(box.height * deviceScale));
    if (officeMinimapCanvas.width !== targetW || officeMinimapCanvas.height !== targetH) {
        officeMinimapCanvas.width = targetW;
        officeMinimapCanvas.height = targetH;
    }

    const width = officeMinimapCanvas.width;
    const height = officeMinimapCanvas.height;
    const pad = Math.round(Math.min(width, height) * OFFICE_MINIMAP_PAD_RATIO);
    const mapW = Math.max(1, width - (pad * 2));
    const mapH = Math.max(1, height - (pad * 2));
    const toMiniX = (pct) => pad + ((pct / 100) * mapW);
    const toMiniY = (pct) => pad + ((pct / 100) * mapH);

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#101a2a';
    ctx.fillRect(0, 0, width, height);

    ctx.fillStyle = '#c4d0e2';
    ctx.fillRect(pad, pad, mapW, mapH);
    ctx.strokeStyle = 'rgba(97, 120, 157, 0.86)';
    ctx.lineWidth = Math.max(1, deviceScale);
    ctx.strokeRect(pad + 0.5, pad + 0.5, Math.max(1, mapW - 1), Math.max(1, mapH - 1));

    officeState.corridors.forEach((corridor) => {
        const x = toMiniX(corridor.x);
        const y = toMiniY(corridor.y);
        const w = (corridor.w / 100) * mapW;
        const h = (corridor.h / 100) * mapH;
        ctx.fillStyle = 'rgba(227, 233, 241, 0.95)';
        ctx.fillRect(x, y, w, h);
    });

    officeState.rooms.forEach((room) => {
        const x = toMiniX(room.x);
        const y = toMiniY(room.y);
        const w = (room.w / 100) * mapW;
        const h = (room.h / 100) * mapH;
        const palette = officeRoomThemePalette(room.theme || room.kind);
        ctx.fillStyle = palette.floor;
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = room.dynamic ? 'rgba(152, 124, 73, 0.9)' : 'rgba(88, 105, 134, 0.85)';
        ctx.lineWidth = Math.max(1, deviceScale);
        ctx.strokeRect(x + 0.5, y + 0.5, Math.max(1, w - 1), Math.max(1, h - 1));
    });

    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        const x = toMiniX(agent.x);
        const y = toMiniY(agent.y);
        const radius = Math.max(2.2, Math.min(4.3, 2.2 * deviceScale));
        ctx.fillStyle = safeString(agent.color) || '#9ad8ff';
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (safeString(officeState.followAgentId) === agent.id) {
            ctx.strokeStyle = 'rgba(255, 237, 167, 0.95)';
            ctx.lineWidth = Math.max(1, 1.2 * deviceScale);
            ctx.beginPath();
            ctx.arc(x, y, radius + 2.4, 0, Math.PI * 2);
            ctx.stroke();
        } else if (safeString(officeState.selectedAgentId) === agent.id) {
            ctx.strokeStyle = 'rgba(129, 208, 255, 0.9)';
            ctx.lineWidth = Math.max(1, 1.1 * deviceScale);
            ctx.beginPath();
            ctx.arc(x, y, radius + 1.8, 0, Math.PI * 2);
            ctx.stroke();
        }
    });

    const view = officeViewportMetrics();
    if (!view) return;
    const renderZoom = officeEffectiveZoom(officeState.zoomLevel);
    const viewportX = officeClamp((-officeState.panX) / renderZoom, 0, officeState.mapWidth);
    const viewportY = officeClamp((-officeState.panY) / renderZoom, 0, officeState.mapHeight);
    const viewportW = officeClamp(view.wrapWidth / renderZoom, 1, officeState.mapWidth);
    const viewportH = officeClamp(view.wrapHeight / renderZoom, 1, officeState.mapHeight);
    const vX = pad + ((viewportX / officeState.mapWidth) * mapW);
    const vY = pad + ((viewportY / officeState.mapHeight) * mapH);
    const vW = (viewportW / officeState.mapWidth) * mapW;
    const vH = (viewportH / officeState.mapHeight) * mapH;
    ctx.strokeStyle = 'rgba(125, 196, 255, 0.95)';
    ctx.lineWidth = Math.max(1, 1.25 * deviceScale);
    ctx.strokeRect(vX + 0.5, vY + 0.5, Math.max(1, vW - 1), Math.max(1, vH - 1));
}

function officeMinimapEventToWorld(event) {
    if (!officeMinimapCanvas || !officeState || !event) return null;
    const rect = officeMinimapCanvas.getBoundingClientRect();
    const canvasWidth = Math.max(1, Number(officeMinimapCanvas.width) || rect.width);
    const canvasHeight = Math.max(1, Number(officeMinimapCanvas.height) || rect.height);
    const scaleX = canvasWidth / Math.max(1, rect.width);
    const scaleY = canvasHeight / Math.max(1, rect.height);
    const localX = officeClamp((event.clientX - rect.left) * scaleX, 0, canvasWidth);
    const localY = officeClamp((event.clientY - rect.top) * scaleY, 0, canvasHeight);
    const pad = Math.round(Math.min(canvasWidth, canvasHeight) * OFFICE_MINIMAP_PAD_RATIO);
    const mapW = Math.max(1, canvasWidth - (pad * 2));
    const mapH = Math.max(1, canvasHeight - (pad * 2));
    const relX = officeClamp((localX - pad) / mapW, 0, 1);
    const relY = officeClamp((localY - pad) / mapH, 0, 1);
    return {
        x: relX * officeState.mapWidth,
        y: relY * officeState.mapHeight,
        mapX: relX * 100,
        mapY: relY * 100,
    };
}

function officeSelectAgentNearMapPoint(point) {
    if (!officeState || !point) return null;
    let closest = null;
    let closestDistance = Number.POSITIVE_INFINITY;
    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        const distance = Math.hypot((Number(point.mapX) || 0) - agent.x, (Number(point.mapY) || 0) - agent.y);
        if (distance < closestDistance) {
            closestDistance = distance;
            closest = agent;
        }
    });
    if (!closest || closestDistance > 3.4) return null;
    officeState.selectedAgentId = closest.id;
    officeSyncCustomizerFields();
    return closest;
}

function officePanToMinimapEvent(event) {
    if (!officeState) return;
    const point = officeMinimapEventToWorld(event);
    if (!point) return;
    const selected = officeSelectAgentNearMapPoint(point);
    if (safeString(officeState.followAgentId) && !selected) {
        officeSetFollowMode(false);
    } else if (safeString(officeState.followAgentId) && selected) {
        officeSetFollowMode(true, selected.id);
    }
    officeCenterOnWorldPoint(point.x, point.y);
}

function officeResetViewport({ preserveZoom = false, immediate = true } = {}) {
    if (!officeState) return;
    const metrics = officeViewportMetrics();
    if (!metrics) return;

    const minZoom = officeDynamicMinZoom(metrics);
    let nextZoom = officeState.zoomLevel;
    if (!preserveZoom) {
        const fitX = (metrics.wrapWidth - 24) / officeState.mapWidth;
        const fitY = (metrics.wrapHeight - 24) / officeState.mapHeight;
        nextZoom = officeClamp(Math.min(fitX, fitY), minZoom, OFFICE_ZOOM_MAX);
    } else {
        nextZoom = officeClamp(officeState.zoomLevel, minZoom, OFFICE_ZOOM_MAX);
    }

    const renderZoom = officeEffectiveZoom(nextZoom);
    const scaledW = officeState.mapWidth * renderZoom;
    const scaledH = officeState.mapHeight * renderZoom;
    const nextPanX = (metrics.wrapWidth - scaledW) / 2;
    const nextPanY = (metrics.wrapHeight - scaledH) / 2;

    officeState.targetZoomLevel = nextZoom;
    officeState.targetPanX = nextPanX;
    officeState.targetPanY = nextPanY;
    if (immediate) {
        officeState.zoomLevel = nextZoom;
        officeState.panX = nextPanX;
        officeState.panY = nextPanY;
    }
    officeApplyZoom();
}

function officeSetZoom(nextZoom, { anchorClientX = Number.NaN, anchorClientY = Number.NaN } = {}) {
    if (!officeState) return;
    const metrics = officeViewportMetrics();
    if (!metrics) return;

    const baseZoomRaw = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    const prevZoomRaw = baseZoomRaw;
    const prevZoom = officeEffectiveZoom(baseZoomRaw);
    const basePanX = Number.isFinite(officeState.targetPanX) ? officeState.targetPanX : officeState.panX;
    const basePanY = Number.isFinite(officeState.targetPanY) ? officeState.targetPanY : officeState.panY;
    const minZoom = officeDynamicMinZoom(metrics);
    const clampedZoom = officeClamp(nextZoom, minZoom, OFFICE_ZOOM_MAX);
    if (Math.abs(clampedZoom - prevZoomRaw) < 0.0001) {
        return;
    }

    let anchorX = metrics.wrapWidth / 2;
    let anchorY = metrics.wrapHeight / 2;
    if (Number.isFinite(anchorClientX) && Number.isFinite(anchorClientY)) {
        anchorX = anchorClientX - metrics.wrapRect.left;
        anchorY = anchorClientY - metrics.wrapRect.top;
    }

    const worldX = (anchorX - basePanX) / prevZoom;
    const worldY = (anchorY - basePanY) / prevZoom;
    const renderClampedZoom = officeEffectiveZoom(clampedZoom);
    const nextPanX = anchorX - (worldX * renderClampedZoom);
    const nextPanY = anchorY - (worldY * renderClampedZoom);
    const clampedPan = officeClampPan(nextPanX, nextPanY, clampedZoom, metrics);

    officeState.targetZoomLevel = clampedZoom;
    officeState.targetPanX = clampedPan.panX;
    officeState.targetPanY = clampedPan.panY;
}

function officePanBy(deltaX, deltaY) {
    if (!officeState) return;
    const baseZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    const basePanX = Number.isFinite(officeState.targetPanX) ? officeState.targetPanX : officeState.panX;
    const basePanY = Number.isFinite(officeState.targetPanY) ? officeState.targetPanY : officeState.panY;
    const clamped = officeClampPan(
        basePanX + deltaX,
        basePanY + deltaY,
        baseZoom,
    );
    officeState.targetPanX = clamped.panX;
    officeState.targetPanY = clamped.panY;
    officeState.targetZoomLevel = baseZoom;
    officeState.panX = clamped.panX;
    officeState.panY = clamped.panY;
    officeState.zoomLevel = baseZoom;
    officeApplyZoom();
}

function officeMapDimensionsForRoomCount(roomCount = 0) {
    const dynamicCount = Math.max(0, roomCount - OFFICE_STATIC_ROOMS.length);
    const scale = 1 + Math.min(0.92, dynamicCount * 0.027);
    return {
        width: Math.round(OFFICE_MAP_WIDTH * scale),
        height: Math.round(OFFICE_MAP_HEIGHT * scale),
    };
}

function officeRecalculateMapSize({ preserveZoom = true, rerender = false } = {}) {
    if (!officeState) return;
    const next = officeMapDimensionsForRoomCount(officeState.rooms.length);
    const changed = next.width !== officeState.mapWidth || next.height !== officeState.mapHeight;
    officeState.mapWidth = next.width;
    officeState.mapHeight = next.height;

    if (rerender) {
        officeRenderScene();
    }

    if (changed || rerender) {
        officeResetViewport({ preserveZoom, immediate: true });
    } else {
        officeApplyZoom();
    }
}

function officeTickCamera(dt = 0.016) {
    if (!officeState) return;
    const targetZoom = Number.isFinite(officeState.targetZoomLevel) ? officeState.targetZoomLevel : officeState.zoomLevel;
    const targetPanX = Number.isFinite(officeState.targetPanX) ? officeState.targetPanX : officeState.panX;
    const targetPanY = Number.isFinite(officeState.targetPanY) ? officeState.targetPanY : officeState.panY;

    const dragging = Boolean(officeState.dragging?.active);
    const zoomGap = Math.abs(targetZoom - officeState.zoomLevel);
    const panGap = Math.hypot(targetPanX - officeState.panX, targetPanY - officeState.panY);
    const zoomSmoothing = dragging
        ? 1
        : officeClamp(1 - Math.exp(-dt * (zoomGap > 0.42 ? 17 : 10)), 0.035, 0.2);
    const panSmoothing = dragging
        ? 1
        : officeClamp(1 - Math.exp(-dt * (panGap > 280 ? 18 : 11.5)), 0.06, 0.26);
    const nextZoom = officeState.zoomLevel + ((targetZoom - officeState.zoomLevel) * zoomSmoothing);
    const nextPanX = officeState.panX + ((targetPanX - officeState.panX) * panSmoothing);
    const nextPanY = officeState.panY + ((targetPanY - officeState.panY) * panSmoothing);

    const zoomSettled = Math.abs(targetZoom - nextZoom) < 0.0005;
    const panSettled = Math.abs(targetPanX - nextPanX) < 0.12 && Math.abs(targetPanY - nextPanY) < 0.12;

    officeState.zoomLevel = zoomSettled ? targetZoom : nextZoom;
    officeState.panX = panSettled ? targetPanX : nextPanX;
    officeState.panY = panSettled ? targetPanY : nextPanY;
    officeApplyZoom();
}

function officeUpdateRoomMeta() {
    if (!officeState?.roomLayerEl) return;
    const taskCounts = new Map();
    const occupancyCounts = new Map();

    officeState.tasks.forEach((task) => {
        if (!task || task.status === 'done') return;
        const existing = taskCounts.get(task.roomId) || { active: 0, queued: 0 };
        if (task.status === 'active') existing.active += 1;
        if (task.status === 'queued') existing.queued += 1;
        taskCounts.set(task.roomId, existing);
    });

    officeState.agents.forEach((agent) => {
        if (!agent || agent.state === 'runaway') return;
        const room = officeCurrentRoomForAgent(agent);
        if (!room) return;
        occupancyCounts.set(room.id, (occupancyCounts.get(room.id) || 0) + 1);
    });

    officeState.rooms.forEach((room) => {
        const roomEl = officeState.roomLayerEl.querySelector(`.office-room[data-room-id="${room.id}"]`);
        const metaEl = roomEl?.querySelector('.office-room-meta');
        if (!metaEl) return;
        const taskCount = taskCounts.get(room.id) || { active: 0, queued: 0 };
        const occupancy = occupancyCounts.get(room.id) || 0;
        const hasWork = taskCount.active > 0 || taskCount.queued > 0;

        metaEl.classList.toggle('has-work', hasWork);
        if (hasWork) {
            metaEl.textContent = `${taskCount.active} active | ${taskCount.queued} queued | ${occupancy} in room`;
            return;
        }
        if (occupancy > 0) {
            metaEl.textContent = `${occupancy} in room`;
            return;
        }
        metaEl.textContent = room.meta;
    });
}

function officeRenderTaskList() {
    if (!officeState || !officeTaskList) return;
    officeTaskList.innerHTML = '';
    const previewScoped = Boolean(officeWorkspace?.classList.contains('chat-preview-active'));
    const visibleTasks = previewScoped
        ? officeState.tasks.filter((task) => officeTaskMatchesChatPreview(task))
        : officeState.tasks;
    if (!visibleTasks.length) {
        const empty = document.createElement('div');
        empty.className = 'office-task-item';
        empty.textContent = previewScoped
            ? 'Background workers for this chat will appear here.'
            : 'No tasks yet. Add one below to dispatch your agents.';
        officeTaskList.appendChild(empty);
        return;
    }

    const rows = [...visibleTasks]
        .sort((a, b) => b.createdAt - a.createdAt)
        .slice(0, OFFICE_MAX_TASKS);

    rows.forEach((task) => {
        const item = document.createElement('div');
        item.className = 'office-task-item';

        let statusLine = 'Queued';
        if (task.status === 'active') {
            const agent = officeGetAgentById(task.assignedAgentId);
            statusLine = agent ? `In progress by ${agent.name}` : 'In progress';
        }
        if (task.status === 'done') {
            statusLine = 'Completed';
        }

        item.innerHTML = `
            <strong>${escapeHtml(task.title)}</strong>
            <div class="office-task-meta">${escapeHtml(task.roomLabel)} | ${escapeHtml(statusLine)}</div>
        `;
        officeTaskList.appendChild(item);
    });
}

function officeCreateAgentElement(agent) {
    const el = document.createElement('div');
    el.className = 'office-agent';
    el.dataset.agentId = agent.id;
    el.tabIndex = 0;
    el.innerHTML = `
        <button type="button" class="office-agent-hitbox" aria-label="Activate ${escapeHtml(agent.name)}">
            ${officePixelAgentMarkup()}
        </button>
        <span class="office-agent-label"></span>
        <span class="office-agent-bubble hidden center above"></span>
    `;

    const triggerTap = (event) => {
        event.preventDefault();
        event.stopPropagation();
        officeHandleAgentTap(agent.id);
    };

    const hitbox = el.querySelector('.office-agent-hitbox');
    if (hitbox) {
        hitbox.addEventListener('pointerdown', triggerTap);
    }

    el.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            triggerTap(event);
        }
    });
    return el;
}

function officeRenderAgents(now = performance.now()) {
    if (!officeState?.agentLayerEl) return;
    const selectedId = safeString(officeState.selectedAgentId);
    officeState.agents.forEach((agent) => {
        let el = officeState.agentElements.get(agent.id);
        if (!el) {
            el = officeCreateAgentElement(agent);
            officeState.agentElements.set(agent.id, el);
            officeState.agentLayerEl.appendChild(el);
        }

        el.style.left = `${agent.x.toFixed(2)}%`;
        el.style.top = `${agent.y.toFixed(2)}%`;
        const palette = officeAgentPalette(agent);
        el.style.setProperty('--agent-primary', palette.primary);
        el.style.setProperty('--agent-secondary', palette.secondary);
        el.style.setProperty('--agent-glow', palette.glow);
        el.classList.toggle('is-working', agent.state === 'working');
        el.classList.toggle('is-colliding', now < agent.bumpUntil);
        el.classList.toggle('is-jumping', now < agent.jumpUntil);
        el.classList.toggle('is-selected', agent.id === selectedId);
        el.dataset.state = safeString(agent.state) || 'idle';
        ['idle', 'walking', 'working', 'break', 'yield', 'runaway'].forEach((stateName) => {
            el.classList.toggle(`state-${stateName}`, agent.state === stateName);
        });

        const labelEl = el.querySelector('.office-agent-label');
        if (labelEl && labelEl.textContent !== agent.name) {
            labelEl.textContent = agent.name;
        }
        const hitboxEl = el.querySelector('.office-agent-hitbox');
        if (hitboxEl) {
            hitboxEl.setAttribute('aria-label', `${agent.name} agent`);
        }

        const pixelEl = el.querySelector('.office-pixel-agent');
        if (pixelEl) {
            pixelEl.classList.toggle('facing-left', agent.facing < 0);
            pixelEl.classList.toggle('looking-user', Boolean(agent.speech));
            pixelEl.classList.toggle('is-bonking', now < agent.bumpUntil);
            pixelEl.classList.remove('costume-cap', 'costume-visor', 'costume-headset', 'costume-bowtie');
            if (agent.costume && agent.costume !== 'none') {
                pixelEl.classList.add(`costume-${agent.costume}`);
            }
        }

        const bubbleEl = el.querySelector('.office-agent-bubble');
        const speechText = officeVisibleSpeech(agent, now);
        if (bubbleEl) {
            if (speechText) {
                const anchor = officeBubbleAnchorForAgent(agent, speechText);
                bubbleEl.classList.remove('hidden', 'left', 'center', 'right', 'above', 'below');
                bubbleEl.classList.add(anchor.horizontal);
                bubbleEl.classList.add(anchor.vertical);
                bubbleEl.style.minWidth = `${Math.round(officeClamp(112 + (speechText.length * 2.3), 126, 236))}px`;
                if (bubbleEl.textContent !== speechText) {
                    bubbleEl.textContent = speechText;
                }
            } else {
                bubbleEl.classList.add('hidden');
                bubbleEl.textContent = '';
                bubbleEl.style.minWidth = '';
            }
        }
    });
    officeRenderRosterPanel();
    officeRenderMinimap();
    composerSyncSendButtonState();
}

function initComposerDeepLink() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const game = safeString(params.get('game')).toLowerCase();
        const resolvedGame = (game === 'jetpack' || game === JETPACK_GAME_ID)
            ? JETPACK_GAME_ID
            : ((game === 'dino' || game === DINO_GAME_ID) ? DINO_GAME_ID : game);
        if (resolvedGame !== 'cloud_jump' && resolvedGame !== JETPACK_GAME_ID && resolvedGame !== DINO_GAME_ID) return;
        ensureChatVisible();
        composerSetMode(resolvedGame);
        chatGameOpen(resolvedGame);
    } catch {
        // Ignore malformed URLs and continue with default boot.
    }
}

function officeRoomFurnitureMarkup(room) {
    const theme = safeString(room?.theme || room?.kind).toLowerCase();
    if (theme === 'engineering') {
        return `
            <span class="office-furniture desk a"></span>
            <span class="office-furniture desk b"></span>
            <span class="office-furniture desk c"></span>
            <span class="office-furniture desk d"></span>
            <span class="office-furniture monitor e"></span>
            <span class="office-furniture board f"></span>
        `;
    }
    if (theme === 'content') {
        return `
            <span class="office-furniture desk a"></span>
            <span class="office-furniture desk b"></span>
            <span class="office-furniture camera c"></span>
            <span class="office-furniture light d"></span>
            <span class="office-furniture sofa e"></span>
        `;
    }
    if (theme === 'research') {
        return `
            <span class="office-furniture desk a"></span>
            <span class="office-furniture desk b"></span>
            <span class="office-furniture shelf c"></span>
            <span class="office-furniture board d"></span>
        `;
    }
    if (theme === 'ops') {
        return `
            <span class="office-furniture rack a"></span>
            <span class="office-furniture rack b"></span>
            <span class="office-furniture rack c"></span>
            <span class="office-furniture desk d"></span>
        `;
    }
    if (theme === 'planning' || theme === 'design') {
        return `
            <span class="office-furniture table a"></span>
            <span class="office-furniture chair b"></span>
            <span class="office-furniture chair c"></span>
            <span class="office-furniture board d"></span>
            <span class="office-furniture desk e"></span>
        `;
    }
    if (theme === 'support') {
        return `
            <span class="office-furniture desk a"></span>
            <span class="office-furniture desk b"></span>
            <span class="office-furniture desk c"></span>
            <span class="office-furniture monitor d"></span>
            <span class="office-furniture monitor e"></span>
        `;
    }
    if (theme === 'break' || theme === 'coffee') {
        return `
            <span class="office-furniture table a"></span>
            <span class="office-furniture chair b"></span>
            <span class="office-furniture chair c"></span>
            <span class="office-furniture coffee d"></span>
            <span class="office-furniture sofa e"></span>
            <span class="office-furniture plant f"></span>
        `;
    }
    if (theme === 'lobby') {
        return `
            <span class="office-furniture reception a"></span>
            <span class="office-furniture kiosk b"></span>
            <span class="office-furniture sofa c"></span>
            <span class="office-furniture sofa d"></span>
            <span class="office-furniture plant e"></span>
            <span class="office-furniture plant f"></span>
        `;
    }
    if (theme === 'pods' || theme === 'dynamic') {
        return `
            <span class="office-furniture desk a"></span>
            <span class="office-furniture desk b"></span>
            <span class="office-furniture table c"></span>
            <span class="office-furniture monitor d"></span>
            <span class="office-furniture monitor e"></span>
        `;
    }
    return `
        <span class="office-furniture desk a"></span>
        <span class="office-furniture desk b"></span>
        <span class="office-furniture table c"></span>
    `;
}

function officeRoomThemePalette(themeRaw) {
    const theme = safeString(themeRaw).toLowerCase();
    const base = {
        floor: '#d8e8f8',
        wall: '#3f5f84',
        accent: '#8fb8e4',
        desk: '#628abf',
    };
    if (theme === 'engineering') return { floor: '#c7e5ff', wall: '#1f5b97', accent: '#62a9f0', desk: '#3f83c2' };
    if (theme === 'content') return { floor: '#ecd7ff', wall: '#6f4da7', accent: '#c29aef', desk: '#9076cb' };
    if (theme === 'research') return { floor: '#d7f1e4', wall: '#3a7f65', accent: '#79c9a2', desk: '#5caa89' };
    if (theme === 'ops') return { floor: '#d0e6fa', wall: '#2d638f', accent: '#76b7dd', desk: '#4c87b4' };
    if (theme === 'planning' || theme === 'design' || theme === 'support') {
        return { floor: '#e2dbf7', wall: '#596aa3', accent: '#aab6eb', desk: '#7289c4' };
    }
    if (theme === 'pods' || theme === 'dynamic') {
        return { floor: '#d8e4fa', wall: '#3f6299', accent: '#92b4e8', desk: '#5f86bf' };
    }
    if (theme === 'break') {
        return { floor: '#efe1cf', wall: '#87684a', accent: '#d2b08a', desk: '#b4875e' };
    }
    if (theme === 'coffee') {
        return { floor: '#fae8cf', wall: '#a26635', accent: '#ebb06a', desk: '#ca8643' };
    }
    if (theme === 'lobby') return { floor: '#d8ebff', wall: '#346fa4', accent: '#8fc2ee', desk: '#5f99ca' };
    return base;
}

function officeCanvasBox(ctx, x, y, w, h, fill, stroke = '', lineWidth = 1) {
    ctx.fillStyle = fill;
    ctx.fillRect(x, y, w, h);
    if (stroke) {
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = stroke;
        ctx.strokeRect(x + 0.5, y + 0.5, Math.max(0, w - 1), Math.max(0, h - 1));
    }
}

function officeCanvasRoundedBox(ctx, x, y, w, h, radius, fill, stroke = '', lineWidth = 1) {
    const width = Math.max(0, Number(w) || 0);
    const height = Math.max(0, Number(h) || 0);
    if (width <= 0 || height <= 0) return;
    const r = officeClamp(Number(radius) || 0, 0, Math.min(width, height) / 2);
    const x2 = x + width;
    const y2 = y + height;

    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x2 - r, y);
    ctx.quadraticCurveTo(x2, y, x2, y + r);
    ctx.lineTo(x2, y2 - r);
    ctx.quadraticCurveTo(x2, y2, x2 - r, y2);
    ctx.lineTo(x + r, y2);
    ctx.quadraticCurveTo(x, y2, x, y2 - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();

    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = stroke;
        ctx.stroke();
    }
}

function officeCanvasCircle(ctx, x, y, radius, fill, stroke = '', lineWidth = 1) {
    const r = Math.max(0, Number(radius) || 0);
    if (r <= 0) return;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = stroke;
        ctx.stroke();
    }
}

function officeCanvasLine(ctx, x1, y1, x2, y2, stroke, lineWidth = 1) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
}

function officeBuildSpriteAtlas() {
    const tile = 24;
    const cols = 12;
    const rows = 6;
    const canvas = document.createElement('canvas');
    canvas.width = cols * tile;
    canvas.height = rows * tile;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.imageSmoothingEnabled = false;

    const fillTile = (col, row, base, accent, accentTwo, line = '') => {
        const ox = col * tile;
        const oy = row * tile;
        ctx.fillStyle = base;
        ctx.fillRect(ox, oy, tile, tile);
        for (let y = 0; y < tile; y += 1) {
            for (let x = 0; x < tile; x += 1) {
                if (((x + (y * 2)) % 7) === 0) {
                    ctx.fillStyle = accent;
                    ctx.fillRect(ox + x, oy + y, 1, 1);
                } else if (((x * 3) + y) % 13 === 0) {
                    ctx.fillStyle = accentTwo;
                    ctx.fillRect(ox + x, oy + y, 1, 1);
                }
            }
        }
        if (line) {
            ctx.fillStyle = line;
            ctx.fillRect(ox, oy + (tile / 2) - 1, tile, 1);
            ctx.fillRect(ox + (tile / 2) - 1, oy, 1, tile);
        }
    };

    const stampSprite = (col, row, pixels, palette, scale = 3) => {
        const ox = col * tile;
        const oy = row * tile;
        const rowsRaw = Array.isArray(pixels) ? pixels : [];
        rowsRaw.forEach((lineRaw, rowIndex) => {
            const line = safeString(lineRaw);
            for (let charIndex = 0; charIndex < line.length; charIndex += 1) {
                const code = line.charAt(charIndex);
                const fill = palette?.[code];
                if (!fill) continue;
                ctx.fillStyle = fill;
                ctx.fillRect(
                    ox + (charIndex * scale),
                    oy + (rowIndex * scale),
                    scale,
                    scale,
                );
            }
        });
    };

    fillTile(0, 0, '#e7f1fb', '#d7e6f7', '#c5d8ee', 'rgba(105, 134, 170, 0.36)');
    fillTile(1, 0, '#d7ebff', '#c4ddfb', '#b0cef1', 'rgba(82, 123, 182, 0.34)');
    fillTile(2, 0, '#eadffb', '#dccff4', '#c8bbe8', 'rgba(119, 101, 170, 0.32)');
    fillTile(3, 0, '#d9f0e9', '#c8e3d8', '#b4d3c5', 'rgba(87, 134, 117, 0.32)');
    fillTile(4, 0, '#f6e9d5', '#ebd9bf', '#dfc6a5', 'rgba(146, 110, 67, 0.34)');
    fillTile(5, 0, '#dff0ff', '#cee4f6', '#bbd3eb', 'rgba(86, 126, 173, 0.34)');

    fillTile(0, 1, '#edf5ff', '#deebf8', '#cfdef0', 'rgba(109, 140, 178, 0.36)');
    fillTile(1, 1, '#d8e9ff', '#c7dcf8', '#b4ceec', 'rgba(75, 117, 176, 0.36)');
    fillTile(2, 1, '#e5dcfa', '#d4c8ef', '#c1b2e1', 'rgba(111, 96, 160, 0.34)');
    fillTile(3, 1, '#d5eee6', '#c2e0d2', '#adcfbf', 'rgba(79, 126, 108, 0.34)');
    fillTile(4, 1, '#f3e2cb', '#e7d2b2', '#d8be98', 'rgba(140, 104, 60, 0.34)');
    fillTile(5, 1, '#d8e9fb', '#c5dcf1', '#b1cae6', 'rgba(72, 112, 159, 0.36)');

    fillTile(0, 2, '#e5effb', '#d4e4f3', '#c3d8eb', 'rgba(94, 126, 166, 0.34)');
    fillTile(1, 2, '#d6e6ff', '#c4d9f8', '#afcaec', 'rgba(65, 107, 163, 0.36)');
    fillTile(2, 2, '#e0d8f7', '#d0c3ec', '#beaee0', 'rgba(104, 90, 152, 0.32)');
    fillTile(3, 2, '#d2eadf', '#bfd9ca', '#abc8b4', 'rgba(77, 119, 102, 0.34)');
    fillTile(4, 2, '#eedbc0', '#e2caa7', '#d4b58d', 'rgba(132, 97, 57, 0.34)');
    fillTile(5, 2, '#d2e3f7', '#bfd5ee', '#a9c7e4', 'rgba(66, 105, 153, 0.34)');

    // Extra hallway surfaces and trim variants.
    fillTile(6, 0, '#f1f5fb', '#e2ebf4', '#d2dfec', 'rgba(91, 116, 150, 0.26)');
    fillTile(7, 0, '#ece4f3', '#dccfe6', '#cabed6', 'rgba(106, 90, 130, 0.24)');
    fillTile(8, 0, '#e3f1eb', '#d1e2d8', '#bfd3c8', 'rgba(87, 116, 103, 0.24)');
    fillTile(9, 0, '#f3eadf', '#e4d8c4', '#d3c5ac', 'rgba(121, 102, 72, 0.24)');
    fillTile(10, 0, '#e2edfb', '#d1e2f3', '#bed3e9', 'rgba(72, 108, 155, 0.24)');
    fillTile(11, 0, '#f0eaf6', '#e0d9ed', '#cec5e3', 'rgba(110, 96, 139, 0.24)');
    fillTile(6, 1, '#e7effa', '#d6e3f2', '#c3d4e7', 'rgba(82, 109, 141, 0.28)');
    fillTile(7, 1, '#ecf1fa', '#dbe5f1', '#c9d8e9', 'rgba(92, 118, 151, 0.28)');
    fillTile(8, 1, '#dde8f3', '#cbd9e8', '#b7cade', 'rgba(79, 103, 133, 0.28)');
    fillTile(9, 1, '#d9e4f0', '#c6d5e6', '#b2c5db', 'rgba(75, 100, 131, 0.3)');
    fillTile(10, 1, '#e0ebf7', '#cddced', '#b9cde2', 'rgba(82, 108, 140, 0.3)');
    fillTile(11, 1, '#e7eef8', '#d5e1ee', '#c1d2e4', 'rgba(90, 115, 147, 0.3)');

    const spritePalette = {
        o: '#22344f',
        a: '#47688f',
        b: '#5f88b6',
        c: '#87add8',
        d: '#b8d5f0',
        e: '#e8f3ff',
        f: '#5a9b74',
        g: '#7bc296',
        h: '#b0e3c4',
        i: '#927ab7',
        j: '#c4afe6',
        k: '#f0c170',
        l: '#ffe2a5',
        m: '#b76a54',
        n: '#dd9d7e',
        p: '#6f86aa',
        q: '#a3bad7',
        r: '#d8e6f5',
    };

    stampSprite(0, 3, [
        '........',
        '.oooooo.',
        '.obbbbo.',
        '.ocddco.',
        '.ocddco.',
        '.obppbo.',
        '.oqqqqo.',
        '..o..o..',
    ], spritePalette);
    stampSprite(1, 3, [
        '........',
        '..oooo..',
        '.obddbo.',
        '.obrrbo.',
        '.obrrbo.',
        '..oooo..',
        '.oo..oo.',
        '........',
    ], spritePalette);
    stampSprite(2, 3, [
        '........',
        '...oo...',
        '..obbo..',
        '.obddbo.',
        '.obddbo.',
        '..obbo..',
        '..o..o..',
        '...oo...',
    ], spritePalette);
    stampSprite(3, 3, [
        '........',
        '.oooooo.',
        '.okkkko.',
        '.okllko.',
        '.okllko.',
        '.okkkko.',
        '.oooooo.',
        '........',
    ], spritePalette);
    stampSprite(4, 3, [
        '........',
        '.oooooo.',
        '.onnnno.',
        '.onnnno.',
        '.ommmmo.',
        '.ommmmo.',
        '.oooooo.',
        '........',
    ], spritePalette);
    stampSprite(5, 3, [
        '...ff...',
        '..fggf..',
        '..fggf..',
        '...ff...',
        '..aaaa..',
        '..apqa..',
        '..apqa..',
        '..aaaa..',
    ], spritePalette);
    stampSprite(6, 3, [
        '........',
        '.oooooo.',
        '.obbbbo.',
        '.obbbbo.',
        '.obbbbo.',
        '.obbbbo.',
        '.oooooo.',
        '........',
    ], spritePalette);
    stampSprite(7, 3, [
        '.eeeeee.',
        '.errrre.',
        '.errrre.',
        '.errrre.',
        '.errrre.',
        '.eeeeee.',
        '..oooo..',
        '..oooo..',
    ], spritePalette);
    stampSprite(8, 3, [
        '........',
        '..kkkk..',
        '..kllk..',
        '..kkkk..',
        '...oo...',
        '..obbo..',
        '..obbo..',
        '..oooo..',
    ], spritePalette);
    stampSprite(9, 3, [
        '........',
        '.oooooo.',
        '.obddbo.',
        '.obddbo.',
        '.obddbo.',
        '.obddbo.',
        '.obbbbo.',
        '.oooooo.',
    ], spritePalette);
    stampSprite(10, 3, [
        '........',
        '..oooo..',
        '.obddbo.',
        '.obddbo.',
        '..oooo..',
        '...oo...',
        '..oooo..',
        '........',
    ], spritePalette);
    stampSprite(11, 3, [
        '........',
        '..eeee..',
        '..eeee..',
        '...oo...',
        '...oo...',
        '...oo...',
        '..obbo..',
        '..obbo..',
    ], spritePalette);

    stampSprite(0, 4, [
        '.eeeeee.',
        '.edddde.',
        '.edddde.',
        '.edddde.',
        '.edddde.',
        '.eeeeee.',
        '........',
        '........',
    ], spritePalette);
    stampSprite(1, 4, [
        '........',
        '.oooooo.',
        '.obbbbo.',
        '.obkkbo.',
        '.obkkbo.',
        '.obbbbo.',
        '.oooooo.',
        '........',
    ], spritePalette);
    stampSprite(2, 4, [
        '........',
        '.oo..oo.',
        '.obddbo.',
        '.obddbo.',
        '.obddbo.',
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
    const sprite = atlas.regions?.[spriteId];
    if (!sprite) return;
    const step = Math.max(6, Number(tileSize) || 20);
    const maxX = x + w;
    const maxY = y + h;
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha *= officeClamp(opacity, 0.05, 1);
    for (let yy = y; yy < maxY; yy += step) {
        for (let xx = x; xx < maxX; xx += step) {
            const drawW = Math.min(step, maxX - xx);
            const drawH = Math.min(step, maxY - yy);
            if (drawW <= 0 || drawH <= 0) continue;
            ctx.drawImage(
                atlas.canvas,
                sprite.x,
                sprite.y,
                sprite.w,
                sprite.h,
                xx,
                yy,
                drawW,
                drawH,
            );
        }
    }
    ctx.restore();
}

function officePaintSpriteStamp(ctx, atlas, spriteId, centerX, centerY, width, height, opacity = 1, { flipX = false } = {}) {
    if (!atlas || !ctx) return;
    const sprite = atlas.regions?.[spriteId];
    if (!sprite) return;
    const drawW = Math.max(2, Number(width) || sprite.w);
    const drawH = Math.max(2, Number(height) || sprite.h);
    const x = (Number(centerX) || 0) - (drawW / 2);
    const y = (Number(centerY) || 0) - (drawH / 2);
    ctx.save();
    ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha *= officeClamp(opacity, 0.08, 1);
    if (flipX) {
        ctx.translate(x + drawW, y);
        ctx.scale(-1, 1);
        ctx.drawImage(atlas.canvas, sprite.x, sprite.y, sprite.w, sprite.h, 0, 0, drawW, drawH);
    } else {
        ctx.drawImage(atlas.canvas, sprite.x, sprite.y, sprite.w, sprite.h, x, y, drawW, drawH);
    }
    ctx.restore();
}

function officeRoomPixels(room, width, height) {
    return {
        x: (room.x / 100) * width,
        y: (room.y / 100) * height,
        w: (room.w / 100) * width,
        h: (room.h / 100) * height,
        doorX: (room.doorX / 100) * width,
        doorY: (room.doorY / 100) * height,
    };
}

