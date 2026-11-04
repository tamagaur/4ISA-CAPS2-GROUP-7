"""G8: the server refuses to start on a weak JWT secret in production or a malformed MFA key; local development with
the variables unset is untouched. Messages name the variable and never the value."""
import pytest
from cryptography.fernet import Fernet

from backend.startup_checks import JWT_MIN_LENGTH, StartupConfigError, validate_secrets


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setattr("backend.startup_checks.load_dotenv", lambda **kw: None)
    for k in ("APP_ENV", "JWT_SECRET_KEY", "MFA_ENCRYPTION_KEY", "MFA_ENABLED"):
        monkeypatch.delenv(k, raising=False)


def test_production_short_jwt_secret_refuses_and_does_not_leak_it(monkeypatch):
    short = "short-secret-value"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", short)
    with pytest.raises(StartupConfigError) as e:
        validate_secrets()
    assert "JWT_SECRET_KEY" in str(e.value) and str(JWT_MIN_LENGTH) in str(e.value)
    assert short not in str(e.value)


def test_production_long_jwt_secret_and_development_short_secret_start(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * JWT_MIN_LENGTH)
    validate_secrets()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "short")
    validate_secrets()


def test_malformed_mfa_key_refuses_when_set_or_when_mfa_enabled(monkeypatch):
    bad = "x" * 44  # right length, not a Fernet key
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", bad)
    with pytest.raises(StartupConfigError) as e:
        validate_secrets()
    assert "MFA_ENCRYPTION_KEY" in str(e.value) and bad not in str(e.value)
    monkeypatch.delenv("MFA_ENCRYPTION_KEY")
    monkeypatch.setenv("MFA_ENABLED", "true")
    with pytest.raises(StartupConfigError):
        validate_secrets()


def test_valid_mfa_key_and_the_unset_local_default_start(monkeypatch):
    validate_secrets()  # nothing set: local development as configured today
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MFA_ENABLED", "true")
    validate_secrets()
