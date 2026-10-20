"""
backend.mailer — sends the dashboard's account emails (invites and password
resets) through the SMTP account in .env: SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM (the group Gmail with an app password; see
.env.example). FRONTEND_URL is where the links in those emails point; it
must be set on a production server (APP_ENV=production), which refuses the
http://localhost:5173 development default instead of mailing it out — an
invite sent from the live API once carried a localhost link (2026-10-20).

Every message carries its own Date and Message-ID. Without them Gmail adds
both after signing, the recipient's DKIM check fails and the message bounces
(550 5.7.30) — found 2026-09-28 with the first test email.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_SETTINGS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")


DEV_FRONTEND_URL = "http://localhost:5173"
FRONTEND_URL_MISSING = (
    "FRONTEND_URL isn't set on the server, so no link to the dashboard could be built. "
    "Set it to the dashboard's public address and restart the server."
)


class MailError(Exception):
    """The email was not sent. The message is safe to show an admin."""


class FrontendUrlMissing(MailError):
    """APP_ENV=production and FRONTEND_URL is unset: a link would point at
    localhost, so none is built."""


def is_configured() -> bool:
    load_dotenv(override=False)
    return all(os.environ.get(name) for name in _SETTINGS)


def is_production() -> bool:
    load_dotenv(override=False)
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def frontend_url() -> str | None:
    """The dashboard's address (FRONTEND_URL, no trailing slash). Unset: the
    Vite dev server's address in development, None in production."""
    load_dotenv(override=False)
    url = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
    if url:
        return url
    return None if is_production() else DEV_FRONTEND_URL


def app_link(path: str) -> str:
    """Absolute link into the frontend, e.g. app_link('/set-password#token=...').
    Raises FrontendUrlMissing rather than build a localhost link in production."""
    base = frontend_url()
    if base is None:
        logger.error("FRONTEND_URL is not set and APP_ENV=production: refusing to build a localhost link.")
        raise FrontendUrlMissing(FRONTEND_URL_MISSING)
    return base + path


def warn_if_frontend_url_unset() -> None:
    """At startup: say so once if links would fall back to localhost."""
    load_dotenv(override=False)
    if not os.environ.get("FRONTEND_URL", "").strip():
        if is_production():
            logger.error("FRONTEND_URL is not set: invites and password resets cannot carry a link until it is.")
        else:
            logger.warning("FRONTEND_URL is not set: email links will point at %s (development default).",
                           DEV_FRONTEND_URL)


def _from_header(user: str) -> str:
    """'Name <address>' for the From line. The address is always SMTP_USER —
    Gmail only sends as the account it signed in to — and SMTP_FROM supplies
    just the display name, with or without an address written into it."""
    name = re.sub(r"<?[\w.+-]+@[\w.-]+>?", "", os.environ.get("SMTP_FROM", "")).strip().strip('"').strip()
    return formataddr((name or "SSM Dashboard", user))


def send(to: str, subject: str, body: str, html: str | None = None,
         inline_images: dict[str, bytes] | None = None) -> None:
    """Sends one email: `body` as plain text, plus `html` as the version
    email apps show when they can, with `inline_images` ({cid: PNG bytes})
    inside it for <img src="cid:..."> (backend/email_templates.py). Raises
    MailError when it can't."""
    if not is_configured():
        logger.warning("Email to %s not sent: the SMTP_* settings are missing.", to)
        raise MailError("Email isn't set up on the server yet, so nothing was sent.")
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _from_header(user)
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_payload()[-1]
        for cid, data in (inline_images or {}).items():
            html_part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>",
                                  disposition="inline", filename=f"{cid}.png")
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            # Google shows app passwords in groups of four; the spaces aren't part of it.
            smtp.login(user, os.environ["SMTP_PASSWORD"].replace(" ", ""))
            # Envelope sender and recipient given outright. Left to be read
            # from the headers, SMTP_FROM written without <...> around its
            # address ("SSM Dashboard x@gmail.com") became the envelope sender
            # verbatim — not an address — and the 2026-09-28 invite to another
            # Gmail account vanished: refused, with no valid address to bounce to.
            smtp.send_message(msg, from_addr=user, to_addrs=[to])
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Could not send email to %s: %s", to, exc)
        raise MailError("The email couldn't be sent, so share the link another way.") from exc
