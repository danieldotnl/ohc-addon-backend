"""GitHub client that orchestrates all operations."""

from .auth import GitHubAuthManager
from .content import GitHubContentManager
from .models import GithubRepositoryRequestConfig
from .rest import GitHubRepositoryManager, GitHubRestAPI


class GitHubClient:
    """High-level GitHub client that orchestrates all operations."""

    def __init__(self, api_url: str, client_id: str, access_token: str | None) -> None:
        """Initialize the GitHub client."""
        self.rest_api = GitHubRestAPI(api_url)
        self.auth_manager = GitHubAuthManager(client_id)
        self.repo_manager = GitHubRepositoryManager(self.rest_api)
        self._content_manager: GitHubContentManager | None = None

        if access_token:
            self.rest_api.set_auth_token(access_token)

    async def authenticate(self, scope: str) -> str:
        """Authenticate and configure the API client."""
        token = await self.auth_manager.authenticate(scope)
        self.rest_api.set_auth_token(token)
        return token

    async def init_repository(self, config: GithubRepositoryRequestConfig) -> None:
        """Initialize or connect to a repository."""
        repository = await self.repo_manager.find_or_create_repository(config)
        self._content_manager = GitHubContentManager(self.rest_api, repository.full_name)

    @property
    def content(self) -> GitHubContentManager:
        """Access to content operations (requires initialized repository)."""
        if not self._content_manager:
            msg = "Repository not initialized. Call init_repository first."
            raise ValueError(msg)
        return self._content_manager

    async def close(self) -> None:
        """Close rest api session."""
        await self.rest_api.session.close()
