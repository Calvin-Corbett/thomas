# Companion Builder Store-Compliance Build Plan

Last updated: 2026-02-20
Owner: Thomas Companion Platform

## 1) Product Goal

Build an "infinite-feeling" companion app platform where:
- Thomas is the control plane and builder runtime.
- The phone app is a fixed native kernel + secure renderer.
- Remote changes are declarative content/workflows, not downloaded native executable code.

Success criteria:
- Fast creation loop (design -> preview -> ship) in Thomas.
- App Store / Play compliant by default.
- Unsafe user uploads and policy-risk payloads blocked before ship.

## 2) Non-Negotiable Architecture Rules

1. Immutable mobile kernel
- Native app binary contains all executable native capabilities.
- Thomas cannot push new native executable code.

2. Declarative remote payloads only
- Thomas ships signed module payloads (UI schema, workflow schema, assets, configs).
- No remote dex/JAR/.so/iOS executable or hidden self-updater path.

3. Capability broker boundary
- Remote modules call only whitelisted host capabilities through brokered APIs.
- No direct bridge to unrestricted native APIs.

4. Store-aware policy gating
- Every ship action is evaluated against target store policy profile(s).
- If device/store profile unknown, fallback to strictest policy.

## 3) Policy Baseline (As Implemented In Thomas Rules)

### Apple App Store profile
Rule anchors:
- 2.5.2: no downloaded code changing app functionality.
- 4.7.1-4.7.5: hosted software safety/moderation/privacy/index/age gating.
- 1.2 and 1.2.1: UGC + creator content moderation and bounded core experience.
- 3.1.1: digital unlocks/features require IAP unless exception applies.
- 5.1: privacy policy + data handling requirements.

### Google Play profile
Rule anchors:
- Device and Network Abuse: no self-update outside Play; no downloadable executable code from outside Play (VM/interpreter exception with policy constraints).
- UGC policy: robust reporting/blocking/moderation obligations.
- Payments policy: digital goods/features in app use Play Billing unless explicit exception applies.
- Data safety form/privacy policy obligations.

Note:
- Thomas policy engine must version these baselines and support updates without codebase-wide rewrites.

## 4) Thomas Compliance Control Plane Design

### 4.1 Device + Distribution Identity (required)
Add immutable registration fields:
- `platform`: ios | android | web | desktop
- `distribution_channel`: app_store | play_store | enterprise | testflight | internal | unknown
- `storefront_region`: ISO country/region (if available)
- `app_build_id`: immutable app build fingerprint
- `runtime_capability_set`: negotiated capability list
- `policy_profile`: resolved profile key (derived)

Resolution logic:
- server resolves `policy_profile` from `(platform, distribution_channel, storefront_region)`.
- unresolved -> `policy_profile = strict_global`.

### 4.2 Policy Profiles
Create `thomas/companion/policy_profiles/*.json` with:
- allowed component types
- forbidden component behaviors
- capability constraints
- payment/link-out rules
- moderation requirements
- age-gating requirements
- privacy disclosure requirements

Each profile has:
- `profile_id`
- `source_rules` (store clauses)
- `effective_from`
- `deprecation_date`
- `enforcement_level` (warn | block)

### 4.3 Pre-Ship Compliance Pipeline
Before `ship` finalizes, run:
1. Contract validation (schema/version/signature)
2. Capability validation (requested vs allowed for profile)
3. Content safety validation (UGC/assets/text)
4. Payments/link-out validation
5. Privacy/disclosure validation
6. Moderation-readiness validation

If any block-level failure:
- ship is rejected
- machine-readable violations returned with remediation hints
- audit event written

### 4.4 Runtime Enforcement (device-side + server-side)
At runtime:
- broker denies disallowed capability calls.
- renderer drops unsupported/forbidden module nodes.
- high-risk features require explicit user consent prompts.
- policy heartbeat can remotely disable violating module versions.

## 5) Hard Locks (What Thomas Must Never Allow Remote Modules To Change)

1. App identity/shell
- bundle id/package id, signing, update channel mechanism.

2. Native permission model
- no remote permission escalation outside declared host capabilities.

3. Payment rails plumbing
- no remote custom checkout for in-app digital goods where store billing required.

4. Security controls
- auth/session/token verification, certificate validation, integrity checks.

5. Moderation/report/block primitives
- cannot be removed by remote payload for UGC-enabled experiences.

6. Policy engine and kill switches
- always host-controlled and immutable by module payload.

## 6) UGC and Upload Safety Plan (Ban-Prevention)

### 6.1 Upload intake
For user-supplied text/images/video/links:
- malware/file-type validation
- MIME and magic-byte validation
- max size/type constraints
- virus scanning (where applicable)
- URL/domain allowlist checks for embedded links

### 6.2 Content policy screening
- pre-publish classifier stack (sexual, violence, hate, scams, self-harm, etc.)
- region/store profile aware thresholds
- queue uncertain results to human moderation

### 6.3 In-app controls (mandatory for UGC paths)
- report content
- block user
- terms acceptance before posting
- abuse response SLA tracking
- audit trail of moderation decisions

### 6.4 Safety fail-safe
- automatic feature freeze if moderation backlog or severe incidents exceed threshold.

## 7) Payments + Commerce Compliance Model

1. Mark each feature as:
- `digital_in_app`
- `physical_or_off_app`
- `enterprise_internal`

2. Policy engine enforces:
- app_store/play_store digital in-app -> store billing path required (unless profile exception explicitly configured).
- disallowed link-outs blocked by profile.

3. Thomas Builder UX:
- payment type selector per module/feature
- compliance badge (pass/warn/block)
- blocked publish if unresolved.

