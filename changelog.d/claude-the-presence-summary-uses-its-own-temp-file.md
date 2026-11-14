### Fixed

- **The repo presence summary no longer shares one temporary file between writers.** `collect_presence` wrote `repo-summary.json` through a fixed `.tmp` name, so two agents collecting presence at once could fail with a permission error (`presence gate failed`). It now writes through the same unique-temp, retrying writer as session presence.
