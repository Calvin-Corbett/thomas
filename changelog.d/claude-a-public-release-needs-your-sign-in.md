### Added

- **A public release can be previewed, then sent to GitHub as a review branch, and only after you sign in with Windows for that exact preview.** The preview builds the public tree in a scratch copy, leaves out the files in `docs/ops/public_exclude.txt`, and runs the publish checks on it, so you see the version, the file counts, each private file left out with its reason, and every check before anything leaves the machine. Publishing makes one commit on top of the public `main` and pushes it to `release/<version>-<date>`. It never writes to `main`, never forces a push, never changes branch protection, and says plainly whether the commit is signed.

### Removed

- **Three leftover run files are gone from the repo root.** `importers.json`, `run.json` and `reservations.json` were committed by accident and nothing read them, and they counted against the root file limit.
