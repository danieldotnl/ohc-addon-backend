"""Base class for GitHub API communications."""

import logging
from typing import Any

import aiohttp
from fastapi import status

from .errors import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubValidationError,
)

logger = logging.getLogger(__name__)


class GitHubBaseAPI:
    """Base class for HTTP communications."""

    async def make_request(self, method: str, url: str, **kwargs: dict) -> Any:  # noqa: ANN401
        """Make HTTP request with comprehensive error handling."""
        logger.debug("Making %s request to: %s", method, url)
        try:
            async with self.session.request(method, url, **kwargs) as response:
                # Handle successful responses
                if response.status in (status.HTTP_200_OK, status.HTTP_201_CREATED):
                    return await response.json()

                # Try to parse error response
                error_data = await self._parse_error_response(response)

                # Handle error response outside the try block
                return await self._handle_error_response(response, error_data, url)

        except aiohttp.ClientError as e:
            logger.exception("Network request failed")
            raise GitHubError from e
        except GitHubError:
            # Re-raise GitHub-specific errors
            raise
        except Exception as e:
            # Catch all other exceptions
            logger.exception("Unexpected error in GitHub API request")
            raise GitHubError from e

    async def _parse_error_response(self, response: aiohttp.ClientResponse) -> dict:
        """Parse error response, handling JSON parsing errors."""
        error_data = {}
        try:
            error_data = await response.json()
        except:  # noqa: E722
            error_data = {"message": await response.text() or "Unknown error"}
        return error_data

    async def _handle_error_response(self, response: aiohttp.ClientResponse, error_data: dict, url: str) -> None:
        """Handle different error responses based on status code with improved context."""
        import sys
        from datetime import datetime

        # Capture request context
        method = response.method
        status_code = response.status
        path_parts = url.split("/")
        resource_type = path_parts[-2] if len(path_parts) >= 2 else "resource"
        resource_id = path_parts[-1] if path_parts else "unknown"

        try:
            if status_code == status.HTTP_404_NOT_FOUND:
                raise GitHubNotFoundError(resource_type, resource_id)

            if status_code == status.HTTP_403_FORBIDDEN and "X-RateLimit-Remaining" in response.headers:
                reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                reset_time_str = datetime.fromtimestamp(
                    reset_time).strftime("%Y-%m-%d %H:%M:%S UTC")
                logger.warning(
                    "GitHub rate limit exceeded. Resets at %s (%d)",
                    reset_time_str, reset_time
                )
                raise GitHubRateLimitError(reset_time)

            if status_code == status.HTTP_401_UNAUTHORIZED:
                # Auth error handling with token cleanup
                from ohc_backend.dependencies import deps
                try:
                    logger.warning(
                        "GitHub authentication failed. Clearing invalid token.")
                    await deps.clear_github_token()
                except Exception as e:
                    logger.exception(
                        "Failed to clear GitHub token: %s", str(e))

                error_msg = error_data.get("message", "Authentication failed")
                raise GitHubAuthError(error_msg)

            if status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
                errors = error_data.get("errors", [])
                error_details = "; ".join(
                    f"{e.get('field')}: {e.get('message')}" for e in errors) if errors else "Validation failed"
                raise GitHubValidationError(
                    error_data.get("message", "Validation failed") +
                    f" - {error_details}",
                    status_code=422,
                    response_data=error_data
                )

            # Better generic error message
            context = f"{method} {url}"
            error_message = error_data.get(
                "message", f"GitHub API error ({context}): Status {status_code}")

            # Add documentation URL if provided by GitHub
            if "documentation_url" in error_data:
                error_message += f" - See: {error_data['documentation_url']}"

            raise GitHubAPIError(
                error_message,
                status_code=status_code,
                response_data=error_data
            )
        except GitHubError:
            # Add request context to all GitHub errors
            e = sys.exc_info()[1]
            if hasattr(e, "__dict__"):  # Add context attributes to the exception
                e.__dict__["request_url"] = url
                e.__dict__["request_method"] = method
                e.__dict__["status_code"] = status_code
            raise
