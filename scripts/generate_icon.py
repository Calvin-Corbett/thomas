"""Generate the Thomas robot face as a multi-resolution ICO icon.

Draws the pixel-art robot from the CSS definitions in part-002b.css
at multiple resolutions for crisp rendering at any size.

Usage:
    python scripts/generate_icon.py [--output path/to/thomas.ico]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    sys.exit(1)


# ── Robot color palette (variant-blue) ───────────────────────────
PRIMARY = (154, 216, 255)  # #9ad8ff — head, upper body
SECONDARY = (90, 174, 255)  # #5aaeff — lower body, legs
TRIM = (13, 17, 23)  # #0d1117 — borders
EYE = (11, 23, 38)  # #0b1726 — eyes
BG = (0, 0, 0, 0)  # transparent

# ── CSS pixel-art geometry (absolute positions) ──────────────────
# All coordinates relative to the 58×54 bot container.
# These match the CSS in part-002b.css exactly.
HEAD = {"x": 16, "y": 2, "w": 24, "h": 14, "border": 2}
EYE_L = {"x": 16 + 5, "y": 2 + 3, "w": 4, "h": 4}
EYE_R = {"x": 16 + 13, "y": 2 + 3, "w": 4, "h": 4}
BODY = {"x": 13, "y": 18, "w": 30, "h": 18, "border": 2}
LEG_L = {"x": 18, "y": 36, "w": 8, "h": 10, "border": 2}
LEG_R = {"x": 32, "y": 36, "w": 8, "h": 10, "border": 2}

# Antenna stub (bonus detail — a 2px line above the head center)
ANTENNA = {"x": 27, "y": 0, "w": 2, "h": 3}

# Total bounding box of the robot.
BOT_W, BOT_H = 58, 54

# We crop to the interesting region with a small margin so the icon
# fills the frame nicely.  The actual drawn area is roughly x:13..43, y:0..46.
CROP_X, CROP_Y = 10, 0
CROP_W, CROP_H = 38, 47


def _draw_bordered_rect(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    border: int,
    fill: tuple,
    border_color: tuple = TRIM,
) -> None:
    """Draw a rectangle with a solid border, matching CSS box model."""
    # Outer border
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=border_color)
    # Inner fill
    ix, iy = x + border, y + border
    iw, ih = w - 2 * border, h - 2 * border
    if iw > 0 and ih > 0:
        draw.rectangle([ix, iy, ix + iw - 1, iy + ih - 1], fill=fill)


def _draw_body_gradient(
    img: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    border: int,
) -> None:
    """Draw body with the two-tone gradient from CSS (44% primary, 56% secondary)."""
    draw = ImageDraw.Draw(img)
    # Border
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=TRIM)
    # Inner area
    ix, iy = x + border, y + border
    iw, ih = w - 2 * border, h - 2 * border
    if iw <= 0 or ih <= 0:
        return
    split = int(ih * 0.44)
    # Upper part — primary
    if split > 0:
        draw.rectangle([ix, iy, ix + iw - 1, iy + split - 1], fill=PRIMARY)
    # Lower part — secondary
    if split < ih:
        draw.rectangle([ix, iy + split, ix + iw - 1, iy + ih - 1], fill=SECONDARY)


def draw_robot(size: int) -> Image.Image:
    """Render the Thomas robot face at the given square icon size.

    Draws at 1:1 pixel scale on a BOT_W×BOT_H canvas, crops to the
    interesting area, then resizes to *size*×*size* with nearest-neighbor
    to preserve the pixel-art crispness.
    """
    img = Image.new("RGBA", (BOT_W, BOT_H), BG)
    draw = ImageDraw.Draw(img)

    # Antenna
    draw.rectangle(
        [ANTENNA["x"], ANTENNA["y"], ANTENNA["x"] + ANTENNA["w"] - 1, ANTENNA["y"] + ANTENNA["h"] - 1],
        fill=TRIM,
    )

    # Head
    _draw_bordered_rect(
        draw,
        HEAD["x"],
        HEAD["y"],
        HEAD["w"],
        HEAD["h"],
        HEAD["border"],
        PRIMARY,
    )

    # Eyes
    draw.rectangle(
        [EYE_L["x"], EYE_L["y"], EYE_L["x"] + EYE_L["w"] - 1, EYE_L["y"] + EYE_L["h"] - 1],
        fill=EYE,
    )
    draw.rectangle(
        [EYE_R["x"], EYE_R["y"], EYE_R["x"] + EYE_R["w"] - 1, EYE_R["y"] + EYE_R["h"] - 1],
        fill=EYE,
    )

    # Body (gradient)
    _draw_body_gradient(
        img,
        BODY["x"],
        BODY["y"],
        BODY["w"],
        BODY["h"],
        BODY["border"],
    )

    # Legs
    _draw_bordered_rect(
        draw,
        LEG_L["x"],
        LEG_L["y"],
        LEG_L["w"],
        LEG_L["h"],
        LEG_L["border"],
        SECONDARY,
    )
    _draw_bordered_rect(
        draw,
        LEG_R["x"],
        LEG_R["y"],
        LEG_R["w"],
        LEG_R["h"],
        LEG_R["border"],
        SECONDARY,
    )

    # Crop to the interesting region
    cropped = img.crop((CROP_X, CROP_Y, CROP_X + CROP_W, CROP_Y + CROP_H))

    # Resize to target with nearest-neighbor (keeps pixel-art sharp)
    return cropped.resize((size, size), Image.Resampling.NEAREST)


def generate_ico(output_path: str | Path) -> Path:
    """Generate a multi-resolution .ico file at *output_path*.

    Includes 16, 32, 48, 64, 128, and 256px versions.
    Returns the resolved output path.
    """
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_robot(s) for s in sizes]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Pillow ICO: the *largest* image is the base, append_images are extras.
    # All images must be provided; Pillow picks sizes from their .size attr.
    base = images[-1]  # 256px
    extras = images[:-1]
    base.save(
        str(out),
        format="ICO",
        append_images=extras,
    )
    return out.resolve()


def generate_png(output_path: str | Path, size: int = 256) -> Path:
    """Generate a single PNG at *output_path* (for macOS/Linux)."""
    img = draw_robot(size)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), format="PNG")
    return out.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Thomas robot icon")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: assets/thomas.ico)",
    )
    parser.add_argument(
        "--png",
        action="store_true",
        help="Also generate a 256px PNG alongside the ICO",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    default_dir = repo_root / "assets"

    ico_path = Path(args.output) if args.output else default_dir / "thomas.ico"
    result = generate_ico(ico_path)
    print(f"ICO → {result}")

    if args.png:
        png_path = ico_path.with_suffix(".png")
        result_png = generate_png(png_path, 256)
        print(f"PNG → {result_png}")


if __name__ == "__main__":
    main()
