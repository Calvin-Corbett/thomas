### Changed

- Separate Chat model controls, history, messages, activity, canvas, media and theme behavior into focused factories with explicit shared-state dependencies, preparing the consolidated page without changing the existing entry point.
- Extract Build transcript rendering and run-stream ownership into focused modules. Keep the existing lifecycle and queue adapters compatible while their callers are rewired.
