### Changed

- **Outside code reaches the checks code through its packages' own names.** 38 imports in 16 files reached into `thomas/server/precard` and `thomas/server/proof` directly. They now take what they need from the two packages, and `handover._moved`, which was being called from outside, is public as `moved`. Nothing changes what this code does.
