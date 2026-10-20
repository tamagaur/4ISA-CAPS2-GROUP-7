"""
backend.email_templates — the account emails (invite, password reset) as an
HTML message plus the same words in plain text (2026-10-16; redesigned
2026-10-20 after the SAN2 mockup: logo header, warehouse hero, red button,
expiry notice, "what happens next" steps, fallback link, tinted footer).

Built for email apps, not browsers: a table layout 600px wide, inline styles
only, no scripts, a button drawn as a table cell so Outlook shows it, and one
small <style> block whose only job is to stack the hero and the steps on a
phone (Gmail, Apple Mail and Outlook's apps honour it; the rest just see the
desktop columns squeezed).

Type (Audrey, 2026-10-20): Manrope for headings and the button
(HEADING_FONT), Inter for the body (FONT), both loaded from Google Fonts for
the apps that honour that (Apple Mail, iOS Mail); Gmail drops web fonts and
shows Roboto, then Arial. Every heading is live text. Drawing the fixed
headings as Manrope pictures was tried and dropped the same day: a picture
keeps its colour whatever the background, so a navy title vanished in dark
mode (which no email app can fix for a picture), and Gmail's apps recolour
text but never pictures. Outlook for Windows is kept off the web fonts
entirely: given a font it doesn't have first in the list, it falls to Times
New Roman instead of the next name, so an Outlook-only style sets Arial. An
app that does load them asks Google Fonts for them when the email is opened,
so Google sees that request; nothing in the email itself tracks the reader.
The logo and the four small icons travel inside the email (inline "cid:"
images, a few KB), so they show without the frontend being reachable and the
email reads fine with images blocked. The one big picture, the warehouse illustration, is
fetched from the frontend (frontend/public/email/warehouse.jpg, served by
Vercel at FRONTEND_URL) so the message itself stays small; it has alt text
and a fixed box, so a blocked image leaves a labelled gap, not a broken
layout. Nothing in it tracks the reader.

The plain-text part carries every fact the HTML does, the link included:
email apps that can't show HTML use it, and the tests read it.
"""
from __future__ import annotations

import datetime
from html import escape
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")

# 300x102, shown at 150x51 so it stays sharp on phones; 128 colours keeps it near 7 KB.
# Gmail fetches images after the text, so the size is fixed in the <img> to keep the
# header from collapsing and the email from jumping when the logo arrives.
LOGO_PATH = ASSETS / "email_logo.png"
LOGO_CID = "ssm-dsd-logo"
LOGO_WIDTH, LOGO_HEIGHT = 150, 51

# The icons and the footer watermark, drawn by scripts/make_email_assets.py
# at 2x. Attached inline like the logo, but only the ones an email uses
# (inline_images_for), so a reset carries no calendar and nothing shows up
# as a stray attachment.
ICONS = {
    "clock": ("ssm-dsd-clock", ASSETS / "email" / "clock.png", 24, 24),
    "calendar": ("ssm-dsd-calendar", ASSETS / "email" / "calendar.png", 24, 24),
    "question": ("ssm-dsd-question", ASSETS / "email" / "question.png", 28, 28),
    "swoosh": ("ssm-dsd-swoosh", ASSETS / "email" / "swoosh.png", 96, 102),
}

# The hosted hero illustration (a delivery truck at a warehouse), 604x448
# shown at 268x199, on the hero's own tint. Its address is built on FRONTEND_URL by the caller
# (backend/account_links.py) and passed in as hero_url.
HERO_IMAGE_PATH = "/email/warehouse.jpg"

HERO_WIDTH, HERO_HEIGHT = 268, 199
# The hero title: 28px, not 30, so "You're invited to the SSM Dashboard" at
# weight 800 stays on two lines in the 286px text column.
TITLE_SIZE = 28
HERO_ALT = "A delivery truck loading at the San San Marketing warehouse"

PRODUCT = "SSM Decision Support Dashboard"
COMPANY = "San San Marketing"
PLACE = "Urdaneta, Pangasinan"
PH_TIME = datetime.timezone(datetime.timedelta(hours=8))  # Philippine time, no daylight saving

