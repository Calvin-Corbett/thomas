### Fixed

- **A file you ask Thomas to delete is no longer counted as a missing output.** The completion gate is rebuilt each turn, and it read any path named in the request that was missing from disk as an output the task would create. So a team asked to delete generated filler, which it did, was blocked on the next turn by "`scripts/generate_gap_assets.py` exists and is non-empty when the work is done". A named path that is in the project's last commit is now read as a file the task refers to, never one it must create; a new path is still an output.
