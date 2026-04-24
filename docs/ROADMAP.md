# Thomas Roadmap

This roadmap is public direction, not a promise that every item is already
available. For current feature status, use `docs/FEATURE_MATRIX.md`.

## Now: Public Release Usability

Goal: make Thomas easy to download, install, diagnose, and understand.

- Keep the Windows installer as the recommended public install path.
- Keep first-run setup understandable to non-engineers.
- Improve issue templates so install failures include logs and environment
  details.
- Keep public release safety gates strict.
- Keep the README, feature matrix, repo map, and agent onboarding docs current.
- Make the support bundle the normal first response for install/startup bugs.

## Next: Everyday Product Reliability

Goal: make the default Thomas experience feel reliable before pushing users into
advanced builder paths.

- Tighten Easy Setup copy and error recovery.
- Add more guided model/provider repair flows.
- Improve Mission Control visibility for long-running work.
- Make memory and automation controls easier to understand.
- Keep Evolve mode guarded and explain when it should be used.
- Add more public examples for tools, browser automation, and local workflows.

## Phase 02: Infinite App

Goal: build a private mobile companion for Thomas.

Planned product shape:

- Mobile companion for iOS, Android, and web-style companion surfaces.
- Private connectivity over Tailscale or equivalent owner-controlled network.
- Direct chat with the local Thomas runtime without needing chat-platform bridges.
- Approval queue, job status, notifications, and focused dashboards.
- app-grid/home-screen area where Thomas-built app surfaces appear as icons.
- Launchable app-like experiences that Thomas builds, hosts, and runs locally.
- Local/headless browser execution where the phone is a control and viewing
  surface, not the authority that executes arbitrary code.

Security and store-safe boundaries:

- Thomas remains the execution, policy, and audit authority.
- The mobile app renders approved declarative surfaces and talks to the
  companion API.
- Remote updates must use the signed module pipeline and rollback controls.
- Store builds must respect the compliance rules in
  `docs/COMPANION_BUILDER_RELEASE_GUIDE.md`.

Relevant docs:

- `docs/THOMAS_INFINITE.md`
- `docs/COMPANION_APP_INTEGRATION.md`
- `docs/COMPANION_PLATFORM_SCOPE.md`
- `docs/COMPANION_BUILDER_RELEASE_GUIDE.md`

## Phase 03: Thomas OS Concept

Goal: explore an OS-level environment built around the Thomas model of local
execution, guarded tools, personal apps, memory, and private companion surfaces.

Current status: concept only.

Open questions:

- What should Thomas OS own that Thomas Core and Infinite cannot own cleanly?
- Which parts need to be Linux distribution work versus application shell work?
- How should local app execution, permissions, storage, updates, and rollback be
  isolated?
- What must be proven in Thomas Core and Infinite before OS work is responsible?

Do not treat Thomas OS as a current deliverable. The responsible sequence is to
stabilize Thomas Core, prove Infinite, then define a real technical plan.
