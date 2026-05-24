"""FastAPI application factory for the API Gateway."""

import os
import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.routes import router as v1_router
from app.api.v1.routes import webhook_router
from app.config import settings
from app.middleware.auth_middleware import auth_middleware
from app.middleware.error_handler import (
    gateway_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.middleware.rate_limiter import rate_limit_middleware
from app.middleware.router import router as proxy_router
from app.middleware.streaming import stream_router
from fastapi.exceptions import RequestValidationError


def setup_logging() -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.environment == "development"
            else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=settings.log_level, format="%(message)s")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title="Doctor AI Agent API Gateway",
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )

    # ─── Middleware Stack (order matters) ─────────────────────────────────────

    # 1. CORS (outermost — runs first on request, last on response)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
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
        max_age=600,
    )

    # 2. Rate Limiting
    app.middleware("http")(rate_limit_middleware)

    # 3. Auth (verifies JWT, sets request.state)
    app.middleware("http")(auth_middleware)

    # ─── Error Handlers ───────────────────────────────────────────────────────

    app.add_exception_handler(StarletteHTTPException, gateway_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ─── Routes ───────────────────────────────────────────────────────────────

    app.include_router(v1_router)
    app.include_router(webhook_router)
    app.include_router(proxy_router)
    app.include_router(stream_router)

    return app


app = create_app()
