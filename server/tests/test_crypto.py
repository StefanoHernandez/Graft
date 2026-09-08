import os

from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip():
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    from graft.config import get_settings
    get_settings.cache_clear()

    from graft.security import crypto

    secret = "sk-super-secret-provider-key"
    token = crypto.encrypt(secret)
    assert token != secret
    assert crypto.decrypt(token) == secret
