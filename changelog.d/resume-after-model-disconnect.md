### Fixed
- Autopilot now parks a failed project after a dropped model connection or expired sign-in, then starts another run when the pause ends.
- Provider-trouble pauses keep retrying through repeated failures and refused starts instead of exhausting their attempt limits. Retry delays stay bounded during long outages.
