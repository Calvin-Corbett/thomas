# Autopoietic (Level 5) For Thomas

**Autopoietic** means Thomas can improve itself over time in a way that is:
- **User-serving**: changes exist to improve the user experience, reliability, or capability.
- **Efficient**: improvements can include removing code, deleting features, or consolidating systems when that reduces complexity.
- **Scoped**: Thomas prefers changing the smallest subsystem required, not rewriting large swaths of the project.
- **Verified**: changes are proven by tests and smoke runs, not guesses.
- **Versioned**: every behavioral change increments the version and is recorded in the changelog.
- **Deployable with rollback**: changes can be adopted safely and reversed quickly if needed.

## Autopoietic Does Not Mean

- Editing live running code in-place when that edit can break the running system.
- Blindly adding dependencies, abstractions, or new "frameworks" that increase complexity.
- Growing features without pruning or consolidation.

## Practical Requirements

When Thomas modifies Thomas:
- It must classify change risk (see `definitions/change-classification.md`).
- For breaking/risky changes it must follow the Doppelganger Protocol (see `definitions/doppelganger-protocol.md`).
- It must update:
  - `pyproject.toml` version
  - `thomas/__init__.py` version
  - `CHANGELOG.md` entry

## Success Metrics (Simple)

- Fewer incidents where the UI "boots but is dead".
- Faster time-to-fix for bugs (better diagnostics, clearer logs).
- Fewer duplicated implementations for the same thing.
- Clearer UX around models, providers, and keys.

