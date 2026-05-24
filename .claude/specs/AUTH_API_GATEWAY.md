# SPEC: Auth & API Gateway

## Status
**Approved**

## Context

This document defines the authentication, authorization, and API Gateway architecture for the Doctor AI Agent SaaS platform. The API Gateway is the single entry point for all client requests — it handles JWT verification, RBAC enforcement, tenant context propagation, rate limiting, request validation, and routing to backend microservices.

The gateway is built with **FastAPI** and integrates with **Supabase Auth** for identity management. All downstream services trust the gateway's verified tenant context — they never re-verify tokens.

## Requirements

1. **JWT Authentication** — All API requests (except public endpoints) require a valid Supabase JWT. Tokens are verified using JWKS (asymmetric keys).
2. **Multi-Tenant RBAC** — Every authenticated request carries `tenant_id` and `role`. RBAC is enforced at the gateway before proxying to services.
3. **Tenant Context Propagation** — Verified tenant context is passed to downstream services via internal headers. Services trust these headers.
4. **Rate Limiting** — Per-tenant rate limits based on subscription tier. Different limits for different endpoint categories.
5. **Request Validation** — Input validation, request size limits, content-type enforcement.
6. **CORS** — Strict CORS policy allowing only the frontend origin.
7. **Audit** — All authentication events (login, logout, token refresh) are logged.
8. **Idempotency** — POST endpoints support idempotency keys for safe retries.
9. **Health Checks** — Liveness (`/health`) and readiness (`/health/ready`) endpoints exposed without auth.

## Design

### 1. Architecture Overview

```
                         ┌──────────────┐
                         │   Frontend   │
                         │ (Next.js 15) │
                         └──────┬───────┘
                                │
                     JWT Bearer Token
                                │
                         ┌──────▼───────┐
                         │  API Gateway  │
                         │ (FastAPI)     │
                         │               │
                         │ 1. CORS       │
                         │ 2. Rate Limit │
                         │ 3. Auth (JWT) │
                         │ 4. RBAC       │
                         │ 5. Proxy      │
                         └──────┬───────┘
                                │
                    Internal headers injected:
                    X-Tenant-ID, X-User-ID, X-User-Role
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
      ┌───────▼──────┐ ┌───────▼──────┐ ┌───────▼──────┐
      │ Appointment  │ │   Patient   │ │  AI Agent    │
      │   Service    │ │   Service   │ │   Service    │
      └──────────────┘ └─────────────┘ └──────────────┘
```

### 2. Authentication Flow

#### 2.1 Sign Up

```
Client → Supabase Auth (direct, NOT through gateway)
  → User created in auth.users
  → Trigger: auth hook creates team_member record
  → Trigger: auth hook creates tenant (clinic) if first user
  → Response: JWT (access + refresh tokens)
```

**Why direct to Supabase?** Sign-up uses Supabase's built-in auth UI/flows (magic link, OAuth, email+password). The gateway only handles API authentication, not user registration.

#### 2.2 Login

```
Client → Supabase Auth → JWT returned to client
Client → stores JWT (httpOnly cookie or memory)
Client → attaches JWT to all API requests: Authorization: Bearer <token>
```

#### 2.3 API Request Authentication (Gateway)

```
1. Client sends request with Authorization: Bearer <token>
2. Gateway extracts token from header
3. Gateway fetches JWKS from Supabase (cached, 1hr TTL)
4. Gateway verifies token: signature, expiry, audience
5. Gateway extracts claims: sub (user_id), app_metadata.tenant_id, app_metadata.role
6. Gateway injects internal headers for downstream services
7. Gateway proxies request to the target service
```

#### 2.4 JWKS Verification (Recommended for 2025+)

Supabase is transitioning from symmetric (HS256) to asymmetric (ES256) signing. JWKS-based verification is required.

```python
# app/gateway/auth.py
"""
JWKS-based JWT verification for Supabase Auth.
Uses asymmetric key verification (ES256).
JWKS is cached globally with periodic refresh.
"""

from jose import jwt, JWTError, jwk
from jose.constants import Algorithms
import httpx
from typing import Dict, Any, Optional
import os
import logging

logger = logging.getLogger(__name__)

SUPABASE_JWKS_URL = os.getenv(
    "SUPABASE_JWKS_URL",
    "https://<project>.supabase.co/auth/v1/.well-known/jwks.json",
)
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF")  # for audience verification

# In-memory cache
_jwks_cache: Dict[str, Any] = {}
_jwks_fetched_at: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_jwks() -> Dict[str, Any]:
    """Fetch JWKS from Supabase, with retry logic."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(SUPABASE_JWKS_URL)
        response.raise_for_status()
        return response.json()


async def get_jwks() -> Dict[str, Any]:
    """Get JWKS from cache or fetch fresh."""
    import time

    global _jwks_cache, _jwks_fetched_at

    now = time.time()
    if not _jwks_cache or (now - _jwks_fetched_at) > JWKS_CACHE_TTL:
        try:
            _jwks_cache = await _fetch_jwks()
            _jwks_fetched_at = now
        except Exception as e:
            logger.warning(f"Failed to fetch JWKS, using cache: {e}")
            if not _jwks_cache:
                raise  # No cache available, fail open is not safe here
    return _jwks_cache


def _get_signing_key(kid: str, jwks: Dict[str, Any]) -> str:
    """Extract the signing key matching the key ID."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwk.construct(key).to_pem()
    raise ValueError(f"No signing key found for kid: {kid}")


async def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Supabase JWT token.
    Returns the decoded payload if valid, None otherwise.
    """
    try:
        # Get key ID from unverified header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            logger.warning("Token missing 'kid' in header")
            return None

        # Get signing key
        jwks = await get_jwks()
        signing_key = _get_signing_key(kid, jwks)

        # Verify and decode
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[Algorithms.ES256, Algorithms.RS256],
            options={"verify_aud": False},  # Aud verification handled by Supabase SDK
        )
        return payload

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected token verification error: {e}")
        return None
```

