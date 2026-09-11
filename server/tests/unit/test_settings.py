import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from graft.config import Settings

VALID_KEY = Fernet.generate_key().decode()


def test_dev_defaults_are_usable_without_secrets(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    settings = Settings(app_env="dev", _env_file=None)
    assert settings.app_env == "dev"
    assert settings.jwt_secret == "change-me"


def test_prod_rejects_placeholder_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env="prod", jwt_secret="change-me", encryption_key=VALID_KEY, _env_file=None)


def test_prod_rejects_empty_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env="prod", jwt_secret="", encryption_key=VALID_KEY, _env_file=None)


@pytest.mark.parametrize("key", ["", "not-a-fernet-key", "c2hvcnQ="])
def test_prod_rejects_invalid_fernet_key(key):
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(app_env="prod", jwt_secret="a-real-secret", encryption_key=key, _env_file=None)


def test_prod_accepts_real_secrets():
    settings = Settings(
        app_env="prod", jwt_secret="a-real-secret", encryption_key=VALID_KEY, _env_file=None
    )
    assert settings.encryption_key == VALID_KEY


def test_validation_error_does_not_echo_the_key():
    secret_looking_key = "super-secret-but-invalid-key"
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            app_env="prod", jwt_secret="a-real-secret", encryption_key=secret_looking_key,
            _env_file=None,
        )
    assert secret_looking_key not in str(excinfo.value)
