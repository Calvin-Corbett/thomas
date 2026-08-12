/** Office agent DOM creation and incremental updates. */

function officeDraftCreateAgentElement(space, agent, index, total, state, options = {}) {
    officeEnsureDraftAgentMotionStyles();
    const palette = officeAgentPalette(agent);
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'office-live-agent';
    el.dataset.officeDraftAgentId = safeString(agent?.id);
    el.dataset.uiId = 'virtual-office.agent';
    el.dataset.uiInstanceKey = safeString(agent?.id);
    el.dataset.uiLabel = `${safeString(agent?.name) || 'Agent'} presence`;
    el.dataset.uiPolicy = 'protected live-map-item';
    el.dataset.uiConstraints = 'no-move no-resize no-delete no-copy';
    el.setAttribute('aria-label', `${safeString(agent?.name) || 'Agent'} office agent`);
    el.style.position = 'absolute';
    el.style.left = '0';
    el.style.top = '0';
    el.style.width = `${OFFICE_DRAFT_AGENT_HITBOX_W}px`;
    el.style.minHeight = `${OFFICE_DRAFT_AGENT_HITBOX_H}px`;
    el.style.setProperty('--agent-primary', palette.primary);
    el.style.setProperty('--agent-secondary', palette.secondary);
    el.style.setProperty('--agent-glow', palette.glow);
    el.innerHTML = `
        <span class="office-live-agent-name" data-office-draft-agent-name="1"></span>
        <span class="office-live-agent-bubble" data-office-draft-agent-bubble="1"></span>
        <span class="office-live-agent-robot" data-office-draft-agent-robot="1">
            ${officePixelAgentMarkup('', `--agent-primary:${palette.primary};--agent-secondary:${palette.secondary};--agent-glow:${palette.glow};`)}
        </span>
        <span class="office-live-agent-prop" data-office-draft-agent-prop="1"></span>
        <span class="office-live-agent-status" data-office-draft-agent-status="1"></span>
        <span class="office-live-agent-can" data-office-draft-agent-can="1">Coke</span>
    `;
    if (options?.skipInitialUpdate !== true) {
        officeDraftUpdateAgentElement(el, space, agent, index, total, state, performance.now());
    }
    el.addEventListener('pointerenter', () => {
        const currentState = officeEnsureDraftMapState();
        currentState.hoveredAgentId = safeString(agent?.id);
        window.clearTimeout(currentState.agentHoverRenderTimer);
        currentState.agentHoverRenderTimer = window.setTimeout(() => {
            if (!officeDraftAgentRenderQuietActive(currentState, performance.now())) {
                officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'hover-enter' });
            }
        }, 140);
    });
    el.addEventListener('pointerleave', () => {
        const currentState = officeEnsureDraftMapState();
        if (safeString(currentState.hoveredAgentId) === safeString(agent?.id)) {
            currentState.hoveredAgentId = '';
            window.clearTimeout(currentState.agentHoverRenderTimer);
            currentState.agentHoverRenderTimer = 0;
        }
    });
    el.addEventListener('pointerdown', (event) => {
        officeDraftHandleAgentPointerDown(event, safeString(agent?.id));
    });
    el.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        officeDraftHandleAgentClick(event, safeString(agent?.id));
    });
    return el;
}

function officeDraftSetDatasetValue(el, key, value) {
    if (!(el instanceof HTMLElement) || !key) return;
    const next = safeString(value);
    if (el.dataset[key] !== next) el.dataset[key] = next;
}

function officeDraftSetStyleValue(el, prop, value) {
    if (!(el instanceof HTMLElement) || !prop) return;
    const next = safeString(value);
    if (el.style[prop] !== next) el.style[prop] = next;
}

function officeDraftSetCssVariable(el, name, value) {
    if (!(el instanceof HTMLElement) || !name) return;
    const next = safeString(value);
    if (el.style.getPropertyValue(name) !== next) el.style.setProperty(name, next);
}

