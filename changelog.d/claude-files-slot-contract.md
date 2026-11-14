### Changed

- **Path checks have one home, ready to move onto.** `thomas/tools/fs_scope.py` now holds the check that keeps a path inside its folder and the check that keeps the signing key unreadable, and both kernels carry it as the `fs` slot. Nothing calls it yet: you will see no change until the sites that test paths by hand move onto it. A new test pins what it refuses: `..`, a sibling folder that shares a prefix, a symlink, a junction and a path in different letter case.
