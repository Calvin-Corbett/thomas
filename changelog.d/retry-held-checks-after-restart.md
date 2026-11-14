### Fixed
- Held hand-in checks booked on an abandoned listener port can be retried by the restarted server after their due time, while rows belonging to a listening server remain untouched. A recovered interrupted check records the new port before its next retry; without optional psutil the listener probe checks both loopback families and leaves the row untouched when the probe is inconclusive.
- Download tracking's CLI test creates its file after the first snapshot without a timing race; Max-effort delegation's test waits for the chat handoff before asserting its result.
