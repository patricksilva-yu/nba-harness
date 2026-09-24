"""Supabase Auth for the API: verify access tokens and describe who is asking.

Supabase issues the tokens; this module only checks them against the
project's published signing keys, so no Supabase secret is needed here.
`NBA_AUTH_MODE=disabled` keeps local development and unit tests open.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request


ALGORITHMS = ["ES256", "RS256"]
AUDIENCE = "authenticated"


@dataclass(frozen=True)
class Viewer:
    """The signed-in requester. `user_id` is None only when auth is disabled,
    which storage reads treat as unfiltered."""

    user_id: str | None
    is_admin: bool


def auth_mode() -> str:
    mode = os.getenv("NBA_AUTH_MODE", "supabase").strip().lower()
    if mode not in {"supabase", "disabled"}:
        raise HTTPException(status_code=503, detail="Invalid NBA_AUTH_MODE")
    return mode


def supabase_issuer() -> str:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=503, detail="Sign-in is not configured on the server")
    return f"{url}/auth/v1"


def admin_user_ids() -> set[str]:
    return {value.strip() for value in os.getenv("NBA_ADMIN_USER_IDS", "").split(",") if value.strip()}


@lru_cache(maxsize=4)
def jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600)


def signing_key(token: str, issuer: str):
    return jwks_client(issuer).get_signing_key_from_jwt(token).key


def verify_token(token: str) -> str:
    """Return the Supabase user id for a valid access token."""
    issuer = supabase_issuer()
    try:
        claims = jwt.decode(token, signing_key(token, issuer), algorithms=ALGORITHMS, audience=AUDIENCE,
                            issuer=issuer, options={"require": ["exp", "sub", "aud", "iss"]})
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(status_code=503, detail="Sign-in service unavailable") from exc
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    return claims["sub"]


def require_user(request: Request) -> Viewer:
    if auth_mode() == "disabled":
        return Viewer(user_id=None, is_admin=True)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    user_id = verify_token(token.strip())
    return Viewer(user_id=user_id, is_admin=user_id in admin_user_ids())


def require_admin(viewer: Viewer = Depends(require_user)) -> Viewer:
    if not viewer.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed")
    return viewer
