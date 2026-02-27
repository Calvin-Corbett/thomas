/**
 * Module-based app loader (modernized from string-array split parts).
 *
 * This replaces the blob URL approach with standard ES module imports.
 * All extracted modules are loaded and their code is executed in the global scope.
 */

// List of all extracted modules in order
// Accessibility module is loaded first to ensure features are available early
const MODULE_FILES = [
    './modules/accessibility.js',
    './modules/001_gl.js',
    './modules/002_generic_module.js',
    './modules/003_generic_module.js',
    './modules/004_message.js',
    './modules/005_capped.js',
    './modules/006_dependencyplanpayload.js',
    './modules/007_errormsg.js',
    './modules/008_init.js',
    './modules/009_modeid.js',
    './modules/010_moving.js',
    './modules/011_groundy.js',
    './modules/012_stabilizeportalanchor.js',
    './modules/013_chatgamestepdinogameover.js',
    './modules/014_chatvisible.js',
    './modules/015_finalprompt.js',
    './modules/016_regenerateresponse.js',
    './modules/017_type.js',
    './modules/018_frag.js',
    './modules/019_renderdebugmodelspanel.js',
    './modules/020_se.js',
    './modules/021_officechance.js',
    './modules/022_tools.js',
    './modules/023_trigger.js',
    './modules/024_stampsprite.js',
    './modules/025_regions.js',
    './modules/026_generic_module.js',
    './modules/027_pillar.js',
    './modules/028_officemissionstatustoofficestate.js',
    './modules/029_outofbounds.js',
    './modules/030_officehandlemention.js',
    './modules/031_roomid.js',
    './modules/032_handler.js',
    './modules/033_missionrunjobaction.js',
    './modules/034_activejobspayload.js',
    './modules/035_contentensurestate.js',
    './modules/037_moduleensurehiddenbucket.js',
    './modules/038_modulerendersubnav.js',
    './modules/039_stlmodule.js',
    './modules/040_generic_module.js',
    './modules/041_target.js',
    './modules/042_tools.js',
    './modules/043_trigger.js',
    './modules/044_modulerenderworkbenchautomations.js',
    './modules/045_blob.js',
    './modules/046_item.js',
    './modules/047_painting.js',
    './modules/048_audiopresetselect.js',
    './modules/049_clip.js',
    './modules/050_getcode.js',
    './modules/051_generic_module.js',
    './modules/052_modulegamestudiostartphaserpreview.js',
    './modules/053_brushes.js',
    './modules/054_generic_module.js',
    './modules/055_prompt.js',
    './modules/056_generic_module.js',
    './modules/057_loadstorednavmode.js',
    './modules/058_timers.js',
    './modules/059_payload.js',
    './modules/060_togglesidebarcollapsed.js',
    './modules/061_appearance.js',
    './modules/062_apikeyspatch.js',
    './modules/063_module_studio_comfy_style_id.js',
];

/**
 * Load all modules using standard ES imports.
 * This approach allows each module to be linted, debugged, and edited individually.
 */
async function loadModulesApp() {
    console.log('[Thomas] Loading app modules (modernized architecture)...');

    try {
        // Import all modules dynamically
        const baseUrl = new URL(import.meta.url);
        const modules = await Promise.all(
            MODULE_FILES.map(file => import(new URL(file, baseUrl).href))
        );

        console.log(`[Thomas] Loaded ${modules.length} modules successfully`);

        // Modules execute their code directly (they contain function definitions, state, etc.)
        // All functions/variables are automatically in the global scope
        return true;
    } catch (error) {
        console.error('[Thomas] Failed to load modules:', error);
        throw error;
    }
}

// Execute immediately
await loadModulesApp();
