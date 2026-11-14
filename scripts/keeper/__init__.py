"""The keeper: find work that lives in only one place and save it where nobody but you can change it.

v1 (P0.3 of the "nothing you worked on is stranded" design) is the capture tool alone: ``capture.py`` reads a place
through the Express referee's no-follow seam and isolated git view, writes each capture into the keep with exclusive
create only, restores a capture into a fresh folder, and records a place's state before and after so a run can prove
it changed nothing. It writes (the keep, its work folder, state files) only where ``private.py`` finds nobody but you
can read. Standard library only, plus ``scripts/cage/referee``.
"""
