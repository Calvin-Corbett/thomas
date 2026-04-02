/**
 * theme_rules.js — Thomas Global Theme Rules
 * ─────────────────────────────────────────────
 * Ensures every marketplace module inherits the active workspace theme.
 *
 * How it works:
 *   1. Defines a theme config object with surface colors, glow accents,
 *      border rules, and background behavior.
 *   2. Injects a <style> block with CSS custom properties that ALL modules
 *      can reference (--tm-* namespace).
 *   3. Provides a simple API for marketplace modules to query the theme
 *      without importing anything: `window.__themeRules`.
 *
 * Marketplace module authors:
 *   - Use `var(--tm-surface)` for panel backgrounds.
 *   - Use `var(--tm-border)` for borders.
 *   - Use `var(--tm-glow)` for subtle highlight effects.
 *   - Use `var(--tm-text)` / `var(--tm-text-dim)` for foreground text.
 *   - The space background is injected automatically for every tab that
 *     doesn't register its own background. You don't need to do anything.
 */
(function () {
    'use strict';

    /* ── Active Theme Definition ─────────────────────────────────────── */

    const SPACE_THEME = {
        id: 'space',
        name: 'Deep Space',

        /* Surface & background */
        rootBg:         '#050608',
        surface:        'rgba(255, 255, 255, 0.04)',
        surfaceRaised:  'rgba(255, 255, 255, 0.07)',
        surfaceOverlay: 'rgba(10, 12, 18, 0.85)',

        /* Borders & rules */
        border:      'rgba(255, 255, 255, 0.10)',
        borderFocus: 'rgba(88, 166, 255, 0.40)',
        rule:        'rgba(255, 255, 255, 0.12)',

        /* Glow & accent */
        glow:         'rgba(88, 166, 255, 0.12)',
        glowStrong:   'rgba(88, 166, 255, 0.25)',
        accent:       '#58a6ff',
        accentDim:    'rgba(88, 166, 255, 0.5)',

        /* Text */
        text:      '#ececf1',
        textDim:   'rgba(236, 236, 241, 0.70)',
        textMuted: 'rgba(236, 236, 241, 0.45)',

        /* Panels — recommended alpha-black backgrounds */
        panelBg:      'rgba(10, 12, 18, 0.52)',
        panelBgDense: 'rgba(10, 12, 18, 0.72)',

        /* Scrollbar tints (keep dark to match space) */
        scrollTrack: 'rgba(5, 6, 8, 0.74)',
        scrollThumb: 'rgba(173, 179, 194, 0.22)',
        scrollThumbHover: 'rgba(173, 179, 194, 0.38)',

        /* Module background mode — tells the runtime which __moduleBackgrounds
           key to use as the fallback. "space" maps to the __default registration
           in token_economy.js which injects the starfield/planet/galaxy canvas stack. */
        defaultBgKey: '__default',
    };

    /* ── Inject CSS Custom Properties ────────────────────────────────── */

    function injectThemeVars(theme) {
        let style = document.getElementById('tm-theme-vars');
        if (!style) {
            style = document.createElement('style');
            style.id = 'tm-theme-vars';
            document.head.appendChild(style);
        }

        style.textContent = `
/* ── Thomas Theme Rules: ${theme.name} ── */
:root {
    --tm-root-bg:         ${theme.rootBg};
    --tm-surface:         ${theme.surface};
    --tm-surface-raised:  ${theme.surfaceRaised};
    --tm-surface-overlay: ${theme.surfaceOverlay};

    --tm-border:       ${theme.border};
    --tm-border-focus: ${theme.borderFocus};
    --tm-rule:         ${theme.rule};

    --tm-glow:        ${theme.glow};
    --tm-glow-strong: ${theme.glowStrong};
    --tm-accent:      ${theme.accent};
    --tm-accent-dim:  ${theme.accentDim};

    --tm-text:       ${theme.text};
    --tm-text-dim:   ${theme.textDim};
    --tm-text-muted: ${theme.textMuted};

    --tm-panel-bg:       ${theme.panelBg};
    --tm-panel-bg-dense: ${theme.panelBgDense};

    --tm-scroll-track:       ${theme.scrollTrack};
    --tm-scroll-thumb:       ${theme.scrollThumb};
    --tm-scroll-thumb-hover: ${theme.scrollThumbHover};
}

/* ── Base module workspace styling ──
   Applied to any module content area so new marketplace modules
   automatically look right against the space background. */
#moduleWorkspace {
    color: var(--tm-text);
}

#moduleWorkspace .module-panel,
#moduleWorkspace .tm-panel {
    background: var(--tm-panel-bg);
    border: 1px solid var(--tm-border);
    border-radius: 10px;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
}

#moduleWorkspace .module-panel:hover,
#moduleWorkspace .tm-panel:hover {
    border-color: var(--tm-border-focus);
    box-shadow: 0 0 12px var(--tm-glow);
}

/* Card / tile pattern for marketplace module items */
#moduleWorkspace .tm-card {
    background: var(--tm-surface-raised);
    border: 1px solid var(--tm-border);
    border-radius: 8px;
    padding: 12px 16px;
    transition: border-color 0.2s, box-shadow 0.2s;
}
#moduleWorkspace .tm-card:hover {
    border-color: var(--tm-accent-dim);
    box-shadow: 0 0 8px var(--tm-glow);
}

/* Labels and secondary text */
#moduleWorkspace .tm-label {
    color: var(--tm-text-dim);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}
#moduleWorkspace .tm-value {
    color: var(--tm-text);
    font-size: 18px;
    font-weight: 700;
}
#moduleWorkspace .tm-muted {
    color: var(--tm-text-muted);
}

/* Buttons inside modules follow the space glow style */
#moduleWorkspace .tm-btn {
    background: var(--tm-surface-raised);
    color: var(--tm-accent);
    border: 1px solid var(--tm-border);
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
#moduleWorkspace .tm-btn:hover {
    background: rgba(88, 166, 255, 0.10);
    border-color: var(--tm-accent-dim);
    box-shadow: 0 0 10px var(--tm-glow);
}

/* Scrollbar theming for module areas */
#moduleWorkspace::-webkit-scrollbar-track {
    background: var(--tm-scroll-track);
}
#moduleWorkspace::-webkit-scrollbar-thumb {
    background: var(--tm-scroll-thumb);
}
#moduleWorkspace::-webkit-scrollbar-thumb:hover {
    background: var(--tm-scroll-thumb-hover);
}
`;
    }

    /* ── Public API ───────────────────────────────────────────────────── */

    const api = {
        /** Current theme object (read-only copy) */
        get current() { return { ...SPACE_THEME }; },

        /** Get a single token value, e.g. themeRules.token('accent') */
        token(key) { return SPACE_THEME[key] ?? null; },

        /** CSS var name for a token, e.g. themeRules.cssVar('surface') → 'var(--tm-surface)' */
        cssVar(key) {
            const map = {
                rootBg: '--tm-root-bg', surface: '--tm-surface',
                surfaceRaised: '--tm-surface-raised', surfaceOverlay: '--tm-surface-overlay',
                border: '--tm-border', borderFocus: '--tm-border-focus', rule: '--tm-rule',
                glow: '--tm-glow', glowStrong: '--tm-glow-strong',
                accent: '--tm-accent', accentDim: '--tm-accent-dim',
                text: '--tm-text', textDim: '--tm-text-dim', textMuted: '--tm-text-muted',
                panelBg: '--tm-panel-bg', panelBgDense: '--tm-panel-bg-dense',
            };
            return map[key] ? `var(${map[key]})` : null;
        },

        /** Re-inject theme vars (call if theme changes at runtime) */
        refresh() { injectThemeVars(SPACE_THEME); },
    };

    /* ── Init ────────────────────────────────────────────────────────── */
    injectThemeVars(SPACE_THEME);
    window.__themeRules = api;

    console.log('[theme-rules] Deep Space theme active — marketplace modules will auto-inherit.');
})();
