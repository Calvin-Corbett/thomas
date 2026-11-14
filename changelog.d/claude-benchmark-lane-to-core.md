### Changed

- **The benchmark lane lives in the core, because the agent loop reads it on every tool call.** `benchmark_lane` moved from `thomas/benchmarks/` to `thomas/core/`, so the loop no longer reaches into a package that can be switched off. Nothing about what it does changed for you.
