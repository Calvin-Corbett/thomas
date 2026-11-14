### Fixed

- Follow explicit imports of `conftest.py` as well as its fixture scope when selecting covering tests. Deleted conftests seed the import graph; conftests reached through production imports or asset references propagate to their direct and transitive importers.
- Retain these importers in the selected files or reported overflow. The selection regressions pass with the fix; restoring both conftest exclusions in a disposable selector makes the deleted-helper, production-dependency, and asset-dependency probes fail.
