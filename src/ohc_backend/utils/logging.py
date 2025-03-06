import logging
import os
import sys


class CompactExceptionFormatter(logging.Formatter):
    """A formatter that makes exception traces more compact."""

    def formatException(self, exc_info) -> str:
        """Format exception with just the main info, not the full trace."""
        if os.getenv("ENVIRONMENT") == "dev" and os.getenv("DETAILED_LOGS", "").lower() == "true":
            # In development with detailed logs enabled, show full traceback
            return super().formatException(exc_info)
        # Otherwise show a compact version
        exc_type, exc_value, _ = exc_info
        return f"{exc_type.__name__}: {exc_value}"


class RequestIDLogFilter(logging.Filter):
    """Add request ID to log records."""

    def filter(self, record) -> bool:
        """Add request ID to log records."""
        from ohc_backend.utils.request_context import get_request_id
        record.request_id = get_request_id() or "-"
        return True


def configure_logging() -> None:
    """Configure application logging."""
    # Map string log levels to logging constants
    log_level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR
    }

    # Get log level from environment variable, default to INFO if not set or invalid
    log_level_str = os.getenv("LOG_LEVEL", "info").lower()
    log_level = log_level_map.get(log_level_str, logging.INFO)

    # Create formatter with request ID
    log_format = "%(asctime)s [%(levelname)8s] [%(request_id)s] %(name)s: %(message)s"
    formatter = CompactExceptionFormatter(log_format)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers and add our own
    root_logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Add the request ID filter to the handler
    request_id_filter = RequestIDLogFilter()
    console_handler.addFilter(request_id_filter)

    root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.client").setLevel(logging.WARNING)


def log_error(logger: logging.Logger, message: str, exc: Exception, *, critical: bool = False) -> None:
    """Log an exception with compact formatting."""
    log_method = logger.critical if critical else logger.error

    # Create a clean message with the exception details
    error_message = f"{message}: {type(exc).__name__}: {exc!s}"
    log_method(error_message)

    # If in dev mode with detailed logs, also log full traceback at debug level
    if os.getenv("ENVIRONMENT") == "dev" and os.getenv("DETAILED_LOGS", "").lower() == "true":
        logger.debug("Exception details:", exc_info=exc)
