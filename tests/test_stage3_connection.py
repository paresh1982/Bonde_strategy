import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from bonde.live.adapters.alpaca.connection import AlpacaConnectionManager
from bonde.live.adapters.alpaca.config import AlpacaConfig

@pytest.fixture
def manager():
    config = AlpacaConfig(api_key="TEST", secret_key="TEST", symbols=["AAPL"])
    return AlpacaConnectionManager(config)

def test_connection_initial_state(manager):
    assert not manager.is_connected
    assert manager.last_data_time is None
    assert not manager.is_stale

def test_connection_symbol_limit_validation():
    symbols = [f"SYM{i}" for i in range(35)]
    with pytest.raises(ValueError, match="exceeds maximum limit"):
        AlpacaConfig(api_key="TEST", secret_key="TEST", symbols=symbols)

def test_connection_reconnect_backoff_delay(manager):
    assert manager._get_backoff_delay(0) == 1.0
    assert manager._get_backoff_delay(1) == 2.0
    assert manager._get_backoff_delay(2) == 4.0
    assert manager._get_backoff_delay(10) <= 60.0

@patch('bonde.live.adapters.alpaca.connection.AlpacaConnectionManager.connect')
def test_connection_max_reconnect_attempts(mock_connect, manager):
    mock_connect.side_effect = Exception("Failed")
    manager.max_reconnect_attempts = 3
    with patch('time.sleep'):
        assert manager.reconnect() is False
        assert manager.reconnect() is False
        assert manager.reconnect() is False
        assert manager.reconnect() is False
        assert mock_connect.call_count == 3

def test_connection_staleness_detection(manager):
    manager.last_data_time = datetime.now() - timedelta(seconds=100)
    manager.staleness_timeout_seconds = 60
    assert manager.is_stale

def test_connection_update_last_data_time(manager):
    manager.update_last_data_time()
    assert manager.last_data_time is not None
    assert not manager.is_stale

def test_connection_graceful_shutdown(manager):
    manager.is_connected = True
    manager.disconnect()
    assert not manager.is_connected

def test_connection_reconnect_resets_counter(manager):
    manager.reconnect_attempts = 5
    manager._handle_successful_connect()
    assert manager.reconnect_attempts == 0
    assert manager.is_connected
