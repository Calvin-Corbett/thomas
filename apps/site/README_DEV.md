# Website Dev Notes (Local-Only)

Use this file as the first stop when working on the public website.

## Working Folder

- `apps/site`

## URLs

- Live worker URL: `https://thomas-site.thomasdevhub.workers.dev`
- Local dev URL: `http://localhost:3000`
- Custom domain target: `https://thomas.dev` (currently not resolving in DNS)

## Spline Sources

- Hero scene (published): `https://prod.spline.design/6Wq1Q7YGyM-iab9i/scene.splinecode`
- Infinite phone prototype (UI file): `https://app.spline.design/ui/ecd1bd3d-ddd4-48e1-a445-069e8334101d`

## Quick Start

```bash
cd apps/site
npm run dev
```

## Quick Check Before Hand-off

```bash
cd apps/site
npm run typecheck
```

## Hard Rule: Visual Verification Proof

For any UI change in `src/app/**` or `src/components/**`, update:

- `apps/site/verification/ui-proof.json`
- `apps/site/verification/runtime-report.json`
- `apps/site/verification/screenshots/full-page.png`
- `apps/site/verification/screenshots/footer-focus.png`
- `apps/site/verification/baselines/full-page.png`
- `apps/site/verification/baselines/footer-focus.png`
- `apps/site/verification/diffs/full-page-diff.png`
- `apps/site/verification/diffs/footer-focus-diff.png`

Run the one-command refresh from repo root:

```bash
python scripts/refresh_site_visual_proof.py
```

This command runs runtime browser verification, refreshes proof artifacts, and executes the proof gate.
CI and pre-commit enforce the same rule. If it fails, do not deploy.

Runtime verification now captures a route matrix (`/`, `/download`, `/updates`, `/journey`, `/support`, and unknown-route smoke check) and writes per-route screenshots to:

- `output/site-visual-proof/routes/`

If the UI change is intentionally large and should reset visual baseline, run:

```bash
python scripts/refresh_site_visual_proof.py --init-pixel-baseline
```

## Rule For Website Tasks

If a request is about the website, always:
1. `cd apps/site`
2. Read this file
3. Then implement changes
