from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import api_router
from app.utils.config import Settings, get_settings
from app.utils.errors import register_exception_handlers
from app.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings)
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

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app: FastAPI = create_app()
