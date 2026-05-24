"""Proxy routing for forwarding requests to backend services."""

import os

import httpx
from fastapi import APIRouter, Request, Response

router = APIRouter()

# Service registry (for when backend services are built)
SERVICE_URLS = {
    "appointment": os.getenv("APPOINTMENT_SERVICE_URL", "http://appointment-service:8001"),
    "patient": os.getenv("PATIENT_SERVICE_URL", "http://patient-service:8002"),
    "doctor": os.getenv("DOCTOR_SERVICE_URL", "http://doctor-service:8003"),
    "billing": os.getenv("BILLING_SERVICE_URL", "http://billing-service:8004"),
    "ai": os.getenv("AI_SERVICE_URL", "http://ai-service:8005"),
}

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

    # Build headers — strip the original auth, add internal context
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Authorization", None)

    # Inject internal context headers (plain headers for MVP)
    headers["X-Tenant-ID"] = getattr(request.state, "tenant_id", "")
    headers["X-User-ID"] = getattr(request.state, "user_id", "")
    headers["X-User-Role"] = getattr(request.state, "user_role", "")
    headers["X-Internal-Auth"] = os.getenv("INTERNAL_AUTH_TOKEN", "dev-internal-token")

    # Forward idempotency key
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

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


@router.api_route("/api/v1/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_handler(request: Request, service: str, path: str) -> Response:
    """Catch-all proxy handler — routes to the appropriate backend service."""
    service_name = ROUTE_MAP.get(f"/api/v1/{service}")
    if not service_name:
        return Response(status_code=404, content='{"detail": "Route not found"}', media_type="application/json")

    return await proxy_request(request, service_name, f"/api/v1/{service}/{path}")
