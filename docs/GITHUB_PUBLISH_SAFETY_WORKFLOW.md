# Public release workflow

The public repository contains a curated product distribution. Development records belong in local or private workspaces.

1. Start from a reviewed source revision and record its identity privately.
2. Build a filtered snapshot with `scripts/forge/publish/snapshot.py`; do not overlay unfiltered directories afterward.
3. Run `python scripts/forge/publish/content_check.py --root .` in the candidate tree.
4. Run applicable lint, focused regression tests, and an installation/server smoke check.
5. Build source and wheel distributions with `python -m build`.
6. Run the content check against the built archives using `--archives dist`.
7. Publish only the reviewed candidate and its verified distributions through repository protections.

Public documentation should describe the product, installation, support, and contribution process. Populated agent boards, task records, conversation transcripts, historical QA output, and personal data must not be published.

The checks supplement review. They do not certify arbitrary screenshots or prose as free of personal information.
