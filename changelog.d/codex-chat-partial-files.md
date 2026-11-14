### Fixed

- Recover unfinished files from failed or stopped Chat tasks as explicitly unverified downloads, keeping them separate from successful deliverables and clearing stale entries on retry.
- Recheck execution ownership and resolved file paths before listing or downloading unfinished files. Reject sibling-workspace junctions, hidden metadata aliases and replacement hardlinks, including saved links whose targets changed.
