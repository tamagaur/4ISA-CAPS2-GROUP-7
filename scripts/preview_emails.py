"""
scripts/preview_emails.py — renders the account emails (backend/email_templates.py)
with sample data into a folder you can open in a browser, without sending
anything. Nothing here touches the database or the mail server.

    python scripts/preview_emails.py --out local/email_previews

Writes one .html and one .txt per sample (the plain-text part is what an
email app without HTML shows). The inline "cid:" pictures are rewritten to
files copied beside the pages, and the hosted hero illustration is read from
frontend/public/email/, so the preview looks like the email will — minus the
email app's own quirks (Outlook squares off rounded corners, Gmail with a
non-Google account ignores the phone layout). <name>_dark.html is the same
page with the dark palette forced on, as Apple Mail or Outlook show it in
dark mode; Gmail's apps recolour the email their own way instead. The sample tokens are not real.
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import email_templates as t  # noqa: E402

BASE = "https://dashboard.example"  # stands in for FRONTEND_URL
LINK = BASE + "/set-password#token=z8AmZMYtvKF3pe2hGHwySOh4-4_pllhChB1NXD5qKXA"
SIGN_IN = BASE + "/login"
EXPIRES = datetime.datetime(2026, 10, 18, 10, 9, tzinfo=datetime.timezone.utc)  # 6:09 PM Philippine time
LONG_NAME = "Maria Theresa Concepcion Villanueva-Bautista de los Santos"
LONG_EMAIL = "maria.theresa.concepcion.villanueva.bautista@sansanmarketing-urdaneta.com.ph"


def samples(hero_url: str | None) -> dict[str, tuple[str, str, str]]:
    return {
        "reset_self": t.reset_email(
            full_name="Mikhaella Audrey Bugayong", email="audrey@example.com", link=LINK,
            valid="30 minutes", hero_url=hero_url),
        "reset_by_admin": t.reset_email(
            full_name="Mikhaella Audrey Bugayong", email="audrey@example.com", link=LINK,
            valid="24 hours", expires_at=EXPIRES, hero_url=hero_url),
        "invite_admin": t.invite_email(
            full_name="Mikhaella Audrey Bugayong", email="audrey@example.com", link=LINK, valid="48 hours",
            sign_in_url=SIGN_IN, expires_at=EXPIRES, invited_by="Audrey Bugayong", role="admin", hero_url=hero_url),
        "invite_staff": t.invite_email(
            full_name="Juan dela Cruz", email="juan@example.com", link=LINK, valid="48 hours",
            sign_in_url=SIGN_IN, expires_at=EXPIRES, invited_by="Audrey Bugayong", role="staff", hero_url=hero_url),
        "invite_staff_two_step": t.invite_email(
            full_name="Juan dela Cruz", email="juan@example.com", link=LINK, valid="48 hours",
            sign_in_url=SIGN_IN, expires_at=EXPIRES, invited_by="Audrey Bugayong", role="staff",
            two_step_required=True, hero_url=hero_url),
        "invite_long_name": t.invite_email(
            full_name=LONG_NAME, email=LONG_EMAIL, link=LINK + "x" * 40, valid="48 hours",
            sign_in_url=SIGN_IN, expires_at=EXPIRES, invited_by=LONG_NAME, role="admin", hero_url=hero_url),
        "invite_minimal": t.invite_email(
            full_name="", email="someone@example.com", link=LINK, valid="48 hours",
            sign_in_url=SIGN_IN),  # no name, role, inviter, expiry or hero picture
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "local" / "email_previews")
    parser.add_argument("--no-hero", action="store_true", help="render without the hosted illustration")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    hero_src = ROOT / "frontend" / "public" / "email" / Path(t.HERO_IMAGE_PATH).name
    hero_url = None
    if not args.no_hero and hero_src.exists():
        shutil.copy(hero_src, out / hero_src.name)
        hero_url = hero_src.name
    pictures = {t.LOGO_CID: t.LOGO_PATH} | {cid: path for cid, path, _w, _h in t.ICONS.values()}
    for cid, path in pictures.items():
        if path.exists():
            shutil.copy(path, out / f"{cid}.png")

    for name, (subject, text, html) in samples(hero_url).items():
        for cid in pictures:
            html = html.replace(f"cid:{cid}", f"{cid}.png")
        (out / f"{name}.html").write_text(html, encoding="utf-8")
        # The same page with the dark palette forced on, as an app in dark mode shows it.
        (out / f"{name}_dark.html").write_text(
            html.replace("@media (prefers-color-scheme: dark)", "@media all"), encoding="utf-8")
        (out / f"{name}.txt").write_text(f"Subject: {subject}\n\n{text}\n", encoding="utf-8")
        print(f"{out / name}.html  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
