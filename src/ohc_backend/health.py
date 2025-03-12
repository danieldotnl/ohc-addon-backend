"""ServiceHealth classes."""

import uuid
from collections.abc import Callable
from enum import IntEnum, auto

from ohc_backend.errors import AppError, ErrorCode


class HealthState(IntEnum):
    """Enumeration of possible service health states."""

    UNINITIALIZED = auto()
    AVAILABLE = auto()
    ERROR = auto()


class HealthStatus:
    """Class for managing health status of services."""

    def __init__(self) -> None:
        """Initialize an empty health status tracker."""
        self._services: dict[str, HealthState] = {}
        self._error_info: dict[str, tuple[ErrorCode, str]] = {}
        self._subscribers: dict[str, Callable[[HealthState, HealthState], None]] = {}
        self._current_state: HealthState = HealthState.UNINITIALIZED

    def get_state(self, service_name: str | None = None) -> HealthState:
        """Get state of a specific service or the overall state."""
        if service_name is not None:
            if service_name not in self._services:
                raise KeyError(f"Service '{service_name}' not found")
            return self._services[service_name]

        if not self._services:
            return HealthState.UNINITIALIZED

        # Overall state is the lowest state (ERROR < UNINITIALIZED < AVAILABLE)
        if any(state == HealthState.ERROR for state in self._services.values()):
            return HealthState.ERROR
        if any(state == HealthState.UNINITIALIZED for state in self._services.values()):
            return HealthState.UNINITIALIZED
        return HealthState.AVAILABLE

    def set_service_state(
        self,
        service_name: str,
        state: HealthState,
        error_code: ErrorCode | None = None,
        description: str | None = None,
    ) -> None:
        """Set or update the state of a service."""
        old_overall_state = self.get_state()

        # Update service state
        self._services[service_name] = state

        # Handle error information
        if state == HealthState.ERROR:
            if error_code is None or description is None:
                raise ValueError("Error code and description must be provided when setting ERROR state")
            self._error_info[service_name] = (error_code, description)
        elif service_name in self._error_info:
            # Clear error info if state is no longer ERROR
            del self._error_info[service_name]

        # Check if overall state changed and notify subscribers if needed
        new_overall_state = self.get_state()
        if new_overall_state != old_overall_state:
            self._notify_subscribers(old_overall_state, new_overall_state)
            self._current_state = new_overall_state

    def get_services(self) -> list[str]:
        """Get a list of all registered services."""
        return list(self._services.keys())

    def get_service_error(self, service_name: str) -> tuple[ErrorCode, str]:
        """Get error information for a service."""
        if service_name not in self._error_info:
            raise KeyError(f"No error information for service '{service_name}'")
        return self._error_info[service_name]

    def remove_service(self, service_name: str) -> None:
        """Remove a service from health tracking."""
        old_overall_state = self.get_state()

        if service_name in self._services:
            del self._services[service_name]

        if service_name in self._error_info:
            del self._error_info[service_name]

        # Check if overall state changed and notify subscribers if needed
        new_overall_state = self.get_state()
        if new_overall_state != old_overall_state:
            self._notify_subscribers(old_overall_state, new_overall_state)
            self._current_state = new_overall_state

    def raise_on_error(self) -> None:
        """Raise an AppError if any service is in ERROR state."""
        for service_name, state in self._services.items():
            if state == HealthState.ERROR:
                error_code, description = self._error_info[service_name]
                message = f"Service '{service_name}' in ERROR state: {error_code.value} - {description}"
                details = {
                    "service_name": service_name,
                    "description": description,
                }

                raise AppError(
                    message=message,
                    error_code=error_code,  # Use the actual ErrorCode from the service
                    details=details,
                )

    def subscribe_to_state_changes(self, callback: Callable[[HealthState, HealthState], None]) -> str:
        """Subscribe to overall state changes."""
        subscription_id = str(uuid.uuid4())
        self._subscribers[subscription_id] = callback
        return subscription_id

    def unsubscribe_from_state_changes(self, subscription_id: str) -> None:
        """Unsubscribe from overall state changes."""
        if subscription_id in self._subscribers:
            del self._subscribers[subscription_id]

    def _notify_subscribers(self, old_state: HealthState, new_state: HealthState) -> None:
        """Notify all subscribers about a state change."""
        for callback in self._subscribers.values():
            callback(old_state, new_state)
