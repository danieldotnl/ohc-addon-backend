"""Application error classes."""
from enum import Enum
from typing import Any

from fastapi import status


class ErrorCode(Enum):
    """Application error codes."""

    AUTHENTICATION_FAILED = "auth_failed"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    GITHUB_API_ERROR = "github_api_error"
    HOME_ASSISTANT_ERROR = "ha_error"
    SYNC_ERROR = "sync_error"
    INTERNAL_ERROR = "internal_error"


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict[str, Any] | None = None
    ) -> None:
        """Initialize the error."""
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API responses."""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "details": self.details
        }


class AuthenticationError(AppError):
    """Authentication errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the error."""
        super().__init__(
            message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code=ErrorCode.AUTHENTICATION_FAILED,
            details=details
        )
