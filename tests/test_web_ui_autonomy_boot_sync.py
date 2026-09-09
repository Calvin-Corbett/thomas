from __future__ import annotations

import re

from tests.web_ui_source import read_app_js_source


def test_web_ui_refresh_identity_syncs_active_autonomy_level() -> None:
    app_js = read_app_js_source()

    refresh_fn = re.search(
        r"async function refreshIdentityState\(\)\s*\{[\s\S]*?\n\}",
        app_js,
    )
    assert refresh_fn is not None

    block = refresh_fn.group(0)
    assert "currentPreferences = await prefsRes.json();" in block
    assert "prefAutonomyRaw" in block
    assert "const prefAutonomy = Number.parseInt(prefAutonomyRaw, 10);" in block
    assert "activeAutonomyLevel = Math.max(1, Math.min(4, prefAutonomy));" in block
    assert "if (settingAutonomy) settingAutonomy.value = `L${activeAutonomyLevel}`;" in block
