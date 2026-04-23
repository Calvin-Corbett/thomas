/* Theme, guardrails posture, and runtime-help helpers shared by settings UI. */

const _defaultIcons = {
    sendBtn: { from: 'ph-arrow-up', to: 'ph-arrow-up' },
    attachBtn: { from: 'ph-plus', to: 'ph-plus' },
    micBtn: { from: 'ph-microphone', to: 'ph-microphone' },
};
const _lightIcons = {
    sendBtn: { to: 'ph-pen-nib' },
    attachBtn: { to: 'ph-paperclip' },
    micBtn: { to: 'ph-waveform' },
};
const _allIconClasses = [
    'ph-arrow-up', 'ph-pen-nib', 'ph-feather',
    'ph-plus', 'ph-paperclip',
    'ph-microphone', 'ph-waveform', 'ph-speaker-high',
];
const THOMAS_THEME_STORAGE_KEY = 'thomas_theme';

function normalizeThemePreference(theme) {
    const normalized = safeString(theme).toLowerCase();
    if (normalized === 'system') return 'auto';
    if (normalized === 'light' || normalized === 'dark' || normalized === 'auto') return normalized;
    return 'auto';
}

function storeThemePreference(theme) {
    try {
        window.localStorage?.setItem(THOMAS_THEME_STORAGE_KEY, normalizeThemePreference(theme));
    } catch (_) {}
}

function syncSpaceThemeState(theme) {
    const normalized = normalizeThemePreference(theme);
    const spaceApi = window.__teSpace;
    if (normalized === 'light' || normalized === 'dark') {
        if (typeof spaceApi?.remove === 'function') {
            spaceApi.remove();
        } else {
            document.body.classList.remove('te-space-active');
        }
        if (window.spaceCanvas) window.spaceCanvas.style.display = 'none';
        return;
    }
    if (typeof spaceApi?.inject === 'function') {
        spaceApi.inject();
    } else {
        document.body.classList.add('te-space-active');
    }
    if (window.spaceCanvas) window.spaceCanvas.style.display = '';
}

function _swapComposerIcons(iconMap) {
    Object.entries(iconMap).forEach(([btnId, cls]) => {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        const icon = btn.querySelector('i.ph');
        if (!icon) return;
        _allIconClasses.forEach((className) => icon.classList.remove(className));
        icon.classList.add(cls.to);
    });
}

function applyTheme(theme) {
    const normalizedTheme = normalizeThemePreference(theme);
    const body = document.body;
    body.classList.remove('te-theme-light', 'te-theme-dark');
    body.removeAttribute('data-theme');
    storeThemePreference(normalizedTheme);
    if (normalizedTheme === 'light') {
        body.classList.add('te-theme-light');
        body.setAttribute('data-theme', 'light');
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_lightIcons);
        _injectLightThemeIntoIframes();
    } else if (normalizedTheme === 'dark') {
        body.classList.add('te-theme-dark');
        body.setAttribute('data-theme', 'dark');
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_defaultIcons);
        _removeLightThemeFromIframes();
    } else {
        syncSpaceThemeState(normalizedTheme);
        _swapComposerIcons(_defaultIcons);
        _removeLightThemeFromIframes();
    }
}

