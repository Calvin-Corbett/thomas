### Fixed

- Your window records a required revert before releasing a failed after-check. If another undo is busy, the revert waits durably and resumes when the undo finishes. Restarting the promoter restores pending or interrupted reverts; completed and cancelled attempts remain recorded and do not restart.
