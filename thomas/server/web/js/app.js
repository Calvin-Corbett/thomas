/**
 * Split app bootstrap.
 * Generated from the previous monolith app.js into ./app_parts/*.js.
 */
const APP_PART_FILES = [
    "part-001.js",
    "part-002.js",
    "part-003.js",
    "part-004.js",
    "part-005.js",
    "part-006.js",
    "part-007.js",
    "part-008.js",
    "part-009.js",
    "part-010.js",
    "part-011.js",
    "part-012.js",
    "part-013.js",
    "part-014.js",
    "part-015.js",
    "part-016.js",
    "part-017.js",
    "part-018.js",
    "part-019.js",
    "part-020.js",
    "part-021.js",
    "part-022.js",
    "part-023.js",
    "part-024.js",
    "part-025.js",
    "part-026.js",
    "part-027.js",
    "part-028.js",
    "part-029.js",
    "part-030.js",
    "part-031.js",
    "part-032.js"
];

async function loadSplitAppModule() {
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

try {
    await loadSplitAppModule();
} catch (error) {
    console.error('Failed to load split app module', error);
}