BRAND = "#C74E3D"  # the logo's red; white on it is 4.6:1 (frontend --color-brand-strong)
INK = "#1C2533"    # headings and body: dark navy
MUTED = "#5B6472"
LINE = "#E6E8EC"
PAGE = "#F5F6F8"
HERO_BG = "#FBF4F0"    # the warm tint behind the hero and the footer
NOTICE_BG = "#FBEFEC"  # the expiry notice
NOTICE_LINE = "#F2D8D2"
PANEL_BG = "#F8F9FB"   # the reset card, the steps box and the link box
# Dark mode (2026-10-20): the same page on a dark palette, for the apps that
# ask for one (Apple Mail, iOS Mail, Outlook's apps and Outlook.com: the
# prefers-color-scheme block and the [data-ogsc]/[data-ogsb] rules in STYLE).
# Every coloured element carries a class the block can restyle: page, card,
# tint, panel, notice, line, ink, muted, brand, circle, btn, btn-a. Gmail's
# apps ignore all of it and recolour the email themselves (light backgrounds
# darkened, dark text lightened); pictures are left alone there, so anything
# that must read on both -- the logo, the icons -- is drawn in the brand red.
DARK = {
    "page": "#15181D", "card": "#1E2329", "line": "#30363F", "tint": "#2A2426", "panel": "#262B33",
    "notice": "#3C2724", "notice_line": "#5E3B35", "ink": "#ECEEF2", "muted": "#B5BBC6", "brand": "#F2927F",
    "circle": "#4D2F2A", "circle_ink": "#F6AB9A", "btn": "#D45A48",
}
FONT = "Inter,Roboto,Arial,Helvetica,sans-serif"            # body text
HEADING_FONT = "Manrope,Roboto,Arial,Helvetica,sans-serif"  # live headings and the button
WEB_FONTS_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Manrope:wght@700;800&display=swap"

ROLE_LABELS = {"admin": "Admin", "staff": "Staff"}
ROLE_WITH_ARTICLE = {"admin": "an Admin", "staff": "a Staff user"}


# ── Words ──────────────────────────────────────────────────────────────────
def expiry_text(expires_at: datetime.datetime | None, valid: str) -> str:
    """'on Oct 18, 2026, 3:45 PM Philippine time', or 'in 30 minutes' when
    the moment isn't known (the self-service reset: the page already told
    the person how long they have)."""
    if expires_at is None:
        return f"in {valid}"
    when = expires_at.astimezone(PH_TIME)
    hour = when.strftime("%I").lstrip("0") or "12"
    return f"on {when.strftime('%b')} {when.day}, {when.year}, {hour}:{when.strftime('%M %p')} Philippine time"


def role_abilities(role: str | None) -> list[str]:
    """What the role's preset lets the person do, in the words of the
    permissions catalog (backend/permissions.py): 'view the dashboard',
    'manage users', ... An admin has every permission; a staff invite
    never claims the admin ones. Empty for an unknown role."""
    if not role:
        return []
    from backend import permissions  # pulls in the API's dependencies; kept local

    keys = permissions.preset(role)
    labels = [entry["label"] for entry in permissions.CATALOG if entry["key"] in keys]
    return [label[0].lower() + label[1:] if label[:2] != label[:2].upper() else label for label in labels]


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def abilities_sentence(role: str | None) -> str | None:
    abilities = role_abilities(role)
    if not abilities:
        return None
    if role == "admin":
        return f"As {ROLE_WITH_ARTICLE['admin']} you have every permission: you can {_join(abilities)}."
    return f"With this account you can {_join(abilities)}."


def _greeting(full_name: str) -> str:
    return f"Hi {full_name.strip()}," if full_name and full_name.strip() else "Hi there,"


# ── Pieces of HTML ─────────────────────────────────────────────────────────
_COLOR_CLASS = {INK: "ink", MUTED: "muted", BRAND: "brand"}


def _p(text: str, *, size: int = 15, color: str = INK, margin: str = "0 0 16px", weight: str = "normal",
       extra: str = "") -> str:
    cls = _COLOR_CLASS.get(color, "")
    return (f'<p class="{cls}" style="margin:{margin};font-family:{FONT};font-size:{size}px;line-height:1.55;'
            f'color:{color};font-weight:{weight};{extra}">{text}</p>')


def _icon(name: str, *, alt: str = "") -> str:
    cid, _path, w, h = ICONS[name]
    return (f'<img src="cid:{cid}" width="{w}" height="{h}" alt="{escape(alt)}" '
            f'style="display:block;width:{w}px;height:{h}px;border:0;">')