### 2.5 Post-Signup Tenant Creation (Supabase Auth Webhook)

When a new user signs up, Supabase Auth fires a webhook. The gateway receives this webhook and atomically creates the tenant, default roles, and team member record — before the user makes their first API call.

```
User signs up → Supabase Auth → POST /api/v1/auth/webhook (Gateway)
  → Gateway validates HMAC signature (pre-shared key)
  → Begin transaction:
    1. INSERT INTO tenants (name, slug, tier)
    2. INSERT INTO roles (x4: admin, doctor, receptionist, viewer)
    3. INSERT INTO team_members (user_id, role=admin)
  → Commit transaction
  → Update auth.users.app_metadata: { tenant_id, role: "admin" }
  → Return 200 OK

User logs in → JWT now contains tenant_id + role → API calls work immediately
```

**Gateway webhook endpoint:**

```python
# app/gateway/webhooks.py
"""
Handles incoming webhooks from Supabase Auth.
Creates tenant + roles + team_member on user signup.
"""

import hmac
import hashlib
import os
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

webhook_router = APIRouter()
SUPABASE_WEBHOOK_SECRET = os.getenv("SUPABASE_WEBHOOK_SECRET")


class SignupEvent(BaseModel):
    type: str  # "user.signup"
    user_id: str
    email: str
    user_metadata: dict = {}


async def verify_supabase_webhook(request: Request) -> bytes:
    """Verify HMAC signature from Supabase webhook."""
    body = await request.body()
    signature = request.headers.get("x-supabase-signature", "")
    expected = hmac.new(
        SUPABASE_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return body


@webhook_router.post("/api/v1/auth/webhook")
async def handle_auth_webhook(request: Request):
    """Handle Supabase Auth webhook events."""
    body = await verify_supabase_webhook(request)
    event = SignupEvent.model_validate_json(body)

    if event.type == "user.signup":
        # Create tenant with default settings
        clinic_name = event.user_metadata.get("clinic_name", f"{event.email}'s Clinic")
        slug = clinic_name.lower().replace(" ", "-")[:50]

        async with get_db_session() as session:
            # Create tenant
            tenant = Tenant(name=clinic_name, slug=slug)
            session.add(tenant)
            await session.flush()

            # Create default roles
            default_roles = [
                Role(tenant_id=tenant.id, name="admin",
                     permissions=ADMIN_PERMISSIONS, is_system_role=True),
                Role(tenant_id=tenant.id, name="doctor",
                     permissions=DOCTOR_PERMISSIONS, is_system_role=True),
                Role(tenant_id=tenant.id, name="receptionist",
                     permissions=RECEPTIONIST_PERMISSIONS, is_system_role=True),
                Role(tenant_id=tenant.id, name="viewer",
                     permissions=VIEWER_PERMISSIONS, is_system_role=True),
            ]
            session.add_all(default_roles)
            await session.flush()

            # Link user as admin
            team_member = TeamMember(
                tenant_id=tenant.id,
                user_id=event.user_id,
                role_id=default_roles[0].id,  # admin role
                is_active=True,
                invited_at=datetime.utcnow(),
                joined_at=datetime.utcnow(),
            )
            session.add(team_member)
            await session.commit()

        # Update user's app_metadata via Supabase Admin API
        await update_user_metadata(
            user_id=event.user_id,
            metadata={"tenant_id": str(tenant.id), "role": "admin"},
        )

    return {"status": "ok"}
```

**Supabase webhook configuration (Supabase Dashboard → Database → Webhooks):**

| Setting | Value |
|---------|-------|
| Trigger | `on INSERT` for `auth.users` |
| HTTP Method | POST |
| URL | `https://api.doctorai.com/api/v1/auth/webhook` |
| Headers | `x-supabase-signature` (auto-added with shared secret) |
| Retry | 3 retries with exponential backoff |

### 3. Token Structure

#### 3.1 JWT Claims

