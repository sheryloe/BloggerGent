from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ENCRYPTION_PREFIX = "enc:v1:"


def _build_fernet() -> Fernet:
    seed = (settings.settings_encryption_secret or "bloggent-local-dev-secret").encode("utf-8")
    key = urlsafe_b64encode(sha256(seed).digest())
    return Fernet(key)


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(ENCRYPTION_PREFIX))


def encrypt_secret_value(value: str) -> str:
    if not value:
        return ""
    if is_encrypted_secret(value):
        return value
    token = _build_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTION_PREFIX}{token}"


def decrypt_secret_value(value: str) -> str:
    if not value:
        return ""
    if not is_encrypted_secret(value):
        return value
    token = value[len(ENCRYPTION_PREFIX) :]
    try:
        return _build_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value