def _button(label: str, link: str) -> str:
    """A red button drawn as a table cell (Outlook shows no CSS buttons),
    centred, 16px bold white on the brand red, with an arrow."""
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:4px auto 20px;">'
        f'<tr><td class="btn" align="center" bgcolor="{BRAND}" style="background-color:{BRAND};border-radius:8px;">'
        f'<a class="btn-a" href="{escape(link)}" target="_blank" style="display:inline-block;padding:15px 36px;'
        f'font-family:{HEADING_FONT};font-size:16px;font-weight:bold;color:#FFFFFF;text-decoration:none;'
        f'border-radius:8px;mso-padding-alt:0;">{escape(label)}&nbsp;&nbsp;&rarr;</a></td></tr></table>'
    )


def _notice(icon: str, html_text: str) -> str:
    """The light-red information box under the button."""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;">'
        f'<tr><td class="notice" bgcolor="{NOTICE_BG}" style="background-color:{NOTICE_BG};border:1px solid {NOTICE_LINE};'
        'border-radius:8px;padding:12px 14px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle" width="36" style="width:36px;">{_icon(icon)}</td>'
        f'<td class="ink" valign="middle" style="font-family:{FONT};font-size:13px;line-height:1.5;color:{INK};">{html_text}</td>'
        '</tr></table></td></tr></table>'
    )


def _title_cell(title: str, href: str | None) -> str:
    text = escape(title)
    if href:
        text = f'<a class="ink" href="{escape(href)}" style="color:{INK};text-decoration:none;">{text}</a>'
    return text


def _steps_box(steps: list[tuple[str, str, str | None]]) -> str:
    """'What happens next?': one numbered column per step on a wide screen,
    stacked on a phone (class="stack"). Each step is (title, detail html,
    link or None)."""
    width = f"{100 // len(steps)}%"
    cells = "".join(
        f'<td class="stack" valign="top" width="{width}" style="width:{width};padding:0 8px 10px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td valign="top" width="38" style="width:38px;padding-top:1px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td class="circle" align="center" '
        f'valign="middle" bgcolor="#F5E1DC" width="28" height="28" style="width:28px;height:28px;border-radius:14px;'
        f'font-family:{HEADING_FONT};font-size:14px;font-weight:bold;color:{BRAND};">{i}</td></tr></table></td>'
        f'<td class="ink" valign="top" style="font-family:{FONT};line-height:1.45;color:{INK};">'
        f'<span class="ink" style="display:block;font-family:{HEADING_FONT};font-size:13px;font-weight:bold;margin:4px 0 3px;">'
        f'{_title_cell(title, href)}</span>'
        f'<span class="muted" style="display:block;font-size:12px;color:{MUTED};word-break:break-word;">{detail}</span></td>'
        '</tr></table></td>'
        for i, (title, detail, href) in enumerate(steps, 1)
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 8px;">'
        f'<tr><td class="panel" bgcolor="{PANEL_BG}" style="background-color:{PANEL_BG};border-radius:10px;padding:20px 22px 12px;">'
        + _p("What happens next?", size=15, weight="bold", margin="0 0 14px", extra=f"font-family:{HEADING_FONT};")
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="table-layout:fixed;width:100%;"><tr>{cells}</tr></table>'
        '</td></tr></table>'
    )


def _hero(*, eyebrow: str, heading: str, intro: str, hero_url: str | None) -> str:
    text_cell = (
        f'<td class="stack pad" valign="middle" width="330" style="width:330px;padding:30px 12px 30px 32px;">'
        + _p(escape(eyebrow), size=12, color=BRAND, weight="bold", margin="0 0 10px",
             extra=f"letter-spacing:1px;text-transform:uppercase;font-family:{HEADING_FONT};")
        + f'<h1 class="h1 ink" style="margin:0 0 12px;font-family:{HEADING_FONT};font-size:{TITLE_SIZE}px;line-height:1.2;'
          f'font-weight:800;color:{INK};">'
          f'{escape(heading)}</h1>'
        + _p(intro, size=15, color=MUTED, margin="0")
        + '</td>'
    )
    if hero_url:
        image_cell = (
            '<td class="stack hero-img" valign="bottom" align="right" width="270" '
            'style="width:270px;padding:18px 0 0;">'
            f'<img class="hero-pic" src="{escape(hero_url)}" width="{HERO_WIDTH}" height="{HERO_HEIGHT}" '
            f'alt="{escape(HERO_ALT)}" '
            f'style="display:block;width:{HERO_WIDTH}px;max-width:100%;height:auto;border:0;'
            f'font-family:{FONT};font-size:12px;color:{MUTED};"></td>'
        )
    else:
        image_cell = ""
    return (
        f'<tr><td class="tint" bgcolor="{HERO_BG}" style="background-color:{HERO_BG};border-bottom:1px solid {LINE};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr>{text_cell}{image_cell}</tr></table></td></tr>'
    )