Supabase JWT payload includes custom claims via `app_metadata`:

```json
{
  "sub": "user-uuid",
  "email": "doctor@clinic.com",
  "app_metadata": {
    "provider": "email",
    "tenant_id": "tenant-uuid",
    "role": "doctor"
  },
  "user_metadata": {
    "first_name": "Jane",
    "last_name": "Smith"
  },
  "iat": 1680000000,
  "exp": 1680000900,
  "aud": "authenticated"
}
```

**Important:** `tenant_id` and `role` are stored in `app_metadata` (not `user_metadata`), because `app_metadata` can only be modified server-side — users cannot tamper with it.

#### 3.2 Signed Internal JWT (Gateway → Services)

After verifying the user's JWT, the gateway creates a **short-lived internal JWT** signed with a service-only key. Services verify this internal JWT instead of trusting plain headers.

```python
# app/gateway/internal_jwt.py
"""
Creates and verifies short-lived internal JWTs for service-to-service auth.
Gateway signs. Services verify. Prevents header spoofing inside the cluster.
"""

import os
import time
import uuid
import jwt as pyjwt
from typing import Dict, Any, Optional

INTERNAL_SHARED_SECRET = os.getenv("INTERNAL_JWT_SECRET")
INTERNAL_JWT_TTL = 30  # seconds — very short-lived


def create_internal_token(
    user_id: str,
    tenant_id: str,
    role: str,
    email: str,
) -> str:
    """Create a short-lived internal JWT for downstream services."""
    now = int(time.time())
    payload = {
        "iss": "api-gateway",
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + INTERNAL_JWT_TTL,
    }
    return pyjwt.encode(payload, INTERNAL_SHARED_SECRET, algorithm="HS256")


def verify_internal_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify an internal JWT. Returns payload if valid, None otherwise."""
    try:
        payload = pyjwt.decode(
            token,
            INTERNAL_SHARED_SECRET,
            algorithms=["HS256"],
            options={"require": ["iss", "tenant_id", "role", "jti"]},
        )
        if payload.get("iss") != "api-gateway":
            return None
        return payload
    except pyjwt.PyJWTError:
        return None
```

**Header format passed to services:**

| Header | Value | Description |
|--------|-------|-------------|
| `X-Internal-JWT` | `{signed_token}` | Short-lived (30s) internal JWT with claims |
| `X-Idempotency-Key` | Request header | Pass-through for idempotency |

**Service-side validation (in every service middleware):**

```python
# Shared middleware in each service
from fastapi import Request, HTTPException
from .internal_jwt import verify_internal_token


async def verify_gateway_request(request: Request):
    """Dependency: verifies the internal JWT from the gateway."""
    internal_jwt = request.headers.get("X-Internal-JWT")
    if not internal_jwt:
        raise HTTPException(status_code=401, detail="Missing internal JWT")

    payload = verify_internal_token(internal_jwt)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired internal JWT")

    # Set request state from verified payload
    request.state.user_id = payload["sub"]
    request.state.tenant_id = payload["tenant_id"]
    request.state.user_role = payload["role"]
    request.state.user_email = payload.get("email", "")

    return payload
```

Services **MUST** also validate that `tenant_id` from the internal JWT matches the `tenant_id` in any request body or path parameter, as defense-in-depth.

### 4. RBAC (Role-Based Access Control)

#### 4.1 Role Definitions

| Role | Scope | Permissions |
|------|-------|-------------|
| `admin` | Full access | Create/read/update/delete all resources. Manage team members. View billing. |
| `doctor` | Clinical | Read/write patient records, appointments, medical summaries. View schedule. |
| `receptionist` | Operational | Create/read/update appointments, register patients. Read-only on medical records. |
| `viewer` | Read-only | View appointments, schedules, patient demographics. Cannot view clinical notes. |

#### 4.2 RBAC Enforcement

```python
# app/gateway/rbac.py
"""
RBAC middleware for FastAPI API Gateway.
Enforces role-based access per endpoint.
"""

from enum import Enum
from functools import wraps
from fastapi import HTTPException, Request
from typing import List, Callable


class Role(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    RECEPTIONIST = "receptionist"
    VIEWER = "viewer"


# Permission hierarchy (higher includes lower)
ROLE_HIERARCHY = {
    Role.ADMIN: 100,
    Role.DOCTOR: 80,
    Role.RECEPTIONIST: 60,
    Role.VIEWER: 40,
}

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "appointments:read": [Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST, Role.VIEWER],
    "appointments:write": [Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST],
    "appointments:delete": [Role.ADMIN],
    "patients:read": [Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST, Role.VIEWER],
    "patients:write": [Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST],
    "patients:clinical:read": [Role.ADMIN, Role.DOCTOR],
    "patients:clinical:write": [Role.ADMIN, Role.DOCTOR],
    "medical_summaries:write": [Role.ADMIN, Role.DOCTOR],
    "billing:read": [Role.ADMIN],
    "billing:write": [Role.ADMIN],
    "team:manage": [Role.ADMIN],
    "ai:chat": [Role.ADMIN, Role.DOCTOR, Role.RECEPTIONIST],
}


def require_permission(permission: str):
    """
    Dependency for FastAPI: checks if the authenticated user has the required permission.
    Usage:
        @router.get("/patients/{id}")
        async def get_patient(
            request: Request,
            _=Depends(require_permission("patients:read"))
        ):
    """
    async def permission_checker(request: Request) -> None:
        user_role = request.state.user_role
        allowed_roles = ROLE_PERMISSIONS.get(permission, [])

        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "https://api.doctorai.com/errors/insufficient-permissions",
                    "title": "Insufficient Permissions",
                    "status": 403,
                    "detail": f"Role '{user_role}' requires permission '{permission}'",
                },
            )

    return permission_checker
```

