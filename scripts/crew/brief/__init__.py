"""Praxis.Crew.Brief -- agent lifecycle (startup, briefing, presence).

Startup router, briefing, presence/identity broker, session report,
preflight, safety-init, bootstrap-claim. Renamed from
``scripts/agent_*.py`` to align with Praxis vocabulary.

NOTE: ``scripts/agent_commit.py`` still lives at the legacy path (Tier 5
relocation pending — most-referenced file in the repo). ``agent_safety_config``
and ``agent_identity`` have been moved here as ``safety_config.py`` and
``identity.py``.
"""
