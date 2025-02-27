"""GitHub-related errors."""


class GitHubError(Exception):
    """Base exception for all GitHub-related errors."""

    def __init__(self, message: str, status_code: int | None = None, error_type: str | None = None) -> None:
        """Initialize the GitHub error."""
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


class GitHubAuthError(GitHubError):
    """Authentication-related errors."""


class GitHubAPIError(GitHubError):
    """API request errors."""

    def __init__(self, message: str, status_code: int, response_data: dict | None = None, error_type: str = "api_error") -> None:
        """Initialize the API error."""
        super().__init__(message, status_code=status_code, error_type=error_type)
        self.response_data = response_data or {}


class GitHubRateLimitError(GitHubAPIError):
    """Rate limit exceeded errors."""

    def __init__(self, reset_time: int | None = None) -> None:
        """Initialize the rate limit error."""
        super().__init__(
            "GitHub API rate limit exceeded",
            status_code=403,
            error_type="rate_limit"
        )
        self.reset_time = reset_time


class GitHubNotFoundError(GitHubAPIError):
    """Resource not found errors."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        """Initialize the not found error."""
        super().__init__(
            f"{resource_type} not found: {resource_id}",
            status_code=404,
            error_type="not_found"
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class GitHubValidationError(GitHubAPIError):
    """Validation errors."""


class GitHubRepositoryError(GitHubError):
    """Repository-specific errors."""


class GitHubContentError(GitHubError):
    """Content operations errors."""
