### Fixed

- Build's first, verification-fix, and contract-continuation briefs now identify a known per-pass limit under a Build pass clock heading. They tell the builder to start long tests early, stop waiting when a test will not finish in time, and report what remains unrun. Both dispatchers pass their timeout into the first brief and fix and continuation passes; prompts omit the clock note when no positive limit is supplied.
- The configured-runner shell comment now describes Guarded shell access under the cage account as well as Open shell access.
