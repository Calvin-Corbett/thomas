# Thomas Infinite

Last updated: 2026-03-18

Thomas Infinite is the Infinite app: Thomas's companion app for Phase 02.
Thomas Infinite is a companion app, not the full Thomas runtime.

It is a private mobile companion connected to Thomas over Tailscale.
It is where Thomas can send focused browser-driven surfaces, status views,
approval queues, and custom app experiences to your phone while Thomas remains
in charge of execution, policy, and audit.

## Canonical Definition

Thomas Infinite is a companion app with a phone-within-a-phone feel:
- a mobile app connected privately to Thomas over Tailscale
- with a built-in browser/runtime for Thomas-delivered surfaces
- where users can open, arrange, and use Thomas-built app experiences
- while Thomas itself stays the real brain, runtime, and authority

Infinite is Phase 02.
Thomas OS is Phase 03.
Do not treat them as the same thing.

## What Infinite Is

- The Thomas companion app.
- The private mobile surface for Thomas-built apps, dashboards, and approvals.
- The bridge between Thomas as a local execution system and Thomas as a broader computing environment.
- The proving ground for generated app surfaces before Thomas OS exists.

## What Infinite Is Not

- Not Thomas OS.
- Not Thomas itself.
- Not a public-cloud bypass around Thomas.
- Not a separate execution authority.

## Product Shape

The intended user experience is:
- talk to Thomas normally
- ask Thomas to do something or build something
- Thomas can prepare a focused app-like surface for that job
- Thomas can push that surface to Infinite
- the user can open it inside the Infinite app like a personal tool

The planned home-screen model is:
- Infinite has a chat area for talking directly with the local Thomas runtime
- Infinite has an app-grid area with icons for Thomas-built app surfaces
- tapping an icon opens a focused app-like surface
- Thomas keeps the app running locally, including browser-driven execution when
  that is the safest prototype path
- the phone is the private control/viewing surface, not the authority that
  executes arbitrary code

The important framing is that Infinite is still a companion app.
It is just a much more capable companion app than a normal remote-control client.

## Why It Matters

Phase 01 proves Thomas Core can execute safely and coherently.
Phase 02 turns that into the Infinite app: a private mobile companion where Thomas can deliver app-like experiences.
Phase 03 is the end goal: Thomas OS, where the whole operating environment is built around those ideas from the start.

## Relationship To Thomas OS

Infinite is the path to Thomas OS, not the replacement for it.

If Infinite works, Thomas proves it can:
- generate and ship focused surfaces
- keep one trust boundary across devices
- make software feel personal and on-demand

The privacy goal is that useful app experiences can move between the local
Thomas host and the user's phone without making public cloud hosting the default
runtime assumption.

Thomas OS is the bigger destination where those ideas stop living in one companion app and start shaping the whole machine.
