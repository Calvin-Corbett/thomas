### Removed

- Removed six Evolve split modules imported only by one another; the active session entry point continues to re-export implementations from `evolve_blue_green`, `evolve_arch_sync`, `evolve_charter`, and `evolve_prompts`.
- Removed the unregistered CLI Telegram command module; the registered Telegram command continues to call `main_runtime_ops.telegram_run_cmd` through `main_chatops`.
- Removed the unreferenced `tools/helper_v2.py` comment-only file.

### Changed

- Updated the CLI status note to point to the registered Telegram command path.
