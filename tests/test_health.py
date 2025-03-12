"""ServiceHealth related tests."""

import pytest

from ohc_backend.errors import AppError, ErrorCode
from ohc_backend.health import HealthState, HealthStatus


def test_health_status_initialization() -> None:
    """Test the initial state of HealthStatus."""
    hs = HealthStatus()
    assert hs.get_state() == HealthState.UNINITIALIZED
    assert len(hs.get_services()) == 0


def test_service_state_setting() -> None:
    """Test setting and updating service states."""
    hs = HealthStatus()

    # Register a service in UNINITIALIZED state
    hs.set_service_state("service1", HealthState.UNINITIALIZED)
    assert hs.get_state(service_name="service1") == HealthState.UNINITIALIZED
    assert hs.get_state() == HealthState.UNINITIALIZED

    # Update to AVAILABLE
    hs.set_service_state("service1", HealthState.AVAILABLE)
    assert hs.get_state(service_name="service1") == HealthState.AVAILABLE
    assert hs.get_state() == HealthState.AVAILABLE

    # Set another service to ERROR
    hs.set_service_state("service2", HealthState.ERROR, error_code=ErrorCode.INTERNAL_ERROR, description="Test error")
    assert hs.get_state(service_name="service2") == HealthState.ERROR
    error_info = hs.get_service_error("service2")
    assert error_info[0] == ErrorCode.INTERNAL_ERROR
    assert error_info[1] == "Test error"
    assert hs.get_state() == HealthState.ERROR


def test_multiple_services_states() -> None:
    """Test overall state calculation with multiple services."""
    hs = HealthStatus()

    # Add multiple services in different states
    hs.set_service_state("service1", HealthState.AVAILABLE)
    hs.set_service_state("service2", HealthState.AVAILABLE)
    assert hs.get_state() == HealthState.AVAILABLE

    # When one service has UNINITIALIZED state, overall should be UNINITIALIZED
    hs.set_service_state("service3", HealthState.UNINITIALIZED)
    assert hs.get_state() == HealthState.UNINITIALIZED

    # When one service has ERROR state, overall should be ERROR
    hs.set_service_state("service3", HealthState.AVAILABLE)
    hs.set_service_state(
        "service2", HealthState.ERROR, error_code=ErrorCode.GITHUB_API_ERROR, description="Another error"
    )
    assert hs.get_state() == HealthState.ERROR


def test_raise_on_error() -> None:
    """Test the raise_on_error method."""
    hs = HealthStatus()

    # No services in error state
    hs.set_service_state("service1", HealthState.AVAILABLE)
    hs.raise_on_error()  # Should not raise

    # Add service in error state
    hs.set_service_state(
        "service2", HealthState.ERROR, error_code=ErrorCode.HOME_ASSISTANT_ERROR, description="Critical error"
    )

    # Should raise AppError exception
    with pytest.raises(AppError) as exc_info:
        hs.raise_on_error()

    error = exc_info.value
    assert error.message.startswith("Service 'service2' in ERROR state")
    assert error.error_code == ErrorCode.HOME_ASSISTANT_ERROR
    assert "service_name" in error.details
    assert error.details["service_name"] == "service2"
    assert "description" in error.details
    assert error.details["description"] == "Critical error"


def test_state_change_subscription() -> None:
    """Test subscription to state changes."""
    hs = HealthStatus()

    # Create a mock for the subscription callback
    callback_called = False
    old_state = None
    new_state = None

    def callback(from_state: HealthState, to_state: HealthState) -> None:
        nonlocal callback_called, old_state, new_state
        callback_called = True
        old_state = from_state
        new_state = to_state

    # Subscribe to state changes
    hs.subscribe_to_state_changes(callback)

    # Initial state should be UNINITIALIZED
    assert hs.get_state() == HealthState.UNINITIALIZED

    # Change state to AVAILABLE
    hs.set_service_state("service1", HealthState.AVAILABLE)

    # Check if callback was called with correct parameters
    assert callback_called
    assert old_state == HealthState.UNINITIALIZED
    assert new_state == HealthState.AVAILABLE

    # Reset for next test
    callback_called = False

    # Change state to ERROR
    hs.set_service_state(
        "service1", HealthState.ERROR, error_code=ErrorCode.SYNC_ERROR, description="Error for callback"
    )

    # Check callback again
    assert callback_called
    assert old_state == HealthState.AVAILABLE
    assert new_state == HealthState.ERROR


