### Fixed

- Plugins: turning a plugin off holds up when two stops overlap or a cleanup gets stuck. Stop now ends a stuck cleanup after 10 seconds and the rest still run, and a plugin that others depend on waits for them first.
