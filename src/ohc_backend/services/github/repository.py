"""GitHub repository management functionality."""

import logging

from ohc_backend.services.settings import GitHubRepoConfig
from ohc_backend.utils.logging import log_error

from .base import GitHubBaseAPI
from .errors import GitHubNotFoundError
from .models import Repository

logger = logging.getLogger(__name__)


class GitHubRepositoryManager:
    """Handles repository creation and management."""

    def __init__(self, api: GitHubBaseAPI) -> None:
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
        except GitHubNotFoundError:
            return None

    async def create_repository(self, config: GitHubRepoConfig) -> Repository:
        """Create a new repository."""
        data = {
            "name": config.name,
            "private": config.private,
            "auto_init": True,  # GitHub will initialize with a default README
            "description": config.description,
        }

        response = await self.api.make_request(
            "POST",
            f"{self.api.base_url}/user/repos",
            json=data,
        )
        repo = Repository(**response)
        logger.debug("Created repository: %s", repo.full_name)
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

            logger.debug("Search result count: %s", response.get("total_count"))

            # Filter for exact match on name
            if response.get("items"):
                for repo in response["items"]:
                    if repo.get("name") == name:
                        logger.debug("Found repository: %s", repo.get("full_name"))
                        return Repository(**repo)
        except Exception as e:  # noqa: BLE001
            log_error(logger, "Error finding repository", e)
            return None
        else:
            return None

    async def find_or_create_repository(self, config: GitHubRepoConfig) -> Repository:
        """Get or create repository."""
        repo = await self.find_repository(config.name)
        if not repo:
            repo = await self.create_repository(config)
        return repo
