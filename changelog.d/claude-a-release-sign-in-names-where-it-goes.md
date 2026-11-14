### Fixed

- **Your sign-in for a public release now covers where it goes, not only what goes.** The preview names the remote, the address it stands for (with any password left out) and the branch, and your sign-in confirms all three together. Publishing sends only to the address in that preview and refuses if the remote was renamed or pointed elsewhere since, if the branch already exists, or if the branch is not named `release/...`.
