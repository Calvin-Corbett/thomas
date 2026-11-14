### Added

- **Everything Thomas is and runs now belongs to the kernel or to one of 35 plugins.** `scripts/plugins/carve.py` holds the map and generates each plugin's manifest from the code as it stands. A new test fails on any file in a code folder that no plugin claims, and every full check now runs it with the fence and the door, so a new crossing between plugins cannot land without a manifest saying so. This changes nothing about how Thomas behaves, and being carved is not yet being independent: 19 plugins still reach most of the repo, and those imports are the next thing to cut.
