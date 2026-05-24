"""JWKS-based JWT verification for Supabase Auth."""

import time
from typing import Any

import httpx
from jose import JWTError, jwk, jwt
from jose.constants import Algorithms

from app.config import settings

# In-memory JWKS cache
_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from Supabase with retry support."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(settings.supabase_jwks_url)
        response.raise_for_status()
        return response.json()


async def get_jwks() -> dict[str, Any]:
    """Get JWKS from cache or fetch fresh keys."""
    now = time.time()
    if not _jwks_cache or (now - _jwks_fetched_at) > JWKS_CACHE_TTL:
        try:
            _jwks_cache = await _fetch_jwks()
            _jwks_fetched_at = now
        except Exception as e:
            if not _jwks_cache:
                raise
    return _jwks_cache


def _get_signing_key(kid: str, jwks: dict[str, Any]) -> str:
    """Extract the signing key matching the key ID."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwk.construct(key).to_pem()
    msg = f"No signing key found for kid: {kid}"
    raise ValueError(msg)


async def verify_token(token: str) -> dict[str, Any] | None:
    """Verify a Supabase JWT. Returns decoded payload if valid, None otherwise."""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            return None

        jwks = await get_jwks()
        signing_key = _get_signing_key(kid, jwks)

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[Algorithms.ES256, Algorithms.RS256],
            options={"verify_aud": False},
        )
        return payload
    except JWTError:
        return None
    except Exception:
        return None
