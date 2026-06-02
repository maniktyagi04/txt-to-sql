from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.init_db import init_databases
from app.middleware import (
    TraceAndLogMiddleware,
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
)
from app.routes import api_router
from app.utils.config import Settings, get_settings
from app.utils.errors import register_exception_handlers
from app.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings)

    # Initialize SQLite databases with mock seed data
    try:
        init_databases()
        logger.info("sqlite_databases_setup_success")
    except Exception as exc:
        logger.critical("sqlite_databases_setup_failed", extra={"error": str(exc)})
        raise exc

    logger.info(
        "application_starting",
        extra={
            "app_name": settings.app_name,
            "environment": settings.environment,
            "version": settings.app_version,
        },
    )
    yield
    logger.info("application_stopping", extra={"app_name": settings.app_name})


def create_app() -> FastAPI:
    settings: Settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Enterprise-grade Text-to-SQL API backend.",
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
    )

    # 1. CORS Configuration Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_hosts,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Hardening Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. Rate Limiting Middleware
    app.add_middleware(RateLimitMiddleware)

    # 4. Correlation / Logging Tracing Middleware (Executed first on incoming requests)
    app.add_middleware(TraceAndLogMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app: FastAPI = create_app()
