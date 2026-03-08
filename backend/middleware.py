import time
import uuid
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from backend.config import API_RATE_LIMIT, API_RATE_WINDOW, IS_PRODUCTION

logger = logging.getLogger("atomicpay.middleware")

_request_counts = defaultdict(list)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request.state.request_id = request_id
        start = time.monotonic()

        response = await call_next(request)

        elapsed = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed:.1f}ms"

        if request.url.path.startswith("/api/"):
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} "
                f"{response.status_code} {elapsed:.1f}ms"
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        _request_counts[client_ip] = [
            t for t in _request_counts[client_ip] if now - t < API_RATE_WINDOW
        ]

        if len(_request_counts[client_ip]) >= API_RATE_LIMIT:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={
                    "Retry-After": str(API_RATE_WINDOW),
                    "X-RateLimit-Limit": str(API_RATE_LIMIT),
                    "X-RateLimit-Remaining": "0",
                },
            )

        _request_counts[client_ip].append(now)

        response = await call_next(request)
        remaining = API_RATE_LIMIT - len(_request_counts[client_ip])
        response.headers["X-RateLimit-Limit"] = str(API_RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))

        return response
