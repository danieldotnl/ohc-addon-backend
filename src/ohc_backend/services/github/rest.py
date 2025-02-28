"""GitHub REST API client and repository manager."""


import aiohttp

from .base import GitHubBaseAPI


class GitHubRestAPI(GitHubBaseAPI):
    """API client for GitHub REST API endpoints."""

    def __init__(self, api_url: str) -> None:
        """Initialize the GitHub API client."""
        self.session = aiohttp.ClientSession(
            headers={
                "Accept": "application/vnd.github.v3+json",
            },
        )
        self.base_url = api_url

    def set_auth_token(self, token: str) -> None:
        """Set the authentication token."""
        self.session.headers["Authorization"] = f"Bearer {token}"
