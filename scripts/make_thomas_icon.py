"""Draw the Thomas app icon: the two-eyes-in-a-block brand mark.

The mark is the one the app itself wears (chat.html's brand span): an accent
rounded square with two dark eyes. This renders it at real icon resolutions
so the desktop shortcut carries Thomas's own face rather than a browser's.

Usage:
    python scripts/make_thomas_icon.py            # writes assets/thomas.ico (+ .png)
    python scripts/make_thomas_icon.py --preview  # also writes a 512px preview
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"

# Straight from tokens.css / the brand span in chat.html.
ACCENT = (139, 140, 255, 255)      # --c-accent  #8b8cff
ACCENT_INK = (10, 11, 22, 255)     # --c-accent-ink #0a0b16
# Proportions of the 30px brand mark: radius 9, eyes 5x6, gap 4.
RADIUS_RATIO = 9 / 30
EYE_W_RATIO = 5 / 30
EYE_H_RATIO = 6 / 30
EYE_GAP_RATIO = 4 / 30
EYE_RADIUS_RATIO = 1 / 30

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> Image.Image:
    """One square icon at ``size`` px, drawn 4x then downsampled for clean edges."""
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # The block. Full-bleed with a hair of padding so the rounded corners are
    # not clipped by the icon frame.
    pad = max(1, round(canvas * 0.02))
    draw.rounded_rectangle(
        [pad, pad, canvas - pad - 1, canvas - pad - 1],
        radius=round(canvas * RADIUS_RATIO),
        fill=ACCENT,
    )

    # The two eyes, centred as a pair.
    eye_w = canvas * EYE_W_RATIO
    eye_h = canvas * EYE_H_RATIO
    gap = canvas * EYE_GAP_RATIO
    eye_r = max(1, round(canvas * EYE_RADIUS_RATIO))
    pair_w = eye_w * 2 + gap
    left = (canvas - pair_w) / 2
    top = (canvas - eye_h) / 2
    for index in range(2):
        x0 = left + index * (eye_w + gap)
        draw.rounded_rectangle(
            [round(x0), round(top), round(x0 + eye_w), round(top + eye_h)],
            radius=eye_r,
            fill=ACCENT_INK,
        )

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="also write a 512px preview png")
    args = parser.parse_args()

    ASSETS.mkdir(parents=True, exist_ok=True)
    frames = [render(size) for size in ICON_SIZES]
    ico_path = ASSETS / "thomas.ico"
    frames[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    png_path = ASSETS / "thomas.png"
    frames[-1].save(png_path, format="PNG")
    print(f"wrote {ico_path} ({', '.join(str(s) for s in ICON_SIZES)})")
    print(f"wrote {png_path}")
    if args.preview:
        preview = ASSETS / "thomas-preview.png"
        render(512).save(preview, format="PNG")
        print(f"wrote {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
