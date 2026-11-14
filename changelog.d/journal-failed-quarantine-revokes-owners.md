### Fixed

- Detecting journal damage now revokes existing owners under the shared per-run lock before quarantine attempts to rename the file. A failed rename leaves those owners unable to execute work, append records, change summaries, or return cached results; unrelated runs remain usable.
- Six regression cases cover a permission-denied quarantine rename followed by attempts to start, finish, close, resume from cache, run work, or mark a step unknown. All six fail with invalidation delayed until after a successful rename and pass with invalidation at damage detection.