def _fallback(link: str) -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td class="line" style="border-top:1px solid {LINE};padding-top:20px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="top" width="44" style="width:44px;padding-top:2px;">{_icon("question")}</td>'
        '<td valign="top">'
        + _p("Button not working?", size=14, weight="bold", margin="0 0 2px", extra=f"font-family:{HEADING_FONT};")
        + _p("Copy and paste this link into your browser:", size=13, color=MUTED, margin="0 0 10px")
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td class="panel" bgcolor="{PANEL_BG}" style="background-color:{PANEL_BG};border:1px solid {LINE};border-radius:8px;'
        f'padding:12px 14px;font-family:{FONT};font-size:13px;line-height:1.5;word-break:break-all;">'
        f'<a class="ink" href="{escape(link)}" target="_blank" style="color:{INK};text-decoration:underline;">{escape(link)}</a>'
        '</td></tr></table>'
        '</td></tr></table></td></tr></table>'
    )


def _footer() -> str:
    return (
        f'<tr><td class="tint" bgcolor="{HERO_BG}" style="background-color:{HERO_BG};border-top:1px solid {LINE};'
        'border-radius:0 0 12px 12px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td class="pad" valign="middle" style="padding:24px 32px;">'
        + _p(PRODUCT, size=13, color=BRAND, weight="bold", margin="0 0 4px", extra=f"font-family:{HEADING_FONT};")
        + _p(f"{COMPANY}, {PLACE}<br>For authorized SSM staff only.", size=13, color=MUTED, margin="0")
        + '</td>'
        f'<td valign="bottom" align="right" width="120" style="width:120px;padding:8px 20px 0 0;">{_icon("swoosh")}</td>'
        '</tr></table></td></tr>'
    )


def _dark_css() -> str:
    """The dark palette, once inside prefers-color-scheme for the apps that
    ask, and once under Outlook.com's [data-ogsc] (text) / [data-ogsb]
    (backgrounds) hooks, which it adds when it darkens an email itself."""
    rules = {
        "body, .page": f"background-color:{DARK['page']} !important;",
        ".card": f"background-color:{DARK['card']} !important;border-color:{DARK['line']} !important;",
        ".tint": f"background-color:{DARK['tint']} !important;border-color:{DARK['line']} !important;",
        ".panel": f"background-color:{DARK['panel']} !important;border-color:{DARK['line']} !important;",
        ".notice": f"background-color:{DARK['notice']} !important;border-color:{DARK['notice_line']} !important;",
        ".line": f"border-color:{DARK['line']} !important;",
        ".ink": f"color:{DARK['ink']} !important;",
        ".muted": f"color:{DARK['muted']} !important;",
        ".brand": f"color:{DARK['brand']} !important;",
        ".circle": f"background-color:{DARK['circle']} !important;color:{DARK['circle_ink']} !important;",
        ".btn": f"background-color:{DARK['btn']} !important;",
        ".btn-a": "color:#FFFFFF !important;",
    }
    media = "\n".join(f"    {sel} {{ {decl} }}" for sel, decl in rules.items())
    outlook = "\n".join(
        "  " + ", ".join(f"[data-ogsc] {one}, [data-ogsb] {one}" for one in sel.split(", ") if one != "body")
        + f" {{ {decl} }}"
        for sel, decl in rules.items()
    )
    return f"  @media (prefers-color-scheme: dark) {{\n{media}\n  }}\n{outlook}\n"


STYLE = f"""
  :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
  body {{ margin:0; padding:0; -webkit-text-size-adjust:100%; }}
{_dark_css()}
  @media only screen and (max-width:600px) {{
    .stack {{ display:block !important; width:100% !important; max-width:100% !important; box-sizing:border-box !important; }}
    .pad {{ padding-left:20px !important; padding-right:20px !important; }}
    .hero-img {{ padding:0 20px 24px !important; }}
    .hero-pic {{ margin:0 auto !important; }}
    .h1 {{ font-size:26px !important; }}
    .card {{ border-radius:0 !important; }}
  }}
"""


