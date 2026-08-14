from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

_NONCE_BYTES = 12
_DOMAIN_SEPARATOR = b"budget:credential:v1\0"


def _key(secret: SecretStr) -> bytes:
    return hashlib.sha256(_DOMAIN_SEPARATOR + secret.get_secret_value().encode("utf-8")).digest()


def _aad(user_id: int, purpose: str) -> bytes:
    return f"budget:credential:v1:user={user_id}:purpose={purpose}".encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_user_secret(
    value: str,
    encryption_key: SecretStr,
    *,
    user_id: int,
    purpose: str,
) -> tuple[str, str]:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key(encryption_key)).encrypt(
        nonce,
        value.encode("utf-8"),
        _aad(user_id, purpose),
    )
    return _encode(ciphertext), _encode(nonce)


def decrypt_user_secret(
    ciphertext: str,
    nonce: str,
    encryption_key: SecretStr,
    *,
    user_id: int,
    purpose: str,
) -> str:
    plaintext = AESGCM(_key(encryption_key)).decrypt(
        _decode(nonce),
        _decode(ciphertext),
        _aad(user_id, purpose),
    )
    return plaintext.decode("utf-8")
