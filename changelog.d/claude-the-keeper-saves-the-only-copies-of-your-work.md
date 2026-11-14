### Added

- `scripts/keeper/capture.py`, the keeper's capture tool. It saves the only copies of your work (a Build team's copy, a scratch clone, a folder) into the keep at `C:\ProgramData\ThomasKeep`, which only ever grows: each capture is created once and never overwritten. It reads git places through an isolated view, refuses links and junctions, stops before the drive drops under its free-space floor, and checks that a place did not change while it was read. On 2026-10-09 it made 1,237 captures (1.7 GB), and a restore drill brought back byte-identical files.
