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
        """Handle different error responses based on status code."""
        # Handle specific error cases
        if response.status == status.HTTP_404_NOT_FOUND:
            # Extract resource info from URL
            path_parts = url.split("/")
            resource_type = path_parts[-2] if len(
                path_parts) >= 2 else "resource"
            resource_id = path_parts[-1] if path_parts else "unknown"
            raise GitHubNotFoundError(resource_type, resource_id)

        if response.status == status.HTTP_403_FORBIDDEN and "X-RateLimit-Remaining" in response.headers:
            # Rate limit error
            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
            raise GitHubRateLimitError(reset_time)

        if response.status == status.HTTP_401_UNAUTHORIZED:
            # Auth error
            raise GitHubAuthError(error_data.get(
                "message", "Authentication failed"))

        if response.status == status.HTTP_422_UNPROCESSABLE_ENTITY:
            # Validation error
            raise GitHubValidationError(
                error_data.get("message", "Validation failed"),
                status_code=422,
                response_data=error_data
            )

        # Generic API error for other cases
        raise GitHubAPIError(
            error_data.get("message", f"API error: {response.status}"),
            status_code=response.status,
            response_data=error_data
        )
