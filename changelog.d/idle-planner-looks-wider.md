### Changed

- When automatic project discovery has capacity, an empty queue, and no bookable result from its regular scan, it also considers slow tests and intermittent failures from recent JUnit reports, repeated errors in the configured server log or local logs, and repeated slow HTML responses for known pages. These candidates use the existing queue deduplication and planner off switch; log message contents are not copied into project requests.
- The server logs the path and elapsed time of HTML page responses that take at least two seconds, without logging query strings or page content.
- The queue-start test waits for its start tasks to complete rather than relying on a fixed 50 ms delay.
