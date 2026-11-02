"""Redis-backed rotating refresh tokens and login lockout (PLAN §18).

Refresh tokens belong to a *family* (one per login). Each refresh consumes the token (GETDEL,
atomic) and issues a new one in the same family. Presenting an already-used token means it was
stolen or replayed → the whole family is revoked (every device session from that login logs out).
Keys hold only SHA-256 hashes of tokens/emails (no PII in Redis).
"""

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.security import new_opaque_token, token_hash

_RT = "auth:rt:"  # token hash -> "user_id:family"
_RT_USED = "auth:rtused:"  # consumed token hash -> family (reuse detection)
_FAMILY = "auth:rtfam:"  # family -> user_id (family alive)
_FAIL = "auth:fail:"  # email hash -> failed attempts in window


class RefreshTokenError(Exception):
    """Refresh token unknown, expired, revoked or reused."""


@dataclass(frozen=True)
class IssuedRefresh:
    token: str
    user_id: uuid.UUID
    family: str


class RefreshTokenStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl = ttl_seconds

    async def issue(self, user_id: uuid.UUID, family: str | None = None) -> IssuedRefresh:
        family = family or uuid.uuid4().hex
        token = new_opaque_token()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(_FAMILY + family, str(user_id), ex=self.ttl)
            pipe.set(_RT + token_hash(token), f"{user_id}:{family}", ex=self.ttl)
            await pipe.execute()
        return IssuedRefresh(token=token, user_id=user_id, family=family)

    async def rotate(self, token: str) -> IssuedRefresh:
        h = token_hash(token)
        raw = await self.redis.getdel(_RT + h)
        if raw is None:
            reused_family = await self.redis.get(_RT_USED + h)
            if reused_family is not None:
                await self.redis.delete(_FAMILY + _s(reused_family))
            raise RefreshTokenError("invalid refresh token")
        user_part, family = _s(raw).split(":", 1)
        await self.redis.set(_RT_USED + h, family, ex=self.ttl)
        if not await self.redis.exists(_FAMILY + family):
            raise RefreshTokenError("session revoked")
        return await self.issue(uuid.UUID(user_part), family)

    async def revoke(self, token: str) -> None:
        raw = await self.redis.getdel(_RT + token_hash(token))
        if raw is not None:
            await self.redis.delete(_FAMILY + _s(raw).split(":", 1)[1])


class LoginLockout:
    """Lock an email after `threshold` failed logins within `window_seconds`."""

    def __init__(self, redis: Redis, threshold: int, window_seconds: int) -> None:
        self.redis = redis
        self.threshold = threshold
        self.window = window_seconds

    def _key(self, email: str) -> str:
        return _FAIL + token_hash(email.lower())

    async def retry_after(self, email: str) -> int | None:
        """Seconds until unlock if locked, else None."""
        key = self._key(email)
        count = await self.redis.get(key)
        if count is None or int(count) < self.threshold:
            return None
        ttl = int(await self.redis.ttl(key))
        return max(ttl, 1)

    async def record_failure(self, email: str) -> None:
        key = self._key(email)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self.window, nx=True)
            await pipe.execute()

    async def reset(self, email: str) -> None:
        await self.redis.delete(self._key(email))


def _s(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
