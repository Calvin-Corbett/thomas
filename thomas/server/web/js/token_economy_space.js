/**
 * Token Economy surface compatibility adapter.
 *
 * Thomas Chat owns the background. This file preserves the historical
 * window.__teSpace API without canvases, animation loops, timers, or observers.
 */
window.__teSpace = (function tokenEconomySurfaceAdapter() {
    'use strict';

    let active = false;
    let callbacks = { onEnter: null, onLeave: null };

    function root() {
        return document.querySelector('[data-te-container] .te-v3');
    }

    function init(nextCallbacks) {
        callbacks = Object.assign(callbacks, nextCallbacks || {});
        return api;
    }

    function inject() {
        const workspace = root();
        if (!workspace || !workspace.isConnected) return false;
        workspace.classList.add('is-active');
        if (active) return true;
        active = true;
        if (typeof callbacks.onEnter === 'function') callbacks.onEnter();
        return true;
    }

    function remove() {
        const workspace = root();
        if (workspace) workspace.classList.remove('is-active');
        const staleRoot = document.getElementById('te-space-root');
        if (staleRoot) staleRoot.remove();
        if (!active) return false;
        active = false;
        if (typeof callbacks.onLeave === 'function') callbacks.onLeave();
        return true;
    }

    function isActive() {
        return active && Boolean(root());
    }

    const api = { init, inject, remove, isActive };
    return api;
}());
