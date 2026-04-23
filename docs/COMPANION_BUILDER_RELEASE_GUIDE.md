# Companion Builder Release Guide (Store-Safe)

Last updated: 2026-02-20

This guide is the execution playbook for building and shipping companion app updates from Thomas without breaking App Store/Play policy boundaries.

## 1) What Thomas Can Change

Allowed:
- Declarative UI payloads (`screen.json` + assets).
- Module routing/layout, text, media, workflows, and release rollouts.
- Capability-gated behavior that maps to native features already inside the shipped mobile binary.

Not allowed:
- Downloaded executable code or dynamic native bridges.
- Remote mutation of app identity/signing/update rail.
- Policy bypasses for payments, moderation, privacy, and age-gating requirements.

## 2) Required Inputs Before Ship

For every release candidate, set:
- `platform` (`ios|android|web|desktop`)
- `distribution_channel` (`app_store|play_store|testflight|enterprise|internal`)
- `storefront_region` (for example `US`)
- `commerce_model` (`digital_in_app|physical_or_off_app|enterprise_internal`)
- `runtime_capability_set`

Hard blocker:
- Production store profiles (`ios_app_store`, `android_play_store`) now fail compliance when any of `platform`, `distribution_channel`, or `storefront_region` is missing.

Optional but recommended:
- `policy_profile_id` (explicit profile lock)
- `url_allowlist`

## 3) Compliance Engine (Now In Thomas)

Thomas now ships with:
- Versioned policy profiles in `thomas/companion/policy_profiles/*.json`.
- Profile resolution from platform + distribution + region.
- Pre-ship compliance gate integrated into:
  - `POST /api/companion/v1/compliance/check`
  - `POST /api/companion/v1/releases/publish`
  - `POST /api/companion/v1/ship`

Ship/publish is blocked when blocking violations exist.

## 4) High-Risk Checks Enforced

- Disallowed module permissions per profile.
- Disallowed/unsafe URL schemes (`javascript:`, `file:`, `data:`, etc.).
- Webview URL policy checks (HTTPS and domain controls where configured).
- Blocked executable/script artifacts in update bundles.
- Store billing requirement for `digital_in_app` on store profiles.
- UGC moderation controls + age-gate requirement when UGC is enabled.
- Privacy policy requirement when personal data collection is declared.

## 5) Recommended Release Workflow

1. Build bundle from Studio.
2. Run `compliance/check` with target store context.
3. Fix all blocking violations.
4. Run verify/preview.
5. Ship with staged rollout (start low, then promote).
6. Monitor audit + runtime telemetry.

## 6) Builder UI Usage

Use `/companion` and fill these sections before ship:
- Store target (`platform`, `distribution_channel`, `storefront_region`, optional profile override).
- Capability + commerce + UGC/privacy fields.
- Compliance Check button.

The Compliance Report panel is source-of-truth for release readiness.

## 7) Integration Rules For Mobile Team

Mobile app must:
- Register device identity with distribution context.
- Send heartbeat with capability set and app build id.
- Render only host-approved declarative payloads.
- Never execute downloaded code.

## 8) Agent Handoff Contract

If another coding agent continues this project, they must start from:
- `plans/thomas/companion/STORE_COMPLIANCE_PLAN.md`
- `docs/COMPANION_APP_INTEGRATION.md`
- `docs/COMPANION_BUILDER_RELEASE_GUIDE.md`

Then run:
- `python scripts/check_plan_structure_gate.py`
- `python scripts/check_release_hygiene.py`

## 9) Minimum Launch Bar

Do not ship if any is true:
- Blocking compliance violations remain.
- Unknown target store context with no explicit strict profile acceptance.
- UGC enabled without report/block/terms + age-gate.
- `digital_in_app` without store billing on App Store/Play profiles.
- Privacy URL missing while personal data collection is enabled.
