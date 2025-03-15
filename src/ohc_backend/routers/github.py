"""Github API router."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ohc_backend.dependencies import deps
from ohc_backend.errors import AppError, ErrorCode
from ohc_backend.services.github.auth import GitHubAuthAPI
from ohc_backend.services.github.models import DeviceFlowInfo
from ohc_backend.services.settings import GithubRepositoryRequestConfig, Settings

router = APIRouter()
logger = logging.getLogger(__name__)


class RepoNameRequest(BaseModel):
    """Repository name request."""

    name: str


@router.post("/setup")
async def setup_repository(
    settings: Annotated[Settings, Depends(deps.get_settings)],
    request: RepoNameRequest,
) -> dict:
    """Update repository configuration."""
    if not request.name:
        raise AppError("Repository name is required", error_code=ErrorCode.VALIDATION_ERROR)

    # Update repository config
    settings.gh_config.repo_request = GithubRepositoryRequestConfig(
        name=request.name,
        private=True,
        description=settings.gh_config.repo_request.description,
    )

    # Save settings
    await settings.save()

    return {"success": True}


@router.post("/device-code")
async def start_github_auth(
    settings: Annotated[Settings, Depends(deps.get_settings)],
) -> DeviceFlowInfo:
    """Start the GitHub device flow authentication process."""
    auth_api = GitHubAuthAPI()
    try:
        return await auth_api.start_device_flow(settings.gh_config.client_id, settings.gh_config.scope)
    finally:
        await auth_api.close()


@router.get("/poll-token/{device_code}")
async def poll_token_status(
    device_code: str,
    settings: Annotated[Settings, Depends(deps.get_settings)],
) -> dict:
    """Poll for GitHub token status."""
    auth_api = GitHubAuthAPI()
    try:
        token_response = await auth_api.poll_for_token(settings.gh_config.client_id, device_code)

        if token_response.success and token_response.access_token:
            # Update settings with token
            settings.gh_config.access_token = token_response.access_token
            await settings.save()

            # TODO: trigger orchestrator to start github client and sync manager  # noqa: FIX002, TD002, TD003

        # Return only the success status, not the token
        return {"success": token_response.success}
    finally:
        await auth_api.close()


@router.get("/config")
async def get_repo_config(
    settings: Annotated[Settings, Depends(deps.get_settings)],
) -> GithubRepositoryRequestConfig:
    """Get the current repository configuration."""
    return settings.gh_config.repo_request
