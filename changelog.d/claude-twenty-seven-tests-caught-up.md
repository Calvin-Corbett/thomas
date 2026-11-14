### Fixed

- **27 tests that had fallen behind the code pass again.** They failed on committed
  `dev` itself, not only in a busy checkout. Each followed a deliberate change its tests
  never learned about:
  - A lead worker may spawn a helper agent (`task.spawn`, 30fc8915). Stand-in tool
    registries in `test_agent_worker_parity.py` had no `register`; they are now the real
    `ToolRegistry`.
  - A stream that ends without a finish is an error, not "done" (9524a23f). A worker
    comment still promised a "compatibility done" and now says what happens.
  - The role-model reader moved to `thomas.preferences.model_prefs`.
  - GPT Build runs need the ChatGPT sign-in before they start. The project-isolation
    tests stub it.
  - Raising file access or autonomy needs a verified Windows sign-in (5213bb30). The
    Build route and self-edit tests grant it the way a sign-in would, and the self-edit
    test proves it still refuses wide access once granted.
  - A self-edit names its exact files (07bdda37). The Redesign guard test now opens its
    thread through the route with a scope.
