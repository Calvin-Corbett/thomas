### Changed

- The public repository leak guard now says what a PASS covered. Without your local blocklist (a fresh clone, or CI) it reports "PASS (path rules only)" and says the substring rules were not loaded, instead of printing the same PASS as a full check. `--require-blocklist` makes such a run fail.

### Security

- **The public-release content check is integrity-checked.** `scripts/forge/publish/content_check.py`, which the publish and public-content workflows run on the public source tree and the built distributions to find internal content, is now in `enforcement_scripts` and hashed in `enforcement_manifest.json` like `preflight.py`, so a rewrite that passed everything is caught instead of silently emptying the check.
