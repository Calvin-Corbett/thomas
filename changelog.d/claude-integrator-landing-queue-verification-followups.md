### Fixed

- **Pruning the landing queue no longer crashes when a reader has a file open.** On Windows that made `land.py` die before it took a ticket and could leave finished tickets looking open again. The prune now deletes tickets first, skips any file it cannot delete, and a housekeeping failure never stops a landing.
- **A holder can no longer restart its own lease** by writing another `granted` line, and `land.py --status` counts commits that bypassed the queue from the oldest open ticket, not the youngest.
- **The briefing now says exactly what keeps your place:** after `--submit` a worker does; a plain `land.py --message` that is killed with its processes loses its ticket, and so does a `--submit` whose tool kills its whole job. It also says that `--submit` exits 0 while the change is not landed yet.