const _LIGHT_IFRAME_CSS = `
/* Injected by Thomas — light journal theme for plugin iframes */
:root, body, html {
    background: #ebe5d9 !important;
    color: #2c2420 !important;
    font-family: 'Georgia','Palatino Linotype','Palatino','Book Antiqua',serif !important;
}
*:not(.ph):not([class*="ph-"]) {
    font-family: 'Georgia','Palatino Linotype','Palatino','Book Antiqua',serif !important;
}
[style*="gradient"], [style*="rgba(8"], [style*="rgba(1"], [style*="rgba(3"],
[style*="rgba(6"], [style*="rgba(5"], [style*="rgb(5,"], [style*="rgb(8,"],
[style*="rgb(10,"], [style*="rgb(1"], [style*="rgb(2"], [style*="rgb(3"] {
    background: #ebe5d9 !important;
    background-image: none !important;
}
section, div, main, article, header, footer, aside, nav {
    background-color: transparent !important;
    background-image: none !important;
}
[class*="-card"], [class*="-tile"], [class*="-panel"],
[class*="-section"], [class*="-block"], [class*="-widget"],
[class*="-hero"], [class*="-header"], [class*="-toolbar"],
[class*="-board"], [class*="-frame"], [class*="-view"],
[class*="stuff-"], [class*="lm-"], [class*="plugin-"] {
    background: #f4efe6 !important;
    background-image: none !important;
    color: #2c2420 !important;
    border-color: #c8bfab !important;
}
body, .app, .wrapper, .container, .content, .main,
[class*="-wrap"], [class*="-container"], [class*="-content"],
[class*="-page"], [class*="-screen"], [class*="-workspace"],
[class*="-dashboard"], [class*="-statusbar"] {
    background: #ebe5d9 !important;
    background-image: none !important;
    color: #2c2420 !important;
}
h1, h2, h3, h4, h5, h6, p, span, a, label, strong, em, li, td, th, dt, dd {
    color: #2c2420 !important;
    text-shadow: none !important;
}
small, .muted, .meta, .subtitle, [class*="-meta"], [class*="-sub"],
[class*="-muted"], [class*="-hint"], [class*="-note"] {
    color: #8a7a65 !important;
}
button, .btn, [class*="-btn"] {
    background: #e0d8ca !important;
    background-image: none !important;
    color: #3d3028 !important;
    border: 1px solid #c8bca8 !important;
    border-radius: 2px !important;
    text-shadow: none !important;
}
button:hover, .btn:hover { background: #d6cebf !important; }
[class*="primary"], [class*="accent"] {
    background: #8a7250 !important;
    background-image: none !important;
    color: #f5f0e8 !important;
    border-color: #7a6240 !important;
}
input, select, textarea {
    background: #f0ebe2 !important;
    color: #2c2420 !important;
    border: 1px solid #c8bca8 !important;
    border-radius: 1px !important;
}
input::placeholder, textarea::placeholder { color: #a0907a !important; font-style: italic !important; }
table, th, td { background: #f4efe6 !important; color: #2c2420 !important; border-color: #c8bfab !important; }
th { background: #e6dfd2 !important; font-weight: 700 !important; }
[class*="-badge"], [class*="-pill"], [class*="-tag"], [class*="-status"] {
    background: #e0d8ca !important;
    color: #3d3028 !important;
    border: 1px solid #c8bca8 !important;
    text-shadow: none !important;
}
::-webkit-scrollbar-thumb { background: #c0ad90 !important; }
::-webkit-scrollbar-track { background: #e2dbd0 !important; }
[class*="-empty"], [class*="empty-"] {
    background: #f4efe6 !important;
    color: #8a7a65 !important;
}
`.trim();

function _injectLightThemeIntoIframes() {
    try {
        document.querySelectorAll('iframe').forEach((frame) => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc) return;
                const existing = doc.getElementById('thomas-light-theme-inject');
                if (existing) existing.remove();
                const style = doc.createElement('style');
                style.id = 'thomas-light-theme-inject';
                style.textContent = _LIGHT_IFRAME_CSS;
                (doc.head || doc.documentElement).appendChild(style);
            } catch (_) {}
        });
    } catch (_) {}
    clearTimeout(window._lightIframeTimer);
    window._lightIframeTimer = setTimeout(() => _injectLightThemeIntoIframes_once(), 1500);
}

function _injectLightThemeIntoIframes_once() {
    if (!document.body.classList.contains('te-theme-light')) return;
    try {
        document.querySelectorAll('iframe').forEach((frame) => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc || doc.getElementById('thomas-light-theme-inject')) return;
                const style = doc.createElement('style');
                style.id = 'thomas-light-theme-inject';
                style.textContent = _LIGHT_IFRAME_CSS;
                (doc.head || doc.documentElement).appendChild(style);
            } catch (_) {}
        });
    } catch (_) {}
}

(function watchForNewIframes() {
    const observer = new MutationObserver((mutations) => {
        if (!document.body.classList.contains('te-theme-light')) return;
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node.tagName === 'IFRAME') {
                    node.addEventListener('load', () => _injectLightThemeIntoIframes_once());
                } else if (node.querySelectorAll) {
                    node.querySelectorAll('iframe').forEach((frame) => {
                        frame.addEventListener('load', () => _injectLightThemeIntoIframes_once());
                    });
                }
            }
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });
})();

function _removeLightThemeFromIframes() {
    clearTimeout(window._lightIframeTimer);
    try {
        document.querySelectorAll('iframe').forEach((frame) => {
            try {
                const doc = frame.contentDocument || frame.contentWindow?.document;
                if (!doc) return;
                const el = doc.getElementById('thomas-light-theme-inject');
                if (el) el.remove();
            } catch (_) {}
        });
    } catch (_) {}
}

function applyFontSize(px) {
    document.documentElement.style.setProperty('--user-font-size', `${px}px`);
    document.body.style.fontSize = `${px}px`;
}

function normalizeGuardrailsPosture(value) {
    const normalized = safeString(value).toLowerCase().replace(/[\s-]+/g, '_');
    if (normalized === 'locked') return 'locked';
    if (normalized === 'builder') return 'builder';
    return 'standard';
}

let runtimeHelpTooltip = null;
let runtimeHelpTooltipTimer = 0;

