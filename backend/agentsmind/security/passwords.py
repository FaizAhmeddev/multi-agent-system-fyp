"""Password hashing (Argon2id via argon2-cffi) and password policy."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id, library defaults (RFC 9106 low-memory profile)

# A dummy hash so unknown-email logins spend the same time as real ones.
_DUMMY_HASH = _hasher.hash("agentsmind-timing-equaliser")

_COMMON = {
    "password", "password123", "123456789012", "qwertyuiop12", "admin12345678",
    "letmein12345", "welcome12345", "iloveyou1234", "changeme1234",
}


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, plain) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


def password_problems(plain: str, *, email: str = "", min_length: int = 12) -> list[str]:
    """Return human-readable reasons a password is unacceptable (empty list = ok)."""
    problems: list[str] = []
    if len(plain) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    if len(plain) > 128:
        problems.append("Use at most 128 characters.")
    if plain.lower() in _COMMON:
        problems.append("This password is too common.")
    local = email.split("@", 1)[0].lower() if email else ""
    if local and len(local) >= 3 and local in plain.lower():
        problems.append("Do not include your email name in the password.")
    if len(set(plain)) < 5:
        problems.append("Use a less repetitive password.")
    return problems