#### 4.3 Permission-to-Endpoint Mapping

| Endpoint Pattern | Required Permission | Roles |
|-----------------|-------------------|-------|
| `GET /api/v1/appointments` | `appointments:read` | All |
| `POST /api/v1/appointments` | `appointments:write` | admin, doctor, receptionist |
| `DELETE /api/v1/appointments/{id}` | `appointments:delete` | admin only |
| `GET /api/v1/patients` | `patients:read` | All |
| `GET /api/v1/patients/{id}/records` | `patients:clinical:read` | admin, doctor |
| `POST /api/v1/patients` | `patients:write` | admin, doctor, receptionist |
| `POST /api/v1/ai/summary` | `medical_summaries:write` | admin, doctor |
| `GET /api/v1/billing/subscription` | `billing:read` | admin only |
| `GET /api/v1/ai/chat` | `ai:chat` | admin, doctor, receptionist |
| `POST /api/v1/team/members` | `team:manage` | admin only |

### 5. Rate Limiting

#### 5.1 Per-Tenant Rate Limits by Tier

| Plan Tier | General API | AI Chat (SSE) | Auth Endpoints |
|-----------|-------------|---------------|----------------|
| **Free** | 60 req/min | 10 req/min | 5 req/min (login) |
| **Pro** | 300 req/min | 60 req/min | 20 req/min (login) |
| **Enterprise** | 1000 req/min | 200 req/min | Custom |

#### 5.2 Rate Limiting Implementation

Uses **sliding window** with Redis for accurate per-tenant counting without clock boundary issues.

```python
# app/gateway/rate_limiter.py
"""
Per-tenant sliding window rate limiter using Redis.
Limits are tier-based, stored in Redis for distributed consistency.
"""

import time
import hashlib
from typing import Optional
import redis.asyncio as redis_async
from fastapi import HTTPException, Request


# Tier limits: {tier: {scope: (limit, window_seconds)}}
TIER_LIMITS = {
    "free": {
        "general": (60, 60),
        "ai_chat": (10, 60),
        "auth": (5, 60),
    },
    "pro": {
        "general": (300, 60),
        "ai_chat": (60, 60),
        "auth": (20, 60),
    },
    "enterprise": {
        "general": (1000, 60),
        "ai_chat": (200, 60),
        "auth": (100, 60),
    },
}


class RateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets.
    Each request adds a timestamped member to a sorted set.
    The window is calculated by removing entries outside the window.
    """

    def __init__(self, redis_client: redis_async.Redis):
        self.redis = redis_client

    async def check(
        self,
        tenant_id: str,
        tier: str,
        scope: str = "general",
        cost: int = 1,
    ) -> bool:
        """
        Check if the request is within rate limits.
        Returns True if allowed, False if rate limited.
        """
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        limit, window = limits.get(scope, limits["general"])

        # Key: tenant-scoped rate limit
        key = f"rl:{tenant_id}:{scope}"
        now = time.time()
        window_start = now - window

        # Use pipeline for atomicity
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)  # Remove old entries
        pipe.zcard(key)                                # Count current entries
        pipe.zadd(key, {f"{now}:{cost}": now})        # Add current request
        pipe.expire(key, window)                       # Set TTL

        _, count, _, _ = await pipe.execute()

        return count < limit

    async def get_remaining(self, tenant_id: str, tier: str, scope: str = "general") -> int:
        """Get remaining requests in the current window."""
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        limit, window = limits.get(scope, limits["general"])

        key = f"rl:{tenant_id}:{scope}"
        now = time.time()
        window_start = now - window

        await self.redis.zremrangebyscore(key, 0, window_start)
        count = await self.redis.zcard(key)

        return max(0, limit - count)


async def rate_limit_middleware(request: Request, call_next):
    """
    FastAPI middleware for rate limiting with tiered failover.
    - Auth scope: fail closed (503) if Redis is down
    - General/AI scope: fail open (log and pass) if Redis is down
    """
    # Skip rate limiting for health checks
    if request.url.path in ("/health", "/health/ready"):
        return await call_next(request)

    tenant_id = getattr(request.state, "tenant_id", "anonymous")
    tier = getattr(request.state, "tier", "free")

    # Determine scope from path
    scope = "general"
    if "/ai/" in request.url.path:
        scope = "ai_chat"
    elif "/auth/" in request.url.path:
        scope = "auth"

    limiter: RateLimiter = request.app.state.rate_limiter

    try:
        allowed = await limiter.check(tenant_id, tier, scope)
    except ConnectionError:
        # Tiered failover: auth fails closed, everything else fails open
        if scope == "auth":
            raise HTTPException(
                status_code=503,
                detail={
                    "type": "https://api.doctorai.com/errors/service-unavailable",
                    "title": "Rate Limiter Unavailable",
                    "status": 503,
                    "detail": "Rate limiting service is temporarily unavailable. Please retry.",
                },
            )
        # General/AI: fail open -- log and allow
        logger.warning(
            "rate_limiter_unavailable",
            tenant_id=tenant_id,
            scope=scope,
            message="Redis unreachable, rate limiting bypassed for non-auth scope",
        )
        response = await call_next(request)
        return response

    if not allowed:
        retry_after = 60
        raise HTTPException(
            status_code=429,
            detail={
                "type": "https://api.doctorai.com/errors/rate-limited",
                "title": "Rate Limit Exceeded",
                "status": 429,
                "detail": f"Tenant rate limit exceeded for scope: {scope}",
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(TIER_LIMITS[tier][scope][0]),
            },
        )

    # Set response headers
    remaining = await limiter.get_remaining(tenant_id, tier, scope)
    request.state.rate_limit_remaining = remaining
    request.state.rate_limit_limit = TIER_LIMITS[tier][scope][0]

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Limit"] = str(TIER_LIMITS[tier][scope][0])
    return response
```

