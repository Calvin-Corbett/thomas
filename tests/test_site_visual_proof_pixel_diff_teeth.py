"""Pin the pixel-diff comparator's actual teeth.

site-visual-proof-baseline-drift-2026-08-26, round 2 (adversarial review
follow-up): round 1's fix made footer-focus captures deterministic and
absorbed real anti-aliasing noise, but an adversarial review found the
comparator itself (`scripts.refresh_site_visual_proof._pixel_diff_stats`)
had a structural blind spot -- deleted content was invisible at ANY scale,
because the comparison only asked "does this CURRENT pixel have a match
nearby in baseline", never the reverse. It also used one global loose
tolerance (32/255) that was never measured against a noise floor, sized
instead to swallow the worst-case glyph jitter -- which meant a uniform
recolor or a several-pixel layout shift (the incident's own visual
signature) went undetected too.

Round 2 made the comparison symmetric (a pixel is changed if EITHER
direction -- current-vs-baseline or baseline-vs-current -- fails to find an
acceptable match) and two-tier (a small _PIXEL_STRICT_TOLERANCE applies
everywhere; a looser _PIXEL_EDGE_TOLERANCE only escapes where local
contrast in either image suggests a real anti-aliased edge). Nothing here
tests those exact production images (they're 1424x768 site screenshots) --
this pins the *behavior* against a small, fully-controlled synthetic
reference image so the next tolerance/radius bump has a red condition
without needing a real browser capture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import scripts.refresh_site_visual_proof as mod
from PIL import Image

# A small (80x60) synthetic reference: a flat dark background with one
# lighter, hard-edged "content" rectangle -- enough to exercise both the
# flat-region strict path and the edge-region escape path, without needing
# a real screenshot.
_WIDTH, _HEIGHT = 80, 60
_BG = (20, 24, 33)
_CONTENT = (230, 230, 230)
_CONTENT_BOX = (10, 10, 50, 30)  # x0, y0, x1, y1 (exclusive)


def _make_reference() -> np.ndarray:
    arr = np.empty((_HEIGHT, _WIDTH, 3), dtype=np.uint8)
    arr[:, :] = _BG
    x0, y0, x1, y1 = _CONTENT_BOX
    arr[y0:y1, x0:x1] = _CONTENT
    return arr


def _save(arr: np.ndarray, path: Path) -> None:
    Image.fromarray(arr, mode="RGB").save(path)


def _diff_ratio(tmp_path: Path, *, baseline_arr: np.ndarray, current_arr: np.ndarray) -> float:
    baseline_path = tmp_path / "baseline.png"
    current_path = tmp_path / "current.png"
    diff_path = tmp_path / "diff.png"
    _save(baseline_arr, baseline_path)
    _save(current_arr, current_path)
    stats = mod._pixel_diff_stats(baseline_path=baseline_path, current_path=current_path, diff_out_path=diff_path)
    assert diff_path.exists(), "diff overlay must always be written, pass or fail"
    return float(stats["diff_ratio"])


def test_unchanged_image_passes(tmp_path: Path) -> None:
    reference = _make_reference()
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=reference.copy())
    assert ratio == 0.0


def test_measured_noise_case_passes(tmp_path: Path) -> None:
    """The real, measured noise this comparator exists to absorb: the
    content edge lands 1px off between two genuine captures of unchanged
    content (real anti-aliasing/rasterization jitter at _PIXEL_AA_NEIGHBORHOOD_RADIUS's
    scale), plus small flat-region byte noise within _PIXEL_STRICT_TOLERANCE.
    Must PASS -- if this starts failing, the tolerance is too tight for real
    captures, which is the other failure mode this suite guards against."""
    reference = _make_reference()
    current = reference.copy()
    x0, y0, x1, y1 = _CONTENT_BOX
    # Shift the content box top edge up by 1px (sub-pixel-scale AA jitter).
    current[y0 - 1 : y1 - 1, x0:x1] = _CONTENT
    current[y1 - 1, x0:x1] = _BG
    # Small flat-region byte noise, well within _PIXEL_STRICT_TOLERANCE.
    rng = np.random.default_rng(1234567)
    noise = rng.integers(-2, 3, size=current.shape, dtype=np.int16)
    noisy = np.clip(current.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=noisy)
    assert ratio <= mod.DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO, (
        f"real measured-noise-scale pair must pass the gate, got {ratio:.4%}"
    )


def test_content_deletion_fails(tmp_path: Path) -> None:
    """CRITICAL-1 (adversarial review): a one-directional comparator lets
    deleted content hide behind matching background at any scale. This is
    the fixture that must never go silent again."""
    reference = _make_reference()
    current = reference.copy()
    x0, y0, x1, y1 = _CONTENT_BOX
    current[y0:y1, x0:x1] = _BG  # the whole content block vanishes
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=current)
    assert ratio > mod.DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO, (
        f"deleted content must fail the gate, got {ratio:.4%} (was silent under round 1's one-directional match)"
    )


def test_uniform_recolor_past_strict_tolerance_fails(tmp_path: Path) -> None:
    """IMPORTANT-1: T=32 was 16-32x the measured 1-2/255 flat-region noise,
    so a uniform recolor up to +32 was invisible. _PIXEL_STRICT_TOLERANCE+1
    applied to every pixel (including flats, which get no neighbourhood
    escape) must fail."""
    reference = _make_reference()
    delta = mod._PIXEL_STRICT_TOLERANCE + 1
    current = np.clip(reference.astype(np.int16) + delta, 0, 255).astype(np.uint8)
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=current)
    assert ratio > mod.DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO, (
        f"a uniform +{delta}/255 recolor must fail the gate, got {ratio:.4%}"
    )


def test_shift_beyond_neighborhood_radius_fails(tmp_path: Path) -> None:
    """IMPORTANT-2: radius=2 fully masked shifts up to 6px -- the
    incident's own visual signature (a margin/padding regression moving the
    footer a few px) was unseeable. A shift of radius+1 must fail."""
    reference = _make_reference()
    shift = mod._PIXEL_AA_NEIGHBORHOOD_RADIUS + 1
    current = np.roll(reference, shift, axis=0)
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=current)
    assert ratio > mod.DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO, (
        f"a {shift}px shift (radius+1) must fail the gate, got {ratio:.4%}"
    )


def test_shift_within_neighborhood_radius_passes(tmp_path: Path) -> None:
    """The intentional AA-tolerance counterpart to the previous test: a
    shift AT the tolerated radius (real sub-pixel jitter scale) must still
    pass, or the tolerance added for round 1's real noise was removed by
    round 2's tightening."""
    reference = _make_reference()
    shift = mod._PIXEL_AA_NEIGHBORHOOD_RADIUS
    current = np.roll(reference, shift, axis=0)
    ratio = _diff_ratio(tmp_path, baseline_arr=reference, current_arr=current)
    assert ratio <= mod.DEFAULT_PIXEL_DIFF_THRESHOLD_RATIO, (
        f"a {shift}px shift (at radius) should still pass, got {ratio:.4%}"
    )
