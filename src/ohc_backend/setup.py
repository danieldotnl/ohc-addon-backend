"""Setup module for the application."""

import logging

from ohc_backend.dependencies import deps
from ohc_backend.services.github import GitHubClient

logger = logging.getLogger(__name__)


async def setup_github(client: GitHubClient) -> None:
    """Start the github auth flow and create repo if required."""
    settings = deps.get_settings()
    if not settings.gh_token:
        scope = settings.gh_config.scope
        token = await client.authenticate(scope)
        settings.gh_config.access_token = token
        await settings.save()
        client.rest_api.set_auth_token(token)

    await client.init_repository(settings.gh_config.repo_request)