### 6. API Gateway Middleware Stack

Middleware executes in this order. Each middleware adds or validates context.

```
Request → CORS → Rate Limit → Auth → RBAC → Proxy → Service
                                                     │
Response ← CORS ← Rate Limit ← Auth ← RBAC ← Proxy ←┘
```

#### 6.1 Middleware Definitions

```python
# app/gateway/middleware.py
"""
API Gateway middleware stack definition.
Each middleware has a single responsibility.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import time
import uuid
import logging

logger = logging.getLogger(__name__)


def setup_middleware(app: FastAPI):
    """Register all gateway middleware in order."""

    # 1. CORS (outermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
        max_age=600,  # Preflight cache: 10 min
    )

    # 2. Request ID
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        start_time = time.time()

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        request.state.latency = time.time() - start_time
        return response

    # 3. Request Logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        response = await call_next(request)
        logger.info(
            "api_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round(getattr(request.state, "latency", 0) * 1000, 2),
            tenant_id=getattr(request.state, "tenant_id", "unknown"),
            user_id=getattr(request.state, "user_id", "unknown"),
            request_id=getattr(request.state, "request_id", "unknown"),
        )
        return response
```

#### 6.2 Auth Middleware

```python
# app/gateway/auth_middleware.py
"""
Authentication middleware: verifies JWT and extracts user context.
Applied to all routes except public ones.
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from .auth import verify_token

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Extracts and verifies JWT from Authorization header.
    Sets request.state with user context on success.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip auth for OPTIONS (CORS preflight, handled by CORS middleware)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "https://api.doctorai.com/errors/missing-token",
                    "title": "Missing Authentication Token",
                    "status": 401,
                    "detail": "Authorization header must be: Bearer <token>",
                },
            )

        token = auth_header.split("Bearer ")[-1].strip()

        # Verify token
        payload = await verify_token(token)
        if payload is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "https://api.doctorai.com/errors/invalid-token",
                    "title": "Invalid or Expired Token",
                    "status": 401,
                    "detail": "Token is invalid or expired. Please refresh.",
                },
            )

        # Extract claims
        app_metadata = payload.get("app_metadata", {})
        tenant_id = app_metadata.get("tenant_id")
        role = app_metadata.get("role", "viewer")

        if not tenant_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "https://api.doctorai.com/errors/no-tenant",
                    "title": "No Tenant Association",
                    "status": 403,
                    "detail": "User is not associated with any tenant.",
                },
            )

        # Set request state
        request.state.user_id = payload.get("sub")
        request.state.tenant_id = tenant_id
        request.state.user_role = role
        request.state.user_email = payload.get("email")
        request.state.tier = app_metadata.get("tier", "free")

        # Create signed internal JWT for downstream services
        internal_token = create_internal_token(
            user_id=payload.get("sub"),
            tenant_id=tenant_id,
            role=role,
            email=payload.get("email", ""),
        )
        request.state.internal_token = internal_token

        return await call_next(request)
```

### 7. Request Routing

The gateway routes requests to the appropriate backend service. Two patterns are used:

#### 7.1 Direct REST Proxy (for CRUD operations)

