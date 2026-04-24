# Prompt Pack Test Stubs

This folder holds prompt-owned regression tests for CLI, gateway, browser, and plugin capabilities.

Naming convention:
- `test_pNNN_<slug>.py`

Each prompt-owned test should validate:
- success path
- invalid input path
- stable output contract (especially JSON shapes where applicable)
