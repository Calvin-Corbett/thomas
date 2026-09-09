# Code Pruning (Removing Code On Purpose)

Autopoietic improvement includes removing code when it reduces complexity without reducing user value.

## When To Prune

- Two or more implementations exist for the same behavior.
- A feature is unused, half-finished, or replaced.
- A subsystem creates more bugs than value (and can be simplified).
- A dependency exists only for a trivial use case.

## How To Prune Safely

- Delete in Green first (Doppelganger Protocol for risky changes).
- Replace with a simpler implementation or remove entirely.
- Run tests and a smoke boot.
- Update docs and changelog explaining what was removed and why.

## Proof Checklist

- `pytest` passes.
- `thomas doctor` is clean enough to run the UI.
- UI loads and basic interactions work (send message, switch model, open settings).

