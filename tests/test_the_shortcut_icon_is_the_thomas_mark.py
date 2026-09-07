"""The desktop shortcut has to wear the same face as the app.

Two files drew the Thomas mark and each carried a comment promising it matched
the other. They did not: thomas-icon.svg draws eyes 13 wide with a 6 gap, while
make_thomas_icon.py drew them 16.7 wide with a 13.3 gap - a third wider, twice
as far apart. The shortcut wore a different face than the browser tab, and the
comments hid it.

The generator also rendered all seven icon sizes and then saved only the 256px
one, letting Pillow downsample it to 16/24/32/48 itself. Six careful renders
were computed and discarded, and the sizes Windows actually draws on the
desktop came out soft.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "thomas" / "server" / "web" / "thomas-icon.svg"

make_thomas_icon = pytest.importorskip("scripts.make_thomas_icon")


def _svg_geometry() -> dict[str, float]:
    """The mark's proportions, read from the SVG's own 100-unit viewBox."""
    text = SVG.read_text(encoding="utf-8")
    view = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    assert view, "the mark needs a viewBox to measure against"
    span = float(view.group(1))

    block = re.search(r'<rect width="100" height="100" rx="([\d.]+)"', text)
    assert block, "the mark needs its block rect"

    eyes = re.findall(
        r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="([\d.]+)"',
        text,
    )
    assert len(eyes) == 2, f"the mark has two eyes, found {len(eyes)}"
    left, right = sorted(eyes, key=lambda e: float(e[0]))

    return {
        "radius": float(block.group(1)) / span,
        "eye_w": float(left[2]) / span,
        "eye_h": float(left[3]) / span,
        "gap": (float(right[0]) - (float(left[0]) + float(left[2]))) / span,
        "eye_radius": float(left[4]) / span,
    }


def test_the_generated_icon_uses_the_same_proportions_as_the_brand_svg() -> None:
    svg = _svg_geometry()
    assert pytest.approx(svg["radius"]) == make_thomas_icon.RADIUS_RATIO
    assert pytest.approx(svg["eye_w"]) == make_thomas_icon.EYE_W_RATIO
    assert pytest.approx(svg["eye_h"]) == make_thomas_icon.EYE_H_RATIO
    assert pytest.approx(svg["gap"]) == make_thomas_icon.EYE_GAP_RATIO
    assert pytest.approx(svg["eye_radius"]) == make_thomas_icon.EYE_RADIUS_RATIO


def test_the_icon_carries_a_real_render_at_every_size_windows_asks_for(tmp_path: Path) -> None:
    """Not one image plus a size list - a distinct render per size.

    Two same-size renders of the same art are byte-identical, so the tell that
    a small layer is a downsample of the 256px frame is that it no longer
    matches a direct render at that size.
    """
    image_mod = pytest.importorskip("PIL.Image")

    frames = [make_thomas_icon.render(size) for size in make_thomas_icon.ICON_SIZES]
    ico = tmp_path / "thomas.ico"
    frames[-1].save(
        ico,
        format="ICO",
        sizes=[(s, s) for s in make_thomas_icon.ICON_SIZES],
        append_images=frames[:-1],
    )

    for size, expected in zip(make_thomas_icon.ICON_SIZES, frames):
        stored = image_mod.open(ico)
        stored.size = (size, size)
        assert stored.convert("RGBA").tobytes() == expected.convert("RGBA").tobytes(), (
            f"the {size}px layer is not the {size}px render - it was resized from another frame"
        )


def test_every_size_windows_draws_on_the_desktop_is_present() -> None:
    # 32 and 48 are the desktop and taskbar sizes; 256 is the large-icons view.
    for size in (16, 32, 48, 256):
        assert size in make_thomas_icon.ICON_SIZES
