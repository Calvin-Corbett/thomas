Original prompt: make me agame

## Progress

- Added a standalone browser game under `demo/circuit-courier`.
- Implemented canvas rendering, keyboard controls, scoring, win/lose states, deterministic stepping, and text-state export.

## Test Notes

- Run with a local static server from this folder.
- Exercise start/restart, movement, dash, packet collection, hazard collision, win and loss states.
- 2026-06-14: `node --check demo/circuit-courier/game.js` passed.
- 2026-06-14: Playwright smoke run passed against `http://127.0.0.1:8765/`; screenshot at `output/circuit-courier-smoke/shot-0.png`.
- 2026-06-14: Playwright collection run passed; `state-0.json` showed score 180, collected 1, packets remaining 5, matching the screenshot.
- 2026-06-14: Final smoke run after favicon fix passed; screenshot at `output/circuit-courier-final-smoke/shot-0.png`.
- 2026-06-14: Final collection run after favicon fix passed; `output/circuit-courier-final-collect/state-0.json` showed score 180, collected 1, packets remaining 5.

## TODO

- Manual route tuning could make a full six-packet speedrun easier, but no functional blockers are known.
