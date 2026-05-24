"""Global error handlers conforming to RFC 9457 Problem Details."""

from http import HTTPStatus

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


async def gateway_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with RFC 9457 Problem Details format."""
    if isinstance(exc.detail, dict) and "type" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content={**exc.detail, "instance": str(request.url.path)},
            headers=exc.headers,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://api.doctorai.com/errors/http-{exc.status_code}",
            "title": HTTPStatus(exc.status_code).phrase,
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": str(request.url.path),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
