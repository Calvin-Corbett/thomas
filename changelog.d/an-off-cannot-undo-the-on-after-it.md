### Fixed

- **Turning a plugin on just after turning it off now sticks.** When the two presses landed a few milliseconds apart, from a second tab or a script, and the plugin was already off, the off could finish last and stop the plugin you had just turned on. It then read off while saved as on, so it came back at the next restart. An off that finds nothing running now only saves your choice.
