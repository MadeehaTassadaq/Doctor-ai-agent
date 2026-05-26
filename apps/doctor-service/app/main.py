"""FastAPI application factory for the Doctor Service."""

import os
import logging

import structlog
from fastapi import FastAPI

from app.api.v1.routes import router as v1_router
from app.config import settings
from app.middleware.auth import verify_internal_auth


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
        title="Doctor AI Agent Doctor Service",
        version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
    )

    # Internal auth middleware (verifies gateway-originated requests)
    app.middleware("http")(verify_internal_auth)

    # Routes
    app.include_router(v1_router)

    return app


app = create_app()
