"""Build the web app's brand images from the logo artwork (assets/brand/logo.png).

    python scripts/brand/make_brand_assets.py        (needs Pillow; a one-off design step)

The artwork is a dark mark and wordmark on an off-white background. This script:
  - measures the background colour and turns it into transparency (anti-aliased by darkness)
  - finds the hexagon mark (the top block of dark pixels) and the full lock-up
  - writes a dark-ink version for the light theme and a light-ink version for the dark theme
Outputs go to frontend/public/brand/. Re-run after replacing the artwork.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "brand" / "logo.png"
OUT = ROOT / "frontend" / "public" / "brand"
INK_LIGHT_THEME = (21, 26, 33)     # --fg, light theme
INK_DARK_THEME = (232, 235, 240)   # --fg, dark theme


def alpha_mask(im: Image.Image) -> Image.Image:
    g = im.convert("L")
    w, h = g.size
    corners = [g.getpixel((x, y)) for x in (5, w - 6) for y in (5, h - 6)]
    bg = sorted(corners)[len(corners) // 2]
    lo = 25  # darkest ink
    lut = [0 if v >= bg - 18 else min(255, int((bg - 18 - v) * 255 / max(1, bg - 18 - lo))) for v in range(256)]
    return g.point(lut).filter(ImageFilter.GaussianBlur(0.3))


def bbox_rows(mask: Image.Image) -> list[tuple[int, int]]:
    """Vertical bands that contain ink, top to bottom."""
    w, h = mask.size
    px = mask.load()
    rows = [any(px[x, y] > 60 for x in range(0, w, 2)) for y in range(h)]
    bands, start = [], None
    for y, on in enumerate(rows + [False]):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start > 3:
                bands.append((start, y))
            start = None
    return bands


def ink(mask: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    out = Image.new("RGBA", mask.size, colour + (0,))
    out.putalpha(mask)
    return out


def crop(img: Image.Image, mask: Image.Image, top: int, bottom: int, pad: int) -> Image.Image:
    band = mask.crop((0, top, mask.width, bottom))
    x0, _, x1, _ = band.getbbox()
    box = (max(0, x0 - pad), max(0, top - pad), min(img.width, x1 + pad), min(img.height, bottom + pad))
    return img.crop(box)


def square(img: Image.Image, size: int) -> Image.Image:
    s = max(img.size)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    canvas.paste(img, ((s - img.width) // 2, (s - img.height) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> int:
    if not SRC.is_file():
        print(f"missing {SRC}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    art = Image.open(SRC).convert("RGB")
    mask = alpha_mask(art)
    bands = bbox_rows(mask)
    if len(bands) < 2:
        print("could not find the mark and the wordmark")
        return 1
    mark_top, mark_bottom = bands[0]
    full_top, full_bottom = bands[0][0], bands[-1][1]
    for name, colour in (("light", INK_LIGHT_THEME), ("dark", INK_DARK_THEME)):
        layer = ink(mask, colour)
        mark = crop(layer, mask, mark_top, mark_bottom, 6)
        square(mark, 256).save(OUT / f"mark-{name}.png", optimize=True)
        full = crop(layer, mask, full_top, full_bottom, 12)
        full.thumbnail((960, 960), Image.LANCZOS)
        full.save(OUT / f"logo-{name}.png", optimize=True)
    square(crop(ink(mask, INK_LIGHT_THEME), mask, mark_top, mark_bottom, 6), 64).save(OUT / "favicon.png", optimize=True)
    print("bands:", bands)
    for p in sorted(OUT.glob("*.png")):
        print(p.relative_to(ROOT), Image.open(p).size, p.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
