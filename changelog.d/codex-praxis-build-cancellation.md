### Fixed

- Stopping a Chat task backed by Build now terminates its linked Build run and records the task as cancelled. The internal stop resolves the exact run ID so another active project is unaffected.
