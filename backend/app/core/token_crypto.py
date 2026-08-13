from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

_DOMAIN_SEPARATOR = b"budget:plaid-access-token:v1\0"
_NONCE_BYTES = 12


def _key(secret: SecretStr) -> bytes:
    return hashlib.sha256(_DOMAIN_SEPARATOR + secret.get_secret_value().encode("utf-8")).digest()


def _aad(user_id: int, item_external_id: str) -> bytes:
    return f"budget:plaid-item:v1:user={user_id}:item={item_external_id}".encode()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encrypt_plaid_access_token(
    access_token: str,
    encryption_key: SecretStr,
    *,
    user_id: int,
    item_external_id: str,
) -> tuple[str, str]:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key(encryption_key)).encrypt(
        nonce,
        access_token.encode("utf-8"),
        _aad(user_id, item_external_id),
    )
    return _encode(ciphertext), _encode(nonce)


def decrypt_plaid_access_token(
    ciphertext: str,
    nonce: str,
    encryption_key: SecretStr,
    *,
    user_id: int,
    item_external_id: str,
) -> str:
    plaintext = AESGCM(_key(encryption_key)).decrypt(
        _decode(nonce),
        _decode(ciphertext),
        _aad(user_id, item_external_id),
    )
    return plaintext.decode("utf-8")
