"""GitHub REST API client and repository manager."""

import logging

import aiohttp
from fastapi import status

from .base import GitHubBaseAPI
from .errors import GitHubError
from .models import GithubRepositoryRequestConfig, Repository

logger = logging.getLogger(__name__)


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


class GitHubRepositoryManager:
    """Handles repository creation and management."""

    def __init__(self, api: GitHubRestAPI) -> None:
        """Initialize the repository manager."""
        self.api = api

    async def get_repository(self, full_name: str) -> Repository | None:
        """Fetch repository if it exists."""
        try:
            response = await self.api.make_request(
                "GET",
                f"{self.api.base_url}/repos/{full_name}",
            )
            return Repository(**response)
        except GitHubError as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                return None
            raise

    async def create_repository(self, config: GithubRepositoryRequestConfig) -> Repository:
        """Create a new repository."""
        data = {
            "name": config.name,
            "private": config.private,
            "auto_init": True,
            "description": config.description,
        }

        response = await self.api.make_request(
            "POST",
            f"{self.api.base_url}/user/repos",
            json=data,
        )
        logger.debug("Created repository: %s", response)
        return Repository(**response)

    async def find_or_create_repository(self, config: GithubRepositoryRequestConfig) -> Repository:
        """Get or create repository."""
        repo = await self.find_repository(config.name)
        if not repo:
            repo = await self.create_repository(config)
        return repo

    async def find_repository(self, name: str) -> Repository | None:
        """Find a repository by name for the authenticated user, using GitHub's search API."""
        try:
            # Use the search API to narrow down candidates
            response = await self.api.make_request(
                "GET",
                f"{self.api.base_url}/search/repositories",
                params={
                    # @me refers to authenticated user
                    "q": f"{name} in:name user:@me",
                    "per_page": 100,  # Get enough results to likely include exact match
                },
            )

            logger.debug("Search result count: %s",
                         response.get("total_count"))

            # Filter for exact match on name
            if response.get("items"):
                for repo in response["items"]:
                    if repo.get("name") == name:
                        logger.debug("Found repository: %s",
                                     repo.get("full_name"))
                        return Repository(**repo)

            return None
        except GitHubError:
            logger.exception("Error finding repository!")
            return None
        else:
            return None