```python
# app/gateway/router.py
"""
Routes API requests to backend services.
Uses httpx.AsyncClient for proxying.
"""

import httpx
from fastapi import APIRouter, Request, Response
from typing import Optional

router = APIRouter()

# Service registry
SERVICE_URLS = {
    "appointment": os.getenv("APPOINTMENT_SERVICE_URL", "http://appointment-service:8001"),
    "patient": os.getenv("PATIENT_SERVICE_URL", "http://patient-service:8002"),
    "doctor": os.getenv("DOCTOR_SERVICE_URL", "http://doctor-service:8003"),
    "billing": os.getenv("BILLING_SERVICE_URL", "http://billing-service:8004"),
    "ai": os.getenv("AI_SERVICE_URL", "http://ai-service:8005"),
}

# Route map: path prefix → service name
ROUTE_MAP = {
    "/api/v1/appointments": "appointment",
    "/api/v1/patients": "patient",
    "/api/v1/doctors": "doctor",
    "/api/v1/billing": "billing",
    "/api/v1/ai": "ai",
}


async def proxy_request(request: Request, service_name: str, path: str) -> Response:
    """Proxy an HTTP request to the target service with internal headers."""
    service_url = SERVICE_URLS.get(service_name)
    if not service_url:
        return Response(
            status_code=502,
            content=f'{{"detail": "Service not found: {service_name}"}}',
            media_type="application/json",
        )

    target_url = f"{service_url}{path}"

    # Build request with internal headers
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Authorization", None)  # Don't forward raw JWT to services

    # Inject internal auth headers
    internal = getattr(request.state, "internal_headers", {})
    headers.update(internal)

    # Forward idempotency key
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    # Proxy the request
    body = await request.body()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=request.query_params,
        )

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("content-type", "application/json"),
    )


# Catch-all route for proxying
@router.api_route("/api/v1/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_handler(request: Request, service: str, path: str):
    service_name = ROUTE_MAP.get(f"/api/v1/{service}")
    if not service_name:
        return Response(status_code=404, content='{"detail": "Route not found"}')

    return await proxy_request(request, service_name, f"/api/v1/{service}/{path}")
```

#### 7.2 SSE Streaming Proxy (for AI Chat)

```python
# app/gateway/streaming.py
"""
Special proxy for SSE streaming endpoints (AI chat).
Uses async iteration to stream chunks to the client.
"""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import httpx

stream_router = APIRouter()


@stream_router.get("/api/v1/ai/chat/stream")
async def proxy_ai_stream(request: Request):
    """Proxy SSE stream from AI Agent Service to the client."""
    ai_service_url = os.getenv("AI_SERVICE_URL", "http://ai-service:8005")
    target_url = f"{ai_service_url}/api/v1/ai/chat/stream?{request.query_params}"

    internal = getattr(request.state, "internal_headers", {})

    async def _stream():
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", target_url, headers=internal) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

### 8. Idempotency

POST endpoints support idempotency via the `Idempotency-Key` header.

```python
# app/gateway/idempotency.py
"""
Idempotency middleware for POST endpoints.
Deduplicates requests with the same idempotency key within 24 hours.
"""

