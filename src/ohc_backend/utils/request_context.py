"""Request context utilities."""
import contextvars
import uuid
from collections.abc import Callable

from fastapi import Request, Response

# Context variable to store request ID
request_id_var = contextvars.ContextVar("request_id", default=None)


def get_request_id() -> str:
    """Get the current request ID."""
    return request_id_var.get()


async def request_id_middleware(request: Request, call_next: Callable[[Request], Response]) -> Response:
    """Middleware to assign a unique ID to each request."""
    request_id = str(uuid.uuid4())[:8]  # Use first 8 chars for brevity
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)
