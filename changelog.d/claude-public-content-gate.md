### Added
- **A public release is now checked for internal content before it ships.** The new `scripts/forge/publish/content_check.py` reads the source tree and the built packages, refuses board messages, board task ids, citations of unpublished design records, personal machine paths and working folders such as `plans/` and `.thomas/`, and says for each refusal what to change. It runs on pushes and pull requests to the public `main` branch (`public-content.yml`) and in the PyPI publish job, so you see a problem before a release goes out.

### Fixed
- **The publish snapshot no longer puts back the files it was told to leave out.** After filtering, it copied whole folders (`docs`, `scripts`, `tests`, `thomas` and others) a second time, which undid both the strip list and the private markers. It now copies only the filtered files, and the strip list grows from 3 to 21 entries, covering every folder the content check refuses.
- **The publish safety workflow listens for `main` instead of `prod`.** Dev's copy waited for a `prod` branch that does not exist, so a release built from dev would have stopped the preflight and leak guard running on the public branch.
