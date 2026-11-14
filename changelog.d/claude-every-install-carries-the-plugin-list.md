### Fixed

- **A released Thomas now has its plugins.** The list of plugins sat beside the package, so a release bundle, a Docker image and a copy made by `install.cmd`, `install.sh` or `pip install` all started without it. With no list no plugin loads, so the Companion apps, the version pile-up check and the goal routes were missing from those installs and answered 404, and the Plugins page had nothing to turn back on. The list now lives inside the package, so every way of installing Thomas carries it.
