"""Praxis.Crew.Brief -- agent lifecycle (startup, briefing, presence).

Startup router, briefing, presence/identity broker, session report,
preflight, safety-init, bootstrap-claim. Renamed from
``scripts/agent_*.py`` to align with Praxis vocabulary.

NOTE: ``scripts/agent_commit.py``, ``scripts/agent_safety_config.py``
remain at the original repo-root location because they are listed in
``agent_safety.toml`` enforcement_scripts (protected). ``scripts/
agent_identity.py`` also remains because it is imported by the protected
``agent_commit.py``; a future protected-files relocation session will
handle all three.
"""
