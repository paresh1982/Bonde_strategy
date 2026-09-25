import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from bonde.live.runner import LivePaperRunner
from bonde.live.models import LiveBar, DataQualityStatus
from bonde.config.strategy_config import StrategyConfig
from bonde.data.models import NY_TZ

class MockStreamingAdapter:
    def __init__(self):
        self.bars = []
        self.quotes = []
        self.data_source = "IEX"
        
    def drain_bars(self):
        res = self.bars
        self.bars = []
        return res
        
    def drain_quotes(self):
        res = self.quotes
        self.quotes = []
        return res

@pytest.fixture
def config():
    return StrategyConfig()

@pytest.fixture
def runner(config):
    adapter = MockStreamingAdapter()
    return LivePaperRunner(config, adapter, adapter)

def test_runner_processes_valid_bars(runner):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(timestamp=dt, symbol="AAPL", security_id="SEC_AAPL", 
                  open=150.0, high=151.0, low=149.0, close=150.0, volume=100)
    runner.market_data_provider.bars = [bar]
    runner.step()
    assert runner.session_summary["bars_processed"] == 1

def test_runner_rejects_invalid_bars(runner):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(timestamp=dt, symbol="AAPL", security_id="SEC_AAPL", 
                  open=-150.0, high=151.0, low=-150.0, close=150.0, volume=100)
    runner.market_data_provider.bars = [bar]
    runner.step()
    assert runner.session_summary["bars_rejected"] == 1

def test_runner_staleness_warning(runner, caplog):
    import logging
    caplog.set_level(logging.WARNING)
    runner.last_data_time = datetime.now(NY_TZ) - timedelta(seconds=65)
    runner.check_staleness()
    assert "stale data warning" in caplog.text.lower() or "stale" in caplog.text.lower()

def test_runner_staleness_halt(runner):
    runner.last_data_time = datetime.now(NY_TZ) - timedelta(seconds=95)
    runner.check_staleness()
    assert runner.is_halted

def test_runner_session_summary_has_data_source(runner):
    runner.stop()
    assert runner.session_summary.get("data_source") == "IEX"

def test_runner_session_summary_counts(runner):
    dt1 = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    dt2 = datetime(2023, 6, 15, 10, 31, tzinfo=NY_TZ)
    bar1 = LiveBar(timestamp=dt1, symbol="AAPL", security_id="SEC_AAPL", 
                   open=150.0, high=151.0, low=149.0, close=150.0, volume=100)
    bar2 = LiveBar(timestamp=dt2, symbol="AAPL", security_id="SEC_AAPL", 
                   open=150.0, high=151.0, low=149.0, close=150.0, volume=100)
    runner.market_data_provider.bars = [bar1, bar2]
    runner.step()
    assert runner.session_summary["bars_processed"] == 2

def test_runner_halt_sets_reason(runner):
    runner.halt("Test reason")
    assert runner.is_halted
    assert runner.halt_reason == "Test reason"

def test_runner_checkpoint_interval(runner):
    runner.last_checkpoint_time = datetime.now(NY_TZ) - timedelta(minutes=6)
    runner.check_and_checkpoint()
    assert runner.last_checkpoint_time > datetime.now(NY_TZ) - timedelta(minutes=1)
