"""
scripts/make_email_assets.py — draws the small pictures the account emails
carry inline (backend/email_templates.py): three 24px icons (clock, calendar,
question mark) and the faint SAN2 swoosh behind the footer, all in the logo's
red, drawn at 2x so they stay sharp on phones. Re-run after changing the logo.
(Headings used to be drawn here too, as Manrope pictures; dropped 2026-10-20
because a picture can't follow dark mode. They are live text now.)

    python scripts/make_email_assets.py
    python scripts/make_email_assets.py --hero-from <crop.png>

It also draws the logo for the email header (backend/assets/email/logo.png)
from backend/assets/email_logo.png with a thin white outline around its dark
lettering only: invisible on the light header, and what keeps "CORPORATION"
readable when Gmail's apps darken the header (they recolour text, never
pictures). The red is left as it is.

--hero-from also builds frontend/public/email/warehouse.png, the hosted hero
illustration, from a picture of a warehouse (Audrey, 2026-10-21; was a JPEG
faded into the light tint, which showed as a pasted rectangle on any other
background, dark mode included): resized to HERO_PX wide, with its left and
top edges feathered to transparency (smoothstep), the way the sign-in page's
yard fades into its cream, so it blends into whatever colour the email app
paints behind it. Transparency needs a PNG. The source in use is
local/email_sources/warehouse-source.png (git-ignored), recovered from the
earlier JPEG by undoing its linear cream fade. That one is served by the
frontend (Vercel), not attached to the email, so the message stays small.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "assets" / "email"
LOGO = ROOT / "backend" / "assets" / "email_logo.png"
HERO_OUT = ROOT / "frontend" / "public" / "email" / "warehouse.png"
HERO_PX = 536  # 2x the 268px it is shown at
LOGO_OUT = OUT / "logo.png"
HERO_BG = (251, 244, 240)  # #FBF4F0, backend/email_templates.HERO_BG
RED = (199, 78, 61)  # #C74E3D, backend/email_templates.BRAND
S = 2  # drawn at 2x


def _canvas(size: int = 24) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def clock() -> Image.Image:
    im, d = _canvas()
    d.ellipse((3 * S, 3 * S, 21 * S, 21 * S), outline=RED, width=2 * S)
    d.line((12 * S, 7 * S, 12 * S, 12 * S), fill=RED, width=2 * S)
    d.line((12 * S, 12 * S, 16 * S, 14 * S), fill=RED, width=2 * S)
    return im


def calendar() -> Image.Image:
    im, d = _canvas()
    d.rounded_rectangle((3 * S, 5 * S, 21 * S, 21 * S), radius=3 * S, outline=RED, width=2 * S)
    d.rectangle((3 * S, 5 * S, 21 * S, 10 * S), fill=RED)
    for x in (8, 16):
        d.line((x * S, 3 * S, x * S, 7 * S), fill=RED, width=2 * S)
    return im


def question() -> Image.Image:
    im, d = _canvas()
    d.ellipse((2 * S, 2 * S, 22 * S, 22 * S), outline=RED, width=2 * S)
    try:
        font = ImageFont.truetype("arialbd.ttf", 14 * S)
    except OSError:
        font = ImageFont.load_default()
    d.text((12 * S, 12 * S), "?", fill=RED, font=font, anchor="mm")
    return im


def swoosh() -> Image.Image:
    """The swoosh on the left of the logo, washed out to a watermark."""
    logo = Image.open(LOGO).convert("RGBA")
    mark = logo.crop((0, 0, 96, logo.height))
    # The logo is a transparent PNG: keep its own outline, flat brand red at 16% opacity.
    out = Image.new("RGBA", mark.size, RED + (0,))
    out.putalpha(mark.getchannel("A").point(lambda a: int(a * 0.16)))
    return _small(out.resize((mark.width * 2, mark.height * 2), Image.LANCZOS), colors=32)


def _small(im: Image.Image, colors: int) -> Image.Image:
    """A palette PNG with its transparency kept: a fraction of the size."""
    return im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)


def _smooth(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def hero(source: Path) -> Image.Image:
    """The illustration with its left 34% and top 12% fading to transparent.
    The right and bottom edges stay hard: they meet the card's edge and the
    hero's bottom line."""
    im = Image.open(source).convert("RGBA")
    im = im.resize((HERO_PX, round(im.height * HERO_PX / im.width)), Image.LANCZOS)
    left, top = round(im.width * 0.34), round(im.height * 0.12)
    ramp = Image.new("L", im.size)
    px = ramp.load()
    for x in range(im.width):
        ax = _smooth(x / left)
        for y in range(im.height):
            px[x, y] = round(255 * ax * _smooth(y / top))
    alpha = Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), ramp)
    im.putalpha(alpha)
    # Full colour: a 256-colour palette banded the fade into steps. Pixels
    # with nothing left to show are cleared, which compresses better.
    clear = Image.new("RGBA", im.size, (0, 0, 0, 0))
    return Image.composite(im, clear, alpha.point(lambda v: 255 if v else 0))


def logo_with_outline() -> Image.Image:
    """The logo with a 2px (1px shown) white outline around its dark pixels."""
    logo = Image.open(LOGO).convert("RGBA")
    r, g, b, a = logo.split()
    # Dark = the navy lettering; the red swoosh and "AN2" are bright enough already.
    dark = Image.eval(Image.merge("RGB", (r, g, b)).convert("L"), lambda v: 255 if v < 90 else 0)
    dark = Image.composite(dark, Image.new("L", logo.size, 0), a.point(lambda v: 255 if v > 40 else 0))
    # Opened first (shrink, then grow back) so stray dark pixels at the
    # swoosh's edge don't each get a white dot.
    dark = dark.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    halo = dark.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(0.6))
    out = Image.new("RGBA", logo.size, (255, 255, 255, 0))
    out.putalpha(halo.point(lambda v: min(255, int(v * 1.1))))
    out.alpha_composite(logo)
    return _small(out, colors=128)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hero-from", type=Path, help="picture to turn into the hosted hero illustration")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in (("clock", clock), ("calendar", calendar), ("question", question), ("swoosh", swoosh)):
        path = OUT / f"{name}.png"
        draw().save(path, optimize=True)
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size:,} bytes")
    logo_with_outline().save(LOGO_OUT, optimize=True)
    print(f"{LOGO_OUT.relative_to(ROOT)}  {LOGO_OUT.stat().st_size:,} bytes")
    if args.hero_from:
        HERO_OUT.parent.mkdir(parents=True, exist_ok=True)
        hero(args.hero_from).save(HERO_OUT, optimize=True)
        print(f"{HERO_OUT.relative_to(ROOT)}  {HERO_OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
