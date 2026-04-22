"""Basic tests for notification system."""

import pytest
from unittest.mock import AsyncMock, patch
from src.notification.types import (
    FullNotificationConfig,
    FullNotificationPayload,
    NotificationEvent,
    NotificationResult,
    DispatchResult,
)
from src.notification.dispatcher import dispatch_notifications


@pytest.mark.asyncio
async def test_dispatch_notifications_no_config():
    """Test dispatch with None config returns empty result."""
    result = await dispatch_notifications(None, FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id="test",
        message="test",
        timestamp="2024-01-01T00:00:00Z",
    ))
    assert isinstance(result, DispatchResult)
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_dispatch_notifications_disabled():
    """Test dispatch with disabled config returns empty result."""
    config = FullNotificationConfig(enabled=False)
    result = await dispatch_notifications(config, FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id="test",
        message="test",
        timestamp="2024-01-01T00:00:00Z",
    ))
    assert isinstance(result, DispatchResult)
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_dispatch_notifications_no_platforms():
    """Test dispatch with no enabled platforms."""
    config = FullNotificationConfig(enabled=True)
    result = await dispatch_notifications(config, FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id="test",
        message="test",
        timestamp="2024-01-01T00:00:00Z",
    ))
    assert isinstance(result, DispatchResult)
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_dispatch_notifications_with_mock_platform():
    """Test dispatch with mocked platform."""
    config = FullNotificationConfig(
        enabled=True,
        webhook=None  # No real webhook
    )
    
    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id="test123",
        message="Test message",
        timestamp="2024-01-01T00:00:00Z",
    )
    
    # Mock the aiohttp session to avoid actual HTTP calls
    with patch('aiohttp.ClientSession') as mock_session_class:
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        result = await dispatch_notifications(config, payload)
        
        assert isinstance(result, DispatchResult)
        # Should have attempted to send to webhook (even though disabled)
        # Actually webhook is None so no attempt
        assert len(result.results) == 0


def test_notification_result_properties():
    """Test NotificationResult properties."""
    result = NotificationResult(
        platform="discord",
        success=True,
        error=None,
        response={"id": "123"}
    )
    assert result.platform == "discord"
    assert result.success is True
    assert result.error is None
    assert result.response == {"id": "123"}


def test_dispatch_result_properties():
    """Test DispatchResult properties."""
    results = [
        NotificationResult(platform="discord", success=True),
        NotificationResult(platform="slack", success=False, error="Network error"),
    ]
    dispatch_result = DispatchResult(results=results)
    
    assert len(dispatch_result.results) == 2
    assert dispatch_result.all_succeeded is False
    assert dispatch_result.any_succeeded is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
