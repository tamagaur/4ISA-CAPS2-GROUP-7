"""
scripts/make_email_assets.py — draws the small pictures the account emails
carry inline (backend/email_templates.py): three 24px icons (clock, calendar,
question mark) and the faint SAN2 swoosh behind the footer, all in the logo's
red, drawn at 2x so they stay sharp on phones. Re-run after changing the logo.
(Headings used to be drawn here too, as Manrope pictures; dropped 2026-10-20
because a picture can't follow dark mode. They are live text now.)

    python scripts/make_email_assets.py
    python scripts/make_email_assets.py --hero-from <crop.png>

--hero-from also builds frontend/public/email/warehouse.jpg, the hosted hero
illustration, from a picture of a warehouse: it resizes it to 604px wide,
fades its left edge into the hero's background tint and saves it as a JPEG
(a palette PNG banded the sky; a full-colour PNG was 220 KB). That one is
served by the frontend (Vercel), not attached to the email, so the message
stays small.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "assets" / "email"
LOGO = ROOT / "backend" / "assets" / "email_logo.png"
HERO_OUT = ROOT / "frontend" / "public" / "email" / "warehouse.jpg"
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


def hero(source: Path) -> Image.Image:
    im = Image.open(source).convert("RGBA")
    width = 604
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    fade = 90  # px, left edge → transparent
    alpha = im.getchannel("A").load()
    for x in range(fade):
        a = x / fade
        for y in range(im.height):
            alpha[x, y] = int(alpha[x, y] * a)
    flat = Image.new("RGBA", im.size, HERO_BG + (255,))
    flat.alpha_composite(im)
    return flat.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hero-from", type=Path, help="picture to turn into the hosted hero illustration")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in (("clock", clock), ("calendar", calendar), ("question", question), ("swoosh", swoosh)):
        path = OUT / f"{name}.png"
        draw().save(path, optimize=True)
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size:,} bytes")
    if args.hero_from:
        HERO_OUT.parent.mkdir(parents=True, exist_ok=True)
        hero(args.hero_from).save(HERO_OUT, quality=84, optimize=True, progressive=True)
        print(f"{HERO_OUT.relative_to(ROOT)}  {HERO_OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