def _layout(*, preheader: str, eyebrow: str, heading: str, intro: str, body_html: str, link: str,
            hero_url: str | None, boxed: bool) -> str:
    """The page: header (logo, company), hero, the message, the fallback
    link, the footer. `boxed` puts the message in a light card (the reset);
    the invite's longer message sits straight on the white."""
    if boxed:
        body_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td class="panel" bgcolor="{PANEL_BG}" style="background-color:{PANEL_BG};border:1px solid {LINE};'
            f'border-radius:10px;padding:24px 24px 8px;">{body_html}</td></tr></table>'
        )
    return f"""<!DOCTYPE html>
<html lang="en" xmlns:o="urn:schemas-microsoft-com:office:office"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<meta name="x-apple-disable-message-reformatting">
<!--[if mso]><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<title>{escape(heading)}</title>
<!--[if !mso]><!--><link href="{WEB_FONTS_URL}" rel="stylesheet" type="text/css"><!--<![endif]-->
<!--[if mso]><style type="text/css">body, table, td, p, a, span, h1 {{ font-family:Arial,Helvetica,sans-serif !important; }}</style><![endif]-->
<style type="text/css">{STYLE}</style>
</head>
<body class="page" style="margin:0;padding:0;background-color:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{escape(preheader)}</div>
<table role="presentation" class="page" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" class="card" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:600px;background-color:#FFFFFF;border:1px solid {LINE};border-radius:12px;">
<tr><td class="pad line" style="padding:22px 32px;border-bottom:1px solid {LINE};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td valign="middle" width="160" style="width:160px;">
<img src="cid:{LOGO_CID}" width="{LOGO_WIDTH}" height="{LOGO_HEIGHT}" alt="SAN2 Corporation"
 style="display:block;width:{LOGO_WIDTH}px;height:{LOGO_HEIGHT}px;border:0;
font-family:{FONT};font-size:16px;font-weight:bold;color:{BRAND};">
</td>
<td class="muted" valign="middle" align="right" style="font-family:{FONT};font-size:13px;line-height:1.5;color:{MUTED};">
<span class="ink" style="display:block;font-weight:bold;letter-spacing:0.5px;color:{INK};">{COMPANY.upper()}</span>
<span class="muted" style="display:block;">{PLACE}</span>
</td></tr></table>
</td></tr>
{_hero(eyebrow=eyebrow, heading=heading, intro=intro, hero_url=hero_url)}
<tr><td class="pad" style="padding:28px 32px 20px;">
{body_html}
</td></tr>
<tr><td class="pad" style="padding:0 32px 28px;">
{_fallback(link)}
</td></tr>
{_footer()}
</table>
</td></tr></table>
</body></html>"""


