# UI Checklist

- Confirm source edits are under `thomas/server/web/js/src/` or other source files, not generated output.
- Confirm `thomas/server/web/js/app.js` still boots only `app_runtime_primary.mjs`.
- If a UI surface replaces an older one, delete or disconnect the older route,
  runtime, and demo backend in the same change.
- Marketplace must read the live companion APIs only:
  `/api/companion/v1/app-store` and `/api/companion/v1/modules`.
- Run targeted UI runtime guards such as `python -m pytest tests/test_ui_editor_rescue_surface.py tests/test_product_surface_copy.py -q`.
- Run visual/runtime checks relevant to changed UI routes.
- Ensure no new monolith violations in source files.
