"""Tests for server authentication module."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.auth import AuthManager


class MockWebSocket:
    """Mock WebSocket connection for testing."""
    
    def __init__(self, remote_address=("127.0.0.1", 8080)):
        self.remote_address = remote_address


class TestAuthManager:
    """Test AuthManager class."""

    def test_init_with_token(self):
        """Initialize with explicit token."""
        manager = AuthManager(token="test-token-123")
        assert manager.token == "test-token-123"
        assert len(manager._authenticated) == 0
        assert len(manager._auth_times) == 0

    def test_init_without_token_uses_env(self):
        """Initialize without token reads from environment."""
        with patch.dict(os.environ, {"AGENT_SERVER_TOKEN": "env-token"}):
            manager = AuthManager()
            assert manager.token == "env-token"

    def test_init_empty_token_warns(self, caplog):
        """Initialize with empty token logs warning."""
        with patch.dict(os.environ, {}, clear=True):
            manager = AuthManager()
            assert manager.token == ""
            # Check that warning was logged
            assert any("AGENT_SERVER_TOKEN 未设置" in record.message 
                      for record in caplog.records)

    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        """Successful authentication with correct token."""
        manager = AuthManager(token="correct-token")
        ws = MockWebSocket()
        
        result = await manager.authenticate(ws, "correct-token")
        
        assert result is True
        assert ws in manager._authenticated
        assert ws in manager._auth_times

    @pytest.mark.asyncio
    async def test_authenticate_failure_wrong_token(self):
        """Authentication fails with wrong token."""
        manager = AuthManager(token="correct-token")
        ws = MockWebSocket()
        
        result = await manager.authenticate(ws, "wrong-token")
        
        assert result is False
        assert ws not in manager._authenticated

    @pytest.mark.asyncio
    async def test_authenticate_failure_no_server_token(self):
        """Authentication fails when server has no token configured."""
        manager = AuthManager(token="")
        ws = MockWebSocket()
        
        result = await manager.authenticate(ws, "any-token")
        
        assert result is False
        assert ws not in manager._authenticated

    @pytest.mark.asyncio
    async def test_is_authenticated_true(self):
        """Check authenticated connection returns True."""
        manager = AuthManager(token="token")
        ws = MockWebSocket()
        
        # Authenticate first
        await manager.authenticate(ws, "token")
        
        # Then check
        assert manager.is_authenticated(ws) is True

    @pytest.mark.asyncio
    async def test_is_authenticated_false(self):
        """Check unauthenticated connection returns False."""
        manager = AuthManager(token="token")
        ws = MockWebSocket()
        
        assert manager.is_authenticated(ws) is False

    @pytest.mark.asyncio
    async def test_unregister_connection_authenticated(self):
        """Unregister authenticated connection cleans up state."""
        manager = AuthManager(token="token")
        ws = MockWebSocket()
        
        # Authenticate
        await manager.authenticate(ws, "token")
        assert ws in manager._authenticated
        
        # Unregister
        manager.unregister(ws)
        
        assert ws not in manager._authenticated
        assert ws not in manager._auth_times

    @pytest.mark.asyncio
    async def test_unregister_connection_unauthenticated(self):
        """Unregister unauthenticated connection is safe."""
        manager = AuthManager(token="token")
        ws = MockWebSocket()
        
        # Should not raise
        manager.unregister(ws)
        
        assert ws not in manager._authenticated

    @pytest.mark.asyncio
    async def test_authenticated_count_property(self):
        """Get count of authenticated connections via property."""
        manager = AuthManager(token="token")
        
        ws1 = MockWebSocket(remote_address=("127.0.0.1", 8080))
        ws2 = MockWebSocket(remote_address=("127.0.0.1", 8081))
        ws3 = MockWebSocket(remote_address=("127.0.0.1", 8082))
        
        await manager.authenticate(ws1, "token")
        await manager.authenticate(ws2, "token")
        await manager.authenticate(ws3, "token")
        
        assert manager.authenticated_count == 3

    @pytest.mark.asyncio
    async def test_authenticated_count_after_unregister(self):
        """Count decreases after unregistering connection."""
        manager = AuthManager(token="token")
        
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.authenticate(ws1, "token")
        await manager.authenticate(ws2, "token")
        assert manager.authenticated_count == 2
        
        manager.unregister(ws1)
        assert manager.authenticated_count == 1

    @pytest.mark.asyncio
    async def test_auth_records_timestamp(self):
        """Authentication records timestamp."""
        manager = AuthManager(token="token")
        ws = MockWebSocket()
        
        before_auth = time.time()
        await manager.authenticate(ws, "token")
        after_auth = time.time()
        
        auth_time = manager._auth_times[ws]
        assert before_auth <= auth_time <= after_auth

    def test_multiple_managers_independent(self):
        """Multiple AuthManager instances are independent."""
        manager1 = AuthManager(token="token1")
        manager2 = AuthManager(token="token2")
        
        assert manager1.token != manager2.token
        assert manager1._authenticated is not manager2._authenticated


class TestAuthManagerIntegration:
    """Integration tests for AuthManager."""

    @pytest.mark.asyncio
    async def test_full_auth_lifecycle(self):
        """Test complete authentication lifecycle."""
        manager = AuthManager(token="secret")
        
        # Create connections
        ws_good = MockWebSocket()
        ws_bad = MockWebSocket()
        
        # Authenticate good connection
        assert await manager.authenticate(ws_good, "secret") is True
        assert manager.is_authenticated(ws_good) is True
        
        # Reject bad connection
        assert await manager.authenticate(ws_bad, "wrong") is False
        assert manager.is_authenticated(ws_bad) is False
        
        # Check counts
        assert manager.authenticated_count == 1
        
        # Remove good connection
        manager.unregister(ws_good)
        assert manager.is_authenticated(ws_good) is False
        assert manager.authenticated_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_authentications(self):
        """Test multiple concurrent authentication attempts."""
        manager = AuthManager(token="token")
        
        connections = [MockWebSocket() for _ in range(5)]
        
        # Authenticate all concurrently
        tasks = [
            manager.authenticate(ws, "token")
            for ws in connections
        ]
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(results)
        assert manager.authenticated_count == 5
