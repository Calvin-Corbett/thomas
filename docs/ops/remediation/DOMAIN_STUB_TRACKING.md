# Domain Skeleton Tracking

These suites currently target intentional product-scope domains whose runtime
behavior is still in skeleton state.

Policy:
- Imports must keep working.
- Runtime placeholders may raise `NotImplementedError` when called.
- Tests are marked `xfail` (not skipped silently) until implementations land.

Tracking scope:
- Agriculture: `tests/test_ag_*.py`
- Supply Chain: `tests/test_supply_chain_*.py`
- Group Chat: `tests/test_groupchat.py`
- Human Loop: `tests/test_human_loop.py`
- Learning: `tests/test_learning.py`
- Sandbox: `tests/test_sandbox.py`
- Travel: `tests/test_travel_*.py`

Exit criteria to remove `xfail` markers:
1. Module APIs are implemented (not skeleton placeholders).
2. Behavioral tests pass without xfail.
3. `docs/ai/FEATURE_REGISTRY.md` statuses are updated from `skeleton`.
