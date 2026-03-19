/**
 * App bootstrap uses a single live runtime.
 *
 * Thomas no longer falls through old generated or split-part runtimes.
 * If the active runtime fails, we enter rescue mode instead of reviving
 * stale UI variants.
 */

async function loadPrimaryAppRuntime() {
    const baseUrl = new URL(import.meta.url);
    const runtimeUrl = new URL('./app_runtime_primary.mjs', baseUrl);
    runtimeUrl.search = baseUrl.search;
    console.log('[Thomas] Loading primary app runtime...');
    await import(runtimeUrl.href);
}

(async () => {
    try {
        await loadPrimaryAppRuntime();
        console.log('[Thomas] SUCCESS: Using primary app runtime');
    } catch (error) {
        console.error('[Thomas] FATAL: Primary app runtime failed to load', error);
        try {
            console.warn('[Thomas] Loading UI editor rescue mode...');
            const rescue = await import(new URL('./ui_editor_rescue.js', import.meta.url).href);
            if (rescue && typeof rescue.startUiEditorRescueMode === 'function') {
                await rescue.startUiEditorRescueMode();
                console.warn('[Thomas] UI editor rescue mode active');
            }
        } catch (rescueError) {
            console.error('[Thomas] UI editor rescue mode failed.', rescueError);
        }
    }
})();