function ensureRuntimeHelpTooltip() {
    if (runtimeHelpTooltip instanceof HTMLElement) return runtimeHelpTooltip;
    const tooltip = document.createElement('div');
    tooltip.className = 'runtime-help-tooltip';
    tooltip.setAttribute('aria-hidden', 'true');
    tooltip.innerHTML = '<div class="runtime-help-tooltip-title"></div><div class="runtime-help-tooltip-body"></div>';
    document.body.appendChild(tooltip);
    runtimeHelpTooltip = tooltip;
    return tooltip;
}

function hideRuntimeHelpTooltip() {
    window.clearTimeout(runtimeHelpTooltipTimer);
    if (!(runtimeHelpTooltip instanceof HTMLElement)) return;
    runtimeHelpTooltip.classList.remove('visible');
    runtimeHelpTooltip.setAttribute('aria-hidden', 'true');
}

function showRuntimeHelpTooltip(anchor) {
    if (!(anchor instanceof HTMLElement)) return;
    const title = safeString(anchor.dataset.runtimeHelpTitle);
    const body = safeString(anchor.dataset.runtimeHelpBody);
    if (!body) return;
    const tooltip = ensureRuntimeHelpTooltip();
    const titleNode = tooltip.querySelector('.runtime-help-tooltip-title');
    const bodyNode = tooltip.querySelector('.runtime-help-tooltip-body');
    if (titleNode) titleNode.textContent = title;
    if (bodyNode) bodyNode.textContent = body;
    tooltip.classList.add('visible');
    tooltip.setAttribute('aria-hidden', 'false');
    const rect = anchor.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    const left = Math.min(
        Math.max(10, rect.left + (rect.width / 2) - (tooltipRect.width / 2)),
        Math.max(10, viewportWidth - tooltipRect.width - 10)
    );
    const top = Math.max(10, rect.top - tooltipRect.height - 10);
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
}

function scheduleRuntimeHelpTooltip(anchor) {
    window.clearTimeout(runtimeHelpTooltipTimer);
    runtimeHelpTooltipTimer = window.setTimeout(() => showRuntimeHelpTooltip(anchor), 360);
}

function wireRuntimeHelpTargets(root = document) {
    if (!(root instanceof Element || root instanceof Document)) return;
    root.querySelectorAll('[data-runtime-help-body]').forEach((node) => {
        if (!(node instanceof HTMLElement) || node.dataset.runtimeHelpBound === 'true') return;
        node.dataset.runtimeHelpBound = 'true';
        node.addEventListener('mouseenter', () => scheduleRuntimeHelpTooltip(node));
        node.addEventListener('focus', () => scheduleRuntimeHelpTooltip(node));
        node.addEventListener('mouseleave', hideRuntimeHelpTooltip);
        node.addEventListener('blur', hideRuntimeHelpTooltip);
    });
}

function getCurrentGuardrailsPosture() {
    return normalizeGuardrailsPosture(currentPreferences?.advanced?.security?.guardrails_posture || activeGuardrailsPosture);
}

function syncGuardrailsManagedControls() {
    const managedInputs = [
        settingAdvQualityEnforce,
        settingAdvQualityRequireVerification,
        settingAdvQualityRequireTests,
        settingAdvQualityRequireMonolithGuard,
        settingAdvRequireCommandApproval,
        settingAdvAllowShell,
        settingAdvAllowFileWrite,
        settingAdvAllowNetwork,
        settingAdvAllowBrowser,
        settingAdvAllowChannels,
        settingAdvAllowGit,
    ];
    managedInputs.forEach((input) => {
        if (!(input instanceof HTMLInputElement)) return;
        input.disabled = true;
        input.setAttribute('title', 'Managed by Guardrails posture');
        const row = input.closest('.switch-row');
        if (row) row.dataset.guardrailsManaged = 'true';
    });
}

async function applyGuardrailsPostureChange(nextPosture, { suppressSuccess = false } = {}) {
    const posture = normalizeGuardrailsPosture(nextPosture);
    const response = await fetch('/api/security/guardrails-posture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ posture }),
    });
    let payload = {};
    try {
        payload = await response.json();
    } catch (_) {}
    if (!response.ok) {
        const message = safeString(payload?.reason) || `HTTP ${response.status}`;
        throw new Error(message || 'guardrails posture update failed');
    }
    currentPreferences = payload?.preferences || currentPreferences;
    activeGuardrailsPosture = normalizeGuardrailsPosture(
        payload?.posture || currentPreferences?.advanced?.security?.guardrails_posture || posture
    );
    if (settingAdvGuardrailsPosture) settingAdvGuardrailsPosture.value = activeGuardrailsPosture;
    setSegmentedControlSelection('setupGuardrailsGroup', activeGuardrailsPosture);
    syncGuardrailsManagedControls();
    renderChatComposerSubbar();
    if (!suppressSuccess) {
        notifyUser(`Guardrails set to ${activeGuardrailsPosture}.`, {
            tone: 'success',
            durationMs: 1800,
            debugKind: 'settings',
        });
    }
    return currentPreferences;
}
