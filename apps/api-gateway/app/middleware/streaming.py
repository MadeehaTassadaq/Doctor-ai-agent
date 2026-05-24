"""SSE streaming proxy for AI chat responses."""

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

stream_router = APIRouter()


@stream_router.get("/api/v1/ai/chat/stream")
async def proxy_ai_stream(request: Request) -> StreamingResponse:
    """Proxy SSE stream from AI Agent Service to the client."""
    ai_service_url = os.getenv("AI_SERVICE_URL", "http://ai-service:8005")
    target_url = f"{ai_service_url}/api/v1/ai/chat/stream?{request.query_params}"

    headers = {
        "X-Tenant-ID": getattr(request.state, "tenant_id", ""),
        "X-User-ID": getattr(request.state, "user_id", ""),
        "X-User-Role": getattr(request.state, "user_role", ""),
        "X-Internal-Auth": os.getenv("INTERNAL_AUTH_TOKEN", "dev-internal-token"),
    }

    async def _stream():
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", target_url, headers=headers) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
