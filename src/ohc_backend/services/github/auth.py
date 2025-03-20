"""GitHub authentication API client and manager."""

import logging

import aiohttp

from .base import GitHubBaseAPI
from .errors import GitHubAuthError
from .models import DeviceFlowInfo, TokenResponse

logger = logging.getLogger(__name__)


class AuthenticationTimeoutError(GitHubAuthError):
    """Raised when authentication flow times out."""

    def __init__(self, timeout_minutes: int) -> None:
        """Initialize the error."""
        super().__init__(
            message=f"GitHub authentication timed out after {timeout_minutes} minutes", error_type="auth_timeout"
        )


class GitHubAuthClient(GitHubBaseAPI):
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
            "POST", f"{self.base_url}/login/device/code", json={"client_id": client_id, "scope": scope}
        )

        if not response:
            msg = "Failed to start device flow authentication"
            raise GitHubAuthError(msg, error_type="device_flow_start_failed")

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
            },
        )

        if not response:
            msg = "Failed to poll for access token"
            raise GitHubAuthError(msg, error_type="token_poll_failed")

        if "error" in response:
            if response["error"] == "authorization_pending":
                return TokenResponse(success=False)
            raise GitHubAuthError(message=f"Authentication error: {response['error']}", error_type=response["error"])

        return TokenResponse(success=True, access_token=response["access_token"])
