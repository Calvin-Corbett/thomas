### Added
- Save separate Build builder and reviewer models in the existing personal model preferences. The visible top picker remains the task manager and default model.
- Freeze helper model choices at dispatch, use the connected ChatGPT account without provider fallback, and report actual manager, builder and reviewer models in progress and receipts.

### Fixed
- Preserve per-role model choices through the browser request and action identity so different helper choices are not treated as the same action.
- Confirm saved model choices before updating the controls, with visible failure feedback.
