"""Automations API."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ohc_backend.dependencies import deps
from ohc_backend.models.ha_entity import Automation
from ohc_backend.services.sync_manager import SyncManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
def get_automations(
    sync_manager: Annotated[SyncManager, Depends(deps.get_sync_manager)],
) -> list[Automation]:
    """Get all automations."""
    automations = sync_manager.get_ohc_state().get_automations()
    logger.info("Retrieved %s automations from storage", len(automations))
    return automations


@router.get("/{automation_id}")
def get_automation(
    automation_id: str,
    sync_manager: Annotated[SyncManager, Depends(deps.get_sync_manager)],
) -> Automation:
    """Get a single automation."""
    result = sync_manager.get_ohc_state().get_automation(automation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Automation not found")
    return result
