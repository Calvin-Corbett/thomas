// Extracted from part-016b.js
// From handler

    officeEnsureState();
    officeUpdateFollowUi();
    officeRenderMinimap();
    officeSyncReducedMotionPreference();
    if (!officeReducedMotionListenerBound && window.matchMedia) {
        officeReducedMotionListenerBound = true;
        const handler = () => officeSyncReducedMotionPreference();
        const queryList = [
            window.matchMedia('(prefers-reduced-motion: reduce)'),
            window.matchMedia('(prefers-contrast: more)'),