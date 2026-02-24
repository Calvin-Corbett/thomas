---
name: ui-precision-guard
description: Deterministic workflow for high-precision website UI edits with route-matrix screenshots, runtime assertions, and proof-gate enforcement.
---

# UI Precision Guard

Use this skill for any website UI change where tiny alignment/regression mistakes matter.

## When to trigger

- CSS/layout/spacing/position tweaks
- animation or micro-interaction changes
- header/footer/nav updates
- visual bugfixes where screenshot accuracy is required

## Mandatory workflow

1. Implement the smallest possible UI delta.
2. Run static safety checks:
   - `cd apps/site`
   - `npm run typecheck`
3. Regenerate runtime visual proof (repo root):
   - Normal: `python scripts/refresh_site_visual_proof.py`
   - Intentional baseline reset: `python scripts/refresh_site_visual_proof.py --init-pixel-baseline`
4. Validate gate explicitly:
   - `python scripts/check_site_visual_proof.py`
5. Review generated artifacts before claiming success:
   - `apps/site/verification/screenshots/full-page.png`
   - `apps/site/verification/screenshots/footer-focus.png`
   - `output/site-visual-proof/routes/*`
   - `apps/site/verification/runtime-report.json`
6. Do not deploy until the proof gate passes.

## Precision rules

- Never claim visual correctness without updated screenshots.
- Verify multiple routes, not only home.
- Verify nav/header persistence while scrolled.
- Verify no horizontal overflow.
- For tiny mount/alignment work, use a dedicated lab page (if present) and tune by numeric offsets, then re-check in real footer/page context.

## Required handoff summary

- list exact files changed
- list exact commands run
- include screenshot artifact paths used for verification
- include whether deploy was performed and the live URL/version
