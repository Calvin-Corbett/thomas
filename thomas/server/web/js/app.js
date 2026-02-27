/**
 * App bootstrap with fallback strategy.
 *
 * Primary: Load from assembled runtime module (./app_runtime_joined.mjs)
 * Fallback: Load from legacy string-array split parts (./app_parts/*.js)
 *
 * The modernized approach allows linting, debugging, and proper IDE support.
 */

async function loadModularAppArchitecture() {
    try {
        console.log('[Thomas] Loading production assembled app runtime...');
        const baseUrl = new URL(import.meta.url);
        const runtimeUrl = new URL('./app_runtime_joined.mjs', baseUrl);
        runtimeUrl.search = baseUrl.search;
        await import(runtimeUrl.href);
        return true;
    } catch (error) {
        console.error('[Thomas] Production assembled app runtime failed to load.', error);
        return false;
    }
}

async function loadLegacySplitAppModule() {
    // Fallback: use the legacy blob URL approach with string arrays
    const APP_PART_FILES = [
        "part-001.js",
        "part-001b.js",
        "part-002.js",
        "part-002b.js",
        "part-003.js",
        "part-003b.js",
        "part-004.js",
        "part-004b.js",
        "part-005.js",
        "part-005b.js",
        "part-006.js",
        "part-006b.js",
        "part-007.js",
        "part-007b.js",
        "part-008.js",
        "part-008b.js",
        "part-009.js",
        "part-009b.js",
        "part-010.js",
        "part-010b.js",
        "part-011.js",
        "part-011b.js",
        "part-012.js",
        "part-012b.js",
        "part-013.js",
        "part-013b.js",
        "part-014.js",
        "part-014b.js",
        "part-015.js",
        "part-015b.js",
        "part-016.js",
        "part-016b.js",
        "part-017.js",
        "part-017b.js",
        "part-018.js",
        "part-019.js",
        "part-020.js",
        "part-020b.js",
        "part-021.js",
        "part-021b.js",
        "part-022.js",
        "part-022b.js",
        "part-023.js",
        "part-023b.js",
        "part-024.js",
        "part-024b.js",
        "part-025.js",
        "part-025b.js",
        "part-026.js",
        "part-026b.js",
        "part-027.js",
        "part-027b.js",
        "part-028.js",
        "part-028b.js",
        "part-029.js",
        "part-030.js",
        "part-030b.js",
        "part-031.js",
        "part-031b.js",
        "part-032.js",
        "part-033.js"
    ];

    const search = new URL(import.meta.url).search || "";
    const modules = await Promise.all(
        APP_PART_FILES.map((fileName) => import(new URL("./app_parts/" + fileName + search, import.meta.url).href))
    );

    const source = modules
        .map((mod, idx) => {
            if (typeof mod.default !== 'string') {
                throw new Error("Invalid app module part: " + APP_PART_FILES[idx]);
            }
            return mod.default;
        })
        .join("\n");

    const blobUrl = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    try {
        await import(blobUrl);
    } finally {
        URL.revokeObjectURL(blobUrl);
    }
}

(async () => {
    try {
        // Try the modernized architecture first
        const success = await loadModularAppArchitecture();

        // Fall back to legacy approach if modernized fails
        if (!success) {
            console.log('[Thomas] Falling back to legacy string-array architecture...');
            await loadLegacySplitAppModule();
            console.log('[Thomas] SUCCESS: Using legacy architecture (fallback)');
        }
    } catch (error) {
        console.error('[Thomas] FATAL: Failed to load app from both strategies', error);
    }
})();
