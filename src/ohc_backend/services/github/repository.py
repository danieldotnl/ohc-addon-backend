"""GitHub repository management functionality."""

import logging
from pathlib import Path

import aiofiles

from ohc_backend.utils.logging import log_error

from .base import GitHubBaseAPI
from .errors import GitHubNotFoundError
from .models import CommitFilesRequest, GithubRepositoryRequestConfig, Repository

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

    async def create_repository(self, config: GithubRepositoryRequestConfig) -> Repository:
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

            logger.debug("Search result count: %s",
                         response.get("total_count"))

            # Filter for exact match on name
            if response.get("items"):
                for repo in response["items"]:
                    if repo.get("name") == name:
                        logger.debug("Found repository: %s",
                                     repo.get("full_name"))
                        return Repository(**repo)
        except Exception as e:
            log_error(logger, "Error finding repository", e)
            return None
        else:
            return None

    async def find_or_create_repository(self, config: GithubRepositoryRequestConfig) -> Repository:
        """Get or create repository."""
        repo = await self.find_repository(config.name)
        if not repo:
            repo = await self.create_repository(config)
        return repo


class RepositoryInitializer:
    """Handles repository initialization with required files."""

    def __init__(self, api: GitHubBaseAPI) -> None:
        """Initialize the repository initializer."""
        self.api = api

    async def initialize_with_readme(self, repo_full_name: str) -> None:
        """Replace the default README with our custom one."""
        from .content import GitHubContentManager

        # Create content manager for this repository
        content_manager = GitHubContentManager(self.api, repo_full_name)

        # Load README template
        template_dir = Path(__file__).parent / "templates"
        readme_path = template_dir / "README.md"

        if readme_path.exists():
            try:
                async with aiofiles.open(readme_path) as f:
                    readme_content = await f.read()

                # Simply update the README - repository already has a commit and main branch
                await content_manager.commit_files(
                    CommitFilesRequest(
                        files={"README.md": readme_content},
                        message="Add README",
                        branch="main",
                        update_only=True  # This will update the existing file
                    )
                )
                logger.info(
                    "Successfully updated repository with OHC README")
            except Exception as e:
                log_error(
                    logger, "Failed to update repository with README", e)
                raise
