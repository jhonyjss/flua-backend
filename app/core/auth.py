"""Supabase JWT authentication.

The Nuxt app sends the user's Supabase access token as `Authorization: Bearer`.

Two verification paths (the project migrated to "JWT Signing Keys"):
- **HS256** (current key = migrated legacy secret): verified with
  SUPABASE_JWT_SECRET.
- **ES256/RS256** (after rotating to the standby ECC key): verified against the
  project's public JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`),
  cached by PyJWKClient — no shared secret needed.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None

ASYMMETRIC_ALGS = {"ES256", "RS256", "EdDSA"}


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None
    role: str | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    settings = get_settings()
    if not settings.supabase_url:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SUPABASE_URL not configured")
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )
    return _jwks_client


def _resolve_asymmetric_key(token: str):
    """Resolve the public key for an asymmetric token (mockable in tests)."""
    return _get_jwks_client().get_signing_key_from_jwt(token).key


def _decode(token: str) -> dict:
    settings = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg", "HS256")
    except jwt.PyJWTError as err:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from err

    options = {"require": ["exp", "sub"]}
    try:
        if alg in ASYMMETRIC_ALGS:
            key = _resolve_asymmetric_key(token)
            return jwt.decode(token, key, algorithms=[alg], audience="authenticated", options=options)
        if not settings.supabase_jwt_secret:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SUPABASE_JWT_SECRET not configured")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options=options,
        )
    except jwt.PyJWTError as err:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from err


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """FastAPI dependency: resolve the authenticated Supabase user or 401."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    claims = _decode(credentials.credentials)
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing subject")
    return AuthUser(id=sub, email=claims.get("email"), role=claims.get("role") or claims.get("user_role"))
