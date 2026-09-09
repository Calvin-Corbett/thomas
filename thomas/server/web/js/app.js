/**
 * App bootstrap — loads the split runtime via the ordered script loader.
 *
 * Thomas loads runtime modules as ordered <script> tags so they share
 * global scope.  The loader (app_runtime_loader.js) is included before
 * this module in index.html and sets window.__thomasRuntimeReady to a
 * Promise that resolves once every script has executed.
 *
 * If the runtime fails, we fall back to rescue mode.
 */

(async () => {
    try {
        if (typeof window.__thomasRuntimeReady === 'undefined') {
            throw new Error('Runtime loader not found — is app_runtime_loader.js included before app.js?');
        }
        await window.__thomasRuntimeReady;
        console.log('[Thomas] SUCCESS: Using split runtime');
    } catch (error) {
        console.error('[Thomas] FATAL: Runtime failed to load', error);
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
