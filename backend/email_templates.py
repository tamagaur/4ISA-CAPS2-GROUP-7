"""
backend.email_templates — the account emails (invite, password reset) as an
HTML message plus the same words in plain text (2026-10-16).

Built for email apps, not browsers: a table layout 600px wide, inline styles
only, no web fonts or scripts, and a button drawn as a table cell so Outlook
shows it. The logo travels inside the email (an inline "cid:" image), so it
shows without the frontend being reachable, and the email reads fine with
images blocked. Nothing in it tracks the reader.

The plain-text part carries every fact the HTML does, the link included:
email apps that can't show HTML use it, and the tests read it.
"""
from __future__ import annotations

import datetime
from html import escape
from pathlib import Path

LOGO_PATH = Path(__file__).with_name("assets") / "email_logo.png"
LOGO_CID = "ssm-dsd-logo"
PRODUCT = "SSM Decision Support Dashboard"
PH_TIME = datetime.timezone(datetime.timedelta(hours=8))  # Philippine time, no daylight saving

BRAND = "#C74E3D"  # the logo's red; white on it is 4.6:1 (frontend --color-brand-strong)
INK = "#1F2937"
MUTED = "#5B6472"
LINE = "#E7EBF0"
PAGE = "#F4F5F7"

ROLE_LABELS = {"admin": "Admin", "staff": "Staff"}
ROLE_WHAT = {
    "admin": "view every page, manage user accounts, edit products and accept or dismiss reorder recommendations",
    "staff": "view every page of the dashboard: sales, stock, product classes, forecasts and reorder recommendations",
}


def expiry_text(expires_at: datetime.datetime | None, valid: str) -> str:
    """'Oct 18, 2026, 3:45 PM Philippine time', or the bare length when
    the moment isn't known."""
    if expires_at is None:
        return f"in {valid}"
    when = expires_at.astimezone(PH_TIME)
    hour = when.strftime("%I").lstrip("0") or "12"
    return f"on {when.strftime('%b')} {when.day}, {when.year}, {hour}:{when.strftime('%M %p')} Philippine time"


def _paragraph(text: str, *, size: int = 15, color: str = INK, margin: str = "0 0 16px") -> str:
    return (f'<p style="margin:{margin};font-family:Arial,Helvetica,sans-serif;font-size:{size}px;'
            f'line-height:1.55;color:{color};">{text}</p>')


def _button(label: str, link: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 20px;">'
        f'<tr><td align="center" bgcolor="{BRAND}" style="border-radius:8px;">'
        f'<a href="{escape(link)}" target="_blank" style="display:inline-block;padding:14px 28px;'
        'font-family:Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;color:#FFFFFF;'
        f'text-decoration:none;border-radius:8px;">{escape(label)}</a></td></tr></table>'
    )


def _steps(steps: list[str]) -> str:
    rows = "".join(
        f'<tr><td valign="top" style="padding:0 10px 8px 0;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;font-weight:bold;color:{BRAND};">{i}.</td>'
        f'<td style="padding:0 0 8px;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'line-height:1.5;color:{INK};">{step}</td></tr>'
        for i, step in enumerate(steps, 1)
    )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">{rows}</table>'


