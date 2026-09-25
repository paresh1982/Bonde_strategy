import pytest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from bonde.live.runner import LivePaperRunner
from bonde.config.strategy_config import StrategyConfig
from bonde.data.models import NY_TZ
from bonde.execution.orders import OrderStatus, OrderType
from bonde.live.models import LiveBar, DataQualityStatus

class MockRecoveryAdapter:
    def __init__(self):
        self.connected = True
        self.bars = []
        self.quotes = []
        self.reconnect_count = 0
        self.backfilled = False
        
    def drain_bars(self):
        res = self.bars
        self.bars = []
        return res
        
    def drain_quotes(self):
        return []
        
    def reconnect(self):
        self.reconnect_count += 1
        if self.reconnect_count < 3:
            self.connected = True
            return True
        return False
        
    def backfill(self):
        self.backfilled = True

@pytest.fixture
def runner():
    config = StrategyConfig()
    adapter = MockRecoveryAdapter()
    return LivePaperRunner(config, adapter, adapter)

def test_disconnect_detected(runner):
    runner.market_data_provider.connected = False
    runner.step()
    assert runner.session_summary["disconnect_count"] >= 1

def test_reconnect_success_resumes_processing(runner):
    runner.market_data_provider.connected = False
    runner.market_data_provider.reconnect = MagicMock(return_value=True)
    runner.handle_disconnect()
    assert runner.market_data_provider.reconnect.called

def test_reconnect_failure_halts_session(runner):
    runner.market_data_provider.connected = False
    runner.market_data_provider.reconnect = MagicMock(return_value=False)
    runner.handle_disconnect()
    assert runner.is_halted

def test_backfill_missed_bars_after_reconnect(runner):
    runner.market_data_provider.connected = False
    runner.market_data_provider.reconnect = MagicMock(return_value=True)
    runner.handle_disconnect()
    assert runner.market_data_provider.backfilled

def test_no_duplicate_bars_after_backfill(runner):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    runner.market_data_provider.bars = [bar]
    runner.step()
    assert runner.bars_processed == 1
    
    # Send identical bar again
    runner.market_data_provider.bars = [bar]
    runner.step()
    assert runner.bars_processed == 1
    assert runner.bars_rejected >= 1

def test_pending_entries_cancelled_on_disconnect(runner):
    mock_broker = MagicMock()
    mock_order = MagicMock()
    mock_order.order_type = OrderType.BUY_STOP
    mock_order.status = OrderStatus.PENDING
    mock_order.order_id = "ORD_123"
    mock_broker.active_orders = {"ORD_123": mock_order}
    
    mock_engine = MagicMock()
    mock_engine.broker = mock_broker
    runner._engine = mock_engine
    
    runner.handle_disconnect()
    mock_broker.cancel_order.assert_called_with("ORD_123", reason="DISCONNECT_ENTRY_CANCEL")

def test_checkpoint_on_disconnect(runner):
    mock_engine = MagicMock()
    runner._engine = mock_engine
    runner.handle_disconnect()
    mock_engine.checkpoint.assert_called()

def test_recovery_deterministic(runner):
    runner.market_data_provider.connected = False
    runner.market_data_provider.reconnect = MagicMock(return_value=True)
    runner.handle_disconnect()
    assert runner.market_data_provider.reconnect.call_count == 1
