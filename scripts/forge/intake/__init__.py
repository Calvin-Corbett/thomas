"""Praxis.Forge.Intake -- external code-drop intake pipeline.

Queue-state workflow (incoming -> staged -> applied | rejected) for
processing batches of code artifacts (unified diffs, feature packs, file
bundles) into the repo. Renamed from ``scripts/code_intake*.py`` to
align with Praxis vocabulary. The ``code_intake/`` directory at the repo
root remains the data store (queue states, reports, templates).
"""
