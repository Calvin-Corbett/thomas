### Added

- **The kernel can now stop a plugin cleanly.** A plugin owns the background work it starts, and turning it off lets running work finish first, with the plugins that depend on it stopping before it does. A plugin that fails keeps the failure to itself and reports why. Nothing you can see changes yet: this is the base for turning parts of Thomas off and on while it runs.
