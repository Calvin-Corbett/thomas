### Changed
- Scratch checkouts now materialize files only once at dev's target tip; the free-space compatibility constant is documented as a reserve bound, not the full admission threshold.
- Pre-card checks now make the patched scratch checkout first and create an unpatched dev checkout only when a failing test, lint finding, or format finding needs comparison. Both checkouts are removed after the check.
- Disk admission keeps a drive-sized reserve (at least 512 MiB, up to 2 GiB) instead of requiring 10 GiB free for every check. Serial checks require room for both the reserve and their estimated writes before making a scratch checkout.
