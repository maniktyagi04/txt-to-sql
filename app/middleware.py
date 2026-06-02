"""Security Hardening and Observability Middlewares."""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.cache import get_cache
from app.utils.config import get_settings
from app.utils.logging import get_logger, request_id_var

logger = get_logger(__name__)


class TraceAndLogMiddleware(BaseHTTPMiddleware):
    """Enforces request-id generation, context propagation, and request/response logging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()

        # Extract or generate Request/Correlation ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)

        logger.info(
            "http_request_incoming",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.query_params),
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(
                "http_request_unhandled_exception",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                },
            )
            # Re-raise so FastAPI's exception handlers can resolve it
            raise exc
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Inject request ID into response headers
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "http_request_outgoing",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

        # Reset context variable to avoid leaking across tasks
        request_id_var.reset(token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects essential security headers to prevent clicks/attacks."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Prevent framing Clickjacking attacks
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Force SSL/TLS in browsers
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Simple CSP header allowing local API docs
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdnjs.cloudflare.com cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com cdn.jsdelivr.net; "
            "img-src 'self' data: fastly.jsdelivr.net; "
            "connect-src 'self';"
        )

        # Cross-Origin Opener Policy
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces API rate limits using the configured Cache layer (Redis/InMemory)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()

        # Skip rate limits on healthcheck to prevent load balancer blocks
        if request.url.path in {"/health", "/healthz"}:
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        cache = get_cache(settings)

        # Rate limit identifier
        minute_key = f"rate_limit:{client_ip}:{int(time.time() // 60)}"
        limit = settings.rate_limit_requests_per_minute

        try:
            current_requests = cache.get(minute_key)
            if current_requests is None:
                current_requests = 0

            if current_requests >= limit:
                logger.warning(
                    "rate_limit_exceeded",
                    extra={
                        "client_ip": client_ip,
                        "limit": limit,
                        "key": minute_key,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "status": "failed",
                        "errors": [
                            {
                                "code": "RATE_LIMIT_EXCEEDED",
                                "message": f"Rate limit exceeded. Maximum allowed is {limit} requests per minute.",
                                "field": None,
                                "details": None,
                            }
                        ],
                        "warnings": [],
                    },
                )

            # Increment request counter (expiry set to 65 seconds to clear naturally)
            cache.set(minute_key, current_requests + 1, ttl_seconds=65)

        except Exception as exc:
            # Fallback gracefully to allow requests in case caching engine goes down entirely
            logger.error("rate_limiter_service_error_allowing_request", extra={"error": str(exc)})

        return await call_next(request)
