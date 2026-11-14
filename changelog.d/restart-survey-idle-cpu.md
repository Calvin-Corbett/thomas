### Fixed

- Restart surveys visit all conversations before retrying read failures, so 126 unreadable records are skipped and named in the log after three surveys rather than blocking recovery one record at a time.
- Retry surveys reuse parsed conversations when their file's modification time and size are unchanged, invalidate changed files, and release the cache after a successful survey.
- The thread sampler counts blocking `psutil.cpu_percent` measurements, including the load meter's sleep, as waiting rather than busy; nonblocking measurements remain busy.
