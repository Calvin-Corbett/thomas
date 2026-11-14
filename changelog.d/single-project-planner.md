### Fixed
- Only the caged server's automatic park tick scans, claims, and starts queued Thomas projects; the desktop server does not run that tick. The caged worker also processes projects queued by the desktop server and reconciles their interrupted starts.
- `/api/health` keeps the commit captured when its server application started and reports a separate `latest_commit` and `stale` flag when the checkout has moved.
- The chat build badge refreshes every 30 seconds and says to restart Thomas when its running build is older than the checkout.