function officeDraftUpdateAgentElement(el, space, agent, index, total, state, now = performance.now()) {
    if (!(el instanceof HTMLElement) || !agent) return;
    officeDraftSetDatasetValue(el, 'uiInstanceKey', safeString(agent?.id));
    officeDraftSetDatasetValue(el, 'uiLabel', `${safeString(agent?.name) || 'Agent'} presence`);
    el.setAttribute('aria-label', `${safeString(agent?.name) || 'Agent'} office agent`);
    const placement = officeDraftAgentPlacement(space, agent, index, total, now);
    const palette = officeAgentPalette(agent);
    const selected = safeString(state.expandedRosterAgentId || officeState?.selectedAgentId) === safeString(agent?.id);
    const globalLayer = el.dataset.officeDraftAgentGlobal === '1';
    const offsetX = globalLayer ? (Number(space?.x) || 0) : 0;
    const offsetY = globalLayer ? (Number(space?.y) || 0) : 0;
    const overviewAgent = officeDraftOverviewMode(state)
        && !selected
        && safeString(state?.hoveredAgentId) !== safeString(agent?.id)
        && !agent?.draftMotion?.dragging;
    officeDraftSetDatasetValue(el, 'officeAgentOverview', overviewAgent ? '1' : '0');
    officeDraftSetCssVariable(el, '--agent-primary', palette.primary);
    officeDraftSetCssVariable(el, '--agent-secondary', palette.secondary);
    officeDraftSetCssVariable(el, '--agent-glow', palette.glow);
    if (overviewAgent) {
        officeDraftSetDatasetValue(el, 'officeAgentActivity', placement.routeActive ? 'walking' : safeString(agent?.state || 'idle'));
        officeDraftSetDatasetValue(el, 'officeAgentAnimation', placement.routeActive ? 'walking' : 'idle');
        officeDraftSetDatasetValue(el, 'officeAgentRouteActive', placement.routeActive ? '1' : '0');
        officeDraftSetDatasetValue(el, 'officeAgentWorldX', String(Math.round(Number(placement.worldX) || (offsetX + placement.x))));
        officeDraftSetDatasetValue(el, 'officeAgentWorldY', String(Math.round(Number(placement.worldY) || (offsetY + placement.y))));
        officeDraftSetStyleValue(el, 'transform', `translate3d(${Math.round(offsetX + placement.x - 24)}px, ${Math.round(offsetY + placement.y - 24)}px, 0)`);
        return;
    }

    const activity = officeDraftAgentActivity(agent, space);
    const animation = officeDraftAgentAnimation(agent, activity, now);
    const sitScale = activity === 'sit' ? ' scale(1,0.88)' : '';
    officeDraftSetDatasetValue(el, 'officeAgentActivity', activity);
    officeDraftSetDatasetValue(el, 'officeAgentAnimation', animation);
    officeDraftSetDatasetValue(el, 'officeAgentRouteActive', placement.routeActive ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentWorldX', String(Math.round(Number(placement.worldX) || (offsetX + placement.x))));
    officeDraftSetDatasetValue(el, 'officeAgentWorldY', String(Math.round(Number(placement.worldY) || (offsetY + placement.y))));
    officeDraftSetStyleValue(el, 'transform', `translate3d(${Math.round(offsetX + placement.x)}px, ${Math.round(offsetY + placement.y)}px, 0)${sitScale}`);
    const visibility = officeDraftAgentUiVisibility(state, agent, activity, selected, now, total);
    officeDraftSetDatasetValue(el, 'officeAgentLabelVisible', visibility.showName ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentStatusVisible', visibility.showStatus ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentPropVisible', visibility.showProp ? '1' : '0');
    officeDraftSetDatasetValue(el, 'officeAgentBubbleVisible', visibility.showBubble ? '1' : '0');
    officeDraftSetStyleValue(el, 'zIndex', selected ? '80' : (visibility.showBubble ? '70' : String(20 + Math.round((Number(placement.y) || 0) / 120))));

    const robotWrap = el.querySelector('[data-office-draft-agent-robot="1"]');
    if (robotWrap instanceof HTMLElement) {
        officeDraftSetStyleValue(robotWrap, 'transform', activity === 'sit' ? 'scale(1.24,0.94)' : 'scale(1.24)');
    }
    const nameEl = el.querySelector('[data-office-draft-agent-name="1"]');
    if (nameEl instanceof HTMLElement) {
        officeDraftSetStyleValue(nameEl, 'display', visibility.showName ? 'block' : 'none');
        if (visibility.showName && nameEl.textContent !== safeString(agent?.name)) {
            nameEl.textContent = safeString(agent?.name) || 'Agent';
        }
    }
    const statusEl = el.querySelector('[data-office-draft-agent-status="1"]');
    const statusText = officeDraftAgentActivityLabel(agent, activity, total);
    if (statusEl instanceof HTMLElement) {
        officeDraftSetStyleValue(statusEl, 'display', visibility.showStatus ? 'block' : 'none');
        if (visibility.showStatus && statusEl.textContent !== statusText) {
            statusEl.textContent = statusText;
        }
    }
    const pixelEl = el.querySelector('.office-pixel-agent');
    if (pixelEl instanceof HTMLElement) {
        officeDraftSetCssVariable(pixelEl, '--agent-primary', palette.primary);
        officeDraftSetCssVariable(pixelEl, '--agent-secondary', palette.secondary);
        officeDraftSetCssVariable(pixelEl, '--agent-glow', palette.glow);
        pixelEl.classList.toggle('facing-left', Number(agent?.facing) < 0);
        pixelEl.classList.toggle('looking-user', activity === 'working' || activity === 'drink' || activity === 'talking' || activity === 'paused');
        pixelEl.classList.remove('costume-cap', 'costume-visor', 'costume-headset', 'costume-bowtie', 'costume-toolbelt', 'costume-satchel', 'costume-scarf', 'costume-badge', 'costume-tablet', 'costume-wrench', 'costume-mug');
        // Costumes are intentionally NOT drawn on the office floor — the small
        // cap/visor/bowtie/headset overlays read as visual noise at scene scale.
        // (The roster panel still previews them for users who opt in per-agent.)
    }
    const propEl = el.querySelector('[data-office-draft-agent-prop="1"]');
    if (propEl instanceof HTMLElement) {
        officeDraftSetStyleValue(propEl, 'display', visibility.showProp ? 'flex' : 'none');
        if (visibility.showProp) {
            const propLabel = officeDraftAgentPropLabel(agent);
            if (propEl.textContent !== propLabel) propEl.textContent = propLabel;
            officeDraftSetStyleValue(propEl, 'borderColor', palette.primary);
            officeDraftSetStyleValue(propEl, 'boxShadow', `0 5px 10px rgba(0,0,0,0.18), 0 0 0 1px ${palette.glow}`);
        }
    }
    const canEl = el.querySelector('[data-office-draft-agent-can="1"]');
    if (canEl instanceof HTMLElement) {
        officeDraftSetStyleValue(canEl, 'display', activity === 'drink' ? 'inline-flex' : 'none');
        if (activity === 'drink') {
            const propLabel = safeString(agent?.draftCommandPropLabel || 'Coke') || 'Coke';
            if (canEl.textContent !== propLabel) canEl.textContent = propLabel;
        }
    }
    const bubbleEl = el.querySelector('[data-office-draft-agent-bubble="1"]');
    const speech = typeof officeVisibleSpeech === 'function' ? officeVisibleSpeech(agent, now) : '';
    const bubbleText = visibility.showBubble ? speech : '';
    if (bubbleEl instanceof HTMLElement) {
        const bubbleLeft = Number(placement.x) > (Number(space?.width) || 0) - 260;
        officeDraftSetStyleValue(bubbleEl, 'left', bubbleLeft ? 'auto' : '136px');
        officeDraftSetStyleValue(bubbleEl, 'right', bubbleLeft ? '136px' : 'auto');
        officeDraftSetStyleValue(bubbleEl, 'display', bubbleText ? 'block' : 'none');
        if (bubbleText && bubbleEl.textContent !== bubbleText) {
            bubbleEl.textContent = bubbleText;
        }
    }
}


