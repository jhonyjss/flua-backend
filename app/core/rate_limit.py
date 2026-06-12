"""In-memory sliding-window rate limiter (parity with server/utils/rateLimiter.ts).

Single-instance only — swap for Redis when running multiple replicas.
"""
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, status

from app.core.auth import AuthUser, get_current_user

_store: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, max_requests: int, window_seconds: float) -> bool:
    """True when the request is allowed; records the hit when allowed."""
    now = time.monotonic()
    timestamps = [ts for ts in _store[key] if now - ts < window_seconds]
    if len(timestamps) >= max_requests:
        _store[key] = timestamps
        return False
    timestamps.append(now)
    _store[key] = timestamps
    return True


def reset_rate_limits() -> None:
    """Test helper."""
    _store.clear()


def rate_limited(name: str, max_requests: int, window_seconds: float):
    """Dependency factory: per-user rate limit for a route group."""

    async def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not check_rate_limit(f"{name}:{user.id}", max_requests, window_seconds):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Muitas requisições. Tente novamente em instantes.",
            )
        return user

    return dependency
