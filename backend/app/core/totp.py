from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    return base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)


def totp_code(secret: str, *, timestamp: int | None = None, step: int = 30, digits: int = 6) -> str:
    counter = int((timestamp if timestamp is not None else time.time()) // step)
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def matching_totp_counter(
    secret: str, code: str, *, timestamp: int | None = None, window: int = 1, step: int = 30
) -> int | None:
    candidate = code.strip().replace(" ", "")
    if len(candidate) != 6 or not candidate.isdigit():
        return None
    current = timestamp if timestamp is not None else int(time.time())
    current_counter = current // step
    for offset in range(-window, window + 1):
        counter = current_counter + offset
        if counter < 0:
            continue
        if hmac.compare_digest(totp_code(secret, timestamp=counter * step, step=step), candidate):
            return counter
    return None


def verify_totp(secret: str, code: str, *, timestamp: int | None = None, window: int = 1) -> bool:
    return matching_totp_counter(secret, code, timestamp=timestamp, window=window) is not None


def otpauth_uri(secret: str, *, email: str, issuer: str = "Budget") -> str:
    label = f"{issuer}:{email}"
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": "6", "period": "30"})
    return f"otpauth://totp/{quote(label, safe='')}?{query}"
