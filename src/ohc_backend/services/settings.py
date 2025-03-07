"""Settings manager for the application."""

import json
import logging
import os
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

import aiofiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GithubRepositoryRequestConfig(BaseModel):
    """GitHub repository request configuration."""

    name: str = Field(
        description="Repository name without owner",
        default="ohc-ha-versioning",
    )
    private: bool = Field(
        description="Whether the repository is private",
        default=True,
    )
    description: str | None = Field(
        description="Repository description",
        default="Repo for version control by the OurHomeConnected add-on, on home assistant automation and scripts.",
    )


class GithubConfig(BaseModel):
    """GitHub configuration."""

    repo_request: GithubRepositoryRequestConfig = Field(
        default=GithubRepositoryRequestConfig(),
        description="GitHub repository request configuration",
    )
    access_token: str | None = Field(
        default=None,
    )
    gh_user: str | None = Field(
        default=None,
        description="GitHub username",
    )
    api_url: str = Field(
        default="https://api.github.com",
        description="GitHub API URL",
    )
    client_id: str = Field(
        default="Ov23licd0c0KujXwABCn",
        description="GitHub OAuth client ID",
        json_schema_extra={"env": "GH_CLIENT_ID"}
    )
    scope: str = Field(
        default="repo user:email",
        description="OAuth scopes for GitHub authentication",
    )


class SyncManagerConfig(BaseModel):
    """Sync configuration."""

    interval: int = Field(
        default=300,
        description="Interval in seconds for syncing with Home Assistant",
        json_schema_extra={"env": "HA_SYNC_INTERVAL"},
    )
    state_file: str = Field(
        default=".ohcstate/ohc_state.json",
        description="Path to state file",
    )
    ha_max_parallel_requests: int = Field(
        default=10,
        description="Maximum number of parallel requests to Home Assistant",
        json_schema_extra={"env": "HA_MAX_PARALLEL_REQUESTS"},
    )


class HAConfig(BaseModel):
    """Home Assistant configuration."""

    server: str = Field(
        default="http://supervisor.core",
        description="Home Assistant server URL",
        json_schema_extra={"env": "HA_SERVER"},
    )
    token: str | None = Field(
        default=None,
        description="Home Assistant authentication token",
        json_schema_extra={"env": "SUPERVISOR_TOKEN"},
    )
    data_folder: str = Field(
        default="/data",
        description="Path to data folder",
        json_schema_extra={"env": "HA_DATA_FOLDER"},
    )


class AppSettings(BaseModel):
    """Application settings."""

    ha: HAConfig | None = Field(
        default=HAConfig(),
        description="Home Assistant configuration",
    )
    gh: GithubConfig | None = Field(
        default=GithubConfig(),
        description="GitHub configuration",
    )
    sync: SyncManagerConfig = Field(
        default=SyncManagerConfig(),
        description="Sync configuration",
    )


class Settings:
    """Settings manager for the application."""

    def __init__(self, file_path: str) -> None:
        """Initialize the settings manager."""
        self._file_path = Path(file_path)
        self._settings = AppSettings()

    async def async_init(self) -> None:
        """Initialize settings."""
        await self._load()

    async def _load(self) -> None:
        """Load settings from file and environment variables."""
        # Load from file first
        if self._file_path.exists():
            try:
                async with aiofiles.open(self._file_path) as f:
                    content = await f.read()
                    file_settings = json.loads(content)
                    self._settings = AppSettings(**file_settings)
            except (json.JSONDecodeError, ValueError):
                logger.exception("Error loading settings file.")

        # Load from environment variables
        self._load_env_vars(self._settings)

    def _load_env_vars(self, model: BaseModel) -> None:
        """Recursively load environment variables for a model and its nested models."""
        for field_name, field in model.model_fields.items():
            # Get current value
            value = getattr(model, field_name)

            # Check if field has env variable defined
            extra = getattr(field, "json_schema_extra", {}) or {}
            if (env_var := extra.get("env")) and (env_value := os.environ.get(env_var)):
                try:
                    parsed_value = self._parse_value(
                        env_value, field.annotation)
                    setattr(model, field_name, parsed_value)
                except ValueError:
                    logger.exception(
                        "Error parsing environment variable %s", env_var)

            # Handle nested models
            if isinstance(value, BaseModel):
                self._load_env_vars(value)
            elif value is None and issubclass(get_origin(field.annotation) or field.annotation, BaseModel):
                model_class = get_args(field.annotation)[0] if get_origin(
                    field.annotation) else field.annotation
                new_model = model_class()
                self._load_env_vars(new_model)
                setattr(model, field_name, new_model)

    def _parse_value(self, value: str, type_: type) -> Any:  # noqa: ANN401
        """Parse string value to target type."""
        # Handle Union types (e.g., str | None)
        if isinstance(type_, UnionType) or get_origin(type_) is Union:
            types = get_args(type_)
            # Use first non-None type
            actual_type = next(t for t in types if t is not type(None))
            return self._parse_value(value, actual_type)

        if type_ is bool:
            return value.lower() in ("true", "1", "yes")
        if isinstance(type_, type) and issubclass(type_, BaseModel):
            return type_(**json.loads(value))
        if isinstance(type_, type) and issubclass(type_, Enum):
            return type_(value)
        return type_(value)

    async def save(self) -> None:
        """Save current settings to disk."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self._file_path, "w") as f:
            await f.write(self._settings.model_dump_json(indent=2))

    async def update(self, **kwargs: dict[str, Any]) -> None:
        """Update settings with new values."""
        new_settings = self._settings.model_copy(update=kwargs)
        # Validate before saving
        self._settings = new_settings
        await self.save()

    def get_env_mappings(self) -> dict[str, str]:
        """Get the mapping of setting names to environment variables."""
        return self._env_mappings.copy()

    def describe(self) -> dict[str, dict[str, Any]]:
        """Get descriptions and metadata for all settings."""
        descriptions = {}
        for field_name, field in AppSettings.model_fields.items():
            descriptions[field_name] = {
                "description": field.description,
                "type": str(field.annotation.__name__),
                "default": field.default,
                "env_var": self._env_mappings.get(field_name, ""),
                "current_value": getattr(self._settings, field_name),
            }
        return descriptions

    # Type hints for common attributes
    @property
    def gh_config(self) -> GithubConfig:
        """Get the GitHub configuration."""
        return self._settings.gh

    @property
    def gh_token(self) -> str:
        """Get the GitHub access token."""
        return self._settings.gh.access_token

    @property
    def ha_config(self) -> HAConfig:
        """Get the Home Assistant configuration."""
        return self._settings.ha

    @property
    def sync_config(self) -> SyncManagerConfig:
        """Get the sync configuration."""
        return self._settings.sync
