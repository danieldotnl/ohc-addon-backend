"""Github API router."""


# router = APIRouter()
# logger = logging.getLogger(__name__)

# setup_status = {}


# @router.post("/device-code")
# async def start_github_auth(
#     settings: Annotated[Settings, Depends(deps.get_settings)],
#     github_auth_service: Annotated[GithubAuthService, Depends(deps.get_github_auth_service)],
# ) -> DeviceFlowInfo:
#     """Start the GitHub device flow authentication process."""
#     return await github_auth_service.start_device_flow(settings.gh_auth_config.scope)


# @router.get("/poll-token/{device_code}")
# async def check_auth_status(
#     device_code: str,
#     settings: Annotated[Settings, Depends(deps.get_settings)],
#     github_auth_service: Annotated[GithubAuthService, Depends(deps.get_github_auth_service)],
# ) -> dict:
#     """Check the status of GitHub authentication."""
#     token_response = await github_auth_service.poll_for_token(device_code)
#     # TODO @<danieldotnl>: remove this logging  # noqa: FIX002, TD003
#     logger.debug("Token response: %s", token_response)

#     if token_response.success:
#         settings.gh_config.access_token = token_response.access_token
#         await settings.save()

#         sync_manager = deps.get_sync_manager()
#         await sync_manager.start()
#     return {"success": token_response.success}
