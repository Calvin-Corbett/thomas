### Fixed
- The stale-run janitor now sweeps the run store on another thread. A freeze dump from 2026-10-27 caught the server's event loop inside that sweep, and every request waited while the disk was busy.
