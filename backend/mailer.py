"""
backend.mailer — sends the dashboard's account emails (invites and password
resets) through the SMTP account in .env: SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM (the group Gmail with an app password; see
.env.example). FRONTEND_URL is where the links in those emails point.

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


class MailError(Exception):
    """The email was not sent. The message is safe to show an admin."""


def is_configured() -> bool:
    load_dotenv(override=False)
    return all(os.environ.get(name) for name in _SETTINGS)


def app_link(path: str) -> str:
    """Absolute link into the frontend, e.g. app_link('/set-password#token=...')."""
    load_dotenv(override=False)
    return os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/") + path


def _from_header(user: str) -> str:
    """'Name <address>' for the From line. The address is always SMTP_USER —
    Gmail only sends as the account it signed in to — and SMTP_FROM supplies
    just the display name, with or without an address written into it."""
    name = re.sub(r"<?[\w.+-]+@[\w.-]+>?", "", os.environ.get("SMTP_FROM", "")).strip().strip('"').strip()
    return formataddr((name or "SSM Dashboard", user))


def send(to: str, subject: str, body: str) -> None:
    """Sends one plain-text email. Raises MailError when it can't."""
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
