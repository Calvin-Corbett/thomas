### Added

- Added a dormant Express landing referee under `scripts/cage/referee`, with its offline test lab under `tests/express_*.py` and `tests/test_express*.py`. It decides whether a small, charter-eligible change may land without a full card, keeps a hash-chained ledger of every decision, and halts itself on any doubt.
- It is off by default and nothing turns it on: no server, launcher, route or setting imports it, so landing behaves exactly as before. Turning it on needs a separate, explicit step from you.
- Added the referee's writer, git session, hand-off, leases, halt and recovery modules, with their simulated-world tests.
- Added the referee's grant, policy, caps, switch, authority and named-pipe channel modules, with their tests. Switching Express on stays a step you take.
- Added the referee's intake, landing, service loop and entry point, with offline service, scale and round-two tests.