def _layout(*, preheader: str, heading: str, body_html: str, link: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(heading)}</title></head>
<body style="margin:0;padding:0;background-color:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:600px;background-color:#FFFFFF;border:1px solid {LINE};border-radius:12px;">
<tr><td style="padding:24px 32px 16px;border-bottom:3px solid {BRAND};">
<img src="cid:{LOGO_CID}" width="150" alt="SAN2 Corporation" style="display:block;width:150px;height:auto;border:0;
font-family:Arial,Helvetica,sans-serif;font-size:18px;font-weight:bold;color:{BRAND};">
</td></tr>
<tr><td style="padding:28px 32px 8px;">
<h1 style="margin:0 0 16px;font-family:Arial,Helvetica,sans-serif;font-size:22px;line-height:1.3;color:{INK};">{escape(heading)}</h1>
{body_html}
</td></tr>
<tr><td style="padding:16px 32px 24px;background-color:#FAFBFC;border-top:1px solid {LINE};border-radius:0 0 12px 12px;">
{_paragraph("Button not working? Copy this link into your browser:", size=12, color=MUTED, margin="0 0 4px")}
<p style="margin:0 0 14px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;word-break:break-all;">
<a href="{escape(link)}" style="color:{BRAND};">{escape(link)}</a></p>
{_paragraph("We will never ask for your password by email. If you weren't expecting this email, ignore it: nothing happens and no account changes.", size=12, color=MUTED, margin="0 0 8px")}
{_paragraph(f"{PRODUCT} &middot; San San Marketing, Urdaneta, Pangasinan &middot; For authorized SSM staff only.", size=11, color=MUTED, margin="0")}
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def invite_email(*, full_name: str, email: str, link: str, valid: str, sign_in_url: str,
                 expires_at: datetime.datetime | None = None, invited_by: str | None = None,
                 role: str | None = None, two_step_required: bool = False) -> tuple[str, str, str]:
    """(subject, plain text, html) for a new account's invite."""
    expires = expiry_text(expires_at, valid)
    role_label = ROLE_LABELS.get(role or "", "")
    who = f"{invited_by} invited you" if invited_by else "You've been invited"
    as_role = f" as {role_label}" if role_label else ""
    can_do = ROLE_WHAT.get(role or "")
    steps = [
        "Choose your password using the link above.",
        f"Sign in at {sign_in_url} with this email address ({email}).",
    ]
    if two_step_required:
        steps.append("Set up two-step sign-in when asked: you'll need an authenticator app on your phone.")

    subject = f"You're invited to the {PRODUCT}"
    text = "\n".join(line for line in [
        f"Hi {full_name},",
        "",
        f"{who} to join the {PRODUCT}{as_role}.",
        f"With this account you can {can_do}." if can_do else None,
        "",
        f"Set your password here. The link works once and expires {expires} ({valid} after it was sent):",
        "",
        link,
        "",
        "What happens next:",
        *[f"  {i}. {s}" for i, s in enumerate(steps, 1)],
        "",
        "We will never ask for your password by email. If you weren't expecting this email, ignore it: "
        "nothing happens and no account changes.",
        "",
        f"{PRODUCT} - San San Marketing, Urdaneta, Pangasinan",
    ] if line is not None)
    body_html = (
        _paragraph(f"Hi {escape(full_name)},")
        + _paragraph(f"{escape(who)} to join the <strong>{PRODUCT}</strong>"
                     + (f" as <strong>{escape(role_label)}</strong>" if role_label else "") + ".")
        + (_paragraph(f"With this account you can {escape(can_do)}.") if can_do else "")
        + _button("Set your password", link)
        + _paragraph(f"This link works once and expires <strong>{escape(expires)}</strong>.", size=14, color=MUTED)
        + _paragraph("<strong>What happens next</strong>", size=15, margin="8px 0 8px")
        + _steps([escape(s) for s in steps])
    )
    html = _layout(preheader=f"Set your password to start using the {PRODUCT}.",
                   heading="You're invited to the SSM Dashboard", body_html=body_html, link=link)
    return subject, text, html


def reset_email(*, full_name: str, email: str, link: str, valid: str,
                expires_at: datetime.datetime | None = None) -> tuple[str, str, str]:
    """(subject, plain text, html) for a password reset."""
    expires = expiry_text(expires_at, valid)
    subject = f"Reset your {PRODUCT} password"
    text = "\n".join([
        f"Hi {full_name},",
        "",
        f"A password reset was requested for your account ({email}).",
        f"Choose a new password here. The link works once and expires {expires} ({valid} after it was sent):",
        "",
        link,
        "",
        "If you didn't ask for this, ignore this email. Your password stays the same.",
        "",
        f"{PRODUCT} - San San Marketing, Urdaneta, Pangasinan",
    ])
    body_html = (
        _paragraph(f"Hi {escape(full_name)},")
        + _paragraph(f"A password reset was requested for your account (<strong>{escape(email)}</strong>).")
        + _button("Choose a new password", link)
        + _paragraph(f"This link works once and expires <strong>{escape(expires)}</strong>.", size=14, color=MUTED)
        + _paragraph("If you didn't ask for this, ignore this email. Your password stays the same.", size=14)
    )
    html = _layout(preheader="Choose a new password for your SSM Dashboard account.",
                   heading="Reset your password", body_html=body_html, link=link)
    return subject, text, html


def logo_bytes() -> bytes | None:
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return None
