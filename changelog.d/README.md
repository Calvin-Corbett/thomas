# changelog.d

One fragment per agent per change, so nobody edits anybody else's changelog
words and no commit has to carry the shared `CHANGELOG.md`.

- File name: `<agent>-<slug>.md`, lowercase, hyphenated (`claude-evolve-split.md`).
- Contents: one or more of `### Added`, `### Changed`, `### Fixed`, `### Removed`,
  `### Security`, each followed by bullets in the changelog's own style:
  `- **What changed, as a sentence.** Why, in one or two more.`
- Check yours: `python scripts/forge/changelog_fragments.py check changelog.d/<file>`
- At release: `python scripts/forge/changelog_fragments.py compile --version X.Y.Z`
  folds every fragment into `## [X.Y.Z]` grouped by section and deletes them.

This README is not a fragment.
