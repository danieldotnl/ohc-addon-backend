"""GitHub authentication API client and manager."""
import asyncio
import logging
import time

import aiohttp

from .base import GitHubBaseAPI
from .errors import GitHubAuthError, GitHubError
from .models import DeviceFlowInfo, TokenResponse

logger = logging.getLogger(__name__)


class AuthenticationTimeoutError(GitHubAuthError):
    """Raised when authentication flow times out."""

    def __init__(self, timeout_minutes: int) -> None:
        """Initialize the error."""
        super().__init__(
            message=f"GitHub authentication timed out after {timeout_minutes} minutes",
            error_type="auth_timeout"
        )


class GitHubAuthAPI(GitHubBaseAPI):
    """API client for GitHub authentication endpoints."""

    def __init__(self) -> None:
        """Initialize the GitHub API client."""
        self.base_url = "https://github.com"
        self.session = None
        self.headers = {"Accept": "application/json"}

    async def ensure_session(self) -> None:
        """Create session if needed."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def close(self) -> None:
        """Close session if it exists."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def start_device_flow(self, client_id: str, scope: str) -> DeviceFlowInfo:
        """Start the device flow authentication process."""
        await self.ensure_session()
        response = await self.make_request(
            "POST",
            f"{self.base_url}/login/device/code",
            json={"client_id": client_id, "scope": scope}
        )

        if not response:
            msg = "Failed to start device flow authentication"
            raise GitHubAuthError(
                msg,
                error_type="device_flow_start_failed"
            )

        return DeviceFlowInfo.model_validate(response)

    async def poll_for_token(self, client_id: str, device_code: str) -> TokenResponse:
        """Poll GitHub for the access token using device code."""
        await self.ensure_session()
        response = await self.make_request(
            "POST",
            f"{self.base_url}/login/oauth/access_token",
            json={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }
        )

        if not response:
            msg = "Failed to poll for access token"
            raise GitHubAuthError(
                msg,
                error_type="token_poll_failed"
            )

        if "error" in response:
            if response["error"] == "authorization_pending":
                return TokenResponse(success=False)
            raise GitHubAuthError(
                message=f"Authentication error: {response['error']}",
                error_type=response["error"]
            )

        return TokenResponse(
            success=True,
            access_token=response["access_token"]
        )


class GitHubAuthManager:
    """Handles GitHub authentication flows."""

    def __init__(self, client_id: str) -> None:
        """Initialize the authentication manager."""
        self.client_id = client_id
        self._auth_api = None

    async def authenticate(self, scope: str) -> str:
        """Complete authentication flow and return access token."""
        auth_api = GitHubAuthAPI()

        try:
            flow_info = await auth_api.start_device_flow(self.client_id, scope)
            logger.info(
                "\n**********************************************************************************\n")
            logger.info("Device flow started. Please complete authentication:")
            logger.info("Verification URL: %s", flow_info.verification_uri)
            logger.info("User code: %s", flow_info.user_code)
            logger.info("Code expires in %d minutes",
                        flow_info.expires_in // 60)
            logger.info(
                "\n**********************************************************************************\n")
            start_time = time.time()
            timeout = flow_info.expires_in - 5  # 5 seconds buffer

            while time.time() - start_time < timeout:
                try:
                    token_response = await auth_api.poll_for_token(self.client_id, flow_info.device_code)
                    if token_response.success and token_response.access_token:
                        logger.info("Authentication successful")
                        return token_response.access_token
                except GitHubAuthError as e:
                    if e.error_type != "authorization_pending":
                        logger.exception("Authentication error!")
                        raise
                    # Ignore authorization_pending errors and continue polling

                await asyncio.sleep(flow_info.interval)

            logger.error("Authentication timed out after %d minutes",
                         timeout)
            raise AuthenticationTimeoutError(timeout)  # noqa: TRY301

        except Exception as e:
            if not isinstance(e, GitHubError):
                # Wrap non-GitHub errors
                logger.exception("Unexpected error during authentication")
                msg = f"Authentication failed: {e!s}"
                raise GitHubAuthError(msg) from e
            raise
        finally:
            await auth_api.close()