import hashlib
import json
from fastapi import Request, Response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Checks Idempotency-Key header on POST requests.
    If the key was already processed, returns the cached response.
    Otherwise, processes the request and caches the response.
    """

    def __init__(self, app, redis_client):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):
        # Only apply to POST
        if request.method != "POST":
            return await call_next(request)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # Check cache
        cache_key = f"idempotency:{idempotency_key}"
        cached = await self.redis.get(cache_key)

        if cached:
            # Return cached response
            data = json.loads(cached)
            return Response(
                content=data["body"],
                status_code=data["status"],
                headers={**data.get("headers", {}), "X-Idempotency-Cached": "true"},
                media_type="application/json",
            )

        # Process request
        response = await call_next(request)

        # Cache successful responses only
        if response.status_code < 500:
            await self.redis.set(
                cache_key,
                json.dumps({
                    "body": response.body.decode(),
                    "status": response.status_code,
                    "headers": dict(response.headers),
                }),
                ex=86400,  # 24 hours
            )

        return response
```

### 9. Public Endpoints (No Auth)

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `GET /health` | Liveness check | None |
| `GET /health/ready` | Readiness check (DB, Redis, Kafka connected) | None |
| `GET /docs` | OpenAPI docs (dev/staging only) | None |
| `GET /redoc` | ReDoc docs (dev/staging only) | None |

### 10. Error Responses

All errors follow RFC 9457 Problem Details format.

#### 10.1 Authentication Errors

```json
{
  "type": "https://api.doctorai.com/errors/missing-token",
  "title": "Missing Authentication Token",
  "status": 401,
  "detail": "Authorization header must be: Bearer <token>",
  "instance": "/api/v1/appointments"
}
```

```json
{
  "type": "https://api.doctorai.com/errors/invalid-token",
  "title": "Invalid or Expired Token",
  "status": 401,
  "detail": "Token is invalid or expired. Please refresh.",
  "instance": "/api/v1/patients"
}
```

#### 10.2 Authorization Errors

```json
{
  "type": "https://api.doctorai.com/errors/insufficient-permissions",
  "title": "Insufficient Permissions",
  "status": 403,
  "detail": "Role 'receptionist' does not have permission 'patients:clinical:read'",
  "instance": "/api/v1/patients/abc/records"
}
```

#### 10.3 Rate Limit Errors

```json
{
  "type": "https://api.doctorai.com/errors/rate-limited",
  "title": "Rate Limit Exceeded",
  "status": 429,
  "detail": "Tenant rate limit exceeded for scope: general. 60 requests per minute allowed.",
  "instance": "/api/v1/appointments"
}
```

### 11. Service Dependencies

The gateway depends on:
- **Supabase Auth** — For JWKS endpoint (token verification)
- **Redis** — For rate limiting counters, idempotency cache
- **Backend Services** — Appointment, Patient, Doctor, Billing, AI Agent (for proxying)

The gateway does NOT depend on PostgreSQL directly. It only authenticates and routes.

### 12. Middleware Error Handler

```python
# app/gateway/error_handler.py
"""
Global error handler for the API Gateway.
Catches all exceptions and returns RFC 9457 Problem Details responses.
"""

from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


async def gateway_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with RFC 9457 Problem Details format."""
    # If already in Problem Details format, pass through
    if isinstance(exc.detail, dict) and "type" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                **exc.detail,
                "instance": str(request.url.path),
            },
            headers=exc.headers,
        )

    # Convert standard HTTPException to Problem Details
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://api.doctorai.com/errors/http-{exc.status_code}",
            "title": exc.detail or HTTPStatus(exc.status_code).phrase,
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": str(request.url.path),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://api.doctorai.com/errors/validation-error",
            "title": "Request Validation Error",
            "status": 422,
            "detail": "One or more fields failed validation.",
            "instance": str(request.url.path),
            "errors": exc.errors(),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unexpected errors. Never leaks stack traces."""
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://api.doctorai.com/errors/internal-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": str(request.url.path),
        },
    )
```

### 13. Gateway Application Factory

```python
# app/gateway/main.py
"""
FastAPI application factory for the API Gateway.
Wires up all middleware, routes, and error handlers.
"""

import os
import redis.asyncio as redis_async
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .middleware import setup_middleware, log_requests
from .auth_middleware import AuthMiddleware
from .rate_limiter import RateLimiter, rate_limit_middleware
from .router import router
from .streaming import stream_router
from .error_handler import (
    gateway_exception_handler,
    validation_exception_handler,
    unhandled_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Startup: initialize connections
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_client = redis_async.from_url(redis_url, decode_responses=True)
    app.state.rate_limiter = RateLimiter(redis_client)
    app.state.redis = redis_client
    yield
    # Shutdown: close connections
    await redis_client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Doctor AI Agent API Gateway",
        version="1.0.0",
        docs_url="/docs" if os.getenv("ENVIRONMENT") != "production" else None,
        redoc_url="/redoc" if os.getenv("ENVIRONMENT") != "production" else None,
        lifespan=lifespan,
    )

    # Register middleware (order matters)
    setup_middleware(app)
    app.add_middleware(AuthMiddleware)

    # Register error handlers
    app.add_exception_handler(StarletteHTTPException, gateway_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Register routes
    app.include_router(router)
    app.include_router(stream_router)

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/health/ready")
    async def readiness():
        # Check Redis connection
        try:
            await app.state.redis.ping()
            redis_ok = True
        except Exception:
            redis_ok = False
        return {"status": "ready" if redis_ok else "degraded", "redis": redis_ok}

    return app
```

### 14. Environment Variables

```env
# Supabase Auth
SUPABASE_JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json
SUPABASE_PROJECT_REF=your_project_ref

# Redis
REDIS_URL=redis://redis:6379/0

# Backend Services
APPOINTMENT_SERVICE_URL=http://appointment-service:8001
PATIENT_SERVICE_URL=http://patient-service:8002
DOCTOR_SERVICE_URL=http://doctor-service:8003
BILLING_SERVICE_URL=http://billing-service:8004
AI_SERVICE_URL=http://ai-service:8005

# Gateway
FRONTEND_URL=http://localhost:3000
ENVIRONMENT=development  # development | staging | production
LOG_LEVEL=INFO
```

## Out of Scope

1. **User Registration Flows** — Sign-up, email verification, password reset handled by Supabase Auth directly, not the gateway.
2. **Social Login Configuration** — Google, Apple, etc. OAuth configured in Supabase dashboard, not in code.
3. **Session Management** — Token refresh is a client-side concern. Gateway validates tokens only.
4. **WebSocket Authentication** — Not needed for MVP. Will be added when real-time features are implemented.
5. **mTLS Between Services** — Service-to-service communication uses internal network, not mTLS (MVP scope).

## Data Flow

### Flow 1: Authenticated API Request

```
1. Client sends POST /api/v1/appointments
   Headers: Authorization: Bearer <jwt>, Content-Type: application/json

2. Gateway: CORS middleware validates origin

3. Gateway: Rate limiter checks Redis
   Key: rl:{tenant_id}:general
   → If over limit: return 429

4. Gateway: Auth middleware
   a. Extract Bearer token
   b. Fetch JWKS from cache (or Supabase)
   c. Verify token signature (ES256/RS256)
   d. Extract claims: sub, tenant_id, role, tier
   e. Set request.state: user_id, tenant_id, user_role, tier

5. Gateway: RBAC check
   → POST /api/v1/appointments requires "appointments:write"
   → If role is 'viewer': return 403

6. Gateway: Proxy request
   a. Strip Authorization header
   b. Inject internal headers: X-Tenant-ID, X-User-ID, X-User-Role
   c. Forward to http://appointment-service:8001/api/v1/appointments

7. Appointment Service: Extracts X-Tenant-ID from header
   a. Sets PostgreSQL session variable: SET app.current_tenant_id = 'uuid'
   b. Creates appointment with tenant_id from header (never from request body)
   c. Returns response

8. Gateway: Returns response to client
   Headers: X-Request-ID, X-RateLimit-Remaining, X-RateLimit-Limit
```

### Flow 2: Token Refresh

```
1. Client detects expired token (401 response)
2. Client sends refresh token to Supabase Auth
3. Supabase returns new access + refresh tokens
4. Client stores new tokens
5. Client retries original request with new token
```

## Implementation Plan

### Phase 1: Core Gateway (MVP)
1. Set up FastAPI project structure
2. Implement JWKS verification
3. Implement auth middleware with JWT extraction
4. Implement RBAC dependency
5. Implement proxy routing
6. Set up health checks
7. Write tenant isolation tests

### Phase 2: Rate Limiting
1. Set up Redis connection
2. Implement sliding window rate limiter
3. Implement rate limit middleware
4. Add rate limit response headers
5. Write rate limit tests

### Phase 3: Hardening
1. Implement idempotency middleware
2. Add request logging with structured logging
3. Set up Prometheus metrics
4. Add CORS hardening
5. Penetration test auth flows

## Testing

### Unit Tests

1. **Token verification** — Test valid, expired, malformed, and wrong-audience JWTs.
2. **RBAC enforcement** — Test each role's access to each endpoint permission.
3. **Rate limiting** — Test per-tier limits, window reset, concurrent requests.
4. **Idempotency** — Test same key returns cached response, different keys are independent.
5. **Proxy routing** — Test correct service routing for each path prefix.
6. **Error responses** — Test RFC 9457 format for all error types.

### Integration Tests

1. **Full auth flow** — Sign up → login → call protected endpoint → refresh → call again.
2. **Tenant isolation** — Tenant A's token cannot access Tenant B's data.
3. **Rate limit enforcement** — Exceed limit → 429 → wait → request succeeds.
4. **SSE streaming** — AI chat SSE stream reaches client with correct format.

### Security Tests

1. **Token tampering** — Modified JWT signature is rejected.
2. **Token replay** — Same token used from different IPs (detect and log, don't block).
3. **No tenant context** — JWT without tenant_id in claims returns 403.
4. **Direct service access** — Verify services reject requests without internal headers.

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| JWKS-based verification over shared secret | Supabase migrating to asymmetric keys by late 2026. JWKS is forward-compatible. | 2026-05 |
| FastAPI dependency injection over middleware | More testable, works with typed dependencies, standard FastAPI pattern. Auth middleware is the exception (sets request state). | 2026-05 |
| Sliding window over fixed window | No boundary bursts (fixed window allows 2x traffic at window edges). Redis sorted sets are accurate and atomic. | 2026-05 |
| Signed internal JWT (X-Internal-JWT) over plain headers | Prevents header spoofing inside the cluster. Services verify a short-lived (30s) signed JWT instead of trusting plain headers. Standard pattern (same as K8s ServiceAccount tokens). | 2026-05 |
| Supabase Auth webhook for post-signup tenant creation | Zero-lag setup — tenant + roles exist before user's first API call. Supabase webhooks are reliable (retry with backoff). Avoids race conditions from lazy creation. | 2026-05 |
| Direct client→Supabase for auth not through gateway | Supabase handles signup, OAuth, email verification natively. Gateway focuses on API security, not identity management. | 2026-05 |
| `app_metadata` for tenant_id and role | JWT `app_metadata` is server-write-only (via Supabase admin API). Users cannot tamper with tenant context. | 2026-05 |
| Tiered rate limit failover | Auth scope fails closed (503), general/AI scope fails open (log + pass). Balances security for auth with availability for clinical operations. | 2026-05 |

---

*This spec defines the authentication, authorization, and gateway layer. Every request passes through this gateway before reaching backend services. Downstream services MUST validate X-Tenant-ID against their own data as defense-in-depth.*
