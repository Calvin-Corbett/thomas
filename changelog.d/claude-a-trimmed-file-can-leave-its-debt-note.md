### Fixed

- **A change that trims a file can take it out of its debt note.** The hand-in size check told a team whose change brought a debt-listed file under 800 lines to take that file out of its note in `thomas/_architecture.py`, then read the note from the running copy instead of from the change, so the fix it asked for could never pass. The performance project did exactly that for `system_map.py` and `workspace_sync_engine.py` and was refused until its repair rounds ran out. The check now reads both size registers from the change's own copy, as its own description always said.
