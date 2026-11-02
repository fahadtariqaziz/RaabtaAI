"""Password hashing (argon2), password rules, access JWTs and opaque tokens (PLAN §4 Auth, §18).

Access token: HS256 JWT, 15 min, claims `sub` (user id), `typ=access`, `iat`, `exp`, `jti`.
It carries no institution — the active institution comes from the `X-Institution` header and is
checked against memberships on every request. Refresh/invite tokens are opaque random strings;
only their SHA-256 is stored.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Hash of a random string: verifying against it keeps unknown-email logins as slow as real ones.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

PASSWORD_MIN_LEN = 10
PASSWORD_MAX_LEN = 128
JWT_ALGORITHM = "HS256"


class PasswordPolicyError(ValueError):
    """Password does not meet the rules (message is safe to show the user)."""


class TokenError(Exception):
    """Access token missing, expired or invalid."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time: always runs one argon2 verify, even when there is no hash."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password(password: str, *, email: str | None = None) -> None:
    if len(password) < PASSWORD_MIN_LEN:
        raise PasswordPolicyError(f"Password must be at least {PASSWORD_MIN_LEN} characters")
    if len(password) > PASSWORD_MAX_LEN:
        raise PasswordPolicyError(f"Password must be at most {PASSWORD_MAX_LEN} characters")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise PasswordPolicyError("Password must contain letters and digits")
    if email and password.lower() in {email.lower(), email.split("@")[0].lower()}:
        raise PasswordPolicyError("Password must not be your email")


def create_access_token(
    user_id: uuid.UUID, *, secret: str, ttl: timedelta, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub", "typ"]}
        )
        if claims["typ"] != "access":
            raise TokenError("wrong token type")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise TokenError(str(exc)) from None


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
