# Thomas Browser

Last reviewed: 2026-05-29.

`thomas.tools.browser` is the live browser runtime. It owns Playwright state,
sessions, navigation, extraction, screenshots, and browser lifecycle.

`thomas.browser` is the compatibility and contract package used by CLI browser
commands. It contains typed request/response contracts, JSON schemas, and
adapters that call the live runtime when available.

Do not add long-lived browser state to `thomas.browser`. If a change needs to
control a real browser, add the runtime behavior to `thomas.tools.browser` and
keep `thomas.browser` as the stable adapter surface.

## Active Paths

- Runtime: `thomas/tools/browser.py`
- CLI adapters: `thomas/cli/commands/browser/`
- Browser contracts: `thomas/browser/`
- Tests: `tests/prompt_pack/test_p0*_browser_*.py` and
  `tests/test_cli_production_assets_integration.py`

## Compatibility Rule

Browser command modules should resolve the runtime through
`thomas.browser.runtime_bridge`. That keeps the compatibility layer aligned with
the current runtime and avoids scattering direct imports of `thomas.tools.browser`
through new code.
