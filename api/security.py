"""Password hashing (scrypt, stdlib) and opaque session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2

MIN_PASSWORD = 10
MAX_PASSWORD = 128
_COMMON = {
    "password", "password1", "password12", "password123", "passw0rd123", "1234567890", "12345678901",
    "qwertyuiop", "qwerty12345", "iloveyou123", "welcome1234", "admin12345", "letmein1234",
    "abcdefghij", "0123456789", "1111111111", "svcetirupati", "campusai123",
}


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=DKLEN, maxmem=_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                                dklen=len(expected), maxmem=128 * n * r * 2)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_dummy_hash: str | None = None


def dummy_verify(password: str) -> None:
    """Spend comparable time when the account does not exist (limits user enumeration by timing)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(password, _dummy_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Only this digest is stored, so a database leak does not yield usable session tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_problem(password: str, *, email: str = "") -> str | None:
    """Return a user-facing reason the password is unacceptable, or None."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 4:
        return "That password is too easy to guess. Choose something less common."
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Your password should not contain your email name."
    return None
