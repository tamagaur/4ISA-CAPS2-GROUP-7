"""
The account emails (backend/email_templates.py) and where their links point
(backend/mailer.app_link). Pure rendering: no database, nothing is sent.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from backend import account_links, email_templates as t, mailer, permissions

LINK = "https://dsd.example/set-password#token=abc-DEF_123"
HERO = "https://dsd.example/email/warehouse.jpg"


def invite(**overrides):
    args = dict(full_name="New User", email="new@ssmcapstone.com", link=LINK, valid="48 hours",
                sign_in_url="https://dsd.example/login",
                expires_at=datetime(2026, 10, 18, 10, 9, tzinfo=timezone.utc),
                invited_by="Admin User", role="staff", hero_url=HERO)
    args.update(overrides)
    return t.invite_email(**args)


def hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


# --- the role's permissions come from the catalog, not a hard-coded sentence --

def test_a_staff_invite_lists_the_staff_preset_and_not_the_admin_permissions():
    _subject, text, html = invite(role="staff")
    staff_labels = [e["label"] for e in permissions.CATALOG if e["key"] in permissions.PRESETS["staff"]]
    for label in staff_labels:
        assert label[0].lower() + label[1:] in text
    assert "manage users" not in text and "manage users" not in html
    assert "accept or dismiss" not in text
    assert "as a Staff user" in text and "a Staff user" in html


def test_an_admin_invite_lists_every_permission():
    _subject, text, html = invite(role="admin")
    for entry in permissions.CATALOG:
        label = entry["label"]
        assert label[0].lower() + label[1:] in text
    assert "every permission" in text and "manage users" in html
    assert "as an Admin" in text and "an Admin" in html


def test_role_abilities_follow_the_preset():
    assert t.role_abilities("staff") == [
        "view the dashboard", "view ABC classification", "view forecasts", "view category trends",
        "view SKU Management", "view reorder recommendations",
    ]
    assert len(t.role_abilities("admin")) == len(permissions.CATALOG)
    assert t.role_abilities(None) == [] and t.role_abilities("manager") == []


# --- the button and the fallback link are the same link ---------------------

@pytest.mark.parametrize("render", [
    lambda: invite(),
    lambda: t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes", hero_url=HERO),
], ids=["invite", "reset"])
def test_the_button_and_the_fallback_link_point_at_the_same_address(render):
    _subject, text, html = render()
    assert hrefs(html).count(LINK) == 2  # the button and the copy-paste box
    assert text.count(LINK) == 1
    # No other token-looking link anywhere.
    assert all("token=" not in h or h == LINK for h in hrefs(html))
    assert f">{LINK}<" in html  # the fallback shows the address in full, selectable


# --- the hero picture is hosted, labelled, and optional ----------------------

def test_the_hero_illustration_is_a_hosted_picture_with_alt_text():
    _s, _t, html = invite(hero_url=HERO)
    assert (f'<img class="hero-pic" src="{HERO}" width="{t.HERO_WIDTH}" height="{t.HERO_HEIGHT}" '
            f'alt="{t.HERO_ALT}"') in html
    _s, _t, html = invite(hero_url=None)
    assert HERO not in html and "warehouse" not in html


def test_only_the_pictures_an_email_uses_travel_with_it():
    _s, _t, reset_html = t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes")
    reset_images = t.inline_images_for(reset_html)
    assert set(reset_images) == {t.LOGO_CID, "ssm-dsd-clock", "ssm-dsd-question", "ssm-dsd-swoosh"}
    _s, _t, invite_html = invite()
    assert set(t.inline_images_for(invite_html)) == {t.LOGO_CID, "ssm-dsd-calendar", "ssm-dsd-question",
                                                      "ssm-dsd-swoosh"}
    for data in reset_images.values():
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert HERO.split("/")[-1] not in str(reset_images)  # the big picture is never attached


# --- expiry, names, missing details -----------------------------------------

def test_the_reset_shows_the_configured_length_or_the_exact_moment():
    _s, text, html = t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes")
    assert "expires in 30 minutes" in text and "expires <strong" in html and "30 minutes</strong>" in html
    _s, text, html = t.reset_email(full_name="N", email="n@x", link=LINK, valid="24 hours",
                                   expires_at=datetime(2026, 10, 18, 10, 9, tzinfo=timezone.utc))
    assert "expires on Oct 18, 2026, 6:09 PM Philippine time" in text
    assert "Oct 18, 2026, 6:09 PM Philippine time</strong>" in html
    assert "If you didn't request this, you can safely ignore this email." in text
    assert "Your password will remain the same." in html


def test_long_names_and_addresses_are_shown_in_full_and_escaped():
    name = "Maria Theresa Concepcion <Villanueva-Bautista> de los Santos"
    email = "maria.theresa.concepcion.villanueva.bautista@sansanmarketing-urdaneta.com.ph"
    _s, text, html = invite(full_name=name, email=email, invited_by=name)
    assert f"Hi {name}," in text
    assert "Hi Maria Theresa Concepcion &lt;Villanueva-Bautista&gt; de los Santos," in html
    assert "<Villanueva-Bautista>" not in html
    assert html.count(email) >= 1 and email in text


def test_an_invite_renders_without_a_name_role_inviter_expiry_or_picture():
    _s, text, html = invite(full_name="", role=None, invited_by=None, expires_at=None, hero_url=None)
    assert "Hi there," in text and "Hi there," in html
    assert "You've been invited to join the SSM Decision Support Dashboard." in text
    assert "expires in 48 hours" in text
    assert "With this account" not in text and "every permission" not in text
    assert "What happens next" in html and "Set your password" in html


def test_the_two_step_sign_in_step_is_added_only_when_required():
    _s, text, _h = invite(two_step_required=False)
    assert "4." not in text and "authenticator" not in text
    _s, text, html = invite(two_step_required=True)
    assert "4. Set up two-step sign-in" in text and "authenticator app" in html


def test_the_shared_header_and_footer_name_the_company():
    for _s, text, html in (invite(), t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes")):
        assert "SAN SAN MARKETING" in html and "Urdaneta, Pangasinan" in html
        assert 'alt="SAN2 Corporation"' in html and 'src="cid:ssm-dsd-logo"' in html
        assert "For authorized SSM staff only." in text and "For authorized SSM staff only." in html
        assert "<script" not in html and "background-image" not in html
        assert 'width="600"' in html and "max-width:600px" in html


# --- dark mode -----------------------------------------------------------------

def test_the_email_carries_a_dark_palette_for_apps_that_ask_for_one():
    for _s, _t, html in (invite(), t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes")):
        assert '<meta name="color-scheme" content="light dark">' in html
        assert "@media (prefers-color-scheme: dark)" in html and "[data-ogsc] .ink" in html
        # Every coloured piece is reachable by class: text, panels, the button.
        for cls in ("ink", "muted", "brand", "tint", "panel", "notice", "btn", "btn-a", "line", "card"):
            assert f'class="{cls}"' in html or f' {cls}"' in html or f'"{cls} ' in html, cls
        assert ".btn-a { color:#FFFFFF !important; }" in html
        assert f".ink {{ color:{t.DARK['ink']} !important; }}" in html


# --- where links point: FRONTEND_URL, never a guessed address in production --

@pytest.fixture
def no_dotenv(monkeypatch):
    """mailer reads .env on every call (load_dotenv); these tests set the
    environment themselves, so a real .env on this machine must not refill it."""
    monkeypatch.setattr(mailer, "load_dotenv", lambda **_kw: None)


def test_links_use_the_configured_frontend_url_without_a_trailing_slash(monkeypatch, no_dotenv):
    monkeypatch.setenv("FRONTEND_URL", "https://dsd.example/")
    monkeypatch.setenv("APP_ENV", "production")
    assert mailer.app_link("/set-password#token=x") == "https://dsd.example/set-password#token=x"
    assert account_links.link_url("x") == "https://dsd.example/set-password#token=x"


def test_development_falls_back_to_the_vite_dev_server(monkeypatch, no_dotenv):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert mailer.app_link("/login") == "http://localhost:5173/login"


def test_production_refuses_to_build_a_localhost_link(monkeypatch, no_dotenv):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(mailer.FrontendUrlMissing):
        mailer.app_link("/login")
    assert account_links.link_url_or_none("x") is None
    # The email is reported as not sent, with the reason, instead of raising.
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: sent.append(a))
    problem = account_links.send_link_email(purpose="reset", email="n@x", full_name="N", token="x", minutes=30)
    assert problem == mailer.FRONTEND_URL_MISSING and sent == []


def test_the_headings_are_live_text_so_dark_mode_can_recolour_them():
    """A picture keeps its colour on any background; text follows the palette."""
    _s, _t, html = invite()
    assert ">You&#x27;re invited to the SSM Dashboard</h1>" in html
    for text in ("Set your password", "Sign in", "Access the dashboard"):
        assert f">{text}</" in html
    assert "ssm-dsd-title-" not in html and "ssm-dsd-step-" not in html
    assert "Manrope,Roboto,Arial,Helvetica,sans-serif" in html
    _s, _t, html = t.reset_email(full_name="N", email="n@x", link=LINK, valid="30 minutes")
    assert ">Reset your password</h1>" in html