## 8) WebSocket + Hybrid Runtime Safety Model

1. WebSocket protocol
- signed session token
- short TTL
- per-device scope
- per-capability authorization claims

2. Message classes
- `layout_patch`
- `workflow_patch`
- `data_bindings`
- `asset_manifest`
- `policy_update`

3. Forbidden over socket
- arbitrary executable bytecode/native libs
- dynamic bridge registration to unrestricted native APIs

4. Offline behavior
- signed snapshot cache
- deterministic rollback to last known-good release

## 9) Observability, Audit, and Rollback

1. Ship-time artifacts
- policy profile used
- module hash/signature
- compliance report
- approving actor

2. Runtime telemetry
- crashes by module version
- policy denials
- moderation incidents
- payment flow compliance errors

3. Auto controls
- rollout pause on anomaly thresholds
- one-click rollback to prior signed release
- remote quarantine of violating module id/version

## 10) Implementation Roadmap

### Phase 0: Foundation Freeze (1 week)
- Freeze kernel boundary and hard-lock list.
- Add distribution identity fields to device registration.
- Add strict-global fallback policy.

### Phase 1: Policy Engine MVP (2 weeks)
- Introduce versioned `policy_profiles`.
- Add pre-ship compliance runner integrated into `ship` and `releases/publish`.
- Return machine-readable violations.

### Phase 2: UGC Safety + Moderation (2-3 weeks)
- Build upload intake scanner chain.
- Add report/block/terms acceptance requirements in schema + runtime checks.
- Add moderation queue + SLA dashboard.

### Phase 3: Commerce Guardrails (1-2 weeks)
- Add feature commerce classification.
- Enforce store-specific billing/link rules in ship validation.
- Add Builder compliance badges.

### Phase 4: Runtime Broker Hardening (2 weeks)
- Capability-scoped websocket tokens.
- Deny-by-default native bridge.
- Offline signed snapshot + rollback.

### Phase 5: Trust & Scale (ongoing)
- Continuous policy update pipeline.
- Region/store profile expansion.
- Advanced integrity/attestation by platform.

## 11) Required Changes in Thomas (Concrete Work Items)

Backend:
- Add `thomas/companion/policy/` package:
  - `profiles.py`
  - `validator.py`
  - `moderation_requirements.py`
  - `commerce_rules.py`
- Add pre-ship gate hook in companion routes (`ship`, `releases/publish`, `studio/build-bundle` when `andShip=true` workflows).
- Add compliance report endpoint:
  - `POST /api/companion/v1/compliance/check`
- Add policy profile inspect endpoint:
  - `GET /api/companion/v1/policy/profile/{id}`

Builder UI:
- Add compliance panel showing:
  - active target profile(s)
  - violations/warnings
  - blocked controls + why
- Add store target selector for simulation.
- Add moderation + commerce requirement checklist per module.

SDK contract:
- Extend TypeScript types with compliance report schemas.
- Add client helpers for `compliance/check` and policy profile retrieval.

Data model:
- Extend device schema with distribution/store identity fields.
- Extend release schema with `compliance_report_id`, `policy_profile_id`.

## 12) Definition of Done (DoD)

A release is "store-safe ready" only if:
1. Compliance check is PASS for all target profiles.
2. UGC-required controls are present where UGC is enabled.
3. Payments routing is valid for targeted stores/regions.
4. Privacy/disclosure metadata requirements are satisfied.
5. Runtime capability requests are subset of profile allowlist.
6. Signed bundle and audit trail are present.
7. Canary rollout health thresholds pass.

## 13) Operational Policy Update Process

1. Track policy changes monthly from Apple/Google sources.
2. Update `policy_profiles` with version bump + changelog.
3. Run regression compliance suite.
4. Flip enforcement from warn -> block after grace period.

## 14) Immediate Next 10 Tasks

1. [x] Add device distribution identity fields and migration.
2. [x] Create `strict_global` + `ios_app_store` + `android_play_store` profiles.
3. [x] Implement `compliance/check` API endpoint.
4. [x] Hook compliance gate into `ship` and `releases/publish`.
5. [x] Add builder compliance panel and target-profile selector.
6. [x] Add first-party URL allowlist validator for webview/navigation actions.
7. [x] Add UGC feature flag + required moderation controls in module schema.
8. [x] Add payment classification field and store-rule validator.
9. [x] Add audit events for policy failures and overrides.
10. [x] Add CI suite for compliance regression by profile.

## 15) Primary Policy References

- Apple App Review Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Apple Mini Apps Partner Program: https://developer.apple.com/programs/mini-apps-partner/
- Google Play Device and Network Abuse: https://support.google.com/googleplay/android-developer/answer/16559646
- Google Play User Generated Content policy: https://support.google.com/googleplay/android-developer/answer/9876937
- Google Play Payments policy: https://support.google.com/googleplay/android-developer/answer/9858738
- Google Play Data safety form: https://support.google.com/googleplay/android-developer/answer/10787469
- Android Dynamic Code Loading risk guidance: https://developer.android.com/privacy-and-security/risks/dynamic-code-loading

## 16) Policy Citation Notes (For Internal Review)

- Apple 2.5.2: no download/install/execute code changing functionality.
- Apple 4.7.1-4.7.5: moderation/privacy/index/age gating for hosted software.
- Apple 3.1.1: in-app digital unlocks require IAP unless exception.
- Google Device & Network Abuse: no self-update outside Play; no external executable code downloads (with interpreter caveat).
- Google UGC: requires report/block/moderation systems.
- Google Payments: in-app digital goods/features use Play Billing unless an explicit exception applies.

