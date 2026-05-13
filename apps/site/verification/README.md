# Website Visual Proof Bundle

This folder is the hard-gated proof bundle for website UI changes.

Required files:

- `ui-proof.json`
- `runtime-report.json`
- `screenshots/full-page.png`
- `screenshots/footer-focus.png`
- `baselines/full-page.png`
- `baselines/footer-focus.png`
- `diffs/full-page-diff.png`
- `diffs/footer-focus-diff.png`

When changing UI in `apps/site/src/app/**` or `apps/site/src/components/**`:

1. Run `python scripts/refresh_site_visual_proof.py` from repo root.
2. Confirm it refreshed all files above.
3. If needed, run `python scripts/forge/gates/site_visual_proof.py` for a manual gate check.

Pixel-diff policy:

- The refresh script compares latest screenshots against committed baselines.
- It fails the gate when changed-pixel ratio exceeds threshold.
- If a visual redesign is intentional, reseed baselines once:
  `python scripts/refresh_site_visual_proof.py --init-pixel-baseline`

The gate is enforced by pre-commit and CI.

Runtime assertions include:

- core layout present across route matrix
- nav persistence while scrolling on each core page
- unknown-route themed page integrity
- no horizontal overflow
- footer rider mount/seat checks
