/**
 * Thomas Runtime Loader
 * Loads split runtime scripts in order, ensuring each completes before the next.
 * All scripts share global scope so they can access each other's variables.
 */
(function () {
    'use strict';

    var RUNTIME_SCRIPTS = [
        '001_preamble.js',
        '002_virtual_office_data.js',
        '003_easy_setup_onboarding_01.js',
        '004_easy_setup_onboarding_02.js',
        '005_easy_setup_onboarding_03.js',
        '006_easy_setup_onboarding_04.js',
        '007_easy_setup_onboarding_05.js',
        '008_easy_setup_onboarding_06.js',
        '009_initialization_composer.js',
        '010_chat_games_01.js',
        '011_chat_games_02.js',
        '012_actions_interactions_01.js',
        '013_actions_interactions_02.js',
        '014_actions_interactions_03.js',
        '015_debug_dock.js',
        '016_session_chat_persistence.js',
        '017_virtual_office_01.js',
        '018_virtual_office_02.js',
        '019_virtual_office_03.js',
        '020_virtual_office_04.js',
        '021_virtual_office_05.js',
        '022_virtual_office_06.js',
        '023_mission_control_01.js',
        '024_mission_control_02.js',
        '025_module_system_command_center_01.js',
        '026_module_system_command_center_02.js',
        '027_module_system_command_center_03.js',
        '028_module_system_command_center_04.js',
        '029_workbench_editors_01.js',
        '030_workbench_editors_02.js',
        '031_workbench_editors_03.js',
        '032_workbench_editors_04.js',
        '033_workbench_editors_05.js',
        '034_workbench_editors_06.js',
        '035_workbench_editors_07.js',
        '036_workbench_editors_08.js',
        '037_workbench_editors_09.js',
        '038_module_rendering_dispatch_01.js',
        '039_module_rendering_dispatch_02.js',
        '040_model_setup_settings_01.js',
        '041_model_setup_settings_02.js',
        '042_model_setup_settings_03.js',
        '043_model_setup_settings_04.js',
        '044_model_setup_settings_05.js',
        '045_model_setup_settings_06.js',
        '046_evolution_dashboard.js',
        '047_evolve_agent_chat.js',
        '048_ui_studio_canvas.js',
    ];

    var basePath = '/static/js/runtime/';
    var loaderEl = document.querySelector('script[src*="app_runtime_loader"]');
    var cacheBust = loaderEl ? (loaderEl.src.split('v=')[1] || '') : String(Date.now());

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            var el = document.createElement('script');
            el.src = basePath + src + '?v=' + cacheBust;
            el.async = false;
            el.onload = resolve;
            el.onerror = function () {
                reject(new Error('Failed to load runtime script: ' + src));
            };
            document.head.appendChild(el);
        });
    }

    function bootstrapRuntime() {
        return new Promise(function (resolve, reject) {
            window.setTimeout(function () {
                try {
                    if (typeof window.__thomasBootstrapApp !== 'function') {
                        throw new Error('Runtime bootstrap function was not registered.');
                    }
                    window.__thomasBootstrapApp();
                    resolve();
                } catch (error) {
                    reject(error);
                }
            }, 0);
        });
    }

    window.__thomasRuntimeReady = (async function () {
        console.log('[Thomas] Loading ' + RUNTIME_SCRIPTS.length + ' runtime modules...');
        var t0 = performance.now();
        for (var i = 0; i < RUNTIME_SCRIPTS.length; i++) {
            await loadScript(RUNTIME_SCRIPTS[i]);
        }
        var elapsed = Math.round(performance.now() - t0);
        console.log('[Thomas] All ' + RUNTIME_SCRIPTS.length + ' runtime modules loaded (' + elapsed + 'ms)');
        await bootstrapRuntime();
    })();
})();
