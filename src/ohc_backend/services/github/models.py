"""Pydantic models for GitHub service."""

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Token response from GitHub."""

    success: bool
    access_token: str | None = None


class DeviceFlowInfo(BaseModel):
    """Device flow authentication information."""

    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class Repository(BaseModel):
    """GitHub repository information."""

    full_name: str
    html_url: str
    description: str | None = None
    private: bool = False


class GitBlob(BaseModel):
    """Git blob object."""

    sha: str
    url: str


class GitTreeItem(BaseModel):
    """Git tree item."""

    path: str
    mode: str = "100644"
    type: str = "blob"
    sha: str


class GitTree(BaseModel):
    """Git tree object."""

    sha: str
    url: str
    tree: list[GitTreeItem]


class GitCommit(BaseModel):
    """Git commit object."""

    sha: str
    url: str
    message: str


class CommitFilesRequest(BaseModel):
    """Request to commit multiple files."""

    files: dict[str, str]
    message: str
    branch: str = "main"
    update_only: bool = True


class GithubRepositoryRequestConfig(BaseModel):
    """Configuration for repository creation."""

    name: str
    full_name: str
    private: bool = True
    description: str | None = None


class GitReference(BaseModel):
    """Git reference representing a branch or tag pointer."""

    ref: str
    node_id: str
    url: str
    object: dict
