"""Password hashing and redirect validation for CryoStack authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlparse


_SALT_BYTES = 16
_KEY_BYTES = 64
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """Return a salted scrypt password hash suitable for database storage."""
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")

    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )

    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${salt.hex()}${key.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password against a value returned by :func:`hash_password`."""
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False

        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(candidate.hex(), expected_hex)


def safe_return_to(value: str | None, default: str = "/index.html") -> str:
    """Accept only same-site relative paths as post-authentication redirects."""
    if not value:
        return default

    value = value.strip()
    parsed = urlparse(value)

    if parsed.scheme or parsed.netloc:
        return default

    if not value.startswith("/") or value.startswith("//"):
        return default

    return value
