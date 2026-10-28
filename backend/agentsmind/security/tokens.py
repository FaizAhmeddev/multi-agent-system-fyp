"""JWT access tokens and opaque refresh / reset tokens."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from ..settings import get_settings

ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    roles: tuple[str, ...]
    jti: str
    iat: int
    exp: datetime


class TokenError(Exception):
    """Invalid, expired or wrong-type token."""


def create_access_token(user_id: int, roles: list[str], *, now: datetime | None = None) -> tuple[str, int]:
    s = get_settings()
    now = now or datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "roles": sorted(roles),
        "typ": "access",
        "iss": s.jwt_issuer,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    try:
        data = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if data.get("typ") != "access":
        raise TokenError("wrong token type")
    try:
        uid = int(data["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("bad subject") from exc
    return AccessClaims(
        user_id=uid,
        roles=tuple(data.get("roles") or ()),
        jti=data["jti"],
        iat=int(data["iat"]),
        exp=datetime.fromtimestamp(data["exp"], tz=UTC),
    )


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