def test_state_change_callback_not_called_on_same_state() -> None:
    """Test that callbacks aren't triggered when state doesn't change."""
    hs = HealthStatus()

    # Counter for callback invocations
    callback_count = 0

    def callback(from_state: HealthState, to_state: HealthState) -> None:
        nonlocal callback_count
        callback_count += 1

    # Subscribe to state changes
    hs.subscribe_to_state_changes(callback)

    # Set initial state
    hs.set_service_state("service1", HealthState.AVAILABLE)
    # Called once for the change from UNINITIALIZED to AVAILABLE
    assert callback_count == 1

    # Set the same state again
    hs.set_service_state("service1", HealthState.AVAILABLE)
    assert callback_count == 1  # Should not be called since state didn't change

    # Another service with the same state should also not trigger callback
    hs.set_service_state("service2", HealthState.AVAILABLE)
    assert callback_count == 1  # Overall state is still AVAILABLE

    # But a different state should trigger the callback
    hs.set_service_state(
        "service3", HealthState.ERROR, error_code=ErrorCode.VALIDATION_ERROR, description="Error state"
    )
    assert callback_count == 2  # Now called again as state changed to ERROR


def test_unsubscribe_from_state_changes() -> None:
    """Test unsubscribing from state changes."""
    hs = HealthStatus()

    # Counter for callback invocations
    callback_count = 0

    def callback(from_state: HealthState, to_state: HealthState) -> None:
        nonlocal callback_count
        callback_count += 1

    # Subscribe and verify it works
    sub_id = hs.subscribe_to_state_changes(callback)
    hs.set_service_state("service1", HealthState.AVAILABLE)
    assert callback_count == 1

    # Unsubscribe and verify callback is not called anymore
    hs.unsubscribe_from_state_changes(sub_id)
    hs.set_service_state(
        "service1", HealthState.ERROR, error_code=ErrorCode.AUTHENTICATION_FAILED, description="After unsubscribe"
    )
    assert callback_count == 1  # Still 1, not incremented


def test_service_removal() -> None:
    """Test removing services and its effect on overall state."""
    hs = HealthStatus()

    hs.set_service_state("service1", HealthState.AVAILABLE)
    hs.set_service_state("service2", HealthState.AVAILABLE)
    assert hs.get_state() == HealthState.AVAILABLE

    # Remove a service
    hs.remove_service("service1")
    assert "service1" not in hs.get_services()
    assert hs.get_state() == HealthState.AVAILABLE

    # Add a service in error state
    hs.set_service_state("service3", HealthState.ERROR, error_code=ErrorCode.NOT_FOUND, description="Error state")
    assert hs.get_state() == HealthState.ERROR

    # Remove the error service
    hs.remove_service("service3")
    assert hs.get_state() == HealthState.AVAILABLE


def test_clear_error() -> None:
    """Test clearing error states."""
    hs = HealthStatus()

    hs.set_service_state("service1", HealthState.ERROR, error_code=ErrorCode.INTERNAL_ERROR, description="Test error")
    assert hs.get_state(service_name="service1") == HealthState.ERROR

    # Clear error by setting to available
    hs.set_service_state("service1", HealthState.AVAILABLE)
    assert hs.get_state(service_name="service1") == HealthState.AVAILABLE

    # Error information should be gone
    with pytest.raises(KeyError):
        hs.get_service_error("service1")
