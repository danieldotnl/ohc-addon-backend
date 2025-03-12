"""Scripts API."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ohc_backend.dependencies import deps
from ohc_backend.models.ha_entity import Script
from ohc_backend.services.sync_manager import SyncManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
def get_scripts(
    sync_manager: Annotated[SyncManager, Depends(deps.get_sync_manager)],
) -> list[Script]:
    """Get all scripts."""
    scripts = sync_manager.get_ohc_state().get_scripts()
    logger.info("Retrieved %s scripts from storage", len(scripts))
    return scripts


@router.get("/{script_id}")
def get_script(
    script_id: str,
    sync_manager: Annotated[SyncManager, Depends(deps.get_sync_manager)],
) -> Script:
    """Get a single script."""
    result = sync_manager.get_ohc_state().get_script(script_id)
    if not result:
        raise HTTPException(status_code=404, detail="Script not found")
    return result
