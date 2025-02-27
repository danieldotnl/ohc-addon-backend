"""HAEntityStorage class, responsible for storing and managing HAEntity objects."""

from __future__ import annotations

import json

from ohc_backend.models.ha_entity import Automation, HAEntity, Script


class OHCState:
    """Storage for HAEntity objects."""

    def __init__(self) -> None:
        """Initialize the storage."""
        self._storage: dict[str, HAEntity] = {}

    def add(self, entity: HAEntity) -> HAEntity:
        """Store a new entity."""
        self._storage[entity.entity_id] = entity
        return entity

    def get_entity(self, entity_id: str) -> HAEntity | None:
        """Get an entity by ID."""
        return self._storage.get(entity_id)

    def get_automation(self, entity_id: str) -> Automation | None:
        """Get an automation by ID."""
        entity = self._storage.get(entity_id)
        if isinstance(entity, Automation):
            return entity
        return None

    def get_script(self, entity_id: str) -> Script | None:
        """Get a script by ID."""
        entity = self._storage.get(entity_id)
        if isinstance(entity, Script):
            return entity
        return None

    def get_automations(self) -> list[Automation]:
        """Get all automations."""
        return [entity for entity in self._storage.values() if isinstance(entity, Automation)]

    def get_scripts(self) -> list[Script]:
        """Get all scripts."""
        return [entity for entity in self._storage.values() if isinstance(entity, Script)]

    def get_entities(self) -> list[HAEntity]:
        """Get all entities."""
        return list(self._storage.values())

    def update(self, entity: HAEntity) -> HAEntity | None:
        """Update an entity."""
        if entity.entity_id in self._storage:
            self._storage[entity.entity_id] = entity
            return entity
        return None

    def remove(self, entity_id: str) -> bool:
        """Delete an entity."""
        if entity_id in self._storage:
            del self._storage[entity_id]
            return True
        return False

    def upsert(self, entity: HAEntity) -> HAEntity:
        """Insert or update an entity."""
        self._storage[entity.entity_id] = entity
        return entity

    def to_json(self) -> str:
        """Serialize the storage to JSON string with pretty printing."""
        return json.dumps(
            self._storage,
            default=lambda x: json.loads(x.model_dump_json()),
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, json_str: str) -> OHCState:
        """Create a new storage instance from JSON string."""
        storage = cls()
        data = json.loads(json_str)

        type_mapping = {
            "automation": Automation,
            "script": Script,
        }

        for entity_id, entity_data in data.items():
            # Get the entity type from the entity_id prefix
            entity_type = entity_id.split(".")[0]
            entity_class = type_mapping.get(entity_type)

            if entity_class is None:
                msg = f"Unknown entity type: {entity_type}"
                raise ValueError(msg)

            storage._storage[entity_id] = entity_class.model_validate(  # noqa: SLF001
                entity_data)

        return storage
