from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models.common import APIError, ErrorResponse
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


def _error_response(
    *,
    request: Request,
    http_status: int,
    code: str,
    message: str,
    field: str | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    response = ErrorResponse(
        request_id=_request_id(request),
        errors=[
            APIError(
                code=code,
                message=message,
                field=field,
                details=details,
            )
        ],
    )
    return JSONResponse(status_code=http_status, content=response.model_dump(mode="json"))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(
        "http_exception",
        extra={
            "request_id": _request_id(request),
            "path": request.url.path,
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
    )
    return _error_response(
        request=request,
        http_status=exc.status_code,
        code="HTTP_EXCEPTION",
        message=str(exc.detail),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    logger.warning(
        "request_validation_error",
        extra={
            "request_id": _request_id(request),
            "path": request.url.path,
            "errors": exc.errors(),
        },
    )
    return _error_response(
        request=request,
        http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="REQUEST_VALIDATION_ERROR",
        message="Request validation failed.",
        details={"errors": exc.errors()},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"request_id": _request_id(request), "path": request.url.path},
    )
    return _error_response(
        request=request,
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