# ── The two emails ─────────────────────────────────────────────────────────
def invite_email(*, full_name: str, email: str, link: str, valid: str, sign_in_url: str,
                 expires_at: datetime.datetime | None = None, invited_by: str | None = None,
                 role: str | None = None, two_step_required: bool = False,
                 hero_url: str | None = None) -> tuple[str, str, str]:
    """(subject, plain text, html) for a new account's invite."""
    expires = expiry_text(expires_at, valid)
    role_label = ROLE_LABELS.get(role or "", "")
    as_role = f" as {ROLE_WITH_ARTICLE[role]}" if role_label else ""
    who = f"{invited_by} invited you" if invited_by else "You've been invited"
    can_do = abilities_sentence(role)
    steps = [
        ("Set your password", "Click the button above to create your password."),
        ("Sign in", f"Use your email address ({email}) to sign in."),
        ("Access the dashboard", f"Start using the {PRODUCT}."),
    ]
    if two_step_required:
        steps.append(("Set up two-step sign-in", "When asked, you'll need an authenticator app on your phone."))

    subject = f"You're invited to the {PRODUCT}"
    text = "\n".join(line for line in [
        PRODUCT.upper(),
        "You're invited to the SSM Dashboard",
        "",
        _greeting(full_name),
        "",
        f"{who} to join the {PRODUCT}{as_role}.",
        can_do,
        "",
        f"Set your password here. This link works once and expires {expires} ({valid} after it was sent):",
        "",
        link,
        "",
        "What happens next:",
        *[f"  {i}. {title}: {detail}" + (f" Sign in at {sign_in_url}." if title == "Sign in" else "")
          for i, (title, detail) in enumerate(steps, 1)],
        "",
        "We will never ask for your password by email. If you weren't expecting this invitation, "
        "you can ignore it: nothing happens and no account changes.",
        "",
        PRODUCT,
        f"{COMPANY}, {PLACE}",
        "For authorized SSM staff only.",
    ] if line is not None)

    html_steps = [(title, escape(detail), sign_in_url if title == "Sign in" else None) for title, detail in steps]
    body_html = (
        _p(escape(_greeting(full_name)), size=17, weight="bold", margin="0 0 12px")
        + _p(f"{escape(who)} to join the {PRODUCT}"
             + (f" as <strong>{escape(ROLE_WITH_ARTICLE[role])}</strong>" if role_label else "") + "."
             + (f" {escape(can_do)}" if can_do else ""), color=MUTED, margin="0 0 22px")
        + _button("Set your password", link)
        + _notice("calendar", f"This link works once and expires <strong class=\"brand\" style=\"color:{BRAND};\">{escape(expires)}</strong>.")
        + _steps_box(html_steps)
        + _p("We will never ask for your password by email. If you weren't expecting this invitation, "
             "you can ignore it: nothing happens and no account changes.", size=13, color=MUTED, margin="12px 0 0")
    )
    intro = (f"You've been invited to join the {PRODUCT}"
             + (f" as <strong class=\"ink\" style=\"color:{INK};\">{escape(ROLE_WITH_ARTICLE[role])}</strong>" if role_label else "")
             + ".")
    html = _layout(preheader=f"Set your password to start using the {PRODUCT}.",
                   eyebrow=PRODUCT, heading="You're invited to the SSM Dashboard", intro=intro,
                   body_html=body_html, link=link, hero_url=hero_url, boxed=False)
    return subject, text, html


def reset_email(*, full_name: str, email: str, link: str, valid: str,
                expires_at: datetime.datetime | None = None,
                hero_url: str | None = None) -> tuple[str, str, str]:
    """(subject, plain text, html) for a password reset."""
    expires = expiry_text(expires_at, valid)
    subject = f"Reset your {PRODUCT} password"
    text = "\n".join([
        PRODUCT.upper(),
        "Reset your password",
        "",
        _greeting(full_name),
        "",
        f"We received a request to reset the password for your {PRODUCT} account ({email}).",
        f"Choose a new password here. This link works once and expires {expires} ({valid} after it was sent):",
        "",
        link,
        "",
        "If you didn't request this, you can safely ignore this email. Your password will remain the same.",
        "",
        PRODUCT,
        f"{COMPANY}, {PLACE}",
        "For authorized SSM staff only.",
    ])
    body_html = (
        _p(escape(_greeting(full_name)), size=17, weight="bold", margin="0 0 12px")
        + _p("Click the button below to choose a new password for your account "
             f"(<strong class=\"ink\" style=\"color:{INK};\">{escape(email)}</strong>).", color=MUTED, margin="0 0 22px")
        + _button("Choose a new password", link)
        + _notice("clock", f"This link works once and expires <strong class=\"brand\" style=\"color:{BRAND};\">{escape(expires)}</strong>.")
        + _p("If you didn't request this, you can safely ignore this email.<br>Your password will remain the same.",
             size=14, margin="0 0 16px")
    )
    html = _layout(preheader="Choose a new password for your SSM Dashboard account.",
                   eyebrow=PRODUCT, heading="Reset your password",
                   intro=f"We received a request to reset the password for your {PRODUCT} account.",
                   body_html=body_html, link=link, hero_url=hero_url, boxed=True)
    return subject, text, html


# ── The pictures that travel with the email ────────────────────────────────
def logo_bytes() -> bytes | None:
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return None


def inline_images_for(html: str) -> dict[str, bytes]:
    """{cid: PNG bytes} for every inline picture the HTML refers to (the
    logo, and whichever icons it uses). A picture missing from disk is
    left out: the email still sends, with its alt text in that spot."""
    images: dict[str, bytes] = {}
    for cid, path in [(LOGO_CID, LOGO_PATH)] + [(cid, path) for cid, path, _w, _h in ICONS.values()]:
        if f"cid:{cid}" not in html:
            continue
        try:
            images[cid] = path.read_bytes()
        except OSError:
            continue
    return images
