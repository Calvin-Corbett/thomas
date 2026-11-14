### Fixed
- `self_improvement_planner.scan` collects evidence and probes wider-discovery capacity outside the queue transaction, avoiding nested acquisition of the queue/ledger's shared mutex. Wider proposals recheck the current enabled setting, queue emptiness, and duplicate history before booking.
- Regression tests exercise ledger reads from discovery callbacks and concurrent queue changes without changing capacity-ledger locking. This is a separate planner defect, not the run-receipts event-loop freeze fixed in `fb8847e6`.
