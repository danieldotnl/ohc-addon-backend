"""GitHub client that orchestrates all operations."""

import logging
from pathlib import Path
from typing import cast

import aiofiles

from ohc_backend.base_types import OHCBaseConfig, OHCBaseService, OHCServiceName
from ohc_backend.errors import GitHubAuthenticationError
from ohc_backend.services.github.models import CommitFilesRequest
from ohc_backend.services.settings import GithubConfig, GitHubRepoConfig
from ohc_backend.utils.logging import log_error

from .content import GitHubContentManager
from .repository import GitHubRepositoryManager
from .rest import GitHubRestAPI

logger = logging.getLogger(__name__)


class GitHubClient(OHCBaseService):
    """High-level GitHub client that orchestrates all operations."""

    def __init__(self) -> None:
        """Initialize the GitHub client."""
        self.rest_api = GitHubRestAPI()
        self.repo_manager = GitHubRepositoryManager(self.rest_api)
        self._content_manager: GitHubContentManager | None = None

        self._repo_config: GitHubRepoConfig | None = None

    def get_service_name(self) -> OHCServiceName:
        """Return the service name for this instance."""
        return OHCServiceName.GITHUB

    def configure(self, config: OHCBaseConfig) -> None:
        """Configure github service with settings."""
        gh_config = cast(GithubConfig, config)
        if not (token := gh_config.access_token):
            raise ValueError("Valid access token required to configure Github service.")
        self.rest_api.set_auth_token(token)
        self.rest_api.base_url = gh_config.api_url

        self._repo_config = gh_config.repo_request

    def update_repo_config(self, repo_config: GitHubRepoConfig) -> None:
        """Update repository configuration."""
        self._repo_config = repo_config

    async def start(self) -> None:
        """Start the GitHub service."""
        if not self._repo_config:
            raise ValueError("Repository configuration not set.")
        await self.init_repository(self._repo_config)

    async def on_auth_issue(self) -> None:
        """Handle authentication error and reset token."""
        error = GitHubAuthenticationError()
        if self.report_critical_error_callback:
            self.report_critical_error_callback(OHCServiceName.GITHUB, error)

    async def init_repository(self, config: GitHubRepoConfig) -> None:
        """Initialize or connect to a repository."""
        repository = await self.repo_manager.find_repository(config.name)
        if not repository:
            logger.info("Repository not found, creating new repository")
            repository = await self.repo_manager.create_repository(config)
            self._content_manager = GitHubContentManager(self.rest_api, repository.full_name)
            await self._initialize_with_readme()
        else:
            self._content_manager = GitHubContentManager(self.rest_api, repository.full_name)

    async def _initialize_with_readme(self) -> None:
        """Replace the default README with our custom one."""
        if not self._content_manager:
            raise ValueError("ContentManager not initialized.")
        # Load README template
        template_dir = Path(__file__).parent / "templates"
        readme_path = template_dir / "README.md"

        if readme_path.exists():
            try:
                async with aiofiles.open(readme_path) as f:
                    readme_content = await f.read()

                # Simply update the README - repository already has a commit and main branch
                await self._content_manager.commit_files(
                    CommitFilesRequest(
                        files={"README.md": readme_content},
                        message="Add README",
                        branch="main",
                        update_only=True,  # This will update the existing file
                    )
                )
                logger.info("Successfully updated repository with OHC README")
            except Exception as e:
                log_error(logger, "Failed to update repository with README", e)
                raise

    @property
    def content(self) -> GitHubContentManager:
        """Access to content operations (requires initialized repository)."""
        if not self._content_manager:
            msg = "Repository not initialized. Call init_repository first."
            raise ValueError(msg)
        return self._content_manager

    async def _stop(self) -> None:
        """Close rest api session."""
        await self.rest_api.session.close()
