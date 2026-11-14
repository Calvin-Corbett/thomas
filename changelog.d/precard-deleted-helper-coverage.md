### Fixed

- Seed test selection from changed helper paths even when those files were deleted. Keep their bare, absolute, and relative importers, including transitive importers, in the selected set or explicitly reported overflow.
- Exercise deleted-helper selection through both supplied source text and a surviving on-disk checkout. Removing the changed-helper seed in a disposable selector copy fails all three on-disk regression cases; the intact selector passes them.
- Keep bare and package-qualified importers of nested test helpers, including transitive importers after deletion. Removing nested bare aliases in a disposable selector copy fails 36 regression cases; restoring them passes.
- Recognize conventional `src/` production-module names when selecting direct and transitive importers, including deleted modules and reported overflow. Removing those aliases in a disposable selector copy fails 12 regression cases; restoring them passes.
